# Codex Review

Verdict: **CONDITIONAL_PASS**

Scope reviewed:

- `research_labor_force_growth_immigration_shock_wage_sensit.py`
- `research_labor_force_growth_immigration_shock_wage_sensit_results.json`
- `README.md`

## Checks

- Lookahead: PASS. Macro z-scores are formed from expanding prior history and
  then explicitly shifted one month before being joined to market targets:
  `signal_panel = z[SIGNAL_COLUMNS].shift(1)`. Market controls are also lagged
  with `.shift(1)`.
- Target alignment: PASS. Month `t` target is forward ETF realized variance
  over month `t` or months `t..t+2`; predictor information is from month `t-1`.
- Partial-month handling: PASS. The script drops the partial final market month,
  so incomplete June 2026 data are not treated as a full realized-volatility
  month.
- Multiple testing: PASS. All 36 ETF x horizon x signal cells are adjusted by
  Holm and Bonferroni; the support gate requires positive coefficient, `|t|>=3`,
  and Holm p < 0.05.
- Bootstrap: PASS for the selected strongest positive cell. The XLI 3m
  `wage_growth_z` coefficient has a 1,000-rep moving-block bootstrap CI above
  zero.
- Result honesty: PASS with caveat. The result is correctly downgraded to
  `CONDITIONAL_SUPPORT` because the strongest evidence is wage growth and
  composite labor stress, not the direct foreign-born labor-force proxy.

## Caveats

- The FRED/BLS series are public labor-market proxies, not true immigration-flow
  data. The experiment cannot support a clean immigration-specific causal claim.
- Most supported cells do not independently clear `t>3` in both pre-2020 and
  post-2020 subsamples. The full-sample evidence is useful as a prior, not as a
  deployable strategy.
- No trading rule, transaction-cost model, or OOS portfolio backtest is tested.

## Reproduction

Commands run:

```bash
uv run python experiments/research_labor_force_growth_immigration_shock_wage_sensit/research_labor_force_growth_immigration_shock_wage_sensit.py
uv run python -m py_compile experiments/research_labor_force_growth_immigration_shock_wage_sensit/research_labor_force_growth_immigration_shock_wage_sensit.py
uv run python - <<'PY'
import json
from pathlib import Path
p=Path('experiments/research_labor_force_growth_immigration_shock_wage_sensit/research_labor_force_growth_immigration_shock_wage_sensit_results.json')
r=json.loads(p.read_text())
assert r['verdict']['verdict']=='CONDITIONAL_SUPPORT'
assert r['test_design']['primary_family_size']==36
assert r['verdict']['positive_harvey_holm_support_count']==6
assert '.shift(1)' in r['signal_metadata']['lookahead_guard']
assert r['market_metadata']['dropped_partial_last_month'] is True
assert r['strongest_positive_bootstrap']['bootstrap']['coef_ci95_low'] > 0
assert len(r['subsample_sensitivity_supported_cells']) == 12
print('results_invariants_ok')
PY
```
