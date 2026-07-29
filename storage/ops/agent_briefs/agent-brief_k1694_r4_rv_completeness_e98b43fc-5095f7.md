# K1694 split stage 1/2 — RV completeness certification repair (Codex round-4 FAIL)

**Model**: opus / max (per model_router --task-type experiment --attempt 2; `at_ceiling=true`, `exhausted=true` → this is the 3-strike "decompose the problem" response, NOT an identical retry)

**Parent timed-out job**: `agent-brief_k1694_repair_e98b43fc-ea643c` (budget 3600s, killed at 3480s)
**Split stage**: `rv-completeness-repair` (stage 1 of 2)
**Worktree (your cwd)**: `.claude/worktrees/dispatch-slot-1-e98b43fc-k1694`
**Required artifact (single)**: `experiments/K1694/r4_repair_report.json`

---

## 0. What already happened — do NOT redo it

The parent job did **not** fail. It ran three full repair rounds and got killed by the wall
clock while writing up round 4. Its work is **already committed** in your worktree:

```
116c42ebc K1694: repair the three Codex round-3 FAIL defects and re-run
5392d2ae7 K1694: repair the four Codex round-2 FAIL requirements and re-run
8e96d1957 K1694: repair all 8 Codex round-1 FAIL defects and re-run
aad5ce399 K1694: preserve Codex round-4 verdict (...) from timed-out job
```

**Read `storage/ops/codex_reviews/k1694_verdict_round4.md` first.** It is the round-4 Codex
verdict: **FAIL**, but with a narrow scope — estimator, provenance and NULL scope did **not**
regress, and a long list of checks passed (DCOT entry-gap fix, `MAX_DCOT_GAP_DAYS` separation,
NOT SUPPORTED wording, 3275/3275 overlap母體一致, bootstrap / shared sample / stationary
bootstrap / t−2 adjacency / PIT regime timing, provenance sha `92b0b771…` + bytes `7075ab8f…`).

**Your scope is exactly the two remaining blocking defects plus one documentation nit. Do not
re-open anything on the passed list.** Widening scope is how the parent ran out of clock.

---

## 1. Blocking defect D1 — count-only RV completeness blind spot is wider than claimed

`_expected_trading_days()` (`experiments/K1694/K1694.py:493`) builds the expected trading-day
count as *weekdays minus US federal holidays minus Good Friday*. It subtracts **Columbus Day and
Veterans Day, on which CME futures actually trade**, so it **understates** the true trading-day
count. The docstring argues that direction is "safe because it only makes the rule more
permissive" — that is true for false negatives, but it **refutes the detection claim the results
file actually makes**.

Codex's reproducible counterexample (verify it yourself before fixing):

- Month **2020-10**: calendar `expected = 21`; every one of the 22 commodities in the frozen
  cache actually has `ndays = 22`.
- Truncate **all 22 commodities by 2 days** (common truncation): `max(ndays) = 20`,
  `expected - max = 1`, cross-sectional shortfall `= 0`.
- Result: **22/22 rows still `rv_complete = True`** — a 2-day common truncation is invisible.

This falsifies, as currently worded, all four of:

- `sample.completeness.rule.rv_rule_detects` — claims a common truncation "of 2 or more days" is detected
- `sample.completeness.rule.rv_residual_blind_spot` — claims the blind spot is "exactly ONE day"
- `sample.panel_span_is_complete_months_only: true`
- `README.md` — "3275 列皆為完整月份"

## 2. Blocking defect D2 — the date-bearing path is not the "true endpoint test" it claims to be

`K1694.py:480-489` admits up to **3 weekday gaps at both the head and the tail** of the month
(`rv_head_gap_days.le(3) & rv_tail_gap_days.le(3)`). Codex's counterexample:

- Inject date columns for **2020-06** and drop **6/30** from every commodity:
  `last_day = 2020-06-29`, `rv_month_shortfall = 1`, `rv_tail_gap_days = 1`
  → **22/22 still complete**.

So the date path carries the very one-day endpoint blind spot that
`sample.completeness.rule.rv_endpoint_test` says exists **only** in the count-only cache
("build_vol() now records them, so any regenerated cache upgrades this to a true endpoint test").
The existing tests only assert the rule string flips to `"applied"`; **none injects head/tail
truncation**.

## 3. Non-blocking (fix while you are in there)

- `README.md` line ~127 still references the deleted key `fcm_avail_inside_outcome_month_rows`.
- The round-2 history table still describes a **retired** completeness rule in the present tense.

---

## 4. Required resolution — pick ONE per defect, with evidence either way

Codex explicitly allows two honest resolutions. **Both are acceptable; what is not acceptable is
a claim that the code does not actually enforce.** Research honesty (AGENTS.md #10, #13) beats
keeping a strong-sounding sentence.

**Path A — make the certification true.**
- D1: replace `_expected_trading_days()` with a **correct CME futures calendar** (i.e. do NOT
  subtract Columbus Day / Veterans Day; the CME equity/commodity holiday set is New Year, MLK,
  Presidents, Good Friday, Memorial, Juneteenth from 2022, Independence, Labor, Thanksgiving,
  Christmas). Note the consequence and handle it explicitly: a *correct, larger* expected count
  makes the rule **stricter**, so months previously certified may now mask → the estimation
  sample can change → **every downstream number must be re-run, not hand-edited**. Genuine
  unscheduled closures (2012-10 Hurricane Sandy, 2018-12 national day of mourning) must be
  handled by an **enumerated, sourced whitelist**, never by loosening a threshold back until the
  old sample returns. Any change in N/3275 must be reported, not hidden.
- D2: require `first_day` / `last_day` to equal the **expected first / last trading day** of the
  month (whitelist as above), instead of `le(3)`.

**Path B — withdraw the claim.**
- Drop `panel_span_is_complete_months_only` to `false` (or delete it), rewrite `rv_rule_detects` /
  `rv_residual_blind_spot` / `rv_endpoint_test` and the README so they state **only** what the
  count-only rule can actually establish, and say plainly that months are screened, not certified
  complete. Codex's line: *"若仍要認證完整月份，count-only frozen cache 需要獨立 endpoint 證據"* —
  if you keep certification wording without endpoint evidence, round 5 fails again.

**Choose per defect and record the choice + reason in the artifact.** Do not regenerate the
frozen cache from raw data unless you can finish it well inside budget — provenance stability of
`rv_monthly.csv` is worth more than upgrading the cache, and Path B is a legitimate answer.

## 5. Mandatory regression gates (both paths)

Add to `experiments/K1694/test_K1694.py` two tests that encode Codex's counterexamples verbatim:

1. `test_common_two_day_truncation_2020_10` — synthesise the 2020-10 case above.
2. `test_endpoint_truncation_2020_06` — inject date columns and drop the last trading day.

Under **Path A** they must assert the months are now **flagged incomplete**. Under **Path B** they
must assert the documented blind spot matches the (weakened) claim string in the results JSON —
i.e. the test pins the disclosure to the behaviour. Either way, a future edit that breaks the
correspondence must fail the suite. Confirm each test **fails on the pre-fix code** and passes
after (report both outcomes in the artifact); a test that never could have failed proves nothing.

## 6. Re-run and consistency

- Re-run `experiments/K1694/K1694.py` end to end. Never hand-edit `K1694_results.json`.
- Keep script sha / `results.code_trace` / `reproduce_spec.json` entrypoint mutually consistent and
  **produced at run time**, not written after the fact (K1715 round-3 lesson).
- Run `uv run python scripts/check_experiment_artifacts.py --experiment K1694 --strict`
  (use the flag spelling the script actually exposes) and record the result.
- Re-run the full `test_K1694.py` suite; all tests must pass.
- README, results JSON and figure captions must agree with each other and with the code. If the
  sample size changed, update every occurrence of 3275 — do not leave stale numbers anywhere.
- Do **not** write `storage/memory/knowledge.json` (K1259 — the main thread owns that write).
- Do **not** leave the round-5 prompt or any raw transcript uncommitted in the worktree.
- Commit your work in the worktree. Do not merge; stage 2 owns the merge decision.

## 7. Artifact contract — `experiments/K1694/r4_repair_report.json`

Write exactly this file (single artifact, machine-readable):

```json
{
  "stage": "rv-completeness-repair",
  "parent_job_id": "agent-brief_k1694_repair_e98b43fc-ea643c",
  "d1": {"path": "A|B", "reason": "...", "code_change": "...",
         "counterexample_2020_10": {"pre_fix_rv_complete_rows": 22, "post_fix_rv_complete_rows": 0}},
  "d2": {"path": "A|B", "reason": "...", "code_change": "...",
         "counterexample_2020_06": {"pre_fix_rv_complete_rows": 22, "post_fix_rv_complete_rows": 0}},
  "readme_nits_fixed": ["fcm_avail_inside_outcome_month_rows", "round2_history_tense"],
  "tests": {"added": ["test_common_two_day_truncation_2020_10", "test_endpoint_truncation_2020_06"],
            "fail_on_pre_fix_code": true, "suite_passed": true, "n_tests": 0},
  "rerun": {"script_sha256": "...", "results_sha256": "...",
            "n_rows_before": 3275, "n_rows_after": 0,
            "artifact_check_strict": "pass|fail"},
  "claims_now_supported": ["exact final wording of each rewritten claim string"],
  "residual_limitations": ["what is still NOT proven — state it plainly"],
  "conclusion_changed": false,
  "self_assessment": "..."
}
```

`conclusion_changed` must be `true` if the headline NULL / NOT SUPPORTED finding moved at all.
**Report a null or weakened result honestly (AGENTS.md #9).** Do not tune thresholds to preserve
the previous sample size — that is fitting the gate to the answer, and Codex round 5 will catch it.

## 8. Success criterion (stage 1 is done when all hold)

1. Both counterexamples are reproduced pre-fix and resolved (Path A) or accurately disclosed (Path B).
2. Both regression tests exist, demonstrably fail pre-fix, and pass post-fix.
3. Full `test_K1694.py` suite passes; strict artifact check passes.
4. `K1694.py` re-run from scratch; results/README/reproduce_spec mutually consistent, run-time provenance.
5. `experiments/K1694/r4_repair_report.json` exists and is complete.
6. Work committed in the worktree; nothing merged; knowledge.json untouched.

**Budget: 3300s wall.** If you are at 2/3 budget and Path A is not converging, switch that defect
to Path B, say so in `d1.reason` / `d2.reason`, and finish. A complete honest Path B beats a
half-finished Path A — the parent job died precisely by not making that call.
