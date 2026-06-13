# Codex 24h Source Review: mile_42b4330c

**Article**: `mile_42b4330c` — 市場一緊張就換另一套模型，真的會更安全嗎？SPY 給的答案不算樂觀

**Experiment**: `K480`

**Date**: 2026-06-12

**Verdict**: FAIL, corrected with errata

## Scope

This review checked whether the production article's numerical claims and methodological framing are supported by:

- `storage/reports/feed.json`
- `storage/drafts/k480_general_draft.md`
- `experiments/k480/k480_regime_tool_selection.py`
- `experiments/k480/k480_regime_tool_selection_results.json`
- `storage/memory/knowledge.json`

## Findings

### HIGH: Same-day VIX is used for same-day regime selection

The script forecasts each OOS date using a rolling window that ends before that date, but then stores same-day `^VIX` close at `vix_arr[i]` and uses it to select `RS_Binary` and `RS_Ternary` for the same target date. This violates the strict tradable timing convention for a switching rule unless the article explicitly frames the rule as a diagnostic regime split.

Relevant source points:

- `vix_arr[i] = feat.iloc[oos_loc]['VIX']`
- `RS_Binary`: `if vix_arr[i] < 20`
- `RS_Ternary`: `if vix_arr[i] < 15` / `elif vix_arr[i] >= 25`

The results file already acknowledges this limitation: "Uses same-day VIX - in practice need previous-day VIX for true out-of-sample."

Impact: the article's conservative conclusion is not overturned. Same-day VIX gives the switching rules more information than a real ex-ante rule would have, yet they still fail to match GJR's VaR pass rate. The public article still needed an errata note because the original wording could be read as a tradable rule.

### MEDIUM: Experiment README was placeholder-only

`experiments/k480/README.md` contained only planning placeholders, despite the experiment being published and used in a production article. This violated the experiment trilogy requirement. The README has been replaced with a source-bound summary, method, caveat, and artifact list.

### PASS: Article headline numbers are traceable

The following article claims match `k480_regime_tool_selection_results.json`:

- 50/50 ensemble average QLIKE rank: 1.8
- RS_Ternary average QLIKE rank: 2.0
- GJR average QLIKE rank: 4.2
- GJR VaR pass count: 7/10
- RS_Ternary VaR pass count: 5/10
- 50/50 ensemble VaR pass count: 3/10

## Actions Taken

- Added the same-day VIX caveat and conclusion-preservation note to the article draft.
- Updated the production article through `scripts/publish_draft.py --update`.
- Rebuilt `experiments/k480/README.md` from existing script/results without changing results.

## Follow-Up

A future K480 follow-up can rerun the switching comparison using `VIX.shift(1)` and IS-estimated VaR mean. That would be a new experiment, not a manual correction to the existing results.
