"""K1116d: TRUE ALFRED first-release vintage retest of K1116c PIT NULL verdict.

Hypothesis chain
----------------
- K1116 / K1116b / K1118 / K1121: alt-data (EPU/NFCI/ANFCI/STLFSI) does not beat VIX
  for SPY weekly vol — across multiple lag conventions.
- K1116c (2026-04-13) ROBUST NULL: even strict point-in-time release-calendar alignment
  on revision-corrected fredgraph data fails to rescue alt-data → DM |t| stays negative
  vs VIX baseline across all 6 lag/PIT variants.
- Residual concern: fredgraph values are revision-corrected, not first-release. If the
  TRUE vintage (what a market participant actually saw at release) carries hidden
  signal, K1116c's "noisier vintage cannot reveal hidden signal" argument fails.

K1116d test
-----------
Replace each indicator's input panel with TRUE first-release vintage (FRED API
output_type=4) and re-run the K1116c 6-variant × 5-spec DM battery. Predicted: still
NULL (vintage is noisier than revised, so its incremental signal can only be ≤ revised's,
which is already NULL). If vintage suddenly PASSES → must reopen Paper 4 narrative.

Implementation fidelity
-----------------------
- 6 lag/PIT variants identical to K1116c: orig_shift1, corrected_shift2,
  conservative_shift2, pit_shift0, pit_shift1, multi_lag_3.
- 5 model specs identical to K1116c: base, vix, epu, finstress, all.
- IS 2018-2022, OOS 2023-2026 (same windows).
- QLIKE: log(pred) + actual/pred (Patton 2011, K1116 convention).
- DM-HLN, h=1, Harvey (2016) |t|>3 threshold (multiple-testing).
- Bootstrap CI on DM stats with seed=42 (1000 reps).
- Baseline lag rule: vix uses .shift(1), identical to K1116c — fair comparison.

Lookahead audit (this file, see build_variant_panel)
----------------------------------------------------
For PIT panels, value at week-end Friday F was set in the fetch script using
RELEASE_DATE <= F (no future leakage). For weekly_mean panels, additional .shift(N)
in build_variant_panel applies the K1116/K1116b convention. AR(1) regressor uses
df["rv"].shift(1) inside make_X. VIX baseline uses .shift(1). All lags explicit.

Author: Yi-Hao Lai + VolPred Research System
Date: 2026-05-09
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
    "experiment_id": "K1116d",
    "title": "True ALFRED first-release vintage retest of K1116c PIT NULL verdict",
    "started_utc": datetime.utcnow().isoformat() + "Z",
    "data_source": "FRED API output_type=4 (first-release vintage) + STLFSI series chain",
    "baseline_experiments": ["K1116", "K1116b", "K1116c"],
    "vintage_method": (
        "FRED API output_type=4 returns one observation per (date, first realtime_start) "
        "pair. STLFSI is chained across STLFSI/STLFSI2/STLFSI3/STLFSI4 (predecessors "
        "discontinued) so each release date carries the value that was actually published. "
        "Daily series (USEPU/WLEMU) chunked yearly to fit FRED API vintage cap."
    ),
    "references": [
        "Baker, Bloom, Davis (2016) QJE - EPU index",
        "Brave, Butters (2011) Fed Letter 286 - NFCI",
        "Kliesen, Smith (2010) - STLFSI",
        "Croushore & Stark (2001) J Econometrics - real-time vintage data",
        "Patton (2011) JoE - QLIKE proxy-robust loss",
        "Harvey, Leybourne, Newbold (1997) IJF - HLN DM correction",
        "Harvey (2016) RFS - |t|>3 multiple-testing threshold",
    ],
}


def log(msg: str) -> None:
    ts = datetime.utcnow().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ---------------------------------------------------------------- data loading
def fetch_spy_vix_weekly() -> pd.DataFrame:
    """SPY weekly RV + VIX weekly mean. Identical to K1116c (yfinance, W-FRI)."""
    import yfinance as yf

    log("Fetching SPY + VIX daily 2018-2026...")
    spy = yf.download("SPY", start="2018-01-01", end="2026-04-13",
                      progress=False, auto_adjust=True)
    vix = yf.download("^VIX", start="2018-01-01", end="2026-04-13",
                      progress=False, auto_adjust=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    spy = spy[["Close"]].copy()
    spy["r"] = np.log(spy["Close"]).diff()
    spy["week"] = spy.index.to_period("W-FRI").to_timestamp("W-FRI")

    weekly = pd.DataFrame(index=spy["week"].unique())
    weekly.index.name = "week"
    weekly["rv"] = spy.groupby("week")["r"].apply(
        lambda x: np.sqrt(np.sum(x.dropna() ** 2))
    )
    weekly["r_n"] = spy.groupby("week")["r"].count()
    weekly = weekly[weekly["r_n"] >= 4].sort_index()

    vix_df = vix[["Close"]].rename(columns={"Close": "vix"})
    vix_df["week"] = vix_df.index.to_period("W-FRI").to_timestamp("W-FRI")
    vix_w = vix_df.groupby("week").agg(vix_mean=("vix", "mean"))

    df = weekly.join(vix_w, how="inner").dropna()
    log(f"SPY+VIX weekly: {len(df)} weeks, "
        f"{df.index.min().date()} to {df.index.max().date()}")
    return df


def load_vintage_two_views() -> dict[str, pd.DataFrame]:
    """Two views from TRUE first-release vintage data:

    - 'weekly_mean': mean of all vintage observations falling in week W (by obs date)
                     — analogue of K1116 weekly_mean construction, but values are
                     vintage not revised.
    - 'pit': at each week-ending Friday F, take most recent vintage obs whose
             RELEASE_DATE <= F. Same construction as K1116c PIT but with vintage values.
    """
    indicators = ["USEPU", "WLEMU", "NFCI", "ANFCI", "STLFSI"]
    views = {"weekly_mean": {}, "pit": {}}

    for alias in indicators:
        rel_csv = DATA_DIR / f"{alias}_vintage_with_release_date.csv"
        pit_csv = DATA_DIR / f"{alias}_weekly_pit.csv"
        if not rel_csv.exists() or not pit_csv.exists():
            raise FileNotFoundError(
                f"Missing vintage data for {alias}: run k1116d_fetch_alfred.py first")

        raw = pd.read_csv(rel_csv, parse_dates=["DATE", "RELEASE_DATE"])
        raw["week"] = raw["DATE"].dt.to_period("W-FRI").dt.to_timestamp("W-FRI")
        wm = raw.groupby("week")["VALUE"].mean().to_frame(alias)
        views["weekly_mean"][alias] = wm

        pit = pd.read_csv(pit_csv, parse_dates=["week_end", "obs_date", "release_date"])
        views["pit"][alias] = pit.set_index("week_end")["value"].to_frame(alias)

    out = {}
    for view_name in views:
        df = None
        for alias in indicators:
            col = views[view_name][alias]
            df = col if df is None else df.join(col, how="outer")
        df = df.sort_index().ffill(limit=2)
        out[view_name] = df
    return out


def load_revised_two_views() -> dict[str, pd.DataFrame]:
    """Same construction as load_vintage_two_views but using fredgraph (revised) data —
    so we can directly compare K1116d vintage vs K1116d revised within ONE run.

    Note: build the same release_date column from BDay offsets for fair PIT alignment
    (matches K1116c logic).
    """
    indicators = ["USEPU", "WLEMU", "NFCI", "ANFCI", "STLFSI"]
    cadence = {"USEPU": "daily", "WLEMU": "daily",
               "NFCI": "wednesday", "ANFCI": "wednesday", "STLFSI": "thursday"}

    def add_release(df: pd.DataFrame, kind: str) -> pd.DataFrame:
        df = df.copy()
        df["DATE"] = pd.to_datetime(df["DATE"])
        if kind == "daily":
            df["RELEASE_DATE"] = df["DATE"] + pd.tseries.offsets.BDay(1)
        elif kind == "wednesday":
            df["RELEASE_DATE"] = df["DATE"] + pd.tseries.offsets.BDay(3)
        elif kind == "thursday":
            df["RELEASE_DATE"] = df["DATE"] + pd.tseries.offsets.BDay(4)
        else:
            df["RELEASE_DATE"] = df["DATE"] + pd.tseries.offsets.BDay(1)
        return df

    def pit_resample(df: pd.DataFrame, freq: str = "W-FRI") -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame()
        fridays = pd.date_range(df["DATE"].min(),
                                df["DATE"].max() + pd.Timedelta(days=14),
                                freq=freq)
        out = []
        df_sorted = df.sort_values("RELEASE_DATE").reset_index(drop=True)
        for f in fridays:
            avail = df_sorted[df_sorted["RELEASE_DATE"] <= f]
            if len(avail) == 0:
                continue
            row = avail.iloc[-1]
            out.append({"week_end": f, "value": row["VALUE"]})
        return pd.DataFrame(out)

    views = {"weekly_mean": {}, "pit": {}}
    for alias in indicators:
        rev_csv = DATA_DIR / f"{alias}_revised_snapshot.csv"
        if not rev_csv.exists():
            log(f"  WARN: missing revised snapshot for {alias}, skipping")
            continue
        rev = pd.read_csv(rev_csv)
        rev["DATE"] = pd.to_datetime(rev["DATE"])
        rev["VALUE"] = pd.to_numeric(rev["VALUE"], errors="coerce")
        rev = rev.dropna(subset=["VALUE"])
        rev = add_release(rev, cadence[alias])

        rev["week"] = rev["DATE"].dt.to_period("W-FRI").dt.to_timestamp("W-FRI")
        wm = rev.groupby("week")["VALUE"].mean().to_frame(alias)
        views["weekly_mean"][alias] = wm

        pit = pit_resample(rev)
        if not pit.empty:
            views["pit"][alias] = pit.set_index("week_end")["value"].to_frame(alias)

    out = {}
    for view_name in views:
        df = None
        for alias in indicators:
            col = views[view_name].get(alias)
            if col is None:
                continue
            df = col if df is None else df.join(col, how="outer")
        if df is not None:
            df = df.sort_index().ffill(limit=2)
        out[view_name] = df
    return out


# ----------------------------------------------------------------------- stats
def dm_hln(e1, e2, h: int = 1):
    """DM-HLN test. Positive t: e1>e2 (baseline loss higher → challenger wins)."""
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
    hln = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    se = np.sqrt(gamma0 / n)
    t = (dbar / se) * hln
    p = 2 * (1 - st.t.cdf(abs(t), df=n - 1))
    return float(t), float(p), int(n)


def dm_bootstrap_ci(e1, e2, h: int = 1, n_boot: int = 1000, seed: int = 42):
    """Stationary bootstrap CI for DM t-stat. Seed=42 enforced."""
    rng = np.random.default_rng(seed)
    d = np.asarray(e1, dtype=float) - np.asarray(e2, dtype=float)
    d = d[~np.isnan(d)]
    n = len(d)
    if n < 30:
        return None
    p_geom = 1.0 / max(int(np.sqrt(n)), 5)  # avg block ~ sqrt(n)
    ts = []
    for _ in range(n_boot):
        idx = [int(rng.integers(0, n))]
        while len(idx) < n:
            if rng.random() < p_geom:
                idx.append(int(rng.integers(0, n)))
            else:
                idx.append((idx[-1] + 1) % n)
        d_bs = d[np.array(idx)]
        dbar = d_bs.mean()
        gamma0 = np.var(d_bs, ddof=1)
        if gamma0 <= 0:
            continue
        hln = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
        ts.append((dbar / np.sqrt(gamma0 / n)) * hln)
    if not ts:
        return None
    ts = np.array(ts)
    return {
        "mean": float(np.mean(ts)),
        "ci_2_5": float(np.percentile(ts, 2.5)),
        "ci_97_5": float(np.percentile(ts, 97.5)),
        "n_boot": int(len(ts)),
    }


# ----------------------------------------------------------------- model
def make_X(df_sub: pd.DataFrame, spec: str) -> pd.DataFrame:
    """Identical to K1116c. AR(1) lag, VIX baseline lag, alt-data already pre-lagged.

    Lag explicit:
      - AR(1) regressor:  rv.shift(1)        — t-1 lag
      - VIX baseline:     vix_mean.shift(1)  — t-1 lag (matches K1116c)
      - Alt-data signals: already pre-lagged in build_variant_panel via _signal suffix
    """
    X = pd.DataFrame(index=df_sub.index)
    X["y_lag1"] = df_sub["rv"].shift(1)

    if spec == "base":
        pass
    elif spec == "vix":
        X["vix_lag1"] = df_sub["vix_mean"].shift(1)
    elif spec == "epu":
        for c in ["USEPU_signal", "WLEMU_signal"]:
            if c in df_sub.columns:
                X[c] = df_sub[c]
    elif spec == "finstress":
        for c in ["NFCI_signal", "ANFCI_signal", "STLFSI_signal"]:
            if c in df_sub.columns:
                X[c] = df_sub[c]
    elif spec == "all":
        X["vix_lag1"] = df_sub["vix_mean"].shift(1)
        for c in ["USEPU_signal", "WLEMU_signal",
                  "NFCI_signal", "ANFCI_signal", "STLFSI_signal"]:
            if c in df_sub.columns:
                X[c] = df_sub[c]
    else:
        raise ValueError(spec)
    return X


def fit_predict_ols(panel: pd.DataFrame, is_end: str, oos_start: str):
    import statsmodels.api as sm

    df_is = panel.loc[:is_end].copy()
    df_oos = panel.loc[oos_start:].copy()
    out = {}
    for spec in ["base", "vix", "epu", "finstress", "all"]:
        X_is = make_X(df_is, spec)
        y_is = df_is["rv"].loc[X_is.index]
        mask = X_is.notna().all(axis=1) & y_is.notna()
        X_is, y_is = X_is[mask], y_is[mask]
        X_is_sm = sm.add_constant(X_is)
        model = sm.OLS(y_is, X_is_sm).fit()

        X_oos = make_X(df_oos, spec)
        mask_oos = X_oos.notna().all(axis=1)
        X_oos = X_oos[mask_oos]
        X_oos_sm = sm.add_constant(X_oos)[X_is_sm.columns]
        y_oos = df_oos["rv"].loc[X_oos.index]
        pred_oos = model.predict(X_oos_sm)
        valid = y_oos.notna() & pred_oos.notna()
        y_oos, pred_oos = y_oos[valid], pred_oos[valid]

        pred_clipped = np.maximum(pred_oos.values, 1e-6)
        actual = y_oos.values
        loss = np.log(pred_clipped) + actual / pred_clipped
        out[spec] = {
            "n_is": int(len(X_is)),
            "n_oos": int(len(y_oos)),
            "oos_qlike": float(np.mean(loss)),
            "oos_rmse": float(np.sqrt(np.mean((actual - pred_oos.values) ** 2))),
            "loss_series": pd.Series(loss, index=y_oos.index),
            "coef": {k: float(v) for k, v in model.params.items()},
            "r2_is": float(model.rsquared),
        }
    return out


# ------------------------------------------------- variant panel construction
def build_variant_panel(market: pd.DataFrame,
                        alt_weekly: pd.DataFrame, alt_pit: pd.DataFrame,
                        variant: str) -> pd.DataFrame:
    """Apply lag/PIT convention to alt data, return merged panel.

    All 6 variants identical to K1116c. _signal suffix marks pre-lagged columns.
    Lag values:
      - orig_shift1: shift(1) all
      - corrected_shift2: daily shift(1), weekly shift(2)
      - conservative_shift2: shift(2) all
      - pit_shift0: shift(0) (PIT already aligned)
      - pit_shift1: shift(1) on PIT (extra margin)
      - multi_lag_3: shift(3) all
    """
    daily = ["USEPU", "WLEMU"]
    weekly = ["NFCI", "ANFCI", "STLFSI"]
    cols = daily + weekly

    if variant == "orig_shift1":
        base = alt_weekly.copy(); lags = {c: 1 for c in cols}
    elif variant == "corrected_shift2":
        base = alt_weekly.copy()
        lags = {c: 1 for c in daily}; lags.update({c: 2 for c in weekly})
    elif variant == "conservative_shift2":
        base = alt_weekly.copy(); lags = {c: 2 for c in cols}
    elif variant == "pit_shift0":
        base = alt_pit.copy(); lags = {c: 0 for c in cols}
    elif variant == "pit_shift1":
        base = alt_pit.copy(); lags = {c: 1 for c in cols}
    elif variant == "multi_lag_3":
        base = alt_weekly.copy(); lags = {c: 3 for c in cols}
    else:
        raise ValueError(variant)

    for c in cols:
        if c in base.columns:
            base[f"{c}_signal"] = base[c].shift(lags[c])
    sig_cols = [f"{c}_signal" for c in cols if c in base.columns]
    base = base[sig_cols]
    merged = market.join(base, how="inner").dropna(subset=["rv", "vix_mean"])
    return merged


# ------------------------------------------------------------------ run cycle
def run_cycle(market, alt_weekly, alt_pit, label: str) -> dict:
    """Run full 6×5 DM battery on a given alt-data backbone."""
    log(f"\n{'='*70}\nCYCLE: {label}\n{'='*70}")

    variants = ["orig_shift1", "corrected_shift2", "conservative_shift2",
                "pit_shift0", "pit_shift1", "multi_lag_3"]
    is_end, oos_start = "2022-12-31", "2023-01-01"

    variant_results, all_loss = {}, {}
    for variant in variants:
        panel = build_variant_panel(market, alt_weekly, alt_pit, variant)
        log(f"  {variant:25s} panel={panel.shape} "
            f"{panel.index.min().date()}..{panel.index.max().date()}")
        fit = fit_predict_ols(panel, is_end, oos_start)
        summary = {}
        for spec, res in fit.items():
            summary[spec] = {k: v for k, v in res.items() if k != "loss_series"}
            all_loss[(variant, spec)] = res["loss_series"]
        variant_results[variant] = summary

    # DM tests vs M2_vix baseline within same variant
    dm_table = {}
    for variant in variants:
        dm_table[variant] = {}
        bl = all_loss.get((variant, "vix"))
        if bl is None:
            continue
        for spec in ["base", "epu", "finstress", "all"]:
            ch = all_loss.get((variant, spec))
            if ch is None:
                continue
            idx = bl.index.intersection(ch.index)
            t, p, n = dm_hln(bl.loc[idx].values, ch.loc[idx].values, h=1)
            ci = dm_bootstrap_ci(bl.loc[idx].values, ch.loc[idx].values,
                                 h=1, n_boot=1000, seed=42)
            verdict = ("CHAL_WINS" if (t is not None and not np.isnan(t) and t > 3)
                       else "BASELINE_WINS" if (t is not None and not np.isnan(t) and t < -3)
                       else "NS")
            dm_table[variant][spec] = {"t": t, "p": p, "n": n,
                                       "verdict": verdict, "bootstrap_ci": ci}

    # Cross-variant DM (K1116c convention: corrected_shift2 vs pit_shift0 same spec)
    cross = {}
    for spec in ["base", "vix", "epu", "finstress", "all"]:
        a = all_loss.get(("corrected_shift2", spec))
        b = all_loss.get(("pit_shift0", spec))
        if a is None or b is None:
            continue
        idx = a.index.intersection(b.index)
        t, p, n = dm_hln(a.loc[idx].values, b.loc[idx].values, h=1)
        cross[spec] = {"t": t, "p": p, "n": n}

    # Verdict
    any_pass = False
    passing = []
    for variant in variants:
        for spec in ["epu", "finstress", "all"]:
            cell = dm_table.get(variant, {}).get(spec, {})
            if cell.get("verdict") == "CHAL_WINS":
                any_pass = True
                passing.append((variant, spec, cell["t"]))

    if any_pass:
        verdict = "H1_PASS" if len(passing) >= 3 else "H3_PARTIAL"
    else:
        verdict = "H2_ROBUST_NULL"

    return {
        "label": label,
        "variant_results": variant_results,
        "dm_vs_vix_baseline": dm_table,
        "cross_variant_dm": cross,
        "verdict": verdict,
        "indicators_passing": [{"variant": v, "spec": s, "t": t} for v, s, t in passing],
    }


# ---------------------------------------------------- vintage-vs-revised diff
def vintage_vs_revised_diff(vintage: dict, revised: dict) -> dict:
    """Per-indicator correlation + max abs diff between vintage and revised PIT panels."""
    out = {}
    indicators = ["USEPU", "WLEMU", "NFCI", "ANFCI", "STLFSI"]
    v_pit = vintage.get("pit")
    r_pit = revised.get("pit")
    if v_pit is None or r_pit is None:
        return out
    for ind in indicators:
        if ind in v_pit.columns and ind in r_pit.columns:
            idx = v_pit.index.intersection(r_pit.index)
            v = v_pit.loc[idx, ind].dropna()
            r = r_pit.loc[idx, ind].dropna()
            common = v.index.intersection(r.index)
            v, r = v.loc[common], r.loc[common]
            if len(common) < 5:
                continue
            try:
                corr = float(np.corrcoef(v.values, r.values)[0, 1])
            except Exception:
                corr = float("nan")
            out[ind] = {
                "n": int(len(common)),
                "corr_vintage_revised": corr,
                "max_abs_diff": float(np.max(np.abs(v.values - r.values))),
                "mean_abs_diff": float(np.mean(np.abs(v.values - r.values))),
            }
    return out


# ---------------------------------------------------------------------- main
def main():
    log("=" * 70)
    log("K1116d: TRUE ALFRED first-release vintage retest")
    log("=" * 70)

    market = fetch_spy_vix_weekly()

    # Load both vintage and revised panels — same construction, different values.
    vintage_views = load_vintage_two_views()
    revised_views = load_revised_two_views()

    log(f"\nVintage panels: weekly_mean={vintage_views['weekly_mean'].shape}, "
        f"pit={vintage_views['pit'].shape}")
    log(f"Revised panels: weekly_mean={revised_views['weekly_mean'].shape}, "
        f"pit={revised_views['pit'].shape}")

    # Diff snapshot for README §4
    diff_snap = vintage_vs_revised_diff(vintage_views, revised_views)
    log("\nVintage-vs-revised PIT differences:")
    for ind, st in diff_snap.items():
        log(f"  {ind:8s}  n={st['n']}  corr={st['corr_vintage_revised']:.4f}  "
            f"max|d|={st['max_abs_diff']:.3f}  mean|d|={st['mean_abs_diff']:.4f}")

    # Run two cycles: vintage backbone + revised backbone (both via the same
    # K1116c 6×5 battery, so they are DIRECTLY comparable in this run).
    vintage_cycle = run_cycle(market,
                              vintage_views["weekly_mean"],
                              vintage_views["pit"], label="VINTAGE (K1116d primary)")
    revised_cycle = run_cycle(market,
                              revised_views["weekly_mean"],
                              revised_views["pit"], label="REVISED (K1116c replication)")

    # ---------- summary verdict ----------
    log("\n" + "=" * 70)
    log("VERDICTS")
    log("=" * 70)
    log(f"  Vintage cycle: {vintage_cycle['verdict']}  "
        f"({len(vintage_cycle['indicators_passing'])} cells passing)")
    log(f"  Revised cycle: {revised_cycle['verdict']}  "
        f"({len(revised_cycle['indicators_passing'])} cells passing)")

    if vintage_cycle["verdict"] == "H2_ROBUST_NULL":
        master_verdict = "H2_ROBUST_NULL_VINTAGE_CONFIRMED"
        narrative_msg = ("True ALFRED vintage data confirms K1116c upper-bound argument. "
                         "All 6 lag/PIT variants × 5 specs fail to reach Harvey |t|>3. "
                         "Paper 4 alt-data NULL is robust to vintage concern.")
    elif vintage_cycle["verdict"] in ("H1_PASS", "H3_PARTIAL"):
        master_verdict = "K1116c_OVERTURNED_VINTAGE_REVEALS_SIGNAL"
        narrative_msg = ("Vintage data reveals incremental signal absent from revised. "
                         "K1116c upper-bound argument fails — revision smoothing was "
                         "masking signal. Paper 4 narrative requires update.")
    else:
        master_verdict = "INCONCLUSIVE"
        narrative_msg = "Unexpected combination — see per-cycle details."

    log(f"\nMASTER VERDICT: {master_verdict}")
    log(f"  {narrative_msg}")

    RESULTS["vintage_cycle"] = vintage_cycle
    RESULTS["revised_cycle"] = revised_cycle
    RESULTS["vintage_vs_revised_diff"] = diff_snap
    RESULTS["master_verdict"] = master_verdict
    RESULTS["narrative_msg"] = narrative_msg
    RESULTS["completed_utc"] = datetime.utcnow().isoformat() + "Z"

    out_path = OUT_DIR / "k1116d_results.json"
    with open(out_path, "w") as f:
        json.dump(RESULTS, f, indent=2, default=str)
    log(f"\nResults saved: {out_path}")

    # ---------- compact summary table ----------
    print("\n" + "=" * 70)
    print("VINTAGE — DM-HLN t-stats (vs M2_vix baseline) — Harvey threshold |t|>3")
    print("=" * 70)
    print(f"{'Variant':25s} {'base':>8s} {'epu':>8s} {'finstress':>10s} {'all':>8s}")
    for variant in ["orig_shift1", "corrected_shift2", "conservative_shift2",
                    "pit_shift0", "pit_shift1", "multi_lag_3"]:
        row = f"{variant:25s}"
        for spec in ["base", "epu", "finstress", "all"]:
            cell = vintage_cycle["dm_vs_vix_baseline"].get(variant, {}).get(spec, {})
            t = cell.get("t")
            width = 10 if spec == "finstress" else 8
            if t is None or (isinstance(t, float) and np.isnan(t)):
                row += f" {'n/a':>{width}s}"
            else:
                row += f" {t:+{width}.3f}"
        print(row)
    return RESULTS


if __name__ == "__main__":
    main()
