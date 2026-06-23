# Codex Review: research_bhc_ai_loss_disclosure_rv

## Scope

Reviewed `research_bhc_ai_loss_disclosure_rv.py`, generated CSVs, plots, and `research_bhc_ai_loss_disclosure_rv_results.json` after the experiment run.

## Checks

- Data provenance: SEC submissions and Archives URLs are recorded per filing in `data/filing_counts.csv`; price source is `yfinance` adjusted close.
- SEC coverage: each of the 10 banks has one 10-K for every report year 2019-2025, for 70 filings total.
- Lookahead: disclosure state is converted to a monthly panel and lagged with `groupby("ticker").shift(1)` before predicting next-month realized volatility.
- Target construction: monthly realized volatility uses daily returns; the final observed price month is dropped to avoid partial-month next-RV targets.
- Controls: bank panel includes current bank RV, absolute current return, KBE/XLF/SPY current RV, bank fixed effects, and year fixed effects.
- Inference: bank panel uses month-clustered standard errors; ETF aggregate tests use HAC standard errors with `maxlags=3`; Harvey-style `abs(t) > 3` is recorded explicitly.
- Result consistency: `MIXED_DISCLOSURE_SIGNAL` matches the tables: no bank-panel signal passes, and only XLF aggregate model-risk passes.

## Findings

No implementation blocker found after the partial-month target fix.

The main residual risk is interpretive, not mechanical: the single XLF model-risk pass may be a common post-2022 sector-regime effect rather than a disclosure-specific forecasting signal. The result should be logged as a candidate governance feature, not as an active trading signal.

## Review Verdict

Accept with conservative interpretation.
