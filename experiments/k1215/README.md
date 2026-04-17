# K1215 — K1211 Paper 2 §5 markdown draft revision integrating K1213 AU resolution

**Status**: COMPLETED — revised markdown draft produced for main-thread cherry-pick.
**Date**: 2026-04-17 (executed 2026-04-18 UTC).
**Worktree**: `agent-a875c734`.
**Task type**: pure writing + canonical number lookup (**no new estimation**).
**Random seed**: 42 (unused — no sampling; declared for reproducibility).
**Predecessor**: K1211 `k1211_draft.md` (commit 9efffe4b).
**Trigger**: K1213 `ABOVE_LADDER_OVERTURNED` verdict (commit c34d0546)
published **after** K1211 draft was produced. K1211 §5.5 framed AU as
below-ladder residual (K1171 pooled θ_rel = 0.150) pending K1210 forensic;
K1213 overturned that framing with a 100-start multi-start resolution
placing AU at θ_rel ∈ [1.07, 1.48] above the ladder. Without K1215,
K1211 §5.5 text would be internally contradicted by K1213 canonical
AU and risk main-thread cherry-pick of stale narrative into
`body_v4.tex`.

---

## 1. Purpose

K1215 delivers a **revised markdown draft** of Paper 2 §5 that
supersedes K1211's §5.5 with K1213 findings while preserving K1211
§§5.1–5.4 and §5.6 verbatim (with only light cross-reference edits in
§5.1 for the K1213 Spearman input and in §5.6 for the K1207
re-interpretation under the K1213 AU canonical). §5.7 FINAL narrative
commitment is rewritten to reclassify AU from mirror-image below-ladder
residual to above-ladder EM-scale residual (AU/BR/CA/IN/MX cluster).

**K1215 does not write to `paper/*/body_v?.tex`, does not add new
estimation, does not compute new statistics.** All numbers are verbatim
from source experiment JSONs (K1165–K1213). K1215 extends the K1211
source traceability tree by exactly two entries: K1210 forensic and
K1213 multi-start resolution.

## 2. Deliverables (all within `experiments/k1215/`)

| File                          | Purpose                                                                            |
|-------------------------------|------------------------------------------------------------------------------------|
| `k1215_revised_draft.md`      | Paper 2 §5 rewrite draft in Markdown — full K1211 body with §5.5 replaced + light §5.1/§5.6/§5.7/Table 5 edits to integrate K1213. Ready for cherry-pick into `body_v4.tex`. |
| `k1215_revision_stats.json`   | Before/after diff summary (K1211 vs K1215): per-section word counts, numerical changes, source-experiment extension, cherry-pick checklist. |
| `README.md`                   | This file — adoption path, traceability, compliance checks.                        |

No new figures are produced. Main thread should re-use existing K1204
Figures 5A–5E and K1207 Figure 5F; K1215 flags **Figure 5G** as a new
figure slot filled by the two K1213 PNGs
(`k1213_theta_eav_hist.png` + `k1213_ll_vs_theta_scatter.png`) which
support the §5.5.2 narrative on basin bimodality.

## 3. Source traceability (verbatim commits)

| Source experiment | Source commit | Source file(s)                                                                                  |
|-------------------|---------------|--------------------------------------------------------------------------------------------------|
| K1165             | `11c3f4bf`    | `experiments/k1165/k1165_results.json`                                                           |
| K1166             | `db9c41ef`    | `experiments/k1166/k1166_results.json`                                                           |
| K1168             | `7d2ee0ef`    | `experiments/k1168/k1168_results.json`                                                           |
| K1171             | `17436274`, `051e840b`           | `experiments/k1171/k1171_results.json`                                      |
| K1172             | `8c226669`, `a837beaf`           | `experiments/k1172/k1172_results.json`                                      |
| K1173             | `ea5c6340`, `e604ed70`           | `experiments/k1173/k1173_results.json`                                      |
| K1163             | `158781aa`, `5ea1ecf1`           | `experiments/k1163/k1163_results.json`                                      |
| K1204             | `cf5188eb`, `6e23e593`           | `experiments/k1204/k1204_results.json` + Figures A–E                        |
| K1207             | `bd365d27`, `760ffb4e`           | `experiments/k1207/k1207_results.json` + 3 PNG                              |
| **K1210 (new vs K1211)** | **`03a94d23`**       | `experiments/k1210/k1210_results.json` + `k1210_figA_cadence.png` + `k1210_figB_jitter.png` |
| **K1213 (new vs K1211)** | **`c34d0546`**       | `experiments/k1213/k1213_results.json` + `k1213_theta_eav_hist.png` + `k1213_ll_vs_theta_scatter.png` |

K1211 predecessor commit: `9efffe4b` (K1211 draft produced before K1213
landed; K1210 flagged as pending in K1211 §5.5). K1215 is the
canonical successor; main-thread cherry-pick should use **K1215 §5.5
in place of K1211 §5.5**, and K1215 §5.1/§5.6/§5.7/Table 5 for
consistency.

## 4. Main-thread adoption path (cherry-pick checklist)

1. **Read**: `experiments/k1215/k1215_revised_draft.md` end-to-end
   (~2,700 words including Table 5 + §5.5 five subsections).
2. **Supersede**: treat `experiments/k1211/k1211_draft.md` §5.5 as
   obsolete; do **not** cherry-pick K1211 §5.5 language. Use K1215
   §5.5 (K1171 → K1210 → K1213 resolution narrative).
3. **Light edits to K1211 §5.1**: one paragraph now notes Panel Harvey
   t invariance under K1213 AU revision; Spearman ρ for N=13 updated
   from +0.385 (K1171 retracted) to +0.418 (K1213 canonical).
4. **Light edits to K1211 §5.6**: K1207 AU amplification (+31%) is
   reported with K1213 caveat (basin-A input, sensitivity to basin
   choice). Pool-level sector-orthogonality conclusion unchanged.
5. **§5.7 FINAL fully replaced**: three caveats updated — (ii) now
   reads "EM above-ladder residuals — BR/IN/MX originally + AU added
   post-K1213 multi-start resolution (all above-ladder, differing
   magnitudes)"; §5.7 closing sentence reworded — no remaining open
   residual after K1213 resolution; only magnitude heterogeneity
   remains for future work.
6. **Table 5 updated**: Iter 5 (K1171) kept for traceability but marked
   "*retracted*"; new row Iter 5′ (K1213) added with AU θ_rel=1.476,
   primary ρ=+0.418, p=0.156, Panel Harvey t=3.808 (invariant).
7. **Figure update**: add Figure 5G slot referencing K1213 basin
   bimodality PNGs; annotate Figure 5A with the K1213 ρ=+0.418 point;
   add AU marker to Figure 5D above-ladder cluster.
8. **Cite**: bibliography additions required beyond K1211's set —
   McCullough & Vinod (2003) for multi-start methodology; Hansen
   (1982) for MLE local-minimum pathology; K1210 and K1213 K-entries
   once main thread records them in `storage/memory/knowledge.json`.
9. **Compile**: `xelatex main_v4.tex` then `uv run volpred ops
   paper-update --paper-id <paper2-id>`.
10. **Integrity re-check**: re-run K1204 32/32 shared-key assertion
    under the K1213 AU canonical (the AU θ_rel field in K1171's
    per-market summary needs a main-thread errata note pointing to
    K1213).

## 5. Compliance checklist (CLAUDE.md)

| Rule                                                                               | Status |
|------------------------------------------------------------------------------------|:------:|
| No `.tex` writes from worktree agent                                               | PASS — only `.md`, `.json` output |
| Numbers verbatim from source JSONs                                                 | PASS — K1211 trajectory + K1213 multi-start canonical |
| Seed 42 declared (no sampling; declarative)                                        | PASS   |
| Worktree only touches `experiments/k1215/`                                         | PASS   |
| No shared-state modification (feed, knowledge, supabase, mirror)                   | PASS   |
| `research_program.md` / `knowledge.json` updates reserved for main thread          | N/A — not attempted |
| Paper narrative state machine — ≥3 complementary experiments for decision          | PASS (9 K1211 set + K1210 + K1213 = 11 total) |
| Cross-experiment numerical divergence halt check                                   | PASS — K1211 trajectory unchanged; K1213 supersedes K1171 AU row only; no other conflicts |
| `paper/*/body_*.tex` untouched                                                     | PASS   |
| Commit on completion                                                               | PENDING — will commit after README finalised |

## 6. Numerical change summary (K1211 → K1215)

| Quantity                                      | K1211 value        | K1215 value        | Source               |
|-----------------------------------------------|--------------------|--------------------|----------------------|
| AU pooled θ_EAV                                | 3.16e-5 (basin-A trap) | **3.12e-4 (basin-B best, L-BFGS-B)** / 2.26e-4 (NM-refined) | K1213 `best_fit` + sensitivity |
| AU θ_rel                                       | 0.150              | **[1.07, 1.48]**   | K1213 `basin_B_theta_rel_mean` / best_fit |
| AU LL                                          | 89047.22           | **89146.69** (L-BFGS-B) / 89303.19 (NM) | K1213 |
| ΔLL vs K1171                                   | — (reference)      | **+99.47** (L-BFGS-B) / +255.97 (NM) | K1213 |
| LR statistic (2·ΔLL) vs χ²(1)=3.84             | —                  | **198.9** (L-BFGS-B) / 511.9 (NM) | K1213 derived |
| Primary Spearman ρ at N=13                     | +0.385             | **+0.418**         | K1213 `spearman_N13.rho` |
| Primary Spearman p at N=13                     | 0.194              | **0.156**          | K1213 `spearman_N13.p` |
| Δρ vs K1172 N=12 baseline                      | −0.056             | **−0.024**         | K1213 `delta_rho_vs_k1172` (sign reconfirmed) |
| Panel Harvey t (N=13)                          | 3.808              | 3.808 (unchanged)  | K1171 / invariant under K1213 |
| Between-R² inst_pct (N=13)                     | 0.4194             | 0.4194 (unchanged) | K1171 / invariant |
| Within-R² log_analyst (N=13)                   | 0.0534             | 0.0534 (unchanged) | K1171 / invariant |
| AU narrative framing                           | below-ladder residual | **above-ladder EM-scale residual (AU/BR/CA/IN/MX)** | K1213 verdict |
| K1207 AU residual absorption                   | −31.2% (amplifies) | −31.2% (unchanged mechanically; re-interpretation noted — K1207 used K1171 basin-A trap as input) | K1207 |
| Number of supporting experiments               | 9 (K1165/K1166/K1168/K1172/K1171/K1173/K1163/K1204/K1207) | **11** (+ K1210 forensic + K1213 multi-start) | K1215 |
| §5 open residuals                              | 1 (AU below-ladder pending K1210) | **0** (K1213 resolves AU; only magnitude heterogeneity remains) | K1215 §5.7 |

## 7. Parallel K-experiments context (K1215 perspective)

- **K1210** (commit `03a94d23`, AU forensic root-cause decomposition):
  diagnosed `NUMERICAL_FRAGILITY` in K1171 pooled AU fit; recommended
  downgrading AU below-ladder reading to INCONCLUSIVE; proposed
  multi-start as follow-up. K1215 §5.5.1 cites verbatim.
- **K1213** (commit `c34d0546`, 100-start multi-start resolution):
  overturned K1171 below-ladder reading with basin-B best at
  θ_rel = 1.476 (L-BFGS-B) / 1.070 (NM-refined), LR=198.9 >> χ²(1).
  K1215 §5.5.2 cites verbatim.
- **K1174–K1177 / K1208–K1209** (proposed follow-ups from K1211 §6):
  not blockers for Paper 2 §5 rewrite; relegated to limitations /
  future-work section.

## 8. References (incremental vs K1211)

All K1211 references carry forward. K1215 adds:

- McCullough, B.D., Vinod, H.D. (2003). *Verifying the Solution from a
  Nonlinear Solver: A Case Study*. **American Economic Review** 93(3),
  873–892. — multi-start as standard robustness check.
- Hansen, L.P. (1982). *Large Sample Properties of Generalized Method
  of Moments Estimators*. **Econometrica** 50(4), 1029–1054. — MLE
  local-minimum pathology.
