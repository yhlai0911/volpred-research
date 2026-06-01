# K1167 — Retail-vs-institutional ownership mechanism for cross-market θ_rel cluster

> **TL;DR**: K1166 confirmed analyst coverage drives θ_EAV_i **within markets**
> (panel β=+9.68e-4, t=+3.56). But analyst coverage alone cannot explain the
> 4-market **cross-market** cluster split (EU has more analysts than JP yet sits
> in LOW θ_rel cluster). K1167 tests the alternative hypothesis that
> **institutional ownership %** (yfinance `major_holders`) drives the cross-market
> pattern. **Verdict: PARTIAL — institutional ownership is the superior
> cross-market ranking variable; analyst coverage is the superior within-market
> driver. The two signals operate at different levels.**
>
> - **Cross-market (N=4)**: institutions_pct ranking `TW(0.247) < EU(0.416) < JP(0.425) < US(0.750)` **matches** θ_rel cluster split; Spearman ρ=+0.80 (p=0.20; limited by N=4). Analyst-median ranking `TW<JP<EU<US` does **not** match (ρ=+0.40).
> - **Within-market (N=109, demeaned)**: log_analyst × θ_EAV r=+0.265 (p=0.005); institutions_pct × θ_EAV r=-0.057 (p=0.56). Analyst dominates.
> - **Joint panel (market FE + log_mcap, N=109)**: log_analyst β=+1.14e-3, t=+2.71; institutions_pct β=-2.73e-3, t=-0.93 (not sig). **Analyst remains the primary per-stock driver; institutions_pct does not subsume it.**
> - **Regressor collinearity**: pooled Pearson r(log_analyst, institutions_pct)=+0.667 (N=110; see errata at end of file). The two variables carry overlapping between-market information but distinct within-market information.
> - **Mechanism verdict (preliminary, N=4 markets)**: two-level story — institutional% captures the between-market (cross-country) vol-response concentration; analyst coverage captures the within-market (per-stock) vol-response sensitivity. Neither alone is sufficient.

[提出: Claude (承接 K1166 next_tasks K1167), 執行: Claude]

**Random seed**: 42
**N stocks**: 110 (TW 31 + US 30 + JP 30 + EU 19) — all 110 fetched institutions_pct successfully via yfinance `major_holders`.
**N markets**: 4 — **preliminary only; recommend K1168/K1165 extension to N≥8 markets**

---

## 1. 動機（Why）

K1166 confirmed the K1153 hypothesis at the within-market level: high-analyst
stocks have higher θ_EAV_i (cleaner earnings-announcement vol kick), with a
panel β=+9.68e-4 (t=+3.56). But the **cross-market** cluster split in
market-level θ_rel remained unexplained:

| Cluster | Markets | θ_rel | Analyst-median (K1164) |
|---------|---------|-------|------------------------|
| **LOW** | EU, TW | 0.14, 0.17 | 21.0, 7.5 |
| **HIGH** | JP, US | 0.39, 0.59 | 14.5, 32.5 |

Analyst ranking is `TW < JP < EU < US`: EU and JP are inverted relative to the
cluster split. So analyst coverage cannot be the cross-market mechanism.

**K1167 hypothesis**: *institutional ownership* (retail-vs-institutional
composition) drives the cross-country pattern. Higher institutional share →
more algorithmic / IV-arb / scheduled-hedging activity around earnings →
concentrated vol response on the announcement day → higher θ_EAV scaled by σ².
Retail-heavy markets (TW, EU-retail-pockets) disperse the reaction across days
and dilute θ_rel.

**A-priori ranking expectation**: US (≈80% institutional per 13F) > JP
(≈50-60%) > EU (≈40-50%, more retail in DAX/CAC) > TW (≈30-40%, high retail)
→ order should be TW < EU < JP < US, exactly the cluster split.

---

## 2. 方法（Method）

### 2.1 Data

- **Institutional ownership**: yfinance `Ticker.major_holders` →
  `institutionsPercentHeld`. Current snapshot (no time series). 110/110 stocks
  returned a value. Fetched by `k1167_fetch.py`, stored in
  `data/institutional_ownership.json` with `fetched_at_utc` timestamp.
- **Per-stock θ_EAV_i**: K1166 per-stock panel CSV
  (`experiments/k1166/k1166_per_stock_table.csv`, 110 stocks, 109 converged with
  analyst_count non-missing). Tautology-free estimates — fitted per stock under
  the Engle-Ghysels-Sohn (2013) E[g]=1 normalization.
- **Analyst count**: reused K1166's analyst_count column (from K1164 proxies).
- **Market-level θ_rel**: documented by K1152 (TW/US/JP) and K1153 (EU).

### 2.2 Tests

1. **Cross-market Spearman (N=4)**
   $\rho(\text{institutions\_pct}_\text{mkt-mean}, \theta_\text{rel})$
   vs $\rho(\text{analyst\_median}, \theta_\text{rel})$.
2. **Rank-ordering check** — does ranking by institutions% match the documented cluster?
3. **Per-stock cross-mechanism panel** (White HC0 robust SE, market FE):
   - Analyst only: $\theta_{EAV,i} \sim \alpha_m + \beta_1 \log(\text{analyst}) + \beta_2 \log(\text{mcap})$
   - Institutional only: $\theta_{EAV,i} \sim \alpha_m + \beta_1 \text{institutions\_pct} + \beta_2 \log(\text{mcap})$
   - Joint: $\theta_{EAV,i} \sim \alpha_m + \beta_1 \log(\text{analyst}) + \beta_2 \text{institutions\_pct} + \beta_3 \log(\text{mcap})$
4. **Within-market demeaned correlation** — partials out the between-market
   component to isolate the pure per-stock channel.

### 2.3 Lookahead discipline

Institutional ownership is a current snapshot (yfinance does not provide
historical time series for this field). This is treated as a **cross-sectional**
regressor, not time-varying. No lookahead in the sense of forward information
leaking into past θ_EAV_i estimates (θ_EAV_i uses only past returns and VIX).

---

## 3. 結果（Results）

### 3.1 Per-market summary

| Market | N | mean institutions_pct | median institutions_pct | θ_EAV mean | analyst_median (K1164) | documented θ_rel (K1152/K1153) |
|--------|---|------------------------|--------------------------|-------------|------------------------|--------------------------------|
| TW | 31 | **0.2470** | 0.2493 | 3.79e-4 | 7.5 | 0.17 |
| EU | 19 | **0.4158** | 0.4077 | 6.61e-4 | 21.0 | 0.14 |
| JP | 30 | **0.4251** | 0.4340 | 1.02e-3 | 14.5 | 0.39 |
| US | 30 | **0.7497** | 0.7583 | 2.02e-3 | 32.5 | 0.59 |

### 3.2 Cross-market rank ordering (N=4)

- **Ranking by institutions_pct**: `TW(0.247) < EU(0.416) < JP(0.425) < US(0.750)`
- **Ranking by analyst_median (K1164)**: `TW(7.5) < JP(14.5) < EU(21) < US(32.5)`
- **Ranking by θ_rel (K1152/K1153)**: `EU(0.14) < TW(0.17) < JP(0.39) < US(0.59)`

The cluster split as reported in K1166 prompt was `TW < EU < JP < US`. The
actual ordering of θ_rel has EU narrowly below TW (0.14 vs 0.17), but **both
are in the LOW cluster**; JP and US are in the HIGH cluster. Institutions_pct
preserves the two-cluster structure; analyst-median does not (it places EU
above JP).

### 3.3 Cross-market Spearman (N=4)

| Variable | ρ vs θ_rel | p |
|----------|------------|---|
| institutions_pct (mkt-mean) | **+0.80** | 0.20 |
| analyst_median | +0.40 | 0.60 |

Both p-values fail significance at N=4 (Spearman ρ=±1 is the only result with
p<0.05 at this sample size). The **relative** ordering of the two
mechanisms' explanatory power is the interpretable signal: institutions% is
closer to 1.0 than analyst is.

**Preamble Rule #5 self-check**: ρ=0.80 from N=4 does not trigger the 0.95
cherry-pick warning. The single rank inversion (TW vs EU, institutions_pct
has TW<EU but θ_rel has EU<TW) is small in magnitude and consistent with
measurement noise in a cross-market snapshot of retail mix.

### 3.4 Per-stock cross-mechanism panel (N=109, market FE + log_mcap)

| Specification | log_analyst β (t) | institutions_pct β (t) | R² |
|---------------|--------------------|--------------------------|------|
| Analyst only | **+8.70e-4 (+3.36)** | — | 0.201 |
| Institutional only | — | -1.01e-3 (-0.40) | 0.128 |
| **Joint** | **+1.14e-3 (+2.71)** | -2.73e-3 (-0.93) | 0.210 |

Harvey (2016) t > 3.0 threshold: analyst-only specification **passes**;
institutional-only **fails**; joint drops analyst to t=+2.71 (below the
conservative threshold but still p<0.01). Institutions_pct is never
significant, and its sign even flips in the joint specification.

### 3.5 Within-market demeaned correlation

Partialling out market fixed effects (demean each variable within market) and
correlating residuals:

| Pair | Pearson r | p | N |
|------|-----------|---|----|
| log_analyst × θ_EAV_i | **+0.265** | 0.005 | 109 |
| institutions_pct × θ_EAV_i | -0.057 | 0.56 | 109 |
| log_analyst × institutions_pct | +0.362 | 0.0001 | 109 |

The pooled raw correlation between log_analyst and institutions_pct is +0.667
(N=110; see errata at end of file; collinear because US stocks are both
high-analyst and high-institutional simultaneously); within-market it drops
to +0.362. The crucial finding is that
**only log_analyst carries within-market signal to θ_EAV_i; institutions_pct
has zero within-market signal once the market mean is removed**.

### 3.6 Per-stock within-market Spearman

| Market | ρ(institutions_pct, θ_EAV) | ρ(log_analyst, θ_EAV) |
|--------|----------------------------|------------------------|
| EU (N=18) | +0.243 (p=0.33) | +0.254 (p=0.31) |
| JP (N=30) | +0.323 (p=0.08) | +0.193 (p=0.31) |
| TW (N=31) | -0.091 (p=0.63) | +0.123 (p=0.51) |
| US (N=30) | -0.012 (p=0.95) | **+0.575 (p=0.001)** |

Confirms the within-market story: analyst explains θ_EAV_i strongly in US
(US is the only market with a very significant per-stock signal; the other
three are underpowered at 18-31 stocks each); institutions_pct provides no
clear within-market signal in any of the 4 markets.

---

## 4. Interpretation — two-level mechanism

The data support a **two-level decomposition** of the θ_rel cluster split:

1. **Between-market level (cross-country)**: the 4-market cluster split
   TW/EU (LOW) vs JP/US (HIGH) aligns with **institutional ownership share**
   (Spearman ρ=+0.80, matches cluster ranking). Retail-heavy markets disperse
   announcement-day vol across days via noise trading, dampening θ_rel.
   Institutionally owned markets concentrate vol through algorithmic /
   IV-arbitrage / scheduled-hedging flows on the announcement day, lifting θ_rel.

2. **Within-market level (per-stock)**: among stocks in the same market,
   θ_EAV_i is driven by **analyst coverage density** (K1166 panel β=+9.68e-4,
   t=+3.56; K1167 joint panel retains t=+2.71). More analysts → more
   information-laden reports, faster price discovery on announcement, sharper
   day-0 vol kick. Institutional % varies within markets but does not
   correlate with per-stock θ_EAV after demeaning.

Neither signal alone is sufficient. K1164 correctly **rejected** analyst
coverage as the cross-market mechanism; K1167 identifies institutional
ownership as the better cross-market ranking variable, but does not displace
analyst coverage at the per-stock level.

### 4.1 Pearl-style DAG
```
market-level retail mix (institutions_pct_mkt-mean)
       │
       │  (between-market channel)
       ▼
market-level θ_rel cluster (LOW vs HIGH)

within-market analyst coverage (log_analyst_i)
       │
       │  (within-market channel)
       ▼
per-stock θ_EAV_i
```
The two channels are correlated in the pooled sample (both scale with market
maturity / economic development) but are statistically separable after
demeaning.

### 4.2 Why the EU-vs-JP inversion works

- **Analyst coverage**: EU > JP (EU large caps have more international analyst
  attention per stock; Tokyo-listed majors have fewer English-language analyst
  reports per name). Prediction: EU θ_rel > JP θ_rel. **Wrong** — θ_rel shows
  JP ≫ EU.
- **Institutional share**: EU ≈ JP (41.6% vs 42.5%), both sit between TW
  (retail) and US (institutional-dominant). **Their θ_rel, however, differs
  sharply (0.14 vs 0.39).** This is a residual the institutional-share
  mechanism also cannot fully explain. The residual is likely driven by
  **market microstructure / press-concentration** (Nikkei-centric Japanese
  press vs fragmented European national press), consistent with K1153's
  original qualitative hypothesis. With N=4 markets the mechanism test cannot
  discriminate between "institutions% near-saturates the cluster ranking" and
  "microstructure is the real driver and institutions% is a proxy".

---

## 5. Mechanism verdict

**PARTIAL / two-level (preliminary, N=4 markets)**

- Cross-market ranking by institutions_pct matches the observed θ_rel cluster
  split (`TW < EU < JP < US`), where analyst-median does not (`TW < JP < EU < US`).
- Per-stock panel (FE + log_mcap) confirms analyst remains the dominant
  within-market driver; institutions_pct is not significant and does not
  subsume analyst.
- The two mechanisms operate at different levels and are complementary, not
  substitutive.
- **Not yet CONFIRMED** at the K1166 "panel t>3" threshold because the
  cross-market N=4 is too small for Spearman significance (minimum p at N=4 is
  0.083 for ρ=1). Narrative support is strong but statistical support is
  preliminary.

---

## 6. Limitations

1. **N=4 markets**: any 4-point Spearman with ρ=0.80 has p=0.20. A single
   market flip would change ρ to 0.40. Conclusion awaits **K1168 / K1165**
   extension to N≥8 markets (HK, SG, KR, AU, CA, BR etc.).
2. **Institutional ownership snapshot only**: yfinance returns current (as of
   fetch date) institutions_pct. Does not capture historical evolution or
   the specific earnings-season period used in θ_EAV_i estimation. The
   assumption is that institutional ownership is slow-moving relative to the
   10+ year sample window of K1145/K1147/K1150/K1153 / K1166.
3. **Institutional share mixes passive (index) and active (stock-picker)
   holders**. Mechanism assumes "institutional = algorithmic/IV-arb", but a
   high Vanguard-index-fund ownership is **not** algorithmic. A finer
   decomposition (active vs passive institutional) is needed.
4. **Collinearity log_analyst vs institutions_pct**: pooled Pearson +0.667
   (corrected, was +0.707 — see errata). US has both highest analysts and
   highest institutions%; TW has both lowest. Separating between-market
   effects requires more markets.
5. **EU-vs-JP gap (0.14 vs 0.39) not fully explained** by institutions_pct
   alone (nearly equal institutions_pct 0.416 vs 0.425). The residual is
   consistent with K1153's press-concentration hypothesis but not tested here.
6. **No formal test that institutions_pct subsumes analyst**. Joint panel
   shows analyst β and t barely change from the analyst-only specification
   (t drops from +3.36 to +2.71, still p<0.01). Institutions_pct is
   statistically non-informative at the per-stock level.

---

## 7. Next tasks

- **K1168**: 擴到 N≥8 markets (HK, SG, KR, AU, CA, BR) to move cross-market
  Spearman out of the p-limited-by-N zone. Target: institutions_pct × θ_rel
  Spearman N≥8, p<0.05.
- **K1169**: 分解 institutional into **active vs passive** (13F HR filings for
  US; TSE index-fund share for JP; JPX ownership tables). Passive institutions
  should not drive IV-arb / algorithmic vol concentration; active institutions
  should.
- **K1170**: press-concentration proxy (Nikkei coverage share for JP; Financial
  Times / national press fragmentation for EU). Test whether this explains
  the residual JP-vs-EU θ_rel gap not captured by institutions_pct.

---

## 8. Paper 2 §5 narrative suggestion

Paper 2 §5 (mechanism section) should distinguish **two channels**:

- **Between-market (cross-country) channel**: retail-vs-institutional mix
  explains the 2-cluster split in θ_rel. Narrative: "markets with higher
  institutional participation concentrate earnings-announcement vol via
  scheduled hedging and option-market arbitrage, inflating θ_rel; retail-heavy
  markets disperse the reaction across days."
- **Within-market (per-stock) channel**: analyst coverage explains cross-stock
  variation in θ_EAV_i. Narrative: "more analyst reports on a stock implies
  more structured information release on announcement days, producing a
  sharper day-0 vol kick."

Do NOT claim institutional ownership subsumes analyst coverage; the joint
panel is explicit that it does not. Report both coefficients.
Clearly flag N=4 markets as preliminary and commit to the K1168 extension
before any strong causal claim.

---

## 9. 檔案

- `k1167_fetch.py` — yfinance `major_holders` fetch (110 tickers)
- `k1167.py` — main analysis: Spearman, rank check, panel OLS, figures
- `k1167_results.json` — complete results including per-market summary,
  cross-market Spearman, within-market Spearman, three panel specifications,
  verdict notes
- `k1167_cross_market_scatter.png` — institutions_pct vs θ_rel and
  analyst_median vs θ_rel, side-by-side (N=4 markets)
- `k1167_panel_forest.png` — t-statistics for the 4 panel specifications
- `data/institutional_ownership.json` — yfinance snapshot (110 records)
- `data/k1166_per_stock_table.csv` — copy of K1166 per-stock panel (source)
- `run_fetch.log`, `run.log` — execution logs

---

## Errata (2026-06-02, via mile_95f49685 Codex 24h-rule review)

- **Pooled Pearson r(log_analyst, institutions_pct)**: originally stated `+0.707`
  in 4 places (TL;DR L15, Section 3.5 narrative L155, Limitations point 4 L268,
  and minor cross-refs). Re-computed from raw source data:
  `k1166_per_stock_table.csv (converged subset)` merged on
  `data/institutional_ownership.json (institutionsPercentHeld)`, log-transformed
  via `log(analyst_count + 1)` → actual Pearson = **+0.6669** (N=110).
  Updated all four occurrences to `+0.667`.
- Reproduce: `uv run python -c "import json,pandas as pd,numpy as np; \
  k=pd.read_csv('experiments/k1166/k1166_per_stock_table.csv'); \
  k=k[k['converged'].astype(bool)]; p=json.load(open('experiments/k1167/data/institutional_ownership.json')); \
  r=pd.DataFrame([{'ticker':x['ticker'],'institutions_pct':(x.get('major_holders') or {}).get('institutionsPercentHeld')} for x in p['records']]); \
  m=k.merge(r,on='ticker'); m['la']=np.log(m['analyst_count'].fillna(0)+1); \
  g=m.dropna(subset=['la','institutions_pct']); print(g['la'].corr(g['institutions_pct']),len(g))"`
- Published article `mile_95f49685` 「台股財報日波動率只有美股的 30%？...」 did
  **not** quote this number, so no feed errata needed; this is a README-only
  data integrity fix to prevent future article-writers from copying the wrong
  value.
- Triggered by: paper_review_mile_95f49685 (Codex 24h-rule primary path),
  2026-06-02 hourly-07 dispatch.
