# Changelog

All notable changes to VaultProxy will be documented in this file.

## [0.2.1] - 2026-10-13

### Fixed & Hardened (Phase 1a & 1b Blockers)
- **B1 (Gzip Compression)**: Client correctly receives and decodes gzip-compressed upstream responses with sensitive tokens restored.
- **B2 (Stream Lifecycle & Client Isolation)**: Completed SSE streams no longer close the shared proxy HTTP client, ensuring concurrent in-flight streams are uninterrupted.
- **B3 (Base URL Routing)**: Upstream routing supports bare host (`http://host:port`), `/v1` suffix, and custom prefixes.
- **B4 (Stream Concurrency Accounting)**: Concurrency slot held across the full lifecycle of SSE response streaming before release, enforcing `MAX_CONCURRENT_REQUESTS`.
- **B5 (Dev Token Enforcement)**: Bearer authentication enforced in development profile whenever `VAULT_AUTH_TOKEN` is configured.
- **B6 (Non-Text Part Filtering)**: Distinguishes metadata/property keys named `'file'` from true binary parts, eliminating false-positive 400 rejections in production.
- **B7 (Error Format & Request ID)**: Client errors return standard OpenAI-compatible error objects with an `x-request-id` HTTP header.
- **B8 (Conditional System Instruction)**: Placeholder preservation instruction (`Keep all token placeholders...`) is injected only when vault contains masked tokens; merged into existing system messages without changing message count.
- **B9 (Integer Leaves & Dictionary Keys)**: Full-match PII scanning extended to integer values and dictionary keys inside messages and tool calls; top-level request parameters and `logit_bias` preserved.
- **B10 (Greedy Priority Span Merging)**: Overlapping entity spans merged using greedy interval priority scheduling without dropping valid non-overlapping spans.
- **B11 (Request Memory Hygiene)**: Retained request payload inspection disabled in production profile (`DEMO_MODE=false`).
- **B12 (Secret Scrubbing)**: Gemini API key removed from all logged URLs and debug logging.
- **B14 (Honesty Fix)**: Removed `_heuristic_gemma_fallback` and all hardcoded person names. Default `GEMMA_BACKEND` set to `"off"`.
- **B15 (Startup Error Diagnostic)**: Production misconfigurations print a clean readable error to stderr and exit without tracebacks.

### Corrections
- Removed `_heuristic_gemma_fallback` and hardcoded person names (`Rajesh Sharma`, `Vikram`, `Ramesh Kumar`, `Aarav`, `Priya Patel`, `Aniket Chaudhary`).
- Removed `"auto"` backend option. `GEMMA_BACKEND` accepts only `off`, `ollama`, or `gemini`, defaulting to `"off"`.
- Configured unknown backend values to print a readable configuration error listing allowed values without Python tracebacks.
- Startup log now explicitly announces `"Protection: rules only"` or `"Protection: rules + <model>"`.
- Tests updated because they froze old heuristic/auto behaviour:
  - `tests/test_phase5_security.py::test_heuristic_fallback_disabled_in_production`
  - `tests/test_gemma_characterization.py::test_gemma_fallback_path_honest_behaviour`
  - `tests/test_merge_and_layer_correctness.py`

### Known Issues
- `/readyz` endpoint can report `"ready"` when the configured SLM backend is offline (B13, scheduled for next release).
- Detector coverage gaps: lowercase PAN, spaced PAN, dotted Aadhaar, unlisted UPI handles, and non-prefixed secret formats.
- Azure OpenAI and native Anthropic `/v1/messages` endpoints are unsupported.
- Untested third-party LLM providers and client libraries beyond OpenAI Python and curl.

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
