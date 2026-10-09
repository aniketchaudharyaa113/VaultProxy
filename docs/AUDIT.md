# VaultProxy Initial Security & Implementation Audit

| Audit Item | Claim / Expectation | Code / Empirical Evidence | Verdict |
| :--- | :--- | :--- | :--- |
| **Model Really Used** | Calls exact configured `GEMMA_MODEL` (e.g. `gemma4:e2b`). | `gemma_layer.py` auto-picks the first available model in Ollama if configured model tag is missing. Spans are labeled `source="gemma"` regardless of actual model. | **FALSE** |
| **Fallback Behaviour** | SLM layer handles entity extraction with local Gemma model. | When Ollama API is down and `backend == "auto"`, `_heuristic_gemma_fallback` runs regexes, labels spans `source="gemma"`, and sets `degraded=False`. | **FALSE** |
| **Benchmark Consistency** | 100% precision & recall overall. | `bench/run.py` results show 100% on 40 generated samples, but 77.78% F1 score on 5 held-out samples (50% on Aadhaar and PAN). | **PARTLY** |
| **What is Masked** | Masks sensitive values in incoming requests. | Only string content in `messages[].content` is masked. Tool calls, function arguments, non-text inputs, and other JSON leaves are not masked. | **PARTLY** |
| **What Can Leak** | Only masked tokens sent upstream. | PII inside unmasked JSON fields (e.g., tool calls, legacy function call args, non-text attachments) or missed regex matches pass directly upstream. | **TRUE** |
| **Default Bind Address** | Secure local proxy binding. | `server.py` line 271 binds to `0.0.0.0:8000`, exposing proxy to all external network interfaces. | **FALSE** |
| **Authentication** | Secure privacy proxy access. | No API key verification or authentication layer exists for proxy endpoints or `/demo` routes. | **FALSE** |
| **Logging of Raw Data** | Raw PII is never logged or stored. | Raw input text is not written to app logs, but `LAST_MASKED_REQUEST` stores request bodies in memory when `DEMO_MODE=True`. | **PARTLY** |
| **Offline Console Use** | Console works offline. | `demo/console/index.html` loads external CDN scripts (`unpkg.com/react`, `unpkg.com/babel-standalone`, `cdn.tailwindcss.com`). | **FALSE** |
| **Verhoeff Math Claim** | Uses D8 dihedral group for Aadhaar checksum. | Verhoeff algorithm uses the dihedral group $D_5$ (order 10). $D_8$ would be order 16. | **FALSE** |

## Audit Summary & Action Items for Subsequent Phases
- **Phase 1**: Enforce explicit `GEMMA_MODEL` calling without auto-discovering arbitrary models; label fallback spans as `source="heuristic"`; set `degraded=True` on fallback.
- **Phase 2**: Expand mask scope to deep-walk all string leaves (`MASK_SCOPE=deep`); handle non-text policies (`NON_TEXT_POLICY`); add endpoint control.
- **Phase 3**: Upgrade rule detectors (card, GSTIN, voter ID, passport, secrets, Unicode decimal normalization).
- **Phase 4**: Add production profile (`VAULT_PROFILE=production`), default bind address `127.0.0.1`, constant-time authentication (`VAULT_AUTH_TOKENS`), request size & rate limits.
- **Phase 8**: Vendor static assets locally in console for full offline usage.
