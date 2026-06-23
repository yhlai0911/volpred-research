# K1541 - Convertible ETF volatility management and beta timing

## Motivation

The backlog question asks whether volatility-managed convertible-bond exposure
has a real edge, or whether the result is mostly equity/credit beta timing in a
hybrid asset class. This experiment tests that question with tradable ETF
proxies and a deliberately conservative benchmark: apply the same lagged
volatility-management scalar to a rolling SPY/QQQ/HYG/LQD beta replication.

## Differentiation

This is not a generic volatility-targeting rerun. Existing internal work has
many SPY/VIX and factor-timing results, but this task focuses on convertible
ETFs as a hybrid equity-credit-option proxy. The design does not claim to
replicate individual convertible bonds, call features, delta hedging, or
convertible-arbitrage books.

Related internal priors:

- Moreira-Muir style VT entries in `storage/memory/knowledge.json`.
- K733 / K506: volatility-managed and regime-rebalanced ETF/factor work.
- K1538/K1539: credit ETF risk proxy work, useful for HYG/LQD controls.

## Literature Precheck

- Moreira and Muir (2017), "Volatility-Managed Portfolios", Journal of
  Finance. The paper motivates inverse-lagged-volatility exposure scaling and
  reports large factor Sharpe/alpha improvements.
  <https://amoreira2.github.io/alan-moreira.github.io/VolPortfolios_published.pdf>
- Cederburg, O'Doherty, Wang, and Yan (2020), "On the Performance of
  Volatility-Managed Portfolios", Journal of Financial Economics. The paper
  warns that real-time/out-of-sample versions do not systematically beat
  unmanaged portfolios in direct comparisons.
  <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3357038>
- Schweigl and Nikolov, "Do Volatility-Managed Portfolios Work Better for
  Convertible Bonds?", Journal of Fixed Income / SSRN. This is the motivating
  convertible-bond-specific paper; the present experiment tests a free ETF
  proxy version and adds beta-replication gates.
  <https://www.pm-research.com/content/iijfixinc/35/4/59>
- Xu (2024), "Improving Volatility-Managed Portfolios in Real Time", CFR /
  Critical Finance Review forthcoming manuscript. This motivates using fixed
  implementable scaling and real-time constraints rather than ex-post
  variance-equating.
  <https://cfr.ivo-welch.info/forthcoming/papers/xu2024improving.pdf>

## Data

- Price data: yfinance adjusted daily close, `auto_adjust=True`.
- Requested span: 2009-01-01 to 2026-06-24.
- Convertible ETF proxies requested: `CWB`, `ICVT`, `CONV`.
- Controls / beta factors: `SPY`, `QQQ`, `HYG`, `LQD`; state ticker `^VIX`
  downloaded for availability diagnostics.
- Sentiment regime: FRED `UMCSENT`, shifted by one monthly observation before
  daily forward fill.

Effective samples after rolling beta lookback:

| Asset | Effective sample | Days | Notes |
|---|---:|---:|---|
| CWB | 2010-04-19 to 2026-06-23 | 4,069 | used |
| ICVT | 2016-06-06 to 2026-06-23 | 2,525 | used |
| CONV | unavailable | 0 | yfinance adjusted close returned empty |

## Method

For each convertible ETF:

1. Build raw ETF daily simple returns.
2. Estimate lagged 21-day annualized volatility:
   `asset_ret.rolling(21).std().mul(sqrt(252)).shift(1)`.
3. Compute volatility-management weight:
   `clip(0.10 / lagged_vol, 0, 2)`.
4. Build `vm_cb_net = weight_t * return_t - 5bp * abs(delta weight_t)`.
5. Estimate rolling 252-day no-intercept beta replication with
   `SPY`, `QQQ`, `HYG`, and `LQD`, using only observations through `t-1`.
6. Build `beta_rep_net` and `vm_beta_rep_net`, charging the same 5bp turnover
   cost on rolling factor weights.
7. Compare raw CB, VM CB, beta replication, and VM beta replication using:
   Sharpe/MDD/CAGR, `strategy_dm_test(loss_fn="negative_return")`, 1,000
   circular 21-day block bootstrap Sharpe-difference CI, and HAC alpha tests.

Primary gate:

Convertible-specific VM edge requires all three:

- Sharpe difference versus `vm_beta_rep_net` is positive.
- 95% block-bootstrap CI lower bound is positive.
- DM t-stat is `<= -3` when comparing `vm_cb_net` against `vm_beta_rep_net`.

This gate intentionally follows the project rule that a large Sharpe headline
cannot stand without formal tests.

## Results

Verdict: **NULL_OR_BETA_TIMING_DOMINATED**.

No asset passes the convertible-specific gate. No asset passes the simpler
VM-vs-raw gate either.

### Performance

| Asset | Strategy | CAGR | Ann vol | Sharpe | MDD | Ann turnover |
|---|---:|---:|---:|---:|---:|---:|
| CWB | raw_cb | 10.53% | 13.26% | 0.822 | -32.06% | n/a |
| CWB | vm_cb_net | 8.97% | 10.96% | 0.838 | -20.90% | 9.91x |
| CWB | beta_rep_net | 9.72% | 11.84% | 0.843 | -25.10% | 5.54x |
| CWB | vm_beta_rep_net | 8.77% | 9.39% | 0.943 | -16.31% | 11.13x |
| ICVT | raw_cb | 13.74% | 15.59% | 0.904 | -33.25% | n/a |
| ICVT | vm_cb_net | 10.94% | 11.04% | 0.995 | -22.41% | 9.16x |
| ICVT | beta_rep_net | 9.65% | 13.31% | 0.759 | -26.75% | 8.09x |
| ICVT | vm_beta_rep_net | 8.43% | 8.78% | 0.965 | -17.56% | 12.93x |

### Formal Comparisons

| Asset | Comparison | Sharpe diff | Ann return diff | DM t | Bootstrap 95% CI | Gate |
|---|---|---:|---:|---:|---|---|
| CWB | VM CB - raw CB | +0.017 | -1.71% | +1.02 | [-0.264, +0.280] | FAIL |
| CWB | VM CB - VM beta | -0.105 | +0.34% | -0.23 | [-0.367, +0.145] | FAIL |
| ICVT | VM CB - raw CB | +0.091 | -3.11% | +1.22 | [-0.313, +0.418] | FAIL |
| ICVT | VM CB - VM beta | +0.030 | +2.51% | -1.20 | [-0.362, +0.396] | FAIL |

HAC alpha of `vm_cb_net ~ vm_beta_rep_net`:

- CWB: alpha = +0.42% annualized, t = 0.30, R2 = 0.719.
- ICVT: alpha = +2.55% annualized, t = 1.22, R2 = 0.627.

### Sentiment Regime

UMCSENT-lagged regimes do not rescue the claim. ICVT has a positive VM-minus-beta
annual return spread in both high and low sentiment regimes, but the full-sample
formal bootstrap and DM tests remain far below the gate. CWB shows similar small
positive return spread versus VM beta, but the Sharpe edge is negative because
the beta baseline has lower volatility.

## Interpretation

Volatility scaling lowers drawdowns for both CWB and ICVT, but it also reduces
CAGR versus raw buy-and-hold after turnover costs. The beta-replicated baseline
captures most of the risk-management benefit, and the same VM scalar applied to
rolling SPY/QQQ/HYG/LQD betas often has equal or better Sharpe.

The supported conclusion is therefore cautious: in this ETF-proxy design, there
is no robust evidence that convertible ETF volatility management is more than
equity/credit beta timing plus volatility scaling. This is a null/beta-timing
result, not a claim that convertible bonds cannot have issue-level or
structure-specific edges.

## Outputs

- `k1541_convertible_vol_management_beta_timing.py`
- `k1541_convertible_vol_management_beta_timing_results.json`
- `k1541_convertible_vol_management_beta_timing_cwb_daily_panel.csv`
- `k1541_convertible_vol_management_beta_timing_icvt_daily_panel.csv`
- `figures/k1541_vm_weights.png`
- `figures/k1541_sharpe_comparison.png`
- `figures/k1541_vm_vs_beta_relative_wealth.png`
- `figures/k1541_sharpe_diff_bootstrap.png`

## Limitations

- ETF proxies are not individual convertible bonds.
- `CONV` could not be tested because yfinance returned no adjusted-close data.
- Levered VM weights ignore financing costs above 1x; only turnover cost is
  charged.
- UMCSENT is a coarse monthly sentiment proxy; AAII was not used in this run.
- Rolling beta replication is a liquid-factor benchmark, not a structural
  convertible valuation model.
