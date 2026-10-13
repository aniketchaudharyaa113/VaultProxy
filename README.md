# VaultProxy

Local-first, OpenAI-compatible privacy proxy for LLM applications.
Intercepts prompt payloads to mask sensitive Indian personal data and API keys before forwarding upstream.
Restores sensitive entities in real time on streaming and non-streaming model responses.

> **Pre-release (0.2.x). Not independently security-reviewed. Try it with non-sensitive data first. Not legal advice; using it does not make a deployment compliant.**

---

## 1. What It Does and What It Does Not Do

### What it does:
- Intercepts OpenAI-compatible chat completion requests locally and masks Indian personal data (Aadhaar, PAN, mobile numbers, UPI IDs, IFSC codes, email addresses) and generic API secrets using deterministic regex and checksum rules.
- Restores original sensitive values on response streams (SSE) and JSON responses so the client receives unmasked output while upstream receives typed token placeholders like `[PAN_1]`.
- Provides an optional secondary SLM layer (Gemma via Ollama or Gemini API) for unstructured personal names and postal addresses with concurrency control and fail-closed strict error handling.

### What it does not do:
- Does not scrub background context, semantic clues, or unmasked identifying details in prompt prose (such as job titles, dates, or relationship references).
- Does not translate non-standard vendor APIs (Azure OpenAI deployment-based endpoints and native Anthropic `/v1/messages` APIs are not supported).
- Does not provide TLS termination or cryptographic access isolation on its own (runs over plain HTTP on `127.0.0.1`; using it does not make an application legally compliant).

---

## 2. How It Works

```text
               +-------------------------------------------------+
               |                   VaultProxy                    |
[Client App]   |                                                 |   [Upstream LLM]
     |         |   1. Inspect JSON & scan leaves                 |         |
     |-------->|   2. Rule Detectors (Aadhaar, PAN, etc.)        |         |
     | Request |   3. Optional SLM (Gemma via Ollama)            |         |
     |         |   4. Tokenize to [PAN_1], store in RequestVault |         |
     |         |                                                 |         |
     |         |---------------- Forward Masked Payload -------->|         |
     |         |                                                 | Receive |
     |         |<--------------- Response with Tokens -----------| Tokens  |
     |         |                                                 |         |
     |<--------|   5. Restore [PAN_1] -> original value          |         |
     | Restored|   6. Add X-Vault-Report header                  |         |
     | Reply   +-------------------------------------------------+         |
```

### Real Execution Example (from `scripts/smoke.sh`)

**Client Request:**
```json
{
  "model": "gpt-4",
  "messages": [
    {
      "role": "user",
      "content": "My Aadhaar is 367598341203 and PAN is ABCPB1234F."
    }
  ],
  "stream": false
}
```

**What the Upstream Received:**
```json
{
  "model": "gpt-4",
  "messages": [
    {
      "role": "system",
      "content": "IMPORTANT: Keep all token placeholders formatted like [TYPE_N] (e.g. [PAN_1], [AADHAAR_1]) EXACTLY as they are in your response. Do not modify, translate, or remove them."
    },
    {
      "role": "user",
      "content": "My Aadhaar is [AADHAAR_1] and PAN is [PAN_1]."
    }
  ],
  "stream": false
}
```

**Restored Reply Received by Client:**
```json
{
  "id": "chatcmpl-mock123",
  "object": "chat.completion",
  "created": 1700000000,
  "model": "gpt-4",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "My Aadhaar is 367598341203 and PAN is ABCPB1234F."
      },
      "finish_reason": "stop"
    }
  ]
}
```

**`X-Vault-Report` Header Added to Response:**
```json
{"masked": {"PAN": 1, "AADHAAR": 1}, "degraded": false, "gemma_used": false, "slm_chunks": 1}
```

---

## 3. Quickstart from Source

*Note: VaultProxy is not on PyPI yet, there is no Docker image yet, and there is no standalone CLI binary yet. Run from source using python.*

### Step 1: Clone Repository
```bash
git clone https://github.com/aniketchaudharyaa113/october.git
cd october
```

### Step 2: Create a Virtual Environment and Install
```bash
python3 -m venv .venv
source .venv/bin/activate  # Fish: source .venv/bin/activate.fish | Windows: .venv\Scripts\Activate.ps1
pip install .

# Or install test dependencies needed to run "pytest -q":
pip install ".[dev]"
```

### Step 3: Run

#### Path (a): Try with Bundled Mock Upstream (Zero API Keys Needed)

> [!WARNING]
> `/demo/*` exposes masked request bodies and must never be enabled outside a local trial.

Terminal 1 — Run mock upstream server:
```bash
python3 -m uvicorn demo.mock_upstream:app --port 8001
```

Terminal 2 — Run VaultProxy pointing to the mock upstream:
```bash
UPSTREAM_BASE_URL="http://localhost:8001" DEMO_MODE=true GEMMA_BACKEND=off python3 -m uvicorn vaultproxy.server:app --port 8000
```

Terminal 3 — Send a test prompt with curl:
```bash
curl -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "My PAN is ABCPB1234F and Aadhaar is 367598341203"}]
  }'
```

Verify what the upstream received by checking `/demo/last`:
```bash
curl http://127.0.0.1:8000/demo/last
```
The upstream receives tokens like `[PAN_1]` and `[AADHAAR_1]`, while the client response contains the restored values `ABCPB1234F` and `367598341203`.

#### Path (b): Connect to a Real OpenAI-Compatible API

```bash
export UPSTREAM_BASE_URL="https://api.openai.com/v1"
export UPSTREAM_API_KEY="your-openai-api-key"
export GEMMA_BACKEND="off"
python3 -m uvicorn vaultproxy.server:app --port 8000
```

---

## 4. Connecting Your App

### OpenAI Python SDK (Tested)
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="your_vault_auth_token_or_dummy_key",
)

response = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "My PAN is ABCPB1234F"}],
)
print(response.choices[0].message.content)
```

### cURL (Tested)
```bash
curl -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer your_vault_auth_token" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "My PAN is ABCPB1234F"}]
  }'
```

### OpenAI Node.js SDK (Untested)
```javascript
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "http://127.0.0.1:8000/v1",
  apiKey: "your_vault_auth_token",
});
```

### LangChain (Untested)
```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="your_vault_auth_token",
    model="gpt-4",
)
```

---

## 5. UPSTREAM_BASE_URL Routing

VaultProxy standardizes routing across common base URL shapes verified in check B3:

| Base URL Form | Example Value | Upstream Path Routed To | Support Status |
| :--- | :--- | :--- | :--- |
| Bare host | `http://127.0.0.1:8001` | `http://127.0.0.1:8001/v1/chat/completions` | Supported |
| With `/v1` suffix | `http://127.0.0.1:8001/v1` | `http://127.0.0.1:8001/v1/chat/completions` | Supported |
| Custom prefix | `http://127.0.0.1:8001/rootapi` | `http://127.0.0.1:8001/rootapi/chat/completions` | Supported |
| Azure OpenAI | `https://{resource}.openai.azure.com` | Deployment-based paths and `api-key` header | Unsupported |
| Anthropic native | `https://api.anthropic.com` | Requires `/v1/messages` and `x-api-key` header | Unsupported |

---

## 6. Configuration Reference

Generated from `vaultproxy.config.Settings`:

### Essentials

| Name | Default | Meaning |
| :--- | :--- | :--- |
| `UPSTREAM_BASE_URL` | `http://localhost:8001` | Upstream OpenAI-compatible API base URL |
| `UPSTREAM_API_KEY` | `""` | Upstream bearer API key forwarded in Authorization header |
| `VAULT_PROFILE` | `development` | Operating profile (`development` or `production`) |
| `VAULT_AUTH_TOKEN` | `""` | Proxy bearer auth token required from clients in production |
| `GEMMA_BACKEND` | `off` | SLM detection backend (`off`, `ollama`, or `gemini`) |
| `STRICT_MODE` | `False` | Fail-closed mode (returns 503 on SLM errors instead of degraded rule fallback) |
| `DEMO_MODE` | `False` | Enables demo helper endpoints and console (`/demo/*`) |

### Advanced

| Name | Default | Meaning |
| :--- | :--- | :--- |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama service base URL |
| `GEMMA_MODEL` | `gemma4:e2b` | Model identifier used for SLM detection |
| `GEMMA_AUTODISCOVER` | `False` | Automatically discover and use the first available Ollama model if configured model is missing |
| `GEMINI_API_KEY` | `""` | Google Gemini API key when GEMMA_BACKEND=gemini |
| `GEMMA_TIMEOUT_SECONDS` | `8.0` | Timeout in seconds for an individual SLM inference call |
| `GEMMA_QUEUE_TIMEOUT_SECONDS` | `2.0` | Max time in seconds to wait in queue for an SLM concurrency slot |
| `GEMMA_CONCURRENCY_LIMIT` | `4` | Maximum concurrent SLM inference requests |
| `GEMMA_CIRCUIT_BREAKER_FAILURES` | `3` | Consecutive SLM failures before opening circuit breaker |
| `GEMMA_CIRCUIT_BREAKER_COOLDOWN_SECONDS` | `30.0` | Cooldown period in seconds before attempting SLM half-open probe |
| `GEMMA_KEEP_ALIVE` | `5m` | Ollama model keep-alive duration in memory |
| `GEMMA_TEMPERATURE` | `0.0` | Sampling temperature for SLM entity extraction |
| `GEMMA_MAX_TOKENS` | `512` | Max token budget for SLM entity extraction JSON response |
| `NON_TEXT_POLICY` | `""` | Non-text content policy (`allow` or `block`; empty string defaults by profile) |
| `MAX_BODY_BYTES` | `10485760` | Maximum incoming request body size in bytes (10MB) |
| `REQUEST_TIMEOUT_SECONDS` | `60.0` | Total upstream request timeout in seconds |
| `MAX_CONCURRENT_REQUESTS` | `50` | Maximum concurrent in-flight requests before HTTP 429 |

---

## 7. Authentication and Production Profile

### What is Enforced
- In `VAULT_PROFILE=production`: Clients must supply `Authorization: Bearer <token>` matching `VAULT_AUTH_TOKEN`. Missing or invalid tokens receive HTTP 401 Unauthorized.
- In `VAULT_PROFILE=development`: If `VAULT_AUTH_TOKEN` is configured, bearer authentication is enforced; if empty, unauthenticated requests are allowed.

### What Production Refuses to Start Without
- Refuses to start if `VAULT_AUTH_TOKEN` is missing or fewer than 24 characters (`VAULT_AUTH_TOKEN is required in production profile and must be at least 24 characters long.`).
- Refuses to start if `DEMO_MODE=true` (`DEMO_MODE=true is refused when VAULT_PROFILE=production.`).

### What Each Route Requires

| Route | Method | Production Profile Requirement | Development Profile Requirement |
| :--- | :--- | :--- | :--- |
| `/v1/chat/completions` | POST | Bearer token required | Token required if `VAULT_AUTH_TOKEN` set |
| `/v1/models` | GET | Bearer token required | Token required if `VAULT_AUTH_TOKEN` set |
| `/metrics` | GET | Bearer token required | Token required if `VAULT_AUTH_TOKEN` set |
| `/readyz` | GET | Unauthenticated returns minimal `{"status": "ready"}`; authenticated returns full readiness diagnostics | Returns full readiness diagnostics |
| `/demo/*` | ANY | Blocked (returns 404 Not Found) | Permitted if `DEMO_MODE=true` |

---

## 8. What It Detects

### Deterministic Rule Detectors

| Entity Type | Exact Matching Rule & Verification Logic |
| :--- | :--- |
| `AADHAAR` | 12-digit Indian Aadhaar number with optional spaces or hyphens, verified with the Verhoeff checksum algorithm. |
| `PAN` | 10-character Permanent Account Number. Fourth character validated for taxpayer entity type (`P`, `C`, `H`, `F`, `A`, `T`, `B`, `L`, `J`, `G`). |
| `MOBILE` | 10-digit Indian mobile number with optional prefix (`+91` or `0`). |
| `EMAIL` | A simple email pattern (`local-part@domain.tld`). |
| `IFSC` | 11-character Indian Financial System Code. |
| `UPI_ID` | Virtual Payment Address (`username@handle`) validated against 8 supported handles: `okaxis`, `oksbi`, `okhdfcbank`, `okicici`, `ybl`, `paytm`, `ibl`, `axl`. Other handles are not detected. |
| `SECRET` | AWS access key IDs (`AKIA...`), GitHub personal access tokens (`ghp_...`), GitHub fine-grained PATs (`github_pat_...`), and JSON Web Tokens (`JWT` / `eyJ...`). |

```text
Detector Pattern Details:
AADHAAR:  \b[2-9]\d{3}[-\s]?\d{4}[-\s]?\d{4}\b (Verhoeff checksum validated)
PAN:      \b[A-Z]{5}[0-9]{4}[A-Z]{1}\b (4th character: P, C, H, F, A, T, B, L, J, G)
MOBILE:   \b(?:(?:\+91|0)[-.\s]*)?[6-9]\d{9}\b
EMAIL:    \b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b
IFSC:     \b[A-Z]{4}0[A-Z0-9]{6}\b
UPI_ID:   \b[a-zA-Z0-9._-]+@(okaxis|oksbi|okhdfcbank|okicici|ybl|paytm|ibl|axl)\b
SECRET:   AKIA access keys, ghp_ tokens, github_pat_ tokens, and JWT strings
```

### Known Misses (from `python scripts/vp_review_check.py . --detectors`)

```text
Detector probes (informational):
MISSED PAN lower              []
MISSED PAN spaced             []
CAUGHT Aadhaar spaced         ['AADHAAR']
MISSED Aadhaar dotted         []
MISSED Aadhaar newline        []
MISSED Aadhaar Arabic-Indic   []
MISSED Aadhaar full-width     []
MISSED Mobile 91              []
MISSED Mobile dots            []
MISSED UPI @apl               []
MISSED UPI @ptsbi             []
MISSED sk- key                []
MISSED Google key             []
MISSED Slack                  []
MISSED Stripe                 []
MISSED Private key            []
CAUGHT DB URL                 ['EMAIL']
MISSED Card                   []
MISSED GSTIN                  []
```

### The SLM Layer
- **Status & Requirement**: Optional, requires a local Ollama instance with a model pulled (e.g. `gemma4:e2b`) or a Google Gemini API key. Defaults to `off`.
- **Input Limit**: 4 chunks of 6,000 characters with 300 characters of overlap (about 23,100 unique characters).
- **Beyond Limit**: In `STRICT_MODE=true`, requests exceeding 4 chunks fail-closed with HTTP 503. In non-strict mode (`STRICT_MODE=false`), the request marks `degraded=true` in `X-Vault-Report` and processes rules-only for the excess text.
- **Behavior on Failure**:
  - `STRICT_MODE=true`: Fails closed with HTTP 503 if the backend is unreachable, times out, or trips the circuit breaker.
  - `STRICT_MODE=false`: Falls back to rule-only detection with empty SLM spans, returning `degraded=true` and `gemma_used=false`.
- **Prompt Injection Vulnerability**: Prompt injection in user text can trick the SLM model into omitting entity spans or hallucinating, reducing its recall. Deterministic regex rules run independently and are not affected by prompt injection.
- **Measured Latency**:
  - Command: `python scripts/load_check.py --requests 200 --levels 1 5 10 20`
  - Date: October 13, 2026
  - Hardware: AMD Ryzen 7 7435HS (16 vCPUs, x86_64, Linux 6.18)
  - Rules-only proxy:
    ```text
    Running load check against http://127.0.0.1:8000/v1/chat/completions
    Requests per level: 200
    Concurrency  | Total  | 200   | 429   | 503   | p50 (ms)  | p95 (ms) 
    ----------------------------------------------------------------------
    1            | 200    | 200   | 0     | 0     | 4.87      | 6.77     
    5            | 200    | 200   | 0     | 0     | 14.90     | 19.69    
    10           | 200    | 200   | 0     | 0     | 30.49     | 40.68    
    20           | 200    | 200   | 0     | 0     | 62.05     | 126.25   
    ```
  - Local SLM: Not yet measured with a real model.

---

## 9. Security Model and Limits

### What is Protected
- Outgoing prompt values that match active regex rules or SLM entity spans are replaced with typed token strings before leaving the host.
- Upstream responses are scanned to restore tokens back to original values in memory before reaching the client application.
- Request vaults are ephemeral and scoped to individual HTTP request lifecycles.
- Client headers are restricted to an allowlist (`content-type`, `accept`, `user-agent`, `openai-organization`, `openai-project`).

### What is Not Protected
- Context remains in text: If prompt wording gives away identity or role without matching an entity detector (e.g. "the CEO of Acme Corp founded in 2020"), that context reaches the upstream model.
- Missed detections: Unrecognized formats, lower-case PANs, dotted digits, or unlisted UPI handles pass through unmasked.
- SLM can be fooled: Adversarial prompt text can suppress entity extraction in the SLM layer.
- Type conversion of numbers: Masked integer leaves become typed token strings (e.g. `"[MOBILE_1]"`). If an upstream function calling tool expects a numeric type, it receives a string.
- Non-text content: Multimodal/binary parts (images, audio) are blocked in production profile (`NON_TEXT_POLICY=block`).
- Plain HTTP transport: VaultProxy binds to `127.0.0.1:8000` over plain HTTP. Deployments exposing network interfaces require a reverse proxy with TLS (such as Caddy or Nginx).
- Vector embeddings: Embeddings computed over masked token strings differ from embeddings of original values and are not comparable across sessions.
- In-memory limits: Resource limits (`MAX_CONCURRENT_REQUESTS`) are enforced per Python process; running multiple worker processes with uvicorn shares no state.

---

## 10. Known Issues in This Release

The following issues are known in release 0.2.1 and documented honestly:
- `/readyz` can say `"ready"` when the configured SLM backend is unreachable (tracked under check B13, scheduled for next release).
- Detector coverage gaps listed in the detector probes section above (lowercase PAN, dotted Aadhaar, arbitrary UPI handles).
- Azure OpenAI and native Anthropic `/v1/messages` APIs are not supported due to different path structures and auth headers.
- Untested LLM providers and client libraries beyond OpenAI Python and curl.

---

## 11. Verification & Benchmarks

### How to Run Checks
```bash
# 1. Run unit and integration test suite
pytest -q

# 2. Run end-to-end smoke test
bash scripts/smoke.sh

# 3. Run automated production security check
bash scripts/verify_production.sh

# 4. Run regression checks (B1 to B15)
python scripts/vp_review_check.py .
```

### What Each Check Proves
- `pytest`: Tests core logic, token parsing, streaming restore, and configuration validation.
- `scripts/smoke.sh`: Proves the end-to-end proxy loop with mock upstream: validates prompt masking, header injection, and client response restoration.
- `scripts/verify_production.sh`: Proves production security constraints: token enforcement, body size limits, demo route blocking, and unauthenticated readiness hygiene.
- `scripts/vp_review_check.py`: Independent regression checks for B1–B12, B14, and B15.

### Benchmark Results (Rules Only)

Evaluated with `bench/run.py`:

- **Generated Test Dataset (N=40)**:
  - Precision: 100.00% (126 TP, 0 FP)
  - Recall: 100.00% (126 TP, 0 FN)
  - F1 Score: 100.00%
- **Held-Out Dataset v1 (N=5)**:
  - Precision: 100.00% (9 TP, 0 FP)
  - Recall: 100.00% (9 TP, 0 FN)
  - F1 Score: 100.00%
  - *Note: N=5 is too small to be considered a statistically significant evaluation result.*
- **Held-Out Challenging Dataset v2 (N=40)**:
  - Precision: 97.37% (37 TP, 1 FP on mobile number format)
  - Recall: 100.00% (37 TP, 0 FN)
  - F1 Score: 98.67%
  - *Note: Written using the same tooling as the detectors; not an independently constructed test set.*

---

## 12. Roadmap

- **Next Release Fixes**: Health check reflecting actual SLM reachability on `/readyz` (B13).
- **CLI & Diagnostics**: Standalone `vaultproxy doctor` command to check upstream connectivity and local Ollama setup.
- **Packaging**: Container images (Docker / Compose) and PyPI release.
- **Detector Expansion**: Additional Indian entity detectors (GSTIN, Driving Licence, Voter ID, lower-case PAN, dotted formatting).
- **Live Gemma Verification**: Automated test against real local Gemma model in CI.

---

## 13. Documentation Links

- [Configuration Guide](docs/CONFIG.md)
- [Changelog](CHANGELOG.md)
- [Security Policy](SECURITY.md)
- [License](LICENSE)
- [Project Documentation](docs/)
