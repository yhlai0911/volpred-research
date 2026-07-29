---
name: citation-verifier
description: >
  Read-only verification of citations and bibliography entries in academic
  manuscripts. Use for reference accuracy, claim-source alignment, DOI and
  bibliographic metadata, and submission-time citation freshness. Do not use
  it to edit the manuscript, change paper state, or perform a general paper
  review.
context: fork
agent: docs-researcher
---

# Citation Verifier

This is a **read-only evidence gate**. It produces a report; it never edits
`.tex`/`.bib`, changes pipeline state, or updates paper metadata.

## Inputs

- Candidate manuscript and bibliography paths.
- Candidate identity: SHA-256 for every reviewed `.tex`/`.bib` input.
- Optional prior report, used only to identify changes since the last review.
- Target journal, if already selected.

If an input cannot be opened or its identity cannot be recorded, return
`BLOCKED`; do not certify the citation gate.

## Verification procedure

1. Enumerate every in-text citation and bibliography entry. Report missing,
   orphaned, duplicate, malformed, or inconsistent keys.
2. Verify title, authors, venue, year, volume/issue/pages, DOI/URL, and
   publication status against primary sources: publisher pages, Crossref,
   official working-paper repositories, or the original paper.
3. Read the cited source far enough to test whether the manuscript's claim,
   scope, direction, and qualification are supported. Metadata-only matching
   is insufficient for claim verification.
4. Flag secondary-source dependence when a primary source is available.
5. Check that references described as current, forthcoming, working papers, or
   online-first still have that status.
6. If a target journal is known, verify its current reference-style rules on
   the journal's official site and record the URL and access time.

Use web access for current source metadata. Prefer DOI/publisher records over
search snippets, aggregators, or model memory.

## Severity and gate

- `MAJOR`: nonexistent/wrong source, source contradicts the claim, materially
  wrong attribution, or an unverifiable central citation.
- `MEDIUM`: material metadata error, weak source-to-claim fit, missing primary
  source, or unresolved publication-status change.
- `MINOR`: presentation/style issue that does not alter evidentiary meaning.

The gate passes only when there are **0 MAJOR** findings and every central
externally attributed empirical or methodological claim has a verified primary
source. MEDIUM and MINOR findings remain explicit; another workflow may impose
a stricter limit.

## Freshness contract

Every report must record:

- reviewed manuscript and bibliography hashes;
- report timestamp and verifier;
- authoritative URLs and access times for web-verified facts;
- unresolved items and their severity;
- `PASS`, `FAIL`, or `BLOCKED`.

A report is stale if any reviewed input hash changes, a cited working paper or
journal rule changes, or an unresolved item is later resolved. A stale report
cannot satisfy a pipeline gate and must be rerun on the current candidate.

## Output

Write a concise Markdown report with:

1. candidate identity and freshness metadata;
2. counts by severity and gate verdict;
3. a finding table (`location`, `citation`, `issue`, `evidence`, `fix`);
4. unresolved verification gaps;
5. a machine-readable summary block containing the hashes and verdict.

Recommend exact corrections, but leave all manuscript edits to the main-thread
`paper-update` workflow.
