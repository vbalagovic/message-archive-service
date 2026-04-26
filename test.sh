#!/usr/bin/env bash
# Smoke-test the message archive API end-to-end.
# Usage:
#   make up            # start the stack
#   bash test.sh       # run this
set -u

KEY="${API_KEY:-dev-key-change-me}"
BASE="${BASE:-http://localhost:8000}"
H_AUTH="X-API-Key: $KEY"
H_JSON="Content-Type: application/json"

uuid() { uuidgen | tr 'A-Z' 'a-z'; }

hr() { printf '\n=== %s ===\n' "$1"; }

# --------------------------------------------------------------------------
hr "0. health & docs"
curl -s "$BASE/healthz" | jq
curl -s "$BASE/readyz"  | jq
echo "Swagger:  $BASE/docs"

# --------------------------------------------------------------------------
CHAT=$(uuid); M1=$(uuid); M2=$(uuid)
# Each run uses a unique sent_at (current UTC, second precision) so repeated
# runs do NOT collide on the timestamp and the sort order is stable & visible.
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
LATER=$(date -u -v+5S +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '+5 seconds' +%Y-%m-%dT%H:%M:%SZ)
echo "CHAT=$CHAT  M1=$M1  M2=$M2  NOW=$NOW  LATER=$LATER"

# --------------------------------------------------------------------------
hr "1. PUT user message (expect 201)"
USER_BODY=$(jq -n \
  --arg id "$M1" --arg chat "$CHAT" --arg sent "$NOW" \
  '{message_id:$id, chat_id:$chat, content:"Explain CAP theorem in one paragraph.",
    rating:null, sent_at:$sent, role:"user"}')
curl -s -o /dev/null -w "HTTP %{http_code}\n" \
  -X PUT "$BASE/api/v1/messages/$M1" -H "$H_AUTH" -H "$H_JSON" -d "$USER_BODY"

# --------------------------------------------------------------------------
hr "2. PUT AI message with markdown content (expect 201)"
# Multiline markdown including a python code block; jq does the JSON escaping.
read -r -d '' MD <<'MARKDOWN' || true
## CAP theorem

In a distributed system you can guarantee at most **two** of:

- Consistency
- Availability
- Partition tolerance

    # python pseudo-code
    assert kept == {C, A, P} - {dropped}
MARKDOWN

AI_BODY=$(jq -n \
  --arg id "$M2" --arg chat "$CHAT" --arg content "$MD" --arg sent "$LATER" \
  '{message_id:$id, chat_id:$chat, content:$content,
    rating:null, sent_at:$sent, role:"ai"}')
curl -s -X PUT "$BASE/api/v1/messages/$M2" -H "$H_AUTH" -H "$H_JSON" -d "$AI_BODY" | jq

# --------------------------------------------------------------------------
hr "3. PATCH rating to true (expect 200)"
curl -s -X PATCH "$BASE/api/v1/messages/$M2" -H "$H_AUTH" -H "$H_JSON" \
  -d '{"rating": true}' | jq '{rating, updated_at}'

hr "4. PATCH rating back to null (expect 200)"
curl -s -X PATCH "$BASE/api/v1/messages/$M2" -H "$H_AUTH" -H "$H_JSON" \
  -d '{"rating": null}' | jq '{rating}'

hr "5. PATCH content (expect 200)"
curl -s -X PATCH "$BASE/api/v1/messages/$M2" -H "$H_AUTH" -H "$H_JSON" \
  -d '{"content": "_(edited)_ CAP: pick two."}' | jq '{content, updated_at}'

# --------------------------------------------------------------------------
hr "6. Idempotent PUT replay (same id, expect 200 not 201)"
curl -s -o /dev/null -w "HTTP %{http_code}\n" \
  -X PUT "$BASE/api/v1/messages/$M1" -H "$H_AUTH" -H "$H_JSON" -d "$USER_BODY"

# --------------------------------------------------------------------------
hr "7a. GET list — sort key visible (sent_at + id)"
curl -s "$BASE/api/v1/messages?limit=10" -H "$H_AUTH" \
  | jq '{count: (.items|length), next_cursor,
         items: [.items[] | {sent_at, role, message_id, content: (.content[0:60])}]}'

hr "7b. GET list — full payload of one row (all 8 fields)"
curl -s "$BASE/api/v1/messages?limit=1" -H "$H_AUTH" | jq '.items[0]'

hr "8. GET filtered by chat_id and role=ai"
curl -s -G "$BASE/api/v1/messages" -H "$H_AUTH" \
  --data-urlencode "chat_id=$CHAT" --data-urlencode "role=ai" \
  | jq '{count: (.items|length)}'

hr "9. GET time-window filter"
curl -s -G "$BASE/api/v1/messages" -H "$H_AUTH" \
  --data-urlencode "since=2026-04-26T00:00:00Z" \
  --data-urlencode "until=2026-04-26T23:59:59Z" \
  | jq '{count: (.items|length)}'

hr "10. Cursor pagination (limit=1)"
PAGE1=$(curl -s "$BASE/api/v1/messages?limit=1" -H "$H_AUTH")
echo "$PAGE1" | jq '{count:(.items|length), next_cursor}'
NEXT=$(echo "$PAGE1" | jq -r '.next_cursor // empty')
if [ -n "$NEXT" ]; then
  curl -s -G "$BASE/api/v1/messages" -H "$H_AUTH" \
    --data-urlencode "limit=1" --data-urlencode "cursor=$NEXT" \
    | jq '{count:(.items|length), next_cursor}'
fi

# --------------------------------------------------------------------------
hr "11. Failure modes"
echo -n "401 missing key:    "; curl -s -o /dev/null -w "HTTP %{http_code}\n" "$BASE/api/v1/messages"
echo -n "401 wrong key:      "; curl -s -o /dev/null -w "HTTP %{http_code}\n" -H "X-API-Key: nope" "$BASE/api/v1/messages"
echo -n "404 patch unknown:  "; curl -s -o /dev/null -w "HTTP %{http_code}\n" -X PATCH "$BASE/api/v1/messages/$(uuid)" -H "$H_AUTH" -H "$H_JSON" -d '{"rating": true}'

WRONG=$(uuid)
MISMATCH=$(jq -n --arg id "$M1" --arg chat "$CHAT" --arg sent "$NOW" \
  '{message_id:$id, chat_id:$chat, content:"x", rating:null, sent_at:$sent, role:"user"}')
echo -n "422 id mismatch:    "; curl -s -o /dev/null -w "HTTP %{http_code}\n" -X PUT "$BASE/api/v1/messages/$WRONG" -H "$H_AUTH" -H "$H_JSON" -d "$MISMATCH"

echo -n "422 unknown field:  "; curl -s -o /dev/null -w "HTTP %{http_code}\n" -X PATCH "$BASE/api/v1/messages/$M2" -H "$H_AUTH" -H "$H_JSON" -d '{"role": "ai"}'

BIG=$(printf 'x%.0s' $(seq 1 40000))
TOOBIG=$(jq -n --arg id "$(uuid)" --arg chat "$CHAT" --arg content "$BIG" --arg sent "$NOW" \
  '{message_id:$id, chat_id:$chat, content:$content, rating:null, sent_at:$sent, role:"user"}')
echo -n "422 content too big:"; curl -s -o /dev/null -w " HTTP %{http_code}\n" -X PUT "$BASE/api/v1/messages/$(uuid)" -H "$H_AUTH" -H "$H_JSON" -d "$TOOBIG"

echo
echo "Done."
