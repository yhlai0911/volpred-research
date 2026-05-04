#!/bin/bash

# Auto-injected: TCC bypass — bash has FDA (System Settings), self-redirect to Desktop log avoids launchd-process-level TCC denial
exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/continue_task_stub.log 2>&1
# Canonical source for continue_task host-cron fallback wrapper.
# 目的（v2 2026-05-04）：
#  1. 寫 pending_continue.json 旗標 + history（既有 stub.py 行為，session_startup.md replay 仰賴）
#  2. 跑 dispatch.py --report 寫 dispatch_report_latest.json（slot-fill 候選清單）
# 主線程下次 idle wake 必讀 dispatch_report_latest.json 派工，不靠 next-session replay。
#
# IMPORTANT: host cron 不能直接 exec Desktop/ 下 .sh（macOS TCC/FDA 限制）。
# cron-exec target 在 ~/.volpred/bin/cron_continue_task_stub.sh；修改本檔後 sync：
#   cp scripts/cron_continue_task_stub.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_continue_task_stub.sh
cd /Users/yhlai0911/Desktop/volpred-research

echo "=== [continue_task_stub] start at $(date -u +%FT%TZ) ==="
/opt/homebrew/bin/uv run python scripts/continue_task_stub.py
echo "--- [continue_task_dispatch report] ---"
/opt/homebrew/bin/uv run python scripts/continue_task_dispatch.py --report
echo "=== [continue_task_stub] exit $? at $(date -u +%FT%TZ) ==="
