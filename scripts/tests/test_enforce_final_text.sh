#!/bin/bash
# Regression test for scripts/hooks/enforce_final_text.py（3-STRIKE 修正 gate）
# Cases:
#  1. turn 以 tool_use 收尾（ScheduleWakeup 後無文字）→ 必 block（今日 incident 重現）
#  2. turn 以非空 text 收尾 → 放行
#  3. stop_hook_active=true → 放行（防無窮迴圈）
#  4. transcript 缺失 → fail-open 放行
#  5. 最後 assistant 行是空 text → block
#  6. canonical interactive completion → say short task label
#  7. same turn re-fired → no duplicate speech
#  8. worktree/background cwd → no speech
#  9. blocked final text → no false completion speech
set -euo pipefail
HOOK="$(cd "$(dirname "$0")/../.." && pwd)/scripts/hooks/enforce_final_text.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0

run_case() { # name transcript_file stop_active expect_block
  local name="$1" tf="$2" active="$3" expect="$4"
  local out
  out="$(printf '{"transcript_path":"%s","stop_hook_active":%s}' "$tf" "$active" | python3 "$HOOK" 2>/dev/null)"
  local blocked=false
  [[ "$out" == *'"decision": "block"'* || "$out" == *'"decision":"block"'* ]] && blocked=true
  if [[ "$blocked" == "$expect" ]]; then echo "PASS: $name"; PASS=$((PASS+1));
  else echo "FAIL: $name (expect block=$expect, got: ${out:-<empty>})"; FAIL=$((FAIL+1)); fi
}

# case 1: 以 tool_use 收尾（incident 重現：ScheduleWakeup 是最後輸出）
cat > "$TMP/t1.jsonl" <<'EOF'
{"type":"assistant","isSidechain":false,"message":{"role":"assistant","content":[{"type":"text","text":"修完了"}]}}
{"type":"assistant","isSidechain":false,"message":{"role":"assistant","content":[{"type":"tool_use","name":"ScheduleWakeup","input":{}}]}}
{"type":"user","message":{"role":"user","content":[{"type":"tool_result","content":"scheduled"}]}}
EOF
run_case "tool_use 收尾必 block" "$TMP/t1.jsonl" false true

# case 2: 非空文字收尾
cat > "$TMP/t2.jsonl" <<'EOF'
{"type":"assistant","isSidechain":false,"message":{"role":"assistant","content":[{"type":"tool_use","name":"ScheduleWakeup","input":{}}]}}
{"type":"user","message":{"role":"user","content":[{"type":"tool_result","content":"scheduled"}]}}
{"type":"assistant","isSidechain":false,"message":{"role":"assistant","content":[{"type":"text","text":"⏱ 完成回報：..."}]}}
EOF
run_case "文字收尾放行" "$TMP/t2.jsonl" false false

# case 3: stop_hook_active 放行（防迴圈）
run_case "stop_hook_active 放行" "$TMP/t1.jsonl" true false

# case 4: transcript 缺失 fail-open
run_case "transcript 缺失 fail-open" "$TMP/nonexistent.jsonl" false false

# case 5: 空 text 收尾 → block
cat > "$TMP/t5.jsonl" <<'EOF'
{"type":"assistant","isSidechain":false,"message":{"role":"assistant","content":[{"type":"text","text":"   "}]}}
EOF
run_case "空文字收尾必 block" "$TMP/t5.jsonl" false true

# Speech contract: fake /usr/bin/say replacement captures argv without producing audio.
mkdir -p "$TMP/canonical" "$TMP/worktree"
cat > "$TMP/fake-say" <<'EOF'
#!/bin/bash
printf '%s\n' "$1" >> "$SAY_CAPTURE"
EOF
chmod +x "$TMP/fake-say"
export VOLPRED_SAY_BIN="$TMP/fake-say"
export VOLPRED_SPEECH_STATE_PATH="$TMP/speech-state.json"
export VOLPRED_SPEECH_CANONICAL_CWD="$TMP/canonical"
export SAY_CAPTURE="$TMP/say-capture.txt"

cat > "$TMP/t6.jsonl" <<'EOF'
{"type":"user","isSidechain":false,"message":{"role":"user","content":"額度恢復後，請接續我最後指定的「(b) 設 Stop hook 機械執行」。"}}
{"type":"assistant","isSidechain":false,"message":{"role":"assistant","content":[{"type":"text","text":"已完成 Stop hook，測試全部通過。"}]}}
EOF
printf '{"session_id":"speech-1","cwd":"%s","transcript_path":"%s","stop_hook_active":false}' \
  "$TMP/canonical" "$TMP/t6.jsonl" | python3 "$HOOK" >/dev/null
if [[ "$(cat "$SAY_CAPTURE")" == "主人，設 Stop hook 機械執行任務已完成" ]]; then
  echo "PASS: canonical completion 播極簡 task brief"; PASS=$((PASS+1))
else
  echo "FAIL: speech phrase 不符"; FAIL=$((FAIL+1))
fi

# Same session/final text fingerprint must not speak twice.
printf '{"session_id":"speech-1","cwd":"%s","transcript_path":"%s","stop_hook_active":false}' \
  "$TMP/canonical" "$TMP/t6.jsonl" | python3 "$HOOK" >/dev/null
if [[ "$(wc -l < "$SAY_CAPTURE" | tr -d ' ')" == "1" ]]; then
  echo "PASS: same turn speech 去重"; PASS=$((PASS+1))
else
  echo "FAIL: same turn 重複 speech"; FAIL=$((FAIL+1))
fi

# Background/worktree cwd must stay silent.
printf '{"session_id":"speech-2","cwd":"%s","transcript_path":"%s","stop_hook_active":false}' \
  "$TMP/worktree" "$TMP/t6.jsonl" | python3 "$HOOK" >/dev/null
if [[ "$(wc -l < "$SAY_CAPTURE" | tr -d ' ')" == "1" ]]; then
  echo "PASS: background cwd 不播報"; PASS=$((PASS+1))
else
  echo "FAIL: background cwd 誤播報"; FAIL=$((FAIL+1))
fi

cat > "$TMP/t9.jsonl" <<'EOF'
{"type":"user","isSidechain":false,"message":{"role":"user","content":"部署正式站"}}
{"type":"assistant","isSidechain":false,"message":{"role":"assistant","content":[{"type":"text","text":"目前無法完成，需要你提供登入權限。"}]}}
EOF
printf '{"session_id":"speech-3","cwd":"%s","transcript_path":"%s","stop_hook_active":false}' \
  "$TMP/canonical" "$TMP/t9.jsonl" | python3 "$HOOK" >/dev/null
if [[ "$(wc -l < "$SAY_CAPTURE" | tr -d ' ')" == "1" ]]; then
  echo "PASS: blocker 不誤報完成"; PASS=$((PASS+1))
else
  echo "FAIL: blocker 誤播完成"; FAIL=$((FAIL+1))
fi

echo "----"
echo "PASS $PASS / FAIL $FAIL"
[[ "$FAIL" -eq 0 ]]
