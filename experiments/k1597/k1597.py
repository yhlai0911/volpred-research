"""K1597: non-Gaussian rough volatility diagnostic and OOS race.

Backlog source:
    Non-Gaussian Rough Vol (alpha-stable increments) -- arXiv:2507.15437.

Scope:
    This is a bounded falsification exercise, not a full LFSM estimator.  It
    checks whether local TAIFEX 5-minute realized volatility increments look
    heavy-tailed enough to motivate stable increments, and whether three
    transparent non-Gaussian/rough-volatility features beat HAR/HARQ under
    one-step-ahead QLIKE with DM/HAC inference.

Lookahead discipline:
    Every forecast for date t uses realized-volatility information through
    date t-1.  Training rows target day j and use features dated <= j-1.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESULTS_PATH = HERE / "k1597_results.json"
FORECASTS_PATH = HERE / "k1597_oos_forecasts.csv"
FIG_PATH = HERE / "k1597_tail_and_oos.png"

TAIFEX_5MIN_CACHE = ROOT / "experiments/k1100h/data/_taifex_5min_2017-2021.parquet"

EPS = 1e-12
MAX_LAG = 66
REFIT_FREQ = 21
OOS_START = "2020-01-01"
MIN_TRAIN = 500

MODELS = ["HAR", "HARQ", "StableTailHAR", "CodiffAR", "LFSM_lite"]
NON_GAUSSIAN_MODELS = ["StableTailHAR", "CodiffAR", "LFSM_lite"]

REFERENCES = [
    {
        "key": "garcin_sawaya_valade_2026_lfsm",
        "citation": "Garcin, Sawaya, and Valade (2026), arXiv:2507.15437v3",
        "role": "linear fractional stable motion prediction via codifference; motivates non-Gaussian rough-volatility increments",
        "url": "https://arxiv.org/abs/2507.15437",
    },
    {
        "key": "gatheral_jaisson_rosenbaum_2018",
        "citation": "Gatheral, Jaisson, and Rosenbaum (2018), Quantitative Finance 18(6), 933-949",
        "role": "canonical rough-volatility evidence",
        "url": "https://doi.org/10.1080/14697688.2017.1393551",
    },
    {
        "key": "cont_das_2024",
        "citation": "Cont and Das (2024), Sankhya B 86, 1-28",
        "role": "cautions that roughness estimates can be artefacts of measurement, microstructure, and non-stationarity",
        "url": "https://ideas.repec.org/a/spr/sankhb/v86y2024i1d10.1007_s13571-024-00322-2.html",
    },
    {
        "key": "corsi_2009",
        "citation": "Corsi (2009), Journal of Financial Econometrics 7(2), 174-196",
        "role": "HAR realized-volatility benchmark",
        "url": "https://academic.oup.com/jfec/article-abstract/7/2/174/787440",
    },
    {
        "key": "patton_2011",
        "citation": "Patton (2011), Journal of Econometrics 160(1), 246-256",
        "role": "QLIKE volatility forecast comparison with imperfect proxies",
        "url": "https://doi.org/10.1016/j.jeconom.2010.03.034",
    },
]


@dataclass
class OLSFit:
    beta: np.ndarray
    x_mean: np.ndarray
    x_std: np.ndarray
    resid_var: float
    model_type: str
    h: float
    alpha: float


def _finite_json(value):
    """Convert numpy scalars and non-finite values for strict JSON output."""
    if isinstance(value, dict):
        return {str(k): _finite_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite_json(v) for v in value]
    if isinstance(value, tuple):
        return [_finite_json(v) for v in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        x = float(value)
        return x if math.isfinite(x) else None
    return value


def _clean_positive(s: pd.Series) -> pd.Series:
    out = pd.to_numeric(s, errors="coerce")
    out = out.replace([np.inf, -np.inf], np.nan).dropna()
    return out[out > 0]


def realized_quarticity(rets: np.ndarray) -> float:
    rets = np.asarray(rets, dtype=float)
    rets = rets[np.isfinite(rets)]
    if len(rets) < 2:
        return float("nan")
    return float((len(rets) / 3.0) * np.sum(rets**4))


def load_taifex_day_rv() -> pd.DataFrame:
    """Build day-session daily RV/RQ from the K1100h 5-minute bar cache."""
    bars = pd.read_parquet(TAIFEX_5MIN_CACHE)
    bars = bars[bars["session"] == "day"].copy()
    bars["session_date"] = pd.to_datetime(bars["session_date"])
    bars["bar_start"] = pd.to_datetime(bars["bar_start"])
    bars = bars.sort_values(["session_date", "bar_start"])

    rows = []
    for date, g in bars.groupby("session_date", sort=True):
        closes = _clean_positive(g["close"])
        if len(closes) < 20:
            continue
        rets = np.diff(np.log(closes.values))
        if len(rets) < 20:
            continue
        rows.append(
            {
                "date": pd.Timestamp(date).normalize(),
                "rv": float(np.sum(rets**2)),
                "rq": realized_quarticity(rets),
                "n_intraday_returns": int(len(rets)),
            }
        )

    df = pd.DataFrame(rows).set_index("date").sort_index()
    df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=["rv", "rq"])
    return df[(df["rv"] > 0) & (df["rq"] > 0)].copy()


def estimate_hurst_variogram(log_rv: pd.Series, max_lag: int = 20) -> dict:
    x = log_rv.dropna().values.astype(float)
    lags: List[int] = []
    moments: List[float] = []
    for lag in range(1, max_lag + 1):
        if len(x) <= lag + 10:
            continue
        diff = x[lag:] - x[:-lag]
        moment = float(np.mean(diff**2))
        if math.isfinite(moment) and moment > 0:
            lags.append(lag)
            moments.append(moment)
    if len(lags) < 6:
        return {"H": float("nan"), "method": "variogram", "n_points": len(lags)}
    reg = stats.linregress(np.log(lags), np.log(moments))
    return {
        "H": float(reg.slope / 2.0),
        "method": "variogram",
        "r2": float(reg.rvalue**2),
        "se_H": float(reg.stderr / 2.0) if reg.stderr is not None else None,
        "n_points": len(lags),
    }


def estimate_hurst_frequency_ratio(log_rv: pd.Series) -> dict:
    x = log_rv.dropna().values.astype(float)
    if len(x) < 30:
        return {"H": float("nan"), "method": "second_difference_frequency_ratio"}
    d1 = x[2:] - 2.0 * x[1:-1] + x[:-2]
    d2 = x[4:] - 2.0 * x[2:-2] + x[:-4]
    m1 = float(np.mean(d1**2))
    m2 = float(np.mean(d2**2))
    if m1 <= 0 or m2 <= 0 or not math.isfinite(m1) or not math.isfinite(m2):
        return {"H": float("nan"), "method": "second_difference_frequency_ratio"}
    return {
        "H": float(0.5 * math.log(m2 / m1, 2)),
        "method": "second_difference_frequency_ratio",
        "n_points": int(min(len(d1), len(d2))),
    }


def hill_tail_index(x: np.ndarray, tail_fraction: float = 0.10, positive_only: bool = False) -> dict:
    z = np.asarray(x, dtype=float)
    z = z[np.isfinite(z)]
    if positive_only:
        y = z[z > 0]
    else:
        y = np.abs(z - np.median(z))
        y = y[y > 0]
    y = np.sort(y)
    if len(y) < 50:
        return {"alpha": float("nan"), "tail_fraction": tail_fraction, "k": int(len(y))}
    k = max(10, int(math.floor(len(y) * tail_fraction)))
    k = min(k, len(y) - 1)
    threshold = float(y[-k - 1])
    tail = y[-k:]
    hill = float(np.mean(np.log(tail / max(threshold, EPS))))
    alpha = float(1.0 / hill) if hill > 0 else float("nan")
    return {
        "alpha": alpha,
        "tail_fraction": float(tail_fraction),
        "k": int(k),
        "threshold": threshold,
        "positive_only": bool(positive_only),
    }


def loglog_tail_slope(x: np.ndarray, min_quantile: float = 0.80) -> dict:
    y = np.abs(np.asarray(x, dtype=float) - np.nanmedian(x))
    y = y[np.isfinite(y) & (y > 0)]
    if len(y) < 50:
        return {"alpha": float("nan"), "min_quantile": min_quantile, "n_tail": int(len(y))}
    cutoff = float(np.quantile(y, min_quantile))
    tail = np.sort(y[y >= cutoff])
    n = len(y)
    survival = 1.0 - np.searchsorted(np.sort(y), tail, side="left") / n
    valid = (tail > 0) & (survival > 0)
    if valid.sum() < 20:
        return {"alpha": float("nan"), "min_quantile": min_quantile, "n_tail": int(valid.sum())}
    reg = stats.linregress(np.log(tail[valid]), np.log(survival[valid]))
    return {
        "alpha": float(-reg.slope),
        "slope": float(reg.slope),
        "r2": float(reg.rvalue**2),
        "min_quantile": float(min_quantile),
        "n_tail": int(valid.sum()),
    }


def empirical_codifference_proxy(x: np.ndarray, y: np.ndarray, u: float = 1.0) -> float:
    """Real log-characteristic-magnitude codifference proxy.

    LFSM work uses codifference because stable increments may not have finite
    covariance.  This finite-sample proxy is diagnostic only.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    x = x[valid]
    y = y[valid]
    if len(x) < 20:
        return float("nan")
    z_xy = np.mean(np.exp(1j * u * (x - y)))
    z_x = np.mean(np.exp(1j * u * x))
    z_y = np.mean(np.exp(-1j * u * y))
    return float(np.log(abs(z_xy) + EPS) - np.log(abs(z_x) + EPS) - np.log(abs(z_y) + EPS))


def autocorr(x: np.ndarray, lag: int) -> float:
    x = np.asarray(x, dtype=float)
    if len(x) <= lag + 5:
        return float("nan")
    a = x[lag:]
    b = x[:-lag]
    valid = np.isfinite(a) & np.isfinite(b)
    if valid.sum() < 10:
        return float("nan")
    return float(np.corrcoef(a[valid], b[valid])[0, 1])


def signed_power(x: np.ndarray, power: float) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    return np.sign(x) * np.power(np.abs(x), power)


def summarize_diagnostics(panel: pd.DataFrame) -> dict:
    log_rv = np.log(panel["rv"])
    dlog = log_rv.diff().dropna()
    x = dlog.values.astype(float)
    x = x[np.isfinite(x)]
    centered = x - np.median(x)
    mad = float(np.median(np.abs(centered)) * 1.4826)
    z = centered / max(mad, EPS)

    jb_stat, jb_p = stats.jarque_bera(x)
    norm_loc, norm_scale = float(np.mean(x)), float(np.std(x, ddof=1))
    norm_ll = float(np.sum(stats.norm.logpdf(x, loc=norm_loc, scale=max(norm_scale, EPS))))
    t_df, t_loc, t_scale = stats.t.fit(x)
    t_ll = float(np.sum(stats.t.logpdf(x, df=t_df, loc=t_loc, scale=t_scale)))

    pearson = {str(lag): autocorr(x, lag) for lag in range(1, 11)}
    sp = signed_power(z, 0.75)
    signed_power_ac = {str(lag): autocorr(sp, lag) for lag in range(1, 11)}
    codiff = {}
    for lag in range(1, 11):
        if len(z) <= lag + 10:
            codiff[str(lag)] = float("nan")
        else:
            codiff[str(lag)] = empirical_codifference_proxy(z[lag:], z[:-lag], u=1.0)

    abs_z = np.abs(z)
    tail_events = abs_z > 2.5

    return {
        "log_rv_hurst": {
            "frequency_ratio": estimate_hurst_frequency_ratio(log_rv),
            "variogram": estimate_hurst_variogram(log_rv),
        },
        "dlog_rv_moments": {
            "n": int(len(x)),
            "mean": float(np.mean(x)),
            "std": float(np.std(x, ddof=1)),
            "skewness": float(stats.skew(x, bias=False)),
            "excess_kurtosis": float(stats.kurtosis(x, fisher=True, bias=False)),
            "jarque_bera_stat": float(jb_stat),
            "jarque_bera_p": float(jb_p),
        },
        "tail_index": {
            "hill_abs_q90": hill_tail_index(x, tail_fraction=0.10, positive_only=False),
            "hill_abs_q95": hill_tail_index(x, tail_fraction=0.05, positive_only=False),
            "hill_right_q90": hill_tail_index(x, tail_fraction=0.10, positive_only=True),
            "loglog_survival_abs_q80": loglog_tail_slope(x, min_quantile=0.80),
        },
        "distribution_fit": {
            "normal": {"loc": norm_loc, "scale": norm_scale, "loglik": norm_ll, "aic": float(2 * 2 - 2 * norm_ll)},
            "student_t": {
                "df": float(t_df),
                "loc": float(t_loc),
                "scale": float(t_scale),
                "loglik": t_ll,
                "aic": float(2 * 3 - 2 * t_ll),
            },
            "delta_aic_normal_minus_t": float((2 * 2 - 2 * norm_ll) - (2 * 3 - 2 * t_ll)),
        },
        "dependence": {
            "pearson_acf_dlog_lags_1_10": pearson,
            "signed_power_075_acf_lags_1_10": signed_power_ac,
            "empirical_codifference_proxy_lags_1_10": codiff,
        },
        "tail_event_rate": {
            "mad_scaled_abs_dlog_gt_2p5": float(np.mean(tail_events)),
            "mad_scale": mad,
        },
    }


def robust_scale(dlog: np.ndarray, end_pos: int, window: int = 252) -> float:
    lo = max(1, end_pos - window)
    hist = dlog[lo:end_pos]
    hist = hist[np.isfinite(hist)]
    if len(hist) < 20:
        return 1.0
    med = float(np.median(hist))
    mad = float(np.median(np.abs(hist - med)) * 1.4826)
    return max(mad, EPS)


def fractional_stable_weights(h: float, alpha: float, max_lag: int = MAX_LAG) -> np.ndarray:
    h_use = float(np.clip(h if np.isfinite(h) else 0.1, 0.01, 0.49))
    alpha_use = float(np.clip(alpha if np.isfinite(alpha) else 1.8, 1.05, 2.0))
    exponent = h_use - (1.0 / alpha_use)
    k = np.arange(1, max_lag + 1, dtype=float)
    w = k**exponent
    w = w / np.sum(np.abs(w))
    return w


def model_kind(model: str) -> str:
    return "level" if model in {"HAR", "HARQ", "StableTailHAR"} else "delta"


def build_feature_row(
    model: str,
    log_rv: np.ndarray,
    rq: np.ndarray,
    dlog: np.ndarray,
    t: int,
    h: float,
    alpha: float,
    max_lag: int = MAX_LAG,
) -> Optional[List[float]]:
    """Build features for target day t using information through t-1."""
    if t < max_lag or t < 23:
        return None

    lag1 = float(log_rv[t - 1])
    lag5 = float(np.mean(log_rv[t - 5 : t]))
    lag22 = float(np.mean(log_rv[t - 22 : t]))

    if model == "HAR":
        return [lag1, lag5, lag22]

    if model == "HARQ":
        log_rq = math.log(max(float(rq[t - 1]), EPS))
        return [lag1, lag5, lag22, log_rq, lag1 * log_rq]

    if model == "StableTailHAR":
        scale = robust_scale(dlog, end_pos=t)
        prev_delta = float(dlog[t - 1])
        z = prev_delta / scale
        hist = dlog[max(1, t - 66) : t]
        tail_intensity = float(np.mean(np.abs(hist / scale) > 2.0)) if len(hist) else 0.0
        signed_tail = float(np.sign(z) * min(abs(z), 10.0) ** 0.75)
        return [lag1, lag5, lag22, math.log1p(abs(z)), signed_tail, tail_intensity]

    if model == "CodiffAR":
        scale = robust_scale(dlog, end_pos=t)
        lags = np.asarray([dlog[t - k] / scale for k in range(1, 6)], dtype=float)
        lags = np.clip(lags, -10.0, 10.0)
        sp = signed_power(lags, 0.75)
        codiff_signal = empirical_codifference_proxy(
            np.asarray(dlog[max(1, t - 67) : t], dtype=float) / scale,
            np.asarray(dlog[max(0, t - 68) : t - 1], dtype=float) / scale,
            u=1.0,
        )
        return list(lags) + list(sp) + [codiff_signal]

    if model == "LFSM_lite":
        scale = robust_scale(dlog, end_pos=t)
        hist = np.asarray(dlog[t - max_lag : t], dtype=float)[::-1]
        z = np.clip(hist / scale, -10.0, 10.0)
        weights = fractional_stable_weights(h, alpha, max_lag=max_lag)
        p = float(np.clip(alpha / 2.0, 0.55, 0.95))
        frac_delta = float(np.dot(weights, hist))
        frac_sp = float(np.dot(weights, signed_power(z, p)))
        frac_abs = float(np.dot(np.abs(weights), np.abs(z)))
        return [frac_delta, frac_sp, frac_abs, h, alpha]

    raise ValueError(f"Unknown model: {model}")


def fit_standardized_ols(y: np.ndarray, x: np.ndarray, model: str, h: float, alpha: float) -> OLSFit:
    x_mean = x.mean(axis=0)
    x_std = x.std(axis=0)
    x_std[x_std < 1e-12] = 1.0
    xs = (x - x_mean) / x_std
    design = np.column_stack([np.ones(len(xs)), xs])
    beta = np.linalg.lstsq(design, y, rcond=None)[0]
    resid = y - design @ beta
    dof = max(1, len(y) - x.shape[1] - 1)
    return OLSFit(
        beta=beta,
        x_mean=x_mean,
        x_std=x_std,
        resid_var=float(np.sum(resid**2) / dof),
        model_type=model_kind(model),
        h=float(h),
        alpha=float(alpha),
    )


def fit_model_for_origin(
    model: str,
    log_rv: np.ndarray,
    rq: np.ndarray,
    dlog: np.ndarray,
    origin_pos: int,
    h: float,
    alpha: float,
    max_lag: int = MAX_LAG,
) -> Optional[OLSFit]:
    rows: List[List[float]] = []
    y: List[float] = []
    start = max(max_lag, 23)
    for target_pos in range(start, origin_pos):
        row = build_feature_row(model, log_rv, rq, dlog, target_pos, h, alpha, max_lag=max_lag)
        if row is None or not np.all(np.isfinite(row)):
            continue
        target = (
            float(log_rv[target_pos])
            if model_kind(model) == "level"
            else float(log_rv[target_pos] - log_rv[target_pos - 1])
        )
        if math.isfinite(target):
            rows.append(row)
            y.append(target)
    if len(y) < 100:
        return None
    return fit_standardized_ols(np.asarray(y), np.asarray(rows), model=model, h=h, alpha=alpha)


def forecast_with_fit(fit: OLSFit, row: Iterable[float], prev_log_rv: float) -> float:
    x = np.asarray(list(row), dtype=float)
    xs = (x - fit.x_mean) / fit.x_std
    pred = float(np.r_[1.0, xs] @ fit.beta)
    if fit.model_type == "level":
        pred_log = pred + 0.5 * fit.resid_var
    else:
        pred_log = prev_log_rv + pred + 0.5 * fit.resid_var
    pred_log = float(np.clip(pred_log, -30.0, 5.0))
    return float(max(math.exp(pred_log), EPS))


def holm_adjust(raw_tests: Dict[str, dict]) -> Dict[str, dict]:
    keys = list(raw_tests)
    pvals = np.asarray([raw_tests[k]["p_value"] for k in keys], dtype=float)
    order = np.argsort(pvals)
    m = len(keys)
    running = 0.0
    adjusted = np.empty(m)
    for rank, idx in enumerate(order):
        adj = min(1.0, (m - rank) * pvals[idx])
        running = max(running, adj)
        adjusted[idx] = running
    out = {}
    for key, adj in zip(keys, adjusted):
        item = dict(raw_tests[key])
        item["holm_p_value"] = float(adj)
        item["holm_5pct"] = bool(adj < 0.05)
        out[key] = item
    return out


def oos_model_race(panel: pd.DataFrame) -> dict:
    panel = panel[["rv", "rq"]].dropna().copy()
    panel = panel[(panel["rv"] > 0) & (panel["rq"] > 0)]
    dates = pd.DatetimeIndex(panel.index)
    rv = panel["rv"].values.astype(float)
    rq = panel["rq"].values.astype(float)
    log_rv = np.log(np.maximum(rv, EPS))
    dlog = np.empty_like(log_rv)
    dlog[:] = np.nan
    dlog[1:] = np.diff(log_rv)

    oos_idx = int(dates.searchsorted(pd.Timestamp(OOS_START)))
    oos_idx = max(oos_idx, MIN_TRAIN, MAX_LAG + 100)

    actual: List[float] = []
    eval_dates: List[pd.Timestamp] = []
    forecasts: Dict[str, List[float]] = {m: [] for m in MODELS}
    h_path: List[float] = []
    alpha_path: List[float] = []
    fit_count = 0
    fits: Dict[str, OLSFit] = {}
    last_fit_pos = -10**9

    for pos in range(oos_idx, len(panel)):
        if pos - last_fit_pos >= REFIT_FREQ or not fits:
            train_log = pd.Series(log_rv[:pos], index=dates[:pos])
            h_freq = estimate_hurst_frequency_ratio(train_log)["H"]
            h_var = estimate_hurst_variogram(train_log)["H"]
            h = h_freq if math.isfinite(h_freq) else h_var
            h = float(np.clip(h if math.isfinite(h) else 0.1, 0.01, 0.49))
            alpha_est = hill_tail_index(dlog[1:pos], tail_fraction=0.10, positive_only=False)["alpha"]
            alpha = float(np.clip(alpha_est if math.isfinite(alpha_est) else 1.8, 1.05, 2.0))

            new_fits = {}
            for model in MODELS:
                fit = fit_model_for_origin(model, log_rv, rq, dlog, pos, h=h, alpha=alpha, max_lag=MAX_LAG)
                if fit is not None:
                    new_fits[model] = fit
            if set(MODELS).issubset(new_fits):
                fits = new_fits
                last_fit_pos = pos
                fit_count += 1

        if not set(MODELS).issubset(fits):
            continue

        row_forecasts = {}
        for model in MODELS:
            row = build_feature_row(
                model,
                log_rv,
                rq,
                dlog,
                pos,
                h=fits[model].h,
                alpha=fits[model].alpha,
                max_lag=MAX_LAG,
            )
            if row is None or not np.all(np.isfinite(row)):
                row_forecasts = {}
                break
            row_forecasts[model] = forecast_with_fit(fits[model], row, prev_log_rv=float(log_rv[pos - 1]))

        if len(row_forecasts) != len(MODELS):
            continue

        actual.append(float(rv[pos]))
        eval_dates.append(pd.Timestamp(dates[pos]))
        for model in MODELS:
            forecasts[model].append(float(row_forecasts[model]))
        h_path.append(float(fits["HAR"].h))
        alpha_path.append(float(fits["HAR"].alpha))

    if not actual:
        raise RuntimeError("No OOS forecasts generated")

    actual_arr = np.asarray(actual, dtype=float)
    forecast_arr = {m: np.asarray(v, dtype=float) for m, v in forecasts.items()}
    losses = {m: qlike_pointwise(actual_arr, forecast_arr[m]) for m in MODELS}
    qlikes = {m: float(qlike(actual_arr, forecast_arr[m])) for m in MODELS}

    raw_tests = {}
    for model in [m for m in MODELS if m != "HAR"]:
        t_stat, p_val = dm_test(losses[model], losses["HAR"], h=1)
        raw_tests[f"{model}_vs_HAR"] = {
            "candidate": model,
            "benchmark": "HAR",
            "t_stat": float(t_stat),
            "p_value": float(p_val),
            "candidate_lower_loss": bool(t_stat < 0),
            "harvey_abs_t_gt_3": bool(abs(t_stat) > 3.0),
            "sign_convention": "negative t => candidate has lower QLIKE loss than benchmark",
        }
    for model in NON_GAUSSIAN_MODELS:
        t_stat, p_val = dm_test(losses[model], losses["HARQ"], h=1)
        raw_tests[f"{model}_vs_HARQ"] = {
            "candidate": model,
            "benchmark": "HARQ",
            "t_stat": float(t_stat),
            "p_value": float(p_val),
            "candidate_lower_loss": bool(t_stat < 0),
            "harvey_abs_t_gt_3": bool(abs(t_stat) > 3.0),
            "sign_convention": "negative t => candidate has lower QLIKE loss than benchmark",
        }
    dm_tests = holm_adjust(raw_tests)

    strict_wins = [
        key
        for key, item in dm_tests.items()
        if item["candidate"] in NON_GAUSSIAN_MODELS
        and item["candidate_lower_loss"]
        and item["harvey_abs_t_gt_3"]
        and item["holm_5pct"]
    ]

    forecast_df = pd.DataFrame({"date": eval_dates, "actual_rv": actual_arr})
    for model in MODELS:
        forecast_df[f"forecast_{model}"] = forecast_arr[model]
        forecast_df[f"loss_{model}"] = losses[model]
    forecast_df.to_csv(FORECASTS_PATH, index=False)

    cumulative_loss_diff_vs_har = {}
    for model in [m for m in MODELS if m != "HAR"]:
        cumulative_loss_diff_vs_har[model] = np.cumsum(losses[model] - losses["HAR"]).tolist()

    return {
        "n_oos": int(len(actual_arr)),
        "start": str(eval_dates[0].date()),
        "end": str(eval_dates[-1].date()),
        "eval_dates": [str(d.date()) for d in eval_dates],
        "oos_start_requested": OOS_START,
        "min_train": MIN_TRAIN,
        "refit_freq_days": REFIT_FREQ,
        "fit_count": int(fit_count),
        "models": MODELS,
        "loss": "QLIKE actual/forecast - log(actual/forecast) - 1",
        "qlike": qlikes,
        "best_model_by_qlike": min(qlikes, key=qlikes.get),
        "dm_tests": dm_tests,
        "non_gaussian_strict_wins": strict_wins,
        "h_train_path": {
            "mean": float(np.mean(h_path)),
            "min": float(np.min(h_path)),
            "max": float(np.max(h_path)),
        },
        "alpha_train_path": {
            "mean": float(np.mean(alpha_path)),
            "min": float(np.min(alpha_path)),
            "max": float(np.max(alpha_path)),
            "note": "Hill tail index clipped to [1.05, 2.0] before LFSM-lite weights",
        },
        "cumulative_loss_diff_vs_har": cumulative_loss_diff_vs_har,
        "forecast_csv": str(FORECASTS_PATH.relative_to(ROOT)),
    }


def make_figure(panel: pd.DataFrame, diagnostics: dict, race: dict) -> None:
    dlog = np.log(panel["rv"]).diff().dropna().values.astype(float)
    tail = np.abs(dlog - np.median(dlog))
    tail = np.sort(tail[np.isfinite(tail) & (tail > 0)])
    survival = 1.0 - np.arange(len(tail), dtype=float) / len(tail)

    fig, axes = plt.subplots(1, 3, figsize=(15.0, 4.3))

    axes[0].loglog(tail, survival, color="#2F6B9A", linewidth=1.6)
    axes[0].set_xlabel("|Delta log RV - median|")
    axes[0].set_ylabel("Empirical survival")
    axes[0].set_title("TAIFEX dlog RV tail")
    tail_alpha = diagnostics["tail_index"]["loglog_survival_abs_q80"]["alpha"]
    axes[0].text(
        0.04,
        0.08,
        f"log-log alpha: {tail_alpha:.2f}",
        transform=axes[0].transAxes,
        fontsize=9,
        bbox={"facecolor": "white", "edgecolor": "#DDDDDD", "alpha": 0.9},
    )

    qlikes = race["qlike"]
    models = list(qlikes)
    vals = [qlikes[m] for m in models]
    colors = ["#4C78A8" if m in {"HAR", "HARQ"} else "#59A14F" for m in models]
    axes[1].bar(np.arange(len(models)), vals, color=colors)
    axes[1].set_xticks(np.arange(len(models)))
    axes[1].set_xticklabels(models, rotation=25, ha="right")
    axes[1].set_ylabel("Mean QLIKE")
    axes[1].set_title("Formal OOS race")

    dates = pd.to_datetime(race["eval_dates"])
    for model, series in race["cumulative_loss_diff_vs_har"].items():
        if model in NON_GAUSSIAN_MODELS:
            axes[2].plot(dates, series, label=model, linewidth=1.4)
    axes[2].axhline(0.0, color="black", linewidth=0.8)
    axes[2].set_ylabel("Cumulative loss diff vs HAR")
    axes[2].set_title("Negative means model beats HAR")
    axes[2].xaxis.set_major_locator(mdates.YearLocator())
    axes[2].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    axes[2].legend(frameon=False, fontsize=8)

    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    panel = load_taifex_day_rv()
    diagnostics = summarize_diagnostics(panel)
    race = oos_model_race(panel)
    make_figure(panel, diagnostics, race)

    heavy_tail_evidence = bool(
        diagnostics["dlog_rv_moments"]["jarque_bera_p"] < 0.05
        and diagnostics["distribution_fit"]["delta_aic_normal_minus_t"] > 10.0
    )
    stable_alpha_support = bool(
        diagnostics["tail_index"]["hill_abs_q90"]["alpha"] < 2.0
        or diagnostics["tail_index"]["loglog_survival_abs_q80"]["alpha"] < 2.0
    )
    forecast_edge = bool(len(race["non_gaussian_strict_wins"]) > 0)

    if heavy_tail_evidence and stable_alpha_support and forecast_edge:
        verdict = "SUPPORTED_WITH_OOS_EDGE"
    elif heavy_tail_evidence and stable_alpha_support:
        verdict = "HEAVY_TAIL_BUT_NO_FORECAST_EDGE"
    elif heavy_tail_evidence:
        verdict = "NON_GAUSSIAN_BUT_NOT_STABLELIKE_NO_EDGE"
    else:
        verdict = "NULL_OR_INSUFFICIENT"

    if forecast_edge:
        conclusion = (
            "TAIFEX 5-minute log-RV increments look non-Gaussian and at least one "
            "non-Gaussian rough-volatility lite signal clears both Harvey |t|>3 "
            "and Holm 5pct gates versus HAR/HARQ."
        )
    elif heavy_tail_evidence:
        conclusion = (
            "TAIFEX 5-minute log-RV increments are strongly non-Gaussian, but the "
            "stable-tail, codifference-proxy, and LFSM-lite forecasts do not beat "
            "HAR/HARQ under one-step-ahead QLIKE with DM/HAC inference."
        )
    else:
        conclusion = (
            "The bounded TAIFEX test does not provide enough non-Gaussian or OOS "
            "forecast evidence to advance alpha-stable rough volatility in this project."
        )

    results = {
        "experiment_id": "k1597",
        "title": "Non-Gaussian Rough Volatility with Stable-Increment Proxies",
        "timestamp_utc": pd.Timestamp.now("UTC").isoformat(),
        "seed": SEED,
        "task_id": "research_non_gaussian_rough_vol_stable_increments_arxiv_2",
        "references": REFERENCES,
        "dataset": {
            "name": "TAIFEX_TX_day_5min",
            "source": str(TAIFEX_5MIN_CACHE.relative_to(ROOT)),
            "start": str(panel.index[0].date()),
            "end": str(panel.index[-1].date()),
            "n_days": int(len(panel)),
            "median_intraday_returns_per_day": float(panel["n_intraday_returns"].median()),
            "rv_definition": "day-session realized variance from 5-minute TX futures bar-close log returns",
        },
        "diagnostics": diagnostics,
        "oos_model_race": race,
        "primary_test": {
            "dataset": "TAIFEX_TX_day_5min",
            "horizon": "one trading day",
            "lookahead_rule": "forecast for date t uses realized-volatility information through date t-1",
            "target": "5-minute realized variance",
            "loss": "QLIKE",
            "statistical_gate": "candidate must have lower QLIKE loss and pass Harvey |DM t|>3 plus Holm 5pct across reported pair tests",
        },
        "verdict": verdict,
        "conclusion": conclusion,
        "research_implication": (
            "The arXiv LFSM/codifference idea is worth tracking as measurement theory, "
            "but in this local market sample it does not yet create a robust forecasting "
            "contribution beyond HAR/HARQ.  A follow-up should require longer cross-asset "
            "intraday data or a faithful LFSM estimator before paper-level claims."
        ),
        "limitations": [
            "StableTailHAR, CodiffAR, and LFSM_lite are transparent proxies, not the full Garcin-Sawaya-Valade LFSM conditional-expectation estimator.",
            "Tail-index estimates are finite-sample diagnostics; they do not prove infinite-variance alpha-stable laws.",
            "TAIFEX day-session futures RV is the only formal dataset here; no cross-asset submission claim is made.",
            "The codifference term is an empirical characteristic-function proxy used for robustness, not structural LFSM estimation.",
        ],
        "outputs": {
            "results_json": str(RESULTS_PATH.relative_to(ROOT)),
            "forecast_csv": str(FORECASTS_PATH.relative_to(ROOT)),
            "figure": str(FIG_PATH.relative_to(ROOT)),
        },
    }

    RESULTS_PATH.write_text(json.dumps(_finite_json(results), indent=2, sort_keys=True) + "\n")
    print(json.dumps(_finite_json({"verdict": verdict, "n_oos": race["n_oos"], "best": race["best_model_by_qlike"]}), indent=2))


if __name__ == "__main__":
    main()
