# K1652 Codex Review

Reviewer: Codex primary path  
Date: 2026-07-06  
Verdict: CONDITIONAL_PASS_MIXED

## Scope

Reviewed:

- `experiments/k1652/k1652.py`
- `experiments/k1652/k1652_results.json`
- `experiments/k1652/README.md`
- `experiments/k1652/k1652_basis_stress.png`

## Findings

### Fixed During Review

1. Early high-vol labels were initially vulnerable to `NaN` threshold mislabeling: `(rv > NaN).astype(float)` can become 0. The script now uses:

```python
high_vol = (native_rv > threshold).astype(float).where(threshold.notna())
```

This makes rows without an expanding threshold drop out through the normal `dropna` path.

2. The first result version reported full augmented QLIKE wins only. Because liquid-staking basis can be structural, the script now also reports `stress_only_robustness`, excluding basis level and wrapped-token absolute return.

3. The results JSON now has top-level `statistical_tests` and `literature_context` sections, not only pair-level metrics.

## Checks

- Lookahead: PASS. All raw features are shifted by one day via `raw_features.shift(1)`.
- High-vol threshold: PASS after fix. Expanding 75th percentile is shifted by one day.
- Seed: PASS. `SEED=42`.
- JSON integrity: PASS. Results are written via temp file, parsed, and atomically replaced.
- DM/QLIKE direction: PASS. QLIKE uses project `qlike_pointwise(actual, predicted)` and DM compares augmented losses against baseline losses; negative t means augmented lower loss.
- Overclaim control: PASS. README explicitly says daily data cannot estimate information share and classification evidence is weak.

## Residual Caveats

1. `cbETH` basis is not a pure peg-stress measure; it embeds liquid-staking economics and can be structurally large.
2. QLIKE improvements pass Harvey for 3/4 pairs, but MSE does not pass and high-vol classification AUC is flat or worse.
3. Yahoo Finance volume is not DEX depth, bridge supply, or liquidity fragmentation.
4. This is one chronological OOS split, not a full rolling production forecast.

## Conclusion

The experiment is sound enough for knowledge storage as a conditional/mixed finding. It should not be promoted as a publication-ready wrapped-token price-discovery result. The most defensible next step is BTC/WBTC with high-frequency CEX/DEX prices plus on-chain liquidity / bridge supply.
