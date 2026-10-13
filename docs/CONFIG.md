# VaultProxy Configuration & Advanced Limits

## Overview & Profile Modes
VaultProxy operates under two primary environment profiles configured by `VAULT_PROFILE`:
- `development` (default): Lenient error modes and diagnostic endpoints enabled.
- `production`: Strict security defaults, production authentication, disabled demo endpoints, CORS disabled.

## SLM Backend Configuration
The SLM layer is controlled by `GEMMA_BACKEND`:
- `off` (default): Only deterministic rule detectors run. Zero external calls or model overhead.
- `ollama`: Uses a local Ollama instance at `OLLAMA_URL` with `GEMMA_MODEL`.
- `gemini`: Uses Google Gemini API with `GEMINI_API_KEY`.
Any unsupported or unknown backend value produces a clear error listing the allowed values without tracebacks.

## Advanced Limits & SLM Chunking

### Maximum Input Size
- **SLM Chunk Size (`SLM_CHUNK_CHARS`)**: 6,000 characters per chunk.
- **Chunk Overlap (`SLM_OVERLAP_CHARS`)**: 300 characters between adjacent chunks.
- **Maximum SLM Chunks (`SLM_MAX_CHUNKS`)**: 4 chunks.
- **Maximum SLM Inspected Input Size**: 24,000 characters per request (4 chunks × 6,000 characters).

### Behavior Beyond Limits
When a request payload contains text exceeding the maximum input size (24,000 characters or requiring more than 4 chunks):
1. **In `STRICT_MODE=true`**:
   The proxy fails closed immediately with an HTTP **503 Service Unavailable** error (`GemmaLayerError`). Uninspected text is never forwarded upstream.
2. **In `STRICT_MODE=false`**:
   The proxy falls back to degraded mode (`degraded=true` in `X-Vault-Report`). Rule-based regex detectors continue scanning the full text, but SLM inspection is truncated after the 4th chunk.

## Integer Leaves & Dictionary Key Masking

Inside messages, tool-call arguments, and metadata, integer leaves and dictionary keys are inspected for sensitive identifiers (e.g. 10-digit mobile numbers or 12-digit Aadhaar numbers):
- **Whole-Match Rule**: An integer or dictionary key is only masked when a detector matches the entire value from beginning to end.
- **Type Conversion**: A masked integer leaf becomes a typed token string (e.g. `9876543210` becomes `"[MOBILE_1]"`).
- **Excluded Fields**: Booleans, floating-point numbers, top-level model request parameters (`seed`, `max_tokens`, `max_completion_tokens`, `n`, `temperature`, `top_p`, `presence_penalty`, `frequency_penalty`, `logprobs`, `top_logprobs`), and keys under `logit_bias` are never modified.
