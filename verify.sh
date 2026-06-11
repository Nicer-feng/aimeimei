#!/usr/bin/env bash
set -euo pipefail

PASS="$(tr -d '\r\n' < /opt/ai-platform/family_password.txt)"
ADMIN="$(tr -d '\r\n' < /opt/ai-platform/admin.key)"
COOKIE="/tmp/ai-platform-cookie.txt"

rm -f "$COOKIE" /tmp/ai-platform-login.json /tmp/ai-platform-models.json \
  /tmp/ai-platform-conversation.json /tmp/ai-platform-stream.sse

echo "[health]"
curl -sS http://127.0.0.1:8080/api/health
echo

echo "[login]"
curl -sS -c "$COOKIE" \
  -H "Content-Type: application/json" \
  -d "{\"password\":\"$PASS\"}" \
  http://127.0.0.1:8080/api/login
echo

echo "[models]"
curl -sS -b "$COOKIE" http://127.0.0.1:8080/api/models \
  > /tmp/ai-platform-models.json
python3 -m json.tool /tmp/ai-platform-models.json

MODEL="$(
  python3 - <<'PY'
import json
data = json.load(open("/tmp/ai-platform-models.json"))
models = data.get("models") or []
print(models[0]["id"] if models else "")
PY
)"
if [[ -z "$MODEL" ]]; then
  echo "no model found" >&2
  exit 1
fi

echo "[create-conversation]"
curl -sS -b "$COOKIE" \
  -H "Content-Type: application/json" \
  -d "{\"model_id\":\"$MODEL\"}" \
  http://127.0.0.1:8080/api/conversations \
  > /tmp/ai-platform-conversation.json
python3 -m json.tool /tmp/ai-platform-conversation.json

CID="$(
  python3 - <<'PY'
import json
data = json.load(open("/tmp/ai-platform-conversation.json"))
print(data["conversation"]["id"])
PY
)"

echo "[messages-before]"
curl -sS -b "$COOKIE" \
  "http://127.0.0.1:8080/api/conversations/$CID/messages" \
  | python3 -m json.tool

echo "[chat-stream-first-lines]"
curl -sS -N -b "$COOKIE" \
  -H "Content-Type: application/json" \
  -d '{"content":"请用一句中文回复：平台联通测试"}' \
  "http://127.0.0.1:8080/api/conversations/$CID/messages" \
  > /tmp/ai-platform-stream.sse
sed -n '1,8p' /tmp/ai-platform-stream.sse

echo "[messages-after]"
curl -sS -b "$COOKIE" \
  "http://127.0.0.1:8080/api/conversations/$CID/messages" \
  | python3 -m json.tool

echo "[admin-model-count]"
curl -sS -H "X-Admin-Key: $ADMIN" \
  http://127.0.0.1:8080/api/admin/models \
  | python3 - <<'PY'
import json, sys
data = json.load(sys.stdin)
print(len(data.get("models") or []))
PY
