# K1116: Alternative Data (EPU + NFCI + STLFSI) for SPY Vol Prediction — NULL

## Motivation (WHY)

**Original brief**: Test Google Trends as alternative data for SPY vol prediction — "this time vol prediction, not return prediction, may differ".

**Step -1/0/1 prechecks uncovered**:
- **K473 (Jan 2026)**: Google Trends attention → vol: NULL (OOS QLIKE worse than VIX+RV).
- **K750 (Mar 2026)**: REAL pytrends 5 fear terms → vol: NULL. IS partial r|VIX=0.271 but OOS DM t=0.669 Harvey FAIL. Cross-OOS 1/5. Fear LAGS VIX at lag=-1.
- **K789 (Apr 2026)**: Google Trends → return + tail: NULL.
- **K192**: Google Trends overfitting warning.
- **pytrends hit 429 rate limit** on first call — and per K789 lesson, any VIX-proxy substitute = circular.

Running Google-Trends-for-vol again would replicate K750 → E060 violation ("接受方向已死，不要繼續加 variant").

**Pivot (per brief fallback)**: "若 pytrends 無法用 → 用替代：FRED Sentiment Index". Chose **genuinely novel, not-yet-tested-for-SPY-vol alternative data from FRED**:
- `USEPUINDXD` — US Economic Policy Uncertainty (daily, Baker/Bloom/Davis 2016 QJE)
- `WLEMUINDXD` — World EPU (daily)
- `NFCI` — National Financial Conditions Index (weekly, Chicago Fed)
- `ANFCI` — Adjusted NFCI (weekly)
- `STLFSI4` — St. Louis Fed Financial Stress Index (weekly)

Knowledge base search shows **no prior SPY-weekly-vol test using EPU or NFCI** (K504 tested STLFSI4 narrow, returned null in different setup).

## Data

- Source: yfinance (SPY, ^VIX) + FRED (USEPUINDXD, WLEMUINDXD, NFCI, ANFCI, STLFSI4)
- Period: 2018-01-12 to 2026-04-10 (431 weeks)
- IS: 2018-01-12 to 2022-12-30 (n=260)
- OOS: 2023-01-06 to 2026-04-10 (n=170, common index after lag)
- Target: SPY weekly realized vol (√Σr²_daily within W-FRI week, ≥4 obs)
- All signals **lagged by 1 week** (signal_t−1 predicts vol_t) — no lookahead by code construction (`shift(1)`).

### IS Lag-1 correlations with RV (for context)
| Signal | r |
|--------|---|
| USEPU | 0.269 |
| WLEMU | 0.573 |
| NFCI | 0.582 |
| ANFCI | 0.553 |
| STLFSI | 0.621 |
| **VIX_mean** | **0.677** |

VIX has the highest unconditional correlation with next-week RV. FinStress (STLFSI, NFCI) are in the 0.55-0.62 range — genuinely informative but less than VIX.

## Models

| M | Specification |
|---|---------------|
| M1_AR1 | AR(1) on RV |
| M2_AR1_VIX | + VIX_lag1 (baseline) |
| M3_AR1_EPU | + USEPU_lag1 + WLEMU_lag1 |
| M4_AR1_FinStress | + NFCI, ANFCI, STLFSI (lag1) |
| M5_AR1_All | All above combined (7 regressors) |

OLS estimation on IS; static coefficients for OOS forecasting. AR(1) model is fair proxy for GARCH mean equation given weekly-aggregated RV target.

## Evaluation

- **QLIKE** loss (Patton 2011, proxy-robust)
- **DM-HLN** test (Harvey 1997 correction, h=1)
- Harvey threshold: |t| > 2.0
- Regime partition: calm (VIX<18), normal (18≤VIX<25), stress (VIX≥25), transition (VIX_{t-1}<18 ∧ VIX_t≥22)
- Sub-period stability: 2023, 2024, 2025 each
- Keyword-level: BH-adj p-values on alt-data regressors in M5 (α=0.10)

## Results

### IS vs OOS QLIKE

| Model | IS R² | IS QLIKE | OOS QLIKE | OOS RMSE |
|---|---|---|---|---|
| M1_AR1 | 0.532 | -2.85 | -3.05 | 0.0105 |
| **M2_AR1_VIX** (baseline) | **0.545** | **-2.86** | **-3.06** | **0.0101** |
| M3_AR1_EPU | 0.545 | -2.85 | -3.04 | 0.0122 |
| M4_AR1_FinStress | 0.555 | -2.86 | -3.04 | 0.0110 |
| M5_AR1_All | 0.595 | -2.84 | **+59.91** ⚠️ | 0.0121 |

**Two red flags**:
1. **M5 catastrophic overfit**: IS QLIKE=-2.84 → OOS QLIKE=+59.9. K1100g_d1 IS-OOS-divergence trap caught live. The 6-regressor model degenerates OOS. Classic overfit.
2. **Alt-data-only models worse OOS than VIX alone**: M3 and M4 OOS QLIKE = -3.04 vs baseline -3.06 (alt-data models are worse by 0.02 QLIKE).

### Full OOS DM-HLN tests (vs M2_AR1_VIX baseline)

positive t = challenger beats baseline; negative t = baseline beats challenger

| Challenger | t-stat | p | Verdict |
|---|---|---|---|
| M1_AR1 (no VIX) | -3.021 | 0.003 | **baseline wins** |
| M3_AR1_EPU | **-2.554** | 0.012 | **baseline wins** |
| M4_AR1_FinStress | **-3.001** | 0.003 | **baseline wins** |
| M5_AR1_All | -1.008 | 0.315 | ns (M5 noisy due to overfit) |

**Active negative evidence**: 2 of 3 pure-alt-data challengers significantly LOSE to VIX baseline (Harvey |t|>2). Not just "null" — alt-data **actively hurts** OOS QLIKE.

### Regime-conditional DM (the new angle vs K750)

| Regime | n | EPU vs VIX | FinStress vs VIX | All vs VIX |
|---|---|---|---|---|
| **calm** (VIX<18) | 111 | t=-2.57 (baseline wins) | t=-3.92 (baseline wins) | t=-1.00 ns |
| normal (18≤VIX<25) | 50 | t=-1.56 ns | t=+0.34 ns | t=-1.49 ns |
| stress (VIX≥25) | 9 | (insufficient n) | — | — |
| transition | **0** | — | — | — |

**Key finding**: The 2023-2026 OOS period had ZERO calm→stress transitions meeting our definition (VIX_{t-1}<18 ∧ VIX_t≥22). The post-2022 regime was structurally low-vol, preventing test of H1-regime (transition edge). Partial test: in calm regime (n=111) alt-data is clearly WORSE than VIX.

### Sub-period stability (annual)

No year shows any alt-data model beating VIX at |t|>2. H3 FAIL.

### In-Sample significance (BH-adj, M5)

Sign pattern contradictions for same underlying construct:
| Regressor | Coef | Raw p | BH p | Sign |
|---|---|---|---|---|
| USEPU | -6.3e-5 | 0.000 | 0.000 | **negative** |
| WLEMU | +3.4e-5 | 0.105 | 0.132 | positive (ns) |
| NFCI | +0.045 | 0.001 | 0.003 | **positive** |
| ANFCI | -0.031 | 0.017 | 0.028 | **negative** |
| STLFSI | +4.1e-4 | 0.850 | 0.850 | ns |

3 of 5 BH-significant at α=0.10 (H2 PASS) BUT signs contradict intuition and each other: USEPU negative (higher uncertainty → lower next-week vol??), WLEMU positive, NFCI positive, ANFCI negative despite measuring similar conditions. This sign inconsistency is a classic symptom of **multicollinearity** in a joint model (EPU-WLEMU corr, NFCI-ANFCI corr both >0.8) — not robust incremental information.

### Hypothesis verdict

| Hypothesis | Result |
|---|---|
| H1-base: alt-data beats VIX on full OOS | **FAIL** (baseline wins 2 of 3) |
| H1-regime: alt-data beats VIX in transition/stress | **UNTESTABLE** (n=0 transition, n=9 stress) + **FAIL in calm** |
| H2: ≥2 alt-data regressors BH-sig in IS M5 | PASS (3/5) — but sign contradictions indicate multicollinearity artifact, not robust signal |
| H3: 2+ of 3 sub-years stable | FAIL |
| QLIKE improvement >5% | FAIL (-0.62%) |
| Triple-gate (DM + QLIKE + stability) | FAIL |

**OVERALL: NULL — alt-data (EPU + NFCI + STLFSI) actively worsens OOS vol prediction vs VIX baseline.**

## Conclusion

**Another VIX-sufficiency confirmation (now #37+)**: news-based uncertainty (EPU) and financial-stress indices (NFCI, STLFSI) contain real information about current conditions (IS correlation 0.27-0.62 with next-week RV), but they add **negative value** on top of VIX for weekly SPY vol prediction. Two specific findings:

1. **Active harm**: Pure alt-data models lose to VIX-only baseline by Harvey-significant DM (|t|>2.5). This is stronger negative evidence than K750 (which was merely ns).
2. **Calm-regime degradation**: Even in calm markets where one might expect alternative signals to matter more (since VIX is stable), alt-data is worse by t=-2.6 (EPU) and t=-3.9 (FinStress).

**Combined with K473/K750/K789/K504**: any reasonable alternative-data fear/sentiment proxy for **weekly vol of SPY** is either null or actively worse than VIX. The VIX sufficient-statistic result is robust across:
- Survey-based (UMich)
- Search-volume based (Google Trends)
- News-text-based (EPU)
- Balance-sheet/rate-based (NFCI, STLFSI)

**Limitation note (per research-honesty principle 10)**:
- OOS window 2023-2026 had zero calm→stress transitions meeting strict threshold — the "transition edge" hypothesis remains formally untestable here.
- Static-coefficient OLS (not full GARCH-X). K750's analogous static-regression setup also concluded NULL, so methodology choice is unlikely to flip the verdict, but this is not ruled out.
- Weekly aggregation; daily high-frequency test may differ (but VIX also available daily so this mostly inflates n).

## Derived directions (to add to research_program.md)

1. **Stress-period high-frequency test**: Re-test EPU/NFCI at DAILY frequency conditional on VIX jump days (VIX_t − VIX_{t-1} > 2σ). Possibly alt-data adds information specifically at the **JUMP** vs the steady-state. This requires a rare-event design (matched-pair over VIX jumps) — not a full-sample regression.

2. **Cross-asset alt-data sufficiency**: Run the same 5 FRED alt-data series on GLD / TLT / Bitcoin / TAIFEX. The result here is SPY-specific. For Bitcoin and TAIFEX, VIX is less directly relevant, and retail-attention / news-uncertainty may have a structurally larger incremental role.

3. **"Sign-flip event" detector**: The USEPU negative sign in the joint model is anomalous (raw +ve unconditional corr 0.27 but in joint model conditional on VIX/NFCI it flips negative). This is econometric — but a focused study of "what does USEPU pick up ONCE NFCI is already in the model?" could be a narrow contribution (partial-effect paper, not headline vol improvement).

## Worktree notes

- Files are all within `experiments/k1116/`
- No shared-state writes (preamble rule 8 respected)
- Main thread responsible for knowledge.json entry + article, not this worktree

## References

- Baker, S. R., Bloom, N., & Davis, S. J. (2016). Measuring economic policy uncertainty. *QJE*, 131(4), 1593-1636.
- Brave, S., & Butters, R. A. (2011). Monitoring financial stability: A financial conditions index approach. *Chicago Fed EP*, Q1.
- Kliesen, K. L., & Smith, D. C. (2010). Measuring financial market stress. *St. Louis Fed Synopses*, (2).
- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160(1), 246-256.
- Harvey, D., Leybourne, S., & Newbold, P. (1997). Testing the equality of prediction mean squared errors. *International Journal of Forecasting*, 13(2), 281-291.

## Files

- `k1116.py` — experiment script (main)
- `k1116_plots.py` — chart generation
- `k1116_results.json` — full results JSON
- `k1116_is_vs_oos_qlike.png` — IS/OOS QLIKE + M5 overfit annotation
- `k1116_dm_tstats.png` — DM-HLN t-stats full OOS + calm regime
- `k1116_bh_significance.png` — BH-adj p-values per alt-data regressor
- `run.log` — execution log
- `references/` — (empty — all citations in this README)
- `data/` — (empty — all data pulled live from yfinance + FRED)
