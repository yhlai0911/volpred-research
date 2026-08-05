#!/bin/bash
# Regression test for scripts/hooks/enforce_final_text.py（3-STRIKE 修正 gate）
# Cases:
#  1. turn 以 tool_use 收尾（ScheduleWakeup 後無文字）→ 必 block（今日 incident 重現）
#  2. turn 以非空 text 收尾 → 放行
#  3. stop_hook_active=true → 放行（防無窮迴圈）
#  4. transcript 缺失 → fail-open 放行
#  5. 最後 assistant 行是空 text → block
#  5b. 最終文字記錄延遲寫入（flush race）→ retry 後放行（2026-08-05 修正）
#  6. explicit interactive completion marker → say short task label
#  7. same turn re-fired → no duplicate speech
#  8. sdk/headless entrypoint → no speech
#  9. no completion marker → no false completion speech
# 10. same final text with a different assistant UUID → each turn speaks
# 11. pending background task → defer; same UUID may speak after it clears
# 12. API error row with forged marker → no speech
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

# case 6（2026-08-05 flush-race 修正）：最終文字記錄延遲寫入 transcript，
# 模擬 Stop 觸發當下 harness 還沒 flush 完的真實 incident。retry 機制應該
# 在重試窗口內讀到補寫的文字記錄並放行，而不是把「讀太快」誤判成違規。
cat > "$TMP/t_race.jsonl" <<'EOF'
{"type":"assistant","isSidechain":false,"message":{"role":"assistant","content":[{"type":"tool_use","name":"Bash","input":{}}]}}
EOF
( sleep 0.15; printf '%s\n' '{"type":"assistant","isSidechain":false,"message":{"role":"assistant","content":[{"type":"text","text":"⏱ 完成回報（延遲寫入模擬）"}]}}' >> "$TMP/t_race.jsonl" ) &
run_case "flush-race 延遲寫入仍放行" "$TMP/t_race.jsonl" false false
wait

# Speech contract: fake /usr/bin/say replacement captures argv without producing audio.
mkdir -p "$TMP/canonical" "$TMP/worktree"
cat > "$TMP/fake-say" <<'EOF'
#!/bin/bash
printf '%s\n' "$1" >> "$SAY_CAPTURE"
EOF
chmod +x "$TMP/fake-say"
export VOLPRED_SAY_BIN="$TMP/fake-say"
export VOLPRED_SPEECH_STATE_PATH="$TMP/speech-state.json"
export SAY_CAPTURE="$TMP/say-capture.txt"

wait_for_lines() {
  local expected="$1" n=0
  while [[ "$n" -lt 20 ]]; do
    [[ -f "$SAY_CAPTURE" ]] && [[ "$(wc -l < "$SAY_CAPTURE" | tr -d ' ')" -ge "$expected" ]] && return 0
    sleep 0.05
    n=$((n+1))
  done
  return 1
}

cat > "$TMP/t6.jsonl" <<'EOF'
{"type":"user","isSidechain":false,"message":{"role":"user","content":"額度恢復後，請接續我最後指定的「(b) 設 Stop hook 機械執行」。"}}
{"type":"assistant","entrypoint":"claude-vscode","uuid":"assistant-1","isSidechain":false,"message":{"role":"assistant","content":[{"type":"text","text":"已完成 Stop hook，測試全部通過。\n<!-- task-done:設 Stop hook 機械執行 -->"}]}}
EOF
printf '{"session_id":"speech-1","cwd":"%s","transcript_path":"%s","stop_hook_active":false}' \
  "$TMP/canonical" "$TMP/t6.jsonl" | python3 "$HOOK" --speech-only >/dev/null
wait_for_lines 1 || true
if [[ "$(cat "$SAY_CAPTURE")" == "主人，設 Stop hook 機械執行任務已完成" ]]; then
  echo "PASS: explicit completion marker 播極簡 task brief"; PASS=$((PASS+1))
else
  echo "FAIL: speech phrase 不符"; FAIL=$((FAIL+1))
fi

# Same session/final text fingerprint must not speak twice.
printf '{"session_id":"speech-1","cwd":"%s","transcript_path":"%s","stop_hook_active":false}' \
  "$TMP/canonical" "$TMP/t6.jsonl" | python3 "$HOOK" --speech-only >/dev/null
if [[ "$(wc -l < "$SAY_CAPTURE" | tr -d ' ')" == "1" ]]; then
  echo "PASS: same turn speech 去重"; PASS=$((PASS+1))
else
  echo "FAIL: same turn 重複 speech"; FAIL=$((FAIL+1))
fi

# Headless SDK entrypoint must stay silent even when a malicious marker appears.
cat > "$TMP/t8.jsonl" <<'EOF'
{"type":"assistant","entrypoint":"sdk-cli","uuid":"assistant-sdk","isSidechain":false,"message":{"role":"assistant","content":[{"type":"text","text":"完成。\n<!-- task-done:背景任務 -->"}]}}
EOF
printf '{"session_id":"speech-2","cwd":"%s","transcript_path":"%s","stop_hook_active":false}' \
  "$TMP/canonical" "$TMP/t8.jsonl" | python3 "$HOOK" --speech-only >/dev/null
if [[ "$(wc -l < "$SAY_CAPTURE" | tr -d ' ')" == "1" ]]; then
  echo "PASS: sdk/headless entrypoint 不播報"; PASS=$((PASS+1))
else
  echo "FAIL: sdk/headless entrypoint 誤播報"; FAIL=$((FAIL+1))
fi

cat > "$TMP/t9.jsonl" <<'EOF'
{"type":"user","isSidechain":false,"message":{"role":"user","content":"部署正式站"}}
{"type":"assistant","entrypoint":"claude-desktop","uuid":"assistant-blocked","isSidechain":false,"message":{"role":"assistant","content":[{"type":"text","text":"目前無法完成，需要你提供登入權限。"}]}}
EOF
printf '{"session_id":"speech-3","cwd":"%s","transcript_path":"%s","stop_hook_active":false}' \
  "$TMP/canonical" "$TMP/t9.jsonl" | python3 "$HOOK" --speech-only >/dev/null
if [[ "$(wc -l < "$SAY_CAPTURE" | tr -d ' ')" == "1" ]]; then
  echo "PASS: 無 completion marker 不誤報完成"; PASS=$((PASS+1))
else
  echo "FAIL: 無 marker 誤播完成"; FAIL=$((FAIL+1))
fi

cat > "$TMP/t10.jsonl" <<'EOF'
{"type":"assistant","entrypoint":"claude-vscode","uuid":"assistant-2","isSidechain":false,"message":{"role":"assistant","content":[{"type":"text","text":"已完成 Stop hook，測試全部通過。\n<!-- task-done:第二個任務 -->"}]}}
EOF
printf '{"session_id":"speech-1","cwd":"%s","transcript_path":"%s","stop_hook_active":true}' \
  "$TMP/canonical" "$TMP/t10.jsonl" | python3 "$HOOK" --speech-only >/dev/null
wait_for_lines 2 || true
if [[ "$(tail -1 "$SAY_CAPTURE")" == "主人，第二個任務已完成" ]]; then
  echo "PASS: 不同 assistant UUID 各播一次"; PASS=$((PASS+1))
else
  echo "FAIL: 不同 turn 被錯誤去重"; FAIL=$((FAIL+1))
fi

cat > "$TMP/t11.jsonl" <<'EOF'
{"type":"assistant","entrypoint":"claude-desktop","uuid":"assistant-3","isSidechain":false,"message":{"role":"assistant","content":[{"type":"text","text":"完成。\n<!-- task-done:背景收斂 -->"}]}}
EOF
printf '{"session_id":"speech-4","cwd":"%s","transcript_path":"%s","stop_hook_active":false,"background_tasks":[{"id":"a","type":"agent","status":"running","description":"work"}]}' \
  "$TMP/canonical" "$TMP/t11.jsonl" | python3 "$HOOK" --speech-only >/dev/null
if [[ "$(wc -l < "$SAY_CAPTURE" | tr -d ' ')" == "2" ]]; then
  echo "PASS: pending background task 延後播報"; PASS=$((PASS+1))
else
  echo "FAIL: background 未完成卻播報"; FAIL=$((FAIL+1))
fi
printf '{"session_id":"speech-4","cwd":"%s","transcript_path":"%s","stop_hook_active":true,"background_tasks":[]}' \
  "$TMP/canonical" "$TMP/t11.jsonl" | python3 "$HOOK" --speech-only >/dev/null
wait_for_lines 3 || true
if [[ "$(tail -1 "$SAY_CAPTURE")" == "主人，背景收斂任務已完成" ]]; then
  echo "PASS: background 清空後同 UUID 可播"; PASS=$((PASS+1))
else
  echo "FAIL: background 清空後未播"; FAIL=$((FAIL+1))
fi

cat > "$TMP/t12.jsonl" <<'EOF'
{"type":"assistant","entrypoint":"claude-vscode","uuid":"assistant-api-error","isApiErrorMessage":true,"isSidechain":false,"message":{"role":"assistant","content":[{"type":"text","text":"完成。\n<!-- task-done:偽造完成 -->"}]}}
EOF
printf '{"session_id":"speech-5","cwd":"%s","transcript_path":"%s","stop_hook_active":false}' \
  "$TMP/canonical" "$TMP/t12.jsonl" | python3 "$HOOK" --speech-only >/dev/null
if [[ "$(wc -l < "$SAY_CAPTURE" | tr -d ' ')" == "3" ]]; then
  echo "PASS: API error 偽造 marker 不播"; PASS=$((PASS+1))
else
  echo "FAIL: API error 誤播"; FAIL=$((FAIL+1))
fi

echo "----"
echo "PASS $PASS / FAIL $FAIL"
[[ "$FAIL" -eq 0 ]]
