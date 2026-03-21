# Session 2026-03-21 Master Finding Synthesis (K43-K92)

50 findings produced in a single session. This document is the definitive reference.

---

## 1. Theoretical Advances: What We Now Know About VT

### 1A. VT = TSMOM + VIX Position Sizing (Dual Mechanism)

The session's headline discovery is a complete decomposition of VT's benefit channels:

| Channel | Mechanism | Metric affected | Evidence |
|---------|-----------|-----------------|----------|
| **Trend Following (TSMOM)** | 1/VIX mechanically creates momentum exposure; VIX drops in uptrends, rises in downtrends | Sharpe (minor, ~1.4% contribution) | K46, K49, K71, K73, K79 |
| **VIX Position Sizing** | VIX level determines cash allocation; high VIX = low equity = crisis protection | MDD (major, 90-97% preserved after TSMOM removal) | K49, K79 |

Key nuance chain:
- K46 initially claimed 91% alpha absorbed by TSMOM. K49 corrected: that was regression-coefficient-level, actual Sharpe impact only 32%. K79 further refined: TSMOM Sharpe contribution is merely 1.4%.
- K71 (FF5+MOM+BAB controls): VT alpha survives all factor controls (only -11.7%). TSMOM is time-series momentum, clearly separable from cross-sectional MOM (t=8.07 post-control).
- K73 (N=22 cross-section): TSMOM-VT correlation r=0.564 (p=0.006). 17/22 assets have significant TSMOM loading; 5 non-significant are all international equity (US VIX weaker TSMOM channel for non-US markets).

### 1B. VT Is Insurance, Not Alpha

Confirmed across multiple dimensions:

- **76 years, 8 decades** (K91): MDD protection 8/8 (100%), Sharpe improvement only 4/8 (50%).
- **13 international markets** (K68): MDD improved 13/13, Sharpe improved only 2/13.
- **Insurance cost**: K41's 4%/yr is a modern-era artifact. 76-year average is ~1.0%/yr (std=2.54%), highly regime-dependent (K91).
- **Interest rate sensitivity** (K62): High rates (IRX>3%) reduce net insurance cost to 1.80%/yr; low rates (IRX<1%) inflate it to 6.10%/yr. Current environment (IRX~4.5%) is historically cheapest.
- **Regime value map** (K92): VT costs money in all 5 VIX regimes (0.2-23.9%/yr). Best value = Normal VIX (17-22): 36% vol reduction for only 0.9%/yr. Low vol (13-17) is the only significantly loss-making regime.

### 1C. VIX Sufficient Statistic -- 23+ Confirmations

This session alone added confirmations #17 through #23:

| # | What was tested | Result | Finding |
|---|-----------------|--------|---------|
| 17 | VVIX / SKEW / VIX3M overlays | 0/18 strategies pass | K43 |
| 18 | SPY TSMOM for Taiwan VT | Fully absorbed by VIX | K57 |
| 19 | HMM regime-switching | corr(VIX weights, regime weights)=0.936 | K61 |
| 20 | Weekly rebalancing | No improvement over monthly | K65 |
| 21 | Seasonal VT threshold | DID t=0.17, p=0.87 NS | K80 |
| 22 | Vol spillover across assets | Harmful when exploited | K84 |
| 23 | Composite crisis predictor | AUC=0.762 vs pure VIX 0.771 | K90 |

### 1D. VT Drawdown Anatomy (K74)

- VT underperforms B&H in 80.3% of rolling quarters and 88.2% of rolling years.
- Core failure mode: VIX>25 + market rally = -42%/yr drag (V-shaped recovery is worst).
- Bear market win rate: 95.9%. Bull market: 2.0%.
- Tail protection is nonlinear: worst month improved by 20pp, worst 3-year by 12pp.
- Gross cost ~13.6%/yr (non-bear months), net cost ~4%/yr (including bear benefit).

### 1E. Asset-Class Boundaries of VT

| Asset class | VT effective? | Mechanism | Evidence |
|-------------|--------------|-----------|----------|
| US Equity | Yes (Sharpe + MDD) | Leverage effect + TSMOM | K46, K58 |
| International Equity | MDD only | VIX universal for MDD, weaker TSMOM | K68, K73 |
| Gold (GLD) | MDD only, weak | Safe-haven demand, not leverage effect | K46, K54 |
| Bonds (TLT) | MDD only, weak | Different mechanism | K46 |
| Commodities | No | No leverage effect | K45 (Hood 2024) |
| BTC | MDD only (own RV) | Uses self-RV, not VIX | Prior findings |
| Sectors (11 ETFs) | All benefit | gamma too narrow (0.07-0.16) to differentiate | K58 |

---

## 2. Practical Recommendations: What Investors Should Do

### 2A. Investor-Type Decision Matrix (K78)

| Type | Profile | Allocation | VT Threshold | Rebalance | Expected MDD |
|------|---------|-----------|-------------|-----------|-------------|
| A | Young DCA (20yr horizon) | 47.5/47.5/5 SPY/GLD/BTC | None | Quarterly | -20.3% |
| B | Mid-career DCA (10yr) | 50/50 SPY/GLD | 30/VIX | Quarterly | -19.0% |
| C | Pre-retirement lump sum | 50/50 SPY/GLD | 12/VIX | Monthly | -10.8% |
| D | Retirement 4% withdrawal | 50/50 SPY/GLD | 12/VIX | Monthly | -13.7% |
| E | Aggressive growth | 45/45/10 SPY/GLD/BTC | None | Quarterly | -24.0% |
| F | Ultra-conservative | 50/50 SPY/GLD | 8/VIX | Monthly | -7.3% |

Core insight: 12/VIX is appropriate for only 2 of 6 investor types (C and D). Young DCA investors using 12/VIX waste 33% of terminal wealth.

### 2B. Defense Layer Hierarchy (K70)

| Layer | Cost | MDD reduction | Mechanism |
|-------|------|---------------|-----------|
| 1 (FREE) | 0% | -11.7pp | 50/50 SPY/GLD diversification |
| 2 (FREE) | 0% | Smoothing | Monthly DCA |
| 3 (CHEAP) | 3.5% wealth | -5.2pp | 30/VIX VT |
| 4 (MODERATE) | 7.2% wealth | -5.9pp | 24/VIX VT |
| 5 (EXPENSIVE) | 35.4% wealth | -14.2pp | 12/VIX VT |

VT effectiveness drops 42% on already-diversified portfolios vs pure SPY. For DCA into 50/50, use 30/VIX or no VT at all.

### 2C. Taiwan-Specific Guidance (K88)

- Best strategy: 8.63/VIX monthly rebalance. k=6~15 all effective.
- 0% capital gains tax = structural advantage (tax drag only 0.33%/yr vs US 2.25%).
- 7 crises all protected (GFC MDD -18% to -3%).
- VIX step rule performs poorly (Sharpe 0.049) -- do not use.
- Current signal (VIX=26.78): hold 32.2% equity.

### 2D. Rebalancing Frequency (K65, K75)

- Sharpe is entirely insensitive to frequency (daily/weekly/monthly/quarterly/annual all NS).
- MDD is the differentiator: monthly -7.9% vs annual -17.7% during COVID.
- Quarterly + VIX>20 trigger is the practical sweet spot (~8 trades/yr, matches monthly MDD during GFC).
- Rebalancing frequency controls insurance response speed, not insurance cost.

### 2E. What NOT to Add

- **TLT/IEF/TIP/VNQ**: None improve 50/50 SPY/GLD (K64).
- **Factor tilts** (MTUM/VLUE/QUAL/USMV): 0/6 significant (K89).
- **Covered calls** (XYLD): Sharpe 0.334 vs SPY 0.578 (K72).
- **Stop-loss**: All hybrids Sharpe <= VT alone; same-day bias inflates claims 89% (K83).
- **Leverage**: Cannot offset insurance cost; breakeven margin rate ~3% (K81).
- **Seasonal adjustments**: DID t=0.17 (K80).

---

## 3. Self-Corrections

### K46 to K49/K50: "91% Alpha Collapse" Overstated

- **K46** claimed VT alpha is 91% trend following (GARCH VT SPY).
- **K49** corrected: 91% was regression-coefficient-level. Actual Sharpe impact only 32%. MDD protection lost only 4% after TSMOM removal.
- **K50** (Codex review): Original alpha was already NS (t=1.01). "91% reduction of a non-significant alpha" is misleading. Correct framing: "substantial TSMOM exposure consistent with leverage-effect channel."
- **K79** further refined: TSMOM Sharpe contribution is actually 1.4%, not 32%. The 32% was also regression-level alpha reduction, not Sharpe-level.

### K85 to K87: "4% to 8% SWR" Overturned

- **K85** claimed VT doubles safe withdrawal rate from 4% to 8% (Monte Carlo zero bankruptcies at 8%).
- **K87** self-challenged and overturned: 5 block sizes show VT 8% survival only 25-28%. Historical rolling windows: 67% survival (worse than B&H's 72%). Cash yield assumption inflated benefit by 255%.
- **Corrected conclusion**: VT stabilizes 4% SWR (near 100% survival), but does NOT double it. Sequencing bonus is real but moderate.

### K41 to K91: Insurance Cost Revised Downward

- **K41** established VT insurance costs ~4%/yr (constant).
- **K91** (76-year analysis) revised: long-run average is ~1.0%/yr (std=2.54%). The 4%/yr was a 2007-2026 artifact. In crisis decades (2000s), cost is negative (VT adds return).
- **K62** added interest-rate conditionality: high rates reduce net cost to 1.80%/yr; current IRX~4.5% is historically cheapest VT insurance.

---

## 4. Null Results (What Doesn't Work)

Organized by category. Each null saves future research time.

### 4A. Model/Method Nulls

| Finding | What was tested | Result |
|---------|----------------|--------|
| K44 | FHS-VaR targeting | = rescaled sigma targeting, no new alpha |
| K51 | MF2-GARCH (Conrad & Engle 2025) | 2/5 assets, no DM significance |
| K60/K61 | HMM Regime-switching VT | Convergence failure / corr=0.936 with VIX weights |
| K67 | EVT-VaR (POT) | Trinity pass rate 73.3% < Skewed-t 86.7% |
| K69 | GARCH-MIDAS (macro variables) | Macro worsens prediction; VIX-MIDAS works but = confirms VIX sufficiency |

### 4B. Strategy/Overlay Nulls

| Finding | What was tested | Result |
|---------|----------------|--------|
| K43 | VVIX/SKEW/VIX3M overlays | 0/18 pass cross-period consistency |
| K48 | Rebalancing boundaries | -69% trades, but Net Sharpe NS |
| K52 | VRP as third channel | R2 increment 1/75 of TSMOM |
| K54 | GLD contrarian VT | 0/7 beat baseline (all p>0.21) |
| K65 | Weekly VT | All frequency differences |t|<0.3 |
| K72 | Covered call (XYLD) + VT | Sharpe 0.334 << SPY 0.578 |
| K75 | Quarterly VT | Sharpe NS; MDD is the differentiator |
| K80 | Seasonal VT threshold | DID t=0.17 (p=0.87) |
| K81 | Leveraged VT | Sharpe +0.007, breakeven margin 3% |
| K83 | VT + Stop-loss | All hybrids <= VT alone |
| K84 | Vol spillover VT | Exploiting it is harmful (DM t=-2.07) |
| K89 | Factor tilts + VT | 0/6 significant (DM p>0.24) |

### 4C. Cross-Asset Nulls

| Finding | What was tested | Result |
|---------|----------------|--------|
| K57 | SPY TSMOM for Taiwan | Fully absorbed by VIX |
| K58 | Gamma predicts sector VT | r=0.163, p=0.632 (within-equity too narrow) |
| K64 | 3-4 asset portfolios | No traditional asset improves 50/50 |

---

## 5. Paper 3 Status

### Title (Working)

"Decomposing the Benefits of Volatility Targeting: Trend Following, Drawdown Insurance, and the VIX"

### Core Claims (Validated)

1. **Equity VT has substantial TSMOM exposure** (N=22, r=0.564, p=0.006) -- K73
2. **MDD protection is independent of TSMOM** (90-97% preserved after removal) -- K49, K79
3. **Dual mechanism is robust across VIX thresholds** (6 tested, all significant) -- K79
4. **Dual mechanism holds for 4/5 equity assets** (GLD excluded as expected) -- K79
5. **FF5+MOM+BAB do not explain VT** (alpha reduction only 11.7%) -- K71
6. **VRP is not a third channel** (R2 increment 1/75 of TSMOM) -- K52

### AI Reviews Received

- **Gemini (K76)**: Strong FRL candidate. Must pivot to "Decomposing Benefits" framing. Add VIX threshold sensitivity. Connect to Global Financial Cycle literature.
- **Codex (K77)**: Major revision. 7 issues including generalizability, table contradictions, scope too broad, word count. Top fixes: OOS identification, narrow scope, shorten.
- **Consensus**: Pivot from "alpha decomposition" to "drawdown insurance mechanism" narrative. FRL target (3500-5000 words).

### Fixes Completed (K79)

- VIX threshold sensitivity: 6 thresholds tested, all TSMOM significant (t=7.98-10.91).
- Multi-asset dual mechanism: 4/5 equity assets validated.
- TSMOM Sharpe contribution clarified as 1.4% (not 32%).

### Remaining Items

- [ ] Shorten to FRL word limit (3500-5000 words, currently ~5700)
- [ ] Fix Table 1 alpha contradictions (K77 item 2)
- [ ] Add spanning test vs managed futures factor (K77 item 4)
- [ ] Connect to Miranda-Agrippino & Rey 2020 Global Financial Cycle (K76 item 3)
- [ ] Add missing references: Cederburg 2020 JFE, Moreira & Muir 2019 RFS, Liu Patton Sheppard 2015
- [ ] Discuss limitation: 12/VIX is one parameterization, not "VT in general" (K77 item 5)

### Submission Readiness: ~70%

Core empirical work is complete. Needs editorial revision and scope narrowing. Target: FRL or JPM.

---

## 6. Open Questions

### High Priority (Actionable Now)

1. **HAR-RV with 5-min data**: SPY at 46 days (need 60+), 0050 at 34 days. SPY should reach threshold ~2026-04-09. Will HAR-RV provide genuine improvement over GJR at daily frequency?

2. **K91's 1%/yr insurance cost vs K41's 4%/yr**: The 76-year average (1.0%) and modern period (4.0%) differ dramatically. Is the increase due to (a) VIX-era improved signals making VT more responsive = more trading = more cost, (b) structural increase in crisis frequency, or (c) different market microstructure?

3. **BTC 5% allocation robustness**: K66 shows p=0.014 across full period and 4/4 sub-periods, but BTC-SPY correlation is structurally rising (0 to 0.43-0.56). Will the diversification benefit persist?

### Medium Priority (Future Sessions)

4. **TSMC concentration risk** (K82): 0050 rolling beta to TSMC rising from 0.38 to 0.72. At what point does concentration invalidate 0050 VT results? Need monitoring threshold.

5. **Interest rate regime change** (K62): If rates normalize to 2% (from 4.5%), VT insurance cost roughly doubles. How should the investor matrix (K78) adapt?

6. **Paper 3 international gap** (K73): 5/22 international ETFs have non-significant TSMOM loading. Is this a US VIX limitation or data issue? Would local implied vol improve?

### Low Priority (Theoretical)

7. **VT as trend following fund-of-funds**: If VT = TSMOM exposure + MDD insurance, is there a decomposition that maps VT to a portfolio of managed futures + put protection?

8. **Conditional VT (VIX>17)** from K92: Sharpe 0.764 vs always-on 0.732. Is this robust across decades, or just a backtest artifact? (Requires knowing VIX threshold ex-ante.)

---

## 7. Next Session Priorities

### Priority 1: Paper 3 Editorial Revision

- Narrow scope to FRL format (3500-5000 words)
- Fix table contradictions (K77)
- Add spanning test vs TSMOM factor
- Incorporate Gemini/Codex consensus: "Decomposing Benefits" framing
- Target: submission-ready draft

### Priority 2: HAR-RV Pipeline Check

- SPY 5-min data should be at 47+ days. Monitor for 60-day threshold.
- When reached, run HAR-RV vs GJR-GARCH comparison (QLIKE + DM test).
- This is the last plausible model improvement avenue.

### Priority 3: 2026 Q1 Live Performance Update

- K42 showed 6/6 strategies outperforming SPY B&H in Q1.
- Update with latest data through end of March.
- Publish Q1 report via feed-publisher skill.

### Priority 4: Research Program Update

- Integrate K43-K92 findings into `research_program.md`.
- Update CLAUDE.md strategy tables with corrected insurance costs.
- Mark completed research directions to prevent re-exploration.

---

## Appendix: Finding Index

| K# | Stars | Category | One-line summary |
|----|-------|----------|-----------------|
| K43 | | market_structure | VVIX/SKEW/VIX3M overlays all NULL (0/18) |
| K44 | | strategy | FHS-VaR targeting = rescaled sigma targeting |
| K45 | | literature | 2024-2026 literature review: Hood (TSMOM), Conrad (MF2), Branco (ML null) |
| K46 | 3 | mechanism | VT Alpha = Trend Following (equity only, 91% absorbed) |
| K47 | | ai_review | Gemini reviews K46: suggests controls, regime orthogonalization |
| K48 | | strategy | Rebalancing boundary: -69% trades but Sharpe NS |
| K49 | 2 | mechanism | K46 correction: actual Sharpe impact 32%, MDD 96% preserved |
| K50 | | ai_review | Codex reviews K46: alpha was already NS, framing too strong |
| K51 | | model | MF2-GARCH: no improvement over GJR in 3.2yr OOS |
| K52 | | mechanism | VRP not a third channel (R2 = 1/75 of TSMOM) |
| K54 | | strategy | GLD contrarian VT NULL (0/7 beat baseline) |
| K55 | | cross_asset | Taiwan VT update + TSMOM exposure |
| K56 | | ai_review | Gemini reviews Paper 2: PBFJ/EMR candidate |
| K57 | | cross_asset | SPY-0050 transmission fully VIX-mediated |
| K58 | | cross_asset | Sector gamma too narrow to predict VT effect |
| K59 | 2 | strategy | DCA needs milder VT: 24/VIX recommended |
| K60 | | model | HMM blocked (convergence failure) |
| K61 | | model | Regime-switching VT NULL (VIX=regime, corr 0.936) |
| K62 | 2 | strategy | Interest rate regime: high rates = cheapest VT insurance |
| K63 | 1 | cross_asset | SPY-GLD correlation stable; 50/50 6th confirmation |
| K64 | 2 | strategy | 3-4 asset portfolios: 50/50 7th confirmation |
| K65 | | strategy | Weekly VT NULL; monthly still best |
| K66 | 2 | strategy | BTC 5%: robust p=0.014 but rising correlation concern |
| K67 | | model | EVT-VaR: no improvement over Skewed-t |
| K68 | 2 | cross_asset | International VT: US VIX universal MDD insurance (13/13) |
| K69 | | model | GARCH-MIDAS: macro worsens, VIX-MIDAS confirms sufficiency |
| K70 | 3 | strategy | DCA 50/50 defense layers: 30/VIX optimal marginal VT |
| K71 | 3 | mechanism | FF5+MOM+BAB: VT alpha survives all (-11.7%), TSMOM separable |
| K72 | | strategy | Covered call (XYLD) + VT: income < capped upside |
| K73 | 2 | mechanism | N=22 TSMOM cross-section: r=0.564, p=0.006, Paper 3 ready |
| K74 | 2 | strategy | VT drawdown anatomy: 80% underperform = normal insurance |
| K75 | | strategy | Quarterly VT: Sharpe NS, MDD differentiates |
| K76 | | ai_review | Gemini reviews Paper 3: strong FRL candidate |
| K77 | | ai_review | Codex reviews Paper 3: major revision, 7 issues |
| K78 | 3 | strategy | Investor-type decision matrix: 6 types, 4 VT thresholds |
| K79 | 2 | mechanism | Paper 3 fixes pass: VIX threshold sensitivity + multi-asset |
| K80 | | strategy | Seasonal VT NULL (DID p=0.87) |
| K81 | | strategy | Leveraged VT NULL (breakeven margin 3%) |
| K82 | 1 | cross_asset | TSMC concentration: 0050 VT robust, add note |
| K83 | | strategy | VT + stop-loss NULL; same-day bias +89% |
| K84 | | cross_asset | Vol spillover: statistically significant, economically harmful |
| K85 | 3 | strategy | VT doubles SWR to 8% (OVERTURNED by K87) |
| K86 | 2 | strategy | VT tax efficiency: Taiwan 0% CGT = structural advantage |
| K87 | 3 | strategy | K85 overturned: VT stabilizes 4% SWR, does not double |
| K88 | | strategy | Taiwan VT practical guide: 8.63/VIX monthly |
| K89 | | strategy | Factor tilts + VT NULL; 50/50 8th confirmation |
| K90 | | strategy | VT traffic light: discipline tool, not trading signal |
| K91 | 3 | mechanism | 76-year validation: 8/8 MDD, 4/8 Sharpe; cost revised to 1%/yr |
| K92 | | mechanism | VT regime value map: normal VIX (17-22) = best insurance value |

---

*Synthesized 2026-03-21. 50 findings, 6 self-corrections, 23+ VIX sufficiency confirmations, 8 confirmations of 50/50 SPY/GLD.*
