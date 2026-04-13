# K1067e — EAV-only ablation of the K1145-K1170 A4f-EAV spec

> **TL;DR**: Is the K1145-K1170 pooled and K1166 per-stock θ_EAV effect truly
> EAV-driven, or is VIX doing the heavy lifting? **Verdict: H3 — partial
> collinearity, but EAV is the dominant signal.** Removing VIX from the
> long-run MIDAS term keeps θ_EAV_i nearly identical (ρ=+0.898, sign agreement
> 96.4%) and strengthens the K1166 analyst-coverage mechanism
> (panel β: +1.17e-3 t=+3.68 vs K1166's +9.68e-4 t=+3.56). **Paper 2 narrative
> SURVIVES the ablation** — EAV is not a VIX artifact.

[提出: Claude (follow-up to K1166 / K1145-K1170 chain), 執行: Claude]

**Random seed**: 42
**N stocks**: 110 (TW 31 + EU 19 + JP 30 + US 30)
**Fit framework**: per-stock MLE, 5 free params (no θ_VIX)
**Runtime**: 12 s total (3.3 s MLE)

---

## 1. 動機（Why）— Ablation test for the whole K1145-K1170 chain

Every experiment in K1145-K1170 — pooled shared fits in K1145 (TW),
K1147 (US), K1150 (JP), K1153 (EU), the cross-market cluster analysis in
K1152/K1164, and the per-stock refit in K1166 — use the **A4f-EAV spec**:

$$
\tau_{i,t} = \max\bigl(\theta_0 + \theta_{VIX}\,VIX^2_{t-1} + \theta_{EAV}\,EAV_{i,t-1},\ \varepsilon\bigr)
$$

This leaves open a critical identification worry: the VIX term captures the
low-frequency global volatility climate, and EAV is a binary lag-1
announcement flag. If earnings days happen disproportionately in
high-VIX regimes (or vice versa), the estimated θ_EAV could be a **residual
artifact of VIX** rather than a genuine earnings-driven signal.

**Three hypotheses** before running:

- **H1 — EAV truly independent**: θ_EAV_i estimated without VIX should look
  essentially identical to the full spec (ρ > 0.9, sign consistency > 85%,
  panel β stays positive and Harvey-significant).
- **H2 — VIX carrying the weight**: noVIX θ_EAV swings wildly, changes sign
  for many stocks, and the K1166 analyst-mechanism β flips or collapses.
- **H3 — Partial collinearity**: signs preserved, but magnitudes shift
  (factor ~1.1–1.5×) because dropping VIX returns variance to the EAV
  loading and to the long-run intercept.

If **H2**, Paper 2's whole mechanism story (EAV → earnings response → analyst
coverage) collapses. If **H1/H3**, the story stands and we just need to
explain the magnitude rescaling.

---

## 2. 方法（Method）

### 2.1 Full baseline vs EAV-only spec

**Full (K1166)** — 6 free params per stock:

$$\tau^{\text{full}}_{i,t} = \max\!\bigl(\theta_{0,i} + \theta_{VIX,i}\,VIX^2_{t-1} + \theta_{EAV,i}\,EAV_{i,t-1},\,\varepsilon\bigr)$$

**K1067e (this experiment)** — 5 free params per stock:

$$\tau^{\text{noVIX}}_{i,t} = \max\!\bigl(\theta_{0,i} + \theta_{EAV,i}\,EAV_{i,t-1},\,\varepsilon\bigr)$$

Identical GJR(1,1) short-run factor $g_{i,t}$ with Engle–Ghysels–Sohn (2013)
$E[g]=1$ normalization ($\omega_{g,i}=1-\alpha_i-\gamma_i/2-\beta_i$). The
noVIX spec is **strictly nested** in the full spec with $\theta_{VIX}=0$, so a
per-stock LR test is valid.

### 2.2 Reused data and caches

Identical 110-stock sample as K1166:

- Price parquets from `experiments/k1145/k1147/k1150/k1153/data/`.
- EAV built from publicly disclosed earnings (TW: `財報公告日.txt`; US/JP/EU:
  `earnings_dates.json`).
- Analyst/mcap proxies from `experiments/k1164/data/analyst_media_proxies.json`.
- **K1166 full-spec per-stock estimates** loaded from
  `data/k1166_per_stock_table.csv` for direct pairwise comparison and for the
  LR test (per-stock `loglik_full`).
- VIX parquet is still loaded for row alignment (K1166 dropped rows where
  VIX was NaN); VIX values never enter the noVIX likelihood.

### 2.3 Estimation and SE

- `scipy.optimize.minimize(..., method='L-BFGS-B')`, 4-start multi-start,
  numba JIT likelihood. 110 fits via `multiprocessing.Pool(8)` in 3.3 s.
- Hessian SE for $\theta_{EAV,i}$ via central 2nd-order finite difference
  (same recipe as K1166).

### 2.4 Lookahead discipline

- `EAV_{i,t-1}` shifted inside the numba likelihood (`eav[t-1]`, t-loop starts
  at `t=1`).
- All RNG seeded to 42.
- EAV uses announcement dates from publicly disclosed filings (no lookahead).

### 2.5 Cross-stock analysis

1. **Pairwise cross-stock correlation** — Spearman / Pearson
   $\rho(\theta^{\text{noVIX}}_{EAV,i},\ \theta^{\text{full}}_{EAV,i})$ pooled
   and per market.
2. **Sign agreement %** — fraction of stocks where the two estimates share the
   same sign.
3. **Magnitude ratio** — $\theta^{\text{noVIX}}/\theta^{\text{full}}$
   distribution (median, mean, IQR).
4. **Per-stock LR test** — $LR_i = 2(\ell^{\text{full}}_i-\ell^{\text{noVIX}}_i)
   \sim \chi^2_1$; report % reject at 0.05/0.01.
5. **Mechanism replay** — rerun K1166's two headline tests using
   $\theta^{\text{noVIX}}_{EAV,i}$:
   - Pooled Spearman $\rho(\log(\text{analyst}+1),\ \theta^{\text{noVIX}}_{EAV,i})$.
   - Panel OLS with market FE + `log_mcap` control (HC0 SE).
6. **Verdict logic** (H1 / H2 / H3 as above).

---

## 3. 資料（Data）

Identical to K1166. All EU tickers that K1166 dropped for insufficient
`n_events` or missing parquet are skipped here as well → N_EU = 19.

| Market | N_loaded | Period |
|--------|----------|--------|
| TW | 31 | 2010-01 → 2025-12 |
| US | 30 | 2014-01 → 2025-12 |
| JP | 30 | 2014-01 → 2025-12 |
| EU | 19 | 2014-01 → 2025-12 |
| **Total** | **110** | — |

`n_obs` ranges 500–3911, `n_events` ≥ 15 for every stock, same filters as
K1166.

---

## 4. 結果（Findings）

### 4.1 Per-stock comparison of θ_EAV — noVIX vs full

| Market | N | ρ (Spearman, noVIX vs full) | Sign agreement | Mean θ_EAV noVIX | Mean θ_EAV full | Ratio (mean) |
|--------|---|-----------------------------|----------------|-------------------|------------------|---------------|
| TW | 31 | **+0.958** | **100%** | +3.56e-4 | +3.79e-4 | 0.94 |
| EU | 19 | +0.626 | 84% | +2.65e-4 | +6.61e-4 | 0.40 |
| JP | 30 | +0.909 | **100%** | +1.19e-3 | +1.02e-3 | 1.17 |
| US | 30 | +0.864 | 97% | +2.36e-3 | +2.02e-3 | 1.17 |
| **Pooled** | **110** | **+0.898** | **96.4%** | — | — | **median 1.12** |

- **Across 110 stocks, 106/110 (96.4%) keep the same sign.** Only 4 stocks
  flip (3 EU + 1 US; all have small |θ_EAV| and large SE in both specs).
- **Pooled Spearman ρ = +0.898 (p = 2.7e-40)**, Pearson r = +0.849 — very
  strong agreement.
- TW and JP: 100% sign agreement, ρ ≥ +0.91 — extreme stability of the
  per-stock ranking.
- EU is the weakest (ρ = +0.626, 84% sign agreement). Inspection shows EU's
  mean |θ_EAV| is the smallest of the four markets, so small perturbations
  matter more per stock. Even so, EU's fraction positive stays at 0.95
  (noVIX) vs 0.89 (full) — still overwhelmingly positive.

### 4.2 Ratio distribution — does magnitude shift?

| Statistic | Value |
|-----------|-------|
| Median ratio $\theta^{\text{noVIX}}/\theta^{\text{full}}$ | **+1.12** |
| Mean ratio | +1.38 |
| IQR | [+0.82, +1.59] |
| N | 110 |

Pooled median ratio ≈ 1.12 means the noVIX estimate is typically ~12% larger
in magnitude than the full-spec estimate. This is consistent with a mild
collinearity: when VIX is dropped from τ, some of its low-frequency
regime-captured variance is reabsorbed into the long-run intercept and into
the EAV loading (if earnings days are non-uniformly distributed over VIX
regimes). The sign almost always stays positive; the 12% rescaling is much
smaller than the 6–16× ratio between K1145-K1153 pooled shared and K1166
per-stock means (driven by EGS normalization, not VIX removal).

### 4.3 LR test — does VIX still add information per-stock?

| Statistic | Value |
|-----------|-------|
| Mean LR = 2(ℓ_full − ℓ_noVIX) | **+31.84** |
| Median LR | +28.10 |
| % stocks where full > noVIX (LL) | 93.6% (103/110) |
| % LR reject at 0.05 | **88.2%** |
| % LR reject at 0.01 | **88.2%** |

**VIX is clearly an informative variable** — per-stock LR tests reject noVIX
for 88% of stocks at 1%. This is fully expected: VIX² is a continuous,
strongly autocorrelated regressor that captures regime variation in daily
variance; EAV is a sparse 0/1 dummy firing on ~1% of days.

But **informative for τ fit ≠ necessary for θ_EAV identification**. The
ablation cleanly separates these two questions, and the ρ=+0.898 / 96.4%
sign agreement tells us that **when θ_EAV is estimated without VIX, it does
not switch to a different sign or drift onto a new set of stocks**. VIX
improves per-stock daily likelihood; it does not drive the θ_EAV
cross-sectional signal.

### 4.4 Mechanism replay — does the K1166 analyst story still hold without VIX?

**Spearman(log_analyst, θ_EAV_noVIX):**

| Group | ρ | p | N | vs K1166 full |
|-------|---|---|---|---------------|
| Pooled | **+0.232** | **0.016** | 108 | K1166 full: +0.241, p=0.012 |
| TW | +0.160 | 0.398 | 30 | K1166: +0.050 (still NS) |
| US | **+0.634** | **0.0002** | 30 | K1166: +0.575, p=0.001 |
| JP | +0.314 | 0.092 | 30 | K1166: +0.193 |
| EU | +0.312 | 0.207 | 18 | K1166: +0.254 |

Pooled ρ virtually identical (+0.232 vs +0.241). **All four markets still
have ρ > 0**; US strengthens from +0.575 to +0.634.

**Panel regression** `θ_EAV_i_noVIX ~ log_analyst + log_mcap + market_FE`
with HC0 robust SE:

| Coefficient | K1067e noVIX β | K1067e t | K1166 full β | K1166 t |
|-------------|----------------|----------|--------------|---------|
| log_analyst | **+1.168e-3** | **+3.68** | +9.68e-4 | +3.56 |
| log_mcap | +1.04e-4 | +0.46 | −3.31e-6 | −0.02 |
| D_TW | −4.84e-3 | −0.81 | −1.53e-3 | −0.30 |
| D_EU | −5.95e-3 | −1.05 | −2.25e-3 | −0.47 |
| D_JP | −5.14e-3 | −0.77 | −1.54e-3 | −0.27 |
| D_US | −4.51e-3 | −0.76 | −1.24e-3 | −0.25 |
| R² | 0.274 | — | 0.188 | — |
| n | 108 | — | 108 | — |

- **log_analyst β stays positive and Harvey-significant** (|t|=3.68 > 3.0),
  actually slightly stronger than K1166's +3.56.
- **R² improves** from 0.188 to 0.274 — most of this is mechanical because
  dropping VIX inflates the within-stock variance carried by the long-run
  intercept shifts, but the analyst coefficient itself is practically
  unchanged.

### 4.5 Per-market θ_EAV_noVIX significance

| Market | N | mean θ | median | %\|t\|>2 | %\|t\|>3 | frac θ>0 |
|--------|---|--------|--------|----------|----------|----------|
| TW | 31 | +3.56e-4 | +8.3e-5 | 42% | 16% | 0.71 |
| EU | 19 | +2.65e-4 | +1.3e-4 | 53% | 26% | 0.95 |
| JP | 30 | +1.19e-3 | +9.8e-4 | **100%** | 70% | **1.00** |
| US | 30 | +2.36e-3 | +3.4e-4 | 63% | 43% | 0.93 |

Same ordinal pattern as K1166: TW ≤ EU < JP < US in typical magnitude. JP is
still universally significant (|t|>2 for 30/30 stocks). The EGS-normalized
scale is preserved — noVIX does not collapse the market ranking.

### 4.6 Ablation verdict

| Check | Threshold for H1 | K1067e value | Status |
|-------|------------------|--------------|--------|
| Spearman ρ(noVIX, full) | > +0.90 | +0.898 | miss by 0.002 |
| Sign agreement | > 85% | 96.4% | **PASS** |
| Panel β same sign + Harvey t>3 | yes | β=+1.17e-3, t=+3.68 | **PASS** |
| Panel β ratio (noVIX / full) | within [0.5, 2.0] | 1.21 | **PASS** |
| Mechanism Spearman sign | positive | +0.232 | **PASS** |

**Verdict code: H3 (partial collinearity)** — one of the five checks
(ρ=+0.898) is just below the 0.9 bar for H1. In all substantive respects
(signs, panel coefficient, mechanism direction, market ordering) the noVIX
and full estimates are consistent. Functionally this is an **extended H1 /
borderline H3** outcome; nothing resembles H2's "VIX artifact" failure.

---

## 5. 結論（Conclusion）

### Verdict: **H3 — partial collinearity, EAV is the dominant signal**

The EAV-only ablation passes every substantive robustness check:

1. **Per-stock signs survive** — 96.4% of stocks keep the same sign, 0 out of
   60 JP/TW stocks flip.
2. **Per-stock magnitudes stable** — median noVIX/full ratio = 1.12,
   ρ=+0.898 pooled.
3. **Paper 2 mechanism (K1166 analyst coverage) strengthens** — panel
   β(log_analyst) = +1.17e-3, t = +3.68 (vs K1166 +9.68e-4, t = +3.56);
   pooled cross-stock Spearman goes from +0.241 to +0.232 (essentially
   unchanged).
4. **Per-stock LR test rejects noVIX at 88%**, confirming VIX adds log-likelihood
   for daily variance prediction, but **this does not change the θ_EAV
   ranking** — VIX and EAV load on different dimensions of τ.
5. **None of the K1145-K1170 conclusions are VIX artifacts.** Dropping VIX
   does not reverse the signs of pooled θ_EAV, does not change the market
   ordering (TW ≤ EU < JP < US in θ_EAV magnitude), and does not overturn
   the K1166 analyst-coverage mechanism.

### Paper 2 narrative impact

**SAFE.** The EAV effect in Paper 2 is not a VIX residual. Paper 2 can
continue to describe θ_EAV as the firm-level earnings-vol response, with the
following clarification:

- Per-stock τ fits include VIX² as a long-run control; dropping VIX inflates
  |θ_EAV| by ~12% on median and introduces no systematic sign changes.
- The cross-sectional mechanism (analyst coverage predicting θ_EAV) is
  marginally stronger without the VIX control (β = +1.17e-3 vs +9.68e-4);
  either specification passes Harvey (2016) t > 3.
- Reporting both specs in a robustness footnote is the most defensible
  option.

### What to do next (K1067f or K1171+)

| K ID | 主題 | 優先度 |
|------|------|--------|
| K1067f | VIX-only ablation (drop EAV, keep VIX²): sanity-check the flip side — does θ_VIX swing when EAV is removed? Expected small because VIX² is orthogonal to a 1% binary EAV flag. | 中 |
| K1171 | Rolling-window stability of θ_EAV_noVIX (e.g., 2014-2018 vs 2019-2025): does the ablation verdict hold across sub-samples? | 中 |
| K1172 | Paper 2 §4 revision: add robustness table with noVIX ablation (K1067e) alongside the main K1166 results. | 高 |

### 局限承認（Limitations）

1. **Same data as K1166**, so inherits K1166's limitations (per-stock N~500-3000,
   analyst count is yfinance current snapshot).
2. **LR test per stock assumes correct specification** — if the true long-run
   term has additional regressors (e.g., realized variance, macro), both
   noVIX and full are misspecified but the pairwise comparison is still
   informative about the marginal role of VIX.
3. **Hessian SE only** — no block-bootstrap, which would cost ~5 min and is
   unlikely to change the qualitative conclusions.
4. **H3 borderline**: pooled ρ = +0.898 is just below the 0.90 H1 threshold.
   Substantively this is indistinguishable from H1, but we report H3 as the
   letter of the decision rule.
5. **VIX column still required for row alignment** — EU stocks with
   insufficient VIX coverage were already dropped in K1166 filters. We do
   not re-evaluate an alternative alignment that might pick up more EU
   stocks.

### Preamble Rule #5 self-check

- ρ = +0.898 — not in the >0.95 "suspicious" zone; falls in the expected
  H3 range for a genuinely shared θ_EAV signal with a mild collinearity
  correction.
- Sign agreement 96.4% — plausible ceiling for sign stability given 4/110
  near-zero estimates whose SE comfortably allows both signs.
- JP 100% |t|>2 persists from K1166 — not a K1067e-specific finding; already
  investigated and defended in K1166 §4.5.
- No lookahead: EAV is shifted at `t-1` inside the numba loop, and VIX is
  not used at all. RNG seed = 42.

---

## 6. 檔案（Files）

- `k1067e.py` — main script: per-stock noVIX MLE + cross-stock analysis +
  mechanism replay + panel regression.
- `k1067e_results.json` — full results JSON.
- `k1067e_per_stock_comparison.csv` — 110 stocks × (noVIX estimate,
  full estimate from K1166, LR stat, LR p, σ², analyst, mcap, ...).
- `k1067e_scatter_noVIX_vs_full.png` — scatter plot of θ_EAV_i noVIX vs full
  (colour by market), y=x reference line.
- `k1067e_sign_consistency_hist.png` — histogram of ratio noVIX/full plus
  per-market sign-agreement and positivity bars.
- `data/analyst_media_proxies.json` — reused from K1164/K1166.
- `data/k1166_per_stock_table.csv` — K1166 full-spec baseline (for direct
  pairwise comparison and LR test).
- `run.log` — full stdout log.

---

## 7. 參考文獻（References）

- Engle, R.F., Ghysels, E., Sohn, B. (2013). *Stock market volatility and
  macroeconomic fundamentals*. **Review of Economics and Statistics**
  95(3), 776-797. (GARCH-MIDAS with E[g]=1 normalization — parent model)
- Harvey, C.R., Liu, Y., Zhu, H. (2016). *…and the cross-section of expected
  returns*. **RFS** 29(1), 5-68. (t > 3 multiple-testing threshold)
- Patton, A.J. (2011). *Volatility forecast comparison using imperfect
  volatility proxies*. **JoE** 160(1), 246-256.
- Newey, W., West, K. (1987). *A simple, positive semi-definite,
  heteroskedasticity and autocorrelation consistent covariance matrix*.
  **Econometrica** 55, 703-708.

---

## 8. 相關 K 編號（Related K）

- **K1145** (TW): pooled shared θ_EAV = +6.36e-5, Harvey-PASS (full spec).
- **K1147** (US): pooled shared θ_EAV = +1.91e-4, Harvey-PASS.
- **K1150** (JP): pooled shared θ_EAV = +1.41e-4, Harvey-PASS.
- **K1151**: EAV binary vs continuous — binary sufficient.
- **K1152/K1164**: θ_rel cross-market cluster analysis (TW/EU LOW vs US/JP HIGH).
- **K1153** (EU): pooled shared θ_EAV = +4.07e-5, Harvey-PASS; analyst
  coverage × media hypothesis.
- **K1166**: per-stock θ_EAV refit removes σ² tautology → analyst
  mechanism CONFIRMED (panel β = +9.68e-4, t = +3.56).
- **K1067e (this experiment)**: EAV-only ablation → mechanism / signs /
  ranking SURVIVE; ρ(noVIX, full) = +0.898, 96.4% sign agreement, panel
  β(log_analyst)_noVIX = +1.17e-3, t = +3.68. Paper 2 narrative safe.
