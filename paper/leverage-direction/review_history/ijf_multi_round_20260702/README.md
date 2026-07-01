# IJF Multi-Round Review — 2026-07-02

**Task**: `paper_review_leverage_direction_ijf_multiround_20260702`  
**Target**: `paper/leverage-direction/main_v_ijf.tex` + `body_v_ijf.tex` + IJF package files  
**Overall verdict**: **FAIL_DO_NOT_ADVANCE**

The IJF reframe improved the contribution framing: the lead claim is now the complexity-ceiling / measurement-to-allocation wedge, and the leverage-direction taxonomy is supporting rather than the headline. That clears the prior contribution-framing objection at the prose level.

It does **not** clear the submission/arXiv gate. The central allocation-level evidence still conflicts with the manuscript's own "same windows / single protocol" language, and the IJF submission package is not yet clean enough for a journal-style final gate.

## Gate Checks Run

- `uv run python reproduce.py` in `paper/leverage-direction/`
  - GREEN: 194 checks, 171 MATCH, 23 NOTE, 0 MISMATCH, traceable match rate 100%.
- `latexmk -pdf -interaction=nonstopmode -halt-on-error main_v_ijf.tex`
  - Exit 0; `main_v_ijf.pdf` compiles to 35 pages; no undefined refs/cites found in log.
  - Noted non-blocking TeX warnings: small overfull hboxes and duplicate hyperref destinations for floats.
- `uv run python scripts/check_paper_compliance.py`
  - CLEAN after removing internal tool references from source comments.
- Citation key audit
  - 39 unique body cite keys; 39 `\bibitem`s; no missing or orphan bibliography entries.
- Format checks
  - Abstract = 143 words.
  - Highlights = 5 bullets; max bullet length = 80 characters, within Elsevier's 85-character rule.

## Pass Summary

| Pass | Verdict | Reason |
|---|---|---|
| LaTeX academic review | FAIL_MAJOR_REVISION | The paper still claims one OOS/sample protocol while the VT table uses asset-native windows; the central allocation-level wedge is not submission-grade. |
| Citation verification | CONDITIONAL_PASS | Citation graph is internally complete; several recent/forthcoming refs need final publisher-status verification, but no blocking fabricated citation found. |
| IJF journal gate | FAIL_MAJOR_REVISION | Reproducibility and compliance are mechanically green, but IJF/CASCaD readiness is not: stale JBF package docs, placeholder K903 README, draft AI disclosure/title-page issue, and mixed-window central evidence. |
| Contribution gate | CONDITIONAL_PASS_ON_FRAMING | Framing now leads with the complexity ceiling, but empirical support for the allocation wedge still needs repair. |

## Old JBF Findings Re-Audited

- Main file double-blind: **moot for `main_v_ijf.tex`**. The main file has no author block. Separate title page exists.
- Highlights too long / stale time-zone bullet: **fixed**. Current highlights are 5 bullets and reflect the IJF manuscript.
- Cover letter mismatch: **mostly fixed**. `cover_letter_ijf.tex` states one central complexity-ceiling claim.
- OOS/sample-map discipline: **not fixed**. The method prose says one protocol and same windows; the VT evidence still uses native windows.

## Blocking Fix List

1. Replace or reframe the VT central evidence so the allocation-level wedge is tested on a uniform, pre-declared OOS panel, or explicitly downgrade it to descriptive/native-window evidence.
2. Add a source-backed, dedicated result artifact for the extended `rho=0.83, N=14` MDD-volatility claim and the 6/6 OOS classification claim, or demote both to supplement-only caveats.
3. Update IJF package docs (`REPLICATION.md`, `submission_package.md`) away from stale JBF language and stale highlights.
4. Replace the draft generative-AI disclosure in `title_page_v_ijf.tex` with an author-approved final statement before any journal package is treated as ready.
5. Complete the placeholder `experiments/k903/README.md`; IJF's data/code policy expects a replicable package readable by an external checker.

**Decision**: Keep `storage/paper_pipeline_status.json` at `multi_round_review`; set `do_not_advance=true`; route fixes back to main-thread paper body/package work.
