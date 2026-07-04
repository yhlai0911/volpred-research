# Codex Source Review - K1625

Reviewer: Codex CLI  
Date: 2026-07-04  
Verdict: **CONDITIONAL_PASS**

## Checks

| Check | Verdict | Evidence |
|---|---|---|
| Data provenance | PASS | Script uses Binance USD-M Futures public API and stores raw funding / kline CSV snapshots under `experiments/k1625/data/`. |
| Reproducibility | PASS | `SEED = 42`; `uv run python experiments/k1625/k1625.py` reruns successfully and regenerates JSON/figures. |
| Lookahead | PASS | Predictors use `funding_mean.shift(1)`, `ret.abs().shift(1)`, and `rv1.rolling(...).shift(1)`; h=5 threshold uses `rv_fwd5.shift(5)` so threshold labels end before forecast date. |
| Target alignment | PASS | `rv_fwd5[t]` is built from `rv[t]..rv[t+4]`; lagged funding at `t-1` precedes the first return in the window. |
| Inference horizon | PASS | HAC covariance uses `maxlags=h` for each horizon. |
| Cross-asset iid risk | PASS | No pooled asset-day inference is used for the primary verdict; BTC and ETH are reported separately. |
| Claim strength | CONDITIONAL_PASS | One BTC h=5 high-RV funding-z cell passes `|t|>=3`, but ETH fails to replicate and asymmetry tests fail. Verdict is correctly limited to `MIXED_WEAK_SINGLE_CELL`. |

## Blocking Issues

None.

## Caveats To Preserve

- Do not publish as "funding predicts crypto volatility" without the BTC-only and ETH-null caveat.
- Do not claim a long-crowding vs short-crowding liquidation asymmetry; the explicit `pos - neg` Wald contrast does not pass the Harvey threshold.
- Binance funding is not market-wide funding. Cross-exchange validation is required before any market-structure article.

