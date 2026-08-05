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

## F3 — SUPERSEDED SAME DAY: Family 3 never used put-call data at all

**What this section said first** (kept, because the correction matters more than the answer):
that F3 was blocked on a provisioning decision, because `data_sources.md:30` records the source
as *"CBOE (via yfinance/manual)"* and **manual** means no replayable acquisition script exists.
A request went to platform engineering asking whether CBOE's historical equity put-call volume is
still retrievable programmatically.

Their reply reported **zero hits** for any put-call collector anywhere in `src/` or `scripts/`.
That prompted reading the producing experiment instead of the data manifest, and the manifest is
wrong.

### What Family 3 actually computes

`paper/vix-sufficiency/experiments/k732_pcr_behavioral_sentiment.py` — the Family 3 producer per
`experiments.md:18` — downloads exactly five tickers (`:53-58`):

```
SPY, GLD, ^VIX, ^SKEW, ^VIX3M
```

No put-call series, from CBOE or anywhere else. The signal is a composite built at `:131`:

```python
df['BSI'] = (df['vix_level_pctile'] + df['ts_ratio_pctile']
             + df['vix_mom_pctile'] + df['skew_pctile']) / 4
```

Four percentile ranks: VIX level, VIX term-structure ratio, VIX momentum, and the CBOE SKEW
index. The script's own header says why (`:11`, `:13`): *"K191: PCR data unavailable, used VIX
proxies"* and *"K523: VIX percentile as PCR proxy"*. The put-call data was never obtained, a
proxy was substituted, and the substitution is recorded in the script but nowhere downstream.

### Three consequences, in increasing order of seriousness

1. **`data_sources.md:30` documents a source that was never used.** The row claims CBOE put-call
   volume, 1995–2026, daily, for Family 3. Nothing reads it. The line should be deleted or
   rewritten to name the actual inputs (`^VIX`, `^SKEW`, `^VIX3M`, 2010–2026).

2. **F3 is not blocked and never was.** Every input is free from Yahoo and `^VIX` is already
   pinned. The nested Clark-West for Family 3 can run today, on the same harness as F10, with no
   external dependency and no provisioning decision. Two of the three "blocked on external data"
   families were never blocked.

3. **The manuscript describes Family 3 as something it is not — and this one is not a
   bookkeeping fix.** `main_v5.tex:519` calls it *"Family 3 (behavioural put-call ratio)"* and
   the Table 4 row is labelled behavioural sentiment. What the family actually tests is whether a
   percentile composite of *VIX level, VIX term structure, VIX momentum and SKEW* improves on a
   VIX-only benchmark. Three of the four components are transforms of the benchmark itself, and
   the fourth (SKEW) is also an SPX-option-implied index — squarely inside the option-market
   information set whose sufficiency the paper is testing.

   That has two effects the paper should state rather than absorb silently:
   - **The Family 3 null is close to tautological.** DM |t| = 0.52 is what one should expect from
     asking whether a non-linear recombination of VIX beats linear VIX. It is not independent
     evidence for VIX sufficiency, and the nested Clark-West will not change that.
   - **Family 3 overlaps Family 2.** The `ts_ratio` component *is* the VIX term structure, which
     is Family 2. The thirteen families are presented as pre-specified and distinct; two of them
     share a component and one is built from the benchmark.

   The headline null survives — nothing here suggests a signal was missed. What does not survive
   is the count: the paper's rhetorical force comes from "thirteen families, none of them work,"
   and one of the thirteen is the benchmark wearing a different label.

### Recommended handling

- Run the F3 nested Clark-West (free, immediate) **and** report it under an accurate label.
- Correct the family description in §2.3, Table 4, and `main_v5.tex:519`: it is an option-implied
  sentiment composite (VIX level / term structure / momentum + SKEW), not a put-call ratio.
- Add one sentence acknowledging that Family 3's inputs are option-implied and therefore inside
  the information set under test — which makes its null *predicted by the paper's own thesis*
  rather than an independent test of it. Stated that way it reads as coherence, not as a weakness.
- Fix `data_sources.md:30`.
- Tell platform engineering to stop looking for the CBOE collector (done, same day).

A referee who opens the replication package and greps for put-call finds nothing. Better to
correct this ourselves than to have it found.

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
