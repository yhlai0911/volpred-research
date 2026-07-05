# taiwan-vt Revision Blocker — Provenance Verification (2026-07-05)

**Verifier**: hourly-10 dispatch, main-thread provenance walk against **body_v3.tex** (the active PBFJ submission version per commit `fd77cdfb6`; `main_v3.tex` `\input{body_v3}`).
**Trigger**: `paper_pipeline_status.json` blocker = "2 HIGH: 0050.TW gamma 3-way inconsistency; 2383.TW in Table 2 not in data description".

## Verdict

| Blocker (as recorded) | Status vs current body_v3.tex | Evidence |
|---|---|---|
| 2383.TW in Table 2 not in data description | **STALE / CLEARED** | 2383.TW (ELITE Material) IS listed in §2.1 data description (`body_v3.tex:35`, "Eleven Taiwan security-level series"). `tab:gamma` (lines 141–164) lists only 2330/2317/2454/2886/0056 as individual rows — **no 2383 row**. The finding matched the deprecated long `body.tex` (`main.tex \input{body}`, line 156 has an `ELITE Material (2383)` row), not the submission version. |
| 0050.TW gamma 3-way inconsistency | **Reduced to 1 residual HIGH (re-fit enqueued)** | Canonical point estimate now **0.097** consistently across abstract (`:14`), Table 1 (`:52`, source K892 full_sample, D3 errata), Table 2 (`:147`), §3.1 (`:136`), §3.2 (`:170,176`). The old 3-way (Table2 0.087 / §4.5 0.124 / Table1) is gone; 0.087 fixed by D3 errata (commit `683ad153c`). |

## The residual (real) issue — §sec:tsmc line 457

Concentration/attribution analysis reports, as if single coherent sub-period GJR fits:
- 0050.TW: γ = **0.124**, t = **2.46**
- TSMC (2330.TW): γ = **0.054**, t = **1.07** (footnote contrasts full-sample 0.052 / 3.98)

**Neither (γ, t) pair is byte-traceable:**
- `0.124` coincides with `experiments/k900 .amplification.gamma_0050.median_gamma = 0.1248` (rolling-252d daily-refit **median**) — but that series' real `hac_t_stat = 19.857`, **not 2.46**.
- `t = 2.46` matches nothing (the `2.4688` in K900 JSON is `table_vt_results.vix_863.es_1pct`, unrelated).
- TSMC (0.054, 1.07) not in any results JSON; the section's own experiment `experiments/paper2_sec45_tsmc_vt` saved VT Sharpe + decomposition r² but **no γ estimates**.

This is a reproducibility gap (research-honesty §1), not a wording fix. The point estimate and t-stat originate from different (or unsaved) computations.

## Resolution routed (this fire)

- `experiments/paper2_sec45_gamma_refit/refit_concentration_gamma.py` re-estimates GJR-GARCH(1,1) Normal Constant-mean MLE (K892 canonical spec) for 0050.TW (split-cleaned) and 2330.TW over `full_vt` (2010–2026) and `common_vt` (2020–2026) windows + a rolling-252d median reconciliation → coherent, reproducible (γ, t) pairs.
- **Enqueued to compute_queue** (`paper2_sec45_gamma_refit`, heavy-compute rule). Followup `paper_body` task (P2) will: Codex-review script+numbers → replace `body_v3.tex:457` with a reproducible coherent pair + `% source` comment → update footnote → `xelatex main_v3.tex` → update tracker.
- Honesty guard in brief: if the re-fit t-stats change the "TSMC sub-period insignificant" narrative, adjust the narrative to match (the qualitative claim *index leverage > constituent leverage* is independently supported by the full-sample Table 2). No fabrication.

## Pipeline tracker

`storage/paper_pipeline_status.json` taiwan-vt `blocker` updated to this verified state; `blocker_verified_at` = 2026-07-05.
