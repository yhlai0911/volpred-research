# Paper 3: Scripts / Reproduction Guide

**Paper**: Is Volatility Targeting Just Trend Following?

---

## Primary Entry Point

| Script | Location | Purpose |
|--------|----------|---------|
| `reproduce.py` | `paper/vt-trend-following/` | Reproducibility audit: loads K55/K54/K79/K898 JSONs, compares against paper numbers, prints MATCH / MISMATCH / UNTRACEABLE report (exit 0 = all match, 1 = mismatches, 2 = untraceable only) |

Run: `uv run python paper/vt-trend-following/reproduce.py`

**Current state**: exits with code 1 (known v2 mismatches; v3 body has already been updated to K898/K1178/K1192/K1193 canonical numbers). The mismatches are documented in `reproducibility_audit/diff_report.md` and the v3 body carries forensic notes for each.

---

## Experiment Scripts

### Paper-folder experiments (`paper/vt-trend-following/experiments/`)

| Script / JSON | Experiment | Purpose |
|---------------|-----------|---------|
| `k898_paper3_table3_supplement.py` | K898 | 5-asset dual-mechanism Table 3 supplement (2005–2026; SPY + 50/50 SPY/GLD + DIA + QQQ + IWM); VT with SHY cash, 252-day TSMOM hedge, 10k-rep block bootstrap |
| `vt_tsmom_final_n22.json` | K55 | 22-asset panel for Tables 1 & 2 (source script lives in prior experiment branches; JSON preserved here) |
| `ff5_factor_controls.json` | K54 / K71 | FF5 + MOM + BAB factor controls for Table 4 (source script preserved in storage/experiments/; JSON copy here) |
| `paper3_fixes.json` | K79 | VIX threshold sensitivity (thresholds 8–20) + 5-asset MDD cross-check (SPY/QQQ/EEM/EFA/GLD) |

Scripts for K55, K54, K71, K79 are not checked into `paper/vt-trend-following/experiments/` because they were executed in prior worktree branches. The JSON outputs are the authoritative deliverables for Tables 1, 2, 4, and the Discussion VIX-threshold sensitivity claim.

### Canonical experiments (`experiments/kXXX/`)

| Script | Experiment | Purpose |
|--------|-----------|---------|
| `experiments/k1178/k1178.py` | K1178 | CANONICAL 13-market Table 5 replication; auto_adjust=True; paper-exact ticker set {EFA, EWJ, EWG, EWU, EWA, EWC, VGK, EEM, FXI, EWZ, INDA, EWT, MCHI} |
| `experiments/k1192/k1192.py` | K1192 | CANONICAL Table 6 block-bootstrap MDD retention; monthly rebalancing per paper spec; 10k reps, block=252, seed=42 |
| `experiments/k1193/k1193.py` | K1193 | CANONICAL split-sample robustness (Section 3.3); gamma 2007–2016, TSMOM_orth 2017–2026 |

### Supporting experiments (`experiments/kXXX/`)

| Script | Experiment | Purpose |
|--------|-----------|---------|
| `experiments/k499/` | K499 | Monthly rebalancing optimality + transaction cost breakeven (daily 3.4bps, monthly 14.9bps) |
| `experiments/k507/` | K507 | 50/50 allocation dynamic-VT fails Harvey threshold |
| `experiments/k518/` | K518 | 5 pure-TF strategies (SMA, Faber, Golden, Dual Mom, MA+VT) all fail Harvey t>3.0 on SPY |
| `experiments/k533/` | K533 | Prediction-vs-allocation decoupling |
| `experiments/k568/` | K568 | 427 VT configuration sweep; 12/VIX is return-optimal |
| `experiments/k687/` | K687 | Post-correction strategy ranking (VT-on-blend, reconciliation) |
| `experiments/k688/` | K688 | CRRA utility with properly lagged signals (reconciliation) |
| `experiments/k697/` | K697 | VIX direction-vs-magnitude predictive power |
| `experiments/k488/`, `experiments/k503/` | K488 / K503 | 12/VIX formula irreducibility |

---

## Figure Generation

| Script | Output |
|--------|--------|
| `paper/vt-trend-following/figures/generate_figures.py` | Regenerates `fig1_return_decomposition.pdf` and `fig2_cross_asset_scatter.pdf` from K898 + K1178 data |

---

## Table → Script Mapping

| Paper Table / Figure | Script(s) | Output File |
|----------------------|-----------|-------------|
| Table 1 (N=22 alpha decomposition) | (prior K55 run) | `experiments/vt_tsmom_final_n22.json` |
| Table 2 (cross-sectional) | (prior K55 run) + K1193 | `experiments/vt_tsmom_final_n22.json` + `experiments/k1193/k1193_results.json` |
| Table 3 (dual mechanism 5-asset) | K898 | `experiments/k898_paper3_table3_supplement_results.json` |
| Table 4 (FF5 controls M1–M5) | (prior K54/K71 run) | `experiments/ff5_factor_controls.json` |
| Table 5 (13-market international) | K1178 | `experiments/k1178/k1178_results.json` |
| Table 6 (MDD retention block bootstrap) | K1192 | `experiments/k1192/k1192_results.json` |
| Figure 1 (Sharpe vs MDD channels) | `figures/generate_figures.py` | `figures/fig1_return_decomposition.pdf` |
| Figure 2 (ΔSharpe vs ΔMDD, N=13) | `figures/generate_figures.py` | `figures/fig2_cross_asset_scatter.pdf` |
| Discussion: VIX threshold 7.98–10.91 | K79 | `experiments/paper3_fixes.json` |
| Discussion: 5 TF strategies fail Harvey | K518 | `experiments/k518/` |
| Discussion: 427 VT configs, 12/VIX optimal | K568 | `experiments/k568/` |
| Discussion: tx cost breakeven 3.4 / 14.9 bps | K499 | `experiments/k499/` |
| Section 4.2: VIX predictive power r=0.570 / 0.042 | K697 | `experiments/k697/` |
| Section 4 reconciliation footnote (K687/K688) | K687, K688 | `experiments/k687/`, `experiments/k688/` |

---

## Full Reproduction Sequence

From a clean checkout with Python >= 3.10:

```bash
# Step 0: Audit current JSONs against paper body
uv run python paper/vt-trend-following/reproduce.py

# Step 1: Re-run K898 (Table 3, 5-asset dual-mechanism)
#   Note: K898 script writes to experiments/k898_paper3_table3_supplement_results.json
#   relative to its CWD. Run from paper/vt-trend-following/ to preserve paper-folder copy.
cd paper/vt-trend-following
uv run python experiments/k898_paper3_table3_supplement.py
cd ../..

# Step 2: Re-run canonical experiments
uv run python experiments/k1178/k1178.py
uv run python experiments/k1192/k1192.py
uv run python experiments/k1193/k1193.py

# Step 3: Regenerate figures
uv run python paper/vt-trend-following/figures/generate_figures.py
```

K55, K54, K71, K79 are not re-runnable from this package (source scripts were in prior worktree branches). Their JSON outputs are the authoritative records; `reproduce.py` verifies body numbers against them.

---

## Dependencies

```
python >= 3.10
yfinance >= 0.2.40
arch >= 6.3.0          # GJR-GARCH for K55, K1193
scipy >= 1.12
statsmodels >= 0.14    # Newey-West HAC
numpy >= 1.26
pandas >= 2.1
matplotlib >= 3.8      # Figures
```

Install: `uv pip install yfinance arch scipy statsmodels numpy pandas matplotlib`

---

## Divergence Audit

See `reproducibility_audit/README.md`, `diff_report.md`, `audit_step1_2.md`, and `nosource_rescan_report.md` for a full forensic trail of:

- Which paper numbers match their source JSONs (77% of extractable numbers verified).
- Which numbers are superseded by K898/K1178/K1192/K1193 canonical runs (body_v3 reflects these).
- Which numbers remain PENDING reconciliation (period-inconsistency, Table 4 M5 N=3740, sector r=0.163 traceability).
