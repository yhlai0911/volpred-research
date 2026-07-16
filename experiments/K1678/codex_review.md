# K1678 Codex Review

## Verdict

`PASS` — the experimental verdict `NULL_NO_ROBUST_SALIENCY_AMPLIFICATION` is supported by the stored artifacts. No blocking methodology or implementation issue remains.

Reviewer source: primary Codex session plus independent fresh-context Codex subagents, pre-run and post-run.

## Pre-run gate

The script was reviewed before the full experiment for:

- SEC Attachment-A full-population parsing and option-identifier exclusion;
- explicit event/attention `shift(1)` and exact t+1…t+H target windows;
- target-free same-ticker matching and event-buffer rules;
- within-ticker H-row event de-clustering;
- horizon-specific HAC lags;
- seed/block bootstrap implementation;
- Bonferroni and BH over exactly m=8;
- conservative verdict logic and atomic JSON replacement.

Result: `PASS`. The source parser smoke test independently recovered 439 blocks, 412 equity tickers, 1,083 date occurrences, and 1,079 unique ticker-dates with the exact expected year counts.

## Post-run artifact verification

- Primary cells: 8/8 independently refitted from `K1678_matched_events.csv.gz`.
- Maximum coefficient discrepancy: `1.07e-13`.
- Maximum HAC t-statistic discrepancy: `2.16e-15`.
- Maximum HAC p-value discrepancy: `1.67e-15`.
- Matched outcome differences recomputed from `data/analysis_panel.csv.gz`; maximum discrepancy `7.28e-12`.
- Matched saliency differences recomputed; maximum discrepancy `4.44e-16`.
- Every formation date maps to the preceding ticker trading row and an exact SEC label.
- Every control set has three rows; nearest control is 11 trading rows from any labelled event, exceeding `max(10,H)`.
- H=5 retained events are at least five ticker trading rows apart.
- H=1/H=5 coverage agrees across JSON and CSV: 525/345 matched rows, 302/242 event-date clusters, 205/204 tickers.
- Bonferroni p-values are all 1.0; minimum BH q is 0.7716; maximum absolute primary HAC t is 1.258.
- All eight 2,000-rep moving-block bootstrap 95% confidence intervals cross zero.
- Base seed 42 and derived per-cell seeds 142–145 / 542–545 are recorded; block length is 10 for both horizons.
- Artifact SHA-256 values match the result JSON.
- Repeated complete cached runs reproduce byte-identical CSV, deterministic gzip, PNG, and canonical JSON after excluding `generated_at`.
- Figure was visually inspected at original resolution; no clipping remains.

## Conclusion ceiling

The evidence supports only a narrow null: broad Wikimedia manipulation/retail-topic attention does not robustly explain cross-event variation in subsequent risk within the surviving portion of one retrospective SEC complaint.

It does **not** show that alleged manipulation dates lack crash risk. Secondary direct event-minus-control left-tail and gap estimates are positive. It also does not reject ticker-specific search/social/news attention, the JBF/JEF China quasi-experimental mechanism, or any causal manipulation channel.

## Nonblocking limitations retained in the artifacts

- Complaint allegations are neither convictions nor point-in-time labels.
- The complaint concerns one alleged trader and an odd-lot/order-book mechanism, not a social-media manipulation population.
- Current Yahoo availability loses 160 requested symbols and creates delisting/survivorship attrition.
- Wikimedia topic pageviews are market-wide, not firm-specific attention.
- A no-label matched day is not verified manipulation-free.

Final review verdict: `PASS`.

---

# K1678 Closeout Review Round 2 (2026-07-17)

Scope: the closeout addition only — `hac_bandwidth_check.py`, `K1678_hac_bandwidth_check.json`, and
the new README §"HAC bandwidth". The original `K1678.py` was not re-reviewed; the 2026-07-10 `PASS`
above still stands and its artifacts are unchanged.

## Why this round happened

`K1678.py:872` sets `maxlags = horizon - 1` for every date-clustered HAC fit. The repo's canonical
bandwidth rule (`.claude/rules/experiments.md`, K1655) requires `max(h-1, ceil(h^(1/3)·n^(1/3)))`
and names `h-1` at `h=1` as a degenerate case. That rule was mechanised on 2026-07-11 — one day
after K1678 ran — and its ratchet only classifies hand-written DM loops, so a statsmodels
`cov_type="HAC"` call with `maxlags = horizon - 1` was never in scope of any gate. The closeout
measured the impact instead of assuming a null was safe.

## Reviewers

- **Primary path**: Codex (`gpt-5.6-sol`, CLI 0.144.1), three rounds, 2026-07-17.
- **Fallback**: `feature-dev:code-reviewer` fresh-context subagent (opus), one round, used while the
  Codex invocation was being debugged. Not a substitute for the primary path; recorded for audit.

The first two Codex attempts timed out. Root cause was the caller, not the CLI: a multi-line prompt
passed as an argv string leaves `codex exec` blocking on stdin. The documented form
(`printf '%s' "$PROMPT" | scripts/codex_exec_bounded.sh --timeout N -s read-only -`) works.

## Round-by-round defects, all found and fixed

1. **Round 1 (subagent, PASS with a factual defect)**: the prose claimed `maxlags=0` leaves "plain
   OLS standard errors". False — truncating the Bartlett kernel at zero lags leaves White
   heteroskedasticity-robust SEs. The error overstated the debt. Fixed in README and docstring.
2. **Round 2 (Codex, FAIL)**: the README asserted the 16 unswept sensitivity fits could not approach
   the gate "under any bandwidth", resting on their as-run `|t| = 1.536`. That is the reasoning
   error the check exists to catch. Fixed by sweeping them: max `|t|` rises to `1.672` — still far
   from the gate, but now measured. The 8 intercept-only direct diagnostics were swept for the same
   reason.
3. **Round 3 (Codex, FAIL)**: "`3.3`–`4.0` across `maxlags` 0 to 20" overstated on two counts — the
   tested range tops at `4.129`, and the grid is discrete, not a continuous 0–20 sweep. Fixed: the
   range now reads `3.305`–`4.129`, the grid is stated up front, and every claim is scoped to
   *tested* bandwidths (JSON field names renamed to match).

## Round 3 verification (Codex, PASS)

- Every README number re-checked against the JSON: `3.305`, `4.129`, `1.258`, `1.672`, `1.536`,
  `2.16e-15`, acf1 range `-0.079`–`+0.292`, and `16.399%` / `10.391%` against
  `K1678_results.json` (`16.398721...` / `10.390582...`).
- "4/8 direct cells above the gate" verified at *every* tested lag, not merely at the maximum; the
  other four never exceed 3.
- No wording implies interpolation between grid points; no inferential claim rests on an as-run
  statistic.

## Outcome

The bandwidth deviation is real methodology debt and is now documented in the README rather than
silently carried. It does not move the verdict: `NULL_NO_ROBUST_SALIENCY_AMPLIFICATION` holds, with
0/8 primary cells reaching Harvey `t ≥ 3` at any tested bandwidth (max `|t| = 1.258`).

Non-blocking, deliberately not acted on: `resid_acf1` is stored inside each `by_maxlags` entry
although residuals are invariant to `cov_type`; a skimmer could misread it as bandwidth-dependent.

Final review verdict: `PASS`.
