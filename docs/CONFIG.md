# VaultProxy Configuration & Advanced Limits

## Overview & Profile Modes
VaultProxy operates under two primary environment profiles configured by `VAULT_PROFILE`:
- `development` (default): Lenient error modes and diagnostic endpoints enabled.
- `production`: Strict security defaults, production authentication, disabled demo endpoints, CORS disabled.

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
