# K1222 — Paper 2 §5 post-K1216b major revision guide

**Status**: completed (worktree agent a5160727, 2026-04-17)
**Verdict**: consolidated revision guide — supersedes K1211 §5 and
K1215 §5 by integrating K1213 / K1216 / K1216b multistart audit
findings. Cross-market institutional-ownership ladder formally
withdrawn; within-market analyst channel + K1207 sector-FE retained
as primary cross-market drivers.

## Scope

K1222 is a **guide-only** experiment (Markdown + JSON; no `.tex`,
no new estimation, no data refetch, per CLAUDE.md paper-workflow
rule). Its job is to give the main thread a single, coherent cherry-
pick target that consolidates a rapid 3-layer narrative evolution:

1. **K1211** (commit `9efffe4b`, `experiments/k1211/k1211_draft.md`):
   7-iteration cross-market ladder STRENGTHENED with 3 residual caveats.
2. **K1215** (commit `45f621ee`,
   `experiments/k1215/k1215_revised_draft.md`): K1213 AU multistart
   integration; AU reclassified above-ladder; STRENGTHENED retained.
3. **K1216** (commit `cbc852ae`) + **K1216b** (commit `ee923da1`):
   100-multistart audit of BR/IN/MX/CH/ID → `ALL_5_EM_FRAGILE`;
   primary Spearman collapses to **ρ = −0.071, p = 0.817, Harvey
   t = −0.24** at N=13.

K1222 consolidates these into a single revision guide that the main
thread cherry-picks into `paper/<paper2>/body_v(n+1).tex`.

## Supersession

- K1211 `k1211_draft.md` — **SUPERSEDED** (entire §5, except K1211
  §5.6 sector discussion which becomes new §5.2 headline).
- K1215 `k1215_revised_draft.md` — **SUPERSEDED** (entire §5; K1215
  §5.5.5 AU reclassification quote absorbed into new §5.4 RETRACTED
  section; K1215 §5.7 FINAL replaced by K1222 §5.6 FINAL).
- **K1222 `k1222_revision_guide.md`** — active revision guide.

## Source of numbers

All numbers in `k1222_revision_guide.md` are **verbatim** from:

- `experiments/k1211/k1211_results.json` /
  `experiments/k1211/k1211_panorama.csv` (K1165 → K1171 trajectory).
- `experiments/k1213/k1213_results.json` (AU basin-B best, NM-polished).
- `experiments/k1216/k1216_results.json` /
  `experiments/k1216/k1216_per_market_summary.csv` (BR / IN / MX refined).
- `experiments/k1216b/k1216b_results.json` /
  `experiments/k1216b/k1216b_per_market_summary.csv` (CH / ID refined,
  5-EM + AU primary Spearman).
- `experiments/k1207/` (sector-FE joint F = 689.5, incremental
  adj-R² 0.148 vs inst-FE 0.0046, 32× ratio).
- `experiments/k1163/` (EU N=30 full coverage bootstrap t = 4.81).

No new estimation in K1222 — this experiment is a pure consolidation
guide. `k1222_revision_diff.json` gives a machine-readable record of
old → new numbers plus the cherry-pick action list.

## Files

| File | Purpose |
|---|---|
| `README.md` | This file |
| `k1222_revision_guide.md` | Main revision guide for main-thread cherry-pick (~2400 words, 5 subsections + narrative commitment + cherry-pick instructions + supersession table) |
| `k1222_revision_diff.json` | Machine-readable old → new number diff + cherry-pick action list |

## Cross-references

- **Source experiments**:
  - K1165 / K1166 / K1168 / K1171 / K1172 / K1173 / K1204 (K1211 pool).
  - K1207 (sector-FE orthogonality).
  - K1163 (EU full N=30 robustness).
  - K1213 (AU 100-multistart resolution; basin-B θ_rel ∈ [1.07, 1.48]).
  - K1216 (BR / IN / MX 100-multistart; all FRAGILE).
  - K1216b (CH / ID 100-multistart; ALL_5_EM_FRAGILE).
- **Knowledge entries**: `storage/memory/knowledge.json` IDs
  `5cf52ce6` (K1216 WIDESPREAD_FRAGILITY), `b40d669f` (K1216b
  ALL_5_EM_FRAGILE), `e4d376ad` (K1213 ABOVE_LADDER_OVERTURNED),
  `5d2d2435` (K1207 SECTOR_ORTHOGONAL_CONFIRMED).

## Rigor checklist

- Seed: K1222 does **no new estimation**, so seed discipline falls on
  upstream K1213 / K1216 / K1216b runs (all base 42; starts 43..142;
  DE seed 49; K-means seed 42 — documented in each experiment's README).
- No data refetch. All source numbers copied verbatim; any re-run for
  the main-thread body rewrite should use the upstream experiment
  JSONs as the single source of truth.
- Worktree contract honoured: only files under
  `experiments/k1222/` produced; no shared-state writes; no
  `paper/*.tex` edits.
- Paper-workflow rule: body rewrite stays in main thread; K1222 only
  produces Markdown + JSON guide artefacts.

## Next steps (main thread)

1. Cherry-pick K1222 §3 block into `paper/<paper2>/body_v(n+1).tex`
   per the §4 cherry-pick instructions.
2. Re-run K1173 ρ rebuild against K1216 / K1216b refined EM `θ_rel`
   values if K1173 is retained in §6 / robustness; re-verify the Δρ
   NULL-band finding at the global optimum. (The per-stock yfinance
   proxy comparison is basin-invariant, but the aggregate ρ number
   needs a verbatim recomputation.)
3. Consider commissioning K1216c (100-multistart on the 7 developed
   pools: TW / EU / JP / US / KR / HK / CA) to confirm the developed
   ladder base is stable. Not a prerequisite for §5.6 commitment,
   because within-market Panel Harvey t is basin-invariant, but would
   complete the multistart audit.
4. Update Figure 5A / 5D / 5G per the K1222 §4 "Figure mapping
   updates" section (K1216b N=13 ρ annotation on 5A; 5D replaced by
   basin-structure visual; 5G expanded to 6-market basin-bimodality
   panel).
5. `knowledge.json` / `experiment_experiences.json` updates are **not**
   made by the worktree agent (CLAUDE.md Worktree rule); main thread
   writes K1222 knowledge entry after cherry-pick.
