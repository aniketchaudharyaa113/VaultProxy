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

## I. Plan after 0.2.0

### A. Git and publishing rules (new, strict)
- Work on one local branch per phase, named phase-<id>-<topic>. Commit freely on local branches.
- You may run git push ONLY if my latest message contains the line "PUSH <branch>" for that exact branch. You may merge into main ONLY if my latest message contains "MERGE <branch>". You may create a tag or release ONLY if my latest message contains "TAG <name>".
- Never force-push, never delete a branch (local or remote), never rewrite history, never change repository visibility or settings, never publish a package or image.
- Before any approved push, run a secret scan over the commits being pushed and show the raw output.
- If unsure whether something publishes or deletes, ask me first.

### B. Standing rules (all earlier rules still apply)
The simplicity rules (S1 to S7), the core contract (C1 to C7), the honesty rules and report format E in sections B to E of this file remain in force. Additions:
- Total NEW settings from here on: at most 2 (VAULT_LISTS_DIR is planned; one spare). Justify each in one line. CLI flags are not settings.
- Any phase touching masking, restore, auth, limits or the SLM layer must include a mutation spot-check: apply 3 deliberate bugs one at a time, paste the exact failing test name and assertion for each, then revert.
- Every report must contain: an evidence table (item, status, test or command that proves it), a "What I could not verify" list, and a list of every place a result differs from earlier claims. No vague words such as "all passing" without numbers.
- No unmeasured claims, no "guarantee", "zero-trust", "100% safe", "ensures compliance". Compare with other tools only using facts verified from their official docs in this session. Fake data only. Never print or log raw prompts, replies, detected values or secrets.
- I may be a beginner at reading diffs: explain every non-trivial change in plain English.

### C. Phases, in this order. Details come from section F of this file unless stated here.
PHASE 5.3 Post-publish fixes (no new features):
 1. README quickstart must truly work for a stranger. Follow ONLY the README in a fresh virtual environment. State which upstream is required and how to set UPSTREAM_BASE_URL and UPSTREAM_API_KEY. Give two paths: (a) try it with the bundled mock upstream, with commands and output proving the upstream received tokens like [PAN_1] while the client got the real value; (b) use a real OpenAI-compatible API. Paste the transcript including the upstream log. Remove any step that works only because of a hidden default.
 2. Held-out benchmark: show the git history and diff of bench/heldout.jsonl and explain why it shrank and changed. List every false negative and false positive with the exact text, the expected span, what the detector returned and WHY, especially the AADHAAR and PAN failures. Fix the DETECTOR when the format is legitimate; never edit data to improve results. Extend to at least 40 hand-style messages in bench/heldout_v2.jsonl (spaces, hyphens, line breaks, punctuation, Indic digits, Hinglish, and tricky negatives such as order IDs, product codes, version numbers, phone-like numbers), all fake. Report sample sizes next to every percentage in the README, with generated and held-out results separate.
 3. LICENSE and pyproject: use the COPYRIGHT HOLDER and AUTHOR NAME I gave at the top. If any is empty, use the placeholder "[COPYRIGHT HOLDER]" or "[AUTHOR NAME]" and ask me. Never infer names from git config.
 4. Run a real secret scan over the full history (gitleaks if installed, otherwise git grep over every commit for common key formats). Paste raw output. List every author name and email in the history.
 5. Explain every change the cleanup commit made to vaultproxy/server.py. Remove agent-specific entries from .gitignore. List tracked files that should not be public (caches, logs, build output, local settings), and say whether uv.lock is used.
PHASE 3a Refactor, zero behaviour change: split vaultproxy/server.py (over 600 lines) into small modules (for example routes, proxying, auth and limits, streaming) with no logic changes. All golden and e2e tests must pass unchanged. Report line counts before and after.
PHASE 3b Easy to use: as in section F, Phase 3. Use the standard library (argparse) for the CLI, no new dependency. Commands: run, init, doctor, check, version. "doctor" must also (i) time a tiny SLM call, (ii) print the SLM concurrency limit, the queue timeout and the estimated maximum SLM throughput (slots divided by measured latency), and (iii) warn in plain English that in strict mode requests beyond that throughput are refused, naming what to change. The production refusal check prints ALL problems at once with fixes. Docs: Essentials (UPSTREAM_BASE_URL, UPSTREAM_API_KEY, VAULT_AUTH_TOKEN, STRICT_MODE, GEMMA_BACKEND, GEMMA_MODEL) and Advanced.
PHASE 6 Packaging and deployment: as in section F, Phase 6. Verify pip install in a clean environment and the Docker image end to end (non-root, healthcheck). docker-compose with proxy and Ollama. A systemd unit, ONE Kubernetes example, and reverse-proxy examples (Caddy and nginx) with response buffering off for SSE and TLS termination.
PHASE 4 Better detection: as in section F, Phase 4, including everything the held-out analysis in Phase 5.3 revealed. Verify identifier format rules against authoritative sources; mark anything unverifiable as heuristic. Add allow and deny lists through VAULT_LISTS_DIR.
PHASE 7 Documentation: as in section F, Phase 7, plus docs/PILOT_GUIDE.md (how to trial it safely on non-sensitive data, how to read the "check" output and missed items, what to measure), docs/OPERATIONS.md (rotate the upstream key and the auth token, upgrade and rollback, what to do when the SLM is down or slow, what to monitor) and docs/PRODUCTION.md (one-page checklist). The comparison with other tools is allowed only with verified facts.
PHASE 9 Final check: as in section F, Phase 9, plus a 30-minute soak test (memory stays flat), chaos tests (upstream slow, upstream dropping mid-stream, SLM down and slow), a load test against real Ollama with the configured Gemma model, and capacity guidance: given the measured SLM latency and my TYPICAL PROMPT SIZE, propose limits (SLM concurrency, queue timeout, chunk limits) as options with numbers and trade-offs for strict and non-strict mode. Do NOT change limits until I choose.
PHASE 8 CI and release: as in section F, Phase 8. Create workflows but make release and publish workflows manual-trigger only and clearly marked; never run them.
PHASE 10 Real-use gates report: write docs/dev/REAL_USE_GATES.md with each gate from section H of this file marked done, not done, or "needs a human", with evidence. Include the gates only a human can do: independent attack attempt, privacy and legal review, trial on low-risk real data with manual review of missed items, and a rollback plan.

### D. End of every phase
Report in format E plus the evidence table and "What I could not verify". Update docs/dev/PROGRESS.md, commit on the phase branch, and STOP and wait for my message. Do not start the next phase until I type "next".
