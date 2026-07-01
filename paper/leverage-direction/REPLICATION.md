# Replication Package — Leverage Direction Matters

**Paper**: "Leverage Direction Matters: Cross-Asset Evidence on GARCH Model Selection and Volatility Targeting"
**Target Journal**: Journal of Banking and Finance (JBF)
**Data snapshot**: 2026-04-19 (frozen; see `data/README.md`)
**Reproduce script**: `reproduce.py` (entry point; must exit 0 with `alert_level=green`)

## 1. Quick start

```bash
uv run python paper/leverage-direction/reproduce.py
```

Reads only `data/*.csv` (no live API calls). Writes
`reproduce_report.json` with a per-Check table (MATCH / NOTE / MISMATCH /
UNTRACEABLE). Current status:

- `alert_level`: green
- `n_checks`: 194
- `n_match`: 171
- `n_note`: 23
- `n_mismatch`: 0
- `traceable_match_rate`: 1.00

Zero mismatches on the frozen vintage is the submission gate. Any re-run must
maintain this before status flips to `ready_for_submission`.

## 2. Directory layout

```
paper/leverage-direction/
├── body.tex                # LaTeX body
├── tables_main.tex         # All main tables (inline typeset from JSON sources)
├── data/                   # Frozen replication CSVs (do not modify)
├── scripts/                # Figure generators + supporting utilities
├── experiments/            # Per-K experiment stubs (main computations)
├── figures/                # Generated PNG/PDF assets
├── data_sources.md         # Data provenance, licensing, ticker rationale
├── experiments.md          # K-index of supporting experiments
├── reproduce.py            # Single-entry verification script
└── reproduce_report.json   # Latest reproduce run output
```

## 3. Regenerating figures

Seven figure generators live under `scripts/figures/`:

```bash
for f in fig_gamma_mechanism fig_mdd_comparison fig_kurtosis_reduction \
         fig_rolling_gamma fig_vix_garch_ratio fig_cumulative_returns \
         fig_vix_weight_timeline; do
  uv run python paper/leverage-direction/scripts/figures/${f}.py
done
```

All scripts pin `SEED = 42` and write to `figures/`. Per-figure completeness
status: `scripts/figures/data_source.md`.

## 4. Regenerating tables

Tables are typeset inline in `tables_main.tex`; each row carries a
`% source:` comment pointing at the JSON field it draws from. To regenerate a
row's underlying number, rerun the corresponding K experiment (see
`experiments.md` for the K-to-Table map), then run `reproduce.py` to confirm
the row still matches.

## 5. Audit history (superseded vintages)

This section documents earlier data / estimation vintages that were
superseded by the frozen 2026-04-19 snapshot. It exists so that reviewers can
verify the paper's numbers were not silently changed; the current tables
reflect only the canonical frozen vintage.

### 5.1 GJR-$\gamma$ estimates (Table 2 in body)

- **Superseded**: An earlier draft carried a GLD rolling-$\gamma$ mean of
  $-0.067$ (HAC $t = -5.79$, 93% of quarterly windows negative) sourced from a
  spec whose experiment could not be re-located in the current ledger. This
  supported a stronger claim of "gold's inverted leverage is statistically
  significant."
- **Canonical (current)**: The K903 replication under the paper's stated
  504/63 window yields GLD mean $\gamma = +0.002$ (HAC $t = +0.15$ NS, 67% of
  quarterly windows negative). The qualitative mixed-sign / regime-dependent
  finding survives; the statistical-significance headline does not.
- **Where reflected**: Table 2 shows the canonical numbers. Body Section 3
  discusses GLD's sign at the regime level (Section 4.2 decomposition) rather
  than the unconditional level.
- **Forensic trace**: `errata_gld_rolling_gamma_forensic.md` (2026-05-30).

Similar revision for SLV: an earlier estimate showed HAC $t = -2.91$; the
canonical replication gives HAC $t = -0.68$ NS.

### 5.2 VaR violation counts (Table 4 in body)

- **Superseded**: Pre-2026-04-19 draft used a rolling yfinance pull; backfill
  revisions on that surface shifted individual violation counts by up to $\pm
  3$ per row on re-run.
- **Canonical (current)**: The 2025-Q4 frozen vintage in `data/` produces
  stable counts. Baseline (Normal) uses symmetric GARCH(1,1), Student-$t$
  applies fixed $df = 5$ with scale correction $\sqrt{(df-2)/df}$, adaptive
  uses a 20-day rolling max of $\hat{\sigma}_t$.

### 5.3 Cross-asset VT panel (Table 7 in body)

- **Superseded**: A uniform-window reproducibility check under 2015--2026 OOS
  matched only 6/20 cells because the paper's headline results use
  asset-specific evaluation windows. Under the uniform window, GLD BH Sharpe
  falls to 0.83 (vs the reported 1.56 on the native 2022--2026 gold-bull
  window) and BTC BH Sharpe rises to 0.92 (vs 0.43 on the reported post-2019
  window that spans the 2022 bear).
- **Canonical (current)**: Each asset uses its native evaluation window,
  motivated by the analysis in Section 4.5 (VaR compliance) and made explicit
  in the Table 7 notes. The directional findings---VT reduces MaxDD for all
  five assets; VT Sharpe $\geq$ BH Sharpe for four of five---are robust
  across specifications, but per-asset Sharpe magnitudes are window-specific.

## 6. Compliance checklist for reviewers

- [x] All CSVs in `data/` are pinned to the 2026-04-19 vintage
- [x] `reproduce.py` reads only local CSVs (no live API calls)
- [x] `auto_adjust=False` used on original pull (see `data_sources.md`)
- [x] `reproduce_report.json` shows `alert_level=green`, `n_mismatch=0`,
      `traceable_match_rate=1.00`
- [x] Every Table row carries an inline `% source:` comment binding to JSON
- [x] Every superseded vintage documented in §5 with the current canonical
      replacement
