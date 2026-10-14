#!/usr/bin/env bash
set -euo pipefail

echo "=========================================="
echo "      VaultProxy Preflight Diagnostic     "
echo "=========================================="

OVERALL_PASS=true

# 1. Check Python version
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo -n "[CHECK] Python version ($PY_VER)... "
if python3 -c "import sys; assert sys.version_info >= (3, 10)" 2>/dev/null; then
  echo "PASS"
else
  echo "FAIL (Python 3.10+ required)"
  OVERALL_PASS=false
fi

# 2. Check Port 8000 (Proxy) & 8001 (Mock Upstream) availability / status
check_port() {
  local port=$1
  local name=$2
  echo -n "[CHECK] Port $port ($name)... "
  if lsof -i:"$port" >/dev/null 2>&1 || nc -z localhost "$port" 2>/dev/null; then
    echo "IN USE / RUNNING (Fix hint: kill existing process on $port if needed)"
  else
    echo "PASS (Free)"
  fi
}

check_port 8000 "VaultProxy Server"
check_port 8001 "Mock Upstream"

# 3. Check Ollama reachability & Gemma Model status
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
GEMMA_MODEL="${GEMMA_MODEL:-gemma4:e2b}"

echo -n "[CHECK] Ollama API Reachability ($OLLAMA_URL)... "
if curl -s -m 3 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
  echo "PASS"
  
  echo -n "[CHECK] Ollama Model ($GEMMA_MODEL)... "
  if curl -s "$OLLAMA_URL/api/tags" | grep -q "$GEMMA_MODEL"; then
    echo "PASS (Model pulled)"
  else
    echo "WARN (Model '$GEMMA_MODEL' not found in Ollama. Fix hint: run 'ollama pull $GEMMA_MODEL')"
  fi
else
  echo "INFO (Ollama offline; GEMMA_BACKEND=off mode will be used)"
fi

echo "------------------------------------------"
if [ "$OVERALL_PASS" = true ]; then
  echo "Preflight Result: PASS (System ready for VaultProxy)"
else
  echo "Preflight Result: FAIL (Please fix failing items above)"
fi
