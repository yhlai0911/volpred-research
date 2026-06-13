# Codex Review

Date: 2026-06-14
Reviewer: codex-desktop
Verdict: PASS

## Scope

Reviewed:

- `k_etf_vs_etf_fragility_2026_06_14.py`
- `k_etf_vs_etf_fragility_2026_06_14_results.json`
- `README.md`

## Findings

No remaining blocking issues.

The initial review found three issues that were fixed before this PASS:

- The PC1 event-study windows were labeled non-overlapping while the first implementation used an insufficient event gap.
- H1 language overclaimed macro-efficiency because shock labels use same-day SPY/VIX returns.
- The fragility interpretation was too causal for a public daily-price reduced-form proxy.

## Verified Fixes

- `non_overlapping_events()` now uses `2 * PC_WINDOW + 1`, so adjacent 21-day pre/post windows do not share observations.
- H1 is explicitly framed as a same-day market-stress co-movement proxy, not independent macro-information evidence or a tradable signal.
- README and results JSON describe the verdict as `REDUCED_FORM_SUPPORT_WITH_CAVEATS` and state that the experiment is not direct evidence of ETF ownership, primary-market create/redeem flows, or underlying-stock arbitrage.

## Residual Caveats

The experiment is valid as descriptive/event-study evidence. It is not a causal ETF ownership or flow design, and it should not be used for strategy deployment without a separate strictly lagged OOS rule.
