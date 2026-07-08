# Codex review - research_giacomini_rossi_fluctuation_test_volpred_dm_ledg

Review date: 2026-07-08

## Verdict

CONDITIONAL_PASS for a method-diagnosis experiment.

The script correctly refuses to run a formal Giacomini-Rossi fluctuation test
when the required chronological loss-differential path is absent. The result is
therefore a data-infrastructure null, not a forecast-superiority finding.

## Checks

- Reproducibility: PASS. `seed=42` is recorded, output JSON is written through a
  temp file and parsed before `os.replace`.
- Source integrity: PASS. The script reads `experiments/k1259/dm_ledger.json`
  and cited source JSON files only. It does not mutate K1259 or shared state.
- Candidate filter: PASS after correction. Model-pair classification uses only
  `model_a` and `model_b`, so `source_field_path` ancestors such as
  `a4f_proxy_sensitivity` cannot incorrectly convert HAR-vs-GJR rows into
  A4f/HAR rows.
- GR precondition logic: PASS. Strict GR requires date-indexed loss
  differentials; the audit found 20 A4f/HAR rows, 0 CF-Rolling rows, and 0
  pair-level raw loss series.
- Claim discipline: PASS. The results JSON marks the ledger diagnostic as
  descriptive only and explicitly rules out regime-concentration and
  predictive-superiority claims.

## Verification commands

```bash
uv run python -m py_compile experiments/research_giacomini_rossi_fluctuation_test_volpred_dm_ledg/research_giacomini_rossi_fluctuation_test_volpred_dm_ledg.py
uv run python experiments/research_giacomini_rossi_fluctuation_test_volpred_dm_ledg/research_giacomini_rossi_fluctuation_test_volpred_dm_ledg.py
uv run python - <<'PY'
import json
r=json.load(open('experiments/research_giacomini_rossi_fluctuation_test_volpred_dm_ledg/research_giacomini_rossi_fluctuation_test_volpred_dm_ledg_results.json'))
assert r['coverage']['n_a4f_har_rows']==20
assert r['coverage']['n_cf_related_rows']==0
assert r['formal_gr_precondition_audit']['raw_loss_series_found']==0
assert r['conclusion']['verdict']=='METHOD_DIAGNOSIS_NULL'
PY
```

## Caveat

This experiment should not be promoted as evidence that A4f, CF-Rolling, or HAR
wins in any regime. The only supported claim is that the current K1259 summary
ledger lacks the raw `d_t` series needed for a formal fluctuation test.
