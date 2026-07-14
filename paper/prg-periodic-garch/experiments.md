# Paper 6: Supporting Experiments Index (v7)

**Paper**: Forecast-Timing Conventions and the Value of Overnight Information in Volatility Forecasting
**Journal**: Finance Research Letters (FRL)
**Status**: v7 rewrite complete (2026-07-14); reproduce gate GREEN 26/26; awaiting v7 review cycle
**Last Updated**: 2026-07-14

---

## Canonical experiments (v7 — the paper's ONLY quantitative sources)

| K | Title | Contribution | Path |
|---|-------|-------------|------|
| K1699 | Six-market Close-convention panel | Strict t−1 close: PRG vs GJR 0/6 Harvey (exp + lag plug-in variants agree); pinned snapshots (SHA256 recorded) + deterministic MLE + bit-identical two-pass; Codex PASS_WITH_CAVEAT | `experiments/k1699/` |
| K1710 | Open-convention + Mixed-anchor panels on K1699 pinned vintage | Open: PRG open-known vs fair GJR-X, all six positive, 5/6 Harvey (QQQ +1.56 NS); Mixed anchor: PRG canonical vs GJR 6/6 Harvey (+4.3..+6.4) — the reproducible version of the old headline object; OOS overnight-variance shares for the Data table; snapshot SHA equality with K1699 asserted at runtime; Codex PASS | `experiments/K1710/` |

Sign convention: both JSONs store DM t as *negative = PRG better*; the paper prints *positive = PRG better* (flip handled by `scripts/gen_flip_table.py` and verified by `reproduce.py`).

## Table / Figure → source mapping (v7)

| Object | Source |
|---|---|
| Table 1 (Data + ON shares) | K1699 `data_snapshots` (N, OOS periods) + K1710 `.markets.<M>.oos_overnight_variance_share` |
| Table 2 (flip table — the paper's centerpiece) | Close col: K1699 `.markets.<M>.dm_tests.PRG_tminus1_exp_vs_GJR`; Mixed col: K1710 `.markets.<M>.dm_tests.mixed_anchor_main`; Open col: K1710 `.markets.<M>.dm_tests.open_panel_main` |
| All prose numbers (ranges, spreads, rank-ordering) | Derived from the same JSONs; regenerate via `scripts/gen_flip_table.py`; asserted by `reproduce.py` (26 checks) |

v7 has no VaR/ES, no VT-economic, no Separate-GARCH, no HAR table — removed because their sources were unpinned drifted-vintage runs (see EXECUTION.md v7 decision record item 2; re-add path = pinned reruns, P1).

## Directional pilots (cited as design lineage, not as table sources)

| K | Role |
|---|---|
| K1544 (`experiments/k1544_prg_fair_info_gjr/`) | Discovered the fair GJR-X reversal + open-known recovery (unpinned 06-24 vintage; direction confirmed by K1710, point values differ — documented in paper Robustness ¶) |
| K880 rerun (2026-06-13) | SPY mixed-timing drift discovery (6.00→5.06) that triggered P0-1; superseded by K1710 mixed anchor |

## Legacy (pre-v7 manuscript sources; retained for history only)

K874c/d/e, K880/K880b/K880v2, K881/K881b, K883, K884, K886 — sources of the v6 tables (mixed-timing headline, MCS, VaR/ES, VT). All unpinned live-fetch era; none is cited by v7. Full line-by-line errata: `review_history/fable_deep_review_20260711/P0-1_errata_map.md`. Co-located scripts under `paper/prg-periodic-garch/experiments/` are that era's replication copies.
