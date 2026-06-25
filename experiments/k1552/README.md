# K1552 - Investor-Memory Cue Public Proxy

## Research Question

Can a public, similarity-based proxy for investor memory predict next-day or next-week volatility persistence, turnover pressure, left-tail returns, or continuation/reversal in US sector ETFs?

The experiment is intentionally narrower than the motivating paper. It does not observe investor recall or account-level trades. It tests whether market return patterns that resemble prior crash/rally episodes contain incremental information for ETF activity and volatility after explicit lagging and controls.

## Literature Basis

- Jiang, Liu, Peng, and Yan (2025), "Investor Memory and Biased Beliefs: Evidence from the Field," *Quarterly Journal of Economics*, 140(4), 2749-2804. The paper finds similarity-based recall affects expectations and trading in investor-level survey plus transaction data. Source: https://academic.oup.com/qje/article/140/4/2749/8215190
- Bordalo, Gennaioli, and Shleifer (2020), "Memory, Attention, and Choice," *Quarterly Journal of Economics*, 135(3), 1399-1442. The model formalizes associative recall of similar experiences and its effect on valuation/choice. Source: https://academic.oup.com/qje/article/135/3/1399/5824669
- Greenwood and Shleifer (2014), "Expectations of Returns and Expected Returns," *Review of Financial Studies*, 27(3), 714-746. Investor expected returns are strongly related to past returns and market levels, but negatively related to model-based expected returns. Source: https://academic.oup.com/rfs/article/27/3/714/1580705
- Malmendier and Nagel (2011), "Depression Babies: Do Macroeconomic Experiences Affect Risk Taking?", *Quarterly Journal of Economics*, 126(1), 373-416. Lifetime return experiences affect risk taking, participation, and return beliefs. Source: https://academic.oup.com/qje/article/126/1/373/1901343

Related project context: K1502 and K1530 tested retail-flow / retail-like participation proxies and found weak or null OOS support. K1552 is different because the signal is a similarity-based recall cue, not retail-flow level or generic sentiment.

## Data

- Source: yfinance daily adjusted OHLCV.
- Assets: `SPY`, `QQQ`, `IWM`, `XLB`, `XLE`, `XLF`, `XLI`, `XLK`, `XLP`, `XLU`, `XLV`, `XLY`, `XLRE`.
- Control: `^VIX` daily close.
- Download window: 2000-01-01 to 2026-06-26.
- Cached data: `data/prices.parquet`.

The script writes `data/data_availability.csv`, `data/asset_panel.parquet`, `data/asset_panel_preview.csv`, `data/aggregate_daily.csv`, and `data/per_ticker_regressions.csv`.

## Method

For each ETF and date `d`, the script computes recent return cues:

```text
ret5_d  = cumulative close-to-close log return over 5 trading days
ret21_d = cumulative close-to-close log return over 21 trading days
```

The historical episode library is the trailing 1260 trading days ending at `d-22`. Loss and rally episodes are the bottom and top 5% of historical `ret21` inside that library. Similarity is:

```text
similarity = exp(-0.5 * standardized Euclidean distance^2)
```

The raw loss/rally memory cue is the maximum similarity to prior loss/rally episodes. Predictive variables are explicitly lagged:

```python
df["loss_memory_lag1"] = df["loss_memory_raw"].shift(1)
df["rally_memory_lag1"] = df["rally_memory_raw"].shift(1)
```

Primary aggregate regressions use equal-weight cross-ETF daily averages and HAC(5) standard errors. Controls include target lag, 5-day return, 21-day absolute return, 21-day RV, `^VIX`, and coverage count. Primary targets:

- `log_range_var`
- `log_fwd5_rv`
- `volume_z`
- `downside_ret`

Formal gate:

- Harvey reference: expected-direction `|t| >= 3`.
- Bonferroni 5% over eight primary signal-target cells.
- Moving-block bootstrap with 1000 reps and 21-day blocks for the strongest absolute-t cell.
- `SEED = 42`.

## Reproduction

```bash
uv run python experiments/k1552/k1552.py
```

Main artifacts:

- `k1552.py`
- `k1552_results.json`
- `figures/k1552_memory_cues.png`
- `figures/k1552_primary_tstats.png`
- `figures/k1552_event_spreads.png`

## Results

Verdict: `NULL_AMPLIFICATION_WITH_OPPOSITE_RALLY_DECOMPRESSION`.

Sample and artifacts from the 2026-06-25 run:

- Asset panel rows: 82,487.
- Aggregate daily rows with valid memory signals: 5,375.
- Last yfinance price date in cache: 2026-06-24.
- Bootstrap: 1000 moving-block reps, 21-day blocks, seed 42.

Primary aggregate HAC/Bonferroni gate:

| Target | Signal | Coef | HAC t | p | Direction vs amplification hypothesis |
|---|---:|---:|---:|---:|---|
| `log_range_var` | loss memory | +0.0932 | +1.12 | 0.263 | expected sign, not significant |
| `log_range_var` | rally memory | -0.2616 | -3.72 | 0.000201 | significant, opposite sign |
| `log_fwd5_rv` | loss memory | -0.0523 | -0.44 | 0.658 | opposite, not significant |
| `log_fwd5_rv` | rally memory | -0.5261 | -4.72 | 0.000002 | significant, opposite sign |
| `volume_z` | loss memory | +0.0622 | +0.94 | 0.348 | expected sign, not significant |
| `volume_z` | rally memory | -0.3215 | -5.58 | 0.00000002 | significant, opposite sign |
| `downside_ret` | loss memory | +0.0054 | +2.44 | 0.0148 | opposite sign; less negative downside |
| `downside_ret` | rally memory | +0.0066 | +3.43 | 0.000606 | significant, opposite sign; less negative downside |

There are **0 expected-direction Bonferroni passes** and **0 expected-direction Harvey `|t| >= 3` passes**. The strongest absolute-t cell is `rally_memory_lag1 -> volume_z`, but it is negative. Its moving-block bootstrap coefficient CI is `[-0.4573, -0.1894]`, confirming the opposite-direction estimate.

Event-spread diagnostics are more suggestive but fail the controlled formal gate. High loss-memory days have higher raw average `log_fwd5_rv` (+0.838), `log_range_var` (+0.826), and `volume_z` (+0.710) than other days, but these spreads do not survive the aggregate HAC regression after lagged return/RV/VIX controls.

Secondary per-ticker regressions produce 3 expected-direction Harvey passes across 78 cells, but this is not the primary gate and is not promoted as an independent discovery.

Interpretation: this public sector-ETF proxy does **not** support the hypothesis that similarity to prior crash/rally episodes robustly amplifies future volatility or activity. The controlled aggregate evidence instead says rally-like memory cues are associated with lower subsequent volatility/activity and less downside. This should be treated as a null/opposite proxy result, not as evidence against the investor-level QJE mechanism.

## Limitations

- This is not a replication of the QJE 2025 investor-level memory survey and transaction evidence.
- Sector ETF similarity cues are only public-market proxies; they can overlap with momentum and volatility clustering despite lagged controls.
- Daily OHLCV cannot observe recalled experiences, headline salience, investor composition, or account-level trading.
- XLRE has a shorter history than the older sector ETFs.
- Per-ticker regressions are secondary diagnostics; the primary gate is the aggregate HAC/Bonferroni test set.
- Knowledge promotion is deferred to the canonical writer/gate; this experiment does not directly edit `storage/memory/knowledge.json`.
