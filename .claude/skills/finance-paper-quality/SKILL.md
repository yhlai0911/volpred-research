---
name: finance-paper-quality
description: >
  Evidence and exposition standards for writing or revising an empirical
  finance paper. Use in the main thread to align claims, methods, results,
  contribution, and limitations. It does not run formal review rounds, verify
  citations, compile the paper, or change pipeline state.
---

# Finance Paper Quality

Use this skill while the main thread writes or revises a paper. Actual `.tex`
changes and compilation follow `paper-update`; independent review follows
`latex-academic-reviewer` and `citation-verifier`.

## Non-negotiable standards

1. **Claim strength follows evidence.** Separate descriptive evidence,
   simulation, theory, in-sample fit, and genuinely out-of-sample evidence.
   Never generalize beyond the tested assets, horizon, period, or protocol.
2. **The economic question leads.** State the decision problem, comparator,
   information set, loss or utility consequence, and why the result matters.
3. **Mechanical and empirical effects stay distinct.** An identity,
   normalization, overlapping-window artifact, or selection rule is not an
   empirical discovery.
4. **Timing is explicit.** Forecasts and strategies must show the information
   set and lag; trading results require `signal.shift(1)` or an equivalent
   auditable implementation.
5. **Comparisons are fair.** Baselines use the same sample, horizon, lag,
   re-estimation schedule, loss definition, and transaction-cost convention.
6. **Inference matches the design.** Use appropriate DM/Harvey correction,
   bootstrap, forecast-comparison, and VaR/ES procedures; fix every stochastic
   seed and disclose multiplicity.
7. **Thresholds are justified.** Pre-specify them, derive them, or report
   sensitivity. A convenient round number is not a scientific rationale.
8. **Nulls and fragility remain visible.** Report failed specifications,
   unstable subperiods, economic insignificance, and limits on identification.
9. **Contributions are few and testable.** Each claimed contribution must map
   to a result, a comparator, and a precise literature gap.
10. **Reproducibility is part of the argument.** Every number and figure must
    trace to archived experiment output, with source, period, sample size,
    seed, and code identity.

## Main-thread writing pass

Before changing prose:

1. Identify the current candidate and the exact archived results supporting
   each proposed claim.
2. Check `docs/error_log.md`, relevant knowledge entries through bounded
   search, and `research_program.md` for superseded conclusions.
3. Build a claim-evidence table:

   | Claim | Evidence artifact | Design scope | Formal test | Limitation |
   |---|---|---|---|---|

4. Downgrade or remove any claim with no artifact-level support.
5. Make the smallest coherent revision through `paper-update`.

## Quality gate

A candidate is not review-ready when any of the following holds:

- headline results cannot be reproduced from the cited artifact;
- timing or baseline conventions differ across compared methods;
- a central claim lacks a formal test or omits a material null result;
- causal language exceeds the identification design;
- contribution statements are not traceable to results and literature;
- the manuscript hashes reviewed by downstream gates do not match the current
  candidate.

Return a short list of blocking issues, then major and minor improvements.
Do not change paper metadata or pipeline state from this skill.
