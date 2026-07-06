# Codex 24h Review - mile_4d67163f (K1633)

- Review date: 2026-07-06
- Reviewer: Codex CLI
- Task id: `paper_review_mile_4d67163f`
- Article id: `mile_4d67163f`
- Article status: `published`
- Linked experiment: `experiments/k1633`
- Evidence file: `experiments/k1633/k1633_results.json`

## Verdict

`PASS_AFTER_TEXT_FIX`

The article's numeric claims match K1633's stored results, and I found no source-code evidence of lookahead, apples-to-oranges baseline comparison, or DM/Harvey overclaim. One public-language issue was corrected during this review: the article described three cells as passing the "strictest" screen, while K1633's own multiple-testing synthesis says no cell survives BH-FDR at 5%; three cells survive only at FDR 10%.

## Correction Applied

I updated `storage/reports/feed.json` for `mile_4d67163f` to qualify the multiple-comparison language:

- Replaced table labels saying `通過最嚴格把關` with `10% 多重比較保留；5% 不保留`.
- Changed the text from "3 cells truly hold up" to "3 cells remain under 10% FDR, but none survive 5% FDR."
- Reframed the 60-day result as a directional quarterly reversal clue rather than a strict trading signal.
- Added an errata entry with action `codex_24h_statistical_language_fix`.

The correction changes interpretation strength only. It does not change the article's reported numbers.

## Number Checks

| Article claim | Evidence field | Stored value | Review |
|---|---:|---:|---|
| Period 1993-01-29 to 2026-07-02; 8,413 trading days | `data.period`; `data.n_trading_days` | 1993-01-29 .. 2026-07-02; 8413 | OK |
| VIX>=30 event count | `events.30.n_events_raw_decluster` | 50 | OK |
| VIX>=35 event count | `events.35.n_events_raw_decluster` | 25 | OK |
| VIX>=40 event count | `events.40.n_events_raw_decluster` | 17 | OK |
| Baseline win rates H5/H10/H20/H60 | `baseline.<H>.win_rate` | 58.8%, 61.9%, 65.4%, 71.9% | OK |
| VIX>=30 H5 excess / win delta / n | `events.30.horizons.5` | +1.2605%; +11.187pp; n=50 | OK |
| VIX>=30 H60 excess / win delta / n | `events.30.horizons.60` | +2.5532%; +2.1456pp; n=50 | OK |
| VIX>=35 H60 excess / win delta / n | `events.35.horizons.60` | +4.8859%; +12.1456pp; n=25 | OK |
| VIX>=40 H60 excess / win delta / n | `events.40.horizons.60` | +6.1937%; +16.3809pp; n=17 | OK |
| 11 of 12 cells have positive excess | `verdict.multiple_testing.n_cells_positive_excess` | 11 | OK |
| FDR 5% survivors | `verdict.multiple_testing.bh_fdr_0.05_survivors` | [] | Corrected in article |
| FDR 10% survivors | `verdict.multiple_testing.bh_fdr_0.10_survivors` | thr30_H5, thr35_H60, thr40_H60 | Corrected in article |

## Lookahead and Alignment Audit

K1633 defines a VIX crossing event as `v[t-1] < threshold <= v[t]`, then computes lag0 forward returns as `SPY[t+H] / SPY[t] - 1`, keeping only events with a complete future window. That is a same-close event study, not a forward-tradable signal, but the article frames the result as historical conditional evidence rather than live trading alpha.

The script also stores an entry-lag robustness variant using `entry_lag=1`, equivalent to entering at the next close after the signal. This is enough for the article's descriptive framing. The article should not be upgraded to a live trading rule without a separate cost-aware out-of-sample strategy test.

## Statistical Framing Audit

The main inference is HAC/Newey-West over the full forward-return series with an event dummy and `maxlags = H`, which is appropriate for overlapping forward windows. K1633 also stores random-entry placebo checks and lag1 robustness. The article does not claim DM/Harvey forecast superiority, strategy alpha, or risk-adjusted portfolio dominance.

The only issue was rhetorical strength around multiple testing. K1633's strict FDR-5% conclusion is null at the individual-cell level, while FDR-10% leaves three cells. The corrected article now states that distinction.

## Conclusion

After the text fix, the production article is aligned with K1633: the myth verdict is `half_true_qualified`, not a confirmed trading signal. No further correction is required from this review.
