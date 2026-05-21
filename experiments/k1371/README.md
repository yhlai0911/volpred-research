# K1371: HAR-RV-X — Financial Sector Lead as TSMC Volatility Predictor

**Status**: Complete | **Date**: 2026-05-17 | **Proposed by**: Claude (autonomous, from research_program.md line 341 + K757 finding)

## Motivation

K757 established a statistically significant Granger causality from Fubon Financial (2881.TW) to TSMC (2330.TW) volatility: F=6.11, p<0.001, over 2010-2026. This temporal precedence suggests that financial sector distress propagates to tech-sector volatility with a measurable lag.

**Research question**: Does this Granger lead translate into economically useful out-of-sample volatility forecasting improvement? Can HAR-RV augmented with financial-sector lagged variance (HAR-RV-X) beat the standard HAR-RV benchmark?

**Differentiation vs K757**:
- K757 tested Granger causality in returns (mean level) and return volatility
- K1371 tests whether financial-sector lagged variance improves HAR-RV **out-of-sample QLIKE** for TSMC daily RV
- K757 used full-sample VAR; K1371 uses rolling-expanding OOS estimation

**Literature basis**:
- Corsi (2009) HAR-RV model: heterogeneous autoregressive realized variance
- HAR-X extensions: Bekaert & Hoerova (2014), Bollerslev et al. (2016) — exogenous variables in HAR
- Cross-asset Granger → forecast improvement: standard in systemic risk literature

## Design

| Item | Setting |
|------|---------|
| Period | 2015-01-01 to 2025-12-31 |
| Assets | TSMC (2330.TW), Fubon Financial (2881.TW), Cathay Financial (2882.TW) |
| RV proxy | Squared daily log returns: RV_t = (log(P_t/P_{t-1}))^2 × 252 (annualized) |
| Train (IS) | 2015-01-02 to 2021-12-31 |
| Test (OOS) | 2022-01-01 to 2025-12-31 (4 years) |
| Estimation | OLS with Newey-West HAC SE (lags=22) per Patton & Sheppard (2009) |
| Seed | np.random.seed(42) |

### Models

| Model | Formula |
|-------|---------|
| **M0: HAR** | RV_t = β0 + β_d·RV_{t-1} + β_w·RV̄_{t-5,t-1} + β_m·RV̄_{t-22,t-1} + ε |
| **M1: HAR-X-d** | M0 + β_f·RV_Fubon_{t-1} |
| **M2: HAR-X-wm** | M0 + β_fw·RV̄_Fubon_{t-5,t-1} + β_fm·RV̄_Fubon_{t-22,t-1} |
| **M3: HAR-X-full** | M0 + Fubon daily+weekly+monthly lags |
| **M4: HAR-X-cat** | M0 + Cathay daily lag (separate test) |
| **M5: HAR-X-fin** | M0 + both Fubon daily + Cathay daily lag |

### Lookahead discipline

- All signals strictly shifted: t-1 for daily lag (ensures signal is from previous day's close)
- RV̄_{t-k,t-1} = mean of squared returns from t-k to t-1 (no t included)
- OOS estimation: expanding window (refit monthly to reduce compute)

### Evaluation metrics

- **QLIKE**: E[-log(σ²_hat) + RV/σ²_hat] — robust loss per Patton (2011)
- **MSE**: E[(σ²_hat - RV)²]
- **DM test**: Harvey, Leybourne & Newbold (1997) — HAR vs each M1-M5
- **MCS**: Model Confidence Set at 10% level if ≥4 models survive DM

### Hypotheses

| # | Hypothesis | Pass threshold |
|---|-----------|---------------|
| H1 | HAR-X-d (M1) improves OOS QLIKE vs HAR (M0) | DM p < 0.05, two-sided |
| H2 | Any HAR-X variant improves OOS QLIKE vs HAR | At least 1 of M1-M5 has DM p < 0.05 |
| H3 | Fubon better than Cathay | QLIKE(M1) < QLIKE(M4) |
| H4 | Financial sector leads significantly improve | Harvey t > 2 for best HAR-X |

## References

- Corsi (2009): "A simple approximate long-memory model of realized volatility" JFE
- Patton (2011): "Volatility forecast comparison using imperfect volatility proxies" JoE
- Harvey, Leybourne, Newbold (1997): DM test critical values
- Bekaert & Hoerova (2014): "The VIX, the variance premium and stock market volatility" JoE
- K757: Taiwan CoVaR + Granger causality (Fubon→TSMC F=6.11 p<0.001)

## Success criteria

- PASS: H1 or H2 satisfied (any financial-sector lag improves QLIKE with DM p<0.05)
- CONDITIONAL_PASS: Improvement present but DM p 0.05-0.15 (borderline)
- FAIL: No significant improvement (all DM p > 0.05) — null result documented

## Results

**OOS period**: 2022-01-01 to 2025-12-31, N=968 days

| Model | QLIKE | vs HAR | DM-t | p |
|-------|------:|-------:|-----:|---|
| M0: HAR (baseline) | 3.8710 | — | — | — |
| M1: HAR-X-d (Fubon daily) | 3.9232 | −1.35% | −3.839 | 0.0001 *** |
| M2: HAR-X-wm (Fubon w+m) | 3.8919 | −0.54% | −1.819 | 0.069 |
| M3: HAR-X-full (Fubon all) | 3.9027 | −0.82% | −2.488 | 0.013 * |
| M4: HAR-X-cat (Cathay daily) | 3.8663 | +0.12% | +0.350 | 0.726 |
| M5: HAR-X-fin (Fubon+Cathay) | 3.9718 | −2.60% | −2.763 | 0.006 ** |

*DM sign: negative = model_x WORSE than HAR; positive = model_x better.*

**Hypotheses**: 0/4 pass. **VERDICT: FAIL**

Striking finding: Adding Fubon daily lag (M1) **significantly hurts** TSMC vol forecasting (DM-t = −3.84, p < 0.001). This is the opposite direction of what K757's Granger finding would predict.

**Why the null?**
1. **Noise amplification**: daily squared returns as RV proxy are very noisy (σ⁴ term in squared return variance). Adding another noisy series compounds measurement error.
2. **Granger ≠ forecast improvement**: K757 found Granger causality in mean returns (VAR framework). Granger in means does not imply useful variance forecasting — the information channel may be in the level, not the volatility of Fubon.
3. **Overfitting risk**: the HAR-X models have more parameters. With noisy RV proxy, added parameters amplify estimation error in OOS expanding window.

**Only Cathay (M4) marginally improves** (+0.12% QLIKE), but with DM t = +0.35, p = 0.73 — completely non-significant.

**Research implication**: K757's Fubon→TSMC Granger causality is real but has no useful OOS volatility forecasting value. Cross-asset Granger does not → cross-asset vol predictability (at least not with daily squared-return RV proxy and HAR framework).

## Files

- `k1371.py` — main experiment script (Codex review: CONDITIONAL_PASS 2026-05-17)
- `k1371_results.json` — results with QLIKE, MSE, DM statistics, verdict
