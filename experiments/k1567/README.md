# K1567: BigTech / merchant-platform credit-stress proxy and ETF RV

**Verdict**: `WEAK_RAW_ONLY` / corrected-primary NULL. Public platform-credit stress proxies have directional raw associations with IWM/HYG forward RV, but no controlled primary coefficient survives 24-test family correction.

## Motivation

Platform lending and merchant financing can substitute for bank credit and can use platform data / payment flows as monitoring technology. The research question here is deliberately narrower: can public market stress in merchant / fintech platform equities lead volatility in small-cap, retail, regional-bank, or high-yield ETF proxies?

## Data

- yfinance adjusted close:
  - Merchant / platform names: `SHOP`, `XYZ` (Block, replacing old `SQ` ticker in current yfinance), `PYPL`, `MELI`.
  - Credit-fintech names: `AFRM`, `UPST`.
  - Targets: `IWM`, `XRT`, `KRE`, `HYG`.
  - Controls: `SPY`, `^VIX`.
- FRED CSV:
  - `BUSLOANS`: commercial and industrial loans.
  - `DRBLACBS`: delinquency rate on business loans, all commercial banks.
  - `NFCI`, `STLFSI4`: financial conditions / stress controls.

Important limitation: no merchant-level approval, reserve, enforcement, repayment, or platform loan-book data are observed. K1567 is a public proxy screen, not a replication of platform-lending papers.

## Method

- Construct stress proxies from public equity baskets:
  - `merchant_platform_stress`: SHOP/XYZ/PYPL/MELI.
  - `credit_fintech_stress`: AFRM/UPST.
  - `combined_platform_stress`: average of merchant and credit-fintech basket returns.
- Each stress proxy averages lag-safe z-scores of:
  - negative 5-day basket return,
  - 21-day realized volatility,
  - 63-day drawdown severity.
- Apply explicit `signal.shift(1)` to every tested predictor.
- Targets: forward 5-day and 21-day annualized close-to-close log realized variance for `IWM`, `XRT`, `KRE`, `HYG`, strictly over `[t+1, t+H]`.
- Primary regression: controlled HAC OLS
  - `fwd_log_RV_H ~ signal_lag1 + own_log_RV21_lag1 + SPY_log_RV21_lag1 + VIX_level_lag1`
  - HAC maxlags = forecast horizon H.
- Supporting diagnostics:
  - Spearman block-bootstrap CI (block=H, B=1000, seed=42).
  - Hanley-McNeil AUC for left-tail events.
  - Bonferroni and Holm-Bonferroni over 4 targets × 2 horizons × 3 signals = 24 primary p-values.

## Success Gate

PASS requires at least one positive controlled-HAC coefficient to survive family-level correction, with supporting AUC/Spearman evidence. Raw-significant cells are diagnostics only.

## Results

Sample: 2018-01-02 to 2026-06-26, 2,132 US trading rows after applying the target/control ETF calendar. Credit-fintech and combined signals start later because AFRM/UPST history begins after IPO.

Primary family: `IWM/XRT/KRE/HYG × 5d/21d × 3 signals = 24` controlled-HAC p-values. Bonferroni alpha is `0.00208`; Holm-Bonferroni also rejects none.

Top controlled-HAC cells:

| Cell | Controlled coef | HAC t | p | Spearman rho / CI | Tail AUC / CI | Status |
|---|---:|---:|---:|---:|---:|---|
| HYG 21d `credit_fintech_stress` | +0.237 | +2.56 | 0.010 | +0.331 [0.156, 0.487] | insufficient 21d tail events | raw-only |
| IWM 5d `credit_fintech_stress` | +0.138 | +2.50 | 0.012 | +0.298 [0.211, 0.381] | 0.612 [0.563, 0.661] | raw-only |
| IWM 5d `combined_platform_stress` | +0.126 | +2.38 | 0.017 | positive | 0.617 approx | raw-only |
| HYG 5d `merchant_platform_stress` | +0.130 | +2.37 | 0.018 | positive | supporting only | raw-only |
| IWM 21d `combined_platform_stress` | +0.140 | +2.11 | 0.035 | positive | diagnostic | raw-only |

Univariate associations are much larger. For example, IWM 5d `credit_fintech_stress` has univariate t=7.01, but after controlling for own RV, SPY RV, and VIX, it falls to t=2.50. That is exactly why the controlled specification is primary: public platform equities partly proxy broad risk conditions already captured by standard market controls.

Interpretation: the proxy is directionally suggestive for small-cap and high-yield risk, especially through AFRM/UPST stress, but the result is not strong enough to publish as "merchant-platform credit stress predicts RV." K1567 should be stored as a weak diagnostic / future-data-motivation result. It is not a strategy signal and not a causal platform-lending claim.

## Literature Context

1. Gopal and Schnabl (2022), *Review of Financial Studies*, "[The Rise of Finance Companies and FinTech Lenders in Small Business Lending](https://academic.oup.com/rfs/article/35/11/4859/6524570)" — fintech / finance-company substitution in small-business credit.
2. Cornelli et al. (2020), BIS Working Paper, "[Fintech and big tech credit: a new database](https://www.bis.org/publ/work887.htm)" — cross-country fintech / BigTech credit measurement.
3. Berg et al. (2020), *Review of Financial Studies*, "[On the Rise of FinTechs: Credit Scoring Using Digital Footprints](https://academic.oup.com/rfs/article/33/7/2845/5735301)" — platform-style digital footprints as credit-scoring information.

## Outputs

- `k1567.py` — reproducible script.
- `k1567_results.json` — all statistics and source hashes.
- `k1567_analysis_dataset.csv` — merged signal/target panel.
- `fig1_platform_credit_stress.png`
- `fig2_hac_tstat_heatmap.png`
- `fig3_combined_stress_vs_targets.png`
- `codex_review.md` — source-level review, verdict `CONDITIONAL_PASS` for artifact integrity with claim-strength caveat.

## Lookahead Policy

- Rolling stress z-scores at date `t` use baselines ending at `t-1`.
- Tested predictors are explicitly lagged via `signal.shift(1)`.
- Forward targets use `[t+1, t+H]`.
- FRED series are shifted by conservative release lags before daily forward-fill.
- The panel calendar is restricted to dates where `IWM/XRT/KRE/HYG/SPY/^VIX` are all observed, avoiding non-US partial-calendar rows from yfinance.
