#!/bin/bash
# Regression test for scripts/hooks/deny_wakeup_interactive.py
# Cases:
#  1. 互動 turn（最後 user 訊息是普通文字）→ deny (exit 2)（五犯 incident 重現）
#  2. autonomous fire turn（user 訊息含 <<autonomous-loop sentinel）→ allow (exit 0)
#  3. 最後 user 行是 tool_result（前面才是真人訊息）→ 用真人訊息判定 → deny
#  4. transcript 缺失 → fail-open allow
#  5. 非 ScheduleWakeup 的 tool_name → allow
set -euo pipefail
HOOK="$(cd "$(dirname "$0")/../.." && pwd)/scripts/hooks/deny_wakeup_interactive.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0

run_case() { # name transcript tool expect_exit
  local name="$1" tf="$2" tool="$3" expect="$4" rc=0
  printf '{"tool_name":"%s","transcript_path":"%s"}' "$tool" "$tf" | python3 "$HOOK" 2>/dev/null || rc=$?
  if [[ "$rc" == "$expect" ]]; then echo "PASS: $name"; PASS=$((PASS+1));
  else echo "FAIL: $name (expect exit=$expect got=$rc)"; FAIL=$((FAIL+1)); fi
}

cat > "$TMP/interactive.jsonl" <<'EOF'
{"type":"user","message":{"role":"user","content":"你還是得要發兩次訊息才會回覆？不能修復？"}}
{"type":"assistant","isSidechain":false,"message":{"role":"assistant","content":[{"type":"text","text":"處理中"}]}}
EOF
run_case "互動 turn 必 deny" "$TMP/interactive.jsonl" "ScheduleWakeup" 2

cat > "$TMP/autonomous.jsonl" <<'EOF'
{"type":"user","message":{"role":"user","content":"<<autonomous-loop-dynamic>> 自主迴圈 fire：執行 ops cycle"}}
EOF
run_case "autonomous fire 放行" "$TMP/autonomous.jsonl" "ScheduleWakeup" 0

cat > "$TMP/toolresult_tail.jsonl" <<'EOF'
{"type":"user","message":{"role":"user","content":"幫我查一下狀態"}}
{"type":"assistant","isSidechain":false,"message":{"role":"assistant","content":[{"type":"tool_use","name":"Bash","input":{}}]}}
{"type":"user","message":{"role":"user","content":[{"type":"tool_result","content":"ok"}]}}
EOF
run_case "tool_result 尾行回溯真人訊息 deny" "$TMP/toolresult_tail.jsonl" "ScheduleWakeup" 2

run_case "transcript 缺失 fail-open" "$TMP/nonexistent.jsonl" "ScheduleWakeup" 0
run_case "非 ScheduleWakeup 放行" "$TMP/interactive.jsonl" "Bash" 0

echo "----"; echo "PASS $PASS / FAIL $FAIL"
[[ "$FAIL" -eq 0 ]]
