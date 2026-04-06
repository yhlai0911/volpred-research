# K922: Copula-GARCH SPY-0050.TW — Cross-Market Tail Dependence for Taiwan Investors

## Question
K920 found SPY-GLD Student-t copula with lambda=0.14 (tail dependence but crisis decoupling).
How does the SPY-0050.TW copula structure compare? Is cross-market tail dependence stronger
or weaker? How large is the tail risk for Taiwan investors holding US equities?

## Motivation
- K920: SPY-GLD Student-t copula, lambda=0.14, crisis conditional independence
- K919: SPY->Taiwan gap channel accounts for 99.7% of transmission (R^2=0.355)
- K907: 0050.TW is net receiver (-18.4%)
- K918: SPY-GLD no cross-spillover (BEKK)
- Paper 2 (Taiwan VT) needs copula perspective
- User expertise: copula-GARCH/hedging

## Method
1. Data: SPY + 0050.TW daily returns (2006-2026), aligned on common trading days
2. Marginals: GJR-GARCH(1,1) Student-t for each asset -> PIT -> uniform
3. Five copulas: Gaussian, Student-t, Clayton, Gumbel, Frank
4. AIC/BIC model selection
5. Rolling 500-day copula for time-varying tail dependence
6. Crisis analysis: GFC 2008, COVID 2020, Rate Hike 2022
7. Copula VaR/ES comparison: 50/50 SPY/GLD vs 50/50 SPY/0050.TW

## Key Hypotheses
- SPY-0050.TW rho > SPY-GLD rho (0.094) since 0050.TW is equity receiver
- Clayton may dominate (asymmetric lower tail dependence — co-crash without co-rally)
- lambda_L may exceed SPY-GLD's 0.14 (cross-market equities co-crash more)
- Crisis decoupling unlikely (unlike gold, 0050.TW has no safe-haven function)

## Error Log Rules Applied
- 0050.TW: must use clean_tw50_data
- Random seed: np.random.seed(42)
- Cross-market: align trading days carefully (ffill prices, holidays return=0)
- Statistical rigor: KS test for PIT uniformity, convergence checks

## Results

### Data
- Period: 2009-01-05 to 2026-04-02 (4081 common trading days)
- IS: 2384 days, OOS: 1697 days
- 0050.TW: higher vol (std=1.34%) than SPY (1.13%), higher kurtosis (18.0 vs 10.9)

### Copula Selection
Best copula: **Student-t** (AIC=-155.62), same family as SPY-GLD (K920)

### Key Comparison: SPY-0050.TW vs SPY-GLD (K920)

| Metric | SPY-GLD (K920) | SPY-0050.TW (K922) |
|--------|---------------|-------------------|
| Best copula | Student-t | Student-t |
| rho | 0.094 | **0.219** |
| nu (df) | 3.05 | **5.75** |
| lambda_L | **0.140** | 0.078 |
| lambda_U | **0.140** | 0.078 |
| Pearson corr | 0.058 | **0.140** |
| Spearman corr | 0.061 | **0.145** |

### Key Findings

1. **Higher correlation, lower tail dependence**: SPY-0050.TW has 2.3x higher linear
   correlation (rho=0.219 vs 0.094) but LOWER tail dependence (lambda=0.078 vs 0.140).
   This is because nu=5.75 (thinner tails) vs nu=3.05 (fatter tails) for SPY-GLD.

2. **Crisis-regime asymmetry**:
   - GFC 2008: SPY-TW lambda=0.000, rho=0.029 (vs SPY-GLD lambda=0.112, rho=0.080)
     -- TW actually DECOUPLED during GFC, possibly because the crisis originated in US
   - COVID 2020: SPY-TW lambda=**0.364**, rho=**0.452** (vs SPY-GLD lambda=0.068, rho=-0.147)
     -- TW had MUCH STRONGER tail dependence during COVID (global pandemic = simultaneous shock)
   - Rate Hike 2022: SPY-TW lambda=0.000, rho=0.025 (vs SPY-GLD lambda=0.049, rho=0.194)

3. **COVID was the turning point**: SPY-0050.TW tail dependence spiked dramatically
   during COVID (lambda=0.364, rho=0.452) -- the strongest co-crash in the sample.
   This confirms K848's finding that Taiwan market is globalizing.

4. **Portfolio tail risk similar**: Copula VaR 1% for 50/50 SPY/TW (-2.00%) is close
   to 50/50 SPY/GLD (-1.97%), but SPY/TW has worse historical VaR (-2.68% vs -2.39%).

5. **0050.TW is NOT a diversifier**: Unlike GLD which decouples in crises (K920),
   0050.TW amplifies co-crashes during global events (COVID). This provides copula-level
   evidence for the 50/50 SPY/GLD moat (K846).

### Hypothesis Verification
- [CONFIRMED] SPY-0050.TW rho (0.219) > SPY-GLD rho (0.094)
- [REJECTED] Clayton does NOT dominate -- Student-t wins (symmetric tail dependence)
- [REJECTED] lambda_L does NOT exceed SPY-GLD (0.078 < 0.140 due to higher nu)
- [PARTIALLY CONFIRMED] Crisis non-decoupling: TRUE for COVID, but DECOUPLED in GFC and Rate Hike

### Limitations
- Common trading day alignment reduces sample (4081 vs 5345 for K920)
- Close-to-close returns may not capture intraday transmission (K919 gap channel)
- PIT uniformity rejected (KS p<0.05) for both assets -- marginal model imperfect
- VaR backtest shows 0 violations (too conservative) -- daily copula VaR overestimates risk

## References
- Patton (2006): Modelling Asymmetric Exchange Rate Dependence, IER
- Joe (1997): Multivariate Models and Dependence Concepts
- Kupiec (1995): Techniques for Verifying VaR, Journal of Derivatives
- Christoffersen (1998): Evaluating Interval Forecasts, IER
- Cherubini, Luciano & Vecchiato (2004): Copula Methods in Finance

## Files
- `k922_copula_spy_tw.py` -- main experiment script
- `k922_copula_spy_tw_results.json` -- complete results
- `k922_copula_comparison.png` -- AIC/BIC copula selection
- `k922_tail_dependence.png` -- rolling tail dependence
- `k922_crisis_analysis.png` -- crisis period comparison with K920
- `k922_copula_var.png` -- VaR backtest
