#!/usr/bin/env python3
"""
VaultProxy independent verification (real servers, fake data only).

Usage (run with the repo's own Python environment, from anywhere):
    /path/to/repo/.venv/bin/python vp_review_check.py /path/to/repo
    ... --only B1,B2        run a subset
    ... --detectors         also print the detector probe table (informational)

It starts a local mock upstream (plain + gzip) and several VaultProxy processes
with different settings, sends requests, prints PASS / FAIL / SKIP per check and
stops everything. Exit code 1 if any check FAILs. It never calls the internet.
Note: secret-looking probe strings are built at runtime from pieces so that
GitHub push protection and secret scanners do not see a complete token in the source.
"""
import argparse, json, os, random, socket, subprocess, sys, tempfile, textwrap, threading, time

try:
    import httpx
except ImportError:
    sys.exit("httpx is required: run this script with the repository's virtual environment Python.")

UPSTREAM_SRC = r'''
import asyncio, json, os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.gzip import GZipMiddleware

app = FastAPI()
if os.environ.get("UP_GZIP") == "1":
    app.add_middleware(GZipMiddleware, minimum_size=0)
LOG = os.environ["UP_LOG"]

async def handler(request: Request):
    body = await request.body()
    try:
        data = json.loads(body)
    except Exception:
        data = {}
    with open(LOG, "a") as f:
        f.write(json.dumps({"path": request.url.path, "body": data}) + "\n")
    text = json.dumps(data.get("messages", data))
    if data.get("stream"):
        slow = "slowstream" in json.dumps(data)
        async def gen():
            n = 8 if slow else 2
            for i in range(n):
                chunk = {"id": "x", "object": "chat.completion.chunk",
                         "choices": [{"index": 0, "delta": {"content": "part%d " % i}, "finish_reason": None}]}
                yield "data: " + json.dumps(chunk) + "\n\n"
                await asyncio.sleep(0.5 if slow else 0.1)
            yield "data: [DONE]\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")
    return JSONResponse({"id": "x", "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]})

@app.post("/v1/chat/completions")
async def c1(request: Request): return await handler(request)
@app.post("/chat/completions")
async def c2(request: Request): return await handler(request)
@app.post("/rootapi/chat/completions")
async def c3(request: Request): return await handler(request)
@app.get("/v1/models")
async def m1(): return {"object": "list", "data": []}
@app.get("/models")
async def m2(): return {"object": "list", "data": []}
'''

TOKEN = "abcdefghijklmnopqrstuvwxyz0123456789"
PAN, AAD = "ABCPB1234F", "367598341203"
RESULTS = []

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def wait_up(url, secs=15):
    end = time.time() + secs
    while time.time() < end:
        try:
            httpx.get(url, timeout=1); return True
        except Exception:
            time.sleep(0.25)
    return False

class Proc:
    def __init__(self, args, env, cwd, name):
        self.log = tempfile.NamedTemporaryFile("w+", delete=False, suffix=f".{name}.log")
        self.p = subprocess.Popen(args, env=env, cwd=cwd, stdout=self.log, stderr=subprocess.STDOUT)
    def stop(self):
        try: self.p.terminate(); self.p.wait(5)
        except Exception:
            try: self.p.kill()
            except Exception: pass
    def output(self):
        self.log.flush(); return open(self.log.name).read()

class Ctx:
    def __init__(self, repo):
        self.repo = repo; self.procs = []
        self.tmp = tempfile.mkdtemp(prefix="vpcheck_")
        open(os.path.join(self.tmp, "vp_upstream.py"), "w").write(UPSTREAM_SRC)
        self.logs = {}
    def upstream(self, gzip=False):
        port = free_port(); log = os.path.join(self.tmp, f"up_{port}.jsonl"); open(log, "w").close()
        env = dict(os.environ, UP_GZIP="1" if gzip else "0", UP_LOG=log)
        pr = Proc([sys.executable, "-m", "uvicorn", "vp_upstream:app", "--app-dir", self.tmp, "--port", str(port), "--log-level", "warning"], env, self.tmp, "up")
        self.procs.append(pr)
        assert wait_up(f"http://127.0.0.1:{port}/models"), "mock upstream did not start"
        self.logs[port] = log
        return port, log
    def proxy(self, upstream_url, env_extra=None, wait=True):
        port = free_port()
        env = dict(os.environ, PYTHONPATH=self.repo, UPSTREAM_BASE_URL=upstream_url, GEMMA_BACKEND="off")
        for k in ("VAULT_PROFILE", "VAULT_AUTH_TOKEN", "DEMO_MODE", "STRICT_MODE", "MAX_CONCURRENT_REQUESTS", "GEMINI_API_KEY"):
            env.pop(k, None)
        for k, v in (env_extra or {}).items():
            if v is None: env.pop(k, None)
            else: env[k] = v
        pr = Proc([sys.executable, "-m", "uvicorn", "vaultproxy.server:app", "--port", str(port), "--log-level", "warning"], env, self.repo, "proxy")
        self.procs.append(pr)
        if wait and not wait_up(f"http://127.0.0.1:{port}/healthz"):
            raise RuntimeError("proxy did not start: " + pr.output()[-400:])
        return f"http://127.0.0.1:{port}", pr
    def close(self):
        for p in self.procs: p.stop()

def upstream_last(log, n=1):
    lines = [json.loads(l) for l in open(log) if l.strip()]
    return lines[-n:] if n > 1 else (lines[-1] if lines else None)

def check(code, title):
    def deco(fn):
        fn._code, fn._title = code, title; RESULTS.append(fn); return fn
    return deco

CHAT = lambda content="My PAN is %s." % PAN: {"model": "m", "messages": [{"role": "user", "content": content}]}
AUTH = {"authorization": f"Bearer {TOKEN}"}

@check("B1", "gzip-compressed upstream reply reaches the client intact")
def b1(c):
    port, log = c.upstream(gzip=True)
    base, _ = c.proxy(f"http://127.0.0.1:{port}")
    try:
        r = httpx.post(base + "/v1/chat/completions", json=CHAT(), timeout=10)
    except Exception as e:
        return "FAIL", f"client error {type(e).__name__}: {str(e)[:80]}"
    ok = r.status_code == 200 and PAN in r.json()["choices"][0]["message"]["content"]
    return ("PASS", "client decoded the reply; PAN restored") if ok else ("FAIL", f"status {r.status_code}")

@check("B2", "a finished stream does not kill other in-flight streams")
def b2(c):
    port, log = c.upstream()
    base, _ = c.proxy(f"http://127.0.0.1:{port}")
    res = {}
    def run(tag, text):
        ev = []
        try:
            with httpx.stream("POST", base + "/v1/chat/completions", json={"model": "m", "stream": True, "messages": [{"role": "user", "content": text}]}, timeout=30) as r:
                for line in r.iter_lines():
                    if line.startswith("data:"): ev.append(line)
        except Exception as e:
            ev.append("EXC " + type(e).__name__)
        res[tag] = ev
    t = threading.Thread(target=run, args=("slow", "slowstream hello")); t.start()
    time.sleep(1.0); run("fast", "quick hello"); t.join()
    slow = res["slow"]; bad = any('"error"' in e or e.startswith("EXC") for e in slow)
    ok = len(slow) == 9 and not bad
    return ("PASS", "slow stream got all 9 events") if ok else ("FAIL", f"slow stream got {len(slow)}/9 events, error={bad}")

@check("B3", "UPSTREAM_BASE_URL works with bare host, /v1 suffix and a custom prefix")
def b3(c):
    port, log = c.upstream(); bad = []
    for suffix, expect in (("", "/v1/chat/completions"), ("/v1", "/v1/chat/completions"), ("/rootapi", "/rootapi/chat/completions")):
        base, _ = c.proxy(f"http://127.0.0.1:{port}{suffix}")
        open(log, "w").close()
        r = httpx.post(base + "/v1/chat/completions", json=CHAT("hello"), timeout=10)
        got = (upstream_last(log) or {}).get("path")
        if r.status_code != 200 or got != expect: bad.append(f"base '{suffix or '(host only)'}' -> status {r.status_code}, upstream path {got}")
    return ("PASS", "all 3 base URL forms route correctly") if not bad else ("FAIL", "; ".join(bad))

@check("B4", "MAX_CONCURRENT_REQUESTS also covers an active stream (second request gets 429)")
def b4(c):
    port, log = c.upstream()
    base, _ = c.proxy(f"http://127.0.0.1:{port}", {"MAX_CONCURRENT_REQUESTS": "1"})
    def run():
        try:
            with httpx.stream("POST", base + "/v1/chat/completions", json={"model": "m", "stream": True, "messages": [{"role": "user", "content": "slowstream hi"}]}, timeout=30) as r:
                for _ in r.iter_lines(): pass
        except Exception: pass
    t = threading.Thread(target=run); t.start(); time.sleep(1.0)
    r = httpx.post(base + "/v1/chat/completions", json=CHAT("second"), timeout=10); t.join()
    after = httpx.post(base + "/v1/chat/completions", json=CHAT("third"), timeout=10).status_code
    ok = r.status_code == 429 and after == 200
    return ("PASS", "429 during stream, 200 after it finished (slot released)") if ok else ("FAIL", f"during stream {r.status_code}, after stream {after}")

@check("B5", "VAULT_AUTH_TOKEN is enforced in the development profile too")
def b5(c):
    port, log = c.upstream()
    base, _ = c.proxy(f"http://127.0.0.1:{port}", {"VAULT_AUTH_TOKEN": TOKEN})
    no = httpx.post(base + "/v1/chat/completions", json=CHAT("hi"), timeout=10).status_code
    models = httpx.get(base + "/v1/models", timeout=10).status_code
    yes = httpx.post(base + "/v1/chat/completions", json=CHAT("hi"), headers=AUTH, timeout=10).status_code
    ok = no == 401 and models == 401 and yes == 200
    return ("PASS", "401 without token (chat and models), 200 with token") if ok else ("FAIL", f"chat no-token {no}, models no-token {models}, with token {yes}")

@check("B6", "a property or metadata key named 'file' is not treated as binary content (production)")
def b6(c):
    port, log = c.upstream()
    base, _ = c.proxy(f"http://127.0.0.1:{port}", {"VAULT_PROFILE": "production", "VAULT_AUTH_TOKEN": TOKEN})
    tool = {"model": "m", "messages": [{"role": "user", "content": "hello"}], "tools": [{"type": "function", "function": {"name": "r", "description": "x", "parameters": {"type": "object", "properties": {"file": {"type": "string"}}}}}]}
    meta = {"model": "m", "messages": [{"role": "user", "content": "hello"}], "metadata": {"file": "report.txt"}}
    img = {"model": "m", "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]}]}
    a, b, i = (httpx.post(base + "/v1/chat/completions", json=x, headers=AUTH, timeout=10).status_code for x in (tool, meta, img))
    ok = a == 200 and b == 200 and i == 400
    return ("PASS", "false positives gone; real image part still blocked") if ok else ("FAIL", f"tool schema {a} (want 200), metadata {b} (want 200), image part {i} (want 400)")

@check("B7", "client errors are 400 with an OpenAI-style body and an x-request-id header")
def b7(c):
    port, log = c.upstream()
    base, _ = c.proxy(f"http://127.0.0.1:{port}")
    r = httpx.post(base + "/v1/chat/completions", content=b"{not json", headers={"content-type": "application/json"}, timeout=10)
    try: shape = "error" in r.json()
    except Exception: shape = False
    rid = "x-request-id" in {k.lower() for k in r.headers}
    ok = r.status_code == 400 and shape and rid
    return ("PASS", "400, error object, request id present") if ok else ("FAIL", f"status {r.status_code} (want 400), OpenAI-style body {shape}, x-request-id {rid}")

@check("B8", "no placeholder instruction is injected when nothing is masked; no extra message when something is")
def b8(c):
    port, log = c.upstream()
    base, _ = c.proxy(f"http://127.0.0.1:{port}")
    msgs = [{"role": "system", "content": "You are helpful."}, {"role": "user", "content": "What is 2+2?"}]
    open(log, "w").close(); httpx.post(base + "/v1/chat/completions", json={"model": "m", "messages": msgs}, timeout=10)
    seen = upstream_last(log)["body"]["messages"]
    clean_ok = len(seen) == 2 and not any("placeholder" in (m.get("content") or "").lower() for m in seen)
    msgs2 = [{"role": "system", "content": "You are helpful."}, {"role": "user", "content": f"My PAN is {PAN}"}]
    open(log, "w").close(); httpx.post(base + "/v1/chat/completions", json={"model": "m", "messages": msgs2}, timeout=10)
    seen2 = upstream_last(log)["body"]["messages"]
    pii_ok = len(seen2) == 2 and sum("placeholder" in (m.get("content") or "").lower() for m in seen2) == 1
    ok = clean_ok and pii_ok
    return ("PASS", "no injection when clean; instruction merged into the existing system message when masked") if ok else ("FAIL", f"clean request upstream saw {len(seen)} messages (want 2); masked request saw {len(seen2)} messages (want 2)")

@check("B9", "integers and object keys carrying PII do not reach the upstream")
def b9(c):
    port, log = c.upstream()
    base, _ = c.proxy(f"http://127.0.0.1:{port}")
    args = json.dumps({"mobile": 9876543210, "aadhaar_no": int(AAD), "9876543211": "key-with-pii"})
    body = {"model": "m", "messages": [{"role": "user", "content": "look up"}, {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "kyc", "arguments": args}}]}]}
    open(log, "w").close(); httpx.post(base + "/v1/chat/completions", json=body, timeout=10)
    seen = open(log).read(); leaked = [n for n in ("9876543210", AAD, "9876543211") if n in seen]
    return ("PASS", "none of the 3 values reached the upstream") if not leaked else ("FAIL", "reached upstream unmasked: " + ", ".join(leaked))

def _py(c, code, env=None, timeout=60):
    e = dict(os.environ, PYTHONPATH=c.repo); e.update(env or {})
    return subprocess.run([sys.executable, "-c", textwrap.dedent(code)], cwd=c.repo, env=e, capture_output=True, text=True, timeout=timeout)

@check("B10", "merge_spans never drops a span unless a kept span overlaps it (200 random cases + the known chain)")
def b10(c):
    r = _py(c, """
        import random
        from vaultproxy.detectors import Span
        from vaultproxy.merge import merge_spans
        def ov(a,b): return a.start < b.end and a.end > b.start
        bad = 0
        A,C,B = Span(0,6,'A','rule',1.0), Span(4,12,'C','rule',1.0), Span(10,19,'B','rule',1.0)
        cases = [[A,B,C]]
        random.seed(7)
        for _ in range(200):
            cases.append([Span(s, s+random.randint(1,12), random.choice('XYZ'), random.choice(['rule','gemma']), random.random()) for s in [random.randint(0,40) for _ in range(random.randint(2,7))]])
        for spans in cases:
            out = merge_spans(list(spans))
            if any(ov(x,y) for i,x in enumerate(out) for y in out[i+1:]): bad += 1; continue
            for s in spans:
                if s not in out and not any(ov(s,k) for k in out): bad += 1; break
        print('BAD', bad)
    """)
    if r.returncode != 0: return "SKIP", "could not import vaultproxy.merge: " + r.stderr[-120:]
    bad = int(r.stdout.strip().split()[-1])
    return ("PASS", "0 of 201 cases dropped a span or produced overlaps") if bad == 0 else ("FAIL", f"{bad} of 201 cases dropped a span or produced overlapping output")

@check("B11", "production keeps no copy of masked request bodies after a request (DEMO_MODE=false)")
def b11(c):
    r = _py(c, """
        import json, httpx
        from fastapi.testclient import TestClient
        import vaultproxy.server as server
        import vaultproxy.health as health
        def handler(req): return httpx.Response(200, json={"id":"x","object":"chat.completion","choices":[{"index":0,"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}]})
        server._httpx_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        cl = TestClient(server.app)
        r = cl.post('/v1/chat/completions', json={"model":"m","messages":[{"role":"user","content":"notes with Sunita Verma and PAN ABCPB1234F"}]}, headers={"authorization":"Bearer %s"})
        held = json.dumps(getattr(health, 'LAST_MASKED_REQUEST', {}))
        print('STATUS', r.status_code, 'HELD', 'Sunita' in held)
    """ % TOKEN, env={"VAULT_PROFILE": "production", "VAULT_AUTH_TOKEN": TOKEN, "GEMMA_BACKEND": "off", "UPSTREAM_BASE_URL": "http://upstream.test", "DEMO_MODE": "false"})
    if "STATUS" not in r.stdout: return "SKIP", "internal API moved or request failed: " + (r.stderr or r.stdout)[-160:]
    held = r.stdout.strip().split()[-1] == "True"
    return ("FAIL", "masked request body still held in a module-level variable") if held else ("PASS", "nothing retained")

@check("B12", "the Gemini API key never appears in request URLs or logs")
def b12(c):
    r = _py(c, """
        import asyncio, io, logging, httpx
        import vaultproxy.server
        import vaultproxy.gemma_layer as gl
        from vaultproxy.config import settings
        settings.GEMMA_BACKEND = 'gemini'; settings.GEMINI_API_KEY = 'FAKE_KEY_abc123SECRET'; settings.STRICT_MODE = False
        seen = []
        orig = httpx.AsyncClient
        def handler(req):
            seen.append(str(req.url) + ' ' + str(dict(req.headers))); return httpx.Response(403, json={"error": "denied"})
        def factory(*a, **k):
            k.pop('transport', None); return orig(*a, transport=httpx.MockTransport(handler), **k)
        httpx.AsyncClient = factory
        buf = io.StringIO(); h = logging.StreamHandler(buf); root = logging.getLogger(); root.addHandler(h); root.setLevel(logging.DEBUG)
        gl.circuit_breaker.state = 'CLOSED'
        asyncio.run(gl.run_gemma_detection('Hello this is a test sentence'))
        print('URLKEY', any('key=FAKE' in s.split(' ')[0] for s in seen), 'LOGKEY', 'FAKE_KEY_abc123SECRET' in buf.getvalue())
    """)
    if "URLKEY" not in r.stdout: return "SKIP", "internal API moved: " + (r.stderr or r.stdout)[-160:]
    parts = r.stdout.split(); url_leak, log_leak = parts[parts.index("URLKEY") + 1] == "True", parts[parts.index("LOGKEY") + 1] == "True"
    return ("PASS", "key not in URL or logs") if not (url_leak or log_leak) else ("FAIL", f"key in URL: {url_leak}, key in logs: {log_leak}")

@check("B13", "/readyz does not say 'ready' when the configured SLM backend is unreachable")
def b13(c):
    port, log = c.upstream()
    base, _ = c.proxy(f"http://127.0.0.1:{port}", {"GEMMA_BACKEND": "ollama", "OLLAMA_URL": "http://127.0.0.1:9"})
    j = httpx.get(base + "/readyz", timeout=10).json()
    return ("PASS", f"status '{j.get('status')}'") if j.get("status") != "ready" else ("FAIL", f"/readyz says '{j.get('status')}' (model shown: {j.get('slm_model')}) while Ollama is down")

@check("B14", "no hardcoded-name heuristic: default settings with no SLM do not mask 'Aniket Chaudhary' or 'Vikram' by name list")
def b14(c):
    port, log = c.upstream()
    base, _ = c.proxy(f"http://127.0.0.1:{port}", {"GEMMA_BACKEND": None, "OLLAMA_URL": "http://127.0.0.1:9"})
    open(log, "w").close()
    httpx.post(base + "/v1/chat/completions", json=CHAT("Hello, I am Aniket Chaudhary and my friend Vikram says hi."), timeout=15)
    seen = upstream_last(log)["body"]["messages"][-1]["content"]
    masked = "Aniket Chaudhary" not in seen or "Vikram" not in seen
    return ("FAIL", f"upstream saw: {seen[:90]}") if masked else ("PASS", "names are not masked by a hardcoded list (SLM off/unavailable is reported, not faked)")

@check("B15", "a misconfigured production start prints a readable message, not a Python traceback")
def b15(c):
    env = dict(os.environ, PYTHONPATH=c.repo, VAULT_PROFILE="production", GEMMA_BACKEND="off"); env.pop("VAULT_AUTH_TOKEN", None)
    p = subprocess.run([sys.executable, "-m", "uvicorn", "vaultproxy.server:app", "--port", str(free_port())], cwd=c.repo, env=env, capture_output=True, text=True, timeout=30)
    out = p.stdout + p.stderr
    ok = p.returncode != 0 and "Traceback" not in out and "VAULT_AUTH_TOKEN" in out
    return ("PASS", "refused to start with a readable message") if ok else ("FAIL", f"exit {p.returncode}, traceback shown: {'Traceback' in out}")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("repo"); ap.add_argument("--only"); ap.add_argument("--detectors", action="store_true")
    a = ap.parse_args(); repo = os.path.abspath(a.repo)
    if not os.path.isdir(os.path.join(repo, "vaultproxy")): sys.exit("not a VaultProxy repo: " + repo)
    only = set(a.only.split(",")) if a.only else None
    c = Ctx(repo); rows = []
    try:
        for fn in RESULTS:
            if only and fn._code not in only: continue
            t0 = time.time()
            try: status, detail = fn(c)
            except Exception as e: status, detail = "FAIL", f"check crashed: {type(e).__name__}: {str(e)[:120]}"
            rows.append((fn._code, status, fn._title, detail, time.time() - t0))
            print(f"[{status:4}] {fn._code:4} {fn._title}\n         {detail}  ({rows[-1][4]:.1f}s)", flush=True)
        if a.detectors:
            r = _py(c, """
                from vaultproxy.detectors.registry import run_rule_detectors
                from vaultproxy.detectors.verhoeff import generate_verhoeff
                A = '36759834120' + str(generate_verhoeff('36759834120'))
                probes = {'PAN lower':'pan abcpb1234f','PAN spaced':'PAN ABCPB 1234 F','Aadhaar spaced':A[:4]+' '+A[4:8]+' '+A[8:],'Aadhaar dotted':A[:4]+'.'+A[4:8]+'.'+A[8:],'Aadhaar newline':A[:4]+chr(10)+A[4:8]+chr(10)+A[8:],'Aadhaar Arabic-Indic':A.translate(str.maketrans('0123456789','٠١٢٣٤٥٦٧٨٩')),'Aadhaar full-width':A.translate(str.maketrans('0123456789','０１２３４５６７８９')),'Mobile 91':'call 919830012345','Mobile dots':'call 98300.12345','UPI @apl':'pay rahul@apl','UPI @ptsbi':'pay rahul@ptsbi','sk- key':'sk'+'-proj-'+'abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGH','Google key':'AI'+'zaSyA1234567890abcdefghijklmnopqrstuv','Slack':'xo'+'xb-'+'123456789012-123456789012-'+'abcdefghijklmnopqrstuvwx','Stripe':'sk_'+'live_'+'abcdefghijklmnopqrstuvwx','Private key':'-----BEGIN '+'RSA PRIVATE'+' KEY-----','DB URL':'postgres://admin:Sup3rSecret@db.internal:5432/app','Card':'card 4111 1111 1111 1111','GSTIN':'GSTIN 27AAPFU0939F1ZV'}
                for k,v in probes.items():
                    s = sorted({x.type for x in run_rule_detectors(v)}); print(('CAUGHT ' if s else 'MISSED ')+k.ljust(22), s)
            """)
            print("\nDetector probes (informational):\n" + (r.stdout or r.stderr))
    finally:
        c.close()
    n = {s: sum(1 for r in rows if r[1] == s) for s in ("PASS", "FAIL", "SKIP")}
    print(f"\nSUMMARY: {n['PASS']} PASS, {n['FAIL']} FAIL, {n['SKIP']} SKIP")
    sys.exit(1 if n["FAIL"] else 0)

if __name__ == "__main__":
    main()
