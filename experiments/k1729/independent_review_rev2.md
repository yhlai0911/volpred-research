# K1729 rev2 — Independent Final Audit

**Reviewer provenance (recorded for honesty)**: produced by a fresh-context
adversarial `code-reviewer` subagent (Claude Opus 4.8) on 2026-07-21, invoked as
the sanctioned fallback in `.claude/rules/experiments.md` because the primary
path (Codex CLI) returned a hard usage-limit error (`You've hit your usage
limit ... try again at Jul 25th, 2026`). Per that rule, a fallback PASS is not
equivalent to a primary-path Codex PASS and requires Codex re-verification once
credits reset — see `review_verdict.json`.

The reviewer had read-only tools (Read/Grep/Glob, no Bash/Write), so it could
not execute code; it verified by reading frozen sources and hand-computing the
settlement calendar against raw CSV rows. Its report is reproduced verbatim
below. It was written to this path by the main thread because the reviewer had
no write tool.

**Files reviewed** (frozen at commit `74e607249`):
`experiments/k1729/{README.md,k1729.py,k1729_results.json}`,
`storage/ops/nested_dm_misuse_baseline.json`,
`docs/governance/2026-07/nested_dm_fp_narrowing_audit.md`

---

## Methodology

Verification was done by: (a) direct code reading of `k1729.py`,
`scripts/collect_taifex_tick.py`, and canonical
`src/volpred/stats/model_evaluation.py` / `src/volpred/evaluation/metrics.py`;
(b) exhaustive line-by-line cross-checking of every number in `README.md`
against `k1729_results.json`; (c) an **independent, hand-computed reproduction
of the Rule E settlement-date logic** (third-Wednesday-of-month arithmetic) for
all 5 claimed ambiguous OOS dates plus 2 control (non-ambiguous) settlement
dates, checked against raw CSV rows via Grep.

## 1. Is Rule E fitted to the data?

**No — independently verified, not fitted.**

Hand-computed TAIFEX settlement dates (3rd Wednesday of the contract month; no
holiday shift needed in any of these cases) for the five dates the repair claims
are the *entire* ambiguity set:

| Claimed ambiguous date | Independent 3rd-Wednesday calc | Match |
|---|---|---|
| 2016-03-16 | Mar 1 2016 = Tue → 1st Wed = Mar 2 → 3rd Wed = **Mar 16** | ✅ |
| 2016-05-18 | May 1 2016 = Sun → 1st Wed = May 4 → 3rd Wed = **May 18** | ✅ |
| 2016-08-17 | Aug 1 2016 = Mon → 1st Wed = Aug 3 → 3rd Wed = **Aug 17** | ✅ |
| 2017-01-18 | Jan 1 2017 = Sun → 1st Wed = Jan 4 → 3rd Wed = **Jan 18** | ✅ |
| 2017-02-15 | Feb 1 2017 = Wed → 1st Wed = Feb 1 → 3rd Wed = **Feb 15** | ✅ |

Raw rows pulled around each date directly from `data/intraday/taifex_5min_rv.csv`:

- **2016-03-16** (ambiguous, in-list): `active_contract` jumps `201603→201604`
  and `is_roll=True` **on the settlement day itself**.
- **2016-05-18**, **2016-08-17**, **2017-01-18**: same pattern — the roll happens
  on the settlement day itself, one day earlier than Rule E predicts.
- **Control 1 — 2016-04-20** (3rd Wed of April 2016, computed independently, NOT
  in the ambiguous list): the roll does **not** happen on 04-20; `active_contract`
  stays `201604` through 04-20 and only flips to `201605` on **2016-04-21** —
  exactly the day *after* settlement, exactly what Rule E predicts, and correctly
  absent from the ambiguity set.
- **Control 2 — 2020-01-15** (3rd Wed of January 2020, independently computed):
  same pattern — contract stays `202001` through 01-15, rolls to `202002` on
  **2020-01-16**, correctly not ambiguous.

This is strong independent confirmation that (a) Rule E's algorithm is correctly
implemented, (b) the 5 claimed ambiguous days are exactly what the README says —
real settlement days where volume genuinely migrated one day early, an
economically explicable microstructure phenomenon localized mostly to 2016–2017,
not a fabricated or hand-picked list, and (c) non-ambiguous settlement days
genuinely follow the calendar rule with no cherry-picking. The 99.80%
(2,545/2,550) and the arithmetic (2550−5=2545) are internally consistent and
match the OOS window definition (`WINDOW=1000` → 2,550 OOS rows, verified in code).

On the "alternative convention selects the same contract on every row" sentence:
the phrasing is genuinely ambiguous on a first read (same as *what*?). The
English docstring clarifies intent — "so the headline does not depend on which
one is used" — i.e. the claim is that the two *candidate ex-ante conventions*
agree with **each other** on every row. Minor wording-clarity issue, not
substantive; recommended for tightening, not blocking.

## 2. Ex-ante ledger conditioning — is disclosure sufficient?

**Sufficient, not blocking.** The residual limitation (conditioning on
calendar-compliance, which is not knowable at 08:45) is explicitly stated in
three places with identical content: README §4.1 last paragraph, README §7
caveats, and `k1729_results.json.target_contract_selection_audit.residual_limitation`.
The argument that the conditioning is model-agnostic (touches neither forecast
nor loss; both models scored on the identical day-set) is correct by
construction — `exante_ok` is computed purely from `date` / `active_contract` /
settlement calendar and never touches `f_rv5` / `f_daily` / loss.

## 3. Does the README present the primary table as lookahead-free anywhere?

**No.** §3 is placed immediately before §4 and explicitly states that the primary
full-ledger numbers *do* contain ex-post selection, that the clean ledger is
§4.1's ex-ante one, and that both are reported. §7's operational headline
explicitly cites the **ex-ante-ledger** numbers (`+14.70% / t=−3.671`；
`+3.39% / t=−3.370`), confirmed by matching against
`results.<target>.sensitivity.exante_contract_ledger` in the JSON — not the
primary-ledger numbers (`t=−3.681` / `t=−3.367`).

Non-blocking observation: the top-level machine-readable `verdict` field is
derived from the **full/primary** ledger, not the ex-ante one. Both ledgers agree
on direction and both clear Harvey |t|>3, so the verdict value is not wrong, but
deriving `overall` from the ex-ante ledger would maximize defensibility of the
machine-readable field.

## 4. Is the nested-DM adjudication correct?

**Correct.** HAR-RV5's regressors and HAR-DAILY's regressors are built from
disjoint underlying series. No coefficient restriction (zero or equality) on one
model's regressor set recovers the other's — the textbook definition of
non-nested. The empirical nondegeneracy diagnostics in the frozen JSON (forecast
correlation ~0.78–0.79, mean relative forecast gap 17.7–20.6%, loss-differential
std > 0, zero exact-zero-differential rate) corroborate that forecasts do not
coincide under any null — which is the actual failure mode raw DM has under
nesting, and it clearly does not apply here.

Cross-checked the cited precedents against
`docs/governance/2026-07/nested_dm_fp_narrowing_audit.md` §2.1: `K1049` and
`k1100b` are both genuinely listed there as adjudicated (a) true false positives
/ non-nested, with reasoning structurally analogous to K1729's disjoint-regressor
argument. Real precedent, not fabricated; routing through `reviewed_nonnested` is
the correct pre-existing exit path, not a new backdoor. Clark-West is not
required; raw DM via canonical `dm_test` is appropriate.

## 5. Does §7's scope still exceed the evidence?

**No.** §7 explicitly retracts rev1's "worth maintaining" claim and narrows to
"the predictive gain is non-zero", further qualified as a statistical (QLIKE)
claim rather than an economic one ("統計顯著 ≠ 值得付錢"). Supported by:
Harvey-significant DM on two oppositely-biased proxies, robustness across three
independent sensitivity ledgers (all six cells `HAR_RV5_WINS`, |t|>3, verified
number-for-number against the JSON), agreement with independent literature
(Andersen & Bollerslev 1998), and a compression ratio consistent with K853
(14.70/3.37 ≈ 4.36×). All remaining caveats are disclosed. No claim in §7 was
found unsupported by the frozen results.

## 6. Lookahead / baseline asymmetry / DM-HAC misuse / number mismatches

- **Feature lag**: `har_features()` correctly shifts by 1 before rolling means;
  training windows for origin `t` end at `t-1`; `X[t]` contains only ≤ t-1 info.
- **Target-side selection**: confirmed as the described (now scoped/quantified)
  issue; independently reproduced in raw data, not a code artifact.
- **QLIKE direction**: `actual/predicted - log(actual/predicted) - 1`, matches
  canonical `volpred.evaluation.metrics.qlike` and the repo hard rule.
- **DM HAC bandwidth**: canonical `dm_test()` floors at 14 for `h=1, n≈2500`;
  never degenerates to 0 — no K1655-class bug. The script's own `hac_lag`
  recomputation is diagnostic-only and does not override the canonical call.
- **Non-positive actuals**: dropped from the ledger, never clipped (K1704).
- **Baseline symmetry**: both models share `har_features()`, identical rolling
  window, refit cadence, insanity filter and common ledger. The filter
  trigger-rate asymmetry (7–12 vs 0) is model behaviour, not code asymmetry, and
  the no-filter sensitivity run (now in the frozen artifact, unlike rev1) shows
  disabling it *strengthens* rather than manufactures HAR-RV5's win.
- **Number cross-check**: every number in README §4, §4.1, §非巢套, the
  sub-sample table and the exclusion table was checked against
  `k1729_results.json` to the displayed precision. All match exactly. No
  fabricated or drifted numbers found.

## Non-blocking observations

1. Top-level machine `verdict` field derived from the full/primary ledger rather
   than the ex-ante one (numbers agree either way — cosmetic).
2. The "alternative convention selects the same contract on every row" sentence
   should state explicitly that it means agreement *with the other ex-ante
   convention*, not with the realized ex-post selection.

## Conclusion

Rev1's blocking defect (undisclosed target-side ex-post contract-selection
lookahead) has been genuinely repaired, not papered over: the mechanism is
disclosed with the correct technical description (verified against
`scripts/collect_taifex_tick.py`), quantified with an independently-reproducible
calendar rule (verified by hand against raw data, not merely trusted), shown not
to drive the result across three sensitivity ledgers, and the operational
conclusion has been narrowed to match the evidence. The nested-DM gate hit is a
genuine, correctly-adjudicated false positive with real precedent. No new
blocking defect was found on adversarial review.

FINAL_VERDICT: PASS

---

## Main-thread disposition of the two non-blocking observations (2026-07-21)

Both reviewers (this one and the independent `agy` / Gemini pass in
`agy_review_rev2.md`) raised the *same* two items, so both were fixed rather than
deferred, and the artifacts were re-frozen and re-confirmed afterwards:

1. **Machine-readable verdict** now requires the full ledger AND the ex-ante
   ledger to agree; disagreement downgrades to
   `PROXY_DEPENDENT_INCONCLUSIVE` / `EXANTE_LEDGER_DISAGREES`.
2. **Convention-agreement wording** tightened in all three surfaces (README §3,
   `k1729.py` docstring, `results.json`) to state precisely that the two ex-ante
   conventions agree *with each other* on every OOS row, and that the sole
   whole-file difference is row 0 (2012-01-02), a dataset-boundary artifact in
   warmup that is never scored — a fact `agy` established by independent
   reimplementation.
