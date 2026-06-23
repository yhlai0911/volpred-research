# Codex Review - K1367

Review date: 2026-06-23

## Verdict

`CONDITIONAL_PASS` for source integrity.

This review supports only the experiment's own `NULL_PROXY` conclusion. It does not support any positive claim that climate-news duration or green/brown reaction-time differences robustly forecast tail risk.

## Checks

- Required experiment files exist:
  - `README.md`
  - `K1367.py`
  - `K1367_results.json`
- Re-ran `uv run python experiments/K1367/K1367.py`; it completed and regenerated `K1367_results.json` with verdict `NULL_PROXY`.
- `python -m py_compile experiments/K1367/K1367.py` passes.
- Data provenance is byte-traceable:
  - raw GDELT API response cached at `data/gdelt_climate_timeline_raw.json`;
  - parsed GDELT daily series cached at `data/gdelt_climate_daily.csv`;
  - yfinance OHLCV cached at `data/yfinance_ohlcv.csv`;
  - event and model panels written to CSV.
- The script contains a Sentometrics MCCC fallback for GDELT DOC rate limits, but this reviewed run used the cached GDELT DOC response (`climate_news.source = GDELT DOC 2.0 TimelineVolRaw`).
- Randomness is fixed with `SEED = 42` and `np.random.default_rng(SEED)` for bootstrap diagnostics.
- Lookahead guard is explicit:
  - rolling news z-score uses `shift(1)` for historical mean/std;
  - response threshold uses lagged 60-day sigma;
  - event features are assigned on `feature_date`;
  - predictive features enter the model through `signal_lagged = signal.shift(1)`.
- Result strength is not overstated:
  - 0/18 focal duration/reaction tests pass Harvey `|t| >= 3`;
  - 0/18 pass Bonferroni `p < 0.05`;
  - event diagnostic bootstrap intervals cross zero.

## Residual Risk

- GDELT keyword volume is a coarse attention proxy, not a validated climate-news classifier or sentiment measure.
- Green/brown ETF baskets are coarse and sector-composition dependent.
- Daily data cannot test the intraday IG-ACD-GARCH mechanism from the JBF 2025 paper.
- Sample size is 69 aligned events; the null is a public-proxy null, not a rejection of firm-level or intraday literature evidence.
