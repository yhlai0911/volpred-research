# K1530 — Taiwan Retail Participation x Recent-Return Interaction For 0050 RV

## Motivation

Backlog question:

> 台股散戶占比 × 近期報酬 interaction 是否預測台股 realized volatility？尤其高散戶活躍度遇到近期負報酬後，次日 RV 是否放大？

This experiment is a conservative hourly-run pilot. It does not have an official
full-market TWSE retail-share series. Instead, it tests two 0050 ETF-level public
proxies:

1. Residual retail participation:
   `1 - (institutional buys + institutional sells) / (2 * 0050 volume)`
2. Margin activity turnover:
   `(margin buy + margin sell + short-sale buy + short-sale sell) / 0050 volume`

These are proxies, not direct household-trading records.

## Literature And Prior-K Context

External references checked:

- Chordia, Lin, and Xiang (2025), "Return Extrapolation and Volatility
  Expectations": recent returns affect volatility expectations.
  https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/issue/3DDD308732093871E6909F7D3A647F0C
- Foucault, Sraer, and Thesmar (2011), "Individual Investors and Volatility":
  retail trading activity can contribute to return volatility.
  https://faculty.haas.berkeley.edu/dsraer/SRD.pdf
- Boehmer, Jones, Zhang, and Zhang (2021), "Tracking Retail Investor Activity":
  retail activity can be inferred from public transaction patterns in some
  markets, but the proxy quality matters.
  https://eng.pbcsf.tsinghua.edu.cn/__local/6/B0/AF/2A35AA5BBB6B2C05786716FA0DF_098DC0E7_107C03.pdf?e=.pdf

Related VolPred priors:

- K1518: weekly TWSE foreign-flow sector-vol predictor was NULL.
- K1374: Taiwan ex-dividend individual-stock event vol effect exists, but ETF
  aggregation can dilute effects.
- K1098 / K1316: cross-market VIX channel is weak for Taiwan vol once tested
  strictly.

## Data

- `storage/macro/yf_0050.TW.csv`
- `storage/sentiment/tw_institutional_0050.csv`
- `storage/sentiment/tw_margin_0050.csv`

Effective price sample:

- 2009-01-05 to 2026-03-17
- OOS starts 2022-01-01
- Valid residual-retail observations: 3370
- Valid margin observations: 3383
- Residual retail-share mean: 0.8177
- Residual retail-share 5th to 95th percentile: 0.4991 to 0.9152

## Method

Targets:

- Day-t annualized squared return, `r2_ann`
- Day-t annualized Parkinson high-low variance, `parkinson_ann`

Baseline features:

- lagged log RV 1 / 5 / 22
- lagged 5-day return
- lagged negative 5-day return

Augmented features:

- lagged retail proxy z-score
- lagged retail proxy z-score × lagged max(-past 5-day return, 0)

Lookahead guard:

- Target is day t.
- Every predictor uses explicit `.shift(1)`.
- This implements `signal from t-1, return / RV at t`.

Inference:

- HAC OLS maxlags=5 for the interaction coefficient.
- Fixed train/OOS split for log-RV prediction.
- Patton QLIKE OOS loss and DM HAC h=1.
- Four headline interaction tests: 2 targets × 2 proxies.
- Bonferroni alpha = 0.0125.
- Harvey OOS pass requires DM t < -3.

## Results

Verdict: `MIXED_PROXY_WEAK_OOS`.

Headline numbers:

| Target | Proxy | Interaction HAC t | Bonferroni pass | OOS QLIKE improvement | DM t | Harvey pass |
|---|---:|---:|---:|---:|---:|---:|
| r2_ann | residual retail | -3.9515 | yes | +9.5498% | -1.7963 | no |
| r2_ann | margin activity | +2.9518 | yes | +8.9273% | -1.5288 | no |
| Parkinson | residual retail | -0.8018 | no | +11.8256% | -2.7765 | no |
| Parkinson | margin activity | +1.2609 | no | +9.5890% | -1.8738 | no |

Interpretation:

- The residual-retail `r2_ann` interaction is statistically strong but has the
  opposite sign from the simple "high retail after losses amplifies RV" story.
- Margin activity has the expected positive interaction sign for `r2_ann`, but
  OOS QLIKE improvement is not Harvey-strength.
- Parkinson target gives the largest OOS QLIKE improvement, but the interaction
  coefficient itself is not Bonferroni-significant and DM t is still below the
  Harvey bar.

Conclusion: this is a mixed proxy result. It suggests there may be some
information in 0050 retail-like activity proxies, but the evidence is not strong
enough for a publishable claim that retail participation × recent losses robustly
predicts Taiwan ETF RV.

## Limitations

- Residual retail participation is inferred for 0050 only, not the official
  full-market retail share.
- Institutional and margin local snapshots end in March 2026.
- ETF trading can reflect creation/redemption, hedging, and liquidity provision,
  not just household retail trading.
- Daily OHLC cannot identify intraday order imbalance.
- Stock-level cross-section may differ from 0050 ETF behavior.

## Reproduction

```bash
uv run python experiments/k1530_tw_retail_interaction_rv/k1530_tw_retail_interaction_rv.py
```

Artifacts:

- `experiments/k1530_tw_retail_interaction_rv/k1530_tw_retail_interaction_rv.py`
- `experiments/k1530_tw_retail_interaction_rv/k1530_tw_retail_interaction_rv_results.json`
- `experiments/k1530_tw_retail_interaction_rv/k1530_tw_retail_interaction_rv.png`
