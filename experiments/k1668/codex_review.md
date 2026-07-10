# K1668 Codex Review

Verdict: `PASS_NULL_RESULT`

Reviewed files:

- `experiments/k1668/K1668.py`
- `experiments/k1668/K1668_results.json`
- `experiments/k1668/README.md`

## Checks

- Lookahead: PASS. The design constructs raw monthly RV/CPU features first, then explicitly applies `signal = raw_signal.shift(1)`. Target month `t` therefore uses features through `t-1`.
- OOS training discipline: PASS. Forecast row `i` is fit with `work.iloc[:i]`; the target row is excluded from training.
- Randomness: PASS. `SEED = 42` is fixed. The main OLS fits are deterministic.
- Data provenance: PASS. CPU is downloaded from the official GKRS GitHub raw file; the GCPU proxy comes from the public policyuncertainty.com multi-country CPU CSV; prices come from yfinance adjusted closes and are cached.
- QLIKE/DM direction: PASS. The script calls `qlike_pointwise(actual, predicted)` and tests `dm_test(challenger_loss, base_loss, h=1)`, so negative DM t means the challenger is better.
- Cross-asset inference: PASS. Overall and sector tests average losses by month before DM, avoiding asset-month iid pooling.
- Results JSON integrity: PASS. The writer uses tmp JSON, parses it, then `os.replace`.
- Null-result honesty: PASS. README and results report that HAR+CPU worsens QLIKE overall and in most assets/sectors.

## Main Audit Numbers

- U.S. CPU overall date-clustered QLIKE improvement: -2.489%, DM t=+1.564, p=0.120.
- Sector improvements: energy -1.515%, agriculture -2.866%, metal -2.876%; no Harvey pass.
- Asset improvements: USO -0.999%, UNG -2.469%, DBA -3.307%, CORN -6.114%, WEAT +1.891%, GLD -2.876%; no Harvey pass.
- GCPU equal-weight proxy robustness: overall -4.766%, DM t=+1.597, p=0.114.

## Caveats

- This is a free-data ETF proxy diagnostic, not a replication of futures-contract connectedness or event-regression evidence.
- Monthly lagging is conservative. A contemporaneous/event-window design might answer a different question and should not be inferred from this null.
- CORN and WEAT have shorter OOS samples; WEAT's positive point estimate is not statistically meaningful.

No blocking issue found. The correct conclusion is a null OOS forecasting result for the free ETF proxy design.
