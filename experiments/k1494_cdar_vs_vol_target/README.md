# K1494: CDaR target vs traditional vol target

## Motivation

The backlog question asks whether a drawdown-aware control objective can beat a standard volatility-aware control objective:

> Conditional Drawdown-at-Risk (CDaR) target vs traditional vol-target on stock / bond / commodity ETFs.

This is distinct from prior VolPred VT work because the target variable changes from realized volatility to the portfolio underwater curve. The risk is also methodological: drawdown is backward-looking and path-dependent, so a CDaR rule can easily become an after-the-fact deleveraging rule that misses recoveries.

## Literature Preamble

Minimum literature search completed before implementation:

- Chekhlov, Uryasev, and Zabarankin (2004/2005), "Portfolio Optimization with Drawdown Constraints" / "Drawdown Measure in Portfolio Optimization": introduces CDaR as the mean of the worst tail of the drawdown path and shows it contains maximum drawdown and average drawdown as limiting cases.
- Rockafellar and Uryasev (2000/2002), CVaR optimization: CDaR is conceptually close to expected shortfall applied to drawdown paths rather than one-period losses.
- scikit-portfolio / PyPortfolioOpt CDaR documentation: practical CDaR frontier implementations formulate minimum-CDaR portfolios through convex optimization.
- Project priors: K5 found pure drawdown-based sizing worse than 12/VIX because drawdown is backward-looking; K648 documented recovery-speed tradeoffs; K713 / 2026-06-13 error log requires standard compounded wealth drawdown definitions.

## Research Question

Does a simple CDaR-target exposure scaler improve OOS net Sharpe, maximum drawdown, and left-tail day frequency versus a traditional realized-volatility target?

## Design

Data:

- yfinance auto-adjusted close.
- Assets: `SPY`, `TLT`, `GLD`, `DBC`.
- Download window: 2006-01-01 to 2026-06-01.
- Analysis starts after required lookbacks.

Portfolio:

- Base return = equal-weight daily return of the four ETFs.
- `buy_hold`: exposure 1.0 to the base portfolio.
- `vol_target`: exposure = `10% / trailing_63d_ann_vol`, clipped to `[0, 1.5]`.
- `cdar_target`: exposure = `target_cdar / trailing_252d_CDaR95`, clipped to `[0, 1.5]`.

Anti-lookahead:

- Both risk signals are shifted by one trading day before returns are applied.
- CDaR target is calibrated only on 2008-2017 IS to match the vol-target average exposure, then evaluated OOS from 2018 onward.

Costs:

- 5 bps one-way transaction cost on absolute exposure changes.

Formal tests:

- 1,000-rep moving-block bootstrap, block length 21, seed 42.
- Paired OOS differences for Sharpe, MDD, CAGR, and left-tail day frequency.

## Success Criteria

CDaR would be considered useful only if it improves OOS MDD / left-tail frequency without materially worsening Sharpe and CAGR. A Sharpe gain caused only by lower exposure is not enough.

## Result

Verdict: **NULL / CDaR scaler does not beat vol target**.

OOS period: 2018-01-02 to 2026-05-29.

| Strategy | CAGR | Sharpe | MDD | CDaR95 | 2% left-tail days | Mean exposure |
|---|---:|---:|---:|---:|---:|---:|
| Buy hold | 10.391% | 1.0293 | -18.003% | 14.033% | 12 | 1.0000 |
| Vol target | 10.441% | 0.9966 | -16.258% | 13.031% | 18 | 1.1304 |
| CDaR target | 11.432% | 0.9312 | -23.237% | 18.185% | 29 | 1.2169 |

The CDaR rule takes more OOS exposure than the vol target, earns higher CAGR, but fails the drawdown-aware objective: MDD worsens by 6.98 percentage points versus vol target and 2% left-tail days rise from 18 to 29.

Paired OOS moving-block bootstrap, 1,000 reps, block length 21, seed 42:

| Difference: CDaR minus vol target | Mean | 95% CI | Interpretation |
|---|---:|---:|---|
| Sharpe | -0.055 | [-0.270, 0.159] | No significant improvement |
| MDD, pp | -5.087 | [-12.020, 1.351] | Skews worse; no reliable MDD gain |
| CAGR, pp | +1.062 | [-1.958, 4.015] | Higher return not statistically tight |
| 2% left-tail frequency | +0.00525 | [0.00095, 0.01041] | Left-tail frequency reliably worsens |

COVID crash slice confirms the mechanism: CDaR exposure stayed higher than vol target during the fast drawdown (`1.0256` vs `0.7814` mean exposure), producing a deeper MDD (`-23.237%` vs `-16.258%`). This is consistent with the project prior that drawdown-based sizing is backward-looking and can react after the damage.

## Files

- `k1494_cdar_vs_vol_target.py`
- `k1494_cdar_vs_vol_target_results.json`
- `k1494_equity_curves.png`
- `k1494_exposure_and_risk_signals.png`
- `data/prices.csv`
