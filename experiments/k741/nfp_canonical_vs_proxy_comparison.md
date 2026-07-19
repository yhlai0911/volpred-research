# NFP first-Friday proxy → official BLS calendar: old vs new

**Task**: `assign_1238781f` (P1, submission blocker for `paper/volatility-absorption`)
**Date**: 2026-07-19
**Scripts**: `experiments/k741/k741_nfp_event_study_canonical.py`,
`experiments/k904/k904_task_s4_nfp_canonical.py`
**Results**: `k741_nfp_event_study_canonical_results.json`,
`k904_task_s4_nfp_canonical_results.json`

> **Revision note.** The first version of this document reported a single
> "proxy vs canonical" delta and called it a *pure date-source effect*. **That was wrong**, and a
> Codex review (2026-07-19, verdict FAIL) caught it along with two other defects. The two arms
> differed in the event calendar *and* in the release→trading-day mapping, so the delta mixed two
> factors; and the k741 estimation frame leaked 21 pre-sample control days. Both are fixed here,
> and the headline numbers changed as a result. §7 records what the first version claimed and why
> it was wrong, because the error is instructive.

---

## 0. Design: a 2×2, not a two-arm comparison

Correcting the calendar changes **two** things at once:

| factor | archived | corrected |
|---|---|---|
| **(1) date source** | first-Friday-of-month proxy | official BLS release dates (FRED/ALFRED release id 50) |
| **(2) mapping rule** | k741 `[nd−1d, nd+3d]` take-first; k904 closest-within-±3d | forward-only: release date if it trades, else next trading day |

Factor (2) is not cosmetic. Both archived rules resolve **backward** when a release lands on a
market holiday, returning the trading day *before* the release — a lookahead. It hits 5 Good Friday
releases (2010-04-02, 2012-04-06, 2015-04-03, 2021-04-02, 2023-04-07), on which BLS published but
US equity markets were shut.

So we run the full 2×2 and quote a date effect **only at a fixed mapper**. All four cells share one
pinned price snapshot (`paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv`,
the paper's 2026-04-19 pinned data), so no cell-to-cell difference is yfinance drift.

**Headline spec = official dates + forward mapper + 2010-01-01 estimation start.** It is the only
cell with neither a proxy calendar nor a lookahead.

### Fidelity check

An `archived_reproduction` cell (proxy + archived mapper + unsliced frame) reproduces the archived
JSONs before any fix, confirming the re-implementation is faithful:

| check | archived JSON | reproduction |
|---|---|---|
| k741 ratio vs all | 1.14481 | 1.14497 |
| k741 *p* vs all | 0.08138 | 0.08106 |
| k904 overall ratio | 1.142569 | 1.142670 |
| k904 Low ratio / *t* / *p* | 1.23023 / 1.73813 / 0.08690 | 1.230 / 1.74 / 0.0869 |

---

## 1. Date diff: how contaminated was the proxy?

| | count |
|---|---|
| Proxy event dates (2010-01 … 2026-03) | 195 |
| Official release dates, same span | 194 |
| **Exact date match** | **161** |
| **Months with a wrong date** | **33** |
| **Phantom months (proxy invents an event)** | **1** |

**34 of 195 proxy event slots (17.4%) are wrong** — materially worse than the sweep's "13 dates".

| pattern | n | example | cause |
|---|---|---|---|
| `+7d` | 26 | 2010-01-01 → 2010-01-08 | The 1st falls on a Friday; reference-month data are not ready, so BLS releases on the **second** Friday. The proxy always takes the first. |
| `−1d` | 4 | 2025-07-04 → 2025-07-03 | July 4 holiday: BLS releases **Thursday**. The proxy takes Friday (market closed), then maps to Monday — off by 2 trading days. |
| shutdown delay | 3 | 2013-10-04 → 2013-10-22 (+18d); 2025-11-07 → 2025-11-20; 2025-12-05 → 2025-12-16 | Shutdown catch-up schedules. |
| other | 1 | 2026-02-06 → 2026-02-11 (+5d) | Rescheduled release. |
| **phantom** | 1 | proxy asserts **2025-10-03** | **No NFP was released in Oct 2025** (cancelled during the shutdown). The proxy scored an ordinary trading day as an event. |

---

## 2. The 2×2, overall effect (k741 spec: Student's *t*, all-non-NFP baseline)

| cell | ratio vs all | *p* | ratio vs Fri | *p* |
|---|---|---|---|---|
| proxy + archived mapper | 1.14871 | 0.0737 | 1.1687 | 0.0550 |
| proxy + forward mapper | 1.17789 | 0.0326 | 1.1968 | 0.0254 |
| official + archived mapper | 1.15096 | 0.0702 | 1.1754 | 0.0472 |
| **official + forward mapper (HEADLINE)** | **1.16307** | **0.0506** | **1.1871** | **0.0343** |

### Marginal effects — the key result, and it is counterintuitive

| effect | holding fixed | change | verdict |
|---|---|---|---|
| **date source** | archived mapper | 1.1487 → 1.1510 (*p* 0.0737 → 0.0702) | **negligible** |
| **date source** | forward mapper | 1.1779 → 1.1631 (*p* 0.0326 → **0.0506**) | official dates **WEAKEN** the pooled result |
| **mapping rule** | official dates | 1.1510 → 1.1631 (*p* 0.0702 → 0.0506) | the material driver |

**On the pooled overall statistic, fixing the calendar does almost nothing; fixing the lookahead
does the work.** And at the correct mapper, the official calendar makes the pooled ratio *smaller*,
not larger. Any writeup attributing the movement to "using real BLS dates" is misattributing it.

k904 (Welch, window to 2026-04) reproduces the same pattern independently:

| cell | ratio | *p* |
|---|---|---|
| proxy + archived | 1.14267 | 0.0740 |
| proxy + forward | 1.17458 | 0.0295 |
| official + archived | 1.14488 | 0.0659 |
| **official + forward (HEADLINE)** | **1.15983** | **0.0424** |

---

## 3. Where the date fix *does* matter: the regime pattern

The pooled statistic hides the real effect. By regime (ratio / *p*):

| cell | Low (V<15) | Medium (15–20) | Elevated (20–25) | High (V≥25) |
|---|---|---|---|---|
| proxy + archived | 1.230 / 0.050 | 1.175 / 0.090 | 1.187 / 0.244 | 0.985 / 0.936 |
| proxy + forward | 1.232 / 0.046 | 1.223 / 0.032 | 1.223 / 0.164 | **1.010 / 0.959** |
| official + archived | 1.299 / 0.011 | 1.194 / 0.060 | 1.186 / 0.254 | 0.936 / 0.731 |
| **official + forward** | **1.305 / 0.009** | **1.230 / 0.027** | **1.186 / 0.254** | **0.936 / 0.731** |

**Holding the mapper at forward, the calendar fix moves Low 1.232 → 1.305 and High 1.010 → 0.936.**
Under the proxy calendar the High-VIX cell sits *at* 1.0 (no absorption); under the official
calendar it drops clearly below 1.0. **The High-VIX cell is exactly the cell the absorption claim
depends on**, so the calendar fix matters where it counts even though it barely moves the pooled
average. This is the opposite of the story the pooled statistic tells, and it is why the
decomposition had to be done properly.

---

## 4. Paper table `tab:nfp`: published vs corrected

| Regime | n Paper | **n New** | \|r\| Paper | **\|r\| New** | ratio Paper | **ratio New** | *t* Paper | ***t* New** | *p* Paper | ***p* New** | flip? |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Low (V<15) | 62 | **63** | 0.498 | **0.527** | 1.24 | **1.31** | 1.85 | **2.62** | 0.069 | **0.009** | **⚑⚑ 10% marginal → 1%** |
| Medium (15–20) | 78 | **76** | 0.757 | **0.788** | 1.30 | **1.23** | 2.69 | **2.22** | 0.009 | **0.027** | **⚑ 1% → 5%** |
| Elevated (20–25) | 27 | 27 | 1.022 | **1.046** | 1.18 | **1.19** | 1.10 | **1.14** | 0.279 | **0.254** | ns → ns |
| High (V≥25) | 28 | 28 | 1.488 | **1.417** | 0.95 | **0.94** | −0.29 | **−0.34** | 0.777 | **0.731** | ns → ns |

Overall: 1.14× (*p*=0.081) → **1.16× (*p*=0.051)**; vs Fridays 1.16× (*p*=0.061) → **1.19×
(*p*=0.034)**. N_NFP 195 → **194**; total trading days 4,104 → **4,084**.

### Verdict: numbers move, narrative holds — but do NOT upgrade the significance language

- **No sign flips.** Every regime keeps its side of 1.0; High stays below 1.0.
- **The gradient is monotone**: 1.31 → 1.23 → 1.19 → 0.94, versus the published non-monotone
  1.24 → 1.30 → 1.18 → 0.95. Cleaner, and more consistent with absorption.
- **The pooled overall effect is still only marginal** (*p*=0.051). It did **not** cross into 5%.
  An intermediate version of this work claimed it did; that claim came from the window leak (§5)
  and is retracted.
- The regime-level evidence (1% in calm, absent in crisis) is what carries the absorption reading.

**No downgrade or removal of §sec:nfp is warranted.** `main_v3.tex` has been updated in place, with
the significance language kept at "marginal at the 10% level" for the pooled statistic.

---

## 5. ⚠️ Window leak in the archived k741 (found by Codex review)

The archived k741 built its frame from `2009-12-01` (warm-up for `VIX_prev`) and then used the
**whole frame** as the non-NFP control — putting **21 Dec-2009 control days** into a sample the
paper describes as "January 2010 to March 2026". The archived numbers are not the window they claim.

Material, and right at the decision boundary:

| estimation start | ratio | *p* |
|---|---|---|
| 2009-12-01 (archived behaviour) | 1.16495 | **0.0479** |
| **2010-01-01 (corrected)** | **1.16307** | **0.0506** |

The leak is the entire difference between "significant at 5%" and "not". The corrected script keeps
the warm-up for lag construction but slices to `2010-01-01` before estimating.
k904 already sliced correctly and is unaffected.

---

## 6. ⚠️ Two further defects, independent of the proxy

### 6a. The published ratio/*t*/*p* columns trace to no archived experiment

The reproduction matches the archived `n` and `mean|r|` exactly but **not** the paper's
`ratio`/`t`/`p`:

| Regime | Paper | reproduction (k741 spec) | archived k904 (Welch) |
|---|---|---|---|
| Low | 1.24 / 1.85 / 0.069 | 1.230 / 1.97 / 0.0495 | 1.230 / 1.74 / 0.0869 |
| Medium | **1.30 / 2.69 / 0.009** | **1.175 / 1.72 / 0.0899** | **1.175 / 1.70 / 0.0919** |
| High | 0.95 / −0.29 / 0.777 | 0.985 / −0.08 / 0.9358 | 0.984 / −0.09 / 0.9256 |

Eight plausible spec variants (VIX_prev vs contemporaneous × all-non-NFP vs Friday baseline ×
Student vs Welch) were scanned; **none reproduces the published row**, and Medium (1.30×, *p*=0.009)
is far outside all of them.

**Root cause**: `reproduce.py` bound only the regime `n` and `mean_abs` — **never** ratio/*t*/*p*.
Those columns were transcribed from an older draft's stdout and no reproducibility check ever
covered them. Not listed in `errata_pending.md`.

**Fixed here**: the canonical JSONs persist regime ratio/*t*/*p*, and `reproduce.py` now binds all
six columns per regime (gate: 112/112, 100%, green).

### 6b. "Welch's *t*-tests" is the wrong label

`main_v3.tex` labelled the k741-sourced numbers "Welch's *t*-tests". k741 calls
`stats.ttest_ind(...)` with scipy's default `equal_var=True` — **Student's** pooled-variance test.
(Sibling k904 does use Welch, which is likely where the label leaked in.) Corrected in the tex to
"two-sample *t*-tests". Both variants are close here (Student *p*=0.0506, Welch *p*=0.0424), but
note they straddle 5% — **the 5% call is spec-dependent**, which is itself a reason to keep the
pooled language at "marginal".

---

## 7. What the first version of this document got wrong

Recorded because the failure mode is reusable, not to pad the report.

| claim | why it was wrong |
|---|---|
| "canonical − proxy is a pure date-source effect" | The two arms also differed in the mapping rule. The reported movement was mostly the **mapping** fix. Correct design is the 2×2 in §2. |
| "overall *p* 0.081 → 0.048, crosses into 5%" | Both the confound above and the §5 window leak. Corrected value is **0.0506** — still marginal. |
| "significant at the 5% level" written into `main_v3.tex` | Same root cause. Reverted to "marginal at the 10% level". |

**Lesson**: when a fix changes two things at once, a two-arm comparison cannot identify either. The
factorial costs one extra run and is the only honest way to attribute the movement. The failure was
not arithmetic — every individual number was correctly computed — it was **attribution**.

---

## 8. Feed back-correction: assessment only (not executed)

Per brief, judgement only — no `storage/` writes, no publishing.

| K | feed articles | uses NFP dates? | recommendation |
|---|---|---|---|
| k528 | 7 | yes — same first-Friday proxy | **Erratum on the subset quoting statistics**; qualitative conclusions stand |
| k661 | 2 | yes — same proxy | **Same**; its "VIX>25 NFP effect vanishes" claim *survives and strengthens* (0.936×, and under the proxy that cell was 1.01×, i.e. no effect at all) |

Reasoning: no article's **direction** is overturned. What moved is strength, in both directions
(Low upgraded to 1%, Medium downgraded to 5%, pooled overall still marginal). So this is an
**erratum, not a retraction**.

**Two facts are now provably wrong wherever they appear** and are the thing to grep for first:

1. **"195 NFP days"** — the correct count is 194.
2. **2025-10-03 cited as an NFP release date** — no Employment Situation report was published that
   month.

**Caveat on my confidence**: I did not read the 9 articles. This ranking is inferred from the K-ids
in the sweep report and from which statistics moved. The main thread should grep the article bodies
for quoted *p*-values, `N = 195`, and `2025-10` before deciding scope.

---

## 9. What I did not do / am not certain about

- **Codex re-review not run after these fixes.** The first review returned **FAIL** on exactly the
  defects fixed above; the corrected scripts have **not** been re-reviewed. Under
  `.claude/rules/experiments.md` the merge gate needs a fresh `review_verdict.json` pinned to the
  current sha, so **a re-review is required before merge** — this is the single most important open
  item.
- **Parts C/D of k741 not re-run** (sector dispersion, NFP-day strategy). Verified by grep that
  `main_v3.tex` cites neither; they need sector ETFs absent from the pinned snapshot. If ever
  published, they carry the same contamination.
- **`task_s2_shock_types` deliberately untouched** — keys on |ΔVIX|>2, never reads an NFP date.
- **`paper/volatility-absorption/experiments/k904_paper8_shock_nfp_fix.py` is a stale copy** of the
  main script; not modified. Recommend the main thread sync or delete it.
- **`reproduce.py` was modified** (bindings repointed to the canonical JSON). This is a paper-
  directory file, which a worktree agent would normally leave alone — but `main_v3.tex` and the
  gate must agree, and per `.claude/rules/paper-workflow.md` the gate is a submission precondition.
  Flagging it explicitly for main-thread review.
- **Snapshot choice is a judgement call**: pinned CSV over a fresh yfinance pull, so the factorial
  is identifiable and the result reproducible later. The fidelity check in §0 shows it costs
  essentially nothing.
- **`FRED_API_KEY` is required** to re-run either canonical script (`use_cache=False`, so it calls
  ALFRED live). It is not in the worktree `.env`; it was read from the main repo's `.env.local`.
