# vix-sufficiency F3 / F9 / F10 — daily nested Clark-West: data-provisioning adjudication

**Canonical task**: `paper_body_vix_sufficiency_daily_F3_F9_F10_external_data` (P3)
**Assigned**: operations manager, work item `item_20260805T085056200252Z_canonical-vix-sufficiency-f3-f9`
**Adjudicated by**: publications department, 2026-08-05
**Parent**: `paper_body_vix_sufficiency_daily_family_clark_west` (F1/F2/F4/F8/F11 DONE, all |CW t| < 3.0)

---

## VERDICT: the blocker is misfiled — one family is not blocked, one should be withdrawn rather than deferred, one needs a provisioning decision

The task reads *"blocked on CBOE put-call / Google Trends / intraday VIX open snapshots,"* which
scans as "the data cannot be obtained." That is not what the evidence says. All three series were
already obtained and used: `paper/vix-sufficiency/data_sources.md` records a source for each, and
Table 4 of `main_v5.tex` reports main-table Diebold-Mariano statistics for all three
(|t| = 0.52 / 0.67 / 1.12, `main_v5.tex:519`). What is missing is a **pinned replication
snapshot**, not access.

Splitting the three accordingly changes what should happen to each:

| Family | Signal | Current status | Verdict |
|---|---|---|---|
| **F10** overnight VIX | `\|VIX_open,t − VIX_close,t−1\|` | Source already in use (`^VIX`, Yahoo) | **NOT BLOCKED — execute now** |
| **F3** behavioural P/C | CBOE equity put-call volume | Source recorded as "via yfinance/**manual**" | **Blocked on a provisioning decision**, not on data existence |
| **F9** Google Trends fear | 5 fear terms, 52-week rolling z | pytrends | **Withdraw, do not defer** — no PIT-safe test is constructible |

---

## F10 — not blocked; the "intraday VIX opening print" framing is what blocked it

`main_v5.tex:240` defines the family as `|VIX_open,t − VIX_close,t−1|` and states explicitly that
its forecast origin is the day-`t` opening auction, making it the sole disclosed exception to the
close-of-`t−1` convention — a legitimate timing choice, since both inputs are observed by the
day-`t` open while the target accumulates strictly after it.

That definition needs **the Open column of the daily `^VIX` OHLC series**. It does not need
intraday tick data. `data_sources.md:12` already lists `^VIX` from Yahoo (yfinance),
1993-01-01 – 2026-04-17, daily. The same download that supplied the VIX level supplies the open.

The one real trap is in that same line: the existing VIX pin is annotated *"lagged 1 day to
enforce no-lookahead."* F10 must **not** inherit that lag — the whole point of the family is the
day-`t` open, and applying the daily-family shift would destroy the signal while looking like
diligence. The snapshot must carry the raw unlagged OHLC and the harness must apply F10's own
convention.

**Action**: pin `^VIX` daily OHLC (unlagged, `auto_adjust=False`, hash-recorded) into the
replication snapshot, then run the k1116e/k1116g harness on F10 with the fixed 2019–2026 split,
NW lag 21, HLN h=22. No new data source, no cost, no external dependency. This is a
straightforward experiment task and should be dispatched as one.

## F3 — blocked on a provisioning decision, and the decision is small

`data_sources.md:30` records the source as *"CBOE (via yfinance/manual)"*. The word **manual** is
the actual blocker: it means no replayable acquisition script exists, so the series cannot be
re-derived from a clean clone — which is a replication-package requirement for Journal of
Forecasting, not merely an internal preference.

Two acceptable resolutions, both cheap:

1. **Replayable fetch** — if CBOE's historical equity put-call volume file is still retrievable
   programmatically, write the fetch into the harness and pin the resulting CSV with its hash.
2. **One-time pinned snapshot with documented provenance** — if acquisition is genuinely manual
   (registration-gated download), pin the CSV and document in `data_sources.md` exactly which
   file, from which CBOE page, retrieved on which date, under what access terms. A manual source
   is acceptable in a replication package **only** when documented to that level.

A **PIT detail that must be settled before the run, not after**: equity put-call volume is a
settled end-of-day statistic, published after the close. Under the paper's close-of-`t−1`
convention for Families 1–9 and 11 this is fine — but only if the harness enforces the shift that
convention implies. This should be asserted in code, in the same style as the existing lag
enforcement, not assumed.

**Action**: route the acquisition-path question to platform engineering; the answer determines
which of the two resolutions applies. The CW run itself is then the same harness call as F10.

## F9 — withdraw the CW cell; the obstacle is methodological, not logistical

This is the substantive finding of this adjudication, and it does not become unblocked by any
amount of data work.

Google Trends does not return a point-in-time series. It returns values **rescaled to 0–100 over
the queried window**, resampled from a stochastic sample of searches, with no vintage API — the
same query issued on two dates returns different numbers, and there is no way to recover what the
index read at a 2019 forecast origin. `main_v5.tex:197` already concedes fragility ("we use 2010+
for stability") without naming this cause.

That places F9 squarely against a standing repository rule (`.claude/rules/experiments.md`,
revision-prone macro series): sources whose history is revised or reconstructed must be evaluated
on real-time vintages, and where that is impossible the result must be relabelled **final-vintage
pseudo-OOS** with the real-time predictive claim withdrawn — not presented as PIT.

Pinning a snapshot today does not fix this. It freezes *one* rendering of a retrospectively
rescaled history and makes it reproducible, which is a different property from being available at
the forecast origin. A nested Clark-West increment computed on it would be exact arithmetic on an
inadmissible input, and — as with K1730's permutation route — the danger is precisely that it
would look rigorous.

**Recommended manuscript change** (`main_v5.tex:519`). The current sentence defers all three
families to "a data-provisioning follow-up." Split F9 out:

> The remaining daily families are treated differently. Families 3 (behavioural put-call ratio)
> and 10 (overnight VIX change) depend on series not yet pinned in the replication snapshot and
> their nested Clark-West increments are deferred to a data-provisioning follow-up. Family 9
> (Google Trends fear) is excluded from the nested Clark-West exercise on methodological rather
> than logistical grounds: Google Trends returns values rescaled to the queried window with no
> vintage archive, so no series available at each forecast origin can be reconstructed. Its
> main-table Diebold-Mariano statistic (|t| = 0.67) is reported as a final-vintage figure and is
> not upgraded to a real-time predictive claim.

This costs the paper nothing — F9's DM statistic is 0.67, immaterial either way — and converts a
lingering "to be completed" into a disclosed methodological boundary. Referees at Journal of
Forecasting are more likely to reward the disclosure than to miss the omission.

---

## Consequences for the paper's own claims

The manuscript's expectation that these three increments will be "equally immaterial"
(`main_v5.tex:519`) is reasonable but is an expectation, not a result. After F10 and F3 run, one
of two things is true and both are fine:

- they confirm the null → Table 3's CW coverage goes from 5/8 to 7/8 daily families with the
  remaining one excluded on stated grounds, and the paper's central claim gets stronger;
- one of them clears |t| > 3.0 → that is a finding, and the paper's headline null needs
  qualification. F10 is the plausible candidate (main-table |t| = 1.12, the largest of the three,
  and its opening-auction origin is genuinely outside the close-of-`t−1` information set the
  other families share).

The second outcome must not be treated as a problem to be managed. It is the reason the test is
worth running.

## Scope note

This department could not execute either run: `experiments/` and `paper/` are outside its
writable subtree under the active permission mode. The two runnable items (F10 immediately, F3
after the provisioning answer) are handed to the operations manager for dispatch, and the
acquisition-path question to platform engineering.

## Stale pipeline blocker (second instance today)

`storage/paper_pipeline_status.json` records vix-sufficiency's blocker as *"main_v4.tex updated
but reproduce.py still v3, gate not re-run."* The manuscript is on `main_v5.tex`, and the
canonical task refers to v5 throughout. This is the same failure mode found on
prg-periodic-garch this session: the blocker string is prose that stops at the moment it was
written, while the work moves on. Two out of two papers inspected today had a materially wrong
blocker. Reported to the manager as a systemic issue rather than patched per-paper.
