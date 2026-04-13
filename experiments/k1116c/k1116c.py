"""
K1116c: Vintage-approximation via point-in-time release-calendar alignment for alt-data.

Goal: Address the residual concern that K1116/K1116b's publication-delay shift(2) is a
calendar-week approximation, not a true vintage-data fix. Real ALFRED vintage data is
inaccessible without a FRED API key (ALFRED download endpoint behind Akamai bot protection).

Approach: Use fredgraph revision-corrected values + release-calendar point-in-time (PIT)
alignment — at each week-ending Friday F, only use observations whose RELEASE_DATE <= F.
Compare against:
  - K1116 original (weekly mean + shift(1) week)
  - K1116b corrected (shift(2) for weekly-cadence FRED series)
  - K1116c PIT (explicit release-date-based)
  - Multi-lag sensitivity: shift(1)/shift(2)/shift(3) at weekly frequency

Scientific argument for valid fallback:
  Revision-corrected data is generally a SMOOTHER estimate of the underlying state than
  first-release (vintage) data. If revision-corrected + proper release-lag still yields
  NULL for alt-data vol prediction, then vintage (noisier) data would also yield NULL.
  The revision-corrected case provides an UPPER BOUND on vintage signal quality.
  Conversely, if revision-corrected PIT shows PASS, a true vintage test would be needed.

Hypotheses:
  H1 (vintage fix unlocks signal): Some alt-data with PIT alignment shows DM |t|>3 vs baseline.
  H2 (robust NULL): All alt-data remains NULL under all lag/PIT variants.
  H3 (partial): Specific indicators (e.g., NFCI) pass under PIT but others NULL.

Data: SPY weekly RV 2018-2026 + 5 FRED indicators (USEPU, WLEMU, NFCI, ANFCI, STLFSI).
IS: 2018-2022, OOS: 2023-2026. Signal lagged per variant.

References:
  - Baker, Bloom, Davis (2016) QJE — EPU
  - Brave, Butters (2011) Fed Letter 286 — NFCI publication schedule (Wed 10:30 CT)
  - Kliesen, Smith (2010) — STLFSI
  - Patton (2011) JoE — QLIKE proxy-robust loss
  - Harvey, Leybourne, Newbold (1997) IJF — HLN DM correction
  - Croushore & Stark (2001) J Econometrics — real-time vintage data importance
  - K1116, K1116b (prior experiments)

Author: Yi-Hao Lai + VolPred Research System
Date: 2026-04-13
"""
from __future__ import annotations

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

np.random.seed(42)

HERE = Path(__file__).parent
DATA_DIR = HERE / "data"
OUT_DIR = HERE

RESULTS = {
    "experiment_id": "K1116c",
    "title": "Vintage-approximation via point-in-time release-calendar alignment for alt-data",
    "started_utc": datetime.utcnow().isoformat() + "Z",
    "data_source": "FRED fredgraph (revision-corrected) + local K1121/storage caches + release-calendar",
    "baseline_experiments": ["K1116", "K1116b"],
    "references": [
        "Baker, Bloom, Davis (2016) QJE - EPU index",
        "Brave, Butters (2011) Fed Letter 286 - NFCI",
        "Kliesen, Smith (2010) - STLFSI",
        "Croushore & Stark (2001) J Econometrics - vintage data importance",
        "Patton (2011) JoE - QLIKE proxy-robust loss",
        "Harvey, Leybourne, Newbold (1997) IJF - HLN DM correction",
    ],
    "vintage_access_note": (
        "ALFRED CSV endpoint is behind Akamai bot protection; fredapi requires FRED_API_KEY "
        "which is unavailable in this environment. K1116c uses fredgraph (revision-corrected) "
        "+ release-calendar PIT alignment as a valid approximation. Rationale: revision-corrected "
        "values are a SMOOTHER estimate of the state than vintage; if revision + PIT gives NULL, "
        "vintage + PIT would also give NULL (H2 robust)."
    ),
}


def log(msg: str) -> None:
    ts = datetime.utcnow().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# -------------------------------------------------------------------
# Data loading
# -------------------------------------------------------------------
def fetch_spy_vix_weekly() -> pd.DataFrame:
    import yfinance as yf

    log("Fetching SPY + VIX daily 2018-2026...")
    spy = yf.download("SPY", start="2018-01-01", end="2026-04-13", progress=False, auto_adjust=True)
    vix = yf.download("^VIX", start="2018-01-01", end="2026-04-13", progress=False, auto_adjust=False)

    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    spy = spy[["Close"]].copy()
    spy["r"] = np.log(spy["Close"]).diff()

    spy["week"] = spy.index.to_period("W-FRI").to_timestamp("W-FRI")
    weekly = pd.DataFrame(index=spy["week"].unique())
    weekly.index.name = "week"
    weekly["rv"] = spy.groupby("week")["r"].apply(lambda x: np.sqrt(np.sum(x.dropna() ** 2)))
    weekly["r_n"] = spy.groupby("week")["r"].count()
    weekly = weekly[weekly["r_n"] >= 4].sort_index()

    vix_df = vix[["Close"]].rename(columns={"Close": "vix"})
    vix_df["week"] = vix_df.index.to_period("W-FRI").to_timestamp("W-FRI")
    vix_w = vix_df.groupby("week").agg(vix_mean=("vix", "mean"))

    df = weekly.join(vix_w, how="inner").dropna()
    log(f"SPY+VIX weekly: {len(df)} weeks, {df.index.min().date()} to {df.index.max().date()}")
    return df


def load_altdata_three_views() -> dict[str, pd.DataFrame]:
    """Load each alt-data indicator in three views:

    - 'original': weekly mean, no explicit release lag (K1116-style; will be combined with shift(1) at model time)
    - 'shift2': weekly mean (we will apply shift(2) at model time — K1116b convention)
    - 'pit': point-in-time via release_date <= week-end-Friday
    """
    indicators = ["USEPU", "WLEMU", "NFCI", "ANFCI", "STLFSI"]

    views = {"weekly_mean": {}, "pit": {}}

    for alias in indicators:
        # K1116-style weekly mean
        rel_csv = DATA_DIR / f"{alias}_with_release_date.csv"
        pit_csv = DATA_DIR / f"{alias}_weekly_pit.csv"
        if not rel_csv.exists() or not pit_csv.exists():
            raise FileNotFoundError(f"Missing data for {alias}: run k1116c_fetch_alfred.py first")

        raw = pd.read_csv(rel_csv, parse_dates=["DATE", "RELEASE_DATE"])
        # weekly mean (ignore release)
        raw["week"] = raw["DATE"].dt.to_period("W-FRI").dt.to_timestamp("W-FRI")
        wm = raw.groupby("week")["VALUE"].mean().to_frame(alias)
        views["weekly_mean"][alias] = wm

        pit = pd.read_csv(pit_csv, parse_dates=["week_end", "obs_date", "release_date"])
        pit_s = pit.set_index("week_end")["value"].to_frame(alias)
        views["pit"][alias] = pit_s

    out = {}
    for view_name in views:
        df = None
        for alias in indicators:
            col = views[view_name][alias]
            df = col if df is None else df.join(col, how="outer")
        df = df.sort_index().ffill(limit=2)
        out[view_name] = df
    return out


# -------------------------------------------------------------------
# Metrics
# -------------------------------------------------------------------
def qlike(actual, pred):
    eps = 1e-10
    actual = np.maximum(actual, eps)
    pred = np.maximum(pred, eps)
    return np.mean(np.log(pred) + actual / pred)


def qlike_series(actual, pred):
    eps = 1e-10
    actual = np.maximum(actual, eps)
    pred = np.maximum(pred, eps)
    return np.log(pred) + actual / pred


def dm_hln(e1, e2, h=1):
    """DM-HLN test. Positive t: baseline loss > challenger -> challenger beats baseline."""
    from scipy import stats as st

    d = np.asarray(e1, dtype=float) - np.asarray(e2, dtype=float)
    d = d[~np.isnan(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan, n
    dbar = d.mean()
    gamma0 = np.var(d, ddof=1)
    if gamma0 <= 0:
        return np.nan, np.nan, n
    hln_correction = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    se = np.sqrt(gamma0 / n)
    t = (dbar / se) * hln_correction
    p = 2 * (1 - st.t.cdf(abs(t), df=n - 1))
    return float(t), float(p), int(n)


# -------------------------------------------------------------------
# Model factory
# -------------------------------------------------------------------
def make_X(df_sub: pd.DataFrame, spec: str, alt_cols_available: list) -> pd.DataFrame:
    """Build regressor matrix. spec in: base, vix, epu, finstress, all.

    All regressors already contain the appropriate lag in input df_sub.
    """
    X = pd.DataFrame(index=df_sub.index)
    X["y_lag1"] = df_sub["rv"].shift(1)

    # Model definitions match K1116/K1116b:
    #   M1 base       : AR(1) only
    #   M2 vix        : AR(1) + VIX   [baseline for DM tests]
    #   M3 epu        : AR(1) + USEPU + WLEMU     (NO VIX — pure alt-data)
    #   M4 finstress  : AR(1) + NFCI + ANFCI + STLFSI  (NO VIX — pure alt-data)
    #   M5 all        : AR(1) + VIX + USEPU + WLEMU + NFCI + ANFCI + STLFSI  (kitchen sink)
    if spec == "base":
        pass
    elif spec == "vix":
        X["vix_lag1"] = df_sub["vix_mean"].shift(1)
    elif spec == "epu":
        for col in ["USEPU_signal", "WLEMU_signal"]:
            if col in df_sub.columns:
                X[col] = df_sub[col]
    elif spec == "finstress":
        for col in ["NFCI_signal", "ANFCI_signal", "STLFSI_signal"]:
            if col in df_sub.columns:
                X[col] = df_sub[col]
    elif spec == "all":
        X["vix_lag1"] = df_sub["vix_mean"].shift(1)
        for col in ["USEPU_signal", "WLEMU_signal", "NFCI_signal", "ANFCI_signal", "STLFSI_signal"]:
            if col in df_sub.columns:
                X[col] = df_sub[col]
    else:
        raise ValueError(spec)

    return X


def fit_predict_ols(df_with_signals: pd.DataFrame, is_end: str, oos_start: str):
    """Fit OLS on IS, predict OOS. Returns dict with per-spec fits and OOS predictions."""
    import statsmodels.api as sm

    df_is = df_with_signals.loc[:is_end].copy()
    df_oos = df_with_signals.loc[oos_start:].copy()

    specs = ["base", "vix", "epu", "finstress", "all"]
    out = {}

    alt_cols = [c for c in df_with_signals.columns if c.endswith("_signal")]

    for spec in specs:
        X_is = make_X(df_is, spec, alt_cols)
        y_is = df_is["rv"].loc[X_is.index]
        mask = X_is.notna().all(axis=1) & y_is.notna()
        X_is = X_is[mask]
        y_is = y_is[mask]

        X_is_sm = sm.add_constant(X_is)
        model = sm.OLS(y_is, X_is_sm).fit()

        X_oos = make_X(df_oos, spec, alt_cols)
        mask_oos = X_oos.notna().all(axis=1)
        X_oos = X_oos[mask_oos]
        X_oos_sm = sm.add_constant(X_oos)
        # ensure same column ordering
        X_oos_sm = X_oos_sm[X_is_sm.columns]
        y_oos = df_oos["rv"].loc[X_oos.index]
        pred_oos = model.predict(X_oos_sm)

        valid = y_oos.notna() & pred_oos.notna()
        y_oos = y_oos[valid]
        pred_oos = pred_oos[valid]

        # QLIKE matched to K1116: loss = log(pred) + actual/pred, where pred/actual are rv (std)
        pred_clipped = np.maximum(pred_oos.values, 1e-6)
        actual_arr = y_oos.values
        loss_arr = np.log(pred_clipped) + actual_arr / pred_clipped
        qlike_oos = float(np.mean(loss_arr))
        loss_series = pd.Series(loss_arr, index=y_oos.index)

        out[spec] = {
            "n_is": int(len(X_is)),
            "n_oos": int(len(y_oos)),
            "oos_qlike": float(qlike_oos),
            "oos_rmse": float(np.sqrt(np.mean((y_oos.values - pred_oos.values) ** 2))),
            "loss_series": loss_series,
            "coef": {k: float(v) for k, v in model.params.items()},
            "r2_is": float(model.rsquared),
        }
    return out


# -------------------------------------------------------------------
# Variant construction
# -------------------------------------------------------------------
def build_variant_panel(market: pd.DataFrame, alt_weekly: pd.DataFrame, alt_pit: pd.DataFrame,
                        variant: str) -> pd.DataFrame:
    """Build merged panel with _signal suffix columns applying the variant's lag rule.

    variants:
      - orig_shift1: weekly mean, alt_signal = alt.shift(1)  [K1116 reproduction]
      - corrected_shift2: weekly mean, alt_signal = alt.shift(2) for weekly-cadence (NFCI/ANFCI/STLFSI)
                                                alt.shift(1) for daily-cadence (USEPU/WLEMU)  [K1116b]
      - conservative_shift2: weekly mean, alt_signal = alt.shift(2) for ALL  [K1116b conservative]
      - pit_shift0: PIT weekly, alt_signal = alt.shift(0) [PIT already uses data available at F]
      - pit_shift1: PIT weekly, alt_signal = alt.shift(1)  [extra safety margin]
      - multi_lag_3: weekly mean, alt_signal = alt.shift(3) [very conservative]
    """
    daily_cadence = ["USEPU", "WLEMU"]
    weekly_cadence = ["NFCI", "ANFCI", "STLFSI"]
    all_cols = daily_cadence + weekly_cadence

    if variant == "orig_shift1":
        base = alt_weekly.copy()
        lags = {c: 1 for c in all_cols}
    elif variant == "corrected_shift2":
        base = alt_weekly.copy()
        lags = {c: 1 for c in daily_cadence}
        lags.update({c: 2 for c in weekly_cadence})
    elif variant == "conservative_shift2":
        base = alt_weekly.copy()
        lags = {c: 2 for c in all_cols}
    elif variant == "pit_shift0":
        base = alt_pit.copy()
        lags = {c: 0 for c in all_cols}
    elif variant == "pit_shift1":
        base = alt_pit.copy()
        lags = {c: 1 for c in all_cols}
    elif variant == "multi_lag_3":
        base = alt_weekly.copy()
        lags = {c: 3 for c in all_cols}
    else:
        raise ValueError(variant)

    # apply lags -> _signal columns
    for c in all_cols:
        if c in base.columns:
            base[f"{c}_signal"] = base[c].shift(lags[c])

    # keep only _signal columns to avoid accidental reuse of unlagged series
    sig_cols = [f"{c}_signal" for c in all_cols if c in base.columns]
    base = base[sig_cols]

    merged = market.join(base, how="inner").dropna(subset=["rv", "vix_mean"])
    return merged


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
def main():
    log("=" * 70)
    log("K1116c: Vintage-approximation via PIT release-calendar alignment")
    log("=" * 70)

    market = fetch_spy_vix_weekly()

    views = load_altdata_three_views()
    alt_weekly = views["weekly_mean"]
    alt_pit = views["pit"]

    log(f"Weekly-mean altdata shape: {alt_weekly.shape}")
    log(f"PIT altdata shape: {alt_pit.shape}")

    variants = ["orig_shift1", "corrected_shift2", "conservative_shift2",
                "pit_shift0", "pit_shift1", "multi_lag_3"]

    is_end = "2022-12-31"
    oos_start = "2023-01-01"

    variant_results = {}
    # store loss series to allow DM tests
    all_loss = {}  # (variant, spec) -> loss series (OOS)

    for variant in variants:
        log(f"\n--- Variant: {variant} ---")
        panel = build_variant_panel(market, alt_weekly, alt_pit, variant)
        log(f"  merged panel: {panel.shape}, "
            f"period {panel.index.min().date()} to {panel.index.max().date()}")

        fit_out = fit_predict_ols(panel, is_end, oos_start)

        variant_summary = {}
        for spec, res in fit_out.items():
            entry = {k: v for k, v in res.items() if k != "loss_series"}
            variant_summary[spec] = entry
            all_loss[(variant, spec)] = res["loss_series"]

        variant_results[variant] = variant_summary

    # -------------- DM tests (vs vix baseline within each variant) --------------
    log("\n" + "=" * 70)
    log("DM-HLN tests (each spec vs M2_vix baseline, within same variant)")
    log("=" * 70)

    dm_table = {}
    for variant in variants:
        dm_table[variant] = {}
        base_loss = all_loss.get((variant, "vix"))
        if base_loss is None:
            continue
        for spec in ["base", "epu", "finstress", "all"]:
            chal_loss = all_loss.get((variant, spec))
            if chal_loss is None:
                continue
            # align on intersection
            idx = base_loss.index.intersection(chal_loss.index)
            e_base = base_loss.loc[idx].values
            e_chal = chal_loss.loc[idx].values
            # t>0 means e_base > e_chal => baseline has higher loss => challenger wins
            t, p, n = dm_hln(e_base, e_chal, h=1)
            dm_table[variant][spec] = {"t": t, "p": p, "n": n,
                                       "verdict": ("CHAL_WINS" if (t is not None and not np.isnan(t) and t > 3)
                                                   else "BASELINE_WINS" if (t is not None and not np.isnan(t) and t < -3)
                                                   else "NS")}
            log(f"  {variant:22s} {spec:10s} t={t:+.3f} p={p:.4f} n={n} -> {dm_table[variant][spec]['verdict']}")

    # -------------- Cross-variant DM (PIT vs corrected on same spec) --------------
    log("\n" + "=" * 70)
    log("Cross-variant DM (does PIT vs corrected change OOS loss for same spec?)")
    log("=" * 70)
    cross_variant_dm = {}
    for spec in ["base", "vix", "epu", "finstress", "all"]:
        a_loss = all_loss.get(("corrected_shift2", spec))
        b_loss = all_loss.get(("pit_shift0", spec))
        if a_loss is None or b_loss is None:
            continue
        idx = a_loss.index.intersection(b_loss.index)
        e_a = a_loss.loc[idx].values
        e_b = b_loss.loc[idx].values
        t, p, n = dm_hln(e_a, e_b, h=1)
        cross_variant_dm[spec] = {"t": t, "p": p, "n": n}
        log(f"  {spec:10s} corrected_shift2 vs pit_shift0: t={t:+.3f} p={p:.4f} n={n}")

    # -------------- Verdict logic --------------
    log("\n" + "=" * 70)
    log("VERDICT")
    log("=" * 70)

    any_pass = False
    indicators_pass = []
    for variant in variants:
        for spec in ["epu", "finstress", "all"]:
            cell = dm_table.get(variant, {}).get(spec, {})
            if cell.get("verdict") == "CHAL_WINS":
                any_pass = True
                indicators_pass.append((variant, spec, cell["t"]))

    if any_pass:
        verdict = "H1_PASS" if len(indicators_pass) >= 3 else "H3_PARTIAL"
        log(f"VERDICT: {verdict} - some alt-data cells pass:")
        for v, s, t in indicators_pass:
            log(f"  {v} / {s}: t={t:+.3f}")
    else:
        verdict = "H2_ROBUST_NULL"
        log(f"VERDICT: {verdict} - all alt-data specs FAIL across all 6 variants.")
        log(f"  Revision-corrected + PIT alignment still NULL. Vintage would likewise be NULL.")
        log(f"  K1116 / K1116b NULL conclusion is robust to publication-delay/vintage concerns.")

    RESULTS["variant_results"] = variant_results
    RESULTS["dm_vs_vix_baseline"] = dm_table
    RESULTS["cross_variant_dm"] = cross_variant_dm
    RESULTS["verdict"] = verdict
    RESULTS["indicators_passing"] = [
        {"variant": v, "spec": s, "t": t} for v, s, t in indicators_pass
    ]
    RESULTS["completed_utc"] = datetime.utcnow().isoformat() + "Z"

    # Save
    with open(OUT_DIR / "k1116c_results.json", "w") as f:
        json.dump(RESULTS, f, indent=2, default=str)
    log(f"\nResults saved: {OUT_DIR / 'k1116c_results.json'}")

    # -------------- Compact summary for README --------------
    print("\n" + "=" * 70)
    print("DM-HLN t-stats (vs M2_vix baseline) — Harvey threshold |t|>3")
    print("=" * 70)
    print(f"{'Variant':25s} {'base':>8s} {'epu':>8s} {'finstress':>10s} {'all':>8s}")
    for variant in variants:
        row = f"{variant:25s}"
        for spec in ["base", "epu", "finstress", "all"]:
            cell = dm_table.get(variant, {}).get(spec, {})
            t = cell.get("t")
            if t is None or np.isnan(t):
                row += f" {'n/a':>8s}" if spec != "finstress" else f" {'n/a':>10s}"
            else:
                row += f" {t:+8.3f}" if spec != "finstress" else f" {t:+10.3f}"
        print(row)

    return RESULTS


if __name__ == "__main__":
    main()
