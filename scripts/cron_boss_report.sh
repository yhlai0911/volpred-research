#!/bin/bash
cd /Users/yhlai0911/volpred-research
echo "=== [boss_report] start at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
/opt/homebrew/bin/uv run python scripts/boss_report.py
EC=$?
echo "=== [boss_report] exit $EC at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
exit $EC
