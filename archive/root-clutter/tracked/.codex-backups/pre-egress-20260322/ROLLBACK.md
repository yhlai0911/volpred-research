Rollback snapshot for the 2026-03-22 egress optimization batch.

Restore these files from this backup folder:
- `frontend-v2-fix/src/lib/data-server.ts`
- `scripts/supabase_sync.py`

Delete these newly added files to return to the pre-change state:
- `frontend-v2-fix/src/app/api/publications/feed/route.ts`
- `frontend-v2-fix/src/app/api/publications/feed/[id]/route.ts`
- `frontend-v2-fix/src/app/api/risk-forecast/route.ts`
