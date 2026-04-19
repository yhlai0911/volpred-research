# Paper 6 Pre-Submission Audit v1

- Paper: `paper/prg-periodic-garch`
- Audit date: 2026-04-19
- Auditor: Codex
- Scope: pre-submission audit for FRL readiness and PRS extension continuity
- Constraint honored: no edits to `main.tex`, no commit

## Audit Basis

Files reviewed:
- `paper/prg-periodic-garch/README.md`
- `paper/prg-periodic-garch/main.tex`
- `paper/prg-periodic-garch/citation_check.md`
- `paper/prg-periodic-garch/reproduce_report.json`

Commands / checks run:
- `./.venv/bin/python paper/prg-periodic-garch/reproduce.py`
- `pdflatex -interaction=nonstopmode -halt-on-error -output-directory=/tmp/prg_audit main.tex`
- `xelatex -interaction=nonstopmode -halt-on-error -output-directory=/tmp/prg_xe main.tex`
- `pdfinfo /tmp/prg_audit/main.pdf`
- `pdfinfo /tmp/prg_xe/main.pdf`

Note:
- Requested file `.agents/rules/paper-workflow.md` was not present in this workspace at audit time. Audit proceeded using repository-local paper files and control-plane docs.
- `session-bootstrap` failed because `agent-specs/guide.md` is missing; task closeout therefore requires the fallback `ops complete` path instead of `finish-task`.

## Scope Verdict Matrix

| Scope item | Verdict | Evidence | Remediation |
|---|---|---|---|
| 1. Read `README.md` + `main.tex` | PASS | README shows target FRL, status near submission, 19 citations, claimed 14 pages. `main.tex` reviewed at abstract, Introduction, Discussion, Conclusion, and bibliography. | None. |
| 2. Run `reproduce.py` and record match rate | WARN | Reproduce script ran and rewrote `reproduce_report.json`; match rate is `13/15 = 86.7%`. Alert is the known amber case. Live sub-runs did not complete because internal `uv` calls fail in this environment, so script fell back to stored JSONs. | No paper-body fix required for this task. Keep recorded as known amber due reproducibility environment / yfinance drift. |
| 3. Verify PRG vs PRS extension framing | FAIL | PRS is cited and PRG is explicitly framed as a parsimonious simplification in Introduction (`main.tex:60`) and Discussion (`main.tex:308`), but Conclusion (`main.tex:318-322`) does not mention PRS or the extension lineage. | Add 1-2 conclusion sentences stating PRG is a deterministic, practitioner-oriented extension/simplification of PRS rather than a rebranding. |
| 4. Check FRL hard requirements | FAIL | Abstract, keywords, and JEL are present, but current `main.tex` compiles to `16` pages under both `pdflatex` and `xelatex`, exceeding the `<=15` requirement. `\documentclass[12pt,a4paper]{article}` also violates the required `11pt` setting. | Reduce current manuscript to `<=15` compiled pages and switch to `11pt` final format before submission. Rebuild the PDF and refresh README/page metadata. |
| 5. Confirm `citation_check.md` contains PRS paper + DOI | WARN | `citation_check.md:29-54` explicitly tracks `Lai2024` and the correct DOI `10.1007/s10690-023-09415-w`; `main.tex:403-408` also includes the DOI. However, `citation_check.md` still labels this as an unresolved must-fix, so the live reference is stale relative to current manuscript state. | Update `citation_check.md` roll-up and Lai2024 status after main-thread final pass so the live tracker matches `main.tex`. |
| 6. Produce audit report | PASS | This file created at `paper/prg-periodic-garch/review_history/pre_submission_audit_v1/audit_report.md`. | None. |

## PRS Extension Framing Verdict

**Verdict: FAIL**

What passes:
- Introduction is explicit that PRS is the prior model and PRG is a parsimonious alternative that retains session-specific structure while removing Markov switching (`main.tex:60`).
- Discussion restates the exact methodological relation: PRG simplifies PRS by replacing Markov switching with a deterministic session index (`main.tex:308`).

What fails:
- Conclusion currently closes on PRG's standalone findings only (`main.tex:318-322`).
- Because the paper is positioned as an extension of the author's prior PRS work, omitting that lineage in the closing section leaves the extension framing incomplete at the exact point where reviewers expect a clean contribution summary.

Required remediation:
- Add a concise conclusion sentence that says PRG extends the PRS insight by replacing latent regime switching with an observed deterministic session index, yielding a simpler and more implementable specification.
- Keep the wording clearly in the "extension / simplification" lane, not "newly invented session model" lane.

## FRL Hard Requirements Audit

| Requirement | Status | Evidence | Notes |
|---|---|---|---|
| `(a) <= 15 pages` | FAIL | Current `main.tex` compiles to `16` pages under both `/tmp/prg_audit/main.pdf` and `/tmp/prg_xe/main.pdf`. | Repository `main.pdf` is an older 14-page artifact and is stale relative to current `main.tex`. |
| `(b) abstract <= 300 words` | PASS | Abstract count is approximately `181` words from `main.tex:39-47`. | Safely below limit. |
| `(c) keywords present` | PASS | `main.tex:43` contains `\textbf{Keywords:}`. | Present. |
| `(d) JEL codes present` | PASS | `main.tex:46` contains `\textbf{JEL Classification:} C22, C53, G17`. | Present. |
| `(e) single-column 11pt` | FAIL | `main.tex:5` is `\documentclass[12pt,a4paper]{article}`. `article` is single-column by default, but the size is `12pt`, not `11pt`. | Current formatting does not meet the stated 11pt requirement. |

FRL summary:
- Current hard-requirement status is **not submission-clean**.
- The hard blockers are page count and font-size format compliance.

## Reproducibility Audit Summary

- Command executed: `./.venv/bin/python paper/prg-periodic-garch/reproduce.py`
- Result: script completed its audit flow and rewrote `reproduce_report.json`, then exited non-zero because the built-in threshold gate flags `86.7% < 95%`.
- Reported match rate: `13/15 = 86.7%`
- Non-matching checks:
- `SPY DM_t (PRG vs GJR)`: paper `6.00` vs reproduced `5.1705`
- `SPY DM_t (PRG vs Separate)`: paper `-6.69` vs reproduced `-5.8608`
- Interpretation for this audit:
- This is consistent with the known amber state and does not by itself indicate a new manuscript regression.
- The environment also prevented live reruns because the script shells out to `uv`, which fails locally in this sandboxed session; stored JSON fallback still produced the expected amber report.

## Citation Check Status

PASS on presence, WARN on tracker freshness.

Evidence:
- `citation_check.md:29-54` names `Lai2024` and records the canonical DOI `10.1007/s10690-023-09415-w`.
- `main.tex:403-408` includes the same DOI in the bibliography.

Issue:
- `citation_check.md` still says the DOI is missing and labels it as must-fix, which is no longer true in the manuscript.

## Remaining Pre-Submission Blockers

Blocker family 1: PRS extension continuity
- Conclusion does not currently restate the PRS-to-PRG extension lineage.

Blocker family 2: FRL hard-format compliance
- Current `main.tex` compiles to 16 pages, above the 15-page cap.
- Current `main.tex` uses `12pt`, not the required `11pt`.

Non-blocking warnings:
- Reproduce remains amber at `86.7%`, consistent with the known yfinance drift case.
- `citation_check.md` is stale relative to the current bibliography state.
- README/page metadata still says 14 pages, but the current manuscript compiles to 16 pages.

## Recommended Main-Thread Fix Order

1. Fix Conclusion framing first so the PRS extension story is explicit at close.
2. Bring the manuscript into true FRL final format (`11pt`) and re-trim to `<=15` compiled pages.
3. Rebuild the final PDF with the intended engine and refresh README metadata.
4. Refresh `citation_check.md` so the live tracker no longer reports an already-fixed Lai2024 DOI issue.

## Bottom Line

This paper is close, but **not yet pre-submission clean**. The remaining blockers are concentrated and mechanical:
- one narrative blocker in Conclusion,
- two format blockers in FRL compliance (page cap and 11pt setting).
