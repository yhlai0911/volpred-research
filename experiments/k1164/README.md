# K1164 — Analyst coverage × media-density mechanism test for cross-market θ_rel cluster

> **TL;DR**: K1153 proposed that **analyst coverage density × earnings-season media
> concentration** drives the 2-cluster split in θ_rel (US/JP HIGH vs TW/EU LOW).
> K1164 tests this with yfinance-reported analyst counts and market-cap/turnover
> proxies across the 109 stocks in K1145+K1147+K1150+K1153. **Verdict: REJECTED.**
> (a) The 4-market rank ordering by analyst coverage is `TW < JP < EU < US`, but
> the θ_rel cluster split requires `TW < EU < JP < US`: **EU has more analysts
> than JP yet sits in the LOW θ_rel cluster, and JP has fewer analysts than EU yet
> sits in the HIGH cluster** — a direct contradiction. (b) Cross-market
> Spearman ρ(analyst_median, θ_rel) = +0.40 with p=0.60 (N=4 markets), far below
> the 0.7 threshold. (c) The per-stock panel with market FE yields
> log_analyst β = -0.149, t = -4.55 — but this is confounded by a mechanical
> tautology: within every market, log(analyst) correlates positively with σ²_i
> (US ρ=+0.65), and θ_rel_i = θ_EAV_shared / σ²_i by construction, so the negative
> sign is a size/vol artifact, not a mechanism. K1153's new hypothesis does not
> survive the mechanism test.

[提出: Claude (承接 K1153 next_tasks K1164), 執行: Claude]

**Random seed**: 42
**N stocks**: 109 (TW 31 + US 30 + JP 30 + EU 18)
**N markets**: 4 — **preliminary only; recommend K1165 extension to N≥8 markets**

---

## 1. 動機（Why）

K1145 (TW, N=31) + K1147 (US, N=30) + K1150 (JP, N=30) + K1153 (EU, N=18) 四市場
pooled θ_EAV direction universally positive (all Harvey t>3). But after scale
normalization (θ_rel = θ_EAV / avg_σ²), a 2-cluster pattern emerged:

| Cluster | Markets | θ_rel |
|---------|---------|-------|
| **LOW** | TW, EU | 0.17, 0.14 |
| **HIGH** | JP, US | 0.39, 0.59 |

K1152 first proposed **quarterly-reporting cadence** as the driver; K1153 rejected
it (EU is 100% quarterly reporters yet in LOW cluster). K1153 then proposed a
**new hypothesis**:

> *High sell-side analyst coverage density + concentrated earnings-season media
> coverage (e.g., CNBC/Bloomberg for US, Nikkei for JP) → HIGH θ_rel.*
> *Diffuse media and lower analyst coverage per stock (TW retail-dominated;
> EU fragmented across national press) → LOW θ_rel.*

**K1164 is the direct mechanism test.** If true:
- ρ(analyst_median, θ_rel) cross-market should be large and positive
- The 4-market rank ordering by analyst coverage should replicate the cluster split
- Per-stock panel (within market FE) should show a positive analyst-θ_rel relation

---

## 2. 方法（What）

### 2.1 Data

**Per-stock proxies (current snapshot, yfinance)**:
- `numberOfAnalystOpinions` — current analyst count (fallback: sum of buy/hold/sell counts from `get_recommendations_summary()`)
- `marketCap` — current market capitalisation
- `median_daily_turnover` — median of `Close × Volume` over full cached daily history (reused from K1145/K1147/K1150/K1153 parquet data)

**Market-level θ_rel**: reused from K1152 (TW/US/JP) and K1153 (EU).

**Per-stock θ_rel_i**: constructed as
$$\theta_{\mathrm{rel},i} = \theta_{\mathrm{EAV}}^{\mathrm{shared}} / \sigma^2_i$$
where:
- $\theta_{\mathrm{EAV}}^{\mathrm{shared}}$ is the shared panel coefficient from the corresponding K experiment (TW +6.36e-5, US +1.91e-4, JP +1.41e-4, EU +4.07e-5).
- $\sigma^2_i$ is stock $i$'s empirical variance of daily log-returns.

This definition matches K1152's market-level θ_rel and allows within-market
variation by stock. But note: it is **mechanically inverse to $\sigma^2_i$** (see §4.3 tautology diagnostic).

### 2.2 Three tests

1. **Cross-market Spearman (N=4)** — rank correlation between market-mean
   (analyst_median, log_marketcap_mean, log_turnover_mean) and documented θ_rel.
2. **Rank-ordering check** — does the sorted analyst rank match the cluster split?
   Expected (hypothesis): bottom two = {TW, EU} (LOW cluster), top two = {US, JP}.
3. **Panel OLS with market fixed effects** — per-stock regression
   $$\theta_{\mathrm{rel},i} = \sum_m \alpha_m D_{m,i} + \beta_1 \log(\text{analyst}_i) + \beta_2 \log(\text{mcap}_i) + \beta_3 \log(\text{turnover}_i) + \varepsilon_i$$
   with HC0 White robust SE. Market FE absorb level differences; β₁ captures
   within-market analyst coverage effect.

### 2.3 Lookahead discipline

Analyst count and market cap are **current snapshots**, not historical.
They are proxies for *long-run institutional characteristics*, which should be
approximately stable over the 2012-2025 sample. Formal 12M trailing analyst
count requires IBES data (paywalled) and is out of scope for this preliminary
4-market test. Results should be interpreted as correlations between long-run
institutional features and θ_rel, not causal claims.

Random seed 42 throughout.

---

## 3. 資料

| Source | Contents |
|--------|----------|
| `experiments/k1145/k1145_results.json` | TW θ_EAV_shared, per-stock tickers |
| `experiments/k1147/k1147_results.json` | US θ_EAV_shared, per-stock tickers |
| `experiments/k1150/k1150_results.json` | JP θ_EAV_shared, per-stock tickers |
| `experiments/k1153/k1153_results.json` | EU θ_EAV_shared, per-stock tickers |
| `experiments/kXXXX/data/*.parquet` | Reused cached daily OHLCV per stock |
| `experiments/k1164/data/analyst_media_proxies.json` | yfinance analyst / mcap / turnover snapshot |

109 stocks total; 108 complete observations after drop-na on the three proxies.

---

## 4. 結果（Findings）

### 4.1 Per-market summary

| Market | Cluster | n | Analyst mean | Analyst median | log(mcap) mean | log(turnover) mean | Documented θ_rel |
|--------|---------|---|--------------|----------------|-----------------|---------------------|-------------------|
| TW | LOW | 31 | 9.37 | 7.5 | 26.56 | 19.24 | 0.167 |
| EU | LOW | 18 | 20.94 | 21.0 | 25.31 | 19.67 | 0.137 |
| JP | HIGH | 30 | 15.03 | 14.5 | 29.99 | 23.37 | 0.388 |
| US | HIGH | 30 | 34.23 | 32.5 | 27.12 | 20.81 | 0.586 |

(JP log-mcap inflated due to JPY currency units; turnover similarly.)

### 4.2 Cross-market Spearman (N=4)

| Feature | Spearman ρ | p | Pearson r |
|---------|------------|---|-----------|
| analyst_mean | +0.400 | 0.600 | +0.730 |
| analyst_median | +0.400 | 0.600 | +0.699 |
| log_marketcap_mean | **+0.800** | 0.200 | +0.490 |
| log_turnover_mean | +0.600 | 0.400 | +0.532 |

**No correlation reaches ρ ≥ 0.7 with significance at N=4.** `log_marketcap_mean`
is the highest (ρ=+0.80, p=0.20), but this is confounded by currency units (JP's
JPY-denominated market cap is ~100× nominal). Pearson r on analyst (+0.70) is
close to threshold but reflects the single US outlier (34 analysts); Spearman
(+0.40) is the robust rank statistic.

### 4.3 Rank-ordering check (key test)

| Ranking variable | Low→High order | Cluster prediction match? |
|-------------------|----------------|----------------------------|
| θ_rel (documented) | EU (0.14) < TW (0.17) < JP (0.39) < US (0.59) | — |
| analyst_median | TW (7.5) < JP (14.5) < EU (21.0) < US (32.5) | **NO** |
| log_mcap_mean | EU (25.3) < TW (26.6) < US (27.1) < JP (30.0) | NO (JP outlier from JPY) |
| log_turnover_mean | TW (19.2) < EU (19.7) < US (20.8) < JP (23.4) | NO (JP outlier) |

**The critical contradiction**: K1153's hypothesis requires the bottom two by
analyst coverage to be {TW, EU} (LOW cluster) and the top two to be {JP, US}
(HIGH cluster). But the actual rank order is `TW < JP < EU < US`, meaning:

- **EU has more analysts (21) than JP (14.5)** — but EU sits in LOW θ_rel cluster and JP in HIGH.
- **JP (HIGH cluster) has fewer analysts than EU (LOW cluster)** — inversion.

This single empirical fact rules out analyst density as the primary driver.

### 4.4 Panel regression (per-stock, with market FE)

n = 108, R² = 0.614, HC0 robust SE:

| Coefficient | β | SE (HC0) | t |
|-------------|---|----------|---|
| D_TW | +0.271 | 0.543 | +0.50 |
| D_US | +1.077 | 0.545 | **+1.98** |
| D_JP | +0.574 | 0.603 | +0.95 |
| D_EU | +0.387 | 0.505 | +0.77 |
| **log_analyst** | **−0.149** | 0.033 | **−4.55** |
| log_mcap | +0.026 | 0.025 | +1.04 |
| log_turnover | −0.023 | 0.015 | −1.48 |

The `log_analyst` coefficient is **negative and highly significant** (t=−4.55),
the opposite sign of the hypothesis. But this is not decisive evidence of a
"reverse mechanism" because of a **mechanical tautology** (§4.5).

### 4.5 Tautology diagnostic (why the panel coef is an artifact)

By construction θ_rel_i = θ_EAV_shared / σ²_i, so within any given market θ_rel_i
is **rank-inversely tied to σ²_i** (Spearman ρ = −1.000 in every market).
Therefore any variable X that positively correlates with σ²_i within market will
**mechanically** appear to negatively correlate with θ_rel_i.

Within-market Spearman ρ(log(analyst), σ²_i):

| Market | N | ρ | p |
|--------|---|---|---|
| TW | 30 | +0.250 | 0.182 |
| **US** | 30 | **+0.645** | **<0.001** |
| JP | 30 | +0.461 | 0.010 |
| EU | 18 | +0.311 | 0.208 |

In the US (and JP and to a lesser extent TW/EU), high-analyst stocks are
**MORE** volatile than low-analyst stocks within the same market — consistent
with the stylised fact that growth / tech / large-cap momentum names attract both
sell-side coverage and higher idiosyncratic vol. Once σ² is inverted into θ_rel
by construction, this same positive relation shows up as a spurious negative
panel coefficient on log(analyst).

**Implication**: the panel log_analyst coef of −0.149 is **not evidence for or
against any mechanism**; it is a deterministic consequence of the stocks' vol
cross-section. A proper mechanism test must use θ_EAV_i directly (requires per-stock
MLE, not a pooled shared coefficient) — that is the K1166+ extension, not K1164.

### 4.6 Preamble Rule #5 self-challenge

| Check | Status |
|-------|--------|
| ρ > 0.95 on N=4 markets | ✓ none — max ρ=+0.80, not extreme |
| Result is mechanical not empirical | **Panel coef IS mechanical (σ² tautology)** — flagged in verdict_notes |
| Sharpe > 2× baseline | N/A (not a strategy test) |
| N_markets too small | **Yes**: N=4 is insufficient for Spearman rank significance at any meaningful α |
| Cluster assignment cherry-picked | No — clusters derived from K1152/K1153 Wald CI overlap, not from this K |

---

## 5. 結論（Conclusion）

### Verdict: **REJECTED** — analyst coverage × media density is NOT the θ_rel cluster mechanism

Three independent pieces of evidence all point against the K1153 hypothesis:

1. **Rank ordering fails** (decisive): `TW < JP < EU < US` by analyst density
   ≠ cluster ordering `TW, EU ∈ LOW, JP, US ∈ HIGH`. EU has more analysts than
   JP yet lower θ_rel.
2. **Spearman cross-market is weak** (ρ=+0.40, p=0.60) — far below any
   preliminary-confirmation threshold even with the N=4 caveat.
3. **Panel coefficient of the wrong sign** but this is a mechanical σ² artifact
   (within-market high-analyst ↔ high σ² stocks) and cannot be invoked as
   reverse-mechanism evidence either.

### Implication for Paper 2 §5.4

K1153 Section 5 should be **revised** to remove the unsupported analyst/media
hypothesis and be rewritten as:

> "We document a robust two-cluster pattern in θ_rel across four markets
> (TW+EU LOW ≈ 0.14–0.17; JP+US HIGH ≈ 0.39–0.59). K1152's quarterly-cadence
> hypothesis was rejected by EU's inclusion in the LOW cluster (K1153), and a
> subsequent analyst-density × media-concentration hypothesis (K1153 §5.4)
> is also rejected by K1164: cross-market analyst coverage rank fails to
> match the θ_rel cluster ordering (EU has more analysts than JP yet belongs
> to the LOW cluster), and a per-stock panel analysis is confounded by a
> mechanical σ² tautology. **The mechanism behind the two-cluster θ_rel
> pattern therefore remains open.** We leave a systematic investigation of
> alternative drivers (retail-vs-institutional ownership, local regulatory
> announcement-window structure, options market depth, intraday press-release
> timing) to future work."

### Alternative hypotheses to test next

1. **Retail-vs-institutional share** — TW known retail-dominant; EU
   ETF/institutional; JP keiretsu cross-holdings; US mutual fund heavy.
   If retail share drives θ_rel low, TW+EU LOW cluster is coherent; JP+US HIGH
   cluster is not immediately obvious though.
2. **Local options market depth** — US (CBOE) and JP (TSE options) have deep
   equity options; TW (TAIFEX equity options thin) and EU (Eurex options on
   DAX mostly index-level, not single-name) have thinner markets. Options
   traders front-run earnings → pre-announcement IV jump → higher θ_EAV ÷ σ².
3. **Intraday press-release timing** — US after-hours concentration
   (4:30-5:00 pm ET) + pre-market trading captures the announcement-day jump
   cleanly; TW and EU announcements scatter across sessions (dilutes signal).
4. **GDP/USD currency block effect** — US+JP are USD-zone / yen-zone with
   concentrated global capital flows at earnings; TW+EU more diverse capital
   sources.

These require additional data (IBES ownership, OCC options volume, intraday
press timing) and are K1165+ topics.

### 局限承認

- **N_markets = 4 is fatally small** for any cross-market Spearman test;
  the p=0.60 on ρ=+0.40 is not informative. The rank-ordering inversion
  (EU > JP in analysts, EU < JP in θ_rel) is the one finding that does not
  depend on N.
- Analyst count is current yfinance snapshot; historical 12M IBES count
  would be preferred. However, institutional differences in coverage density
  are very stable over 10+ year horizons, so the ordinal ranking is unlikely
  to flip with better historical data.
- θ_rel_i per stock is mechanically tied to σ²_i; any per-stock analysis
  using θ_rel_i as DV is confounded. The cross-market mean-level test
  (§4.2) is unconfounded but has N=4.
- "Media density" was proxied by median_daily_turnover (dollar turnover);
  a true news-intensity proxy (e.g., RavenPack headlines per earnings date)
  would be more direct. Left for K1167+ if warranted.

### Preamble Rule #5 final self-check

⚠️ Rule 1 (mechanical vs empirical): §4.4's negative panel coef on log_analyst
is **mechanical** (σ² tautology) — explicitly flagged in verdict_notes and
§4.5, not claimed as evidence.

⚠️ Rule 3 (Harvey t>3): |panel coef t| = 4.55 > 3, but the sign/interpretation
is confounded → not a valid "PASS"; we do not invoke it as a mechanism finding.

⚠️ Rule 5 (self-question): N=4 markets, ρ not extreme, rank test conclusive →
verdict is REJECTED (strong enough), not "CONFIRMED" (insufficient df).

### 衍生 next_tasks（K1165+）

| K ID | 主題 | 優先度 |
|------|------|--------|
| K1165 | Extend to N≥8 markets (add AU ASX, KR KOSPI, CA TSX, HK HSI; each N≈15-20 stocks) — restore df so cross-market Spearman has power | **高** |
| K1166 | Replace pooled θ_EAV with per-stock θ_EAV_i via stock-level GJR-MIDAS MLE (k1145_refit) → remove σ² tautology → proper per-stock mechanism regression | 高 |
| K1167 | Retail-vs-institutional ownership as panel control (TW FISC, EU ECB, JP MOF, US Russell 3000 13F data) | 中 |
| K1168 | Options volume / implied-vol term structure on earnings day as mediator of θ_EAV | 中 |
| K1169 | Paper 2 §5 rewrite: drop analyst hypothesis, add "mechanism remains open" language, include K1164 as a null result | **高（等 K1165）** |

---

## 6. 檔案

- `k1164_fetch.py` — yfinance fetch of analyst / mcap / turnover per stock
- `k1164.py` — main analysis: per-stock panel, cross-market Spearman, OLS with market FE, rank test
- `k1164_results.json` — full results JSON (4 markets × proxies × θ_rel + Spearman N=4 + panel + verdict)
- `k1164_per_stock_panel.csv` — per-stock panel data for reproducibility
- `k1164_scatter.png` — market-median analyst vs market θ_rel (N=4 scatter)
- `k1164_bar_cluster.png` — θ_rel bar + analyst-median bar, ordered LOW→HIGH
- `data/analyst_media_proxies.json` — raw yfinance fetch results
- `run_fetch.log` — yfinance fetch stdout
- `run.log` — main analysis stdout

---

## 7. 參考文獻

- Bhushan (1989). *Firm characteristics and analyst following*. *JAE* 11(2-3), 255-274. (analyst coverage determinants)
- Brennan & Hughes (1991). *Stock prices and the supply of information*. *JoF* 46(5), 1665-1691. (coverage × price)
- Hong, Lim & Stein (2000). *Bad news travels slowly*. *JoF* 55(1), 265-295. (coverage × announcement timing)
- Hope, Hu & Zhou (2022). *JAR* 60(1), 385-430. (analyst coverage × announcement premium heterogeneity; cited in K1153)
- Engle, Ghysels & Sohn (2013). *RES* 95(3), 776-797. (GARCH-MIDAS long-run τ spec — parent model of A4f-EAV)

---

## 8. 相關 K 編號

- **K1145** — TW N=31 pooled A4f-EAV PASS（θ_EAV = +6.36e-5）
- **K1147** — US N=30 S&P 500 pooled A4f-EAV PASS（θ_EAV = +1.91e-4）
- **K1150** — JP N=30 TOPIX pooled A4f-EAV PASS（θ_EAV = +1.41e-4）
- **K1151** — EAV surprise magnitude: binary sufficient
- **K1152** — θ_rel cross-market analysis: quarterly-density hypothesis (later rejected by K1153)
- **K1153** — EU N=18 PASS; quarterly-density REJECTED; **analyst × media hypothesis proposed** (tested here)
- **K1164 (this experiment)** — **analyst × media hypothesis REJECTED**; mechanism remains open
- **K1165 (planned)** — N≥8 market extension to restore Spearman df
- **K1166 (planned)** — per-stock θ_EAV_i refit to remove σ² tautology
