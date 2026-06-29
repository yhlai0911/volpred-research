# Codex 24h Review - mile_190c7e3c / K566

- **Article**: `mile_190c7e3c`
- **Task**: `paper_review_mile_190c7e3c`
- **Experiment**: `experiments/k566/`
- **Review timestamp**: 2026-06-29 16:55 Asia/Taipei
- **Verdict**: **CONDITIONAL_PASS AFTER CAVEAT**

## Scope

Checked the published feed entry against:

- `storage/reports/feed.json` entry `mile_190c7e3c`
- `storage/drafts/k566_general_draft.md`
- `experiments/k566/k566_factor_timing_vt_results.json`
- `experiments/k566/k566_factor_timing_vt.py`
- `experiments/k566/README.md`

## Claim-Evidence Check

| Claim | Evidence | Status |
|---|---|---|
| Assets are SPY, VLUE, MTUM, QUAL, IWM, USMV, GLD, VIX | `results.assets` | Match |
| Period is 2014-03-28 to 2026-03-27, n=3,018 trading days | `results.period`, `results.n_days` | Match |
| Benchmark SPY VT+GLD Sharpe is 1.545 | `full_sample_results.benchmark_spy_vt_gld.sharpe=1.5451` | Match |
| Best monthly variant is static QUAL with Sharpe 1.514 | `full_sample_results.static_qual.sharpe=1.5139` | Match |
| No monthly factor strategy beats benchmark | all monthly full-sample Sharpes are below 1.5451 | Match |
| Daily top-1 momentum Sharpe is 2.091 and daily-monthly gap is 0.642 | `daily_vs_monthly_comparison.daily_mom_sharpe=2.0905`, `artifact_gap=0.6424` | Match |
| Cross-OOS QUAL vs benchmark: 1.926 vs 1.940; 0.924 vs 0.952; 2.219 vs 2.271 | `cross_oos_results` | Match |
| No monthly strategy passes Harvey-style t > 3 gate | `harvey_pass=false`; all monthly `dm_tests.*.harvey_pass=false` | Match |

## Methodology Findings

1. **Lookahead violation in source code**: `df_analysis['vt_weight'] = 12/VIX` is used on the same row as that day's returns (`K566.py:216`, `K566.py:272-324`). A tradable volatility-targeting rule must use prior close VIX, e.g. `vt_weight.shift(1)`.
2. **Monthly factor selection is not truly next-month aligned**: rolling momentum sums use same-day returns (`K566.py:183`, `K566.py:188`), month-end selection is updated at `date in rebal_dates`, and the new selection is immediately applied to that same day's return (`K566.py:287-324`). The article says "月底決定下個月", but code includes the rebalance day's close-to-close return in both the signal and the realized payoff.
3. **The published conclusion is conservative despite the bug**: even the biased, pre-lag version fails to beat the benchmark on monthly factor variants. This supports a cautious null takeaway, but the exact Sharpe/DM values are not lag-clean evidence.
4. **Reproducibility weakness**: `README.md` is a placeholder and the script writes to a relative path `experiments/k566_factor_timing_vt_results.json`, not the committed `experiments/k566/k566_factor_timing_vt_results.json`, so rerun provenance is weaker than current experiment standards.

## Action Taken

- Updated `storage/drafts/k566_general_draft.md` with a top-of-article Codex caveat.
- Updated `mile_190c7e3c` via `scripts/publish_draft.py --update` with errata action `codex_24h_review_caveat`.
- Full `feed-sync --apply` hung after local write, so it was interrupted. Synced the single article through `scripts.supabase_sync.sync_article()`.
- Read back Supabase `articles` row and confirmed `status=published` and `remote_has_caveat=true`.

## Recommendation

Do not cite K566 as a formal lag-clean strategy result until a rerun explicitly lags both VIX weights and factor selection signals. The current public article is acceptable only as a caveated null-result explainer: "even under a favorable pre-lag audit, monthly factor rotation did not beat the simple benchmark."
