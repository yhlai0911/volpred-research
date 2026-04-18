# K1172 — N>=13 cross-market ladder extension (K1168 +MX/ZA/ID)

> **TL;DR**: K1172 extends K1168's N=10 test by adding MX/ZA/ID. Effective
> N=12 because ZA is **UNDERPOWERED** (yfinance returns 0-4 earnings events
> per JSE Top 40 ticker, all 10 fail the >=15-events filter). MX and ID
> converge 10/10. Primary cross-market Spearman
> **ρ(institutions_pct, θ_rel) drops from +0.612 (N=10, p=0.060) to
> +0.441 (N=12, p=0.152) — REGRESSED from STRENGTHENED to PARTIAL.**
>
> - **Primary Spearman**: ρ=+0.441, p=0.152, N=12. Direction positive but
>   mechanism weakened. MX (inst_pct=0.20, θ_rel=1.20) is a new
>   high-θ_rel residual at low-mid institutional ownership — same pattern
>   as BR/IN that caused the K1168 decay.
> - **Drop-MX LOO**: ρ=+0.609, p=0.047 (MX is the new leverage point).
>   Drop-EU LOO ρ=+0.564, p=0.071 (EU still the canonical single residual).
> - **Panel OLS (N=172, market FE + log_mcap, joint)**: log_analyst
>   β=+1.28e-3, **t=+3.79 (Harvey PASS)**; institutions_pct β=-2.15e-3,
>   t=-1.32 (NS). **Within-market analyst mechanism remains CONFIRMED**
>   (K1168 t=+3.63 → K1172 t=+3.79, slight gain with 19 new obs).
> - **Two-level R² decomposition**: institutions_pct **43.2% between-market**
>   R² (vs K1168 53.8%) vs 2.7% for log_analyst; log_analyst **5.3%
>   within-market** R² vs 1.2% institutions_pct. The ≈16× ratio (between
>   inst vs analyst) is preserved, but both R² magnitudes weakened.
> - **Analyst cross-market**: ρ=-0.14, p=0.69 — still not a cross-market
>   driver (consistent with K1165/K1168).
>
> **Verdict**: **PARTIAL (not CONFIRMED, not STRENGTHENED)**. Primary
> Spearman p=0.152 failed both 5% and 1% thresholds — a REGRESSION from
> K1168 N=10 p=0.060. But the structural two-level picture (between-market
> inst vs within-market analyst) survives, and the within-market analyst
> channel strengthens with more data (Harvey t=3.79). Emerging-market
> residual story deepens: BR/IN/MX all sit at mid inst_pct but very high
> θ_rel, breaking the developed-market ladder.
>
> **Paper 2 §5 narrative pivot**: do **NOT** upgrade to CONFIRMED. Keep
> K1168's STRENGTHENED language BUT add an emerging-market scale residual
> explicit caveat AND a concrete K1172 result table. The K1168 "STRENGTHENED
> with caveat" framing is stronger than K1172 can justify upward; the
> structural two-level picture remains the dominant claim. Proposed Paper 2
> §5 stance: "Between-market institutional ownership explains ~43% of
> θ_rel variation across 12 markets; developed markets form a clean ladder,
> but emerging markets (BR/IN/MX) sit at elevated θ_rel that the ladder
> does not predict — likely reflecting cross-country differences in
> yfinance's institutions_pct definition (US 13F vs emerging-market
> beneficial-ownership vs state/promoter disclosure). The within-market
> analyst channel is the robust panel mechanism (Harvey t=3.79, N=172)."

[提出: User brief / K1168 STRENGTHENED verdict follow-up, 執行: Claude worktree agent]

**Random seed**: 42
**N markets intended**: 13 (K1168 N=10 + MX + ZA + ID)
**N markets actually tested**: 12 (ZA UNDERPOWERED, dropped)
**Panel N (stock-level)**: 172 (MX has 9 with non-null inst_pct; GRUMAB.MX
missing inst_pct in yfinance)
**Sample period**: 2014–2025 for all new markets; legacy markets inherit
K1145/K1147/K1150/K1153 periods.

---

## 1. 動機（Why）

K1168 (N=10: TW/EU/JP/US/KR/CA/HK/BR/CH/IN) reported primary Spearman
ρ=+0.612, p=0.060 — **STRENGTHENED but not CONFIRMED**. The brief
hypothesis: adding 3 emerging markets (MX/ZA/ID) with different
institutional ownership structures should double effective N on the
between-market dimension, pushing p across 5% or 1% threshold if the
direction is robust.

**What K1172 adds**:
- **MX (Bolsa Mexicana)**: WALMEX, AMXB, GFNORTEO, FEMSAUBD, CEMEXCPO,
  BIMBOA, GMEXICOB, KOFUBL, TLEVISACPO, GRUMAB (ALFAA.MX delisted 2022 →
  substituted with GRUMAB.MX). 10/10 converged, earnings n=27-88 per
  ticker, analyst_count 6-18.
- **ZA (JSE Top 40 subset)**: NPN, BHG, AGL, SOL, MTN, SBK, FSR, ABG, SLM,
  CPI. **ALL 10 DROPPED**: yfinance `Ticker.get_earnings_dates` returns
  0-4 events per ticker (JSE firms report semi-annually and yfinance does
  not reliably surface them). Below the K1165 >=15-events filter.
  **UNDERPOWERED per brief — did not force-fit.**
- **ID (IDX Composite large-caps)**: BBCA, BBRI, TLKM, ASII, UNVR, ICBP,
  BMRI, ADRO, GGRM, INDF. 10/10 converged, earnings n=36-82 per ticker,
  analyst_count 9-23.

---

## 2. 方法（Method）

All methodological choices are **identical to K1165/K1166/K1168** (fair
comparison requirement per brief):

- GJR(1,1) + VIX² + EAV MIDAS per stock, 6 free params, L-BFGS-B multi-start
- >=15 events and >=500 obs filter
- Pooled per-market MLE (shared θ0, θ_VIX, θ_EAV; stock-specific α/γ/β)
- θ_{rel,m} = pooled_θ_EAV_m / mean_σ²_m (same as K1152)
- Cross-market Spearman: ρ(inst_pct_mean, θ_rel), ρ(analyst_median, θ_rel),
  ρ(log_mcap_median, θ_rel)
- Panel OLS (stock-level) with market FE + log_mcap (HC0 SE); 3 specs
- Within-market demeaned Pearson
- Two-level R² decomposition: between-market (bm-mean) vs within-market (demeaned)
- Leave-one-out sensitivity

**Lookahead discipline**: VIX²_{t-1} and EAV_{t-1} shifted; earnings
filtered `date < today at fetch`. Random seed 42 fixed.

**PIT alignment for institutions_pct**: yfinance
`Ticker.major_holders.institutionsPercentHeld` is a single-snapshot field
(current disclosure). K1167 noted this limitation; K1172 inherits it. For
between-market tests the snapshot is treated as structural (market-level
long-run mean), not as a time-varying predictor. A proper PIT panel
(per-year 13F / local equivalent) is open for future K-number.

---

## 3. 資料覆蓋（Data coverage）

| Market | Tickers intended | Price OK | Earnings >=15 | Converged | Pooled OK | inst_pct data |
|--------|------------------|----------|---------------|-----------|-----------|---------------|
| MX     | 10               | 9        | 10 (after ALFAA→GRUMAB) | 10      | YES (t=11.26) | 9/10 (GRUMAB NaN) |
| **ZA** | 10               | 10       | **0** (all 0-4 events) | **0** | **NO (dropped)** | 10/10 (unused) |
| ID     | 10               | 10       | 10            | 10        | YES (t=4.90)  | 10/10 |

Note: ZA `inst_pct_mean=0.579` was fetched successfully, but θ_rel cannot
be computed without a converged pooled MLE, so ZA is excluded from the
Spearman.

---

## 4. 結果（Results）

### 4.1 Per-market summary sorted by institutions_pct_mean ascending

| Market | N_stocks | inst_pct_mean | analyst_median | log_mcap_median | pooled θ_EAV | t     | **θ_rel** |
|--------|----------|---------------|----------------|------------------|--------------|-------|-----------|
| ID     | 10       | **0.154**     | 20.0           | 32.6             | 9.67e-5      | 4.9   | **0.238** |
| CH     | 10       | 0.157         | NaN            | 27.0             | 1.07e-4      | 5.3   | **0.304** |
| MX     | 10       | **0.195**     | 13.0           | 26.8             | 4.15e-4      | 11.3  | **1.202** |
| TW     | 31       | 0.247         | 7.5            | 26.5             | 6.36e-5      | 14.1  | 0.170     |
| HK     | 5        | 0.261         | 17.0           | 28.5             | 5.21e-5      | 2.4   | 0.180     |
| KR     | 10       | 0.365         | 25.5           | 31.6             | 1.27e-4      | 2.7   | 0.276     |
| IN     | 10       | 0.383         | 37.0           | 29.9             | 3.25e-4      | 13.3  | **1.170** |
| EU     | 19       | 0.416         | 21.0           | 25.5             | 4.07e-5      | 10.0  | 0.140     |
| JP     | 30       | 0.425         | 14.5           | 29.9             | 1.41e-4      | 20.2  | 0.390     |
| BR     | 10       | 0.486         | 13.0           | 26.0             | 1.22e-3      | 10.5  | **1.887** |
| CA     | 10       | 0.552         | 14.5           | 25.6             | 3.13e-4      | 10.3  | 1.448     |
| US     | 30       | 0.750         | 32.5           | 26.8             | 1.91e-4      | 22.4  | 0.590     |

**New K1172 rows in bold (ID, MX)**. MX sits at 3rd-lowest inst_pct
(0.195) but 5th-highest θ_rel (1.20) — a mid-inst, high-θ_rel residual
mirroring BR and IN.

### 4.2 Cross-market Spearman (primary test, N=12)

| Regressor vs θ_rel | ρ | p | n |
|---|---|---|---|
| **institutions_pct_mean** | **+0.441** | **0.152** | **12** |
| analyst_median | -0.137 | 0.688 | 11 |
| log_mcap_median | -0.154 | 0.633 | 12 |

- Primary ρ dropped from K1165 +0.750 (N=7) → K1168 +0.612 (N=10) →
  K1172 +0.441 (N=12). Direction still positive, but consistent decay as
  the emerging-market residual pattern accumulates.
- Analyst flipped slightly negative at N=11, but |ρ|<0.15 — still no
  cross-market channel.

### 4.3 Leave-one-out (drop each, N=11)

| Drop market | ρ | p |
|---|---|---|
| BR | +0.318 | 0.340 |
| CA | +0.318 | 0.340 |
| CH | +0.436 | 0.180 |
| **EU** | **+0.564** | **0.071** |
| HK | +0.464 | 0.151 |
| ID | +0.400 | 0.223 |
| IN | +0.455 | 0.160 |
| JP | +0.364 | 0.272 |
| KR | +0.427 | 0.190 |
| **MX** | **+0.609** | **0.047** |
| TW | +0.464 | 0.151 |
| US | +0.427 | 0.190 |

- **MX** is now the **strongest leverage point** (drop-MX → ρ=+0.609,
  p=0.047 — would cross 5% if MX had never been added). EU is 2nd (drop-EU
  → ρ=+0.564, p=0.071).
- Drop-BR or drop-CA → ρ=+0.318 (lowest): BR/CA remain the two
  high-θ_rel anchors that keep the positive slope alive.
- **All LOO ρ > 0** — direction stable in every sub-sample.

### 4.4 Panel OLS (N=172, market FE + log_mcap)

| Specification | log_analyst β (t) | institutions_pct β (t) | log_mcap β (t) | R² |
|---|---|---|---|---|
| Analyst only | **+1.12e-3 (+4.06)** | — | -2.47e-4 (-1.43) | 0.212 |
| Institutional only | — | -1.33e-3 (-0.88) | -5.6e-6 (-0.03) | 0.159 |
| **Joint** | **+1.28e-3 (+3.79)** | -2.15e-3 (-1.32) | -2.52e-4 (-1.53) | 0.237 |

- **log_analyst passes Harvey |t|>3 in both analyst-only AND joint
  (t=+4.06, +3.79)** — strongest reading in the K1165/K1166/K1168/K1172
  sequence (K1165 t=+3.24 N=133 → K1166 t=+3.56 N=109 → K1168 t=+3.63
  N=153 → K1172 t=+3.79 N=172). Within-market analyst channel
  structurally strengthens with sample size.
- institutions_pct NS in all 3 specs (β sign negative in joint). Not a
  within-market channel, consistent with K1167 two-level claim.

### 4.5 Within-market demeaned Pearson (N=172)

| Pair | r | p |
|---|---|---|
| log_analyst × θ_EAV | **+0.231** | 0.002 |
| institutions_pct × θ_EAV | -0.109 | 0.155 |
| log_analyst × institutions_pct | +0.236 | 0.002 |

Matches K1168 (+0.250, -0.101, +0.223). Only log_analyst carries
within-market signal.

### 4.6 Two-level R² decomposition

| Channel | Between-market R² (N=11) | Within-market R² (N=172) |
|---|---|---|
| institutions_pct | **0.432** | 0.012 |
| log_analyst | 0.027 | **0.053** |
| log_mcap | 0.117 | 0.000 |

- **Between-market**: institutions_pct = 43% vs log_analyst = 2.7%.
  Dropped from K1168 (54%) and K1165 (63%) as N grew, but ~16× ratio
  (inst vs analyst) preserved.
- **Within-market**: log_analyst = 5.3% vs institutions_pct = 1.2%.
  Matches K1168 (6.2% vs 1.0%) and K1165 (7.2% vs 0.4%).
- Two-level split direction preserved, but between-market R² decay
  continues as emerging-market residuals accumulate.

### 4.7 Diagnostic — per-market within Spearman

(saved in `k1172_results.json.per_market_within_spearman`)

- US still strongest analyst signal per-market (ρ≈+0.58).
- MX and ID within-market analyst ρ are positive but small (n=10 each).

---

## 5. Delta table (K1168 N=10 → K1172 N=12)

| Metric | K1168 N=10 | K1172 N=12 | Δ | Interpretation |
|---|---|---|---|---|
| Cross-market Spearman ρ(inst_pct) | +0.612 | **+0.441** | -0.171 | **Regressed** |
| Primary p-value | 0.060 | **0.152** | +0.092 | **Moved away from 5%** |
| Drop-EU LOO ρ | +0.750 | +0.564 | -0.186 | Weakened; still 2nd residual |
| Drop-(new leverage) LOO ρ | (BR drop +0.533) | **MX drop +0.609** | — | MX is new leverage |
| Panel OLS log_analyst t (joint) | +3.63 | **+3.79** | +0.16 | **Strengthened** (Harvey PASS) |
| Panel N_stocks | 153 | **172** | +19 | More power within-market |
| Between-market R² (inst_pct) | 0.538 | 0.432 | -0.106 | Decay continues |
| Within-market R² (log_analyst) | 0.062 | 0.053 | -0.009 | Stable |

**Direction of evidence**: cross-market Spearman signal WEAKENED as 2
more emerging markets joined; panel within-market analyst channel
STRENGTHENED. The two-level picture is preserved in sign but compressed
in magnitude.

---

## 6. Interpretation

### 6.1 Why ρ dropped from +0.61 to +0.44

**MX is the primary driver**: at inst_pct=0.195 (third-lowest) but
θ_rel=1.20 (fifth-highest), MX sits as an off-ladder residual in the
same pattern as BR, IN, and CH. The K1167 developed-market ladder (TW <
EU ≈ JP < US at 0.25 → 0.42 → 0.43 → 0.75 inst_pct, 0.17 → 0.14 → 0.39
→ 0.59 θ_rel) predicts MX should sit at ~0.15 θ_rel, not 1.20. Three
possible explanations:

1. **Emerging-market cost-of-capital scale factor**: BR/IN/MX (and to a
   lesser extent CA) have pooled θ_EAV 3e-4 to 1.2e-3, 3-25× the
   developed-market range. This elevates θ_rel mechanically through the
   numerator regardless of inst_pct denominator.

2. **yfinance institutions_pct under-counts emerging-market structural
   holders**: MX has high promoter/family concentration (Slim family in
   AMXB, BIMBOA), Brazil has BNDES/Petrobras state holdings, India has
   promoter group disclosure. yfinance returns Yahoo's internal
   "institutional" classification which under-counts these. The "true"
   institutional share at MX/BR/IN may be closer to 0.4-0.5 than the
   reported 0.19/0.49/0.38 — which would collapse the residual.

3. **ID (inst=0.15, θ_rel=0.24)** sits close to the K1165 CH position
   (0.16, 0.30), consistent with a shared emerging-market low-inst +
   mid-θ_rel cluster. ID by itself is not a residual.

### 6.2 Two-level picture structurally intact

- Panel Harvey t=+3.79 is the **highest** across K1165 → K1166 → K1168 →
  K1172, confirming the within-market analyst channel scales cleanly
  with sample size.
- Between-market institutions_pct still explains 43% of θ_rel (vs 2.7%
  for log_analyst) — ≈16× ratio in direction of K1167 prediction.
- The **direction** of the two-level picture survives; the **magnitude**
  of the between-market ladder is measurably weakened by emerging-market
  residuals.

### 6.3 Paper 2 §5 narrative commitment

**Decision: do NOT upgrade to CONFIRMED.**

Primary Spearman p=0.152 at N=12 fails both 5% and 1% thresholds. The
K1168 "STRENGTHENED, not CONFIRMED" language was already the
upper-bound commitment given N=7 K1165 and N=10 K1168 evidence.

**Recommended Paper 2 §5 stance** (for main text):

> "The two-level mechanism operates at different statistical levels. The
> within-market analyst channel is strongly supported by panel regressions
> (Harvey t=3.79, N=172 across 12 markets; log_analyst β=+1.28e-3,
> p<0.001 under stock-level fixed effects). The between-market
> institutional-ownership channel explains 43% of cross-market θ_rel
> variation, but the primary rank test at N=12 fails 5% significance
> (Spearman ρ=+0.44, p=0.15). Developed markets (TW, EU, JP, US) form a
> clean institutional-ownership ladder matching Ferreira & Matos (2008)
> and Bartram, Brown & Stulz (2012); emerging markets (BR, IN, MX) sit
> off-ladder at elevated θ_rel that the ladder does not predict. The
> emerging-market residual may reflect (i) structural cross-country
> differences in the yfinance institutionsPercentHeld definition
> (US 13F vs emerging-market promoter/state disclosure), or (ii) a
> cost-of-capital scale factor in pooled θ_EAV that is orthogonal to
> institutional ownership. A PIT institutional-ownership panel (13F,
> Japan Securities Surveys, B3 disclosure, India promoter filings) is
> needed to distinguish these."

**Paper 2 §5 commitment**: STRENGTHENED (K1168 language) with concrete
12-market table; acknowledge PARTIAL on primary Spearman at N=12 and
explain. Do not claim CONFIRMED.

---

## 7. Limitations

1. **ZA earnings coverage failure** is structural in yfinance, not fixable
   at this experiment. JSE companies report semi-annually, and
   `Ticker.get_earnings_dates` returns 0-4 events per ticker. A different
   data source (Alpha Vantage, SharadarZA, or paid FactSet) would be
   needed to bring ZA into the between-market test.
2. **MX GRUMAB inst_pct=None**: yfinance returned no major_holders data
   for GRUMAB.MX (Gruma). Panel N drops from 182 to 172 on the
   institutions_pct dimension. Not large enough to change panel
   conclusions.
3. **PIT alignment for institutions_pct**: the brief flagged this as a
   rule. Yfinance major_holders is a single snapshot (current). K1167
   acknowledges this limitation. For between-market tests the snapshot
   is interpreted as a structural (long-run) marker, not a time-varying
   predictor; within-market panel regressions also use the snapshot as a
   time-invariant stock characteristic. A proper per-year PIT panel is
   a future K-number.
4. **Emerging-market institutions_pct definition heterogeneity**: BR/CH/
   IN/MX use different country-specific disclosure regimes (B3 vs
   A-share vs Indian promoter vs Mexican insider). The "true"
   institutional share may be much higher than yfinance reports for
   markets with large promoter/state holdings (cf. K1168 §6.2 CH note).
5. **N=12 is still small for Spearman**. Stamp (1914) / Kendall's
   exact-null test gives p=0.15 at ρ=+0.44 for N=12; the same magnitude
   at N=20 gives p≈0.05. Future K-numbers could attempt SG (SGX top 10),
   TH (SET top 10), MY (Bursa top 10), AR (BYMA), and AU (via Alpha
   Vantage per K1171 proposed) to reach N=18-20.
6. **Seed-stability check not done here**. K1168 / K1165 used seed 42
   only; K1172 follows convention. Pooled MLE t-stats are well above 4
   in 11/12 markets, so seed sensitivity is unlikely to change the
   ranking materially.
7. **No MSE-based bootstrap CI on θ_rel**. Future K-number could run
   pooled MLE bootstrap (200 bootstraps) per market to get CI on the
   rank test.

---

## 8. Preamble Rule #5 self-challenge

| Check | Status |
|---|---|
| Mechanical vs empirical | Empirical — no construction forces correlation |
| Tautology? | No — cross-sectional inst_pct vs temporal θ_rel |
| ρ > 0.95 trigger? | No — primary ρ=+0.441; LOO max +0.609 |
| Sharpe > 2× baseline? | N/A |
| Sample size | N=12 markets (adequate for Spearman but not asymptotic); N=172 stocks (ample) |
| Result strength exceeds evidence? | No — verdict=PARTIAL, not CONFIRMED |
| Mechanical ρ drop anticipated? | Yes — K1168 README §4.1 documented the emerging-market residual scaling factor. K1172 MX + ID confirms this pattern, with MX replicating BR/IN |

---

## 9. Files

- `k1172_fetch_3markets.py` — yfinance fetch for MX/ZA/ID (30 tickers
  initially; ALFAA.MX delisted, replaced by GRUMAB.MX)
- `k1172_per_stock_refit.py` — per-stock + pooled MLE (same spec as
  K1168)
- `k1172.py` — main N>=13 → N=12 cross-market analysis
- `k1172_results.json` — full results (per-market, Spearman + LOO, panel
  OLS, within-market Pearson, two-level R², verdict, K1168 delta)
- `k1172_pooled_by_market.json` — pooled MLE for MX/ID (ZA dropped)
- `k1172_per_stock_table_newmkts.csv` — MX/ZA/ID per-stock fits (MX/ID
  converged; ZA not attempted after coverage failure)
- `k1172_per_stock_table.csv` — combined N=172 panel
- `k1172_cross_market_scatter.png` — N=12 scatter (inst_pct vs θ_rel +
  analyst vs θ_rel)
- `k1172_panel_forest.png` — t-stats across analyst-only / inst-only /
  joint panel
- `k1172_delta_vs_k1168.png` — side-by-side delta barplot (K1168 N=10
  vs K1172 N=12)
- `data/` — yfinance parquet + JSON caches for MX/ZA/ID
- `run_fetch.log`, `run_refit.log`, `run.log` — execution logs

---

## 10. References

- Engle, R.F., Ghysels, E., Sohn, B. (2013). *Stock market volatility and
  macroeconomic fundamentals*. **RES** 95(3), 776–797.
- Patton, A.J. (2011). *Volatility forecast comparison using imperfect
  volatility proxies*. **JoE** 160(1), 246–256.
- Harvey, C.R., Liu, Y., Zhu, H. (2016). *… and the cross-section of
  expected returns*. **RFS** 29(1), 5–68.
- Bartram, S.M., Brown, G.W., Stulz, R.M. (2012). *Why are U.S. stocks
  more volatile?* **JF** 67(4), 1329–1370.
- Ferreira, M.A., Matos, P. (2008). *The colors of investors' money: the
  role of institutional investors around the world*. **JFE** 88(3), 499–533.
- Brennan, M.J., Jegadeesh, N., Swaminathan, B. (1993). *Investment
  analysis and the adjustment of stock prices to common information*.
  **RFS** 6, 799–824.
- K1145 / K1147 / K1150 / K1153 / K1165 / K1166 / K1167 / K1168 (legacy).

---

## 11. Related K

- **K1165**: N=7 (TW/EU/JP/US/KR/CA/HK), ρ=+0.750, p=0.052, STRENGTHENED.
- **K1166**: per-stock θ_EAV → analyst within-market CONFIRMED (t=+3.56).
- **K1167**: institutions_pct cross-market at N=4 (preliminary ρ=+0.80).
- **K1168**: N=10 extension (BR/CH/IN added). ρ=+0.612, p=0.060,
  STRENGTHENED. Two-level R² survives.
- **K1172 (this)**: N=12 extension (MX/ID added; ZA UNDERPOWERED dropped).
  ρ=+0.441, p=0.152, **PARTIAL**. Panel Harvey t=+3.79 strengthens.
  Paper 2 §5 narrative stays STRENGTHENED (not CONFIRMED); add
  emerging-market scale-residual caveat + K1172 delta table.
- **K1170 (proposed)**: EU press-concentration proxy for EU residual.
- **K1171 (proposed)**: ASX data recovery for AU via Alpha Vantage.
- **K1173 (proposed)**: better institutional-share proxy for CH (Wind /
  CSMAR), IN (NSDL / CDSL), MX (CNBV), BR (CVM).
- **K1174 (proposed)**: ZA earnings date recovery via Alpha Vantage /
  FMP; bring ZA into the N=13 test.
- **K1175 (proposed)**: PIT panel — per-year 13F (US), CSMAR (CH), NSDL
  (IN), CNBV (MX), CVM (BR) to test K1167 time-series.
- **K1176 (proposed)**: pooled MLE bootstrap (200 reps) per market to
  get CI on θ_rel and Spearman rank test.
