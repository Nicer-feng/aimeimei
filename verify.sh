#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$PROJECT_ROOT/scripts/check_release_version.py"

PASS="$(tr -d '\r\n' < /opt/ai-platform/family_password.txt)"
ADMIN="$(tr -d '\r\n' < /opt/ai-platform/admin.key)"
COOKIE="/tmp/ai-platform-cookie.txt"
CAPTCHA_JSON="/tmp/ai-platform-captcha.json"

rm -f "$COOKIE" /tmp/ai-platform-login.json /tmp/ai-platform-models.json \
  /tmp/ai-platform-conversation.json /tmp/ai-platform-stream.sse "$CAPTCHA_JSON"

echo "[health]"
curl -sS http://127.0.0.1:8080/api/health
echo

echo "[login]"
PYTHONPATH="$PROJECT_ROOT" python3 - <<'PY2' > "$CAPTCHA_JSON"
import json
from ai_platform.handlers.auth import captcha_answer_hash
from ai_platform.handlers.shared import b64_token, db, now

captcha_id = b64_token(18)
answer = "ABCD"
ts = now()
with db() as conn:
    conn.execute(
        "INSERT INTO login_captchas(id, answer_hash, created_at, expires_at, attempts) VALUES (?, ?, ?, ?, 0)",
        (captcha_id, captcha_answer_hash(captcha_id, answer), ts, ts + 300),
    )
print(json.dumps({"captcha_id": captcha_id, "captcha": answer}))
PY2
CAPTCHA_ID="$(python3 - <<'PY2'
import json
print(json.load(open("/tmp/ai-platform-captcha.json"))["captcha_id"])
PY2
)"
CAPTCHA="$(python3 - <<'PY2'
import json
print(json.load(open("/tmp/ai-platform-captcha.json"))["captcha"])
PY2
)"
LOGIN_BODY="$(PASS="$PASS" CAPTCHA_ID="$CAPTCHA_ID" CAPTCHA="$CAPTCHA" python3 - <<'PY2'
import json
import os
print(json.dumps({
    "username": "admin",
    "password": os.environ["PASS"],
    "captcha_id": os.environ["CAPTCHA_ID"],
    "captcha": os.environ["CAPTCHA"],
}, ensure_ascii=False))
PY2
)"
curl -sS -c "$COOKIE"   -H "Content-Type: application/json"   -d "$LOGIN_BODY"   http://127.0.0.1:8080/api/login
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
