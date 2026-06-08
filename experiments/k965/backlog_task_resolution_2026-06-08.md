# Backlog Task Resolution — `research_wild_bootstrap_ohr`

- **Task ID**: `research_wild_bootstrap_ohr`
- **Resolved at**: 2026-06-08 台灣時間
- **Resolver**: Codex CLI
- **Resolution**: `duplicate_already_covered`

## Why this task is closed without a new experiment

The pending backlog item asks for a Wild Bootstrap OHR experiment under the futures-hedging methodology track. That work already exists in the repo as `K965`, with the required experiment triplet:

- `experiments/k965/README.md`
- `experiments/k965/k965_wild_bootstrap_ohr.py`
- `experiments/k965/k965_wild_bootstrap_ohr_results.json`

`K965` already tests the relevant research question:

- wild bootstrap percentile-based OHR
- comparison against static OLS, rolling OLS, naive `h=1`, and DCC-GARCH
- OOS hedging effectiveness on a high-correlation spot-futures pair
- interpretation that the value of wild bootstrap is uncertainty quantification, not a meaningfully better point estimate

## Existing result already on point

From `K965` and `storage/memory/knowledge.json`:

- Pair: `SPY / ES=F`
- Sample: about 2010-01 to 2026-04
- Core result: WB-75th `HE=0.9437` vs OLS static `HE=0.9435`
- DM tests: all wild-bootstrap variants vs OLS are not significant
- Main conclusion: for very high-correlation spot-futures hedges, wild bootstrap adds confidence intervals but does not materially improve the hedge ratio point estimate

This is substantively the same question as the backlog title `Wild Bootstrap OHR`.

## Literature cross-check

The existing experiment is aligned with the literature chain implied by the task:

1. **JRFM 2024** — *Estimation of Optimal Hedge Ratio: A Wild Bootstrap Approach*  
   MDPI page: `https://www.mdpi.com/1911-8074/17/7/310`

2. **Mammen (1993)** — wild bootstrap two-point distribution  
   Referenced by the JRFM paper and used directly in `k965_wild_bootstrap_ohr.py`

3. **Ederington (1979)** — classic hedging effectiveness benchmark  
   Journal of Finance / Wiley listing: `https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1979.tb02077.x`

These three references are sufficient to justify that `K965` already covers the method family and evaluation framework requested by the queue item.

## Why not rerun now

Opening a second experiment for the same topic would create duplicated evidence and dilute provenance. If this topic is revisited, it should be a clearly differentiated follow-up, for example:

- lower-correlation cross-hedges where bootstrap percentile choice may matter more
- bootstrap-based uncertainty intervals for commodity or currency hedges
- transaction-cost-aware rebalancing under bootstrap-selected hedge ratios

Absent that differentiation, the honest action is to mark the backlog item complete as already satisfied by `K965`.
