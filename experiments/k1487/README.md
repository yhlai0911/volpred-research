# K1487: GDELT novel-risk intensity as a daily RV leading signal

## Motivation

This experiment tests the backlog idea "LLM novel-risk intensity as an RV leading signal" with a conservative first pass. Instead of claiming a full LLM classifier, it uses a transparent keyword taxonomy on GDELT DOC 2.0 TimelineVol:

- AI infrastructure
- private credit
- tariffs and trade war
- cyber risk
- supply-chain disruption

The question is whether this daily novel-risk intensity adds out-of-sample realized-volatility forecast value for SPY, QQQ, HYG, and TLT.

## Prior Work Checked

Project context:

- K531: FRED sentiment and uncertainty proxies do not improve OOS volatility prediction beyond VIX.
- K446: geopolitical-risk news index does not add reliable realized-volatility forecast value beyond VIX.
- K1268: GDELT public bulk data is usable, but historical intraday SPY data blocked the high-frequency test.

External references:

- GDELT DOC 2.0 API: TimelineVol reports matched news coverage as share of total monitored coverage.
- Tetlock (2007), Journal of Finance: media content and market activity.
- Baker, Bloom, Davis (2016), QJE: newspaper-frequency uncertainty index.
- RiskLabs, arXiv:2404.07452: LLM-based financial risk prediction motivation.

## Data

- Market data: yfinance adjusted close for SPY, QQQ, HYG, TLT, and ^VIX.
- Market sample: 2023-01-03 to 2026-06-12.
- Novel-risk data: GDELT DOC 2.0 TimelineVol daily volume intensity, `sourceCountry:US`.
- GDELT sample: 2023-01-01 to 2026-06-12.
- OOS start: 2025-01-01.

The GDELT API is rate-limited. Raw API JSON responses are cached under `data/`; the combined panel is written to `data/gdelt_theme_intensity.csv`.

## Method

Targets:

- h=1: close-to-close squared log return, `r_t^2`.
- h=5: forward five-trading-day mean squared log return.

Models:

- HAR: lagged daily, weekly, and monthly realized variance.
- HAR_NovelComposite: HAR plus equal-weight novel-risk z-score composite.
- HAR_VIX: HAR plus lagged VIX-implied daily variance.
- HAR_VIX_NovelComposite: HAR_VIX plus novel-risk composite.
- HAR_VIX_NovelThemes: HAR_VIX plus all five theme z-scores.

Lookahead controls:

- GDELT features use explicit `.shift(1)` in `expanding_z_lagged()`.
- VIX and HAR realized-volatility features use `.shift(1)`.
- For h=5, the expanding regression excludes training targets not fully observed before forecast origin t.

Evaluation:

- OOS QLIKE, MSE, Spearman rank correlation.
- Diebold-Mariano tests use `volpred.stats.model_evaluation.dm_test`.
- Harvey gate: `|t| > 3.0`.

## Results

Verdict: **NULL_NEGATIVE**.

Active GDELT themes actually retrieved:

- `ai_infrastructure`
- `private_credit`
- `cyber`

Unavailable due to GDELT HTTP 429 during this hourly run:

- `tariff_trade`
- `supply_chain`

Mean OOS QLIKE across SPY/QQQ/HYG/TLT:

| Horizon | HAR | HAR + novel | HAR + VIX | HAR + VIX + novel composite | HAR + VIX + novel themes |
|---:|---:|---:|---:|---:|---:|
| 1 day | 3.7349 | 4.0342 | 2.5502 | 2.6898 | 2.8047 |
| 5 day | 0.6502 | 0.6879 | 0.4818 | 0.5010 | 0.5075 |

No novel-risk augmentation improves QLIKE in any asset/horizon comparison. Several one-day comparisons are Harvey-significantly **worse**:

| Asset | Horizon | Comparison | DM t | p-value | QLIKE improvement |
|---|---:|---|---:|---:|---:|
| HYG | 1 | HAR_VIX_NovelThemes vs HAR_VIX | +3.504 | 0.00052 | -10.26% |
| TLT | 1 | HAR_NovelComposite vs HAR | +4.350 | 0.000018 | -15.27% |
| TLT | 1 | HAR_VIX_NovelComposite vs HAR_VIX | +4.412 | 0.000014 | -14.33% |
| TLT | 1 | HAR_VIX_NovelThemes vs HAR_VIX | +4.066 | 0.000059 | -13.32% |

DM sign convention: negative t means the novel-risk challenger has lower QLIKE loss. All significant values above are positive, so they indicate significant deterioration.

Conclusion: daily GDELT keyword intensity for AI/private-credit/cyber risk should **not** be treated as a reliable RV leading signal in this pilot. It is directionally consistent with prior K531/K446 VIX-sufficiency evidence.

Run:

```bash
uv run python experiments/k1487/k1487.py
```

Artifacts:

- `k1487.py`
- `k1487_results.json`
- `figures/k1487_qlike_by_asset.png`
- `figures/k1487_signal_vs_spy_rv.png`
- `data/gdelt_theme_intensity.csv`

## Interpretation Rules

This is a keyword-only pilot. A positive result would justify a second-stage open-source LLM classifier. A null result should be read as evidence that coarse daily public-news coverage is unlikely to beat HAR/VIX baselines, not as a proof that all LLM narrative systems are useless.
