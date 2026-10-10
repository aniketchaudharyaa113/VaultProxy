# Changelog

All notable changes to VaultProxy will be documented in this file.

## [Unreleased]

### Corrections
- **H1**: The SLM layer calls exactly the configured model (`GEMMA_MODEL`). Auto-discovery of arbitrary models in Ollama is now opt-in via `GEMMA_AUTODISCOVER=false` (default: false). Spans carry `source="gemma"` only if the model name starts with `"gemma"` (case-insensitive); otherwise `source="slm:<model_name>"`.
- **H2**: Heuristic fallback extractor (`_heuristic_gemma_fallback`) labels its spans as `source="heuristic"`, sets `degraded=True`, sets `gemma_used=False`, and counts as an SLM failure (raising `GemmaLayerError` in strict mode). It is disabled in the production profile.
- **H5**: Invalid JSON, schema violations, or unparseable SLM outputs count as an SLM failure: raising `GemmaLayerError` (which triggers 503 fail-closed in `STRICT_MODE=true`) and continuing on rules with `degraded=True` and `gemma_used=False` in `STRICT_MODE=false`.
- **H6**: `gemma_used` in `X-Vault-Report` (and internal state) is `True` ONLY if the SLM call successfully completed and returned valid parsed output. If the SLM call failed, timed out, or had unparseable output, `gemma_used=False` and `degraded=True`.
- **H7**: `MASK_SCOPE=deep` is now the default scope across all profiles. The legacy 'messages'-only scope mode and `MASK_SCOPE` setting have been removed. Deep payload inspection with exact structural allowlisting is applied universally.
