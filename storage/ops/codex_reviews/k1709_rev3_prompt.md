# K1709 rev3 — independent re-review of the frozen claim surface

**Reviewer**: you (Codex, gpt-5.6-sol / ultra) — the same model that FAILed rev2.
**Sandbox**: read-only. You cannot write files, and that is deliberate: a reviewer that can
write is a reviewer that can "fix" the thing it was meant to judge. **Your verdict is your
stdout.** Emit it in the format at the bottom; the main thread transcribes it into
`review_verdict.json`.

**Files under review** (paths relative to repo root, you are running from repo root):
`.claude/worktrees/dispatch-slot-2-c873d04d-k1709/experiments/k1709/`
— `k1709.py`, `render_readme.py`, `README.md`, `k1709_results.json`, `test_k1709.py`

**Frozen commit**: `f3f9d3034b1a5cc4c42cacae1528178e798d08d1` (branch `exp/k1709-btc-etf-flow-vol`,
in that worktree). Experiment: spot BTC/ETH ETF flow → RV incremental predictability.

## What happened before you

You reviewed the frozen SHA `c97d690c` and returned **FAIL** with exactly one blocking defect
plus 4 non-blocking items. Your verdict is preserved at
`.../experiments/k1709/codex_review_rev2_c97d690c.txt`. Your blocking finding:

> `k1709.py`'s "Giacomini-White gate" implements the h_t ≡ 1 unconditional DM special case — no
> instrument vector, no q×q covariance, no Wald statistic, no chi-square_q. The README's "GW gate /
> GW z / Giacomini-White on QLIKE" therefore claims conditional / state-dependent predictive ability
> the design cannot deliver. The arithmetic is sound; the LABEL overreaches. The numbers support only
> what GW (2006) Sec 3.4 authorises: equal *unconditional* predictive ability under a bounded-memory
> forecasting method.

You offered fix (a) relabel, or (b) actually build the conditional GW test. The main thread took (a).

## What rev3 changed (this is what you are re-reviewing)

**No estimate moved. Not one.** The vendor flow vintage is not archived, so re-running the study to
fix a WORD would silently re-estimate it on a later sample — the numbers would move for reasons
having nothing to do with the correction, and the artefact you froze would cease to exist.

1. `k1709.py`: `giacomini_white` → `gw_unconditional_dm`. Docstring now leads with **what the test
   is NOT** (no h_t, no Wald, no chi-square_q) before explaining why the GW *name* is still apt (the
   estimation scheme — bounded memory — is what makes a DM-form statistic legal under nesting).
2. Every claim sentence in `verdict_basis` was extracted into a pure function `build_verdict_basis()`
   — counts in, words out, touches no data. A new `--relabel` entry point rebuilds those sentences
   from the frozen counts and **asserts every non-string field is byte-identical**, refusing to write
   if any number moves.
3. New field `conditional_predictive_ability_not_tested`: states plainly that a flow effect which
   helps in one regime and hurts in another, netting to zero on average, is invisible to this design
   and is NOT excluded by it.
4. Headline claim narrowed: "no incremental predictive content" → "no incremental **UNCONDITIONAL**
   predictive content".

Verify the "numbers unchanged" claim yourself — do not take it on trust. From inside that worktree:
`git show c97d690c:experiments/k1709/k1709_results.json` vs the current file; compare all non-string
values.

## Your task — rule on all five

1. **Claim surface.** Is any remaining sentence — README, docstrings, or results JSON — still
   claiming more than an unconditional, average-loss statement licenses?

2. **Numbers.** Did the relabel move any number, anywhere? (If yes → FAIL, and say which.)

3. **rev2's 4 non-blocking items** (bound-monotonicity assumption, fig2 event-day shift, README's
   live-rerun invariance promise, vendor vintage not archived): now fixed, or explicitly stated as
   limitations, or silently still there?

4. **The nested-DM ratchet.** The honest relabel **trips the repo's own gate**
   (`scripts/audit_nested_dm_misuse.py`, test `scripts/tests/test_nested_dm_misuse_ratchet.py`). That
   auditor decides lexically: "PRIMARY" within 80 chars of "DM" → raw DM adjudicating a nested
   comparison → violation. Under rev2's "GW gate" wording the file read as safe; now that it says
   truthfully "the primary family is judged by an unconditional GW/DM statistic", the auditor flags
   it. 61/62 of the experiment's own tests pass; this is the 62nd.
   **Do not let this be fixed by re-wording the experiment back into vagueness** — that is the auditor
   training the science to lie to it. The question: is the auditor's two-role model wrong (it cannot
   express a third, legitimate role — a DM-form statistic made valid under nesting by a bounded-memory
   fixed-window scheme), and if so, **what evidence must a file produce before the ratchet accepts
   that role?** Be adversarial: an escape hatch in a ratchet is how ratchets die. A separate task owns
   the auditor change — rule on it, do not edit it.

5. **NEW — the renderer's hardcoded prose (rule on this explicitly).** The main thread found that
   `render_readme.py` (~line 701-715, the `else:` branch) emits the README's reader-facing "Does say"
   bullet #1 as **hardcoded prose, not rendered from `verdict_basis`**:

   > "**No robust incremental predictive evidence was found** for spot BTC/ETH ETF net flow over a
   > HAR-RV baseline."

   The *same* sentence inside the frozen JSON reads: "no robust incremental **UNCONDITIONAL**
   predictive evidence was found". So the qualifier rev3 added lands in the JSON but **not** in the
   most-read line of the README — and because the sentence is renderer prose, `--relabel`'s
   byte-identity invariant cannot see it at all. The claim surface has **two authors** (JSON +
   renderer prose) and the invariant covers only one.

   Rule on: (a) is this a blocking claim-surface defect, or is it cured by README line ~38's blanket
   "Every claim below is therefore UNCONDITIONAL" disclaimer? (b) does "Does not say" need to carry
   rev3's conditional-predictability caveat as its own bullet? (c) independent of (a)/(b), is
   "claim sentences live in two places, one of them outside the invariant" itself a defect in the
   rev3 design that must be closed before merge?

## Rules

- Do NOT re-run `k1709.py` — it fetches an unarchived vendor vintage; a re-run destroys the frozen
  artefact. Read the code and the frozen JSON.
- **FAIL is a perfectly good answer.** Research honesty outranks closing the task. Anything but PASS
  blocks the merge into main, which is exactly what it is for.
- Do not soften a finding because rev3 "tried hard". The question is only whether the claim surface
  now matches what the code does.

## Output format (this is the deliverable — stdout only)

**Do not invent or restate a verdict schema.** `experiments/k1709/review_verdict.json` already exists,
generated by the repo's own gate (`scripts/experiment_gates.py verdict-template`), with the five
claim-surface files' sha256 already pinned. The main thread fills it from your stdout. A brief that
hand-writes the schema is exactly how rev2 nearly wasted a 30-minute review certifying nothing
(`.claude/rules/experiments.md` §審查認證) — so you emit findings, the gate owns the fields.

Line 1, exactly:
`REVIEWED_COMMIT: f3f9d3034b1a5cc4c42cacae1528178e798d08d1`

Line 2, exactly one of:
`VERDICT: PASS` or `VERDICT: FAIL` (anything but PASS blocks the merge — that is what it is for)

Then, under a `## BLOCKING DEFECTS` heading, one numbered entry per defect that makes this a FAIL
(write `none` if PASS). Each entry: file:line, what is claimed, what the code actually licenses.

Then your prose review under `## REVIEW`, organised by the five questions above. Q4's ratchet ruling
and any non-blocking items live **here, in prose** — not in the verdict JSON.

Finally, under `## SHA256`, the output of `shasum -a 256` for the five files you actually read, so the
main thread can confirm your bytes match the pinned ones (a drifted sha voids the verdict).
