"""K1587: NYC PM2.5 as a lagged behavioral volatility regressor.

Research question
-----------------
Does New York City PM2.5 contain incremental information for next-day or
next-week SPY volatility after controlling for lagged volatility and VIX?

Lookahead policy
----------------
EPA AirData daily PM2.5 summaries are end-of-local-day aggregates. The script
therefore treats them as unavailable for same-day trading and explicitly uses:

    pm25_signal = pm25_raw.shift(1)
    high_aqi100_signal = high_aqi100_raw.shift(1)
    high_aqi150_signal = high_aqi150_raw.shift(1)

The dependent variables are forward realized variance from trading date t
onward. Expanding OOS forecasts train only on rows whose overlapping forward
targets are fully realized before the forecast origin.
"""

from __future__ import annotations

import json
import math
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from volpred.stats.model_evaluation import dm_test, qlike_pointwise


EXPERIMENT_ID = "K1587"
EXP_DIR = Path(__file__).resolve().parent
DATA_DIR = EXP_DIR / "data"
RAW_DIR = DATA_DIR / "raw_epa_airdata"
FIG_DIR = EXP_DIR / "figures"
RESULTS_PATH = EXP_DIR / "K1587_results.json"
NYC_PM25_CACHE = DATA_DIR / "nyc_pm25_daily.csv"
PANEL_PATH = DATA_DIR / "k1587_panel.csv"
FIG_PATH = FIG_DIR / "k1587_pm25_vol_diagnostics.png"

SPY_VIX_PATH = ROOT / "paper" / "garch-x-vix" / "data" / "spy_vix_qqq_eem_fez_2000-2026.csv"
EPA_URL_TEMPLATE = "https://aqs.epa.gov/aqsweb/airdata/daily_88101_{year}.zip"

SEED = 42
START_YEAR = 2018
END_YEAR = 2025
MIN_TRAIN = 1000
MIN_EXPANDING_OBS = 252
BOOTSTRAP_REPS = 2000
BOOTSTRAP_BLOCK = 5
HORIZONS = (1, 5)
EPS = 1e-12

NYC_COUNTIES = {
    "005": "Bronx",
    "047": "Kings",
    "061": "New York",
    "081": "Queens",
    "085": "Richmond",
}


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)


def finite_float(value: object) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(out):
        return None
    return out


def fetch_epa_zip(year: int) -> Path:
    path = RAW_DIR / f"daily_88101_{year}.zip"
    if path.exists() and path.stat().st_size > 100_000:
        try:
            with zipfile.ZipFile(path) as zf:
                if zf.testzip() is None:
                    return path
        except zipfile.BadZipFile:
            pass
        path.unlink(missing_ok=True)
    url = EPA_URL_TEMPLATE.format(year=year)
    urllib.request.urlretrieve(url, path)
    if path.stat().st_size <= 100_000:
        raise RuntimeError(f"EPA AirData download appears too small: {url}")
    return path


def parse_epa_year(year: int) -> pd.DataFrame:
    zip_path = fetch_epa_zip(year)
    usecols = [
        "State Code",
        "County Code",
        "Site Num",
        "Parameter Code",
        "Date Local",
        "Observation Percent",
        "Arithmetic Mean",
        "AQI",
        "County Name",
        "City Name",
        "Sample Duration",
        "Pollutant Standard",
    ]
    frames: list[pd.DataFrame] = []
    with zipfile.ZipFile(zip_path) as zf:
        csv_names = [name for name in zf.namelist() if name.lower().endswith(".csv")]
        if not csv_names:
            raise RuntimeError(f"EPA AirData zip has no CSV member: {zip_path}")
        name = csv_names[0]
        for chunk in pd.read_csv(
            zf.open(name),
            usecols=usecols,
            dtype={"State Code": str, "County Code": str, "Site Num": str, "Parameter Code": str},
            chunksize=250_000,
        ):
            keep = (
                (chunk["State Code"] == "36")
                & chunk["County Code"].isin(NYC_COUNTIES)
                & (chunk["Parameter Code"] == "88101")
            )
            sub = chunk.loc[keep].copy()
            if len(sub):
                frames.append(sub)
    if not frames:
        return pd.DataFrame(columns=usecols)
    return pd.concat(frames, ignore_index=True)


def load_nyc_pm25(force: bool = False) -> pd.DataFrame:
    if NYC_PM25_CACHE.exists() and not force:
        df = pd.read_csv(NYC_PM25_CACHE, parse_dates=["date"])
        if len(df) > 1000:
            return df

    ensure_dirs()
    rows = [parse_epa_year(year) for year in range(START_YEAR, END_YEAR + 1)]
    raw = pd.concat(rows, ignore_index=True)
    if raw.empty:
        raise RuntimeError("No NYC PM2.5 rows found in EPA AirData files")

    raw["date"] = pd.to_datetime(raw["Date Local"], format="mixed").dt.normalize()
    raw["pm25"] = pd.to_numeric(raw["Arithmetic Mean"], errors="coerce")
    raw["aqi"] = pd.to_numeric(raw["AQI"], errors="coerce")
    raw["obs_pct"] = pd.to_numeric(raw["Observation Percent"], errors="coerce")

    # Prefer daily standard rows with AQI where available; this removes duplicate
    # hourly monitor summaries while keeping monitor-day coverage.
    raw["standard_rank"] = np.where(raw["Pollutant Standard"].notna(), 0, 1)
    raw["aqi_rank"] = np.where(raw["aqi"].notna(), 0, 1)
    raw = raw.sort_values(["date", "County Code", "Site Num", "standard_rank", "aqi_rank", "obs_pct"])
    monitor_daily = raw.drop_duplicates(["date", "County Code", "Site Num"], keep="last").copy()
    monitor_daily = monitor_daily[monitor_daily["pm25"].notna()]

    daily = monitor_daily.groupby("date").agg(
        pm25_mean=("pm25", "mean"),
        pm25_median=("pm25", "median"),
        pm25_max=("pm25", "max"),
        aqi_mean=("aqi", "mean"),
        aqi_max=("aqi", "max"),
        n_monitors=("pm25", "count"),
        n_counties=("County Code", "nunique"),
    )
    daily = daily.reset_index().sort_values("date")
    daily["high_aqi100_raw"] = (daily["aqi_max"] >= 100).astype(float)
    daily["high_aqi150_raw"] = (daily["aqi_max"] >= 150).astype(float)
    daily["pm25_top_decile_raw"] = (
        daily["pm25_mean"] >= daily["pm25_mean"].quantile(0.90)
    ).astype(float)

    daily.to_csv(NYC_PM25_CACHE, index=False)
    return daily


def load_spy_vix() -> pd.DataFrame:
    df = pd.read_csv(SPY_VIX_PATH)
    cols = ["date", "spy_adj_close", "spy_high", "spy_low", "vix_close"]
    missing = sorted(set(cols).difference(df.columns))
    if missing:
        raise ValueError(f"Missing SPY/VIX columns: {missing}")
    df = df[cols].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    for col in cols[1:]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=cols).sort_values("date").reset_index(drop=True)
    df["spy_log_ret"] = np.log(df["spy_adj_close"]).diff()
    df["rv1"] = df["spy_log_ret"] ** 2
    df["parkinson_var"] = (np.log(df["spy_high"] / df["spy_low"]) ** 2) / (4.0 * np.log(2.0))
    return df


def forward_rv(series: pd.Series, horizon: int) -> pd.Series:
    return series.rolling(horizon, min_periods=horizon).sum().shift(-(horizon - 1))


def expanding_zscore(series: pd.Series, min_periods: int = MIN_EXPANDING_OBS) -> pd.Series:
    mean = series.expanding(min_periods=min_periods).mean()
    std = series.expanding(min_periods=min_periods).std(ddof=0)
    return (series - mean) / std.replace(0.0, np.nan)


def build_panel() -> pd.DataFrame:
    pm25 = load_nyc_pm25()
    market = load_spy_vix()
    panel = pd.merge_asof(
        market.sort_values("date"),
        pm25.sort_values("date"),
        on="date",
        direction="backward",
    )
    panel = panel[(panel["date"] >= f"{START_YEAR}-01-01") & (panel["date"] <= f"{END_YEAR}-12-31")].copy()

    for horizon in HORIZONS:
        panel[f"fwd_rv{horizon}"] = forward_rv(panel["rv1"], horizon)
        panel[f"log_fwd_rv{horizon}"] = np.log(panel[f"fwd_rv{horizon}"].clip(lower=EPS))

    # Explicit signal lag. No contemporaneous PM2.5 is used.
    panel["pm25_signal"] = panel["pm25_mean"].shift(1)
    panel["aqi_signal"] = panel["aqi_max"].shift(1)
    panel["high_aqi100_signal"] = panel["high_aqi100_raw"].shift(1)
    panel["high_aqi150_signal"] = panel["high_aqi150_raw"].shift(1)
    panel["pm25_top_decile_signal"] = panel["pm25_top_decile_raw"].shift(1)
    panel["pm25_3d_mean_signal"] = panel["pm25_mean"].rolling(3, min_periods=3).mean().shift(1)
    panel["high_aqi100_3d_signal"] = panel["high_aqi100_raw"].rolling(3, min_periods=3).sum().shift(1)

    panel["pm25_z"] = expanding_zscore(panel["pm25_signal"])
    panel["pm25_3d_z"] = expanding_zscore(panel["pm25_3d_mean_signal"])
    panel["vix_signal"] = panel["vix_close"].shift(1)
    panel["vix_log_signal"] = np.log(panel["vix_signal"].clip(lower=EPS))
    panel["vix_z"] = expanding_zscore(panel["vix_signal"])
    panel["rv22_lag"] = panel["rv1"].rolling(22, min_periods=22).sum().shift(1)
    panel["log_rv22_lag"] = np.log(panel["rv22_lag"].clip(lower=EPS))
    panel["parkinson22_lag"] = panel["parkinson_var"].rolling(22, min_periods=22).sum().shift(1)
    panel["log_parkinson22_lag"] = np.log(panel["parkinson22_lag"].clip(lower=EPS))
    panel["ret5_lag"] = panel["spy_log_ret"].rolling(5, min_periods=5).sum().shift(1)
    panel["abs_ret5_lag"] = panel["spy_log_ret"].abs().rolling(5, min_periods=5).sum().shift(1)
    panel["pm25_x_vix"] = panel["pm25_z"] * panel["vix_z"]

    panel.to_csv(PANEL_PATH, index=False)
    return panel


BASE_COLS = ["vix_log_signal", "log_rv22_lag", "log_parkinson22_lag", "ret5_lag", "abs_ret5_lag"]
AUG_COLS = BASE_COLS + [
    "pm25_z",
    "pm25_3d_z",
    "high_aqi100_signal",
    "high_aqi100_3d_signal",
    "pm25_x_vix",
]


def regression_sample(panel: pd.DataFrame, horizon: int) -> pd.DataFrame:
    cols = ["date", f"fwd_rv{horizon}", f"log_fwd_rv{horizon}"] + AUG_COLS
    sample = panel[cols].dropna().copy()
    sample = sample[sample[f"fwd_rv{horizon}"] > 0].reset_index(drop=True)
    return sample


def fit_hac(panel: pd.DataFrame, horizon: int) -> dict[str, object]:
    sample = regression_sample(panel, horizon)
    y = sample[f"log_fwd_rv{horizon}"].to_numpy(dtype=float)
    out: dict[str, object] = {"horizon": horizon, "n": int(len(sample))}
    for name, cols in (("baseline_har_vix", BASE_COLS), ("augmented_pm25", AUG_COLS)):
        x = sm.add_constant(sample[cols], has_constant="add")
        fit = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": horizon})
        out[name] = {
            "r2": finite_float(fit.rsquared),
            "adj_r2": finite_float(fit.rsquared_adj),
            "aic": finite_float(fit.aic),
            "bic": finite_float(fit.bic),
            "coefficients": {key: finite_float(value) for key, value in fit.params.items()},
            "tvalues_hac": {key: finite_float(value) for key, value in fit.tvalues.items()},
            "pvalues_hac": {key: finite_float(value) for key, value in fit.pvalues.items()},
        }
    base = out["baseline_har_vix"]
    aug = out["augmented_pm25"]
    assert isinstance(base, dict) and isinstance(aug, dict)
    out["delta_adj_r2_aug_minus_base"] = finite_float(aug["adj_r2"] - base["adj_r2"])
    return out


def fit_predict(train_x: np.ndarray, train_y: np.ndarray, predict_x: np.ndarray) -> tuple[float, float]:
    beta, *_ = np.linalg.lstsq(train_x, train_y, rcond=None)
    residual = train_y - train_x @ beta
    resid_var = float(np.mean(residual * residual))
    pred_log = float(predict_x @ beta)
    pred_rv = float(np.exp(pred_log + 0.5 * resid_var))
    return pred_log, max(pred_rv, EPS)


def expanding_oos(panel: pd.DataFrame, horizon: int) -> dict[str, object]:
    sample = regression_sample(panel, horizon)
    y_log = sample[f"log_fwd_rv{horizon}"].to_numpy(dtype=float)
    y_rv = sample[f"fwd_rv{horizon}"].to_numpy(dtype=float)
    x_base = sm.add_constant(sample[BASE_COLS], has_constant="add").to_numpy(dtype=float)
    x_aug = sm.add_constant(sample[AUG_COLS], has_constant="add").to_numpy(dtype=float)

    rows: list[dict[str, object]] = []
    start = MIN_TRAIN + horizon
    for i in range(start, len(sample)):
        train_stop = i - horizon + 1
        if train_stop < MIN_TRAIN:
            continue
        pred_log_base, pred_rv_base = fit_predict(x_base[:train_stop], y_log[:train_stop], x_base[i])
        pred_log_aug, pred_rv_aug = fit_predict(x_aug[:train_stop], y_log[:train_stop], x_aug[i])
        rows.append(
            {
                "date": sample.loc[i, "date"],
                "actual_rv": y_rv[i],
                "actual_log_rv": y_log[i],
                "baseline_pred_log": pred_log_base,
                "augmented_pred_log": pred_log_aug,
                "baseline_pred_rv": pred_rv_base,
                "augmented_pred_rv": pred_rv_aug,
            }
        )

    forecasts = pd.DataFrame(rows)
    if forecasts.empty:
        return {"horizon": horizon, "n_oos": 0}
    loss_base = qlike_pointwise(forecasts["actual_rv"], forecasts["baseline_pred_rv"])
    loss_aug = qlike_pointwise(forecasts["actual_rv"], forecasts["augmented_pred_rv"])
    dm_t, dm_p = dm_test(loss_aug, loss_base, h=horizon)
    mean_base = float(np.mean(loss_base))
    mean_aug = float(np.mean(loss_aug))
    mse_base = float(np.mean((forecasts["actual_log_rv"] - forecasts["baseline_pred_log"]) ** 2))
    mse_aug = float(np.mean((forecasts["actual_log_rv"] - forecasts["augmented_pred_log"]) ** 2))
    return {
        "horizon": horizon,
        "n_oos": int(len(forecasts)),
        "start_date": str(pd.Timestamp(forecasts["date"].min()).date()),
        "end_date": str(pd.Timestamp(forecasts["date"].max()).date()),
        "mean_qlike_baseline_har_vix": mean_base,
        "mean_qlike_augmented_pm25": mean_aug,
        "qlike_improvement_pct_augmented_vs_baseline": finite_float((mean_base - mean_aug) / mean_base * 100.0),
        "dm_t_augmented_vs_baseline": finite_float(dm_t),
        "dm_p_augmented_vs_baseline": finite_float(dm_p),
        "mse_log_baseline": mse_base,
        "mse_log_augmented": mse_aug,
        "mse_log_improvement_pct_augmented_vs_baseline": finite_float((mse_base - mse_aug) / mse_base * 100.0),
    }


def block_resample_mean(values: np.ndarray, rng: np.random.Generator, block: int) -> float:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    n = len(values)
    if n == 0:
        return float("nan")
    if n <= block:
        return float(np.mean(values[rng.integers(0, n, size=n)]))
    starts = rng.integers(0, n - block + 1, size=int(math.ceil(n / block)))
    return float(np.concatenate([values[start : start + block] for start in starts])[:n].mean())


def event_diff(panel: pd.DataFrame, flag: str, target: str) -> dict[str, object]:
    sample = panel[[flag, target]].dropna()
    treated = sample.loc[sample[flag] > 0, target].to_numpy(dtype=float)
    control = sample.loc[sample[flag] <= 0, target].to_numpy(dtype=float)
    treated = treated[np.isfinite(treated)]
    control = control[np.isfinite(control)]
    out: dict[str, object] = {
        "flag": flag,
        "target": target,
        "n_treated": int(len(treated)),
        "n_control": int(len(control)),
        "treated_mean": finite_float(np.mean(treated)) if len(treated) else None,
        "control_mean": finite_float(np.mean(control)) if len(control) else None,
    }
    if len(treated) < 5 or len(control) < 50:
        out.update({"diff": None, "ci95_low": None, "ci95_high": None, "p_one_sided_treated_greater": None})
        return out
    observed = float(np.mean(treated) - np.mean(control))
    rng = np.random.default_rng(SEED)
    diffs = np.empty(BOOTSTRAP_REPS)
    for i in range(BOOTSTRAP_REPS):
        diffs[i] = block_resample_mean(treated, rng, BOOTSTRAP_BLOCK) - block_resample_mean(control, rng, BOOTSTRAP_BLOCK)
    out.update(
        {
            "diff": observed,
            "ratio": finite_float(np.mean(treated) / np.mean(control)) if np.mean(control) != 0 else None,
            "ci95_low": finite_float(np.quantile(diffs, 0.025)),
            "ci95_high": finite_float(np.quantile(diffs, 0.975)),
            "p_one_sided_treated_greater": finite_float(np.mean(diffs <= 0.0)),
        }
    )
    return out


def summarize_pollution(panel: pd.DataFrame) -> dict[str, object]:
    sample = panel.dropna(subset=["pm25_signal"])
    aqi_sample = panel.dropna(subset=["aqi_signal"])
    top_dates = (
        aqi_sample.sort_values("aqi_signal", ascending=False)
        .head(10)[["date", "pm25_signal", "aqi_signal", "fwd_rv1", "fwd_rv5"]]
        .assign(date=lambda x: x["date"].dt.strftime("%Y-%m-%d"))
        .to_dict(orient="records")
    )
    return {
        "pm25_signal_rows": int(len(sample)),
        "aqi_signal_rows": int(len(aqi_sample)),
        "pm25_signal_mean": finite_float(sample["pm25_signal"].mean()),
        "pm25_signal_std": finite_float(sample["pm25_signal"].std()),
        "aqi_signal_max": finite_float(aqi_sample["aqi_signal"].max()),
        "high_aqi100_signal_days": int((aqi_sample["high_aqi100_signal"] > 0).sum()),
        "high_aqi150_signal_days": int((aqi_sample["high_aqi150_signal"] > 0).sum()),
        "pm25_top_decile_signal_days": int((sample["pm25_top_decile_signal"] > 0).sum()),
        "top_aqi_signal_dates": top_dates,
    }


def make_figure(panel: pd.DataFrame, oos: dict[str, dict[str, object]], event_tests: dict[str, object]) -> None:
    plot = panel.dropna(subset=["date", "pm25_z", "vix_z"]).copy()
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))

    axes[0, 0].plot(plot["date"], plot["pm25_z"], lw=1.0, label="NYC PM2.5 z")
    axes[0, 0].plot(plot["date"], plot["vix_z"], lw=0.9, alpha=0.75, label="VIX z")
    axes[0, 0].axhline(0.0, color="black", lw=0.8)
    axes[0, 0].set_title("Lagged signals")
    axes[0, 0].legend(fontsize=8)

    high = panel.loc[panel["high_aqi100_signal"] > 0, "fwd_rv5"].dropna()
    normal = panel.loc[panel["high_aqi100_signal"] <= 0, "fwd_rv5"].dropna()
    axes[0, 1].boxplot([normal, high], tick_labels=["AQI<100", "AQI>=100"], showfliers=False)
    axes[0, 1].set_title("Forward 5d RV by lagged AQI bucket")

    labels = []
    base_values = []
    aug_values = []
    for horizon in HORIZONS:
        key = f"h{horizon}"
        labels.append(f"{horizon}d")
        base_values.append(oos[key].get("mean_qlike_baseline_har_vix", np.nan))
        aug_values.append(oos[key].get("mean_qlike_augmented_pm25", np.nan))
    x = np.arange(len(labels))
    width = 0.35
    axes[1, 0].bar(x - width / 2, base_values, width, label="HAR/VIX", color="#64748b")
    axes[1, 0].bar(x + width / 2, aug_values, width, label="HAR/VIX+PM2.5", color="#0f766e")
    axes[1, 0].set_xticks(x, labels)
    axes[1, 0].set_title("OOS QLIKE")
    axes[1, 0].legend(fontsize=8)

    keys = ["high_aqi100_fwd_rv1", "high_aqi100_fwd_rv5", "top_decile_fwd_rv1", "top_decile_fwd_rv5"]
    ratios = [event_tests[key].get("ratio", np.nan) for key in keys]
    axes[1, 1].bar(["AQI100 1d", "AQI100 5d", "Top10 1d", "Top10 5d"], ratios, color="#2563eb")
    axes[1, 1].axhline(1.0, color="black", lw=0.8)
    axes[1, 1].set_title("Pollution bucket RV ratio")
    axes[1, 1].tick_params(axis="x", rotation=20, labelsize=8)

    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=150)
    plt.close(fig)


def classify(results: dict[str, object]) -> dict[str, object]:
    oos = results["oos_forecast"]
    regs = results["in_sample_hac_regressions"]
    events = results["pollution_event_tests"]
    assert isinstance(oos, dict) and isinstance(regs, dict) and isinstance(events, dict)

    pass_horizons: list[int] = []
    weak_horizons: list[int] = []
    for horizon in HORIZONS:
        o = oos[f"h{horizon}"]
        r = regs[f"h{horizon}"]
        assert isinstance(o, dict) and isinstance(r, dict)
        aug = r["augmented_pm25"]
        assert isinstance(aug, dict)
        tvalues = aug["tvalues_hac"]
        assert isinstance(tvalues, dict)
        pm25_terms = ["pm25_z", "pm25_3d_z", "high_aqi100_signal", "high_aqi100_3d_signal", "pm25_x_vix"]
        continuous_terms = ["pm25_z", "pm25_3d_z", "pm25_x_vix"]
        best_t = max(abs(float(tvalues.get(term) or 0.0)) for term in pm25_terms)
        best_continuous_t = max(abs(float(tvalues.get(term) or 0.0)) for term in continuous_terms)
        improvement = float(o.get("qlike_improvement_pct_augmented_vs_baseline") or 0.0)
        dm_t = float(o.get("dm_t_augmented_vs_baseline") or 0.0)
        if improvement > 0.0 and dm_t < -3.0 and best_t > 3.0:
            pass_horizons.append(horizon)
        elif improvement > 0.0 or best_continuous_t > 2.0:
            weak_horizons.append(horizon)

    event_support = False
    for key in ("high_aqi100_fwd_rv1", "high_aqi100_fwd_rv5", "top_decile_fwd_rv1", "top_decile_fwd_rv5"):
        item = events[key]
        assert isinstance(item, dict)
        p = item.get("p_one_sided_treated_greater")
        diff = item.get("diff")
        if p is not None and diff is not None and float(diff) > 0 and float(p) < 0.05:
            event_support = True

    if pass_horizons:
        label = "SUPPORTIVE"
        reason = "PM2.5 terms improve OOS QLIKE with DM t<-3 and pass HAC term support."
    elif event_support or weak_horizons:
        label = "WEAK_RAW_ONLY"
        reason = "Some raw or in-sample PM2.5 diagnostics are positive, but the formal OOS forecast gate is not met."
    else:
        label = "NULL"
        reason = "PM2.5 does not improve OOS volatility forecasts and pollution-bucket evidence is weak."
    return {
        "label": label,
        "pass_horizons": pass_horizons,
        "weak_horizons": weak_horizons,
        "event_support": bool(event_support),
        "reason": reason,
    }


def run() -> dict[str, object]:
    ensure_dirs()
    panel = build_panel()
    regressions = {f"h{horizon}": fit_hac(panel, horizon) for horizon in HORIZONS}
    oos = {f"h{horizon}": expanding_oos(panel, horizon) for horizon in HORIZONS}
    event_tests = {
        "high_aqi100_fwd_rv1": event_diff(panel, "high_aqi100_signal", "fwd_rv1"),
        "high_aqi100_fwd_rv5": event_diff(panel, "high_aqi100_signal", "fwd_rv5"),
        "high_aqi150_fwd_rv1": event_diff(panel, "high_aqi150_signal", "fwd_rv1"),
        "high_aqi150_fwd_rv5": event_diff(panel, "high_aqi150_signal", "fwd_rv5"),
        "top_decile_fwd_rv1": event_diff(panel, "pm25_top_decile_signal", "fwd_rv1"),
        "top_decile_fwd_rv5": event_diff(panel, "pm25_top_decile_signal", "fwd_rv5"),
    }

    results: dict[str, object] = {
        "experiment_id": EXPERIMENT_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data": {
            "epa_source_template": EPA_URL_TEMPLATE,
            "epa_years": [START_YEAR, END_YEAR],
            "epa_parameter_code": "88101 PM2.5 - Local Conditions",
            "nyc_counties": NYC_COUNTIES,
            "nyc_pm25_cache": str(NYC_PM25_CACHE.relative_to(ROOT)),
            "spy_vix_source": str(SPY_VIX_PATH.relative_to(ROOT)),
            "panel_path": str(PANEL_PATH.relative_to(ROOT)),
            "panel_rows": int(len(panel)),
            "panel_start": str(panel["date"].min().date()),
            "panel_end": str(panel["date"].max().date()),
            "regression_rows_h1": int(regressions["h1"]["n"]),
            "regression_rows_h5": int(regressions["h5"]["n"]),
        },
        "method": {
            "pollution_signal": "NYC monitor-day PM2.5 mean and AQI max from EPA daily_88101 files; signal.shift(1).",
            "market_target": "SPY close-to-close forward realized variance, h in {1,5}.",
            "controls": BASE_COLS,
            "augmented_terms": [col for col in AUG_COLS if col not in BASE_COLS],
            "oos_guard": "For horizon h, forecast row i trains only on rows j <= i-h.",
            "formal_gate": "Support requires OOS QLIKE improvement with DM t<-3 and a PM2.5 HAC term |t|>3.",
            "limitation": "Daily SPY proxy, not intraday RV/spread; NYC pilot, not a 47-city replication.",
        },
        "pollution_summary": summarize_pollution(panel),
        "pollution_event_tests": event_tests,
        "in_sample_hac_regressions": regressions,
        "oos_forecast": oos,
        "figure": str(FIG_PATH.relative_to(ROOT)),
    }
    results["verdict"] = classify(results)
    make_figure(panel, oos, event_tests)
    RESULTS_PATH.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    return results


if __name__ == "__main__":
    output = run()
    print(json.dumps(output["verdict"], indent=2, sort_keys=True))
