#!/bin/bash
# telegram-poll daemon shim — LaunchAgent com.volpred.telegram-poll (KeepAlive)
exec >> /Users/yhlai0911/.volpred/logs/telegram_poll.log 2>&1
cd /Users/yhlai0911/volpred-research
exec /opt/homebrew/bin/uv run --no-sync python scripts/telegram_poll.py --daemon
