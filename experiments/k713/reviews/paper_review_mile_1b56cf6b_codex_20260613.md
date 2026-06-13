# K713 / mile_1b56cf6b — Post-Publish Source-Level Review

- **Article**: `mile_1b56cf6b` "股票加黃金還不夠？多放一點長債，報酬會少一點，但跌的時候真的差很多"
- **Published**: 2026-06-13T04:01:14.933126+00:00
- **Review date**: 2026-06-13
- **Reviewer**: Codex desktop
- **Task**: `paper_review_mile_1b56cf6b`
- **Linked K**: `K713`

## (A) Number Consistency — PASS

Cross-check against [`experiments/k713/k713_results.json`](/Users/yhlai0911/Desktop/volpred-research/experiments/k713/k713_results.json):

| Article claim | Ground truth | Verdict |
|---|---|---|
| 25% TLT risk-adjusted score about 0.933 | `tlt_25.sharpe = 0.933` | PASS |
| 30% TLT no further improvement | `tlt_30.sharpe = 0.932`, below `tlt_25` | PASS |
| MDD improves from -36.8% to -23.8% | `tlt_0.mdd = -36.8`, `tlt_25.mdd = -23.8` | PASS |
| CAGR falls from 11.4% to 9.7% | `tlt_0.cagr = 11.4`, `tlt_25.cagr = 9.7` | PASS |
| 20-25% TLT is a balanced zone | `tlt_20.sharpe = 0.926`, `tlt_25.sharpe = 0.933`, `tlt_30.sharpe = 0.932` | Supported descriptively |

The published quantitative claims are aligned with the current results artifact.

## (B) Source Reproducibility — FAIL

K713 does not satisfy the current experiment audit standard:

- [`experiments/k713/README.md`](/Users/yhlai0911/Desktop/volpred-research/experiments/k713/README.md) is a planning placeholder.
- No `experiments/k713/k713.py` or equivalent script exists in the current repo.
- `git log --all -- '*k713*'` shows the original K713 commit added only `experiments/k713_results.json`; no source script is recoverable from git history.
- [`experiments/k713/k713_results.json`](/Users/yhlai0911/Desktop/volpred-research/experiments/k713/k713_results.json) contains only summary metrics. It does not record data source, sample period, rebalance rule, transaction-cost assumption, or exact portfolio construction details.

This is a publication-source problem rather than a numeric mismatch. The article's numbers are real relative to the stored JSON, but the stored JSON is not independently reproducible.

## (C) Lookahead / Methodology — NOT VERIFIABLE

Because no script exists, the review cannot verify:

- whether weights were formed using information available before returns,
- whether rebalancing used same-day close-to-close returns,
- what period and data vintage were used,
- whether transaction costs or dividends were included,
- whether 50/50 SPY/GLD plus TLT weights were normalized as expected.

No lookahead bug is proven, but the absence of source code prevents a clean pass.

## (D) Production Article Correction

Applied a live article update via `scripts/publish_draft.py --update`:

- Removed user-facing K-id references from the general-audience body.
- Added an explicit "conservative use" section explaining that K713 is a legacy migrated artifact with results and figures retained but no original recomputation script.
- Reframed the 20-25% TLT conclusion as a historical descriptive result requiring rerun before paper-grade or strategy-grade use.

## Overall Verdict

**CONDITIONAL PASS AFTER CORRECTION**

- **PASS**: Numeric claims match the retained JSON.
- **FAIL**: Source-level reproducibility is not sufficient for a clean review.
- **Mitigation applied**: Production article now discloses the limitation and no longer presents the result as fully audit-grade.

## Required Follow-Up

Create a new platform/experiment task to reconstruct K713 with:

- `experiments/k713/README.md`
- `experiments/k713/k713.py`
- `experiments/k713/k713_results.json`
- pinned data source / sample period / rebalance convention
- generated figures matching the article or a new corrected article if results change
