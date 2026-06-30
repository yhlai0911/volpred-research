# Generic Pre-Submission Checklist (floor — every journal extends)

This is the MINIMUM gate for any submission. Each `references/<abbrev>.md` adds
the journal's specific mechanical rules on top (abstract cap, highlights, fee,
data policy, anonymization model). Run this FIRST, then the journal's own list.

## Compliance (hard — cross-ref `paper-workflow.md` / `publishing.md` rules)
- [ ] **Authorship = Yi-Hao Lai (賴奕豪) ONLY.** No co-authors. No AI / agent
      listed as author (Elsevier/JFE/RFS forbid AI authorship).
- [ ] **No "volpred" / "VolPred" / "AI" / "LLM" / "Claude" / "Codex" / agent /
      model branding** anywhere — manuscript, title, abstract, metadata,
      acknowledgements, filenames, figure captions, or code comments shipped in
      the replication package. `grep -ri` the .tex + .bib + the package to prove it.
- [ ] If generative AI was genuinely used in preparation and the journal requires
      it (Elsevier/IJF/PBFJ), put a generative-AI-use declaration as a SEPARATE
      titled section before references — never satisfy it by branding the paper as
      AI-authored, and never hide a real use.
- [ ] **No AI-style phrasing** in reader-facing prose (abstract, introduction) —
      run `anti-ai-style` editor SOP.

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
- [ ] Submission fee budgeted + paid where required (JFE $850 · JBF $350 ·
      PBFJ $220 · FRL $200 · JoE $75; RFS tiered; IJF/JoF/JPM/FAJ none) — confirm
      scope fit BEFORE paying (non-refundable; forfeited on desk-reject).
- [ ] Declarations completed (COI / funding / CRediT / generative-AI use) per the
      journal's tool.
- [ ] Cover letter prepared where required (`templates/cover-letter.md`).
- [ ] Boss notified with target journal + fee + decision horizon + open risks
      before the portal upload; actual submission is a boss decision.
