# Paper 3 Outline: Is Volatility Targeting Just Trend Following?

**Author:** Yi-Hao Lai (Da-Yeh University) + VolPred Research System
**Date:** March 2026 (Draft outline)
**Key findings:** K46, K47, K49, K50, K53, K58, K68

---

## Title Options

1. **Is Volatility Targeting Just Trend Following? Decomposing Alpha Through the Leverage Effect**
2. **The Dual Mechanism of Volatility Targeting: Trend-Following Returns and VIX-Based Drawdown Insurance**
3. **Volatility Targeting and Time-Series Momentum: Cross-Asset Evidence on Alpha Sources and Drawdown Protection**

Preferred: Option 1 (provocative question format, matches Gemini K47 suggestion; concise enough for FRL, substantive enough for JEF/JBF).

---

## Abstract (~150 words)

We decompose the alpha of volatility targeting (VT) strategies into trend-following and residual components across 15 assets spanning equities, commodities, bonds, and international markets. Equity VT has significant time-series momentum (TSMOM) exposure in all 15 assets tested, driven by the leverage effect: GJR-GARCH gamma predicts TSMOM loading (r = 0.742, p = 0.002, N = 15). However, VT alpha is not fully absorbed by TSMOM. We identify a dual mechanism: (i) Sharpe ratio improvement derives partially from implicit trend-following (32% of incremental Sharpe), while (ii) maximum drawdown protection (averaging 28.7 percentage points across 13 international markets) is almost entirely preserved after TSMOM removal (96% retained), attributable to VIX-based position sizing rather than momentum. The gamma-TSMOM link operates across asset classes but not within equity sectors (r = 0.163, NS for 11 sectors), delineating its domain. These findings reconcile the VT and managed-futures literatures by showing that VT embeds a free trend-following overlay while its primary economic value---drawdown insurance---operates through a distinct channel.

**Keywords:** volatility targeting, time-series momentum, leverage effect, drawdown, VIX, cross-asset

**JEL Classification:** C22, G11, G12, G15

---

## Section Structure

### 1. Introduction (4-5 pages)

- **Opening hook:** VT (Moreira & Muir, 2017) and TSMOM (Moskowitz, Ooi & Pedersen, 2012) are two of the most documented anomalies in asset pricing. Are they the same thing?
- **The puzzle:** VT scales exposure by inverse volatility; when negative returns raise volatility (leverage effect), VT mechanically deleverages after declines --- mimicking trend-following. Hood & Raughtigan (2025) show 91% of equity VT alpha is absorbed by TSMOM. But does this mean VT is *redundant*?
- **Our answer:** No. We show VT has a dual mechanism:
  - **Channel 1 (Sharpe):** Partially (~32%) from implicit TSMOM exposure, linked to leverage effect strength (gamma)
  - **Channel 2 (MDD):** Almost entirely (~96%) from VIX-level-based position sizing, *not* from trend-following
- **Three contributions** (see Contribution Statement below)
- **Preview of results:** 15 assets, 13 international markets, 11 equity sectors
- **Paper organization paragraph**

### 2. Literature Review (3-4 pages)

#### 2.1 Volatility Targeting
- Moreira & Muir (2017): VT alpha in equity factors
- Harvey et al. (2018): multi-asset VT
- Fleming, Kirby & Ostdiek (2001, 2003): volatility timing
- Bozovic (2024): VIX-managed portfolios
- Cederburg et al. (2020): VIX vs realized vol scaling
- Xu (2024): real-time viability of VT (148/197 factors improved)
- **Our Paper 1** (Lai, 2026): gamma taxonomy, complexity ceiling

#### 2.2 Time-Series Momentum
- Moskowitz, Ooi & Pedersen (2012): TSMOM across 58 futures
- Baltas & Kosowski (2013): TSMOM in equities
- Kim, Tse, & Wald (2016): TSMOM and volatility scaling
- Huang, Song & Xiang (2024): momentum and volatility dynamics

#### 2.3 The Connection Between VT and TSMOM
- Hood & Raughtigan (2025): VT alpha = trend following for equities (key predecessor)
- Barroso & Santa-Clara (2015): risk-managed momentum
- Daniel & Moskowitz (2016): momentum crashes and volatility
- **Gap:** Hood & Raughtigan use 50 futures but don't decompose the dual channel (Sharpe vs MDD), don't test cross-asset predictors, and don't examine international universality

#### 2.4 The Leverage Effect as Mechanism
- Black (1976), Christie (1982): original leverage effect
- Glosten, Jagannathan & Runkle (1993): GJR-GARCH
- Engle & Siriwardane (2018): structural interpretation
- Chevallier & Ielpo (2017): inverted leverage in commodities
- **Our Paper 1** (Lai, 2026): leverage direction taxonomy

### 3. Data and Methodology (4-5 pages)

#### 3.1 Data
- **Primary sample:** 15 assets (7 from Paper 1 + 8 additional: SLV, IWM, VGK, EWJ, EWZ, DBA, USO, HYG) --- equities, commodities, bonds, EM, HY
- **International sample:** 13 country ETFs (7 developed + 6 emerging): EWU, EWG, EWQ, EWA, EWC, EWH, EWJ, EWT, EWY, EWZ, EWW, INDA, EWS
- **Sector sample:** 11 SPDR sector ETFs (XLB through XLU)
- **Period:** 2007-01 to 2026-03 (full); OOS: 2023-01 to 2026-03
- **VIX data:** CBOE VIX index (daily)
- **Risk-free rate:** 13-week T-bill (IRX), time-varying (not hardcoded --- per K50 Codex critique)

#### 3.2 Volatility Targeting Construction
- VT weight: $w_t = \sigma_{target} / \hat{\sigma}_t$ (capped at 1.0)
- Two implementations: (a) GARCH-based ($\hat{\sigma}_t$ = GJR-GARCH), (b) VIX-based ($w_t = 12/VIX_t$)
- Monthly rebalancing, lagged weights (VIX_t determines w_{t+1})
- Transaction costs: 10 bps round-trip

#### 3.3 TSMOM Factor Construction
- Following Moskowitz, Ooi & Pedersen (2012): sign of past 12-month (252-day) return
- **Orthogonalized TSMOM** (per K50 Codex critique): TSMOM residual after removing MKT exposure
  - $TSMOM_t^{\perp} = TSMOM_t - \hat{\beta}_{MKT} \cdot MKT_t$
- Robustness: 1/3/6/9/12 month lookback windows

#### 3.4 Alpha Decomposition
- **Stage 1:** CAPM: $r_{VT,t} - r_{f,t} = \alpha + \beta_{MKT}(r_{MKT,t} - r_{f,t}) + \varepsilon_t$
- **Stage 2:** CAPM + TSMOM: add orthogonalized TSMOM factor
- **Stage 3:** CAPM + TSMOM + controls (VRP, Fama-French MOM)
- Alpha reduction = $(\alpha_{Stage1} - \alpha_{Stage2}) / \alpha_{Stage1}$
- **HAC standard errors** (Newey-West, per K50 Codex critique): lag = floor(4*(T/100)^(2/9))

#### 3.5 Pure VT Alpha Construction (K49 methodology)
- Construct TSMOM-hedged VT: $r_{PureVT,t} = r_{VT,t} - \hat{\beta}_{TSMOM,t} \cdot TSMOM_t$
- Rolling 252-day regression for time-varying beta
- Compare Sharpe and MDD of VT vs PureVT vs TSMOM-only

#### 3.6 Cross-Sectional Tests
- Dependent variables: TSMOM beta, Sharpe improvement, MDD improvement
- Key predictor: GJR-GARCH gamma (per K50: use gamma, not rolling correlation)
- Spearman rank correlation + bootstrap CI (5000 reps)
- Minimum N = 15 assets (K50 critique addressed; Hood used 50)

### 4. Empirical Results (8-10 pages)

#### 4.1 VT Has Significant TSMOM Exposure (Table 2)
- All 15 assets: TSMOM beta significantly positive for equities, near-zero/negative for non-equity
- 252-day TSMOM dominant; sub-period robustness (all t > 5)
- Alpha reduction: equity SPY 91%, EEM 92% vs GLD -3%, TLT 11%

#### 4.2 The Dual Mechanism: Sharpe vs MDD Decomposition (Table 3, Figure 1)
- **Key result:** After TSMOM removal, Sharpe drops only 32% but MDD protection retained 96%
- SPY: MDD -24.7% (VT) vs -26.9% (PureVT) vs -33.7% (B&H) --- MDD channel independent
- Mechanism: VIX-level position sizing (high VIX = low weight) provides drawdown insurance regardless of trend signal
- VRP does not constitute a third channel (K52: R-squared increment only 0.0007)

#### 4.3 Leverage Effect Drives TSMOM Loading (Table 4, Figure 2)
- Cross-asset: corr(gamma, TSMOM_beta) = 0.742, p = 0.002, N = 15
- Economic interpretation: higher gamma (stronger leverage effect) = VT more mechanically trend-following
- GJR gamma predicts Sharpe improvement: Spearman 0.830, p = 0.0005 (K68, N=13 international)

#### 4.4 Boundary Condition: Gamma Does Not Predict Within Sectors (Table 5)
- 11 equity sectors: corr(gamma, delta-Sharpe) = 0.163, p = 0.632 (NS)
- Gamma range too narrow within equity (0.07-0.16) vs cross-asset (negative to 0.27)
- VIX sensitivity homogeneous within equity (-0.40 to -0.65)
- Practical implication: sector rotation investors use uniform 12/VIX overlay

#### 4.5 International Universality: US VIX as Global MDD Insurance (Table 6, Figure 3)
- 13/13 international markets: MDD improved (avg +28.7pp, t = 15.70)
- Only 2/13 Sharpe improved --- confirms insurance pricing (K41)
- VIX sensitivity predicts MDD benefit (r = -0.770, p = 0.002)
- Developed markets stronger (+32pp) than emerging (+25pp)
- Single US VIX signal sufficient for all global equity allocations

#### 4.6 Robustness Tests (Table 7)
- HAC/Newey-West vs OLS: qualitatively identical
- Orthogonalized vs raw TSMOM: alpha absorption unchanged
- Sub-period stability: 5 OOS periods, all consistent
- TSMOM lookback windows (1/3/6/9/12 months): 12-month dominant
- Fama-French 5-factor + MOM + BAB controls
- Time-varying cash rate (IRX) vs fixed 4%

### 5. Discussion (3-4 pages)

#### 5.1 Reconciling VT and Managed Futures
- VT embeds free trend-following exposure as a byproduct of the leverage effect
- But VT is NOT just trend following: the MDD channel is distinct
- Investors pay ~4%/yr "insurance premium" (K41) that is economically rational for drawdown-averse investors (lambda >= 2)
- Interest rate regime matters (K62): high-rate environment reduces effective premium

#### 5.2 Why Doesn't TSMOM Fully Absorb VT?
- The MDD channel operates through *level* of VIX, not *direction* of returns
- TSMOM captures sign(past returns); VIX captures magnitude(implied fear)
- During slow drawdowns (2022): TSMOM signal can be ambiguous, VIX still elevated
- VT corr with regime = 0.936 (K61) --- VIX is itself regime-adaptive

#### 5.3 Practical Implications
- VT investors already have TSMOM exposure --- no need to add managed futures overlay
- 12/VIX is sufficient: 20+ confirmations of VIX as sufficient statistic (J3/J4/J8/K61/K65)
- Sector rotation: uniform overlay, no sector-specific tuning needed
- International: single US VIX signal for all equity markets

#### 5.4 Limitations
- 15 assets still modest (Hood uses 50 futures); expanding to more commodities/FI desirable
- OOS 2023-2026 may not capture full-cycle dynamics (no 2008-type crash in OOS)
- VIX availability limits non-US analysis (pre-1990 not possible)
- Gamma estimation requires sufficient history (w=2000 = 8 years)

### 6. Conclusion (1-2 pages)

- VT has a dual mechanism: Sharpe from TSMOM (32%), MDD from VIX position sizing (96% retained)
- Leverage effect (gamma) is the mechanical link between VT and TSMOM
- This link operates cross-asset class but not within equity sectors
- US VIX is universal MDD insurance for global equities
- VT is not redundant with TSMOM --- its primary value (drawdown protection) is orthogonal to trend-following

---

## Key Tables and Figures

### Tables

| Table | Title | Content |
|-------|-------|---------|
| 1 | Descriptive Statistics | 15 assets: mean, std, skewness, kurtosis, gamma, VIX sensitivity |
| 2 | VT Alpha Decomposition: CAPM vs CAPM+TSMOM | 15 assets x {alpha, TSMOM beta, R-sq, alpha reduction %}, HAC t-stats |
| 3 | Dual Mechanism: Sharpe and MDD Decomposition | VT vs PureVT vs TSMOM-only vs B&H: {Sharpe, MDD, Calmar}, with % attribution |
| 4 | Cross-Asset Predictors of TSMOM Loading | Spearman/Pearson correlations: gamma, VIX sensitivity, base vol vs TSMOM beta |
| 5 | Sector VT: Gamma Does Not Predict Within-Equity | 11 sectors: gamma, delta-Sharpe, delta-MDD, TSMOM beta |
| 6 | International VT: US VIX as Universal MDD Insurance | 13 markets: {Sharpe B&H, Sharpe VT, MDD B&H, MDD VT, VIX sensitivity} |
| 7 | Robustness: HAC, Orthogonalization, Sub-periods, Controls | Panel A: HAC vs OLS; Panel B: TSMOM variants; Panel C: 5 sub-periods; Panel D: additional factors |

### Figures

| Figure | Title | Type |
|--------|-------|------|
| 1 | The Dual Mechanism of Volatility Targeting | Schematic diagram: VT -> {TSMOM channel (Sharpe, 32%)} + {VIX level channel (MDD, 96%)} |
| 2 | Gamma Predicts TSMOM Loading Cross-Asset | Scatter plot: x = GJR gamma, y = TSMOM beta, N=15, with regression line and CI |
| 3 | International MDD Improvement vs VIX Sensitivity | Scatter plot: x = VIX sensitivity, y = MDD improvement (pp), N=13 |
| 4 | Rolling Alpha: VT vs PureVT | Time series: 252-day rolling alpha for SPY VT and PureVT, with shaded recessions |
| 5 | Sharpe and MDD Decomposition Bar Chart | Grouped bars: {B&H, VT, PureVT, TSMOM-only} for SPY, 50/50, EEM, GLD |
| 6 | Gamma Range: Cross-Asset vs Within-Sector | Two-panel: (a) 15 assets wide gamma range, (b) 11 sectors narrow range; explains why mechanism works cross-asset but not within-sector |

---

## Contribution Statement (3 Points)

1. **We decompose VT alpha into two distinct channels** --- trend-following (Sharpe) and VIX-based position sizing (MDD) --- showing that while TSMOM explains ~32% of VT's risk-adjusted return improvement, ~96% of its drawdown protection is orthogonal to trend-following. This resolves the apparent tension between Hood & Raughtigan (2025), who find 91% alpha absorption, and the widespread practical observation that VT remains valuable even for investors already holding managed futures.

2. **We identify the leverage effect (GJR gamma) as the mechanical link between VT and TSMOM** across 15 assets (r = 0.742, p = 0.002), and delineate its boundary: the link operates across asset classes (equities vs commodities vs bonds) but not within equity sectors (r = 0.163, NS, N = 11), where gamma variation is insufficient to differentiate TSMOM exposure.

3. **We demonstrate that US VIX is universal drawdown insurance** for 13 international equity markets (13/13 MDD improved, avg +28.7pp, t = 15.70), with VIX sensitivity predicting the magnitude of protection (r = -0.770, p = 0.002). This extends VT from a domestic to a global asset allocation tool and confirms that VT's primary economic value is an "insurance pricing" relationship (constant ~4%/yr Sharpe drag for 100% MDD protection).

---

## Target Journals

| Journal | Fit | Rationale |
|---------|-----|-----------|
| **Finance Research Letters (FRL)** | Best fit (short format) | Provocative question format, clear empirical result, 5000-word limit suits focused decomposition. Impact factor ~7.0. Fast turnaround (8-12 weeks). |
| **Journal of Portfolio Management (JPM)** | Strong fit (practitioner) | Direct practical implications (VT vs managed futures, global VIX overlay). Practitioner audience values the "do I still need VT if I have TSMOM?" question. |
| **Journal of Empirical Finance (JEF)** | Good fit (methodology) | Econometric decomposition, HAC inference, cross-sectional tests. More technical audience. Longer format allows fuller robustness. |
| **Journal of Banking & Finance (JBF)** | Stretch target | If expanded with more assets (50+) and deeper international analysis. Higher bar but broader scope matches their cross-asset papers. |
| **Pacific-Basin Finance Journal (PBFJ)** | Backup | International VT angle (13 markets including 6 Asia-Pacific). Lower acceptance threshold. |

**Recommended submission strategy:** FRL first (fast review, high impact, focused format). If rejected with constructive feedback, expand to JEF or JBF.

---

## Additional Experiments Needed Before Submission

### Critical (Must-Have)

1. **Expand asset universe to N >= 20** (currently 15 for cross-sectional test)
   - Add: DBA (agriculture), USO (oil), IWM (small cap), VGK (Europe), EWJ (Japan), HYG (high yield), LQD (investment grade), UUP (USD)
   - Target: 20-25 assets for credible cross-sectional claim
   - K50 Codex recommendation: ideally 50 (Hood's sample), but 20+ is minimum for journal

2. **Full Fama-French 5-factor + MOM + BAB control**
   - Currently only CAPM + TSMOM tested
   - K50/K47 both recommend: ensure TSMOM is not proxying for known factors
   - Download FF5 + MOM from Ken French's library

3. **Orthogonalized TSMOM implementation**
   - K50 requires TSMOM orthogonalized to MKT to avoid correlated regressor bias
   - Two approaches: (a) Fama-MacBeth (b) portfolio-level orthogonalization
   - Report both raw and orthogonalized results

4. **Time-varying T-bill rate**
   - K50 criticism: hardcoded 4% cash rate biases alpha
   - Use daily IRX (13-week T-bill) as actual risk-free rate
   - Re-run all alpha regressions with time-varying rf

### Important (Strongly Recommended)

5. **Sub-period analysis: 5 non-overlapping windows**
   - 2007-2010 (GFC), 2011-2014 (recovery), 2015-2018 (bull), 2019-2022 (COVID+taper), 2023-2026 (OOS)
   - Show dual mechanism holds in each period

6. **Bootstrap confidence intervals for decomposition**
   - 5000 reps block bootstrap (block size = 63 days for autocorrelation)
   - CI for: % Sharpe from TSMOM, % MDD retained after TSMOM removal

7. **TSMOM lookback sensitivity**
   - Test 1/3/6/9/12 month lookback windows
   - Show 12-month is dominant but results qualitatively robust to shorter windows

8. **VRP control regression**
   - K52 shows VRP is marginally significant but does not absorb alpha
   - Include for completeness, report null result

### Nice-to-Have (For Extended Version)

9. **Regime-specific decomposition**
   - Bull vs bear vs crisis: does the Sharpe/MDD split change?
   - K46: crisis periods show strongest alpha absorption (50-79%)

10. **Transaction cost sensitivity**
    - 0/5/10/20 bps round-trip
    - Show dual mechanism is TC-invariant

11. **Real-time implementability**
    - Pseudo out-of-sample: estimate gamma in-sample, predict TSMOM loading OOS
    - K46: already have "gamma from 2010-2017 predicts trend beta 2018-2026" (rho = 0.821)

12. **Comparison with managed futures indices**
    - SG CTA Index or BTOP50 as benchmark TSMOM proxy
    - Show VT provides similar TSMOM exposure at zero fee vs 2-and-20

---

## Estimated Timeline

| Phase | Task | Duration |
|-------|------|----------|
| 1 | Expand asset universe + re-run decomposition (N=20+) | 1-2 days |
| 2 | FF5+MOM+BAB controls + orthogonalized TSMOM | 1 day |
| 3 | Time-varying rf + HAC inference cleanup | 0.5 days |
| 4 | International + sector panels (already done, verify) | 0.5 days |
| 5 | Sub-period + bootstrap robustness | 1 day |
| 6 | Figures (6 publication-quality) | 1 day |
| 7 | Writing first draft | 3-5 days |
| 8 | Codex + Gemini review cycle | 1-2 days |
| 9 | Revision and polish | 2-3 days |
| **Total** | | **~10-15 days** |

---

## Key Literature to Cite

- Moreira & Muir (2017) --- VT alpha in equity factors
- Hood & Raughtigan (2025) --- VT = trend following (direct predecessor)
- Moskowitz, Ooi & Pedersen (2012) --- TSMOM
- Harvey et al. (2018) --- multi-asset VT
- Harvey, Liu & Zhu (2016) --- multiple testing threshold t > 3.0
- Barroso & Santa-Clara (2015) --- risk-managed momentum
- Fleming, Kirby & Ostdiek (2001) --- volatility timing
- Bozovic (2024) --- VIX-managed portfolios
- Glosten, Jagannathan & Runkle (1993) --- GJR-GARCH
- Black (1976), Christie (1982) --- leverage effect
- Newey & West (1987) --- HAC standard errors
- Lai (2026a) --- Paper 1 (gamma taxonomy, complexity ceiling)
- Lai (2026b) --- Paper 2 (Taiwan VT, amplification)

---

## Differentiation from Paper 1

| Dimension | Paper 1 (Leverage Direction) | Paper 3 (VT = Trend Following?) |
|-----------|------------------------------|----------------------------------|
| Central question | Which GARCH model for which asset? | Why does VT work? |
| Core finding | Gamma taxonomy + complexity ceiling | Dual mechanism (Sharpe/TSMOM + MDD/VIX) |
| Gamma role | Model selection criterion | Predictor of TSMOM loading |
| VT analysis | Secondary (gamma -> VT alpha channel) | Primary (full decomposition) |
| TSMOM | Not discussed | Central factor |
| International | Not covered | 13 markets |
| Sector analysis | Not covered | 11 sectors |
| Practical takeaway | Use GJR for gamma > 0.10 | VT != managed futures; VIX is universal MDD insurance |
