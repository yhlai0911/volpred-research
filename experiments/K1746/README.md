# K1746 — Bottom-up versus top-down portfolio VaR/ES

## Identity and the prior failed job

The earlier Claude job `agent-k1746-var-es-4316fc94` is **ZERO_SALVAGE**: it stopped at a provider weekly quota before research began, emitted no scientific artifact, and is neither a successful experiment nor a scientific null. This directory is a distinct Codex failover execution. The current verdict below comes only from `K1746_results.json#/verdict`.

## Falsifiable question and preregistered bar

For the equal-weight SPY/TLT/GLD/HYG/QQQ basket, does cross-sectional aggregation direction change genuinely OOS one-day 1%/5% VaR/ES calibration and FZ0 joint proper loss? A substantive positive required Holm-aware joint-score evidence, fewer calibration rejections, and at least 75% sensitivity-direction stability. Failure to reject coverage was never treated as superiority.

## Data and point-in-time policy

Frozen yfinance `auto_adjust=True` adjusted-close cache, originally committed by K1727 on 2026-07-28; local bytes and source metadata are in `source_manifest.json`. Strict common-date intersection, no imputation, daily equal-weight rebalancing primary, weekly reset/drift sensitivity. Every target at t uses volatility signals explicitly formed by `signal.shift(1)` and residual labels ending at t-1; runtime assertions and `test_K1746.py` enforce the seam. Exact periods/counts are `K1746_results.json#/data` and `#/backtests`.

## Methods

Primary bottom-up FHS rescales component standardized residuals with t-origin component EWMA volatilities and aggregates the same-date residual vector with portfolio weights, retaining point-in-time empirical dependence. Top-down FHS uses the same filter/window on the identical realized portfolio target. The marginal VaR/ES sum is labelled `naive_marginal_sum` and is only a dependence-ignoring diagnostic. Sensitivities change window (756→504), dependence (independent marginal permutations), distribution (Gaussian), rebalancing (weekly), and crisis sample (2020+). Empirical covariance eigenvalues are recorded; exact empirical support is used, so primary simulation error is zero conditional on the finite residual window. Tail dependence remains limited to events observed in that window.

## Formal tests and loss

Per method/alpha: Kupiec UC, Christoffersen independence and conditional coverage, Engle–Manganelli-style DQ (4 hit lags plus scaled VaR), and Acerbi–Szekely Z2 ES moment with paired moving-date-block bootstrap. Holm controls the complete 3 methods × 2 alphas × 5 tests family. FZ0 is a jointly elicitable VaR/ES loss (lower better). MCS uses identical date-level loss series, block 10, 2,000 resamples, seed 42, 90% confidence, and eliminates the higher-loss method only when the centered pairwise bootstrap rejects. Full definitions/nulls/orientations are in `K1746_results.json#/methodology`, `#/backtests`, and `#/model_confidence_set`.

## Result — `NULL_NO_MULTIPLICITY_AWARE_DIRECTIONAL_SUPERIORITY`

- `alpha_0.01`: bottom-up mean FZ0 `-3.91313742`, top-down `-3.86496546`, bottom-minus-top `-0.04817196`, Holm p `0.191904` (`K1746_results.json#/proper_score_inference/alpha_0.01`).

- `alpha_0.05`: bottom-up mean FZ0 `-4.37720727`, top-down `-4.36877364`, bottom-minus-top `-0.00843363`, Holm p `0.453273` (`K1746_results.json#/proper_score_inference/alpha_0.05`).

- MCS `alpha_0.01` included set `['bottom_up']`, p `0.095952` (`K1746_results.json#/model_confidence_set/alpha_0.01`).

- MCS `alpha_0.05` included set `['bottom_up', 'top_down']`, p `0.453273` (`K1746_results.json#/model_confidence_set/alpha_0.05`).

Calibration rejection counts after the global Holm family are `{'bottom_up': 2, 'top_down': 4, 'naive_marginal_sum': 9}` (`K1746_results.json#/verdict/calibration_rejections_after_global_holm`). These counts cannot be read as rankings by themselves.

## Limitations

ETF history begins only after HYG has common adjusted prices; adjusted yfinance history is a current-vintage vendor product, not an exchange-certified PIT tape. FHS tail support is bounded by a rolling window; 1% inference has few effective tail events. Empirical same-date dependence captures observed nonlinear co-movement but cannot extrapolate unseen tail dependence. Weekly rebalancing is a defensible convention sensitivity, not a full transaction-cost implementation. DQ and ES bootstrap p-values are finite-sample approximations. MCS has only the two scientific direction candidates; the naive diagnostic is intentionally excluded.

## Literature (verified primary metadata)

- Wang & Wang (2025), Journal of Forecasting 44(2), 391–423, DOI [10.1002/for.3195](https://doi.org/10.1002/for.3195).
- Fissler & Ziegel (2016), Annals of Statistics 44(4), DOI [10.1214/16-AOS1439](https://doi.org/10.1214/16-AOS1439).
- Hansen, Lunde & Nason (2011), Econometrica 79(2), DOI [10.3982/ECTA5771](https://doi.org/10.3982/ECTA5771).
- Acerbi & Szekely (2014), [MSCI research paper](https://www.msci.com/research-and-insights/paper/research-insight-backtesting-expected-shortfall-december-2014).
- Engle & Manganelli (2004), JBES 22(4), DOI [10.1198/073500104000000370](https://doi.org/10.1198/073500104000000370).

## Reproduce

```bash
uv run python experiments/K1746/K1746.py
uv run pytest -q experiments/K1746
```

Numeric tables and claims are generated from the same in-memory payload finalized into `K1746_results.json`; forecasts/loss inputs are in `K1746_forecasts.csv.gz`, and every inference cell is mirrored in `K1746_inference_cells.json`. Independent review is deliberately deferred to PHASE A; this worktree does not contain `review_verdict.json`.
