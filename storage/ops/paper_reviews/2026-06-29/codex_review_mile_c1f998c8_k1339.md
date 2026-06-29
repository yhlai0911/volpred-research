# Codex 24h Review - mile_c1f998c8 / K1339

- **Article**: `mile_c1f998c8`
- **Task**: `paper_review_mile_c1f998c8`
- **Experiment**: `experiments/K1339/`
- **Review timestamp**: 2026-06-29 15:40 Asia/Taipei
- **Verdict**: **PASS FOR PUBLISHED FEED VERSION**

## Scope

Checked the published feed entry against:

- `storage/reports/feed.json` entry `mile_c1f998c8`
- `storage/reports/mile_c1f998c8.json`
- `experiments/K1339/K1339_results.json`
- `experiments/K1339/K1339.py`
- `experiments/K1339/README.md`
- `experiments/K1339/codex_review.md`

## Claim-Evidence Check

| Claim | Source evidence | Status |
|---|---|---|
| Data source yfinance adjusted close, ETFs USO/UNG/CPER/SPY, 2015-01-01 to 2026-06-14, 2,878 trading days | `data` block: `n_trading_days=2878`, `first_date=2015-01-02`, `last_date=2026-06-12` | Match |
| Momentum proxy is 21d vs 63d log-return slope and uses `prices.shift(1)` | `method.regime_proxy`; `K1339.py:88-105` | Match |
| Event confirmation: sustained 10 days, cross-window 21 business days, forward window starts at event_date+1 | `method`; `K1339.py:108-194`, `K1339.py:203-241` | Match |
| Event counts: cold-to-hot 52, hot-to-cold 43 | `events.contango_to_back_count=52`, `events.back_to_contango_count=43` | Match |
| CPER H=30 mean vol jump +18.0%, CI [+7.2%, +29.2%], bootstrap p=0.003, n=52 | `pooled_bootstrap.contango_to_back.30.CPER.vol_jump` | Match |
| UNG H=30 mean +10.0%, CI [-0.2%, +22.6%], p=0.079, n=52 | `pooled_bootstrap.contango_to_back.30.UNG.vol_jump` | Match |
| USO H=30 mean +6.9%, CI [-4.0%, +18.2%], p=0.227, n=52 | `pooled_bootstrap.contango_to_back.30.USO.vol_jump` | Match |
| CPER H=60 +7.0%, p=0.074; H=90 +4.3%, p=0.213 | `pooled_bootstrap.contango_to_back.60/90.CPER.vol_jump` | Match |
| CPER-SPY H=30 correlation change +0.038, CI [-0.032,+0.108], p=0.291 | `pooled_bootstrap.contango_to_back.30.CPER.dcorr_spy` | Match |
| No effect size cell has abs(mean) > 0.25 | `effect_hits_abs_gt_025=[]` | Match |
| Sign-flip null p=0.0026 for CPER H=30 | Not in `K1339_results.json`; recorded in `experiments/K1339/codex_review.md` as Codex cross-check | Supported by review artifact, not primary results JSON |

## Methodology

- Lookahead status is clean. `regime_state()` uses `prices.shift(1)`, the sustained filter returns the first date on which the 10-day confirmation is known, and post-event windows start at `event_loc + 1`.
- The published feed version correctly frames the signal as ETF momentum-regime switching rather than direct observation of futures backwardation/contango.
- The feed version accurately preserves the existing experiment-level downgrade: multiple testing, overlapping event windows, indirect proxy, and Python `hash()` seed instability.
- The code's bootstrap is iid paired resampling over event values with centered p-value logic, not block bootstrap. The article states this limitation.

## Overclaim Check

The published feed version has no material overclaim. It says the result is a candidate feature for future HAR/GARCH testing, not a standalone trading rule, and explicitly says it does not imply buying copper, buying volatility products, or SPY spillover.

The stale single-article file `storage/reports/mile_c1f998c8.json` is a problem: it still has `status="draft"` and an older title/content using stronger "期貨期限結構翻轉" wording. Since `feed.json` is canonical, this does not change the published feed verdict, but it exposed a sync-path risk.

## Action Taken

- Patched `scripts/supabase_sync.py` so incremental article sync no longer reads `storage/reports/<id>.json` to overwrite feed entry content. This prevents stale single report files from reviving older article text during Supabase sync.
- Added regression test `test_sync_full_ignores_stale_single_report_content` in `tests/test_supabase_sync_hash.py`.

## Recommendation

Keep the published feed article live as reviewed. Treat `storage/reports/feed.json` as the article source of truth and ignore stale single report files in sync paths; if single files remain in the tree, they should be considered non-canonical artifacts only.
