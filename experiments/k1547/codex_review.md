# Codex Source Review: K1547

- Reviewer: Codex (`codex-vscode`)
- Date: 2026-06-24
- Verdict: PASS_WITH_NULL_FINDING

## Scope

Reviewed `experiments/k1547/k1547.py`, `k1547_results.json`, generated figures, and README claims for the CTA / managed-futures ETF proxy crisis-alpha experiment.

## Checks

1. **Lookahead**: PASS. The 252-day time-series momentum signal is `np.sign(trailing_valid).shift(1)`, and VIX / SPY drawdown stress states use prior-close information via `.shift(1)`.
2. **Pre-history signal handling**: PASS after fix. The timing strategy is undefined before a valid 252-day signal exists; those dates are excluded instead of being counted as cash alpha. This prevents the 2020 Covid window from being credited to a signal that did not yet exist.
3. **Holiday / missing-row handling**: PASS after fix. The 252-day rolling momentum calculation runs on valid `CTA_EW` trading days and then reindexes to the main calendar, avoiding a single holiday NaN contaminating the next 252 rows.
4. **Statistical gate**: PASS. Stress-alpha pass requires paired excess-return `t > 3` plus block-bootstrap 95% CI lower bound above zero. The experiment does not overclaim sub-Harvey 2022 evidence.
5. **Result integrity**: PASS. Output JSON, input cache, and four figures were regenerated from the script. Verdict is a null/negative finding for the free ETF proxy, not a broad rejection of managed futures literature.

## Residual Caveats

- ETF proxy sample is short and does not represent the diversified futures universe in Moskowitz-Ooi-Pedersen or AQR-style long-history studies.
- The 2020 Covid crash cannot be used for the 252-day timing overlay because the ETF proxy lacks enough pre-crash history.
- The 2022 inflation subperiod is positive but below the project Harvey gate; it should be described as suggestive, not decisive.
