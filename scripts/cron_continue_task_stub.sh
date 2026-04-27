#!/bin/bash

# Auto-injected: TCC bypass — bash has FDA (System Settings), self-redirect to Desktop log avoids launchd-process-level TCC denial
exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/continue_task_stub.log 2>&1
# Canonical source for continue_task host-cron fallback wrapper.
# 目的：在 Claude Code session 關閉期間，host cron 仍可寫入 pending_continue.json，
# 下次 session 開啟時由 scripts/session_startup.md replay 機制補跑 continue_task。
#
# IMPORTANT: host cron 不能直接 exec Desktop/ 下 .sh（macOS TCC/FDA 限制）。
# cron-exec target 在 ~/.volpred/bin/cron_continue_task_stub.sh；修改本檔後 sync：
#   cp scripts/cron_continue_task_stub.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_continue_task_stub.sh
cd /Users/yhlai0911/Desktop/volpred-research
exec /opt/homebrew/bin/uv run python scripts/continue_task_stub.py
