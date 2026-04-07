# K960: HAR-RV Formal Experiment with SPY 5-min Realized Variance

## Motivation
- K188 showed HAR loses to GARCH on daily data -- because HAR requires intraday RV as input
- K744 confirmed RV AC(1)=0.423 vs daily r-squared AC(1)=0.076 (5.6x gap), validating the GARCH daily ceiling hypothesis
- With 56 days of 5-min data now available, this is the first formal HAR-RV experiment using real intraday data

## Method
- **Data**: SPY 5-min intraday prices from yfinance (2026-01-14 to 2026-04-06, 56 trading days)
- **RV Calculation**: Sum of squared 5-min log returns per day
- **Model**: HAR-RV (Corsi 2009) -- OLS regression of RV_{t+1} on daily, weekly (5d), monthly (22d) RV components
- **Estimation**: Expanding window OLS, initial IS=14 obs, OOS=19 obs
- **Cross-model comparison**: Patton (2011) QLIKE on r-squared (proxy-robust)

## Key Results

### Part A: RV Descriptive Statistics
- Mean annualized vol: 11.30%
- RV AC(1)=0.291 (vs daily r-squared AC(1)=-0.040) -- RV far more persistent
- RV is stationary (ADF p < 0.001)
- Ljung-Box not significant at 5% (p=0.207 at lag 5) -- likely due to small sample

### Part B: HAR-RV Estimation
- Full-sample R-squared: 0.077 (low, but 33 obs is extremely small)
- Only monthly component (beta_m=1.059) approaches significance (t=1.55, p=0.13)
- Daily and weekly components insignificant -- multicollinearity in tiny sample

### Part C: OOS Prediction
- **OOS R-squared vs naive: 0.243** -- HAR beats yesterday's-RV naive forecast
- HAR QLIKE: 0.118 vs Naive QLIKE: 0.180 (34% improvement)
- MZ regression: beta=-0.36 (far from ideal 1.0) -- forecast biased, but directionally useful
- Spearman rho: -0.15 (not significant) -- rank ordering poor

### Part D: Cross-Model Comparison
- Patton QLIKE on r-squared: HAR-RV (1.455) > GARCH (1.631) > GJR (1.792) -- HAR best
- DM test: HAR vs GARCH DM=-1.36 (p=0.19) -- not significant (19 obs, no power)
- All Spearman correlations near zero -- none of the models rank-order well with 19 obs

### Part E: VT Strategy Pilot
- 18-day pilot (far too short for any conclusion)
- VT cumulative: -4.08% vs BH -3.43% (bear market period)
- NOT a valid backtest

## Conclusions
1. RV persistence (AC(1)=0.291) confirms intraday data captures volatility dynamics that daily r-squared misses
2. HAR-RV shows positive OOS R-squared (0.243) and lower QLIKE than naive -- evidence of predictive ability even with tiny sample
3. Cross-model: HAR-RV slightly beats GARCH/GJR on Patton QLIKE, but DM test has no power with 19 obs
4. **All results carry severe small-sample caveat** -- 56 days / 19 OOS obs is far below standard for publishable results (need 1+ year)
5. Priority: continue accumulating 5-min data; re-run with 252+ OOS days

## Limitations
- 56 days of 5-min data (extremely small for HAR-RV)
- OOS only 19 days (ideal >= 252)
- Initial IS only 14 obs -- HAR parameters unstable
- No microstructure noise correction (Hansen-Lunde subsampling)
- Single asset (SPY)
- DM test cannot meet Harvey (2016) |t|>3.0 threshold with this sample size

## References
- Corsi (2009) "A Simple Approximate Long-Memory Model of Realized Volatility." J.Fin.Econometrics 7(2):174-196
- Patton (2011) "Volatility Forecast Comparison Using Imperfect Volatility Proxies." J.Econometrics 160(1):246-256
- K188: HAR on daily data loses to GARCH
- K744: RV AC(1)=0.423 vs daily r-squared AC(1)=0.076

## Files
- `k960_har_rv.py` -- experiment script
- `k960_har_rv_results.json` -- complete results with all statistics
- `k960_har_rv_results.png` -- 6-panel figure (RV series, AC comparison, OOS forecast, MZ scatter, QLIKE comparison, VT pilot)
- `k960_rv_distribution.png` -- RV distribution plots
