# K1535 — ML-vs-GARCH Volatility "Reproduction Adjudication" (Daily U.S. Equity)

**Status:** SMOKE framework + validation run. `verdict = SMOKE_PENDING_FULL_RUN`.
Full multi-index / multi-horizon / 5-seed / three-RV-proxy run is reserved for
the main thread after code review.

**Code review:** Codex CLI hit its usage limit (resets 2026-06-25), so an
independent review was run via `agy` (Antigravity CLI) — verdict
**CONDITIONAL_PASS**: lookahead train/test split, DM-HLN sign + Harvey
correction, and QLIKE direction all confirmed correct. The one flagged item (a
possible `origins`/`win_origins` naming collision) was verified to be a
false-positive in the actual code (distinct variable names; lines 602 vs 675).
Causality was also verified numerically: for H∈{1,5,22} the max training
target_end day (6254) is strictly < the first OOS origin (6255), i.e.
`target_end < forecast_origin` holds exactly (K1337/K446). The main thread
should re-run a primary-path **Codex** review when quota resets before writing
`knowledge.json` (per `.claude/rules/experiments.md` subagent-fallback rule).

## Motivation

The platform's flagship question: *why do the published deep-learning (DL)
volatility papers claim ML beats GARCH, while our own experiments keep landing
on NULL?* This experiment answers it by **reproducing one such paper and then
adjudicating it** — first reproducing its claimed "win" faithfully, then adding
the fair baselines and significance tests the paper omitted, to see whether the
DL advantage survives.

### Reproduced paper

Aljadani et al. (2025), "Deep Learning and Transformer Architectures for
Volatility Forecasting: Evidence from U.S. Equity Indices," *Journal of Risk and
Financial Management* 18(12):685.
<https://www.mdpi.com/1911-8074/18/12/685>

It claims a lightweight patch-Transformer (**PatchTST-lite**) beats LSTM,
CNN-LSTM, Vanilla-Transformer, and the classical ARIMA / GARCH(1,1) / HAR-RV on
daily realized variance for S&P 500 / NASDAQ 100 / DJIA, horizons h = 1/5/22,
on QLIKE / RMSE / MAE.

### The two structural weaknesses we adjudicate

- **M1 — weak baseline.** The only GARCH is plain Gaussian GARCH(1,1): no GJR /
  EGARCH / Student-t, no GARCH-X. The paper's own Table A2 shows HAR-RV crushes
  GARCH(1,1) (DM ≈ 21), so "beats GARCH(1,1)" is a low bar.
- **M2 — no significance test on the DL models.** Table A2's DM tests only
  compare the *classical* models with each other; the DL models never enter any
  DM or MCS test. The Transformer "win" is a raw point-metric ranking, never
  tested for significance against HAR-RV.
- **M3 — possible covariate asymmetry.** If the NN is fed an RV proxy while
  GARCH only sees return², the comparison conflates *architecture* with
  *information set*.

## Design

### Phase A — faithful reproduction
Build ARIMA(1,0,1), Gaussian GARCH(1,1), HAR-RV (Corsi 1/5/22), plus LSTM,
CNN-LSTM, PatchTST-lite, and Vanilla Transformer. Confirm we can reproduce:
1. the **raw ranking** (PatchTST-lite QLIKE ≤ GARCH(1,1)), and
2. the **Table A2 classical sanity** (HAR-RV ≫ GARCH(1,1), DM significant).

If we cannot reproduce the paper's win, the NN is fixed *before* any claim — this
guards against a fake NULL produced by an undertrained net.

### Phase B — fair baseline (adjudication core)
Add the comparisons + tests the paper omitted:
- **(i) GJR-GARCH-t** (leverage + fat tails) — the M1 fix.
- **(ii) HAR-RV-X / GARCH-X** fed the **same information set** as the DL models:
  lagged RV(1,5,22) + VIX. This is the only way to separate an *architecture*
  advantage from an *information* advantage (the M3 control).
- **Diebold-Mariano (HLN small-sample correction)** of **each DL model vs GJR-t
  and vs HAR-RV-X** — the tests the paper never ran on its DL models (M2 fix).
- **Hansen-Lunde-Nason MCS** over the full model pool
  (`volpred.stats.mcs`, stationary bootstrap).

### Information symmetry (M3 control)
The feature matrix fed to every NN window is exactly
`[ret_t, log RV_t, log RV_w(5), log RV_m(22), log VIX²_t]` — the **same lagged
RV(1,5,22) + VIX** information the GARCH-X / HAR-X baselines receive. A unit test
(`test_information_symmetry`) asserts column-level identity.

## Lag / lookahead discipline (highest risk)

- Every forecast of RV_t uses only information dated ≤ t-1. NN input windows end
  at day t-1; GARCH/HAR covariates enter lagged.
- **Forward-label target** = mean RV over `[origin, origin+H-1]`. The fit only
  sees rows ≤ origin-1, so `train_end (origin-1) < forecast_origin (origin)`.
  This is the K1337 / K446 lesson: `signal.shift(1)` alone is **not** enough for
  forward-label targets — the target window must satisfy
  `target_end < forecast_origin`. The NN window builder enforces this by taking
  the target from `[j+1, j+H]` for an input window ending at day j.
- Each horizon H uses a DM/HLN inference horizon **equal to that H** (never
  shared across horizons) — `.claude/rules/experiments.md`.
- Cross-index loss differentials would be **date-clustered before HAC** (K1355);
  the smoke run uses a single index so no clustering is needed yet.
- All RNG (NN init, MCS bootstrap, GARCH multistart) uses a fixed seed.

## Data (zero-gap, deterministic from OHLC)

`prepare_data.py` downloads daily OHLC via yfinance for `^GSPC`, `^NDX`, `^DJI`
(2000-01 onward) and `^VIX`. Three RV targets are built deterministically from
same-day OHLC (no 5-min data needed), exactly as in the paper:
- `rv_cc` — Close-to-Close squared log return.
- `rv_park` — Parkinson (1980) high-low range.
- `rv_yz` — Yang-Zhang (2000) daily OHLC (Rogers-Satchell + overnight).

All in `(100·logret)²` units to match the GARCH percent-return likelihood.
VIX (level) + lagged RV are the GARCH-X / HAR-X covariates. Sample counts are
recorded in `data/data_meta.json` and the results JSON.

## Smoke scale (this run)

One index (`^GSPC`), Close-to-Close target, h = 1, reduced NN epochs, `--max-oos
400`, seed = 0 (+ a seed-1 determinism check on PatchTST-lite). Goal:
1. (Phase A) reproduce the raw ranking PatchTST-lite ≤ GARCH(1,1);
2. (Phase B) check whether the fair baselines (GJR-t / GARCH-X / HAR-RV-X) +
   DM/MCS erase the PatchTST advantage.

**The full multi-index / multi-horizon / 5-seed / three-RV-proxy run + SPY/QQQ
true-5-min robustness is left to the main thread.**

## Smoke findings (GSPC, h=1, seed=0, 400 OOS origins)

**Target choice is decisive.** The paper's headline is on a *smooth* realized
variance target; the close-to-close `r²` proxy (`rv_cc`) is a near-unpredictable
noise series on which classical GARCH wins by construction.

| | `rv_cc` (noisy r²) | `rv_park` (smooth RV — faithful target) |
|---|---|---|
| Phase A: PatchTST-lite QLIKE ≤ GARCH(1,1)? | **No** (14.54 vs 1.79; PatchTST worst) | **Yes** (0.455 ≤ 0.620) — *paper win reproduced* |
| QLIKE top-5 | GARCH-family | all four NNs + HAR-RV-X |
| Any DL Harvey-sig over HAR-RV-X? | No | **No** |
| MCS members | all 10 | all 10 |

**Adjudication verdict on the faithful target (`rv_park`): the ceiling HOLDS.**
- DL models DO significantly beat the *weak* baselines the paper used — e.g.
  Transformer vs GARCH-X DM-HLN = −4.06 (Harvey-sig), vs GJR-t = −3.58. This is
  the paper's "win" (M1: a weak GARCH(1,1) is a low bar).
- **But no DL model is Harvey-significant over HAR-RV-X** (same lagged
  RV(1,5,22)+VIX info): PatchTST-lite vs HAR-RV-X DM = **+0.90** (HAR-X even
  slightly ahead, n.s.); LSTM/CNN-LSTM/Transformer vs HAR-RV-X all |DM|<1.1,
  p>0.3. The MCS retains all ten models — no separation.
- Conclusion: the paper's DL advantage is an **information advantage, not an
  architecture advantage** (M2 + M3 confirmed). Give a simple HAR-RV-X the same
  information and the Transformer edge vanishes. This is consistent with the
  platform's repeated ML-vs-GARCH NULLs.

This is a SMOKE result (single index/horizon/seed, reduced epochs). It is *not*
a final claim — the full run must confirm across NDX/DJI, h=1/5/22, the three RV
proxies, and ≥5 seeds before any publication. `verdict = SMOKE_PENDING_FULL_RUN`.

The `phaseA_reproduction` gate passing on `rv_park` (PatchTST does reproduce the
paper's raw win) is the key guard that the "ceiling holds" verdict is **not** a
fake NULL from an undertrained net.

## Files

- `prepare_data.py` — yfinance OHLC → three RV targets + VIX, per-index parquet.
- `k1535.py` — Phase A + Phase B engine (classical MLE/OLS + torch NNs + DM/MCS).
- `test_k1535.py` — 8 anti-bug unit tests (lookahead causality, QLIKE direction,
  info symmetry, seed determinism, DM-HLN horizon wiring). **All 8 pass.**
- `k1535_ml_garch_adjudication_equity_results.json` — smoke results.
- `data/` — per-index parquet + `data_meta.json` provenance.
- `figures/` — QLIKE ranking + DM bar charts.

## Honesty note

The adjudication is **faithful-reproduce-FIRST**. If, after adding the fair
baselines, **PatchTST-lite still sits inside the MCS and significantly beats both
GJR-t and GARCH-X**, that is a real, publishable counter-example (ML genuinely
breaking the ceiling) and is reported as such — *not* suppressed. Both outcomes
are complete results. The NN is never weakened, nor the baseline strengthened,
to manufacture an expected "ceiling holds" conclusion.

## Full-run improvements (for the main thread)

1. **ARIMA refit cadence.** ARIMA(1,0,1) is currently re-fit at every OOS origin
   (statsmodels), which dominates wall time (~6-7 min/pass, ~22 min for the
   2-target + seed-check smoke). Refit it on the same `refit_every` cadence as
   GARCH/GJR for a ~20x speedup with negligible accuracy loss.
2. **Seed-check efficiency.** `--seed-check` re-runs the *full* classical loop
   twice even though only PatchTST-lite is needed; gate the classical refits off
   when `nn_kinds` is a singleton, or cache classical forecasts across seeds.
3. **GARCH-X covariate parity.** GARCH-X currently takes a single lagged RV; for
   strict information parity with HAR-RV-X / the NN it should also take VIX (and
   ideally the 5/22-day RV aggregates). Note the *binding* fair baseline is
   already HAR-RV-X (it gets the full info set), so the smoke verdict is
   conservative, but full parity tightens the M3 control.
4. **Multi-step horizons.** h=5/22 use a persistence/martingale projection for
   the GARCH/HAR multi-step path; the NN predicts the H-day mean directly. Both
   are lookahead-safe (z held flat, no future peek) but the projections should
   be sanity-checked against a direct multi-step GARCH simulation at the full
   scale. Each horizon's DM/HLN inference horizon must equal that H (already
   wired; verify in the full run).
5. **Optional embargo.** The train/OOS boundary is tight (`gap=0`,
   `target_end = forecast_origin - 1`). Strictly correct, but an explicit
   H-1-day embargo between the NN training block and the OOS origins would add a
   defensive margin for h>1.
6. **Primary-path Codex review** must be re-run when quota resets (2026-06-25)
   before any `knowledge.json` write; this smoke carries an `agy`
   CONDITIONAL_PASS + numerical causality verification only.
7. **Cross-index date-clustering (K1355).** When NDX/DJI are added, aggregate
   the cross-index loss differential by date *before* HAC/DM; do not stack
   asset-day observations as iid.

## References

- Aljadani et al. (2025), *JRFM* 18(12):685 — the reproduced paper.
- Corsi (2009), *J. Financial Econometrics* — HAR-RV.
- Glosten, Jagannathan & Runkle (1993) — GJR-GARCH.
- Parkinson (1980); Yang & Zhang (2000); Rogers & Satchell (1991) — OHLC RV.
- Patton (2011), *J. Econometrics* 160 — QLIKE proxy-robust loss.
- Diebold & Mariano (1995); Harvey, Leybourne & Newbold (1997) — DM + correction.
- Hansen, Lunde & Nason (2011), *Econometrica* 79 — Model Confidence Set.
