# VaultProxy

> **Early pre-release (0.x). Not independently security-reviewed. Test with non-sensitive data first.**

VaultProxy is a local-first, OpenAI-compatible privacy proxy for LLM applications focused on Indian data.
It intercepts outgoing API requests, masks sensitive PII and secret credentials with typed placeholders,
and automatically restores the original sensitive values in streaming or non-streaming replies.
By performing deterministic rule masking and optional local SLM detection before prompts leave your network,
it significantly reduces data exposure risks while preserving full API contract compatibility with cloud LLM SDKs.

---

## Quickstart (3 Steps)

### 1. Install
```bash
pip install vaultproxy
```
*(Or install locally: `pip install -e .`)*

### 2. Run
```bash
export VAULT_AUTH_TOKEN="your_secure_auth_token_here_at_least_24_chars"
vaultproxy
```
VaultProxy starts an OpenAI-compatible proxy server at `http://127.0.0.1:8000`.

### 3. Change `base_url` in your OpenAI client
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="your_secure_auth_token_here_at_least_24_chars",
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "user", "content": "My PAN is ABCPB1234F and Aadhaar is 3675 9834 1203."}
    ],
)
print(response.choices[0].message.content)
```

---

## What VaultProxy Detects Today

### Built-in Deterministic Rule Detectors
- **Indian PAN Cards**: Validated via format regex and check character.
- **Aadhaar Numbers**: 12-digit Indian national ID validated via the Verhoeff checksum algorithm.
- **Mobile Numbers**: 10-digit Indian phone numbers with optional `+91` or leading `0`.
- **Email Addresses**: Standard email addresses.
- **IFSC Codes**: 11-character Indian Financial System Codes.
- **UPI IDs**: Virtual Payment Addresses (`username@bank`).
- **Indic Script & Spans**: Indic language characters and name patterns.
- **Generic Secrets**: AWS Access Keys (`AKIA...`), GitHub Personal Access Tokens (`ghp_...`, `github_pat_...`), and JWTs (`eyJ...`).

### Optional Local SLM Detector
When enabled (`GEMMA_BACKEND=ollama` or `auto`), VaultProxy calls a local SLM (such as Gemma 2B via Ollama) to extract:
- **PERSON**: Human names.
- **ADDRESS**: Physical street and postal addresses.

### What VaultProxy Does NOT Detect
- **No Images or Audio**: VaultProxy operates on text content only. Requests containing non-text parts (e.g. `image_url`, `input_audio`) are either blocked or passed uninspected depending on `NON_TEXT_POLICY`.
- **Embeddings Caveat**: Masking modifies prompt text before forwarding. If text is sent to `/v1/embeddings` or used for RAG/vector indexing, masked text strings will alter generated embedding vectors.
- **Non-Standard Tokens**: Rule-based detectors use specific regexes and checksums; non-standard or misspelled entity formats may be missed without the SLM layer.

---

## Known Limitations & Measured Capacities

- **SLM Input Size Limit**: The SLM detector processes inputs up to **24,000 characters** total across 4 overlapping chunks (6,000 chars/chunk with 300-char overlap). Inputs exceeding 24,000 characters fail-closed with HTTP 503 in `STRICT_MODE`, or mark `degraded=true` in non-STRICT mode.
- **Plain HTTP Binding**: By default, VaultProxy binds to `127.0.0.1:8000` over plain HTTP. For remote network deployment, run VaultProxy behind a TLS-terminating reverse proxy (such as Nginx or Caddy) with HTTPS enabled.
- **Concurrency & Overload Behavior**: Measured capacity using a mock SLM is **2.0 requests per second** (`GEMMA_CONCURRENCY_LIMIT=4` slots with 2.0s SLM delay). When incoming request concurrency exceeds this capacity:
  - In `STRICT_MODE=true`: Queued requests exceeding the queue timeout (2.0s) fail-closed immediately with **HTTP 503 Service Unavailable**.
  - In `STRICT_MODE=false`: Queued requests exceeding timeout fall back to rule-only masking and return HTTP 200 OK with header `x-vault-report: {"degraded": true, ...}`.
- **Detector Accuracy**: Rule detectors can miss non-standard or misspelled values.

---

## Benchmark Results

Benchmark measured using `bench/run.py` in rule-detector evaluation mode:

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

## Development Console
VaultProxy includes a web-based interactive demo console at `/demo/console` for local testing. It is intended solely as a development convenience and is automatically disabled when running in the `production` profile (`VAULT_PROFILE=production`).

---

## License
VaultProxy is released under the [MIT License](LICENSE).
