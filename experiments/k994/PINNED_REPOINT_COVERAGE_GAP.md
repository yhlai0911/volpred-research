# K994 pinned-snapshot repoint — coverage gap (2026-07-27)

Part of task `k892_k994_pinned_snapshot_repoint_20260721`. The **k892 half is done and
verified** (see `experiments/k892/k892_verify_tw_gamma.py` — 0050.TW now reads the pinned
`0050_tw_adj_close` column and reproduces gamma=0.097042 / t=3.5965 / n_obs=4219
byte-for-byte). The **k994 half is blocked by a data-coverage gap** and needs a decision
before the loader can be repointed.

## The gap

- `experiments/k994/k994.py` sets `DATA_START='2005-01-01'`, `DATA_END='2026-04-08'`,
  `OOS_START='2019-01-01'`, window=2000, `REFIT_EVERY=63` (quarterly).
- The paper-cited number is **0050.TW DM t=1.44** (`paper/garch-x-vix/main.tex:531`,
  `= |−1.4388|` from `k994_results.json .assets["0050.TW"].dm_tests["A4f_vs_GJR"]`), an
  **OOS statistic over 2019-01-01 … 2026-04-08**.
- The 0050.TW pinned snapshot that ships with garch-x-vix is
  `paper/garch-x-vix/data/0050_tw_vix_2007-2022.csv` — it **ends in 2022**. It therefore
  does **not** cover the 2019–2026 OOS window that produced DM t=1.44. Repointing k994's
  0050.TW loader to this CSV would truncate the OOS sample to 2019–2022 and change the
  cited statistic.

## Column/vintage recipe (already solved, reusable)

The k892 half established that the reproducible input is the **`*_adj_close`** column
(yfinance `auto_adjust=True` makes `df['Close']` adjusted), truncated to the original run's
`end` (yfinance `end` is exclusive). The same recipe applies to k994's other assets whose
pinned CSVs cover the run window:
- SPY/QQQ/EEM/FEZ/VIX → `spy_vix_qqq_eem_fez_2000-2026.csv` (`*_adj_close`), covers to 2026.
- GLD/GVZ/VIX → `gld_vix_gvz_2000-2026.csv` (`*_adj_close`), covers to 2026.
- 0050.TW/VIX → `0050_tw_vix_2007-2022.csv` — **short**; this is the blocker.

## Decision needed (owner/reviewer)

One of:
1. **Extend the 0050.TW pinned snapshot to 2026-04-08** (re-snapshot `0050.TW` + `^VIX`
   adjusted-close through the run end) and then repoint + verify DM t≈1.44 reproduces.
2. **Restate the paper's 0050.TW OOS window to end 2022** in the pinned data and re-run,
   accepting a revised (smaller-sample) DM statistic for that row.
3. Keep 0050.TW on live yfinance for the post-2022 tail with an explicit, documented
   caveat (weakest — leaves the reproducibility defect for that one row).

Options 1 and 2 both need a bounded k994 OOS re-run (quarterly-refit backtest — route
through `compute_queue`, not a live fire). The non-0050 assets can be repointed with the
recipe above independently and reproduce from their 2026-covering snapshots.
