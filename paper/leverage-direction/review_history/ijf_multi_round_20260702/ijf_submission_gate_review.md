# IJF Submission Gate Review

**Verdict**: **FAIL_MAJOR_REVISION**  
**Target journal**: International Journal of Forecasting (IJF)

## IJF Fit

The topic fits IJF better than the old JBF framing. The paper is now a forecasting/evaluation paper about when volatility measurement improves downstream decisions, and IJF explicitly covers financial forecasting, evaluation, and implementation.

The fit is still conditional on tightening the empirical gate. IJF is receptive to honest null/negative results, but the negative result has to be produced by a clean OOS protocol and a reproducible package.

## Mechanical Format Checks

- `main_v_ijf.tex` uses `elsarticle` with `review` option.
- Main PDF compiles: 35 pages, no undefined refs/cites.
- Abstract: 143 words, within the IJF profile's 100-150 word target.
- Highlights: 5 bullets; longest bullet 80 characters, within Elsevier's 85-character rule.
- `cover_letter_ijf.tex` now states one central complexity-ceiling contribution rather than the stale three-contribution JBF letter.

## Compliance Checks

- `scripts/check_paper_compliance.py` is CLEAN after removing internal platform/tool references from source comments.
- `pdftotext main_v_ijf.pdf` has no VolPred / Claude / Codex / OpenAI / Anthropic / internal K-id hits.
- `main_v_ijf.tex` contains no author block; title page is separate.

## Blocking Submission-Package Issues

### J1. Title-page AI disclosure is still a draft placeholder

`title_page_v_ijf.tex:40` contains a draft generative-AI disclosure that explicitly says it requires author sign-off and is not finalized. That is honest as a working file, but it is not a submission-ready declaration.

**Required fix**: author must approve or rewrite the disclosure before any journal package is treated as ready. Do not silently remove a real AI-use disclosure; finalize it accurately.

### J2. IJF reproducibility package is not yet external-checker ready

IJF/IIF policy makes data/code sharing mandatory in normal cases and conditions acceptance on reproducibility checks. The local `reproduce.py` gate is green, but the external package docs are stale or incomplete:

- `REPLICATION.md:3`-`4` still names the old title and target journal JBF.
- `submission_package.md:1`-`5` is still a JBF package with a stale READY_FOR_UPLOAD status.
- `submission_package.md:34`-`42` still lists old JBF highlights with stale gold/time-zone claims.
- `experiments/k903/README.md:1`-`20` is a placeholder with "planning" / "待補充".

This is not compatible with a CASCaD-style reproducibility handoff.

### J3. The central allocation-level claim is not supported by the stated OOS protocol

The manuscript claims a single OOS protocol, but the main VT table uses asset-native windows. That is a journal-submission blocker because the complexity-ceiling contribution turns on the allocation-level result.

See `latex_academic_review.md` H1 for line-level evidence.

### J4. Pipeline status had stale gate facts

The task/status description said 26 pages and `elsarticle.cls` unavailable in earlier notes. Current verification shows:

- `kpsewhich elsarticle.cls` is available via TeX Live 2026.
- `main_v_ijf.pdf` compiles to 35 pages under `elsarticle[review]`.

The status file has been updated to record this review result.

## External IJF Sources Used

- IJF/IIF scope and double-blind/data-code/reproducibility policy: <https://forecasters.org/ijf/>.
- IJF author page: code/data sufficient for replication and LaTeX/BibTeX guidance: <https://forecasters.org/ijf/authors/>.
- Elsevier highlights guidance: 85-character limit: <https://www.elsevier.com/researcher/author/tools-and-resources/highlights>.

## Bottom Line

Do not advance to `arxiv_ready` or journal submission package. The package needs a paper-body/evidence fix plus replication-package cleanup, then a fresh multi-round review.
