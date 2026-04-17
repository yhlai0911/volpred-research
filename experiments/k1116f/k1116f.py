"""
K1116f: Cross-asset PIT (point-in-time) alignment extension.

Goal: Apply the K1116c PIT release-calendar alignment framework to the K1118 cross-asset
cells (GLD / TLT / BTC-USD). K1118 used shift(1) as a simple weekly lag that can still
leak publication timing (e.g. NFCI observed Fri W is released Wed W+1, so shift(1) at
weekly W-FRI frequency leaks 5 days of data). K1116c confirmed SPY alt-data null under
PIT. Question: does the SPY NULL generalize to GLD / TLT / BTC under strict PIT alignment?

Design decisions:
  * Reuse the K1116c PIT CSVs (`experiments/k1116c/data/<alias>_weekly_pit.csv`). They
    embed the indicator-specific publication lag (USEPU/WLEMU T+1bday, NFCI/ANFCI Wed W+1,
    STLFSI Thu W+1) into the PIT value available at each Friday F.
  * Baseline family is weekly W-FRI AR(1) + native IV (per K1118), since that is the
    K1118 baseline being extended. HAR-RV(1/5/22) is natural at daily frequency but
    K1118/K1116c are weekly; converting cross-asset to daily HAR would require re-fetching
    the full daily panel and is *not* what "extend K1116c PIT to K1118 cells" means.
    We therefore keep K1118's weekly AR(1)+IV baseline spec and swap the alt-data lag
    convention.
  * Five specs (base / iv / epu / finstress / all) match K1118 exactly.
  * Two lag variants: K1118 original (shift(1) on weekly mean) and K1116c PIT (shift(0)
    on PIT release-calendar panel). The PIT variant is the primary test.
  * DM-HLN with Harvey (1997) correction; Harvey (2016) |t|>3.0 as significance gate
    (project policy from research_program.md), plus the softer |t|>2 K1118 gate reported
    for comparability.
  * Seed 42. OOS 2023-01-01 onward (>=170 weeks common) per K1118 convention.

Scientific scope:
  The question is whether publication-timing artefacts in K1118 shift(1) might have
  *overstated* alt-data power; tightening to true PIT should weakly *worsen* alt-data
  relative to the native-IV baseline (no asset should suddenly pass a gate it failed
  under shift(1), and the marginal finstress t for TLT in K1118, +3.74 at shift(1),
  should pull back under PIT).

Output:
  * k1116f_results.json: per asset x per variant x per spec QLIKE + DM t/p + gate flags,
    plus cross-asset synthesis, plus comparison to K1116c SPY and K1118 shift(1).
  * k1116f_dm_heatmap.png: 3 assets x 4 alt-spec DM t bars with Harvey thresholds.
  * k1116f_qlike_ratio.png: aug/baseline QLIKE ratio per asset x spec.

References: inherit K1116c and K1118 citation stacks.
Author: VolPred Research System (worktree agent-a458447b), 2026-04-17.
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
K1116C_DATA = HERE.parent / "k1116c" / "data"
OUT_DIR = HERE

RESULTS: dict = {
    "experiment_id": "K1116f",
    "title": "PIT (point-in-time) alignment extended to GLD/TLT/BTC cross-asset cells",
    "started_utc": datetime.utcnow().isoformat() + "Z",
    "seed": 42,
    "predecessor_experiments": {
        "K1116c": "SPY weekly, PIT + 6 lag variants, robust NULL",
        "K1118": "GLD/TLT/BTC weekly with shift(1), NULL across 3 assets (TLT M4 marginal +3.74 t but QLIKE <5%)",
        "K1116b": "SPY weekly, shift(2) publication-delay correction",
        "K1116": "SPY weekly original shift(1)",
    },
    "scope_note": (
        "Extending K1116c PIT framework to cross-asset cells. Weekly AR(1)+IV "
        "baseline (per K1118 convention). HAR-RV(1/5/22) is daily-native; the K1118 "
        "stack is weekly so we keep weekly AR(1)+IV for direct comparability."
    ),
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
        "Liu (2021) - BTC retail sentiment (K1118 H3)",
    ],
}


# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------
def log(msg: str) -> None:
    ts = datetime.utcnow().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ---------------------------------------------------------------------
# Market data (weekly RV + native IV), per K1118 convention
# ---------------------------------------------------------------------
def fetch_asset_weekly(ticker: str, iv_ticker: str | None, iv_type: str = "close",
                       start: str = "2018-01-01", end: str = "2026-04-13") -> pd.DataFrame:
    """Fetch underlying weekly RV and native implied-vol proxy, identical to K1118.

    Weekly W-FRI aggregation. RV = sqrt(sum(r^2)) across the week.
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
    min_n = 4 if ticker != "BTC-USD" else 5
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
# Alt-data views: shift1 weekly-mean (K1118) and PIT (K1116c)
# ---------------------------------------------------------------------
def load_altdata_two_views() -> dict[str, pd.DataFrame]:
    """Return dict with keys:
      'weekly_mean' -> K1118-style weekly mean panel (to be lagged with shift(1))
      'pit'         -> K1116c PIT panel (already release-calendar aligned; shift(0))
    """
    indicators = ["USEPU", "WLEMU", "NFCI", "ANFCI", "STLFSI"]
    wm_frames = []
    pit_frames = []
    for alias in indicators:
        rel_csv = K1116C_DATA / f"{alias}_with_release_date.csv"
        pit_csv = K1116C_DATA / f"{alias}_weekly_pit.csv"
        if not rel_csv.exists() or not pit_csv.exists():
            raise FileNotFoundError(
                f"Missing K1116c data for {alias}. Required file: {rel_csv} or {pit_csv}. "
                "Run experiments/k1116c/k1116c_fetch_alfred.py first."
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
# Metrics / stats
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
      positive t => baseline loss > challenger => challenger beats baseline
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
    """Merge market (rv + iv_mean) with alt-data under a specific lag variant.

    Variants:
      * 'k1118_shift1': weekly-mean panel; alt signal = alt.shift(1)  [K1118 original]
      * 'pit_shift0':   PIT panel; alt signal = alt.shift(0)  [K1116c PIT primary]
      * 'pit_shift1':   PIT panel; alt signal = alt.shift(1)  [extra safety]
    """
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

    # DM tests vs iv baseline
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

    # QLIKE improvement pct (best alt vs iv baseline)
    iv_q = fits[base_name]["oos_qlike"]
    alts = ["epu", "finstress", "all"]
    best_alt = min(alts, key=lambda s: fits[s]["oos_qlike"])
    best_q = fits[best_alt]["oos_qlike"]
    qlike_improv_pct = float((iv_q - best_q) / abs(iv_q) * 100) if abs(iv_q) > 1e-12 else 0.0

    # Gates
    any_challenger_t3 = any(v["challenger_wins_harvey2016_t3"] for v in dm_tbl.values())
    any_challenger_t2 = any(v["challenger_wins_t2"] for v in dm_tbl.values())
    baseline_beats_count = sum(v["baseline_wins_harvey2016_t3"] for v in dm_tbl.values())

    # trim loss_series out of json payload (keep in-memory only)
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
# Plots
# ---------------------------------------------------------------------
def plot_dm_heatmap(asset_results: dict, out_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    assets = list(asset_results.keys())
    specs = ["base", "epu", "finstress", "all"]
    variants = ["k1118_shift1", "pit_shift0", "pit_shift1"]

    fig, axes = plt.subplots(1, len(assets), figsize=(5.2 * len(assets), 4.6), sharey=True)
    if len(assets) == 1:
        axes = [axes]

    for ax, asset in zip(axes, assets):
        data = np.full((len(variants), len(specs)), np.nan)
        for i, v in enumerate(variants):
            d = asset_results[asset]["variants"].get(v)
            if d is None:
                continue
            dm_tbl = d["dm_vs_iv"]
            for j, sp in enumerate(specs):
                entry = dm_tbl.get(f"iv_vs_{sp}")
                if entry is not None and entry["t_stat"] is not None:
                    data[i, j] = entry["t_stat"]
        im = ax.imshow(data, cmap="RdBu_r", vmin=-5, vmax=5, aspect="auto")
        ax.set_xticks(range(len(specs)))
        ax.set_xticklabels(specs, rotation=30, ha="right")
        ax.set_yticks(range(len(variants)))
        ax.set_yticklabels(variants)
        ax.set_title(f"{asset}")
        for i in range(len(variants)):
            for j in range(len(specs)):
                val = data[i, j]
                if not np.isnan(val):
                    ax.text(j, i, f"{val:+.2f}", ha="center", va="center",
                            color="white" if abs(val) > 2.5 else "black", fontsize=8)
    fig.suptitle("K1116f — DM t vs IV baseline (positive = alt beats IV; Harvey |t|>3)", fontsize=11)
    fig.colorbar(im, ax=axes, shrink=0.85, label="DM t-stat")
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    log(f"  saved {out_path.name}")


def plot_qlike_ratio(asset_results: dict, out_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    assets = list(asset_results.keys())
    variants = ["k1118_shift1", "pit_shift0"]
    specs = ["epu", "finstress", "all"]

    fig, axes = plt.subplots(1, len(assets), figsize=(5.2 * len(assets), 4.2), sharey=True)
    if len(assets) == 1:
        axes = [axes]
    x = np.arange(len(specs))
    w = 0.35
    for ax, asset in zip(axes, assets):
        for k, v in enumerate(variants):
            d = asset_results[asset]["variants"].get(v)
            if d is None:
                continue
            iv_q = d["specs"]["iv"]["oos_qlike"]
            ratios = [d["specs"][s]["oos_qlike"] / iv_q if abs(iv_q) > 1e-12 else np.nan for s in specs]
            ax.bar(x + (k - 0.5) * w, ratios, w, label=v)
        ax.axhline(1.0, color="black", linewidth=0.8, linestyle="--")
        ax.set_xticks(x)
        ax.set_xticklabels(specs)
        ax.set_title(asset)
        ax.set_ylabel("OOS QLIKE / IV baseline QLIKE")
        ax.legend(fontsize=8)
    fig.suptitle("K1116f — Alt-spec QLIKE / IV baseline (>1 = worse than IV)", fontsize=11)
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    log(f"  saved {out_path.name}")


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
def main() -> None:
    asset_configs = [
        ("GLD", "GLD", "^GVZ", "close"),
        ("TLT", "TLT", "^MOVE", "close"),
        ("BTC-USD", "BTC-USD", None, "rv30"),
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
            "iv_ticker": iv_ticker,
            "iv_type": iv_type,
            "variants": variant_results,
        }

    RESULTS["asset_results"] = asset_results

    # Cross-asset synthesis: for each variant, count assets passing Harvey |t|>3
    synth = {}
    for v in variants:
        assets_pass_t3 = []
        assets_pass_t2 = []
        baseline_wins_count = 0
        per_asset_finstress_t = {}
        for name, rec in asset_results.items():
            if "variants" not in rec:
                continue
            vr = rec["variants"].get(v)
            if not vr or "error" in vr:
                continue
            if vr["gates"]["any_challenger_wins_harvey_t3"]:
                assets_pass_t3.append(name)
            if vr["gates"]["any_challenger_wins_t2"]:
                assets_pass_t2.append(name)
            baseline_wins_count += vr["gates"]["baseline_beats_alt_harvey_t3_count"]
            fs = vr["dm_vs_iv"].get("iv_vs_finstress")
            per_asset_finstress_t[name] = fs["t_stat"] if fs else None
        synth[v] = {
            "assets_pass_harvey_t3": assets_pass_t3,
            "assets_pass_t2": assets_pass_t2,
            "baseline_wins_harvey_t3_total": int(baseline_wins_count),
            "finstress_dm_t_by_asset": per_asset_finstress_t,
        }
    RESULTS["cross_asset_synthesis"] = synth

    # Spearman rank corr on finstress DM t across assets (null-direction consistency)
    try:
        from scipy.stats import spearmanr
        pit_ts = [synth["pit_shift0"]["finstress_dm_t_by_asset"].get(a) for a in ["GLD", "TLT", "BTC-USD"]]
        sh1_ts = [synth["k1118_shift1"]["finstress_dm_t_by_asset"].get(a) for a in ["GLD", "TLT", "BTC-USD"]]
        rho, p = spearmanr(pit_ts, sh1_ts, nan_policy="omit")
        RESULTS["spearman_pit_vs_shift1_finstress_t"] = {
            "rho": float(rho) if rho is not None else None,
            "p_value": float(p) if p is not None else None,
            "interpretation": (
                "positive rho => PIT and shift(1) agree on asset-level finstress ranking => "
                "NULL direction consistent; negative => PIT disagrees with shift(1) interpretation."
            ),
        }
    except Exception as exc:
        RESULTS["spearman_pit_vs_shift1_finstress_t"] = {"error": str(exc)}

    # Universal vs asset-specific verdict
    pit_pass = synth["pit_shift0"]["assets_pass_harvey_t3"]
    if len(pit_pass) == 0:
        verdict = (
            "UNIVERSAL_NULL — No asset (GLD/TLT/BTC) shows any alt-data spec beating "
            "native IV at Harvey |t|>3 under PIT alignment. Confirms K1116c SPY NULL "
            "generalizes across asset classes."
        )
    elif len(pit_pass) < 3:
        verdict = (
            f"ASSET_SPECIFIC — Only {pit_pass} show alt-data DM>3 under PIT; other "
            "assets remain NULL. Paper 4 narrative needs per-asset treatment."
        )
    else:
        verdict = "ALT_UNIVERSAL_PASS — Unexpected: all 3 assets show alt-data >3 under PIT."
    RESULTS["verdict"] = verdict

    # Comparison to K1116c SPY and K1118 shift(1) numbers
    RESULTS["reference_numbers"] = {
        "K1116c_SPY_PIT_shift0_finstress_t": -3.001,
        "K1116c_SPY_PIT_shift0_all_t": -2.537,
        "K1116c_SPY_PIT_shift0_epu_t": -2.603,
        "K1118_GLD_shift1_finstress_t": "-3.34 (baseline beats M4; from K1118_results.json)",
        "K1118_TLT_shift1_finstress_t": "+3.74 (marginal challenger win at shift1 but QLIKE<5%)",
        "K1118_BTC_shift1_finstress_t": "+1.37 (ns)",
    }

    RESULTS["finished_utc"] = datetime.utcnow().isoformat() + "Z"

    with open(OUT_DIR / "k1116f_results.json", "w") as f:
        json.dump(RESULTS, f, indent=2, default=str)
    log(f"Saved {OUT_DIR / 'k1116f_results.json'}")

    # Plots
    try:
        plot_dm_heatmap(asset_results, OUT_DIR / "k1116f_dm_heatmap.png")
        plot_qlike_ratio(asset_results, OUT_DIR / "k1116f_qlike_ratio.png")
    except Exception as exc:
        log(f"Plot error: {exc}")

    # Summary print
    print("\n" + "=" * 90)
    print("K1116f SUMMARY — Cross-asset PIT alignment vs K1118 shift(1)")
    print("=" * 90)
    print(f"Verdict: {verdict}\n")
    for name, rec in asset_results.items():
        if "variants" not in rec:
            print(f"[{name}] ERROR: {rec.get('error')}")
            continue
        print(f"[{name}]")
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
    print("\nCross-asset synthesis:")
    for v, d in synth.items():
        print(f"  {v}: harvey>3 pass = {d['assets_pass_harvey_t3']}, "
              f"|t|>2 pass = {d['assets_pass_t2']}, "
              f"baseline>3 wins total = {d['baseline_wins_harvey_t3_total']}")


if __name__ == "__main__":
    main()
