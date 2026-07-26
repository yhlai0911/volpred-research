#!/bin/bash
cd /Users/yhlai0911/volpred-research || exit 1
exec /opt/homebrew/bin/uv run python scripts/recover_owned_publisher_articles.py --limit 25
