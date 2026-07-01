"""K1601: Agreed vs disagreed uncertainty and SPY forward volatility.

Research question
-----------------
Does forecast-disagreement information help identify high-uncertainty regimes
that forecast SPY forward realized volatility or left-tail risk beyond VIX?

Design
------
The experiment adapts the "agreed vs disagreed uncertainty" distinction to a
market-volatility setting:

* uncertainty level: VIX daily close (primary), JLN 3-month macro uncertainty
  from FRED (secondary).
* disagreement: Philadelphia Fed SPF cross-sectional forecast dispersion for
  RGDP quarter-over-quarter growth, measure D2, horizon T+1.
* target: next 21 trading days of SPY close-to-close realized variance and
  left-tail loss.

Lookahead controls
------------------
All predictors used at row t are explicitly shifted by one trading day after
daily alignment. SPF data are conservatively treated as known only at the first
day of the next quarter. JLN monthly data are conservatively treated as known
only after a two-month lag. Rolling regime thresholds use prior predictor
history only via series.shift(1).rolling(...).

For expanding OOS forecasts, target rows are forward 21-day windows. Training
therefore uses only rows with target_end_pos < forecast_pos; this avoids the
common overlapping-target leak where row pos-1 contains returns after pos.
"""

from __future__ import annotations

import io
import json
import math
import re
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import yfinance as yf


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from volpred.stats.mcs import model_confidence_set
from volpred.stats.model_evaluation import dm_test, qlike_pointwise


EXP_DIR = Path(__file__).resolve().parent
DATA_DIR = EXP_DIR / "data"
FIG_DIR = EXP_DIR / "figures"
DATA_DIR.mkdir(parents=True, exist_ok=True)
FIG_DIR.mkdir(parents=True, exist_ok=True)

SEED = 42
EPS = 1e-12
HORIZON = 21
MIN_TRAIN = 1000
ROLLING_THRESHOLD_WINDOW = 756
ROLLING_THRESHOLD_MIN = 252
N_BOOT = 1000
MCS_BOOT = 1000
MCS_ALPHA = 0.10
START = "1990-01-01"
END = "2026-07-01"

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
SPF_DISPERSION_2_URL = (
    "https://www.philadelphiafed.org/-/media/FRBP/Assets/Surveys-And-Data/"
    "survey-of-professional-forecasters/historical-data/Dispersion_2.xlsx"
    "?sc_lang=en&hash=E0A0D114F37EC56209ECB512CA07FA84"
)


@dataclass(frozen=True)
class RegressionResult:
    beta: float
    se: float
    t: float
    p: float
    n: int
    r2: float
    hac_lag: int


def _download_bytes(url: str, cache_path: Path) -> bytes:
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return cache_path.read_bytes()
    headers = {"User-Agent": "volpred-research/1.0"}
    response = requests.get(url, headers=headers, timeout=60)
    response.raise_for_status()
    cache_path.write_bytes(response.content)
    return response.content


def load_fred_series(series_id: str) -> pd.Series:
    cache_path = DATA_DIR / f"fred_{series_id}.csv"
    if cache_path.exists() and cache_path.stat().st_size > 0:
        frame = pd.read_csv(cache_path)
    else:
        url = FRED_CSV.format(series_id=series_id)
        frame = pd.read_csv(url)
        frame.to_csv(cache_path, index=False)
    frame["observation_date"] = pd.to_datetime(frame["observation_date"])
    frame[series_id] = pd.to_numeric(frame[series_id], errors="coerce")
    out = frame.set_index("observation_date")[series_id].sort_index()
    out.name = series_id
    return out.dropna()


def load_spy_close() -> pd.Series:
    cache_path = DATA_DIR / "spy_close_yfinance.csv"
    if cache_path.exists() and cache_path.stat().st_size > 0:
        frame = pd.read_csv(cache_path, parse_dates=["Date"]).set_index("Date")
        close = frame["SPY"].astype(float)
        close.name = "SPY"
        return close.dropna()

    raw = yf.download("SPY", start=START, end=END, progress=False, auto_adjust=True)
    if raw.empty:
        raise RuntimeError("yfinance returned no SPY data")
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]["SPY"].astype(float)
    else:
        close = raw["Close"].astype(float)
    close.name = "SPY"
    close.to_frame().to_csv(cache_path, index_label="Date")
    return close.dropna()


def _xlsx_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for item in root.findall(ns + "si"):
        strings.append("".join(node.text or "" for node in item.iter(ns + "t")))
    return strings


def _xlsx_sheet_path(zf: zipfile.ZipFile, sheet_name: str) -> str:
    main_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    relmap = {node.attrib["Id"]: node.attrib["Target"] for node in rels}
    for sheet in wb.find(f"{{{main_ns}}}sheets"):
        if sheet.attrib.get("name") == sheet_name:
            rel_id = sheet.attrib[f"{{{rel_ns}}}id"]
            target = relmap[rel_id]
            return "xl/" + target if not target.startswith("xl/") else target
    raise KeyError(f"sheet not found: {sheet_name}")


def _xlsx_col_number(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    out = 0
    for ch in letters:
        out = out * 26 + ord(ch.upper()) - 64
    return out


def _xlsx_cell_value(cell: ET.Element, shared_strings: list[str]) -> str | None:
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    cell_type = cell.attrib.get("t")
    value_node = cell.find(ns + "v")
    if value_node is None:
        inline_node = cell.find(ns + "is")
        if inline_node is None:
            return None
        return "".join(node.text or "" for node in inline_node.iter(ns + "t"))
    text = value_node.text
    if text is None:
        return None
    if cell_type == "s":
        return shared_strings[int(text)]
    return text


def parse_spf_rgdp_dispersion_t1() -> pd.DataFrame:
    """Parse Philadelphia Fed SPF Dispersion_2.xlsx without pandas/openpyxl.

    The host environment currently has an old openpyxl version, so the parser
    reads the XLSX XML directly. We use RGDP_D2(T+1): 75th minus 25th percentile
    of professional forecasts for next-quarter RGDP Q/Q growth.
    """
    cache_path = DATA_DIR / "spf_Dispersion_2.xlsx"
    content = _download_bytes(SPF_DISPERSION_2_URL, cache_path)
    zf = zipfile.ZipFile(io.BytesIO(content))
    shared = _xlsx_shared_strings(zf)
    sheet_path = _xlsx_sheet_path(zf, "RGDP")
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    root = ET.fromstring(zf.read(sheet_path))

    rows: list[dict[int, str | None]] = []
    for row in root.find(ns + "sheetData").findall(ns + "row"):
        parsed = {
            _xlsx_col_number(cell.attrib["r"]): _xlsx_cell_value(cell, shared)
            for cell in row.findall(ns + "c")
        }
        rows.append(parsed)

    header_row = None
    for row in rows:
        if row.get(1) == "Survey_Date(T)":
            header_row = row
            break
    if header_row is None:
        raise RuntimeError("SPF RGDP header row not found")
    headers = {idx: name for idx, name in header_row.items() if name}
    wanted_col = next(idx for idx, name in headers.items() if name == "RGDP_D2(T+1)")

    out_rows: list[dict[str, object]] = []
    survey_pattern = re.compile(r"^(\d{4})Q([1-4])$")
    for row in rows:
        label = row.get(1)
        if not label or not survey_pattern.match(str(label)):
            continue
        match = survey_pattern.match(str(label))
        year = int(match.group(1))
        quarter = int(match.group(2))
        value = pd.to_numeric(row.get(wanted_col), errors="coerce")
        if not np.isfinite(value):
            continue
        q_start = pd.Timestamp(year=year, month=3 * (quarter - 1) + 1, day=1)
        known_from = q_start + pd.DateOffset(months=3)
        out_rows.append(
            {
                "survey": label,
                "survey_quarter_start": q_start,
                "known_from": known_from,
                "spf_rgdp_d2_t1": float(value),
            }
        )
    out = pd.DataFrame(out_rows).sort_values("known_from").reset_index(drop=True)
    out.to_csv(DATA_DIR / "spf_rgdp_d2_t1_parsed.csv", index=False)
    return out


def daily_from_known_values(values: pd.Series, known_from: pd.Series, trading_index: pd.DatetimeIndex) -> pd.Series:
    known = pd.DataFrame({"known_from": pd.to_datetime(known_from), "value": values.astype(float)})
    known = known.dropna().sort_values("known_from")
    daily = pd.Series(index=trading_index, dtype=float)
    cursor = 0
    last = np.nan
    records = known.to_dict("records")
    for date in trading_index:
        while cursor < len(records) and records[cursor]["known_from"] <= date:
            last = float(records[cursor]["value"])
            cursor += 1
        daily.loc[date] = last
    return daily


def forward_sum(series: pd.Series, horizon: int) -> pd.Series:
    parts = [series.shift(-i) for i in range(1, horizon + 1)]
    return pd.concat(parts, axis=1).sum(axis=1, min_count=horizon)


def forward_min(series: pd.Series, horizon: int) -> pd.Series:
    parts = [series.shift(-i) for i in range(1, horizon + 1)]
    return pd.concat(parts, axis=1).min(axis=1)


def trailing_threshold(series: pd.Series, quantile: float) -> pd.Series:
    return series.shift(1).rolling(
        ROLLING_THRESHOLD_WINDOW, min_periods=ROLLING_THRESHOLD_MIN
    ).quantile(quantile)


def build_panel() -> pd.DataFrame:
    close = load_spy_close()
    trading_index = close.index
    ret = np.log(close / close.shift(1))
    target_rv = forward_sum(ret * ret, HORIZON)
    target_min_ret = forward_min(ret, HORIZON)
    target_tail_loss = (-target_min_ret).clip(lower=0.0)

    vix = load_fred_series("VIXCLS").reindex(trading_index).ffill()
    jln_raw = load_fred_series("JLNUM3M")
    jln_known_from = jln_raw.index + pd.DateOffset(months=2)
    jln_daily = daily_from_known_values(jln_raw, pd.Series(jln_known_from, index=jln_raw.index), trading_index)

    spf = parse_spf_rgdp_dispersion_t1()
    spf_daily = daily_from_known_values(spf["spf_rgdp_d2_t1"], spf["known_from"], trading_index)

    panel = pd.DataFrame(
        {
            "date": trading_index,
            "spy_close": close,
            "ret": ret,
            "target_rv_21": target_rv,
            "target_vol_ann_21": np.sqrt((target_rv / HORIZON) * 252.0),
            "target_min_ret_21": target_min_ret,
            "target_tail_loss_21": target_tail_loss,
            "vix": vix,
            "jln3m": jln_daily,
            "spf_disp": spf_daily,
        },
        index=trading_index,
    )

    for col in ["vix", "jln3m", "spf_disp"]:
        panel[f"{col}_lag1"] = panel[col].shift(1)
        panel[f"log_{col}_lag1"] = np.log(panel[f"{col}_lag1"].clip(lower=EPS))

    panel["vix_q75"] = trailing_threshold(panel["log_vix_lag1"], 0.75)
    panel["jln_q75"] = trailing_threshold(panel["log_jln3m_lag1"], 0.75)
    panel["spf_median"] = trailing_threshold(panel["log_spf_disp_lag1"], 0.50)
    panel["vix_high"] = panel["log_vix_lag1"] >= panel["vix_q75"]
    panel["jln_high"] = panel["log_jln3m_lag1"] >= panel["jln_q75"]
    panel["spf_high"] = panel["log_spf_disp_lag1"] >= panel["spf_median"]
    panel["agreed_vix"] = panel["vix_high"] & (~panel["spf_high"])
    panel["disagreed_vix"] = panel["vix_high"] & panel["spf_high"]
    panel["agreed_jln"] = panel["jln_high"] & (~panel["spf_high"])
    panel["disagreed_jln"] = panel["jln_high"] & panel["spf_high"]

    panel = panel.reset_index(drop=True)
    panel["position"] = np.arange(len(panel), dtype=int)
    panel["target_end_pos"] = panel["position"] + HORIZON
    panel = panel.dropna(
        subset=[
            "target_rv_21",
            "target_tail_loss_21",
            "log_vix_lag1",
            "log_jln3m_lag1",
            "log_spf_disp_lag1",
            "vix_q75",
            "jln_q75",
            "spf_median",
        ]
    ).reset_index(drop=True)
    panel.to_csv(DATA_DIR / "k1601_panel.csv", index=False)
    return panel


def _normal_p_from_t(t_value: float) -> float:
    # Avoid importing scipy.stats in tiny helper; erf is enough for large-N HAC.
    return float(2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t_value) / math.sqrt(2.0)))))


def ols_hac(y: np.ndarray, x: np.ndarray, hac_lag: int) -> RegressionResult:
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    valid = np.isfinite(y)
    if x.ndim == 1:
        x = x.reshape(-1, 1)
    valid &= np.isfinite(x).all(axis=1)
    y = y[valid]
    x = x[valid]
    n = len(y)
    xmat = np.column_stack([np.ones(n), x])
    beta, *_ = np.linalg.lstsq(xmat, y, rcond=None)
    resid = y - xmat @ beta
    xtx_inv = np.linalg.inv(xmat.T @ xmat)
    xu = xmat * resid.reshape(-1, 1)
    s_mat = xu.T @ xu
    for lag in range(1, hac_lag + 1):
        weight = 1.0 - lag / (hac_lag + 1.0)
        gamma = xu[lag:].T @ xu[:-lag]
        s_mat += weight * (gamma + gamma.T)
    cov = xtx_inv @ s_mat @ xtx_inv
    se = np.sqrt(np.maximum(np.diag(cov), 0.0))
    t_stats = beta / np.where(se > 0, se, np.nan)
    fitted = xmat @ beta
    ss_res = float(np.sum((y - fitted) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return RegressionResult(
        beta=float(beta[-1]),
        se=float(se[-1]),
        t=float(t_stats[-1]),
        p=_normal_p_from_t(float(t_stats[-1])),
        n=int(n),
        r2=float(1.0 - ss_res / ss_tot) if ss_tot > 0 else float("nan"),
        hac_lag=int(hac_lag),
    )


def block_bootstrap_group_diff(frame: pd.DataFrame, value_col: str, flag_col: str) -> dict:
    rng = np.random.default_rng(SEED)
    ordered = frame[[value_col, flag_col]].dropna().reset_index(drop=True)
    n = len(ordered)
    observed = (
        ordered.loc[ordered[flag_col], value_col].mean()
        - ordered.loc[~ordered[flag_col], value_col].mean()
    )
    draws: list[float] = []
    for _ in range(N_BOOT):
        idx: list[int] = []
        while len(idx) < n:
            start = int(rng.integers(0, n))
            idx.extend((start + k) % n for k in range(HORIZON))
        sample = ordered.iloc[idx[:n]]
        if sample[flag_col].sum() == 0 or (~sample[flag_col]).sum() == 0:
            continue
        draws.append(
            float(
                sample.loc[sample[flag_col], value_col].mean()
                - sample.loc[~sample[flag_col], value_col].mean()
            )
        )
    arr = np.asarray(draws, dtype=float)
    p_gt_0 = float(np.mean(arr > 0.0)) if len(arr) else float("nan")
    return {
        "observed_diff": float(observed),
        "ci95": [float(np.quantile(arr, 0.025)), float(np.quantile(arr, 0.975))],
        "p_two_sided": float(2.0 * min(p_gt_0, 1.0 - p_gt_0)) if len(arr) else float("nan"),
        "n_boot": int(len(arr)),
        "block_len": HORIZON,
        "seed": SEED,
    }


def regime_comparison(panel: pd.DataFrame, prefix: str) -> dict:
    high_col = f"{prefix}_high"
    agreed_col = f"agreed_{prefix}"
    sub = panel[panel[high_col]].copy()
    sub["low_disagreement"] = ~sub["spf_high"]
    out: dict[str, object] = {
        "n_high_uncertainty": int(len(sub)),
        "n_agreed_high_uncertainty": int(sub["low_disagreement"].sum()),
        "n_disagreed_high_uncertainty": int((~sub["low_disagreement"]).sum()),
    }
    for target_col in ["target_vol_ann_21", "target_tail_loss_21"]:
        y = sub[target_col].to_numpy(dtype=float)
        flag = sub["low_disagreement"].astype(float).to_numpy()
        reg = ols_hac(y, flag, HORIZON)
        boot = block_bootstrap_group_diff(sub, target_col, "low_disagreement")
        out[target_col] = {
            "agreed_mean": float(sub.loc[sub["low_disagreement"], target_col].mean()),
            "disagreed_mean": float(sub.loc[~sub["low_disagreement"], target_col].mean()),
            "agreed_minus_disagreed": float(
                sub.loc[sub["low_disagreement"], target_col].mean()
                - sub.loc[~sub["low_disagreement"], target_col].mean()
            ),
            "hac_t": reg.t,
            "hac_p": reg.p,
            "hac_lag": HORIZON,
            "block_bootstrap": boot,
        }
    return out


MODEL_FEATURES = {
    "VIX": ["log_vix_lag1"],
    "VIX_SPF": ["log_vix_lag1", "log_spf_disp_lag1"],
    "VIX_SPF_JLN": ["log_vix_lag1", "log_spf_disp_lag1", "log_jln3m_lag1"],
    "JLN_SPF": ["log_jln3m_lag1", "log_spf_disp_lag1"],
}


def fit_predict_log_ols(train: pd.DataFrame, test: pd.DataFrame, cols: list[str]) -> float:
    x_train = train[cols].to_numpy(dtype=float)
    y_train = np.log(train["target_rv_21"].clip(lower=EPS).to_numpy(dtype=float))
    x_train = np.column_stack([np.ones(len(x_train)), x_train])
    beta, *_ = np.linalg.lstsq(x_train, y_train, rcond=None)
    resid = y_train - x_train @ beta
    denom = max(len(resid) - len(beta), 1)
    resid_var = float(np.sum(resid * resid) / denom)

    x_test = test[cols].to_numpy(dtype=float)
    x_test = np.column_stack([np.ones(len(x_test)), x_test])
    pred_log = float(x_test[0] @ beta)
    return max(float(math.exp(pred_log + 0.5 * max(resid_var, 0.0))), EPS)


def expanding_oos(panel: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for _, test_row in panel.iterrows():
        forecast_pos = int(test_row["position"])
        train_pool = panel[panel["target_end_pos"] < forecast_pos]
        if len(train_pool) < MIN_TRAIN:
            continue
        test = test_row.to_frame().T
        row: dict[str, object] = {
            "date": str(pd.Timestamp(test_row["date"]).date()),
            "position": forecast_pos,
            "actual_rv_21": float(test_row["target_rv_21"]),
            "train_n": int(len(train_pool)),
            "latest_train_target_end_pos": int(train_pool["target_end_pos"].max()),
        }
        for name, cols in MODEL_FEATURES.items():
            row[f"{name}_forecast"] = fit_predict_log_ols(train_pool, test, cols)
        rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(DATA_DIR / "k1601_oos_forecasts.csv", index=False)
    return out


def evaluate_oos(forecasts: pd.DataFrame) -> dict:
    actual = forecasts["actual_rv_21"].to_numpy(dtype=float)
    losses: dict[str, np.ndarray] = {}
    models: dict[str, dict[str, float]] = {}
    for name in MODEL_FEATURES:
        pred = forecasts[f"{name}_forecast"].to_numpy(dtype=float)
        loss = qlike_pointwise(actual, pred)
        losses[name] = loss
        models[name] = {
            "qlike": float(np.mean(loss)),
            "mse": float(np.mean((actual - pred) ** 2)),
            "mean_forecast_rv": float(np.mean(pred)),
        }

    pairwise: dict[str, dict[str, object]] = {}
    base_loss = losses["VIX"]
    for name in MODEL_FEATURES:
        if name == "VIX":
            continue
        t_stat, p_val = dm_test(losses[name], base_loss, h=HORIZON)
        improvement = (models["VIX"]["qlike"] - models[name]["qlike"]) / abs(models["VIX"]["qlike"])
        pairwise[name] = {
            "dm_t_model_minus_vix": float(t_stat),
            "dm_p": float(p_val),
            "qlike_improvement_pct": float(improvement * 100.0),
            "harvey_pass_model_better": bool(t_stat < -3.0 and improvement > 0.0),
            "interpretation": "negative DM t means candidate has lower QLIKE than VIX baseline",
        }

    mcs_raw = model_confidence_set(losses, alpha=MCS_ALPHA, n_boot=MCS_BOOT, seed=SEED)
    return {
        "n_oos": int(len(forecasts)),
        "first_oos_date": str(forecasts["date"].iloc[0]) if len(forecasts) else None,
        "last_oos_date": str(forecasts["date"].iloc[-1]) if len(forecasts) else None,
        "models": models,
        "pairwise_vs_vix": pairwise,
        "mcs": {
            "members": list(mcs_raw.get("mcs_models", [])),
            "eliminated": mcs_raw.get("eliminated", []),
            "p_values": mcs_raw.get("p_values", {}),
            "alpha": MCS_ALPHA,
            "n_boot": MCS_BOOT,
            "seed": SEED,
            "method": "HLN2011_stationary_bootstrap",
        },
    }


def make_figures(panel: pd.DataFrame, oos_eval: dict) -> list[str]:
    paths: list[str] = []

    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    means = []
    labels = []
    for prefix, title in [("vix", "VIX high"), ("jln", "JLN high")]:
        sub = panel[panel[f"{prefix}_high"]].copy()
        means.extend(
            [
                sub.loc[~sub["spf_high"], "target_vol_ann_21"].mean(),
                sub.loc[sub["spf_high"], "target_vol_ann_21"].mean(),
            ]
        )
        labels.extend([f"{title}\nlow SPF disp", f"{title}\nhigh SPF disp"])
    ax.bar(range(len(means)), means, color=["#4C78A8", "#F58518", "#4C78A8", "#F58518"])
    ax.set_xticks(range(len(means)))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("Next 21d annualized realized vol")
    ax.set_title("K1601 agreed vs disagreed uncertainty regimes")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    path = FIG_DIR / "k1601_regime_forward_vol.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path.relative_to(ROOT)))

    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    names = [name for name in MODEL_FEATURES if name != "VIX"]
    vals = [oos_eval["pairwise_vs_vix"][name]["qlike_improvement_pct"] for name in names]
    ax.bar(names, vals, color=["#54A24B", "#B279A2", "#E45756"])
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.set_ylabel("QLIKE improvement vs VIX baseline (%)")
    ax.set_title("K1601 expanding OOS forecast comparison")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    path = FIG_DIR / "k1601_oos_qlike_improvement.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path.relative_to(ROOT)))

    return paths


def determine_verdict(oos_eval: dict, regime_results: dict) -> tuple[str, str]:
    augmented_passes = [
        name
        for name, stats in oos_eval["pairwise_vs_vix"].items()
        if stats["harvey_pass_model_better"] and name in set(oos_eval["mcs"]["members"])
    ]
    if augmented_passes:
        return (
            "PASS",
            "At least one SPF-disagreement augmented model beats the VIX baseline by QLIKE, passes Harvey t<-3, and remains in MCS.",
        )

    directional = [
        name
        for name, stats in oos_eval["pairwise_vs_vix"].items()
        if stats["qlike_improvement_pct"] > 0
    ]
    vix_agreed_t = regime_results["vix"]["target_vol_ann_21"]["hac_t"]
    if directional or abs(vix_agreed_t) >= 2.0:
        return (
            "DIRECTIONAL_ONLY",
            "Some regime or OOS statistics have a suggestive sign, but no SPF-disagreement augmented model passes the Harvey/MCS forecast gate.",
        )
    return (
        "NULL",
        "SPF forecast disagreement does not provide statistically defensible incremental SPY forward-volatility information beyond VIX in this design.",
    )


def main() -> dict:
    np.random.seed(SEED)
    started_at = datetime.now(timezone.utc).isoformat()
    panel = build_panel()
    regime_results = {
        "vix": regime_comparison(panel, "vix"),
        "jln": regime_comparison(panel, "jln"),
    }

    y = np.log(panel["target_rv_21"].clip(lower=EPS).to_numpy(dtype=float))
    vix_reg = ols_hac(y, panel[["log_vix_lag1"]].to_numpy(dtype=float), HORIZON)
    vix_spf_reg = ols_hac(
        y,
        panel[["log_vix_lag1", "log_spf_disp_lag1"]].to_numpy(dtype=float),
        HORIZON,
    )
    vix_spf_jln_reg = ols_hac(
        y,
        panel[["log_vix_lag1", "log_jln3m_lag1", "log_spf_disp_lag1"]].to_numpy(dtype=float),
        HORIZON,
    )

    forecasts = expanding_oos(panel)
    oos_eval = evaluate_oos(forecasts)
    verdict, summary = determine_verdict(oos_eval, regime_results)
    figures = make_figures(panel, oos_eval)

    results = {
        "experiment_id": "K1601",
        "title": "Agreed vs disagreed uncertainty regimes for SPY forward volatility",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "summary": summary,
        "research_question": "Does SPF forecast disagreement identify high-uncertainty regimes or improve SPY forward realized-volatility forecasts beyond VIX?",
        "data": {
            "spy": {
                "source": "yfinance SPY adjusted close",
                "date_range": [str(pd.Timestamp(panel["date"].min()).date()), str(pd.Timestamp(panel["date"].max()).date())],
            },
            "vix": "FRED VIXCLS daily close; aligned to SPY trading days and shifted one trading day.",
            "jln": "FRED JLNUM3M monthly macro uncertainty; treated as known after a conservative two-month lag, then shifted one trading day.",
            "spf": "Philadelphia Fed SPF Dispersion_2.xlsx, RGDP_D2(T+1), 75th-25th percentile dispersion for next-quarter RGDP growth; treated as known at next-quarter start, then shifted one trading day.",
            "panel_rows": int(len(panel)),
            "panel_file": "experiments/k1601/data/k1601_panel.csv",
            "oos_forecast_file": "experiments/k1601/data/k1601_oos_forecasts.csv",
        },
        "timing": {
            "feature_lag": "All daily-aligned predictors use explicit .shift(1).",
            "regime_thresholds": "Rolling thresholds use series.shift(1).rolling(window=756, min_periods=252), so threshold history excludes the current row.",
            "target": "target_rv_21 at row t is sum of squared SPY log returns from t+1 through t+21.",
            "oos_cutoff": "Expanding OOS train rows satisfy target_end_pos < forecast_pos, preventing overlapping-forward-target leakage.",
            "horizon": HORIZON,
        },
        "literature": [
            {
                "citation": "Gambetti, Korobilis, Tsoukalas and Zanetti (2023/2025), Agreed and Disagreed Uncertainty",
                "url": "https://arxiv.org/abs/2302.01621",
                "use": "Motivates distinguishing high-uncertainty/low-disagreement from high-uncertainty/high-disagreement states.",
            },
            {
                "citation": "Jurado, Ludvigson and Ng (2015), Measuring Uncertainty",
                "url": "https://www.aeaweb.org/articles?id=10.1257/aer.20131193",
                "use": "Motivates macro uncertainty as forecast-error variance and FRED JLNUM3M proxy.",
            },
            {
                "citation": "Lahiri and Sheng (2010), Measuring Forecast Uncertainty by Disagreement",
                "url": "https://doi.org/10.1002/jae.1167",
                "use": "Motivates forecast disagreement as an imperfect but informative uncertainty-related proxy.",
            },
            {
                "citation": "Federal Reserve Bank of Philadelphia, SPF cross-sectional forecast dispersion data",
                "url": "https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/dispersion-forecasts",
                "use": "Primary disagreement data source.",
            },
        ],
        "regime_results": regime_results,
        "full_sample_predictive_regressions": {
            "log_rv_on_log_vix": vix_reg.__dict__,
            "log_rv_on_log_vix_plus_log_spf": vix_spf_reg.__dict__,
            "log_rv_on_log_vix_log_jln_plus_log_spf": vix_spf_jln_reg.__dict__,
            "note": "Reported for sign diagnostics only; expanding OOS is the forecast gate.",
        },
        "oos": oos_eval,
        "figures": figures,
        "limitations": [
            "SPF RGDP dispersion is quarterly and macro-focused, not the consumer-disagreement measure used in Gambetti et al.; this is a free-data market-volatility adaptation.",
            "FRED JLN values are revision-corrected, not vintage ALFRED data. A conservative release lag is used, but this remains a pilot rather than a real-time macro data study.",
            "Targets are overlapping 21-trading-day realized-variance windows; HAC lag and OOS target_end_pos cutoff mitigate but do not eliminate power limitations.",
            "The experiment tests SPY only. It challenges the within-market VIX sufficiency line only for this SPF-disagreement proxy.",
        ],
    }
    out_path = EXP_DIR / "K1601_results.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    print(f"[done] {results['experiment_id']} verdict={verdict}")
    print(f"[done] wrote {out_path}")
    return results


if __name__ == "__main__":
    main()
