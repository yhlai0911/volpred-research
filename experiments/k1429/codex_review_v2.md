# K1429 v2 Codex Re-review — VERDICT: CONDITIONAL_PASS

**Reviewer**: Codex CLI
**Reviewed at**: 2026-06-09
**Files reviewed**:
- `experiments/k1429/k1429_v2.py`
- `experiments/k1429/k1429_v2_results.json`
- `experiments/k1429/draft_v2.md`
- `storage/reports/mile_072c3972.json`

## Severity 1

None. The two v1 blockers are resolved:

1. **Baseline inference** no longer uses `ttest_rel` against a duplicated
   constant. v2 uses a two-sided randomization test against baseline pseudo-event
   samples, so baseline uncertainty is no longer suppressed.
2. **Event alignment** now comes from actual `yfinance` earnings timestamps, and
   all in-sample announcements are mapped to the first tradable reaction day.

## Severity 2

1. **Sample still small**: each ticker has 10 events, so inference remains
   fragile and article claims should stay descriptive rather than universal.
2. **Baseline windows still come from the same market regime**: this is much
   better than v1, but not a fully exogenous counterfactual.
3. **Daily close-to-close data** still compresses after-hours jumps and intraday
   digestion into one daily return series.

## Severity 3

1. The article now preserves the old tag set, so `MSFT` / `AAPL` are present in
   content and experiment refs but not in the persisted feed tags.
2. `feed-sync --apply` did not return within the interactive window, so this
   review only verifies local artifacts and the updated single-report file.

## Verdict rationale

The core methodological defects from v1 are fixed, and the rewritten article no
longer overclaims NVDA pre-earnings compression. The corrected body now matches
the v2 evidence:

- **NVDA pre**: lower mean, but not significant
- **AAPL**: no robust signal
- **MSFT post**: large positive difference that still survives Bonferroni

That is publishable as a corrected, cautious reader-facing article, but only as
**CONDITIONAL_PASS** because the sample remains small and the evidence is still
daily-data event-study evidence rather than a definitive stylized fact.
