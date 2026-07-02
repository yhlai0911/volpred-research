# Codex Review

## Scope

Reviewed `research_shareholder_democracy_public_goods_vote_risk_n_p.py`, the generated result JSON, cached data diagnostics, and figures.

## Findings

- Lookahead: pass. Event dates are aligned to the first trading day on or after the proposal/vote date, then the predictive signal is explicitly lagged with `raw_event_signal.shift(1)`. The target is the next close-to-close squared return.
- Data provenance: pass with limitations. Proposal events come from the public Proxy Monitor API and the fetch metadata records API count, fetched rows, stop rule, and analysis window. Price data are cached from yfinance with `auto_adjust=False` and explicit `Adj Close` use.
- Coverage: acceptable for a pilot. Firm event rows with usable price history are 1,103/1,184; missing rows are due to ticker/delisting/price-history gaps and are listed in `data/raw/yfinance_failed_symbols.json`.
- Statistical framing: pass after correction. The main one-sample and comparison tests use scaled abnormal variance `target_r2 / prior_60d_baseline_var - 1`; log-ratio one-sample testing was avoided because it would be mechanically biased negative by Jensen effects.
- OOS forecast check: pass as a diagnostic, not a model claim. The public-goods event multiplier improves mean QLIKE directionally but is not statistically significant; CI includes zero.
- Sector spillover: pass as a bounded proxy. Industry-to-sector ETF mapping is coarse, and no significant spillover is found.

## Residual Risk

- Proxy Monitor is not the full Form N-PX mutual-fund-voting panel and does not identify large index-manager vote pressure.
- Event timing is daily, not intraday, so the experiment cannot distinguish vote-result announcement time from annual-meeting calendar effects.
- Public-goods and shareholder-democracy labels are rule-based and should be replaced with ISS/FactSet categories for a publishable version.

## Verdict

The implementation is reproducible and the reported `null_or_inconclusive` conclusion is supported by the available public-data pilot. Do not promote this to a strong article claim without a richer N-PX/ISS/FactSet panel.
