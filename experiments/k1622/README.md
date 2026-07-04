# K1622 — Forecast Reconciliation for RV Prediction: is coherence a "free lunch"?

**Verdict (one line): NO free lunch.** Temporal reconciliation is a near-exact
NULL (asset/horizon-mixed, net ≈ 0); cross-sectional reconciliation is neutral-to-
**harmful** (significantly degrades the SPY aggregate at 1d) and can produce
invalid negative-variance forecasts; combined inherits the cross-sectional cost.

---

## 1. Motivation

HAR base forecasts of realized variance (RV) are produced **independently** for
each horizon (1d/5d/22d) and each asset (SPY aggregate vs sector-ETF components).
**Forecast reconciliation** (Wickramasuriya, Athanasopoulos & Hyndman 2019, JASA —
"MinT") is an *ex-post* linear projection that forces those independent forecasts
onto a **coherent** subspace: (i) temporal aggregation consistency (the 5-day and
22-day forecasts equal the sums of their daily constituents) and (ii) cross-
sectional aggregation consistency (the aggregate equals a linear combination of
components). The strong claim in the hierarchical-forecasting literature is that
reconciliation is essentially **"free"**: coherence never hurts and often helps
*every* series, at *every* level, for *free* (no extra data, only a projection).

We test that strong claim on RV, a quantity where the temporal aggregation is an
exact sum but the **cross-sectional aggregation is only approximate** (portfolio
variance is *not* the linear sum of component variances — correlations matter).
That asymmetry is the crux of whether reconciliation is truly free here.

## 2. Differentiation from prior K (reconciliation ≠ combination)

- **K1315 (PASS_NULL)** — forecast **combination**: a weighted/convex average of
  competing models (HAR-ABS + HAR-VIX) for **one** target (SPY daily RV);
  concluded VIX is a sufficient statistic, combination adds nothing.
- **K1184** — HAR combination under exp-QLIKE. Same "pool competing models on one
  target" paradigm.
- **K1622 is orthogonal**: reconciliation does **not** average competing models.
  It imposes cross-horizon / cross-asset **aggregation constraints** on forecasts
  of *different-but-related* targets and projects them onto a coherent subspace.
  A weighted average lives inside one target's space; a reconciliation moves across
  a hierarchy. This is the first test in our program of whether *coherence itself*
  (not model averaging) buys anything for RV.

## 3. Data (long-history proxy — disclosed)

| Role | Ticker(s) | n_obs | Period |
|---|---|---|---|
| Cross-sectional aggregate | SPY | 4147 | 2010-01-04 .. 2026-06-30 |
| Cross-sectional components | XLK, XLF, XLE, XLV, XLY, XLI | 4147 each | same |
| TW temporal robustness | 0050.TW | 4013 | same |

- **RV measure = Garman-Klass range-based variance proxy** from daily OHLC:
  `GK = 0.5·(ln H/L)² − (2 ln2 − 1)·(ln C/O)²`, with a Parkinson fallback
  `(1/4ln2)·(ln H/L)²` on the (rare) non-positive GK day (0 US, 16 TW days).
- **Proxy disclosure (honesty):** GK is chosen *deliberately* to obtain a **long
  sample (≥500/asset; here ~4100)**, which the strong "free-lunch" claim requires.
  It is **NOT** 5-minute RV. Our local 5-min RV series are far too short to be the
  main sample (SPY 117 obs, 0050 empty).
- **Recent high-frequency cross-check (SPY only, 115 overlapping days, 2026-01-14
  .. 2026-06-30):** GK vs 5-min RV log-Pearson = **0.688**, Spearman = **0.692**,
  mean ratio GK/5-min = **0.918**. The range proxy tracks true intraday RV with
  good rank fidelity and near-unit level — adequate for a *relative* comparison of
  base vs reconciled (both use the identical proxy, so any proxy bias cancels).
- Data cached under `data/` (yfinance daily OHLC, `auto_adjust=False`).

## 4. Method

### 4.1 HAR base forecasts (Corsi 2009)
Per asset, per node: `target = β0 + β_d·RV_d + β_w·RV_w + β_m·RV_m + ε`, where
`RV_d=RV(o)`, `RV_w=mean RV(o-4..o)`, `RV_m=mean RV(o-21..o)` use info **up to and
including** the forecast origin `o`. Expanding window, OLS, **monthly refit** (21
trading days). OOS after a 750-day burn-in → **3375 origins** (US), 3241 (TW).

### 4.2 Temporal hierarchy (grouped, exact-sum coherence)
Bottom = 3 non-overlapping blocks of the 22-day-ahead window:
`b1 = day 1`, `b2 = days 2–5` (4d), `b3 = days 6–22` (17d).
Aggregates: `A5 = b1+b2` (**5-day target**), `A22 = b1+b2+b3` (**22-day target**);
`b1` **is** the 1-day target. Direct HAR base forecasts for all 5 nodes; MinT then
projects onto the 3-dim coherent bottom. Summing matrix `S` (5×3) has all
non-negative integer entries → temporal aggregation is an *exact* identity.

### 4.3 Cross-sectional hierarchy (approximate coherence — disclosed)
Aggregate `SPY = w'·[6 sector RVs]`, weights `w` fit by **NNLS** (non-negative,
in-sample, refit monthly, on realized variances up to the no-lookahead cutoff).
Non-negativity is imposed because a variance cannot contribute negatively;
unconstrained OLS weights (tested) inject spurious negative weights that make MinT
emit invalid negative-variance forecasts. This coherence is **approximate**:
variances are not linearly additive across assets, so `w'·sectors ≈ SPY` is a
fitted projection, not an accounting identity. The empirical question is precisely
whether imposing this imperfect constraint helps (free) or hurts (misspecified).

### 4.4 Combined (sequential cross-temporal)
Temporal MinT first (per asset), then cross-sectional MinT on the temporally-
reconciled forecasts (Kourentzes & Athanasopoulos 2019, sequential cross-temporal
approximation — disclosed; full one-shot cross-temporal MinT not attempted). The
cross-sectional covariance `W_cs` in this step is estimated from the residuals of
the **reconciliation input** (the temporally-reconciled forecasts), not the raw
base, so `W` is consistent with what MinT actually operates on (Codex-review fix).

### 4.5 Reconciliation
MinT(Shrink): `G = (S'W⁻¹S)⁻¹ S'W⁻¹`, `b̃ = G·ŷ`, `ỹ = S·b̃`. Covariance `W`
= Schäfer–Strimmer shrinkage of the **in-sample** base-forecast error covariance
toward its diagonal (no lookahead; seed=42).

### 4.6 Evaluation
- **QLIKE canonical** `actual/pred − log(actual/pred) − 1` via
  `volpred.stats.model_evaluation.qlike_pointwise` (K783c rule — no reverse QLIKE).
- **Per-horizon DM**: HAC variance with lags `1..H−1` (**1d→0, 5d→4, 22d→21**) +
  **HLN (1997)** finite-sample correction `√((T+1−2H+H(H−1)/T)/T)`, Student-t(T−1).
  `t>0 ⇒ reconciliation has lower loss (better)`. **Harvey (2016) |t|>3** for
  significance. No shared DM horizon across targets.
- **Cross-sectional DM (K1355)**: aggregate the cross-asset QLIKE loss differential
  **by date** first, then run per-horizon HAC/DM on the date series (primary).
  Stacked asset-day DM reported as **diagnostic only** (understates SE).
- **Invalid-forecast handling (honesty):** MinT can (rarely) emit non-positive or
  implausibly-tiny variance forecasts, which are singular under QLIKE's log. We
  floor arrays at 1e-12 for safety but **exclude** from QLIKE/DM any forecast
  below `VALID_FLOOR = 1e-6 ≈ (0.1% daily vol)²` — the minimum economically
  plausible daily variance (empirical 1-day actual 1st-pct ≈ 4.7e-6; multi-day
  cumulative variances are far larger), so the threshold catches **only** the
  ~0.004–0.013% numerical artifacts, never real low-vol days. Base HAR forecasts
  never trip it — measured `n_invalid_base = 0` at every horizon confirms the mask
  is unbiased/symmetric. Excluded counts are **reported** (`n_invalid_recon`,
  `n_invalid_base`) as the key cross-sectional instability diagnostic. Critically,
  excluding the worst reconciled points is **conservative for the no-free-lunch
  conclusion**: including them would only make reconciliation look *worse*, so the
  reported harm is a lower bound.

## 5. Related K
K1315 (VIX sufficiency / combination PASS_NULL), K1184 (HAR combination), K1355
(cross-asset pooled inference → date-aggregate before DM), K783c (canonical QLIKE),
K445 (arch forecast alignment / off-by-one risk).

## 6. Anti-error self-check table

| Risk | Rule | Status | Evidence |
|---|---|---|---|
| **Lookahead (features)** | RV_d/w/m use ≤ day o | ✅ | `har_features` rolling means end at o |
| **Lookahead (train target)** | j+H ≤ o−1 (`target_end < origin`) | ✅ | `cutoff = o−1−NODE_MAXH[node]` per node |
| **Lookahead (MinT W / CS weights)** | in-sample only, ≤ cutoff | ✅ | W from `R[:cutoff+1]`; NNLS on `act_mat[:cutoff+1]` |
| **Lookahead (empirical audit)** | corrupt future ⇒ past unchanged | ✅ | ×1000 future RV → **max\|Δ\|=0.0** on 1727 safe origins; post-cut Δ=742 (test valid) |
| **Per-horizon DM** | lag=H−1, no shared horizon | ✅ | `dm_hln(..., H)` with `range(1,H)` + HLN |
| **HLN small-sample** | √((T+1−2H+H(H−1)/T)/T) | ✅ | `corr` in `dm_hln` |
| **Cross-asset HAC (K1355)** | date-aggregate then DM | ✅ | `date_aggregated_dm`; stacked = diagnostic |
| **Canonical QLIKE (K783c)** | actual/pred, no reverse | ✅ | `qlike_pointwise` (volpred) |
| **Seed fixed** | seed=42 | ✅ | `np.random.seed(42)`; shrinkage analytic |
| **Fair comparison** | base & recon: same lag/OOS/loss/mask | ✅ | identical origins, identical QLIKE, symmetric VALID_FLOOR |
| **Too-good-to-be-true** | Sharpe/impr >> baseline ⇒ suspect | ✅ | improvements are ~0.01–6%, mostly null; no miracle |

## 7. Results

Base QLIKE is the same across all variants at a given horizon (identical base
forecasts). `impr%` = (QLIKE_base − QLIKE_recon)/QLIKE_base; **positive = recon
better**. DM `t>0 = recon better`; **|t|>3 = significant** (Harvey).

### 7.1 Temporal reconciliation — near-exact NULL
Pooled across the 7 US assets (date-aggregated, N=3375):

| Horizon | QLIKE base | QLIKE recon | impr% | DM t | verdict |
|---|---|---|---|---|---|
| 1d | 0.3900 | 0.3899 | +0.014% | +2.14 | PASS_NULL |
| 5d | 0.3055 | 0.3055 | −0.002% | −0.09 | PASS_NULL |
| 22d | 0.3191 | 0.3190 | +0.024% | +2.02 | PASS_NULL |

Per-asset DM t (verdict): the effect is **mixed and asset-specific**, netting to
zero — some significant *gains* (XLF 1d t=+4.04 PASS; XLE 22d t=+3.07 PASS) offset
by significant *losses* (SPY 1d t=−4.96 FAIL; 0050.TW 1d t=−3.29 FAIL). Magnitudes
are economically negligible everywhere (|impr| < 0.1%). **No uniform free lunch:
temporal coherence neither systematically helps nor hurts.** The significant-but-
tiny signs are a power artifact (N=3375, near-identical losses).

### 7.2 Cross-sectional reconciliation — neutral-to-harmful
Date-aggregated (primary):

| Horizon | QLIKE base | QLIKE recon | impr% | DM t | verdict | n_invalid |
|---|---|---|---|---|---|---|
| 1d | 0.3903 | 0.3941 | **−0.98%** | **−3.70** | **FAIL** | 1 |
| 5d | 0.3067 | 0.3084 | −0.54% | −0.80 | PASS_NULL | 0 |
| 22d | 0.3221 | 0.3323 | −3.16% | −0.65 | PASS_NULL | 3 |

Direction is **uniformly negative** (recon worse) at every horizon. The damage
concentrates on **the SPY aggregate** (1d per-asset t=**−6.23**, −6.16%): imposing
the approximate cross-sectional identity pulls the already-good aggregate forecast
toward noisier sector-based information. Sectors are mostly PASS_NULL. MinT also
emitted 1–3 invalid (negative/near-zero) variance forecasts per horizon — a
concrete failure of the "free lunch" claim, since a *free* method should never
produce an *invalid* forecast. Stacked-diagnostic DM agrees (1d t=−4.57 FAIL).

### 7.3 Combined (sequential) — inherits cross-sectional cost
1d −0.97% (t=−3.66 **FAIL**), 5d −0.52% (PASS_NULL), 22d −3.82% (PASS_NULL). The
cross-sectional step dominates; temporal-first does not rescue it.

### 7.4 Codex review
Independent Codex (gpt-5.5) review: **core PASS** — temporal lookahead, target
slicing (no off-by-one), per-horizon DM (lag=H−1 + HLN), QLIKE direction, and MinT
formula all verified correct. Four CONCERNs were raised and all addressed in this
version: (i) combined `W_cs` now uses the reconciliation-input residuals; (ii)
`n_invalid_base` now counted/reported (=0 everywhere); (iii) conservative-exclusion
of invalid forecasts documented as a lower bound on harm; (iv) design string
corrected OLS→NNLS. None changed the direction of any verdict.

## 8. Success criteria & honest conclusion

**Success criterion (pre-registered):** cleanly decide, per horizon × variant,
whether reconciliation beats base under a proxy-robust loss with lookahead-safe,
horizon-correct inference — *whatever the direction*. Met.

**Conclusion — reconciliation is NOT a free lunch for RV forecasting:**
1. **Temporal** coherence (exact-sum hierarchy) is a **near-exact null**: mixed,
   asset-specific, economically negligible, net ≈ 0. HAR base forecasts already
   extract the aggregation-relevant information, so imposing consistency adds no
   orthogonal signal.
2. **Cross-sectional** coherence is **neutral-to-harmful** and, unlike the strong
   claim, can *degrade* the aggregate and even emit *invalid* forecasts. Root cause
   is economic, not numerical: portfolio variance is not the linear sum of
   component variances, so the imposed identity is misspecified and injects error.
3. **Combined** inherits the cross-sectional cost.

The claim's strength is bounded by the evidence: we do **not** claim reconciliation
is universally harmful — temporal reconciliation is genuinely null and a few
asset/horizon cells show small significant gains. We claim only that the **"free
lunch / helps everything" framing is rejected for RV**, and that cross-sectional
variance reconciliation specifically carries a misspecification cost.

**Caveats / residual risk:** (a) GK range proxy (not 5-min RV) — recent SPY cross-
check ρ≈0.69 supports rank fidelity but a full 5-min replication on a long sample
would strengthen it; (b) cross-sectional coherence is a fitted NNLS projection, not
an identity — a covariance-aware (RCov) aggregation might behave differently and is
left for future work; (c) combined uses a *sequential* (not one-shot) cross-temporal
MinT; (d) monthly refit (not daily) for tractability.

## 9. Files
- `k1622.py` — reproducible pipeline (fetch/cache → HAR → MinT → DM → JSON → figs)
- `k1622_results.json` — per-horizon × variant QLIKE / DM t / p / N / n_invalid + per-asset breakdown + 5-min cross-check
- `plots/fig1_qlike_base_vs_recon.png` — per-horizon base vs reconciled QLIKE (3 variants) with DM significance
- `plots/fig2_cross_sectional_improvement.png` — per-asset QLIKE improvement distribution (cross-sectional)
- `data/*.csv` — cached daily OHLC

## 10. References
- Wickramasuriya, Athanasopoulos & Hyndman (2019). *Optimal forecast reconciliation
  for hierarchical and grouped time series through trace minimization.* JASA 114(526).
- Athanasopoulos, Hyndman, Kourentzes & Petropoulos (2017). *Forecasting with
  temporal hierarchies.* European Journal of Operational Research 262(1).
- Kourentzes & Athanasopoulos (2019). *Cross-temporal coherent forecasts.* (sequential
  cross-temporal reconciliation).
- Athanasopoulos, Gamakumara, Panagiotelis, Hyndman & Affan (2024). *Forecast
  reconciliation: a review.* International Journal of Forecasting.
- Corsi (2009). *A simple approximate long-memory model of realized volatility.*
  Journal of Financial Econometrics 7(2).
- Parkinson (1980). *The extreme value method for estimating the variance of the
  rate of return.* Journal of Business 53(1).
- Garman & Klass (1980). *On the estimation of security price volatilities from
  historical data.* Journal of Business 53(1).
- Patton (2011). *Volatility forecast comparison using imperfect volatility proxies.*
  Journal of Econometrics 160(1). (proxy-robust QLIKE)
- Harvey, Leybourne & Newbold (1997). *Testing the equality of prediction mean
  squared errors.* International Journal of Forecasting 13(2). (small-sample DM)
- Diebold & Mariano (1995); Harvey et al. (2016) (|t|>3 multiple-testing threshold).
