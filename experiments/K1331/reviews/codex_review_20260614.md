# Codex Review — K1331

- **Date**: 2026-06-14
- **Reviewer**: Codex desktop
- **Verdict**: CONDITIONAL_PASS

## Scope Reviewed

- `experiments/K1331/K1331.py`
- `experiments/K1331/K1331_results.json`
- `experiments/K1331/README.md`

## Checks

- Experiment three-piece artifact exists: README, script, results JSON.
- `seed=42` is fixed.
- Data source, period, sample size, tickers, and limitations are recorded.
- Trading signals use explicit `shift(1)` before applying to next-day returns.
- Forecast target is next 21 trading days (`t+1..t+21`) and does not include same-day returns.
- OOS forecast comparison uses repo-standard `qlike_pointwise` and `dm_test(..., h=21)`.
- README correctly downscopes the result: realized proxy only, not option-implied DSPX or a tradable correlation risk premium.

## Findings

No blocking issue found.

Residual risks:

- Current large-cap basket introduces survivorship bias.
- Equal-weight component variance is a proxy, not a historical S&P 500 cap-weighted constituent reconstruction.
- Downside strategy improvement is partly mechanical exposure reduction; it should not be promoted as return alpha.

## Required Wording

Use: "realized dispersion/correlation proxy mean-reverts; forecast value is null; downside timing is conditional."

Avoid: "correlation risk premium captured" or "dispersion trade alpha."
