# PRG review round v8 — 2026-08-05

**Paper**: `prg-periodic-garch` — *Forecast-Timing Conventions and the Value of Overnight
Information in Volatility Forecasting*
**Target**: Finance Research Letters
**Stage at round start**: `revision` (entered 2026-05-21; 76.7 days, the portfolio's longest)
**Previous round**: `paper/prg-periodic-garch/review_history/v7_review_20260714/`
(verdict `MINOR_FIXES`)
**Assigned by**: operations manager, work item
`item_20260805T084606769682Z_a-cadence-prg-periodic-garch-v7` (P1, decision 1 of 4)
**Executed by**: publications department, main thread

## ROUND VERDICT: `FAIL` — 4 MAJOR, 2 MINOR, 0 BLOCKING

Reviewable candidate, no fabrication, no lookahead, no unbound number. All four MAJORs are
prose fixes of one to two sentences each; none requires new computation. The paper is close to
referee-ready — closer than the raw finding count suggests — but three of the four MAJORs are
research-honesty defects (a false statement about its own robustness result, an unqualified
significance claim in the abstract, and an unsupported accusation against two published
papers), and those cannot ship.

## Archive location — read this first

**These reports belong in `paper/prg-periodic-garch/review_history/v8_review_20260805/`.**
They are here instead because the publications department could not write to `paper/` this
session (`Write` denied under the active permission mode; the department charter also declares
no owned paths outside its own subtree). The round is complete and the evidence is immutable
as written; only its filesystem location is provisional. Migration requested from the platform
engineering department — see the department journal entry for 2026-08-05.

## Contents

| File | SHA-256 | Bytes |
|---|---|---|
| `latex_review.md` | `5e9c7509dbd1bf89f67d5f6b6368c78cc3a54f66cc8c2fd3c4417bf296ca3e81` | 14,610 |
| `citation_report.md` | `c26e7f5d88195eeb9b852326e8aa7882332560a91a1d102a91859e7e5f029655` | 7,414 |
| `reproducibility_manifest.md` | `c1e24145165c7bd724a20feca0c07be73637188ffaa684c22d384c575531a92d` | 8,846 |

(Hashes cover the files as first written; this README is excluded, since it names them.)

## Candidate identity

| File | SHA-256 | Bytes |
|---|---|---|
| `main.tex` (canonical per `canonical.json`) | `8852326a7b77eb3455038f558c823dcefa311a282697f82ff2e5d798813c86ed` | 30,408 |
| `main.pdf` (untracked; page-1 content matches) | `8c2d2ddc673df0f7b153365f23095fc846e629ef620040a68e63cd65af95f017` | 68,804 |
| `experiments/k1699/k1699_results.json` | `b258c40489bccc1146cf31b1a8bd40c857541f343253259db62102816de52c3a` | 29,380 |
| `experiments/K1710/K1710_results.json` | `7e5f4b5c38372b0d5e2d745f95be05b06a91a651f8974a822dce6457380c6da9` | 29,850 |

Repo HEAD at round start: `431de4564`. Full manifest in `reproducibility_manifest.md` §1.

## Commands run

```bash
uv run python scripts/paper_pipeline_check.py                                    # read model
uv run python scripts/reproduce_check.py inventory
uv run python scripts/reproduce_check.py run --experiment k1699  --timeout 1200  # unverified
uv run python scripts/reproduce_check.py run --experiment K1710 --timeout 1200   # unverified
git log --format='%h %ad %s' --date=iso -6 -- paper/prg-periodic-garch/
git show 9f868e41f -- src/volpred/stats/model_evaluation.py                      # +3 lines
jq … experiments/{k1699,K1710}/*_results.json                                    # 24 DM cells
```

Plus two throwaway scripts (AST function-level hashing of the shared stats module; FRL word
count), both reported inline in `reproducibility_manifest.md` §3 and `latex_review.md`.

## Findings

| # | Severity | Location | One line |
|---|---|---|---|
| MAJOR-1 | MAJOR | L207 vs L103–106 | Conclusion names Tsiakas (2008) and Todorova & Souček (2014) as instances of the mixed-timing confound; neither commits it, §2.3 says no published instance is known, and Todorova & Souček is an FRL paper — the target venue |
| MAJOR-2 | MAJOR | L198 | "Nothing approaches the conservative threshold in either variant" is false — QQQ's lagged cell is t = −2.95, p = 0.003, 0.048 below the paper's own threshold |
| MAJOR-3 | MAJOR | L39 vs L187 | Abstract's "zero of six markets significant" has no threshold qualifier; QQQ is p = 0.023 (exp) and p = 0.003 (lag). The §4.1 fix for this exact defect did not reach the abstract |
| MAJOR-4 | MAJOR | L118 footnote | "Every number … reproduces bit-identically from the archived snapshots" has no passing end-to-end receipt; the experiment gate is `unverified` |
| MINOR-1 | MINOR | L111 | Multiple-testing family excludes the six lagged tests on a data-dependent, and partly inaccurate, rationale |
| MINOR-2 | MINOR | L195 | "High overnight share" group omits 0050.TW (63.5%), which outranks GLD (60.9%), included |

## Ordered revision list for `paper-update`

Sequenced so each edit is independent; 1–3 are the honesty-critical ones.

1. **L198** — replace the lagged-variant sentence with the version in `latex_review.md`
   MAJOR-2. Reports the QQQ number explicitly; the paragraph gets stronger, not weaker.
2. **L39** — add "clear the conservative |t| > 3 threshold" to the close-panel claim
   (MAJOR-3). Abstract is at 230/250 words; costs 9.
3. **L207** — drop `\citep[e.g.,][]{Tsiakas2008,Todorova2014}`, or reframe both as coherent
   open-time antecedents **after** confirming their designs against the primary PDFs
   (MAJOR-1). Do not commit the reframed sentence on secondary sources alone.
4. **L118 footnote** — soften to the binding claim that is evidenced (MAJOR-4), or hold until
   the experiment gate can produce a passing end-to-end receipt.
5. **L111** — fix the family definition ex ante (MINOR-1). Either all 24 tests, threshold
   3.0 → 3.08, no verdict changes; or state the diagnostics are outside the family and why.
6. **L195** — add 0050.TW to the high-share enumeration (MINOR-2).

After the edits: recompile, rerun `paper/prg-periodic-garch/reproduce.py`, and open round v9.
All three reports in this round are bound to `main.tex` sha256 `8852326a…` and go stale the
moment the first edit lands.

## Unresolved / carried forward

- **Experiment reproducibility gate is `unverified`** for both k1699 and K1710
  (`INPUT_HASH_MISMATCH` on `src/volpred/stats/model_evaluation.py`). Proved non-substantive
  at function level, but no end-to-end receipt exists. Blocks the submission-package gate, not
  this round.
- **Codex independent methodology track not run.** `codex exec` and
  `scripts/codex_exec_bounded.sh` are both denied under the active permission mode. This round
  is two-track (referee + citation) against the v7 round's three. The v7 Codex track is what
  caught M5 and M6 — the same defect class as this round's MAJOR-2 and MAJOR-3 — so a third
  track for round v9 is worth restoring rather than skipping.
- **FRL reference-style compliance unverified.** Manuscript uses `apalike` author–year;
  `WebFetch`/`curl` denied this session, and secondary sources disagree. For the
  journal-review gate before submission.
- **Submission-package items**: no CRediT statement; `\thanks` says data available "upon
  request" while a self-contained replication package exists.

## Pipeline note

The blocker string in `storage/paper_pipeline_status.json` — *"v7 review cycle (latex +
citation + Codex) not yet run"* — is factually wrong and should be corrected rather than
cleared. The v7 round ran on 2026-07-14 and its six MAJORs were fixed across `e2ffd8d90`,
`af81d2e73` and `c23e36b5c`. The real blocker was the post-revision round, which is this one.
Proposed replacement: *"v8 review round FAIL (4 MAJOR, 2 MINOR) 2026-08-05; awaiting
paper-update on the ordered revision list, then round v9."*

No pipeline state was written by this round. `paper-review-cycle` does not advance state, and
the department has no verified canonical writer for this transition in the current checkout.
