# K1100h-v2 Self-Review (Pre-Codex)

**Date**: 2026-05-11
**Author**: Claude (主線程)
**Predecessor**: K1100h Phase 1 v1 — Codex primary-path FAIL (2 MAJOR + 2 MINOR)

## v1 Issues vs v2 Fixes

### MAJOR 1 — Bar aggregation endpoint mis-binning

**v1 problem**: 423/1138 day-sessions had **61 bars** instead of 60.

**Root cause**: `tick_df["ts"].dt.floor("5min")` puts the 13:45:00.000 closing-tick into its OWN bar (`bar_start=13:45`), creating a phantom 61-st bar (08:45, 08:50, …, 13:40, **13:45**) instead of the canonical 60 bars (08:45→13:40 starts; (13:40,13:45] is the last bin).

**v2 fix** (`k1100h_load_taifex.py` `build_5min_bars`):
```python
tick_df["bar_start"] = tick_df["ts"].dt.floor("5min")
day_close_ts = file_date.normalize() + pd.Timedelta(hours=13, minutes=45)
is_day_close_endpoint = (
    (tick_df["session"] == "day") & (tick_df["bar_start"] >= day_close_ts)
)
if is_day_close_endpoint.any():
    last_day_bar = day_close_ts - pd.Timedelta(minutes=5)
    tick_df.loc[is_day_close_endpoint, "bar_start"] = last_day_bar
```

**Why this rather than `pd.cut closed='right'`**: Right-closed binning would also collapse the 08:45:00 opening tick into the previous (08:40) bin. Day session window is exactly `[08:45, 13:45]` so we need **left-closed except at 13:45 endpoint**. Surgical mask is safer than wholesale binning convention switch.

**v2 validation**:
```
Day-session days total: 1138
Bar count distribution: {57: 49, 58: 7, 60: 1082}
Days >60 bars: 0
```
The 49+7 = 56 days with <60 bars are real TAIFEX half-day early-close events (not a bug; verified against TAIFEX calendar — early closes occur on某 holiday-eve days).

**Spot-check 2017-05-18**: was a 61-bar day in v1 → now 60 bars, day_rv_5min=1.9e-05 (vs v1 with 61 bars summed extra noise). Re-binning shrinks RV slightly (one fewer squared-return summand), which is the expected direction.

---

### MAJOR 2 — Roll/settlement handling on TX1.csv

**v1 problem**: K1100h loader reads TX1.csv (近月). On the **3rd Wednesday (settlement day)**, TX1 is the **expiring** contract — liquidity fragments to TX2 during the day, cash-settle flow contaminates intraday microstructure. v1 only filtered K1100g's `is_roll==True` (61 days = day AFTER settlement when most-volume switches), but did **NOT** drop the settlement day itself.

**v2 fix** (`k1100h.py` post-merge filter):
```python
df = df[df["is_roll"] == False].copy()       # contract-switch day (existing)
df = df[df["is_settlement"] == False].copy() # K1100h-v2 MAJOR 2: TX1 = expiring
```

`is_settlement` already exists in K1100g cache (`_is_third_wednesday`: weekday==2 & day in [15,21]). 60 settlement days expected over 2017-2021.

**Why drop both `is_roll` AND `is_settlement`**:
- `is_roll==True` (≈61 days): day AFTER settlement, contract_month switches in K1100g cache. K1100g_d5/d6 baselines drop these → K1100h must drop for parity.
- `is_settlement==True` (≈60 days): the settlement day itself. TX1 is expiring contract; intraday tick stream has anomalous volume profile + final-hour cash-settle flow. K1100g_d5/d6 do NOT explicitly drop these (they used TX with most-volume contract per day, so on settlement day they pick the front month which is fine), but K1100h's **TX1-only loader** REQUIRES dropping them.

**Asymmetry justification**: K1100g uses TX (all contracts) + most-volume picker → settlement-day contamination is naturally avoided by the picker switching on settlement day. K1100h's TX1 stream cannot replicate this without either (a) reading TX (whole) and re-implementing the picker, or (b) dropping the contaminated days. (b) is simpler and equivalent for daily-aggregate features.

**Sample-size impact**: 1082 → ~1022 rows after extra settlement drop (~5.5% loss). OOS test window n drops from 464 → ~440. Still ≥400 → DM-test power adequate.

---

### MINOR 1 — Big5 header/encoding validation

**v1 problem**: Hardcoded `encoding="big5"` with no fallback; no schema sanity check on column count.

**v2 fix** (`load_one_file`):
```python
for enc in ("big5", "cp950", "utf-8"):
    try:
        df = pd.read_csv(fn, encoding=enc, low_memory=False, na_values=["-"])
        break
    except UnicodeDecodeError:
        continue
if df is None: raise RuntimeError(...)
if df.shape[1] != len(COLS_RAW): raise RuntimeError(...)
```

Belt-and-suspenders: encoding fallback chain + schema column-count assert. If TAIFEX changes export format mid-history (which has happened — see 2014 schema change documented in `experiments/k1100g/k1100g.py:28`), v2 will fail loud rather than silently mis-parse.

Re-run confirmed: all 1223 TX1 files in 2017-2021 parsed without error.

---

### MINOR 2 — HAC lag schedule

**v1 problem**: `lag = int(np.floor(n ** (1 / 3)))` — fine for T>27 but produces lag=0 (degenerate to gamma_0-only) when T<27, and is not the canonical Newey-West automatic bandwidth.

**v2 fix** (`dm_test_hln`):
```python
lag = max(1, int(np.floor(4.0 * (n / 100.0) ** (2.0 / 9.0))))
```

This is the Newey & West (1994) automatic bandwidth selector, standard in DM/HLN literature. Hard floor of `lag=1` ensures kernel sum always includes at least γ_0 + 2*w*γ_1.

For our OOS test n≈440: v1 lag = floor(440^(1/3)) = floor(7.61) = **7**; v2 lag = floor(4*(4.4)^(2/9)) = floor(4*1.376) = **5**. Slightly tighter window → marginally smaller variance estimate → marginally larger |t|. Neither lag schedule is "wrong" but v2 matches academic convention.

---

## Lookahead Discipline (UNCHANGED from v1; re-affirmed)

- ✓ Multi-exog kernel (`_prg_variance_recursion_multi` line ~146) reads `exog_mat[t-1, :]` → enforced lag-1
- ✓ Loader does NOT pre-shift features (would compound to lag-2)
- ✓ Baseline M1 (no exog) uses identical kernel → identical r[t-1] structure
- ✓ Feature standardization (`standardize` in main) uses TRAIN-window only (`train_idx` mask)
- ✓ `np.random.seed(42)` + `RNG = np.random.default_rng(42)` + per-fit `local_rng = np.random.default_rng(SEED)` — all stochastic init reproducible

## Expected v2 Effect on Results

- **bar agg fix**: day_rv_5min and day_bipower_var on 423 days will be slightly smaller (one fewer squared-return summand). day_intraday_mom unchanged (uses open/close only). hod_rv_ratio recalibrates because numerator and denominator both shift by 1 bar.
- **settlement drop**: ~60 fewer rows in IS, ~25 fewer in OOS test window. v1's ~+2.85 DM-t for M2/M3 likely shifts (could go either way: settlement days are high-vol so dropping them changes both numerator and denominator of QLIKE).
- **HAC lag**: marginal; tighter NW lag → slightly larger |t-stat|.

**Most likely v2 verdict**: still BORDERLINE (sub-Harvey, secondary 5%). The Phase 1 hypothesis (intraday features improve daily PRG via DM) was already ~2.85 in v1 — fixes don't expect to push past 3.0. If v2 jumps to >3.0, that would be suspicious and warrant deeper Codex audit (since most fixes are conservative shrinkage of contaminated samples).

## Files Changed

- `experiments/k1100h/k1100h_load_taifex.py`: MAJOR 1 (bar agg) + MINOR 1 (encoding fallback + schema assert) + `Optional` import
- `experiments/k1100h/k1100h.py`: MAJOR 2 (settlement filter) + MINOR 2 (NW HAC lag)
- `experiments/k1100h/data/_taifex_5min_2017-2021.parquet`: REBUILT (3.6 MB)
- `experiments/k1100h/data/_taifex_daily_features_2017-2021.parquet`: REBUILT

## What I'd Want Codex to Check

1. Is the bar-agg fix's surgical mask logically equivalent to right-closed binning for the day-session endpoint? Any edge case I'm missing?
2. Is dropping `is_settlement` the right MAJOR 2 fix vs. re-implementing TX-with-volume-picker? Asymmetry vs K1100g_d5 is the concern.
3. NW lag formula — `floor(4*(T/100)^(2/9))` is Newey-West (1994); any reason to prefer alternatives like Andrews-Monahan?
4. Lookahead audit: walk through `_prg_variance_recursion_multi` with `exog_mat=mom_z` and confirm at t=k, only `mom_z[k-1]` (computed from day k-1's session, all realized before day k 08:45) enters the variance for day k.
5. Standardization: `standardize(rv5, train_idx)` uses train-mean/std but applied to BOTH train and test rows — is this leakage-clean? (My read: yes, because we standardize `x[full_array]` using only train statistics, so test rows' z-score uses train-window μ,σ which is the correct out-of-sample protocol.)
