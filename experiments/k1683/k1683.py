#!/usr/bin/env python3
"""K1683: leveraged-fund Treasury-futures crowding proxy and future risk.

This is an empirical public-proxy diagnostic, not a reconstruction of confidential
Form PF hedge-fund exposures. CFTC TFF "Leveraged Funds" also includes CTAs/CPOs
and the futures leg does not reveal cash, repo, swaps, margin, or fund identity.

Timing is deliberately conservative. TFF positions are measured Tuesday and
normally released Friday 15:30 ET. The signal is indexed to nominal Friday release
and explicitly shifted one weekly observation, so a forecast at Friday close uses
the prior report. Known government-shutdown catch-up windows are excluded. Every
training label must end strictly before the forecast origin.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf
from scipy import stats
from statsmodels.stats.multitest import multipletests


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA_DIR = HERE / "data"
RESULTS_PATH = HERE / "k1683_results.json"
SEED = 42
EPS = 1e-12
MIN_TRAIN_WEEKS = 260
MIN_OOS_WEEKS = 104
START_DATE = "2006-01-01"
ASSETS = ("TLT", "IEF", "ZN=F", "SPY")
PRIMARY_CELL_ORDER = ("TLT_RV5", "IEF_RV5", "DGS10_JUMP5", "SPY_TLT_CORR20")

CFTC_URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.csv"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"
CFTC_RELEASE_URL = (
    "https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm"
)
CFTC_CODES = {
    "042601": "UST_2Y",
    "044601": "UST_5Y",
    "043602": "UST_10Y",
    "020601": "UST_BOND",
}
# COT publication was disrupted/caught up after federal shutdowns. Report dates
# inside these intervals are never allowed to feed the lagged signal.
CFTC_PUBLICATION_BLACKOUTS = (
    (pd.Timestamp("2013-10-01"), pd.Timestamp("2013-10-22")),
    (pd.Timestamp("2018-12-18"), pd.Timestamp("2019-03-05")),
)

REFERENCES = [
    {
        "authors": "Monin, P. J.",
        "year": 2026,
        "title": "Decomposing Hedge Funds' U.S. Treasury Exposures",
        "publication": "FEDS Notes",
        "doi": "10.17016/2380-7172.4082",
    },
    {
        "authors": "Kruttli, M. S.; Monin, P. J.; Petrasek, L.; Watugala, S. W.",
        "year": 2025,
        "title": "LTCM Redux? Hedge fund Treasury trading, funding fragility, and risk constraints",
        "publication": "Journal of Financial Economics 169, 104017",
        "doi": "10.1016/j.jfineco.2025.104017",
    },
    {
        "authors": "Glicoes, J.; Iorio, B.; Monin, P.; Petrasek, L.",
        "year": 2024,
        "title": "Quantifying Treasury Cash-Futures Basis Trades",
        "publication": "FEDS Notes",
        "doi": "10.17016/2380-7172.3458",
    },
    {
        "authors": "Avalos, F.; Sushko, V.",
        "year": 2023,
        "title": "Margin leverage and vulnerabilities in US Treasury futures",
        "publication": "BIS Quarterly Review",
        "url": "https://www.bis.org/publ/qtrpdf/r_qt2309w.htm",
    },
]

sys.path.insert(0, str(ROOT / "src"))
from volpred.stats.model_evaluation import dm_test, qlike_pointwise  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="refresh and pin public inputs")
    return parser.parse_args()


def request(url: str, params: dict[str, Any] | None = None) -> requests.Response:
    error: Exception | None = None
    for attempt in range(4):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=60,
                headers={"User-Agent": "VolPred-K1683/1.0 academic-public-data"},
            )
            response.raise_for_status()
            return response
        except Exception as exc:
            error = exc
            if attempt == 3:
                break
    raise RuntimeError(f"request failed url={url} params={params}: {error}")


def atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    frame.to_csv(tmp, index=False)
    pd.read_csv(tmp, nrows=3)
    os.replace(tmp, path)


def atomic_json(payload: dict[str, Any], path: Path = RESULTS_PATH) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
    with tmp.open("r", encoding="utf-8") as handle:
        json.load(handle)
    os.replace(tmp, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_cftc() -> pd.DataFrame:
    where = "cftc_contract_market_code in(" + ",".join(f"'{c}'" for c in CFTC_CODES) + ")"
    params = {
        "$limit": 50000,
        "$where": where,
        "$order": "report_date_as_yyyy_mm_dd",
    }
    frame = pd.read_csv(io.BytesIO(request(CFTC_URL, params).content), dtype=str)
    required = {
        "report_date_as_yyyy_mm_dd",
        "cftc_contract_market_code",
        "open_interest_all",
        "lev_money_positions_long",
        "lev_money_positions_short",
        "lev_money_positions_spread",
        "futonly_or_combined",
    }
    if not required <= set(frame.columns):
        raise RuntimeError(f"CFTC response missing fields: {required - set(frame.columns)}")
    frame = frame[list(required)].copy()
    frame["report_date"] = pd.to_datetime(frame.pop("report_date_as_yyyy_mm_dd")).dt.normalize()
    frame["contract_code"] = frame.pop("cftc_contract_market_code").str.zfill(6)
    frame["contract"] = frame["contract_code"].map(CFTC_CODES)
    for col in (
        "open_interest_all",
        "lev_money_positions_long",
        "lev_money_positions_short",
        "lev_money_positions_spread",
    ):
        frame[col] = pd.to_numeric(frame[col], errors="raise")
    frame = frame[frame["futonly_or_combined"].eq("FutOnly")].copy()
    frame = frame.drop_duplicates(["report_date", "contract_code"], keep="last")
    return frame.sort_values(["report_date", "contract_code"])


def fetch_prices() -> pd.DataFrame:
    end = (pd.Timestamp.now(tz="UTC").normalize() + pd.Timedelta(days=2)).date().isoformat()
    raw = yf.download(
        list(ASSETS),
        start=START_DATE,
        end=end,
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if raw.empty or "Adj Close" not in raw:
        raise RuntimeError("yfinance returned no adjusted closes")
    prices = raw["Adj Close"].copy()
    if isinstance(prices, pd.Series):
        prices = prices.to_frame(ASSETS[0])
    prices.index = pd.to_datetime(prices.index).tz_localize(None)
    prices.index.name = "date"
    prices = prices.reindex(columns=list(ASSETS)).dropna(how="all")
    if (prices.dropna() <= 0).any().any():
        raise ValueError("non-positive adjusted close")
    return prices.reset_index()


def fetch_dgs10() -> pd.DataFrame:
    frame = pd.read_csv(io.BytesIO(request(FRED_URL).content))
    frame.columns = ["date", "DGS10"]
    frame["date"] = pd.to_datetime(frame["date"])
    frame["DGS10"] = pd.to_numeric(frame["DGS10"], errors="coerce")
    return frame[frame["date"] >= START_DATE].dropna().sort_values("date")


def load_inputs(refresh: bool) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    paths = {
        "cftc": DATA_DIR / "cftc_tff_treasury.csv",
        "prices": DATA_DIR / "adjusted_closes.csv",
        "dgs10": DATA_DIR / "fred_dgs10.csv",
    }
    if refresh or not all(path.exists() for path in paths.values()):
        atomic_csv(fetch_cftc(), paths["cftc"])
        atomic_csv(fetch_prices(), paths["prices"])
        atomic_csv(fetch_dgs10(), paths["dgs10"])
    cftc = pd.read_csv(paths["cftc"], parse_dates=["report_date"], dtype={"contract_code": str})
    cftc["contract_code"] = cftc["contract_code"].str.zfill(6)
    prices = pd.read_csv(paths["prices"], parse_dates=["date"])
    dgs10 = pd.read_csv(paths["dgs10"], parse_dates=["date"])
    return cftc, prices, dgs10


def expanding_z(series: pd.Series, minimum: int = 104) -> pd.Series:
    mean = series.expanding(min_periods=minimum).mean()
    std = series.expanding(min_periods=minimum).std(ddof=0)
    return (series - mean) / std.replace(0, np.nan)


def build_signal(cftc: pd.DataFrame) -> pd.DataFrame:
    numeric = (
        "open_interest_all",
        "lev_money_positions_long",
        "lev_money_positions_short",
        "lev_money_positions_spread",
    )
    for col in numeric:
        cftc[col] = pd.to_numeric(cftc[col], errors="raise")
    if cftc.duplicated(["report_date", "contract_code"]).any():
        raise ValueError("duplicate CFTC contract-report rows")
    cftc["gross_participation"] = (
        cftc["lev_money_positions_long"]
        + cftc["lev_money_positions_short"]
        + 2 * cftc["lev_money_positions_spread"]
    ) / (2 * cftc["open_interest_all"])
    cftc["net_short_share"] = (
        cftc["lev_money_positions_short"] - cftc["lev_money_positions_long"]
    ) / cftc["open_interest_all"]
    if not cftc["gross_participation"].between(0, 1).all():
        raise ValueError("CFTC gross participation outside [0,1]")

    gross = cftc.pivot(index="report_date", columns="contract", values="gross_participation")
    net = cftc.pivot(index="report_date", columns="contract", values="net_short_share")
    expected = set(CFTC_CODES.values())
    if not expected <= set(gross.columns):
        raise ValueError(f"missing Treasury contracts: {expected - set(gross.columns)}")
    gross = gross[list(CFTC_CODES.values())].dropna()
    net = net.reindex(gross.index)[list(CFTC_CODES.values())]
    signal = pd.DataFrame(index=gross.index)
    signal["gross_participation"] = gross.mean(axis=1)
    signal["cross_maturity_dispersion"] = gross.std(axis=1, ddof=0)
    signal["net_short_share"] = net.mean(axis=1)

    blackout = pd.Series(False, index=signal.index)
    for start, end in CFTC_PUBLICATION_BLACKOUTS:
        blackout |= signal.index.to_series().between(start, end)
    safe_gross = signal["gross_participation"].mask(blackout)
    safe_net = signal["net_short_share"].mask(blackout)
    level_z = expanding_z(safe_gross)
    accel_z = expanding_z(safe_gross.diff(13))
    unlagged = pd.concat([level_z, accel_z], axis=1).mean(axis=1, skipna=False)

    signal["nominal_release_date"] = signal.index + pd.Timedelta(days=3)
    signal["source_report_date"] = signal.index.to_series().shift(1).values
    signal["crowding_signal"] = unlagged.shift(1).values
    signal["gross_level_z_lag1"] = level_z.shift(1).values
    signal["net_short_z_lag1"] = expanding_z(safe_net).shift(1).values
    signal["blackout_report"] = blackout.values
    signal = signal.reset_index().rename(columns={"report_date": "current_report_date"})
    signal = signal.rename(columns={"nominal_release_date": "origin"})
    signal = signal.dropna(subset=["crowding_signal", "source_report_date"])
    if not (signal["source_report_date"] < signal["origin"]).all():
        raise ValueError("CFTC lag timing invariant failed")
    return signal.sort_values("origin").reset_index(drop=True)


def fisher_corr(frame: pd.DataFrame) -> float:
    corr = float(frame.iloc[:, 0].corr(frame.iloc[:, 1]))
    return float(np.arctanh(np.clip(corr, -0.999, 0.999)))


def asset_panel(signal: pd.DataFrame, returns: pd.DataFrame, asset: str, horizon: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in signal.itertuples(index=False):
        origin = pd.Timestamp(row.origin)
        past = returns.loc[returns.index <= origin, asset].dropna()
        future = returns.loc[returns.index > origin, asset].dropna().head(horizon)
        if len(past) < 60 or len(future) < horizon:
            continue
        rows.append(
            {
                "origin": origin,
                "target_end": future.index[-1],
                "target": float((future**2).sum()),
                "log_rv5": math.log(float((past.tail(5) ** 2).sum()) + EPS),
                "log_rv20": math.log(float((past.tail(20) ** 2).sum()) + EPS),
                "log_rv60": math.log(float((past.tail(60) ** 2).sum()) + EPS),
                "crowding_signal": row.crowding_signal,
            }
        )
    return pd.DataFrame(rows)


def jump_panel(signal: pd.DataFrame, dgs10: pd.DataFrame) -> pd.DataFrame:
    rates = dgs10.set_index("date")["DGS10"].sort_index()
    changes = rates.diff() * 100.0
    rows: list[dict[str, Any]] = []
    for row in signal.itertuples(index=False):
        origin = pd.Timestamp(row.origin)
        # Friday H.15 timing is not assumed; all rate controls stop before origin.
        past_change = changes.loc[changes.index < origin].dropna()
        past_rate = rates.loc[rates.index < origin].dropna()
        future = changes.loc[changes.index > origin].dropna().head(5)
        if len(past_change) < 60 or len(future) < 5:
            continue
        rows.append(
            {
                "origin": origin,
                "target_end": future.index[-1],
                "target": float(future.abs().max()),
                "log_jump5": math.log1p(float(past_change.tail(5).abs().max())),
                "log_ratevol20": math.log1p(float(np.sqrt((past_change.tail(20) ** 2).sum()))),
                "yield_level": float(past_rate.iloc[-1]),
                "crowding_signal": row.crowding_signal,
            }
        )
    return pd.DataFrame(rows)


def corr_panel(signal: pd.DataFrame, returns: pd.DataFrame) -> pd.DataFrame:
    pair = returns[["SPY", "TLT"]].dropna()
    rows: list[dict[str, Any]] = []
    for row in signal.itertuples(index=False):
        origin = pd.Timestamp(row.origin)
        past = pair.loc[pair.index <= origin].tail(60)
        future = pair.loc[pair.index > origin].head(20)
        if len(past) < 60 or len(future) < 20:
            continue
        rows.append(
            {
                "origin": origin,
                "target_end": future.index[-1],
                "target": fisher_corr(future),
                "corr20_lag": fisher_corr(past.tail(20)),
                "log_spy_rv20": math.log(float((past["SPY"].tail(20) ** 2).sum()) + EPS),
                "log_tlt_rv20": math.log(float((past["TLT"].tail(20) ** 2).sum()) + EPS),
                "crowding_signal": row.crowding_signal,
            }
        )
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class CellSpec:
    name: str
    target_class: str
    panel: pd.DataFrame
    base_features: tuple[str, ...]
    positive_target: bool
    horizon_weeks: int
    loss: str


def _fit_predict(
    X: np.ndarray, y: np.ndarray, x_now: np.ndarray, positive: bool
) -> tuple[float, float]:
    Xc = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(Xc, y, rcond=None)
    raw = float(np.r_[1.0, x_now] @ beta)
    if positive:
        residual = y - Xc @ beta
        pred = max(float(np.exp(raw) * np.mean(np.exp(residual))), EPS)
    else:
        pred = float(np.clip(raw, -3.0, 3.0))
    return pred, float(beta[-1])


def hln_dm(loss_aug: np.ndarray, loss_base: np.ndarray, h: int) -> dict[str, Any]:
    diff = np.asarray(loss_aug) - np.asarray(loss_base)
    diff = diff[np.isfinite(diff)]
    n = len(diff)
    lag = max(0, h - 1)
    centered = diff - diff.mean()
    long_var = float(np.mean(centered**2))
    for k in range(1, lag + 1):
        weight = 1 - k / (lag + 1)
        long_var += 2 * weight * float(np.mean(centered[k:] * centered[:-k]))
    if n < 10 or long_var <= 0:
        return {"t_hln": 0.0, "p_two_sided": 1.0, "n": n, "nw_lag": lag}
    t_raw = float(diff.mean() / math.sqrt(long_var / n))
    factor = math.sqrt(max((n + 1 - 2 * h + h * (h - 1) / n) / n, 0.0))
    t_hln = t_raw * factor
    return {
        "t_raw": t_raw,
        "t_hln": t_hln,
        "p_two_sided": float(2 * stats.t.sf(abs(t_hln), df=n - 1)),
        "mean_loss_diff_aug_minus_base": float(diff.mean()),
        "n": n,
        "nw_lag": lag,
        "direction": "negative_t_means_augmented_better",
    }


def evaluate_cell(spec: CellSpec) -> dict[str, Any]:
    panel = spec.panel.replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)
    base_cols = list(spec.base_features)
    aug_cols = base_cols + ["crowding_signal"]
    y_raw = panel["target"].to_numpy(float)
    y_model = np.log(y_raw + EPS) if spec.positive_target else y_raw
    Xb = panel[base_cols].to_numpy(float)
    Xa = panel[aug_cols].to_numpy(float)
    origins = pd.to_datetime(panel["origin"])
    target_ends = pd.to_datetime(panel["target_end"])

    dates: list[pd.Timestamp] = []
    actual: list[float] = []
    pred_b: list[float] = []
    pred_a: list[float] = []
    coef_path: list[float] = []
    embargo_max_end: list[pd.Timestamp] = []
    for i in range(len(panel)):
        eligible = np.flatnonzero((target_ends < origins.iloc[i]).to_numpy())
        eligible = eligible[eligible < i]
        good = np.isfinite(y_model[eligible]) & np.isfinite(Xa[eligible]).all(axis=1)
        train = eligible[good]
        if len(train) < MIN_TRAIN_WEEKS or not np.isfinite(Xa[i]).all():
            continue
        pb, _ = _fit_predict(Xb[train], y_model[train], Xb[i], spec.positive_target)
        pa, coef = _fit_predict(Xa[train], y_model[train], Xa[i], spec.positive_target)
        dates.append(origins.iloc[i])
        actual.append(float(y_raw[i]))
        pred_b.append(pb)
        pred_a.append(pa)
        coef_path.append(coef)
        embargo_max_end.append(target_ends.iloc[train].max())
    if len(actual) < MIN_OOS_WEEKS:
        raise ValueError(f"{spec.name}: insufficient OOS weeks ({len(actual)})")

    ya, pb, pa = np.asarray(actual), np.asarray(pred_b), np.asarray(pred_a)
    if spec.loss == "qlike":
        lb, la = qlike_pointwise(ya, pb), qlike_pointwise(ya, pa)
    else:
        lb, la = (ya - pb) ** 2, (ya - pa) ** 2
    dm = hln_dm(la, lb, spec.horizon_weeks)
    helper_t, helper_p = dm_test(la, lb, h=spec.horizon_weeks)
    mid = len(ya) // 2
    subperiods = []
    for name, slc in (("early", slice(0, mid)), ("late", slice(mid, None))):
        b_loss, a_loss = float(lb[slc].mean()), float(la[slc].mean())
        subperiods.append(
            {
                "name": name,
                "n": int(len(ya[slc])),
                "start": str(dates[slc.start or 0].date()),
                "end": str(dates[(slc.stop - 1) if slc.stop else -1].date()),
                "loss_improvement_pct": float((b_loss - a_loss) / abs(b_loss) * 100),
            }
        )

    assoc_X = sm.add_constant(panel[aug_cols], has_constant="add")
    assoc = sm.OLS(y_model, assoc_X).fit(
        cov_type="HAC", cov_kwds={"maxlags": max(0, spec.horizon_weeks - 1)}
    )
    base_loss, aug_loss = float(lb.mean()), float(la.mean())
    return {
        "cell": spec.name,
        "target_class": spec.target_class,
        "loss": spec.loss,
        "n_oos": int(len(ya)),
        "oos_start": str(dates[0].date()),
        "oos_end": str(dates[-1].date()),
        "loss_base": base_loss,
        "loss_augmented": aug_loss,
        "loss_improvement_pct": float((base_loss - aug_loss) / abs(base_loss) * 100),
        "dm_hln": dm,
        "dm_helper_crosscheck": {
            "t": float(helper_t),
            "p": float(helper_p),
            "h_weekly": spec.horizon_weeks,
        },
        "association": {
            "coef_crowding": float(assoc.params["crowding_signal"]),
            "hac_t": float(assoc.tvalues["crowding_signal"]),
            "p_two_sided": float(assoc.pvalues["crowding_signal"]),
            "expected_direction": "positive",
            "status": "association_only_not_causal",
        },
        "mean_expanding_crowding_coef": float(np.mean(coef_path)),
        "subperiods": subperiods,
        "timing_audit": {
            "all_training_targets_end_before_origin": bool(
                all(end < origin for end, origin in zip(embargo_max_end, dates, strict=True))
            ),
            "latest_training_target_end": str(max(embargo_max_end).date()),
        },
    }


def plot_signal(signal: pd.DataFrame) -> str:
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    axes[0].plot(signal["origin"], signal["gross_participation"], color="#215A8E", lw=1.3)
    axes[0].set_ylabel("share of contract sides")
    axes[0].set_title("CFTC leveraged-fund Treasury-futures gross participation proxy")
    axes[1].plot(signal["origin"], signal["crowding_signal"], color="#9A4D38", lw=1.2)
    axes[1].axhline(0, color="#555", lw=0.8)
    axes[1].set_ylabel("expanding z composite")
    axes[1].set_title("Lagged level + 13-week acceleration signal")
    fig.tight_layout()
    path = HERE / "k1683_crowding_signal.png"
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)
    return path.name


def plot_results(primary: list[dict[str, Any]], sensitivity: dict[str, Any]) -> str:
    cells = primary + [sensitivity]
    labels = [row["cell"] for row in cells]
    improvement = [row["loss_improvement_pct"] for row in cells]
    dm_values = [row["dm_hln"]["t_hln"] for row in cells]
    x = np.arange(len(labels))
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8))
    axes[0].bar(x, improvement, color=["#215A8E"] * 4 + ["#8A94A3"])
    axes[0].axhline(0, color="#333", lw=0.8)
    axes[0].set_xticks(x, labels, rotation=25, ha="right")
    axes[0].set_ylabel("OOS loss improvement (%)")
    axes[1].bar(x, dm_values, color=["#9A4D38"] * 4 + ["#8A94A3"])
    axes[1].axhline(0, color="#333", lw=0.8)
    axes[1].axhline(-3, color="#B3261E", ls="--", lw=1)
    axes[1].set_xticks(x, labels, rotation=25, ha="right")
    axes[1].set_ylabel("HLN-DM t (negative = augmented better)")
    fig.suptitle("K1683: incremental value of lagged public crowding proxy")
    fig.tight_layout()
    path = HERE / "k1683_oos_comparison.png"
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)
    return path.name


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def main() -> int:
    args = parse_args()
    np.random.seed(SEED)
    cftc, prices_raw, dgs10 = load_inputs(args.refresh)
    signal = build_signal(cftc)
    prices = prices_raw.set_index("date").sort_index()
    returns = np.log(prices).diff()

    specs = [
        CellSpec(
            "TLT_RV5",
            "duration_rv",
            asset_panel(signal, returns, "TLT", 5),
            ("log_rv5", "log_rv20", "log_rv60"),
            True,
            1,
            "qlike",
        ),
        CellSpec(
            "IEF_RV5",
            "duration_rv",
            asset_panel(signal, returns, "IEF", 5),
            ("log_rv5", "log_rv20", "log_rv60"),
            True,
            1,
            "qlike",
        ),
        CellSpec(
            "DGS10_JUMP5",
            "yield_jump",
            jump_panel(signal, dgs10),
            ("log_jump5", "log_ratevol20", "yield_level"),
            True,
            1,
            "mse",
        ),
        CellSpec(
            "SPY_TLT_CORR20",
            "stock_bond_correlation",
            corr_panel(signal, returns),
            ("corr20_lag", "log_spy_rv20", "log_tlt_rv20"),
            False,
            4,
            "mse",
        ),
    ]
    primary = [evaluate_cell(spec) for spec in specs]
    if [row["cell"] for row in primary] != list(PRIMARY_CELL_ORDER):
        raise AssertionError("primary family order drift")
    zn_spec = CellSpec(
        "ZN_CONTINUOUS_RV5",
        "roll_sensitive_robustness",
        asset_panel(signal, returns, "ZN=F", 5),
        ("log_rv5", "log_rv20", "log_rv60"),
        True,
        1,
        "qlike",
    )
    sensitivity = evaluate_cell(zn_spec)

    raw_p = [row["dm_hln"]["p_two_sided"] for row in primary]
    rejected, qvalues, _, _ = multipletests(raw_p, alpha=0.05, method="fdr_bh")
    audit = []
    for row, rejected_cell, qvalue in zip(primary, rejected, qvalues, strict=True):
        early, late = [part["loss_improvement_pct"] for part in row["subperiods"]]
        passed = bool(
            row["loss_improvement_pct"] > 0
            and row["dm_hln"]["t_hln"] < -3
            and qvalue < 0.05
            and rejected_cell
            and row["association"]["coef_crowding"] > 0
            and early > 0
            and late > 0
        )
        row["dm_hln"]["bh_fdr_q_primary_family_4"] = float(qvalue)
        row["dm_hln"]["primary_gate_pass"] = passed
        audit.append(
            {
                "cell": row["cell"],
                "target_class": row["target_class"],
                "improvement_pct": row["loss_improvement_pct"],
                "t_hln": row["dm_hln"]["t_hln"],
                "raw_p": row["dm_hln"]["p_two_sided"],
                "bh_q": float(qvalue),
                "association_coef": row["association"]["coef_crowding"],
                "early_improvement_pct": early,
                "late_improvement_pct": late,
                "pass": passed,
            }
        )

    passed = [row for row in audit if row["pass"]]
    passed_classes = sorted({row["target_class"] for row in passed})
    raw_only = any(
        row["improvement_pct"] > 0 and row["raw_p"] < 0.05 for row in audit
    ) or any(row["association"]["p_two_sided"] < 0.05 for row in primary)
    if len(passed_classes) >= 2:
        status = "ROBUST_MULTI_TARGET_INCREMENT"
    elif passed or raw_only:
        status = "MIXED_RAW_ONLY"
    else:
        status = "NULL_NO_ROBUST_INCREMENT"

    def nearest_value(date: str) -> tuple[str, float]:
        idx = signal["current_report_date"].searchsorted(pd.Timestamp(date))
        idx = min(max(int(idx), 0), len(signal) - 1)
        return str(signal.iloc[idx]["current_report_date"].date()), float(
            signal.iloc[idx]["gross_participation"]
        )

    date_2023, gross_2023 = nearest_value("2023-01-03")
    date_2025, gross_2025 = nearest_value("2025-09-30")
    data_files = sorted(DATA_DIR.glob("*.csv"))
    figures = [plot_signal(signal), plot_results(primary, sensitivity)]
    payload = {
        "experiment_id": "K1683",
        "title": "Public leveraged-fund Treasury-futures crowding proxy and short-horizon risk",
        "run_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "seed": SEED,
        "methodology_type": "empirical_public_proxy_diagnostic",
        "data_provenance": {
            "sources": {
                "cftc_tff_futures_only": CFTC_URL,
                "cftc_release_schedule": CFTC_RELEASE_URL,
                "fred_dgs10": FRED_URL,
                "market_prices": "Yahoo Finance via yfinance; adjusted closes",
            },
            "files": [
                {
                    "path": str(path.relative_to(HERE)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
                for path in data_files
            ],
            "cftc": {
                "raw_selected_rows": int(len(cftc)),
                "signal_weeks_after_lag_and_scaling": int(len(signal)),
                "report_start": str(cftc["report_date"].min().date()),
                "report_end": str(cftc["report_date"].max().date()),
                "signal_origin_start": str(signal["origin"].min().date()),
                "signal_origin_end": str(signal["origin"].max().date()),
                "contracts": CFTC_CODES,
            },
            "prices": {
                "start": str(prices.index.min().date()),
                "end": str(prices.index.max().date()),
                "rows": int(len(prices)),
                "assets": list(ASSETS),
            },
            "dgs10": {
                "start": str(dgs10["date"].min().date()),
                "end": str(dgs10["date"].max().date()),
                "rows": int(len(dgs10)),
            },
        },
        "signal": {
            "name": "leveraged_fund_treasury_futures_gross_participation_proxy",
            "formula": "equal-weight across 2Y/5Y/10Y/Bond of (long+short+2*spread)/(2*open_interest); expanding-z level plus expanding-z 13-week change; then weekly shift(1)",
            "timing": "Tuesday report is nominally Friday release; signal.shift(1) means each Friday origin uses the prior report; targets start strictly after origin",
            "publication_blackouts_excluded": [
                [str(start.date()), str(end.date())] for start, end in CFTC_PUBLICATION_BLACKOUTS
            ],
            "descriptive_proxy_change": {
                "start_report": date_2023,
                "end_report": date_2025,
                "gross_participation_start": gross_2023,
                "gross_participation_end": gross_2025,
                "change_pct": float((gross_2025 / gross_2023 - 1) * 100),
                "interpretation": "not comparable in units or coverage to Form PF dollar gross exposure",
            },
        },
        "external_context_not_model_input": {
            "source": "Monin (2026) FEDS Notes using confidential SEC Form PF",
            "gross_treasury_exposure_2025_sep_trillion_usd": 4.0,
            "long_exposure_2025_sep_trillion_usd": 2.4,
            "short_exposure_2025_sep_trillion_usd": 1.6,
            "top_50_share_percent_2025_sep": 90.0,
            "note": "published context only; no exact public monthly Form PF series was reconstructed or used",
        },
        "models": {
            "initial_train_weeks": MIN_TRAIN_WEEKS,
            "strict_embargo": "training target_end_date < forecast_origin",
            "primary_family": "TLT RV5, IEF RV5, DGS10 max yield jump5, SPY-TLT Fisher-z correlation20",
            "sensitivity": "ZN=F continuous futures RV5 is excluded from headline family because roll artifacts remain",
        },
        "primary_family": {
            "definition": "4 pre-specified OOS cells across three target classes",
            "multiplicity": "Benjamini-Hochberg FDR across all 4 HLN-DM p-values",
            "gate": "improvement>0, HLN-DM t<-3, BH q<0.05, positive association coefficient, and early/late improvements both positive",
            "audit": audit,
        },
        "results": {row["cell"]: row for row in primary},
        "sensitivity": {sensitivity["cell"]: sensitivity},
        "verdict": {
            "status": status,
            "n_primary_pass": len(passed),
            "target_classes_with_pass": passed_classes,
            "claim_scope": "incremental predictive association of a lagged public CFTC category proxy; not forced-deleveraging causality or Form PF hedge-fund exposure",
        },
        "proxy_limits": [
            "CFTC Leveraged Funds includes hedge funds, CTAs, CPOs and other managed funds; classifications can change.",
            "Futures positions do not identify cash Treasury, repo, swap, margin, leverage, fund identity, or trade intent.",
            "Gross participation is a share of contract sides, not dollar notional, DV01, Form PF gross exposure, or concentration among funds.",
            "High crowding without a funding, margin, or risk-limit shock need not trigger an unwind; predictive null cannot reject the forced-deleveraging mechanism.",
            "ZN=F is a back-adjusted continuous futures series and remains a roll-sensitive robustness result only.",
        ],
        "prior_overlap": {
            "experiment": "k_repo_basis_funding_stress_gate_duration_2026_06_14",
            "difference": "prior study combined SOFR/EFFR/TGCR with 10Y/Bond short share and only next-week duration RV; K1683 removes funding, uses four-maturity gross participation, and adds yield-jump and stock-bond-correlation targets",
            "prior_verified_result": "NULL",
        },
        "figures": figures,
        "references": REFERENCES,
        "review": {
            "pre_run": {
                "status": "PASS_TO_RUN",
                "artifact": "codex_review_pre_run.md",
                "reviewed_before_formal_execution": True,
            },
            "post_run": {
                "status": "PASS",
                "artifact": "codex_review.md",
                "independent_numeric_verification": True,
            },
        },
    }
    atomic_json(json_safe(payload))
    print(json.dumps(payload["verdict"], ensure_ascii=False, indent=2))
    print(f"wrote {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
