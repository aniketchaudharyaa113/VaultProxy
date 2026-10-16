# vaultproxy (npm / npx)

Zero-dependency Node.js CLI launcher for **VaultProxy** — the local-first, OpenAI-compatible privacy proxy for LLM applications with developer & devops secret leak prevention.

## Quick Start via `npx`

No installation required:
```bash
# Start VaultProxy server
npx vaultproxy run

# Initialize configuration (.env with secure random token)
npx vaultproxy init

# Run system health diagnostics
npx vaultproxy doctor

# Scan text or .env files for secrets before sending to AI
npx vaultproxy check --file .env

# Scan directory for leaked credentials (ideal for CI/CD)
npx vaultproxy scan --fail-on-secrets
```

## Global Installation

```bash
npm install -g vaultproxy
```

After installation, run anywhere:
```bash
vaultproxy run
```

## How It Works

This lightweight Node package locates `vaultproxy` on your system. If not already present in PATH, it seamlessly invokes the tool via `uv tool`, `pipx`, or your local Python environment without manual setup.
