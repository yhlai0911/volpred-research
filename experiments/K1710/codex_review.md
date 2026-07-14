# K1710 Codex Review

- Reviewer: Codex CLI `codex-cli 0.144.1`, default model `gpt-5.6-sol` (ultra reasoning), read-only sandbox
- Invocation: `bash scripts/codex_exec_bounded.sh --timeout N -s read-only --skip-git-repo-check -` (bounded wrapper; bare `codex exec` is blocked by policy)
- Target: `experiments/K1710/K1710.py`
- Focus: lookahead / information set, refit boundary, QLIKE direction, DM orientation, formula + TAIFEX alignment

## Round 1 — OVERALL VERDICT: FAIL (computation sound, metadata inconsistent)

| Item | Area | Verdict |
|---|---|---|
| 1 | Lookahead / information set | **PASS** — `h_ov` uses only `t-1` state; `h_in_c` / open-known add only day-d realized overnight `r2_overnight[t]`, never `r_c2c[t]`, intraday return, or `target[t]`. FairGJRX uses `r_c2c[t-1]` + `r2_overnight[t]`; GJR uses `return[t-1]` only. TAIFEX `h_ov ∈ F_{d-1}`, `h_in_c` reads day-d overnight session. |
| 2 | Refit boundary / stale state | **PASS** — every PRG/GJR-X/GJR fit trains on `[:t]` (strictly before origin). On a failed scheduled refit the state still advances one day (inherits K1699's fix), never stalling at `F_{t-2}`. |
| 3 | QLIKE direction | **PASS** — canonical `volpred qlike_pointwise(target, forecast)` = `a/f - log(a/f) - 1`; no reverse/local QLIKE. |
| 4 | DM computation + orientation | **FAIL** — DM math correct (canonical `dm_test`, `d = loss_a - loss_b`, neg t = A better), but three **documentation/metadata** contradictions (below). |
| 5 | Formula + TAIFEX alignment | **PASS** — canonical vs open-known differ only in the first full-day term (shared `h_in_c`); TAIFEX overnight=2d / intraday=2d+1 verified against the pinned snapshot (4214 sessions = 2×2107 days, strict 0/1 alternation, session x == daily columns). Suggested adding defensive alignment asserts. |

### Round-1 findings (all item 4/5, no computation bug)

- **4a** docstring said the mixed-timing DM was "+5" without stating orientation, ambiguous against K1710's PRG-first (negative = PRG better) convention.
- **4b** JSON key `k880_spy_canonical_vs_gjr_dm_t_positive_prg_better` was self-contradictory (canonical-minus-GJR positive should favour GJR, not PRG).
- **4c** hardcoded anchor `5.06`, while the checked-in `k880_results.json` stores `GJR_vs_PRG_Extended = +6.4537` (a different vintage) — provenance unclear.
- **5** (suggestion) add TAIFEX session-alignment asserts to prevent silent 2d/2d+1 misalignment on future data swaps.

## Fixes applied

- **4a** Docstring rewritten to state the orientation explicitly: legacy GJR-vs-PRG t ~ +5 to +6 (PRG better) maps to a large **negative** mixed-anchor t under K1710's standardised PRG-first `dm_cell(PRG, baseline)` convention.
- **4b** Removed the misleading key. `anchor_validation.mixed_anchor_vs_k880_spy` now exposes `k880_gjr_vs_prg_extended_t_positive_prg_better` and `k880_prg_first_equivalent_t_negative_prg_better`, plus `direction_matches_k880` — direction-only, both orientations named.
- **4c** Added `read_k880_spy_anchor()`, which reads `layer5_dm_tests.GJR_vs_PRG_Extended.t_stat` from the pinned `paper/prg-periodic-garch/experiments/k880_results.json` at runtime (no hardcode), records `source_file` / `source_key` / both orientations, and notes the 2026-06-13 rerun (~+5.06) as a directional prior across vintages. `relation_to_prior.K880` also disambiguated (+5.06 rerun vs +6.4537 artifact; both = PRG better).
- **5** Added asserts in `taifex_canonical_and_open()`: `n_sessions == 2*n_days`, strict 0/1 session-type alternation, and `x_arr[::2] == daily x_overnight`. The full run passed all three (exit 0).

## Round 2 (re-review of fixes) — OVERALL VERDICT: PASS_WITH_CAVEAT

- 4a — PASS (docstring orientation explicit)
- 4b — PASS (old key gone; new fields name both orientations)
- 4c — PASS (reads pinned artifact `GJR_vs_PRG_Extended = 6.4537`, records provenance + rerun directional note)
- 5 — PASS (three alignment asserts present)
- Residual caveat: `relation_to_prior.K880` still cited "+5.06" without disambiguation → **fixed after round 2** (now labels +5.06 as the 2026-06-13 rerun directional value vs the +6.4537 checked-in artifact, both PRG-better, pointing to `anchor_validation` for provenance). No remaining computation or metadata contradiction.

## Net verdict

**PASS.** No lookahead, correct refit boundary, canonical QLIKE and DM, matching baseline lag. All round-1/round-2 findings were documentation/metadata (not computation) and are resolved. Internal consistency independently confirms correctness: K1710's `PRG_canonical_mixed` and `GJR` OOS QLIKE reproduce K1699's `PRG_canonical_diag` / `GJR` on the same pinned vintage to full precision (e.g. TAIFEX 0.120932 exact; SPY canonical 0.746933, GJR 0.853368).
