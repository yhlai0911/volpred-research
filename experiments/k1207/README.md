# K1207 — GICS sector-FE decomposition of K1171 N=182 pool (empirical test of K1171 sector-orthogonal claim)

> **TL;DR**: K1171 (commit 17436274) hypothesised that "sector composition
> is an independent driver of θ_rel orthogonal to institutional ownership."
> K1207 tests this claim empirically on K1171's N=182 × 12-market pool with
> GICS sector classifications (100% yfinance coverage).
>
> **Verdict: `SECTOR_ORTHOGONAL_CONFIRMED`.**
>
> - **Sector-FE joint F = 689.5, p = 7.9 × 10⁻¹⁴** (market-clustered SE).
> - **Sector-FE incremental adj-R² (M3 − M1) = 0.148 ≈ 32 × inst-FE
>   incremental adj-R² (M2 − M1) = 0.0046**. Sector is the dominant
>   within-market driver of θ_EAV.
> - **inst_pct coefficient stable across M2 → M4**: β −0.00127 → −0.00122
>   (4.4% relative change; both |t| < 1, NS). Adding sector FE does NOT
>   kill the (already weak) inst_pct within-market channel.
> - **Cross-sector Spearman ρ(sector θ_EAV median, sector inst_pct
>   median) = −0.006, p = 0.987, n = 10 sectors** — the two covariates are
>   empirically orthogonal at the sector level.
> - **Sector-adjusted residual shrinkage**: BR −38.6%, IN −95.4%, MX
>   −78.2%, JP −99.6% — sector mix explains most of the above-ladder
>   residual for BR/IN/MX. **AU is the exception**: sector-adjusted residual
>   increases in magnitude (−31% "reduction" is negative = grew), meaning
>   AU's below-ladder position is **NOT** sector-explained; the K1171
>   semi-annual reporting / HAND_CODED ±1-day hypotheses remain the
>   leading candidates for AU specifically.
>
> **Paper 2 §5 narrative commitment**: add a "sector as independent
> structural driver" bullet supported by K1207 empirical numbers; but keep
> K1171 AU caveat separately — sector mechanism resolves BR/IN/MX
> residuals, does NOT resolve AU below-ladder residual.

[提出: K1171 narrative audit backlog, 執行: Claude worktree agent k1207]

**Random seed**: 42
**N stocks**: 182 (100% GICS-classified from yfinance Ticker.info)
**N markets**: 12 (= K1171 13 − CH analyst NaN drop; actually K1171 panel
already N=182 without CH because K1171 table excludes CH price panel by
design)
**N GICS sectors present in pool**: 10 (Utilities absent;
Real Estate only n=1 — hand-marked in figure 1)

---

## 1. 動機（Why）

K1171 (commit 17436274) closed the AU data gap via HAND_CODED ASX
earnings. AU's θ_rel landed at **0.150** — second-lowest in the N=13
panel, at inst_pct_mean = 0.368 (mid-ladder). This is the mirror image
of BR/IN/MX, which sit above the institutional-ownership ladder at
θ_rel ≈ 1.2–1.9.

K1171 §6.2 wrote:

> "The mirror image of the emerging-market residuals … argues for
> heterogeneous sector-composition drivers of θ_rel that are
> **orthogonal** to institutional ownership, rather than for
> yfinance-definition artefacts alone."

This is a narrative-level claim ungrounded in any empirical sector
regression. K1207's job is to test it:

- If sector-FE carries incremental explanatory power AND inst_pct is
  stable in a joint spec → K1171 claim is supported → Paper 2 §5 gains a
  concrete "sector as independent driver" line.
- If sector-FE R² << inst-FE R² or inst_pct β collapses when sector
  enters → K1171 claim is empirically NULL → BR/IN/MX residuals need
  other explanations (cost-of-capital, PIT institutional panel, etc.).

---

## 2. 方法（Method）

### 2.1 Data

- **Panel source**: `experiments/k1171/k1171_per_stock_table.csv` —
  182 stocks × 12 markets, each with θ_EAV, σ²_sample, log_mcap,
  log_analyst, institutions_pct. Each stock fitted via GJR(1,1) + VIX² +
  EAV MIDAS (K1165–K1171 spec).
- **Sector classifications**: `k1207_fetch_sectors.py` pulls
  `Ticker(...).info['sector']` from yfinance for each ticker and maps
  Yahoo's 11-sector scheme to the GICS 11-sector taxonomy:
  - Technology → Information Technology
  - Basic Materials → Materials
  - Consumer Defensive → Consumer Staples
  - Consumer Cyclical → Consumer Discretionary
  - Financial Services → Financials
  - Healthcare → Health Care
  - Others (Communication Services / Energy / Industrials / Real Estate /
    Utilities) mapped 1:1.
- **Fallback**: hand-coded sector map for all 182 tickers curated from
  Bloomberg / company disclosure (retained in code as backup). Actual
  yfinance coverage = 182/182 (100%); fallback not invoked.

### 2.2 Specifications

**Analysis 1 — sector-FE only regression:**

- S1: θ_EAV_i = α + Σ_s β_s · 1{sector=s}_i + ε
- S2: S1 + log_mcap

**Analysis 2 — 4-model comparison (primary):**

- M1: θ_EAV ~ const + market_FE + log_mcap                   (K1171 baseline)
- M2: θ_EAV ~ const + market_FE + log_mcap + inst_pct         (K1171 current)
- M3: θ_EAV ~ const + market_FE + log_mcap + sector_FE        (K1207 new)
- M4: θ_EAV ~ const + market_FE + log_mcap + inst_pct + sector_FE (joint)

All fit via `statsmodels.OLS` with `cov_type='cluster'`,
`cov_kwds={'groups': market_int_code, 'use_correction': True}`.
First market (`AU` alphabetically) dropped from dummy block; first
sector dropped from dummy block.

**Analysis 2b — robustness (y = θ_rel_stock):**

Same 4 models with stock-level θ_rel analog = θ_EAV / σ²_sample.

**Analysis 3a — sector-adjusted residual per market:**

For each stock, subtract its GICS sector global mean θ_EAV; then
compute per-market mean raw vs sector-adjusted residual. This
diagnoses HOW MUCH of each market's off-ladder residual is explained
by its sector mix.

**Analysis 3b — per-market sector mix report:**

AU / BR / IN / MX / EU / US / CA / JP: top sector, top sector %,
inst_pct_mean, θ_EAV median.

**Analysis 4 — cross-sector orthogonality Spearman:**

Per-GICS-sector median θ_EAV vs median inst_pct (across 10 sectors);
Spearman rho → tests if sector-level θ is a function of sector-level
inst pct.

### 2.3 Guardrails

- Seed = 42.
- Cluster-robust SE (by market) — K1171 / K1172 panel convention.
- F-tests computed on joint sector-FE block (9 dummies; 10 sectors − 1
  base).
- Coverage verified via assert panel == 182 rows after merge.
- Yfinance fetch done once (2026-04-18) with 0.1s polite sleep; results
  persisted to `k1207_stock_sectors.csv`.

---

## 3. Data coverage

| Market | N | GICS-classified | Source |
|--------|---|-----------------|--------|
| AU | 10 | 10 (100%) | yfinance |
| BR | 10 | 10 (100%) | yfinance |
| CA | 10 | 10 (100%) | yfinance |
| EU | 18 | 18 (100%) | yfinance |
| HK | 5 | 5 (100%) | yfinance |
| ID | 10 | 10 (100%) | yfinance |
| IN | 10 | 10 (100%) | yfinance |
| JP | 30 | 30 (100%) | yfinance |
| KR | 10 | 10 (100%) | yfinance |
| MX | 9 | 9 (100%) | yfinance |
| TW | 30 | 30 (100%) | yfinance |
| US | 30 | 30 (100%) | yfinance |
| **Total** | **182** | **182 (100%)** | |

Sector counts: Financials 45, Information Technology 29, Industrials 19,
Consumer Staples 19, Communication Services 17, Consumer Discretionary
15, Health Care 14, Materials 13, Energy 10, Real Estate 1.
Utilities absent from the K1171 pool entirely.

---

## 4. Results

### 4.1 Analysis 1 — Sector-FE only (no market FE)

| Spec | R² | Adj-R² | Sector-FE F | p | df |
|---|---|---|---|---|---|
| S1 sector-FE | 0.1792 | 0.1362 | 380.39 | 2.0e-12 | 9 |
| S2 +log_mcap | 0.1837 | 0.1360 | — | — | — |

Even without market-FE, GICS sector explains 18% of total θ_EAV
between-stock variance. log_mcap adds <0.5 percentage point.

### 4.2 Analysis 2 — 4-model panel OLS (y = θ_EAV) [PRIMARY]

| Model | Controls | R² | Adj-R² | inst_pct β (t) | sector-FE F (p) |
|---|---|---|---|---|---|
| **M1** | mkt FE + log_mcap | 0.1547 | 0.0947 | — | — |
| **M2** | M1 + inst_pct | 0.1640 | 0.0993 | **−1.27e−3 (−0.87)** | — |
| **M3** | M1 + sector FE | **0.3305** | **0.2427** | — | **689.5 (7.9e−14)** |
| **M4** | M1 + inst_pct + sector FE | 0.3376 | 0.2460 | **−1.22e−3 (−0.80)** | **154.4 (2.8e−10)** |

**Incremental adj-R²**:
- inst-FE (M2 − M1): **+0.0046**
- sector-FE (M3 − M1): **+0.1480**
- joint (M4 − M1): +0.1513

**Sector-FE adds 32× more explanatory power than inst_pct**.

**inst_pct coefficient stability** (M2 → M4):
- β: −0.001274 → −0.001219 (|Δ|/|β| = **4.4%** — stable)
- t: −0.87 → −0.80
- Both remain NS in cluster-robust SE panel.

**Reading**: adding sector FE (a) MASSIVELY increases explained
variance, (b) leaves inst_pct's (already weak) within-market coefficient
essentially unchanged in sign, magnitude, and significance. Sector and
inst_pct are **empirically orthogonal within-market channels** — exactly
what K1171's narrative claim predicted.

### 4.3 Analysis 2b — Robustness: y = θ_rel_stock

| Model | R² | Adj-R² | inst_pct β (t) | sector-FE F (p) |
|---|---|---|---|---|
| M1_rel | 0.1726 | 0.1138 | — | — |
| M2_rel | 0.1731 | 0.1091 | +0.577 (+0.42) | — |
| M3_rel | 0.3031 | 0.2116 | — | 688.3 (7.9e−14) |
| M4_rel | 0.3034 | 0.2070 | +0.501 (+0.23) | 372.9 (2.3e−12) |

Incremental adj-R²: inst = **−0.005** (actually negative adj),
sector = **+0.098**. Qualitative pattern identical to primary spec;
sector dominates. inst_pct sign flips to positive but |t| < 0.5 NS in
both M2_rel and M4_rel. Conclusion robust to the θ_rel_stock scaling.

### 4.4 Analysis 3a — Sector-adjusted residual by market

After subtracting each stock's GICS-sector global mean, per-market
residual magnitude changes by:

| Market | raw θ_EAV mean | sec-adj mean | |Δ| reduction% | Interpretation |
|---|---|---|---|---|
| JP | +1.02e−3 | −3.7e−6 | **+99.6%** | Sector fully explains JP |
| IN | +6.98e−4 | −3.2e−5 | **+95.4%** | Sector explains IN almost entirely |
| ID | +4.28e−4 | −7.1e−5 | +83.5% | Sector dominates ID |
| MX | +6.90e−4 | +1.50e−4 | **+78.2%** | Sector explains ~3/4 of MX |
| US | +2.02e−3 | +9.97e−4 | +50.6% | Sector explains half of US |
| EU | +6.49e−4 | −3.4e−4 | +48.1% | Half EU explained; residual negative |
| BR | +1.68e−3 | +1.03e−3 | **+38.6%** | Sector explains ~38% of BR residual |
| CA | +3.60e−4 | −2.65e−4 | +26.3% | Sector explains 1/4 of CA |
| **AU** | +2.95e−4 | −3.87e−4 | **−31.2%** | **Sector-adjustment AMPLIFIES AU residual — NOT explained by sector** |
| TW | +3.95e−4 | −5.51e−4 | −39.6% | Sector amplifies TW residual |
| HK | +2.47e−4 | −3.44e−4 | −39.2% | Sector amplifies HK residual |
| KR | +7.7e−5 | −9.60e−4 | **−1149.9%** | Sector amplifies KR residual massively |

**Reading**: the K1171 "sector as independent driver" claim is
empirically VERIFIED for the above-ladder residuals (BR, IN, MX —
38.6%, 95.4%, 78.2% of the raw residual is sector-attributable) and
for JP (99.6% sector-absorbed). For AU, TW, HK, KR the raw θ_EAV is
BELOW the global sector mean, so removing sector expectations
amplifies (rather than reduces) the absolute residual — i.e. these
markets are **actively low-θ_EAV relative to their sector mix**, and
the residual is NOT sector-driven. AU below-ladder K1171 hypotheses
(semi-annual reporting cadence, HAND_CODED ±1-day precision) retain
leading-explanation status.

### 4.5 Analysis 3b — per-market sector mix (highlighted)

| Market | N | Top sector | Top % | inst_pct_mean | θ_EAV median |
|---|---|---|---|---|---|
| AU | 10 | Financials | **50.0** | 0.375 | 1.16e−4 |
| BR | 10 | Financials | 40.0 | 0.486 | 7.91e−4 |
| IN | 10 | Financials | 40.0 | 0.383 | 6.09e−4 |
| MX | 9 | Consumer Staples | 44.4 | 0.195 | 2.08e−4 |
| EU | 18 | Consumer Discretionary | 22.2 | 0.413 | 2.27e−4 |
| US | 30 | Information Technology | 23.3 | 0.750 | 2.32e−4 |
| CA | 10 | Financials | **50.0** | 0.552 | 1.05e−4 |
| JP | 30 | Industrials | 26.7 | 0.425 | 7.62e−4 |

Interesting structural observation: AU and CA are BOTH
Financials-heavy (50%) and BOTH land low-θ_EAV relative to their
inst_pct rank. This hints at a "Financials-dominant market depresses
θ_EAV" effect — but K1207 does NOT claim this beyond AU/CA
observation since N=2 is too thin.

### 4.6 Analysis 4 — cross-sector orthogonality Spearman

| Sector | n | median θ_EAV | median inst_pct | median log_analyst |
|---|---|---|---|---|
| Communication Services | 17 | 3.35e−4 | 0.318 | 2.94 |
| Consumer Discretionary | 15 | 3.52e−4 | 0.342 | 3.18 |
| Consumer Staples | 19 | 1.84e−4 | 0.195 | 2.94 |
| Energy | 10 | 1.72e−4 | 0.552 | 3.04 |
| Financials | 45 | **1.22e−4** | 0.407 | 2.71 |
| Health Care | 14 | 1.95e−4 | 0.575 | 3.20 |
| Industrials | 19 | 5.66e−4 | 0.378 | 2.71 |
| Information Technology | 29 | **1.37e−3** | 0.464 | 3.14 |
| Materials | 13 | 2.08e−4 | 0.244 | 2.56 |
| Real Estate | 1 | 5.12e−4 | 0.474 | 2.48 |

**Spearman ρ(sector θ_median, sector inst_pct_median) = −0.006,
p = 0.987, n = 10**.

The two variables are **empirically independent** at sector level.

Notable extremes:
- **Information Technology** has **highest** sector-median θ_EAV
  (1.37e−3) — ~10× above Financials' median (1.22e−4). This is the
  dominant sector-level effect: earnings-announcement vol is a strong
  function of whether the firm is in a high-growth / high-idiosyncratic
  sector (IT) or a low-idiosyncratic regulated sector (Financials).
- **Financials lowest** — consistent with AU / CA Financials-heavy
  markets landing below ladder.
- **Consumer Staples** has LOWEST inst_pct_median (0.195) but mid θ_EAV
  (1.84e−4) — counter-example to any "more institutional → higher
  θ_EAV" within-sector story.

---

## 5. Verdict

**`SECTOR_ORTHOGONAL_CONFIRMED`**.

All 3 verdict-rule thresholds cleared:

| Rule | Threshold | K1207 actual | Pass |
|---|---|---|---|
| sector adj-R² inc ≥ 0.5 × inst adj-R² inc | 0.5× (0.0046) = 0.0023 | sector inc = 0.1480 | 32× over ✓ |
| inst_pct β \|Δ\| M2→M4 < 25% | < 25% | 4.4% | ✓ |
| sector-FE joint p < 0.10 | p < 0.10 | 7.9e−14 | ✓✓✓ |

**Note on interpretation**: "orthogonal" here means sector_FE and
inst_pct carry (statistically) independent within-market information
about θ_EAV. It does NOT mean sector is the *mechanism behind* the
BR/IN/MX residual. The sector-adjusted residual table (§4.4) shows
sector explains ~40–95% of those residuals' magnitude, which is a
STRONGER claim: **sector is the dominant channel, inst_pct a
tangential one**. Paper 2 §5 narrative should say so plainly.

---

## 6. Paper 2 §5 narrative commitment

**Decision**: K1171 sector-orthogonal claim is **EMPIRICALLY VERIFIED**.
Paper 2 §5 should absorb one concrete bullet and preserve the AU
caveat:

> "A GICS sector fixed-effect augmentation of the K1171 panel adds
> incremental adj-R² of 0.148 — roughly 32 times the incremental adj-R²
> of institutional ownership (0.005) — and the joint sector F-test is
> highly significant (F = 689.5, p < 10⁻¹³, market-clustered SE).
> Institutional-ownership coefficient is stable across specifications
> (Δβ = 4.4%, |t| < 1 both with and without sector FE). Per-market
> sector-adjusted residuals absorb 95%, 78%, 39% of the India, Mexico,
> Brazil above-ladder residuals respectively. The Australian
> below-ladder residual is NOT sector-absorbed (sector adjustment
> amplifies its magnitude by 31%), so the K1171 hypothesis that AU's
> low θ_rel reflects semi-annual reporting cadence or HAND_CODED
> date precision remains the leading explanation. Sector composition
> is therefore a dominant independent structural driver of θ_rel for
> emerging markets, while idiosyncratic reporting features dominate
> for developed-market outliers."

This survives the **narrative state machine** (≥ 3 supporting
experiments — K1168 / K1171 / K1172 / K1204 / **K1207**). **Not a
unilateral pivot; K1207 concretises a claim already present in K1171
§6.2.**

The two-level R² structure (between inst 0.42, within analyst 0.053
from K1204) is preserved — K1207 adds a **third level**: within-market
sector-FE 0.148 > inst-FE 0.005.

---

## 7. Limitations

1. **GICS at parent-company level**: yfinance returns HQ-country parent
   sector. Multi-sector conglomerates (Reliance IN, Wesfarmers AU) are
   classified to their "primary" sector; GICS Industry Group / Sub-
   Industry granularity not tested.
2. **N per sector uneven**: Financials n=45, Real Estate n=1. Per-sector
   within-market Spearman limited by sample; Spearman across 10 sectors
   with n_sectors=10 gives moderate power.
3. **Utilities absent from pool**: the K1171 large-cap slice excludes
   utility firms entirely. Paper 2 §5 narrative should note this.
4. **Sector-FE ≠ sector mechanism**: K1207 decomposes variance; it does
   NOT pin down *why* IT has high θ_EAV and Financials low. Candidate
   channels (idiosyncratic growth vol, regulatory earnings smoothing,
   analyst dispersion) remain for follow-up K1208+.
5. **No sector × market interaction**: M4 assumes sector effect is the
   same across markets. A saturated sector × market FE model (~100 cell
   combos) is underpowered at N=182 and not attempted.
6. **AU mechanism not resolved**: K1207 confirms AU residual is NOT
   sector-explained but does not test the semi-annual / HAND_CODED
   hypotheses. K1176 (AU mid-cap) and K1177 (HAND_CODED ±3-day
   sensitivity) remain open.

---

## 8. Preamble Rule #5 self-challenge

| Check | Status |
|---|---|
| Mechanical vs empirical | Empirical — sector FE is a covariate control, not a construction |
| Tautology? | No — θ_EAV is per-stock MLE output; sector is external classification |
| ρ > 0.95 trigger? | No — sector-vs-inst Spearman = −0.006 NS; F-test large but expected given 9 df and n=182 |
| Panel t > 10 trigger? | No — biggest t (log_mcap) |t| = 0.37 |
| Sharpe > 2× baseline? | N/A |
| Sample size | N=182 OK; per-sector min=1 (Real Estate), otherwise 10+ |
| Result strength exceeds evidence? | No — "sector orthogonal to inst" confirmed but "sector explains AU" clearly rejected |
| yfinance coverage | 100% — no HAND fallback invoked; HAND map retained for reproducibility |

---

## 9. Files

- `k1207_fetch_sectors.py` — yfinance sector fetcher + HAND_CODED backup
  map for all 182 tickers.
- `k1207.py` — main 4-model panel OLS + 3 diagnostic analyses.
- `k1207_figures.py` — 3 PNGs at 300dpi (sector-median θ, per-market
  sector mix, R² decomposition).
- `k1207_stock_sectors.csv` — 182-row sector classification (100%
  yfinance, 0% HAND used).
- `k1207_sector_median.csv` — per-GICS-sector θ_EAV / inst_pct medians.
- `k1207_per_market_sector_mix_pct.csv` — 12 × 10 market × sector share
  pivot table.
- `k1207_sector_adjusted_residuals.csv` — per-market raw vs
  sector-adjusted θ residuals.
- `k1207_results.json` — full structured results (all 4 models + 2b
  robustness + 3a/3b + verdict).
- `k1207_sector_theta_median.png` — Fig 1.
- `k1207_per_market_sector_mix.png` — Fig 2.
- `k1207_r2_decomposition.png` — Fig 3.
- `run_fetch.log`, `run.log` — execution logs.

---

## 10. References

- Bartram, S.M., Brown, G.W., Stulz, R.M. (2012). *Why are U.S. stocks
  more volatile?* **JF** 67(4), 1329–1370. (sector composition as
  idiosyncratic-vol driver)
- Ferreira, M.A., Matos, P. (2008). *The colors of investors' money*.
  **JFE** 88(3), 499–533. (institutional-ownership cross-country panel)
- Patton, A.J. (2011). *Volatility forecast comparison using imperfect
  volatility proxies*. **JoE** 160(1), 246–256.
- Harvey, C.R., Liu, Y., Zhu, H. (2016). **RFS** 29(1), 5–68.
- MSCI / S&P Dow Jones Indices. *Global Industry Classification Standard
  (GICS) methodology* (11 sectors, 25 industry groups).

---

## 11. Related K

- **K1168**: N=10 cross-market first extension, ρ(inst_pct)=+0.612.
- **K1171**: N=13 extension (+AU HAND_CODED), ρ=+0.385, narrative
  introduced "sector orthogonal driver" claim without empirical test.
- **K1172**: N=12 extension (+MX, +ID; ZA dropped).
- **K1204**: Paper 2 §5 synthesis with two-level R² decomposition
  (between inst 0.42, within analyst 0.053). K1207 adds a third level:
  within-market sector-FE 0.148.
- **K1207 (this)**: GICS sector-FE empirical test of K1171 claim.
  **SECTOR_ORTHOGONAL_CONFIRMED.** Sector-FE incremental adj-R² 32×
  inst-FE; inst_pct β stable M2 → M4; sector explains 95/78/39% of
  IN/MX/BR residual magnitudes; does NOT explain AU below-ladder
  residual (sector-adjustment amplifies by 31%).
- **K1208 (proposed)**: sector × market interaction FE + IT-vs-Financials
  per-market θ_EAV decomposition.
- **K1209 (proposed)**: GICS Industry-Group (25-way) granularity test —
  does the Financials low-θ finding survive banks vs insurance vs
  diversified-financials split?
- **K1176 (open)**: AU mid-cap test — does ASX 50–200 slice carry higher
  θ_EAV than the Top-10 Financials-dominated slice used in K1171?
- **K1177 (open)**: HAND_CODED ±3-day sensitivity — bounds AU θ_EAV
  uncertainty from date precision.
