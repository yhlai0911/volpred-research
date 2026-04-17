# K1228: BTC GAS-t Negative Paper Repo Initialization Guide

**Status**: completed (2026-04-17)
**Proposer**: Claude (main-thread)
**Executor**: Claude (worktree `agent-a20a86c5`)
**Related K**: K1129 (BTC full-sample reversal), K1133 (sub-period decomposition), K1133b (5-model attribution + MS-GAS-t), K1214 (4829-word markdown draft source)

## Purpose

Produce a step-by-step execution plan (markdown guide + JSON checklist) for main-thread to initialize `paper/btc-gas-negative/` as a self-contained paper folder per `docs/paper-guide.md` 5-item hard requirement. Translates K1214 markdown draft into an actionable repo-init sequence covering skeleton → LaTeX cherry-pick → reproducibility package → compile + paper-upsert → long-term review cycle.

## Why NOT `.tex`

Per `CLAUDE.md` rule: *"禁止用 background agent 直接寫論文 `.tex`；寫作與方法論決策要在主線程完成"*. K1228 produces only `.md` + `.json`; main-thread owns the LaTeX conversion in Phase 2 of the guide.

## Source materials

- `experiments/k1214/k1214_paper_draft.md` — full 4829-word draft (commit `91e5ab1d`).
- `experiments/k1214/k1214_paper_outline.json` — structured outline + cross-experiment consistency check.
- `experiments/k1214/README.md` — adoption-path outline (10 steps) that K1228 expands into 24 steps.
- `experiments/K1129/k1129_results.json` — Table 1 source (full-sample BTC n_OOS=1926, DM t=-4.58).
- `experiments/k1133/k1133_results.json` — Table 2 source (P1/P2/P3 sub-period decomposition).
- `experiments/k1133b/k1133b_results.json` — Tables 3-4 source (5-model + MS-GAS-t OOS).
- `docs/paper-guide.md` — 5-item self-contained rule, three-way consistency rule, submission prep checklist (canonical reference).
- `paper/leverage-direction/` — structural template reference (main.tex / body_vN.tex / review_history / reproduce.py pattern).
- `storage/memory/knowledge.json` — K1129 entry (id `ab4b18be`), K1133 entry (id `47a41ba8`), K1133b entry.

## Files produced

| File | Purpose |
|---|---|
| `k1228_repo_init_guide.md` | 5-phase, 24-step execution plan (~1900 words). Includes paper metadata, repo structure, per-phase steps + durations, submission prep checklist, risk register, go/no-go gate questions for user. |
| `k1228_init_checklist.json` | Structured 24-step checklist in JSON for programmatic consumption by main-thread orchestrator. |
| `README.md` | This file. |

## User gate

**GO decision required before Phase 1 execution.** The guide lists 5 gate questions for user confirmation:

1. Target journal final decision (JoEF primary vs JFEC pivot)
2. Title wording (keep "Fails"/"Culprit" or soften)
3. Bibliography expansion scope (16 → 25-30 and when)
4. Figure PDF generation timing (Phase 3 fresh or Phase 5 defer)
5. Orphan K resolution (P2/P3 preliminary caveat or drop)

## Success criteria (per K1228 brief)

- [x] `k1228_repo_init_guide.md` written (~1900 words, target was 1500-2000).
- [x] 5 phases + 24 steps clearly enumerated.
- [x] Submission prep checklist included (8 items).
- [x] Paper metadata (title, target journals ranked, slug, supporting K list).
- [x] Self-contained 5-item mapping per `docs/paper-guide.md`.
- [x] Estimated effort table (~2 hours Phase 1-4 + 1-2 weeks Phase 5).
- [x] Risk register (5 entries).
- [x] Go/no-go gate questions for user.
- [x] `k1228_init_checklist.json` 24-step structured form.
- [x] `README.md` produced.
- [x] No `.tex` output (only `.md` + `.json`).
- [x] Numbers verbatim from K1214 / K1129 / K1133 / K1133b.
- [x] Fixed seed 42 referenced.
- [x] Worktree scope limited to `experiments/k1228/`.

## Strict constraints followed

- Only `.md` + `.json` output — no `.tex` written.
- Verbatim canonical numbers (full-sample DM t=-4.58, P1 DM t=-4.67, M4 vs M3 DM t=+2.67, MS vs M3 DM t=+5.97, MS vs M1 DM t=+0.28, ~75%/25% attribution).
- `docs/paper-guide.md` self-contained 5-item rule compliance folded into Phase 1 baseline commit.
- Three-way consistency (script ↔ data ↔ paper numbers) mandated via Phase 3 `reproduce.py`.
- Seed 42 referenced.
- Worktree only `experiments/k1228/` files produced.
- Shared state (`storage/memory/*.json`, `storage/reports/feed.json`, Supabase/Mirror sync) untouched per worktree rules.

## Next action

Main-thread reads `k1228_repo_init_guide.md`, presents 5 gate questions to user, collects answers, and proceeds with Phase 1 step 1.
