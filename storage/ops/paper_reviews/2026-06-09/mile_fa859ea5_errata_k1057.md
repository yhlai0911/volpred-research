# Errata — mile_fa859ea5 / K1057

- Article: `mile_fa859ea5`
- Experiment: `K1057`
- Applied at: 2026-06-09
- Reason: Codex follow-up amend after source-code review

## What changed

1. BN-S jump test was re-implemented using the canonical relative z-statistic.
2. K1057 is now pinned to the original 60-day sample (`2026-01-14` to `2026-04-10`) so later intraday files do not drift the result.
3. Daily SPY/VIX loading now falls back to a local cached series when live `yfinance` is unavailable.
4. QLIKE was updated to the canonical Patton-style form.
5. README / report metadata now clarify that:
   - Spearman uses the 30-day common OOS window.
   - DM uses HAC variance and is not Harvey (1997) small-sample correction.

## Old vs new headline-sensitive numbers

| Metric | Old published text | Amended result |
|---|---:|---:|
| Significant jump days | 8/60 (13.3%) | 4/60 (6.7%) |
| Max BN-S z-stat | 12.59 | 2.64 |
| Max-z date | 2026-01-30 | 2026-02-09 |
| Overnight variance share | 32.7% | 33.0% |

## What did not change

- Core NULL claim still holds: HAR-RV-J does not beat HAR-RV.
- HAR-RV-J vs HAR-RV DM remains non-significant on both RV and `r^2` proxies.
- HAR-series Spearman on RV remains negative in the 30-day OOS window.
- Article remains `PRELIMINARY`; no retraction required.

## Files updated

- `experiments/k1057/k1057.py`
- `experiments/k1057/k1057_results.json`
- `experiments/k1057/README.md`
- `storage/reports/feed.json` (`details.errata`)
