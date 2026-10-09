# VaultProxy 🛡️🇮🇳

A local-first, privacy-preserving proxy for LLM applications focused on Indian data entities (Aadhaar, PAN, Indian Mobile, UPI IDs, IFSC, Emails, API Secrets).

VaultProxy intercepts OpenAI-compatible requests, detects sensitive values across all message contents, replaces them with typed tokens (e.g. `[PAN_1]`), forwards the masked payload to upstream LLMs, and restores the real values in incoming responses (including streamed SSE chunks).

> ⚠️ **Notice**: VaultProxy is a risk-reduction tool. No privacy tool is 100% safe. Always verify compliance for your specific deployment.

---

## ASCII Architecture Overview

```
 +------------------+                +-------------------+                +---------------------+
 |  LLM Client App  | ---(Prompt)--->|    VaultProxy     | ---(Masked)--->|  Upstream OpenAI/  |
 |  (OpenAI SDK)    |                |  (Local Port 8000)|                |    Cloud Backend    |
 |                  | <--(Restored)--|                   | <--(Stream)----|  (Port 8001/Cloud)  |
 +------------------+                +-------------------+                +---------------------+
                                               |
                                  +--------------------------+
                                  | In-Memory Request Vault  |
                                  | (Value <-> Typed Tokens) |
                                  +--------------------------+
```

---

## Quick Start (1-Minute Integration)

Change **one line** in your OpenAI client configuration to point `base_url` to VaultProxy:

```python
from openai import OpenAI

# Instead of https://api.openai.com/v1, point to local VaultProxy
client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="your-api-key"
)

response = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "My Aadhaar is 367598341203 and PAN is ABCPB1234F"}]
)

print(response.choices[0].message.content)
# Output: "My Aadhaar is 367598341203 and PAN is ABCPB1234F" (Cloud only saw [AADHAAR_1] & [PAN_1])
```

---

## Benchmark Results (`bench/RESULTS.md`)

Evaluation on 40 seeded test samples covering clean texts, Hinglish chat, formal emails, secrets in logs, and tricky negatives:

| Entity Type | Precision | Recall | F1 Score | TP | FP | FN |
|---|---|---|---|---|---|---|
| AADHAAR | 100.00% | 100.00% | 100.00% | 19 | 0 | 0 |
| EMAIL | 100.00% | 100.00% | 100.00% | 21 | 0 | 0 |
| IFSC | 100.00% | 100.00% | 100.00% | 18 | 0 | 0 |
| MOBILE | 100.00% | 34.78% | 51.61% | 8 | 0 | 15 |
| PAN | 100.00% | 100.00% | 100.00% | 23 | 0 | 0 |
| SECRET | 100.00% | 100.00% | 100.00% | 4 | 0 | 0 |
| UPI_ID | 100.00% | 100.00% | 100.00% | 18 | 0 | 0 |
| **OVERALL** | **100.00%** | **88.10%** | **93.67%** | **111** | **0** | **15** |

---

## How VaultProxy Differs From Existing Tools

| Feature | Microsoft Presidio | LLM Guard | Gateway Guardrails | **VaultProxy** |
|---|---|---|---|---|
| **Primary Focus** | General PII (US/EU) | Content moderation & safety | API rate limits / routing | **Indian PII & Local Privacy** |
| **Aadhaar Verhoeff Checksum** | ❌ No native checksum | ❌ No | ❌ No | **✅ Built-in Verhoeff checksum** |
| **Indian Mobile / UPI / IFSC** | ❌ Limited / None | ❌ None | ❌ None | **✅ Native detectors** |
| **Streaming Token Restoration** | ❌ No SSE stream state | ❌ Non-streaming focus | ❌ Pass-through only | **✅ 24-char partial SSE token buffer** |
| **Zero Database Footprint** | Requires storage setup | In-memory / DB | DB / Redis required | **✅ Strictly in-memory per request** |

---

## Limitations (What VaultProxy Cannot Do)

1. **Non-Text Modalities**: VaultProxy redacts text parts only. It does not perform image OCR or audio transcription redaction.
2. **Ambiguous Context Names**: Rule-based detectors target deterministic patterns (Aadhaar checksum, PAN, UPI handles, IFSC). Ambiguous names without explicit patterns require the optional Gemma layer (`GEMMA_BACKEND=ollama` or `gemini`).
3. **Modified LLM Output Tokens**: If an upstream model alters a token (e.g. changes `[PAN_1]` to `[pan 1]`), restoration is performed case-insensitively, but heavily mangled tokens will not match.
4. **Embeddings & Token IDs**: When using `/v1/embeddings`, VaultProxy adds the `X-Vault-Warning` header indicating that embeddings of masked text are not comparable across requests. Integer token ID lists cannot be inspected and return HTTP 400 in production mode.


---

## How to Add a Detector

To add a new rule-based entity detector:

1. Create `vaultproxy/detectors/your_entity.py`:
   ```python
   import re
   from typing import List
   from vaultproxy.detectors import Span

   YOUR_REGEX = re.compile(r"\b[A-Z]{3}\d{3}\b")

   def detect_your_entity(text: str) -> List[Span]:
       spans = []
       for match in YOUR_REGEX.finditer(text):
           spans.append(Span(start=match.start(), end=match.end(), type="YOUR_TYPE", source="rule"))
       return spans
   ```
2. Register it in `vaultproxy/detectors/registry.py`:
   ```python
   from vaultproxy.detectors.your_entity import detect_your_entity

   def run_rule_detectors(text: str) -> List[Span]:
       # ...
       spans.extend(detect_your_entity(text))
       return spans
   ```
3. Add unit tests in `tests/test_detectors.py`.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
