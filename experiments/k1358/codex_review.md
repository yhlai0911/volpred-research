# K1358 Codex Review

Review date: 2026-06-21

Verdict: PASS for research-honesty controls; empirical verdict is `NULL_PROXY`.

## Checks

- Data provenance: PASS. Results record yfinance, Felten/Raj/Seamans AIIE, GDELT, and FRED/BLS sources. Raw/cached inputs are saved under `data/`.
- AIIE parsing: PASS. The script parses Appendix B from `AIOE_DataAppendix.xlsx` without `openpyxl` in `K1358.py:121-190`.
- Proxy ceiling: PASS. Sector AI exposure is a transparent NAICS-prefix average in `K1358.py:193-215`; it is not holdings-level or worker-level exposure.
- Rolling z-scores: PASS. Daily and monthly rolling z-scores use past moments via `x.shift(1)` in `K1358.py:107-118`.
- BLS availability: CONDITIONAL_PASS. Monthly FRED/BLS values are conservatively delayed by next month plus four business days in `K1358.py:290-295`; this is an approximation, not exact release-calendar matching.
- Event lookahead: PASS. Event shocks are measured at `t`; forward RV/downside/correlation responses use `t+1` forward windows in `K1358.py:354-356`.
- Forecast target and signals: PASS. Forecast target is `RV[t+1..t+5]` in `K1358.py:354`; all forecast features are shifted in `K1358.py:381-388`.
- OOS fitting: PASS. Expanding OLS trains only on rows before forecast row `i` in `K1358.py:417-422`.
- Multi-sector DM: PASS. Pooled loss differentials are averaged by date before DM in `K1358.py:473-475`, avoiding asset-day independence.
- Bootstrap: PASS. Event DID uses fixed `SEED=42` and 2,000 bootstrap draws in `K1358.py:485-501`.

## Result Integrity

- Event DID fails the stated risk gate. High-AI-exposure sectors have lower forward RV on shock days (`-0.0001007`, CI `[-0.0001812,-0.0000196]`) and no significant downside-semivariance increase.
- Correlation-to-SPY DID is positive (`+0.0147`, CI `[+0.0014,+0.0280]`), but that alone does not satisfy the predeclared RV + downside risk criteria.
- Forecast gate fails. Pooled QLIKE loss differential is `+0.04937`, DM `t=+1.790`, `p=0.0736`; positive t means the AI-labor challenger is worse on average. Only 2 of 11 sectors improve.
- Knowledge promotion: NOT recommended.

## Caveats

- GDELT article counts are attention proxies, not firm-level adoption or layoff labels.
- The BLS/FRED residuals are macro labor surprises, not sector-specific employment/wage surprise data.
- Sector ETF returns contain many non-labor channels, so this cannot identify a household human-capital hedging mechanism.
