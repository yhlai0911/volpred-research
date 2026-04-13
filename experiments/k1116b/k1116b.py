"""
K1116b: FRED Publication Delay Re-verification for K1116 & K1118

Motivation (from K1121 discovery, E062):
  K1121 revealed FRED NFCI has 5-day publication delay (observed Fri, released Wed).
  K1116/K1118 use NFCI/STLFSI/ANFCI with shift(1) at WEEKLY frequency — possibly latent
  lookahead because NFCI[Friday W-1] is not released until Wed of week W, yet
  predicting RV[W] requires signal known before Mon W.

Design:
  Re-run K1116 (SPY) and K1118 (GLD/TLT/BTC) with corrected publication-delay lags:
    - NFCI, ANFCI, STLFSI: .shift(2) weekly (instead of .shift(1))
    - USEPU, WLEMU:        .shift(1) weekly (unchanged; daily release, next-day lag)

  Also run a "Conservative-Weekly" variant where ALL alt-data shifts by 2 weeks
  for maximum paranoia.

  Compare original t-stats to corrected t-stats. Report H1/H2/H3 verdict.

Key comparisons (all from ORIGINAL results JSONs):
  SPY M3 EPU: t=-2.554   (alt-data worse)
  SPY M4 NFCI: t=-3.001  (alt-data worse) — CRITICAL: was the driver of K1116 "active harm"
  GLD M4 NFCI: t=-3.341  (alt-data worse)
  TLT M4 NFCI: t=+3.743  *** ONLY positive-significant cell in entire K1118 ***
  BTC M3 EPU: t=-5.039   (alt-data very worse)

The TLT M4 result is the single most paper-relevant cell. If it flips under
correction, the "alt-data actively hurts" narrative strengthens.  If it stays,
genuine TLT niche exists.

References:
  K1116 (experiments/k1116/k1116.py) — SPY weekly 5-model OOS
  K1118 (experiments/k1118/k1118.py) — GLD/TLT/BTC parallel
  K1121 (experiments/k1121/k1121.py) — daily allocation with shift(2) EPU / shift(5) NFCI
  E062  (docs/error_log.md 2026-04-13) — publication-delay discovery
  Baker-Bloom-Davis (2016) QJE — EPU (daily, next-day release)
  Brave-Butters (2011) — NFCI (weekly Fri obs, Wed release)
  Kliesen-Smith (2010) — STLFSI (weekly)
"""
import io
import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

OUT_DIR = Path(__file__).parent
RESULTS = {
    "experiment_id": "K1116b",
    "title": "K1116 & K1118 FRED Publication-Delay Re-verification",
    "started_utc": datetime.utcnow().isoformat() + "Z",
    "data_source": "yfinance (SPY, GLD, TLT, BTC-USD, ^VIX, ^GVZ, ^MOVE) + FRED (USEPUINDXD, WLEMUINDXD, NFCI, ANFCI, STLFSI4)",
    "period": "2018-01 to 2026-04 weekly (W-FRI)",
    "precedessor": "K1116 (SPY), K1118 (GLD/TLT/BTC)",
    "delay_corrections": {
        "USEPU": "1 week (daily series, 1-day release lag → weekly aggregation safe with shift(1))",
        "WLEMU": "1 week (same as USEPU)",
        "NFCI": "2 weeks (weekly Fri obs, 5-cal-day release; needs extra week lag)",
        "ANFCI": "2 weeks (same as NFCI)",
        "STLFSI": "2 weeks (weekly Fri obs, 6-cal-day release; needs extra week lag)",
    },
    "references": [
        "K1121 publication-delay discovery (E062)",
        "Baker, Bloom, Davis (2016) QJE — EPU",
        "Brave, Butters (2011) — NFCI",
        "Kliesen, Smith (2010) — STLFSI",
        "Patton (2011) — QLIKE",
        "Harvey, Leybourne, Newbold (1997) — HLN DM",
    ],
}


def log(msg):
    ts = datetime.utcnow().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# -------- Data fetching (shared between SPY & cross-asset) --------

def fetch_asset_weekly(ticker, iv_ticker, start="2018-01-01", end="2026-04-13", iv_type="close"):
    import yfinance as yf

    log(f"Fetching {ticker} + {iv_ticker}...")
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
        iv_w = iv_daily.groupby("week").agg(iv_mean=("iv", "mean"), iv_last=("iv", "last")).dropna()
    else:
        iv = yf.download(iv_ticker, start=start, end=end, progress=False, auto_adjust=False)
        if isinstance(iv.columns, pd.MultiIndex):
            iv.columns = iv.columns.get_level_values(0)
        iv = iv[["Close"]].rename(columns={"Close": "iv"}).copy()
        iv["week"] = iv.index.to_period("W-FRI").to_timestamp("W-FRI")
        iv_w = iv.groupby("week").agg(iv_mean=("iv", "mean"), iv_last=("iv", "last"))

    df = weekly.join(iv_w, how="inner").dropna()
    log(f"  {ticker}: {len(df)} weeks")
    return df


def fetch_fred_altdata():
    """Fetch FRED series. Prefer local cache (from K1121 + storage/macro), fallback to
    pandas_datareader (fred.stlouisfed.org CSV endpoint intermittently blocks our subnet).
    """
    from pandas_datareader import data as pdr

    ROOT = Path(__file__).resolve().parent.parent.parent

    codes = {
        "USEPU": "USEPUINDXD",
        "WLEMU": "WLEMUINDXD",
        "NFCI": "NFCI",
        "ANFCI": "ANFCI",
        "STLFSI": "STLFSI4",
    }
    local_cache = {
        "USEPU": ROOT / "experiments/k1121/data/fred_USEPUINDXD.csv",
        "NFCI": ROOT / "experiments/k1121/data/fred_NFCI.csv",
        "STLFSI": ROOT / "storage/macro/fred_STLFSI4.csv",
    }

    log(f"Fetching FRED: {list(codes.values())}")
    frames = {}
    for name, code in codes.items():
        cached = local_cache.get(name)
        if cached and cached.exists():
            try:
                s = pd.read_csv(cached)
                # normalize to date index + single-column named {name}
                date_col = s.columns[0]
                s[date_col] = pd.to_datetime(s[date_col])
                s = s.set_index(date_col)
                val_col = s.columns[0]
                s = s.rename(columns={val_col: name})
                s[name] = pd.to_numeric(s[name], errors="coerce")
                s = s.dropna()
                # Filter to relevant window
                s = s.loc["2018-01-01":"2026-04-13"]
                frames[name] = s
                log(f"  {code} (cache): {len(s)} rows, last={s.index[-1].date()}")
                continue
            except Exception as e:
                log(f"  {code} cache read failed: {str(e)[:80]}")
        # Fallback to pandas_datareader
        try:
            s = pdr.DataReader(code, "fred", "2018-01-01", "2026-04-13")
            s.columns = [name]
            s = s.dropna()
            frames[name] = s
            log(f"  {code} (pdr): {len(s)} rows, last={s.index[-1].date()}")
        except Exception as e:
            log(f"  {code}: FAIL {str(e)[:100]}")

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


# -------- Stats --------

def qlike(actual, pred):
    eps = 1e-10
    actual = np.maximum(actual, eps)
    pred = np.maximum(pred, eps)
    return np.mean(np.log(pred) + actual / pred)


def dm_hln(e1, e2, h=1):
    """DM-HLN; e1=baseline loss, e2=challenger loss. Positive t = challenger beats baseline."""
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


# -------- Model runner --------

def run_asset_battery(asset_name, df, alt_cols, baseline_name, baseline_series_name,
                      delay_spec, variant_tag):
    """Run 5-model battery for a single asset.

    delay_spec: dict mapping each of (USEPU, WLEMU, NFCI, ANFCI, STLFSI) to number of
                weeks to shift() at weekly frequency. Baseline (VIX or IV) uses shift(1).
    baseline_series_name: column in df used as baseline IV regressor ("vix_mean" or "iv_mean")
    baseline_name: "M2_AR1_VIX" for SPY, "M2_AR1_IV" for cross-asset
    """
    import statsmodels.api as sm

    is_end = "2022-12-31"
    oos_start = "2023-01-01"
    df_is = df.loc[:is_end].copy()
    df_oos = df.loc[oos_start:].copy()

    def make_X(df_sub, spec):
        X = pd.DataFrame(index=df_sub.index)
        X["y_lag1"] = df_sub["rv"].shift(1)
        if spec == "base":
            return X.dropna()
        if spec == "iv":
            X["iv_lag1"] = df_sub[baseline_series_name].shift(1)
        elif spec == "epu":
            X["USEPU_lag"] = df_sub["USEPU"].shift(delay_spec["USEPU"])
            X["WLEMU_lag"] = df_sub["WLEMU"].shift(delay_spec["WLEMU"])
        elif spec == "finstress":
            X["NFCI_lag"] = df_sub["NFCI"].shift(delay_spec["NFCI"])
            X["ANFCI_lag"] = df_sub["ANFCI"].shift(delay_spec["ANFCI"])
            X["STLFSI_lag"] = df_sub["STLFSI"].shift(delay_spec["STLFSI"])
        elif spec == "all":
            X["iv_lag1"] = df_sub[baseline_series_name].shift(1)
            X["USEPU_lag"] = df_sub["USEPU"].shift(delay_spec["USEPU"])
            X["WLEMU_lag"] = df_sub["WLEMU"].shift(delay_spec["WLEMU"])
            X["NFCI_lag"] = df_sub["NFCI"].shift(delay_spec["NFCI"])
            X["ANFCI_lag"] = df_sub["ANFCI"].shift(delay_spec["ANFCI"])
            X["STLFSI_lag"] = df_sub["STLFSI"].shift(delay_spec["STLFSI"])
        return X.dropna()

    specs = ["base", "iv", "epu", "finstress", "all"]
    model_names = {
        "base": "M1_AR1",
        "iv": baseline_name,
        "epu": "M3_AR1_EPU",
        "finstress": "M4_AR1_FinStress",
        "all": "M5_AR1_All",
    }

    oos_losses = {}
    is_oos_table = {}
    fitted = {}

    for spec in specs:
        name = model_names[spec]
        X_is = make_X(df_is, spec)
        y_is = df_is["rv"].loc[X_is.index]
        Xc_is = sm.add_constant(X_is, has_constant="add")
        ols = sm.OLS(y_is, Xc_is).fit()
        fitted[name] = (ols, Xc_is.columns.tolist())

        X_oos = make_X(df_oos, spec)
        Xc_oos = sm.add_constant(X_oos, has_constant="add").reindex(columns=Xc_is.columns, fill_value=0.0)
        pred_oos = ols.predict(Xc_oos).clip(lower=1e-6)
        actual_oos = df_oos["rv"].loc[X_oos.index]
        oos_losses[name] = np.log(pred_oos) + actual_oos / pred_oos

        pred_is = ols.predict(Xc_is).clip(lower=1e-6)
        actual_is = df_is["rv"].loc[X_is.index]
        is_oos_table[name] = {
            "IS_R2": float(ols.rsquared),
            "IS_QLIKE": float(qlike(actual_is.values, pred_is.values)),
            "n_is": int(len(y_is)),
            "n_oos": int(len(actual_oos)),
        }

    common_idx = oos_losses[baseline_name].index
    for m in oos_losses:
        common_idx = common_idx.intersection(oos_losses[m].index)

    for name in model_names.values():
        loss = oos_losses[name].reindex(common_idx)
        actual_oos = df_oos["rv"].reindex(common_idx)
        # Re-compute OOS QLIKE on common index
        # loss = log(pred) + actual/pred; average gives QLIKE
        is_oos_table[name]["OOS_QLIKE"] = float(loss.mean())
        is_oos_table[name]["OOS_n_common"] = int(len(common_idx))

    base_loss = oos_losses[baseline_name].reindex(common_idx)
    dm_results = {}
    for m in ["M1_AR1", "M3_AR1_EPU", "M4_AR1_FinStress", "M5_AR1_All"]:
        m_loss = oos_losses[m].reindex(common_idx)
        t, p = dm_hln(base_loss.values, m_loss.values)
        challenger_beats = (not np.isnan(t)) and (t > 2.0)
        baseline_beats = (not np.isnan(t)) and (t < -2.0)
        dm_results[f"{baseline_name}_vs_{m}"] = {
            "t_stat": float(t) if not np.isnan(t) else None,
            "p_value": float(p) if not np.isnan(p) else None,
            "challenger_wins_harvey": bool(challenger_beats),
            "baseline_wins_harvey": bool(baseline_beats),
        }

    return {
        "asset": asset_name,
        "variant": variant_tag,
        "delay_spec_weeks": delay_spec,
        "n_is": int(len(df_is)),
        "n_oos": int(len(df_oos)),
        "n_common_oos": int(len(common_idx)),
        "is_oos_table": is_oos_table,
        "dm_results": dm_results,
    }


# -------- Main --------

def main():
    np.random.seed(42)
    altdata = fetch_fred_altdata()

    log("Fetching SPY + VIX weekly...")
    spy = fetch_asset_weekly("SPY", "^VIX", iv_type="close").rename(columns={"iv_mean": "vix_mean", "iv_last": "vix_last"})

    log("Fetching GLD + GVZ weekly...")
    gld = fetch_asset_weekly("GLD", "^GVZ", iv_type="close")

    log("Fetching TLT + MOVE weekly...")
    tlt = fetch_asset_weekly("TLT", "^MOVE", iv_type="close")

    log("Fetching BTC-USD weekly with RV30 proxy...")
    btc = fetch_asset_weekly("BTC-USD", None, iv_type="rv30")

    # Merge FRED altdata
    spy_m = spy.join(altdata, how="inner").dropna()
    gld_m = gld.join(altdata, how="inner").dropna()
    tlt_m = tlt.join(altdata, how="inner").dropna()
    btc_m = btc.join(altdata, how="inner").dropna()

    alt_cols = list(altdata.columns)

    # Define delay variants
    delay_variants = {
        "original_k1116": {  # baseline: ALL shift(1) weekly (reproduce original)
            "USEPU": 1, "WLEMU": 1, "NFCI": 1, "ANFCI": 1, "STLFSI": 1
        },
        "corrected": {  # NFCI/ANFCI/STLFSI shift(2) weekly; USEPU/WLEMU shift(1)
            "USEPU": 1, "WLEMU": 1, "NFCI": 2, "ANFCI": 2, "STLFSI": 2
        },
        "conservative": {  # ALL shift(2) weekly
            "USEPU": 2, "WLEMU": 2, "NFCI": 2, "ANFCI": 2, "STLFSI": 2
        },
    }

    assets = [
        ("SPY", spy_m, "M2_AR1_VIX", "vix_mean"),
        ("GLD", gld_m, "M2_AR1_IV", "iv_mean"),
        ("TLT", tlt_m, "M2_AR1_IV", "iv_mean"),
        ("BTC-USD", btc_m, "M2_AR1_IV", "iv_mean"),
    ]

    all_results = {}
    for asset_name, df, baseline_name, baseline_col in assets:
        log(f"\n===== ASSET: {asset_name} =====")
        asset_variants = {}
        for variant_tag, delay_spec in delay_variants.items():
            log(f"  Variant: {variant_tag} -> {delay_spec}")
            result = run_asset_battery(
                asset_name, df, alt_cols, baseline_name, baseline_col,
                delay_spec, variant_tag
            )
            asset_variants[variant_tag] = result
        all_results[asset_name] = asset_variants

    RESULTS["full_results"] = all_results

    # ------- Build comparison table: original vs corrected -------
    log("\n===== COMPARISON TABLE =====")
    comparison = []
    # From original JSONs (hardcoded for reference check)
    original_literature = {
        "SPY": {
            "M1_AR1": -3.021, "M3_AR1_EPU": -2.554,
            "M4_AR1_FinStress": -3.001, "M5_AR1_All": -1.008,
        },
        "GLD": {
            "M1_AR1": -2.103, "M3_AR1_EPU": -1.773,
            "M4_AR1_FinStress": -3.341, "M5_AR1_All": -0.128,
        },
        "TLT": {
            "M1_AR1": 1.433, "M3_AR1_EPU": -0.830,
            "M4_AR1_FinStress": 3.743, "M5_AR1_All": -5.179,
        },
        "BTC-USD": {
            "M1_AR1": -5.494, "M3_AR1_EPU": -5.039,
            "M4_AR1_FinStress": 1.370, "M5_AR1_All": -1.282,
        },
    }

    for asset_name, variants in all_results.items():
        baseline_name = "M2_AR1_VIX" if asset_name == "SPY" else "M2_AR1_IV"
        for model in ["M1_AR1", "M3_AR1_EPU", "M4_AR1_FinStress", "M5_AR1_All"]:
            key = f"{baseline_name}_vs_{model}"
            orig_lit_t = original_literature.get(asset_name, {}).get(model)
            orig_repro_t = variants["original_k1116"]["dm_results"].get(key, {}).get("t_stat")
            corrected_t = variants["corrected"]["dm_results"].get(key, {}).get("t_stat")
            conservative_t = variants["conservative"]["dm_results"].get(key, {}).get("t_stat")

            delta_corrected = None
            if orig_repro_t is not None and corrected_t is not None:
                delta_corrected = corrected_t - orig_repro_t

            # Flag if crosses ±2 threshold
            flip_flag = ""
            if orig_repro_t is not None and corrected_t is not None:
                orig_sig = abs(orig_repro_t) > 2.0
                corr_sig = abs(corrected_t) > 2.0
                sign_match = (orig_repro_t > 0) == (corrected_t > 0)
                if orig_sig != corr_sig:
                    flip_flag = "THRESHOLD_FLIP"
                elif not sign_match:
                    flip_flag = "SIGN_FLIP"

            comparison.append({
                "asset": asset_name,
                "model": model,
                "original_literature_t": orig_lit_t,
                "original_repro_t": orig_repro_t,
                "corrected_t": corrected_t,
                "conservative_t": conservative_t,
                "delta_corrected_minus_repro": delta_corrected,
                "flag": flip_flag,
            })

    RESULTS["comparison"] = comparison

    # ------- Verdict -------
    n_flips = sum(1 for r in comparison if r["flag"] in ("THRESHOLD_FLIP", "SIGN_FLIP"))
    key_models_affected = [
        f"{r['asset']} {r['model']}" for r in comparison if r["flag"]
    ]

    # TLT M4 specifically (the only original positive-significant cell)
    tlt_m4 = next((r for r in comparison if r["asset"] == "TLT" and r["model"] == "M4_AR1_FinStress"), None)
    tlt_m4_verdict = ""
    if tlt_m4:
        orig_t = tlt_m4["original_repro_t"]
        corr_t = tlt_m4["corrected_t"]
        if orig_t is not None and corr_t is not None:
            if corr_t > 2.0:
                tlt_m4_verdict = f"HOLDS: TLT M4 NFCI remains positive-significant (orig_repro={orig_t:.3f}, corrected={corr_t:.3f}) → genuine Treasury niche"
            elif corr_t > 0:
                tlt_m4_verdict = f"WEAKENS: TLT M4 NFCI loses significance (orig_repro={orig_t:.3f}, corrected={corr_t:.3f}) → borderline"
            else:
                tlt_m4_verdict = f"FLIPS: TLT M4 NFCI no longer beats baseline (orig_repro={orig_t:.3f}, corrected={corr_t:.3f}) → no Treasury niche"

    # Overall hypothesis verdict
    if n_flips == 0:
        h_verdict = "H1 (lucky): publication-delay corrections do NOT change any DM threshold conclusions"
    elif n_flips <= 2:
        h_verdict = f"H2 (concerning): {n_flips} cells flip — check details"
    else:
        h_verdict = f"H3 (disastrous): {n_flips} cells flip — broader recheck of Paper 4 needed"

    RESULTS["verdict"] = {
        "n_threshold_flips": n_flips,
        "cells_affected": key_models_affected,
        "tlt_m4_nfci_verdict": tlt_m4_verdict,
        "h_verdict": h_verdict,
    }

    RESULTS["finished_utc"] = datetime.utcnow().isoformat() + "Z"

    with open(OUT_DIR / "k1116b_results.json", "w") as f:
        json.dump(RESULTS, f, indent=2, default=str)
    log(f"Saved -> {OUT_DIR / 'k1116b_results.json'}")

    # CSV table for easy inspection
    rows = []
    for r in comparison:
        rows.append(r)
    pd.DataFrame(rows).to_csv(OUT_DIR / "comparison_table.csv", index=False)
    log(f"Saved -> {OUT_DIR / 'comparison_table.csv'}")

    # Print summary
    print("\n" + "=" * 100)
    print("K1116b SUMMARY")
    print("=" * 100)
    print(f"{'Asset':<10} {'Model':<22} {'Orig(lit)':>10} {'Orig(repro)':>12} {'Corrected':>11} {'Conserv':>9} {'Δcorr':>9} {'Flag':>18}")
    for r in comparison:
        ol = f"{r['original_literature_t']:+.3f}" if r['original_literature_t'] is not None else "n/a"
        orr = f"{r['original_repro_t']:+.3f}" if r['original_repro_t'] is not None else "n/a"
        ct = f"{r['corrected_t']:+.3f}" if r['corrected_t'] is not None else "n/a"
        cons = f"{r['conservative_t']:+.3f}" if r['conservative_t'] is not None else "n/a"
        d = f"{r['delta_corrected_minus_repro']:+.3f}" if r['delta_corrected_minus_repro'] is not None else "n/a"
        print(f"{r['asset']:<10} {r['model']:<22} {ol:>10} {orr:>12} {ct:>11} {cons:>9} {d:>9} {r['flag']:>18}")

    print(f"\nTLT M4 NFCI: {tlt_m4_verdict}")
    print(f"\nOverall verdict: {h_verdict}")


if __name__ == "__main__":
    main()
