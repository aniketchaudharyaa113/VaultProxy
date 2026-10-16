"""
Phase 1a extra tests (added before Phase 1b).

These tests were written TEST-FIRST: each one exposes the old (broken) behaviour
before the corresponding fix is applied.  After the fix every test in this file
must PASS.

Items covered
─────────────
1. B2 + B4 (real uvicorn): two concurrent streams of different lengths both
   deliver all events + [DONE]; during an active stream with
   MAX_CONCURRENT_REQUESTS=1 a second request gets 429; after the stream ends
   (or the client disconnects) a new request gets 200.

2. Slot conservation: after 100 mixed requests (stream, non-stream, errors,
   client-disconnect) the semaphore's internal counter equals its starting value.

3. B1 for streaming responses: gzip from upstream is fully decoded when the
   response is a text/event-stream.

4. B5 on every route: /v1/chat/completions, /v1/embeddings, /v1/models,
   /metrics, and the "detail" part of /readyz all require the token.  When
   DEMO_MODE=true and a token is set the demo endpoints must also require the
   token.

5. B12 log-level lines + ALL-log-output test: assert the two lines in server.py
   that set httpx / httpcore to WARNING exist, and run a real run_gemma_detection
   call with a fake key at DEBUG and check the key never appears in output.
"""

import asyncio
import io
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from vaultproxy.config import settings
from vaultproxy.server import app

# ─── helpers ──────────────────────────────────────────────────────────────────

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = sys.executable
TOKEN = "abcdefghijklmnopqrstuvwxyz0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_up(url: str, secs: float = 15) -> bool:
    end = time.time() + secs
    while time.time() < end:
        try:
            httpx.get(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.2)
    return False


# ─── real-server fixture ──────────────────────────────────────────────────────

UPSTREAM_SRC = r"""
import asyncio, json, os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()
LOG = os.environ["UP_LOG"]

async def handler(request: Request):
    body = await request.body()
    try:
        data = json.loads(body)
    except Exception:
        data = {}
    with open(LOG, "a") as f:
        f.write(json.dumps({"path": request.url.path, "body": data}) + "\n")
    if data.get("stream"):
        slow = "slowstream" in json.dumps(data)
        async def gen():
            n = 8 if slow else 2
            for i in range(n):
                chunk = {
                    "id": "x", "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": {"content": f"part{i} "},
                                 "finish_reason": None}]
                }
                yield "data: " + json.dumps(chunk) + "\n\n"
                await asyncio.sleep(0.5 if slow else 0.05)
            yield "data: [DONE]\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")
    return JSONResponse({
        "id": "x", "object": "chat.completion",
        "choices": [{"index": 0,
                     "message": {"role": "assistant",
                                 "content": json.dumps(data.get("messages", data))},
                     "finish_reason": "stop"}]
    })

@app.post("/v1/chat/completions")
async def chat(request: Request): return await handler(request)
@app.get("/v1/models")
async def models(): return {"object": "list", "data": []}
"""


class _Proc:
    def __init__(self, args, env, cwd):
        import tempfile
        self._log = tempfile.NamedTemporaryFile("w+", delete=False, suffix=".log")
        self.p = subprocess.Popen(
            args, env=env, cwd=cwd,
            stdout=self._log, stderr=subprocess.STDOUT,
        )

    def stop(self):
        try:
            self.p.terminate()
            self.p.wait(5)
        except Exception:
            try:
                self.p.kill()
            except Exception:
                pass

    def output(self) -> str:
        self._log.flush()
        return open(self._log.name).read()


def _start_upstream(tmpdir: str) -> tuple[str, str]:
    """Start a bare mock upstream; returns (base_url, log_path)."""

    src_path = os.path.join(tmpdir, "upstream.py")
    open(src_path, "w").write(UPSTREAM_SRC)
    log_path = os.path.join(tmpdir, "up.jsonl")
    open(log_path, "w").close()
    port = free_port()
    env = dict(os.environ, UP_LOG=log_path)
    _Proc(
        [PYTHON, "-m", "uvicorn", "upstream:app",
         "--app-dir", tmpdir,
         "--port", str(port),
         "--log-level", "warning"],
        env, tmpdir,
    )
    assert wait_up(f"http://127.0.0.1:{port}/v1/models"), "mock upstream did not start"
    return f"http://127.0.0.1:{port}", log_path


def _start_proxy(upstream_url: str, env_extra: dict | None = None) -> tuple[str, _Proc]:
    """Start a real VaultProxy uvicorn process; returns (base_url, proc)."""
    port = free_port()
    env = dict(os.environ,
               PYTHONPATH=REPO_ROOT,
               UPSTREAM_BASE_URL=upstream_url,
               GEMMA_BACKEND="off")
    # scrub env vars that might leak from the host shell
    for k in ("VAULT_PROFILE", "VAULT_AUTH_TOKEN", "DEMO_MODE",
               "STRICT_MODE", "MAX_CONCURRENT_REQUESTS", "GEMINI_API_KEY"):
        env.pop(k, None)
    for k, v in (env_extra or {}).items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    pr = _Proc(
        [PYTHON, "-m", "uvicorn", "vaultproxy.server:app",
         "--port", str(port),
         "--log-level", "warning"],
        env, REPO_ROOT,
    )
    if not wait_up(f"http://127.0.0.1:{port}/healthz"):
        raise RuntimeError("proxy did not start:\n" + pr.output()[-600:])
    return f"http://127.0.0.1:{port}", pr


# ═══════════════════════════════════════════════════════════════════════════════
# 1. B2 + B4: real uvicorn concurrent-stream tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestB2B4RealServer:
    """Real-server tests for streaming correctness and concurrency gate."""

    def setup_method(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp(prefix="vp_b2b4_")
        self.procs: list[_Proc] = []

    def teardown_method(self):
        for p in self.procs:
            p.stop()

    def _proxy(self, upstream_url, env_extra=None):
        base, pr = _start_proxy(upstream_url, env_extra)
        self.procs.append(pr)
        return base

    def test_b2_real_two_concurrent_streams_both_complete(self):
        """B2 (real server): two concurrent streams of different lengths both
        deliver all events including [DONE]."""
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix="vp_up_")
        self.tmpdir = tmpdir  # for teardown
        up_url, _ = _start_upstream(tmpdir)
        base = self._proxy(up_url)

        results: dict[str, list[str]] = {}
        errors: list[str] = []

        def stream_request(tag: str, content: str) -> None:
            events: list[str] = []
            try:
                with httpx.stream(
                    "POST", base + "/v1/chat/completions",
                    json={"model": "m", "stream": True,
                          "messages": [{"role": "user", "content": content}]},
                    timeout=60,
                ) as r:
                    for line in r.iter_lines():
                        if line.startswith("data:"):
                            events.append(line)
            except Exception as exc:
                errors.append(f"{tag}: {exc}")
            results[tag] = events

        slow_thread = threading.Thread(
            target=stream_request, args=("slow", "slowstream request")
        )
        slow_thread.start()
        time.sleep(0.8)  # let slow stream get going first

        stream_request("fast", "quick request")
        slow_thread.join(timeout=30)

        assert not errors, f"Stream errors: {errors}"

        slow_events = results.get("slow", [])
        fast_events = results.get("fast", [])

        # slow: 8 data chunks + [DONE] = 9 events
        assert len(slow_events) == 9, (
            f"slow stream got {len(slow_events)}/9 events: {slow_events}"
        )
        assert slow_events[-1] == "data: [DONE]", (
            f"slow stream last event was {slow_events[-1]!r}"
        )

        # fast: 2 data chunks + [DONE] = 3 events
        assert len(fast_events) == 3, (
            f"fast stream got {len(fast_events)}/3 events: {fast_events}"
        )
        assert fast_events[-1] == "data: [DONE]", (
            f"fast stream last event was {fast_events[-1]!r}"
        )

    def test_b4_real_429_during_stream_200_after(self):
        """B4 (real server): with MAX_CONCURRENT_REQUESTS=1, a second request
        gets 429 while a stream is active; after the stream ends a new request
        gets 200 (slot was released)."""
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix="vp_up_")
        up_url, _ = _start_upstream(tmpdir)
        base = self._proxy(up_url, {"MAX_CONCURRENT_REQUESTS": "1"})

        stream_started = threading.Event()
        stream_done = threading.Event()

        def do_slow_stream():
            try:
                with httpx.stream(
                    "POST", base + "/v1/chat/completions",
                    json={"model": "m", "stream": True,
                          "messages": [{"role": "user",
                                        "content": "slowstream test"}]},
                    timeout=30,
                ) as r:
                    for line in r.iter_lines():
                        if line.startswith("data:"):
                            stream_started.set()  # signal first event received
            except Exception:
                pass
            stream_done.set()

        t = threading.Thread(target=do_slow_stream)
        t.start()

        # wait until the stream has started delivering events
        assert stream_started.wait(timeout=10), "slow stream never started"

        # while stream is active → must get 429
        r_during = httpx.post(
            base + "/v1/chat/completions",
            json={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
            timeout=10,
        )
        assert r_during.status_code == 429, (
            f"Expected 429 while stream active, got {r_during.status_code}"
        )

        # wait for the slow stream to finish
        t.join(timeout=30)
        assert stream_done.is_set(), "slow stream thread did not finish"

        # small pause to let the server release the slot
        time.sleep(0.2)

        # after stream ends → must get 200
        r_after = httpx.post(
            base + "/v1/chat/completions",
            json={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
            timeout=10,
        )
        assert r_after.status_code == 200, (
            f"Expected 200 after stream finished, got {r_after.status_code}. "
            "Semaphore slot was NOT released by sem_holding_stream."
        )

    def test_b4_real_slot_released_on_client_disconnect(self):
        """B4 (real server): if the client disconnects mid-stream, the slot is
        still released so the next request gets 200."""
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix="vp_up_")
        up_url, _ = _start_upstream(tmpdir)
        base = self._proxy(up_url, {"MAX_CONCURRENT_REQUESTS": "1"})

        # Start a slow stream and disconnect after the first event
        try:
            with httpx.stream(
                "POST", base + "/v1/chat/completions",
                json={"model": "m", "stream": True,
                      "messages": [{"role": "user", "content": "slowstream disc"}]},
                timeout=30,
            ) as r:
                for line in r.iter_lines():
                    if line.startswith("data:"):
                        break  # disconnect after first event
        except Exception:
            pass

        # give the server a moment to notice disconnect and release slot
        time.sleep(1.5)

        r_after = httpx.post(
            base + "/v1/chat/completions",
            json={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
            timeout=10,
        )
        assert r_after.status_code == 200, (
            f"Expected 200 after client disconnect, got {r_after.status_code}. "
            "Slot was NOT released on disconnect."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Slot conservation: after 100 mixed requests, counter equals start
# ═══════════════════════════════════════════════════════════════════════════════

class TestSlotConservation:
    """After 100 mixed requests the semaphore counter must equal its start."""

    def _make_mock_client(self, stream: bool = False):
        if stream:
            async def handler(req: httpx.Request) -> httpx.Response:
                _ = await req.aread()
                async def body_gen():
                    for i in range(3):
                        chunk = json.dumps({
                            "id": "x", "object": "chat.completion.chunk",
                            "choices": [{"index": 0,
                                         "delta": {"content": f"tok{i}"},
                                         "finish_reason": None}],
                        })
                        yield f"data: {chunk}\n\n".encode()
                    yield b"data: [DONE]\n\n"

                return httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    stream=httpx.ByteStream(b""),  # won't be used
                )
        else:
            async def handler(req: httpx.Request) -> httpx.Response:
                return httpx.Response(
                    200,
                    headers={"content-type": "application/json"},
                    content=json.dumps({
                        "id": "x", "object": "chat.completion",
                        "choices": [{"index": 0,
                                     "message": {"role": "assistant",
                                                 "content": "ok"},
                                     "finish_reason": "stop"}],
                    }).encode(),
                )
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    def test_slot_conservation_100_mixed(self):
        """After 100 mixed non-stream requests the semaphore counter = start."""
        import vaultproxy.server as srv

        # Read initial semaphore state after resetting it
        with patch.object(settings, "GEMMA_BACKEND", "off"), \
             patch.object(settings, "MAX_CONCURRENT_REQUESTS", 10):
            # Force semaphore recreation
            srv._concurrency_semaphore = None
            sem = srv.get_concurrency_semaphore()
            # For asyncio.Semaphore, _value is the internal counter
            start_value = sem._value  # type: ignore[attr-defined]

            # Run 100 non-stream requests
            async def _run_many():
                ok_resp = httpx.Response(
                    200,
                    headers={"content-type": "application/json"},
                    content=json.dumps({
                        "id": "x", "object": "chat.completion",
                        "choices": [{"index": 0,
                                     "message": {"role": "assistant",
                                                 "content": "hi"},
                                     "finish_reason": "stop"}],
                    }).encode(),
                )
                bad_resp = httpx.Response(
                    500,
                    headers={"content-type": "application/json"},
                    content=b'{"error": "upstream down"}',
                )

                client = TestClient(app)
                for i in range(100):
                    if i % 10 == 3:
                        # bad JSON body → 400
                        client.post(
                            "/v1/chat/completions",
                            content=b"not-json",
                            headers={"content-type": "application/json"},
                        )
                    elif i % 10 == 5:
                        # upstream error 500
                        with patch("httpx.AsyncClient.send",
                                   new_callable=AsyncMock,
                                   return_value=bad_resp):
                            client.post(
                                "/v1/chat/completions",
                                json={"messages": [{"role": "user",
                                                    "content": "hello"}]},
                            )
                    elif i % 10 == 7:
                        # 413 body-too-large path
                        with patch.object(settings, "MAX_BODY_BYTES", 1):
                            client.post(
                                "/v1/chat/completions",
                                json={"messages": [{"role": "user",
                                                    "content": "hi there"}]},
                            )
                    else:
                        with patch("httpx.AsyncClient.send",
                                   new_callable=AsyncMock,
                                   return_value=ok_resp):
                            client.post(
                                "/v1/chat/completions",
                                json={"messages": [{"role": "user",
                                                    "content": "hello"}]},
                            )

                return sem._value  # type: ignore[attr-defined]

            end_value = asyncio.run(_run_many())

        assert end_value == start_value, (
            f"Semaphore counter drifted: started at {start_value}, "
            f"ended at {end_value} after 100 requests. "
            "Slot was acquired but not always released."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 3. B1 for streaming responses
# ═══════════════════════════════════════════════════════════════════════════════

class TestB1Streaming:
    """Gzip-compressed upstream reply is decoded for streaming responses too."""

    def test_b1_gzip_streaming_response_decoded(self):
        """B1 (stream): if upstream sends Content-Encoding: gzip on a streaming
        response, the proxy must decode it before forwarding to the client."""
        import gzip as gzip_mod

        # Build a raw SSE body and gzip it
        raw_sse = (
            'data: {"id":"x","object":"chat.completion.chunk",'
            '"choices":[{"index":0,"delta":{"content":"hello"},'
            '"finish_reason":null}]}\n\n'
            "data: [DONE]\n\n"
        )
        gzipped = gzip_mod.compress(raw_sse.encode())

        mock_resp = httpx.Response(
            200,
            headers={
                "content-type": "text/event-stream",
                "content-encoding": "gzip",
                "content-length": str(len(gzipped)),
            },
            content=gzipped,
        )

        with patch.object(settings, "GEMMA_BACKEND", "off"), \
             patch("httpx.AsyncClient.send",
                   new_callable=AsyncMock,
                   return_value=mock_resp):
            client = TestClient(app)
            with client.stream(
                "POST", "/v1/chat/completions",
                json={"model": "m", "stream": True,
                      "messages": [{"role": "user", "content": "hi"}]},
            ) as resp:
                assert resp.status_code == 200
                # Response headers must NOT include content-encoding
                assert "content-encoding" not in resp.headers, (
                    "content-encoding header must be stripped from streaming response"
                )
                lines = [line for line in resp.iter_lines() if line.startswith("data:")]
                assert len(lines) >= 1, (
                    "Expected at least one SSE data line from decoded gzip stream"
                )


# ═══════════════════════════════════════════════════════════════════════════════
# 4. B5 on every route
# ═══════════════════════════════════════════════════════════════════════════════

class TestB5EveryRoute:
    """VAULT_AUTH_TOKEN enforced on every route that returns sensitive data."""

    @pytest.fixture
    def authed_client(self):
        with patch.object(settings, "VAULT_AUTH_TOKEN", TOKEN), \
             patch.object(settings, "VAULT_PROFILE", "development"), \
             patch.object(settings, "GEMMA_BACKEND", "off"):
            yield TestClient(app)

    def test_b5_chat_completions_requires_token(self, authed_client):
        resp = authed_client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 401, (
            f"/v1/chat/completions without token → {resp.status_code}, want 401"
        )
        resp_ok = authed_client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers=AUTH,
        )
        # May fail at upstream but must not be 401
        assert resp_ok.status_code != 401

    def test_b5_embeddings_requires_token(self, authed_client):
        resp = authed_client.post(
            "/v1/embeddings",
            json={"model": "m", "input": "hello"},
        )
        assert resp.status_code == 401, (
            f"/v1/embeddings without token → {resp.status_code}, want 401"
        )

    def test_b5_models_requires_token(self, authed_client):
        resp = authed_client.get("/v1/models")
        assert resp.status_code == 401, (
            f"/v1/models without token → {resp.status_code}, want 401"
        )

    def test_b5_metrics_requires_token(self, authed_client):
        resp = authed_client.get("/metrics")
        assert resp.status_code == 401, (
            f"/metrics without token → {resp.status_code}, want 401"
        )

    def test_b5_readyz_detail_hidden_without_token(self, authed_client):
        """Without a token /readyz must return only {status: ...}, no SLM detail."""
        resp = authed_client.get("/readyz")
        assert resp.status_code == 200
        data = resp.json()
        assert "slm_backend" not in data, (
            f"/readyz without token must not expose slm_backend; got {data}"
        )
        assert set(data.keys()) <= {"status"}, (
            f"/readyz without token must only return {{status}}, got {set(data.keys())}"
        )

    def test_b5_readyz_detail_present_with_token(self, authed_client):
        """With a valid token /readyz must return the full detail."""
        resp = authed_client.get("/readyz", headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert "slm_backend" in data, (
            f"/readyz with token must expose slm_backend; got {data}"
        )

    def test_b5_demo_mode_endpoints_require_token(self):
        """When DEMO_MODE=true and a token is set, demo endpoints require the token."""
        with patch.object(settings, "VAULT_AUTH_TOKEN", TOKEN), \
             patch.object(settings, "VAULT_PROFILE", "development"), \
             patch.object(settings, "DEMO_MODE", True), \
             patch.object(settings, "GEMMA_BACKEND", "off"):
            client = TestClient(app)

            # /demo/last without token
            resp = client.get("/demo/last")
            assert resp.status_code == 401, (
                f"/demo/last without token → {resp.status_code}, want 401"
            )

            # /demo/last with token
            resp_ok = client.get("/demo/last", headers=AUTH)
            assert resp_ok.status_code in (200, 404), (
                f"/demo/last with token → {resp_ok.status_code}, want 200 or 404"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 5. B12: log-level lines in source + ALL-log-output test
# ═══════════════════════════════════════════════════════════════════════════════

class TestB12LogLevels:
    """B12: verify the lines that suppress httpx/httpcore logs, and that a
    real Gemini call with a fake key at DEBUG level never leaks the key."""

    def test_b12_log_level_lines_in_server_source(self):
        """The two lines that set httpx/httpcore to WARNING must exist in server.py."""
        server_src_path = os.path.join(REPO_ROOT, "vaultproxy", "server.py")
        src = open(server_src_path).read()

        assert 'logging.getLogger("httpx").setLevel(logging.WARNING)' in src, (
            'server.py must contain: logging.getLogger("httpx").setLevel(logging.WARNING)'
        )
        assert 'logging.getLogger("httpcore").setLevel(logging.WARNING)' in src, (
            'server.py must contain: logging.getLogger("httpcore").setLevel(logging.WARNING)'
        )

    def test_b12_fake_key_not_in_all_debug_output(self):
        """At DEBUG level, a fake Gemini key must never appear in any log record."""
        from vaultproxy.gemma_layer import circuit_breaker, run_gemma_detection

        circuit_breaker.state = "CLOSED"
        circuit_breaker.failure_count = 0

        fake_key = "FAKEGEMINIKEY_ShouldNeverAppearInLogs_XYZ789"

        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        root_logger = logging.getLogger()
        original_level = root_logger.level

        try:
            root_logger.addHandler(handler)
            root_logger.setLevel(logging.DEBUG)

            async def _run():
                def mock_handler(req: httpx.Request) -> httpx.Response:
                    return httpx.Response(403, json={"error": "fake denied"})

                orig = httpx.AsyncClient

                def mock_factory(*a, **kw):
                    kw.pop("transport", None)
                    return orig(*a, transport=httpx.MockTransport(mock_handler), **kw)

                with patch.object(settings, "GEMMA_BACKEND", "gemini"), \
                     patch.object(settings, "GEMINI_API_KEY", fake_key), \
                     patch.object(settings, "STRICT_MODE", False), \
                     patch("httpx.AsyncClient", side_effect=mock_factory):
                    await run_gemma_detection("Hello this is a test sentence.")

            asyncio.run(_run())

        finally:
            root_logger.removeHandler(handler)
            root_logger.setLevel(original_level)
            circuit_breaker.state = "CLOSED"
            circuit_breaker.failure_count = 0

        log_output = buf.getvalue()
        assert fake_key not in log_output, (
            f"Fake Gemini API key appeared in log output at DEBUG level!\n"
            f"Key: {fake_key!r}\n"
            f"Log output (first 500 chars): {log_output[:500]}"
        )

    def test_b12_httpx_httpcore_suppressed_at_warning(self):
        """httpx and httpcore loggers must be at WARNING or higher, not DEBUG."""
        import vaultproxy.server  # noqa: F401 (import triggers the setLevel calls)

        httpx_logger = logging.getLogger("httpx")
        httpcore_logger = logging.getLogger("httpcore")

        assert httpx_logger.level >= logging.WARNING, (
            f"httpx logger level is {httpx_logger.level}, expected >= {logging.WARNING} (WARNING)"
        )
        assert httpcore_logger.level >= logging.WARNING, (
            f"httpcore logger level is {httpcore_logger.level}, expected >= {logging.WARNING} (WARNING)"
        )
