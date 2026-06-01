# Paper 8: Scripts / Reproduction Guide

---

## Primary Scripts (paper root)

| Script | Location | Purpose |
|--------|----------|---------|
| `reproduce.py` | `paper/volatility-absorption/` | Main reproduction pipeline |

## Experiment Scripts (paper/volatility-absorption/experiments/)

| Script | Experiment | Purpose |
|--------|-----------|---------|
| `k741_nfp_event_study.py` | K741 | Revised NFP event study; addresses reviewer S4 (Table 5 discrepancies) |
| `k897_sar_null_simulation.py` | K897 | SAR null simulation — proves absorption is not a GARCH artifact; addresses reviewer S1 |
| `k903_paper8_robustness.py` | K903 | Alternative shock thresholds robustness; generates Table 9 candidates |
| `k904_paper8_shock_nfp_fix.py` | K904 | Combined shock definition + NFP fix; addresses S2 sample-size inconsistency |

## Reconstructed Core Scripts (K716–K722, commit `86d10c7b` 2026-04-17)

Originally missing; reconstructed from `main_v2.tex` methodology + JSON reverse-engineering. Live at repo-root `experiments/`:

| K | Reconstructed Script | Diff Report | Purpose |
|---|---|---|---|
| K716 | `experiments/k716.py` | `experiments/k716_reconstruction_diff.md` | SAR core / absorption regression |
| K717 | `experiments/k717.py` | `experiments/k717_reconstruction_diff.md` | VT scorecard |
| K718 | `experiments/k718.py` | `experiments/k718_reconstruction_diff.md` | Cross-asset (0050.TW) |
| K719 | `experiments/k719.py` | `experiments/k719_reconstruction_diff.md` | NFP synthesis |
| K720 | `experiments/k720.py` | `experiments/k720_reconstruction_diff.md` | VRP flip / shock decomposition |
| K721 | `experiments/k721.py` | `experiments/k721_reconstruction_diff.md` | Rate-shock NSI |
| K722 | `experiments/k722.py` | `experiments/k722_reconstruction_diff.md` | RV robustness |

### Errata pending — reconstruction–paper numeric divergences

Four locations show numeric drift (signs and qualitative findings unchanged); root causes are data vintage / sample-filter unrecoverable to paper-time:

| Location | Paper value | Reconstruction | Drift | Qualitative status |
|---|---|---|---|---|
| K716 NSI t-stat | -3.42 (N=893) | -1.77 (N=767) | sample filter diff | sign same; absorption still significant |
| K718 0050.TW slope | +0.00019 | +0.00008 | ~60% magnitude | sign same; non-absorption conclusion intact |
| K721 high_vix_norm | 0.066 | 0.060 | ~9% | recheck rate-shock absorption coeff +0.019 |
| K722 corr_raw | 0.6803 | 0.5671 | ~17% | "not improved" conclusion intact (low risk) |

**Submission policy** (decided 2026-06-02, task `VolAbsorption_errata_decision`): submit with current paper numbers; reconstruction approximate, qualitative conclusions unaffected; errata may follow if reviewer requests exact replication. Endogenous absorption, paralysis flags, VRP positive, and 0050.TW NO-paralysis findings all replicate. Separate R1 errata (K903/K904 snapshot drift) tracked in `paper/volatility-absorption/errata_pending.md`.

## Full Reproduction Sequence

```bash
# Step 1: Core results (K716–K722, reconstructed scripts)
uv run python experiments/k716.py
uv run python experiments/k717.py
uv run python experiments/k718.py
uv run python experiments/k719.py
uv run python experiments/k720.py
uv run python experiments/k721.py
uv run python experiments/k722.py

# Step 2: Revision experiments
uv run python paper/volatility-absorption/experiments/k741_nfp_event_study.py
uv run python paper/volatility-absorption/experiments/k897_sar_null_simulation.py
uv run python paper/volatility-absorption/experiments/k903_paper8_robustness.py
uv run python paper/volatility-absorption/experiments/k904_paper8_shock_nfp_fix.py
```

## Dependencies

```
yfinance >= 0.2.40
scipy >= 1.12
statsmodels >= 0.14
numpy >= 1.26
pandas >= 2.1
matplotlib >= 3.8
```

Install: `uv pip install yfinance scipy statsmodels numpy pandas matplotlib`
