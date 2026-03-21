#!/bin/bash
# Sync all local data to Zeabur (without rebuild)
# Usage: bash scripts/sync_zeabur.sh

REMOTE="https://volpred.zeabur.app"
echo "=== Syncing to $REMOTE ==="

# Feed
curl -s -X PUT "$REMOTE/api/sync/feed.json" \
  -H "Content-Type: application/json" \
  -d @storage/reports/feed.json > /dev/null 2>&1 && echo "  feed.json ✓"

# Memory files
for file in thinking_journal.json knowledge.json paper_trading.json open_questions.json research_log.json; do
  src="storage/memory/$file"
  [ ! -f "$src" ] && src="storage/$file"
  [ -f "$src" ] && curl -s -X PUT "$REMOTE/api/sync/$file" \
    -H "Content-Type: application/json" -d @"$src" > /dev/null 2>&1 && echo "  $file ✓"
done

# Experiments (fix Infinity)
python3 -c "
import json
with open('storage/memory/experiments.json') as f:
    c = f.read().replace('Infinity','null').replace('NaN','null')
with open('/tmp/exp_clean.json','w') as f:
    f.write(c)
" && curl -s -X PUT "$REMOTE/api/sync/experiments.json" \
  -H "Content-Type: application/json" -d @/tmp/exp_clean.json > /dev/null 2>&1 && echo "  experiments.json ✓"

# Reports
count=0
for f in storage/reports/mile_*.json storage/reports/cmp_*.json storage/reports/pub_*.json; do
  [ -f "$f" ] && curl -s -X PUT "$REMOTE/api/sync/reports/$(basename $f)" \
    -H "Content-Type: application/json" -d @"$f" > /dev/null 2>&1 && count=$((count+1))
done
echo "  $count reports ✓"

echo "=== Done ==="
