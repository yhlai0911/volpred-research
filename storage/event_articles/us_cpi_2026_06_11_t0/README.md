# US CPI 2026-06 T+0 — event article evidence pack

**Status**: never published. This is a pre-publication internal correction, not a live errata.
**Errata rerun**: 2026-07-19 (task `assign_a31a311d`), triggered by K1442 `related_event_date_audit`.
**Prior artifacts**: `_archive_20260719/` (untouched, for audit).

---

## What this study is

The reader-facing question is narrow: the June-2026 US CPI printed hot on the headline
and in line on the core — how did the vol complex price it, and did the reaction survive
into the next session?

- **Event date t** = official BLS news-release date, **2026-06-10**, 08:30 ET.
- **Event window** = trading days t-1, t, t+1 → 2026-06-09 / 06-10 / 06-11.
- **Reaction** = t-1 close → t close. The 08:30 release precedes the 09:30 open, so
  measuring the same session is not lookahead.
- **Historical comparison** = the same t-1→t VIX reaction on every official CPI release
  in 2025-05-01 … 2026-06-12.
- Data: yfinance `^VIX`, `^VIX9D`, `SPY` (adjusted closes); BLS CPI Summary USDL-26-0824.
- Release calendar: **FRED/ALFRED release id 10**, via `volpred.data.event_dates.cpi_release_dates`.

## What was wrong with the first draft

The event window was correct. The **historical comparison was built on a hard-coded
calendar** derived from a "CPI comes out around the 13th" proxy. Against the official
calendar, **7 of the 14 hard-coded entries are not CPI release dates**:

| hard-coded | official | kind | why it differs |
|---|---|---|---|
| 2025-10-15 | 2025-10-24 | misdated | release delayed by the government shutdown |
| 2025-11-13 | — | **phantom** | BLS published **no CPI at all** in Nov 2025; the Oct-2025 reference month was cancelled during the shutdown |
| 2025-12-10 | 2025-12-18 | misdated | shutdown backlog still unwinding |
| 2026-01-14 | 2026-01-13 | misdated | proxy off by one day |
| 2026-02-12 | 2026-02-13 | misdated | proxy off by one day |
| 2026-03-12 | 2026-03-11 | misdated | proxy off by one day |
| 2026-05-13 | 2026-05-12 | misdated | proxy off by one day |

The other 7 entries (2025-05-13, 06-11, 07-15, 08-12, 09-11, 2026-04-10, 2026-06-10)
were already correct. The proxy is not wrong everywhere — it is wrong at the shutdown
boundary and wherever BLS did not land near the 13th. That is what makes it dangerous:
it produced a complete, plausible table with no exception and no NaN.

## The correction, and why it inverts the headline claim

Sample: **14 → 13** (the phantom is deleted; the six misdated entries move rather than drop).

The draft claimed the 2026-06-10 VIX move ranked **4th of 14**. Every one of the three
moves it ranked above 2026-06-10 was on a **non-event day**:

| draft rank | date | VIX % | is it a CPI release? |
|---|---|---|---|
| 1 | 2026-02-12 | +17.96 | no — official was 02-13 |
| 2 | 2025-11-13 | +14.22 | **no — phantom, no release existed** |
| 3 | 2026-03-12 | +12.63 | no — official was 03-11 |
| 4 | 2026-06-10 | +11.827 | yes |

Remove the non-events and **2026-06-10 (+11.827%) is rank 1 of 13** — and by a wide
margin. Rank 2 is 2026-01-13 at +5.688%, under half the size.

The contamination was directional, not random: it manufactured exactly the three
competitors that demoted the actual event to fourth.

### The corrected sample also changes what "normal" means

| statistic | official 13-release sample |
|---|---|
| mean CPI-day VIX change | **-0.847%** |
| median | **-1.334%** |
| positive days | **4 / 13** |
| 2026-06-10 | **+11.827%, rank 1** |

So the CPI-day norm in this sample is a VIX **decline** — event uncertainty resolving and
short-dated premium being crushed. 2026-06-10 was not merely a large move; it ran
**against** the modal direction and was the largest in the sample. This is a stronger
result than the draft claimed, which is not a reason to relax about it: n=13 is small,
these are descriptive statistics, and no test was run. The article says so explicitly.

### An error the date fix did not cause

The draft's prose named its third-largest move as "2025 年 7 月 15 日的一次更大跳升".
2025-07-15 **is** an official release date, and its VIX move was **+1.047%** — 4th of 13,
nowhere near the top. That sentence did not match the draft's own `evidence.json`, which
ranked 2025-11-13 second. It was an independent prose fabrication layered on top of the
calendar bug, and it is recorded here rather than quietly deleted.

## Method deltas (disclosed, not claimed absent)

1. **Release dates from the official calendar**, fail-closed. No proxy, no fallback.
2. **XNYS session filter.** yfinance returns a `^VIX` quote for Memorial Day 2026-05-25,
   when the exchange was shut. Every reaction here is row arithmetic (`iloc[pos-1]` →
   `iloc[pos]`), which assumes the index *is* the session list. A missing, duplicated or
   out-of-order session now raises. **Verified inert on this data**: 2026-05-25 neighbours
   no official release date, so no reported number changes.
3. **Event window derived** from the release date's position in the session index rather
   than three hard-coded dates. On this data the derived window is identical.
4. **`OUT_DIR = Path(__file__).resolve().parent`.** The original hard-coded
   `/Users/yhlai0911/Desktop/volpred-research/...`, a root the repo moved out of.
   *Correction to the task framing:* the brief described this as a cwd-relative path that
   drifts with the working directory. It is not — it is an unportable **absolute** path,
   which combined with `mkdir(parents=True)` would silently resurrect a stale Desktop tree
   and write there from any cwd. Different failure mode, same fix. Flagged by Codex review.

## Figures — kept, and why

Both figures plot **only the 2026-06-09 … 06-11 event window**. Neither renders a
historical date, a rank, or the CPI sample. They are therefore structurally immune to the
calendar bug. Verified per-file rather than asserted:

| figure | verdict | evidence |
|---|---|---|
| `fig1_cpi_t0_reaction.png` | **content unchanged** | regenerated output is **byte-identical** to the archived copy (sha256 `8cf618f1…f445c`) |
| `fig2_cpi_t0_event_window.png` | **content unchanged** | 252 of ~2.5M pixels differ by ≤1/255 (anti-aliasing only); see caveat below |

fig2's sub-pixel drift is **not** from the date fix. yfinance restates `SPY` adjusted
closes as dividends are paid, so the 2026-06-12 download and the 2026-07-19 download
disagree in the 5th decimal (e.g. 2026-06-09 SPY 737.05 → 735.16 in level terms). The
*percentage* changes the article quotes are unaffected to 6 decimal places
(-1.5765545% → -1.5765563%). `^VIX` and `^VIX9D` are unadjusted and are bit-identical.

Both files were rewritten by the rerun; both are validated as content-unchanged.

## Independent check

The rank claim was recomputed by a second path before the script was rewritten: a
standalone pandas snippet that pulled `^VIX` directly, applied the XNYS filter, and ranked
the t-1→t reaction on the 13 official dates. It returned 2026-06-10 rank 1 at +11.827%,
matching `evidence.json`. The same snippet reproduced the draft's "rank 4 of 14" when fed
the legacy hard-coded list, which is what confirms the diagnosis rather than merely
asserting it.

## Regression tests

`tests/test_cpi_t0_official_release_dates.py` — 39 tests.

Not a smoke test: the suite was verified to **fail** when `official_cpi_dates` is reverted
to the hard-coded list — **8 of the 9** tests in `TestScriptUsesOfficialCalendar` fail. It
drives the script's own date resolution through a mocked `_fetch`, which a hard-coded list
would ignore. The one test that survives the revert is
`test_target_release_is_resolved_from_the_calendar`: the legacy list happened to contain
the correct 2026-06-10, so it resolves the right target for the wrong reason. That is
stated rather than rounded up to "every test fails".

Coverage:

- every legacy date pinned as not-a-release; the 7 correct ones pinned as still-correct
- Nov-2025 has no release (phantom guard)
- the script returns the 13 official dates and no legacy date survives
- **FRED release id 10 specifically** is what gets requested — without this, a script that
  called `nfp_release_dates` would be handed the CPI fixture and pass
- fail-closed on: a target month with no release, a release off the session calendar, an
  empty calendar
- `reaction_pct` rejects NaN/inf quotes and a zero prior close — the session guard
  validates the *index*, these pin the *values*
- `OUT_DIR` is the script directory and contains no `Desktop` path
- `evidence.json` on disk agrees with the official calendar, ranks 2026-06-10 first of 13,
  and its summary field reconciles with its own ranked table (catches a stale artifact
  produced by correct code that was never rerun)

### Known test-coverage limits

Stated rather than left for the next reader to discover:

- The `TestLegacyCalendarWasWrong` fixtures are hand-written and checked against each
  other. They prove internal consistency and catch typos; they do not independently
  re-verify FRED against BLS. The live calendar was checked once, by hand, during this
  rerun.
- The `evidence.json` tests check internal consistency of the artifact. They do not
  recompute reactions from market closes, so a regression in the price arithmetic would
  pass as long as the artifact was not rerun. `TestReactionArithmeticRejectsPoisonedQuotes`
  covers the arithmetic separately.
- The `OUT_DIR` tests pin a value; they do not `chdir` and rerun.

## Codex review

A read-only source-level review was run over `analysis.py` and the test file
(`scripts/codex_exec_bounded.sh --timeout 540 -s read-only`). It cleared the lookahead
question (t-1 close → t close is legitimate; the 08:30 release precedes the 09:30 open),
confirmed no path lets a legacy date into the sample, and confirmed the row arithmetic is
off-by-one free given the session guard.

Three findings were accepted and fixed in this commit:

1. The test class claimed reverting fails *every* test; it fails 8 of 9. Corrected.
2. The "cwd drift" characterisation of the original output path was wrong — it was an
   absolute path, not a cwd-relative one. Corrected in `analysis.py`, here, and in the
   results JSON.
3. The session guard validates the index but not the values; a NaN close would sort
   silently into the ranking. `reaction_pct` now raises on non-finite quotes and on a zero
   prior close, with tests. Verified inert: `evidence.json` is byte-identical after the
   change.

Two were noted and deliberately not acted on: `event_dates.release_dates()` collapses
multiple same-month FRED entries to the last one (canonical-module behaviour, documented
there, out of scope for this errata), and yfinance history is not snapshotted, so a future
rerun could shift if the vendor restates data — which is exactly what the SPY adjusted
closes did here, and is recorded above.

## Files

| file | role |
|---|---|
| `analysis.py` | the rerun; regenerates everything below |
| `evidence.json` | all reported numbers + an `errata` block |
| `article.md` | reader-facing draft, corrected, with an errata footer |
| `details.json` | publisher metadata; `event_key` corrected to `CPI_US_2026_06_10` |
| `k1442_cpi_date_fix_results.json` | task result artifact |
| `fig1_…png`, `fig2_…png` | event-window charts |
| `_archive_20260719/` | pre-correction copies, unmodified |

## Reproduce

```bash
FRED_API_KEY=… uv run python storage/event_articles/us_cpi_2026_06_11_t0/analysis.py
uv run --extra dev pytest tests/test_cpi_t0_official_release_dates.py -q
```

`FRED_API_KEY` is read from the repo-root `.env` / `.env.local` when not exported.
Git worktrees do not carry those untracked files, so the variable must be exported
explicitly when running from a worktree.

## Handoff

The article is **still unpublished and still a draft**. Nothing here publishes it. If it
is picked up for publication, note that it is now over a month stale (the release was
2026-06-10) and the "下週 FOMC" framing in the body no longer holds — it would need a
retrospective reframe, not a copy-paste. The corrected numbers are publication-ready; the
tense is not.
