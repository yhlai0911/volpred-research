#!/bin/bash
# Independent cross-model paper review — Codex (GPT-5.4) + agy (Gemini).
# Rationale: paper review_history v1-v4 were all Claude-subagent proxies
# (Claude reviewing Claude-written papers). This adds genuinely independent
# second/third models to catch self-review blind spots before submission.
# 2026-05-21, triggered by user audit of "ready_for_submission" rigor.
set -u
cd /Users/yhlai0911/Desktop/volpred-research

PAPERS=(crypto-fear-channel prg-periodic-garch vt-crowding-abm)
LOG=/tmp/independent_review.log
: > "$LOG"

read -r -d '' PROMPT <<'EOF'
你是 JBF / FRL 等 top finance journal 的資深審稿人。獨立審查指定手稿。
重要背景：這篇論文先前的所有 review 都是同一個 AI（Claude）自審，你的價值
在於抓出「同模型自審會忽略的盲點」。請特別查：
1. 事實/數值宣稱無證據或與內文矛盾
2. 方法論缺陷（identification、estimator、lookahead、sample 選擇）
3. 過度宣稱（結論強度超過證據）
4. 缺漏的 robustness / 對照組
5. 引用問題（關鍵宣稱無 cite、cite 不支持該宣稱）
6. 邏輯漏洞、內部不一致
輸出格式：(a) 一行整體傾向 ACCEPT / MINOR_REVISION / MAJOR_REVISION / REJECT
(b) 依嚴重度 BLOCKING / MAJOR / MINOR 編號列問題，每條附 section/line 定位。
若無 blocking issue 也明說。請繁體中文。
EOF

for p in "${PAPERS[@]}"; do
  TEX="paper/$p/main.tex"
  OUT="paper/$p/review_history/v5_independent"
  mkdir -p "$OUT"
  [ -f "$TEX" ] || { echo "[skip] $p — no main.tex" >>"$LOG"; continue; }

  echo "=== [$(date '+%H:%M:%S')] Codex review: $p ===" >>"$LOG"
  codex exec --skip-git-repo-check \
    "$PROMPT

手稿檔：$TEX — 請讀取該檔全文後審查。" \
    > "$OUT/codex_review.md" 2>>"$LOG"
  echo "[$(date '+%H:%M:%S')] Codex $p exit=$?" >>"$LOG"

  echo "=== [$(date '+%H:%M:%S')] agy review: $p ===" >>"$LOG"
  agy -p "$PROMPT

手稿檔：$TEX — 請讀取 repo 內該檔全文後審查。" \
    --dangerously-skip-permissions \
    > "$OUT/agy_review.md" 2>>"$LOG"
  echo "[$(date '+%H:%M:%S')] agy $p exit=$?" >>"$LOG"
done
echo "=== ALL DONE $(date '+%H:%M:%S') ===" >>"$LOG"
