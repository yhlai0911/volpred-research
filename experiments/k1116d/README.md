# K1116d: True ALFRED First-Release Vintage Retest of K1116c PIT NULL Verdict

**Status**: v2 FETCH-FIX APPLIED, vintage data gap-free; main 6×5 PIT battery still pending
**Date**: 2026-05-09 (v1) / 2026-05-11 (v2 chunk-boundary fix)
**Trigger**: K1116c (2026-04-13) flagged true ALFRED vintage as future work; FRED API key
became available 2026-05-10. Hook discipline: code written first → Codex review → main run.

## v2 (2026-05-11) — Chunk-boundary fix

Codex 2026-05-11 audit found 1 MAJOR: yearly chunking in `k1116d_fetch_alfred.py`
dropped 8 USEPU/WLEMU obs dates across 7 years (chunk boundaries `12-01..12-08`).
Root cause: yearly chunks set `realtime_end == obs_end`. For daily series with
D+1 publication delay, the boundary obs date X has `realtime_start = X+1` falling
outside the chunk's realtime window; next chunk starts at X+1 (obs_start) so X is
also missing there.

**Fix** (`fetch_chained_first_release`):
- Chunks shortened from yearly → **6-month obs windows** (8 -> 17 chunks per daily series)
- `realtime_end` extended **+14 days** beyond chunk's obs_end so D+1..D+14
  first releases of boundary obs are reachable
- Existing `seen_release_dates` set de-dups overlap region; same-DATE multiple-
  release rows kept earliest release (true first publication)

**Verification** (`data/gap_validation_v2.json`):
| Series | Before | After | Δ | Gap >5bd |
|---|---|---|---|---|
| USEPU | 3046 | **3056** | +10 | 0 |
| WLEMU | 3046 | **3056** | +10 | 0 |
| NFCI | 436 | 436 | 0 (unaffected, weekly) | 0 |
| ANFCI | 436 | 436 | 0 (unaffected, weekly) | 0 |
| STLFSI | 432 | 432 | 0 (3 chain-transition gaps, intrinsic) | 3 (intrinsic) |

December year-boundary spot check: all 9 years (2017-2025) now have full 12-01..12-10
weekday coverage for both USEPU and WLEMU.

## 1. Motivation

K1116c established the PIT-aligned alt-data NULL using **revision-corrected** fredgraph
values plus an explicit release-calendar PIT alignment. Its central argument was:

> Revision-corrected values are a smoother estimate of the latent state than vintage
> (first-release) values. If revision-corrected + PIT yields NULL, vintage + PIT also
> yields NULL — vintage is noisier and noise cannot reveal hidden signal.

**Residual concern**: this is a methodological argument, not an empirical demonstration.
A reviewer can validly object: "Run the test on real vintage data anyway." K1116d
removes that objection.

## 2. What changed since K1116c

| Item | K1116c (2026-04-13) | K1116d (2026-05-09) |
|------|---------------------|---------------------|
| Vintage data access | ALFRED CSV behind Akamai; no FRED API key | **FRED API key in `.env.local`** |
| Vintage method | None (fallback to fredgraph revised) | **FRED API `output_type=4`** — first-release per obs date |
| STLFSI series | STLFSI4 only (revised backfill 2018-2022) | **Chained STLFSI → STLFSI2 → STLFSI3 → STLFSI4** to match what was actually published at each release date |
| Compare scope | 6 lag/PIT variants × 5 specs (revised only) | Same 6×5 battery, run twice — once on vintage, once on revised — direct in-run comparison |

## 3. Vintage data audit

### 3.1 First-release coverage (per fetch_log.json)

| Indicator | Vintage rows | PIT weekly rows | Source breakdown |
|-----------|-------------:|----------------:|------------------|
| USEPU | 3046 | 439 | USEPUINDXD daily |
| WLEMU | 3046 | 439 | WLEMUINDXD daily |
| NFCI | 436 | 437 | NFCI weekly |
| ANFCI | 436 | 437 | ANFCI weekly |
| STLFSI | 432 | 437 | STLFSI(120) → STLFSI2(94) → STLFSI3(42) → STLFSI4(176) |

The STLFSI chain matters most. K1116c used STLFSI4 alone — but STLFSI4 only began
publishing 2022-11-17. Pre-2022 values in K1116c's STLFSI4 panel were **revision
backfill** (computed retroactively after STLFSI4 launched). True vintage requires
chaining STLFSI / STLFSI2 / STLFSI3 / STLFSI4 in sequence.

### 3.2 API mechanics

- `output_type=4` returns one observation per `(date, first realtime_start)` pair.
- Daily series (USEPU, WLEMU) chunked yearly to fit the FRED API 1000-vintage-per-call
  cap (8.4-yr window has 2056+ vintages otherwise).
- Weekly series (NFCI, ANFCI) fit in one call.
- STLFSI chain: each predecessor queried in its active window with a small overlap; at
  the chain transition the earliest realtime_start wins (by `drop_duplicates(subset=DATE,
  keep="first")` after sort by RELEASE_DATE).

### 3.3 Network incident (2026-05-10 fetch run)

WLEMU initial fetch hit transient DNS failure (`nodename nor servname provided`).
Fetch script is now idempotent: cached files skipped on re-run. WLEMU + revised
snapshots fetched on second pass. All 5 indicators have complete vintage + PIT + revised
snapshot CSVs in `data/`.

## 4. Design

### 4.1 Two cycles in one run

The same K1116c 6-variant × 5-spec battery is run **twice** within `k1116d.py`:

1. **Vintage cycle** — `weekly_mean` and `pit` panels built from
   `*_vintage_with_release_date.csv`. Values are first-release.
2. **Revised cycle** — same panels built from `*_revised_snapshot.csv`. Values are
   current revision-corrected. Release-date offsets (BDay+1 daily, BDay+3 NFCI/ANFCI,
   BDay+4 STLFSI) reproduced exactly as K1116c.

This puts vintage and revised on **identical methodology** so the verdict diff isolates
the data-vintage effect.

### 4.2 6 lag/PIT variants (identical to K1116c)

| Variant | USEPU/WLEMU lag | NFCI/ANFCI/STLFSI lag | Backbone |
|---------|-----------------|----------------------|----------|
| `orig_shift1` | shift(1) | shift(1) | weekly_mean |
| `corrected_shift2` | shift(1) | shift(2) | weekly_mean |
| `conservative_shift2` | shift(2) | shift(2) | weekly_mean |
| `pit_shift0` | shift(0) | shift(0) | pit |
| `pit_shift1` | shift(1) | shift(1) | pit |
| `multi_lag_3` | shift(3) | shift(3) | weekly_mean |

### 4.3 5 model specs (identical to K1116/K1116c)

| Spec | Regressors |
|------|------------|
| M1 base | AR(1) only |
| M2 vix | AR(1) + VIX (baseline) |
| M3 epu | AR(1) + USEPU + WLEMU |
| M4 finstress | AR(1) + NFCI + ANFCI + STLFSI |
| M5 all | AR(1) + VIX + 5 alt-data |

### 4.4 Lag audit (lookahead protection)

| Component | Lag | Where applied |
|-----------|-----|---------------|
| AR(1) regressor | `rv.shift(1)` | `make_X` line `X["y_lag1"] = df_sub["rv"].shift(1)` |
| VIX baseline | `vix_mean.shift(1)` | `make_X` (matches K1116c) |
| Alt-data signals | per-variant | `build_variant_panel` `base[c].shift(lags[c])` |
| PIT panel | release-date enforced | fetch script `RELEASE_DATE <= F` |

Bootstrap and any random ops use `seed=42`.

### 4.5 Statistical battery

- QLIKE: `log(pred) + actual/pred` (Patton 2011)
- DM-HLN h=1 (Harvey, Leybourne, Newbold 1997)
- Significance threshold: **Harvey (2016) |t| > 3.0** (multiple-testing corrected)
- Bootstrap 95% CI with stationary bootstrap, 1000 reps, seed=42, block ≈ √n
- Cross-variant DM (corrected_shift2 vs pit_shift0 same spec) replicated per K1116c

## 5. Pre-registered hypotheses

| Hypothesis | Description | Pre-registered prediction |
|------------|-------------|---------------------------|
| H1 (vintage rescues) | Vintage data unlocks alt-data signal | **Unlikely** — vintage noisier |
| H2 (NULL holds) | Vintage cycle still NULL across 6×5 cells | **Most likely** |
| H3 (partial) | Some indicator passes under vintage | Unlikely; if observed, isolate |

**90% bug check**: if any vintage cell shows DM |t| > 5 vs VIX, treat as bug suspect
first. Vintage cannot dominate revised by a wide margin; that would imply revision
smoothing destroyed signal — physically dubious for a Fed-published macro indicator.

## 6. Files (so far)

- `k1116d_fetch_alfred.py` — true vintage fetch via FRED API output_type=4
- `k1116d.py` — main 6×5 battery, two cycles (vintage + revised)
- `data/<alias>_vintage_with_release_date.csv` — first-release vintage panels
- `data/<alias>_weekly_pit.csv` — PIT-aligned weekly panels (vintage)
- `data/<alias>_revised_snapshot.csv` — fredgraph current revised
- `data/fetch_log.json` — fetch audit + chain breakdown

## 7. Results (2026-05-11 main run, post v2 fetch fix)

**Master verdict**: `H2_ROBUST_NULL_VINTAGE_CONFIRMED`
- Vintage cycle: 0/24 challenger cells reach Harvey |t|>3 — all DM t-stats negative vs M2_vix
- Revised cycle: 0/24 cells pass — replicates K1116c
- Vintage-vs-revised PIT correlations: USEPU 0.77, WLEMU 0.81, NFCI 0.83, ANFCI 0.83, STLFSI 0.41

### Vintage DM t-stats (vs M2_vix baseline)
| Variant | base | epu | finstress | all |
|---|---|---|---|---|
| orig_shift1 | -3.021 | -2.218 | -2.966 | -4.567 |
| corrected_shift2 | -3.021 | -2.218 | -3.081 | -4.465 |
| conservative_shift2 | -3.021 | -2.015 | -3.081 | -4.297 |
| pit_shift0 | -3.021 | -1.906 | -2.964 | -3.872 |
| pit_shift1 | -3.021 | -3.267 | -3.081 | -5.213 |
| multi_lag_3 | -3.021 | -2.070 | -3.120 | -3.606 |

All cells negative; the largest negative (`pit_shift1` × all = -5.21) is the strongest evidence
that adding alt-data on top of VIX **hurts** the model. Bootstrap CIs (n_boot=1000, seed=42)
in `k1116d_results.json`.

### Sensitivity: drop STLFSI (Codex MINOR)
Codex 2026-05-11 review CONDITIONAL PASS flagged that the STLFSI vintage chain
(STLFSI→STLFSI2→STLFSI3→STLFSI4) and the revised STLFSI4 fredgraph backfill are not
a pure same-series revision comparator (corr=0.41). `k1116d_sensitivity_no_stlfsi.py`
re-runs finstress + all without STLFSI signal:
- vintage no_stlfsi: **H2_ROBUST_NULL**, 0 passing
- revised no_stlfsi: **H2_ROBUST_NULL**, 0 passing

Verdict robust to STLFSI exclusion → chain comparator concern does not drive the NULL.

### Codex review summary
- v2 fetch fix: **PASS** (2 MINOR addressed)
- Main 6×5 battery: **CONDITIONAL PASS** (1 MINOR — STLFSI comparator caveat — addressed by sensitivity)

## 8. Paper 4 implications

K1116c's "noisier vintage cannot reveal hidden signal" upper-bound argument is now
**empirically demonstrated**, not just methodological. The Paper 4 alt-data NULL stands:
EPU + financial-stress indices add no incremental value over VIX for SPY weekly volatility,
across 6 lag/PIT conventions × 5 specs × 2 data backbones (vintage + revised) × STLFSI on/off.

## 9. Limitations

- IS/OOS windows fixed at 2018-2022 / 2023-2026; no rolling re-estimation.
- Asset is SPY; the NULL may be index-specific (cf. K1118/K1121 cross-asset).
- STLFSI vintage uses predecessor chain; the underlying methodology shifted across
  STLFSI/2/3/4 (Brave-Butters smoothing changes), so STLFSI vintage values are not
  identical-construct across the chain. This is documented as a caveat, mitigated by
  the no_STLFSI sensitivity above.
- Bootstrap CI uses stationary bootstrap with seed=42; results sensitive to block-length
  choice not formally tested (but H2 is direction-of-effect, not boundary case).

## 8. Scope guardrails

- All outputs under `experiments/k1116d/` (worktree rule).
- **No** modifications to `experiments/k1116c/*` or `storage/memory/*` (per task brief).
- **No** feed article — experiment-only; article published separately if results merit.
- API failures fall back loudly with verdict label; no silent "best effort" pass-through.

## 9. References

- Baker, Bloom, Davis (2016) QJE — EPU index
- Brave & Butters (2011) Chicago Fed EP Q1 — NFCI publication schedule
- Kliesen & Smith (2010) STL Fed Synopses — STLFSI
- Croushore & Stark (2001) J Econometrics — vintage data importance
- Patton (2011) JoE — QLIKE proxy-robust loss
- Harvey, Leybourne, Newbold (1997) IJF — HLN DM correction
- Harvey (2016) RFS — |t| > 3 multiple-testing threshold
- K1116, K1116b, K1116c, K1118, K1121 — prior alt-data NULL chain
- Error log E062 (2026-04-13) — FRED publication-delay bug

## 10. Worktree notes

- All files within `experiments/k1116d/`.
- No modifications to shared state (`storage/memory/*`, `feed.json`, paper body).
- Fetch script is **idempotent** — re-runs skip cached files. Safe to re-execute.
- Main script not yet executed — awaits Codex review per hook discipline.
