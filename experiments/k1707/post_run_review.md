# K1707 post-run independent review

VERDICT: PASS

Reviewer scope: process integrity and adequacy-audit correctness. This is not a
positive scientific verdict; the experiment's scientific status remains
`INSUFFICIENT_STRESS_SUPPORT`.

## Verified

- All four pre-registered support gates fail on the frozen public sample: 16
  dates, zero high-stress dates, three symbols, and six weekend dates.
- VIX is constructed with `ffill().shift(1)` and enters only the support audit.
- The frozen panel independently reconstructs the pooled benefits in the
  results file, with correct direction conventions.
- `MULTIPLE_IND` is reported only as an auction-only rate (5.07%).
- No interaction, VIX slope, p-value, null claim, or causal claim is reported.
- Manifest hashes match the reviewed script, aggregate panel, and VIX file.
- Both reader-facing figures correctly distinguish support failure from the
  pooled pseudo-data description.
- Two complete reruns produced identical SHA-256 values for results, panel,
  manifest, VIX, and both figures.

## Nonblocking limitations

- The public file is smaller, independently noised pseudo-data with altered
  dates, not the original OPRA sample.
- The sample cannot answer the scientific stress-interaction question and its
  failure of support must not be interpreted as null evidence.
