#!/bin/bash
# telegram-poll daemon shim — LaunchAgent com.volpred.telegram-poll (KeepAlive)
umask 077
cd /Users/yhlai0911/volpred-research
exec /opt/homebrew/bin/uv run --no-sync python scripts/telegram_poll.py --daemon
