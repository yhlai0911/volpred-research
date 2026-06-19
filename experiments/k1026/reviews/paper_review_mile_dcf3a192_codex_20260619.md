# K1026 / mile_dcf3a192 Codex 24h Publication Review

- Article: `mile_dcf3a192` - "少做一點假設，反而更接近真實風險"
- Task: `paper_review_mile_dcf3a192`
- Source experiment: `experiments/k1026/`
- Reviewer: Codex
- Review date: 2026-06-19
- Verdict: **PASS with source caveats**

## Bottom Line

The published article is supported by the committed K1026 artifacts. The reader-facing claims about conformal VaR improving calibration, preserving 2.5% VaR scorecards, narrowing the VIX-regime calibration gap, and paying a wider-VaR sharpness cost match `k1026_results.json`.

No public correction, retraction, or result change is required. K1026 should not be promoted into a formal paper result without first tightening two source-level details documented below.

## Claim-Evidence Match

| Article claim | Source check | Status |
|---|---:|---|
| The test compares 5 VaR methods on SPY OOS from 2013 to 2026 | `metadata.asset = SPY`, `metadata.oos_start = 2013-01-02`; methods M1-M5 are present in `var_eval` | PASS |
| Overall pass rates are 58%, 58%, 83%, 92%, 92% | Core 4-test totals are M1 7/12, M2 7/12, M3 10/12, M4 11/12, M5 11/12 | PASS |
| At 2.5% VaR, conformal methods are 6/6 | `M4_Conformal_GJR["0.025"].scorecard = 6/6`; `M5_Conformal_A4f["0.025"].scorecard = 6/6` | PASS |
| Traditional methods miss more in the tail | M1 2.5% violation rate 3.506%, M2 3.386%, M3 3.057% vs target 2.5% | PASS |
| Conformal methods are closer to target coverage | M4 2.556%, M5 2.708% at the 2.5% VaR level | PASS |
| VIX-regime gap improves | M1 high-low gap 5.084pp; M4 2.919pp; M5 2.615pp | PASS |
| The cost is wider VaR | At 2.5%, M4 avg `|VaR|` 0.02000 vs M2 0.01809, about 10.5% wider; M5 0.01946 vs M3 0.01811, about 7.4% wider | PASS |
| Sample counts differ by method | Results use T=3337 for parametric methods and T=3287 for conformal methods, matching the article's stated 3,287 to 3,337 trading days | PASS |

## Lookahead / Timing Audit

No lookahead issue was found.

- GJR OOS forecasts fit on `returns[s:t]`, excluding the target-day return, then forecast day `t` from `returns[t-1]`.
- A4f OOS forecasts fit on `returns[s:t]` and `vix2[s:t]`, then forecast day `t` from `vix2[t-1]` and `returns[t-1]`.
- Conformal VaR uses standardized residuals from `t-cal_window` through `t-1`; the current target return is excluded.
- The generic `scripts/lookahead_audit.py` scan does not flag `experiments/k1026/k1026.py`.

This satisfies the project convention for forecast information: signal and risk inputs are available before the target return is evaluated.

## Statistical Claims

The article does not use DM or Harvey claims. That is acceptable here because this is not a mean-forecast or strategy-return comparison; it is a VaR/ES calibration exercise. The relevant tests are Kupiec UC, Christoffersen CC, DQ, Basel traffic-light status, and Acerbi-Szekely ES checks.

The public article is appropriately framed for a general audience. It states that conformal methods are more reliable in this SPY test, but still notes the sharpness cost and does not claim the method is perfect or cross-asset-proven.

## Source Caveats

These are not public-article blockers, but they matter before K1026 is reused as formal evidence.

1. The DQ test currently receives `sigma_gjr` for every method:

   `eval_res = var_es_evaluation(..., sigma_arr=sigma_gjr)`

   For A4f methods, the DQ conditioning variable should be method-specific sigma or an explicitly documented common proxy. A no-write sensitivity run through the original `2026-04-09` cutoff showed the reported pass-rate ranking is not overstated by this issue; using method-specific sigma preserves the article's core conclusions and, if anything, makes `M5_Conformal_A4f` look slightly stronger.

2. Conformal VaR is described as a 252-day calibration window, but the implementation starts once at least 50 valid residuals exist during the OOS warm-up. The article's stated sample count range is consistent with this implementation, so the public numbers are transparent. Future technical writing should call this a 252-day rolling window with a 50-observation warm-up, or require a full 252 valid residuals and rerun the scorecard.

Both caveats are source-specification issues, not evidence of fabricated or unsupported article numbers.

## Reproducibility / Provenance

K1026 has the required experiment triad:

- `experiments/k1026/README.md`
- `experiments/k1026/k1026.py`
- `experiments/k1026/k1026_results.json`

The top-level K1026 source and result files are byte-identical to the nested `experiments/k1026/k1026/` copies. The stored result metadata records yfinance as the data source, `seed=42`, OOS start `2013-01-02`, and result date `2026-04-10 17:32`.

I did not rerun `run_experiment()` because it rewrites result JSON and plots and would use a fresh vendor pull. Instead, I ran non-writing sensitivity snippets that imported the experiment functions, truncated data to the original result cutoff, and compared the source caveats above.

## Verification

- `uv run python -m py_compile experiments/k1026/k1026.py` passed.
- `uv run python scripts/lookahead_audit.py --json` reported no K1026 finding.
- JSON checks confirmed the article's pass rates, 2.5% scorecards, violation rates, VIX-regime gaps, sharpness cost, and sample counts.
- Non-writing sensitivity checks confirmed that the DQ sigma caveat does not create a public overclaim.

## Verdict

`PASS with source caveats`.

The public article can remain published. K1026 should be tightened before being used as paper-grade evidence or as a base for future conformal VaR experiments.
