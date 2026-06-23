# Codex Review

Verdict: **CONDITIONAL_PASS_AS_UNDERPOWERED_NULL_PROXY**

## Checks

- Lookahead: OK. High-concentration threshold uses
  `close30_vol_share.shift(1).rolling(...).quantile(0.80)`, and source-day
  close-window signals are tested only against day `t+1` targets.
- Target: OK. Primary targets are next-session open-to-close squared return,
  next-session 5-minute RV, and next-session reversal payoff.
- QLIKE / DM: N/A. This canonical script is an event/proxy diagnostic, not the
  unreproducible daily HAR/QLIKE rerun that earlier draft text referenced.
- DM horizon: N/A for the same reason.
- Randomness: OK. Bootstrap uses `np.random.default_rng(SEED)` with `SEED=42`.
- Calendar handling: OK for proxy purpose. Third-Friday OPEX is adjusted to the
  previous trading day within 3 calendar days when the nominal Friday is closed.
- Claim strength: WARN. The data are SPY-only local 5-minute snapshots, not true
  exchange closing-auction prints or MOC imbalance feeds.
- Publication: FAIL for positive article. Results support only a null /
  underpowered proxy screen.

## Key Evidence

- Local sample: 106 usable SPY sessions, 6 monthly OPEX days, 2 triple-witching
  proxy days.
- Triple-witching close-30m RV share is descriptively high, 17.69% vs 6.76%,
  but `N=2` blocks inference.
- High close-concentration signal is null-to-negative for next OC r²
  (`t=-0.27`) and next 5-minute RV (`t=-0.78`).
- Reversal payoff is positive but not significant (`t=1.32`).
- Continuous Newey-West regressions all have `|t| < 1.31`, far below the
  Harvey-style `|t| > 3` gate.

## Required Framing

Do not publish this as a positive trading or volatility signal. If used at all,
frame it as a free-data limitation result and a requirement for multi-year
minute bars or true auction/imbalance data.
