# Generic Pre-Submission Checklist (floor — every journal extends)

This is the MINIMUM gate for any submission. Each `references/<abbrev>.md` is a
local checklist, not live authority. Run this first, then verify every material
journal rule on an official page and record its URL and access timestamp.

## Compliance (hard — cross-ref `paper-workflow.md` / `publishing.md` rules)
- [ ] **Authorship = Yi-Hao Lai (賴奕豪) ONLY.** No co-authors. No AI / agent
      listed as author (Elsevier/JFE/RFS forbid AI authorship).
- [ ] **No "volpred" / "VolPred" / "Claude" / "Codex" / agent/model branding**
      anywhere — manuscript, title, abstract, metadata, acknowledgements,
      filenames, figure captions, or shipped code comments. Required,
      factually accurate AI-use disclosure is not branding and must not be
      suppressed. Scan the full submission set and preserve the receipt.
- [ ] If generative AI was genuinely used in preparation and the journal requires
      it (Elsevier/IJF/PBFJ), put a generative-AI-use declaration as a SEPARATE
      titled section before references — never satisfy it by branding the paper as
      AI-authored, and never hide a real use.
- [ ] **No AI-style phrasing** in reader-facing prose (abstract, introduction) —
      run `anti-ai-style` editor SOP.

- [ ] **No fabricated acknowledgments** (boss 2026-07-01). An unpublished
      manuscript has NOT been presented at a seminar/conference and has NOT been
      peer-reviewed, so "I/we thank seminar participants / conference participants
      / (two) anonymous referees for helpful comments" is *fabrication*. Remove it.
      Add real thanks only after a real presentation/review. Make a data/code
      availability claim only when the package actually satisfies it.
- [ ] **No internal experiment-registry IDs (K123 / K1234)** in any reader-facing
      text, table caption, footnote, or bibliography `\bibitem`. Reword to the
      paper's own "canonical replication" / Section / Table refs or "(replication
      package)". They are meaningless to a referee and leak the internal system.
- [ ] **Unpublished integrity ("尚未發表")**: the manuscript must not reveal that
      its findings were previously disseminated on a public platform/blog/feed.
      ("Online supplement / online appendix" referring to the paper's *own*
      accompanying file is standard and fine — not a prior-publication signal.)
- [ ] **Scope boundary**: scrub the *submission set only* (main.tex compile
      closure + cover_letter + supplementary). Internal provenance — version
      archives (`*_v2/_v3/_backup`) and `*_diff.tex` revision records that honestly
      attribute work to the AI system — stay honest (do NOT falsify) and must NOT
      ship in the replication package.
- [ ] **Automated gate (run last, must be CLEAN)**:
      `uv run python scripts/check_paper_compliance.py <paper-id> --json`
      scans one paper using its installed positional interface. Preserve the
      current candidate's findings and scanned-file closure.
- [ ] If an official journal rule requires a truthful disclosure that the
      current checker rejects, mark the compliance gate `BLOCKED` and create an
      implementation/governance task. Never omit a required disclosure or
      bypass the checker merely to obtain a clean receipt.

## Reproducibility (hard — cross-ref `experiments.md`)
- [ ] Replication package regenerates EVERY table and figure from raw or
      clearly-instructed data (fixed seeds for bootstrap/MC/CV/train-test split).
- [ ] README + pinned environment (software/OS versions, module list).
- [ ] Data-availability statement written; data + code deposited in / ready for
      the repository the journal mandates (JBF Option C / JFE Mendeley / RFS
      Harvard Dataverse / IJF CASCaD / FRL Option C / PBFJ); confidential data →
      runnable synthetic/pseudo dataset + cover-letter exemption.
- [ ] No look-ahead: explicit `signal.shift(1)` / lag; forward-label
      `target_end < forecast_origin`; baseline and proposed model use the same lag
      convention.

## Format
- [ ] Abstract within the journal's word cap (count it — see the per-journal ref).
- [ ] Main-text / page length within the journal's limit.
- [ ] Highlights file if required (3-5 bullets, each ≤85 chars incl. spaces,
      filename contains "highlights").
- [ ] Anonymization correct for the journal's review model (double-blind: strip
      names/affiliations/acks/self-identifying cites + file metadata; single-blind
      e.g. JoF: keep author block) — see the per-journal ref.
- [ ] Separate title page file where required (names/affiliations/emails/ORCID).
- [ ] References in the journal's style (author-date Harvard / APA / Chicago —
      NOT numbered unless specified); every in-text cite ↔ list entry matches;
      DOIs added; verified via `citation-verifier`.
- [ ] **Figures vector / high-resolution**; legible in black-and-white where the
      journal prints/reviews in B&W (FAJ, JPM); editable tables/equations (not
      images) for Elsevier journals.
- [ ] Editable source supplied where required (.tex elsarticle / single-column
      .docx); PDF not an acceptable source for Elsevier.
- [ ] Keywords (and JEL codes where the journal uses them) on the title page.

## Substance
- [ ] Contribution framed for THIS journal's audience (see step 5 of SKILL.md).
- [ ] 2-3 concrete, defensible contributions; claim strength matches evidence
      scope (no "only/unique" without re-verifying the current results table).
- [ ] Robustness battery incl. a crisis/bear subperiod; multiple-testing control
      where many models/strategies are compared (SPA / Reality Check / Romano-Wolf).
- [ ] Forecast-eval correctness (vol work): DM / HLN / Giacomini-White / MCS;
      QLIKE = actual/predicted; horizon-matched inference; cluster-robust or
      date-aggregated loss (no asset-day iid pooling); proper VaR/ES + Basel
      calibration.
- [ ] Multi-round `latex-academic-reviewer` + `citation-verifier` findings
      converged (no new structural/citation defects).

## Process
- [ ] Current submission fee and refund terms verified on an official page,
      with URL/access time recorded. Stop for the user before any payment.
- [ ] COI, funding, CRediT, originality, and generative-AI declarations are
      prepared from verified facts. Stop for the author before a legal
      attestation or signature.
- [ ] Cover letter prepared where required (`templates/cover-letter.md`).
- [ ] Target, verified fee, expected decision horizon, and open risks recorded
      in the submission receipt. Routine target/timing decisions use the
      standing authorization; stop only at the non-delegable boundaries above
      (or login/MFA).
