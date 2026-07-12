# paper2_taiwan_indiv_rolling_gamma

**Calendar-aligned rolling-window (w=2000) GJR-GARCH leverage parameters for Taiwan-VT Table 2 (`tab:gamma`).**

Run date: 2026-07-13 · Data pulled: 2026-07-13 · Common end: **2026-07-09** · `arch` 8.0.0

---

## 1. Why this was re-run: the previous "RESOLVED" was false

The 2026-07-07 run answered Codex's calendar-alignment CONDITIONAL_PASS caveat by truncating all
ten securities to a common terminal date of **2025-01-22**, and wrote
`codex_caveat_calendar_alignment: "RESOLVED"` into the results JSON.

That resolution was cosmetic. **2025-01-22 was not a market fact.** It was the last row of two stale
offline snapshots — `experiments/k1302/data/2383_tw.csv` and `2886_tw.csv`. The other eight
securities had data running well into 2026 and were discarded so that the windows would line up with
two expired files.

The consequence was a research-honesty defect, not merely a precision one:

> The paper states its individual-stock sample runs to 2026 ("Individual stocks use the full
> available sample (2008–2026)", `body_v3.tex` L196), while Table 2's rolling rows actually ended in
> **January 2025**.

Alignment was real. The sample period was not.

The stated reason for truncating rather than re-fetching was to preserve the "fully reproducible, no
network" guarantee. **Both are obtainable at once**, which is what this run does:
`fetch_snapshots.py` pulls every series **once** into this experiment's own `data/` directory, and
`paper2_taiwan_indiv_rolling_gamma.py` then estimates **fully offline** from those committed
snapshots. Reproducibility is preserved; the sample is honest.

---

## 2. Data

| | |
|---|---|
| Source | yfinance, single pull 2026-07-13 |
| Convention | `auto_adjust=False`, price column = **`Adj Close`** (dividend + split adjusted) — matches the paper's canonical rule (`body_v3.tex` L33) |
| Series | 9 stocks (2317, 2454, 2383, 2886, 2412, 2881, 2882, 2885, 2891) + 0056.TW ETF + index rows TWII, 0050.TW |
| Snapshots | `data/*.csv`, manifest in `data/MANIFEST.json` |
| Sample start | 2008-01-01 (irrelevant to a last-2000 window, but keeps the paper's framing) |
| Common end | **2026-07-09** — the latest trading day on which *all twelve* series have data. Bound by `^TWII`, which posts one session behind the single stocks. |

**Regression check (the refresh did not change the data, only the window).** Every refreshed series'
log returns reproduce the previous canonical snapshots (paper CSV / k1302 / k1302b) to **< 1e-6** over
the overlapping sample. See `data/MANIFEST.json → series[*].regression_vs_old_snapshot`. Confirmed
end-to-end as well: re-estimating the *old* window (end 2025-01-22) on the *new* data reproduces the
2026-07-07 run's numbers (9-stock mean γ 0.0241 both times; TWII γ 0.1575 both times). So the refresh
moved the **sample window**, not the data.

**A false caveat in the old results JSON, now withdrawn.** The previous `data_source_note` claimed the
package mixed adjusted and raw closes ("Mixed adj/close is inherited from the canonical K1302/K1302b
data package"). **That was wrong.** The k1302b snapshots' column is *named* `Close` only because they
were downloaded with `auto_adjust=True`, which writes the *adjusted* series into that column. Verified:
k1302b log returns match fresh `Adj Close` log returns to ~1e-6 (adjusted-price returns are
vintage-invariant, so this is a decisive test). There is **no** mixed convention anywhere in the data
package. A caveat describing a defect that does not exist is still a provenance error, and it is
retracted here.

---

## 3. Headline results (primary: common end 2026-07-09)

All twelve rows share `window_end = 2026-07-09`. All fits converged (`convergence = 0`); no restarts
were needed. Window *starts* span only 2018-04-18 to 2018-04-19 — each row takes its own last 2000
*observations*, and securities differ by a day or two of trading-calendar coverage.

### Individual stocks (the 9-stock cross-section)

| Ticker | Name | γ | t | Persistence |
|---|---|---|---|---|
| 2317.TW | Hon Hai | 0.020 | 0.55 | 0.970 |
| 2454.TW | MediaTek | 0.017 | 0.80 | 0.942 |
| 2383.TW | Elite Material | 0.025 | 1.04 | 0.967 |
| 2886.TW | Mega Financial | 0.170 | 1.56 | 0.789 |
| 2412.TW | Chunghwa Telecom | **−0.030** | −0.55 | 0.797 |
| 2881.TW | Fubon | 0.009 | 0.27 | 0.959 |
| 2882.TW | Cathay Financial | 0.024 | 0.57 | 0.958 |
| 2885.TW | Yuanta | 0.025 | 0.51 | 0.893 |
| 2891.TW | CTBC | 0.031 | 0.67 | 0.967 |

### ETF and index rows

| Ticker | γ | t |
|---|---|---|
| **0056.TW** (High-Div ETF) | **0.222** | **2.95** |
| TWII (TAIEX) | 0.198 | 1.86 |
| 0050.TW | 0.106 | 2.01 |

### Aggregates

| Quantity | Value |
|---|---|
| 9-stock mean γ | 0.0323 |
| 10-security mean γ (incl. 0056) | 0.0512 |
| TWII rolling γ | 0.1975 |
| ~~Amplification ratio (9-stock)~~ | ~~6.12×~~ — **do not report; see §6.3** |
| ~~Amplification ratio (10-security)~~ | ~~3.85×~~ — **do not report; see §6.3** |
| **Difference** γ_TWII − γ̄_9stock | **0.184**, 95% CI [0.072, 0.298] ← **report this instead** |

> **The amplification ratio must not be quoted as a point estimate.** Its denominator is a mean of nine
> individually insignificant γ's whose bootstrap CI **covers zero**, which makes the ratio's Fieller
> confidence set unbounded (bootstrap 95% CI: **[−26×, +34×]**). The ratios above are printed only
> because the paper currently reports one and the comparison is owed. **§6.3 gives the two statistics
> that are robust and should replace it.**

**Not one of the nine individual stocks has a significant γ** (largest |t| = 1.56). Chunghwa Telecom's
point estimate is *negative*. And the TAIEX's own rolling γ carries **t = 1.86 — not significant at
5%**. The only significant leverage effect anywhere in the rolling block belongs to 0056.TW.

---

## 4. New vs. old

`N121` = the values currently rendered in `body_v3.tex`, traceable only to a knowledge entry derived
from a since-deleted run (no surviving source JSON). `prior run` = the 2026-07-07 truncated-to-2025
estimates.

| Row | N121 (rendered) | prior run (end 2025-01-22) | **NEW primary (end 2026-07-09)** |
|---|---|---|---|
| Hon Hai 2317 | 0.052 / t=1.14 | 0.015 / 0.45 | **0.020 / 0.55** |
| MediaTek 2454 | 0.044 / 0.96 | 0.027 / 1.22 | **0.017 / 0.80** |
| Mega 2886 | 0.179 / 2.42 | 0.054 / 1.41 | **0.170 / 1.56** |
| 0056 ETF | 0.112 / 1.87 | 0.202 / 2.89 | **0.222 / 2.95** |
| 9-stock mean γ | 0.054 | 0.024 | **0.032** |
| 10-security mean γ | 0.060 | 0.042 | **0.051** |
| TWII rolling γ | 0.272 | 0.158 | **0.198** |
| Ratio (9-stock) | 5.0× | 6.53× | **6.12×** |
| Ratio (10-security) | 4.5× | 3.75× | **3.85×** |

### The 2886 "3× off" self-accusation — withdraw it, but do **not** replace it with vindication

`body_v3.tex` L155–181 currently self-reports: *"2886 legacy 0.179 → reproducible 0.054 (3× off)"*.

An earlier draft of this README argued that the 2026 window gives 0.170 ≈ the legacy 0.179, so the
paper's self-accusation was wrong. **That argument was motivated reasoning and is withdrawn.** §6 of this
same README shows 2886's γ is *end-date dependent*; an agreement that can be reached by moving the
terminal date is not evidence that N121 was computed correctly. It is a coin-flip agreement, and a
referee would read it as one.

**The honest statement:** the 0.054-vs-0.179 gap is *not* evidence of a reproduction failure — it is
inside the range this estimator spans as the end date moves. But N121 **remains untraceable** (no
surviving source JSON), and its agreement with one particular window does not retire that provenance
problem. The paper should drop the "3× off" claim as unfounded **and** keep treating N121 as
unreproducible.

(The *t*-statistic also moves: 2.42 → 1.56, so 2886 is not significant at the primary window either.)

---

## 5. The 0056.TW narrative flips — and the flip is robust

**What the paper currently argues.** `body_v3.tex` §3.2 ("Sensitivity to 0056.TW inclusion") rests on
0056 having the *second*-highest γ (rendered 0.112), so that folding this diversified ETF into the
stock average biases the amplification ratio **downward** — i.e. *excluding* it is the conservative
choice.

**What the data says.** 0056's rolling γ is **0.222 (t = 2.95) — the highest of all twelve rows**,
above every individual stock *and above the TAIEX itself*. It ranks **first of twelve at every single
end date** in the sensitivity sweep (§6), so this is not an artifact of the window we happened to pick.

**The argument inverts.** Including 0056 *raises* the stock-side average (9-stock 0.032 → 10-security
0.051) and therefore *lowers* the ratio (6.12× → 3.85×). **Excluding 0056 is the choice that flatters
the headline ratio, not the one that guards against it.** §3.2 has to be rewritten. The exclusion
itself remains defensible — but only on the grounds the paper already states (0056 is a diversified
ETF, not an individual stock), **never** on a conservatism claim the data contradicts.

**A hypothesis, explicitly not tested here** (a direction for the main thread, not a finding): 0056 is a
high-dividend basket tilted to value/financial names. A diversified basket's returns are dominated by
the common factor, and the leverage effect is largely a *factor-level* phenomenon — which is the paper's
own diversification-amplification thesis. On that reading a 0056 γ above the single-stock average is
**consistent with** the paper's mechanism, and 0056 belongs with the index-like rows rather than the
stock cross-section. Establishing that needs a decomposition this experiment does not run.

---

## 6. The rolling estimates are imprecise, and the paper must say so

The three named end dates differ by only a few months, yet the 9-stock mean γ moves by ~40%. That had
to be characterised rather than hidden behind whichever end date we happened to choose. Sweeping the
common end monthly from 2025-01 to 2026-07 (figure: `end_date_sensitivity.png`):

| Quantity | Range across end dates |
|---|---|
| 9-stock mean γ | 0.022 – 0.062 |
| TWII rolling γ | 0.151 – 0.261 |
| Amplification ratio (9-stock) | **3.26× – 6.80×** |
| TWII γ median implied SE | **0.082** |
| 0056's rank among the 12 | **1st at every end date** |

**A claim we got backwards, twice.** The first draft argued the spread was "about one standard error
wide, so the estimates are imprecise". The second draft withdrew that as *un-rigorous*. **Both were
wrong, and in the same direction.** The overlap does not merely weaken the comparison — **it reverses
it.**

σ ≈ 0.08 is the marginal sampling SD of *one* estimate around the true γ. The spread is a dispersion of
*differences between estimates that share most of their data*. Under a constant-parameter null, two
windows of length *n* sharing a fraction ρ of their observations satisfy

> **SD(γ̂₁ − γ̂₂) ≈ σ·√(2(1−ρ))**

Adjacent end dates here have ρ ≈ 0.99, so the correct null SD is roughly **one seventh of σ** — not
√2 × σ. Scoring the observed movement against σ *understates* it several-fold. And the worst offender is
our own headline: **the 9-stock mean γ doubles (0.027 → 0.058) between two windows sharing 99% of their
observations.** No constant-parameter DGP produces that from sampling noise.

The two readings were also self-contradictory: §6 cannot say "just imprecision" twenty lines above §6.1
saying "an event-driven statistic". **Noise is not attributable to nameable sessions.** The fact that we
can point at 2025-04-07 is itself evidence against the noise reading.

**So the sweep is tested properly instead of narrated** (`inference.py` → `inference_results.json`
`.c_constant_gamma_null`): fit GJR to the full TWII sample, simulate paths in which γ is **constant by
construction**, run the *identical* 19-date rolling sweep on each, and ask how often the swept max−min
range is as large as the observed one. This handles the ~99% overlap **and** the max−min multiplicity
exactly, with no asymptotics. Result in §6.2 below.

**What this design can and cannot establish.** It *can* show the movement exceeds what a constant-γ
process produces, and trace it to specific sessions. It **cannot** separate (i) genuine time-variation in
γ from (ii) the GJR MLE's finite-sample sensitivity to a handful of influential negative returns. Both
imply the same policy, and we do not adjudicate between them.

**On the ratio.** The swept range 3.26×–6.80× is **a factor of 2.08 — the *first* significant digit is
not identified.** That the paper's rendered 5.0× "sits inside" that interval is not validation; so would
almost any number one might have written down. **Do not report a point ratio.** See §6.3 — the ratio is
worse than imprecise, it is ill-posed.

### 6.2 The movement is **not** sampling noise — tested, not asserted

Constant-γ parametric bootstrap, B = 999 (`inference_results.json` `.c_constant_gamma_null`):

| | |
|---|---|
| Observed sweep range (max − min TWII γ) | **0.1099** |
| Null distribution of that range, 95th pct | 0.0326 |
| Null 99th pct | 0.0413 |
| **p-value** | **0.0010** |

**Reject the constant-γ null.** The observed movement is more than three times the null's 95th
percentile. Whatever it is, it is not what a constant-parameter GJR process does. (It still does not
identify *which* of the two causes — genuine time-variation, or MLE sensitivity to a few influential
shocks — and we do not claim it does.)

### 6.3 The amplification ratio is **ill-posed** — do not report it

This is independent of the sweep, and it is the single biggest referee risk in the package.

The ratio is γ_TWII / γ̄_9stock. **Not one of the nine stock γ's is significant** (|t| = 0.27 … 1.56; 2412's
is negative), and **the numerator is not significant either** (t = 1.86). A ratio whose denominator's
confidence interval covers zero has an **unbounded Fieller confidence set**. The moving-block bootstrap
(B = 999, 252-session blocks, date blocks resampled *jointly* across all ten securities so their
cross-sectional dependence is preserved) confirms this is not a theoretical worry:

| Quantity | Bootstrap 95% CI |
|---|---|
| Denominator γ̄_9stock | **[−0.016, 0.130]** — **covers zero** |
| **Ratio** γ_TWII / γ̄_9stock | **[−26.2×, +33.6×]** (full range −2504× … +8205×) |

**The ratio is not a usable statistic.** Reporting "6.12×" — or the paper's "5.0×" — as a point estimate,
with the sweep range passed off as its uncertainty, would not survive review.

**What to report instead.** Two things, both robust:

| Statistic | Value | Inference |
|---|---|---|
| **Difference** D = γ_TWII − γ̄_9stock | **0.184** | 95% CI **[0.072, 0.298]**, **P(D ≤ 0) = 0.0000** |
| **Ordering**: index γ exceeds *every* stock's γ | **9 / 9** | sign test **p = 0.0020**; Wilcoxon **p = 0.0020** |

**The paper's diversification-amplification thesis survives — its quantification does not.** The index's
leverage effect really is larger than the individual stocks', robustly and significantly. It simply
cannot be expressed as a multiple. Say "the index γ exceeds every one of the nine constituents'
(sign test p = 0.002), by 0.18 [0.07, 0.30] in absolute terms" — and drop the "×".

*(Caveat on the block bootstrap: block resampling splices the GARCH recursion at block boundaries, which
attenuates measured persistence. A 252-session block leaves only ~8 boundaries in 2000 sessions, so the
distortion is small — but this is an approximate interval. The sign test is the assumption-light backstop
and it agrees.)*

### 6.4 Which observations actually drive it — **identified, not asserted**

An earlier draft attributed the movement to specific segments by comparing two windows — which cannot
work, because those windows differ at *both* ends (observations enter at the back **and** leave at the
front). The identified test holds one window fixed and **ablates** the candidate sessions from inside it
(`inference_results.json` `.b_event_ablation`):

| Ablation | Window | γ with | γ without | Δ |
|---|---|---|---|---|
| **3 sessions**: 2025-04-07…09 (tariff shock) | primary, 2000 obs | TWII 0.1975 | 0.1673 | **−0.030** |
| same 3 sessions | primary, 2000 obs | 9-stock mean 0.0323 | **0.0134** | **−0.019 (−58%)** |
| **1 session**: 2018-02-06 (VIXmageddon) | 2026-04-17 window | TWII 0.2650 | 0.2315 | **−0.034** |

**Three sessions out of two thousand carry more than half of the nine-stock leverage estimate.** One
single session moves the index's γ by 0.034. That is the mechanism behind §6.2's rejection, and it is
why the rolling block cannot carry a structural interpretation.

### Segment description (context for the above)

This is not random drift. It is a handful of extreme sessions moving in and out of an 8-year window
whose boundaries are set by the arbitrary date of the data pull:

- **2025-04 tariff shock enters** (between the 2025-03-31 and 2025-04-30 end dates): a **−10.20%
  limit-down TAIEX session on 2025-04-07**, plus −5.96% and −4.10% follow-through — the largest cluster
  of negative shocks in the sample. The 9-stock mean γ **more than doubles**: 0.027 → 0.058.
- **2018-Q1 spike leaves** (as the end moves 2026-04-17 → 2026-07-09, the window start slides past
  2018-02-06's −5.08% "VIXmageddon" session). Dropping a large negative shock lowers γ.
- **2026-Q2 enters**: volatile (1.86%/day) but **roughly symmetric** (skew ≈ 0; its biggest moves include
  +4.51%, +4.47%, +4.47% sessions). Volatility *not* driven by negative shocks **dilutes** the measured
  asymmetry.

**The rolling-w2000 last-window γ is an event-driven statistic, not a stable structural parameter.** That
is a reason to keep the **full-sample Bollerslev–Wooldridge spec as the paper's primary evidence** (as
`body_v3.tex` already does) and to carry the rolling block with an explicit imprecision caveat.

---

## 7. Data defects found (all inherited; none introduced here)

1. **2317.TW is corrupted around its 2018-10-18 capital reduction** (yfinance split factor 0.8). The
   close is **frozen at 85.125 for six consecutive sessions** (2018-10-18 … 10-25 — six spurious zero
   returns), then "catches up" with a **−10.49% move on 2018-10-26**, which is *beyond Taiwan's ±10%
   daily limit* and so cannot be a genuine close-to-close return. The block sits **inside** the rolling
   window, and the catch-up day is a large negative shock — exactly what γ loads on.
   - **Sensitivity (a clean ablation)**: excluding the block cuts 2317's γ by nearly two-thirds
     (**0.020 → 0.007**), but moves the 9-stock mean only 0.0323 → 0.0309 and the ratio 6.12× → 6.39×.
     **Conclusions unaffected; the displayed 2317 row is not.**
   - The ablation is applied *after* the window is cut, never before. Removing the rows from the series
     first would make the last-2000 slice reach ~7 sessions further back — into April 2018, right beside
     the 2018-Q1 volatility spike we independently know moves γ — confounding "removed the corrupt days"
     with "added days from a high-asymmetry period". (With the wrong ordering the same sensitivity
     reported 0.009 instead of 0.007, i.e. it understated the contamination.)
   - The primary estimate keeps the data as fetched, for consistency with the rest of the paper's data
     handling — the defect is present identically in the previous snapshots.
2. **The paper's canonical CSV has 10 duplicated date rows.**
   `paper/taiwan-vt/data/0050_tw_twii_..._2008-2026.csv` repeats 2026-05-04 … 2026-05-15 verbatim — an
   append that ran twice. This experiment does not read that file for estimation, so it is unaffected;
   but **any experiment that differences its `twii`/`spy`/`vix` columns without de-duplicating will
   inject spurious jump returns.** Flagged for the main thread; **not edited here** (outside a worktree
   agent's scope, and other experiments depend on the file).
3. **0050.TW's 4:1 split (2014-01-02)** leaves a spurious split-date return even under
   `auto_adjust=False` (log return −1.389). Excluded per the paper's own canonical rule. It falls outside
   every window used here, so it does not affect these estimates.

## 8. Also worth the main thread's attention

- **The table note's "Newey–West HAC" label is wrong.** `body_v3.tex` L196 describes the rolling-window
  *t*-statistics as Newey–West HAC. That is not what is computed — here or in K892. These are
  **Bollerslev–Wooldridge robust sandwich MLE** *t*-values (NW-HAC is not a standard estimator for GARCH
  MLE parameters). The note should be corrected; we report what we actually compute.
- **The Codex review gate is silently broken from this repo.** Two `codex exec` review calls, each given
  an explicit prompt naming these two files, **ignored the prompt entirely** and went off to review an
  unrelated FB-posting script instead. Root cause: `AGENTS.md` (which Codex auto-loads) tells the agent to
  *"claim a pending task from the task pool"*, so Codex abandons the prompt and does dispatcher work.
  **Any `codex exec` code review launched from this repo is liable to be hijacked the same way** — which
  matters, because Codex review is the gate in front of `knowledge.json` writes. Per the two-strikes rule
  this review was re-run on a different model (§9). Flagged for the main thread; `AGENTS.md` is outside a
  worktree agent's write scope.

---

## 9. Review — **CONDITIONAL_PASS**

Independent adversarial review by a fresh-context `feature-dev:code-reviewer` subagent (Codex hijacked —
see §8). Verdict: **CONDITIONAL_PASS** — *"the estimates are trustworthy; the conclusions drawn from them
are not."* It was right, and it caught two ship-blockers I had missed or got backwards:

1. **The "imprecise, not regime-unstable" reading was backwards**, and the overlap *reverses* rather than
   merely weakens the inference. → Tested properly (§6.2): **constant-γ null rejected, p = 0.001**.
2. **The amplification ratio is ill-posed**, not merely imprecise — its denominator is not
   distinguishable from zero. → Confirmed (§6.3): bootstrap ratio CI **[−26×, +34×]**. Replaced with the
   difference and the sign test.

It also caught that I had fixed the ablation ordering for 2317 but **not for the identical 0050 case**,
that the multistart compared candidates against a *non-converged* incumbent, and that my 2886
"vindication" (§4) was motivated reasoning. All fixed. Full findings and per-item disposition:
**`review_notes.md`**.

## 10. Honesty ledger

- **No lookahead, by construction.** γ is an in-sample descriptive MLE on the last 2000-observation
  window. No forecast, no OOS split, no train/test boundary, no signal — there is no channel through
  which future information could enter.
- **Seeded.** MLE is deterministic; `SEED = 20260713` seeds the perturbed restarts and both bootstraps.
- **"All fits converged, no restarts needed" is backed by a counter, not a spot check**:
  `fit_diagnostics` in the results JSON covers **all 276 fits** in the run (3 named variants + the
  ablation variant + every row of the 19-date sweep) — `max_restarts = 0`, `nonzero_convergence = 0`.
- **Calendar alignment is an asserted invariant, not an observation.** `run_variant()` **raises** if the
  12 rows do not share one `window_end`. It held across all 23 runs. (The 12 series do *not* share a
  trading calendar — the stocks' windows start 2018-04-18, the index/ETF rows 2018-04-19 — so this could
  silently regress without the assert.)
- **Offline reproducibility is proven, not asserted**: the estimation script runs to completion with all
  outbound socket connections blocked.
- **Nothing hand-edited.** Every number in both results JSONs is produced by the scripts from the
  committed snapshots.
- **Two claims were withdrawn after they were already written** (§6, §4). Both are recorded rather than
  quietly deleted, because a reader who saw the earlier version deserves to know which way the error ran.
- **Reproduce** (offline, reads only `data/`):
  ```
  uv run python experiments/paper2_taiwan_indiv_rolling_gamma/paper2_taiwan_indiv_rolling_gamma.py
  uv run python experiments/paper2_taiwan_indiv_rolling_gamma/inference.py
  ```
  To re-pull the snapshots (needs network): `... /fetch_snapshots.py`
- **Scope.** This experiment produces numbers and narrative implications only. It does **not** touch
  `paper/taiwan-vt/**`: the Table 2 rewrite, the §3.2 0056 rewrite, the ratio→difference change, and the
  table-note correction are main-thread work (CLAUDE.md paper narrative state machine).

## Files

| File | |
|---|---|
| `fetch_snapshots.py` | one-off yfinance pull → `data/` (+ regression check against the old snapshots, at the tolerance it claims) |
| `paper2_taiwan_indiv_rolling_gamma.py` | offline **estimation**: variants, sensitivities, figure |
| `inference.py` | offline **inference**: sign test, event ablation, constant-γ null, block bootstrap |
| `paper2_taiwan_indiv_rolling_gamma_results.json` | estimation results |
| `inference_results.json` | inference results — **read this before quoting any ratio** |
| `end_date_sensitivity.png` | end-date sensitivity figure (§6) |
| `data/` | committed offline snapshots + `MANIFEST.json` |
| `review_notes.md` | independent review verdict + per-finding disposition |
