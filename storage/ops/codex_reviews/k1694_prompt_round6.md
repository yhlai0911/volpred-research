# K1694 — ROUND 6 review (re-review after the round-5 FAIL was repaired)

You have judged this experiment five times, FAIL each time. **This round is narrow.**
Round 5's verdict is in `experiments/K1694/review_verdict.json` and named exactly two
blocking defects. Judge those two, spot-check that nothing round 1–4 fixed regressed, and
write a verdict. Do **not** re-derive the estimator; you certified it in rounds 3–5.

Working tree: this repo. Reviewed commit: `2724b3587`. Sandbox is read-only.

## Read, in this order

1. `experiments/K1694/review_verdict.json` — the two defects you are judging.
2. `experiments/K1694/r6_repair_report.json` — what was done and what is admitted unresolved.
3. `experiments/K1694/calendar_sources.md` and `experiments/K1694/calendar_fixtures.json`.
4. `experiments/K1694/K1694.py` — the calendar block (`PRODUCT_SCHEDULE`, `CALENDAR_SPECS`,
   `UNSCHEDULED_CLOSURES`, `_validate_unscheduled_closures`, `trading_days`,
   `expected_trading_days`, `expected_month_endpoints`), `monthly_coverage`,
   `coverage_report`, `unverified_status_insensitivity`, `strict_month_gate_sensitivity`.
5. `experiments/K1694/test_K1694.py` — the round-6 tests.
6. `experiments/K1694/gate_history/a5896554__K1694.py` — the preserved round-5 bytes.

## Defect 1 — `product_scoped_calendar_required`

You blocked because `CME_UNSCHEDULED_CLOSURES` removed 2012-10-29, 2012-10-30 and
2018-12-05 for every commodity, contradicted by CME's and ICE's own notices, and because
removing it changes the sample.

What was done: the whitelist is **deleted**. `PRODUCT_SCHEDULE` maps all 22 tickers to
`CME_GLOBEX_COMMODITY` (18) or `ICEUS_SOFTS` (4); `rv_expected_trading_days`, the month
anchor and the cross-sectional peer maximum are all computed **within a schedule**; both
`UNSCHEDULED_CLOSURES` entries are `{}` because the primary sources say all three dates
were trading days for every product here. `_validate_unscheduled_closures()` raises at
import on any closure lacking `source_id` + `quote`.

**Check, hard:**

- Is the source table real? Every ticker must have an exchange and a resolvable official
  URL in `calendar_sources.md`. Are the quotes actually in those documents, and do they
  say what the table claims? Note `cmegroup.com` returns 403 to non-browser agents; the
  Wayback `id_` mirrors are given in `calendar_fixtures.json`.
- The Sandy status of **CBOT grains and CME livestock** rests on CFTC 12-363 *not*
  mentioning them (labelled `explicit-by-exclusion`). Is that inference sound, or is it
  the same "absence of evidence" move in a new costume? Does anything in the estimation
  sample turn on it?
- Is the per-schedule scoping real or cosmetic? Both venues' holiday sets are claimed to be
  identical **as a checked fact**. Verify that: if it is asserted rather than checked, say so.
- Is the month anchor `expected - max(ndays within schedule)` correct now that the peer
  group is smaller? Note the direction: a smaller peer group makes `rv_cross_shortfall`
  **looser** and `rv_month_shortfall` **stricter**. Did any row flip for the wrong reason?
- Was any threshold moved? (`MIN_RV_DAYS`, `MAX_RV_SHORTFALL_VS_CALENDAR`,
  `MAX_RV_CROSS_SHORTFALL`, `MAX_RV_MONTH_SHORTFALL` are claimed unchanged since round 4.)

## Defect 2 — `calendar_truth_test_is_tautological`

You blocked because `test_endpoint_gate_accepts_an_untruncated_dated_cache` injected
`expected_month_endpoints()` and asked the same implementation to accept it.

What was done: that test is **deleted**. `calendar_fixtures.json` is the oracle — 16 dated
open/closed fixtures and 10 month fixtures hand-transcribed from the notices, each with a
URL and a quote — and the new tests read expected values only from it.

**Check, hard:**

- Does **any** calendar test still take an expected value from `K1694.py`? If one does, the
  defect is not fixed.
- `test_endpoint_gate_accepts_a_primary_source_untruncated_cache` injects the notices'
  endpoints (must pass) and then truncates one trading day (must fail). Is that genuinely
  two-sided, or can it be satisfied by a degenerate gate?
- The repair claims the oracle produces **9 contradictions** against
  `gate_history/a5896554__K1694.py` and 0 against the current code. Reproduce it. The old
  module computes `DATA` from its own `__file__`, so **set `old.DATA` to
  `experiments/K1694/data`** or it will try to re-download and you will be comparing
  against different bytes.

## Quantified change (round 5's explicit requirement)

`r6_repair_report.json → quantified_change`. Verify against the artifacts, not the prose:
3276 → 3275 rows (CORN 2018-12), lagged 2749 → 2748, coverage `rv_complete` 5252 → 5229,
2012-10 22/22 → 0/22, 2018-12 22/22 → 21/22, spec1 3.097e-04 / t 1.53 → 3.034e-04 / t 1.48,
VERDICT still NULL. The 5252 figure is claimed to be recomputed from the preserved bytes
against the same frozen cache — check that, it is the one number not taken from an artifact.

## The new disclosure — judge whether it is honest or self-serving

Removing the whitelist means 2018-12 now **passes** the completeness screen while CME's own
notice says the market was open on a day no commodity has a bar for. The repair publishes
`rule.rv_months_short_of_the_exchange_calendar` (13 schedule-months, with a
`caught_by_the_rule` flag), adds a limitation saying the screen is not a certificate, and
adds `robustness_strict_month_gate` (tolerance forced to 0: n 3210, t_DK 1.69).

- Is `robustness_strict_month_gate` correctly implemented and correctly labelled as **not**
  the reported specification? Does it restore the global it mutates?
- Same question for `unverified_status_insensitivity`, which mutates `UNSCHEDULED_CLOSURES`
  and claims to prove the restore by re-reading the reported vector.
- Is anything overclaimed? The report says the conclusion is unchanged — is it, on the
  artifacts?

## Admitted unresolved — judge whether the treatment is right

1. **No source found for ICE Futures U.S. on 2018-12-05.** No closure asserted; carried as
   open; immateriality measured at run time (0 rows flip). Is "carry it as open and measure"
   the right call, or should the month be dropped?
2. The "New Year on a Saturday is not rolled back to 31 Dec" rule is backed by the panel's
   own bar counts, not a notice, and is labelled `EMPIRICAL-FROM-PANEL`.
3. The frozen `rv_monthly.csv` is still count-only, so the endpoint gate is not exercised by
   the reported run.

## Regression spot-check (do not re-derive)

Round 4's two counterexamples still gated (`test_common_two_day_truncation_2020_10`,
`test_endpoint_truncation_2020_06`); NULL scope and NOT-SUPPORTED wording intact;
`reproduce_spec` / `code_trace` identity; `signal.shift(1)`-equivalent lag still visible;
seed fixed. `uv run --active python -m pytest experiments/K1694/test_K1694.py -q` → 50 passed.

## Output

Write your verdict to **stdout only** (the sandbox is read-only). Be economical — you have a
hard time bound. Start with a single line `VERDICT: PASS` / `CONDITIONAL_PASS` / `FAIL`,
then for each of the two defects `RESOLVED` or `NOT RESOLVED` with the evidence, then any
new blocking defects with a concrete counterexample, then anything you could not verify in
the time available. If it is a FAIL, say which specific thing is wrong — a repair cannot be
aimed at "insufficiently convincing".
