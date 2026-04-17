# Project Improvement Status

Last updated: 2026-04-17

## Completed

- Phase 0 rollback baseline is in place.
  - Canonical rollback tooling exists in `src/volpred/ops/rollback.py`
  - Multiple named rollback points have been created under `storage/ops/rollback_points/`
- Root-level low-risk repo cleanup is in place.
  - Root clutter has been consolidated into `archive/root-clutter/`
  - Hygiene tooling exists in `src/volpred/ops/hygiene.py`
- Phase 0.5 agent-spec canonical is in place.
  - Canonical source: `agent-specs/`
  - Generated outputs: `CLAUDE.md`, `AGENTS.md`, `.claude/...`, `.agents/...`
  - Agent-spec tooling exists in `src/volpred/ops/agent_spec.py`
- Phase 1 local VS Code control plane is in place.
  - Local task state: `storage/ops/tasks/`, `storage/ops/agents/`, `storage/ops/executions/`, `storage/ops/approvals/`
  - Local control plane implementation: `src/volpred/ops/local_control_plane.py`
  - CLI wiring: `src/volpred/cli.py`
- Website zero-regression guardrails are in place.
  - Frontend regression verifier: `frontend-v2-fix/scripts/verify-regressions.mjs`
  - Web admin mirror for local control plane is in place
- `.venv` dev/test environment is usable.
  - `uv sync --extra dev` has been run
  - `pytest` is available through the repo `.venv`
- `experiments/` touched-file migration tooling is in place.
  - Implementation: `src/volpred/ops/experiments.py`
  - Tests: `tests/test_experiments_ops.py`
- Historical `experiments/` top-level loose-file cleanup is complete.
  - Current hygiene snapshot:
    - `loose_files=0`
    - `candidate_groups=0`
    - `top_level_dirs=1010`
  - Arbitrary loose-file adoption is supported via `uv run volpred ops experiments adopt ...`
  - The final wrap-up pass adopted 56 non-`kXXX` experiment groups and rewrote repo references to their canonical paths
- Targeted experiment-migration regression coverage is now in place.
  - `tests/test_experiments_ops.py` now covers clean `loose_files=0` snapshots
  - Conflict + `--overwrite` behavior is covered for both `migrate` and `adopt`
  - Json-only and py-only arbitrary adoption branches are both covered with placeholder scaffold assertions
- Phase 2 schedule definition convergence is in place.
  - Canonical source: `config/runtime_schedules.json`
  - Shared loader: `src/volpred/config/schedules.py`
  - Local CLI readout: `uv run volpred ops schedule-report`
  - Admin `/admin/schedules` now reads canonical spec + live `crontab -l`, instead of reverse-parsing rendered guides
- Mirror API live verification is in place.
  - Authenticated live `mirror-api` `/api/mirror/health` + `/api/mirror/manifest` succeeded on 2026-04-17
  - Public `volpred.zeabur.app/api/research/summary` + `/api/health` responded successfully on 2026-04-17
  - `MemorySystem` now warns on Mirror sync failures, and a full reconcile closed the one-entry `knowledge.json` drift (`local=remote=1929`)
- Provider-native agent governance surfaces are now modularized.
  - `agent-specs/guide.md` has been reduced to a bootstrap guide instead of duplicating long operational manuals
  - Claude-specific path-scoped rules now render to `.claude/rules/`
  - Claude / Codex subagents now render to `.claude/agents/` and `.codex/agents/`
  - Codex project config now lives in canonical `agent-specs/codex/config.toml` and renders to `.codex/config.toml`
  - Root `CLAUDE.md` / `AGENTS.md` stay canonical outputs, but detailed guidance is intentionally pushed down into docs, skills, rules, and provider-native subagent config
- Website admin now has partial local control-plane write access.
  - `POST/PATCH /api/admin/local-control-plane` now bridge into the canonical Python file-backed control plane, instead of exposing a read-only mirror only
  - `/admin/ops` can create local `storage/ops/tasks/*.json` work items and approve/reject `awaiting_approval` tasks directly from the console
  - Validation still runs through the existing Python control-plane primitives, so admin writes use the same schema and lock-aware path as CLI usage
- Phase B dual-agent concurrency guardrails are in place (2026-04-17).
  - `src/volpred/ops/shared_lock.py` exposes `shared_state_lock(name)` (fcntl LOCK_EX at `storage/ops/locks/<name>.lock`)
  - `src/volpred/memory/system.py` `_append_to_index` now acquires `memory_<stem>` lock + emits writer_log entry
  - `src/volpred/publisher/publisher.py` `_append_to_feed` now acquires `publisher_feed` lock + emits writer_log entry (also tmp+rename atomic)
  - `src/volpred/ops/writer_log.py` writes JSONL provenance to `storage/ops/writer_log.jsonl` (`actor` taken from `VOLPRED_ACTOR` env)
  - `claim_next_task` reclaims tasks held by stale agents (heartbeat > 5 min) back to queued with writer_log trail
  - New tests: `tests/test_shared_lock.py`, `tests/test_publisher_provenance.py`, `tests/test_stale_reclaim.py` (all green, plus `test_memory_system` extended)
- Phase C admin UI action closure (2026-04-17).
  - `admin-local-control-plane.ts` bridge extended with `claim` / `complete` / `fail` / `rollback_restore` operations
  - `admin_override_claim(task_id, agent_name, actor)` added to the Python control plane (explicit pin overrides normal claim-pull)
  - OpsConsole adds per-status task actions: Claim (Claude/Codex), Mark Succeeded, Mark Failed (with prompt for reason)
  - New `/api/admin/rollback-points` GET (list manifests) + POST (dry-run / force restore)
  - Dedicated Rollback panel in OpsConsole with dropdown + dry-run preview + double-confirm destructive restore
- Phase D governance trim + invariants doc (2026-04-17).
  - `research_program.md` trimmed 958 → 513 lines (-47%); archived sections moved to `agent-specs/references/research_program_archive_2026Q2.md`
  - New `docs/agent-collab-invariants.md` codifies shared-state lock naming, writer-log schema, VOLPRED_ACTOR convention, stale reclaim rules
- Phase A.1 rollback points pruning executed (2026-04-17).
  - `scripts/prune_rollback_points.py` extended with `--preserve <id>` flag
  - `storage/ops/rollback_points/` reduced 13.6GB → 509MB (10 points removed, 14 preserved incl. 2 baselines + latest 11)

## In Progress

_(no active items — Phase B/C/D closed out below)_

## Remaining

- Optional next cleanup:
  - Add repo-wide script-level hygiene checks for legacy hard-coded experiment output paths when those families are next touched
  - ~~Retire stale pre-convergence schedule examples from historical reports when those docs are next touched~~ → **done 2026-04-17**: `docs/platform-test-report-2026-03-21.md` header flagged as historical snapshot with pointers to current canonical crons.
  - rollback_points (14GB) retention: pruning tool shipped (`scripts/prune_rollback_points.py`) with 14-day retention default. Weekly cron NOT yet enabled — user to opt-in.

## Verified Live (2026-04-17)

- Supabase migration 018 is live on `qxhfgdfzazwpkdgesavm` (unique constraint `paper_trades_strategy_trade_date_key` + `idx_paper_trades_strategy_date` confirmed via `execute_sql`).
- Supabase migration 019 is live (`market_daily` table has 825 rows spanning 2023-01-04 → 2026-04-17).
- Frontend redeploy is serving updated code on `https://volpred.zeabur.app` (`/api/health` 200, ~280ms); `fetchAPI` timeout remains at the corrected 15000ms in source.

## Current Readout

- Core improvement plan status:
  - Rollback / safety: complete
  - Agent-spec canonical sync: complete
  - Local dual-agent control plane: complete for v1
  - Website admin surfacing: partial local control-plane write path is in place
  - Historical experiments cleanup: complete for top-level file layout
