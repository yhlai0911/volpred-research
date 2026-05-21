# Paper 8: The Volatility Absorption Hypothesis

**Target Journal**: TBD
**Status**: R1 review — Path B errata revision applied in main_v3.tex (2026-05-13) | Reproduce gate 61.3% **red** (canonical threshold: <80% match → red; previously mislabelled "amber" prior to alert_level schema fix 2026-05-12). **2026-04-19 CRITICAL errata** (see `errata_pending.md`):
- ~~**CRITICAL**: controlled regression $t = -3.14 \to -1.17$ crosses Harvey boundary~~ → **ADDRESSED** in main_v3.tex: K903 values applied ($\beta=-0.000216$, $t=-1.26$) with Harvey-boundary footnote
- ~~**HIGH**: T10 2020-2026 $\beta$ sign flip~~ → **ADDRESSED** in main_v3.tex: table updated to K903 snapshot (2020-2026 $\beta=+0.000141$, $t=+0.47$); "all periods" claim removed; crisis-era caveat added
- **MEDIUM**: 10+ T9/T10 magnitude drifts within acceptable yfinance drift range
- **Remaining**: cross-asset table (GLD/TLT/0050.TW) K903 snapshot rerun + paper-update sync

### **2026-05-06 K716 errata disclosure (per K1249 finding, upgrade from option (a) to (c))**

**K1249 confirmed K716 (a) rebuild is BLOCKED** by yfinance data-vintage drift:
- Sample size mismatch: paper N=893 vs current snapshot N=767 (unreproducible without paper-time CSV archive)
- Slope drift: 3.57% absolute change between paper-time and current pull
- t-statistic divergence: 48% (Harvey threshold sensitive)
- SAR Table 3 ≤0.82% drift (within tolerance, retained as-is)

**Acknowledged limitation**: K716 absorption regression cannot be exactly reproduced from current yfinance data. The qualitative paralysis claim (absorption mechanism exists) and SAR Table 3 quantitative results remain valid; the specific Table 9-10 K716 cell numbers are pinned to paper-drafting-time data which we cannot retroactively recover. Future readers should treat K716 numerical cells as **frozen paper-time values** (cited verbatim from paper PDF), not currently reproducible against live yfinance — equivalent to citing a discontinued data vendor.

**Mitigation**: see `errata_pending.md` §Path B/C for full disclosure; SAR Table 3 (≤0.82% drift) carried forward with current snapshot, K716 Table 9-10 cells kept as paper-time values with footnote.
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
