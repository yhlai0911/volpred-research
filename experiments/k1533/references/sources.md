# K1533 — Primary sources

## Replicated paper (RECH-X)
- Nguyen, H.T., Nguyen, H., & Tran, M.-N. (2024). "Deep learning enhanced
  volatility modeling with covariates." *Finance Research Letters* 69:106145.
  - SSRN abstract_id=4657189
  - LiU DiVA full text: diva2:1901445
    (https://www.diva-portal.org/smash/get/diva2:1901445/FULLTEXT01.pdf)
  - Model RECH-X (Eqs. 2a-2d): SRN-GARCH(1,1), Student-t innovations, exogenous
    covariate `z` fed into the SRN input `x_t = (omega_{t-1}, y_{t-1},
    sigma_{t-1}^2, z_{t-1})`.
  - Estimation: Bayesian likelihood-annealing SMC (Duan & Fulop 2015); priors
    alpha,beta~U(0,1), beta0,beta1~U(0,0.5), RNN weights ~N(0,0.1), regressor
    coeff ~N(0,0.5), nu~Gamma(1,0.1).
  - Data: 10 stock indices incl. S&P500, Nikkei225, from the Oxford-Man Institute
    (5-min realized volatility). 2001 prices → 2000 returns; first 1500 train,
    last 500 OOS, one-step-ahead.
  - Evaluation (Appendix A): PPS, QS (VaR quantile score), MSE, MAE, R2LOG —
    point and density forecast scores. MSE/MAE compare sqrt(RV) vs sqrt(forecast).
  - Headline (Table 3, S&P500): RECH-X best on all 5 scores; beats RealGARCH on
    MSE 0.095 vs 0.120 (~21%), MAE 0.234 vs 0.283.

## Base RECH model
- Nguyen, T.-N., Tran, M.-N., Gunawan, D., Kohn, R. (2022). "Recurrent
  Conditional Heteroskedasticity." *Journal of Applied Econometrics* 37(5):
  1031-1054. (arXiv:2010.13061.)
  - SRN-GARCH spec (Eqs. 8a-8d): sigma_t^2 = omega_t + alpha y_{t-1}^2 +
    beta sigma_{t-1}^2; omega_t = beta0 + beta1 h_t; h_t = SRN(x_t, h_{t-1}) =
    phi(v'x_t + w h_{t-1} + b); phi = BOUNDED ReLU (Theorem 1 requires bounded
    recurrent component for finite unconditional variance).
  - No-covariate input: x_t = (omega_{t-1}, y_{t-1}, sigma_{t-1}^2).

## Baselines
- Bollerslev (1986) GARCH; Glosten, Jagannathan & Runkle (1993) GJR;
  Hansen, Huang & Shek (2012) RealGARCH (non-exponential).
- Engle (2002) MEM; Barndorff-Nielsen & Shephard (2002) realized measures.

## Evaluation methodology
- Patton (2011) — QLIKE robust to noisy volatility proxy.
- Diebold & Mariano (1995); Harvey, Leybourne & Newbold (1997) small-sample
  correction.

## Related RECH extension
- Liu et al. (2023) RealRECH — LSTM + RealGARCH measurement equation. RECH-X
  differs by injecting the covariate directly into the variance recursion rather
  than via a measurement equation.
