# K1551 Codex Review

Review date: 2026-06-24

## Verdict

PASS with strict scope limits.

K1551 is suitable as a data-limited proxy diagnostic. It should be described as partial group-level evidence that credit/EM/muni/corporate bond ETF fragility proxies line up with larger stress-day fair-value residuals and forward RV. It must not be described as a true authorized-participant concentration result.

## Checks

- Required experiment artifacts exist: `README.md`, `k1551.py`, and `k1551_results.json`.
- The script writes data artifacts, figures, and a data availability audit under `experiments/k1551/`.
- Data source, sample window, ticker universe, and stress definition are explicit in results.
- Random procedures use `SEED = 1551`.
- No `storage/memory/knowledge.json` write is performed by Codex.
- The yfinance institutional-holder failure is recorded instead of silently replacing it with a false AP concentration variable.
- Lookahead controls are explicit:
  - rolling fair-value coefficients use observations through `t-1`;
  - stress-day outcomes use date `t` as the event;
  - forward RV uses `t+1` through `t+5`;
  - bootstrap sampling is fixed-seed.
- Formal tests include date-level high-minus-low group spread tests, bootstrap CIs, and ETF-level Spearman ranking checks.

## Result Audit

- Verdict: `PARTIAL_GROUP_SUPPORT_MIXED_ETF_RANKING`
- High-fragility group: `EMB`, `HYG`, `LQD`, `MUB`
- Low-fragility group: `AGG`, `BND`, `IEF`, `TLT`
- Abs residual DID: 0.000860, Welch t = 8.34, bootstrap CI [0.000672, 0.001069]
- Forward 5d RV DID: 0.000107, Welch t = 4.88, bootstrap CI [0.000067, 0.000153]
- Spearman fragility vs residual lift: rho = 0.262, p = 0.531
- Spearman fragility vs forward RV lift: rho = 0.214, p = 0.610

The group-level result is positive, but ETF-level ranking evidence is weak. The partial/mixed verdict is the correct one.

## Issues Found During Review

1. The original backlog phrasing requested AP concentration via public 13F/yfinance holder data. yfinance holder modules are empty/404 for the tested bond ETFs, so the experiment correctly downgraded to a proxy diagnostic rather than manufacturing AP concentration.
2. The first script verdict gate would have labeled the result full support when group-level DIDs were positive even though ETF-level Spearman ranking was insignificant. The gate was tightened so this case becomes `PARTIAL_GROUP_SUPPORT_MIXED_ETF_RANKING`.

## Remaining Limitations

- The fair-value residual is only a proxy for price/NAV deviation.
- Static yfinance metadata cannot represent historical AP participation or changing creation/redemption capacity.
- The universe is too small for precise cross-sectional ranking.
- Duration shocks make `TLT` a useful counterexample: low AP-fragility proxy does not mean low stress dislocation.
- Any future publishable AP-concentration result needs Form N-CEN/AP activity data, CRSP or issuer NAV premium/discount series, and ideally creation/redemption basket data.
