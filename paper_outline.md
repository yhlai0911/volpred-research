# Paper Outline: Cross-Asset Volatility Forecasting and the Inverted Leverage Effect

## Working Title
**"Leverage Direction Matters: Cross-Asset Evidence on GARCH Model Selection, VaR Compliance, and Volatility Targeting"**

## Target Journals
- Journal of Banking & Finance (JBF)
- European Journal of Finance (EJFE)
- Journal of Empirical Finance

## Abstract (Draft — updated with new findings)
We conduct a comprehensive cross-asset analysis of GARCH-family volatility forecasting across 15 assets spanning equities, commodities, bonds, and cryptocurrency over 2017–2025. Our key contributions: (1) Gold's inverted leverage (t=-5.79 HAC) is **regime-dependent**—inverted during bull markets (fear-driven buying) but standard during bear markets (t=-4.71, p<0.0001). (2) The GJR-GARCH gamma t-statistic provides a significance-based model selection criterion that correctly classifies all 12 Diebold-Mariano tests across 6 assets. (3) Student-t VaR reduces violations by 21-48% (SPY 1/6→6/6 Green Zone), and fixed df=5 outperforms jointly estimated df (17 vs 24 violations). (4) VT effectiveness is independent of leverage direction (MaxDD improves for 7/7 assets, ρ=0.983 with base vol). (5) VIX/GARCH ratio > 1.5 identifies 94% of VaR violations (violation rate 4.6% vs 0.1% when ratio < 1.5).

## 1. Introduction
- Motivation: GARCH models widely used, but model selection across asset classes lacks systematic guidance
- Gap: Leverage effect assumed to be universal (negative returns → higher vol), but not verified cross-asset
- Contribution 1: Systematic cross-asset leverage direction framework — formal hypothesis testing (t=-8.30 for gold) and taxonomy linking γ sign to economic role. Extends Chevallier & Ielpo (2017) from commodity-only to multi-asset-class comparison
- Contribution 2: Leverage direction > skewness for model selection — gold has skew=-0.30 but γ<0, showing skewness is misleading
- Contribution 3: Student-t distribution is the primary VaR improvement factor (attribution analysis)
- Contribution 4: VT effectiveness is independent of leverage direction

## 2. Literature Review
- GARCH family: Bollerslev (1986), Nelson (1991) EGARCH, Glosten et al. (1993) GJR
- Leverage effect: Black (1976), Christie (1982), Engle & Siriwardane (2014) Structural GARCH
- Gold volatility: Baur & McDermott (2010) safe haven, Batten et al. (2010) gold vol dynamics
- Commodity asymmetry: Chevallier & Ielpo (2017) RIBF — inverted leverage in gold, wheat, coffee, cocoa
- VaR: McNeil et al. (2015) QRM, Basel III framework
- Volatility targeting: Moreira & Muir (2017), Harvey et al. (2018)
- Gap: No systematic cross-asset study of leverage direction and its implications

## 3. Data and Methodology

### 3.1 Data
- Assets: SPY, QQQ, GLD, TLT, BTC-USD (primary), EEM, SLV (supplementary), JO, WEAT, UNG, USO, DBA, NIB, PPLT (commodity extension)
- Period: 2017–2026 (IS: 2017–2019, OOS: 2020–2025)
- Frequency: Daily returns
- Source: Yahoo Finance

### 3.2 Models
- GARCH(1,1): σ²_t = ω + α ε²_{t-1} + β σ²_{t-1}
- GJR-GARCH(1,1): σ²_t = ω + (α + γ I_{t-1}) ε²_{t-1} + β σ²_{t-1}
- Window: 504 trading days (rolling re-estimation)
- Distribution: Normal, Student-t (estimated df), GED

### 3.3 Evaluation
- Statistical: QLIKE (primary), MSE, MAE, R²-log
- Diebold-Mariano test for significance
- VaR backtesting: Kupiec (unconditional), Christoffersen (independence)
- Basel III zone classification

### 3.4 Leverage Direction Analysis
- Rolling gamma estimation (quarterly, w=504)
- Stability metrics: mean, std, sign consistency
- Correlation with return characteristics

## 4. Empirical Results

### 4.1 Data Characteristics
- Table 1: Descriptive statistics (returns, skewness, kurtosis, JB test, ARCH LM)
- SPY/QQQ: negative skew, high kurtosis
- GLD: negative skew BUT inverted leverage
- TLT: near-zero skew, low kurtosis
- BTC: near-zero skew, extreme kurtosis

### 4.2 Leverage Direction Across Assets
- Table 2: GJR gamma estimates (multiple windows, rolling stability)
- Figure 1: Rolling gamma time series (2007–2026 for SPY, 2017–2026 for others)
- Key finding: γ sign is asset-class specific and temporally stable
  - Equities (SPY, QQQ): γ > 0 (standard), range 0.06–0.50
  - Gold (GLD): γ < 0 (inverted), range -0.15 to -0.01
  - Bonds (TLT): γ ≈ 0 (neutral)
  - Crypto (BTC): γ > 0 (mild standard)

### 4.3 Model Selection: Gamma Direction vs Skewness
- Table 3: GARCH vs GJR QLIKE comparison across assets
- DM test results: GJR significantly better only when γ > 0.05
- GLD: DM p=0.87 (2023-2024), p=0.25 (2025) — no difference
- Proposition: Use γ direction, not skewness, for model selection
  - GLD has skew=-0.645 but γ<0 → GARCH sufficient (DM confirmed)

### 4.4 VaR Compliance: Student-t Attribution
- Table 4: Annual Basel III VaR violations (2020–2025, 6 years)
- Attribution decomposition:
  - Normal → Student-t: -45.5% violations (biggest factor)
  - + Adaptive threshold: -33.3%
  - + Jump augmentation: +0% (redundant)
- Cross-asset VaR results: 5 assets × 7 years
  - SPY: 7/7 Green, QQQ: 6/7, GLD: 6/7, TLT: 7/7, BTC: 6/7
- Practical implication: Use estimated Student-t df, not complex adjustments

### 4.5 Volatility Targeting Across Leverage Regimes
- Table 5: VT performance (BH vs VT, multiple assets and periods)
- Figure 2: Cumulative returns BH vs VT
- VT Sharpe improvement: +10-15% across all assets regardless of γ direction
- SPY VT: Sharpe 0.61 (16 years)
- GLD VT: Sharpe 0.62 (16 years)
- Anti-VT (GLD): Sharpe 1.51 (4 years, but 1.51 < VT 1.71)
- MaxDD improvement: 10pp across assets

### 4.6 Robustness
- Cross-OOS periods (2022-2023, 2023-2024, 2025)
- Window size sensitivity (252, 504)
- Distribution sensitivity (Normal, Student-t, GED)
- The daily-frequency GARCH ceiling (QLIKE ≈ -9.034, Ljung-Box confirms iid residuals)

## 5. Discussion

### 5.1 Why Gold Has Inverted Leverage
- Safe-haven effect: gold rallies during market stress (Baur & McDermott 2010)
- Fear-driven buying → high uncertainty → high volatility
- Opposite of equity "leverage effect" (debt-to-equity ratio mechanism)
- Not a statistical artifact: stable over 12+ quarters

### 5.2 Practical Implications
- Model selection: check γ direction before choosing GJR vs GARCH
- VaR: Student-t distribution is the "low-hanging fruit" — more impactful than fancy adjustments
- Volatility targeting: works universally regardless of leverage direction
- Risk management: GLD VaR may underperform during flash crashes (Jan 2026, -10.27%)

### 5.3 Limitations
- Daily frequency only (intraday/tick data may reveal different patterns)
- 5 assets (could expand to commodities, FX, emerging markets)
- VT performance sensitive to bull/bear market conditions
- Student-t df assumed constant within estimation window

## 6. Conclusion
- Leverage direction is asset-class specific and stable
- GJR-GARCH should only be used when γ is consistently positive
- Student-t VaR is the simple, effective solution for Basel III compliance
- Volatility targeting improves risk-adjusted returns by 10-15% across all leverage regimes

## Tables and Figures
1. Table 1: Descriptive statistics
2. Table 2: Cross-asset gamma estimates and stability
3. Table 3: GARCH vs GJR QLIKE + DM tests
4. Table 4: Annual Basel III VaR violations (attribution)
5. Table 5: VT performance comparison
6. Figure 1: Rolling gamma time series
7. Figure 2: Cumulative returns (BH vs VT)
8. Figure 3: VaR violation attribution waterfall

## Data Availability
- All data from Yahoo Finance (reproducible)
- Code available on request
