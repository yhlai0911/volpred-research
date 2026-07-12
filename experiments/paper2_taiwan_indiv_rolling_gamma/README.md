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
| Amplification ratio (9-stock) | **6.12×** |
| Amplification ratio (10-security) | 3.85× |

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

### A correction the paper owes itself

`body_v3.tex` L155–181 currently self-reports: *"2886 legacy 0.179 → reproducible 0.054 (3× off)"*.

**That accusation was itself an artifact of the stale window.** On the correct 2026 window, Mega
Financial's γ is **0.170** — close to the legacy 0.179, not 3× away from it. The 0.054 came from a
window that ended in January 2025. The paper currently accuses itself of a discrepancy that does not
exist at the right sample, and the provenance comment must be corrected along with the numbers.

(The *t*-statistic does move: 2.42 → 1.56. 2886 loses significance; its point estimate stands.)

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

**Interpretation — and a claim we withdrew.** The first draft of this README argued that because the
TWII γ spread across end dates (~0.11) is about the size of its own standard error (~0.08), the
estimates are "imprecise rather than regime-unstable". **That inference is not valid and is withdrawn.**
Consecutive end dates share ~97% of their observations, so their sampling errors are strongly
*positively* correlated: the standard error of the *difference* between two overlapping estimates is far
smaller than √2 × SE. Two such estimates can therefore be significantly different from each other even
though their individual confidence intervals overlap almost entirely. Comparing a spread of dependent
point estimates against marginal standard errors is not a test of anything, and the sweep is not a
sampling distribution.

What can be said **without** that machinery:

1. **Each individual estimate is imprecise on its own terms.** TWII's rolling γ at the primary window is
   0.198 with **t = 1.86 — not significant at 5%**. Its 95% CI is roughly [−0.01, 0.41], which contains
   every other end date's point estimate *and* contains the paper's rendered 0.272. The data do not
   reject the legacy value; they simply cannot pin it down.
2. **The estimates depend materially on the terminal date**, and the driver is identifiable (below):
   specific extreme sessions entering and leaving the window.
3. Therefore **no single end date's point estimate should be reported as a sharp structural constant.**
   The rendered 5.0× ratio sits inside the swept interval, so the ratio's **order of magnitude survives**
   — but its second digit is not identified.

**What would settle whether the movement is *real*** (i.e. genuine parameter instability rather than
noise): a formal parameter-stability test on the GJR coefficients (Nyblom / CUSUM), or a block bootstrap
over the union sample that respects the overlap. **This experiment does not run either**, so it makes no
claim about structural stability in the statistical sense — only the descriptive claim that the reported
number moves with an arbitrary choice, which is enough to require the caveat in the paper.

### Which observations actually drive it

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

## 9. Review

Independent adversarial review by a fresh-context `feature-dev:code-reviewer` subagent (Codex hijacked —
see §8). Verdict and the disposition of every finding: **`review_notes.md`**.

## 10. Honesty ledger

- **No lookahead, by construction.** γ is an in-sample descriptive MLE on the last 2000-observation
  window. No forecast, no OOS split, no train/test boundary, no signal — there is no channel through
  which future information could enter.
- **Seeded.** The MLE is deterministic; `SEED = 20260713` is used only for perturbed restarts on
  non-convergence. **No restart was needed** — all fits converged first try.
- **Nothing hand-edited.** Every number in the results JSON is produced by the script from the committed
  snapshots.
- **Reproduce** (offline, reads only `data/`):
  `uv run python experiments/paper2_taiwan_indiv_rolling_gamma/paper2_taiwan_indiv_rolling_gamma.py`
  To re-pull the snapshots (needs network):
  `uv run python experiments/paper2_taiwan_indiv_rolling_gamma/fetch_snapshots.py`
- **Scope.** This experiment produces numbers and narrative implications only. It does **not** touch
  `paper/taiwan-vt/**`: the Table 2 rewrite, the §3.2 0056 rewrite, and the table-note correction are
  main-thread work (CLAUDE.md paper narrative state machine).

## Files

| File | |
|---|---|
| `fetch_snapshots.py` | one-off yfinance pull → `data/` (+ regression check against the old snapshots) |
| `paper2_taiwan_indiv_rolling_gamma.py` | offline estimation: all variants, sensitivities, figure |
| `paper2_taiwan_indiv_rolling_gamma_results.json` | all results |
| `end_date_sensitivity.png` | end-date sensitivity figure (§6) |
| `data/` | committed offline snapshots + `MANIFEST.json` |
| `review_notes.md` | independent review verdict + disposition |
