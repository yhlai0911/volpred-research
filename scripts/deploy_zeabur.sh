#!/bin/bash
# Deploy to Zeabur as Next.js standalone app
# Usage: bash scripts/deploy_zeabur.sh
#
# Rollback: git checkout pre-restructure
# Express fallback: frontend/zeabur-server-fallback.js

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$PROJECT_DIR/frontend"
DEPLOY_DIR="/tmp/zeabur-deploy"

echo "=== Deploying to Zeabur (Next.js Standalone) ==="
echo "Project: $PROJECT_DIR"

# 1. Kill local dev server (will restart after)
echo "1. Stopping local dev server..."
kill $(lsof -ti:3000) 2>/dev/null || true
sleep 1

# 2. Sync data from storage/ to frontend/data/
echo "2. Syncing data files to frontend/data/..."
mkdir -p "$FRONTEND_DIR/data/reports" "$FRONTEND_DIR/data/notifications"

# Core data files
cp "$PROJECT_DIR/storage/reports/feed.json" "$FRONTEND_DIR/data/" 2>/dev/null || true
cp "$PROJECT_DIR/storage/risk_forecast.json" "$FRONTEND_DIR/data/" 2>/dev/null || true
cp "$PROJECT_DIR/storage/memory/thinking_journal.json" "$FRONTEND_DIR/data/" 2>/dev/null || true
cp "$PROJECT_DIR/storage/memory/open_questions.json" "$FRONTEND_DIR/data/" 2>/dev/null || true
cp "$PROJECT_DIR/storage/memory/knowledge.json" "$FRONTEND_DIR/data/" 2>/dev/null || true
cp "$PROJECT_DIR/storage/memory/research_log.json" "$FRONTEND_DIR/data/" 2>/dev/null || true
cp "$PROJECT_DIR/storage/memory/experiments.json" "$FRONTEND_DIR/data/" 2>/dev/null || true
cp "$PROJECT_DIR/storage/paper_trading.json" "$FRONTEND_DIR/data/" 2>/dev/null || true

# Copy individual report files
for f in "$PROJECT_DIR/storage/reports/"*.json; do
    [ -f "$f" ] && cp "$f" "$FRONTEND_DIR/data/reports/" 2>/dev/null || true
done

# Copy notification files
for f in "$PROJECT_DIR/storage/notifications/"*.json; do
    [ -f "$f" ] && cp "$f" "$FRONTEND_DIR/data/notifications/" 2>/dev/null || true
done

# Sort feed.json by published_at (most recent first)
echo "   Sorting feed.json..."
python3 -c "
import json, os
fp = '$FRONTEND_DIR/data/feed.json'
if os.path.exists(fp):
    feed = json.load(open(fp))
    feed.sort(key=lambda x: x.get('published_at', ''), reverse=True)
    json.dump(feed, open(fp, 'w'), indent=2, ensure_ascii=False, default=str)
    print(f'  Sorted {len(feed)} items by published_at')
else:
    print('  No feed.json found, skipping sort')
"

# 3. Build Next.js standalone
echo "3. Building Next.js standalone..."
cd "$FRONTEND_DIR"
npm run build 2>&1 | tail -10

# 4. Prepare deploy directory from .next/standalone/
echo "4. Preparing deploy directory..."
rm -rf "$DEPLOY_DIR"
cp -r "$FRONTEND_DIR/.next/standalone" "$DEPLOY_DIR"

# Copy static assets (not included in standalone by default)
mkdir -p "$DEPLOY_DIR/.next/static"
cp -r "$FRONTEND_DIR/.next/static/"* "$DEPLOY_DIR/.next/static/" 2>/dev/null || true

# Copy public/ assets
if [ -d "$FRONTEND_DIR/public" ]; then
    cp -r "$FRONTEND_DIR/public" "$DEPLOY_DIR/public"
fi

# Copy data/ into deploy root (where server.js will look via process.cwd())
cp -r "$FRONTEND_DIR/data" "$DEPLOY_DIR/data"

# Add zbpack.json for Zeabur Node.js detection
cat > "$DEPLOY_DIR/zbpack.json" << 'ZBPACK'
{
  "build_command": "",
  "start_command": "node server.js",
  "node_version": "20"
}
ZBPACK

echo "   Deploy dir ready: $DEPLOY_DIR"
echo "   Size: $(du -sh "$DEPLOY_DIR" | cut -f1)"

# 5. Deploy to Zeabur
echo "5. Deploying to Zeabur..."
cd "$DEPLOY_DIR"
npx zeabur@latest deploy --project-id 69b5b264800a475a1f82b073 --service-id 69b5b279e0a0c18cef9d780d 2>&1 | tail -5

# 6. Clean .next cache to prevent dev server corruption
echo "6. Cleaning .next cache..."
cd "$FRONTEND_DIR"
rm -rf .next 2>/dev/null || true

# 7. Restart local dev server
echo "7. Restarting local dev server..."
npx next dev -p 3000 &
sleep 3

echo ""
echo "=== Done! Next.js standalone deployed to Zeabur ==="
echo "=== Local dev server restarted on :3000 ==="
