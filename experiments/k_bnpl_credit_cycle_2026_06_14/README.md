# k_bnpl_credit_cycle_2026_06_14

## Question

Can a public-market BNPL / consumer-lending proxy act as an early warning signal for credit-cycle stress in IWM, HYG, and financial-sector volatility?

## Motivation

The backlog item asks whether AFRM / UPST / SOFI / ALLY realized volatility, together with consumer-credit macro context, leads realized volatility in IWM, HYG, and financial stocks. The literature motivation is real: consumer lending has expanded into BNPL and platform lending, while public risk metrics remain incomplete or delayed.

## Literature Checked

- CFA Institute Research Foundation, `Alternative Credit: The Rise of Consumer Lending` (2025), frames consumer lending as a growing private-credit subasset class with BNPL as a newer segment and highlights borrower performance, underwriting, regulation, and macro conditions as key risk drivers: <https://rpc.cfainstitute.org/research/foundation/2025/alternative-credit-rise-of-consumer-lending>
- CFPB, `Consumer Use of Buy Now, Pay Later and Other Unsecured Debt` (2025), documents that many BNPL borrowers have higher unsecured debt balances and that BNPL loans have historically been hard for external observers to measure in credit records: <https://files.consumerfinance.gov/f/documents/cfpb_BNPL_Report_2025_01.pdf>
- BIS Quarterly Review, `Buy now, pay later: a cross-country analysis` (2023), argues that BNPL users tend to have riskier credit profiles than traditional consumer-credit users and that BNPL shifts credit risk toward platforms: <https://www.bis.org/publ/qtrpdf/r_qt2312e.htm>
- New York Fed Staff Report 1167, `Understanding Consumer Demand for Buy Now, Pay Later` (2026), estimates stronger BNPL demand among lower-income and lower-credit-score consumers and notes that the modern US BNPL system has not yet faced a full macro cycle: <https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr1167.pdf>
- FRED `DRCLACBS` / `DRCCLACBS` provide quarterly consumer-loan and credit-card delinquency context, but these are slow-moving and release-lagged: <https://fred.stlouisfed.org/series/DRCLACBS>

## Related Knowledge Search

Searches in `storage/memory/knowledge.json`, `research_program.md`, `experiments/`, and `docs/` for `BNPL`, `Affirm`, `Upstart`, `SoFi`, `Ally`, `consumer credit`, and `delinquency` found this backlog line but no completed BNPL-specific volatility experiment. Relevant methodological lessons came from prior logs:

- use explicit lagging for every predictive signal;
- do not use same-day signals with same-day returns;
- avoid overclaiming from noisy public proxies;
- use HAC / DM-style formal tests rather than chart-only conclusions;
- be careful with low-frequency FRED data because revised or delayed macro series can create false timing.

## Data

- Price data: yfinance adjusted close.
- Sample: starts at the first common AFRM / UPST / SOFI / ALLY / IWM / HYG / XLF / SPY / VIX date after 2021-01-01 and ends at 2026-06-12 in the current run.
- BNPL / consumer-lending proxy: equal-weight returns of `AFRM`, `UPST`, `SOFI`, `ALLY`.
- Targets: `IWM`, `HYG`, `XLF`.
- Market controls: `SPY`, `^VIX`.
- Macro context: FRED `DRCLACBS`, `DRCCLACBS`, `UMCSENT`.

## Method

1. Build close-to-close log returns and squared daily returns as a noisy daily realized-variance proxy.
2. Create a lagged BNPL stress signal: prior-day BNPL log RV above its own lagged rolling 252-day 90th percentile.
3. Run an event diagnostic comparing target RV after lagged BNPL stress vs non-stress days with a 5-day moving-block bootstrap (`N_BOOT=1000`, `seed=42`).
4. Fit HAC regressions of target log RV on HAR own-vol lags plus lagged BNPL, market, and conservative-lag macro controls.
5. Run rolling expanding OOS comparisons:
   - `har`: own HAR lags;
   - `har_market`: own HAR lags + lagged SPY/VIX volatility;
   - `har_bnpl`: own HAR lags + lagged BNPL volatility/downside;
   - `har_market_bnpl`: market baseline + lagged BNPL features.
6. Evaluate OOS forecasts by QLIKE on target-day squared return and DM tests. Strict pass requires lower QLIKE and Harvey-style `|t| > 3`.

## Lookahead Controls

- Predictive daily features use `.shift(1)` or equivalent lag.
- The BNPL stress event flag is `raw_signal.shift(1)`, so target-day RV is never paired with same-day BNPL stress.
- FRED quarterly delinquency series are shifted by 63 trading days; monthly sentiment is shifted by 21 trading days.

## Reproduction

```bash
uv run python experiments/k_bnpl_credit_cycle_2026_06_14/k_bnpl_credit_cycle_2026_06_14.py
```

Expected artifacts:

- `k_bnpl_credit_cycle_2026_06_14_results.json`
- `fig_bnpl_stress_event.png`
- `fig_oos_qlike_delta.png`
- `fig_macro_credit_context.png`

## Results

Status: `NULL_NO_ROBUST_OOS_EDGE`.

The descriptive event diagnostic shows that a lagged BNPL stress day is followed by higher next-day target RV:

| Target | Next-day stress / non-stress RV | Forward 5-day mean stress / non-stress RV | Bootstrap p, next-day | Bootstrap p, 5-day |
|---|---:|---:|---:|---:|
| IWM | 1.379 | 1.234 | 0.049 | 0.096 |
| HYG | 1.671 | 1.204 | 0.081 | 0.276 |
| XLF | 1.690 | 1.217 | 0.047 | 0.255 |

These event results are descriptive and do not survive a strict multiple-testing interpretation. The forward 5-day effect is weaker than the next-day effect.

Rolling OOS model comparison is negative for BNPL as an incremental forecasting feature:

| Target | Best OOS model | HAR QLIKE | HAR+BNPL QLIKE | HAR+market QLIKE | HAR+market+BNPL QLIKE | BNPL-vs-base DM t |
|---|---|---:|---:|---:|---:|---:|
| IWM | `har_market` | 2.881 | 2.893 | 2.870 | 2.885 | 0.579 / 0.723 |
| HYG | `har_market` | 3.089 | 3.122 | 3.063 | 3.094 | 1.640 / 1.633 |
| XLF | `har` | 3.709 | 3.727 | 3.820 | 3.816 | 0.203 / -0.042 |

None of the BNPL-augmented models reaches the strict Harvey-style `|t| > 3` threshold, and most have worse QLIKE than their base model.

Macro context is also not supportive of a clean "public BNPL equity RV tracks realized consumer-credit deterioration" story. Monthly BNPL proxy RV has negative Spearman correlation with conservatively lagged consumer-loan delinquency (`rho=-0.300`, `p=0.0168`) and credit-card delinquency (`rho=-0.318`, `p=0.0111`) over this short 63-month window, which likely reflects 2021-2022 listed-fintech repricing rather than loan-performance lead-lag.

## Conclusion

The experiment finds a short-horizon stress association but no robust OOS volatility-forecasting edge. A safe publishable angle would be: "listed BNPL / consumer-lending equities react noisily to fintech-rate-cycle stress, but they are not yet a reliable standalone early-warning signal for IWM/HYG/XLF volatility." It should not be framed as evidence that private BNPL loan performance leads public credit-market volatility.
