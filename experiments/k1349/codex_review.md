# Codex Review: K1349

## Scope

Reviewed `experiments/k1349/K1349.py`, reran the experiment, checked JSON/CSV/PNG outputs,
and audited the lookahead and 0050.TW cleaning safeguards.

## Findings

No blocking issue found for the pilot-only conclusion.

Important checks:

- `clean_tw50_data` is imported and applied as a daily close sanity path. It made `0` adjustments,
  as expected for 2026-only 5-minute bars.
- HAR and BPV features use explicit `shift(1)` lagging before forecast-date alignment.
- Expanding OOS fits only prior rows: `train = df.iloc[:pos]`.
- The script does not impute missing 5-minute bars. It reports 94 usable days, 53-54 bars/day,
  and 0 large intraday gap days.
- The verdict correctly stays `PILOT_ONLY_INSUFFICIENT_OOS` because OOS N is 34/33, below the
  project's 252-day minimum.

## Verification

Commands run:

```bash
uv run python -m py_compile experiments/k1349/K1349.py
uv run python experiments/k1349/K1349.py
jq '{data_quality, forecast_evaluation, verdict}' experiments/k1349/K1349_results.json
file experiments/k1349/*.png
```

Outputs checked:

- `K1349_results.json` verdict: `PILOT_ONLY_INSUFFICIENT_OOS`.
- Intraday RV OOS N: `34`.
- Total RV OOS N: `33`.
- PNG files are non-empty and render expected RV / QLIKE / intraday-pattern plots.

## Residual Risk

This is a 2026-only yfinance 5-minute sample. It is suitable for pipeline validation and pilot
diagnostics, not for paper-grade HAR-RV claims or strategy onboarding.
