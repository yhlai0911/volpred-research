# K1222b — Paper 2 §5 post-K1216c FINAL revision guide (supersedes K1222)

**Status**: completed (worktree agent `agent-a12f00e5`, 2026-04-17)

**Verdict**: FINAL consolidated revision guide — supersedes K1222 (commit `75df1c8f`). K1222 was
written on top of the K1216b asymmetric-refinement artefact headline ρ = −0.071 and framed the
cross-market institutional-ownership ladder as WITHDRAWN. K1216c (commit `3cf6bc84`) has since
demonstrated that the −0.071 number was an asymmetric-refinement artefact — once the identical
100-multistart protocol is applied panel-wide (5 EM + 4 DEV + AU), the primary Spearman rebounds
to ρ = +0.379 (p = 0.201, N=13), statistically indistinguishable from the canonical +0.441 under
Fisher z (p ≈ 0.87). K1222b restores the cross-market institutional-ownership ladder to
MODESTLY WEAKER BUT SURVIVING status and promotes the multistart methodology from appendix-only
to an ADDITIONAL Paper 2 contribution (§5.4).

## Scope

K1222b is a **guide-only** experiment (Markdown + JSON; no `.tex`, no new estimation, no data
refetch, per CLAUDE.md paper-workflow rule). Its job is to give the main thread a single, coherent
cherry-pick target that reframes the rapid 4-layer narrative evolution following K1216c:

1. **K1211** (commit `9efffe4b`, `experiments/k1211/k1211_draft.md`): 7-iteration cross-market
   ladder STRENGTHENED with 3 residual caveats — **SUPERSEDED**.
2. **K1215** (commit `45f621ee`, `experiments/k1215/k1215_revised_draft.md`): K1213 AU multistart
   integration; AU reclassified above-ladder — **SUPERSEDED**.
3. **K1222** (commit `75df1c8f`, `experiments/k1222/k1222_revision_guide.md`): K1216 + K1216b
   ALL_5_EM_FRAGILE integration; headline ρ = −0.071 / ladder WITHDRAWN — **SUPERSEDED** by
   K1216c on asymmetric-refinement artefact grounds.
4. **K1222b (this guide) FINAL**: K1216c 9-market multistart audit; headline ρ = +0.379 / ladder
   MODESTLY WEAKER BUT SURVIVING; multistart methodology promoted to ADDITIONAL Paper 2
   contribution.

K1222b is the active revision guide that the main thread cherry-picks into
`paper/<paper2>/body_v(n+1).tex`.

## Supersession

- `k1211_draft.md` — SUPERSEDED (entire §5 except §5.6 sector discussion promoted to §5.2).
- `k1215_revised_draft.md` — SUPERSEDED (entire §5; AU reclassification subsumed by §5.4).
- **`k1222_revision_guide.md` — SUPERSEDED** (entire K1222; K1222's "ladder WITHDRAWN" framing
  reversed on K1216c evidence).
- **`k1222b_revision_guide.md`** — active FINAL revision guide.

## Source of numbers

All numbers in `k1222b_revision_guide.md` are **verbatim** from:

- `experiments/k1211/k1211_results.json` and `k1211_panorama.csv` — K1165 → K1171 canonical
  trajectory.
- `experiments/k1213/k1213_results.json` — AU basin-B best θ_rel=1.476; LR=198.9 (511.9 NM).
- `experiments/k1216/k1216_results.json` and `k1216_per_market_summary.csv` — BR / IN / MX refined.
- `experiments/k1216b/k1216b_results.json` and `k1216b_per_market_summary.csv` — CH / ID refined;
  asymmetric-refinement -0.071 intermediate.
- **`experiments/k1216c/k1216c_results.json` and `k1216c_per_market_summary.csv`** — US / EU /
  JP / TW refined; 9-market consistent Spearman ρ = +0.379 p = 0.201 N=13 (FINAL).
- `experiments/k1207/k1207_results.json` — sector-FE F=689.5, p=7.9e-14, adj-R² 0.148 vs 0.0046.
- `experiments/k1163/` — EU N=30 bootstrap t=4.81, 95% CI [0.127, 0.277].
- `experiments/k1172/k1172_results.json` — canonical baseline Spearman +0.441 N=12.

No new estimation in K1222b — pure consolidation guide over K1213/K1216/K1216b/K1216c.
`k1222b_vs_k1222_diff.json` gives a machine-readable record of K1222 → K1222b changes plus the
full K1211 → K1215 → K1222 → K1222b trajectory.

## Files

| File | Purpose |
|---|---|
| `README.md` | This file |
| `k1222b_revision_guide.md` | Main revision guide for main-thread cherry-pick (~3100 words, 5 subsections + narrative commitment + cherry-pick instructions + supersession summary + 4-version narrative table) |
| `k1222b_vs_k1222_diff.json` | Machine-readable K1222 → K1222b diff + full 4-version trajectory + 10-market LR audit + cherry-pick action list (13 items) |

## Key numerical updates vs K1222

| Element | K1222 | K1222b FINAL |
|---|---|---|
| Primary ρ (N=13) | −0.071 (p=0.817) | **+0.379 (p=0.201)** |
| Harvey t (panel) | −0.24 | **+1.36** |
| Ladder status | WITHDRAWN (artefact) | **MODESTLY WEAKER BUT SURVIVING** |
| Methodology role | appendix only (§5.5) | **ADDITIONAL Paper 2 contribution (§5.4)** |
| # cross-market drivers | 2 (analyst + sector) | **3 (analyst + sector + modestly-weaker ladder)** |
| # caveats | 1 (EU) | **2 (EU + CA/HK/KR unaudited disclosure)** |
| Panel-wide audit scope | 6 markets (AU + 5 EM) | **10 markets (AU + 5 EM + 4 DEV)** |
| Basin-bimodality figure | 6-market panel | **10-market panel** |

Δρ K1222 → K1222b FINAL = **+0.4505**; Δρ canonical +0.441 → K1222b FINAL = **−0.062** (Fisher z
indistinguishable, p ≈ 0.87).

## Cross-references

- **Source experiments**:
  - K1165 / K1166 / K1168 / K1171 / K1172 / K1173 / K1204 (K1211 pool).
  - K1207 (sector-FE orthogonality).
  - K1163 (EU full N=30 robustness).
  - K1213 (AU 100-multistart resolution; basin-B θ_rel ∈ [1.07, 1.48]).
  - K1216 (BR / IN / MX 100-multistart; all FRAGILE).
  - K1216b (CH / ID 100-multistart; ALL_5_EM_FRAGILE; -0.071 asymmetric-refinement artefact).
  - **K1216c (US / EU / JP / TW 100-multistart; ROOT_CAUSE_METHODOLOGY; 9-market refined ρ=+0.379
    FINAL)**.
- **Knowledge entries**: `storage/memory/knowledge.json` IDs
  - `f63b6e01` (K1216c ROOT_CAUSE_METHODOLOGY; DEV/EM unified fragility; ρ rebounds),
  - `b40d669f` (K1216b ALL_5_EM_FRAGILE; artefact),
  - `5cf52ce6` (K1216 WIDESPREAD_FRAGILITY),
  - `e4d376ad` (K1213 ABOVE_LADDER_OVERTURNED),
  - `5d2d2435` (K1207 SECTOR_ORTHOGONAL_CONFIRMED).

## Rigor checklist

- Seed: K1222b does **no new estimation**, so seed discipline falls on upstream K1213 / K1216 /
  K1216b / K1216c runs (all base=42; starts 43..142; DE seed 49; K-means seed 42 — documented in
  each experiment's README).
- No data refetch. All source numbers copied verbatim; any re-run for the main-thread body
  rewrite should use the upstream experiment JSONs as the single source of truth.
- Worktree contract honoured: only files under `experiments/k1222b/` produced; no shared-state
  writes; no `paper/*.tex` edits.
- Paper-workflow rule: body rewrite stays in main thread; K1222b only produces Markdown + JSON
  guide artefacts.
- K1222 supersession discipline: K1222 commit `75df1c8f` explicitly marked SUPERSEDED in K1222b
  title, §0 header, narrative state evolution (§1), section mapping, and supersession summary (§6).

## Next steps (main thread)

1. Cherry-pick K1222b §3 block into `paper/<paper2>/body_v(n+1).tex` per the §4 cherry-pick
   instructions (13 items).
2. **Revert** any K1222 "WITHDRAWN" / "COLLAPSED" / "numerical artefact" language if partially
   merged into `body_v(n).tex`.
3. Re-run K1173 aggregate ρ rebuild against PANEL-WIDE K1216 / K1216b / K1216c refined inputs
   (if K1173 retained in §6 robustness). Per-stock yfinance proxy comparison remains basin-invariant;
   aggregate ρ number needs panel-wide recomputation.
4. **Consider commissioning K1216d** (100-multistart on the 3 remaining unaudited markets: CA,
   HK, KR). Given 9 / 9 audited markets FRAGILE, these 3 pools are expected to also shift; final
   Spearman likely to move between +0.30 and +0.50. Not a prerequisite for K1222b §5.5 commitment
   because within-market Panel Harvey t is invariant.
5. Update Figure 5A / 5D / 5G per K1222b §4 Figure mapping; add NEW Figure 5H (K1216c 3-scenario
   Spearman trajectory: canonical +0.441 / asymmetric −0.071 / 9-market refined +0.379).
6. `knowledge.json` / `experiment_experiences.json` updates for K1222b are **not** made by the
   worktree agent (CLAUDE.md Worktree rule); main thread writes K1222b knowledge entry and logs
   K1222 SUPERSEDED after cherry-pick.
