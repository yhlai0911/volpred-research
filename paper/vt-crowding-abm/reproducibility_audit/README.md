# Paper 8 Reproducibility Audit

**Paper**: When Volatility Targeting Crowds: Quantifying the Tipping Point via Agent-Based Simulation
**Date**: 2026-04-17
**Status**: COMPLETE

## Files

| File | Contents |
|------|----------|
| `main_tex_numbers.csv` | 162 numbers extracted from main.tex with paper vs. computed comparison |
| `script_output.json` | K mapping, no-source rescan, seed determinism check, param consistency |
| `diff_report.md` | Full diff analysis with (a)/(b)/(c) for each divergence |
| `README.md` | This file |

## Audit Results

- **Coverage**: 162 numbers audited (97.5% match rate)
- **Matched**: 158
- **Divergent**: 4 (1 trivial rounding, 3 methodology/documentation issues)
- **Seed determinism**: CONFIRMED DETERMINISTIC
- **Lookahead**: CLEAN
- **Critical errors**: NONE

## Primary Source

All paper numbers come from K827v3:
- Script: `paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity.py`
- Results: `paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity_results.json`

## Reproduction

```bash
uv run python paper/vt-crowding-abm/reproduce.py
```

## Key Divergences

1. **DIV-1** (trivial): ΔVol at 100% = paper 119.1% vs. computed 119.0% (±0.1% rounding)
2. **DIV-2** (methodology): Tab.3 Threshold column classification uses code's 30%-cutoff but paper footnote defines threshold as 50%-degradation. Paper text/table are correct; code metadata is mislabeled.
3. **DIV-3** (medium): K827v2 Sharpe values in sec:validation (0.43/0.18) not formally audited
4. **DIV-4** (low): "VT adoption below 5%" has no citation
