# K1227 — Paper 3 Triple-Path Edit Guide (paths a/b/c pre-production)

**Status**: Pre-decision pre-production material (markdown + JSON only, NOT LaTeX).
**Date**: 2026-04-17
**Seed**: 42 (no estimation; seed fixed for any downstream scripts)
**Data**: None (synthesis of K1205 + K1217 prior products; all numbers verbatim from K1205 integrity-verified canonical).
**Author**: Claude (worktree K1227)

## 1. Purpose

K1227 extends K1217 (which produced a full pre-draft only for narrative path b) by adding complementary pre-production guides for path (a) and path (c), so the user can review all three Paper 3 K1128 narrative-pivot options in one pass and select from complete pre-produced materials.

- Path (a): full K1142 vol-norm anchor — outline + target-journal + risk-profile pre-produced here.
- Path (b): hybrid null + K1142 partial positive (K1205 RECOMMENDED) — full ~4,991-word body at `experiments/k1217/k1217_paper_draft.md`; K1227 cross-references it.
- Path (c): abandon Paper 3 — three salvage options pre-produced here (methodology note, appendix donation, internal memo).

## 2. Why K1227 exists

K1217 fully drafted path (b) but did not address path (a) and path (c). Without pre-produced materials for all three paths, the user faces an incomplete decision menu. K1227 fills the two missing slots so:

1. The user can compare all three paths side-by-side in one review pass.
2. Once the user selects a path, execution can begin immediately from pre-produced material (no extra background-agent round-trip).
3. The decision matrix in `k1227_triple_path_guide.md` §4 quantifies the trade-offs across 9 dimensions.

## 3. CONDITIONAL status

**This guide is a pre-decision working product.** Per CLAUDE.md paper narrative state machine:

> 論文 narrative state machine（防 Paper 2/4 單一實驗觸發反覆 pivot）：
> - 單一實驗不可直接改 paper body.tex — 只能更新 `research_program.md` + knowledge.json
> - 必須 ≥ 3 個互補實驗（OOS-verified + Codex/Gemini reviewed）都完成才進 narrative decision
> - 決策 user confirm 後設 `status='decision_made_awaiting_body_rewrite'`，body rewrite 才開始

K1227 is **not** a committed paper body. It is a menu of pre-computed options. No `paper/<name>/main.tex` write is authorized by K1227.

## 4. Parallel source cross-reference

| Source | Role in K1227 |
|--------|---------------|
| `experiments/k1205/k1205_synthesis_table.csv` | Canonical 4-branch numbers (all verbatim) |
| `experiments/k1205/k1205_integrity_report.txt` | 7-check cross-experiment integrity (ALL PASS) |
| `experiments/k1205/k1205_results.json` | Consolidated canonical results |
| `experiments/k1217/k1217_paper_draft.md` | Path (b) full pre-draft (~4,991 words) — K1227 cross-references, does not duplicate |
| `experiments/k1217/README.md` | Path (b) conditional-status framework (K1227 adopts the same state-machine discipline) |
| `storage/memory/knowledge.json` id=aab5c94b | K1205 synthesis knowledge entry |
| `storage/memory/knowledge.json` id=f63b6e01 | K1128 tertile NULL knowledge entry |
| `storage/memory/knowledge.json` id=ae05df05 | K1142 vol-norm PARTIAL_OOS_ONLY knowledge entry |
| `research_program.md` §Paper 3 | Current state of Paper 3 narrative decision |
| `docs/error_log.md` 2026-04-13 | IS-regime degeneracy lesson |

## 5. Files in `experiments/k1227/`

| File | Purpose |
|------|---------|
| `README.md` | This file. K1227 purpose, conditional status, cross-reference. |
| `k1227_triple_path_guide.md` | ~2,000-word triple-path guide. Paths a / b / c outlines + decision matrix + recommendation. |
| `k1227_triple_path.json` | Structured 3-path metadata (headline numbers, risks, journals, effort, draft status). |

## 6. Canonical number sources

All numbers in `k1227_triple_path_guide.md` are verbatim from K1205 canonical products. No new estimation was performed in K1227. The K1205 integrity report (ALL PASS, 7 checks) is the authority for cross-experiment numerical consistency.

## 7. Reproduction

K1227 has no reproducible computation; it is a text synthesis of prior experiments. Upstream canonical scripts:

```bash
python experiments/k1128/k1128.py
python experiments/k1131/k1131.py
python experiments/k1142/k1142.py
python experiments/k1199/k1199.py
python experiments/k1205/k1205.py          # canonical synthesis
python experiments/k1205/k1205_figures.py  # figures
```

No random sampling is involved.

## 8. Scope and limitations

- **Markdown + JSON only**: per CLAUDE.md worktree rule, agents may not write LaTeX bodies. K1227 produces `.md` + `.json` only.
- **No new estimation**: all numbers verbatim from K1205.
- **No figure generation**: cross-references K1205 figures (`k1205_figureA_panorama.pdf/png`, `k1205_figureB_regime_coverage.pdf/png`, `k1205_figureC_auc_ranking.pdf/png`).
- **No duplicate of K1217 body**: K1227 cross-references K1217 for path (b) full draft; does not re-author.
- **Pre-decision only**: no paper body write is authorized by K1227. User selection (a/b/c) must occur in the main thread before any body rewrite begins.
- **No Codex review performed**: K1227 is a text synthesis, not code. Main-thread `latex-academic-reviewer` + `citation-verifier` should be invoked if the user selects path (a) or (b) and the paper moves into body rewrite.

## 9. Derived directions

If user selects path (a):
- K1228 — Build `paper/prg-volnorm-anchor/` shell (README, data_sources.md, experiments.md per self-contained-paper-folder rule).
- K1229 — Codex adversarial review of path (a) single-cell evidentiary framing.
- K1220 (already planned) — Cross-market vol-norm replication (ES / NQ) before submission.

If user selects path (b):
- K1218 (already planned) — Codex adversarial review of K1217 draft.
- K1219 (already planned) — .bib construction + citation verification.
- K1220 (already planned) — Cross-market K1142 replication as robustness.

If user selects path (c):
- K1230 — Execute chosen salvage option (methodology note / appendix donation / internal memo).
- `research_program.md` Paper 3 section → `status='abandoned_with_salvage'`.
- `knowledge.json` Paper 3 abandonment + salvage decision entry.

## 10. References

- `experiments/k1205/` — K1205 canonical 4-branch synthesis
- `experiments/k1217/` — K1217 path (b) full pre-draft
- `experiments/k1128/`, `experiments/k1131/`, `experiments/k1142/`, `experiments/k1199/` — four branches
- `experiments/k1100g_d7/` — cross-market weak-universal gap² evidence
- `experiments/k1124/` — TAIFEX TX 5-minute cache
- `research_program.md` §Paper 3
- `docs/error_log.md` 2026-04-13 — IS-regime degeneracy lesson
- CLAUDE.md — paper narrative state machine rule
