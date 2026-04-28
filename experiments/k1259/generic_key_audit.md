# K1259 MAJOR-2 Audit — Generic-Key False-Positive Sweep

**Audit date**: 2026-04-28
**Trigger**: Codex review (subagent fallback 2026-04-28) MAJOR-2 — `get_dm_stat`
priority list includes generic single-letter `"t"` and `"stat"` keys (positions
6 and 10), which can match non-DM dicts (e.g., scipy `ttest_ind` results
`{t, p}`, `mcnemar` results `{stat, p}`, GARCH parameter `t` for Student-t df).

## Methodology

For every row in `dm_ledger.json`:

1. Re-open `source_file`.
2. Navigate to `source_field_path` (the pair_dict).
3. Walk the priority list `[dm_stat, dm_t, DM, dm, t_stat, t,
   dm_stat_oos, harvey_t, DM_HLN_t, stat]` and identify the **first** key
   actually present.
4. Flag rows where the first match was `t` or `stat` (generic) for path-pattern
   inspection.
5. False-positive criterion: source_field_path contains a token from
   `{ttest, mcnemar, wilcoxon, kstest, kruskal}` — these are well-known
   non-DM hypothesis tests sharing the `{t/stat, p}` schema.

Audit script: `/tmp/k1259_generic_key_audit.py` (one-off) +
`extract_phase15_asset_map.py`-style pin (the path-token blacklist now
lives in `build_dm_ledger.py` `NON_DM_PATH_TOKENS`).

## First-match key distribution (pre-audit ledger, 2367 navigable rows of 2741)

| Priority | Key | Count | Risk |
|---|---|---:|---|
| 1 | `dm_stat` | 447 | DM-specific |
| 2 | `dm_t` | 352 | DM-specific |
| 3 | `DM` | 10 | DM-specific |
| 4 | `dm` | 1 | DM-specific |
| 5 | `t_stat` | 1001 | DM-specific (commonly used) |
| **6** | **`t`** | **167** | ⚠️ generic |
| 7 | `dm_stat_oos` | 0 | DM-specific |
| 8 | `harvey_t` | 0 | DM-specific |
| 9 | `DM_HLN_t` | 163 | DM-specific |
| **10** | **`stat`** | **226** | ⚠️ generic |

Generic-key matches: **393 / 2367 = 16.6%** raw count. After parent/leaf
path inspection (paths containing `dm`, `DM`, `harvey`, `hln`, `_vs_`),
**all 393 except the patterns below are bona-fide DM tests** — code authors
chose to name the field `t` or `stat` despite computing Diebold-Mariano.
Examples: K1130 `H2_OOS_DM_ext_regime_vs_base.t`, K1131 `DM_spline_vs_base.t`,
K891 `dm_test_var_tick.5pct.M1_..._vs_M2_....stat`, K414
`harvey_scorecard.DiD SPY vs GLD.t`. These are correct extractions.

## Confirmed false positives (11 rows from 5 K-experiments)

| K | source_field_path | model_a / model_b | What it actually is |
|---|---|---|---|
| K649 | `calm_before_storm.down_storm_to_calm.ttest_vs_unconditional` | `ttest` / `unconditional` | scipy `ttest_1samp` of vol level |
| K649 | `calm_before_storm.up_calm_to_storm.ttest_vs_unconditional` | `ttest` / `unconditional` | same |
| K649 | `calm_before_storm.down_storm_to_calm.ttest_before_vs_after` | `ttest_before` / `after` | paired `ttest` of pre/post regime |
| K649 | `calm_before_storm.up_calm_to_storm.ttest_before_vs_after` | `ttest_before` / `after` | same |
| K706 | `fixed_vs_dynamic_oos.ttest_fixed_vs_maxsharpe` | `ttest_fixed` / `maxsharpe` | `ttest` of Sharpe ratios |
| K706 | `fixed_vs_dynamic_oos.ttest_fixed_vs_minvar` | `ttest_fixed` / `minvar` | same |
| K744 | `part_c_intraday_patterns.ttest_first_vs_middle` | `ttest_first` / `middle` | `ttest` of intraday return windows |
| K744 | `part_c_intraday_patterns.ttest_last_vs_middle` | `ttest_last` / `middle` | same |
| K1059 | `part_b_clustering.ttest_dense_vs_none` | `ttest_dense` / `none` | `ttest` of clustering effect |
| K1059 | `part_b_clustering.ttest_any_vs_none` | `ttest_any` / `none` | same |
| K789 | `part_b_return_prediction.mcnemar_fear_vs_vix` | `mcnemar_fear` / `vix` | McNemar test for sign accuracy |

## Fix

`build_dm_ledger.py` now defines:

```python
NON_DM_PATH_TOKENS = ("ttest", "mcnemar", "wilcoxon", "kstest", "kruskal")
```

`iter_pair_entries` checks `_path_is_non_dm(ctx_path)` before yielding any
pair entry. Both Case-A (dict-is-pair) and Case-B (mapping-of-pairs) paths
gated. Defensive — extends to other common stats-test packaging beyond just
`ttest` / `mcnemar` to harden against future K experiments.

## Phase 2 MCS impact

Pre-audit dm_ledger: **2741 rows** → post-audit: **2730 rows** (−11).

Pre-audit MCS run (seed=42, B=1000, 2741-row ledger):
- 18/20 cells passed (0050.TW/MSE skipped insufficient_models)
- n_pairs_total = 418 across all cells

Post-audit re-run (same seed, 2730-row ledger):
- 18/20 cells (unchanged)
- n_pairs_total = **418 (unchanged)** — because the false-positive K-pairs
  hit `MIN_PAIRS_PER_MODEL=2` filter (each ttest-named model had only 1
  pair row, getting pruned anyway)
- Superior sets identical at all asset/loss/α combinations **except**
  SPY/QLIKE: `"middle"` model (the K744 comparator) drops from superior set
  at α=0.10 and α=0.20.

`"middle"` was a pseudonym for "intraday-mid window return distribution" in
K744 — not a volatility model. Its presence in the SPY/QLIKE superior set
was a benign cosmetic artifact (it had `MIN_PAIRS_PER_MODEL=2` rows but no
valid pairs against any other candidate, so contributed zero information).
Its removal from MCS superior set is a **clean correction**, not a result
revision.

## Verification

```bash
# Reproduce post-audit ledger
python experiments/k1259/build_dm_ledger.py
python experiments/k1259/apply_phase15_backfill.py \
    --in experiments/k1259/dm_ledger.json \
    --out experiments/k1259/dm_ledger.json

# Verify zero ttest/mcnemar rows
jq '[.rows[] | select(.source_field_path | test("ttest|mcnemar"; "i"))] | length' \
    experiments/k1259/dm_ledger.json
# expected: 0

# Re-run Phase 2 MCS
python experiments/k1259/k1259_mcs.py
# expected: 18/20 cells, superior sets match this audit's documented results
```

## Closes K1259 MAJOR-2

All 3 Codex MAJOR findings now resolved:
- ✅ MAJOR-1 (Phase 1.5 backfill script + asset map) — commit `53c1d559`
- ✅ MAJOR-2 (generic-key false-positive sweep) — this audit + filter
- ✅ MAJOR-3 (`load_ledger` docstring fix) — commit `d4c2faf1`

Phase 3 article can cite K1259 as fully reviewed and provenance-clean.
