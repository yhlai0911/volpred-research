# NFP first-Friday proxy → official BLS calendar: old vs new

**Task**: `assign_1238781f` (P1, submission blocker for `paper/volatility-absorption`)
**Date**: 2026-07-19
**Scripts**: `experiments/k741/k741_nfp_event_study_canonical.py`,
`experiments/k904/k904_task_s4_nfp_canonical.py`
**Results**: `k741_nfp_event_study_canonical_results.json`,
`k904_task_s4_nfp_canonical_results.json`

---

## 0. How to read this (the comparison is three-way, not two-way)

The archived k741/k904 JSONs differ from any re-run in **two** ways at once: the event-date
source *and* the price snapshot (they used live yfinance pulls; yfinance retroactively revises
history — the paper documents this in §robustness). A naive archived-vs-canonical diff would
confound the two.

So both scripts run **two arms on one identical pinned price snapshot**
(`paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv`, the paper's own
2026-04-19 pinned data):

| column | meaning |
|---|---|
| **Paper** | what `main_v3.tex` currently prints |
| **Proxy (same data)** | first-Friday proxy re-estimated on the pinned snapshot |
| **Canonical** | official BLS release dates on the *same* pinned snapshot |

**Canonical − Proxy is the clean date-source effect.** Proxy − Paper is snapshot drift plus
transcription, reported separately in §4.

**Validation that the re-implementation is faithful**: the proxy arm reproduces the archived
JSONs essentially to the digit.

| check | archived JSON | proxy arm (pinned) |
|---|---|---|
| k741 ratio vs all | 1.14481 | 1.14497 |
| k741 p vs all | 0.08138 | 0.08113 |
| k741 Low n / mean\|r\| | 62 / 0.4982 | 62 / 0.498 |
| k904 overall ratio | 1.142569 | 1.142565 |
| k904 overall t / p | 1.79390 / 0.074220 | 1.794 / 0.07422 |
| k904 Low ratio / t / p | 1.23023 / 1.73813 / 0.08690 | 1.230 / 1.74 / 0.0869 |

Snapshot drift is therefore **negligible** for these statistics. Everything below is the date fix.

---

## 1. Date diff: how contaminated was the proxy?

Official source: FRED/ALFRED release id 50 ("Employment Situation") via
`volpred.data.event_dates.nfp_release_dates`.

| | count |
|---|---|
| Proxy event dates (2010-01 … 2026-03) | 195 |
| Canonical release dates, same span | 194 |
| **Exact date match** | **161** |
| **Months where the date is wrong** | **33** |
| **Phantom months (proxy invents an event)** | **1** |

**34 of 195 proxy event slots (17.4%) are wrong** — materially worse than the sweep's
"13 wrong dates" estimate.

Failure modes:

| pattern | n | example | cause |
|---|---|---|---|
| `+7d` | 26 | 2010-01-01 → 2010-01-08 | The 1st of the month falls on a Friday. The prior month's data is not ready, so BLS releases on the **second** Friday. The proxy always takes the first. |
| `−1d` | 4 | 2025-07-04 → 2025-07-03 | July 4 holiday: BLS releases **Thursday**. The proxy takes Friday (market closed) and then maps forward to Monday — off by 2 trading days. |
| shutdown delay | 2 | 2025-11-07 → 2025-11-20 (+13d), 2025-12-05 → 2025-12-16 (+11d) | Government-shutdown catch-up schedule. |
| other | 1 | 2026-02-06 → 2026-02-11 (+5d) | Rescheduled release. |
| **phantom** | 1 | proxy asserts **2025-10-03** | **No NFP was released in Oct 2025** — cancelled during the shutdown. The proxy scored an ordinary trading day as an event day. |
| 2013 shutdown | 1 | 2013-10-04 → 2013-10-22 (+18d) | Included in the 33. |

A separate defect the fix also had to address: the archived date→trading-day mapping searched
`[nd−1d, nd+3d]` (k741) / "closest within ±3d" (k904) and so resolved **backward** to the trading
day *before* the release when a release landed on a market holiday. That is a **lookahead**, and it
bites 5 Good Friday releases (2010-04-02, 2012-04-06, 2015-04-03, 2021-04-02, 2023-04-07) on which
BLS published but US equity markets were shut. The canonical arms map forward only. Recorded as
`methodology_deltas` in both result JSONs.

---

## 2. Overall NFP effect — abstract L43 / L72, Results L368

k741 spec (Student's *t*, `equal_var=True`; see §5 on the paper's "Welch" label).

| statistic | Paper | Proxy (same data) | **Canonical** | Δ vs Paper | significance flip? |
|---|---|---|---|---|---|
| ratio vs all non-NFP | 1.14 | 1.1450 | **1.1650** | **+0.025** | — |
| *p* vs all non-NFP | 0.081 | 0.0811 | **0.0479** | **−0.033** | **⚑ YES — 10% marginal → 5% significant** |
| ratio vs Fridays | 1.16 | 1.1648 | **1.1885** | **+0.029** | — |
| *p* vs Fridays | 0.061 | 0.0605 | **0.0328** | **−0.028** | **⚑ YES — 10% marginal → 5% significant** |
| Wilcoxon *p* vs all | 0.0037 | 0.0037 | **0.0006** | −0.0031 | already <1%, strengthens |
| N_NFP | 195 | 195 | **194** | **−1** | phantom 2025-10 removed |
| N_non-NFP | 3,909 | 3,910 | **3,911** | +2 | |
| Total trading days | 4,104 | 4,105 | **4,105** | **+1** | pinned snapshot has 1 more day |

k904 corroboration (Welch, all-non-NFP baseline, window to 2026-04):

| statistic | Proxy (same data) | **Canonical** | flip? |
|---|---|---|---|
| overall ratio | 1.1426 | **1.1624** | — |
| overall *p* | 0.0742 | **0.0401** | **⚑ 10% → 5%** |
| vs-Friday ratio | 1.1634 | **1.1871** | — |
| vs-Friday *p* | 0.0683 | **0.0361** | **⚑ 10% → 5%** |

**Two independent scripts, two sample windows, two test variants converge on the same canonical
answer** (1.165 vs 1.162 overall; 1.189 vs 1.187 vs-Friday). The corroboration is real, not shared code.

---

## 3. Regime table `tab:nfp` — main_v3.tex L375–391

| Regime | n Paper | **n Canon** | \|r\| Paper | **\|r\| Canon** | ratio Paper | **ratio Canon** | *t* Paper | ***t* Canon** | *p* Paper | ***p* Canon** | flip? |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Low (V<15) | 62 | **63** | 0.498 | **0.527** | 1.24 | **1.305** | 1.85 | **2.62** | 0.069 | **0.0089** | **⚑⚑ UPGRADE: 10% marginal → 1% significant** |
| Medium (15–20) | 78 | **76** | 0.757 | **0.788** | 1.30 | **1.232** | 2.69 | **2.23** | 0.009 | **0.0257** | **⚑ DOWNGRADE: 1% → 5%** |
| Elevated (20–25) | 27 | 27 | 1.022 | **1.046** | 1.18 | **1.198** | 1.10 | **1.21** | 0.279 | **0.2257** | not significant either way |
| High (V≥25) | 28 | 28 | 1.488 | **1.417** | 0.95 | **0.936** | −0.29 | **−0.34** | 0.777 | **0.7312** | not significant either way |

k904 canonical regimes agree: Low 1.305 (*p*=0.0260), Medium 1.230 (*p*=0.0285),
Elevated 1.188 (*p*=0.2628), High 0.935 (*p*=0.7032).

### Direction and structure: intact, and cleaner

- **No sign flips.** Every regime keeps its side of 1.0; High stays below 1.0 (0.936).
- **The absorption gradient is now monotone.** Published: 1.24 → 1.30 → 1.18 → 0.95 (Medium
  *above* Low, a bump the paper never explained). Canonical: **1.305 → 1.232 → 1.198 → 0.936**,
  a clean monotone decline in ambient fear — *more* consistent with the absorption hypothesis,
  not less.
- **Net significance improves.** Overall crosses into 5%; Low gains two thresholds; Medium loses
  one (1% → 5%, still significant). Nothing that was significant becomes insignificant.

**Verdict: this is the "numbers move, narrative holds" branch of the brief.** No downgrade or
removal of §sec:nfp is warranted. The corrected evidence supports the paper's claim more strongly
than the contaminated evidence did.

---

## 4. ⚠️ Second, independent defect found: the published ratio/*t*/*p* are untraceable

While validating, the proxy arm reproduced the archived `n` and `mean|r|` **exactly** — but **not**
the paper's `ratio`, `t`, and `p` columns:

| Regime | Paper ratio/*t*/*p* | proxy repro (k741 spec) | archived k904 (Welch) |
|---|---|---|---|
| Low | 1.24 / 1.85 / 0.069 | 1.230 / 1.97 / 0.0495 | 1.230 / 1.74 / 0.0869 |
| Medium | **1.30 / 2.69 / 0.009** | **1.181 / 1.77 / 0.0775** | **1.175 / 1.70 / 0.0919** |
| Elevated | 1.18 / 1.10 / 0.279 | 1.169 / 1.04 / 0.2997 | 1.149 / 0.91 / 0.3701 |
| High | 0.95 / −0.29 / 0.777 | 0.985 / −0.08 / 0.9358 | 0.984 / −0.09 / 0.9256 |

I scanned **8 plausible spec variants** (VIX_prev vs contemporaneous VIX × all-non-NFP vs
Friday-only baseline × Student vs Welch). **None reproduces the published row**, and Medium
(1.30×, *p*=0.009) is far outside all of them.

**Root cause of the miss**: `paper/volatility-absorption/reproduce.py` binds only the regime `n`
and `mean_abs` (lines 144–147) and the *overall* ratios (139–143). **It never binds the regime
ratio/*t*/*p*.** Those three columns were transcribed from an older draft's stdout and no
reproducibility check has ever covered them.

This is **independent of the proxy defect** and would have survived the date fix. The canonical
re-run resolves both at once, because the new JSONs now *persist* regime ratio/*t*/*p* — so
`reproduce.py` can bind them. **Recommend the main thread add those bindings** (not done here:
`reproduce.py` is paper infrastructure, outside a worktree agent's remit).

Not listed in `errata_pending.md`, which covers only the K903/K904 snapshot drifts.

---

## 5. ⚠️ Third defect: the paper calls these "Welch's *t*-tests" — they are not

`main_v3.tex` L72 and §sec:nfp label the overall NFP numbers "Welch's *t*-tests". Those values
(1.14, *p*=0.081; 1.16, *p*=0.061) come from k741, which calls
`stats.ttest_ind(nfp_abs, non_abs)` — scipy's default is `equal_var=True`, i.e. **Student's**
pooled-variance *t*-test. k741 never passes `equal_var=False`. (Sibling k904 *does* use Welch,
which is likely where the label leaked in from.)

Purely a labelling error — independent of the date proxy. The canonical k741 arm keeps
`equal_var=True` for 1:1 comparability, so **the label must be corrected in the tex**, or the
statistic switched to Welch deliberately. Both canonical arms are significant at 5% either way
(Student *p*=0.0479, Welch *p*=0.0401), so the choice does not affect any claim.

---

## 6. Feed back-correction: assessment only (not executed)

Per brief, judgement only — no `storage/` writes, no publishing.

| K | feed articles | uses NFP dates? | recommendation |
|---|---|---|---|
| k528 | 7 | yes — same first-Friday proxy | **Erratum warranted for any article quoting a *p*-value or a "not significant" verdict**; headline direction is unchanged |
| k661 | 2 | yes — same proxy | **Same**, plus check the "VIX>25 NFP effect vanishes" claim, which survives (0.936×, *p*=0.73) |

Reasoning: the *direction* of every NFP claim survives the correction, so no article is
**wrong in its conclusion**. What changed is **strength**: several results move from "marginally
significant / not significant at 5%" to "significant at 5%", and Low-VIX moves to 1%. An article
that told readers "the NFP effect is *not* statistically robust" is now understating the
corrected evidence.

**Recommended scope: erratum note, not retraction, on the subset that quotes statistics.**
Articles that only describe the qualitative pattern (NFP matters more in calm markets, vanishes in
crises) need no change — that pattern is *strengthened*.

**Caveat on my own confidence here**: I did not read the 9 articles. This ranking is inferred from
the K-ids in the sweep report and the statistics that moved. The main thread should grep the actual
article bodies for quoted *p*-values and N before deciding. The one thing I would check first is
whether any article cites **N=195 NFP days** or **2025-10-03** as an event date — both are now
provably wrong, independent of any significance question.

---

## 7. What I did not do / am not certain about

- **No Codex review yet.** `.claude/rules/experiments.md` makes Codex review the gate before
  `knowledge.json`. Not run here; the main thread owns that gate.
- **Parts C/D of k741 not re-run** (sector dispersion, NFP-day strategy). Verified by grep that
  `main_v3.tex` cites neither, and they need sector ETFs absent from the pinned snapshot. If they
  are ever published, they carry the same contamination.
- **`task_s2_shock_types` deliberately untouched**, per brief — it keys on |ΔVIX|>2 and never
  reads an NFP date.
- **`paper/volatility-absorption/experiments/k904_paper8_shock_nfp_fix.py` is a stale copy** of the
  main `experiments/k904/` script. I did not modify it (paper-directory files are outside a
  worktree agent's remit). **Recommend the main thread sync or delete it** — `reproduce.py` reads
  the paper-directory copy's *results* JSON, so a divergent copy is a live reproducibility hazard.
- **Snapshot choice is a judgement call I made**: pinned CSV over a fresh yfinance pull, to make
  the date effect identifiable and the result reproducible in future. It means the canonical
  numbers are on the paper's 2026-04-19 pinned snapshot rather than k741's original live pull. The
  proxy-arm validation in §0 shows this costs essentially nothing, but it is a deviation worth
  knowing about.
- **The 4,104 → 4,105 total-trading-day change** is from the pinned snapshot, not the date fix. I
  did not chase which single day differs from the archived live pull.
