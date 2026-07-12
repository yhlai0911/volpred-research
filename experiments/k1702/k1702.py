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

# Mkt-RF is the Moreira-Muir (2017) headline factor and is carried as the
# reference cell: if the pipeline cannot reproduce its in-sample result, the
# zoo-wide null would be uninterpretable.  The other six are the "zoo".
FACTORS = ("MktRF", "SMB", "HML", "RMW", "CMA", "MOM", "QMJ")
ZOO_FACTORS = ("SMB", "HML", "RMW", "CMA", "MOM", "QMJ")

# Lag grid for the HAC bandwidth sensitivity report required by
# .claude/rules/experiments.md.  The primary lag is chosen at runtime as
# max(h - 1, canonical) where canonical = ceil(h^(1/3) * n^(1/3)).
HAC_LAG_GRID = (0, 3, 6, 12)
ACF_MAX_LAG = 12

# The AQR workbook carries a few header / note / spacer rows before the series
# starts.  A handful of skips is expected; a large number means the layout or the
# date format changed and real observations would be silently lost.
MAX_UNPARSEABLE_QMJ_ROWS = 200

# Fail-loud unit guard: every factor here is a DAILY return in decimal units.
# French files are percent (divided by 100 at parse); AQR is already decimal.  If a
# vintage ever ships different units, a 100x scale error would silently corrupt
# every realized variance and every result, so assert the plausible range instead.
MIN_PLAUSIBLE_DAILY_STD = 0.0005
MAX_PLAUSIBLE_DAILY_STD = 0.05

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RESULTS_PATH = BASE_DIR / "k1702_results.json"
PANEL_PATH = BASE_DIR / "analysis_panel.csv"
SUMMARY_PATH = BASE_DIR / "summary_table.csv"

FF3_URL = (
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
    "F-F_Research_Data_Factors_daily_CSV.zip"
)
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
    """Parse sheet1/`QMJ Factors` without an openpyxl dependency.

    Unparseable rows are COUNTED, not silently dropped.  The AQR workbook has a
    handful of header / note / spacer rows before the series starts, so a few
    skips are expected -- but a silent ``except: pass`` here could quietly
    discard real observations if AQR ever changes its date format, and the
    ``len < 1000`` guard alone would not catch a partial loss.  The count is
    bounded and surfaced in the results JSON.
    """
    skipped_rows = 0
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
                        skipped_rows += 1
                row.clear()
    if usa_column is None or len(observations) < 1_000:
        raise ValueError(f"Could not recover a valid USA QMJ series from {path}")
    if skipped_rows > MAX_UNPARSEABLE_QMJ_ROWS:
        raise ValueError(
            f"AQR QMJ parser skipped {skipped_rows} unparseable rows "
            f"(limit {MAX_UNPARSEABLE_QMJ_ROWS}); the date format or layout likely "
            f"changed and real observations may be silently missing: {path}"
        )
    series = pd.Series(
        [value for _, value in observations],
        index=pd.DatetimeIndex([date for date, _ in observations]),
        name="QMJ",
        dtype=float,
    ).sort_index()
    series = series[~series.index.duplicated(keep="last")]
    return series.replace([-99.99, -999.0], np.nan)


def annualized_metrics(returns: pd.Series) -> dict[str, float | int | bool]:
    returns = returns.dropna().astype(float)
    if len(returns) < 12:
        return {"n_months": int(len(returns))}
    mean = float(returns.mean())
    volatility = float(returns.std(ddof=1))

    # A month <= -100% drives cumulative wealth negative, after which the
    # wealth/cummax drawdown is arithmetically meaningless.  Emit an explicit flag
    # rather than a silently garbage max_drawdown number.  The uncapped variant is
    # the one at risk, and whether it triggers is data-vintage dependent.
    bankrupt = bool((returns <= -1.0).any())
    if bankrupt:
        max_drawdown: float | None = None
    else:
        wealth = (1.0 + returns).cumprod()
        max_drawdown = float((wealth / wealth.cummax() - 1.0).min())

    annual_volatility = volatility * np.sqrt(12.0)

    # Raw max drawdown is NOT scale-invariant.  A vol-managed series that simply
    # runs at a quarter of the benchmark's exposure will show a shallower drawdown
    # for purely mechanical reasons -- that is "taking less risk", not "timing risk
    # well".  Reporting raw MDD improvement alone would overstate the case for
    # vol-managing, so the drawdown per unit of realized volatility is reported
    # alongside it; that ratio IS scale-invariant and is the honest comparison.
    max_drawdown_per_annual_vol = (
        None
        if (max_drawdown is None or annual_volatility <= 0)
        else float(max_drawdown / annual_volatility)
    )

    return {
        "n_months": int(len(returns)),
        "annual_return_arithmetic": mean * 12.0,
        "annual_volatility": annual_volatility,
        "sharpe_zero_rf": mean / volatility * np.sqrt(12.0) if volatility > 0 else np.nan,
        "max_drawdown": max_drawdown,
        "max_drawdown_per_annual_vol": max_drawdown_per_annual_vol,
        "bankrupt_month_leq_minus_100pct": bankrupt,
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
    # (1 + k) / (B + 1) continuity correction: without it the bootstrap p can be
    # exactly 0, which is not a valid p-value and would propagate into BH-FDR.
    p_two_sided = min(
        1.0,
        2.0
        * min(
            (1.0 + float(np.sum(differences <= 0.0))) / (N_BOOT + 1.0),
            (1.0 + float(np.sum(differences >= 0.0))) / (N_BOOT + 1.0),
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


def canonical_hac_lag(n: int, h: int = 1) -> int:
    """Repo-canonical Newey-West bandwidth: ceil(h^(1/3) * n^(1/3)), capped at n//4.

    Mirrors ``volpred.stats.model_evaluation.dm_test`` so the spanning
    regression and the DM test share one bandwidth rule.
    """
    return max(1, min(int(np.ceil(h ** (1 / 3) * n ** (1 / 3))), n // 4))


def sample_acf(values: np.ndarray, max_lag: int = ACF_MAX_LAG) -> dict[str, float]:
    """Sample autocorrelations, used to justify the HAC bandwidth choice."""
    series = np.asarray(values, dtype=np.float64)
    series = series[np.isfinite(series)]
    n = len(series)
    demeaned = series - series.mean()
    gamma0 = float(np.mean(demeaned**2))
    if gamma0 <= 0:
        return {}
    out: dict[str, float] = {}
    for lag in range(1, min(max_lag, n - 2) + 1):
        gamma = float(np.mean(demeaned[lag:] * demeaned[:-lag]))
        out[f"acf_{lag}"] = gamma / gamma0
    return out


def hac_spanning_regression(
    managed: pd.Series, unmanaged: pd.Series, h: int = 1
) -> dict[str, Any]:
    """Moreira-Muir spanning regression with an acf-justified HAC bandwidth.

    .claude/rules/experiments.md forbids fixing the Newey-West lag at ``h - 1``:
    at h = 1 that degenerates to zero lags (no HAC at all), and the residual
    autocorrelation of a volatility-managed series is driven by the persistence
    of the variance signal, not by forecast-window overlap.  The primary lag is
    therefore ``max(h - 1, canonical)`` and the full lag grid is reported so the
    alpha t-stat can be read against bandwidth sensitivity.  Omitting HAC is a
    two-sided misspecification: positive residual autocorrelation inflates |t|,
    negative autocovariance deflates it.
    """
    aligned = pd.concat(
        [managed.rename("managed"), unmanaged.rename("unmanaged")], axis=1
    ).dropna()
    n = int(len(aligned))
    design = sm.add_constant(aligned["unmanaged"])
    ols = sm.OLS(aligned["managed"], design)

    canonical = canonical_hac_lag(n, h)
    primary_lag = max(h - 1, canonical)

    fit = ols.fit(cov_type="HAC", cov_kwds={"maxlags": primary_lag})
    residual_acf = sample_acf(np.asarray(fit.resid, dtype=float))

    sensitivity: dict[str, dict[str, float]] = {}
    for lag in sorted({*HAC_LAG_GRID, primary_lag}):
        if lag <= 0:
            alt = ols.fit()  # lag 0 == plain OLS, i.e. no HAC correction
        elif lag >= n // 2:
            continue
        else:
            alt = ols.fit(cov_type="HAC", cov_kwds={"maxlags": lag})
        sensitivity[str(lag)] = {
            # lag 0 is plain OLS with NO HAC correction -- do not read its t as a
            # HAC t.  It is included precisely to show what omitting HAC would do.
            "alpha_t": float(alt.tvalues["const"]),
            "alpha_p": float(alt.pvalues["const"]),
            "hac_applied": bool(lag > 0),
        }

    return {
        "alpha_monthly": float(fit.params["const"]),
        "alpha_annualized": float(fit.params["const"] * 12.0),
        "alpha_hac_t": float(fit.tvalues["const"]),
        "alpha_hac_p": float(fit.pvalues["const"]),
        "beta_unmanaged": float(fit.params["unmanaged"]),
        "r_squared": float(fit.rsquared),
        "n_months": n,
        "hac_lag_primary": int(primary_lag),
        "hac_lag_canonical": int(canonical),
        "hac_lag_rule": "max(h-1, ceil(h^(1/3) * n^(1/3)))",
        "residual_acf": residual_acf,
        "hac_lag_sensitivity": sensitivity,
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


def period_slice(series: pd.Series, start: str | None, end: str | None) -> pd.Series:
    mask = np.ones(len(series), dtype=bool)
    if start is not None:
        mask &= series.index >= pd.Period(start, freq="M")
    if end is not None:
        mask &= series.index <= pd.Period(end, freq="M")
    return series.loc[mask]


def moreira_muir_replication(ff3_path: Path) -> dict[str, Any]:
    """Falsification test for the pipeline itself, run before the zoo is judged.

    A zoo-wide null is only interpretable if this *same code* can reproduce
    Moreira and Muir's (2017) headline market result on *their* sample.  If it
    cannot, a null is a pipeline artifact, not evidence about factors.

    MM's headline is an IN-SAMPLE analysis: the constant is set so the managed
    and unmanaged series carry equal unconditional volatility over the evaluated
    window, and the Sharpe lift plus the spanning alpha are then reported.  This
    function replicates exactly that -- uncapped and costless, as in the paper --
    on MM's own 1926-07..2015-12 window, and then re-runs it on the zoo's
    calibration and OOS windows to expose how much of the effect is a
    sample-period artifact.

    Every cell here is IN-SAMPLE by construction and must never be read as an
    out-of-sample claim; it is a diagnostic, not a result.
    """
    ff3 = parse_french_zip(ff3_path, ("Mkt-RF",)).rename(columns={"Mkt-RF": "MktRF"})
    daily = ff3["MktRF"].replace([np.inf, -np.inf], np.nan).dropna()
    month = daily.index.to_period("M")
    monthly = (1.0 + daily).groupby(month).prod() - 1.0
    realized_variance = daily.pow(2).groupby(month).sum()
    signal = (1.0 / realized_variance.clip(lower=1e-12)).shift(1)

    windows = {
        "mm_1926_2015_paper_sample": ("1926-07", "2015-12"),
        "full_1926_latest": ("1926-07", None),
        "pre_1963_only": ("1926-07", "1963-06"),
        "zoo_calibration_1963_1999": ("1963-07", "1999-12"),
        "zoo_oos_2000_latest": ("2000-01", None),
    }
    out: dict[str, Any] = {
        "_interpretation": (
            "IN-SAMPLE diagnostic only (constant fitted on the same window it is "
            "evaluated on), uncapped and costless, replicating Moreira-Muir (2017). "
            "Not an out-of-sample claim. Purpose: verify the pipeline can reproduce "
            "the published market result before any zoo null is believed."
        ),
        "daily_start": daily.index.min().date().isoformat(),
        "daily_end": daily.index.max().date().isoformat(),
        "daily_observations": int(len(daily)),
    }
    for name, (start, end) in windows.items():
        frame = pd.concat(
            [
                period_slice(signal, start, end).rename("weight"),
                period_slice(monthly, start, end).rename("factor_return"),
            ],
            axis=1,
        ).dropna()
        raw_managed = frame["weight"] * frame["factor_return"]
        denominator = float(raw_managed.std(ddof=1))
        if denominator <= 0:
            continue
        scale = float(frame["factor_return"].std(ddof=1) / denominator)
        managed = scale * raw_managed
        unmanaged = frame["factor_return"]
        managed_metrics = annualized_metrics(managed)
        unmanaged_metrics = annualized_metrics(unmanaged)
        out[name] = {
            "n_months": int(len(frame)),
            "start": str(frame.index.min()),
            "end": str(frame.index.max()),
            "unmanaged": unmanaged_metrics,
            "managed": managed_metrics,
            "sharpe_difference": (
                managed_metrics.get("sharpe_zero_rf", np.nan)
                - unmanaged_metrics.get("sharpe_zero_rf", np.nan)
            ),
            "spanning_regression_hac": hac_spanning_regression(managed, unmanaged),
        }
    return out


def main() -> None:
    np.random.seed(SEED)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    ff3_path = resolve_data_file(
        "FF3_DAILY_ZIP", "F-F_Research_Data_Factors_daily_CSV.zip", FF3_URL
    )
    ff5_path = resolve_data_file(
        "FF5_DAILY_ZIP", "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip", FF5_URL
    )
    mom_path = resolve_data_file(
        "MOM_DAILY_ZIP", "F-F_Momentum_Factor_daily_CSV.zip", MOM_URL
    )
    qmj_path = resolve_data_file(
        "AQR_QMJ_XLSX", "Quality-Minus-Junk-Factors-Daily.xlsx", QMJ_URL
    )

    ff5 = parse_french_zip(ff5_path, ("Mkt-RF", "SMB", "HML", "RMW", "CMA")).rename(
        columns={"Mkt-RF": "MktRF"}
    )
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
        daily_std = float(np.std(values, ddof=1))
        if not MIN_PLAUSIBLE_DAILY_STD < daily_std < MAX_PLAUSIBLE_DAILY_STD:
            raise RuntimeError(
                f"{factor}: daily std {daily_std:.6g} is outside the plausible decimal-return "
                f"range ({MIN_PLAUSIBLE_DAILY_STD}, {MAX_PLAUSIBLE_DAILY_STD}). A source likely "
                f"changed units (percent vs decimal); a 100x scale error would silently corrupt "
                f"every realized variance. Refusing to continue."
            )
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

    # "in_sample" reuses the calibration window, where the scaling constant was
    # fitted.  It is deliberately in-sample: it is the IS-vs-OOS contrast that
    # shows whether the Moreira-Muir effect survives real-time implementation,
    # and it must never be read as evidence of OOS performance.
    period_specs = {
        "in_sample": (None, str(CALIBRATION_END)),
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
                        "managed_mdd_per_annual_vol": managed_metrics.get(
                            "max_drawdown_per_annual_vol"
                        ),
                        "unmanaged_mdd_per_annual_vol": unmanaged_metrics.get(
                            "max_drawdown_per_annual_vol"
                        ),
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
                is_primary_cell = (
                    variant == PRIMARY_VARIANT and cost_bps == PRIMARY_COST_BPS
                )
                full_oos_inference[key] = {
                    # K1655 lesson: the real failure point is "which variant fed the
                    # outward-facing claim". Every cell is tagged so a downstream
                    # writer cannot quietly cherry-pick a favourable non-primary cell,
                    # or quote an uncorrected number as if it survived multiple testing.
                    "is_primary_spec": bool(is_primary_cell),
                    "is_zoo_factor": bool(factor in ZOO_FACTORS),
                    "multiple_testing_corrected": bool(
                        is_primary_cell and factor in ZOO_FACTORS
                    ),
                    "strategy_dm_mean_return_SCALE_DEPENDENT_diagnostic": {
                        "t": dm_t,
                        "p": dm_p,
                        "_warning": (
                            "NOT risk-adjusted. loss_fn='negative_return' compares RAW MEAN "
                            "RETURNS. The managed series runs at far lower exposure than the "
                            "benchmark (the constant is fixed pre-2000 and post-2000 realized "
                            "variance is higher), so its mean return is mechanically lower even "
                            "when its Sharpe is much higher. Do NOT gate on this and do NOT read "
                            "a positive t as 'vol-managing hurts'. Scale-invariant evidence lives "
                            "in paired_stationary_bootstrap_sharpe_difference and "
                            "spanning_regression_hac (beta absorbs the exposure mismatch)."
                        ),
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

    # ── Cross-factor aggregation: the DeMiguel-Martin-Utrera-Uppal (2024) view ──
    # .claude/rules/experiments.md forbids treating factor-month cells as iid in a
    # pooled test, because factors sharing a calendar month share a market shock.
    # So aggregate ACROSS factors WITHIN each month first (equal-weight zoo
    # combination), then run the time-series DM / HAC inference on that single
    # monthly series.  No stacked factor-month test is reported anywhere.
    multifactor: dict[str, Any] = {}
    zoo_unmanaged_ew = monthly_returns[list(ZOO_FACTORS)].mean(axis=1)
    for cost_bps in COST_BPS:
        zoo_managed_ew = pd.DataFrame(
            {f: managed_returns[f][PRIMARY_VARIANT][cost_bps] for f in ZOO_FACTORS}
        ).mean(axis=1)
        aligned = pd.concat(
            [
                period_slice(zoo_managed_ew, "2000-01", None).rename("managed"),
                period_slice(zoo_unmanaged_ew, "2000-01", None).rename("unmanaged"),
            ],
            axis=1,
        ).dropna()
        dm_t, dm_p = strategy_dm_test(
            aligned["managed"].to_numpy(),
            aligned["unmanaged"].to_numpy(),
            h=1,
            loss_fn="negative_return",
        )
        managed_metrics = annualized_metrics(aligned["managed"])
        unmanaged_metrics = annualized_metrics(aligned["unmanaged"])
        bootstrap = paired_sharpe_bootstrap(
            aligned["managed"], aligned["unmanaged"], seed_offset
        )
        seed_offset += 1
        multifactor[str(cost_bps)] = {
            "n_months": int(len(aligned)),
            "managed": managed_metrics,
            "unmanaged": unmanaged_metrics,
            "sharpe_difference": (
                managed_metrics.get("sharpe_zero_rf", np.nan)
                - unmanaged_metrics.get("sharpe_zero_rf", np.nan)
            ),
            "strategy_dm_negative_t_managed_better": {
                "t": dm_t,
                "p": dm_p,
                "harvey_pass": bool(dm_t < -3.0),
            },
            "paired_stationary_bootstrap_sharpe_difference": bootstrap,
            "spanning_regression_hac": hac_spanning_regression(
                aligned["managed"], aligned["unmanaged"]
            ),
        }

    primary_keys = {
        factor: f"{factor}|{PRIMARY_VARIANT}|{PRIMARY_COST_BPS}bp" for factor in FACTORS
    }
    # The BH-FDR family is the six ZOO factors.  Mkt-RF is a pre-specified
    # replication reference (does the pipeline reproduce Moreira-Muir's headline
    # factor at all?), not a discovery hypothesis, so it is reported separately
    # and neither enters nor dilutes the multiple-testing correction.
    # SCALE-INVARIANT GATE.  The DM test above compares RAW MEAN RETURNS and is not
    # risk-adjusted.  Because the constant is fixed on pre-2000 data and post-2000
    # realized variance is higher, the managed series runs at far lower exposure
    # (MOM: 4.4% vs 17.4% annualized vol), so its mean return is mechanically lower
    # even where its Sharpe is much higher.  Gating on that DM would make a
    # "managed is worse" verdict nearly impossible to avoid -- an instrument that
    # manufactures the null we already expected, which is exactly as untrustworthy
    # as one that manufactures a win.  The gate therefore uses the two
    # scale-invariant statistics: the paired Sharpe bootstrap, and the spanning
    # alpha (whose beta absorbs the exposure mismatch, and which is Moreira-Muir's
    # own headline statistic).  The DM is retained as a labelled diagnostic only.
    primary_boot_p = {
        factor: full_oos_inference[primary_keys[factor]][
            "paired_stationary_bootstrap_sharpe_difference"
        ]["p_two_sided"]
        for factor in ZOO_FACTORS
    }
    primary_alpha_p = {
        factor: full_oos_inference[primary_keys[factor]]["spanning_regression_hac"][
            "alpha_hac_p"
        ]
        for factor in ZOO_FACTORS
    }
    primary_dm_p = {
        factor: full_oos_inference[primary_keys[factor]][
            "strategy_dm_mean_return_SCALE_DEPENDENT_diagnostic"
        ]["p"]
        for factor in ZOO_FACTORS
    }
    bootstrap_fdr = benjamini_hochberg(primary_boot_p)
    alpha_fdr = benjamini_hochberg(primary_alpha_p)
    dm_fdr = benjamini_hochberg(primary_dm_p)  # diagnostic only; not a gate input

    primary_table = summary[
        (summary["variant"] == PRIMARY_VARIANT)
        & (summary["cost_bps"] == PRIMARY_COST_BPS)
        & (summary["period"] == "oos_full")
    ].set_index("factor")
    zoo_table = primary_table.loc[list(ZOO_FACTORS)]
    positive_sharpe = int((zoo_table["sharpe_difference"] > 0).sum())
    bootstrap_positive = 0
    harvey_positive = 0
    for factor in ZOO_FACTORS:
        inference = full_oos_inference[primary_keys[factor]]
        bootstrap = inference["paired_stationary_bootstrap_sharpe_difference"]
        bootstrap_positive += int(
            bootstrap["ci_2_5"] > 0 and bootstrap_fdr[factor] < 0.05
        )
        alpha = inference["spanning_regression_hac"]
        harvey_positive += int(
            alpha["alpha_hac_t"] > 3.0 and alpha_fdr[factor] < 0.05
        )

    subperiod_primary = summary[
        (summary["variant"] == PRIMARY_VARIANT)
        & (summary["cost_bps"] == PRIMARY_COST_BPS)
        & (summary["period"].isin(["oos_2000_2012", "oos_2013_latest"]))
        & (summary["factor"].isin(ZOO_FACTORS))
    ]
    factors_positive_both_subperiods = int(
        (subperiod_primary.groupby("factor")["sharpe_difference"].min() > 0).sum()
    )
    # Pre-registered gate (README "事前成功標準"), scaled to the six-factor zoo.
    conditional_support = (
        positive_sharpe >= 4
        and bootstrap_positive >= 2
        and harvey_positive >= 2
        and factors_positive_both_subperiods >= 2
    )
    market_reference = {
        "note": (
            "Mkt-RF replication reference; excluded from the zoo BH-FDR family "
            "because it is a pre-specified check, not a discovery hypothesis."
        ),
        "oos_sharpe_difference": float(primary_table.loc["MktRF", "sharpe_difference"]),
        "inference": full_oos_inference[primary_keys["MktRF"]],
    }
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
        # Count and median are over the SIX ZOO FACTORS only.  Including Mkt-RF
        # would contaminate the zoo statistic with the reference cell -- and in the
        # direction that flatters vol-managing (it would report 2/7 positive when
        # the zoo truth is 1/6).  per_factor keeps all seven, which is explicit.
        zoo_cost_table = table.loc[list(ZOO_FACTORS)]
        cost_survival[str(cost_bps)] = {
            "zoo_positive_sharpe_difference_count": int(
                (zoo_cost_table["sharpe_difference"] > 0).sum()
            ),
            "zoo_factor_count": len(ZOO_FACTORS),
            "zoo_median_sharpe_difference": float(
                zoo_cost_table["sharpe_difference"].median()
            ),
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

    def cell(cost_bps: int, period: str) -> pd.DataFrame:
        return summary[
            (summary["variant"] == PRIMARY_VARIANT)
            & (summary["cost_bps"] == cost_bps)
            & (summary["period"] == period)
        ].set_index("factor")

    is_gross = cell(0, "in_sample")
    oos_gross = cell(0, "oos_full")
    oos_net = cell(PRIMARY_COST_BPS, "oos_full")

    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.4), sharey=True)
    x = np.arange(len(FACTORS))
    width = 0.36

    axes[0].bar(
        x - width / 2,
        [float(is_gross.loc[f, "sharpe_difference"]) for f in FACTORS],
        width,
        label="In-sample (calibration window)",
        color="#059669",
    )
    axes[0].bar(
        x + width / 2,
        [float(oos_gross.loc[f, "sharpe_difference"]) for f in FACTORS],
        width,
        label="Out-of-sample (2000+)",
        color="#dc2626",
    )
    axes[0].set_title("A. In-sample vs out-of-sample (gross, 0bp)")
    axes[0].set_ylabel("Managed minus unmanaged Sharpe")

    axes[1].bar(
        x - width / 2,
        [float(oos_gross.loc[f, "sharpe_difference"]) for f in FACTORS],
        width,
        label="OOS gross (0bp)",
        color="#dc2626",
    )
    axes[1].bar(
        x + width / 2,
        [float(oos_net.loc[f, "sharpe_difference"]) for f in FACTORS],
        width,
        label=f"OOS net ({PRIMARY_COST_BPS}bp overlay)",
        color="#7c2d12",
    )
    axes[1].set_title(f"B. OOS gross vs net ({PRIMARY_COST_BPS}bp overlay lower bound)")

    for ax in axes:
        ax.axhline(0.0, color="black", linewidth=0.8)
        ax.set_xticks(x, FACTORS)
        ax.legend(frameon=False)
    fig.suptitle(
        "K1702: volatility-managed factor zoo, fixed-calibration real-time OOS",
        fontsize=12,
    )
    fig.tight_layout()
    fig.savefig(BASE_DIR / "is_vs_oos_gross_vs_net.png", dpi=170)
    plt.close(fig)

    # Does vol-managing actually REDUCE DRAWDOWN, or merely reduce EXPOSURE?
    # The project knowledge base carries the claim (orphan entry "R3", and K1265)
    # that "MDD improvement is robust (5/6 factors) while Sharpe is unchanged".
    # But raw MDD is not scale-invariant: a series running at a quarter of the
    # benchmark's exposure has a shallower drawdown mechanically.  So the claim is
    # tested BOTH ways -- raw, and per unit of realized volatility.
    drawdown_rows = {
        factor: {
            "managed_max_drawdown": float(primary_table.loc[factor, "managed_max_drawdown"]),
            "unmanaged_max_drawdown": float(
                primary_table.loc[factor, "unmanaged_max_drawdown"]
            ),
            "managed_mdd_per_annual_vol": float(
                primary_table.loc[factor, "managed_mdd_per_annual_vol"]
            ),
            "unmanaged_mdd_per_annual_vol": float(
                primary_table.loc[factor, "unmanaged_mdd_per_annual_vol"]
            ),
            "managed_annual_volatility": float(
                primary_table.loc[factor, "managed_annual_volatility"]
            ),
            "unmanaged_annual_volatility": float(
                primary_table.loc[factor, "unmanaged_annual_volatility"]
            ),
        }
        for factor in ZOO_FACTORS
    }
    raw_mdd_improved = sum(
        row["managed_max_drawdown"] > row["unmanaged_max_drawdown"]
        for row in drawdown_rows.values()
    )
    scaled_mdd_improved = sum(
        row["managed_mdd_per_annual_vol"] > row["unmanaged_mdd_per_annual_vol"]
        for row in drawdown_rows.values()
    )
    drawdown_analysis = {
        "_question": (
            "Is the widely-reported 'vol-managing compresses drawdown' result a real "
            "risk-timing skill, or a mechanical consequence of holding less exposure?"
        ),
        "raw_mdd_improved_count": int(raw_mdd_improved),
        "vol_normalized_mdd_improved_count": int(scaled_mdd_improved),
        "zoo_factor_count": len(ZOO_FACTORS),
        "_interpretation": (
            "Raw MDD is NOT scale-invariant; MDD per unit of realized volatility is. "
            "If the raw count is high but the vol-normalized count collapses, the "
            "'drawdown benefit' is mostly just lower exposure, not better risk timing."
        ),
        "per_factor": drawdown_rows,
    }

    mm_replication = moreira_muir_replication(ff3_path)

    payload: dict[str, Any] = {
        "experiment_id": "k1702",
        "moreira_muir_replication_check": mm_replication,
        "title": "Volatility-managed factor zoo: fixed-calibration real-time OOS audit",
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "methodology_type": "empirical",
        "verdict": verdict,
        "data": {
            "sources": {
                "ff3_daily_for_mm_replication": {
                    "url": FF3_URL,
                    "sha256": sha256(ff3_path),
                    "role": "1926+ market factor, used only for the Moreira-Muir replication gate",
                },
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
            "zoo_factors_tested": list(ZOO_FACTORS),
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
                "strategy_dm_test_source": "volpred.stats.model_evaluation.strategy_dm_test",
                "dm_hac_bandwidth": "canonical ceil(h^(1/3) * n^(1/3)), from volpred dm_test",
                "spanning_hac_bandwidth": "max(h-1, ceil(h^(1/3) * n^(1/3))); acf and lag grid reported per cell",
                "hac_lag_grid": list(HAC_LAG_GRID),
                "harvey_abs_t_threshold": 3.0,
                "stationary_bootstrap_reps": N_BOOT,
                "stationary_bootstrap_mean_block_months": BOOT_MEAN_BLOCK,
                "multiple_testing": (
                    "Benjamini-Hochberg across the six zoo factors; Mkt-RF is a "
                    "pre-specified replication reference and is excluded from the family"
                ),
                "cross_factor_pooling": (
                    "Equal-weight aggregation ACROSS factors WITHIN each month, then "
                    "time-series DM/HAC on the single monthly series. No stacked "
                    "factor-month test is reported: same-month factors share a market shock."
                ),
            },
        },
        "market_reference_mktrf": market_reference,
        "drawdown_analysis": drawdown_analysis,
        "multifactor_equal_weight_zoo": multifactor,
        "calibration": calibration,
        "primary_gate": {
            "_gate_statistics": (
                "SCALE-INVARIANT only: paired Sharpe bootstrap and spanning alpha. "
                "The mean-return DM is explicitly NOT a gate input -- the managed "
                "series runs at much lower exposure, so its raw mean return is "
                "mechanically lower and a DM gate could never fire."
            ),
            "positive_sharpe_factors": positive_sharpe,
            "zoo_factor_count": len(ZOO_FACTORS),
            "bootstrap_positive_fdr_factors": bootstrap_positive,
            "alpha_harvey_positive_fdr_factors": harvey_positive,
            "factors_positive_both_subperiods": factors_positive_both_subperiods,
            "conditional_support": conditional_support,
        },
        "primary_multiple_testing": {
            "bootstrap_raw_p": primary_boot_p,
            "bootstrap_bh_q": bootstrap_fdr,
            "spanning_alpha_raw_p": primary_alpha_p,
            "spanning_alpha_bh_q": alpha_fdr,
            "_dm_is_diagnostic_not_a_gate": (
                "scale-dependent mean-return test; retained for transparency only"
            ),
            "dm_raw_p": primary_dm_p,
            "dm_bh_q": dm_fdr,
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
            "is_vs_oos_gross_vs_net.png",
        ],
    }
    atomic_write_json(RESULTS_PATH, payload)
    print(json.dumps(json_ready(payload["primary_gate"]), indent=2))
    print(f"verdict={verdict}")
    print(f"results={RESULTS_PATH}")


if __name__ == "__main__":
    main()
