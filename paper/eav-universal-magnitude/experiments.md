# Supporting Experiments

All experiments use yfinance daily close data (2014–2025) with parquet snapshots stored under each experiment's `data/` directory. No live fetch is required to reproduce reported results.

## Primary Evidence (Three-Market EAV Regularity)

| K-ID | Market | Role | Verdict | Key Statistic |
|------|--------|------|---------|---------------|
| **K1145** | Taiwan (TWSE N=31) | Main IS estimate | PASS | θ̂=6.36e-5, cluster-t=5.24, placebo z=13.27σ (0/60) |
| **K1147** | US (S&P 500 N=30) | Main IS estimate | PASS | θ̂=1.91e-4, cluster-t=4.50, placebo z=70.74σ (0/60) |
| **K1150** | Japan (TOPIX N=30) | Main IS estimate | PASS | θ̂=1.41e-4, cluster-t=11.99, placebo z=38.65σ (0/60) |

## Null Heterogeneity Evidence Chain (Within-Market)

| K-ID | Hypothesis | Verdict | Contribution |
|------|-----------|---------|-------------|
| **K1109** | TW sector ANOVA (7 sectors, N=31) | FAIL | Joint F=1.31, p=0.297; no BH-FDR survivor |
| **K1113** | TW 6-covariate panel (mktcap, beta, earnings freq, volume, vol, momentum) | FAIL | CV R²=−0.661; max BH-FDR adj p=0.854 |
| **K1114** | TW rolling θ_EAV time-varying (3 stocks, w=500/step=21) | SPURIOUS | OLS-SE PASS collapses under HAC (K1140) |
| **K1140** | HAC Newey-West re-test of K1114 | FAIL | All 3 K1114 passes collapse under HAC |

## Supplementary / Robustness

| K-ID | Role | Verdict |
|------|------|---------|
| **K1148** | TW continuous \|surprise\| IS + OOS; binary vs continuous comparison | Binary preferred (DM t=−5.58 US OOS); continuous also significant (DM t=−5.25) |
| **K1149** | PCA factor absorption + stress interaction | Scenario A+D: absorption PASS both markets (US IS t=23.81, TW IS t=10.62); stress asymmetric (US PASS t=5.04; TW NS t=−0.39; LRT p=0.010) |

## Data Sources

- **Taiwan (K1145)**: `experiments/k1145/data/*.TW.parquet` — daily OHLCV 2014–2025 (yfinance, auto_adjust=False snapshot); `data/IDX_VIX.parquet`; `財報公告日.txt`
- **US (K1147)**: `experiments/k1147/data/*.parquet` + `data/earnings_dates.json` — 30 S&P 500 large-caps; VIX
- **Japan (K1150)**: `experiments/k1150/data/*.parquet` + `data/earnings_dates.json` — 30 TOPIX large-caps; VIX
