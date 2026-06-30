"""K1585: Agreed-vs-disagreed uncertainty regime test.

Research question
-----------------
Does a low-disagreement/high-uncertainty cell ("agreed uncertainty") forecast
higher future SPY realized volatility or downside tail risk than a
high-disagreement/high-uncertainty cell, and does SPF disagreement add forecast
power beyond VIX?

Lookahead policy
----------------
Daily predictors are explicitly shifted by one trading day before forecasting
forward SPY realized volatility:

    signal_vix_t = vix_close.shift(1)
    signal_disagreement_t = spf_disagreement_daily.shift(1)

The SPF survey-disagreement workbook does not include exact release timestamps,
so this script uses a conservative availability date: survey quarter end + 45
calendar days, then daily forward-fill, then the one-day shift above. Expanding
OOS regressions also train only on rows whose overlapping forward-RV targets are
fully realized before the forecast origin.
"""

from __future__ import annotations

import json
import math
import re
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

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


EXPERIMENT_ID = "K1585"
EXP_DIR = Path(__file__).resolve().parent
DATA_DIR = EXP_DIR / "data"
FIG_DIR = EXP_DIR / "figures"
RESULTS_PATH = EXP_DIR / "k1585_results.json"
FIG_PATH = FIG_DIR / "k1585_regime_diagnostics.png"

SPY_VIX_PATH = ROOT / "paper" / "garch-x-vix" / "data" / "spy_vix_qqq_eem_fez_2000-2026.csv"
SPF_D2_PATH = DATA_DIR / "Dispersion_2.xlsx"
SPF_D2_URL = (
    "https://www.philadelphiafed.org/-/media/FRBP/Assets/Surveys-And-Data/"
    "survey-of-professional-forecasters/historical-data/Dispersion_2.xlsx"
)

SEED = 42
EPS = 1e-12
MIN_EXPANDING_OBS = 252
MIN_TRAIN = 1000
BOOTSTRAP_REPS = 2000
BOOTSTRAP_BLOCK = 21
HORIZONS = (5, 21)


NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)


def ensure_spf_workbook() -> None:
    if SPF_D2_PATH.exists():
        return
    ensure_dirs()
    urllib.request.urlretrieve(SPF_D2_URL, SPF_D2_PATH)


def col_to_int(col: str) -> int:
    value = 0
    for ch in col:
        value = value * 26 + ord(ch) - ord("A") + 1
    return value


def read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    shared: list[str] = []
    for item in root.findall("a:si", NS):
        texts = [node.text or "" for node in item.findall(".//a:t", NS)]
        shared.append("".join(texts))
    return shared


def workbook_sheet_paths(zf: zipfile.ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    relmap = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
    paths: dict[str, str] = {}
    for sheet in workbook.findall("a:sheets/a:sheet", NS):
        rid = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        target = relmap[rid].lstrip("/")
        if not target.startswith("xl/"):
            target = f"xl/{target}"
        paths[sheet.attrib["name"]] = target
    return paths


def cell_value(cell: ET.Element, shared: list[str]) -> str | float | None:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        texts = [node.text or "" for node in cell.findall(".//a:t", NS)]
        return "".join(texts)
    value_node = cell.find("a:v", NS)
    if value_node is None:
        return None
    raw = value_node.text
    if raw is None:
        return None
    if cell_type == "s":
        return shared[int(raw)]
    if cell_type == "str":
        return raw
    try:
        return float(raw)
    except ValueError:
        return raw


def parse_xlsx_sheet(path: Path, sheet_name: str) -> pd.DataFrame:
    with zipfile.ZipFile(path) as zf:
        shared = read_shared_strings(zf)
        sheet_paths = workbook_sheet_paths(zf)
        if sheet_name not in sheet_paths:
            raise KeyError(f"Sheet {sheet_name!r} not found in {path}")
        root = ET.fromstring(zf.read(sheet_paths[sheet_name]))

        rows: list[tuple[int, dict[str, object]]] = []
        for row in root.findall(".//a:sheetData/a:row", NS):
            row_number = int(row.attrib["r"])
            values: dict[str, object] = {}
            for cell in row.findall("a:c", NS):
                match = re.match(r"([A-Z]+)(\d+)", cell.attrib["r"])
                if not match:
                    continue
                values[match.group(1)] = cell_value(cell, shared)
            rows.append((row_number, values))

    header_row = None
    for row_number, values in rows:
        if values.get("A") == "Survey_Date(T)":
            header_row = row_number
            header = {col: str(value) for col, value in values.items() if value is not None}
            break
    if header_row is None:
        raise ValueError(f"Could not find SPF header row in sheet {sheet_name}")

    records: list[dict[str, object]] = []
    for row_number, values in rows:
        if row_number <= header_row:
            continue
        record: dict[str, object] = {}
        for col, name in header.items():
            record[name] = values.get(col)
        if record.get("Survey_Date(T)") is not None:
            records.append(record)
    return pd.DataFrame(records)


def load_spf_disagreement() -> pd.DataFrame:
    ensure_spf_workbook()
    frames: list[pd.DataFrame] = []
    for var in ("RGDP", "PGDP"):
        sheet = parse_xlsx_sheet(SPF_D2_PATH, var)
        col = f"{var}_D2(T+4)"
        frame = sheet[["Survey_Date(T)", col]].copy()
        frame = frame.rename(columns={"Survey_Date(T)": "survey_quarter", col: f"{var.lower()}_d2_t4"})
        frame[f"{var.lower()}_d2_t4"] = pd.to_numeric(frame[f"{var.lower()}_d2_t4"], errors="coerce")
        frames.append(frame)

    merged = frames[0].merge(frames[1], on="survey_quarter", how="inner")
    merged = merged.dropna(subset=["rgdp_d2_t4", "pgdp_d2_t4"]).copy()

    periods = pd.PeriodIndex(merged["survey_quarter"].astype(str), freq="Q-DEC")
    merged["survey_quarter_start"] = periods.start_time.normalize()
    merged["survey_quarter_end"] = periods.end_time.normalize()
    merged["release_date"] = merged["survey_quarter_end"] + pd.Timedelta(days=45)

    # Both components are D2 interquartile ranges in annualized percentage
    # points. log1p keeps the composite positive and dampens rare survey spikes.
    merged["spf_disagreement_raw"] = (
        np.log1p(merged["rgdp_d2_t4"].clip(lower=0.0))
        + np.log1p(merged["pgdp_d2_t4"].clip(lower=0.0))
    ) / 2.0
    return merged.sort_values("release_date").reset_index(drop=True)


def load_daily_spy_vix() -> pd.DataFrame:
    df = pd.read_csv(SPY_VIX_PATH)
    required = ["date", "spy_adj_close", "vix_close"]
    missing = sorted(set(required).difference(df.columns))
    if missing:
        raise ValueError(f"Missing required SPY/VIX columns: {missing}")
    df = df[required].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["spy_adj_close"] = pd.to_numeric(df["spy_adj_close"], errors="coerce")
    df["vix_close"] = pd.to_numeric(df["vix_close"], errors="coerce")
    df = df.dropna(subset=["spy_adj_close", "vix_close"]).sort_values("date").reset_index(drop=True)
    df["spy_log_ret"] = np.log(df["spy_adj_close"]).diff()
    df["rv1"] = df["spy_log_ret"] ** 2
    return df


def forward_realized_variance(ret2: pd.Series, horizon: int) -> pd.Series:
    return ret2.rolling(horizon, min_periods=horizon).sum().shift(-(horizon - 1))


def forward_drawdown(close: pd.Series, horizon: int) -> pd.Series:
    values = close.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    for i in range(1, len(values) - horizon + 1):
        base = values[i - 1]
        if not np.isfinite(base) or base <= 0:
            continue
        future = values[i : i + horizon]
        future = future[np.isfinite(future)]
        if len(future) == horizon:
            out[i] = float(np.min(future) / base - 1.0)
    return pd.Series(out, index=close.index)


def expanding_zscore(series: pd.Series, min_periods: int = MIN_EXPANDING_OBS) -> pd.Series:
    mean = series.expanding(min_periods=min_periods).mean()
    std = series.expanding(min_periods=min_periods).std(ddof=0)
    return (series - mean) / std.replace(0.0, np.nan)


def merge_daily_features(daily: pd.DataFrame, spf: pd.DataFrame) -> pd.DataFrame:
    df = pd.merge_asof(
        daily.sort_values("date"),
        spf[["release_date", "survey_quarter", "rgdp_d2_t4", "pgdp_d2_t4", "spf_disagreement_raw"]],
        left_on="date",
        right_on="release_date",
        direction="backward",
    )

    for horizon in HORIZONS:
        df[f"fwd_rv{horizon}"] = forward_realized_variance(df["rv1"], horizon)
        df[f"log_fwd_rv{horizon}"] = np.log(df[f"fwd_rv{horizon}"].clip(lower=EPS))
    df["fwd_drawdown21"] = forward_drawdown(df["spy_adj_close"], 21)
    df["tail_event21"] = np.where(
        df["fwd_drawdown21"].notna(),
        (df["fwd_drawdown21"] <= -0.05).astype(float),
        np.nan,
    )

    # Explicit lag policy: signal from t-1, return/RV target from t onward.
    df["vix_signal"] = df["vix_close"].shift(1)
    df["spf_disagreement_signal"] = df["spf_disagreement_raw"].shift(1)
    df["vix_z"] = expanding_zscore(df["vix_signal"])
    df["disagreement_z"] = expanding_zscore(df["spf_disagreement_signal"])
    df["vix_x_disagreement"] = df["vix_z"] * df["disagreement_z"]

    df["rv21_lag"] = df["rv1"].rolling(21, min_periods=21).sum().shift(1)
    df["log_rv21_lag"] = np.log(df["rv21_lag"].clip(lower=EPS))
    df["ret21_lag"] = df["spy_log_ret"].rolling(21, min_periods=21).sum().shift(1)
    df["abs_ret5_lag"] = df["spy_log_ret"].abs().rolling(5, min_periods=5).sum().shift(1)

    valid_regime = df["vix_z"].notna() & df["disagreement_z"].notna()
    high_vix = df["vix_z"] > 0.0
    high_dis = df["disagreement_z"] > 0.0
    df["regime"] = np.select(
        [
            valid_regime & high_vix & ~high_dis,
            valid_regime & high_vix & high_dis,
            valid_regime & ~high_vix & ~high_dis,
            valid_regime & ~high_vix & high_dis,
        ],
        [
            "high_uncertainty_low_disagreement",
            "high_uncertainty_high_disagreement",
            "low_uncertainty_low_disagreement",
            "low_uncertainty_high_disagreement",
        ],
        default="unclassified",
    )
    return df


def finite_float(value: object) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(out):
        return None
    return out


def summarize_regimes(df: pd.DataFrame) -> dict[str, dict[str, float | int | None]]:
    sample = df.dropna(subset=["regime", "fwd_rv5", "fwd_rv21", "fwd_drawdown21", "tail_event21"])
    sample = sample[sample["regime"] != "unclassified"]
    out: dict[str, dict[str, float | int | None]] = {}
    for regime, group in sample.groupby("regime"):
        out[regime] = {
            "n": int(len(group)),
            "mean_fwd_rv5": finite_float(group["fwd_rv5"].mean()),
            "mean_fwd_rv21": finite_float(group["fwd_rv21"].mean()),
            "annualized_vol_from_mean_fwd_rv21": finite_float(math.sqrt(group["fwd_rv21"].mean() * 252.0 / 21.0)),
            "tail_event21_rate": finite_float(group["tail_event21"].mean()),
            "mean_fwd_drawdown21": finite_float(group["fwd_drawdown21"].mean()),
            "median_vix_signal": finite_float(group["vix_signal"].median()),
            "median_spf_disagreement": finite_float(group["spf_disagreement_signal"].median()),
        }
    return out


def block_resample_mean(values: np.ndarray, rng: np.random.Generator, block: int) -> float:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    n = len(values)
    if n == 0:
        return float("nan")
    if n <= block:
        return float(np.mean(values[rng.integers(0, n, size=n)]))
    starts = rng.integers(0, n - block + 1, size=int(math.ceil(n / block)))
    samples = [values[start : start + block] for start in starts]
    return float(np.concatenate(samples)[:n].mean())


def bootstrap_regime_difference(df: pd.DataFrame, column: str) -> dict[str, float | int | None]:
    sample = df.dropna(subset=["regime", column])
    agreed = sample.loc[sample["regime"] == "high_uncertainty_low_disagreement", column].to_numpy(dtype=float)
    disagreed = sample.loc[sample["regime"] == "high_uncertainty_high_disagreement", column].to_numpy(dtype=float)
    agreed = agreed[np.isfinite(agreed)]
    disagreed = disagreed[np.isfinite(disagreed)]
    if len(agreed) < 30 or len(disagreed) < 30:
        return {
            "metric": column,
            "n_agreed": int(len(agreed)),
            "n_disagreed": int(len(disagreed)),
            "observed_diff_agreed_minus_disagreed": None,
            "ci95_low": None,
            "ci95_high": None,
            "p_one_sided_agreed_greater": None,
        }
    observed = float(np.mean(agreed) - np.mean(disagreed))
    rng = np.random.default_rng(SEED)
    diffs = np.empty(BOOTSTRAP_REPS)
    for i in range(BOOTSTRAP_REPS):
        diffs[i] = block_resample_mean(agreed, rng, BOOTSTRAP_BLOCK) - block_resample_mean(disagreed, rng, BOOTSTRAP_BLOCK)
    return {
        "metric": column,
        "n_agreed": int(len(agreed)),
        "n_disagreed": int(len(disagreed)),
        "observed_diff_agreed_minus_disagreed": observed,
        "ci95_low": finite_float(np.quantile(diffs, 0.025)),
        "ci95_high": finite_float(np.quantile(diffs, 0.975)),
        "p_one_sided_agreed_greater": finite_float(np.mean(diffs <= 0.0)),
    }


def regression_sample(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    cols = [
        "date",
        f"fwd_rv{horizon}",
        f"log_fwd_rv{horizon}",
        "vix_z",
        "disagreement_z",
        "vix_x_disagreement",
        "log_rv21_lag",
        "ret21_lag",
        "abs_ret5_lag",
    ]
    sample = df[cols].dropna().copy()
    sample = sample[sample[f"fwd_rv{horizon}"] > 0].reset_index(drop=True)
    return sample


def fit_hac_models(df: pd.DataFrame, horizon: int) -> dict[str, object]:
    sample = regression_sample(df, horizon)
    y = sample[f"log_fwd_rv{horizon}"].to_numpy(dtype=float)
    base_cols = ["vix_z", "log_rv21_lag", "ret21_lag", "abs_ret5_lag"]
    aug_cols = base_cols + ["disagreement_z", "vix_x_disagreement"]

    results: dict[str, object] = {"n": int(len(sample)), "horizon": horizon}
    for name, cols in (("baseline_vix_only", base_cols), ("augmented_vix_spf", aug_cols)):
        x = sm.add_constant(sample[cols], has_constant="add")
        fit = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": horizon})
        results[name] = {
            "r2": finite_float(fit.rsquared),
            "adj_r2": finite_float(fit.rsquared_adj),
            "aic": finite_float(fit.aic),
            "bic": finite_float(fit.bic),
            "coefficients": {key: finite_float(value) for key, value in fit.params.items()},
            "tvalues_hac": {key: finite_float(value) for key, value in fit.tvalues.items()},
            "pvalues_hac": {key: finite_float(value) for key, value in fit.pvalues.items()},
        }

    fit_base = results["baseline_vix_only"]
    fit_aug = results["augmented_vix_spf"]
    assert isinstance(fit_base, dict) and isinstance(fit_aug, dict)
    results["delta_adj_r2_aug_minus_base"] = finite_float(fit_aug["adj_r2"] - fit_base["adj_r2"])
    return results


def fit_predict_expanding(train_x: np.ndarray, train_y: np.ndarray, predict_x: np.ndarray) -> tuple[float, float]:
    beta, *_ = np.linalg.lstsq(train_x, train_y, rcond=None)
    residual = train_y - train_x @ beta
    resid_var = float(np.mean(residual * residual))
    pred_log = float(predict_x @ beta)
    pred_rv = float(np.exp(pred_log + 0.5 * resid_var))
    return pred_log, max(pred_rv, EPS)


def expanding_oos(df: pd.DataFrame, horizon: int) -> dict[str, object]:
    sample = regression_sample(df, horizon)
    y_log = sample[f"log_fwd_rv{horizon}"].to_numpy(dtype=float)
    y_rv = sample[f"fwd_rv{horizon}"].to_numpy(dtype=float)

    base_cols = ["vix_z", "log_rv21_lag", "ret21_lag", "abs_ret5_lag"]
    aug_cols = base_cols + ["disagreement_z", "vix_x_disagreement"]
    x_base = sm.add_constant(sample[base_cols], has_constant="add").to_numpy(dtype=float)
    x_aug = sm.add_constant(sample[aug_cols], has_constant="add").to_numpy(dtype=float)

    start = MIN_TRAIN + horizon
    rows: list[dict[str, object]] = []
    for i in range(start, len(sample)):
        train_stop = i - horizon + 1
        if train_stop < MIN_TRAIN:
            continue
        pred_log_base, pred_rv_base = fit_predict_expanding(x_base[:train_stop], y_log[:train_stop], x_base[i])
        pred_log_aug, pred_rv_aug = fit_predict_expanding(x_aug[:train_stop], y_log[:train_stop], x_aug[i])
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

    mse_log_base = float(np.mean((forecasts["actual_log_rv"] - forecasts["baseline_pred_log"]) ** 2))
    mse_log_aug = float(np.mean((forecasts["actual_log_rv"] - forecasts["augmented_pred_log"]) ** 2))
    mean_base = float(np.mean(loss_base))
    mean_aug = float(np.mean(loss_aug))
    return {
        "horizon": horizon,
        "n_oos": int(len(forecasts)),
        "start_date": str(pd.Timestamp(forecasts["date"].min()).date()),
        "end_date": str(pd.Timestamp(forecasts["date"].max()).date()),
        "mean_qlike_baseline_vix_only": mean_base,
        "mean_qlike_augmented_vix_spf": mean_aug,
        "qlike_improvement_pct_augmented_vs_baseline": finite_float((mean_base - mean_aug) / mean_base * 100.0),
        "dm_t_augmented_vs_baseline": finite_float(dm_t),
        "dm_p_augmented_vs_baseline": finite_float(dm_p),
        "mse_log_baseline": mse_log_base,
        "mse_log_augmented": mse_log_aug,
        "mse_log_improvement_pct_augmented_vs_baseline": finite_float((mse_log_base - mse_log_aug) / mse_log_base * 100.0),
    }


def make_figure(df: pd.DataFrame, regime_summary: dict[str, dict[str, object]], oos: dict[str, dict[str, object]]) -> None:
    plot_sample = df.dropna(subset=["date", "vix_z", "disagreement_z"]).copy()
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))

    axes[0, 0].plot(plot_sample["date"], plot_sample["vix_z"], label="VIX z", lw=1.0)
    axes[0, 0].plot(plot_sample["date"], plot_sample["disagreement_z"], label="SPF disagreement z", lw=1.0)
    axes[0, 0].axhline(0, color="black", lw=0.8)
    axes[0, 0].set_title("Lagged signals (expanding z)")
    axes[0, 0].legend(loc="upper right", fontsize=8)

    order = [
        "high_uncertainty_low_disagreement",
        "high_uncertainty_high_disagreement",
        "low_uncertainty_low_disagreement",
        "low_uncertainty_high_disagreement",
    ]
    labels = ["High VIX / Low SPF", "High VIX / High SPF", "Low VIX / Low SPF", "Low VIX / High SPF"]
    vols = [
        regime_summary.get(key, {}).get("annualized_vol_from_mean_fwd_rv21", np.nan)
        for key in order
    ]
    tails = [regime_summary.get(key, {}).get("tail_event21_rate", np.nan) for key in order]
    axes[0, 1].bar(labels, vols, color=["#3b82f6", "#ef4444", "#94a3b8", "#f59e0b"])
    axes[0, 1].set_title("Forward 21d annualized vol by regime")
    axes[0, 1].tick_params(axis="x", rotation=25, labelsize=8)

    axes[1, 0].bar(labels, tails, color=["#3b82f6", "#ef4444", "#94a3b8", "#f59e0b"])
    axes[1, 0].set_title("Forward 21d drawdown <= -5% rate")
    axes[1, 0].tick_params(axis="x", rotation=25, labelsize=8)

    horizon_labels = []
    base_values = []
    aug_values = []
    for horizon in HORIZONS:
        key = f"h{horizon}"
        horizon_labels.append(f"{horizon}d")
        base_values.append(oos[key].get("mean_qlike_baseline_vix_only", np.nan))
        aug_values.append(oos[key].get("mean_qlike_augmented_vix_spf", np.nan))
    x = np.arange(len(horizon_labels))
    width = 0.35
    axes[1, 1].bar(x - width / 2, base_values, width, label="VIX baseline", color="#64748b")
    axes[1, 1].bar(x + width / 2, aug_values, width, label="VIX+SPF", color="#0f766e")
    axes[1, 1].set_xticks(x, horizon_labels)
    axes[1, 1].set_title("OOS QLIKE")
    axes[1, 1].legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=150)
    plt.close(fig)


def classify_verdict(results: dict[str, object]) -> dict[str, object]:
    oos = results["oos_forecast"]
    regressions = results["in_sample_hac_regressions"]
    assert isinstance(oos, dict) and isinstance(regressions, dict)
    supportive_horizons: list[int] = []
    weak_horizons: list[int] = []
    for horizon in HORIZONS:
        oos_h = oos[f"h{horizon}"]
        reg_h = regressions[f"h{horizon}"]
        assert isinstance(oos_h, dict) and isinstance(reg_h, dict)
        aug = reg_h["augmented_vix_spf"]
        assert isinstance(aug, dict)
        tvalues = aug["tvalues_hac"]
        assert isinstance(tvalues, dict)
        spf_t = abs(float(tvalues.get("disagreement_z") or 0.0))
        inter_t = abs(float(tvalues.get("vix_x_disagreement") or 0.0))
        improvement = float(oos_h.get("qlike_improvement_pct_augmented_vs_baseline") or 0.0)
        dm_t = float(oos_h.get("dm_t_augmented_vs_baseline") or 0.0)
        if improvement > 0.0 and dm_t < -3.0 and max(spf_t, inter_t) > 3.0:
            supportive_horizons.append(horizon)
        elif improvement > 0.0 or max(spf_t, inter_t) > 2.0:
            weak_horizons.append(horizon)

    regime_21 = results["agreed_vs_disagreed_tests"]["fwd_rv21"]
    assert isinstance(regime_21, dict)
    regime_diff = regime_21.get("observed_diff_agreed_minus_disagreed")
    regime_p = regime_21.get("p_one_sided_agreed_greater")
    regime_support = (
        regime_diff is not None
        and regime_p is not None
        and float(regime_diff) > 0.0
        and float(regime_p) < 0.05
    )

    if supportive_horizons:
        label = "SUPPORTIVE"
        reason = "VIX+SPF improves OOS QLIKE with DM |t|>3 and HAC SPF term support."
    elif regime_support and weak_horizons:
        label = "WEAK_RAW_ONLY"
        reason = "Regime contrast is positive, but formal incremental forecast gates are not all met."
    else:
        label = "NULL"
        reason = "SPF disagreement does not clear the incremental VIX forecast gate, and regime evidence is insufficient or opposite."
    return {
        "label": label,
        "supportive_horizons": supportive_horizons,
        "weak_horizons": weak_horizons,
        "regime_support_21d": bool(regime_support),
        "reason": reason,
    }


def run() -> dict[str, object]:
    ensure_dirs()
    spf = load_spf_disagreement()
    daily = load_daily_spy_vix()
    df = merge_daily_features(daily, spf)

    regime_summary = summarize_regimes(df)
    agreed_tests = {
        "fwd_rv5": bootstrap_regime_difference(df, "fwd_rv5"),
        "fwd_rv21": bootstrap_regime_difference(df, "fwd_rv21"),
        "tail_event21": bootstrap_regime_difference(df, "tail_event21"),
        "fwd_drawdown21": bootstrap_regime_difference(df, "fwd_drawdown21"),
    }
    regressions = {f"h{horizon}": fit_hac_models(df, horizon) for horizon in HORIZONS}
    oos = {f"h{horizon}": expanding_oos(df, horizon) for horizon in HORIZONS}

    results: dict[str, object] = {
        "experiment_id": EXPERIMENT_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data": {
            "spy_vix_source": str(SPY_VIX_PATH.relative_to(ROOT)),
            "spf_source": str(SPF_D2_PATH.relative_to(ROOT)),
            "spf_url": SPF_D2_URL,
            "daily_rows_raw": int(len(daily)),
            "daily_date_start": str(daily["date"].min().date()),
            "daily_date_end": str(daily["date"].max().date()),
            "spf_quarterly_rows": int(len(spf)),
            "spf_quarter_start": str(spf["survey_quarter"].iloc[0]),
            "spf_quarter_end": str(spf["survey_quarter"].iloc[-1]),
            "regression_rows_h5": int(regressions["h5"]["n"]),
            "regression_rows_h21": int(regressions["h21"]["n"]),
        },
        "method": {
            "uncertainty_level": "VIX close, shifted by one trading day, then expanding z-score.",
            "disagreement_proxy": "Philly Fed SPF D2(T+4) IQR composite: mean(log1p(RGDP), log1p(PGDP)).",
            "spf_availability_lag": "Survey quarter end + 45 calendar days, daily forward-fill, then signal.shift(1).",
            "regime_rule": "High uncertainty/disagreement means expanding z-score > 0.",
            "targets": "Forward 5d/21d SPY close-to-close realized variance and forward 21d max drawdown <= -5%.",
            "oos_training_guard": "For horizon h, an OOS row i trains only on rows j <= i-h, so overlapping targets are fully observed.",
            "formal_gate": "Support requires OOS QLIKE improvement with DM t < -3 and HAC SPF/disagreement term |t| > 3.",
        },
        "regime_summary": regime_summary,
        "agreed_vs_disagreed_tests": agreed_tests,
        "in_sample_hac_regressions": regressions,
        "oos_forecast": oos,
        "figure": str(FIG_PATH.relative_to(ROOT)),
    }
    results["verdict"] = classify_verdict(results)

    make_figure(df, regime_summary, oos)
    RESULTS_PATH.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    return results


if __name__ == "__main__":
    out = run()
    print(json.dumps(out["verdict"], indent=2, sort_keys=True))
