"""
K1118: Cross-asset alt-data sufficiency test — does VIX-style implied vol sufficiency generalize?

Hypothesis (H1, universal sufficiency): If native implied-vol (VIX/GVZ/MOVE/BVOL-proxy) is
    sufficient for weekly RV prediction across GLD, TLT, BTC (just as K1116 showed for SPY),
    then EPU/NFCI add no OOS value in any asset -> strong multi-asset null -> paper
    contribution strengthens from "SPY-specific" to "universal".
H2 (asset-specific niche): At least 1 asset has M3 or M4 OOS DM t < -2 vs native-IV
    baseline (i.e., alt-data helps, implied vol NOT sufficient).
H3 (retail/sentiment channel): BTC (most retail-driven) might show M5 hybrid edge.

Design: 3 assets x 5 models, same framework as K1116.
  - GLD (native IV: GVZ)
  - TLT (native IV: MOVE)
  - BTC-USD (native IV: 30-day rolling RV as proxy; DVOL/BVOL not on yfinance)

Note on Taiwan (0050.TW):
  VIXTWN has data gap 2022-2025-11 (TAIFEX legacy 2007-2021 + new CSV 2025-12+).
  2018-2026 weekly window infeasible. K1098 already tested VIXTWN -> 0050.TW NULL.
  We note this in conclusions without re-running.

Model specs (per asset):
  M1: AR(1) baseline (only y_lag1)
  M2: AR(1) + native IV (VIX/GVZ/MOVE/BTC-RV30)   -- sufficiency baseline
  M3: AR(1) + EPU composite (USEPU + WLEMU)
  M4: AR(1) + financial stress (NFCI, ANFCI, STLFSI4)
  M5: AR(1) + native IV + EPU + fin-stress (hybrid)

Baseline for DM test: M2 (native IV), same as K1116.

Eval gates (K1100g_d1 rule):
  - DM-HLN |t| > 2 (challenger beats baseline when t > +2 ; negative means baseline wins)
  - QLIKE improvement > 5% (best alt model vs native-IV baseline)
  - Sub-period stability >= 2/3 years (challenger winning)

Data sources:
  yfinance: GLD, TLT, BTC-USD, ^GVZ, ^MOVE, ^VIX
  FRED: USEPUINDXD, WLEMUINDXD, NFCI, ANFCI, STLFSI4
Period: 2018-01 to 2026-04 weekly (W-FRI aggregation).
IS: 2018-2022 ; OOS: 2023-2026.

References:
  Baker, Bloom, Davis (2016) QJE - EPU
  Brave, Butters (2011) - NFCI
  Kliesen, Smith (2010) - STLFSI
  Patton (2011) QLIKE
  Harvey, Leybourne, Newbold (1997) - HLN DM correction
  Liu (2021) - BTC retail sentiment (motivates H3 for BTC)
  K1116 - SPY EPU+NFCI+STLFSI null (direct predecessor)
  K1098 - VIXTWN sufficient for 0050.TW (Taiwan parallel)
  K473/K750/K789 - Google Trends null for SPY
"""
import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

OUT_DIR = Path(__file__).parent
RESULTS = {
    "experiment_id": "K1118",
    "title": "Cross-asset alt-data sufficiency test (GLD/TLT/BTC, native IV vs EPU+FinStress)",
    "started_utc": datetime.utcnow().isoformat() + "Z",
    "data_source": "yfinance (GLD, TLT, BTC-USD, ^GVZ, ^MOVE, ^VIX) + FRED (USEPUINDXD, WLEMUINDXD, NFCI, ANFCI, STLFSI4)",
    "period": "2018-01 to 2026-04 weekly (W-FRI)",
    "is_period": "2018-01 to 2022-12",
    "oos_period": "2023-01 to 2026-04",
    "predecessor": "K1116 (SPY): native VIX sufficient, alt-data actively worse",
    "related": {
        "K1116": "SPY EPU+NFCI+STLFSI: NULL (alt-data actively worsens vs VIX baseline)",
        "K1098": "0050.TW: VIXTWN sufficient, EPU+NFCI+STLFSI null",
        "K473/K750/K789": "Google Trends null for SPY vol",
        "K504": "STLFSI4 null (narrow test)",
    },
    "hypotheses": {
        "H1_universal_sufficiency": "Native IV sufficient across all 3 assets -> strengthens publication claim",
        "H2_asset_niche": ">=1 asset shows M3/M4 DM t < -2 vs native IV -> niche for that asset",
        "H3_BTC_retail_edge": "M5 hybrid best for BTC (retail-driven) per Liu (2021)",
    },
    "references": [
        "Baker, Bloom, Davis (2016) QJE - EPU index",
        "Brave, Butters (2011) - NFCI",
        "Kliesen, Smith (2010) - STLFSI",
        "Patton (2011) - QLIKE proxy-robust loss",
        "Harvey, Leybourne, Newbold (1997) - HLN DM correction",
        "Liu (2021) - BTC retail sentiment",
    ],
}


def log(msg):
    ts = datetime.utcnow().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def fetch_asset_weekly(ticker, native_iv_ticker, start="2018-01-01", end="2026-04-13", iv_type="close"):
    """Fetch underlying asset + its native implied vol. Weekly aggregation.
    iv_type='close' uses closing IV; iv_type='rv30' computes 30-day rolling RV as proxy.
    """
    import yfinance as yf

    log(f"Fetching {ticker} + {native_iv_ticker}...")
    px = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if isinstance(px.columns, pd.MultiIndex):
        px.columns = px.columns.get_level_values(0)
    px = px[["Close"]].copy()
    px["r"] = np.log(px["Close"]).diff()

    # Weekly RV = sqrt(sum(r^2))
    px["week"] = px.index.to_period("W-FRI").to_timestamp("W-FRI")
    weekly = pd.DataFrame(index=px["week"].unique())
    weekly.index.name = "week"
    weekly["rv"] = px.groupby("week")["r"].apply(lambda x: np.sqrt(np.sum(x.dropna() ** 2)))
    weekly["r_n"] = px.groupby("week")["r"].count()
    # BTC has 7-day trading; so expect higher n. SPY/GLD/TLT ~5.
    min_n = 4 if ticker != "BTC-USD" else 5
    weekly = weekly[weekly["r_n"] >= min_n]
    weekly = weekly.sort_index()

    # Native IV
    if iv_type == "rv30":
        # BTC proxy: 30-day rolling realized vol (daily annualized-ish, we keep raw sqrt(sum r^2))
        px["rv30"] = px["r"].rolling(30).apply(lambda x: np.sqrt(np.sum(x ** 2) * (252 / 30)))
        iv_daily = px[["rv30", "week"]].copy().rename(columns={"rv30": "iv"})
        iv_w = iv_daily.groupby("week").agg(iv_mean=("iv", "mean"), iv_last=("iv", "last"))
        iv_w = iv_w.dropna()
    else:
        iv = yf.download(native_iv_ticker, start=start, end=end, progress=False, auto_adjust=False)
        if isinstance(iv.columns, pd.MultiIndex):
            iv.columns = iv.columns.get_level_values(0)
        iv = iv[["Close"]].rename(columns={"Close": "iv"}).copy()
        iv["week"] = iv.index.to_period("W-FRI").to_timestamp("W-FRI")
        iv_w = iv.groupby("week").agg(iv_mean=("iv", "mean"), iv_last=("iv", "last"))

    df = weekly.join(iv_w, how="inner").dropna()
    log(f"  {ticker}: {len(df)} weeks, {df.index.min().date()} to {df.index.max().date()}, iv n-missing={iv_w['iv_mean'].isna().sum()}")
    return df


def fetch_fred_altdata():
    """Fetch FRED series via CSV endpoint using requests (urllib has HTTP/2 issues;
    pandas_datareader broken with current pandas version)."""
    import io
    import requests

    codes = {
        "USEPU": "USEPUINDXD",
        "WLEMU": "WLEMUINDXD",
        "NFCI": "NFCI",
        "ANFCI": "ANFCI",
        "STLFSI": "STLFSI4",
    }
    log(f"Fetching FRED alt-data via CSV (requests): {list(codes.values())}")
    sess = requests.Session()
    sess.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    frames = {}
    for name, code in codes.items():
        try:
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={code}&cosd=2018-01-01&coed=2026-04-13"
            r = sess.get(url, timeout=90)
            r.raise_for_status()
            s = pd.read_csv(io.StringIO(r.text))
            date_col = s.columns[0]
            s[date_col] = pd.to_datetime(s[date_col])
            s = s.set_index(date_col)
            s.columns = [name]
            s[name] = pd.to_numeric(s[name], errors="coerce")
            s = s.dropna()
            frames[name] = s
            log(f"  {code}: {s.shape}, last={s.index[-1].date()}")
        except Exception as e:
            log(f"  {code}: FAIL {str(e)[:120]}")

    weekly_frames = []
    for name, s in frames.items():
        s = s.copy()
        s["week"] = s.index.to_period("W-FRI").to_timestamp("W-FRI")
        w = s.groupby("week").agg({name: "mean"})
        weekly_frames.append(w)

    out = weekly_frames[0]
    for w in weekly_frames[1:]:
        out = out.join(w, how="outer")
    out = out.sort_index().ffill(limit=2)
    log(f"FRED weekly merged: {out.shape}")
    return out


def qlike(actual, pred):
    eps = 1e-10
    actual = np.maximum(actual, eps)
    pred = np.maximum(pred, eps)
    return np.mean(np.log(pred) + actual / pred)


def dm_hln(e1, e2, h=1):
    """DM-HLN. Sign convention: e1=baseline loss, e2=challenger loss.
    Positive t -> e1 > e2 -> challenger beats baseline.
    Negative t -> baseline beats challenger.
    """
    from scipy import stats as st

    d = np.asarray(e1, dtype=float) - np.asarray(e2, dtype=float)
    d = d[~np.isnan(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan
    dbar = d.mean()
    gamma0 = np.var(d, ddof=1)
    if gamma0 <= 0:
        return np.nan, np.nan
    hln_correction = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    se = np.sqrt(gamma0 / n)
    t = (dbar / se) * hln_correction
    p = 2 * (1 - st.t.cdf(abs(t), df=n - 1))
    return t, p


def run_asset(asset_name, ticker, iv_ticker, altdata, iv_type="close"):
    """Run the 5-model battery for one asset. Returns dict of results."""
    import statsmodels.api as sm

    log(f"\n===== Asset: {asset_name} (ticker={ticker}, IV={iv_ticker}) =====")
    market = fetch_asset_weekly(ticker, iv_ticker, iv_type=iv_type)

    df = market.join(altdata, how="inner").dropna()
    log(f"  Merged panel: {len(df)} weeks")

    alt_cols = list(altdata.columns)
    is_end = "2022-12-31"
    oos_start = "2023-01-01"
    df_is = df.loc[:is_end].copy()
    df_oos = df.loc[oos_start:].copy()
    log(f"  IS n={len(df_is)}, OOS n={len(df_oos)}")

    # Descriptive
    desc = {
        "rv": {"mean": float(df["rv"].mean()), "std": float(df["rv"].std()),
               "min": float(df["rv"].min()), "max": float(df["rv"].max())},
        "iv_mean": {"mean": float(df["iv_mean"].mean()), "std": float(df["iv_mean"].std())},
    }

    # IS corrs
    corr = {}
    for c in alt_cols + ["iv_mean"]:
        s = df_is[c].shift(1)
        valid = s.notna() & df_is["rv"].notna()
        corr[c] = float(s[valid].corr(df_is["rv"][valid]))

    def make_X(df_sub, spec):
        X = pd.DataFrame(index=df_sub.index)
        X["y_lag1"] = df_sub["rv"].shift(1)
        if spec == "base":
            return X.dropna()
        if spec == "iv":
            X["iv_lag1"] = df_sub["iv_mean"].shift(1)
        elif spec == "epu":
            X["USEPU_lag1"] = df_sub["USEPU"].shift(1)
            X["WLEMU_lag1"] = df_sub["WLEMU"].shift(1)
        elif spec == "finstress":
            X["NFCI_lag1"] = df_sub["NFCI"].shift(1)
            X["ANFCI_lag1"] = df_sub["ANFCI"].shift(1)
            X["STLFSI_lag1"] = df_sub["STLFSI"].shift(1)
        elif spec == "all":
            X["iv_lag1"] = df_sub["iv_mean"].shift(1)
            X["USEPU_lag1"] = df_sub["USEPU"].shift(1)
            X["WLEMU_lag1"] = df_sub["WLEMU"].shift(1)
            X["NFCI_lag1"] = df_sub["NFCI"].shift(1)
            X["ANFCI_lag1"] = df_sub["ANFCI"].shift(1)
            X["STLFSI_lag1"] = df_sub["STLFSI"].shift(1)
        return X.dropna()

    specs = ["base", "iv", "epu", "finstress", "all"]
    model_names = {
        "base": "M1_AR1",
        "iv": "M2_AR1_IV",
        "epu": "M3_AR1_EPU",
        "finstress": "M4_AR1_FinStress",
        "all": "M5_AR1_All",
    }

    is_results = {}
    fitted = {}
    oos_losses = {}
    oos_forecasts = {}

    for spec in specs:
        name = model_names[spec]
        X_is = make_X(df_is, spec)
        y_is = df_is["rv"].loc[X_is.index]
        Xc_is = sm.add_constant(X_is, has_constant="add")
        ols = sm.OLS(y_is, Xc_is).fit()
        fitted[name] = (ols, Xc_is.columns.tolist())
        is_results[name] = {
            "r2": float(ols.rsquared),
            "adj_r2": float(ols.rsquared_adj),
            "aic": float(ols.aic),
            "bic": float(ols.bic),
            "n_is": int(len(y_is)),
            "params": {k: float(v) for k, v in ols.params.to_dict().items()},
            "pvalues": {k: float(v) for k, v in ols.pvalues.to_dict().items()},
        }
        X_oos = make_X(df_oos, spec)
        Xc_oos = sm.add_constant(X_oos, has_constant="add").reindex(columns=Xc_is.columns, fill_value=0.0)
        pred = ols.predict(Xc_oos).clip(lower=1e-6)
        actual = df_oos["rv"].loc[X_oos.index]
        oos_forecasts[name] = {"pred": pred, "actual": actual}
        oos_losses[name] = np.log(pred) + actual / pred

    # DM tests vs M2_AR1_IV
    baseline = "M2_AR1_IV"
    common_idx = oos_losses[baseline].index
    for m in oos_losses:
        common_idx = common_idx.intersection(oos_losses[m].index)
    base_loss = oos_losses[baseline].reindex(common_idx)

    dm_tests = {}
    for m in ["M1_AR1", "M3_AR1_EPU", "M4_AR1_FinStress", "M5_AR1_All"]:
        m_loss = oos_losses[m].reindex(common_idx)
        t, p = dm_hln(base_loss.values, m_loss.values)
        challenger_beats = (not np.isnan(t)) and (t > 2.0)
        baseline_beats = (not np.isnan(t)) and (t < -2.0)
        dm_tests[f"{baseline}_vs_{m}"] = {
            "t_stat": float(t) if not np.isnan(t) else None,
            "p_value": float(p) if not np.isnan(p) else None,
            "interpretation": (
                f"{m} beats baseline" if challenger_beats
                else (f"baseline beats {m}" if baseline_beats else "indistinguishable")
            ),
            "challenger_wins_harvey": bool(challenger_beats),
            "baseline_wins_harvey": bool(baseline_beats),
        }

    # IS vs OOS QLIKE
    is_oos_table = {}
    for name in model_names.values():
        ols, cols = fitted[name]
        spec = [k for k, v in model_names.items() if v == name][0]
        X_is = make_X(df_is, spec)
        Xc_is = sm.add_constant(X_is, has_constant="add").reindex(columns=cols, fill_value=0.0)
        pred_is = ols.predict(Xc_is).clip(lower=1e-6)
        actual_is = df_is["rv"].loc[X_is.index]
        is_qlike = float(qlike(actual_is.values, pred_is.values))

        actual_oos = oos_forecasts[name]["actual"].reindex(common_idx)
        pred_oos = oos_forecasts[name]["pred"].reindex(common_idx)
        oos_qlike = float(qlike(actual_oos.values, pred_oos.values))
        oos_rmse = float(np.sqrt(np.mean((actual_oos.values - pred_oos.values) ** 2)))

        is_oos_table[name] = {
            "IS_R2": is_results[name]["r2"],
            "IS_QLIKE": is_qlike,
            "OOS_QLIKE": oos_qlike,
            "OOS_RMSE": oos_rmse,
            "OOS_n": int(len(common_idx)),
            "divergence_IS_OOS": oos_qlike - is_qlike,
        }

    # Sub-period stability (2023, 2024, 2025)
    subperiod_dm = {}
    for year in [2023, 2024, 2025]:
        yr_mask = pd.Series([d.year == year for d in common_idx], index=common_idx)
        n_yr = int(yr_mask.sum())
        if n_yr < 10:
            subperiod_dm[str(year)] = {"n": n_yr, "note": "insufficient"}
            continue
        subperiod_dm[str(year)] = {"n": n_yr}
        base_sub = base_loss[yr_mask].values
        for m in ["M3_AR1_EPU", "M4_AR1_FinStress", "M5_AR1_All"]:
            m_sub = oos_losses[m].reindex(common_idx)[yr_mask].values
            t, p = dm_hln(base_sub, m_sub)
            challenger_beats = (not np.isnan(t)) and (t > 2.0)
            baseline_beats = (not np.isnan(t)) and (t < -2.0)
            subperiod_dm[str(year)][f"{baseline}_vs_{m}"] = {
                "t_stat": float(t) if not np.isnan(t) else None,
                "p_value": float(p) if not np.isnan(p) else None,
                "challenger_wins_harvey": bool(challenger_beats),
                "baseline_wins_harvey": bool(baseline_beats),
            }

    # Best alt-model QLIKE improvement
    base_oos_qlike = is_oos_table[baseline]["OOS_QLIKE"]
    alt_models = ["M3_AR1_EPU", "M4_AR1_FinStress", "M5_AR1_All"]
    best_alt = min(alt_models, key=lambda m: is_oos_table[m]["OOS_QLIKE"])
    best_alt_qlike = is_oos_table[best_alt]["OOS_QLIKE"]
    qlike_improv_pct = float((base_oos_qlike - best_alt_qlike) / abs(base_oos_qlike) * 100)

    # Triple-gate verdict
    h1_base_pass = any(
        v.get("challenger_wins_harvey", False)
        for k, v in dm_tests.items()
        if k != f"{baseline}_vs_M1_AR1"
    )
    baseline_wins_count = sum(
        v.get("baseline_wins_harvey", False)
        for k, v in dm_tests.items()
        if k != f"{baseline}_vs_M1_AR1"
    )
    qlike_5pct_pass = qlike_improv_pct > 5.0
    stability_count = 0
    for yr, d in subperiod_dm.items():
        if not isinstance(d, dict) or d.get("n", 0) < 10:
            continue
        if any(isinstance(v, dict) and v.get("challenger_wins_harvey", False) for v in d.values()):
            stability_count += 1
    h3_stability_pass = stability_count >= 2

    triple_gate = h1_base_pass and qlike_5pct_pass and h3_stability_pass
    active_harm = baseline_wins_count >= 2
    if triple_gate:
        verdict = "POSITIVE (triple-gate passed)"
    elif active_harm:
        verdict = "NULL (native-IV baseline actively beats alt-data)"
    else:
        verdict = "NULL (no significant improvement)"

    return {
        "asset": asset_name,
        "ticker": ticker,
        "iv_ticker": iv_ticker,
        "iv_type": iv_type,
        "n_full": int(len(df)),
        "n_is": int(len(df_is)),
        "n_oos": int(len(df_oos)),
        "n_common_oos": int(len(common_idx)),
        "descriptive": desc,
        "lag1_corr_IS": corr,
        "is_results": is_results,
        "is_oos_comparison": is_oos_table,
        "dm_tests_full_oos": dm_tests,
        "subperiod_dm": subperiod_dm,
        "best_alt_model": best_alt,
        "qlike_improvement_pct": qlike_improv_pct,
        "gates": {
            "H1_any_challenger_beats_IV_baseline": bool(h1_base_pass),
            "baseline_beats_challengers_count": int(baseline_wins_count),
            "QLIKE_improvement_gt_5pct": bool(qlike_5pct_pass),
            "subperiod_stability_ge_2of3": bool(h3_stability_pass),
            "triple_gate_PASS": bool(triple_gate),
            "active_harm_alt_data_worse_than_IV": bool(active_harm),
        },
        "verdict": verdict,
    }


def main():
    np.random.seed(42)
    altdata = fetch_fred_altdata()
    RESULTS["alt_data_columns"] = list(altdata.columns)

    asset_configs = [
        ("GLD", "GLD", "^GVZ", "close"),
        ("TLT", "TLT", "^MOVE", "close"),
        ("BTC-USD", "BTC-USD", None, "rv30"),  # RV30 proxy because DVOL/BVOL not on yfinance
    ]

    asset_results = {}
    for name, ticker, iv_t, iv_type in asset_configs:
        try:
            asset_results[name] = run_asset(name, ticker, iv_t, altdata, iv_type=iv_type)
        except Exception as e:
            log(f"Asset {name} FAILED: {e}")
            import traceback
            traceback.print_exc()
            asset_results[name] = {"error": str(e)}

    RESULTS["asset_results"] = asset_results

    # Cross-asset synthesis
    log("\n===== Cross-asset synthesis =====")
    cross_synth = {}
    for name, r in asset_results.items():
        if "error" in r:
            cross_synth[name] = {"status": "error"}
            continue
        cross_synth[name] = {
            "verdict": r["verdict"],
            "triple_gate": r["gates"]["triple_gate_PASS"],
            "active_harm": r["gates"]["active_harm_alt_data_worse_than_IV"],
            "qlike_improvement_pct": r["qlike_improvement_pct"],
            "best_alt_model": r["best_alt_model"],
            "baseline_wins_count": r["gates"]["baseline_beats_challengers_count"],
        }
    RESULTS["cross_asset_synthesis"] = cross_synth

    # Hypothesis verdicts
    n_triple_gate = sum(
        1 for v in cross_synth.values()
        if v.get("triple_gate", False)
    )
    n_active_harm = sum(
        1 for v in cross_synth.values()
        if v.get("active_harm", False)
    )
    n_null = sum(
        1 for v in cross_synth.values()
        if "NULL" in str(v.get("verdict", ""))
    )
    n_assets = len([v for v in cross_synth.values() if v.get("verdict")])

    h1_universal = n_null == n_assets and n_assets >= 2  # all tested assets null
    h2_any_niche = n_triple_gate >= 1  # at least 1 asset alt-data helps
    # H3 BTC-specific check
    btc_res = asset_results.get("BTC-USD", {})
    h3_btc_edge = False
    if "gates" in btc_res:
        # BTC M5 is best OR M3+M4 both beat baseline in DM
        h3_btc_edge = btc_res["best_alt_model"] == "M5_AR1_All" and btc_res["qlike_improvement_pct"] > 5

    RESULTS["hypothesis_tests"] = {
        "H1_universal_sufficiency": bool(h1_universal),
        "H2_any_asset_niche": bool(h2_any_niche),
        "H3_BTC_retail_edge": bool(h3_btc_edge),
        "n_assets_tested": int(n_assets),
        "n_triple_gate_pass": int(n_triple_gate),
        "n_active_harm": int(n_active_harm),
    }

    # Paper 4 compendium boundary implication
    if h1_universal:
        compendium_implication = (
            "STRENGTHENS: Native implied-vol sufficiency extends beyond SPY (K1116) to "
            "GLD/TLT/BTC across equity/commodity/bond/crypto asset classes. "
            "Publication narrative: UNIVERSAL sufficiency of native IV for weekly RV prediction."
        )
    elif n_triple_gate > 0:
        wins = [n for n, v in cross_synth.items() if v.get("triple_gate", False)]
        compendium_implication = (
            f"NUANCED: {wins} show alt-data niche. SPY/other assets remain null. "
            "Publication narrative: Native IV sufficient for most assets; niche for "
            f"{', '.join(wins)}. This motivates asset-specific alt-data research."
        )
    else:
        compendium_implication = "MIXED: Partial evidence; see per-asset verdicts."
    RESULTS["paper4_compendium_implication"] = compendium_implication

    RESULTS["finished_utc"] = datetime.utcnow().isoformat() + "Z"
    with open(OUT_DIR / "k1118_results.json", "w") as f:
        json.dump(RESULTS, f, indent=2, default=str)
    log(f"Saved -> {OUT_DIR / 'k1118_results.json'}")

    # Summary print
    print("\n" + "=" * 90)
    print("K1118 SUMMARY — Cross-asset alt-data sufficiency test")
    print("=" * 90)
    for name, r in asset_results.items():
        if "error" in r:
            print(f"\n[{name}] ERROR: {r['error']}")
            continue
        print(f"\n[{name}]  ticker={r['ticker']}  IV={r['iv_ticker']} ({r['iv_type']})")
        print(f"  n_full={r['n_full']}  IS={r['n_is']}  OOS={r['n_oos']}  common_OOS={r['n_common_oos']}")
        print(f"  Best alt-model (OOS QLIKE): {r['best_alt_model']}  QLIKE improvement: {r['qlike_improvement_pct']:+.2f}%")
        print(f"  IS-vs-OOS QLIKE:")
        for mn, v in r["is_oos_comparison"].items():
            print(f"    {mn:<22}  IS R²={v['IS_R2']:.4f}  IS QLIKE={v['IS_QLIKE']:+.4f}  OOS QLIKE={v['OOS_QLIKE']:+.4f}")
        print(f"  DM tests (vs M2_AR1_IV):")
        for k, v in r["dm_tests_full_oos"].items():
            t = v["t_stat"]
            if t is None:
                print(f"    {k}: n/a")
                continue
            tag = "*challenger WINS*" if v["challenger_wins_harvey"] else ("[baseline wins]" if v["baseline_wins_harvey"] else "ns")
            print(f"    {k}: t={t:+.3f} p={v['p_value']:.4f} {tag}")
        print(f"  Gates: triple_gate={r['gates']['triple_gate_PASS']} active_harm={r['gates']['active_harm_alt_data_worse_than_IV']}")
        print(f"  VERDICT: {r['verdict']}")

    print(f"\n\nCross-asset hypothesis tests:")
    for h, v in RESULTS["hypothesis_tests"].items():
        print(f"  {h}: {v}")

    print(f"\n\nPaper 4 compendium implication:\n  {RESULTS['paper4_compendium_implication']}")


if __name__ == "__main__":
    main()
