# K1553: Coherent VaR/ES Estimator Guardrail

- Experiment ID: `K1553`
- Status: `COMPLETE`
- Created: 2026-06-28
- Script: `experiments/k1553/k1553.py`
- Results: `experiments/k1553/k1553_results.json`

## Motivation

The trigger is Aichele, Cialenco, Jelito, and Pitera (2026), "Coherent Estimation
of Risk Measures" in the Journal of Financial Econometrics. The paper's warning
is directly relevant to VolPred's risk stack: a coherent risk measure such as
Expected Shortfall does not automatically make every practical estimator
coherent.

K1553 asks whether common rolling VaR/ES estimators can change capital rankings,
backtest outcomes, and volatility-target / drawdown-risk-parity de-risking
signals even when they are all marketed as tail-risk estimators.

## Literature Preamble

- Artzner, Delbaen, Eber, and Heath (1999), "Coherent Measures of Risk":
  establishes the coherence axioms and motivates ES over non-subadditive VaR.
- Acerbi and Szekely (2014), "Backtesting Expected Shortfall": ES can be
  backtested; elicitability concerns forecast comparison, not model testing.
- Fissler and Ziegel (2016), "Expected Shortfall is jointly elicitable with
  Value at Risk": joint VaR/ES scoring and DM-style comparison are valid.
- Aichele et al. (2026), "Coherent Estimation of Risk Measures": coherence of
  the risk measure need not carry over to the estimator; coherent L-estimator
  weight structures can materially alter capital adequacy outcomes.

## Data

- Source: `yfinance`, adjusted close.
- Assets: SPY, QQQ, IWM, TLT, HYG.
- Requested period: 2007-01-01 through 2026-06-28.
- The script records the actual fetched date range and observations in
  `k1553_results.json`.
- Daily close-to-close simple returns are used. No intraday RV is mixed into this
  experiment.

## Methods

Rolling window: 500 trading days. Forecasts for day `t` use only returns through
`t-1`.

Methods compared:

- `hist`: unweighted historical simulation VaR and historical ES.
- `ewma`: EWMA scenario-weighted VaR and ES with lambda 0.97.
- `cornish_fisher`: Cornish-Fisher moment-adjusted VaR and numerical CF ES.
- `spectral_l`: a coherent L-estimator style smoothed tail estimator, using
  monotone non-negative weights over the worst alpha share of losses.

Evaluation:

- 1% and 5% VaR violation rate, Kupiec, Christoffersen, Basel-style traffic
  light, and Acerbi-Szekely ES Z1 approximation.
- Estimator subadditivity on all 10 equal-weight asset pairs:
  `rho(0.5 X + 0.5 Y) <= 0.5 rho(X) + 0.5 rho(Y)`.
- Capital ranking by average 5% ES forecast versus realized OOS 5% ES.
- Equal-weight portfolio de-risking triggers using a target daily ES budget.

## Lookahead Policy

- Rolling estimators slice `returns[t-window:t]` and evaluate return `t`.
- The VT/DRP-like exposure signal is explicitly lagged:
  `applied_leverage = raw_leverage.shift(1)`.
- No same-day signal is multiplied by same-day return.
- Random seed is fixed at 42. The only non-deterministic dependency is the
  yfinance data vendor snapshot.

## Success Criteria

- `PASS`: at least one non-L-estimator produces economically material
  subadditivity violations, capital ranking flips, or de-risking trigger drift,
  while the coherent L-estimator materially reduces those problems.
- `CONDITIONAL_PASS`: differences exist but are narrow, sample-dependent, or
  mostly limited to one estimator.
- `NULL`: estimator choice does not materially change coherence diagnostics,
  backtests, capital ranking, or trigger counts.

## Result

Verdict: `PASS`.

Headline findings:

- Sample: yfinance adjusted close, 2007-04-11 to 2026-06-26, 4,833 daily
  return rows, 4,333 rolling OOS forecasts after the 500-day window.
- 5% ES subadditivity test across all 10 equal-weight asset pairs:
  `hist` 0.00%, `ewma` 9.59%, `cornish_fisher` 4.28%, `spectral_l` 0.00%.
- Average 5% ES capital ranking did not flip in this ETF universe:
  all methods rank IWM > QQQ > SPY > TLT > HYG, matching realized OOS ES.
- De-risking trigger counts are highly estimator-sensitive: raw low-exposure
  days range from 2,180 (`ewma`) to 3,628 (`cornish_fisher`), a 1,448-day
  spread.
- VaR/ES backtests are not production-clean: several methods fail
  Christoffersen, Basel, or ES Z1 checks. The PASS is therefore a guardrail
  finding about estimator choice, not approval of any estimator as a live risk
  model.

See `k1553_results.json` for the full numerical output. The headline verdict is
stored under `verdict`.

## Files

- `k1553.py`: reproducible experiment script.
- `k1553_results.json`: byte-traceable numeric results.
- `k1553_capital_rank.png`: capital ranking comparison.
- `data/adjusted_close.csv`: adjusted close snapshot used by the script.
- `data/daily_returns.csv`: computed daily returns snapshot.
