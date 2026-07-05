# K506 Codex Re-review — 2026-07-05 Methodology Hardening

**Reviewer**: Codex CLI
**Verdict**: **PASS**（可作內部 no-deploy / null-result 決策；knowledge 寫入仍需走正式 writer/gate）
**Scope**: follow-up task `experiment_k506_methodology_hardening`

## What Changed

The rerun fixes the three blockers from `codex_review_20260705.md`:

1. **Rebalance channel**: monthly rebalance days now decompose 0050 return into close-to-open and open-to-close legs. The old weight earns the overnight gap; the new target weight earns only the tradable open-to-close leg. Between monthly rebalances, weights drift with returns rather than being implicitly reset daily.
2. **Calendar as-of**: EWT realized volatility and VIX use `merge_asof(..., allow_exact_matches=False)` from US calendars to Taiwan trading dates. This uses the latest US close strictly before the Taiwan trading date, including US-only trading days during Taiwan holidays, without leaking same-calendar-day US closes.
3. **Transaction costs**: K625 costs are now side-aware: buy = 4.275bp, sell = 14.275bp. The script no longer deducts the full 18.55bp round-trip cost on every absolute weight change.

The hardening also found and fixed a fourth issue:

4. **0050.TW split artifact**: the local cache's `Adj Close` still contained a 2014-01-02 close ratio of 0.249361. The script now detects split-like jumps and scales prior adjusted OHLC by 0.25. This removes the false 2014 crash from returns and realized volatility.
5. **EWT provenance**: the 2010-2021 EWT window is now frozen as `experiments/k506/data/EWT_2010_2021_yfinance.csv`; reruns use the repo-local snapshot before any yfinance fallback.

## Hardened Results

- Data range: 2010-02-04 to 2021-12-30.
- OOS pooled days: 2447.
- Cross-OOS score: VT+VS wins 2/5; VT wins 3/5.
- Pooled DM: t=-1.9050, p=0.0569.
- Multiple testing: Bonferroni p=0.3414; BH p=0.1818.
- Harvey: VT-only t=2.903; VT+VS t=2.829; both below the t > 3.0 threshold.
- Verdict from `results.json`: `FAIL — VT+VolSpread does NOT consistently outperform. Do NOT deploy.`

## Research Integrity Assessment

The original MARGINAL 3/5 result is superseded. Under the hardened tradable specification, the overlay fails the pre-stated win-count gate and remains insignificant after multiple-testing correction. The result is conservative and does not support deployment.

No `knowledge.json` write was made in this Codex task. That is intentional: project governance requires the formal writer/gate path for knowledge materialization.

## Residual Notes

- The split repair is a transparent heuristic for discrete split-like jumps. It correctly catches the 2014 0050.TW 4-for-1 jump in this sample, but any future reuse should keep the detected event list in the result artifact.

## Disposition

K506 is suitable as an internal null-result / do-not-deploy finding. It is not a positive strategy result and should not be used to justify the VT+VolSpread overlay. Any `knowledge.json` materialization should still be done by the formal writer/gate path, not by manual JSON edits.
