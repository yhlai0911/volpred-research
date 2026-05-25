# Paper 1 — Replication Scripts

**Paper**: Leverage Direction Matters (`paper/leverage-direction/`)
**Purpose**: entry points for regenerating tables, figures, and the
reproduce-gate report from the pinned data in `../data/`.
**Last updated**: 2026-05-25

---

## 1. End-to-end verification

The single entry point that verifies every paper number against its source
JSON is:

```bash
uv run python paper/leverage-direction/reproduce.py
```

Outputs `paper/leverage-direction/reproduce_report.json` and prints a
per-Check table to stdout (MATCH / NOTE / MISMATCH / UNTRACEABLE). Exit
code 0 requires `0 MISMATCH`; `alert_level` is `green` at ≥95% traceable
match rate, else `amber` (currently `amber`, pass_with_untraceable; structural
gaps in Tables 1/2/6/7/8/11/14 documented in `reproduce_report.json`).

This is the **only** script that must run before any submission, review, or
status flip per `.claude/rules/paper-workflow.md` §Reproduce gate.

---

## 2. Tables

Tables are typeset inline in `../tables.tex` (LaTeX), not regenerated from
scripts. Each Table row carries an inline `% source:` comment pointing at the
JSON field, per `.claude/rules/paper-workflow.md` §Table row → JSON source.

To regenerate a particular table's numbers, rerun the corresponding K
experiment listed in `../experiments.md` and verify diff via `reproduce.py`.
Example for Table 8 (window-size robustness):

```bash
uv run python experiments/k1188/k1188.py
uv run python paper/leverage-direction/reproduce.py  # confirms 15/15 MATCH
```

---

## 3. Figures

Seven figure generators in `scripts/figures/`. Full per-figure status
(COMPLETE / PARTIAL / MISSING) is documented in
`scripts/figures/data_source.md`.

```bash
# Run all seven
uv run python paper/leverage-direction/scripts/figures/fig_gamma_mechanism.py
uv run python paper/leverage-direction/scripts/figures/fig_mdd_comparison.py
uv run python paper/leverage-direction/scripts/figures/fig_kurtosis_reduction.py
uv run python paper/leverage-direction/scripts/figures/fig_rolling_gamma.py
uv run python paper/leverage-direction/scripts/figures/fig_vix_garch_ratio.py
uv run python paper/leverage-direction/scripts/figures/fig_cumulative_returns.py
uv run python paper/leverage-direction/scripts/figures/fig_vix_weight_timeline.py
```

All scripts:
- Pin `SEED = 42`
- Write PNG to `../figures/fig_<name>.png` (PDFs in paper root preserved)
- Mark synthetic / placeholder regions clearly when underlying daily CSV is
  not yet bundled

Three figures (fig_gamma_mechanism, fig_mdd_comparison, fig_kurtosis_reduction)
are COMPLETE today. The other four switch from labelled placeholder to real
data the moment the corresponding CSV is added to `scripts/figures/data/`
— gap list in `scripts/figures/data_source.md`.

---

## 4. Re-fitting an experiment from scratch

Experiments are pinned in two locations:

| Path | Purpose |
|---|---|
| `../experiments/k<NNN>_<slug>.py` | Paper-folder shim (small copies for K799 / K802 / K824v2 / K902) |
| `../../../experiments/k<NNN>/k<NNN>.py` | Canonical project K-exp tree (full provenance, README, run.log) |

Canonical K-experiments that back the paper's main tables:

```bash
uv run python experiments/k1185/k1185.py   # Table 4 four-config canonical
uv run python experiments/k1188/k1188.py   # Table 8 window-size robustness
uv run python experiments/k1256/k1256.py   # Sec 4.7 HM γ 3-spec
```

After any rerun, `reproduce.py` must pass with `0 MISMATCH` before commit.

---

## 5. Dependencies

Pinned in repo root `pyproject.toml`. Smoke list:
- Python ≥ 3.11
- `uv` for env management
- `pandas`, `numpy`, `scipy`, `arch` (GJR-GARCH), `matplotlib`, `statsmodels`
- `yfinance` only for refreshing snapshots (not used by `reproduce.py` itself)

No external services / credentials required to regenerate the existing
numbers and figures from the pinned data in `../data/`.

---

## 6. Cross-reference

- `../README.md` — paper status, R1 issues, snapshot pinning
- `../data_sources.md` — pinned CSV provenance + license
- `../experiments.md` — table/figure → K-id mapping
- `../results/README.md` — index of canonical result JSONs
- `../reproduce.py` / `../reproduce_report.json` — paper-wide verifier
- `../experiments/` — paper-folder shim copies
- `figures/data_source.md` — per-figure status ledger
