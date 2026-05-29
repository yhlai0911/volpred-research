#!/bin/bash

# Auto-injected: TCC bypass — self-redirect to Desktop log avoids launchd-process-level TCC denial
exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/arxiv_scan.log 2>&1
# Canonical source for the host-cron wrapper.
# IMPORTANT: host cron does NOT exec files under Desktop/ (macOS TCC/FDA blocks
# the cron daemon). The cron-exec target lives at ~/.volpred/bin/cron_arxiv_scan.sh.
# After editing this file, sync with:
#   cp scripts/cron_arxiv_scan.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_arxiv_scan.sh
#
# 目的（Phase 2，2026-05-29 老闆「你決定就好」授權）：每週掃 arXiv q-fin 前沿，
# 把命中研究軸的新論文 seed 到 staging 候選池 storage/research/arxiv_candidates.json，
# 補「研究方向被既有主題框住」的缺口。scanner 走 ground-truth RSS（不經 LLM，避免
# hallucinate citation）。只 seed 候選，不自動改 research_program 北極星檔 —— 主線程
# 選題時 review staging、把真正相關的 promote。有新候選才寄 info email。

set -u
cd /Users/yhlai0911/Desktop/volpred-research || exit 1

echo "=== [arxiv_scan] $(date '+%Y-%m-%d %H:%M:%S %Z') start ==="

BEFORE=$(/opt/homebrew/bin/uv run python -c "import json,pathlib;p=pathlib.Path('storage/research/arxiv_candidates.json');print(json.loads(p.read_text())['total'] if p.exists() else 0)" 2>/dev/null)

/opt/homebrew/bin/uv run python scripts/scan_arxiv_topics.py --source rss --write-staging --markdown
RC=$?

AFTER=$(/opt/homebrew/bin/uv run python -c "import json,pathlib;p=pathlib.Path('storage/research/arxiv_candidates.json');print(json.loads(p.read_text())['total'] if p.exists() else 0)" 2>/dev/null)
echo "staging total: ${BEFORE:-0} -> ${AFTER:-0} (rc=$RC)"

if [ "${BEFORE:-0}" != "${AFTER:-0}" ]; then
  ADDED=$(( ${AFTER:-0} - ${BEFORE:-0} ))
  echo "new candidates +${ADDED}; emailing boss"
  /opt/homebrew/bin/uv run volpred ops send-alert --level info \
    --title "arXiv 前沿掃描：+${ADDED} 新候選（池中 ${AFTER}）" \
    --body "## 觸發
週度 arXiv q-fin 前沿掃描 (cron_arxiv_scan.sh) 新增 ${ADDED} 篇命中研究軸的候選。

## 候選池
storage/research/arxiv_candidates.json（status=new 待主線程 review）。
主線程選題時會 review，把真正相關的 promote 到 research_program + seed experiment。
不自動改北極星檔（避免 axis matcher 邊際命中污染研究方向）。

## 服務目標
Mission 2/3：研究不被既有主題框住，持續引入學術前沿。"
fi

echo "=== [arxiv_scan] $(date '+%Y-%m-%d %H:%M:%S %Z') exit rc=$RC ==="
