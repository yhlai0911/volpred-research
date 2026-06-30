# Codex Research Integrity Review

Verdict: PASS_WITH_LIMITATIONS

Reviewed files:
- `README.md`
- `research_rough_volatility_arrv_fractional_ou_joe_2023_fou.py`
- `research_rough_volatility_arrv_fractional_ou_joe_2023_fou_results.json`
- `rough_vol_model_race.png` presence only; visual inspection was not needed for the integrity checks.

## Required Files

PASS. The required experiment files exist: README, executable experiment script, results JSON, and generated figure. The results JSON parses cleanly.

## Findings

1. Lookahead: PASS.

The OOS forecast loop is chronologically aligned. At forecast position `pos`, the Hurst estimate and model fits use `log_rv[:pos]`; training rows use targets only for `t < pos`; forecast features use lagged windows ending at `t-1` (`log_rv[t - 1]`, `log_rv[t - 5:t]`, `log_rv[t - 22:t]`, `rq[t - 1]`, and fractional windows `log_rv[t - max_lag:t]`). This satisfies the project rule of signal through `t-1`, target at `t`. I did not find same-day target leakage in the model race.

2. Target/model matching: PASS_WITH_LIMITATIONS.

The loss target is realized variance, and the script forecasts a positive RV level by fitting log-RV models and back-transforming with a residual variance adjustment before QLIKE evaluation. That is a coherent target/loss pairing. The limitation is model interpretation: `ARRV` and `fOU_lite` are transparent proxy specifications, not full structural ARRV or fractional-OU maximum-likelihood implementations. The README/results disclose this, so the result is valid as a bounded proxy race, not as a definitive rejection of all fOU or rough-volatility models.

3. QLIKE/DM usage: PASS.

The script uses repo helpers `qlike`, `qlike_pointwise`, and `dm_test`. Candidate losses are passed as `losses[model]` against `losses["HAR"]`, matching the helper convention that a negative DM t-stat means the candidate has lower loss than HAR. The reported sign convention and the QLIKE rankings are consistent. The one-step horizon setting `h=1` is appropriate for daily one-step RV forecasts. The Harvey `|t| > 3.0` gate is applied consistently as a conservative multiple-testing heuristic.

4. Sample and OOS honesty: PASS_WITH_LIMITATIONS.

TAIFEX sample disclosure is consistent with the source cache: 1,138 day-session dates from 2017-05-16 to 2021-12-30, with 488 OOS forecast days. The first generated forecast date is 2020-01-02 even though the configured OOS start is 2020-01-01; this is acceptable because 2020-01-01 is not a generated trading forecast day, but future writeups should state the actual first forecast date when reporting OOS windows.

SPY is correctly marked diagnostic-only with 40 OOS days and below the 252-day floor. Minor metadata drift: the JSON sample says 113 valid SPY days, README also says 113, but the limitations text says the archive covers 114 days. A source count shows 114 raw CSV files and 113 valid parsed sample days, so the limitation should say "114 raw files / 113 valid sample days" if reused. This does not affect the formal TAIFEX result.

5. Regime split interpretation: PASS_WITH_LIMITATIONS.

The high-VIX split is an ex-post OOS subgroup analysis, not part of the forecasting model. Because the code aligns exact calendar-date VIX to TAIFEX forecast dates, the VIX close would not necessarily be known before the Taiwan day session forecast. This is acceptable for descriptive regime analysis, especially since it finds no rough-model win, but it must not be described as a tradable or allocation-ready high-VIX rule unless VIX is lagged/as-of aligned.

6. Conclusion strength: PASS_WITH_LIMITATIONS.

The NULL conclusion is supported for this bounded experiment: TAIFEX 5-minute RV is low-H by the reported diagnostics, but ARRV/fOU-lite do not beat HAR and fail the Harvey gate. The conclusion should remain scoped to "these lite rough-volatility proxies on TAIFEX day-session 5-minute RV" plus the short SPY diagnostic. Avoid broader claims that rough volatility is useless or that full fOU/ARRV models have been rejected. Also, the phrase "roughness is real as a path property" is stronger than the evidence strictly supports: the diagnostics are computed on a daily sequence of 5-minute realized-variance estimates, not a full continuous-time intraday volatility path.

## Bottom Line

No critical research-integrity failure found. The experiment can be used as a bounded NULL result, provided the writeup keeps the proxy-model, ex-post regime, and SPY short-sample limitations explicit.

Post-review resolution: the 114 raw SPY files / 113 valid sample days wording and the over-strong "path property" phrase were tightened after this review without changing the numerical results.
