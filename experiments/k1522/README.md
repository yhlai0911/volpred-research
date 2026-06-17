# K1522: Corporate-Bond ETF Factor-Zoo Bias-Correction Audit

## Question

This experiment audits whether simple corporate-bond ETF factor premia survive a conservative bias-correction proxy. The backlog item was motivated by recent corporate-bond factor-zoo replication work, but this run is deliberately narrower: it uses liquid ETFs (`HYG`, `JNK`, `LQD`, `VCIT`, `VCSH`, `VCLT`, `IGSB`, `IGIB`) because the workspace does not contain TRACE bond-level data.

## Literature Setup

- Dickerson, Robotti, and Rossetti (2026), *The Corporate Bond Factor Replication Crisis*, argues that many corporate-bond factors are inflated by transaction-price measurement error entering both sorting signals and return denominators, plus ex-post filtering/lookahead. It also points to Open Bond Asset Pricing as the correct bond-level framework.
- Open Bond Asset Pricing provides reproducible corporate-bond factor code/data. K1522 does not replicate that framework; it borrows only the denominator-bias audit idea at ETF level.
- The Co-Pricing Factor Zoo (2026) provides context that corporate-bond factors can become redundant once common equity and Treasury term risks are handled.

## Design

Data source: `yfinance`, daily OHLCV and adjusted close.

Sample: starts at available ETF data from 2009; OOS starts `2015-01-02`.

Signals:

- `momentum_63`: 63-trading-day adjusted-price momentum.
- `carry_252`: 252-day total-return minus close-price return, a dividend/carry proxy.
- `illiquidity_amihud_21`: 21-day Amihud-style `|return| / dollar_volume`.
- `range_vol_21`: 21-day high-low range over close.
- `credit_beta_126`: 126-day beta to `HYG - LQD` credit return.
- `term_beta_126`: 126-day beta to `TLT` return.

Portfolio construction: daily cross-sectional rank-weighted long-high/short-low factor return across the corporate-bond ETF set.

Bias-correction proxy:

- Naive: signal at `t` predicts adjusted return from `t` to `t+1`.
- Bias-corrected: `signal.shift(1)` predicts adjusted return from `t` to `t+1`.

The extra lag is conservative and breaks the shared `P_t` denominator between price-based signals and next-period returns. It is not a full Open Bond Asset Pricing correction.

Formal test: `volpred.stats.model_evaluation.strategy_dm_test` against zero return, `h=5`; Harvey-style pass requires `DM t < -3` and positive annualized return.

## Results

Run:

```bash
uv run python experiments/k1522/k1522.py
```

Outputs:

- `k1522_results.json`
- `k1522_factor_audit.png`

Verdict: `NULL_ETF_PROXY`.

Key numbers from the 2015-2026 OOS:

| Signal | Bias-corrected Sharpe | Ann. return | DM t vs zero | Harvey pass |
|---|---:|---:|---:|---|
| `carry_252` | `0.251` | `0.71%` | `-0.978` | no |
| `range_vol_21` | `0.173` | `0.57%` | `-0.640` | no |
| `credit_beta_126` | `0.111` | `0.44%` | `-0.483` | no |
| `illiquidity_amihud_21` | `-0.074` | `-0.18%` | `0.336` | no |
| `term_beta_126` | `-0.080` | `-0.32%` | `0.337` | no |
| `momentum_63` | `-0.320` | `-1.06%` | `1.035` | no |

No ETF proxy factor delivers positive premium with Harvey-strength evidence after the extra-lag correction. The best corrected signal is `carry_252`, but its DM statistic is far from the `|t| > 3` threshold.

The naive-to-corrected comparison does not show a large hidden premium being destroyed by the correction either: the largest Sharpe drop is `range_vol_21` (`0.214` to `0.173`), and no naive signal passed Harvey before correction. This supports a conservative null: the ETF proxy does not rescue a tradable corporate-bond factor-zoo claim.

## Integrity Notes

- Signals are current or lagged; the bias-corrected headline uses `signal.shift(1)`.
- The experiment does not write `knowledge.json`.
- ETF-level evidence must not be described as bond-level factor-zoo replication.
