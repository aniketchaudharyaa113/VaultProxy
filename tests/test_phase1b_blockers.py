"""
Phase 1b tests (B6-B10) — written test-first.

Each test is written to fail against the old code and pass after the fix.
This file tests:
  B6  – 'file' key in tool schema or metadata not blocked in production
  B7  – bad JSON returns 400 with OpenAI-style error body + x-request-id header
  B8  – no placeholder instruction when clean; instruction in system message only
  B9  – integer and dict-key PII is masked before reaching upstream
  B10 – merge_spans correctness (no drops, no overlaps)
"""

import asyncio
import json
import random
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from vaultproxy.config import settings
from vaultproxy.detectors import Span
from vaultproxy.masking import has_non_text_parts
from vaultproxy.merge import merge_spans
from vaultproxy.server import app
from vaultproxy.vault import RequestVault

# ─── shared helpers ───────────────────────────────────────────────────────────

PROD_TOKEN = "a_very_long_secure_vault_production_token_123456"
PAN = "ABCPB1234F"
AAD = "367598341203"

_OK_RESP = httpx.Response(
    200,
    headers={"content-type": "application/json"},
    content=json.dumps({
        "id": "x", "object": "chat.completion",
        "choices": [{"index": 0,
                     "message": {"role": "assistant", "content": "ok"},
                     "finish_reason": "stop"}],
    }).encode(),
)


def _prod_client():
    return TestClient(app)


# ═══════════════════════════════════════════════════════════════════════════════
# B6 – 'file' key in tool schema / metadata must NOT be blocked in production
# ═══════════════════════════════════════════════════════════════════════════════

class TestB6FileKeyNotBinary:
    """has_non_text_parts must not flag 'file' as non-text unless it is an actual
    content part with type=='file'.  Tool schemas, metadata dicts, and function
    parameters may legitimately have a key named 'file'."""

    # ---------- unit tests for has_non_text_parts ----------

    def test_b6_tool_schema_with_file_property_not_non_text(self):
        """A tool schema that has a property named 'file' must not be flagged."""
        payload = {
            "messages": [{"role": "user", "content": "hello"}],
            "tools": [{
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file": {"type": "string", "description": "path"},
                        },
                    },
                },
            }],
        }
        assert not has_non_text_parts(payload), (
            "Tool schema with a 'file' property key must NOT be flagged as non-text"
        )

    def test_b6_metadata_with_file_key_not_non_text(self):
        """A metadata dict with key 'file' must not be flagged."""
        payload = {
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"file": "report.txt"},
        }
        assert not has_non_text_parts(payload), (
            "Metadata dict with key 'file' must NOT be flagged as non-text"
        )

    def test_b6_actual_image_url_part_is_non_text(self):
        """An actual image_url content part must still be detected."""
        payload = {
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                ],
            }],
        }
        assert has_non_text_parts(payload), (
            "An actual image_url content part must be flagged as non-text"
        )

    def test_b6_actual_file_content_part_is_non_text(self):
        """An actual 'file' content part (type == 'file') must still be detected."""
        payload = {
            "messages": [{
                "role": "user",
                "content": [{"type": "file", "file": {"url": "..."}}],
            }],
        }
        assert has_non_text_parts(payload), (
            "A content part with type=='file' must be flagged as non-text"
        )

    # ---------- integration tests via real proxy ----------

    def test_b6_tool_schema_returns_200_in_production(self):
        """POST /v1/chat/completions with a tool schema containing 'file' property
        must return 200 (not 400) in production profile."""
        payload = {
            "model": "m",
            "messages": [{"role": "user", "content": "hello"}],
            "tools": [{
                "type": "function",
                "function": {
                    "name": "r",
                    "description": "x",
                    "parameters": {
                        "type": "object",
                        "properties": {"file": {"type": "string"}},
                    },
                },
            }],
        }
        with patch.object(settings, "VAULT_PROFILE", "production"), \
             patch.object(settings, "VAULT_AUTH_TOKEN", PROD_TOKEN), \
             patch.object(settings, "GEMMA_BACKEND", "off"), \
             patch("httpx.AsyncClient.send",
                   new_callable=AsyncMock,
                   return_value=_OK_RESP):
            client = _prod_client()
            resp = client.post(
                "/v1/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {PROD_TOKEN}"},
            )
            assert resp.status_code == 200, (
                f"Tool schema with 'file' property → {resp.status_code}, want 200. "
                f"Body: {resp.text[:200]}"
            )

    def test_b6_metadata_file_returns_200_in_production(self):
        """POST /v1/chat/completions with metadata={'file': ...} must return 200."""
        payload = {
            "model": "m",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"file": "report.txt"},
        }
        with patch.object(settings, "VAULT_PROFILE", "production"), \
             patch.object(settings, "VAULT_AUTH_TOKEN", PROD_TOKEN), \
             patch.object(settings, "GEMMA_BACKEND", "off"), \
             patch("httpx.AsyncClient.send",
                   new_callable=AsyncMock,
                   return_value=_OK_RESP):
            client = _prod_client()
            resp = client.post(
                "/v1/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {PROD_TOKEN}"},
            )
            assert resp.status_code == 200, (
                f"Metadata with 'file' key → {resp.status_code}, want 200. "
                f"Body: {resp.text[:200]}"
            )

    def test_b6_real_image_part_returns_400_in_production(self):
        """A real image_url content part must still return 400 in production."""
        payload = {
            "model": "m",
            "messages": [{
                "role": "user",
                "content": [{"type": "image_url",
                             "image_url": {"url": "data:image/png;base64,AAAA"}}],
            }],
        }
        with patch.object(settings, "VAULT_PROFILE", "production"), \
             patch.object(settings, "VAULT_AUTH_TOKEN", PROD_TOKEN), \
             patch.object(settings, "GEMMA_BACKEND", "off"):
            client = _prod_client()
            resp = client.post(
                "/v1/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {PROD_TOKEN}"},
            )
            assert resp.status_code == 400, (
                f"Image content part → {resp.status_code}, want 400."
            )


# ═══════════════════════════════════════════════════════════════════════════════
# B7 – bad JSON returns 400 with OpenAI-style body + x-request-id header
# ═══════════════════════════════════════════════════════════════════════════════

class TestB7BadJsonError:
    """Malformed JSON bodies must return 400 (not 503) with an OpenAI-style
    error object and an x-request-id header."""

    def _post_bad_json(self):
        with patch.object(settings, "GEMMA_BACKEND", "off"):
            client = TestClient(app)
            return client.post(
                "/v1/chat/completions",
                content=b"{not json at all",
                headers={"content-type": "application/json"},
            )

    def test_b7_bad_json_returns_400(self):
        """Malformed JSON body must return HTTP 400, not 503."""
        resp = self._post_bad_json()
        assert resp.status_code == 400, (
            f"Bad JSON → {resp.status_code}, want 400 (got: {resp.text[:100]})"
        )

    def test_b7_bad_json_has_openai_error_body(self):
        """Response body must be an OpenAI-style error object with 'error' key."""
        resp = self._post_bad_json()
        try:
            body = resp.json()
        except Exception:
            pytest.fail(f"Response body is not valid JSON: {resp.text[:100]}")
        assert "error" in body, (
            f"Bad JSON response must have 'error' key; got: {body}"
        )
        assert isinstance(body["error"], dict), (
            f"'error' must be a dict; got: {body['error']!r}"
        )

    def test_b7_bad_json_has_x_request_id(self):
        """Response must include an x-request-id header."""
        resp = self._post_bad_json()
        header_names = {k.lower() for k in resp.headers}
        assert "x-request-id" in header_names, (
            f"Bad JSON response must include x-request-id header; "
            f"got headers: {dict(resp.headers)}"
        )

    def test_b7_embeddings_bad_json_returns_400(self):
        """Same contract for /v1/embeddings."""
        with patch.object(settings, "GEMMA_BACKEND", "off"):
            client = TestClient(app)
            resp = client.post(
                "/v1/embeddings",
                content=b"[not valid",
                headers={"content-type": "application/json"},
            )
        assert resp.status_code == 400, (
            f"Bad JSON to /v1/embeddings → {resp.status_code}, want 400"
        )
        header_names = {k.lower() for k in resp.headers}
        assert "x-request-id" in header_names


# ═══════════════════════════════════════════════════════════════════════════════
# B8 – placeholder instruction injection behaviour
# ═══════════════════════════════════════════════════════════════════════════════

class TestB8PlaceholderInstruction:
    """When nothing is masked, the proxy must NOT inject a placeholder instruction
    message.  When something IS masked, the instruction must be merged into the
    existing system message, not added as a new message."""

    def _send(self, messages: list, *, capture_upstream_body: list | None = None):
        """Send a chat request and capture what the upstream receives."""
        upstream_received: list[dict] = []

        async def mock_handler(req: httpx.Request) -> httpx.Response:
            body = await req.aread()
            upstream_received.extend(json.loads(body).get("messages", []))
            return _OK_RESP

        with patch.object(settings, "GEMMA_BACKEND", "off"), \
             patch("httpx.AsyncClient.send",
                   new_callable=AsyncMock,
                   return_value=_OK_RESP) as mock_send:
            # Capture request body from mock call
            client = TestClient(app)
            resp = client.post(
                "/v1/chat/completions",
                json={"model": "m", "messages": messages},
            )
            # Extract what mock received
            if mock_send.called:
                sent_req = mock_send.call_args[0][0]  # first positional arg
                try:
                    body = sent_req.content
                    upstream_messages = json.loads(body).get("messages", [])
                    if capture_upstream_body is not None:
                        capture_upstream_body.extend(upstream_messages)
                    return resp, upstream_messages
                except Exception:
                    pass
            return resp, []

    def test_b8_clean_request_no_injection(self):
        """When no PII is detected, upstream must receive exactly the original
        messages — no extra system message injected."""
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "What is 2+2?"},
        ]
        _, upstream_msgs = self._send(messages)
        assert len(upstream_msgs) == 2, (
            f"Clean request: upstream must receive exactly 2 messages, "
            f"got {len(upstream_msgs)}: {upstream_msgs}"
        )
        assert not any(
            "placeholder" in (m.get("content") or "").lower()
            for m in upstream_msgs
        ), (
            "Clean request: no message may contain 'placeholder' text"
        )

    def test_b8_clean_no_system_msg_no_injection(self):
        """Clean request with no system message must also not get one injected."""
        messages = [{"role": "user", "content": "Tell me a joke."}]
        _, upstream_msgs = self._send(messages)
        assert len(upstream_msgs) == 1, (
            f"Clean request (no system msg): must get 1 upstream message, "
            f"got {len(upstream_msgs)}: {upstream_msgs}"
        )

    def test_b8_masked_request_instruction_in_existing_system(self):
        """When PII is masked, the instruction must be appended to the existing
        system message — the message count must not increase."""
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": f"My PAN is {PAN}"},
        ]
        _, upstream_msgs = self._send(messages)
        assert len(upstream_msgs) == 2, (
            f"Masked request: upstream must receive exactly 2 messages "
            f"(instruction merged into existing system message), "
            f"got {len(upstream_msgs)}: {upstream_msgs}"
        )
        # The system message content must include the instruction
        sys_content = next(
            (m.get("content", "") for m in upstream_msgs if m.get("role") == "system"),
            ""
        )
        assert "placeholder" in sys_content.lower(), (
            f"System message must contain placeholder instruction after masking; "
            f"got: {sys_content!r}"
        )

    def test_b8_masked_no_system_msg_instruction_prepended(self):
        """When PII is masked and there's no existing system message, a new
        system message must be inserted — total count = original + 1 at most."""
        messages = [{"role": "user", "content": f"My PAN is {PAN}"}]
        _, upstream_msgs = self._send(messages)
        # Either merged or a new system prepended — but not more than original + 1
        assert len(upstream_msgs) <= 2, (
            f"Masked request (no system msg): upstream must receive at most 2 "
            f"messages, got {len(upstream_msgs)}: {upstream_msgs}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# B9 – integer PII and dict-key PII masked before reaching upstream
# ═══════════════════════════════════════════════════════════════════════════════

class TestB9IntegerAndKeyPII:
    """Integers carrying PII (mobile, Aadhaar) and object keys that are PII
    values must be detected and masked before reaching the upstream."""

    def _chat(self, body: dict) -> tuple[httpx.Response, str]:
        """Send a chat request; return (response, raw upstream body string)."""
        upstream_body: list[str] = []

        async def mock_send_capture(req, **kw):
            upstream_body.append((await req.aread()).decode())
            return _OK_RESP

        with patch.object(settings, "GEMMA_BACKEND", "off"), \
             patch("httpx.AsyncClient.send",
                   new_callable=AsyncMock,
                   side_effect=mock_send_capture):
            client = TestClient(app)
            resp = client.post("/v1/chat/completions", json=body)

        return resp, upstream_body[0] if upstream_body else ""

    def test_b9_integer_mobile_number_masked(self):
        """An integer mobile number in a tool_call argument must be masked."""
        args = json.dumps({"mobile": 9876543210})
        body = {
            "model": "m",
            "messages": [
                {"role": "user", "content": "look up"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "c1", "type": "function",
                        "function": {"name": "kyc", "arguments": args},
                    }],
                },
            ],
        }
        resp, upstream_raw = self._chat(body)
        assert resp.status_code == 200
        assert "9876543210" not in upstream_raw, (
            f"Mobile number 9876543210 reached upstream unmasked.\n"
            f"Upstream body: {upstream_raw[:300]}"
        )

    def test_b9_integer_aadhaar_masked(self):
        """An integer Aadhaar number in a tool_call argument must be masked."""
        args = json.dumps({"aadhaar_no": int(AAD)})
        body = {
            "model": "m",
            "messages": [
                {"role": "user", "content": "verify"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "c2", "type": "function",
                        "function": {"name": "kyc", "arguments": args},
                    }],
                },
            ],
        }
        resp, upstream_raw = self._chat(body)
        assert resp.status_code == 200
        assert AAD not in upstream_raw, (
            f"Aadhaar {AAD} reached upstream unmasked.\n"
            f"Upstream body: {upstream_raw[:300]}"
        )

    def test_b9_pii_dict_key_masked(self):
        """A dict key that is itself a PII value (mobile number) must be masked."""
        args = json.dumps({"9876543211": "key-with-pii"})
        body = {
            "model": "m",
            "messages": [
                {"role": "user", "content": "process"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "c3", "type": "function",
                        "function": {"name": "proc", "arguments": args},
                    }],
                },
            ],
        }
        resp, upstream_raw = self._chat(body)
        assert resp.status_code == 200
        assert "9876543211" not in upstream_raw, (
            f"PII dict key '9876543211' reached upstream unmasked.\n"
            f"Upstream body: {upstream_raw[:300]}"
        )

    def test_b9_all_three_combined(self):
        """All three: integer mobile, integer Aadhaar, PII dict-key — none must reach upstream."""
        args = json.dumps({
            "mobile": 9876543210,
            "aadhaar_no": int(AAD),
            "9876543211": "key-with-pii",
        })
        body = {
            "model": "m",
            "messages": [
                {"role": "user", "content": "look up"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "c4", "type": "function",
                        "function": {"name": "kyc", "arguments": args},
                    }],
                },
            ],
        }
        resp, upstream_raw = self._chat(body)
        assert resp.status_code == 200
        leaked = [v for v in ("9876543210", AAD, "9876543211") if v in upstream_raw]
        assert not leaked, (
            f"PII values reached upstream unmasked: {leaked}\n"
            f"Upstream body: {upstream_raw[:400]}"
        )

    def test_b9_large_seed_not_changed(self):
        """A top-level parameter 'seed' that looks like a 10-digit mobile number must NOT be changed."""
        body = {
            "model": "m",
            "messages": [{"role": "user", "content": "hello"}],
            "seed": 9876543210,
        }
        resp, upstream_raw = self._chat(body)
        assert resp.status_code == 200
        sent = json.loads(upstream_raw)
        assert sent.get("seed") == 9876543210, (
            f"Top-level seed was modified or masked: {sent.get('seed')}"
        )

    def test_b9_large_max_tokens_not_changed(self):
        """A top-level parameter 'max_tokens' must NOT be changed."""
        body = {
            "model": "m",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 9876543210,
        }
        resp, upstream_raw = self._chat(body)
        assert resp.status_code == 200
        sent = json.loads(upstream_raw)
        assert sent.get("max_tokens") == 9876543210, (
            f"Top-level max_tokens was modified or masked: {sent.get('max_tokens')}"
        )

    def test_b9_booleans_and_floats_never_touched(self):
        """Booleans and floats inside messages or metadata must never be touched."""
        body = {
            "model": "m",
            "messages": [
                {
                    "role": "user",
                    "content": "check settings",
                    "flag": True,
                    "score": 98.76543210,
                }
            ],
            "metadata": {
                "is_active": False,
                "temperature_override": 0.987654321,
            },
        }
        resp, upstream_raw = self._chat(body)
        assert resp.status_code == 200
        sent = json.loads(upstream_raw)
        assert sent["messages"][0].get("flag") is True
        assert sent["messages"][0].get("score") == 98.76543210
        assert sent["metadata"].get("is_active") is False
        assert sent["metadata"].get("temperature_override") == 0.987654321

    def test_b9_logit_bias_keys_and_values_never_touched(self):
        """Keys and values under logit_bias must never be modified, even if keys match PII formats."""
        body = {
            "model": "m",
            "messages": [{"role": "user", "content": "hello"}],
            "logit_bias": {
                "9876543210": 100,
                "367598341203": -100,
            },
        }
        resp, upstream_raw = self._chat(body)
        assert resp.status_code == 200
        sent = json.loads(upstream_raw)
        assert sent.get("logit_bias") == {
            "9876543210": 100,
            "367598341203": -100,
        }

    def test_b9_partial_integer_not_masked(self):
        """An integer that does NOT match the detector as a whole string must NOT be changed."""
        body = {
            "model": "m",
            "messages": [
                {
                    "role": "user",
                    "content": "order id",
                    "order_id": 98765,  # 5 digits, not a 10-digit mobile or 12-digit aadhaar
                }
            ],
        }
        resp, upstream_raw = self._chat(body)
        assert resp.status_code == 200
        sent = json.loads(upstream_raw)
        assert sent["messages"][0].get("order_id") == 98765


# ═══════════════════════════════════════════════════════════════════════════════
# B10 – merge_spans correctness
# ═══════════════════════════════════════════════════════════════════════════════

class TestB10MergeSpans:
    """merge_spans must never drop a non-overlapping span and must never produce
    overlapping output spans."""

    def _overlaps(self, a: Span, b: Span) -> bool:
        return a.start < b.end and a.end > b.start

    def _check_case(self, spans: list[Span]) -> str | None:
        """Return an error string if the result is invalid, else None."""
        out = merge_spans(list(spans))
        # No overlapping output spans
        for i, x in enumerate(out):
            for y in out[i + 1:]:
                if self._overlaps(x, y):
                    return f"Output contains overlapping spans: {x} vs {y}"
        # No dropped non-overlapping spans
        for s in spans:
            if s not in out and not any(self._overlaps(s, k) for k in out):
                return f"Span {s} was dropped without being overlapped by any kept span"
        return None

    def test_b10_known_chain_a_c_b(self):
        """A=[0,6), C=[4,12), B=[10,19): overlapping chain must resolve without
        dropping any span that isn't covered by another kept span."""
        A = Span(0, 6, "A", "rule", 1.0)
        C = Span(4, 12, "C", "rule", 1.0)
        B = Span(10, 19, "B", "rule", 1.0)
        err = self._check_case([A, B, C])
        assert err is None, f"Known chain [A,B,C]: {err}"

    def test_b10_non_overlapping_spans_all_kept(self):
        """Non-overlapping spans must all appear in the output."""
        spans = [
            Span(0, 5, "PAN", "rule", 1.0),
            Span(10, 20, "MOBILE", "rule", 1.0),
            Span(30, 40, "AADHAAR", "rule", 1.0),
        ]
        out = merge_spans(list(spans))
        assert len(out) == 3, (
            f"3 non-overlapping spans must all be in output; got: {out}"
        )

    def test_b10_higher_priority_wins_overlap(self):
        """When two spans overlap, the higher-priority one (rule > gemma) must win."""
        rule_span = Span(0, 10, "PAN", "rule", 0.5)
        gemma_span = Span(2, 8, "PERSON", "gemma", 0.9)
        out = merge_spans([gemma_span, rule_span])
        assert len(out) == 1
        assert out[0] == rule_span, (
            f"Rule span must win over gemma span; got: {out[0]}"
        )

    def test_b10_longer_span_wins_same_source(self):
        """When two spans from the same source overlap, the longer one wins."""
        short = Span(0, 5, "PAN", "rule", 1.0)
        longer = Span(0, 10, "PAN", "rule", 1.0)
        out = merge_spans([short, longer])
        assert len(out) == 1
        assert out[0] == longer, (
            f"Longer span must win; got: {out[0]}"
        )

    def test_b10_200_random_cases(self):
        """200 randomly generated cases must produce no overlaps and no dropped spans."""
        random.seed(7)
        errors: list[str] = []
        for case_idx in range(200):
            spans = [
                Span(
                    start := random.randint(0, 40),
                    start + random.randint(1, 12),
                    random.choice(["PAN", "MOBILE", "AADHAAR"]),
                    random.choice(["rule", "gemma"]),
                    random.random(),
                )
                for _ in range(random.randint(2, 7))
            ]
            err = self._check_case(spans)
            if err:
                errors.append(f"Case {case_idx}: {err}\n  Input: {spans}")
        assert not errors, (
            f"{len(errors)} of 200 random cases failed:\n" + "\n".join(errors[:3])
        )
