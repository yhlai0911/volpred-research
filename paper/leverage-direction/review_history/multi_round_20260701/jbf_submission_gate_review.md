# JBF Submission Gate Review — 2026-07-01
Verdict: FAIL_MAJOR_REVISION
High findings: 5
Medium findings: 4

Basis: reviewed the project JBF profile, manuscript source, main tables, cover letter, and prior Codex contribution gate. I also spot-checked the current ScienceDirect JBF guide on 2026-07-01; it conflicts with the local JBF profile on abstract length (official guide says 250 words, local profile says 150). Until the project profile is updated, this gate treats `.claude/skills/journal-review/references/jbf.md` as the local submission checklist.

## High Findings

### H1. Main manuscript is not JBF double-blind compliant

JBF local profile requires a fully anonymized main file, a separate title page, and strict double-anonymization (`.claude/skills/journal-review/references/jbf.md:16`, `.claude/skills/journal-review/references/jbf.md:22`, `.claude/skills/journal-review/references/jbf.md:31`, `.claude/skills/journal-review/references/jbf.md:36`). The active main manuscript includes author identity, affiliation, email, and a title-footnote data/code statement in the main file (`paper/leverage-direction/main.tex:25`, `paper/leverage-direction/main.tex:27`). The package checklist also incorrectly records that JBF is "non-blinded" and retains the author block (`paper/leverage-direction/submission_package.md:51`, `paper/leverage-direction/submission_package.md:53`).

JBF action: create an anonymized manuscript source/PDF, separate title page, and remove identifying footnotes, acknowledgements, metadata, and author source comments from the blinded main file.

### H2. Required JBF package items are missing or mis-specified

JBF requires an anonymized manuscript, separate title page, highlights, data-availability statement, and declarations including COI/funding/AI/CRediT (`.claude/skills/journal-review/references/jbf.md:21`, `.claude/skills/journal-review/references/jbf.md:22`, `.claude/skills/journal-review/references/jbf.md:31`, `.claude/skills/journal-review/references/jbf.md:37`, `.claude/skills/journal-review/references/jbf.md:39`). The current portal bundle lists PDFs, cover letter, highlights, and graphical abstract, but no separate title page, declarations file, or formal data-availability statement (`paper/leverage-direction/submission_package.md:14`-`paper/leverage-direction/submission_package.md:24`). The available provenance file is useful but is a data-sources memo, not a submission statement (`paper/leverage-direction/data_sources.md:10`-`paper/leverage-direction/data_sources.md:15`). The main manuscript still says data/code are "available upon request" (`paper/leverage-direction/main.tex:25`), which is weaker than the JBF Option C deposit-or-explain standard.

JBF action: add a formal data-availability statement, declarations/CRediT/AI-use files or portal text, title page, and an editable source bundle containing `main.tex`, `body.tex`, `tables_main.tex`, figures, bibliography/bbl, supplement, and replication material.

### H3. Highlights fail JBF format and include a contribution not in the manuscript

JBF highlights must be a separate editable file with 3-5 bullets, each no more than 85 characters including spaces (`.claude/skills/journal-review/references/jbf.md:31`, `.claude/skills/journal-review/references/jbf.md:35`). The current file has five bullets, but the bullets are approximately 125-203 characters each (`paper/leverage-direction/highlights.txt:3`-`paper/leverage-direction/highlights.txt:7`). The fifth highlight asserts US-to-Asia time-zone momentum (`paper/leverage-direction/highlights.txt:7`), while the active abstract and introduction frame only two contributions (`paper/leverage-direction/main.tex:39`, `paper/leverage-direction/body.tex:9`-`paper/leverage-direction/body.tex:13`).

JBF action: rewrite highlights as five short bullets under 85 characters and remove the time-zone bullet unless the manuscript is rebuilt around that contribution.

### H4. Cover letter is inconsistent with the manuscript and JBF submission process

The local JBF profile says new submissions do not require a formal cover letter and do not request suggested reviewers (`.claude/skills/journal-review/references/jbf.md:22`). The cover letter nevertheless includes suggested reviewers (`paper/leverage-direction/cover_letter.tex:37`-`paper/leverage-direction/cover_letter.tex:43`). It also says the paper has three contributions (`paper/leverage-direction/cover_letter.tex:29`) and adds a time-zone arbitrage contribution (`paper/leverage-direction/cover_letter.tex:33`), while the manuscript says it makes two contributions (`paper/leverage-direction/main.tex:39`, `paper/leverage-direction/body.tex:9`-`paper/leverage-direction/body.tex:13`, `paper/leverage-direction/body.tex:511`). The package memo repeats this three-contribution framing (`paper/leverage-direction/submission_package.md:29`).

JBF action: if the portal permits no cover letter, omit it. If a cover letter is uploaded anyway, align it to the two-contribution manuscript and remove suggested reviewers/time-zone claims.

### H5. Single desk-reject risk: contribution still looks unsettled rather than JBF-clean

Topical fit is plausible: JBF scope includes empirical/applied finance, financial markets, risk management, volatility forecasting, and institutional decision relevance (`.claude/skills/journal-review/references/jbf.md:7`-`.claude/skills/journal-review/references/jbf.md:10`, `.claude/skills/journal-review/references/jbf.md:40`). The manuscript covers GARCH selection, VaR/ES, and volatility targeting (`paper/leverage-direction/body.tex:212`-`paper/leverage-direction/body.tex:218`, `paper/leverage-direction/body.tex:242`-`paper/leverage-direction/body.tex:253`). The desk-reject risk is not scope; it is that the paper still reads as an overextended empirical GARCH/VT exercise with many modules. The prior contribution gate explicitly judged it "CONTRIBUTION BORDERLINE" (`paper/leverage-direction/review_history/codex_contribution_gate_20260701.md:10`-`paper/leverage-direction/review_history/codex_contribution_gate_20260701.md:14`) and identified the likely desk-reject reason as an incremental exercise with unstable claims (`paper/leverage-direction/review_history/codex_contribution_gate_20260701.md:118`-`paper/leverage-direction/review_history/codex_contribution_gate_20260701.md:122`). The manuscript itself admits 110+ experiments and in-sample thresholds pending replication (`paper/leverage-direction/body.tex:497`).

JBF action: make the submission package tell one JBF story: leverage direction as an economically interpretable state variable for risk management and allocation. Move or suppress time-zone, broad complexity-ceiling, HAR/VIX/crowding side claims unless directly tied to that story.

## Medium Findings

### M1. Abstract length gate is ambiguous but currently unsafe

The local JBF profile says the abstract cap is 150 words (`.claude/skills/journal-review/references/jbf.md:14`, `.claude/skills/journal-review/references/jbf.md:34`). The active abstract paragraph is about 246 rendered words, and the full LaTeX abstract environment is about 264 words because keywords/JEL are inside it (`paper/leverage-direction/main.tex:36`-`paper/leverage-direction/main.tex:48`). The current official ScienceDirect guide appears to use a 250-word cap, so the paragraph may pass official JBF but fails the local profile and becomes borderline if the portal extracts the whole environment.

JBF action: update the project JBF profile if the 250-word cap is accepted, move keywords/JEL outside the abstract environment/title-page file, and keep the rendered abstract clearly below the active cap.

### M2. JBF fit is real but the framing is not yet sufficiently institutional/policy-facing

JBF's profile emphasizes applied finance, implementation, and communication to policymakers/operational decision-makers (`.claude/skills/journal-review/references/jbf.md:7`-`.claude/skills/journal-review/references/jbf.md:10`, `.claude/skills/journal-review/references/jbf.md:40`). The cover letter says the paper fits because it addresses GARCH model selection, Basel III VaR, and implementable strategies (`paper/leverage-direction/cover_letter.tex:35`), but the manuscript title/abstract still foreground a broad cross-asset model-selection and VT contribution (`paper/leverage-direction/main.tex:25`, `paper/leverage-direction/main.tex:39`).

JBF action: sharpen first-page framing around institutional risk management: when asymmetric volatility has economic content, when it matters for model selection, and what risk managers should do differently.

### M3. Source format and upload bundle are not yet Elsevier-ready

The local JBF profile says editable source is required and PDF alone is not acceptable as source (`.claude/skills/journal-review/references/jbf.md:19`, `.claude/skills/journal-review/references/jbf.md:38`). The package bundle currently lists `main.pdf` and `supplementary.pdf` as manuscript files (`paper/leverage-direction/submission_package.md:16`-`paper/leverage-direction/submission_package.md:20`). The source uses generic `article` rather than `elsarticle` (`paper/leverage-direction/main.tex:1`); this may be acceptable at submission only if the portal accepts generic LaTeX, but it is not the clean Elsevier path.

JBF action: prepare a source ZIP and consider converting to `elsarticle` after content is frozen, or document that JBF accepts the current source class.

### M4. Graphical abstract should not be in the JBF package

The local JBF profile says JBF has no graphical abstract (`.claude/skills/journal-review/references/jbf.md:18`, `.claude/skills/journal-review/references/jbf.md:31`). The package nevertheless lists PNG/PDF/SVG graphical abstract files for portal upload (`paper/leverage-direction/submission_package.md:22`-`paper/leverage-direction/submission_package.md:24`, `paper/leverage-direction/submission_package.md:44`-`paper/leverage-direction/submission_package.md:49`).

JBF action: remove graphical abstract artifacts from the JBF upload bundle unless the Editorial Manager portal explicitly asks for them.

## Short JBF Action Checklist

- Freeze the JBF rule source: reconcile local `jbf.md` with the current official guide, especially abstract cap and cover-letter handling.
- Build a double-blind main file and separate title page; do not submit the current `main.tex` as the blinded manuscript.
- Replace `available upon request` with a JBF Option C data/code availability statement and repository/deposit plan, or an explicit non-availability explanation.
- Add declarations: COI, funding, CRediT, and AI-use statement if any generative AI was used.
- Rewrite highlights to 3-5 bullets under 85 characters; remove time-zone momentum.
- Drop or rewrite the cover letter; remove suggested reviewers and all contribution claims not in the manuscript.
- Remove graphical abstract from the JBF package.
- Reframe the package around one contribution: leverage direction as economic content for risk management/model selection/VT, with side modules moved to supplement or omitted.
