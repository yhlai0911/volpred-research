"""
K1203: Close Paper 4's 7-asset PIT panorama by adding EEM (Emerging Markets ETF).

Goal: Complete the K1116c / K1116f / K1201 PIT framework coverage to 7/7 of the Paper 4
cross-asset universe. K1201 closed QQQ + USO (6/7). EEM was the only remaining cell, which
K1201 itself flagged as follow-up. K1203 tests whether alt-data (USEPU / WLEMU / NFCI /
ANFCI / STLFSI) beats a native-IV baseline on weekly EEM RV under point-in-time release-
calendar alignment.

Design decisions (mirror K1201 / K1116f to ensure direct comparability):
  * Reuse K1116c PIT CSVs (`experiments/k1116c/data/<alias>_weekly_pit.csv`).
  * Weekly W-FRI AR(1) + native IV baseline (K1118 convention).
  * Five specs: base / iv / epu / finstress / all.
  * Three lag variants: k1118_shift1, pit_shift0 (primary), pit_shift1.
  * DM-HLN with Harvey (1997) correction; Harvey (2016) |t|>3 gate.
  * Seed 42. OOS 2023-01-01 onward, >=170 weeks.

Native IV choice (EEM):
  * Primary: ^VIX + caveat. K1203 2026-04-17 test confirmed ^VXEEM is delisted on yfinance
    (HTTP 404 "Quote not found for symbol: VXEEM"; also checked ^VXFXI, ^CIV — all empty).
    Per brief fallback spec, use ^VIX as the implied-vol regressor with an explicit caveat:
    VIX reflects SPY / S&P 500 option IV, not EEM-specific IV, so the "native IV" label is
    weaker than QQQ's ^VXN or USO's ^OVX. EEM-VIX correlation is empirically high (~0.75
    weekly), so VIX remains a reasonable spill-over proxy.
  * Secondary (robustness): rv30 — 30-day annualised rolling realised vol of EEM itself,
    identical to K1118 / K1116f BTC convention. This gives an IV-free baseline for
    sensitivity check.

The primary verdict uses ^VIX; rv30 is reported in asset_results for cross-reference.

Output:
  * k1203_results.json: per variant x per spec QLIKE + DM t/p + gate flags, 4-variant
    DM table, 7-asset panorama, verdict, Paper 4 body.tex rewrite gate.
  * k1203_dm_bar.png: EEM DM t bar chart by spec (pit_shift0).
  * k1203_dm_heatmap_7asset.png: 7-asset DM t heatmap (extend K1201 fig).
  * k1203_qlike_improvement_7asset.png: 7-asset QLIKE improvement bar chart.

References: inherit K1116c / K1116f / K1118 / K1201 citation stacks + CBOE VIX methodology.
Author: VolPred Research System (worktree agent-a16dfea0), 2026-04-17.
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
EXP_ROOT = HERE.parent
REPO_ROOT = EXP_ROOT.parent
# Worktree-local K1116c cache (same shas as main; read-only reference)
K1116C_DATA = EXP_ROOT / "k1116c" / "data"
K1116C_RESULTS = EXP_ROOT / "k1116c" / "k1116c_results.json"
K1116F_RESULTS = EXP_ROOT / "k1116f" / "k1116f_results.json"
K1118_RESULTS = EXP_ROOT / "k1118" / "k1118_results.json"
# K1201 lives on main branch, not in this worktree; fall back to absolute path on host.
K1201_RESULTS_CANDIDATES = [
    EXP_ROOT / "k1201" / "k1201_results.json",
    Path("/Users/yhlai0911/Desktop/volpred-research/experiments/k1201/k1201_results.json"),
]
OUT_DIR = HERE

RESULTS: dict = {
    "experiment_id": "K1203",
    "title": "PIT alignment extended to EEM; closes Paper 4 7-asset panorama",
    "started_utc": datetime.utcnow().isoformat() + "Z",
    "seed": 42,
    "predecessor_experiments": {
        "K1116c": "SPY weekly, PIT + 6 lag variants, robust NULL",
        "K1116f": "GLD / TLT / BTC-USD PIT extension; ASSET_SPECIFIC with TLT finstress caveat",
        "K1118": "Cross-asset shift(1) baseline (GLD / TLT / BTC)",
        "K1116b": "SPY weekly shift(2) publication-delay correction",
        "K1201": "QQQ + USO PIT; 6/7 panorama UNIVERSAL_NULL with TLT caveat",
    },
    "scope_note": (
        "Adds EEM (iShares MSCI Emerging Markets ETF) as the final cell of the Paper 4 "
        "panorama. ^VXEEM was delisted on yfinance (404) at 2026-04-17 so the primary "
        "native-IV regressor is ^VIX with a documented caveat; rv30 serves as the IV-free "
        "robustness check."
    ),
    "iv_selection_trace": {
        "target": "^VXEEM (CBOE Emerging Markets VIX)",
        "yfinance_check_2026_04_17": {
            "^VXEEM": "HTTP 404 Quote not found; no price data found (delisted)",
            "VXEEM": "possibly delisted; no timezone found",
            "^VXFXI": "HTTP 404 Quote not found; no price data found",
            "^CIV": "no price data found",
        },
        "fallback_chosen": "^VIX (spillover proxy) + rv30 (internal RV proxy, robustness)",
        "caveat": (
            "^VIX is SPX-native not EEM-native. Weekly EEM-VIX correlation in this sample "
            "is ~0.75 per K1121 diagnostics, so VIX captures substantial but imperfect "
            "emerging-market systemic vol risk. Result should be read as 'IV proxy NULL' "
            "not 'native EEM IV NULL'; the rv30 secondary run controls for this by using "
            "a purely EEM-driven vol estimate."
        ),
    },
    "pit_spec": {
        "source": "experiments/k1116c/data/<alias>_weekly_pit.csv",
        "USEPU_publication_lag": "T+1 business day (daily cadence)",
        "WLEMU_publication_lag": "T+1 business day (daily cadence)",
        "NFCI_publication_lag": "Wed of W+1 (observed Fri W)",
        "ANFCI_publication_lag": "Wed of W+1 (observed Fri W)",
        "STLFSI_publication_lag": "Thu of W+1 (observed Fri W)",
        "construction": "at each W-FRI week-end F, take latest observation with release_date<=F",
    },
    "references": [
        "Baker, Bloom, Davis (2016) QJE - EPU index",
        "Brave, Butters (2011) Chicago Fed Letter 286 - NFCI Wed release",
        "Kliesen, Smith (2010) - STLFSI",
        "Croushore, Stark (2001) J Econometrics - vintage data importance",
        "Patton (2011) JoE - QLIKE proxy-robust loss",
        "Harvey, Leybourne, Newbold (1997) IJF - HLN DM correction",
        "Harvey (2016) RFS - |t|>3 multiple-testing threshold",
        "CBOE VIX methodology doc - S&P 500 implied volatility",
        "Aboura & Chevallier (2015) - emerging-market VIX spillovers",
    ],
}


# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------
def log(msg: str) -> None:
    ts = datetime.utcnow().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ---------------------------------------------------------------------
# Market data (weekly RV + native IV), per K1118 / K1116f / K1201 convention
# ---------------------------------------------------------------------
def fetch_asset_weekly(ticker: str, iv_ticker: str | None, iv_type: str = "close",
                       start: str = "2018-01-01", end: str = "2026-04-13") -> pd.DataFrame:
    """Fetch underlying weekly RV and native implied-vol proxy.

    iv_type:
      - "close": use Close of iv_ticker (primary; ^VIX for EEM here)
      - "rv30": 30-day rolling annualised realised vol of the underlying itself
    """
    import yfinance as yf

    log(f"Fetching {ticker} + IV={iv_ticker} (iv_type={iv_type})...")
    px = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if isinstance(px.columns, pd.MultiIndex):
        px.columns = px.columns.get_level_values(0)
    px = px[["Close"]].copy()
    px["r"] = np.log(px["Close"]).diff()

    px["week"] = px.index.to_period("W-FRI").to_timestamp("W-FRI")
    weekly = pd.DataFrame(index=px["week"].unique())
    weekly.index.name = "week"
    weekly["rv"] = px.groupby("week")["r"].apply(lambda x: np.sqrt(np.sum(x.dropna() ** 2)))
    weekly["r_n"] = px.groupby("week")["r"].count()
    min_n = 4
    weekly = weekly[weekly["r_n"] >= min_n].sort_index()

    if iv_type == "rv30":
        px["rv30"] = px["r"].rolling(30).apply(lambda x: np.sqrt(np.sum(x ** 2) * (252 / 30)))
        iv_daily = px[["rv30", "week"]].copy().rename(columns={"rv30": "iv"})
        iv_w = iv_daily.groupby("week").agg(iv_mean=("iv", "mean"), iv_last=("iv", "last"))
        iv_w = iv_w.dropna()
    else:
        iv = yf.download(iv_ticker, start=start, end=end, progress=False, auto_adjust=False)
        if isinstance(iv.columns, pd.MultiIndex):
            iv.columns = iv.columns.get_level_values(0)
        iv = iv[["Close"]].rename(columns={"Close": "iv"}).copy()
        iv["week"] = iv.index.to_period("W-FRI").to_timestamp("W-FRI")
        iv_w = iv.groupby("week").agg(iv_mean=("iv", "mean"), iv_last=("iv", "last"))

    df = weekly.join(iv_w, how="inner").dropna()
    log(f"  {ticker}: {len(df)} weeks, {df.index.min().date()} to {df.index.max().date()}")
    return df


# ---------------------------------------------------------------------
# Alt-data views (reuse K1116c cache)
# ---------------------------------------------------------------------
def load_altdata_two_views() -> dict[str, pd.DataFrame]:
    indicators = ["USEPU", "WLEMU", "NFCI", "ANFCI", "STLFSI"]
    wm_frames = []
    pit_frames = []
    for alias in indicators:
        rel_csv = K1116C_DATA / f"{alias}_with_release_date.csv"
        pit_csv = K1116C_DATA / f"{alias}_weekly_pit.csv"
        if not rel_csv.exists() or not pit_csv.exists():
            raise FileNotFoundError(
                f"Missing K1116c data for {alias}. Required file: {rel_csv} or {pit_csv}."
            )
        raw = pd.read_csv(rel_csv, parse_dates=["DATE", "RELEASE_DATE"])
        raw["week"] = raw["DATE"].dt.to_period("W-FRI").dt.to_timestamp("W-FRI")
        wm = raw.groupby("week")["VALUE"].mean().to_frame(alias)
        wm_frames.append(wm)

        pit = pd.read_csv(pit_csv, parse_dates=["week_end", "obs_date", "release_date"])
        pit_s = pit.set_index("week_end")["value"].to_frame(alias)
        pit_frames.append(pit_s)

    wm_df = wm_frames[0]
    for f in wm_frames[1:]:
        wm_df = wm_df.join(f, how="outer")
    wm_df = wm_df.sort_index().ffill(limit=2)

    pit_df = pit_frames[0]
    for f in pit_frames[1:]:
        pit_df = pit_df.join(f, how="outer")
    pit_df = pit_df.sort_index().ffill(limit=2)

    return {"weekly_mean": wm_df, "pit": pit_df}


# ---------------------------------------------------------------------
# Metrics / stats (identical to K1201 for direct comparability)
# ---------------------------------------------------------------------
def qlike(actual, pred):
    eps = 1e-10
    actual = np.maximum(np.asarray(actual, dtype=float), eps)
    pred = np.maximum(np.asarray(pred, dtype=float), eps)
    return float(np.mean(np.log(pred) + actual / pred))


def qlike_loss_series(actual: pd.Series, pred: pd.Series) -> pd.Series:
    eps = 1e-10
    a = np.maximum(actual.values.astype(float), eps)
    p = np.maximum(pred.values.astype(float), eps)
    return pd.Series(np.log(p) + a / p, index=actual.index)


def dm_hln(e1, e2, h=1):
    """Harvey-Leybourne-Newbold DM correction.

    Sign convention: e1=baseline loss, e2=challenger loss.
      positive t => challenger beats baseline
      negative t => baseline wins
    """
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
    corr = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    se = np.sqrt(gamma0 / n)
    t = (dbar / se) * corr
    p = 2 * (1 - st.t.cdf(abs(t), df=n - 1))
    return float(t), float(p), int(n)


# ---------------------------------------------------------------------
# Variant / panel builder
# ---------------------------------------------------------------------
def build_variant_panel(market: pd.DataFrame, wm: pd.DataFrame, pit: pd.DataFrame,
                        variant: str) -> pd.DataFrame:
    indicators = ["USEPU", "WLEMU", "NFCI", "ANFCI", "STLFSI"]
    if variant == "k1118_shift1":
        base = wm.copy()
        lags = {c: 1 for c in indicators}
    elif variant == "pit_shift0":
        base = pit.copy()
        lags = {c: 0 for c in indicators}
    elif variant == "pit_shift1":
        base = pit.copy()
        lags = {c: 1 for c in indicators}
    else:
        raise ValueError(variant)

    for c in indicators:
        if c in base.columns:
            base[f"{c}_signal"] = base[c].shift(lags[c])

    sig_cols = [f"{c}_signal" for c in indicators if c in base.columns]
    base = base[sig_cols]

    merged = market[["rv", "iv_mean"]].join(base, how="inner").dropna(subset=["rv", "iv_mean"])
    return merged


# ---------------------------------------------------------------------
# Model fitting
# ---------------------------------------------------------------------
def make_X(df_sub: pd.DataFrame, spec: str) -> pd.DataFrame:
    X = pd.DataFrame(index=df_sub.index)
    X["y_lag1"] = df_sub["rv"].shift(1)
    if spec == "base":
        pass
    elif spec == "iv":
        X["iv_lag1"] = df_sub["iv_mean"].shift(1)
    elif spec == "epu":
        X["USEPU_signal"] = df_sub.get("USEPU_signal")
        X["WLEMU_signal"] = df_sub.get("WLEMU_signal")
    elif spec == "finstress":
        X["NFCI_signal"] = df_sub.get("NFCI_signal")
        X["ANFCI_signal"] = df_sub.get("ANFCI_signal")
        X["STLFSI_signal"] = df_sub.get("STLFSI_signal")
    elif spec == "all":
        X["iv_lag1"] = df_sub["iv_mean"].shift(1)
        X["USEPU_signal"] = df_sub.get("USEPU_signal")
        X["WLEMU_signal"] = df_sub.get("WLEMU_signal")
        X["NFCI_signal"] = df_sub.get("NFCI_signal")
        X["ANFCI_signal"] = df_sub.get("ANFCI_signal")
        X["STLFSI_signal"] = df_sub.get("STLFSI_signal")
    else:
        raise ValueError(spec)
    return X


def fit_specs(df: pd.DataFrame, is_end: str, oos_start: str) -> dict:
    import statsmodels.api as sm

    df_is = df.loc[:is_end]
    df_oos = df.loc[oos_start:]
    specs = ["base", "iv", "epu", "finstress", "all"]
    out = {}

    for spec in specs:
        X_is = make_X(df_is, spec)
        y_is = df_is["rv"].loc[X_is.index]
        mask_is = X_is.notna().all(axis=1) & y_is.notna()
        X_is = X_is[mask_is]
        y_is = y_is[mask_is]

        X_is_sm = sm.add_constant(X_is, has_constant="add")
        model = sm.OLS(y_is, X_is_sm).fit()

        X_oos = make_X(df_oos, spec)
        mask_oos = X_oos.notna().all(axis=1)
        X_oos = X_oos[mask_oos]
        X_oos_sm = sm.add_constant(X_oos, has_constant="add").reindex(columns=X_is_sm.columns,
                                                                       fill_value=0.0)
        y_oos = df_oos["rv"].loc[X_oos.index]
        pred_oos = model.predict(X_oos_sm)

        valid = y_oos.notna() & pred_oos.notna()
        y_oos = y_oos[valid]
        pred_oos = pred_oos[valid]

        loss = qlike_loss_series(y_oos, pred_oos.clip(lower=1e-6))
        out[spec] = {
            "n_is": int(len(X_is)),
            "n_oos": int(len(y_oos)),
            "oos_qlike": float(loss.mean()),
            "oos_rmse": float(np.sqrt(np.mean((y_oos.values - pred_oos.values) ** 2))),
            "is_r2": float(model.rsquared),
            "coef": {k: float(v) for k, v in model.params.items()},
            "loss_series": loss,
        }
    return out


# ---------------------------------------------------------------------
# Per asset x per variant runner
# ---------------------------------------------------------------------
def run_asset_variant(asset_name: str, market: pd.DataFrame, wm: pd.DataFrame,
                       pit: pd.DataFrame, variant: str,
                       is_end: str = "2022-12-31", oos_start: str = "2023-01-01") -> dict:
    panel = build_variant_panel(market, wm, pit, variant)
    fits = fit_specs(panel, is_end=is_end, oos_start=oos_start)

    specs = ["base", "iv", "epu", "finstress", "all"]
    base_name = "iv"
    common_idx = None
    for sp in specs:
        idx = fits[sp]["loss_series"].index
        common_idx = idx if common_idx is None else common_idx.intersection(idx)

    base_loss = fits[base_name]["loss_series"].reindex(common_idx)
    dm_tbl = {}
    for sp in specs:
        if sp == base_name:
            continue
        ch_loss = fits[sp]["loss_series"].reindex(common_idx)
        t, p, n = dm_hln(base_loss.values, ch_loss.values)
        dm_tbl[f"iv_vs_{sp}"] = {
            "t_stat": t if not np.isnan(t) else None,
            "p_value": p if not np.isnan(p) else None,
            "n": n,
            "challenger_wins_harvey2016_t3": bool((not np.isnan(t)) and (t > 3.0)),
            "challenger_wins_t2": bool((not np.isnan(t)) and (t > 2.0)),
            "baseline_wins_harvey2016_t3": bool((not np.isnan(t)) and (t < -3.0)),
            "baseline_wins_t2": bool((not np.isnan(t)) and (t < -2.0)),
        }

    iv_q = fits[base_name]["oos_qlike"]
    alts = ["epu", "finstress", "all"]
    best_alt = min(alts, key=lambda s: fits[s]["oos_qlike"])
    best_q = fits[best_alt]["oos_qlike"]
    qlike_improv_pct = float((iv_q - best_q) / abs(iv_q) * 100) if abs(iv_q) > 1e-12 else 0.0

    any_challenger_t3 = any(v["challenger_wins_harvey2016_t3"] for v in dm_tbl.values())
    any_challenger_t2 = any(v["challenger_wins_t2"] for v in dm_tbl.values())
    baseline_beats_count = sum(v["baseline_wins_harvey2016_t3"] for v in dm_tbl.values())

    fits_out = {}
    for sp, v in fits.items():
        fits_out[sp] = {k: vv for k, vv in v.items() if k != "loss_series"}

    return {
        "variant": variant,
        "n_panel": int(len(panel)),
        "n_common_oos": int(len(common_idx)) if common_idx is not None else 0,
        "specs": fits_out,
        "dm_vs_iv": dm_tbl,
        "best_alt_spec": best_alt,
        "qlike_improvement_pct": qlike_improv_pct,
        "gates": {
            "any_challenger_wins_harvey_t3": bool(any_challenger_t3),
            "any_challenger_wins_t2": bool(any_challenger_t2),
            "baseline_beats_alt_harvey_t3_count": int(baseline_beats_count),
            "qlike_improvement_gt_5pct": bool(qlike_improv_pct > 5.0),
        },
    }


# ---------------------------------------------------------------------
# Integration: pull prior-experiment DM t for 7-asset panorama
# ---------------------------------------------------------------------
def _extract_t(dm_tbl: dict, spec: str) -> float | None:
    entry = dm_tbl.get(f"iv_vs_{spec}")
    if entry is None:
        return None
    v = entry.get("t_stat")
    return float(v) if v is not None else None


def load_prior_dm_t() -> dict:
    """Extract pit_shift0 DM t (vs IV baseline) for SPY / GLD / TLT / BTC / QQQ / USO."""
    panorama = {}

    # SPY from K1116c (format: dm_vs_vix_baseline[variant][spec] = {t, p, n, verdict})
    if K1116C_RESULTS.exists():
        try:
            with open(K1116C_RESULTS) as f:
                r = json.load(f)
            dm_root = r.get("dm_vs_vix_baseline") or {}
            pit = dm_root.get("pit_shift0") or {}
            if pit:
                def _t(sp):
                    v = pit.get(sp, {}).get("t")
                    return float(v) if v is not None else None
                panorama["SPY"] = {
                    "source": "K1116c",
                    "finstress_t": _t("finstress"),
                    "epu_t": _t("epu"),
                    "all_t": _t("all"),
                    "base_t": _t("base"),
                }
        except Exception as exc:
            log(f"  K1116c results parse error: {exc}")

    if "SPY" not in panorama:
        panorama["SPY"] = {
            "source": "K1116c README (pit_shift0)",
            "finstress_t": -3.001,
            "epu_t": -2.603,
            "all_t": -2.537,
            "base_t": -3.021,
        }

    # GLD / TLT / BTC from K1116f
    if K1116F_RESULTS.exists():
        try:
            with open(K1116F_RESULTS) as f:
                r = json.load(f)
            asset_res = r.get("asset_results", {})
            for ak in asset_res:
                vr = asset_res[ak].get("variants", {}).get("pit_shift0")
                if not vr or "error" in vr:
                    continue
                dm = vr.get("dm_vs_iv", {})
                panorama[ak] = {
                    "source": "K1116f",
                    "finstress_t": _extract_t(dm, "finstress"),
                    "epu_t": _extract_t(dm, "epu"),
                    "all_t": _extract_t(dm, "all"),
                    "base_t": _extract_t(dm, "base"),
                }
        except Exception as exc:
            log(f"  K1116f results parse error: {exc}")

    # QQQ / USO from K1201 (search across candidates)
    k1201_path = None
    for cand in K1201_RESULTS_CANDIDATES:
        if cand.exists():
            k1201_path = cand
            break
    if k1201_path is not None:
        try:
            with open(k1201_path) as f:
                r = json.load(f)
            asset_res = r.get("asset_results", {})
            for ak in asset_res:
                vr = asset_res[ak].get("variants", {}).get("pit_shift0")
                if not vr or "error" in vr:
                    continue
                dm = vr.get("dm_vs_iv", {})
                panorama[ak] = {
                    "source": "K1201",
                    "finstress_t": _extract_t(dm, "finstress"),
                    "epu_t": _extract_t(dm, "epu"),
                    "all_t": _extract_t(dm, "all"),
                    "base_t": _extract_t(dm, "base"),
                }
        except Exception as exc:
            log(f"  K1201 results parse error: {exc}")

    # Hardcoded fallback from K1201 README for QQQ / USO (if file not found)
    if "QQQ" not in panorama:
        panorama["QQQ"] = {
            "source": "K1201 README (pit_shift0)",
            "finstress_t": -2.439,
            "epu_t": -1.967,
            "all_t": -1.967,
            "base_t": -2.186,
        }
    if "USO" not in panorama:
        panorama["USO"] = {
            "source": "K1201 README (pit_shift0)",
            "finstress_t": -2.584,
            "epu_t": -5.596,
            "all_t": -3.735,
            "base_t": -3.049,
        }

    return panorama


# ---------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------
def plot_dm_bar_eem(dm_tbl: dict, variant: str, out_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    specs = ["base", "epu", "finstress", "all"]
    vals = [dm_tbl.get(f"iv_vs_{sp}", {}).get("t_stat") for sp in specs]
    vals = [v if v is not None else np.nan for v in vals]

    fig, ax = plt.subplots(figsize=(6.0, 3.8))
    colors = []
    for v in vals:
        if np.isnan(v):
            colors.append("#cccccc")
        elif v > 3:
            colors.append("#2ca02c")  # challenger wins
        elif v > 2:
            colors.append("#98df8a")
        elif v < -3:
            colors.append("#d62728")  # baseline wins
        elif v < -2:
            colors.append("#ff9896")
        else:
            colors.append("#7f7f7f")

    bars = ax.bar(specs, vals, color=colors)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.axhline(3, color="green", linewidth=0.8, linestyle="--", label="Harvey +3")
    ax.axhline(-3, color="red", linewidth=0.8, linestyle="--", label="Harvey -3")
    for b, v in zip(bars, vals):
        if not np.isnan(v):
            ax.text(b.get_x() + b.get_width() / 2, v + (0.12 if v >= 0 else -0.35),
                    f"{v:+.2f}", ha="center", va="bottom" if v >= 0 else "top", fontsize=9)
    ax.set_ylabel("DM t-stat (positive = alt beats IV baseline)")
    ax.set_title(f"K1203 — EEM DM t vs ^VIX baseline ({variant})\n"
                 "negative = ^VIX wins; Harvey |t|>3 gate")
    ax.legend(loc="lower right", fontsize=8)
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    log(f"  saved {out_path.name}")


def plot_dm_heatmap_7asset(panorama: dict, out_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    order = ["SPY", "GLD", "TLT", "BTC-USD", "QQQ", "USO", "EEM"]
    order = [a for a in order if a in panorama]
    specs = ["base", "epu", "finstress", "all"]

    data = np.full((len(order), len(specs)), np.nan)
    for i, a in enumerate(order):
        rec = panorama[a]
        for j, sp in enumerate(specs):
            v = rec.get(f"{sp}_t")
            if v is not None:
                data[i, j] = v

    fig, ax = plt.subplots(figsize=(7.5, max(3.0, 0.75 * len(order) + 1.2)))
    im = ax.imshow(data, cmap="RdBu_r", vmin=-6, vmax=6, aspect="auto")
    ax.set_xticks(range(len(specs)))
    ax.set_xticklabels(specs, rotation=30, ha="right")
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(order)
    for i in range(len(order)):
        for j in range(len(specs)):
            val = data[i, j]
            if not np.isnan(val):
                ax.text(j, i, f"{val:+.2f}", ha="center", va="center",
                        color="white" if abs(val) > 2.5 else "black", fontsize=9)
    ax.set_title(
        f"K1203 — Paper 4 panorama DM t vs IV baseline (pit_shift0; {len(order)}/7 assets)\n"
        "positive = alt-data beats IV; Harvey |t|>3",
        fontsize=10,
    )
    fig.colorbar(im, ax=ax, shrink=0.85, label="DM t-stat")
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    log(f"  saved {out_path.name}")


def plot_qlike_improvement_7asset(eem_q: float, out_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Prior-experiment QLIKE improvements from each README
    combined = {
        "SPY": -1.70,  # K1116c pit_shift0 best-alt vs VIX (approx, reported)
        "GLD": -0.63,
        "TLT": 0.50,
        "BTC-USD": 0.23,
        "QQQ": -0.56,
        "USO": -0.84,
        "EEM": eem_q,
    }
    order = ["SPY", "GLD", "TLT", "BTC-USD", "QQQ", "USO", "EEM"]
    vals = [combined[a] for a in order]

    fig, ax = plt.subplots(figsize=(8.0, 4.0))
    bars = ax.bar(order, vals, color=["#d62728" if v < 0 else "#2ca02c" if v > 5 else "#7f7f7f" for v in vals])
    ax.axhline(0, color="black", linewidth=0.8)
    ax.axhline(5, color="green", linewidth=0.8, linestyle="--", label="5% gate")
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + (0.1 if v >= 0 else -0.3),
                f"{v:+.2f}%", ha="center", va="bottom" if v >= 0 else "top", fontsize=9)
    ax.set_ylabel("QLIKE improvement (%) — best alt vs IV baseline")
    ax.set_title("K1203 — Paper 4 panorama: QLIKE improvement by asset (pit_shift0; 7/7)")
    ax.legend()
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    log(f"  saved {out_path.name}")


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
def main() -> None:
    # Two EEM runs: primary with ^VIX, secondary with rv30 (robustness)
    asset_configs = [
        ("EEM", "EEM", "^VIX", "close"),       # primary: VIX spillover proxy
        ("EEM_rv30", "EEM", None, "rv30"),      # robustness: internal 30-day RV
    ]

    log("Loading alt-data PIT + weekly-mean views from K1116c cache...")
    views = load_altdata_two_views()
    wm = views["weekly_mean"]
    pit = views["pit"]
    log(f"  weekly_mean panel: {wm.shape}, PIT panel: {pit.shape}")

    asset_results: dict = {}
    variants = ["k1118_shift1", "pit_shift0", "pit_shift1"]

    for name, ticker, iv_ticker, iv_type in asset_configs:
        try:
            market = fetch_asset_weekly(ticker, iv_ticker, iv_type=iv_type)
        except Exception as exc:
            log(f"  {name}: market fetch FAILED: {exc}")
            asset_results[name] = {"error": str(exc)}
            continue

        variant_results = {}
        for v in variants:
            try:
                variant_results[v] = run_asset_variant(name, market, wm, pit, v)
                d = variant_results[v]
                dm = d["dm_vs_iv"]
                log(
                    f"  [{name}/{v}] best_alt={d['best_alt_spec']} "
                    f"qlike_imp%={d['qlike_improvement_pct']:+.2f} "
                    f"DM finstress t={dm['iv_vs_finstress']['t_stat']:+.2f} "
                    f"n_oos={d['n_common_oos']}"
                )
            except Exception as exc:
                log(f"  [{name}/{v}] FAILED: {exc}")
                variant_results[v] = {"error": str(exc)}

        asset_results[name] = {
            "ticker": ticker,
            "iv_ticker": iv_ticker or "rv30(internal)",
            "iv_type": iv_type,
            "variants": variant_results,
        }

    RESULTS["asset_results"] = asset_results

    # EEM-only gates (primary = ^VIX run)
    eem_primary = asset_results.get("EEM", {}).get("variants", {})
    eem_rv30 = asset_results.get("EEM_rv30", {}).get("variants", {})
    synth = {}
    for v in variants:
        vr_primary = eem_primary.get(v)
        vr_rv30 = eem_rv30.get(v)
        synth[v] = {
            "primary_vix": {
                "dm_finstress_t": None,
                "dm_epu_t": None,
                "dm_all_t": None,
                "dm_base_t": None,
                "any_challenger_wins_harvey_t3": None,
                "qlike_improvement_pct": None,
            },
            "robustness_rv30": {
                "dm_finstress_t": None,
                "dm_epu_t": None,
                "dm_all_t": None,
                "dm_base_t": None,
                "any_challenger_wins_harvey_t3": None,
                "qlike_improvement_pct": None,
            },
        }
        if vr_primary and "error" not in vr_primary:
            dm = vr_primary["dm_vs_iv"]
            synth[v]["primary_vix"] = {
                "dm_finstress_t": _extract_t(dm, "finstress"),
                "dm_epu_t": _extract_t(dm, "epu"),
                "dm_all_t": _extract_t(dm, "all"),
                "dm_base_t": _extract_t(dm, "base"),
                "any_challenger_wins_harvey_t3": vr_primary["gates"]["any_challenger_wins_harvey_t3"],
                "qlike_improvement_pct": vr_primary["qlike_improvement_pct"],
            }
        if vr_rv30 and "error" not in vr_rv30:
            dm = vr_rv30["dm_vs_iv"]
            synth[v]["robustness_rv30"] = {
                "dm_finstress_t": _extract_t(dm, "finstress"),
                "dm_epu_t": _extract_t(dm, "epu"),
                "dm_all_t": _extract_t(dm, "all"),
                "dm_base_t": _extract_t(dm, "base"),
                "any_challenger_wins_harvey_t3": vr_rv30["gates"]["any_challenger_wins_harvey_t3"],
                "qlike_improvement_pct": vr_rv30["qlike_improvement_pct"],
            }
    RESULTS["eem_synthesis"] = synth

    # 7-asset panorama: SPY (K1116c) + GLD/TLT/BTC (K1116f) + QQQ/USO (K1201) + EEM (K1203 primary)
    panorama = load_prior_dm_t()
    # Inject EEM primary (^VIX) run
    eem_pit0 = eem_primary.get("pit_shift0")
    if eem_pit0 and "error" not in eem_pit0:
        dm = eem_pit0["dm_vs_iv"]
        panorama["EEM"] = {
            "source": "K1203 (^VIX primary)",
            "finstress_t": _extract_t(dm, "finstress"),
            "epu_t": _extract_t(dm, "epu"),
            "all_t": _extract_t(dm, "all"),
            "base_t": _extract_t(dm, "base"),
        }
    RESULTS["panorama_7asset_pit_shift0"] = panorama
    RESULTS["panorama_coverage"] = {
        "covered_assets": sorted(panorama.keys()),
        "paper4_universe_size": 7,
        "covered_count": len(panorama),
        "missing_assets": [a for a in ["SPY", "GLD", "TLT", "BTC-USD", "QQQ", "USO", "EEM"]
                          if a not in panorama],
        "status": "COMPLETE" if len(panorama) >= 7 else "PARTIAL",
    }

    # Verdict assembly
    pit_pass_primary = []
    if eem_pit0 and "error" not in eem_pit0:
        if eem_pit0["gates"]["any_challenger_wins_harvey_t3"]:
            pit_pass_primary.append("EEM")

    # 7-asset panorama outliers (any spec > +3)
    panorama_pass_t3 = []
    for a in panorama:
        for sp in ["finstress", "epu", "all", "base"]:
            v = panorama[a].get(f"{sp}_t")
            if v is not None and v > 3.0:
                panorama_pass_t3.append((a, sp, v))
                break

    # TLT-only outlier check (known from K1116f)
    outlier_assets = sorted(set(a for a, _, _ in panorama_pass_t3))

    if len(panorama_pass_t3) == 0:
        verdict = (
            "UNIVERSAL_NULL_7_OF_7 — Every asset in SPY/GLD/TLT/BTC/QQQ/USO/EEM fails to "
            "show any alt-data spec beating its IV baseline at Harvey |t|>3 under PIT "
            "alignment (pit_shift0). The 7-asset panorama confirms 'native IV sufficiency' "
            "for the Paper 4 universe."
        )
    elif outlier_assets == ["TLT"]:
        verdict = (
            "UNIVERSAL_NULL_7_OF_7 with TLT caveat — SPY/GLD/BTC/QQQ/USO/EEM all confirm "
            "NULL under PIT; only TLT finstress pit_shift0 gives a marginal +3.74 (K1116f) "
            "which was already shown lag-sensitive (collapses to +2.00 at pit_shift1) and "
            "fails QLIKE 5% gate. Paper 4 'native IV sufficient' claim is 6/7 robust + 1 "
            "non-structural outlier."
        )
    else:
        verdict = (
            f"MIXED_7_OF_7 — panorama outliers at |t|>3: {panorama_pass_t3}. "
            "Needs per-asset narrative before Paper 4 body.tex rewrite."
        )

    # Paper 4 body.tex rewrite gate (CLAUDE.md narrative-state-machine)
    # Need: ≥ 3 complementary experiments, 7/7 PIT coverage, no unexplained outliers.
    complementary_experiment_count = 4  # K1116c, K1116f, K1201, K1203
    gate_criteria = {
        "coverage_7_of_7": len(panorama) >= 7,
        "complementary_experiments_ge_3": complementary_experiment_count >= 3,
        "no_unexplained_outliers": outlier_assets in [[], ["TLT"]],
        "eem_primary_null": (
            eem_pit0 is not None
            and "error" not in eem_pit0
            and not eem_pit0["gates"]["any_challenger_wins_harvey_t3"]
        ),
    }
    gate_unlocked = all(gate_criteria.values())
    RESULTS["paper4_body_rewrite_gate"] = {
        "status": "UNLOCKED" if gate_unlocked else "STILL_CAVEAT",
        "criteria": gate_criteria,
        "notes": (
            "UNLOCKED means main thread may proceed to Paper 4 body.tex rewrite per "
            "CLAUDE.md §automation narrative-state-machine. STILL_CAVEAT means further "
            "follow-up needed (see criteria)."
        ),
    }
    RESULTS["verdict"] = verdict

    RESULTS["reference_numbers"] = {
        "K1116c_SPY_PIT_shift0_finstress_t": -3.001,
        "K1116c_SPY_PIT_shift0_epu_t": -2.603,
        "K1116f_GLD_PIT_shift0_finstress_t": -3.341,
        "K1116f_TLT_PIT_shift0_finstress_t": 3.743,
        "K1116f_BTC_PIT_shift0_finstress_t": 1.370,
        "K1201_QQQ_PIT_shift0_finstress_t": -2.439,
        "K1201_USO_PIT_shift0_finstress_t": -2.584,
    }

    RESULTS["finished_utc"] = datetime.utcnow().isoformat() + "Z"

    with open(OUT_DIR / "k1203_results.json", "w") as f:
        json.dump(RESULTS, f, indent=2, default=str)
    log(f"Saved {OUT_DIR / 'k1203_results.json'}")

    # Plots
    try:
        if eem_pit0 and "error" not in eem_pit0:
            plot_dm_bar_eem(eem_pit0["dm_vs_iv"], "pit_shift0",
                            OUT_DIR / "k1203_dm_bar.png")
        plot_dm_heatmap_7asset(panorama, OUT_DIR / "k1203_dm_heatmap_7asset.png")
        eem_q = (eem_pit0["qlike_improvement_pct"]
                 if eem_pit0 and "error" not in eem_pit0 else 0.0)
        plot_qlike_improvement_7asset(eem_q, OUT_DIR / "k1203_qlike_improvement_7asset.png")
    except Exception as exc:
        log(f"Plot error: {exc}")

    # Console summary
    print("\n" + "=" * 90)
    print("K1203 SUMMARY — EEM PIT + 7-asset panorama complete")
    print("=" * 90)
    print(f"Verdict: {verdict}")
    print(f"Paper 4 body.tex rewrite gate: {RESULTS['paper4_body_rewrite_gate']['status']}\n")
    for name, rec in asset_results.items():
        if "variants" not in rec:
            print(f"[{name}] ERROR: {rec.get('error')}")
            continue
        print(f"[{name}]  ticker={rec['ticker']}  IV={rec['iv_ticker']}")
        for v, d in rec["variants"].items():
            if "error" in d:
                print(f"  {v}: ERROR {d['error']}")
                continue
            dm = d["dm_vs_iv"]
            print(
                f"  {v:14s}  n_oos={d['n_common_oos']}  best_alt={d['best_alt_spec']:<10s}  "
                f"qlike_imp%={d['qlike_improvement_pct']:+.2f}"
            )
            for key in ["iv_vs_base", "iv_vs_epu", "iv_vs_finstress", "iv_vs_all"]:
                entry = dm.get(key)
                if entry is None or entry["t_stat"] is None:
                    continue
                tag = (
                    "CH>3" if entry["challenger_wins_harvey2016_t3"]
                    else ("CH>2" if entry["challenger_wins_t2"]
                          else ("B<-3" if entry["baseline_wins_harvey2016_t3"]
                                else ("B<-2" if entry["baseline_wins_t2"] else "ns")))
                )
                print(f"    {key:<20}  t={entry['t_stat']:+.3f}  p={entry['p_value']:.4f}  [{tag}]")

    print("\nPanorama (7-asset, pit_shift0 DM t vs IV baseline):")
    for a in ["SPY", "GLD", "TLT", "BTC-USD", "QQQ", "USO", "EEM"]:
        if a in panorama:
            rec = panorama[a]
            print(
                f"  {a:<8}  src={rec['source']:<30}  "
                f"base={_fmt(rec.get('base_t'))}  epu={_fmt(rec.get('epu_t'))}  "
                f"finstress={_fmt(rec.get('finstress_t'))}  all={_fmt(rec.get('all_t'))}"
            )
        else:
            print(f"  {a:<8}  NOT AVAILABLE")


def _fmt(v):
    if v is None:
        return "  n/a"
    return f"{v:+.3f}"


if __name__ == "__main__":
    main()
