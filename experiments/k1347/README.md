# K1347 — CVaR-RP vs Sigma-RP (ERC) on SPY/TLT/GLD/PDBC

## Motivation

K1387 found NULL for Gaussian vs Student-t DCC ERC on SPY/TLT/GLD (sigma-based risk
parity). The natural next question is whether **risk parity defined on tail risk
(CVaR contribution)** rather than volatility (sigma contribution) materially shifts
allocation away from negative-skew assets during stress periods, improving MDD
without sacrificing Sharpe.

This differs from K1387 in three ways:
1. **Risk definition**: equal CVaR contribution (α=0.05) vs equal sigma contribution.
2. **Asset universe**: adds PDBC (Invesco Optimum Yield Diversified Commodity) as a
   4th asset to test whether the tail-aware allocator can pick up commodity diversification
   in inflationary regimes (2022).
3. **Stress-period focus**: per-period metrics on 2018Q4 (Volmageddon aftermath /
   Fed pivot), 2020 COVID, 2022 inflation, 2025 Apr (Trump tariff shock).

K1123 also relevant — alt-data regime signals on SPY+GLD+TLT did NOT beat plain
risk parity, suggesting "naive" risk parity is hard to beat. Our hypothesis here is
that the bar to beat is sigma-RP, and switching the risk definition (not the data)
may help.

## Method

### Data
- Tickers: SPY, TLT, GLD, PDBC
- Source: yfinance, adjusted close
- Period: 2018-01-01 to 2025-12-31 (8 years)
- Frequency: daily

### Allocators

**M0 Equal-weight (EW)** — sanity check, 25% each.

**M1 Sigma-RP (ERC)** — baseline. Each month-end after close:
- 60-day rolling covariance Σ from returns available through the rebalance-day close
- Solve for w s.t. each asset's marginal risk contribution
  RC_i = w_i (Σw)_i / sqrt(w'Σw) is equal across i
- Implementation: scipy SLSQP minimize sum((RC_i − sigma_p/N)^2)
- Constraints: w_i ≥ 0.02, sum w = 1

**M2 CVaR-RP** — treatment. Each month-end after close:
- Use last 250-day historical returns (longer window needed for stable tail estimate)
- For candidate w, simulate portfolio return r_p(w) = R @ w
- CVaR_α(w) = -E[r_p | r_p ≤ VaR_α(w)], α=0.05
- Marginal CVaR contribution CRC_i(w) ≈ -E[R_i | r_p ≤ VaR_α(w)] * w_i
- Solve for w s.t. CRC_i / sum(CRC) is equalized across assets
- Implementation: scipy SLSQP minimize sum((CRC_i − CVaR/N)^2)
- Constraints: w_i ≥ 0.02, sum w = 1

### Lookahead protection
- All weights at month t formed using data up to and including t (last business day)
- Holdings start at first business day of month t+1
- Explicit `weights.shift(1)` on the daily weight series before computing portfolio returns
- This means weights formed end-of-month M are applied from first trading day of M+1 onward
- seed=42 fixed for bootstrap (CVaR uses historical simulation, no random draw)

### Transaction cost
- 5 bps per side on turnover (consistent with K1387)
- net_return_t = gross_return_t − cost * |Δweight_t|

### Metrics
- Full period: annual return, annual vol, net Sharpe, Sortino, MDD, Calmar
- Stress periods (per-period MDD and return):
  - 2018-10-01..2018-12-31 (Q4 selloff)
  - 2020-02-15..2020-04-30 (COVID crash + initial rebound)
  - 2022-01-01..2022-10-31 (inflation bear)
  - 2025-04-01..2025-04-30 (Trump tariff shock)
- 2018Q4 is reported as insufficient data in the final output because the common OOS
  sample starts on 2019-01-02 after the 250-day CVaR warmup and PDBC alignment.
- DM test for net return difference (CVaR-RP vs sigma-RP), HAC SE
- Bootstrap CI (1000 reps, seed=42) on Sharpe diff and MDD diff (stationary block bootstrap, block=20)

## Result

Verdict: **FAIL**.

- Full-period net Sharpe: Sigma-RP 0.966 vs CVaR-RP 0.949.
- Full-period max drawdown: Sigma-RP -20.35% vs CVaR-RP -19.80%.
- Stress-period MDD improved in only 1/3 evaluable periods: CVaR-RP improved 2022 inflation,
  but worsened 2020 COVID and 2025 tariff; 2018Q4 had no common OOS observations.
- DM test on net returns is not significant (p=0.796); bootstrap Sharpe-diff CI crosses zero.

## Success criteria

- **PASS**: CVaR-RP MDD significantly lower than sigma-RP in ≥3 stress periods, DM p-value on Sharpe diff not significantly negative (p<0.05), bootstrap CI on Sharpe diff does not cross 0 negatively.
- **CONDITIONAL_PASS**: MDD improves but Sharpe slightly worse, or only some stress periods improve.
- **NULL/FAIL**: no significant difference, or CVaR-RP underperforms.

Honest reporting required regardless of outcome (research honesty principle).

## Differentiation vs prior K

| K | Asset | Risk def | Result |
|---|-------|----------|--------|
| K1123 | SPY/TLT/GLD | regime signals on top of RP | NULL |
| K1387 | SPY/TLT/GLD | sigma-RP (DCC) | NULL Gaussian vs t |
| **K1347** | **SPY/TLT/GLD/PDBC** | **CVaR contribution vs sigma** | (this experiment) |

## Files
- `k1347.py` — full reproducible script
- `k1347_results.json` — all metrics + DM + bootstrap CI + codex review
- `k1347_fig.png` — equity + drawdown curves
- `README.md` — this file
