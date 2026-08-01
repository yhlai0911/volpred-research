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

## Rejected-branch cross-implementation check (2026-08-02)

Before retiring rejected branch `codex/k1707-pseudo-stress` at tip
`de0dbef8c4bf2acf55a0e913f146a77824b46445`, its independently written raw-file
pipeline was compared with the certified main implementation. Both obtained
exactly 1,161,488 rows: 384,580 auction and 776,908 continuous observations.
They also agreed on the support limitations: 16 dates, three anonymized
symbols, six weekend dates, and the 2020-09-18 through 2020-12-14 date range.
This agreement is a cross-implementation validation of the committed sample
inventory, not permission to adopt the rejected branch's scientific output.

The rejected branch joined altered pseudo-dates to historical VIX and reported
permutation p-values. Those p-values remain excluded from the certified result:
altered timestamps cannot identify a real market stress effect, and the branch
itself marked the sample `UNIDENTIFIED_PSEUDO_SAMPLE`. Only its generic Holm
step-down and exact fixed-count permutation algorithms were salvaged behind the
canonical `volpred.stats.inference` interface and independently tested. No
branch result, market claim, chart, or experiment implementation was merged.
