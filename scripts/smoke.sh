#!/usr/bin/env bash
set -euo pipefail

echo "=== VaultProxy Smoke Test ==="

cleanup() {
  echo "Cleaning up processes..."
  if [ -n "${MOCK_PID:-}" ]; then kill "$MOCK_PID" 2>/dev/null || true; fi
  if [ -n "${PROXY_PID:-}" ]; then kill "$PROXY_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT

# 1. Start mock upstream on port 8001
GEMMA_BACKEND=off python3 -m uvicorn demo.mock_upstream:app --port 8001 > /tmp/mock_upstream.log 2>&1 &
MOCK_PID=$!

# 2. Start proxy server on port 8000
GEMMA_BACKEND=off DEMO_MODE=true python3 -m uvicorn vaultproxy.server:app --port 8000 > /tmp/proxy.log 2>&1 &
PROXY_PID=$!

echo "Waiting for servers to start..."
sleep 3

# 3. Send test payload containing valid fake Aadhaar (367598341203) and PAN (ABCPB1234F)
PAYLOAD='{
  "model": "gpt-4",
  "messages": [
    {
      "role": "user",
      "content": "My Aadhaar is 367598341203 and PAN is ABCPB1234F."
    }
  ],
  "stream": false
}'

echo "Sending request through proxy..."
RESPONSE_HEADERS=$(mktemp)
RESPONSE_BODY=$(curl -s -D "$RESPONSE_HEADERS" -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")

echo "Response Body: $RESPONSE_BODY"

# 4. Assert X-Vault-Report header exists
if ! grep -qi "x-vault-report" "$RESPONSE_HEADERS"; then
  echo "FAIL: X-Vault-Report header missing in response!"
  exit 1
fi
echo "PASS: X-Vault-Report header present."

# 5. Assert client got raw values restored in reply
if ! echo "$RESPONSE_BODY" | grep -q "367598341203"; then
  echo "FAIL: Client response missing restored Aadhaar number!"
  exit 1
fi
if ! echo "$RESPONSE_BODY" | grep -q "ABCPB1234F"; then
  echo "FAIL: Client response missing restored PAN number!"
  exit 1
fi
echo "PASS: Client response received restored values."

# 6. Check what the cloud/upstream saw via GET /demo/last
LAST_REQ=$(curl -s http://localhost:8000/demo/last)
echo "Upstream Request Seen: $LAST_REQ"

if echo "$LAST_REQ" | grep -q "367598341203"; then
  echo "FAIL: Raw Aadhaar was leaked to upstream!"
  exit 1
fi
if echo "$LAST_REQ" | grep -q "ABCPB1234F"; then
  echo "FAIL: Raw PAN was leaked to upstream!"
  exit 1
fi
if ! echo "$LAST_REQ" | grep -q "\[AADHAAR_1\]"; then
  echo "FAIL: Upstream request missing [AADHAAR_1] token!"
  exit 1
fi
if ! echo "$LAST_REQ" | grep -q "\[PAN_1\]"; then
  echo "FAIL: Upstream request missing [PAN_1] token!"
  exit 1
fi

echo "PASS: Upstream received tokens only, zero raw PII leaked."
echo "=== Smoke Test PASSED Successfully! ==="
rm -f "$RESPONSE_HEADERS"
