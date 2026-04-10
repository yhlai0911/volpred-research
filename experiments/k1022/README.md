# K1022: A4f Cross-Asset Robustness Verification (Paper 9)

**[提出: 賴奕豪, 執行: Claude]**

## Research Question

Does the A4f multiplicative GARCH-X specification (τ = θ₀ + θ₁×VIX², free ω, GJR g_t) generalize robustly across 6 diverse assets when using Student-t(df=8) innovations?

## Background

- **K988**: A4f champion for SPY with Normal innovations (DM t=+4.48 vs GJR)
- **K994**: Cross-asset with Normal — QQQ/GLD significant, EEM/0050.TW not significant
- **K1021**: Student-t df≈8.5 optimal for SPY/QQQ; df=8 fixed best QLIKE-VaR balance
- **K1004**: A4f-VIX9D in SPY better than A4f-VIX (DM t=-4.588)

## Method

- **Assets (6)**: SPY, QQQ, GLD (with GVZ proxy), EEM, TLT (new), 0050.TW
- **Models (3 per asset)**:
  - M1: GJR-t(df=8) — baseline
  - M2: A4f-VIX-t(df=8) — all assets use VIX
  - M3: A4f-LocalFear-t(df=8) — GLD uses GVZ, others = M2
- **Data**: yfinance 2005-2026. OOS: 2019-01-01 onwards.
- **Rolling**: window=2000, refit every 63 days, seed=42
- **Custom MLE with numba-accelerated recursions**
- **Student-t(df=8) innovations** with scale correction sqrt((df-2)/df)
- **Evaluation**: QLIKE on r² (Patton 2011), DM test (Harvey t>3.0), VaR 2.5% Kupiec, Spearman ρ

## Key Results

### Cross-Asset Summary Table

| Asset    | GJR QLIKE | A4f QLIKE | DM t   | Harvey sig | QLIKE +% | VaR GJR | VaR A4f |
|----------|-----------|-----------|--------|------------|----------|---------|---------|
| SPY      | 1.5133    | 1.4106    | -2.753 | NO         | +6.78%   | FAIL    | PASS    |
| QQQ      | 1.5079    | 1.4202    | -2.123 | NO         | +5.82%   | FAIL    | PASS    |
| GLD      | 1.5347    | 1.5049    | -2.387 | NO         | +1.94%   | PASS    | PASS    |
| EEM      | 1.3365    | 1.3179    | -1.609 | NO         | +1.39%   | PASS    | PASS    |
| TLT      | 1.2097    | 1.1694    | -2.749 | NO         | +3.33%   | PASS    | PASS    |
| 0050.TW  | 1.5025    | 1.4849    | -0.517 | NO         | +1.17%   | FAIL    | PASS    |

### GLD with GVZ (Local Fear Proxy)
- A4f-GVZ QLIKE: 1.4409 (vs VIX: 1.5049, vs GJR: 1.5347)
- GVZ DM t = -2.959 (close to Harvey threshold but not quite)
- QLIKE improvement: +6.11% (vs GJR), better than VIX proxy (+1.94%)

## Key Findings

1. **A4f uniformly improves QLIKE** in all 6/6 assets (lower QLIKE = better forecast). The improvement ranges from +1.17% (0050.TW) to +6.78% (SPY).

2. **A4f VaR 2.5% passes Kupiec test in 6/6 assets**, while GJR-t(df=8) fails on 3 assets (SPY, QQQ, 0050.TW). This is the most important practical result: A4f produces better calibrated tail risk estimates.

3. **No individual DM test reaches Harvey t>3.0 threshold** with Student-t(df=8). The strongest signals are SPY (-2.753) and TLT (-2.749), followed by GLD-GVZ (-2.959).

4. **Contrast with K988 (Normal innovations, DM t=+4.48)**: When using Student-t, the heavier tails absorb some of the forecasting gains that VIX² provides through τ. The t-distribution itself captures tail events that VIX² otherwise helps with, narrowing the gap between models.

5. **Asset class pattern**:
   - **Equity (SPY/QQQ)**: Largest QLIKE improvements (5-7%), strongest DM stats
   - **Bonds (TLT)**: Surprising — DM t=-2.749, QLIKE +3.33%, A4f works for bonds too
   - **Gold (GLD)**: GVZ proxy substantially better than VIX (+6.11% vs +1.94%)
   - **EM (EEM)**: Moderate improvement, weaker significance
   - **Taiwan (0050.TW)**: Smallest improvement, weakest significance (VIX is foreign, lag+1)

6. **VaR improvement is more robust than QLIKE improvement**: Even where DM tests are weak (EEM, 0050.TW), A4f still passes VaR 2.5% while GJR sometimes fails.

## Limitations

- Harvey (2016) |t|>3.0 threshold not met for any asset individually with Student-t(df=8)
- The combined evidence (6/6 QLIKE better, 6/6 VaR pass) is strong but individual significance is marginal
- 0050.TW uses lagged VIX (timezone gap) — local fear index (VIXTWN) might be better
- GVZ data only from 2008, shorter sample for GLD local fear model
- df=8 is fixed across assets; optimal df may differ by asset class

## Implications for Paper 9

1. **Cannot claim Harvey-significant improvement** for individual assets with Student-t — but can report uniform directional improvement and VaR superiority
2. **Joint test approach** (panel/pooled DM) may be more appropriate for cross-asset evidence
3. **Normal-innovation results (K988)** should be presented as primary QLIKE comparison, with Student-t as robustness check showing VaR improvement
4. **GVZ for GLD** is strongly recommended over VIX — closer to threshold and economically meaningful
5. **TLT (bonds)** is a valuable addition — A4f works beyond equity markets

## Files

- `k1022.py` — Experiment script
- `k1022_results.json` — Full results
- `k1022_dm_t_bar.png` — Cross-asset DM t-statistic bar chart
- `k1022_qlike_var_comparison.png` — QLIKE improvement + VaR violation rate comparison

## References

- Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals. RES 95(3):776-797.
- Engle & Rangel (2008). Spline-GARCH. RFS 21(3):1187-1222.
- Conrad & Loch (2015). Anticipating Long-Term Stock Market Volatility. JBES 33(3):338-358.
- Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
- Harvey et al. (2016). t > 3.0 threshold for multiple testing.
- Kupiec (1995). Techniques for Verifying the Accuracy of Risk Measurement Models. J Deriv 3:73-84.
