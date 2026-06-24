# Codex Review

Review date: 2026-06-24

## Verdict

Pass with limitations. The experiment is suitable as a descriptive diagnostic of
recent large index-inclusion/reconstitution events. It is not evidence for a
direct 2026 fast-entry mega-IPO effect.

## Checks

- Required experiment triplet exists: README, executable script, and results
  JSON.
- The script is deterministic for bootstrap intervals (`SEED = 42`).
- Event windows are based on effective inclusion dates and use only pre-event
  returns for normalization and jump thresholds.
- There is no trading strategy or same-day signal-times-return calculation.
- Results are written by the script, not manually edited.
- Primary conclusion is aligned with the formal gate: the primary
  stock-minus-peer RV differential has mean 0.0107, t=0.07, and bootstrap CI
  crossing zero.

## Lookahead / Alignment Review

The key anti-lookahead guard is:

```python
pre = index[pos - PRE_WINDOW : pos]
post_full = index[pos : pos + POST_FULL]
```

All pre-event denominators and jump thresholds are computed from `pre`, which
excludes the effective date and all post-event returns. Because this is an
event-study measurement rather than a forecast or strategy, there is no
`signal.shift(1)` series; the equivalent lag discipline is the non-overlapping
pre/post split and the absence of any same-day signal-return PnL calculation.

## Residual Risks

- Same-date events are not independent. The reported date-cluster bootstrap is
  a useful sensitivity but still has only six event-date clusters.
- Same-sector peer lists are hand-built and can affect peer-relative results.
- yfinance survivorship, ticker-history, and adjusted-close behavior are
  adequate for a screen but not for publication-grade microstructure claims.
- Nasdaq-100 observations are annual reconstitution additions, not the 2026
  fast-entry rule itself.

## Acceptance

The null/weak conclusion is credible given the small sample and public data
limits. Do not use this result to claim that index fast-entry mechanisms have no
effect generally; the supported claim is only that this recent public proxy
sample does not show robust post-inclusion RV or peer-relative RV uplift.
