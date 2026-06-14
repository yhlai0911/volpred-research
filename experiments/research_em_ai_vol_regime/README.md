# EM equity volatility regimes conditional on AI-trade coupling

## Verdict

**NULL.** Public-market AI/semiconductor coupling does not provide robust evidence of a distinct future EM volatility regime after controlling for lagged own volatility and VIX.

Primary test: high-minus-low AI-coupling regime effect on future 21-trading-day realized volatility.

- Sample: yfinance adjusted close, 2012-02-03 to 2026-06-12, joint ETF sample.
- EM ETFs: EEM, INDA, EWZ, EWY, EWT, EWW, FXI.
- AI proxy: equal-weight log return of SMH, SOXX, NVDA, MSFT, QQQ.
- Inference: OLS with Newey-West HAC standard errors, `maxlags=21`.
- Multiple testing: Bonferroni alpha across 7 EM ETFs = 0.007143.
- Result: high AI-coupling regime effect is positive for only 3/7 ETFs and 0/7 survive Bonferroni.

## Motivation

The task asks whether EM equities act as diversification against the AI trade, or whether their volatility regimes switch when they become more coupled to AI-related trading. This is related to, but distinct from, K1441: K1441 showed a dominant common EM volatility factor and borderline high-correlation regime evidence. This experiment conditions EM future volatility on an ex-ante AI-specific coupling signal rather than on EM internal RV synchronization.

Relevant prior local findings:

- K1441: EM 5-ETF RV has a strong common factor, but high-correlation regime evidence weakens after HAC and multiple-testing control.
- K1466: frontier/SE Asia EM decoupling exists in calm periods but converges in crisis.
- K1487: coarse AI/news intensity did not improve RV forecasts after lagging and OOS testing.

## Literature And External Context

- Bekaert, Harvey, and Ng, "Volatility spillovers and contagion from mature to emerging stock markets" (ECB working paper): mature-market volatility transmission to EM motivates the spillover framing.
- Adekoya et al. (2024), "Exploring volatility interconnections between AI tokens, AI stocks, and fossil fuel markets": motivates AI-stock volatility connectedness as a measurable market object.
- IMF Global Financial Stability Report, October 2024, Chapter 3: motivates AI-driven trading as a possible accelerator of market stress transmission.
- Goldman Sachs, "Emerging Markets Stocks Can Balance Volatility from the AI Trade": practitioner claim tested here with transparent public ETF proxies.

## Design

For each EM ETF, the experiment constructs an ex-ante AI-coupling signal:

1. Compute daily log returns from adjusted closes.
2. Build an AI-trade proxy as the equal-weight return of SMH, SOXX, NVDA, MSFT, and QQQ.
3. For each date `t`, estimate 126-day partial correlation between the EM return and the AI proxy, controlling for SPY, using only returns through `t-1`.
4. Assign low/mid/high coupling regimes using recursive expanding 30/70 quantiles with 504-observation warm-up; thresholds are shifted before assignment.
5. Test whether high coupling predicts higher future 21-day realized volatility from returns `t..t+20`.
6. Control for lagged 21-day own realized volatility and `log(VIX_{t-1})`.

The key regression is:

```text
future_rv_t = a + b_high * 1(high_coupling_t)
                + b_low * 1(low_coupling_t)
                + c * lagged_rv_t
                + d * log_vix_{t-1}
                + e_t
```

The reported primary contrast is `b_high - b_low`, with HAC standard errors.

## Results

Primary high-minus-low HAC contrasts:

| ETF | High-low future RV | HAC t | HAC p |
|---|---:|---:|---:|
| EEM | -0.0091 | -0.72 | 0.472 |
| INDA | +0.0013 | +0.13 | 0.900 |
| EWZ | +0.0454 | +1.48 | 0.138 |
| EWY | +0.0159 | +1.20 | 0.229 |
| EWT | -0.0067 | -0.59 | 0.557 |
| EWW | -0.0086 | -0.56 | 0.575 |
| FXI | -0.0226 | -1.16 | 0.248 |

Continuous coupling also fails: 0/7 ETFs have Bonferroni-significant `coupling_z_lag1` coefficients. Lagged AI shock days are positive for 7/7 ETFs directionally, but 0/7 survive Bonferroni, so this remains descriptive and weak.

## Figures

- `figures/median_ai_coupling.png`
- `figures/future_rv_by_coupling_regime.png`
- `figures/high_minus_low_hac_effects.png`
- `figures/coupling_vs_future_rv.png`

## Research Honesty Notes

- This is a public-market proxy study, not direct observation of AI trading flow or AI capex surprises.
- ETF prices are USD-denominated; local-currency EM equity volatility and FX translation are not separated.
- The design tests forecast association and conditioning, not structural causality.
- The result is a NULL finding: EM-AI coupling is visible in returns, but it is not a robust standalone signal for next-month EM realized volatility once lagged RV and VIX are controlled.

## Reproducibility

Required artifacts:

- `research_em_ai_vol_regime.py`
- `research_em_ai_vol_regime_results.json`
- `README.md`

Run:

```bash
uv run python experiments/research_em_ai_vol_regime/research_em_ai_vol_regime.py
```

The script caches adjusted close data in `data/adjusted_close.csv` and writes figures under `figures/`.
