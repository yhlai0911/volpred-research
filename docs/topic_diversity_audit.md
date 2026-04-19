# Topic Diversity Audit

_Generated: 2026-04-19 19:30 UTC — source: `storage/reports/feed.json` (tags), `experiments/` (dir names), `storage/memory/knowledge.json` (K categories + content keyword scan). Re-run: `uv run python scripts/build_topic_diversity_audit.py`._

## Purpose

1. Show the **dominant topic axes** the platform has accumulated — so the main thread can see where the coverage is.
2. Surface **under-explored topics** for novelty quota selection (per user 2026-04-19 directive: reserve slots to step off the dominant axes).

## Source-level Stats

- Feed tags: 4731 total tokens / 1097 unique (after stop-word filter)
- Experiments: 1139 dirs (K-numbered + named)
- Knowledge records: sum of category counts = 2043

## Top 30 feed tags (topic signal, stop-words removed)

| rank | tag | count | latest article |
|---|---|---|---|
| 1 | SPY | 342 | 2026-04-19 |
| 2 | 波動率預測 | 250 | 2026-04-19 |
| 3 | VIX | 189 | 2026-04-19 |
| 4 | VT策略 | 178 | 2026-04-18 |
| 5 | GLD | 172 | 2026-04-19 |
| 6 | GARCH | 167 | 2026-04-17 |
| 7 | GJR-GARCH | 133 | 2026-04-19 |
| 8 | VaR | 125 | 2026-04-12 |
| 9 | 風險管理 | 124 | 2026-04-19 |
| 10 | 0050.TW | 82 | 2026-04-19 |
| 11 | 波動率 | 78 | 2026-04-19 |
| 12 | 12/VIX | 71 | 2026-04-18 |
| 13 | Hybrid-VT | 70 | 2026-03-16 |
| 14 | 跨資產 | 65 | 2026-04-19 |
| 15 | 危機分析 | 65 | 2026-03-18 |
| 16 | 台股 | 48 | 2026-04-19 |
| 17 | Gamma效應 | 38 | 2026-03-16 |
| 18 | VT | 34 | 2026-04-19 |
| 19 | 50/50 | 34 | 2026-04-17 |
| 20 | 每日建議 | 32 | 2026-04-18 |
| 21 | TLT | 32 | 2026-04-15 |
| 22 | BTC | 32 | 2026-04-15 |
| 23 | COVID | 30 | 2026-04-19 |
| 24 | 避險 | 29 | 2026-04-11 |
| 25 | QLIKE | 28 | 2026-04-18 |
| 26 | VRP | 27 | 2026-04-10 |
| 27 | QQQ | 23 | 2026-04-14 |
| 28 | HAR-RV | 22 | 2026-04-19 |
| 29 | 方法論 | 21 | 2026-04-19 |
| 30 | 0050 | 21 | 2026-04-19 |

## Top 20 experiment-dir tokens (from named experiments)

| rank | token | count |
|---|---|---|
| 1 | charts | 18 |
| 2 | vol | 14 |
| 3 | k1100g | 10 |
| 4 | vix | 7 |
| 5 | asset | 5 |
| 6 | garch | 4 |
| 7 | pilot | 4 |
| 8 | cross | 4 |
| 9 | k1148 | 3 |
| 10 | decomposition | 3 |
| 11 | btc | 3 |
| 12 | regime | 3 |
| 13 | hybrid | 3 |
| 14 | term | 3 |
| 15 | structure | 3 |
| 16 | analysis | 3 |
| 17 | frequency | 2 |
| 18 | var | 2 |
| 19 | k880v2 | 2 |
| 20 | structural | 2 |

## Top 20 knowledge.json categories

| rank | category | count |
|---|---|---|
| 1 | unknown | 387 |
| 2 | model_behavior | 227 |
| 3 | experiment | 219 |
| 4 | experiment_result | 96 |
| 5 | knowledge | 53 |
| 6 | vol_prediction | 52 |
| 7 | vt_strategy | 48 |
| 8 | research_methodology | 43 |
| 9 | strategy | 38 |
| 10 | data_property | 37 |
| 11 | strategies | 36 |
| 12 | literature | 35 |
| 13 | strategy_optimization | 35 |
| 14 | cross_asset | 34 |
| 15 | model_comparison | 29 |
| 16 | leverage_effect | 27 |
| 17 | vol_models | 27 |
| 18 | research_finding | 27 |
| 19 | market_context | 26 |
| 20 | var_methods | 24 |

## Dominant topic clusters (synthesized)

Each cluster aggregates related tags. `feed_ct` = sum of tag counts in feed.json; `exp_ct` = experiments with dir-name matching any cluster keyword (approx).

| cluster | feed_ct | exp_ct | latest feed date |
|---|---|---|---|
| SPY / US equity core | 371 | 0 | 2026-04-19 |
| GARCH family (GARCH/GJR/EGARCH) | 318 | 6 | 2026-04-19 |
| VT strategies / VT-family | 301 | 14 | 2026-04-19 |
| VIX & VIX-derivatives | 272 | 7 | 2026-04-19 |
| GLD / gold / commodities | 206 | 1 | 2026-04-19 |
| VaR / ES / tail risk | 186 | 13 | 2026-04-12 |
| Taiwan market (0050 / TAIFEX) | 169 | 1 | 2026-04-19 |
| Model diagnostics (DM / MCS / QLIKE) | 72 | 1 | 2026-04-19 |
| Crypto / BTC / ETH | 62 | 6 | 2026-04-15 |
| HAR-RV / realized vol | 52 | 20 | 2026-04-19 |
| Leverage / regime / gamma | 46 | 0 | 2026-04-19 |
| FOMC / Fed / rate events | 44 | 0 | 2026-04-18 |
| Behavioral / DCA / retail | 38 | 1 | 2026-04-18 |
| VRP / options | 36 | 1 | 2026-04-14 |
| TLT / bonds / duration | 32 | 0 | 2026-04-15 |
| Earnings / corporate events | 29 | 0 | 2026-04-19 |
| Deep learning (LSTM / NN) | 25 | 4 | 2026-04-17 |
| GARCH-MIDAS / mixed-frequency | 23 | 1 | 2026-04-19 |
| Copula / DCC / dependence | 17 | 0 | 2026-04-07 |
| Bayesian / SSVS / ML-avg | 15 | 0 | 2026-04-05 |
| Overnight / intraday / gap | 12 | 0 | 2026-04-11 |
| Momentum / TSMOM | 9 | 3 | 2026-04-04 |

## Under-explored topic probe

Each probed topic: how many feed tags & knowledge-records mention its keywords. Low scores = genuine gaps; `feed_ct=0` with small `kb_ct` = novelty quota candidates.

| topic | feed_ct | kb_ct (content match) |
|---|---|---|
| reinforcement learning vol | 0 | 0 |
| high-frequency microstructure (sub-5min) | 0 | 0 |
| intraday seasonality / session-boundary | 0 | 0 |
| crypto-stablecoin spillover | 0 | 2 |
| bayesian model averaging vol | 0 | 2 |
| model confidence sets / SPA / Reality Check | 0 | 3 |
| dynamic Nelson-Siegel / term structure ML | 1 | 0 |
| climate event vol (已有 1 experiment — extend) | 1 | 0 |
| retail order flow / gamma squeeze | 0 | 4 |
| REIT / housing vol | 1 | 1 |
| options IV surface / skew dynamics | 0 | 6 |
| commodities ex-GLD (oil, copper, ag) | 0 | 6 |
| network / systemic risk (ex-CoVaR) | 1 | 7 |
| sentiment / NLP text signals | 1 | 9 |
| credit / CDS / funding stress | 0 | 13 |
| climate / physical risk / ESG | 2 | 7 |
| cross-border policy / geopolitical | 1 | 12 |
| FX vol / DXY / carry | 3 | 10 |
| realized semivariance / signed jumps | 3 | 10 |
| ML interpretability / SHAP | 4 | 44 |

## Recommended novelty candidates (5-10)

These are topics with **no feed coverage** (feed_ct=0) and low knowledge-base footprint. Pick 1-2 per novelty-quota cycle; confirm no in-flight experiment before dispatching.

1. **reinforcement learning vol** — feed_ct=0, kb_ct=0
2. **high-frequency microstructure (sub-5min)** — feed_ct=0, kb_ct=0
3. **intraday seasonality / session-boundary** — feed_ct=0, kb_ct=0
4. **crypto-stablecoin spillover** — feed_ct=0, kb_ct=2
5. **bayesian model averaging vol** — feed_ct=0, kb_ct=2
6. **model confidence sets / SPA / Reality Check** — feed_ct=0, kb_ct=3
7. **retail order flow / gamma squeeze** — feed_ct=0, kb_ct=4
8. **options IV surface / skew dynamics** — feed_ct=0, kb_ct=6
9. **commodities ex-GLD (oil, copper, ag)** — feed_ct=0, kb_ct=6
10. **credit / CDS / funding stress** — feed_ct=0, kb_ct=13

## Notes / methodology

- Stop-words (`研究`, `一般讀者`, K-numbers, etc.) removed from tag frequency to avoid swamping the top table.
- `exp_ct` uses substring match on directory name; it under-counts K-numbered experiments (which are labeled by serial ID, not topic). The true experiment coverage for each cluster is higher — treat `exp_ct` as a lower bound.
- `kb_ct` counts distinct K records whose `content` field contains any probe keyword (case-insensitive).
- To refine gap detection, extend `PROBE_TOPICS` in `scripts/build_topic_diversity_audit.py`.

