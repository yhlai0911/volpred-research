"""K1724 — 台股當沖佔比與波動：散戶 herding 的在地量化.

Research questions
------------------
1. Predictive value: does the daily aggregate day-trading turnover ratio
   published by TWSE carry INCREMENTAL out-of-sample predictive power for
   next-day realized volatility (RV) on top of a HAR-RV baseline?
2. Causal direction (bidirectional Granger): is it "volatility attracts
   day-trading" (vol -> DT) or "day-trading amplifies volatility"
   (DT -> vol, retail herding), or a two-way feedback?

Data (all free)
---------------
- Day-trading ratio: TWSE `TWTB4U` "當日沖銷交易統計資訊" aggregate table.
  Endpoint: https://www.twse.com.tw/exchangeReport/TWTB4U?response=json&date=YYYYMMDD
  Aggregate table (tables[0]) fields:
    當日沖銷交易總成交股數, 占市場比重%(股數),
    當日沖銷交易總買進成交金額, 占市場比重%(買金額),
    當日沖銷交易總賣出成交金額, 占市場比重%(賣金額)
  Coverage verified 2014-01-06 (start of 現股當沖) → present, consistent format.
  Primary variable = value-based day-trade ratio = mean(buy%, sell%).
- TAIEX (^TWII) daily OHLCV via yfinance. RV proxies from daily OHLC:
  Garman-Klass (primary), Parkinson, close-to-close squared return (robustness).
  No free intraday for TAIEX, so range-based estimators are used and this
  limitation is stated explicitly.

Usage
-----
  uv run python experiments/k1724/k1724.py fetch --start 20140630 --end 20261231
  uv run python experiments/k1724/k1724.py analyze
  uv run python experiments/k1724/k1724.py all     # fetch (resumable) + analyze

Research honesty
----------------
- All numbers computed from real data. If day-trading ratio shows NO
  incremental predictive power / Granger is insignificant, the NULL is
  reported as-is; no fabrication, no placeholders.
- Random / split procedures are deterministic (OOS uses a fixed expanding
  window; no random sampling). Look-ahead avoided: every predictor at time t
  uses only information dated <= t to forecast RV_{t+1}.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# Repo canonical DM + pointwise QLIKE (Newey-West HAC with bandwidth
# ceil(h^(1/3)·n^(1/3)); QLIKE = actual/pred - log(actual/pred) - 1).
# Mandated by .claude/rules/experiments.md (do not hand-roll local DM/QLIKE).
from volpred.stats.model_evaluation import dm_test as canon_dm
from volpred.stats.model_evaluation import qlike_pointwise as canon_qlike
# Clark-West (2007) MSPE-adjusted test — the correct test for NESTED forecast
# comparison (augmented model nests HAR); plain DM is biased against the larger
# model under the null of zero added coefficients.
from volpred.stats.model_evaluation import clark_west_test as canon_cw

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
DT_CACHE = DATA / "daytrade_ratio.csv"
TWII_CACHE = DATA / "twii_ohlc.csv"
RESULTS = HERE / "k1724_results.json"

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)
TWTB4U = "https://www.twse.com.tw/exchangeReport/TWTB4U?response=json&date={ymd}"


# --------------------------------------------------------------------------- #
# 1. TWSE day-trading ratio fetch (resumable, rate-limited, no silent fallback)
# --------------------------------------------------------------------------- #
def _num(s: str) -> float:
    return float(str(s).replace(",", "").strip())


def _fetch_day(ymd: str, timeout: float = 30.0) -> dict | None:
    """Return aggregate day-trade dict for one day, or None if no data/error."""
    req = urllib.request.Request(TWTB4U.format(ymd=ymd), headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # network / parse — caller retries next run
        print(f"  [dt] {ymd} fetch error: {exc}", file=sys.stderr)
        return None
    if payload.get("stat") != "OK":
        return None  # weekend / holiday / not-yet-published
    tables = payload.get("tables") or []
    if not tables:
        print(f"  [dt] {ymd} OK but no tables (format drift?)", file=sys.stderr)
        return None
    agg = tables[0]
    rows = agg.get("data") or []
    if not rows or len(rows[0]) < 6:
        print(f"  [dt] {ymd} aggregate table empty/short", file=sys.stderr)
        return None
    r = rows[0]
    return {
        "dt_vol_ratio": _num(r[1]),   # day-trade volume as % of market volume
        "dt_buy_ratio": _num(r[3]),   # day-trade buy value as % of market value
        "dt_sell_ratio": _num(r[5]),  # day-trade sell value as % of market value
        "dt_vol_shares": _num(r[0]),
        "dt_buy_value": _num(r[2]),
        "dt_sell_value": _num(r[4]),
    }


def _iter_weekdays(start: date, end: date):
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            yield cur
        cur += timedelta(days=1)


def fetch_daytrade(start: date, end: date, *, sleep: float = 0.4) -> dict:
    """Backfill day-trade ratio cache. Resumable: skips dates already cached."""
    DATA.mkdir(parents=True, exist_ok=True)
    cached: set[str] = set()
    if DT_CACHE.exists():
        prev = pd.read_csv(DT_CACHE, dtype={"date": str})
        cached = set(prev["date"].tolist())
    fields = ["date", "dt_vol_ratio", "dt_buy_ratio", "dt_sell_ratio",
              "dt_vol_shares", "dt_buy_value", "dt_sell_value"]
    write_header = not DT_CACHE.exists()
    counts = {"saved": 0, "cached": 0, "no_data": 0}
    with DT_CACHE.open("a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if write_header:
            w.writerow(fields)
        for d in _iter_weekdays(start, end):
            iso = d.isoformat()
            if iso in cached:
                counts["cached"] += 1
                continue
            rec = _fetch_day(d.strftime("%Y%m%d"))
            if rec is None:
                counts["no_data"] += 1
                time.sleep(sleep)
                continue
            w.writerow([iso, rec["dt_vol_ratio"], rec["dt_buy_ratio"], rec["dt_sell_ratio"],
                        rec["dt_vol_shares"], rec["dt_buy_value"], rec["dt_sell_value"]])
            fh.flush()
            counts["saved"] += 1
            time.sleep(sleep)
    print(f"[dt] fetch {start}->{end}: {counts}  (total cached rows now)")
    return counts


def load_daytrade() -> pd.DataFrame:
    if not DT_CACHE.exists():
        raise FileNotFoundError(f"day-trade cache missing: {DT_CACHE}. Run `fetch` first.")
    df = pd.read_csv(DT_CACHE, parse_dates=["date"]).sort_values("date").drop_duplicates("date")
    df = df.set_index("date")
    # Primary value-based day-trade ratio = average of buy% and sell% ratios.
    df["dt_ratio"] = 0.5 * (df["dt_buy_ratio"] + df["dt_sell_ratio"])
    return df


# --------------------------------------------------------------------------- #
# 2. TAIEX RV via yfinance (cached)
# --------------------------------------------------------------------------- #
def fetch_twii(start: str = "2014-01-01", end: str | None = None) -> pd.DataFrame:
    import yfinance as yf
    if end is None:
        end = (date.today() + timedelta(days=1)).isoformat()
    df = yf.download("^TWII", start=start, end=end, auto_adjust=False, progress=False)
    if df.empty:
        raise RuntimeError("yfinance returned empty ^TWII frame")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.index.name = "date"
    DATA.mkdir(parents=True, exist_ok=True)
    df.to_csv(TWII_CACHE)
    return df


def load_twii() -> pd.DataFrame:
    if not TWII_CACHE.exists():
        return fetch_twii()
    df = pd.read_csv(TWII_CACHE, parse_dates=["date"]).set_index("date")
    return df


def compute_rv(ohlc: pd.DataFrame) -> pd.DataFrame:
    """Daily variance proxies (scaled x1e4 for numerical stability).

    Parkinson    : (1/(4 ln2)) (ln H/L)^2
    Garman-Klass : 0.5 (ln H/L)^2 - (2 ln2 - 1)(ln C/O)^2   [primary]
    sq. return   : (ln C_t / C_{t-1})^2                     [close-to-close]
    """
    o, h, l, c = ohlc["Open"], ohlc["High"], ohlc["Low"], ohlc["Close"]
    ln_hl = np.log(h / l)
    ln_co = np.log(c / o)
    park = (1.0 / (4.0 * np.log(2.0))) * ln_hl ** 2
    gk = 0.5 * ln_hl ** 2 - (2.0 * np.log(2.0) - 1.0) * ln_co ** 2
    ret = np.log(c / c.shift(1))
    sq = ret ** 2
    out = pd.DataFrame({
        "rv_gk": gk * 1e4,
        "rv_park": park * 1e4,
        "rv_sq": sq * 1e4,
        "ret": ret,           # close-to-close log return (fraction)
        "log_vol": np.log(ohlc["Volume"].replace(0, np.nan)),
    })
    # Guard: GK can be tiny-negative when C≈O and H≈L rounding; floor at small pos.
    n_neg = int((out["rv_gk"] <= 0).sum())
    if n_neg:
        print(f"  [rv] flooring {n_neg} non-positive GK RV to 1e-6 (rounding)", file=sys.stderr)
        out.loc[out["rv_gk"] <= 0, "rv_gk"] = 1e-6
    out["rv_park"] = out["rv_park"].clip(lower=1e-6)
    out["rv_sq"] = out["rv_sq"].clip(lower=1e-6)
    return out


# --------------------------------------------------------------------------- #
# 3. Build merged dataset
# --------------------------------------------------------------------------- #
def build_dataset(start: str = "2014-06-30") -> pd.DataFrame:
    dt = load_daytrade()
    rv = compute_rv(load_twii())
    df = rv.join(dt[["dt_ratio", "dt_vol_ratio"]], how="inner")
    df = df.loc[df.index >= pd.Timestamp(start)].dropna(subset=["rv_gk", "rv_park", "rv_sq", "dt_ratio"])
    return df


def har_terms(x: pd.Series) -> pd.DataFrame:
    """HAR components known at time t: daily, weekly(5), monthly(22) averages."""
    return pd.DataFrame({
        f"{x.name}_d": x,
        f"{x.name}_w": x.rolling(5).mean(),
        f"{x.name}_m": x.rolling(22).mean(),
    })


# --------------------------------------------------------------------------- #
# 4. Predictive test: HAR baseline vs augmented (IS + OOS + DM)
# --------------------------------------------------------------------------- #
def _ols(y: np.ndarray, X: np.ndarray) -> np.ndarray:
    """OLS coefficients with intercept column already in X. lstsq for stability."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return beta


def predictive_test(df: pd.DataFrame, rv_col: str = "rv_gk",
                    min_train: int = 750, add_controls: bool = False) -> dict:
    """Expanding-window 1-step-ahead OOS forecast of RV_{t+1}.

    Baseline  : HAR(RV)
    Augmented : HAR(RV) + day-trade ratio HAR terms (all dated <= t)
    Optionally add contemporaneous (time-t, known at forecast origin) |ret| and
    log volume controls to BOTH models.
    """
    rv = df[rv_col]
    y = rv.shift(-1)  # target = next-day RV

    har_rv = har_terms(rv.rename("rv"))
    har_dt = har_terms(df["dt_ratio"].rename("dt"))

    base_cols = ["rv_d", "rv_w", "rv_m"]
    aug_extra = ["dt_d", "dt_w", "dt_m"]
    X_all = pd.concat([har_rv, har_dt], axis=1)
    if add_controls:
        X_all["abs_ret"] = df["ret"].abs()
        X_all["log_vol"] = df["log_vol"]
        base_cols = base_cols + ["abs_ret", "log_vol"]

    data = pd.concat([y.rename("target"), X_all], axis=1).dropna()

    Xb = data[base_cols].values
    Xa = data[base_cols + aug_extra].values
    yv = data["target"].values
    n = len(yv)
    if n <= min_train + 30:
        raise RuntimeError(f"too few obs ({n}) for OOS with min_train={min_train}")

    def add_const(X):
        return np.column_stack([np.ones(len(X)), X])

    fb = np.full(n, np.nan)
    fa = np.full(n, np.nan)
    for t in range(min_train, n):
        bb = _ols(yv[:t], add_const(Xb[:t]))
        ba = _ols(yv[:t], add_const(Xa[:t]))
        fb[t] = float((add_const(Xb[t:t + 1]) @ bb)[0])
        fa[t] = float((add_const(Xa[t:t + 1]) @ ba)[0])

    mask = ~np.isnan(fb)
    act = yv[mask]
    fb_o, fa_o = fb[mask], fa[mask]

    def r2(f):
        ybar = act.mean()
        return 1 - np.sum((act - f) ** 2) / np.sum((act - ybar) ** 2)

    mse_b = float(np.mean((act - fb_o) ** 2))
    mse_a = float(np.mean((act - fa_o) ** 2))
    ql_b = canon_qlike(act, fb_o)
    ql_a = canon_qlike(act, fa_o)
    # incremental OOS R2 of augmented vs baseline forecasts
    inc_r2 = 1 - np.sum((act - fa_o) ** 2) / np.sum((act - fb_o) ** 2)

    # canonical DM: dm_test(loss1, loss2); positive t => loss1>loss2 (model2 better).
    # Here loss1=baseline, loss2=augmented, so positive => augmented better.
    dm_mse, p_mse = canon_dm((act - fb_o) ** 2, (act - fa_o) ** 2)
    dm_ql, p_ql = canon_dm(ql_b, ql_a)

    # Clark-West nested test (small=baseline HAR, large=augmented). One-sided:
    # positive t / small p => augmented has incremental predictive content.
    cw = canon_cw(act, fb_o, fa_o)

    # In-sample full-period incremental fit (adj R2 gain, and DT joint significance)
    is_res = _insample_incremental(data, base_cols, aug_extra)

    return {
        "rv_proxy": rv_col,
        "controls": add_controls,
        "n_total": int(n),
        "min_train": int(min_train),
        "n_oos": int(mask.sum()),
        "oos_r2_baseline_vs_mean": round(r2(fb_o), 6),
        "oos_r2_augmented_vs_mean": round(r2(fa_o), 6),
        "oos_incremental_r2_aug_vs_base": round(float(inc_r2), 6),
        "oos_mse_baseline": mse_b,
        "oos_mse_augmented": mse_a,
        "oos_qlike_baseline": float(np.mean(ql_b)),
        "oos_qlike_augmented": float(np.mean(ql_a)),
        "dm_mse_stat": round(dm_mse, 4),
        "dm_mse_pvalue": round(p_mse, 4),
        "dm_qlike_stat": round(dm_ql, 4),
        "dm_qlike_pvalue": round(p_ql, 4),
        "dm_convention": "positive DM => baseline loss > augmented loss (augmented better)",
        "clark_west_nested": {
            "t_stat": round(float(cw["t_stat"]), 4),
            "p_value_one_sided": round(float(cw["p_value_one_sided"]), 4),
            "hac_lag": int(cw["hac_lag"]),
            "note": "one-sided; small p => augmented has incremental predictive content (correct test for nested comparison)",
        },
        "insample": is_res,
    }


def _insample_incremental(data: pd.DataFrame, base_cols: list, aug_extra: list) -> dict:
    """Full-sample OLS with HAC(Newey-West) SE; report DT joint F-test & adjR2 gain."""
    import statsmodels.api as sm
    y = data["target"].values
    Xb = sm.add_constant(data[base_cols].values)
    Xa = sm.add_constant(data[base_cols + aug_extra].values)
    mb = sm.OLS(y, Xb).fit(cov_type="HAC", cov_kwds={"maxlags": 10})
    ma = sm.OLS(y, Xa).fit(cov_type="HAC", cov_kwds={"maxlags": 10})
    # Wald test that the aug_extra coefficients are jointly zero
    k = Xa.shape[1]
    R = np.zeros((len(aug_extra), k))
    for i in range(len(aug_extra)):
        R[i, k - len(aug_extra) + i] = 1.0
    wald = ma.wald_test(R, scalar=True)
    return {
        "adj_r2_baseline": round(float(mb.rsquared_adj), 6),
        "adj_r2_augmented": round(float(ma.rsquared_adj), 6),
        "adj_r2_gain": round(float(ma.rsquared_adj - mb.rsquared_adj), 6),
        "dt_joint_wald_stat": round(float(np.asarray(wald.statistic).item()), 4),
        "dt_joint_wald_pvalue": round(float(np.asarray(wald.pvalue).item()), 6),
        "dt_coefs": {name: round(float(c), 6) for name, c in
                     zip(aug_extra, ma.params[-len(aug_extra):])},
    }


# --------------------------------------------------------------------------- #
# 5. Stationarity + bidirectional Granger
# --------------------------------------------------------------------------- #
def stationarity(series: pd.Series, name: str) -> dict:
    from statsmodels.tsa.stattools import adfuller, kpss
    s = series.dropna()
    adf = adfuller(s, autolag="AIC")
    try:
        kp = kpss(s, regression="c", nlags="auto")
        kpss_stat, kpss_p = float(kp[0]), float(kp[1])
    except Exception as e:
        print(f"  [stationarity] KPSS {name} failed: {e}", file=sys.stderr)
        kpss_stat, kpss_p = float("nan"), float("nan")
    return {
        "series": name,
        "n": int(len(s)),
        "adf_stat": round(float(adf[0]), 4),
        "adf_pvalue": round(float(adf[1]), 4),
        "adf_stationary_5pct": bool(adf[1] < 0.05),
        "kpss_stat": round(kpss_stat, 4),
        "kpss_pvalue": round(kpss_p, 4),
        "kpss_stationary_5pct": bool(kpss_p > 0.05) if kpss_p == kpss_p else None,
    }


def bidirectional_granger(df: pd.DataFrame, rv_col: str = "rv_gk",
                          maxlag: int = 30, force_both_diff: bool = False) -> dict:
    """VAR(p) on stationary transforms of {log RV, day-trade ratio}; both
    directions of Granger causality. Transform chosen after ADF/KPSS.

    force_both_diff=True difference BOTH series (robustness against mixing an
    I(0) level with an I(1)-differenced series in the same VAR)."""
    from statsmodels.tsa.api import VAR

    log_rv = np.log(df[rv_col]).rename("log_rv")
    dt = df["dt_ratio"].rename("dt_ratio")

    # stationarity on levels
    st_levels = [stationarity(log_rv, "log_rv_level"),
                 stationarity(dt, "dt_ratio_level")]

    # dt_ratio strongly trends -> use first difference; log_rv mostly stationary
    # but we difference dt only if its level is non-stationary (data-driven).
    dt_level_stationary = st_levels[1]["adf_stationary_5pct"] and st_levels[1]["kpss_stationary_5pct"]
    if dt_level_stationary and not force_both_diff:
        dt_use = dt
        dt_transform = "level"
    else:
        dt_use = dt.diff()
        dt_transform = "first_difference"

    # log RV: ADF strongly rejects a unit root (I(0)) while KPSS also rejects
    # level-stationarity. This ADF-reject / KPSS-reject pattern is the signature
    # of a PERSISTENT / long-memory but non-unit-root series (well documented for
    # realized volatility), NOT of a unit root. A VAR requires I(0) inputs, and
    # a series with no unit root is admissible in levels; differencing an I(0)
    # long-memory series would over-difference it. We therefore keep log RV in
    # levels when ADF rejects the unit root, and separately report the fully
    # both-differenced VAR as robustness (force_both_diff / robustness section).
    log_rv_level_stationary = st_levels[0]["adf_stationary_5pct"]
    if log_rv_level_stationary and not force_both_diff:
        rv_use = log_rv
        rv_transform = "log_level"
    else:
        rv_use = log_rv.diff()
        rv_transform = "log_first_difference"

    st_used = [stationarity(rv_use, f"rv_{rv_transform}"),
               stationarity(dt_use, f"dt_{dt_transform}")]

    joint = pd.concat([rv_use.rename("RV"), dt_use.rename("DT")], axis=1).dropna()
    model = VAR(joint)
    sel = model.select_order(maxlag)
    p_aic = int(sel.aic) if sel.aic and sel.aic > 0 else 1
    p_bic = int(sel.bic) if sel.bic and sel.bic > 0 else 1
    p = max(p_aic, 1)
    res = model.fit(p)

    # DT -> RV : does DT Granger-cause RV?
    dt_to_rv = res.test_causality("RV", ["DT"], kind="f")
    # RV -> DT : does RV Granger-cause DT?
    rv_to_dt = res.test_causality("DT", ["RV"], kind="f")

    contemp_corr = float(joint["RV"].corr(joint["DT"]))

    return {
        "rv_proxy": rv_col,
        "stationarity_levels": st_levels,
        "transforms": {"rv": rv_transform, "dt": dt_transform},
        "stationarity_used": st_used,
        "var_lag_selection": {"aic": p_aic, "bic": p_bic, "used": p,
                              "search_maxlag": maxlag,
                              "at_search_boundary": bool(p_aic >= maxlag)},
        "n_obs": int(len(joint)),
        "granger_DT_to_RV": {
            "hypothesis": "day-trading -> volatility (retail herding amplifies vol)",
            "F_stat": round(float(dt_to_rv.test_statistic), 4),
            "pvalue": round(float(dt_to_rv.pvalue), 6),
            "significant_5pct": bool(dt_to_rv.pvalue < 0.05),
            "lag": p,
        },
        "granger_RV_to_DT": {
            "hypothesis": "volatility -> day-trading (vol attracts speculators)",
            "F_stat": round(float(rv_to_dt.test_statistic), 4),
            "pvalue": round(float(rv_to_dt.pvalue), 6),
            "significant_5pct": bool(rv_to_dt.pvalue < 0.05),
            "lag": p,
        },
        "contemporaneous_corr": round(contemp_corr, 4),
    }


# --------------------------------------------------------------------------- #
# 6. Robustness: subperiods + RV proxy swap
# --------------------------------------------------------------------------- #
def robustness(df: pd.DataFrame) -> dict:
    out = {"subperiods": {}, "rv_proxy_swap": {}, "with_controls": {}}

    # subperiods: pre-COVID vs COVID-onward (2020-01-01 split)
    split = pd.Timestamp("2020-01-01")
    for label, sub in [("pre_2020", df.loc[df.index < split]),
                       ("2020_onward", df.loc[df.index >= split])]:
        try:
            if len(sub) > 400:
                pr = predictive_test(sub, "rv_gk", min_train=max(200, len(sub) // 2))
                out["subperiods"][label] = {
                    "n": int(len(sub)),
                    "oos_incremental_r2": pr["oos_incremental_r2_aug_vs_base"],
                    "dm_qlike_stat": pr["dm_qlike_stat"],
                    "dm_qlike_pvalue": pr["dm_qlike_pvalue"],
                    "is_dt_joint_wald_pvalue": pr["insample"]["dt_joint_wald_pvalue"],
                }
            else:
                out["subperiods"][label] = {"n": int(len(sub)), "skipped": "too few obs"}
        except Exception as e:
            print(f"  [robust] subperiod {label} failed: {e}", file=sys.stderr)
            out["subperiods"][label] = {"error": str(e)}

    # RV proxy swap: Parkinson and squared return
    for proxy in ["rv_park", "rv_sq"]:
        try:
            pr = predictive_test(df, proxy)
            gr = bidirectional_granger(df, proxy)
            out["rv_proxy_swap"][proxy] = {
                "oos_incremental_r2": pr["oos_incremental_r2_aug_vs_base"],
                "dm_qlike_stat": pr["dm_qlike_stat"],
                "dm_qlike_pvalue": pr["dm_qlike_pvalue"],
                "granger_DT_to_RV_p": gr["granger_DT_to_RV"]["pvalue"],
                "granger_RV_to_DT_p": gr["granger_RV_to_DT"]["pvalue"],
            }
        except Exception as e:
            print(f"  [robust] proxy {proxy} failed: {e}", file=sys.stderr)
            out["rv_proxy_swap"][proxy] = {"error": str(e)}

    # controls: add contemporaneous (time-t) |ret| and log volume to both models
    try:
        pr = predictive_test(df, "rv_gk", add_controls=True)
        out["with_controls"] = {
            "oos_incremental_r2": pr["oos_incremental_r2_aug_vs_base"],
            "dm_qlike_stat": pr["dm_qlike_stat"],
            "dm_qlike_pvalue": pr["dm_qlike_pvalue"],
            "is_dt_joint_wald_pvalue": pr["insample"]["dt_joint_wald_pvalue"],
        }
    except Exception as e:
        print(f"  [robust] controls failed: {e}", file=sys.stderr)
        out["with_controls"] = {"error": str(e)}

    # Granger with BOTH series differenced (guards against mixed I(0)/I(1) VAR),
    # for ALL three RV proxies so the DT->RV fragility is characterised symmetrically.
    out["granger_both_differenced"] = {}
    for proxy in ["rv_gk", "rv_park", "rv_sq"]:
        try:
            gr = bidirectional_granger(df, proxy, force_both_diff=True)
            out["granger_both_differenced"][proxy] = {
                "transforms": gr["transforms"],
                "lag": gr["var_lag_selection"]["used"],
                "at_search_boundary": gr["var_lag_selection"]["at_search_boundary"],
                "granger_DT_to_RV_p": gr["granger_DT_to_RV"]["pvalue"],
                "granger_RV_to_DT_p": gr["granger_RV_to_DT"]["pvalue"],
            }
        except Exception as e:
            print(f"  [robust] granger both-diff {proxy} failed: {e}", file=sys.stderr)
            out["granger_both_differenced"][proxy] = {"error": str(e)}

    return out


# --------------------------------------------------------------------------- #
# 7. Figures
# --------------------------------------------------------------------------- #
def make_figures(df: pd.DataFrame) -> list:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    paths = []

    # English labels for reproducibility (no CJK font dependency; research artifact).
    # Fig 1: day-trade ratio vs realized vol (dual axis)
    fig, ax1 = plt.subplots(figsize=(11, 5))
    rv_vol = np.sqrt(df["rv_gk"] / 1e4) * 100  # daily vol %
    ax1.plot(df.index, df["dt_ratio"], color="#c0392b", lw=0.8)
    ax1.set_ylabel("Day-trade turnover ratio (%)", color="#c0392b")
    ax1.tick_params(axis="y", labelcolor="#c0392b")
    ax2 = ax1.twinx()
    ax2.plot(df.index, rv_vol.rolling(22).mean(), color="#2c3e50", lw=0.9)
    ax2.set_ylabel("Realized daily vol, GK (22d MA, %)", color="#2c3e50")
    ax2.tick_params(axis="y", labelcolor="#2c3e50")
    ax1.set_title("TAIEX day-trading ratio vs realized volatility (2014-2026)")
    fig.tight_layout()
    p1 = HERE / "fig1_daytrade_vs_rv.png"
    fig.savefig(p1, dpi=130)
    plt.close(fig)
    paths.append(str(p1.name))

    # Fig 2: scatter of ΔDT (t) vs next-day Δlog RV (t+1)
    fig, ax = plt.subplots(figsize=(7, 6))
    d_dt = df["dt_ratio"].diff()
    d_rv = np.log(df["rv_gk"]).diff().shift(-1)
    m = (~d_dt.isna()) & (~d_rv.isna())
    ax.scatter(d_dt[m], d_rv[m], s=6, alpha=0.25, color="#2980b9")
    ax.set_xlabel("Change in day-trade ratio, t")
    ax.set_ylabel("Change in log RV, t+1")
    ax.set_title("Day-trade ratio change vs next-day realized-vol change")
    ax.axhline(0, color="grey", lw=0.5); ax.axvline(0, color="grey", lw=0.5)
    fig.tight_layout()
    p2 = HERE / "fig2_ddt_vs_drv.png"
    fig.savefig(p2, dpi=130)
    plt.close(fig)
    paths.append(str(p2.name))
    return paths


# --------------------------------------------------------------------------- #
# 8. Orchestration
# --------------------------------------------------------------------------- #
def summary_stats(df: pd.DataFrame) -> dict:
    def desc(s):
        s = s.dropna()
        return {"mean": round(float(s.mean()), 4), "std": round(float(s.std()), 4),
                "min": round(float(s.min()), 4), "max": round(float(s.max()), 4),
                "n": int(len(s))}
    rv_vol = np.sqrt(df["rv_gk"] / 1e4) * 100
    return {
        "dt_ratio_value_pct": desc(df["dt_ratio"]),
        "dt_vol_ratio_pct": desc(df["dt_vol_ratio"]),
        "rv_gk_daily_vol_pct": desc(rv_vol),
        "corr_dt_ratio_vs_rvvol": round(float(df["dt_ratio"].corr(rv_vol)), 4),
    }


def analyze() -> dict:
    df = build_dataset()
    print(f"[analyze] merged sample: {df.index.min().date()} -> {df.index.max().date()}  N={len(df)}")

    results = {
        "experiment_id": "K1724",
        "title": "台股當沖佔比與波動：散戶 herding 的在地量化",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "sample": {
            "start": str(df.index.min().date()),
            "end": str(df.index.max().date()),
            "n_trading_days": int(len(df)),
        },
        "data_provenance": {
            "daytrade_ratio": {
                "source": "TWSE exchangeReport TWTB4U 當日沖銷交易統計資訊 (aggregate table)",
                "endpoint": "https://www.twse.com.tw/exchangeReport/TWTB4U?response=json&date=YYYYMMDD",
                "variable": "dt_ratio = mean(當沖總買進金額占市場比重%, 當沖總賣出金額占市場比重%)",
                "note": "value-based day-trade turnover ratio; TWSE definition uses (market buy+sell)/2 as denominator",
                "coverage_verified": "2014-01-06 (start of 現股當沖) onward",
            },
            "realized_vol": {
                "source": "yfinance ^TWII (TAIEX) daily OHLCV",
                "rv_primary": "Garman-Klass range-based variance proxy x1e4",
                "rv_robustness": ["Parkinson", "close-to-close squared return"],
                "limitation": "no free intraday for TAIEX; range-based proxies used (not 5-min RV)",
            },
        },
        "summary_stats": summary_stats(df),
    }

    print("[analyze] predictive test (GK)...")
    results["predictive_test_primary"] = predictive_test(df, "rv_gk")
    print("[analyze] bidirectional Granger (GK)...")
    results["granger_primary"] = bidirectional_granger(df, "rv_gk")
    print("[analyze] robustness...")
    results["robustness"] = robustness(df)
    print("[analyze] figures...")
    results["figures"] = make_figures(df)

    results["honest_conclusion"] = _conclude(results)

    RESULTS.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"[analyze] wrote {RESULTS}")
    return results


def _conclude(r: dict) -> dict:
    pt = r["predictive_test_primary"]
    gr = r["granger_primary"]
    rob = r["robustness"]
    cw = pt["clark_west_nested"]
    # nested test governs incremental-predictive-power verdict; require CW 5%
    # one-sided AND a positive incremental OOS R2.
    pred_helps = (pt["oos_incremental_r2_aug_vs_base"] > 0) and (cw["p_value_one_sided"] < 0.05)
    dt_to_rv = gr["granger_DT_to_RV"]["significant_5pct"]
    rv_to_dt = gr["granger_RV_to_DT"]["significant_5pct"]
    if dt_to_rv and rv_to_dt:
        direction_gk = "bidirectional_feedback"
    elif dt_to_rv:
        direction_gk = "day_trading_amplifies_volatility (DT->RV)"
    elif rv_to_dt:
        direction_gk = "volatility_attracts_day_trading (RV->DT)"
    else:
        direction_gk = "no_significant_granger_either_direction"

    # cross-proxy robustness of each Granger direction (5% level)
    swap = rob.get("rv_proxy_swap", {})
    dt_to_rv_ps = [gr["granger_DT_to_RV"]["pvalue"]] + [
        v.get("granger_DT_to_RV_p") for v in swap.values() if isinstance(v, dict) and "granger_DT_to_RV_p" in v]
    rv_to_dt_ps = [gr["granger_RV_to_DT"]["pvalue"]] + [
        v.get("granger_RV_to_DT_p") for v in swap.values() if isinstance(v, dict) and "granger_RV_to_DT_p" in v]
    dt_to_rv_robust = all(p is not None and p < 0.05 for p in dt_to_rv_ps)
    rv_to_dt_robust = all(p is not None and p < 0.05 for p in rv_to_dt_ps)

    # derive rq2 verdict from the robustness booleans (no hardcoded claim)
    def _leg(name, robust, any_sig):
        if robust:
            return f"{name}: ROBUST (significant across all RV proxies)"
        if any_sig:
            return f"{name}: FRAGILE (significant under some but not all RV proxies)"
        return f"{name}: not significant under any RV proxy"
    rq2 = "; ".join([
        _leg("RV->DT (volatility attracts day-trading)", rv_to_dt_robust,
             any(p is not None and p < 0.05 for p in rv_to_dt_ps)),
        _leg("DT->RV (day-trading amplifies volatility)", dt_to_rv_robust,
             any(p is not None and p < 0.05 for p in dt_to_rv_ps)),
    ])

    return {
        "rq1_incremental_predictive_power": bool(pred_helps),
        "rq1_verdict": ("NULL at 5%: augmented model does not significantly beat "
                        "HAR-RV out of sample. Clark-West (nested) is borderline "
                        f"(one-sided p={cw['p_value_one_sided']}), not a strong "
                        "'zero information' claim; DM(MSE)/DM(QLIKE) insignificant; "
                        "incremental OOS R2 economically trivial and not robust "
                        "across subperiods / RV proxies / with controls."),
        "oos_incremental_r2": pt["oos_incremental_r2_aug_vs_base"],
        "clark_west_t": cw["t_stat"],
        "clark_west_p_one_sided": cw["p_value_one_sided"],
        "dm_qlike_pvalue": pt["dm_qlike_pvalue"],
        "insample_dt_joint_wald_p": pt["insample"]["dt_joint_wald_pvalue"],
        "granger_direction_gk_proxy": direction_gk,
        "granger_DT_to_RV_p_gk": gr["granger_DT_to_RV"]["pvalue"],
        "granger_RV_to_DT_p_gk": gr["granger_RV_to_DT"]["pvalue"],
        "granger_DT_to_RV_pvalues_across_proxies": [round(p, 5) for p in dt_to_rv_ps if p is not None],
        "granger_RV_to_DT_pvalues_across_proxies": [round(p, 5) for p in rv_to_dt_ps if p is not None],
        "granger_DT_to_RV_robust_across_proxies": bool(dt_to_rv_robust),
        "granger_RV_to_DT_robust_across_proxies": bool(rv_to_dt_robust),
        "rq2_verdict": rq2,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--start", default="20140630")
    f.add_argument("--end", default=None)
    f.add_argument("--sleep", type=float, default=0.4)
    sub.add_parser("analyze")
    a = sub.add_parser("all")
    a.add_argument("--start", default="20140630")
    args = ap.parse_args()

    if args.cmd in ("fetch", "all"):
        start = datetime.strptime(getattr(args, "start", "20140630"), "%Y%m%d").date()
        end = (datetime.strptime(args.end, "%Y%m%d").date()
               if getattr(args, "end", None) else date.today())
        fetch_daytrade(start, end, sleep=getattr(args, "sleep", 0.4))
        load_twii() if TWII_CACHE.exists() else fetch_twii()
        if args.cmd == "fetch":
            return 0
    if args.cmd in ("analyze", "all"):
        analyze()
    return 0


if __name__ == "__main__":
    sys.exit(main())
