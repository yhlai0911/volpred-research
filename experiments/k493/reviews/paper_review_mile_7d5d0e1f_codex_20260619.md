# K493 / mile_7d5d0e1f Codex 24h Publication Review

- Article: `mile_7d5d0e1f` — "VIX 報的是恐慌，不是真實波動——有辦法同時吸收兩者的優點嗎？"
- Source experiment: `experiments/k493/`
- Reviewed files: `k493_signal_comparison.py`, `k493_signal_comparison_results.json`, `storage/reports/feed.json`
- Verdict: **CONDITIONAL_PASS_AFTER_PATCH**
- Reviewer: Codex
- Review date: 2026-06-19

## Bottom Line

The article's headline numbers trace to `experiments/k493/k493_signal_comparison_results.json`: 559 analysis days, MZ RV5 R2 values `0.4716 / 0.3475 / 0.6143`, VIX-GJR-X correlation `0.9632`, GJR-X higher-than-VIX weight on `98.39%` of days, and the three event-window means all match the stored result file.

I patched the article language because two source-level caveats were not visible enough:

1. K493's `actual_rv5` target is a trailing/current realized-variance proxy ending at the evaluated day, not a clean future 5-day target.
2. The pure GJR baseline is not updated symmetrically between 21-day refits, while GJR-X is manually propagated daily. This makes the `35%` pure-GJR comparison useful as a descriptive control, but too weak to support the original "75% better than pure GARCH" headline-strength wording.

After the patch, the publication claim is narrowed to: **GJR-X(VIX9D) tracks the same realized-vol proxy better than VIX-implied volatility over this 2024-2026 window, and that better statistical signal still should not be sold as a better VT strategy.**

## Claim-Evidence Match

| Article claim | JSON / code source | Status |
|---|---:|---|
| Analysis period 2024-01-02 to 2026-03-25 | `analysis_period` | PASS |
| `n=559` trading days | `n_analysis=559` | PASS |
| VIX-implied RV5 R2 around `47%` | `mincer_zarnowitz_rv5_target.VIX-implied.R2=0.47165` | PASS |
| Pure GJR RV5 R2 around `35%` | `mincer_zarnowitz_rv5_target.GJR.R2=0.34750` | CONDITIONAL |
| GJR-X(VIX9D) RV5 R2 around `61%` | `mincer_zarnowitz_rv5_target.GJR-X(VIX9D).R2=0.61433` | PASS |
| VIX vs GJR-X correlation `0.963` | `signal_correlations.pearson.vix_gjrx=0.96319` | PASS |
| GJR-X weight higher than VIX `98.4%` of days, mean diff `22pp` | `vt_weight_analysis` | PASS |
| Event table values | `market_events` | PASS |
| Earlier VT strategy result: better forecast does not improve strategy return | K488 / K1074 knowledge support | PASS as a broad thesis |

## Lookahead / Timing Audit

No same-day signal leak found for the main VIX and GJR-X signals:

- VIX signal uses `vix_var_all[t-1]`.
- GJR-X daily recursion uses `returns_all[t-1]` and `vix9d_var_all[t-1]`.
- Model fits use `returns_all[window_start:t]` and `vix9d_var_all[window_start:t]`.

The article now avoids describing the RV5 table as a forward 5-day forecast. In code, `actual_rv5[i] = np.var(returns_all[t-4:t+1])`, so the target includes the current day plus the prior four days.

## Methodology Caveats

### Pure GJR baseline asymmetry

In `k493_signal_comparison.py`, GJR-X is rolled forward daily between refits:

- update shock from `returns_all[t-1]`
- update variance state with `h_new`
- append `h_new` to `last_gjrx_res['h_series']`

The pure GJR branch calls `last_gjr_res.forecast(horizon=1, reindex=False)` on the last fitted result object on every non-refit day. It does not append new returns or recursively update the conditional variance state between monthly refits. That can make the pure GJR baseline stale and weakens any strong claim about GJR-X being `75%` better than pure GARCH.

### DM wording

K493 includes two QLIKE DM comparisons: GJR-X vs VIX-implied and GJR-X vs GJR. The original article called them "two strict statistical tests." That wording was too strong because they are two pairwise comparisons in one experiment, not independent test designs, and the implementation is a hand-rolled HAC-normal DM rather than the project canonical helper / HLN small-sample correction. The patched article removes that overstatement.

### Mechanism wording

The original article said GJR-X "removes" the VIX risk premium. K493 does not estimate or decompose a variance-risk-premium component. It only compares VIX, VIX9D, and GARCH-X signals. The patched article says GJR-X reduces reliance on the 30-day VIX path rather than claiming VRP removal.

## Reproducibility Issues

- `experiments/k493/README.md` is a placeholder and should be replaced with methods/results.
- The script's hard-coded output path is `experiments/k493_signal_comparison_results.json`, not `experiments/k493/k493_signal_comparison_results.json`. A fresh run from repo root would write outside the experiment folder.
- The existing result file is usable for source review, but the experiment is not one-command reproducible until the output path and README are fixed.

## Actions Taken

- Rewrote the article through `scripts/publish_draft.py --update`.
- Added an audit-trail errata entry with action `codex_review_fix`.
- Added this review file under `experiments/k493/reviews/`.

## Verdict

`CONDITIONAL_PASS_AFTER_PATCH`.

The patched article's numeric claims match K493, the main VIX/GJR-X timing is lag-clean, and the language now discloses the RV5 target and baseline limitations. Do not reuse the original stronger claims that GJR-X is definitively `75%` better than pure GARCH or that K493 proves VIX risk-premium removal.
