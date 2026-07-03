# Codex Review - K1615

Review date: 2026-07-03

## Verdict

`CONDITIONAL_PASS` for a narrow public-proxy diagnostic.

The code produces the required artifacts, uses explicit official event dates, fixes the seed, and does not make a forecasting/lookahead claim. The empirical conclusion must remain `DIRECTIONAL_ONLY`; it is not strong enough for publication-grade or trading claims.

## Checks

- Lookahead: clean for an event study. Events are fixed from public announcement dates, mapped to the next trading day, and windows are measured mechanically in `K1615.py`. No market outcome is used to choose events.
- Data provenance: yfinance adjusted closes are cached in `data/yfinance_adjusted_close.csv`; official event calendar is written to `data/event_calendar.csv`.
- Statistical gate: primary direct tests are only the apartment REIT basket on residential events and the travel basket on the hotel/travel event. Apartment REIT log-RV coefficient is positive but fails the project gate (`t=2.05`, Holm p=`0.0799`, threshold `|t|>=3` and Holm p `<0.05`). Travel has one official event and is non-gateable.
- Multiple testing: the two direct basket tests receive Holm correction. Individual and cross-spillover regressions remain diagnostics.
- Randomness: seed fixed at 42. No stochastic bootstrap is used in the current run.

## Issues / Caveats

- MEDIUM: event count is small. Residential has 8 official milestones; travel has only 1, so travel-side findings cannot be interpreted formally.
- MEDIUM: public tickers are weak exposure proxies. Most named RealPage-related landlords are private or subsidiaries; AVB/EQR/UDR/ESS/CPT/MAA are sector proxies, not confirmed treated firms.
- LOW: same-day market controls are appropriate for an event-window diagnostic, but they absorb some broad legal-policy market reaction. Do not compare coefficients to a forecasting design.
- LOW: daily close-to-close squared returns are coarse; a stronger version would use intraday realized variance.

## Allowed Claim

K1615 can claim that residential algorithmic-pricing enforcement windows show a positive but non-gateable controlled volatility direction for public apartment REIT proxies. It cannot claim a statistically significant RealPage legal-risk premium, causal exposure, cross-sector spillover, or investable signal.
