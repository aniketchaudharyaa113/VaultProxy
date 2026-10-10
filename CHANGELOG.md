# Changelog

All notable changes to VaultProxy will be documented in this file.

## [0.2.0] - 2026-10-10

### Added & Improved
- **Universal Deep Masking**: Deep payload inspection is applied across all nested JSON prompt elements (messages, tool calls, tool schemas, system prompts, metadata) with strict structural key allowlisting (`metadata.id`, `metadata.type`, tool schema names, argument keys).
- **Production Profile & Security Enforcement**: Added `VAULT_PROFILE=production` mode. Refuses to start without a strong `VAULT_AUTH_TOKEN` (minimum 24 characters) or if `DEMO_MODE=true`. Disables the interactive demo console route.
- **Bearer Token Authentication**: Enforced Bearer token authentication on `/v1/chat/completions`, `/v1/models`, and `/metrics` in production. Unauthenticated `/readyz` returns minimal status `{"status": "ready"}`.
- **Safe Built-in Resource Limits**:
  - `MAX_BODY_BYTES` (default 10MB) enforced while reading request body streams (supports chunked transfer encoding without Content-Length).
  - `REQUEST_TIMEOUT_SECONDS` (30s) connect/read/write timeout for upstream client calls.
  - `MAX_CONCURRENT_REQUESTS` (100) concurrency semaphore for incoming HTTP requests.
  - `GEMMA_CONCURRENCY_LIMIT` (4 slots) and `GEMMA_QUEUE_TIMEOUT_SECONDS` (2.0s) for local SLM calls.
- **Strict Mode & Fail-Closed Guarantee**: In `STRICT_MODE=true`, unexpected masking errors, Gemma queue timeouts, circuit breaker open states, or Gemma failures fail-closed immediately with HTTP 503 and forward nothing upstream. In `STRICT_MODE=false`, degrades to rule-only masking and sets `x-vault-report: {"degraded": true, ...}` header.
- **Log Privacy & Header Hygiene**: Structured JSON logging contains zero PII, secrets, or raw prompt values even at DEBUG log level. Upstream request headers are strictly allowlisted; `Cookie`, `X-User-Email`, `X-Forwarded-For`, and response `Set-Cookie` are dropped.
- **Metrics & Observability**: `/metrics` endpoint exports Prometheus metrics (`vaultproxy_requests_total`, `vaultproxy_request_duration_seconds`, `vaultproxy_masked_entities_total`, `vaultproxy_degraded_requests_total`, `vaultproxy_circuit_breaker_state`). Metric labels contain zero request payload values.
- **Comprehensive Test Suite & Verification**: Expanded test suite to 150 passing unit/integration tests with 86% overall code coverage (100% on `vaultproxy/metrics.py` and `vaultproxy/vault.py`). Added `scripts/verify_production.sh` for automated production security verification.

### Known Limitations
- **SLM Input Size Limit**: Max 24,000 characters total across 4 overlapping chunks (6,000 chars/chunk x 300 overlap). Inputs exceeding 24,000 characters fail-closed with HTTP 503 in `STRICT_MODE`, or mark `degraded=true` in non-STRICT mode.
- **Plain HTTP Binding**: Binds to `127.0.0.1:8000` over plain HTTP. Remote deployments require a TLS-terminating reverse proxy (Nginx, Caddy).
- **Concurrency & Overload Behavior**: Measured capacity with mock SLM is 2.0 req/s (`GEMMA_CONCURRENCY_LIMIT=4` slots at 2.0s delay). Overload triggers HTTP 503 in strict mode or rule-only fallback with `degraded=true` in non-strict mode.
- **Text-Only Scope**: Operates on text fields only. Non-text parts are blocked or ignored per `NON_TEXT_POLICY`. Prompt masking alters text strings, which modifies embedding vectors if used for RAG indexing.

## [0.1.0] - 2026-10-09

### Initial Core Release
- Initial local-first OpenAI-compatible privacy proxy.
- Deterministic rule detectors for Indian PAN, Aadhaar, Mobile, Email, IFSC, UPI, Indic script, and Generic Secrets.
- Optional Gemma SLM layer integration via Ollama.
- Streaming SSE response restoration with split-token protection.
