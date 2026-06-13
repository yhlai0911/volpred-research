# K1491 Codex Review — 2026-06-13

## Verdict

**PASS with caveats**

K1491 successfully fixes the K1490 methodology failure: all 8 Granger tests return valid F-statistics and p-values, with no constant-column errors. The experiment package has the required README, script, results JSON, and real PNG figures.

## Checks

- `MPLCONFIGDIR=/tmp .venv/bin/python experiments/k1491/k1491.py` completed successfully.
- `python3 -m json.tool experiments/k1491/k1491_results.json` parses cleanly.
- Figures exist and are non-empty:
  - `k1491_spillover_heatmap.png`
  - `k1491_tail_signal_timeseries.png`
- Lookahead control is explicit:
  - crypto VoV predictor uses `.shift(1)`
  - target tail threshold uses lagged rolling q95 via `.shift(1)`
- K1490 sparse-binary failure is addressed by continuous `tail_signal_t = max(0, |r_t| - lagged rolling q95)`.

## Findings

- Granger: 8/8 valid pairs, 0 errors.
- Granger Bonferroni passes: BTC→USO, BTC→TLT, ETH→USO, ETH→TLT.
- QuantReg q95 absolute-return passes: 7/8 pairs after Bonferroni.
- Interpretation should remain `PARTIAL`, not a broad crypto-to-equity spillover claim, because SPY/GLD do not pass the Granger correction and the strongest signals are USO/TLT.

## Residual Risks

- The run used local snapshot data from `experiments/k1090b/data` because live yfinance DNS failed. This is reproducible locally but the sample ends at `2024-12-30` for traditional targets.
- The Granger test still uses best-lag selection over lags 1-5, but K1491 mitigates this by multiplying the best raw p-value by `MAX_LAG` before pair-level Bonferroni.
- This is reduced-form predictive evidence only. Do not write `knowledge.json` until a main-thread review decides whether the local snapshot sample is acceptable.
