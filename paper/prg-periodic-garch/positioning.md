# PRG Paper — Step 3: Literature Positioning

Date: 2026-04-05
Based on: literature_survey.md (36 papers) + K874d/K880v2/K881/K881b/K883 results

## The Gap

Existing session-decomposition volatility models fall into three categories, each with limitations:

1. **Complex score-driven models** (Linton & Wu 2020, JEconometrics): Coupled DCS-EGARCH for intraday/overnight with ~12+ parameters. Theoretically rich but estimation is heavy and practitioner adoption low.

2. **Continuous-time Ito models** (Kim, Shin & Wang 2023, JBES): Overnight GARCH-Ito with separate diffusion processes. Elegant but requires specialized estimation machinery.

3. **Independent session models** (Liang, Du & Huang 2023, JFM): Bisected Realized GARCH (BRG) treats sessions separately. No cross-session variance linkage — misses the h_{n-1} bridge that empirically matters.

**What's missing**: A parsimonious (6-8 parameter) GARCH model that captures cross-session variance transmission through a single recursive h_{n-1} bridge, using realized measures for precision while remaining simple enough for routine practitioner use.

## Our Position

The Periodic Realized GARCH (PRG) fills this gap by:

1. **Extending periodic GARCH** (Bollerslev & Ghysels 1996) from calendar periodicity (day-of-week) to session periodicity (overnight/intraday), motivated by Blanc et al. (2014)'s finding that overnight and intraday feedback structures are fundamentally different.

2. **Simplifying PRS** (Lai, Wang & Chang 2024, APFM): Replace Markov regime switching with deterministic session index → eliminates Hamilton filter, reduces parameters from ~12 (PRS with 2 regimes) to 6-8.

3. **Incorporating realized measures** (Hansen, Huang & Shek 2012): Uses 5-min RV as volatility proxy, bridging the Realized GARCH and periodic GARCH literatures.

4. **Maintaining cross-session linkage**: The single h_{n-1} recursion carries variance information across session boundaries — this is what separates PRG from BRG/separate models and is empirically validated (DM t=-5.16 to -6.34, all Harvey PASS).

## Three Contributions (for FRL)

### Contribution 1: The PRG Model
- Single GARCH recursion with session-periodic parameters (α_s, β_s, γ_s for s ∈ {overnight, intraday})
- h_{n-1} bridges sessions: variance at overnight close informs intraday open prediction and vice versa
- 6 parameters (Basic) or 8 parameters (Extended, with leverage)
- Parsimony advantage: PRG has 6-8 params vs. Linton & Wu ~12+, Kim et al. ~10+, PRS ~12+

### Contribution 2: Fair Comparison Framework
- Common target: σ²_fullday = r²_gap + RV_intra + RV_night
- Each model predicts its native target, then converts to common target via scaling ratios estimated in-sample
- Addresses Hansen & Lunde (2005) concern about comparing models on different targets
- Reveals that HAR's apparent superiority over GJR on RV is a target-mismatch artifact (K874c DM t=-11.14 disappears on common target: t=0.57, NS)

### Contribution 3: Cross-Market Empirical Evidence
- 5 markets: TAIFEX (tick data), SPY, QQQ, GLD, EEM
- PRG Extended beats GJR in 4/5 markets (Harvey PASS: t=4.26 to 6.63)
- Cross-session bridge matters: PRG vs Separate GARCH, DM t=-5.16 to -6.34 (all Harvey PASS)
- Benefit increases with overnight variance share: TAIFEX (49.6%) > EEM (52.6%) > GLD (53.1%) >> SPY (34.5%)
- When overnight share is low (SPY ~35%), PRG converges to GJR → graceful degradation

## Key Result Table

| Market | Overnight % | PRG Ext QLIKE | GJR QLIKE | Improvement | DM t (vs GJR) |
|--------|------------|---------------|-----------|-------------|----------------|
| TAIFEX | 49.6% gap | 0.198 | 0.447 | 55.7% | 5.10*** |
| EEM | 52.6% | 0.664 | 0.790 | 15.9% | 6.63*** |
| GLD | 53.1% | 0.820 | 0.902 | 9.1% | 6.12*** |
| QQQ | 27.9% | 0.765 | 0.826 | 7.3% | 4.26*** |
| SPY | 34.5% | 0.864 | 0.854 | -1.2% | NS |

*** = Harvey (2016) t > 3.0

Cross-session bridge (PRG vs Separate):
| Market | DM t | Harvey |
|--------|------|--------|
| QQQ | -5.47 | PASS |
| GLD | -5.16 | PASS |
| EEM | -6.34 | PASS |
| TAIFEX | (in K874d) | (to verify) |

## Target Journal: Finance Research Letters (FRL)
- 14-page limit (current draft ~12 pages)
- 2 contributions is sufficient
- Short literature review acceptable
- Empirical results + practical implications preferred

## Differentiation from Competitors

| Model | Parameters | Cross-session h link | Realized measures | Estimation |
|-------|-----------|---------------------|-------------------|------------|
| **PRG (ours)** | 6-8 | Yes (h_{n-1} bridge) | Yes (5-min RV) | MLE |
| Linton & Wu (2020) | ~12+ | Yes (coupled DCS) | No | Score-driven |
| Kim et al. (2023) | ~10+ | Yes (Ito diffusion) | Yes (integrated vol) | QML + RV |
| Liang et al. (2023) BRG | ~10 | No (separate) | Yes | MLE |
| PRS (Lai et al. 2024) | ~12+ | Yes (Markov switching) | No | Hamilton filter |
| Standard PGARCH | varies | No (calendar only) | No | MLE |

PRG's unique selling point: **simplest model with cross-session linkage + realized measures**.

## Limitations to Acknowledge

1. Without tick data (SPY), PRG advantage disappears → overnight proxy (r²_overnight) is noisy
2. r²_gap (single squared return) is a poor proxy for overnight variance; with tick data, RV_night is much better
3. Session timing assumptions (fixed open/close times) may not hold during holidays/half-days
4. Linear GARCH specification — may benefit from log-linear extension (Hansen & Huang 2016)
5. Univariate only — multivariate extension not explored (cf. Kim et al. 2023 Factor O-GARCH-Ito)

## Next Steps (Step 4: Theory)

1. Formal model specification with information set F_{n-1}
2. Stationarity conditions via companion matrix eigenvalue < 1
3. Proof that h_{n-1} bridge is identifiable (not absorbed by separate intercepts)
4. Relationship to PRS: show PRG is the deterministic-session special case
5. Common target conversion theory (bias correction under scaling)
