# Hardening Plan

### A. Goal
Make VaultProxy safe to run in production AND very simple to use. Simplicity is a hard requirement.

### B. Simplicity rules
S1 A new user gets a working protected proxy in 3 steps: install, run, change base_url. No config file required.
S2 Convention over configuration. The total number of NEW settings in the whole hardening effort is at most 8; 3 are used so far (VAULT_PROFILE, MASK_SCOPE, NON_TEXT_POLICY), so at most 5 more. Each new setting needs a one-line justification. Existing settings keep names and defaults.
S3 No new abstractions: no plugin systems, store interfaces, dependency injection or user-supplied regex engine.
S4 No new runtime dependencies unless essential; optional features go in extras.
S5 Errors say what happened, why and how to fix it. No stack traces to clients, and never input text in an error.
S6 Delete before you add. Report net lines per phase and justify any phase over 400 added lines.
S7 Two profiles only: development (current behaviour) and production (refuses unsafe configuration).
If a requirement would make the tool harder to use, STOP and ask me a short question.

### C. Core contract (must stay true)
C1 Typed tokens [TYPE_N]; the same value gets the same token within a request; the vault is per-request, in memory only, never persisted.
C2 Fail closed: an unexpected masking error returns 503 and forwards nothing; STRICT_MODE plus an SLM failure returns 503.
C3 X-Vault-Report keeps its fields (additive changes only; counts only, never values).
C4 Streaming restore never leaks partial tokens (split-at-every-position tests keep passing).
C5 Everything works with GEMMA_BACKEND=off and offline.
C6 Existing env var names and development-profile defaults are unchanged.
C7 Existing tests pass, except tests that froze a "KNOWN LEAK" and are deliberately updated (list each by name).

### D. Honesty rules
Docs, UI and README must be true and measured. Never write "guarantees", "zero-trust", "100% safe", "ensures compliance"; say it reduces risk. Compliance notes: supports safeguards, not legal advice. Compare with other tools only using facts verified from their official docs in this session. Never print or log raw prompts, replies, detected values or secrets. Fake data only. Never push to a remote.

### E. Report format (end of every phase)
(1) What a user can now do, in 3 lines. (2) Commands for me to try it, including real proxy runs, not only filtered pytest. (3) Tests and the real coverage table (run pytest --cov=vaultproxy --cov-report=term-missing without disabling addopts). (4) Regression report: golden tests unchanged yes/no, and each deliberately changed test with a reason. (5) Net lines of code, and any new settings with justification. (6) Risks. Then update docs/PROGRESS.md, commit, and STOP and wait for "next".

### F. Remaining plan (Phase order: 2.6 -> 5 -> 3 -> 6 -> 4 -> 7 -> 9 -> 8)
PHASE 2.5 (done): fix and prove Phase 2.
PHASE 2.6 (done): prove Phase 2.5 (SLM chunking, H7 universal deep scope, clean vault.py, 125 tests, 83% total coverage).
PHASE 5 Production safety basics (doing now): VAULT_AUTH_TOKEN, safe built-in limits, JSON request logging (never content), /healthz and /readyz, authenticated /metrics, CORS off, security tests, SECURITY.md, docs/THREAT_MODEL.md.
PHASE 3 Easy to use: CLI "vaultproxy" with run, init, doctor, check, version. Startup banner, library API, production profile validation checks.
PHASE 6 Packaging and deployment: pyproject console entry point, Dockerfile, docker-compose.yml, systemd unit, Kubernetes examples.
PHASE 4 Better detection, kept small: card (Luhn), GSTIN, voter ID, passport, vehicle reg, IPv4/IPv6, database URLs, private keys, secrets. VAULT_LISTS_DIR allow/deny lists. Benchmark updates.
PHASE 7 Documentation: README quickstarts, HOW_IT_WORKS.md, CONFIG.md, PRODUCTION.md, DETECTORS.md, TROUBLESHOOTING.md, CONTRIBUTING.md.
PHASE 9 Final check: console offline verification, scripts/live_gemma_check.sh, doctor, load test, claims re-audit, v1.0.0-rc1 tag.
PHASE 8 CI and release: GitHub Actions workflows, pip-audit, Dependabot, PyPI/GHCR release workflow.

### G. Not now (do not build)
Signed receipts, audit hash chain, policy YAML, reply scan, Postgres or Mongo stores, Helm, OpenTelemetry, per-token rate limits, user-supplied regex detectors, native provider adapters, image redaction, a docs-site generator.

### H. Real-use gates
The project is now intended for real-world use with real personal data and credentials. Security, fail-closed safety, and technical honesty outrank demo polish or decorative UI features. Hackathon-only and demo-only items (e.g. unauthenticated demo console endpoints, fake source badges, hardcoded fallbacks) are removed or strictly gated behind explicit development flags.
