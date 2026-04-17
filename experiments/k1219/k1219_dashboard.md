# Main-Thread Cherry-Pick Dashboard (Session 2026-04-17)

**K1219 — Unified consolidation of 6 paper-related markdown drafts**
**Produced by**: Claude (worktree `agent-a53cb331`)
**Date**: 2026-04-17
**Seed**: 42 (declared for compliance; no RNG used)
**Task type**: Pure consolidation — no new claims, no re-estimation, all word counts + commit hashes verbatim from source READMEs.

---

## Summary

**6 markdown drafts** produced this session targeting **5 existing papers + 1 new paper**.

- **3 papers READY for immediate cherry-pick** (no decision blocker): Paper 1, Paper 2, Paper 6
- **2 drafts blocked on user decision**: Paper 4 (CONFLICT-A4 framing), Paper 3 (a/b/c pivot)
- **1 NEW paper awaiting go/no-go**: BTC GAS-t negative result (K1214)

Total draft volume: **20,057 words** across 6 files.

---

## Paper-by-Paper Status Matrix

| Paper | Draft | Status | Adoption Gate | Target Action | Words | Decision Blocker |
|-------|-------|--------|---------------|---------------|-------|------------------|
| Paper 1 leverage-direction | K1209 Batch 2 | READY | None | Cherry-pick 8 items into `body_v4.tex` + create `experiments.md` + update `tables.tex` | 3574 words, 8 items | None (Batch 1 already committed `0a442356`) |
| Paper 2 taiwan-vt | K1215 §5 revised | READY | None | Replace v3 §5 with K1215 §5.5 full rewrite + light §5.1/5.6/5.7 edits + Table 5 Iter 5' row | 3971 words, 7 subsections | None |
| Paper 3 vt-trend-following | K1217 path (b) | CONDITIONAL | User pivot decision (a/b/c) | If (b): create `paper/prg-hybrid-null/` + initialize main.tex | 4991 words, 6 sections | User decision on K1128 pivot |
| Paper 4 vix-sufficiency | K1208 §5 | READY-WITH-BLOCKER | User Paper 4 framing (CONFLICT-A4) | Body_v4.tex rewrite once framing chosen | 1762 words, 6 subsections | CONFLICT-A4: channel-specific vs UNIVERSAL_NULL |
| Paper 6 prg-periodic-garch | K1218 Appendix A | READY | None | Cherry-pick appendix A.1–A.5 into main.tex `\appendix` or separate `appendix.tex` | 930 words, 5 subsections | None |
| NEW: BTC GAS negative | K1214 (new paper) | READY | User go/no-go | If go: create `paper/btc-gas-negative/` + initialize | 4829 words, 6 sections + refs + appendix | User approval of new paper initiative |

---

## Source Commit Hashes (verbatim from session git log)

| K# | Commit Hash | Commit Subject |
|----|-------------|----------------|
| K1208 | `af7b196a` | Paper 4 §5 cross-asset panorama markdown rewrite draft |
| K1209 | `2ca9f2f8` | Paper 1 Batch 2 errata rewrite markdown draft (8 items, NOT .tex) |
| K1214 | `91e5ab1d` | BTC GAS-t negative-result paper markdown draft |
| K1215 | `45f621ee` | Revise K1211 Paper 2 §5 markdown draft §5.5 to integrate K1213 AU resolution |
| K1217 | `4b100d3b` | Paper 3 path (b) hybrid null+positive CONDITIONAL markdown draft |
| K1218 | `581be90f` | Paper 6 Appendix A markdown draft (K1200 clean-slate replication) |

Note: Batch 1 predecessor for Paper 1 is commit `0a442356` (Kupiec p 2-decimal + GLD γ forensic + γ_HM 5.4 disambiguation).

---

## Detailed Cherry-Pick Instructions Per Paper

### Paper 1 (K1209) — READY, 8 items (Batch 2)

**Source**: `experiments/k1209/k1209_batch2_draft.md` + `k1209_batch2_items.json`
**Target**: `paper/leverage-direction/body_v4.tex` (create v4, do not modify v3) + `tables.tex` + new `experiments.md`
**Scope**: 6 pending_rewrite + 1 pending_add + 1 dropped = 8 items total

#### Item-by-item action list

| # | Item | Action | v3 line pointer | Source K |
|---|------|--------|-----------------|----------|
| 1 | Table 3 vs Table 8 SPY 2023-24 GJR QLIKE inconsistency (-9.034 vs -8.671) | add_footnote | body_v3.tex line 219 (Table 3 narrative) | K903, K1188 |
| 2 | Table 6 VaR panel errata (3 cells: StudentT5 57.1→76.2, Skewed-t 76.2→90.5, CF-VaR 66.7→76.2) | rewrite_table_rows_plus_sentence_plus_footnote | body_v3.tex line 249 + `tables.tex` tab:var_panel | K1186, K1206 |
| 3 | Table 4 base = GARCH(1,1) not GJR methodology footnote | add_footnote | body_v3.tex line 247 (after Table~\ref{tab:var}) | K1185 |
| 4 | Table 7 per-asset evaluation period disclosure | amend_caption_plus_footnote | body_v3.tex line 279 + `tables.tex` tab:vt caption | K1187 |
| 5 | Table 7 GLD 1.56 Sharpe forensic footnote (period-specific 2022-2026) | add_footnote | body_v3.tex line 294 ("buy-and-hold's 1.56") | K1187 |
| 6 | Create `paper/leverage-direction/experiments.md` | add_new_file | NEW file | K903/K1185/K1186/K1187/K1188/K1198/K1206 |
| 7 | Tables 10/11/12 + §4.2.3 pre-K unified rebuild footnote (3/6 matched) | add_unified_footnote | First Table 10/11/12 or §4.2.3 value in reading order | K1198 |
| 8 | γ_HM Sec 4.7 second disambiguation | DROPPED | N/A | Batch 1 Sec 5.4 footnote sufficient |

**Post-adoption commit template** (from k1209_batch2_items.json):
> "Paper 1 errata batch 2 (v4): Table 6 errata + Table 3/4/7 footnotes + experiments.md"

**Gate**: None. Can execute immediately.

---

### Paper 2 (K1215) — READY, §5 full revision integrating K1213

**Source**: `experiments/k1215/k1215_revised_draft.md` + `k1215_revision_stats.json`
**Target**: `paper/taiwan-vt/body_v4.tex` (create v4, do not modify v3)
**Predecessor**: K1211 draft (commit `9efffe4b`) — superseded by K1215 due to K1213 AU resolution

#### Section-level change summary

| Subsection | K1211 action | K1215 action | Notes |
|------------|--------------|--------------|-------|
| §5.1 | verbatim | +89 words (light edit) | Harvey t invariance note + Spearman ρ N=13 update (+0.385 → +0.418) |
| §5.2–5.4 | verbatim | verbatim | No change |
| §5.5 | below-ladder AU residual framing | **FULL REWRITE (451→1228 words)** | Integrates K1213 multi-start resolution; AU reclassified to above-ladder EM-scale residual |
| §5.6 | K1207 amplification narrative | +92 words | K1213 caveat on basin-A input |
| §5.7 FINAL | 1 open residual (AU) | +108 words, FULL replacement | 0 open residuals; only magnitude heterogeneity remains |
| Table 5 | Iter 5 (K1171) | Iter 5 marked *retracted*; **new row Iter 5' (K1213)** — AU θ_rel=1.476, ρ=+0.418, p=0.156, Panel Harvey t=3.808 | |
| Figure 5G | N/A | NEW slot: K1213 basin bimodality PNGs | `k1213_theta_eav_hist.png` + `k1213_ll_vs_theta_scatter.png` |

**New bibliography entries**:
- McCullough, B.D., Vinod, H.D. (2003). *AER* 93(3), 873–892.
- Hansen, L.P. (1982). *Econometrica* 50(4), 1029–1054.

**Gate**: None. Can execute immediately.

---

### Paper 3 (K1217) — CONDITIONAL on user pivot decision

**Source**: `experiments/k1217/k1217_paper_draft.md` (DRAFT STATUS banner)
**Target**: `paper/prg-hybrid-null/` (NEW paper folder, if path (b) selected)
**User decision required**: path (a) full K1142 anchor / (b) hybrid null+positive / (c) abandon

**K1205 recommendation**: Path (b) — "Hybrid null+positive: 4-branch honest null + K1142 vol-norm partial適合 negative-result methodological paper"

#### Action flow per pivot choice

- **If (a)**: K1217 archived; high reviewer risk path; single positive cell.
- **If (b)**: K1217 becomes seed for new paper body. Action steps:
  1. Create `paper/prg-hybrid-null/{figures,tables,scripts,data_docs,review_history}`
  2. Copy `k1217_paper_draft.md` §1-§6 content as basis for `main.tex` body
  3. Add standard LaTeX preamble + bibliography from 24 references
  4. Link K1205 figures (panorama / regime coverage / AUC ranking PDFs) into `figures/`
  5. Run `paper-review-cycle` round 1
  6. Iterate via `paper-update` CLI
- **If (c)**: K1217 archived; K1142 kept for separate submission.

**Target journal (if path b)**: Journal of Empirical Finance primary / IRFA / Pacific-Basin Finance Journal

**Gate**: Paper 3 K1128 narrative pivot decision (a/b/c).

---

### Paper 4 (K1208) — READY-WITH-BLOCKER (CONFLICT-A4 pending)

**Source**: `experiments/k1208/k1208_draft.md` + `k1208_panorama_table.csv`
**Target**: `paper/vix-sufficiency/body_v4.tex`
**Narrative state**: UNLOCKED (4 OOS-verified experiments: K1116c/K1116f/K1201/K1203, 7/7 panorama complete)

#### CONFLICT-A4 blocker

Two incompatible framing decisions observed in session:
- User 2026-04-17 decision `7ecab636`: "channel-specific pivot"
- K1203 session gate: "UNIVERSAL_NULL_7_OF_7 final"

K1208 draft written in UNIVERSAL_NULL framing. If user wants channel-specific, draft §5.1-5.6 needs re-framing before adoption.

#### Adoption steps (once framing resolved)

1. Create `paper/vix-sufficiency/body_v4.tex` or add new §5 block inside `main_v4.tex`
2. Renumber current v3 §5 "Volatility-Timing Strategy Design" to §6 (or trim)
3. Map Markdown headings → `\subsection{...}` / `\subsubsection{...}`
4. Convert Tables 5.1/5.2 to LaTeX `tabular` using `k1208_panorama_table.csv` (pit_shift0 rows)
5. Attach Figure 5.1: `experiments/k1203/k1203_dm_heatmap_7asset.png` (already 7-asset ready)
6. Run `paper-review-cycle` on v4 draft
7. Compile + `uv run volpred ops paper-update --paper-id vix-sufficiency`
8. Update `research_program.md` + `knowledge.json` narrative-state transition (main thread)

**Gate**: User CONFLICT-A4 clarification (channel-specific vs UNIVERSAL_NULL framing).

---

### Paper 6 (K1218) — READY, Appendix A

**Source**: `experiments/k1218/k1218_appendix_draft.md` + `k1218_appendix_meta.json`
**Target**: `paper/prg-periodic-garch/main.tex` `\appendix` block OR separate `appendix.tex`
**Evidence**: K1200 clean-slate replication (commit `287de785`), verdict MINOR_DIVERGENT (clean-slate performs better)

#### Canonical table (A.1–A.5 replication numbers, verbatim from k1200)

| Metric | K880 canonical | K1200 clean-slate | Δ |
|--------|----------------|-------------------|---|
| GJR QLIKE | 0.8542 | 0.8544 | +0.0002 |
| PRG Extended QLIKE | 0.7478 | 0.7355 | -0.0124 |
| DM t (PRG vs GJR) | 6.004 | 6.128 | +0.124 |
| Spearman ρ (PRG Extended) | 0.5678 | 0.5761 | +0.0084 |
| OOS observations | 1823 | 1823 | 0 |

#### 4 adoption steps

1. Cherry-pick into `\appendix \section{Independent Replication of the Two-Phase Forecast Timing}`
2. Add Section 4 cross-reference: *"Appendix A.3 documents an independent clean-slate replication of the SPY results, yielding DM t = 6.13 against the main-text 6.00, which confirms the transcription of Eqs.(5)-(6)."*
3. `xelatex main.tex × 2` (resolve cross-references)
4. `uv run volpred ops paper-update --paper-id prg-periodic-garch`

**Gate**: None. Can execute immediately.

---

### NEW BTC Paper (K1214) — READY, requires go/no-go

**Source**: `experiments/k1214/k1214_paper_draft.md` + `k1214_paper_outline.json`
**Target**: `paper/btc-gas-negative/` (NEW repo)
**Paper title**: *Why GAS-t Fails on Bitcoin: Student-t Innovation Is the Culprit, Regime-Switching Cannot Rescue*
**Core claim**: BTC GAS-t underperformance (DM t = -4.58) is (i) concentrated 2015-2020 pre-institutional, (ii) ~75% attributable to Student-t innovation / 25% to GAS dynamics, (iii) cannot be rescued by MS-GAS-t; falsifies Catania (2018) regime-switching remedy for BTC.

#### Section/word budget

| Section | Target | Actual |
|---------|--------|--------|
| Abstract | 200 | ~280 |
| 1. Introduction | 800 | ~820 |
| 2. Methodology | 500 | ~650 |
| 3. Data | 300 | ~320 |
| 4. Results | 1200 | ~1200 |
| 5. Discussion | 600 | ~700 |
| 6. Conclusion | 300 | ~230 |
| References | ~20 | 16 |
| Appendix A | — | ~250 |

#### If approved (9 initialization steps)

1. `mkdir -p paper/btc-gas-negative/{figures,tables,scripts,data_docs,review_history}`
2. Seed `main.tex`: cherry-pick draft sections, convert math to amsmath, tables to booktabs
3. `README.md`: title, target journal, status=`draft`, K-list (K1129/K1133/K1133b), data source summary
4. `experiments.md`: K1129 (full-sample reversal), K1133 (sub-period), K1133b (decomposition + MS-GAS-t OOS)
5. `data_sources.md`: yfinance BTC-USD 2015-01-02 to 2026-04-14, n=4121, pct_change*100, seed 42
6. `scripts/README.md`: Table 1 ← K1129/k1129.py; Tables 2-3 + App A.1 ← k1133b.py; App A.3 ← k1133.py
7. `figures/`: soft-link 7 PNGs from K1129/K1133/K1133b
8. Pre-submission checklist per `CLAUDE.md` paper-workflow
9. `reproduce.py`: one-shot runner + `reproduce_report.json` diff

**Target journal**: Journal of Empirical Finance (primary; JFEC fallback — home of Catania 2018; Journal of Risk tertiary)

**Gate**: User approval of new paper initiative.

---

## Session Stats (from K1212 session delta draft, commit `1a23e22c`)

- ~30 K experiments completed this session
- 88 knowledge entries added
- 6 markdown drafts for adoption (K1208, K1209, K1214, K1215, K1217, K1218)
- 3 papers ready immediate / 2 with decision blocker / 1 new paper candidate

---

## Execution Order (Recommended)

1. **Immediate (no gate)**: K1209 + K1215 + K1218 → Papers 1 / 2 / 6
   - Each is a self-contained cherry-pick; parallel execution feasible
   - Estimated main-thread time: 15–30 min per paper
2. **User quick decisions (5–10 min each)**:
   - Paper 4 CONFLICT-A4: channel-specific vs UNIVERSAL_NULL framing clarification
   - BTC paper (K1214) go / no-go
3. **User deep decision (30+ min thinking)**:
   - Paper 3 K1128 pivot: path (a) / (b) / (c) — K1205 recommends (b)
4. **After all decisions**: execute corresponding drafts
   - Paper 4 body_v4.tex rewrite (K1208)
   - New paper initialization (K1214 → `paper/btc-gas-negative/`)
   - New paper initialization (K1217 → `paper/prg-hybrid-null/` if (b) selected)

---

## Compliance Note

- K1219 is pure consolidation; no new numerical claims.
- All word counts verbatim from `wc -w` on source draft files (see `k1219_session_actions.json`).
- All commit hashes verbatim from `git log` 2026-04-16+ session window.
- Worktree scope: `experiments/k1219/` only.
- No `.tex` output. No mutation of `paper/**`, `storage/**`, `research_program.md`, or `knowledge.json`.
