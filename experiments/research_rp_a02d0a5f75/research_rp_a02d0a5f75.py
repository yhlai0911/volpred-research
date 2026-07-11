#!/usr/bin/env python3
"""Fixed-calibration OOS audit of volatility-managed equity factors.

Data sources
------------
* Kenneth R. French Data Library daily FF5 and Momentum factor files.
* AQR Quality Minus Junk daily factor workbook, USA column.

The experiment is empirical and descriptive/predictive, not causal.  The
transaction-cost layer only charges changes in factor-level exposure and is a
lower bound; constituent-level trading costs cannot be recovered from factor
return series.

Timing convention
-----------------
Daily returns in calendar month t produce RV_t.  Exposure in month t+1 uses
``inverse_variance.shift(1)``.  The normalisation constant and leverage cap
are fixed using data no later than 1999-12-31.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
import statsmodels.api as sm
from statsmodels.stats.diagnostic import het_arch


SEED = 42
N_BOOT = 2_000
BOOT_MEAN_BLOCK = 12
CALIBRATION_END = pd.Period("1999-12", freq="M")
OOS_START = pd.Period("2000-01", freq="M")
LEVERAGE_CAP = 3.0
COST_BPS = (0, 10, 25, 50)
PRIMARY_VARIANT = "capped_3x"
PRIMARY_COST_BPS = 25
FACTORS = ("SMB", "HML", "MOM", "QMJ")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RESULTS_PATH = BASE_DIR / "research_rp_a02d0a5f75_results.json"
PANEL_PATH = BASE_DIR / "analysis_panel.csv"
SUMMARY_PATH = BASE_DIR / "summary_table.csv"

FF5_URL = (
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
    "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip"
)
MOM_URL = (
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
    "F-F_Momentum_Factor_daily_CSV.zip"
)
QMJ_URL = (
    "https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/"
    "Quality-Minus-Junk-Factors-Daily.xlsx"
)

REFERENCES = [
    {
        "authors": "Moreira and Muir",
        "year": 2017,
        "journal": "Journal of Finance",
        "doi": "10.1111/jofi.12513",
    },
    {
        "authors": "Cederburg, O'Doherty, Wang, and Yan",
        "year": 2020,
        "journal": "Journal of Financial Economics",
        "doi": "10.1016/j.jfineco.2020.04.015",
    },
    {
        "authors": "Barroso and Detzel",
        "year": 2021,
        "journal": "Journal of Financial Economics",
        "doi": "10.1016/j.jfineco.2020.11.006",
    },
    {
        "authors": "DeMiguel, Martin-Utrera, and Uppal",
        "year": 2024,
        "journal": "Journal of Finance",
        "doi": "10.1111/jofi.13395",
    },
    {
        "authors": "Asness, Frazzini, and Pedersen",
        "year": 2019,
        "journal": "Review of Accounting Studies",
        "doi": "10.1007/s11142-018-9470-2",
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_download(url: str, destination: Path) -> Path:
    """Download to a sibling .part then atomically replace destination."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "VolPred-research/1.0"})
    with urllib.request.urlopen(request, timeout=180) as response, tmp.open("wb") as out:
        shutil.copyfileobj(response, out)
        out.flush()
        os.fsync(out.fileno())
    if tmp.stat().st_size < 1_000:
        raise RuntimeError(f"Downloaded file is implausibly small: {tmp}")
    os.replace(tmp, destination)
    return destination


def resolve_data_file(env_name: str, cache_name: str, url: str) -> Path:
    override = os.environ.get(env_name)
    if override:
        path = Path(override).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"{env_name} does not point to a file: {path}")
        return path
    path = DATA_DIR / cache_name
    if not path.exists():
        atomic_download(url, path)
    return path


def parse_french_zip(path: Path, required_columns: tuple[str, ...]) -> pd.DataFrame:
    """Parse a Kenneth French daily CSV ZIP; source values are percentage points."""
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"Expected exactly one CSV in {path}, found {names}")
        text = archive.read(names[0]).decode("latin-1")

    lines = text.splitlines()
    header_idx = None
    for idx, line in enumerate(lines):
        normalized = [part.strip() for part in line.split(",")]
        if all(column in normalized for column in required_columns):
            header_idx = idx
            break
    if header_idx is None:
        raise ValueError(f"Could not locate {required_columns} header in {path}")

    reader = csv.reader(io.StringIO("\n".join(lines[header_idx:])))
    header = [cell.strip() for cell in next(reader)]
    rows: list[dict[str, Any]] = []
    for raw in reader:
        if not raw:
            continue
        date_text = raw[0].strip()
        if not re.fullmatch(r"\d{8}", date_text):
            break
        record: dict[str, Any] = {"date": pd.to_datetime(date_text, format="%Y%m%d")}
        for column in required_columns:
            value = float(raw[header.index(column)].strip())
            record[column] = np.nan if value <= -99.0 else value / 100.0
        rows.append(record)
    frame = pd.DataFrame(rows).set_index("date").sort_index()
    if frame.empty or not frame.index.is_unique:
        raise ValueError(f"Invalid French factor frame from {path}")
    return frame


_XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _cell_text(cell: ET.Element, shared_strings: list[str]) -> str:
    value = cell.find(_XLSX_NS + "v")
    if cell.attrib.get("t") == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(_XLSX_NS + "t"))
    if value is None or value.text is None:
        return ""
    if cell.attrib.get("t") == "s":
        return shared_strings[int(value.text)]
    return value.text


def parse_aqr_qmj_xlsx(path: Path) -> pd.Series:
    """Parse sheet1/`QMJ Factors` without an openpyxl dependency."""
    with zipfile.ZipFile(path) as archive:
        shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        shared = [
            "".join(node.text or "" for node in item.iter(_XLSX_NS + "t"))
            for item in shared_root.findall(_XLSX_NS + "si")
        ]
        usa_column: str | None = None
        observations: list[tuple[pd.Timestamp, float]] = []
        with archive.open("xl/worksheets/sheet1.xml") as sheet:
            for _, row in ET.iterparse(sheet, events=("end",)):
                if row.tag != _XLSX_NS + "row":
                    continue
                values: dict[str, str] = {}
                for cell in row.findall(_XLSX_NS + "c"):
                    reference = cell.attrib.get("r", "")
                    match = re.match(r"[A-Z]+", reference)
                    if match:
                        values[match.group()] = _cell_text(cell, shared).strip()
                if usa_column is None:
                    usa_matches = [col for col, text in values.items() if text == "USA"]
                    if usa_matches:
                        usa_column = usa_matches[0]
                elif values.get("A") and values.get(usa_column, ""):
                    try:
                        date = pd.to_datetime(values["A"], format="%m/%d/%Y")
                        observations.append((date, float(values[usa_column])))
                    except (TypeError, ValueError):
                        pass
                row.clear()
    if usa_column is None or len(observations) < 1_000:
        raise ValueError(f"Could not recover a valid USA QMJ series from {path}")
    series = pd.Series(
        [value for _, value in observations],
        index=pd.DatetimeIndex([date for date, _ in observations]),
        name="QMJ",
        dtype=float,
    ).sort_index()
    series = series[~series.index.duplicated(keep="last")]
    return series.replace([-99.99, -999.0], np.nan)


def annualized_metrics(returns: pd.Series) -> dict[str, float | int]:
    returns = returns.dropna().astype(float)
    if len(returns) < 12:
        return {"n_months": int(len(returns))}
    mean = float(returns.mean())
    volatility = float(returns.std(ddof=1))
    wealth = (1.0 + returns).cumprod()
    drawdown = wealth / wealth.cummax() - 1.0
    return {
        "n_months": int(len(returns)),
        "annual_return_arithmetic": mean * 12.0,
        "annual_volatility": volatility * np.sqrt(12.0),
        "sharpe_zero_rf": mean / volatility * np.sqrt(12.0) if volatility > 0 else np.nan,
        "max_drawdown": float(drawdown.min()),
        "skewness": float(stats.skew(returns, bias=False)),
        "excess_kurtosis": float(stats.kurtosis(returns, fisher=True, bias=False)),
    }


def stationary_bootstrap_indices(
    n: int, n_boot: int, mean_block: int, rng: np.random.Generator
) -> np.ndarray:
    """Politis-Romano stationary bootstrap indices."""
    probability = 1.0 / mean_block
    output = np.empty((n_boot, n), dtype=np.int32)
    for boot in range(n_boot):
        index = int(rng.integers(0, n))
        for position in range(n):
            if position == 0 or rng.random() < probability:
                index = int(rng.integers(0, n))
            else:
                index = (index + 1) % n
            output[boot, position] = index
    return output


def sharpe_ratio(values: np.ndarray) -> float:
    std = float(np.std(values, ddof=1))
    return float(np.mean(values) / std * np.sqrt(12.0)) if std > 0 else np.nan


def paired_sharpe_bootstrap(
    managed: pd.Series, unmanaged: pd.Series, seed_offset: int
) -> dict[str, float | int]:
    aligned = pd.concat([managed.rename("managed"), unmanaged.rename("unmanaged")], axis=1).dropna()
    managed_values = aligned["managed"].to_numpy(float)
    unmanaged_values = aligned["unmanaged"].to_numpy(float)
    rng = np.random.default_rng(SEED + seed_offset)
    indices = stationary_bootstrap_indices(
        len(aligned), N_BOOT, BOOT_MEAN_BLOCK, rng
    )
    differences = np.empty(N_BOOT, dtype=float)
    for boot, sample in enumerate(indices):
        differences[boot] = sharpe_ratio(managed_values[sample]) - sharpe_ratio(
            unmanaged_values[sample]
        )
    observed = sharpe_ratio(managed_values) - sharpe_ratio(unmanaged_values)
    p_two_sided = min(
        1.0,
        2.0
        * min(
            float(np.mean(differences <= 0.0)),
            float(np.mean(differences >= 0.0)),
        ),
    )
    return {
        "n_boot": N_BOOT,
        "mean_block_months": BOOT_MEAN_BLOCK,
        "observed_sharpe_difference": observed,
        "ci_2_5": float(np.quantile(differences, 0.025)),
        "ci_97_5": float(np.quantile(differences, 0.975)),
        "p_two_sided": p_two_sided,
    }


def benjamini_hochberg(p_values: dict[str, float]) -> dict[str, float]:
    names = list(p_values)
    values = np.asarray([p_values[name] for name in names], dtype=float)
    order = np.argsort(values)
    adjusted = np.empty(len(values), dtype=float)
    running = 1.0
    for reverse_rank in range(len(values) - 1, -1, -1):
        original_index = order[reverse_rank]
        rank = reverse_rank + 1
        candidate = values[original_index] * len(values) / rank
        running = min(running, candidate)
        adjusted[original_index] = min(1.0, running)
    return {name: float(adjusted[idx]) for idx, name in enumerate(names)}


def hac_spanning_regression(managed: pd.Series, unmanaged: pd.Series) -> dict[str, float]:
    aligned = pd.concat([managed.rename("managed"), unmanaged.rename("unmanaged")], axis=1).dropna()
    design = sm.add_constant(aligned["unmanaged"])
    fit = sm.OLS(aligned["managed"], design).fit(cov_type="HAC", cov_kwds={"maxlags": 6})
    return {
        "alpha_monthly": float(fit.params["const"]),
        "alpha_annualized": float(fit.params["const"] * 12.0),
        "alpha_hac_t": float(fit.tvalues["const"]),
        "beta_unmanaged": float(fit.params["unmanaged"]),
        "r_squared": float(fit.rsquared),
    }


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, float):
        return None if not np.isfinite(value) else value
    if isinstance(value, (pd.Timestamp, pd.Period)):
        return str(value)
    return value


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(json_ready(payload), handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    with tmp.open(encoding="utf-8") as handle:
        json.load(handle)
    os.replace(tmp, path)


def period_slice(series: pd.Series, start: str, end: str | None) -> pd.Series:
    mask = series.index >= pd.Period(start, freq="M")
    if end is not None:
        mask &= series.index <= pd.Period(end, freq="M")
    return series.loc[mask]


def main() -> None:
    np.random.seed(SEED)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    ff5_path = resolve_data_file(
        "FF5_DAILY_ZIP", "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip", FF5_URL
    )
    mom_path = resolve_data_file(
        "MOM_DAILY_ZIP", "F-F_Momentum_Factor_daily_CSV.zip", MOM_URL
    )
    qmj_path = resolve_data_file(
        "AQR_QMJ_XLSX", "Quality-Minus-Junk-Factors-Daily.xlsx", QMJ_URL
    )

    ff5 = parse_french_zip(ff5_path, ("SMB", "HML"))
    momentum = parse_french_zip(mom_path, ("Mom",)).rename(columns={"Mom": "MOM"})
    qmj = parse_aqr_qmj_xlsx(qmj_path)
    daily = ff5.join(momentum, how="inner").join(qmj, how="inner")[list(FACTORS)]
    daily = daily.replace([np.inf, -np.inf], np.nan).dropna()
    if len(daily) < 5_000 or daily.index.max() < pd.Timestamp("2020-01-01"):
        raise RuntimeError("Common factor sample is too short for the planned OOS audit")

    month = daily.index.to_period("M")
    monthly_returns = (1.0 + daily).groupby(month).prod() - 1.0
    monthly_rv = daily.pow(2).groupby(month).sum()
    # HARD no-lookahead rule: month t inverse variance becomes month t+1 signal.
    inverse_variance_signal = (1.0 / monthly_rv.clip(lower=1e-12)).shift(1)

    calibration_mask = monthly_returns.index <= CALIBRATION_END
    oos_mask = monthly_returns.index >= OOS_START
    if calibration_mask.sum() < 240 or oos_mask.sum() < 252:
        raise RuntimeError("Insufficient calibration or OOS monthly observations")

    data_diagnostics: dict[str, Any] = {}
    for factor in FACTORS:
        values = daily[factor].to_numpy(float)
        arch_stat, arch_p, _, _ = het_arch(values, nlags=12)
        data_diagnostics[factor] = {
            "daily_mean": float(np.mean(values)),
            "daily_std": float(np.std(values, ddof=1)),
            "daily_skewness": float(stats.skew(values, bias=False)),
            "daily_excess_kurtosis": float(stats.kurtosis(values, fisher=True, bias=False)),
            "arch_lm_12_stat": float(arch_stat),
            "arch_lm_12_p": float(arch_p),
        }

    weights: dict[str, dict[str, pd.Series]] = {}
    managed_returns: dict[str, dict[str, dict[int, pd.Series]]] = {}
    calibration: dict[str, Any] = {}
    panel = monthly_returns.copy()

    for factor in FACTORS:
        raw_weight = inverse_variance_signal[factor]
        training = pd.concat(
            [raw_weight.rename("weight"), monthly_returns[factor].rename("return")], axis=1
        ).loc[calibration_mask].dropna()
        raw_training_managed = training["weight"] * training["return"]
        denominator = float(raw_training_managed.std(ddof=1))
        if denominator <= 0:
            raise RuntimeError(f"Non-positive managed calibration volatility for {factor}")
        scale = float(training["return"].std(ddof=1) / denominator)
        uncapped = scale * raw_weight
        capped = uncapped.clip(lower=0.0, upper=LEVERAGE_CAP)
        weights[factor] = {"uncapped": uncapped, PRIMARY_VARIANT: capped}
        calibration[factor] = {
            "normalization_constant": scale,
            "training_months": int(len(training)),
            "training_unmanaged_vol_monthly": float(training["return"].std(ddof=1)),
            "training_uncapped_managed_vol_monthly": float(
                (uncapped * monthly_returns[factor]).loc[calibration_mask].dropna().std(ddof=1)
            ),
        }
        managed_returns[factor] = {}
        for variant, factor_weight in weights[factor].items():
            turnover = factor_weight.diff().abs()
            managed_returns[factor][variant] = {}
            for cost_bps in COST_BPS:
                cost = turnover * (cost_bps / 10_000.0)
                managed_returns[factor][variant][cost_bps] = (
                    factor_weight * monthly_returns[factor] - cost
                )
        panel[f"{factor}_primary_weight"] = capped
        panel[f"{factor}_primary_managed_return"] = managed_returns[factor][PRIMARY_VARIANT][
            PRIMARY_COST_BPS
        ]

    period_specs = {
        "oos_full": ("2000-01", None),
        "oos_2000_2012": ("2000-01", "2012-12"),
        "oos_2013_latest": ("2013-01", None),
    }
    rows: list[dict[str, Any]] = []
    full_oos_inference: dict[str, Any] = {}
    seed_offset = 0

    from volpred.stats.model_evaluation import strategy_dm_test

    for factor in FACTORS:
        unmanaged_full = monthly_returns[factor]
        for variant, factor_weight in weights[factor].items():
            for cost_bps in COST_BPS:
                managed_full = managed_returns[factor][variant][cost_bps]
                for period_name, (start, end) in period_specs.items():
                    unmanaged = period_slice(unmanaged_full, start, end)
                    managed = period_slice(managed_full, start, end)
                    aligned = pd.concat(
                        [managed.rename("managed"), unmanaged.rename("unmanaged")], axis=1
                    ).dropna()
                    managed_metrics = annualized_metrics(aligned["managed"])
                    unmanaged_metrics = annualized_metrics(aligned["unmanaged"])
                    row = {
                        "factor": factor,
                        "variant": variant,
                        "cost_bps": cost_bps,
                        "period": period_name,
                        "start": str(aligned.index.min()),
                        "end": str(aligned.index.max()),
                        "n_months": int(len(aligned)),
                        "managed_sharpe": managed_metrics.get("sharpe_zero_rf"),
                        "unmanaged_sharpe": unmanaged_metrics.get("sharpe_zero_rf"),
                        "sharpe_difference": (
                            managed_metrics.get("sharpe_zero_rf", np.nan)
                            - unmanaged_metrics.get("sharpe_zero_rf", np.nan)
                        ),
                        "managed_annual_return": managed_metrics.get(
                            "annual_return_arithmetic"
                        ),
                        "unmanaged_annual_return": unmanaged_metrics.get(
                            "annual_return_arithmetic"
                        ),
                        "managed_annual_volatility": managed_metrics.get(
                            "annual_volatility"
                        ),
                        "unmanaged_annual_volatility": unmanaged_metrics.get(
                            "annual_volatility"
                        ),
                        "managed_max_drawdown": managed_metrics.get("max_drawdown"),
                        "unmanaged_max_drawdown": unmanaged_metrics.get("max_drawdown"),
                    }
                    rows.append(row)
                full_aligned = pd.concat(
                    [
                        period_slice(managed_full, "2000-01", None).rename("managed"),
                        period_slice(unmanaged_full, "2000-01", None).rename("unmanaged"),
                    ],
                    axis=1,
                ).dropna()
                dm_t, dm_p = strategy_dm_test(
                    full_aligned["managed"].to_numpy(),
                    full_aligned["unmanaged"].to_numpy(),
                    h=1,
                    loss_fn="negative_return",
                )
                bootstrap = paired_sharpe_bootstrap(
                    full_aligned["managed"], full_aligned["unmanaged"], seed_offset
                )
                seed_offset += 1
                key = f"{factor}|{variant}|{cost_bps}bp"
                full_oos_inference[key] = {
                    "strategy_dm_negative_t_managed_better": {
                        "t": dm_t,
                        "p": dm_p,
                        "harvey_pass": bool(dm_t < -3.0),
                    },
                    "paired_stationary_bootstrap_sharpe_difference": bootstrap,
                    "spanning_regression_hac": hac_spanning_regression(
                        full_aligned["managed"], full_aligned["unmanaged"]
                    ),
                    "weight_diagnostics": {
                        "mean": float(factor_weight.loc[oos_mask].mean()),
                        "median": float(factor_weight.loc[oos_mask].median()),
                        "max": float(factor_weight.loc[oos_mask].max()),
                        "p99": float(factor_weight.loc[oos_mask].quantile(0.99)),
                        "annual_turnover": float(
                            factor_weight.diff().abs().loc[oos_mask].mean() * 12.0
                        ),
                    },
                }

    summary = pd.DataFrame(rows)
    summary.to_csv(SUMMARY_PATH, index=False, float_format="%.10g")
    panel.loc[oos_mask].to_timestamp(how="end").to_csv(
        PANEL_PATH, index_label="month", float_format="%.12g"
    )

    primary_keys = {
        factor: f"{factor}|{PRIMARY_VARIANT}|{PRIMARY_COST_BPS}bp" for factor in FACTORS
    }
    primary_dm_p = {
        factor: full_oos_inference[key]["strategy_dm_negative_t_managed_better"]["p"]
        for factor, key in primary_keys.items()
    }
    primary_boot_p = {
        factor: full_oos_inference[key][
            "paired_stationary_bootstrap_sharpe_difference"
        ]["p_two_sided"]
        for factor, key in primary_keys.items()
    }
    dm_fdr = benjamini_hochberg(primary_dm_p)
    bootstrap_fdr = benjamini_hochberg(primary_boot_p)

    primary_table = summary[
        (summary["variant"] == PRIMARY_VARIANT)
        & (summary["cost_bps"] == PRIMARY_COST_BPS)
        & (summary["period"] == "oos_full")
    ].set_index("factor")
    positive_sharpe = int((primary_table["sharpe_difference"] > 0).sum())
    bootstrap_positive = 0
    harvey_positive = 0
    for factor, key in primary_keys.items():
        inference = full_oos_inference[key]
        bootstrap = inference["paired_stationary_bootstrap_sharpe_difference"]
        bootstrap_positive += int(
            bootstrap["ci_2_5"] > 0 and bootstrap_fdr[factor] < 0.05
        )
        dm = inference["strategy_dm_negative_t_managed_better"]
        harvey_positive += int(dm["t"] < -3.0 and dm_fdr[factor] < 0.05)

    subperiod_primary = summary[
        (summary["variant"] == PRIMARY_VARIANT)
        & (summary["cost_bps"] == PRIMARY_COST_BPS)
        & (summary["period"].isin(["oos_2000_2012", "oos_2013_latest"]))
    ]
    factors_positive_both_subperiods = int(
        (subperiod_primary.groupby("factor")["sharpe_difference"].min() > 0).sum()
    )
    conditional_support = (
        positive_sharpe >= 3
        and bootstrap_positive >= 2
        and harvey_positive >= 2
        and factors_positive_both_subperiods >= 2
    )
    verdict = (
        "CONDITIONAL_PASS_CROSS_FACTOR_OOS"
        if conditional_support
        else "NULL_OR_MIXED_INDIVIDUAL_FACTOR_OOS"
    )

    cost_survival: dict[str, Any] = {}
    for cost_bps in COST_BPS:
        table = summary[
            (summary["variant"] == PRIMARY_VARIANT)
            & (summary["cost_bps"] == cost_bps)
            & (summary["period"] == "oos_full")
        ].set_index("factor")
        cost_survival[str(cost_bps)] = {
            "positive_sharpe_difference_count": int((table["sharpe_difference"] > 0).sum()),
            "median_sharpe_difference": float(table["sharpe_difference"].median()),
            "per_factor_sharpe_difference": {
                factor: float(table.loc[factor, "sharpe_difference"]) for factor in FACTORS
            },
        }

    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(FACTORS))
    unmanaged_values = [float(primary_table.loc[factor, "unmanaged_sharpe"]) for factor in FACTORS]
    managed_values = [float(primary_table.loc[factor, "managed_sharpe"]) for factor in FACTORS]
    width = 0.36
    ax.bar(x - width / 2, unmanaged_values, width, label="Unmanaged", color="#6b7280")
    ax.bar(
        x + width / 2,
        managed_values,
        width,
        label=f"Vol-managed cap 3x, {PRIMARY_COST_BPS}bp overlay",
        color="#2563eb",
    )
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.set_xticks(x, FACTORS)
    ax.set_ylabel("OOS annualized Sharpe (zero RF)")
    ax.set_title("Fixed-calibration volatility management: 2000+ OOS")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(BASE_DIR / "factor_sharpe_comparison.png", dpi=170)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 5))
    for factor in FACTORS:
        differences = [
            cost_survival[str(cost)]["per_factor_sharpe_difference"][factor]
            for cost in COST_BPS
        ]
        ax.plot(COST_BPS, differences, marker="o", label=factor)
    ax.axhline(0.0, color="black", linewidth=0.8, linestyle="--")
    ax.set_xlabel("Overlay cost per unit exposure change (bps)")
    ax.set_ylabel("Managed minus unmanaged OOS Sharpe")
    ax.set_title("Factor-level scaling cost sensitivity (lower-bound cost)")
    ax.legend(frameon=False, ncol=2)
    fig.tight_layout()
    fig.savefig(BASE_DIR / "cost_sensitivity.png", dpi=170)
    plt.close(fig)

    payload: dict[str, Any] = {
        "experiment_id": "research_rp_a02d0a5f75",
        "title": "Volatility-managed factor zoo: fixed-calibration real-time OOS audit",
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "methodology_type": "empirical",
        "verdict": verdict,
        "data": {
            "sources": {
                "ff5_daily": {"url": FF5_URL, "sha256": sha256(ff5_path)},
                "momentum_daily": {"url": MOM_URL, "sha256": sha256(mom_path)},
                "aqr_qmj_daily": {
                    "url": QMJ_URL,
                    "sha256": sha256(qmj_path),
                    "vintage_warning": "AQR states that it reconstructs full history on updates",
                },
            },
            "common_daily_start": daily.index.min().date().isoformat(),
            "common_daily_end": daily.index.max().date().isoformat(),
            "common_daily_observations": int(len(daily)),
            "monthly_start": str(monthly_returns.index.min()),
            "monthly_end": str(monthly_returns.index.max()),
            "monthly_observations": int(len(monthly_returns)),
            "calibration_period": f"{monthly_returns.index.min()} through {CALIBRATION_END}",
            "oos_period": f"{OOS_START} through {monthly_returns.index.max()}",
            "oos_observations": int(oos_mask.sum()),
            "diagnostics": data_diagnostics,
        },
        "methodology": {
            "factor_set": list(FACTORS),
            "monthly_return": "compound daily factor returns within month",
            "realized_variance": "sum of squared daily factor returns within month",
            "timing": "inverse_variance_signal = (1 / monthly_rv).shift(1)",
            "normalization": "factor-specific constant fixed on pre-2000 data to match training volatility",
            "variants": ["uncapped", PRIMARY_VARIANT],
            "leverage_cap": LEVERAGE_CAP,
            "overlay_cost_bps": list(COST_BPS),
            "cost_scope": (
                "lower-bound factor-level exposure-change cost only; excludes constituent-level "
                "turnover, spread, short-leg, and factor-reconstitution costs"
            ),
            "primary_specification": {
                "variant": PRIMARY_VARIANT,
                "overlay_cost_bps": PRIMARY_COST_BPS,
            },
            "inference": {
                "strategy_dm_test_h": 1,
                "harvey_abs_t_threshold": 3.0,
                "stationary_bootstrap_reps": N_BOOT,
                "stationary_bootstrap_mean_block_months": BOOT_MEAN_BLOCK,
                "multiple_testing": "Benjamini-Hochberg across four primary factors",
            },
        },
        "calibration": calibration,
        "primary_gate": {
            "positive_sharpe_factors": positive_sharpe,
            "bootstrap_positive_fdr_factors": bootstrap_positive,
            "harvey_positive_fdr_factors": harvey_positive,
            "factors_positive_both_subperiods": factors_positive_both_subperiods,
            "conditional_support": conditional_support,
        },
        "primary_multiple_testing": {
            "dm_raw_p": primary_dm_p,
            "dm_bh_q": dm_fdr,
            "bootstrap_raw_p": primary_boot_p,
            "bootstrap_bh_q": bootstrap_fdr,
        },
        "cost_survival": cost_survival,
        "full_oos_inference": full_oos_inference,
        "summary_rows": rows,
        "references": REFERENCES,
        "limitations": [
            "Published factor returns are not directly investable portfolios.",
            "Overlay costs are a lower bound and are not a Barroso-Detzel stock-level cost replication.",
            "AQR reconstructs full QMJ history on updates; no historical vintages were available here.",
            "The fixed 2000 split is one real-time design; it does not eliminate all specification uncertainty.",
            "The experiment covers US equity factors and has no like-for-like Taiwan QMJ factor series.",
        ],
        "artifacts": [
            PANEL_PATH.name,
            SUMMARY_PATH.name,
            "factor_sharpe_comparison.png",
            "cost_sensitivity.png",
        ],
    }
    atomic_write_json(RESULTS_PATH, payload)
    print(json.dumps(json_ready(payload["primary_gate"]), indent=2))
    print(f"verdict={verdict}")
    print(f"results={RESULTS_PATH}")


if __name__ == "__main__":
    main()
