# K1208 — Paper 4 §5 cross-asset panorama rewrite draft (MARKDOWN)

**Status**: COMPLETED — markdown draft produced for main-thread adoption
**Date**: 2026-04-17
**Worktree**: `agent-a7c52d1b`
**Task type**: pure writing + canonical number lookup (**no new estimation**)

## 1. Purpose

Paper 4 (VIX sufficiency, `paper/vix-sufficiency/`) reached a narrative-state-machine
unlock gate after four OOS-verified complementary experiments:

1. K1116c — SPY 6 PIT variants, alt-data NULL robust to publication-delay (commit `64a9d569`).
2. K1116f — GLD / TLT / BTC-USD 3 PIT variants (commit `885d7b0b`).
3. K1201 — QQQ / USO 3 PIT variants; 6/7 panorama (commit `87059567`).
4. K1203 — EEM 3 PIT variants with ^VIX primary + rv30 robustness; **7/7 panorama, gate UNLOCKED** (commit `477c504a`).

The unlock means the main thread is permitted to rewrite Paper 4 §5 (currently
"Volatility-Timing Strategy Design" under the v3 partial-framing) into the new
"Cross-Asset Universality of VIX Sufficiency" narrative. CLAUDE.md
paper-workflow rule forbids background / worktree agents from editing `.tex` —
but a worktree agent **can** produce a markdown draft for main-thread review,
adaptation, and paste-in.

K1208's single scope is that markdown draft. No new data, no new estimation,
no DM re-computation. All numbers are **verbatim** from K1116c / K1116f / K1201
/ K1203 `*_results.json`.

## 2. Narrative state-machine status

Per CLAUDE.md §Automation "narrative state machine":

| Criterion                                                   | Required | Actual        | Pass |
|-------------------------------------------------------------|----------|---------------|:----:|
| Complementary OOS-verified experiments                      | ≥ 3      | 4             | PASS |
| Paper 4 universe coverage                                   | 7/7      | 7/7           | PASS |
| No unexplained outliers                                     | required | TLT caveat is documented as regime artefact | PASS |
| Primary EEM cell `pit_shift0` NULL                          | required | ^VIX NULL + rv30 NULL | PASS |
| Gate status                                                 | -        | **UNLOCKED**  | -    |

Paper status transition permitted: `status=decision_made_awaiting_body_rewrite`.
Body rewrite should be executed in the main thread using this K1208 draft as
the cherry-pick source. This worktree does **not** set the paper status itself
(that is main-thread / ops-layer responsibility).

## 3. Deliverables (all within `experiments/k1208/`)

| File                           | Purpose                                                                     |
|--------------------------------|-----------------------------------------------------------------------------|
| `k1208_draft.md`               | §5 rewrite draft in Markdown — ready for cherry-pick into `body_v4.tex`.    |
| `k1208_panorama_table.csv`     | 28-cell DM t-stat + QLIKE + gate results (pit_shift0 + pit_shift1).         |
| `k1208_results.json`           | Canonical number consolidation + narrative-state metadata (same format family as K1205 synthesis). |
| `README.md`                    | This file: adoption path, traceability, compliance.                         |

Note: no figures are produced in K1208. The main thread should re-use the
existing figure `experiments/k1203/k1203_dm_heatmap_7asset.png` as Paper 4
Figure 5.1 (already 7-asset ready).

## 4. Main-thread adoption path

The K1208 deliverables are meant to be consumed by the main thread as follows:

1. **Review `k1208_draft.md`** — check that the six subsections (5.1 panorama
   overview, 5.2 results by asset class, 5.3 TLT outlier, 5.4 ^VXEEM data gap,
   5.5 final narrative commitment, 5.6 limitations) align with Paper 4
   authorial voice and v3 surrounding sections.
2. **Create `paper/vix-sufficiency/body_v4.tex`** (new file) or add a new §5
   block inside `main_v4.tex`. The current `main_v3.tex` §5 is "Volatility-Timing
   Strategy Design" — that section should be renumbered (e.g., §6) or trimmed
   so the new §5 slot is available for the Cross-Asset Universality content.
3. **Cherry-pick Markdown → LaTeX** from `k1208_draft.md`:
   - Map Markdown headings to `\subsection{...}` / `\subsubsection{...}`.
   - Convert Tables 5.1 / 5.2 to LaTeX `tabular` environments using the
     machine-readable source `k1208_panorama_table.csv` (pit_shift0 rows).
   - Replace `>` blockquotes with `\begin{quote}...\end{quote}` or inline
     emphasis as journal style dictates.
4. **Attach Figure 5.1**: include `experiments/k1203/k1203_dm_heatmap_7asset.png`
   as a `\includegraphics`-based figure; caption should reference the 28-cell
   panorama and the lone TLT outlier.
5. **Run `paper-review-cycle`** on the v4 draft to get a round of
   `latex-academic-reviewer` + `citation-verifier` feedback before compile.
6. **Compile + `paper-update` CLI**:

   ```bash
   cd paper/vix-sufficiency
   xelatex main_v4.tex && xelatex main_v4.tex
   cd -
   uv run volpred ops paper-update --paper-id vix-sufficiency
   ```

7. **Update `research_program.md`** and `storage/memory/knowledge.json` to
   record the narrative-state transition (main thread only; worktree agents
   must not touch these).

## 5. Verbatim source traceability table

Every panorama cell in `k1208_draft.md` Table 5.1 and Appendix A is directly
extracted from the underlying experiment's `*_results.json`. Extraction is
lossless to four decimal places.

| Asset    | Native IV | Source experiment | Source commit | Source JSON field |
|----------|-----------|-------------------|---------------|-------------------|
| SPY      | ^VIX      | K1116c            | `64a9d569`    | `dm_vs_vix_baseline.pit_shift0.{base,epu,finstress,all}.t` |
| QQQ      | ^VXN      | K1201             | `87059567`    | `asset_results.QQQ.variants.pit_shift0.dm_vs_iv.iv_vs_{base,epu,finstress,all}.t_stat` |
| GLD      | ^GVZ      | K1116f            | `885d7b0b`    | `asset_results.GLD.variants.pit_shift0.dm_vs_iv.iv_vs_{base,epu,finstress,all}.t_stat` |
| USO      | ^OVX      | K1201             | `87059567`    | `asset_results.USO.variants.pit_shift0.dm_vs_iv.iv_vs_{base,epu,finstress,all}.t_stat` |
| TLT      | ^MOVE     | K1116f            | `885d7b0b`    | `asset_results.TLT.variants.pit_shift0.dm_vs_iv.iv_vs_{base,epu,finstress,all}.t_stat` |
| BTC-USD  | rv30_self | K1116f            | `885d7b0b`    | `asset_results.BTC-USD.variants.pit_shift0.dm_vs_iv.iv_vs_{base,epu,finstress,all}.t_stat` |
| EEM      | ^VIX_spillover | K1203        | `477c504a`    | `asset_results.EEM.variants.pit_shift0.dm_vs_iv.iv_vs_{base,epu,finstress,all}.t_stat` |

**DM sign convention** (confirmed from `k1116f.py` line 211 `dm_hln` docstring):
> `e1 = baseline loss, e2 = challenger loss`. `positive t => baseline loss > challenger`
> => challenger beats baseline. `negative t => baseline wins`.

All JSON t_stat values and the README tables in each source experiment use this
same convention with no additional negation, so K1208 values match each source's
published README table exactly.

**QLIKE improvement**: computed from `specs.iv.oos_qlike` vs
`min(specs.{epu,finstress,all}.oos_qlike)` as
`100 * (iv_q - best_alt_q) / |iv_q|`. Positive = alt-data beats IV. All values
fail the 5 % gate (largest positive is TLT / finstress / pit_shift0 at +0.50 %).

No cross-experiment numerical divergence was detected during consolidation.
If a divergence is later discovered, this README must be annotated with
`DIVERGENCE: ...` and the main thread should reconcile against source before
body rewrite proceeds.

## 6. Compliance checklist

- [x] Output is .md / .csv / .json only — **no .tex produced** (CLAUDE.md paper-workflow rule).
- [x] All numbers are **verbatim** from source experiments — no re-estimation.
- [x] Seed = 42 was fixed in all source experiments; no random sampling in K1208 itself.
- [x] Worktree output confined to `experiments/k1208/`.
- [x] No mutation of `storage/**`, `paper/**`, `research_program.md`,
      `storage/memory/knowledge.json`, or sync pipelines (worktree rule).
- [x] Narrative state-machine unlock gate verified before draft production.
- [x] Source-commit hashes documented for every panorama cell.

## 7. Derived follow-ups (recorded in `k1208_draft.md` §5.6)

1. Extend panorama to additional asset classes (EFA, LQD, HYG, VNQ, DBA).
2. Acquire ALFRED vintage via FRED API key to eliminate revision-vs-release
   ambiguity in PIT alignment (follow-up to K1116c §2).
3. Acquire ^VXEEM directly from CBOE historical data (optional EEM strengthening).
4. TLT-specific rates-native study conditioning on MOVE-regime transitions or
   using ACM term-premium baseline, to resolve the finstress / regime-artefact
   characterisation at sharper identification.
5. Daily HAR-RV cross-asset PIT horse race (K1121 prior suggests NULL extends).

## 8. References

Canonical source experiments (all in `experiments/` on `main`):

- `experiments/k1116c/` — commit `64a9d569`
- `experiments/k1116f/` — commit `885d7b0b`
- `experiments/k1201/`  — commit `87059567`
- `experiments/k1203/`  — commit `477c504a`

Methodological references (full bibliography inherited via `k1208_draft.md`):
Baker, Bloom, Davis (2016 QJE); Brave, Butters (2011 Chicago Fed Letter);
Kliesen, Smith (2010 St. Louis Fed Synopses); Croushore, Stark (2001 JoE);
Patton (2011 JoE); Harvey, Leybourne, Newbold (1997 IJF); Harvey (2016 RFS);
CBOE VIX / VXN / OVX / GVZ methodology docs; Aboura, Chevallier (2015)
emerging-market VIX spillovers; Corsi (2009) HAR-RV.

## 9. Worktree discipline

- All K1208 outputs are in `experiments/k1208/` only.
- No shared-state file modified.
- Worktree agent does **not** commit `paper/vix-sufficiency/body_v4.tex` or
  any other `.tex` — that remains a main-thread responsibility per
  CLAUDE.md paper-workflow rule.
- Worktree commit will be made at task-end per repository convention.
