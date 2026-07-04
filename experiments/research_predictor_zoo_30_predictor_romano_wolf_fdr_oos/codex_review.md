# Codex Review

Verdict: CONDITIONAL_PASS

Scope reviewed:

- `research_predictor_zoo_30_predictor_romano_wolf_fdr_oos.py`
- `research_predictor_zoo_30_predictor_romano_wolf_fdr_oos_results.json`
- `predictor_zoo_audit_table.csv`
- `README.md`

Checks:

- Reproducibility: script runs under `uv run`, fixes seed at 42, and regenerates
  JSON / CSV / PNG outputs.
- Source provenance: every extracted row keeps `source_group`, `source_file`,
  and `source_field_path`; source artifacts are read-only.
- No lookahead exposure: this is a meta-audit of prior reported results and does
  not create new forecasts. The script records but does not re-time any source
  signal.
- Multiple testing: Holm and BH are implemented directly from primary p-values.
  The `rw_style_independent_maxT_p` field is explicitly labelled as an
  independent-null maxT approximation.
- Silent-fallback risk: JSON/text read failures return empty rows silently inside
  local extraction helpers. That is acceptable for this one-off experiment but
  should not be reused as ops code without observable warnings.

Important caveats:

- Formal Romano-Wolf is not claimed. The blocker is structural: historical
  experiments do not persist aligned pointwise loss-differential matrices.
- The primary extraction is conservative relative to earlier drafts, but still
  automated. It excludes diagnostics, intercept/const rows, correlation,
  Granger/lead-lag, and IS/full-sample/descriptive rows; however, it does not
  manually adjudicate whether a significant row is a useful predictor or a
  candidate-worse-than-baseline result.
- Summary-stat survivors therefore mean "statistical cells surviving this
  correction table", not "publishable positive predictor edges".

Result: acceptable as a scoped methodology / infrastructure audit. Do not use it
as a claim that formal Romano-Wolf found 34 robust external predictors.
