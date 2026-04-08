# K914: Overnight-Intraday Decomposed MF-GJR

## Problem
K906 found SPY overnight volatility accounts for ~50% of total volatility. Standard MF-GJR uses close-to-close returns, mixing overnight and intraday volatility sources. **Can decomposing MF-GJR's long-run factor into overnight and intraday components improve forecasts?**

## Motivation
- K906: Overnight ~50% of total vol for SPY
- K912: MF-GJR has largest advantage in low-VIX environments (tau dominates)
- K889: MF-GJR sigma^2 = tau_t * g_t, tau_t = exp(theta0 + theta1 * logVIX)
- **Innovation**: Decompose return into r_overnight = log(Open_t / Close_{t-1}) and r_intraday = log(Close_t / Open_t), then test whether overnight and intraday have different VIX elasticities

## Method

### Step 1: Return Decomposition
- r_total = log(Close_t / Close_{t-1})  (close-to-close)
- r_overnight = log(Open_t / Close_{t-1})  (overnight gap)
- r_intraday = log(Close_t / Open_t)  (open-to-close)
- Verify: r_total approx r_overnight + r_intraday

### Step 2: Decomposition Analysis
- Variance ratio: var(r_overnight) / var(r_total)
- Autocorrelation structure of each component
- Correlation of each component with VIX
- Granger causality: overnight -> intraday? intraday -> overnight?

### Step 3: Four Models
1. **Model A: Standard MF-GJR** (baseline, same as K889v2)
2. **Model B: MF-GJR + Overnight Regressor** (add r^2_overnight,t-1 to tau)
3. **Model C: Separate Overnight/Intraday MF-GJR** (independent models, sum variances)
4. **Model D: MF-GJR + Overnight Ratio** (add overnight_ratio_{t-1} to tau)

### Step 4: Evaluation
- QLIKE on r^2 (Patton 2011)
- DM test vs Model A (Harvey |t| > 3.0)
- Spearman rank correlation
- VaR 1% + 5% Trinity (Kupiec + Christoffersen + Basel)

### Step 5: OOS Settings
- Same as K889v2: DATA_START=2005-01-01, OOS_START=2019-01-01, WINDOW=2000, REFIT_EVERY=63
- SPY only (maximum statistical power on most liquid asset)

## References
- Engle, Ghysels & Sohn (2013) RES 95(3):776-797
- Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics
- Patton (2011) J Econometrics 160:246-256
- Harvey et al. (2016) JBES 34:92-104
- Hansen & Lunde (2005) J Econometrics 127(1-2):255-285

## Expected Results
- VIX likely more correlated with overnight volatility (international info accumulates outside US trading hours)
- Model B (add r^2_overnight) may improve if overnight r^2 contains independent info about next-day vol
- Model C (separate models) may perform worse (overnight and intraday are NOT independent)
- Null result = overnight/intraday decomposition unnecessary for MF-GJR (VIX elasticity already implicitly captures this)

## Files
- `k914_overnight_intraday_mfgjr.py` - Main experiment script
- `k914_overnight_intraday_mfgjr_results.json` - Results
- `k914_decomposition.png` - Overnight vs intraday volatility characteristics
- `k914_model_comparison.png` - 4-model QLIKE comparison
