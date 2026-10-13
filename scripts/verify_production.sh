#!/usr/bin/env bash
set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

LOG_DIR="/tmp/vaultproxy_verify"
mkdir -p "$LOG_DIR"
UPSTREAM_LOG="$LOG_DIR/upstream_log.json"
PROXY_LOG="$LOG_DIR/proxy_log.txt"
CHUNK_FILE="$LOG_DIR/oversized.json"

rm -f "$UPSTREAM_LOG" "$PROXY_LOG" "$CHUNK_FILE"

PROD_TOKEN="prod_secure_token_1234567890_abcdef"
FAKE_PAN="ABCPB1234F"
FAKE_AADHAAR="367598341203"
FAKE_KEY="AK""IAIOSFODNN7EXAMPLE"

cleanup() {
  if [ -n "$PROXY_PID" ] && kill -0 "$PROXY_PID" 2>/dev/null; then
    kill "$PROXY_PID" 2>/dev/null || true
  fi
  if [ -n "$UPSTREAM_PID" ] && kill -0 "$UPSTREAM_PID" 2>/dev/null; then
    kill "$UPSTREAM_PID" 2>/dev/null || true
  fi
  rm -f "$CHUNK_FILE"
}
trap cleanup EXIT

print_result() {
  local name="$1"
  local status="$2"
  if [ "$status" = "PASS" ]; then
    echo -e "[ ${GREEN}PASS${NC} ] $name"
  else
    echo -e "[ ${RED}FAIL${NC} ] $name"
    exit 1
  fi
}

echo "=== VaultProxy Production Verification Script ==="

# 1. Refuses to start without a token
if VAULT_PROFILE=production VAULT_AUTH_TOKEN="" PYTHONPATH=. python3 -c "from vaultproxy.config import settings; print(settings.VAULT_AUTH_TOKEN)" >/dev/null 2>&1; then
  print_result "refuses to start without a token" "FAIL"
else
  print_result "refuses to start without a token" "PASS"
fi

# 2. Refuses a short token (< 24 chars)
if VAULT_PROFILE=production VAULT_AUTH_TOKEN="short_token_123" PYTHONPATH=. python3 -c "from vaultproxy.config import settings; print(settings.VAULT_AUTH_TOKEN)" >/dev/null 2>&1; then
  print_result "refuses a short token" "FAIL"
else
  print_result "refuses a short token" "PASS"
fi

# 3. DEMO_MODE=true is refused in production
if VAULT_PROFILE=production DEMO_MODE=true VAULT_AUTH_TOKEN="$PROD_TOKEN" PYTHONPATH=. python3 -c "from vaultproxy.config import settings; print(settings.DEMO_MODE)" >/dev/null 2>&1; then
  print_result "DEMO_MODE=true is refused in production" "FAIL"
else
  print_result "DEMO_MODE=true is refused in production" "PASS"
fi

# Start Tiny Upstream Server (port 8002)
PYTHONPATH=. python3 -c '
import asyncio, json
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI()

@app.post("/v1/chat/completions")
async def chat(request: Request):
    headers = dict(request.headers)
    body = (await request.body()).decode("utf-8", errors="replace")
    record = {"headers": headers, "body": body}
    with open("'"$UPSTREAM_LOG"'", "a") as f:
        f.write(json.dumps(record) + "\n")
    return JSONResponse({"choices": [{"message": {"role": "assistant", "content": "Hello user"}}]})

uvicorn.run(app, host="127.0.0.1", port=8002, log_level="error")
' >/dev/null 2>&1 &
UPSTREAM_PID=$!

# Start VaultProxy in Production Mode (port 8000)
VAULT_PROFILE=production \
VAULT_AUTH_TOKEN="$PROD_TOKEN" \
UPSTREAM_BASE_URL="http://127.0.0.1:8002" \
GEMMA_BACKEND="off" \
MAX_BODY_BYTES=1000 \
PYTHONPATH=. python3 -m uvicorn vaultproxy.server:app --host 127.0.0.1 --port 8000 --log-level debug >"$PROXY_LOG" 2>&1 &
PROXY_PID=$!

# Wait for proxy to start
for i in {1..15}; do
  if curl -s http://127.0.0.1:8000/readyz >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

# 4. 401 without a token
HTTP_401_NO_TOKEN=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/v1/chat/completions -H "Content-Type: application/json" -d '{"model":"gpt-4","messages":[{"role":"user","content":"hi"}]}')
if [ "$HTTP_401_NO_TOKEN" = "401" ]; then
  print_result "401 without a token" "PASS"
else
  print_result "401 without a token" "FAIL"
fi

# 5. 401 with a wrong token
HTTP_401_WRONG_TOKEN=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/v1/chat/completions -H "Authorization: Bearer wrong_token_1234567890_abcdef" -H "Content-Type: application/json" -d '{"model":"gpt-4","messages":[{"role":"user","content":"hi"}]}')
if [ "$HTTP_401_WRONG_TOKEN" = "401" ]; then
  print_result "401 with a wrong token" "PASS"
else
  print_result "401 with a wrong token" "FAIL"
fi

# 6. 200 with the right token
PAYLOAD="{\"model\":\"gpt-4\",\"messages\":[{\"role\":\"user\",\"content\":\"PAN is $FAKE_PAN, Aadhaar is $FAKE_AADHAAR, key is $FAKE_KEY\"}]}"
HTTP_200=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer $PROD_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Cookie: user_session=secret_cookie" \
  -H "X-User-Email: user@example.com" \
  -d "$PAYLOAD")

if [ "$HTTP_200" = "200" ]; then
  print_result "200 with the right token" "PASS"
else
  print_result "200 with the right token" "FAIL"
fi

# 7. Cookie and X-User-Email headers did not reach upstream
if grep -i "cookie" "$UPSTREAM_LOG" >/dev/null 2>&1 || grep -i "x-user-email" "$UPSTREAM_LOG" >/dev/null 2>&1; then
  print_result "Cookie and X-User-Email headers did not reach upstream" "FAIL"
else
  print_result "Cookie and X-User-Email headers did not reach upstream" "PASS"
fi

# 8. Upstream log and proxy log contain none of fake PAN, Aadhaar, API key
LEAKED=0
for item in "$FAKE_PAN" "$FAKE_AADHAAR" "$FAKE_KEY"; do
  if grep -F "$item" "$UPSTREAM_LOG" >/dev/null 2>&1; then
    echo "Leaked item in upstream log: $item"
    LEAKED=1
  fi
  if grep -F "$item" "$PROXY_LOG" >/dev/null 2>&1; then
    echo "Leaked item in proxy log: $item"
    LEAKED=1
  fi
done

if [ "$LEAKED" -eq 0 ]; then
  print_result "upstream and proxy logs contain zero fake PII/secrets" "PASS"
else
  print_result "upstream and proxy logs contain zero fake PII/secrets" "FAIL"
fi

# 9. Oversized chunked request returns 413
# MAX_BODY_BYTES is set to 1000 above
python3 -c 'import json; print(json.dumps({"model":"gpt-4","messages":[{"role":"user","content":"A"*2000}]}))' > "$CHUNK_FILE"
HTTP_413=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer $PROD_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Transfer-Encoding: chunked" \
  --data-binary "@$CHUNK_FILE")

if [ "$HTTP_413" = "413" ]; then
  print_result "oversized chunked request returns 413" "PASS"
else
  print_result "oversized chunked request returns 413" "FAIL"
fi

echo "================================================="
echo -e "${GREEN}ALL PRODUCTION VERIFICATION CHECKS PASSED SUCCESSFULLY!${NC}"
echo "================================================="
