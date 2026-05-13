# K1303 v2: HAR-CJ — Jump Decomposition vs HAR-RV

**Revision**: v2_abd (2026-05-13)
**Status**: NULL — HAR-CJ does not significantly improve over HAR-RV on TX1 (gateable primary)

---

## Motivation

K1255 ran intraday seasonality pilot; K1301 (HAR-RS semivariance) reported NULL on TX1+SPY. K1303 tests the **orthogonal decomposition**: continuous (CV) vs jump (J) components of realized variance, following Barndorff-Nielsen & Shephard (2004 JBES; 2006 JFEC) and Andersen-Bollerslev-Diebold (2007 RFS).

Connection to K1301: K1301's semivariance decomposition (RV+/RV−) is **signed** but jump-agnostic; K1303 adds the **orthogonal** decomposition (CV/J). Together they form the 4-component HAR-CSJ family, but K1303 isolates the jump term first to avoid one-shot 4-way confound.

---

## Hypothesis

**H1 (jump-component gain)**: HAR-CJ delivers OOS QLIKE strictly below HAR-RV on TX1 with DM-Harvey corrected |t| > 3 (Harvey 2016 threshold).

**H2 (universality)**: H1 extends to ≥2 of {QQQ, GLD, SPY}.

---

## v2 Corrections (from Codex FAIL report 2026-05-13)

Three blocking defects fixed (ABD1/2/3):

### ABD1: Formal jump identification + stable feature scaling
- **Problem**: v1 used `J = max(RV-BPV, 0)` for all days → noisy near-zero J values → explosive betas (j_d=2224 in v1).
- **Fix**: 3-sigma threshold: `jump_day = max(RV-BPV,0) > μ+3σ`; J_t=0 on non-jump days. Jump expressed as **J/RV ratio** (dimensionless jump share [0,1]) rather than absolute J_abs — this resolves the 100,000x scale mismatch between log(CV)≈−10 and log1p(J_abs)≈0.000006 that caused explosive OLS betas. TX1 has 23 jump days (1.1%) over 2186 trading days.

### ABD2: HAC DM test with QLIKE loss
- **Problem**: v1 used plain sample variance for DM test; MSE loss (not Patton-robust).
- **Fix**: `dm_test()` from `src/volpred/stats/model_evaluation.py:83` (Newey-West HAC). QLIKE pointwise loss per Patton (2011).

### ABD3: Standard 1-step lag
- **Problem**: v1 predicted RV_{t+1} using features at t-1 (2-step-ahead, non-standard).
- **Fix**: Target = log(RV_t), features = .shift(1) → standard 1-step HAR per ABD (2007).

---

## Design

| Item | Setting |
| --- | --- |
| Assets | TX1 (TAIFEX, 2017-2026, primary), SPY/QQQ/GLD (60d yfinance cap, exploratory) |
| Intraday | 5-min log-return²-sum, day session only |
| BPV | (π/2)×(M/(M-1))×Σ\|r_k\|·\|r_{k-1}\| |
| Jump ID | 3-sigma threshold: max(RV-BPV,0) > μ+3σ |
| J feature | J_t/RV_t (dimensionless jump share, [0,1]) |
| CV feature | log(CV_t) |
| Baseline | HAR-RV: log(RV_t) on log lagged RV_{d/w/m} |
| Challenger | HAR-CJ: log(RV_t) on log(CV_{d/w/m}) + J_share_{d/w/m} |
| OOS split | 70/30 chronological |
| DM test | HAC Newey-West (model_evaluation.py:83), QLIKE loss, h=1 |
| Pass rule | \|DM_HLN_t\| > 3 AND HAR-CJ lower QLIKE |
| Seed | 42 |

---

## Lookahead Discipline

- All features use `.shift(1)`: feature at row t = value from day t-1.
- Rolling windows applied to already-shifted series: rv_w at row t = mean(rv_{t-5..t-1}).
- Target = log(RV_t) at row t — no future leakage.
- BPV/J computed from day t-1 intraday only; no contemporaneous day-t data.

---

## Results (v2)

| Asset | n_train | n_test | DM_HLN_t | p | QLIKE_RV | QLIKE_CJ | CJ Lower? | PASS? | Gateable? |
|-------|---------|--------|----------|---|----------|----------|-----------|-------|-----------|
| TX1 | 1514 | 650 | 1.002 | 0.317 | 4.110 | 4.003 | Yes | No | Yes |
| SPY | 26 | 12 | −0.935 | 0.370 | 0.247 | 0.447 | No | No | No |
| QQQ | 26 | 12 | 1.868 | 0.089 | 1.466 | 0.387 | Yes | No | No |
| GLD | 26 | 12 | 2.379 | 0.037 | 1.417 | 0.889 | Yes | No | No |

**Overall verdict: NULL**

- **TX1** (primary, n_test=650, gateable): DM_HLN_t=1.002, p=0.317 — not significant. HAR-CJ lower QLIKE by ~2.6% but not statistically meaningful.
- **TX1 betas** (plausible after fix): cv_d=0.28, cv_w=0.43, cv_m=0.17; j_d=0.92, j_w=1.54, j_m=−3.33 (all |β|<10).
- **US ETFs** (non-gateable, n_train=26 < 200): OLS extrapolation territory. DM results unreliable; not counted toward H2.

### TX1 Jump Descriptives

- Jump frequency: 1.05% of trading days (23/2186 days)
- Raw J/RV share: 7.1% mean across all days
- After 3-sigma threshold: 0.24% mean J/RV (only true jump days)
- Jump threshold: 3.08e-05 (in squared log-return units)

---

## Interpretation

HAR-CJ does NOT significantly improve volatility forecasts over HAR-RV on TAIFEX TX1 under correct methodology. This is consistent with:
- **K1301** (HAR-RS/semivariance NULL on same TX1 data, DM_HLN=-0.91→1.29)
- **K868** (Day/Night decomposition NULL)

The pattern suggests TX1's 5-min volatility structure is well-captured by pooled HAR-RV without decomposition, potentially because TAIFEX's day session (08:45–13:45, 60 bars) has fewer microstructure jumps than US equity markets.

---

## References

- Barndorff-Nielsen & Shephard (2004) JBES — Power and bipower variation
- Andersen, Bollerslev & Diebold (2007) RFS — Roughing it up (HAR-CJ specification)
- Patton (2011) J. Econometrics — Proxy-robust loss functions (QLIKE)
- Harvey et al. (2016) — Multiple testing threshold |t|>3.0
- Corsi (2009) JFEC — HAR-RV baseline
- K1255 (this repo) — Intraday data infrastructure
- K1301 (this repo) — HAR-RS semivariance (NULL on TX1+SPY)
