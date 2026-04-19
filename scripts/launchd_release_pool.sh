#!/bin/zsh
# LaunchAgent wrapper for volpred release-pool-by-settings
# Logs timestamps so each fire leaves a footprint even if uv fails.
set +e

REPO=/Users/yhlai0911/Desktop/volpred-research
LOG=$REPO/storage/logs/cron/release_pool.log

exec >>"$LOG" 2>&1
echo ""
echo "=== [release-pool] fire at $(date) ==="
cd "$REPO" || { echo "cd failed"; exit 1; }

# Load user shell env (uv path, pyenv, etc.) — non-fatal if missing
source ~/.zshenv 2>/dev/null
source ~/.zshrc 2>/dev/null

# Try uv from multiple known locations
for UV in /opt/homebrew/bin/uv /Users/yhlai0911/.local/bin/uv /usr/local/bin/uv; do
    [ -x "$UV" ] && break
done

if [ -z "$UV" ] || [ ! -x "$UV" ]; then
    echo "ERROR: uv not found in expected locations"
    exit 127
fi

echo "using uv=$UV"
"$UV" run volpred ops release-pool-by-settings
echo "=== exit $? at $(date) ==="
