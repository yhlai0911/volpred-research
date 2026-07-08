"""K1660 — Mincer-Zarnowitz calibration audit of the VolPred HAR/GARCH forecast library.

Motivation
----------
VolPred has accumulated 102 stored OOS forecast sets (``storage/results/<id>_forecasts.json``
+ companion ``<id>.json`` metadata) from HAR/GARCH-family models, but the library has never
been audited for *calibration*. The Mincer-Zarnowitz (MZ) regression
    realized_t = a + b * forecast_t + e_t,  H0: a=0 AND b=1
is the standard forecast-efficiency test (Mincer & Zarnowitz 1969; Patton 2011). Rejecting H0
means the model has a systematic bias (over/under-forecast). This audit is zero extra data cost
and directly raises the credibility of every stored forecast.

Realized-target choice (CRITICAL, per experiment-preamble)
----------------------------------------------------------
GARCH/GJR/EGARCH/CGARCH forecast *close-to-close conditional variance* (full day, incl. overnight).
The preamble-mandated realized target for these models is r^2 = (log close-to-close return)^2,
which is a conditionally UNBIASED proxy: E[r^2_t | F_{t-1}] = sigma^2_t. We use r^2 as the PRIMARY
realized target for the four pure conditional-variance families.

The stored pipeline metrics used ``rv_proxy = rv_parkinson`` (intraday high-low range variance) as
"actual". Parkinson is (a) the WRONG scale for close-to-close GARCH forecasts (misses overnight) and
(b) known in this project to underestimate true variance by ~34% (5-min RV calibration K). We
reconstruct Parkinson too, purely to (i) VALIDATE that our yfinance data matches the pipeline
(mean Parkinson over the exact forecast dates vs stored ``mean_actual_var``) and (ii) show, as a
diagnostic, how the proxy choice inflates apparent over-forecast.

Method
------
* Unit of analysis = one forecast file = (asset, model_family, OOS window). Every MZ regression is a
  SINGLE-asset time series -> Newey-West HAC on the time dimension is clean; no asset-day iid pooling
  (K1355). Family verdicts are aggregated from per-file verdicts.
* MZ in variance space (primary) and log-variance space (robustness). OLS point estimates with
  Newey-West HAC SE (lag = floor(4*(n/100)^(2/9))). Report a_hat, b_hat, t vs (0,1), and the HAC
  joint Wald test of H0: a=0 AND b=1. Report R^2.
* Verdict: well-calibrated (fail to reject joint Wald at 5%) / over-forecast / under-forecast
  (direction from mean forecast / mean realized and b_hat).
* Bias correction: expanding-window (OOS-valid) linear correction f_adj = a_hat_{<=t-1} + b_hat*f,
  QLIKE (canonical, volpred.stats.model_evaluation.qlike_pointwise) raw vs corrected + DM test, for the
  flagship SPY families. Full-sample in-sample correction reported separately as an IN-SAMPLE diagnostic.

Reproducibility: fixed seed; OHLC cached to ./data/. HAC lag, all conventions logged.
"""
from __future__ import annotations

import glob
import json
import os
import sys
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
np.random.seed(42)  # deterministic; only relevant for any bootstrap path

# --- volpred canonical helpers (no self-written reverse QLIKE, per K783c) ---
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))
from volpred.stats.model_evaluation import qlike_pointwise  # noqa: E402
from volpred.evaluation.statistical_tests import diebold_mariano_test  # noqa: E402

import statsmodels.api as sm  # noqa: E402
from scipy import stats as scipy_stats  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
RESULTS_JSON = os.path.join(HERE, "k1660_mz_calibration_audit_results.json")

# Pure close-to-close conditional-variance families -> r^2 is the correct target (preamble).
CORE_FAMILY_MAP = {
    "garch_arch": "GARCH(1,1)",
    "gjr_arch": "GJR-GARCH",
    "egarch_arch": "EGARCH",
    "cgarch": "CGARCH",
}
# Secondary (reported with target caveat): hybrid / range / HAR target intraday RV, not r^2.
CAVEAT_FAMILY_MAP = {
    "gjr_har": "GJR-HAR(hybrid)",
}
MIN_N = 200  # families below this flagged, not used for headline verdict


# ----------------------------------------------------------------------------- load forecasts
def load_forecast_records():
    recs = []
    for meta_fp in sorted(glob.glob(os.path.join(REPO, "storage/results/*.json"))):
        if meta_fp.endswith("_forecasts.json"):
            continue
        try:
            meta = json.load(open(meta_fp))
        except Exception as e:  # noqa
            print(f"skip meta {meta_fp}: {e}")
            continue
        if not isinstance(meta, dict) or "asset" not in meta:
            continue
        fam_key = meta.get("model_name")
        if fam_key not in CORE_FAMILY_MAP and fam_key not in CAVEAT_FAMILY_MAP:
            continue
        fc_fp = meta_fp.replace(".json", "_forecasts.json")
        if not os.path.exists(fc_fp):
            continue
        try:
            fc = json.load(open(fc_fp))
        except Exception as e:  # noqa
            print(f"skip forecasts {fc_fp}: {e}")
            continue
        df = pd.DataFrame(fc)
        if df.empty or "variance_forecast" not in df:
            continue
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        df = df[["date", "variance_forecast"]].dropna().sort_values("date")
        recs.append({
            "exp_id": meta.get("experiment_id"),
            "asset": meta.get("asset"),
            "fam_key": fam_key,
            "family": CORE_FAMILY_MAP.get(fam_key, CAVEAT_FAMILY_MAP.get(fam_key)),
            "is_core": fam_key in CORE_FAMILY_MAP,
            "dist": (meta.get("config", {}).get("model_params", {}) or {}).get("dist", "?"),
            "oos_start": meta.get("config", {}).get("oos_start"),
            "oos_end": meta.get("config", {}).get("oos_end"),
            "mean_actual_var_stored": meta.get("metrics", {}).get("mean_actual_var"),
            "fc": df,
        })
    return recs


# ----------------------------------------------------------------------------- realized data
def build_realized(assets, date_min, date_max):
    """Download OHLC per asset (cached), build r^2 (close-to-close) and Parkinson variance."""
    import yfinance as yf
    real = {}
    start = (pd.Timestamp(date_min) - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    end = (pd.Timestamp(date_max) + pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    for a in assets:
        cache = os.path.join(DATA_DIR, f"{a.replace('-', '_')}_ohlc.csv")
        if os.path.exists(cache):
            df = pd.read_csv(cache, parse_dates=["Date"]).set_index("Date")
        else:
            raw = yf.download(a, start=start, end=end, progress=False, auto_adjust=False)
            if raw.empty:
                print(f"WARN empty download {a}")
                continue
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            df = raw[["Open", "High", "Low", "Close"]].copy()
            df.index.name = "Date"
            df.to_csv(cache)
        df = df.sort_index()
        logret = np.log(df["Close"] / df["Close"].shift(1))
        r2 = logret ** 2  # conditionally-unbiased proxy for close-to-close conditional variance
        park = (1.0 / (4.0 * np.log(2.0))) * np.log(df["High"] / df["Low"]) ** 2  # pipeline rv_proxy
        out = pd.DataFrame({"r2": r2, "parkinson": park})
        out.index = pd.to_datetime(out.index).normalize()
        real[a] = out.dropna()
    return real


# ----------------------------------------------------------------------------- MZ core
def hac_lag(n: int) -> int:
    return max(1, int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0))))


def mz_regression(realized: np.ndarray, forecast: np.ndarray, lag: int):
    """OLS realized = a + b*forecast with Newey-West HAC; joint Wald H0: a=0 & b=1."""
    X = sm.add_constant(forecast)
    model = sm.OLS(realized, X)
    # use_t=False -> HAC asymptotic (normal/chi2) inference, required for the joint Wald test
    res = model.fit(cov_type="HAC", cov_kwds={"maxlags": lag}, use_t=False)
    a_hat, b_hat = float(res.params[0]), float(res.params[1])
    a_se, b_se = float(res.bse[0]), float(res.bse[1])
    # t-stats vs (0, 1)
    t_a = a_hat / a_se if a_se > 0 else np.nan
    t_b = (b_hat - 1.0) / b_se if b_se > 0 else np.nan
    p_a = float(2 * (1 - scipy_stats.norm.cdf(abs(t_a)))) if np.isfinite(t_a) else np.nan
    p_b = float(2 * (1 - scipy_stats.norm.cdf(abs(t_b)))) if np.isfinite(t_b) else np.nan
    # joint Wald H0: a=0 AND b=1 with HAC cov (manual, NaN-robust)
    cov = np.asarray(res.cov_params())
    diff = np.array([a_hat - 0.0, b_hat - 1.0])
    if np.isfinite(cov).all() and np.isfinite(diff).all():
        try:
            wald_stat = float(diff @ np.linalg.solve(cov, diff))
            wald_p = float(scipy_stats.chi2.sf(wald_stat, df=2))
        except np.linalg.LinAlgError as e:
            print(f"  WARN wald singular cov (n={len(realized)}): {e}")  # no-silent-fallback
            wald_stat, wald_p = float("nan"), float("nan")
    else:
        print(f"  WARN wald non-finite cov (n={len(realized)}), skipping joint test")  # no-silent-fallback
        wald_stat, wald_p = float("nan"), float("nan")
    return {
        "a_hat": a_hat, "b_hat": b_hat, "a_se": a_se, "b_se": b_se,
        "t_a_vs0": float(t_a), "p_a_vs0": p_a,
        "t_b_vs1": float(t_b), "p_b_vs1": p_b,
        "wald_stat": wald_stat, "wald_p": wald_p,
        "r2": float(res.rsquared), "hac_lag": lag,
    }


def verdict_from(mz, mean_fc, mean_real):
    ratio = mean_fc / mean_real if mean_real > 0 else np.nan
    if not np.isfinite(mz["wald_p"]):
        return "undetermined", ratio
    if mz["wald_p"] > 0.05:
        return "well-calibrated", ratio
    # rejected -> direction
    if ratio > 1.05:
        return "over-forecast", ratio
    if ratio < 0.95:
        return "under-forecast", ratio
    # mean matches but slope off -> conditional miscalibration
    return "conditionally-miscalibrated", ratio


# ----------------------------------------------------------------------------- per-file audit
def audit_file(rec, real):
    a = rec["asset"]
    if a not in real:
        return None
    rdf = real[a]
    fc = rec["fc"]
    merged = fc.merge(rdf, left_on="date", right_index=True, how="inner").dropna(
        subset=["variance_forecast", "r2", "parkinson"]
    )
    n = len(merged)
    if n < 30:
        return None
    f = merged["variance_forecast"].to_numpy(float)
    r2 = merged["r2"].to_numpy(float)
    park = merged["parkinson"].to_numpy(float)
    lag = hac_lag(n)

    # validation: our reconstructed Parkinson vs stored mean_actual_var
    mean_park = float(np.mean(park))
    stored = rec["mean_actual_var_stored"]
    park_match_ratio = (mean_park / stored) if (stored and stored > 0) else np.nan

    # PRIMARY MZ: r^2 target (variance space)
    mz_r2 = mz_regression(r2, f, lag)
    # log-variance robustness (drop non-finite / zero r^2)
    lr = np.log(np.maximum(r2, 1e-16))
    lf = np.log(np.maximum(f, 1e-16))
    good = np.isfinite(lr) & np.isfinite(lf) & (r2 > 1e-14)
    mz_log = mz_regression(lr[good], lf[good], hac_lag(int(good.sum()))) if good.sum() > 30 else None
    # DIAGNOSTIC MZ: Parkinson target (as the pipeline evaluated) — shows proxy effect
    mz_park = mz_regression(park, f, lag)

    mean_fc, mean_r2 = float(np.mean(f)), float(np.mean(r2))
    verdict, ratio = verdict_from(mz_r2, mean_fc, mean_r2)

    return {
        "exp_id": rec["exp_id"], "asset": a, "family": rec["family"],
        "fam_key": rec["fam_key"], "is_core": rec["is_core"], "dist": rec["dist"],
        "oos_start": rec["oos_start"], "oos_end": rec["oos_end"], "n": n, "hac_lag": lag,
        "mean_forecast_var": mean_fc, "mean_realized_r2": mean_r2,
        "fc_over_r2_ratio": ratio,
        "mean_parkinson": mean_park, "mean_actual_var_stored": stored,
        "parkinson_validation_ratio": park_match_ratio,
        "mz_r2": mz_r2, "mz_logvar": mz_log, "mz_parkinson_diag": mz_park,
        "verdict": verdict,
        "_arrays": {"f": f, "r2": r2, "dates": merged["date"].astype(str).tolist()},
    }


# ----------------------------------------------------------------------------- bias correction (OOS)
def expanding_bias_correction(f, r2, burn=60):
    """Expanding-window MZ correction (OOS-valid): at t use params from data < t."""
    n = len(f)
    if n <= burn + 20:
        return None
    f_adj = np.full(n, np.nan)
    for t in range(burn, n):
        X = sm.add_constant(f[:t])
        try:
            p = sm.OLS(r2[:t], X).fit().params
            # economically-sane floor: corrected variance never below 20% of the model's own
            # forecast (prevents early-window unstable fits from producing near-zero f_adj that
            # blows up QLIKE = actual/f_adj). Relative floor, not an absolute magic number.
            f_adj[t] = max(p[0] + p[1] * f[t], 0.2 * f[t], 1e-8)
        except Exception as e:  # noqa
            print(f"  bias-corr fit fail t={t}: {e}")  # no-silent-fallback
            f_adj[t] = f[t]
    mask = np.arange(n) >= burn
    q_raw = qlike_pointwise(r2[mask], f[mask])
    q_adj = qlike_pointwise(r2[mask], f_adj[mask])
    dm = diebold_mariano_test(q_raw, q_adj)  # loss1=raw, loss2=adj; positive stat => raw worse
    return {
        "n_eval": int(mask.sum()), "burn": burn,
        "qlike_raw": float(np.mean(q_raw)), "qlike_adj_expanding": float(np.mean(q_adj)),
        "qlike_improvement_pct": float(100 * (np.mean(q_raw) - np.mean(q_adj)) / abs(np.mean(q_raw)))
        if np.mean(q_raw) != 0 else np.nan,
        "dm_stat": float(dm.get("statistic", dm.get("dm_stat", np.nan))),
        "dm_p": float(dm.get("p_value", dm.get("pvalue", np.nan))),
    }


def insample_correction(f, r2):
    """Full-sample linear correction — IN-SAMPLE diagnostic upper bound only."""
    X = sm.add_constant(f)
    p = sm.OLS(r2, X).fit().params
    f_adj = np.maximum(p[0] + p[1] * f, 1e-10)
    q_raw = qlike_pointwise(r2, f)
    q_adj = qlike_pointwise(r2, f_adj)
    return {
        "qlike_raw": float(np.mean(q_raw)), "qlike_adj_insample": float(np.mean(q_adj)),
        "qlike_improvement_pct": float(100 * (np.mean(q_raw) - np.mean(q_adj)) / abs(np.mean(q_raw)))
        if np.mean(q_raw) != 0 else np.nan,
    }


# ----------------------------------------------------------------------------- main
def main():
    t0 = datetime.now()
    recs = load_forecast_records()
    print(f"loaded {len(recs)} forecast files (core+caveat families)")
    assets = sorted({r["asset"] for r in recs})
    dmin = min(pd.Timestamp(r["fc"]["date"].min()) for r in recs)
    dmax = max(pd.Timestamp(r["fc"]["date"].max()) for r in recs)
    print(f"assets={assets}  date range {dmin.date()}..{dmax.date()}")
    real = build_realized(assets, dmin, dmax)

    audits = []
    for r in recs:
        a = audit_file(r, real)
        if a is not None:
            audits.append(a)
    print(f"completed {len(audits)} per-file MZ audits")

    # ---- family-level aggregation (core families, n>=MIN_N) ----
    families = {}
    for a in audits:
        if not a["is_core"]:
            continue
        fam = a["family"]
        families.setdefault(fam, [])
        if a["n"] >= MIN_N:
            families[fam].append(a)

    family_summary = {}
    for fam, items in families.items():
        if not items:
            continue
        verdicts = [it["verdict"] for it in items]
        b_hats = [it["mz_r2"]["b_hat"] for it in items]
        a_hats = [it["mz_r2"]["a_hat"] for it in items]
        ratios = [it["fc_over_r2_ratio"] for it in items]
        wald_reject = sum(1 for it in items if it["mz_r2"]["wald_p"] <= 0.05)
        family_summary[fam] = {
            "n_files": len(items),
            "assets": sorted({it["asset"] for it in items}),
            "median_b_hat": float(np.median(b_hats)),
            "mean_b_hat": float(np.mean(b_hats)),
            "median_a_hat": float(np.median(a_hats)),
            "median_fc_over_r2_ratio": float(np.median(ratios)),
            "n_wald_reject_at_5pct": int(wald_reject),
            "frac_wald_reject": float(wald_reject / len(items)),
            "verdict_counts": {v: verdicts.count(v) for v in set(verdicts)},
        }

    # ---- flagship bias-correction: one SPY file per core family, 2023-2024 window ----
    flagship = {}
    for fam in CORE_FAMILY_MAP.values():
        cand = [a for a in audits if a["family"] == fam and a["asset"] == "SPY"
                and a["oos_start"] == "2023-01-01" and a["n"] >= MIN_N]
        if not cand:
            cand = [a for a in audits if a["family"] == fam and a["asset"] == "SPY" and a["n"] >= MIN_N]
        if not cand:
            continue
        pick = max(cand, key=lambda x: x["n"])
        f = np.array(pick["_arrays"]["f"]); r2 = np.array(pick["_arrays"]["r2"])
        exp = expanding_bias_correction(f, r2)
        ins = insample_correction(f, r2)
        flagship[fam] = {
            "exp_id": pick["exp_id"], "asset": "SPY",
            "oos_start": pick["oos_start"], "oos_end": pick["oos_end"], "n": pick["n"],
            "mz_r2": pick["mz_r2"], "verdict": pick["verdict"],
            "fc_over_r2_ratio": pick["fc_over_r2_ratio"],
            "bias_correction_expanding_OOS": exp,
            "bias_correction_full_sample_INSAMPLE_diag": ins,
        }
        print(f"flagship {fam}: b={pick['mz_r2']['b_hat']:.3f} wald_p={pick['mz_r2']['wald_p']:.3g} "
              f"verdict={pick['verdict']}")

    # ---- Parkinson-proxy diagnostic: library-wide validation + proxy-effect ----
    valid_ratios = [a["parkinson_validation_ratio"] for a in audits
                    if a["parkinson_validation_ratio"] and np.isfinite(a["parkinson_validation_ratio"])]
    proxy_diag = {
        "n_files_validated": len(valid_ratios),
        "median_parkinson_vs_stored_ratio": float(np.median(valid_ratios)) if valid_ratios else None,
        "note": ("Ratio ~1.0 confirms reconstructed OHLC matches pipeline data source; "
                 "stored mean_actual_var == mean Parkinson variance."),
    }
    # median b under Parkinson vs r^2 across core files (shows proxy inflates over-forecast)
    core = [a for a in audits if a["is_core"] and a["n"] >= MIN_N]
    proxy_diag["median_b_hat_r2_target"] = float(np.median([a["mz_r2"]["b_hat"] for a in core])) if core else None
    proxy_diag["median_b_hat_parkinson_target"] = float(
        np.median([a["mz_parkinson_diag"]["b_hat"] for a in core])) if core else None
    proxy_diag["median_fc_over_parkinson_ratio"] = float(
        np.median([a["mean_forecast_var"] / a["mean_parkinson"] for a in core if a["mean_parkinson"] > 0])) if core else None
    proxy_diag["median_fc_over_r2_ratio"] = float(
        np.median([a["fc_over_r2_ratio"] for a in core if np.isfinite(a["fc_over_r2_ratio"])])) if core else None

    # strip large arrays before serialization
    audits_out = []
    for a in audits:
        a2 = {k: v for k, v in a.items() if k != "_arrays"}
        audits_out.append(a2)

    out = {
        "experiment_id": "k1660_mz_calibration_audit",
        "title": "Mincer-Zarnowitz calibration audit of the VolPred HAR/GARCH forecast library",
        "generated_at": t0.isoformat(),
        "seed": 42,
        "method": {
            "mz_regression": "realized = a + b*forecast (OLS, Newey-West HAC, lag=floor(4*(n/100)^(2/9)))",
            "joint_test": "HAC Wald H0: a=0 AND b=1",
            "primary_realized_target": "r^2 = (log close-to-close return)^2 (conditionally unbiased, preamble-correct for GARCH-family)",
            "diagnostic_realized_target": "Parkinson variance (pipeline rv_proxy) — for data validation + proxy-effect diagnostic",
            "unit": "one forecast file = single-asset OOS series (no asset-day iid pooling; K1355-safe)",
            "qlike": "volpred.stats.model_evaluation.qlike_pointwise (canonical actual/predicted direction)",
        },
        "n_files_audited": len(audits),
        "assets": assets,
        "family_summary": family_summary,
        "flagship_bias_correction": flagship,
        "proxy_scale_diagnostic": proxy_diag,
        "per_file": audits_out,
    }

    # atomic write (preamble rule)
    tmp = RESULTS_JSON + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(out, fh, indent=2, default=lambda o: None if isinstance(o, float) and not np.isfinite(o) else o)
    json.load(open(tmp))
    os.replace(tmp, RESULTS_JSON)
    print(f"wrote {RESULTS_JSON}")

    # keep flagship arrays for plotting
    return out, {fam: flagship[fam]["exp_id"] for fam in flagship}, audits, real


if __name__ == "__main__":
    out, flag_ids, audits, real = main()
    # charts
    try:
        from k1660_make_charts import make_charts
        make_charts(out, audits)
    except Exception as e:  # noqa
        print(f"chart generation deferred: {e}")
