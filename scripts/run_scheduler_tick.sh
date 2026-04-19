#!/bin/bash
set -euo pipefail

cd /Users/yhlai0911/Desktop/volpred-research
set -a
source .env.local 2>/dev/null || true
set +a
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$HOME/.nvm/versions/node/v22.20.0/bin:$PATH"

exec uv run volpred ops scheduler-tick
