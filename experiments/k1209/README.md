# K1209: Paper 1 Batch 2 Errata Rewrite Markdown Draft

**Status**: Completed 2026-04-17
**Type**: Markdown draft (NOT a .tex write) for main-thread cherry-pick
**Predecessor**: Batch 1 commit `0a442356` (Kupiec p 2-decimal + GLD γ forensic + γ_HM disambiguation)
**Follow-on**: Main-thread reviews `k1209_batch2_draft.md`, accepts/edits/rejects per item, integrates into `body_v4.tex`.

---

## Purpose

Paper 1 Batch 1 (commit `0a442356`) already corrected three high-priority items in `body_v3.tex`
(Kupiec 2-decimal precision, GLD γ forensic footnote, γ_HM disambiguation). The commit message
explicitly deferred a set of further edits to a "future v3.1 batch":

> Deferred to future v3.1 batch: Table 3 vs 8 reconciliation, Table 4/7
> methodology footnotes, experiments.md K1188 entry, Table 7 GLD 1.56 forensic.

K1209 consolidates those deferrals plus every other Batch 2 item identified by recent
replication experiments (K1186/K1188/K1198/K1206) into a **single reviewable markdown draft**.

Worktree agents are forbidden from editing `paper/` LaTeX directly. K1209 therefore delivers a
markdown package (`k1209_batch2_draft.md` + `k1209_batch2_items.json`) so the main thread can:

1. Review every proposed edit against the canonical K experiment numbers.
2. Decide per item: accept, edit, or reject.
3. Cherry-pick accepted edits into `body_v4.tex` in a single focused commit.

---

## Batch 2 Items (8 total)

All numbers verified against canonical K experiment JSON / diff reports.

| # | Item | Source K | Current v3 loc | Rationale | Status |
|---|------|----------|----------------|-----------|--------|
| 1 | Table 3 vs Table 8 internal inconsistency (SPY 2023-24 GJR QLIKE: -9.034 vs -8.671) | K903, K1188 | body_v3 line 219 (Table 3 narrative) | K903 rolling w=504 gives -8.674 — matches Table 8, not Table 3. Add footnote clarifying the Table 3 cell uses a different window/refit convention. | PENDING REWRITE |
| 2 | Table 6 VaR panel errata (Student-t 57.1→76.2, Skewed-t 76.2→90.5, CF-VaR 66.7→76.2) | K1186 canonical + K1206 forensic | body_v3 line 249 (Trinity pass-rate sentence) + tables.tex tab:var_panel | K1206 exhausted sensitivity space (data vintage, Skewed-t bisection, CF-VaR variants) — no variant reconstructs Paper 1 numbers. Errata_recommended. | PENDING REWRITE |
| 3 | Table 4 methodology footnote (base = GARCH(1,1) not GJR) | K1185 | body_v3 line 247 (VaR Compliance section; refers to Table 4 as "attribution analysis") | K1185 confirmed Table 4 uses GARCH(1,1) baseline despite body prescribing GJR for SPY. Potential reader confusion without an explicit footnote. | PENDING REWRITE |
| 4 | Table 7 per-asset evaluation period clarification | K1187 | body_v3 line 279 (Table 5 VT cross-asset) + caption of Table 7 | K1187 shows body says "7-16 year periods" but per-asset dates are undisclosed; SPY 2014-2026, GLD 2022-2026, BTC ~2019+, etc. Add per-asset period list to Table 7 caption. | PENDING REWRITE |
| 5 | Table 7 GLD 1.56 Sharpe forensic footnote | K1187 | body_v3 line 294 (Gold VT paradox paragraph, "buy-and-hold's 1.56") | K1187 cannot reproduce BH Sharpe 1.56 from any standard period (max found 1.29). Paper sentence implies 2022-2026 gold bull. Add footnote citing period + K1187 replication package. | PENDING REWRITE |
| 6 | experiments.md K1188 + K1186 + K1187 + K1198 + K1206 entries | K1188, K1186, K1187, K1198, K1206 | N/A — `paper/leverage-direction/experiments.md` does not exist | Paper-folder rule requires experiments.md (or README list) of supporting K experiments. Paper 1 folder currently lacks this file. Create it. | PENDING ADD |
| 7 | Tables 10/11/12/C3 pre-K footnote (KB-only rebuild 3/6 matched) | K1198 | body_v3 lines for tab:amplify / tab:tail / tab:gamma-mechanism / §4.2.3 C3 | K1198 rebuilt 6 KB-only-pre-K values, 3 MATCHED (BH ES, BH kurtosis, Spearman ρ); 3 DIVERGED (SPY avg constituent γ, ETF-vs-stock t-stat, gold regime t-stat). Add unified footnote acknowledging rebuild + divergences. | PENDING REWRITE |
| 8 | γ_HM Sec 4.7 vs 5.4 second clarification | (N/A — Batch 1 already addressed 5.4 side) | body_v3 line ~5.4 (Batch 1 footnote already inserted) | Cross-check: if Sec 4.7 still mentions γ_HM without disambiguation, extend footnote reference. If not, DROP. | DROPPED (see Item 8) |

---

## Canonical Sources (all verified 2026-04-17)

- **K903** (`experiments/k903/k903_vs_paper_diff.md`): SPY 2023-24 GJR QLIKE rolling w=504 step=63 = **-8.674**, matches Paper Table 8 (-8.671) within 0.003. Paper Table 3 cell -9.034 diverges by 4.1% — indicates different window/refit.
- **K1185** (`experiments/k1185/README.md`): Table 4 uses GARCH(1,1), not GJR. 3/4 configs matched; Normal 33→30 divergence from yfinance data revision.
- **K1186** (`experiments/k1186/`): Paper 1 Table 6 canonical replication, 2/5 EXACT (Normal, FHS), 3/5 DIVERGED (Student-t 57.1→76.2, Skewed-t 76.2→90.5, CF-VaR 66.7→76.2).
- **K1187** (`experiments/k1187/README.md`): Paper 1 Table 7 match 6/20; root cause = undisclosed per-asset periods. GLD 1.56 Sharpe not reproducible from any standard period.
- **K1188** (`experiments/k1188/README.md`): Paper 1 Table 8 Window Robustness — 15/15 EXACT match. Resolves STILL_NO_SOURCE flag.
- **K1198** (`experiments/k1198/README.md`): Paper 1 Tables 10/11/12 + §4.2.3 C3 KB-only rebuild — 3/6 matched.
- **K1206** (`experiments/k1206/README.md`): Paper 1 Table 6 forensic sensitivity — no variant reconstructs Paper 1 numbers. `errata_recommended`.

---

## Adoption Path

Main thread workflow when ready to issue `body_v4.tex`:

1. Read `k1209_batch2_draft.md` Section 2 (8 items) + Section 4 (checklist).
2. For each item set status = accepted / edited / rejected.
3. For accepted items, copy the "Proposed v4 text" block into `body_v4.tex` at the line pointer.
4. For footnotes, append to the existing footnote queue in `body_v4.tex`.
5. Create or update `paper/leverage-direction/experiments.md` using Item 6 content.
6. Update `tables.tex` tab:var_panel Trinity column per Item 2.
7. Compile `main_v4.pdf` via xelatex.
8. `uv run volpred ops paper-update --paper-id leverage-direction`.

---

## Files

- `README.md` — this file.
- `k1209_batch2_draft.md` — consolidated 8-item rewrite draft with current v3 text, proposed v4 text, rationale, and main-thread adoption checklist.
- `k1209_batch2_items.json` — structured JSON (machine-readable) of all 8 items.

No code script, no data fetches: K1209 is a **synthesis-only** experiment. All numbers come
from prior K experiment JSONs (K903, K1185, K1186, K1187, K1188, K1198, K1206) already committed
to the repo. Seed N/A (no RNG). Canonical numbers quoted verbatim.

---

## Cross-Reference to Batch 1

Batch 1 (commit `0a442356`) already handled:

- Kupiec p-value 2-decimal precision (Sec 4.5 and Sec 4.8).
- GLD γ = -0.067 rolling-window mean retained with forensic footnote vs K903 full-sample γ = +0.002.
- γ_HM disambiguation footnote in Sec 5.4 covering three values (-0.035 / -0.068 / -0.043).

K1209 **does not** re-edit any of the Batch 1 items. Item 8 (γ_HM Sec 4.7) is marked DROPPED
because Sec 5.4 footnote already covers the disambiguation; if a reader-thread audit later
surfaces a second instance in Sec 4.7, it can be re-opened as a stand-alone fix.

---

## Decision

`draft_ready` — main-thread review + cherry-pick required before any `body_v4.tex` edit.
