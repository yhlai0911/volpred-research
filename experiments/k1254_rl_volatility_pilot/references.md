# K1254 References

Literature gathered 2026-04-18 via WebSearch (3 query passes). Each entry: title / authors / year / venue / contribution / relevance to K1254 / dataset / baseline / metric.

## Primary anchors (RL + volatility, 2024-2025)

### R1. Solving The Dynamic Volatility Fitting Problem: A Deep Reinforcement Learning Approach
- **Authors**: Cao, J. et al. (2024)
- **Venue**: arXiv 2410.11789
- **URL**: https://arxiv.org/html/2410.11789
- **Contribution**: Applies DRL (DDPG / SAC variants) to dynamic local-volatility surface fitting under SDE constraints; shows comparable or better performance than classical fitting algos.
- **Relevance to K1254**: Closest existing precedent. **Different target** — they fit an option-implied vol surface; K1254 forecasts realized vol scalar h+1. Demonstrates RL is at least viable for vol-related tasks.
- **Dataset**: Synthetic + market option surfaces (paper-internal).
- **Baseline**: Standard local-vol calibrators (Dupire-style).
- **Metric**: Calibration RMSE on surface points.

### R2. Deep Reinforcement Learning for Risk-Aware Portfolio Optimization: A Comparative Study of PPO, QR-DDPG, DDPG, and SAC under Market Uncertainty
- **Authors**: (preprint, see Zenodo record)
- **Year**: 2025
- **Venue**: Zenodo working paper
- **URL**: https://zenodo.org/records/18666986 (also ResearchGate 398486187)
- **Contribution**: Head-to-head comparison of PPO vs DDPG vs SAC vs QR-DDPG on 25-asset portfolio optimization with drawdown-penalized reward. PPO best (Sharpe 2.15 ± 0.05, CVaR -1.8% ± 0.1%).
- **Relevance to K1254**: Justifies algorithm choice. PPO outperforms DDPG/SAC in financial RL; supports our PPO-first decision in §3.3.
- **Dataset**: 25 US equities, 2015-2024.
- **Baseline**: 1/N, mean-variance.
- **Metric**: Sharpe, CVaR, max drawdown.

### R3. Deep Learning-Based Volatility Forecasting, Portfolio Management, and Reinforcement Learning-Based Risk Optimisation
- **Authors**: (see Springer record)
- **Year**: 2025
- **Venue**: National Academy Science Letters (Springer)
- **DOI / URL**: https://link.springer.com/article/10.1007/s40009-025-01914-w
- **Contribution**: Two-stage pipeline — LSTM/GRU forecast vol → PPO uses forecast as input for risk-budget allocation. Reports realized vol forecast metrics (MSE, QLIKE, Pearson) plus DM tests.
- **Relevance to K1254**: Confirms QLIKE + DM is the standard evaluation kit even in DL-for-vol papers. **Crucially, in this paper RL is downstream of vol forecast (not the forecaster itself)** — this is the literature gap K1254 targets.
- **Dataset**: S&P 500 + VIX, 2015-2024.
- **Baseline**: GARCH, HAR.
- **Metric**: QLIKE, MSE, DM-HLN, Sharpe.

## Supporting refs (DL-vol context, justifies the baselines)

### R4. Deep Learning and Transformer Architectures for Volatility Forecasting: Evidence from U.S. Equity Indices
- **Authors / Year**: (MDPI, 2025)
- **Venue**: Journal of Risk and Financial Management 18(12), 685
- **URL**: https://www.mdpi.com/1911-8074/18/12/685
- **Contribution**: Compares HAR-RV, ARIMA, GARCH vs LSTM, CNN-LSTM, PatchTST-lite, Transformer on US indices 2000-2025. PatchTST-lite wins; HAR-RV remains a hard-to-beat baseline.
- **Relevance**: Confirms 2025 SOTA finding that **HAR-RV is the right baseline** to beat for daily realized vol. Justifies §3.2 baseline choice.
- **Metric**: QLIKE, RMSE, MAE.

### R5. Dynamics in Realized Volatility Forecasting: Evaluating GARCH Models and Deep Learning Algorithms Across Parameter Variations
- **Year**: 2024
- **Venue**: Computational Economics (Springer)
- **DOI / URL**: https://link.springer.com/article/10.1007/s10614-024-10694-2
- **Contribution**: Cross-parameter robustness study of GARCH-family vs DL on RV forecasting.
- **Relevance**: Documents the variance of DL vs GARCH results across hyperparameter settings — supports our 5-seed protocol in §3.5.

### R6. Hybrid deep learning and GARCH-family models for forecasting volatility of cryptocurrencies
- **Venue**: ScienceDirect (Journal of Finance and Data Science)
- **URL**: https://www.sciencedirect.com/science/article/pii/S266682702300018X
- **Year**: 2023
- **Contribution**: Hybrid DL + GARCH on crypto. Useful comparator if K1254 extends to BTC in k1254b.

## Methodology refs (statistical evaluation)

### R7. Patton, A.J. (2011). Volatility forecast comparison using imperfect volatility proxies.
- **Venue**: Journal of Econometrics 160(1), 246-256
- **DOI**: 10.1016/j.jeconom.2010.03.034
- **Relevance**: Establishes QLIKE as robust loss function under noisy RV proxy. Cited in §3.6 for primary metric.
- **Note**: Already on platform's standard reading list (see `research_program.md`).

### R8. Hansen, P.R., Lunde, A., Nason, J.M. (2011). The Model Confidence Set.
- **Venue**: Econometrica 79(2), 453-497
- **DOI**: 10.3982/ECTA5771
- **Relevance**: MCS test required for §3.6 to handle multiple comparisons across baselines.

### R9. Diebold, F.X., Mariano, R.S. (1995); Harvey, Leybourne, Newbold (1997) small-sample correction.
- **Venue**: J. Business & Economic Statistics 13(3); International J. Forecasting 13(2)
- **Relevance**: DM-HLN is the standard pairwise predictive accuracy test used throughout platform (per `research_program.md` rules).

## Tangential / negative-evidence refs

### R10. Deep Reinforcement Learning for Investor-Specific Portfolio Optimization: A Volatility-Guided Asset Selection Approach
- **URL**: https://arxiv.org/html/2505.03760
- **Year**: 2025
- **Why listed**: Another instance of the dominant pattern — vol forecast feeds RL trader, vol is **input**, not target. Reinforces K1254's literature gap.

### R11. Deep neural network approach integrated with reinforcement learning for forecasting exchange rates
- **URL**: https://www.nature.com/articles/s41598-025-12516-3
- **Venue**: Scientific Reports (2025)
- **Why listed**: RL-as-forecaster, but FX point forecast (not vol). Demonstrates technique transfers; closest "RL emits the forecast" precedent in adjacent task.

## Conformal prediction (relegated — not used in v1 spec)

Conformal prediction surfaced in 2024-25 (Rose-STL-Lab CPTC NeurIPS 2025; Monash WP20-2024 multi-step CP) as an uncertainty-quantification overlay on top of vol forecasts. **Out of scope for K1254 v1** — would add a second methodological dimension and inflate compute. Note for K1254-conformal as potential follow-up if K1254 v1 is WEAK/STRONG PASS.

- Rose-STL-Lab CPTC: https://arxiv.org/abs/2509.02844
- Monash WP20-2024: https://www.monash.edu/business/ebs/research/publications/ebs/2024/wp20-2024.pdf

## Coverage check vs platform rule (≥3 real recent papers)

- R1 (2024 arXiv) + R2 (2025 Zenodo) + R3 (2025 Springer) = 3 primary RL+vol refs
- R4 (2025 MDPI) + R5 (2024 Springer) + R6 (2023 ScienceDirect) = 3 supporting DL-vol refs
- R7-R9 = methodology canon (already platform standard)
- R10-R11 = literature-gap evidence

**Total: 11 refs, of which 6 are 2023-2025 primary literature.** Exceeds ≥3 threshold.

## Honest limitation

R2 is a Zenodo preprint, not peer-reviewed. R3's full PDF was not accessed (paywall, did not pay). Citations are **WebSearch-derived metadata** — when K1254 actually runs and writes results, the implementing agent must verify each ref via DOI lookup or `sci-hub` skill before citing in any feed article or paper. Do not pass these verbatim into a paper without verification.
