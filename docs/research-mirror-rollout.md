# Research Mirror Rollout

## Goal

Keep the current frontend behavior unchanged while moving heavy research payloads off Supabase egress.

The current rollout keeps:

- Supabase as the existing read path during rollout
- dual-write enabled for heavy memory files
- an env switch for safe cutover and rollback

## Scope

Heavy mirror payloads:

- `thinking_journal.json`
- `knowledge.json`
- `experiments.json`
- `research_log.json`

Supabase remains the source for product-facing tables such as:

- `articles`
- `questions`
- `papers`
- `paper_trades`
- `risk_forecasts`
- `strategy_signals`
- auth and analytics tables

## Services

### 1. `mirror-api`

Deploy the existing Python API with [`Dockerfile.api`](/Users/yhlai0911/Desktop/volpred-research/Dockerfile.api).

Required env:

- `VOLPRED_STORAGE_DIR=/data/storage-mirror`
- `RESEARCH_MIRROR_TOKEN=<shared-secret>`

Recommended Zeabur setup:

- mount a persistent volume at `/data/storage-mirror`
- enable scheduled backups for that volume
- expose the service only through Zeabur private networking if possible

Useful endpoints:

- `GET /api/health`
- `GET /api/mirror/health`
- `GET /api/mirror/manifest`
- `PUT /api/mirror/memory/{filename}`
- `GET /api/research/{thinking|knowledge|experiments|log|summary}`

### 2. `frontend-v2-fix`

Required env for mirror support:

- `RESEARCH_MIRROR_API_URL=<mirror-api base url>`
- `RESEARCH_MIRROR_TOKEN=<shared-secret>`
- `RESEARCH_MIRROR_MODE=supabase|shadow|mirror`

Mode behavior:

- `supabase`: read from Supabase only, but heavy syncs still dual-write to mirror when configured
- `shadow`: read from Supabase, compare mirror payloads in logs
- `mirror`: prefer mirror for heavy research reads and fall back to Supabase if mirror read fails

## Rollout Sequence

1. Deploy `mirror-api` with the persistent volume attached.
2. Set `RESEARCH_MIRROR_API_URL` and `RESEARCH_MIRROR_TOKEN` on `frontend-v2-fix`.
3. Keep `RESEARCH_MIRROR_MODE=supabase`.
4. Let normal research sync traffic populate the mirror.
5. Verify `GET /api/mirror/health` reports all expected files.
6. Switch `RESEARCH_MIRROR_MODE=shadow` and watch logs for mismatches.
7. If shadow mode stays clean, switch `RESEARCH_MIRROR_MODE=mirror`.
8. Keep Supabase `memory_entries` in place for the observation window.

## Rollback

Rollback is intentionally simple:

1. Set `RESEARCH_MIRROR_MODE=supabase`
2. Restart `frontend-v2-fix`

No code revert is required, and Supabase remains the fallback read path.

## Verification Checklist

- `mirror-api` health responds successfully
- `mirror-api` manifest shows all four heavy memory files
- `/api/research/summary` still returns the same shape as before
- `/admin` and `/admin/thinking` continue loading after the cutover
- logs show no repeated shadow mismatches

## Notes

- Research-side writes now also sync `experiments.json` and `research_log.json`, so mirror freshness matches admin summary expectations.
- This rollout changes only the heavy research data path. Public product features continue using Supabase.
