# K1217 — Paper 3 Path (b) Hybrid Null + Positive Conditional Draft

**Status**: CONDITIONAL draft (markdown only, NOT LaTeX body)
**Date**: 2026-04-17
**Seed**: 42 (no estimation performed; seed fixed for reproducibility of any downstream scripts)
**Data**: None (synthesis of prior experiments; all numbers verbatim from K1205)
**Author**: Claude (worktree agent-adecfdf2 / K1217)

## 1. Purpose

K1217 produces a **conditional Paper 3 markdown draft** for the Path (b) "Hybrid null + positive" narrative pivot option recommended in K1205 synthesis (`experiments/k1205/`). The draft:

- Structures a 6-section methodology paper (Abstract + Intro + Methodology + Data + Results + Discussion + Conclusion + References) of approximately 5,000 words.
- Uses the four-branch honest-null framing (K1128 tertile + K1131 spline + K1142 vol-norm + K1199 expanding) as the core evidentiary backbone.
- Adopts K1142 vol-normalization as the single partial-positive result (DM t = +2.25, AUC = 0.594 OOS), framed as methodological |t| > 2 threshold crossing but not Harvey (2016) |t| > 3 publication threshold.
- Corroborates with cross-market weak-universal gap² evidence from K1100g_d7 (TAIFEX / SPY / N225 direction-consistent +/+/+, max t = +2.32 N225).

## 2. CONDITIONAL Status

**This draft is CONDITIONAL on the user selecting Path (b) in the Paper 3 K1128 narrative-pivot decision.** Per CLAUDE.md paper narrative state machine:

> 論文 narrative state machine（防 Paper 2/4 單一實驗觸發反覆 pivot）：
> - 單一實驗不可直接改 paper body.tex — 只能更新 `research_program.md` + knowledge.json
> - 必須 ≥ 3 個互補實驗（OOS-verified + Codex/Gemini reviewed）都完成才進 narrative decision
> - 決策 user confirm 後設 `status='decision_made_awaiting_body_rewrite'`，body rewrite 才開始

K1217 is a pre-decision working product. It is **NOT** a committed paper body and must not be cherry-picked into any `paper/<name>/main.tex` without explicit main-thread / user approval.

## 3. K1205 Synthesis Reference & Path (b) Recommendation

K1205 (commit e7088770, 2026-04-17) produced the canonical 4-branch synthesis table and numerical-integrity report:

- `experiments/k1205/k1205_synthesis_table.csv` — 4-branch panorama CSV
- `experiments/k1205/k1205_results.json` — consolidated canonical numbers + decision matrix
- `experiments/k1205/k1205_integrity_report.txt` — 7-check cross-experiment integrity log (all PASS)
- `experiments/k1205/README.md` — pivot decision matrix (§4)

K1205 explicitly recommends Path (b):

> 推薦 Path (b) Hybrid null+positive：4-branch honest null + K1142 vol-norm partial 適合 negative-result methodological paper，evidence 完整且不過度宣稱。

K1217 implements this recommendation in markdown form but does not replace K1205's decision document — it supplements it.

## 4. Main-Thread Adoption Workflow (CONDITIONAL)

If and only if the user selects Path (b):

1. **User decision** on Paper 3 K1128 pivot. Three options in K1205 §4:
   - (a) Full K1142 vol-norm anchor — high reviewer risk, single positive cell
   - **(b) Hybrid null + positive** — complete 4-branch evidence + methodological-paper positioning  ← **K1217 addresses this path**
   - (c) Abandon leverage-direction — K1142 kept for separate submission

2. **If Path (b) selected**, the main thread (or user) should:
   - Create a new paper folder `paper/prg-hybrid-null/` (or equivalent, tentative name)
   - Copy `k1217_paper_draft.md` content as the basis for `main.tex` body sections (§1-§6)
   - Add standard LaTeX preamble, bibliography (.bib file from references listed), and figure references
   - Link K1205 figures (`k1205_figureA_panorama.pdf`, `k1205_figureB_regime_coverage.pdf`, `k1205_figureC_auc_ranking.pdf`) into `paper/prg-hybrid-null/figures/`
   - Run `paper-review-cycle` for round 1 review
   - Iterate via `paper-update` CLI

3. **If Path (a) or (c) selected**, K1217 output should be archived unused. No body rewrite should be triggered by K1217 alone.

## 5. Target Journals

Primary target (methodological paper positioning, honest-null reporting standard, microstructure-specific):

1. **Journal of Empirical Finance** (JoE) — best fit for methodological contribution with empirical application, short-to-medium-length papers, receptive to null-result papers with strong methodology framing.

2. **International Review of Financial Analysis** — second choice, broader scope, receptive to honest-null + methodology-contribution framing.

3. **Pacific-Basin Finance Journal** — third choice, Taiwan-specific audience, faster review cycle but lower impact.

JoE is explicitly preferred because: (i) peer review standards are rigorous but receptive to honest-null framings, (ii) the paper's methodological contribution (four-branch null protocol + regime-free alternative identification) aligns with JoE's methodology-paper tradition, (iii) Taiwan-market microstructure is underrepresented in JoE and the editorial team has previously signaled interest in emerging-market microstructure.

## 6. Files in `experiments/k1217/`

| File | Purpose |
|------|---------|
| `README.md` | This file. Describes K1217 purpose, conditional status, and adoption workflow. |
| `k1217_paper_draft.md` | ~5,000-word CONDITIONAL paper draft. 6 sections + abstract + references. DRAFT STATUS banner prominently displayed. |
| `k1217_paper_outline.json` | Structured outline (section headings, word targets, canonical-number references). |

## 7. Canonical Number Sources

All numbers in `k1217_paper_draft.md` are verbatim from:

- `experiments/k1205/k1205_synthesis_table.csv` — 4-branch AUC / LL / Brier / DM
- `experiments/k1128/k1128_results.json` — K1128 tertile primary + secondary splits
- `experiments/k1131/k1131_results.json` — K1131 spline coefficients, shape, LRT
- `experiments/k1142/k1142_results.json` — K1142 volnorm IS/OOS metrics, DM, lag-12 robustness, conditional probability deciles
- `experiments/k1199/k1199_results.json` — K1199 expanding-window coverage, OOS DM
- `experiments/k1100g_d7/README.md` — Cross-market weak-universal gap² evidence

No new estimation was performed in K1217. K1217 does not reconcile the K1142 vs K1199 vol-norm AUC difference (documented implementation difference, not bug; K1142 0.594 is canonical per K1205 integrity check #7).

## 8. Reproduction

K1217 has no reproducible computation; it is a text synthesis of prior experiments. To re-generate canonical numbers, the prior experiments' `*.py` scripts are:

```bash
python experiments/k1128/k1128.py
python experiments/k1131/k1131.py
python experiments/k1142/k1142.py
python experiments/k1199/k1199.py
python experiments/k1205/k1205.py          # canonical synthesis
python experiments/k1205/k1205_figures.py  # all figures
```

No random sampling is involved in K1205/K1217; all inputs are deterministic.

## 9. Scope and Limitations

- **Markdown only**: per CLAUDE.md worktree rule, agents may not write LaTeX bodies. K1217 is `.md` + `.json`, not `.tex`.
- **No new estimation**: all numbers verbatim from prior experiments.
- **No figure generation**: K1217 references K1205's existing figures; no new figures generated.
- **No Codex review performed**: this is a text synthesis, not code. Main-thread `latex-academic-reviewer` + `citation-verifier` should be invoked if Path (b) adoption proceeds to paper body.
- **CONDITIONAL**: adoption requires explicit Path (b) selection by user.

## 10. Derived Directions (3)

If Path (b) is adopted and the paper moves into body rewrite:

1. **K1218 — Codex adversarial review of the K1217 draft**: submit the full markdown to Codex for challenge-the-design review. Expected focus: (i) is the honest-null framing methodologically rigorous? (ii) is the vol-normalization partial-positive claim properly calibrated? (iii) is the target journal fit correct?

2. **K1219 — Reference .bib construction + citation verification**: extract all 24 references from the markdown into a BibTeX file. Run `citation-verifier` for DOI / year / author / venue accuracy.

3. **K1220 — Cross-market K1142 replication (deferred K1145)**: if Path (b) adoption proceeds, K1220 runs the vol-normalized OFI specification on US ES / NQ as a robustness addendum. A universal vol-normalization result would materially strengthen the paper's claim.

## 11. References

- K1205 (2026-04-17) — Canonical synthesis of the four-branch null
- K1128 (2026-04-13) — VIX tertile IS-fixed, primary NULL
- K1131 (2026-04-17) — Natural cubic spline, NULL (reverse direction)
- K1142 (2026-04-17) — Vol-normalized OFI, PARTIAL_OOS_ONLY
- K1199 (2026-04-17) — Expanding-window adaptive quantile, NULL
- K1100g_d7 (2026-04-17) — Cross-market gap² replication, DIRECTION_CONSISTENT_ALL_BORDERLINE
- K1124 (2026-04-10) — TAIFEX TX 5-minute bar cache construction
- K1125 (2026-04-13) — Original OFI → jump regression (baseline M1-M4)
- `docs/error_log.md` 2026-04-13 entry — IS-regime degeneracy lesson
- `research_program.md` §Paper 3 — current state and narrative decision options
- CLAUDE.md "paper narrative state machine" rule — governs when body rewrite may begin
