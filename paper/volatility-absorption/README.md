# Paper 8: The Volatility Absorption Hypothesis

**Target Journal**: TBD
**Status**: R1 review — 5 SEVERE, needs major revision | Reproduce gate 61.3% **red** (canonical threshold: <80% match → red; previously mislabelled "amber" prior to alert_level schema fix 2026-05-12). **2026-04-19 CRITICAL errata identified** (see `errata_pending.md`):
- **CRITICAL**: controlled regression $t = -3.14 \to -1.17$ crosses Harvey boundary under K903 snapshot rerun
- **HIGH**: T10 2020-2026 $\beta$ sign flip (paper -0.00035 vs snapshot +0.000139) — "absorption all periods" claim breaks for COVID/inflation era
- **MEDIUM**: 10+ T9/T10 magnitude drifts within acceptable yfinance drift range
- **Gate history**: 50.7% → 61.3% via Sub6 T6 5 (a) 修論文 + T5 (c) footnote; CRITICAL/HIGH require paper body revision before submission (Path B recommended: research-honest crisis-era caveat)
**Pages**: 38 | **Citations**: 37

## Data Sources
- SPY: yfinance
- VIX: yfinance
- NFP dates: manual

## Reproduction
```bash
uv run python paper/volatility-absorption/reproduce.py
```

## Known Issues
- S1: Null simulation → K897 proves absorption is real (not GARCH artifact)
- S2: Table 5 sample-size inconsistency
- S3: Tables 9-10 fully untraceable
- S4: Table 6 NFP discrepancies
- Missing .py scripts for K716-K722

## Self-Contained Index (2026-04-17)

| File | Status |
|------|--------|
| `data_sources.md` | ✅ All data sources documented |
| `scripts/README.md` | ✅ Reproduction guide; missing K716-K722 scripts noted |
| `results/README.md` | ✅ Table → JSON source mapping |
| `figures/` | ✅ Directory created (no figures in current draft) |
| `experiments.md` | ✅ Full K-number index (K716–K904) |

## Supporting Experiments (K Index)

| K | Title | Key Result |
|---|-------|-----------|
| K716 | Absorption regression (SPY) | Shock amplification ratio; VIX regime binning |
| K718 | Cross-asset absorption | Cross-asset absorption coefficients |
| K719 | NFP event study (original) | NFP day volatility by VIX regime |
| K720 | Absorption by shock type | Positive vs negative shock asymmetry |
| K721 | VRP by regime | VRP narrowing at high VIX |
| K722 | Hedging cost-benefit | Cost-benefit by VIX regime |
| K741 | NFP event study (revision) | Revised; addresses S4 |
| K897 | SAR null simulation | Absorption is real, not GARCH artifact |
| K903 | Robustness | Alternative shock thresholds |
| K904 | Shock + NFP fix | Combined S2+S4 fix |
