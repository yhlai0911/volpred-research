# K1334: Downside-CVaR target vs traditional volatility target

## Motivation

The backlog question asks whether a **conditional tail loss (CVaR / Expected Shortfall)** objective can beat a standard volatility-aware control objective on a multi-asset ETF portfolio:

> Downside-CVaR (Expected Shortfall) dynamic exposure scaling vs fixed volatility target.

The hypothesis is that targeting tail loss directly should compress the left tail of the portfolio return distribution more effectively than targeting realized volatility, because realized vol weights up the body of the distribution while CVaR weights only the worst α-fraction.

## Orthogonal contrast with K1494

This experiment is the **tail-aware** sibling of K1494 (drawdown-aware):

| Aspect | K1494 (CDaR target) | K1334 (CVaR target) |
|---|---|---|
| Risk objective | Drawdown path tail | One-period return left tail |
| Backward-looking? | Yes (drawdown peak) | Yes (252d historical ES) |
| Expected pathology | Stays long during fast crashes (COVID -23% MDD) | Reacts to realized tail; still unable to anticipate jumps |
| Verdict (K1494) | NULL — left-tail freq worsens 18→29 days | This experiment tests whether tail objective fixes the gap |

**Why methodology must match K1494**: orthogonal comparison demands the *only* difference between K1494 and K1334 is the risk objective (CDaR vs CVaR). Same base portfolio (equal-weight SPY/TLT/GLD/DBC), same calibration window (2008-2017 IS), same OOS (2018+), same vol-target spec, same exposure clip [0, 1.5], same lookback (252d for the alternative signal), same paired moving-block bootstrap (1000 reps, block 21, seed 42).

**Difference vs K1494**:
1. Risk signal: 252d historical 99% **CVaR** (mean of worst 1% daily returns over trailing 252d) instead of 252d CDaR95.
2. Transaction cost: 10 bps one-way (per task brief; K1494 used 5 bps). To preserve apples-to-apples comparability with K1494, we **also report a 5 bps variant** in `metrics_full_5bp` and use 10 bps as the headline.
3. CVaR target calibration: same procedure as K1494 — search target such that IS mean exposure ≈ vol-target IS mean exposure.

## Literature

- Rockafellar & Uryasev (2000, 2002) — CVaR / Expected Shortfall as coherent risk measure; foundation for tail risk targeting.
- Acerbi & Tasche (2002) — coherence of ES (CVaR); ES respects sub-additivity unlike VaR.
- Boudt, Peterson, Croux (2008) — estimation of portfolio CVaR with Cornish-Fisher tail; relevant to historical vs parametric trade-off.
- VolPred priors:
  - **K1494** — CDaR target failed (backward-looking; mean exposure too high in COVID).
  - **K5** — pure drawdown-based sizing inferior to 12/VIX; backward-looking risk signals lag realized tail events.
  - **K648** — recovery-speed trade-offs in dynamic sizing rules.
  - **K713** / 2026-06-13 error log — standard compounded wealth drawdown definitions.

## Research Question

Does a 1-day 99% historical CVaR (Expected Shortfall) target scaler improve OOS net Sharpe, left-tail day frequency, and CVaR/VaR breach rate versus traditional realized-vol targeting, while not catastrophically worsening MDD (the K1494 failure mode)?

## Design

**Data**

- Source: yfinance auto-adjusted close
- Tickers: `SPY`, `TLT`, `GLD`, `DBC` (same as K1494 for orthogonal comparison)
- Download window: 2006-01-01 to 2026-06-01
- Analysis start: 2008-01-02 (after lookbacks settle)
- IS calibration: 2008-01-02 to 2017-12-29
- OOS evaluation: 2018-01-02 to end

**Portfolio**

- Base return = equal-weight daily return of the four ETFs
- `buy_hold`: exposure 1.0
- `vol_target`: exposure = `0.10 / trailing_63d_ann_vol`, clip [0, 1.5]
- `cvar_target`: exposure = `target_cvar / |trailing_252d_99%_ES|`, clip [0, 1.5]

**CVaR estimation**

For each day t we use the trailing 252 daily base returns `r[t-252..t-1]`:

1. Compute the 1% empirical quantile `q01`.
2. Compute `ES99 = mean( r[r <= q01] )` — this is the mean of the worst-1% tail (Expected Shortfall / Conditional VaR).
3. We use `|ES99|` (positive number) as the risk denominator.

We pick the 1% level (rather than 5%) because the prompt specifies *99% CVaR*. With 252 obs the worst 1% is `ceil(0.01 * 252) = 3` days — small but non-trivial; we additionally sanity check with 5% (`metrics_full_alt_5pct`).

**Anti-lookahead**

- Both `vol_target` and `cvar_target` risk signals are computed from data **up to and including t-1** (via `rolling(window).std()` / rolling CVaR which is naturally backward-looking) and **further `.shift(1)`** before applying to returns at t. This guarantees `signal_t uses info up to t-1` even if the rolling window edge had been interpreted ambiguously.
- IS calibration uses only 2008-01-02 to 2017-12-29; OOS evaluation never reuses IS data for target picking.

**Costs**

- 10 bps one-way transaction cost on absolute exposure changes (per task brief)
- 5 bps variant reported as robustness

**Formal tests**

- Paired moving-block bootstrap: 1000 reps, block length 21, seed 42, OOS sample only
- Paired differences: Sharpe, MDD (pp), CAGR (pp), 2% left-tail frequency, daily 5% CVaR
- Report 95% CI and `Pr(diff > 0)`

## Success criteria

- **PASS**: CVaR-target Sharpe > vol-target Sharpe **and** left-tail frequency / daily CVaR significantly improves (95% CI on improvement does not cross 0).
- **NULL (still valuable)**: CVaR-target and vol-target indistinguishable. Completes the risk-target series story: drawdown-aware (K1494) AND tail-aware (K1334) both fail to beat backward-looking vol-target.
- **FAIL**: Lookahead violation / code bug / non-convergence.

We expect either NULL or marginal because CVaR is itself backward-looking — the COVID-style fast crash mechanism that broke K1494 (signal not yet reflecting the crash) is structurally identical for historical CVaR.

## Files

- `K1334.py` — main script
- `K1334_results.json` — byte-traceable outputs
- `k1334_equity_curves.png`
- `k1334_exposure_and_risk_signals.png`
- `data/prices.csv` — cached prices for reproducibility

## Reproduction

```
cd experiments/K1334
python K1334.py
```

Random state: `numpy.random.default_rng(42)` for bootstrap. yfinance prices cached to `data/prices.csv` after first run.
