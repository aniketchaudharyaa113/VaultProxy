#!/usr/bin/env bash
set -euo pipefail

echo "=========================================="
echo "    Starting VaultProxy Judge Console     "
echo "=========================================="

# 1. Run preflight diagnostic
./scripts/preflight.sh

echo ""
echo "Launching background processes..."

# 2. Kill any existing instances on port 8000/8001 if needed
fuser -k 8000/tcp 2>/dev/null || true
fuser -k 8001/tcp 2>/dev/null || true
sleep 1

# 3. Start mock upstream (port 8001)
python3 -m uvicorn demo.mock_upstream:app --port 8001 > /tmp/mock_upstream.log 2>&1 &
MOCK_PID=$!

# 4. Start VaultProxy server (port 8000) in DEMO_MODE=true
DEMO_MODE=true python3 -m uvicorn vaultproxy.server:app --port 8000 > /tmp/proxy.log 2>&1 &
PROXY_PID=$!

sleep 2

echo "=========================================="
echo "  VaultProxy Judge Console is LIVE! 🚀    "
echo "  Console URL: http://localhost:8000/demo  "
echo "=========================================="
