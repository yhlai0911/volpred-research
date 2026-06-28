"""K1560: Quadratic-variation estimator disagreement as forecast uncertainty.

Question
--------
Do disagreements among volatility measurement proxies at date t predict the
one-day-ahead forecast loss and volatility-target sizing error at t+1?

This is a short-window pilot because yfinance 5-minute bars are available only
for a recent rolling window. The script therefore reports a conservative
diagnostic result, not a publication-grade long-sample claim.

Timing discipline
-----------------
All measurement-disagreement signals are computed at origin date t and shifted
onto target date t+1 before QLIKE / sizing-error evaluation.

GARCH forecasts are indexed explicitly by target date. The script does not rely
on arch's origin-aligned forecast table for evaluation alignment.
"""

from __future__ import annotations

import json
import math
import random
import sys
import warnings
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from volpred.stats.mcs import model_confidence_set  # noqa: E402
from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise  # noqa: E402


EXPERIMENT_ID = "K1560"
SEED = 42
ASSETS = ["SPY", "QQQ", "IWM", "TLT", "GLD", "HYG"]
START_DATE = "2018-01-01"
REQUEST_END_DATE = "2026-06-29"
INTRADAY_PERIOD = "60d"
INTRADAY_INTERVAL = "5m"
ROLLING_N = 20
HAR_MIN_TRAIN = 252
HAR_MAX_TRAIN = 1500
GARCH_INITIAL_WINDOW = 756
GARCH_REFIT_EVERY = 10
MCS_BOOTSTRAPS = 1000
VOL_TARGET_ANNUAL = 0.10
FLOOR = 1e-12

OUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = OUT_DIR / "k1560_results.json"
PLOT_DISPERSION = OUT_DIR / "k1560_dispersion_timeseries.png"
PLOT_BINNED_LOSS = OUT_DIR / "k1560_dispersion_vs_loss.png"

random.seed(SEED)
np.random.seed(SEED)
warnings.filterwarnings("ignore", category=FutureWarning)


@dataclass
class GarchAudit:
    fit_attempts: int = 0
    fit_failures: int = 0
    convergence_warnings: int = 0
    ewma_fallbacks: int = 0


def flatten_yfinance_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return df


def clean_date_index(idx: pd.Index) -> pd.DatetimeIndex:
    out = pd.to_datetime(idx)
    if getattr(out, "tz", None) is not None:
        out = out.tz_convert(None)
    return out.normalize()


def load_daily(ticker: str) -> pd.DataFrame:
    df = yf.download(
        ticker,
        start=START_DATE,
        end=REQUEST_END_DATE,
        progress=False,
        auto_adjust=False,
        threads=False,
    )
    if df.empty:
        raise RuntimeError(f"{ticker}: empty daily yfinance response")
    df = flatten_yfinance_columns(df)
    needed = ["Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise RuntimeError(f"{ticker}: missing daily columns {missing}")
    df = df[needed].copy()
    df.index = clean_date_index(df.index)
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df = df[(df[["Open", "High", "Low", "Close"]] > 0).all(axis=1)]
    df = df[df["High"] >= df["Low"]]
    return df


def load_intraday_5m(ticker: str) -> pd.DataFrame:
    df = yf.download(
        ticker,
        period=INTRADAY_PERIOD,
        interval=INTRADAY_INTERVAL,
        progress=False,
        auto_adjust=False,
        prepost=False,
        threads=False,
    )
    if df.empty:
        raise RuntimeError(f"{ticker}: empty 5m yfinance response")
    df = flatten_yfinance_columns(df)
    if "Close" not in df.columns:
        raise RuntimeError(f"{ticker}: missing 5m Close column")
    df = df[["Close"]].copy()
    idx = pd.to_datetime(df.index)
    if getattr(idx, "tz", None) is None:
        idx = idx.tz_localize("UTC")
    df.index = idx.tz_convert("America/New_York")
    df = df[df["Close"] > 0].sort_index()
    return df


def compute_daily_estimators(df: pd.DataFrame, rolling_n: int = ROLLING_N) -> pd.DataFrame:
    out = df.copy()
    ln_h = np.log(out["High"].astype(float))
    ln_l = np.log(out["Low"].astype(float))
    ln_o = np.log(out["Open"].astype(float))
    ln_c = np.log(out["Close"].astype(float))
    ln_c_prev = ln_c.shift(1)

    hl = ln_h - ln_l
    co = ln_c - ln_o
    ho = ln_h - ln_o
    lo = ln_l - ln_o
    overnight = ln_o - ln_c_prev

    out["ret_cc"] = ln_c - ln_c_prev
    out["abs_ret_cc"] = out["ret_cc"].abs()
    out["rv_cc"] = out["ret_cc"] ** 2
    out["overnight_var"] = overnight ** 2
    out["dollar_volume"] = out["Close"] * out["Volume"].clip(lower=0)
    out["log_dollar_volume"] = np.log(out["dollar_volume"].clip(lower=1.0))

    out["sigma2_P"] = (hl ** 2) / (4.0 * np.log(2.0))
    out["sigma2_GK"] = 0.5 * (hl ** 2) - (2.0 * np.log(2.0) - 1.0) * (co ** 2)
    out["sigma2_RS"] = ho * (ho - co) + lo * (lo - co)
    k_const = 0.34 / (1.34 + (rolling_n + 1.0) / (rolling_n - 1.0))
    s_o = overnight.rolling(rolling_n).var(ddof=1)
    s_c = co.rolling(rolling_n).var(ddof=1)
    s_rs = out["sigma2_RS"].rolling(rolling_n).mean()
    out["sigma2_YZ"] = s_o + k_const * s_c + (1.0 - k_const) * s_rs
    out["sigma2_EnsOHLC"] = out[["sigma2_P", "sigma2_GK", "sigma2_RS", "sigma2_YZ"]].mean(axis=1)
    return out.replace([np.inf, -np.inf], np.nan)


def realized_kernel_lite(log_returns: np.ndarray, max_lag: int = 3) -> float:
    r = np.asarray(log_returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    if len(r) < max_lag + 2:
        return np.nan
    gamma0 = float(np.dot(r, r))
    rk = gamma0
    for lag in range(1, max_lag + 1):
        weight = 1.0 - lag / (max_lag + 1.0)
        gamma = float(np.dot(r[lag:], r[:-lag]))
        rk += 2.0 * weight * gamma
    return max(rk, FLOOR)


def compute_intraday_measures(intra: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for session_date, g in intra.groupby(intra.index.date):
        close = g["Close"].dropna().astype(float)
        if len(close) < 30:
            continue
        lr = np.diff(np.log(close.to_numpy()))
        if len(lr) < 10:
            continue
        rv5 = float(np.sum(lr ** 2))
        sparse_rvs = []
        for offset in range(2):
            c_sparse = close.iloc[offset::2]
            if len(c_sparse) >= 10:
                sparse_lr = np.diff(np.log(c_sparse.to_numpy()))
                sparse_rvs.append(float(np.sum(sparse_lr ** 2)))
        rv_sub = float(np.mean(sparse_rvs)) if sparse_rvs else np.nan
        rows.append(
            {
                "date": pd.Timestamp(session_date),
                "rv_5m": max(rv5, FLOOR),
                "rv_5m_subsampled_10m": max(rv_sub, FLOOR) if np.isfinite(rv_sub) else np.nan,
                "rv_kernel_lite": realized_kernel_lite(lr),
                "bars_5m": int(len(close)),
            }
        )
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).set_index("date").sort_index()
    return out.replace([np.inf, -np.inf], np.nan)


def add_measurement_dispersion(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    all_cols = [
        "rv_cc",
        "sigma2_P",
        "sigma2_GK",
        "sigma2_RS",
        "sigma2_YZ",
        "rv_5m",
        "rv_5m_subsampled_10m",
        "rv_kernel_lite",
        "rv_total_5m",
    ]
    daily_cols = ["rv_cc", "sigma2_P", "sigma2_GK", "sigma2_RS", "sigma2_YZ"]
    intra_cols = ["rv_5m", "rv_5m_subsampled_10m", "rv_kernel_lite"]

    def row_disp(row: pd.Series, cols: list[str]) -> pd.Series:
        vals = row.reindex(cols).astype(float).to_numpy()
        vals = vals[np.isfinite(vals) & (vals > 0)]
        if len(vals) < max(3, min(5, len(cols))):
            return pd.Series({"log_std": np.nan, "log_range": np.nan, "log_iqr": np.nan, "n": len(vals)})
        logs = np.log(np.clip(vals, FLOOR, None))
        return pd.Series(
            {
                "log_std": float(np.std(logs, ddof=1)),
                "log_range": float(np.max(logs) - np.min(logs)),
                "log_iqr": float(np.percentile(logs, 75) - np.percentile(logs, 25)),
                "n": int(len(vals)),
            }
        )

    all_disp = out.apply(lambda r: row_disp(r, all_cols), axis=1)
    daily_disp = out.apply(lambda r: row_disp(r, daily_cols), axis=1)
    intra_disp = out.apply(lambda r: row_disp(r, intra_cols), axis=1)
    out["dispersion_log_std"] = all_disp["log_std"]
    out["dispersion_log_range"] = all_disp["log_range"]
    out["dispersion_log_iqr"] = all_disp["log_iqr"]
    out["dispersion_proxy_count"] = all_disp["n"]
    out["daily_dispersion_log_std"] = daily_disp["log_std"]
    out["intraday_dispersion_log_std"] = intra_disp["log_std"]
    return out


def ewma_forecast(returns: pd.Series, target_dates: pd.Index, lam: float = 0.94) -> pd.Series:
    r2 = returns.astype(float).pow(2).clip(lower=FLOOR)
    h = r2.ewm(alpha=1.0 - lam, adjust=False).mean()
    forecasts = {}
    idx = list(r2.index)
    pos_map = {d: i for i, d in enumerate(idx)}
    for target in target_dates:
        if target not in pos_map or pos_map[target] == 0:
            continue
        origin = idx[pos_map[target] - 1]
        forecasts[target] = float(max(h.loc[origin], FLOOR))
    return pd.Series(forecasts, name="fc_EWMA")


def har_forecast(returns: pd.Series, target_dates: pd.Index) -> pd.Series:
    r2 = returns.astype(float).pow(2).clip(lower=FLOOR)
    features = pd.DataFrame(index=r2.index)
    features["log_rv_d"] = np.log(r2)
    features["log_rv_w"] = np.log(r2.rolling(5).mean().clip(lower=FLOOR))
    features["log_rv_m"] = np.log(r2.rolling(22).mean().clip(lower=FLOOR))
    features["y_next"] = np.log(r2.shift(-1).clip(lower=FLOOR))
    idx = list(features.index)
    pos_map = {d: i for i, d in enumerate(idx)}

    forecasts: dict[pd.Timestamp, float] = {}
    for target in target_dates:
        if target not in pos_map:
            continue
        target_pos = pos_map[target]
        origin_pos = target_pos - 1
        if origin_pos < HAR_MIN_TRAIN:
            continue
        train = features.iloc[:origin_pos].dropna()
        if len(train) < HAR_MIN_TRAIN:
            continue
        train = train.iloc[-HAR_MAX_TRAIN:]
        x_origin = features.iloc[origin_pos][["log_rv_d", "log_rv_w", "log_rv_m"]]
        if not np.isfinite(x_origin.to_numpy(dtype=float)).all():
            continue
        x = np.column_stack([np.ones(len(train)), train[["log_rv_d", "log_rv_w", "log_rv_m"]].to_numpy()])
        y = train["y_next"].to_numpy()
        beta, *_ = np.linalg.lstsq(x, y, rcond=None)
        x0 = np.array([1.0, *x_origin.to_numpy(dtype=float)])
        pred = float(np.exp(np.clip(np.dot(x0, beta), -40, 5)))
        forecasts[target] = max(pred, FLOOR)
    return pd.Series(forecasts, name="fc_HAR")


def garch_forecast(returns: pd.Series, target_dates: pd.Index) -> tuple[pd.Series, GarchAudit]:
    try:
        from arch import arch_model
    except ImportError as exc:
        raise RuntimeError("arch package required for K1560 GARCH baseline") from exc

    r = returns.dropna().astype(float)
    r_pct = r * 100.0
    idx = list(r_pct.index)
    pos_map = {d: i for i, d in enumerate(idx)}
    audit = GarchAudit()
    forecasts: dict[pd.Timestamp, float] = {}
    last_params = None
    last_fit_origin_pos = -10**9

    ewma = ewma_forecast(r, target_dates)

    for target in target_dates:
        if target not in pos_map:
            continue
        target_pos = pos_map[target]
        origin_pos = target_pos - 1
        if origin_pos < GARCH_INITIAL_WINDOW:
            continue
        need_refit = last_params is None or (origin_pos - last_fit_origin_pos) >= GARCH_REFIT_EVERY
        if need_refit:
            audit.fit_attempts += 1
            y = r_pct.iloc[: origin_pos + 1].to_numpy()
            am = arch_model(y, mean="Zero", vol="GARCH", p=1, q=1, dist="Normal", rescale=False)
            try:
                res = am.fit(disp="off", show_warning=False)
                flag = int(getattr(res, "convergence_flag", 0) or 0)
                if flag != 0:
                    audit.convergence_warnings += 1
                last_params = res.params
                last_fit_origin_pos = origin_pos
            except Exception as exc:
                audit.fit_failures += 1
                print(f"[K1560][GARCH] fit failed at {target.date()}: {exc}", file=sys.stderr)
                if last_params is None:
                    if target in ewma.index:
                        forecasts[target] = float(ewma.loc[target])
                        audit.ewma_fallbacks += 1
                    continue

        omega = float(last_params.get("omega", np.nan))
        alpha = float(last_params.get("alpha[1]", np.nan))
        beta = float(last_params.get("beta[1]", np.nan))
        if not np.isfinite([omega, alpha, beta]).all() or omega < 0 or alpha < 0 or beta < 0:
            if target in ewma.index:
                forecasts[target] = float(ewma.loc[target])
                audit.ewma_fallbacks += 1
            continue

        eps2 = r_pct.iloc[: origin_pos + 1].to_numpy() ** 2
        if (1.0 - alpha - beta) > 1e-6:
            h = max(omega / (1.0 - alpha - beta), FLOOR * 10000.0)
        else:
            h = max(float(np.var(r_pct.iloc[: origin_pos + 1].to_numpy())), FLOOR * 10000.0)
        for e2 in eps2:
            h = omega + alpha * e2 + beta * h
        forecasts[target] = max(float(h) / 10000.0, FLOOR)

    return pd.Series(forecasts, name="fc_GARCH"), audit


def prepare_asset(ticker: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    daily_raw = load_daily(ticker)
    daily = compute_daily_estimators(daily_raw)
    intra = compute_intraday_measures(load_intraday_5m(ticker))
    if intra.empty:
        raise RuntimeError(f"{ticker}: no valid intraday sessions")

    combined = daily.join(intra, how="left")
    combined["rv_total_5m"] = combined["overnight_var"].fillna(0.0) + combined["rv_5m"]
    combined["rv_total_kernel"] = combined["overnight_var"].fillna(0.0) + combined["rv_kernel_lite"]
    combined = add_measurement_dispersion(combined)

    returns = combined["ret_cc"].dropna()
    target_dates = combined.index[combined["rv_total_5m"].notna()]
    target_dates = pd.Index([d for d in target_dates if d in returns.index])

    fc_har = har_forecast(returns, target_dates)
    fc_ewma = ewma_forecast(returns, target_dates)
    fc_garch, garch_audit = garch_forecast(returns, target_dates)

    shifted = pd.DataFrame(index=combined.index)
    shifted["fc_Parkinson"] = combined["sigma2_P"].clip(lower=FLOOR).shift(1)
    shifted["fc_GarmanKlass"] = combined["sigma2_GK"].clip(lower=FLOOR).shift(1)
    shifted["fc_RogersSatchell"] = combined["sigma2_RS"].clip(lower=FLOOR).shift(1)
    shifted["fc_YangZhang"] = combined["sigma2_YZ"].clip(lower=FLOOR).shift(1)
    shifted["fc_EqualOHLC"] = combined["sigma2_EnsOHLC"].clip(lower=FLOOR).shift(1)
    shifted["fc_RV5mPersist"] = combined["rv_total_5m"].clip(lower=FLOOR).shift(1)
    shifted["signal_dispersion"] = combined["dispersion_log_std"].shift(1)
    shifted["signal_dispersion_range"] = combined["dispersion_log_range"].shift(1)
    shifted["signal_daily_dispersion"] = combined["daily_dispersion_log_std"].shift(1)
    shifted["signal_intraday_dispersion"] = combined["intraday_dispersion_log_std"].shift(1)
    shifted["origin_rv_total"] = combined["rv_total_5m"].shift(1)
    shifted["origin_abs_return"] = combined["abs_ret_cc"].shift(1)
    shifted["origin_log_dollar_volume"] = combined["log_dollar_volume"].shift(1)
    shifted["origin_bars_5m"] = combined["bars_5m"].shift(1)
    shifted["origin_date"] = pd.Series(combined.index, index=combined.index).shift(1)

    table = pd.DataFrame(index=target_dates)
    table["asset"] = ticker
    table["actual_total_rv"] = combined.loc[target_dates, "rv_total_5m"].clip(lower=FLOOR)
    table["actual_kernel_total_rv"] = combined.loc[target_dates, "rv_total_kernel"].clip(lower=FLOOR)
    table = table.join(shifted, how="left")
    table = table.join(fc_har, how="left")
    table = table.join(fc_ewma, how="left")
    table = table.join(fc_garch, how="left")
    table = table.replace([np.inf, -np.inf], np.nan)

    forecast_cols = [c for c in table.columns if c.startswith("fc_")]
    for col in forecast_cols:
        table[col] = table[col].clip(lower=FLOOR)

    table = table.dropna(
        subset=[
            "actual_total_rv",
            "signal_dispersion",
            "signal_intraday_dispersion",
            "origin_bars_5m",
            "fc_HAR",
            "fc_GARCH",
        ]
    )

    summary = {
        "daily_rows": int(len(daily)),
        "daily_start": str(daily.index.min().date()),
        "daily_end": str(daily.index.max().date()),
        "intraday_sessions": int(len(intra)),
        "intraday_start": str(intra.index.min().date()),
        "intraday_end": str(intra.index.max().date()),
        "median_5m_bars": float(intra["bars_5m"].median()),
        "garch_audit": garch_audit.__dict__,
        "eval_rows": int(len(table)),
    }

    return table, summary


def add_losses_and_targets(table: pd.DataFrame) -> pd.DataFrame:
    out = table.copy()
    forecast_cols = [c for c in out.columns if c.startswith("fc_")]
    actual = out["actual_total_rv"].to_numpy(dtype=float)
    for col in forecast_cols:
        out[f"loss_{col[3:]}"] = qlike_pointwise(actual, out[col].to_numpy(dtype=float))
        out[f"abs_log_ratio_{col[3:]}"] = np.abs(np.log(np.clip(actual, FLOOR, None) / out[col].clip(lower=FLOOR)))

    daily_target_var = (VOL_TARGET_ANNUAL / math.sqrt(252.0)) ** 2
    for model in ["HAR", "GARCH", "EWMA"]:
        fc_col = f"fc_{model}"
        weight = np.sqrt(daily_target_var / out[fc_col].clip(lower=FLOOR)).clip(upper=3.0)
        realized_scaled_var = weight.pow(2) * out["actual_total_rv"]
        out[f"vt_excess_risk_{model}"] = (realized_scaled_var / daily_target_var - 1.0).clip(lower=0.0)
        out[f"vt_abs_log_error_{model}"] = np.abs(np.log((realized_scaled_var / daily_target_var).clip(lower=FLOOR)))
    return out


def add_future_near_best_size(panel: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    out = panel.copy()
    loss_cols = [c for c in out.columns if c.startswith("loss_")]
    out["future_near_best_size_5d"] = np.nan
    for asset, g in out.groupby("asset", sort=False):
        g = g.sort_index()
        losses = g[loss_cols]
        values = []
        for i in range(len(g)):
            chunk = losses.iloc[i : i + window]
            if len(chunk) < window:
                values.append(np.nan)
                continue
            means = chunk.mean(axis=0, skipna=True)
            if means.notna().sum() < 3:
                values.append(np.nan)
                continue
            best = float(means.min())
            tol = max(0.10 * abs(best), 0.05)
            values.append(int((means <= best + tol).sum()))
        asset_mask = out["asset"].eq(asset)
        out.loc[asset_mask, "future_near_best_size_5d"] = values
    return out


def holm_adjust(p_values: list[float]) -> list[float]:
    m = len(p_values)
    order = np.argsort(np.asarray(p_values, dtype=float))
    adjusted = np.ones(m)
    running = 0.0
    for rank, idx in enumerate(order):
        adj = (m - rank) * float(p_values[idx])
        running = max(running, adj)
        adjusted[idx] = min(running, 1.0)
    return adjusted.tolist()


def panel_regressions(panel: pd.DataFrame) -> list[dict[str, Any]]:
    import statsmodels.formula.api as smf

    targets = [
        ("loss_HAR", "HAR next-day QLIKE"),
        ("loss_GARCH", "GARCH next-day QLIKE"),
        ("loss_EWMA", "EWMA next-day QLIKE"),
        ("vt_excess_risk_HAR", "HAR vol-target excess realized variance"),
        ("vt_excess_risk_GARCH", "GARCH vol-target excess realized variance"),
        ("vt_abs_log_error_GARCH", "GARCH vol-target absolute log sizing error"),
        ("future_near_best_size_5d", "future 5d near-MCS proxy size"),
    ]
    rows: list[dict[str, Any]] = []
    for target, label in targets:
        cols = [
            target,
            "signal_dispersion",
            "origin_rv_total",
            "origin_abs_return",
            "origin_log_dollar_volume",
            "asset",
        ]
        df = panel[cols].dropna().copy()
        if len(df) < 60 or df["asset"].nunique() < 2:
            continue
        df["log_origin_rv_total"] = np.log(df["origin_rv_total"].clip(lower=FLOOR))
        formula = (
            f"{target} ~ signal_dispersion + log_origin_rv_total + "
            "origin_abs_return + origin_log_dollar_volume + C(asset)"
        )
        fit = smf.ols(formula, data=df).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
        rows.append(
            {
                "target": target,
                "label": label,
                "n": int(len(df)),
                "assets": int(df["asset"].nunique()),
                "coef_signal_dispersion": float(fit.params.get("signal_dispersion", np.nan)),
                "t_signal_dispersion": float(fit.tvalues.get("signal_dispersion", np.nan)),
                "p_signal_dispersion": float(fit.pvalues.get("signal_dispersion", np.nan)),
                "r2": float(getattr(fit, "rsquared", np.nan)),
                "covariance": "HAC(maxlags=5)",
                "formula": formula,
            }
        )
    if rows:
        adj = holm_adjust([r["p_signal_dispersion"] for r in rows])
        for r, p_adj in zip(rows, adj):
            r["holm_p_signal_dispersion"] = float(p_adj)
            r["holm_significant_5pct"] = bool(p_adj < 0.05)
    return rows


def per_asset_spearman(panel: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    targets = ["loss_HAR", "loss_GARCH", "vt_excess_risk_GARCH", "future_near_best_size_5d"]
    for asset, g in panel.groupby("asset"):
        for target in targets:
            df = g[["signal_dispersion", target]].dropna()
            if len(df) < 15:
                continue
            rho, p = stats.spearmanr(df["signal_dispersion"], df[target])
            rows.append(
                {
                    "asset": asset,
                    "target": target,
                    "n": int(len(df)),
                    "rho": float(rho),
                    "p": float(p),
                }
            )
    return rows


def model_metrics(panel: pd.DataFrame) -> dict[str, Any]:
    loss_cols = [c for c in panel.columns if c.startswith("loss_")]
    models = [c.replace("loss_", "") for c in loss_cols]
    by_asset: dict[str, Any] = {}
    for asset, g in panel.groupby("asset"):
        asset_res = {"n": int(len(g)), "qlike": {}, "best_model": None}
        for model in models:
            fc = g[f"fc_{model}"].to_numpy(dtype=float)
            actual = g["actual_total_rv"].to_numpy(dtype=float)
            asset_res["qlike"][model] = qlike(actual, fc)
        finite = {k: v for k, v in asset_res["qlike"].items() if np.isfinite(v)}
        asset_res["best_model"] = min(finite, key=finite.get) if finite else None
        by_asset[asset] = asset_res
    return {"models": models, "by_asset": by_asset}


def dm_and_mcs(panel: pd.DataFrame) -> dict[str, Any]:
    models = [c.replace("loss_", "") for c in panel.columns if c.startswith("loss_")]
    dm_rows: list[dict[str, Any]] = []
    mcs_rows: dict[str, Any] = {}
    for asset, g in panel.groupby("asset"):
        loss_map = {m: g[f"loss_{m}"].dropna().to_numpy(dtype=float) for m in models}
        usable = {m: v for m, v in loss_map.items() if len(v) >= 20}
        for i, m1 in enumerate(models):
            for m2 in models[i + 1 :]:
                l1 = g[f"loss_{m1}"].to_numpy(dtype=float)
                l2 = g[f"loss_{m2}"].to_numpy(dtype=float)
                mask = np.isfinite(l1) & np.isfinite(l2)
                if mask.sum() < 20:
                    continue
                t_stat, p_val = dm_test(l1[mask], l2[mask], h=1)
                dm_rows.append(
                    {
                        "asset": asset,
                        "model_1": m1,
                        "model_2": m2,
                        "n": int(mask.sum()),
                        "dm_t": float(t_stat),
                        "p": float(p_val),
                        "harvey_abs_t_gt_3": bool(abs(t_stat) > 3.0),
                        "better_model": m1 if t_stat < 0 else m2,
                    }
                )
        if len(usable) >= 3:
            min_len = min(len(v) for v in usable.values())
            aligned = {m: v[-min_len:] for m, v in usable.items()}
            try:
                mcs = model_confidence_set(
                    aligned,
                    alpha=0.10,
                    n_boot=MCS_BOOTSTRAPS,
                    seed=SEED,
                )
                members = mcs.get("mcs_models", [])
                mcs_rows[asset] = {
                    "n": int(min_len),
                    "members": members,
                    "size": int(len(members)),
                    "eliminated": mcs.get("eliminated", []),
                    "p_values": mcs.get("p_values", {}),
                    "method": "HLN2011_stationary_bootstrap_TR",
                    "bootstrap_B": MCS_BOOTSTRAPS,
                    "seed": SEED,
                }
            except Exception as exc:
                mcs_rows[asset] = {"error": str(exc)}

    if dm_rows:
        adj = holm_adjust([r["p"] for r in dm_rows])
        for r, p_adj in zip(dm_rows, adj):
            r["holm_p"] = float(p_adj)
            r["holm_significant_5pct"] = bool(p_adj < 0.05)

    return {
        "dm_tests": dm_rows,
        "dm_summary": {
            "pairs": int(len(dm_rows)),
            "harvey_abs_t_gt_3": int(sum(r["harvey_abs_t_gt_3"] for r in dm_rows)),
            "holm_significant_5pct": int(sum(r.get("holm_significant_5pct", False) for r in dm_rows)),
        },
        "mcs_by_asset": mcs_rows,
    }


def plot_outputs(panel: pd.DataFrame) -> None:
    fig, axes = plt.subplots(len(ASSETS), 1, figsize=(12, 10), sharex=True)
    for ax, asset in zip(axes, ASSETS):
        g = panel[panel["asset"] == asset].sort_index()
        ax.plot(g.index, g["signal_dispersion"], lw=1.4, color="#1f77b4")
        ax.set_ylabel(asset, rotation=0, labelpad=28, fontsize=9)
        ax.grid(alpha=0.25)
    axes[0].set_title("K1560 origin-date estimator disagreement shifted to target date")
    axes[-1].set_xlabel("Target date")
    fig.tight_layout()
    fig.savefig(PLOT_DISPERSION, dpi=160)
    plt.close(fig)

    p = panel.dropna(subset=["signal_dispersion", "loss_HAR", "loss_GARCH", "vt_excess_risk_GARCH"]).copy()
    p["dispersion_quartile"] = p.groupby("asset")["signal_dispersion"].transform(
        lambda s: pd.qcut(s.rank(method="first"), 4, labels=["Q1", "Q2", "Q3", "Q4"])
    )
    binned = p.groupby("dispersion_quartile", observed=False)[
        ["loss_HAR", "loss_GARCH", "vt_excess_risk_GARCH"]
    ].mean()
    fig, ax1 = plt.subplots(figsize=(9, 5))
    x = np.arange(len(binned.index))
    width = 0.27
    ax1.bar(x - width, binned["loss_HAR"], width, label="HAR QLIKE", color="#4c78a8")
    ax1.bar(x, binned["loss_GARCH"], width, label="GARCH QLIKE", color="#f58518")
    ax1.set_ylabel("Mean next-day QLIKE")
    ax1.set_xticks(x)
    ax1.set_xticklabels(binned.index.astype(str))
    ax2 = ax1.twinx()
    ax2.bar(x + width, binned["vt_excess_risk_GARCH"], width, label="GARCH VT excess risk", color="#54a24b")
    ax2.set_ylabel("Mean GARCH vol-target excess risk")
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(handles1 + handles2, labels1 + labels2, loc="upper left")
    ax1.set_title("K1560 losses by within-asset estimator-disagreement quartile")
    ax1.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(PLOT_BINNED_LOSS, dpi=160)
    plt.close(fig)


def build_lookahead_audit(panel: pd.DataFrame) -> dict[str, Any]:
    examples = []
    pass_count = 0
    checked = 0
    for asset, g in panel.groupby("asset"):
        g = g.sort_index()
        for target in g.index[:3]:
            origin_raw = g.loc[target, "origin_date"]
            if pd.isna(origin_raw):
                continue
            origin = pd.Timestamp(origin_raw)
            checked += 1
            ok = bool(
                pd.notna(g.loc[target, "signal_dispersion"])
                and pd.notna(g.loc[target, "signal_intraday_dispersion"])
                and origin < pd.Timestamp(target)
            )
            pass_count += int(ok)
            examples.append(
                {
                    "asset": asset,
                    "origin_date": str(origin.date()),
                    "target_date": str(pd.Timestamp(target).date()),
                    "strict_origin_before_target": bool(origin < pd.Timestamp(target)),
                    "origin_has_intraday_dispersion": bool(pd.notna(g.loc[target, "signal_intraday_dispersion"])),
                    "signal_dispersion_shifted_value": float(g.loc[target, "signal_dispersion"]),
                }
            )
            break
    return {
        "rule": "signals and OHLC/RV direct forecasts are shifted by one trading row before target-date evaluation",
        "checked_examples": checked,
        "passed_examples": pass_count,
        "all_passed": bool(checked > 0 and pass_count == checked),
        "examples": examples,
        "garch_alignment": "manual forecast loop indexes each variance forecast by target date target_pos=origin_pos+1",
        "qlike_direction": "volpred.stats.model_evaluation.qlike_pointwise(actual, predicted)",
    }


def decide_verdict(regressions: list[dict[str, Any]], spearman_rows: list[dict[str, Any]], panel: pd.DataFrame) -> str:
    primary_targets = {
        "loss_HAR",
        "loss_GARCH",
        "vt_excess_risk_GARCH",
        "vt_abs_log_error_GARCH",
    }
    primary_hits = [
        r
        for r in regressions
        if r["target"] in primary_targets
        and r["coef_signal_dispersion"] > 0
        and r.get("holm_p_signal_dispersion", 1.0) < 0.05
    ]
    sign_rows = [r for r in spearman_rows if r["target"] in {"loss_HAR", "loss_GARCH"} and r["rho"] > 0]
    sign_assets = len({r["asset"] for r in sign_rows})
    min_asset_rows = int(panel.groupby("asset").size().min()) if not panel.empty else 0
    if min_asset_rows < 40:
        return "UNDERPOWERED_NULL_SHORT_INTRADAY_WINDOW"
    if len(primary_hits) >= 2 and sign_assets >= 4:
        return "CONDITIONAL_PASS_SHORT_WINDOW"
    if len(primary_hits) >= 1:
        return "WEAK_CONDITIONAL_SHORT_WINDOW"
    return "NULL_SHORT_WINDOW"


def json_sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): json_sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_sanitize(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (pd.Timestamp, datetime, date)):
        return obj.isoformat()
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def main() -> None:
    print(f"[{EXPERIMENT_ID}] start {datetime.now().isoformat(timespec='seconds')}")
    tables: list[pd.DataFrame] = []
    data_summary: dict[str, Any] = {}
    errors: dict[str, str] = {}

    for ticker in ASSETS:
        print(f"[{EXPERIMENT_ID}] loading {ticker}")
        try:
            table, summary = prepare_asset(ticker)
            table = add_losses_and_targets(table)
            tables.append(table)
            data_summary[ticker] = summary
        except Exception as exc:
            errors[ticker] = str(exc)
            print(f"[{EXPERIMENT_ID}] ERROR {ticker}: {exc}", file=sys.stderr)

    if not tables:
        raise RuntimeError("No assets produced evaluation rows")

    panel = pd.concat(tables).sort_index()
    panel = add_future_near_best_size(panel)

    regressions = panel_regressions(panel)
    spearman_rows = per_asset_spearman(panel)
    metrics = model_metrics(panel)
    dm_mcs = dm_and_mcs(panel)
    plot_outputs(panel)
    lookahead_audit = build_lookahead_audit(panel)
    verdict = decide_verdict(regressions, spearman_rows, panel)

    strongest = sorted(
        regressions,
        key=lambda r: (r.get("holm_p_signal_dispersion", 1.0), -abs(r.get("t_signal_dispersion", 0.0))),
    )
    positive_assets = {
        target: sorted({r["asset"] for r in spearman_rows if r["target"] == target and r["rho"] > 0})
        for target in ["loss_HAR", "loss_GARCH", "vt_excess_risk_GARCH", "future_near_best_size_5d"]
    }

    results = {
        "experiment_id": EXPERIMENT_ID,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "verdict": verdict,
        "random_seed": SEED,
        "config": {
            "assets": ASSETS,
            "daily_source": "yfinance daily OHLCV",
            "intraday_source": f"yfinance {INTRADAY_INTERVAL} bars, period={INTRADAY_PERIOD}, prepost=False",
            "daily_start": START_DATE,
            "request_end_date": REQUEST_END_DATE,
            "har_min_train": HAR_MIN_TRAIN,
            "garch_initial_window": GARCH_INITIAL_WINDOW,
            "garch_refit_every": GARCH_REFIT_EVERY,
            "mcs_bootstraps": MCS_BOOTSTRAPS,
        },
        "data_summary": data_summary,
        "errors": errors,
        "panel_rows": int(len(panel)),
        "panel_rows_by_asset": {k: int(v) for k, v in panel.groupby("asset").size().items()},
        "lookahead_audit": lookahead_audit,
        "regression_tests": regressions,
        "per_asset_spearman": spearman_rows,
        "positive_spearman_assets": positive_assets,
        "model_metrics": metrics,
        "dm_and_mcs": dm_mcs,
        "strongest_regression_tests": strongest[:5],
        "plots": [str(PLOT_DISPERSION.relative_to(ROOT)), str(PLOT_BINNED_LOSS.relative_to(ROOT))],
        "literature_preamble": [
            "Andersen, Bollerslev, Diebold, and Labys (2003), Econometrica: realized volatility measurement and forecasting.",
            "Hansen and Lunde (2006), Journal of Business and Economic Statistics: realized variance and market microstructure noise.",
            "Barndorff-Nielsen, Hansen, Lunde, and Shephard (2009), Econometrics Journal: realized kernels in practice.",
            "Patton (2011), Journal of Econometrics: robust volatility forecast comparison with imperfect proxies.",
            "Hansen, Lunde, and Nason (2011), Econometrica: Model Confidence Set.",
        ],
        "caveats": [
            "yfinance 5-minute bars provide only a short recent rolling window; this is a pilot diagnostic.",
            "realized-kernel-lite is a Bartlett autocovariance proxy, not a full noise-optimized realized kernel implementation.",
            "near-MCS size is a five-day near-best loss proxy; formal HLN MCS is reported only as full-sample per-asset diagnostics.",
            "daily OHLC estimators and intraday RV target different pieces of the trading day; rv_total_5m adds overnight variance to reduce target mismatch.",
        ],
    }

    RESULTS_PATH.write_text(json.dumps(json_sanitize(results), indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(json_sanitize({"verdict": verdict, "rows": len(panel), "errors": errors}), ensure_ascii=False))


if __name__ == "__main__":
    main()
