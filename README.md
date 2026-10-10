# VaultProxy

> **Early pre-release (0.x). Not independently security-reviewed. Test with non-sensitive data first.**

VaultProxy is a local-first, OpenAI-compatible privacy proxy designed for LLM applications handling sensitive Indian personal data and API credentials.
It sits transparently between your application and cloud LLM providers (such as OpenAI, Anthropic, or Azure OpenAI), intercepting outgoing prompt payloads, tokenizing sensitive entities (PAN, Aadhaar, phone numbers, emails, secrets, person names, addresses), and restoring the original sensitive values in real-time streaming or non-streaming responses.

---

## Table of Contents
- [Quickstart (3 Steps)](#quickstart-3-steps)
- [Architecture & How It Works](#architecture--how-it-works)
- [Detection Capabilities](#detection-capabilities)
- [Configuration Reference](#configuration-reference)
- [Production Hardening & Security Profile](#production-hardening--security-profile)
- [Observability & Metrics](#observability--metrics)
- [Known Limitations & Threat Model](#known-limitations--threat-model)
- [Benchmark Results](#benchmark-results)
- [Comparison](#comparison)
- [Development Demo Console](#development-demo-console)
- [License & Security Policy](#license--security-policy)

---

## Quickstart (3 Steps)

### 1. Install VaultProxy
```bash
pip install vaultproxy
```
*(For local development editable install: `pip install -e .`)*

### 2. Run VaultProxy Server
```bash
export VAULT_AUTH_TOKEN="your_secure_auth_token_here_at_least_24_chars"
vaultproxy
```
VaultProxy starts listening at `http://127.0.0.1:8000`.

### 3. Update Client `base_url`
VaultProxy is drop-in compatible with standard OpenAI SDKs and frameworks (LangChain, LlamaIndex, LiteLLM):

#### Python OpenAI Client
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="your_secure_auth_token_here_at_least_24_chars",
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {
            "role": "user",
            "content": "My name is Rajesh Sharma, PAN is ABCPB1234F and Aadhaar is 3675 9834 1203.",
        }
    ],
)
print(response.choices[0].message.content)
```

#### cURL
```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer your_secure_auth_token_here_at_least_24_chars" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "My phone is 9876543210 and email is user@example.in"}]
  }'
```

---

## Architecture & How It Works

```
                     +-----------------------------------+
                     |       Client Application          |
                     |  (OpenAI SDK / LangChain / cURL)  |
                     +-----------------+-----------------+
                                       | Request (Raw Prompt)
                                       v
                     +-----------------+-----------------+
                     |            VaultProxy             |
                     |                                   |
                     |  1. Bearer Token Auth Check       |
                     |  2. Universal Deep Payload Mask   |
                     |     - Rule Detectors (Layer 1)    |
                     |     - Local Gemma SLM (Layer 2)   |
                     |  3. In-Memory Vault Store        |
                     +-----------------+-----------------+
                                       | Masked Prompt ([PAN_1], [PERSON_1])
                                       v
                     +-----------------+-----------------+
                     |       Cloud LLM Provider          |
                     |     (OpenAI / Azure / etc.)       |
                     +-----------------+-----------------+
                                       | Response Stream
                                       v
                     +-----------------+-----------------+
                     |            VaultProxy             |
                     |  4. Token Buffer Stream Restorer  |
                     |     (Un-masks [PAN_1] -> real val)|
                     +-----------------+-----------------+
                                       | Restored Response
                                       v
                     +-----------------+-----------------+
                     |       Client Application          |
                     +-----------------------------------+
```

### Request Lifecycle
1. **Authentication & Authorization**: In production mode, VaultProxy validates the client Bearer token before performing any body parsing or detector execution.
2. **Layer 1 Rule Detectors**: High-speed regex and algorithmic validators scan for structured Indian identifiers (PAN, Aadhaar, Phone, Email, IFSC, UPI, API keys).
3. **Layer 2 Local SLM Detector**: If enabled (`GEMMA_BACKEND=ollama` or `auto`), VaultProxy calls a local Ollama SLM (Gemma 2B) to extract unstructured PERSON names and ADDRESS entities.
4. **Span Merging & Deduplication**: Overlapping spans from rule detectors and SLM layers are merged. Deterministic rule spans take precedence over SLM spans to eliminate false overlaps.
5. **Universal Deep Masking**: Sensitive strings inside nested JSON fields (messages, tool call arguments, tool descriptions, system prompts, metadata) are replaced with typed tokens (`[PAN_1]`, `[AADHAAR_1]`, `[PERSON_1]`). Structural keys (`metadata.id`, `metadata.type`, tool schema names) are allowlisted and preserved.
6. **In-Memory Vault**: Token-to-value mappings are stored in an ephemeral, per-request memory vault. Mappings are isolated to the single HTTP request lifecycle and never written to disk or database.
7. **Response Stream Restoration**: As the cloud LLM streams SSE responses back, VaultProxy buffers token boundaries to ensure split tokens (e.g. `[PAN_` in chunk 1 and `1]` in chunk 2) are seamlessly reassembled and swapped back to original sensitive values before reaching the client.

---

## Detection Capabilities

### Built-in Deterministic Rule Detectors (Layer 1)
- **Indian PAN (Permanent Account Number)**: 10-character alphanumeric strings (`[A-Z]{5}[0-9]{4}[A-Z]{1}`) with check character validation.
- **Aadhaar Numbers**: 12-digit Indian national identity numbers verified using the Verhoeff checksum algorithm. Supports spaced (`XXXX XXXX XXXX`) and hyphenated formats.
- **Mobile Numbers**: 10-digit Indian mobile numbers with optional `+91`, `91`, or leading `0` prefixes.
- **Email Addresses**: Standard email addresses (`user@domain.tld`).
- **IFSC Codes**: 11-character Indian Financial System Codes (`[A-Z]{4}0[A-Z0-9]{6}`).
- **UPI Handles**: Virtual Payment Addresses (`username@bank`).
- **Indic Script & Spans**: Indic language characters and name word patterns.
- **Generic Secrets**: High-entropy API credentials including AWS Access Keys (`AKIA...`), GitHub Personal Access Tokens (`ghp_...`, `github_pat_...`), and JWT tokens (`eyJ...`).

### Optional Local SLM Detector (Layer 2)
When configured with `GEMMA_BACKEND=ollama` or `auto`, VaultProxy calls a local Gemma model to extract:
- **PERSON**: Unstructured human names (e.g., "Rajesh Sharma", "Priya Patel").
- **ADDRESS**: Street addresses, locality names, and physical location coordinates.

### What VaultProxy Does NOT Detect
- **Non-Text Content**: VaultProxy operates exclusively on text fields. Requests containing binary non-text objects (`image_url`, `input_audio`, `file`) are blocked or passed with warnings according to `NON_TEXT_POLICY`.
- **Custom Obfuscated Formats**: Misspelled, non-standard, or deliberately obfuscated values not matching rule algorithms or SLM prompts will not be masked.
- **Embeddings Vectors**: Prompt text is masked before sending to endpoints. If text is forwarded to `/v1/embeddings` or stored in a vector database, masked token placeholders will alter resulting embedding representations.

---

## Configuration Reference

VaultProxy is configured using environment variables or a `.env` file. Zero configuration files are required to start.

| Setting | Type | Default | Description |
| --- | --- | --- | --- |
| `VAULT_PROFILE` | `str` | `"development"` | Profile mode: `"development"` (lenient defaults, demo console enabled) or `"production"` (strict security, authentication enforced, console disabled). |
| `VAULT_AUTH_TOKEN` | `str` | `""` | Bearer token required for client authentication in production profile (minimum 24 characters). |
| `UPSTREAM_BASE_URL` | `str` | `"https://api.openai.com"` | Target upstream LLM provider API base URL. |
| `UPSTREAM_API_KEY` | `str` | `""` | Upstream provider API key forwarded in `Authorization: Bearer <key>` header. |
| `STRICT_MODE` | `bool` | `false` | Fail-closed toggle. When `true`, any masking exception or SLM failure returns HTTP 503 fail-closed with 0 upstream forwarding. |
| `GEMMA_BACKEND` | `str` | `"auto"` | SLM backend mode: `"off"` (rules only), `"ollama"` (local Ollama server), or `"auto"` (auto-detect with rule fallback). |
| `OLLAMA_URL` | `str` | `"http://127.0.0.1:11434"` | Local Ollama server endpoint. |
| `GEMMA_MODEL` | `str` | `"gemma2:2b"` | Target SLM model name in Ollama. |
| `GEMMA_CONCURRENCY_LIMIT` | `int` | `4` | Maximum parallel local SLM inference requests. |
| `GEMMA_QUEUE_TIMEOUT_SECONDS` | `float` | `2.0` | Maximum queue wait time for an available SLM concurrency slot before timing out. |
| `MAX_BODY_BYTES` | `int` | `10485760` | Maximum allowed request body size in bytes (10MB). Enforced incrementally during body stream reading. |
| `REQUEST_TIMEOUT_SECONDS` | `float` | `30.0` | Upstream HTTP client timeout for connect, read, write, and pool operations. |
| `MAX_CONCURRENT_REQUESTS` | `int` | `100` | Maximum total concurrent incoming HTTP requests allowed by proxy server. |
| `NON_TEXT_POLICY` | `str` | `"warn"` | Policy for requests containing non-text objects: `"warn"` (forward with warning header) or `"block"` (return HTTP 400). |
| `DEMO_MODE` | `bool` | `false` | Enables `/demo/console` UI. Refused in `production` profile. |

---

## Production Hardening & Security Profile

When running in `VAULT_PROFILE=production`, VaultProxy enforces strict security controls:

1. **Mandatory Token Authentication**: Startup fails immediately if `VAULT_AUTH_TOKEN` is missing or under 24 characters. All calls to `/v1/*` and `/metrics` require `Authorization: Bearer <token>`.
2. **Demo Endpoint Refusal**: `DEMO_MODE=true` is strictly prohibited and causes immediate startup failure. The interactive console route `/demo/console` is unmounted.
3. **Header Sanitization**: Incoming client request headers are strictly allowlisted (`Content-Type`, `Accept`, `User-Agent`, `OpenAI-Organization`, `OpenAI-Project`, `OpenAI-Beta`). Sensitive client headers (`Cookie`, `X-User-Email`, `X-Forwarded-For`) are stripped before forwarding upstream. Upstream `Set-Cookie` headers are stripped from client responses.
4. **Log Privacy**: Structured JSON logs contain zero raw prompt text, sensitive PII values, or secret credentials at all log levels (`DEBUG`, `INFO`, `ERROR`).
5. **Fail-Closed Architecture**: In `STRICT_MODE=true`, any unexpected internal masking exception, JSON parse error, SLM queue timeout, or circuit breaker open state halts execution and returns **HTTP 503 Service Unavailable** (`VaultProxy fail-closed`). Zero unmasked data ever reaches upstream servers.

---

## Observability & Metrics

VaultProxy provides comprehensive metrics and diagnostic reporting:

### Prometheus Endpoint (`/metrics`)
Requires Bearer authentication in production mode. Exports standard Prometheus metrics:
- `vaultproxy_requests_total`: Counter of total processed HTTP requests.
- `vaultproxy_request_duration_seconds`: Histogram of request processing latency.
- `vaultproxy_masked_entities_total`: Counter of total masked entities.
- `vaultproxy_degraded_requests_total`: Counter of requests processed in degraded mode.
- `vaultproxy_circuit_breaker_state`: Gauge of SLM circuit breaker state (`0=CLOSED`, `1=HALF_OPEN`, `2=OPEN`).

*Label Privacy Design:* Zero metric labels contain raw prompt text or request values.

### `X-Vault-Report` Header
Every response from VaultProxy includes a JSON metadata header detailing masking execution:
```http
X-Vault-Report: {"masked": {"PAN": 1, "AADHAAR": 1, "PERSON": 1}, "degraded": false, "gemma_used": true, "slm_chunks": 1}
```

---

## Known Limitations & Threat Model

### Limitations & Measured Numbers
- **SLM Input Capacity Limit**: The local SLM detector inspects inputs up to **24,000 characters** total across 4 overlapping chunks (6,000 chars/chunk with 300-char overlap). Prompts exceeding 24,000 characters fail-closed with HTTP 503 in `STRICT_MODE`, or mark `degraded=true` in non-STRICT mode.
- **Transport Security**: VaultProxy speaks plain HTTP and binds to `127.0.0.1:8000`. For remote or multi-host deployments, VaultProxy **must** run behind a TLS-terminating reverse proxy (Nginx, Caddy, HAProxy) with HTTPS.
- **SLM Throughput & Overload**: Measured capacity with a mock SLM is **2.0 requests per second** (`GEMMA_CONCURRENCY_LIMIT=4` slots at 2.0s SLM delay). Under heavy load (e.g. 10 or 20 concurrent requests):
  - In `STRICT_MODE=true`: Queued requests exceeding the queue timeout (2.0s) fail-closed with HTTP 503.
  - In `STRICT_MODE=false`: Queued requests fall back to rule-only masking and return HTTP 200 OK with `degraded=true`.
- **Narrative Context Retention**: VaultProxy tokenizes identified entities (e.g., `[PAN_1]`), but narrative structure, surrounding business text, and domain context remain in the prompt sent to the cloud provider.
- **Rule Misses**: Algorithmic rule detectors rely on standard regexes and checksums. Misspelled, non-standard, or novel entity formats can be missed without the SLM layer.

---

## Benchmark Results

Evaluated using `bench/run.py` in rule-detector evaluation mode:

### Generated Test Dataset (40 Samples)
| Entity Type | Precision | Recall | F1 Score | TP | FP | FN |
|---|---|---|---|---|---|---|
| AADHAAR | 100.00% | 100.00% | 100.00% | 23 | 0 | 0 |
| EMAIL | 100.00% | 100.00% | 100.00% | 25 | 0 | 0 |
| IFSC | 100.00% | 100.00% | 100.00% | 21 | 0 | 0 |
| MOBILE | 100.00% | 100.00% | 100.00% | 16 | 0 | 0 |
| PAN | 100.00% | 100.00% | 100.00% | 16 | 0 | 0 |
| SECRET | 100.00% | 100.00% | 100.00% | 4 | 0 | 0 |
| UPI_ID | 100.00% | 100.00% | 100.00% | 21 | 0 | 0 |
| **OVERALL** | **100.00%** | **100.00%** | **100.00%** | **126** | **0** | **0** |

*Mean Latency:* 0.03 ms per request.

### Held-Out Evaluation Dataset (5 Samples)
| Entity Type | Precision | Recall | F1 Score | TP | FP | FN |
|---|---|---|---|---|---|---|
| AADHAAR | 50.00% | 50.00% | 50.00% | 1 | 1 | 1 |
| EMAIL | 100.00% | 100.00% | 100.00% | 1 | 0 | 0 |
| IFSC | 100.00% | 100.00% | 100.00% | 1 | 0 | 0 |
| MOBILE | 100.00% | 100.00% | 100.00% | 1 | 0 | 0 |
| PAN | 50.00% | 50.00% | 50.00% | 1 | 1 | 1 |
| SECRET | 100.00% | 100.00% | 100.00% | 1 | 0 | 0 |
| UPI_ID | 100.00% | 100.00% | 100.00% | 1 | 0 | 0 |
| **OVERALL** | **77.78%** | **77.78%** | **77.78%** | **7** | **2** | **2** |

---

## Comparison
Similar tools exist, for example Presidio and LLM Guard. We have not benchmarked against them.

---

## Development Demo Console

VaultProxy includes an interactive web console at `/demo/console` for testing masking and restoration visually during development. It is available ONLY in `VAULT_PROFILE=development` mode with `DEMO_MODE=true` and is automatically disabled in production.

---

## License & Security Policy

### License
VaultProxy is open-source software released under the [MIT License](LICENSE). Copyright (c) 2026 Aniket Chaudhary.

### Security Vulnerability Reporting
If you discover a security vulnerability or potential privacy leak in VaultProxy, please report it privately via GitHub Private Vulnerability Reporting under the repository **Security** tab. Please do not open public issues for security vulnerabilities.
