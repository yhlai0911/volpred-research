# K1706 primary-path Codex review — 2026-07-16

- **Reviewed commit:** `071fdc73a287dad615cbd731f84920d33c5031af`
- **Reviewer:** Codex CLI 0.144.1, `gpt-5.6-sol`, high reasoning, read-only sandbox
- **Session:** `019f6832-90d6-7e12-8bd2-8a766044e088`
- **Verdict:** `PASS`
- **Claim scope:** range heterogeneity only; RV and liquidity outcomes are non-rejection diagnostics

## Review conclusion

No blocking defects remain. The final revision removes the earlier October-boundary leakage by
filtering to frozen pre/post observations before calculating raw returns, adjusted returns,
adjustment-factor changes, Amihud, and rolling RV. The confirmatory classification is justified
only for the daily range proxy under the frozen design.

## Checks performed

- All tracked experiment bytes match the reviewed commit and the pinned SHA-256 values.
- External and results-embedded manifests are identical; panel, assignment, OHLCV, spread, and
  script hashes match the manifest.
- Boundary reconstruction found zero October rows. All 4,166 `symbol × analysis_period` groups
  have missing first raw return, adjusted return, and adjustment-factor change. All 2,064
  retained stocks have missing first-post Amihud input.
- The rebuilt panel matches the committed 340,283-row panel.
- Recomputed primary, heterogeneity, and placebo results match stored values within floating-point
  noise (`≤ 2.85e-14`).
- Alternating-projection stock/date FE converges at `1e-12`; stock clustering, explicit
  `signal.shift(1)`, seed 42, 999 RI permutations, fixed bins, separate Holm families, placebo,
  atomic validated JSON replacement, and non-silent parse skips remain intact.
- Silent-fallback and experiment-integrity gates pass.

## Frozen success rule

`range_bps` alone qualifies:

- Narrow primary RI: `p=0.002`, Holm `p=0.016`.
- Narrow-minus-wide heterogeneity RI: `p=0.001`, Holm `p=0.004`.
- Both range placebos: Holm `p=1.0`.
- Sample gates pass: narrow control/treated `778/757`; wide `260/269`.

## Remaining limitations

Daily OHLCV proxies are not intraday measures. RI preserves treated counts within frozen spread
strata but does not reconstruct every official randomization stratum. Public-data coverage may
still introduce survivorship/data-availability selection, and 999 permutations limit p-value
resolution.

## Trust boundary

The confirmatory claim is trusted only for range heterogeneity. RV, log-dollar-volume, and
Amihud are non-rejection/null diagnostics; they do not establish equivalence or rule out
economically meaningful effects.
