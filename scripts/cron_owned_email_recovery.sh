#!/bin/bash
cd /Users/yhlai0911/volpred-research || exit 1
exec /opt/homebrew/bin/uv run python scripts/recover_owned_email_notifications.py --limit 25 --max-age-seconds 3600
