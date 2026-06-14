# Codex review: research_em_ai_vol_regime

VERDICT: PASS_WITH_CAVEATS

## Checks

- Lookahead control: PASS. `rolling_partial_corr()` assigns the signal at date `i` using `frame.iloc[i - window : i]`, so the signal uses returns through `t-1`. Regime thresholds use expanding quantiles shifted by one additional observation. Controls use lagged RV and `log(VIX_{t-1})`.
- Target alignment: PASS. `future_realized_vol()` uses returns `t..t+20`, while all signals and controls are known before return `t`.
- Regime-threshold lookahead: PASS. Thresholds are recursive expanding quantiles with 504-observation warm-up and `shift(1)`.
- HAC inference: PASS. The future 21-day RV target is overlapping, and the regression uses Newey-West HAC with `maxlags=21`.
- Multiple testing: PASS. The primary family is 7 EM ETF high-minus-low contrasts with Bonferroni alpha `0.05 / 7`.
- Seed/randomness: PASS. `SEED=42` is fixed; no bootstrap or Monte Carlo is used.

## Caveats

- This is a conditioning/regression study, not a trading strategy or model-selection OOS horse race. Regression coefficients are estimated on the full available sample; claims are therefore association-level, not deployable forecast model claims.
- The AI proxy is a public-market ETF/stock basket. It is not observed AI order flow, AI capex surprises, or proprietary positioning.
- USD-denominated ETFs mix local equity volatility and FX translation.

## Conclusion

The NULL result is credible under the stated design. The implementation is explicit about lagging, recursive regime labels, HAC inference for overlapping RV, and multiple-testing control.
