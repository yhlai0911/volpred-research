# Codex Review — research_conditional_sequential_mcs

**Verdict**: PASS with explicit scope limitations.

## Checks Performed

- `python -m py_compile experiments/research_conditional_sequential_mcs/research_conditional_sequential_mcs.py`
- `python experiments/research_conditional_sequential_mcs/research_conditional_sequential_mcs.py`
- `jq '{experiment_id, findings_count: (.main_findings | length), limitations_count: (.limitations | length), figure}' experiments/research_conditional_sequential_mcs/research_conditional_sequential_mcs_results.json`
- PNG non-empty / dimensions checked via PIL.

## Review Notes

1. **No fabricated loss series**: the script only reads K1259 `dm_ledger.json` and does not reconstruct missing per-day losses.
2. **Conditional scope is honest**: regime labels are taken only from explicit `period` / `source_field_path` strings; no date-based recession or VIX labels are inferred.
3. **Multi-asset rows are not misassigned**: conditional rows are marked as `multi_asset`, preserving the ambiguity instead of forcing them into SPY or another ticker.
4. **Sequential scope is honest**: K-number prefix is reported as an evidence-arrival proxy, not calendar-time sequential inference.
5. **Randomness is pinned**: MCS bootstrap uses `seed=42`, `B=1000`.

## Residual Risk

- The conditional result is a coverage audit plus pilot MCS, not a publishable CMCS claim.
- True CMCS / CSPA / JRSS-B sequential MCS requires dated per-observation losses by model and regime.
- `normal_proxy` has only 6 usable rows, so it should not be cited as substantive evidence beyond "coverage insufficient".

