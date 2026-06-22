# K1362 Codex Source Review

Review date: 2026-06-22

Verdict: `CONDITIONAL_PASS`

## Scope

Reviewed:

- `experiments/k1362/K1362.py`
- `experiments/k1362/K1362_results.json`
- `experiments/k1362/README.md`

## Findings

No source-level blocker found for the reported weak/null timing conclusion.

The implementation does not label public Cboe put/call ratios as true ACIB.
That distinction is essential because the motivating JFQA paper uses
open-buy/open-sell option order imbalance, while K1362 only observes aggregate
call and put volumes.

Predictive timing uses explicit one-day lags:

```python
panel[f"{col}_lag1"] = panel[col].shift(1)
```

The SVXY risk-off diagnostic uses a lagged rolling 80th-percentile threshold,
so the gating rule itself is not using a future full-sample cutoff.

## Checks

- `SEED = 42` is fixed.
- Cboe raw and parsed CSVs are cached under `data/`.
- The README matches `K1362_results.json`: one expected-direction HAC pass
  (`equity_call_demand_z -> VIX change 5d`, t=+3.03), no SPY/SVXY strong pass,
  and verdict `WEAK_DIAGNOSTIC_NULL_STRONG_TIMING`.
- The SVXY risk-off result is presented as a weak diagnostic, not a deployed
  strategy or an ACIB replication.

## Caveats

- The direct free Cboe bulk CSV window ends on 2019-10-04.
- Cboe exchange-level volume is not OCC consolidated all-market open-close
  volume.
- SVXY is a VIX-futures ETF with product-design effects.

## Allowed Knowledge Claim

K1362 supports only a weak public-proxy statement: public equity call-demand
pressure has a Harvey-level association with next 5-day VIX change, but it does
not robustly forecast SPY excess returns or SVXY returns, and it does not
replace true option order-imbalance data.
