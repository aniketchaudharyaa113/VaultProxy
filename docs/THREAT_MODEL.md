# VaultProxy Threat Model

## 1. Overview
VaultProxy is a local privacy proxy designed to reduce the risk of accidental PII and secret exposure to cloud LLM providers by performing local detection, tokenization, and response restoration.

## 2. Protected Assets & Security Controls
### What IS Protected
- **Structured Indian PII**: Aadhaar numbers (with Verhoeff checksum verification), PANs, Indian mobile numbers, email addresses, IFSC codes, UPI handles.
- **Secrets & Credentials**: API keys, access tokens, high-entropy secret patterns.
- **Unstructured Names & Addresses**: Extracted by local SLM (Gemma) model layer.
- **Restoration**: SSE stream and JSON response token restoration back to client.

---

## 3. Limitations & Out of Scope Risk
### What IS NOT Protected
1. **Context & Semantic Clues ("Context Stays")**:
   - VaultProxy replaces sensitive entities with tokens (e.g. `[PAN_1]`), but surrounding context, domain terminology, and narrative structure remain in the prompt sent upstream.
2. **Missed Detections**:
   - Obfuscated, misspelled, or novel PII formats not matching deterministic rules or SLM patterns will not be masked.
3. **Prompt Injection**:
   - VaultProxy does not filter prompt injection attacks. Malicious user prompts designed to manipulate cloud LLM output logic are passed through (masked).
4. **Compromised Host**:
   - VaultProxy relies on the local system's security boundaries. If the host machine running VaultProxy is compromised, the in-memory token vault can be inspected.
5. **Provider-Side Logging of Masked Text**:
   - The upstream cloud LLM provider still receives and logs the masked prompt containing token placeholders and unmasked background text.
6. **Proxy Outage on Strict Fail-Closed**:
   - In `STRICT_MODE=true`, any SLM layer failure, queue timeout, or unhandled exception halts request execution and returns HTTP 503, intentionally choosing availability loss over privacy risk.
