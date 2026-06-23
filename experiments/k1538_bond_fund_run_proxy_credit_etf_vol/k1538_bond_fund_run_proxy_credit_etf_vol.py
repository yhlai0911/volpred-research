"""K1538: bond-fund run-pressure proxy and credit ETF volatility.

Research question
-----------------
Can a free-data proxy for open-end fixed-income fund run pressure lead realized
volatility in credit ETFs?

This is not a fund-level flow/NAV replication. The proxy uses investable bond
ETF prices and volumes, plus public FRED cash-migration series when available.
Every predictive signal is lagged with ``signal_raw.shift(1)`` before it is used
against the target date.
"""

from __future__ import annotations

import json
import math
from io import StringIO
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import yfinance as yf


EXPERIMENT_ID = "K1538"
TASK_ID = "research_bond_mutual_fund_demandable_equity_run_proxy_etf"
SEED = 42
START = "2010-01-01"
END = "2026-06-24"
TRADING_DAYS = 252
RV_WINDOW = 21
ROLL_Z = 252
MIN_TRAIN = 756

BASE_DIR = Path(__file__).resolve().parent
FIG_DIR = BASE_DIR / "figures"
RESULTS_PATH = BASE_DIR / "k1538_bond_fund_run_proxy_credit_etf_vol_results.json"
PANEL_PATH = BASE_DIR / "k1538_bond_fund_run_proxy_credit_etf_vol_daily_panel.csv"

ETF_TICKERS = ["AGG", "BND", "LQD", "HYG", "BKLN", "TLT", "SPY", "^VIX"]
FUND_PROXY_ETFS = ["AGG", "BND", "LQD", "HYG"]
ILLIQUIDITY_ETFS = ["HYG", "LQD", "BKLN"]
TARGETS = ["HYG", "LQD", "BKLN", "TLT"]
HORIZONS = [5, 21]

FRED_SERIES = {
    "bank_deposits": "DPSACBW027SBOG",
    "money_market_assets": "MMMFFAQ027S",
}


@dataclass
class HACTest:
    target: str
    horizon: str
    n_obs: int
    beta: float
    hac_t: float
    hac_p: float
    expected_direction: str
    passes_harvey_t3: bool


@dataclass
class OOSResult:
    target: str
    horizon: str
    n_oos: int
    mse_baseline: float
    mse_augmented: float
    mse_improvement_pct: float
    dm_t_aug_minus_base: float
    dm_p: float
    passes_harvey_t3: bool


def finite(value):
    if isinstance(value, dict):
        return {k: finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [finite(v) for v in value]
    if isinstance(value, tuple):
        return [finite(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        value = float(value)
        return value if math.isfinite(value) else None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return value


def normal_p_value(t_stat: float) -> float:
    return 2.0 * (1.0 - NormalDist().cdf(abs(float(t_stat))))


def rolling_zscore(series: pd.Series, window: int = ROLL_Z) -> pd.Series:
    mean = series.rolling(window, min_periods=max(30, window // 4)).mean()
    std = series.rolling(window, min_periods=max(30, window // 4)).std(ddof=0)
    return (series - mean) / std.replace(0.0, np.nan)


def bh_qvalues(p_values: list[float]) -> list[float]:
    n = len(p_values)
    order = np.argsort(np.asarray(p_values, dtype=float))
    out = np.empty(n, dtype=float)
    running = 1.0
    for reverse_rank, idx in enumerate(order[::-1], start=1):
        rank = n - reverse_rank + 1
        running = min(running, p_values[idx] * n / rank)
        out[idx] = running
    return [float(min(1.0, x)) for x in out]


def hac_mean_test(series: pd.Series, maxlags: int) -> tuple[float, float, float]:
    clean = series.replace([np.inf, -np.inf], np.nan).dropna().to_numpy(dtype=float)
    if len(clean) < max(30, maxlags + 5):
        return float("nan"), float("nan"), float("nan")
    demeaned = clean - clean.mean()
    n = len(clean)
    gamma0 = float(np.dot(demeaned, demeaned) / n)
    long_run_var = gamma0
    for lag in range(1, min(maxlags, n - 1) + 1):
        cov = float(np.dot(demeaned[lag:], demeaned[:-lag]) / n)
        weight = 1.0 - lag / (maxlags + 1.0)
        long_run_var += 2.0 * weight * cov
    se = math.sqrt(max(long_run_var, 0.0) / n) if long_run_var >= 0 else float("nan")
    mean = float(clean.mean())
    t_stat = mean / se if se and math.isfinite(se) and se > 0 else float("nan")
    p_value = normal_p_value(t_stat) if math.isfinite(t_stat) else float("nan")
    return mean, t_stat, p_value


def hac_regression(y: pd.Series, x: pd.DataFrame, maxlags: int) -> tuple[np.ndarray, np.ndarray]:
    df = pd.concat([y.rename("y"), x], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(df) < max(80, 5 * x.shape[1]):
        raise ValueError("insufficient observations for HAC regression")
    yv = df["y"].to_numpy(dtype=float)
    xv = np.column_stack([np.ones(len(df)), df.drop(columns=["y"]).to_numpy(dtype=float)])
    beta = np.linalg.lstsq(xv, yv, rcond=None)[0]
    resid = yv - xv @ beta
    xtx_inv = np.linalg.pinv(xv.T @ xv)
    scores = xv * resid[:, None]
    meat = scores.T @ scores
    for lag in range(1, min(maxlags, len(df) - 1) + 1):
        weight = 1.0 - lag / (maxlags + 1.0)
        gamma = scores[lag:].T @ scores[:-lag]
        meat += weight * (gamma + gamma.T)
    cov = xtx_inv @ meat @ xtx_inv
    se = np.sqrt(np.maximum(np.diag(cov), 0.0))
    return beta, se


def extract_field(raw: pd.DataFrame, field: str) -> pd.DataFrame:
    if not isinstance(raw.columns, pd.MultiIndex):
        if field in raw.columns:
            return raw[[field]]
        raise KeyError(field)
    if field in raw.columns.get_level_values(0):
        out = raw[field].copy()
    elif field in raw.columns.get_level_values(1):
        out = raw.xs(field, axis=1, level=1).copy()
    else:
        raise KeyError(field)
    out.columns = [str(c) for c in out.columns]
    return out


def download_yfinance(tickers: Iterable[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = yf.download(
        list(tickers),
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned no data")
    close = extract_field(raw, "Close").sort_index()
    volume = extract_field(raw, "Volume").sort_index()
    close.index = pd.to_datetime(close.index).tz_localize(None)
    volume.index = pd.to_datetime(volume.index).tz_localize(None)
    return close.dropna(axis=1, how="all"), volume.reindex(close.index)


def download_fred(series_id: str) -> pd.Series:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    rows = pd.read_csv(StringIO(response.text))
    if "observation_date" not in rows.columns or series_id not in rows.columns:
        raise RuntimeError(f"unexpected FRED CSV schema for {series_id}")
    series = pd.to_numeric(rows[series_id].replace(".", np.nan), errors="coerce")
    out = pd.Series(series.to_numpy(dtype=float), index=pd.to_datetime(rows["observation_date"]), name=series_id)
    return out.dropna()


def load_fred_features(daily_index: pd.DatetimeIndex) -> tuple[pd.DataFrame, dict]:
    features: dict[str, pd.Series] = {}
    status: dict[str, dict] = {}
    for label, series_id in FRED_SERIES.items():
        try:
            series = download_fred(series_id)
            status[label] = {
                "series_id": series_id,
                "status": "ok",
                "start": series.index.min().strftime("%Y-%m-%d"),
                "end": series.index.max().strftime("%Y-%m-%d"),
                "observations": int(series.notna().sum()),
            }
            features[label] = series
        except Exception as exc:  # explicit non-silent fallback, recorded in results
            status[label] = {"series_id": series_id, "status": "failed", "error": repr(exc)}
    if not features:
        return pd.DataFrame(index=daily_index), status

    fred = pd.DataFrame(features).sort_index()
    daily = fred.reindex(daily_index.union(fred.index)).ffill().reindex(daily_index)
    if {"bank_deposits", "money_market_assets"}.issubset(daily.columns):
        mmf_chg = daily["money_market_assets"].pct_change(63)
        dep_chg = daily["bank_deposits"].pct_change(21)
        daily["cash_migration_z"] = rolling_zscore(mmf_chg - dep_chg)
    elif "money_market_assets" in daily.columns:
        daily["cash_migration_z"] = rolling_zscore(daily["money_market_assets"].pct_change(63))
    elif "bank_deposits" in daily.columns:
        daily["cash_migration_z"] = rolling_zscore(-daily["bank_deposits"].pct_change(21))
    return daily[["cash_migration_z"]].copy(), status


def forward_realized_variance(returns: pd.Series, horizon: int) -> pd.Series:
    squared = returns.pow(2)
    pieces = [squared.shift(-i) for i in range(horizon)]
    return sum(pieces) * TRADING_DAYS / horizon


def forward_downside_corr(x: pd.Series, y: pd.Series, horizon: int) -> pd.Series:
    x_down = x.clip(upper=0.0)
    y_down = y.clip(upper=0.0)
    values: list[float] = []
    idx = x.index
    for pos in range(len(idx)):
        xs = x_down.iloc[pos : pos + horizon]
        ys = y_down.iloc[pos : pos + horizon]
        if len(xs) < horizon or xs.std(ddof=0) == 0 or ys.std(ddof=0) == 0:
            values.append(float("nan"))
        else:
            values.append(float(xs.corr(ys)))
    return pd.Series(values, index=idx)


def build_panel(close: pd.DataFrame, volume: pd.DataFrame, fred: pd.DataFrame) -> pd.DataFrame:
    available = [ticker for ticker in ETF_TICKERS if ticker in close.columns]
    ret = np.log(close[available] / close[available].shift(1)).replace([np.inf, -np.inf], np.nan)
    dollar_volume = (close.reindex(columns=available) * volume.reindex(columns=available)).replace(0.0, np.nan)

    panel = pd.DataFrame(index=close.index)
    fund_volume_shock = pd.concat(
        [rolling_zscore(np.log(dollar_volume[ticker])) for ticker in FUND_PROXY_ETFS if ticker in dollar_volume],
        axis=1,
    ).mean(axis=1)
    bond_basket_ret5 = ret[[t for t in FUND_PROXY_ETFS if t in ret]].mean(axis=1).rolling(5).sum()
    credit_gap_21 = (ret["HYG"] - ret["LQD"]).rolling(21).sum() if {"HYG", "LQD"}.issubset(ret.columns) else np.nan
    amihud = pd.concat(
        [
            rolling_zscore((ret[ticker].abs() / dollar_volume[ticker]).replace([np.inf, -np.inf], np.nan))
            for ticker in ILLIQUIDITY_ETFS
            if ticker in ret and ticker in dollar_volume
        ],
        axis=1,
    ).mean(axis=1)

    panel["fund_volume_shock_z"] = fund_volume_shock
    panel["bond_price_pressure_z"] = rolling_zscore(-bond_basket_ret5)
    panel["credit_underperformance_z"] = rolling_zscore(-credit_gap_21)
    panel["etf_illiquidity_z"] = amihud
    if "cash_migration_z" in fred.columns:
        panel["cash_migration_z"] = fred["cash_migration_z"]

    component_cols = [
        "fund_volume_shock_z",
        "bond_price_pressure_z",
        "credit_underperformance_z",
        "etf_illiquidity_z",
        "cash_migration_z",
    ]
    panel["run_pressure_raw"] = panel[[c for c in component_cols if c in panel.columns]].mean(axis=1)
    panel["run_pressure_index"] = rolling_zscore(panel["run_pressure_raw"])

    rv21 = ret.pow(2).rolling(RV_WINDOW).mean() * TRADING_DAYS
    panel["spy_rv21_lag"] = np.log1p(rv21["SPY"]).shift(1) if "SPY" in rv21 else np.nan
    panel["vix_log_lag"] = np.log(close["^VIX"]).shift(1) if "^VIX" in close.columns else np.nan
    panel["hyg_lqd_gap_21_lag"] = (-credit_gap_21).shift(1) if isinstance(credit_gap_21, pd.Series) else np.nan

    # Critical lookahead guard: signals observed at t-1 predict targets beginning at t.
    panel["signal_lag"] = panel["run_pressure_index"].shift(1)
    for target in TARGETS:
        if target not in ret.columns:
            continue
        panel[f"{target}_rv21_lag"] = np.log1p(rv21[target]).shift(1)
        for horizon in HORIZONS:
            panel[f"{target}_fwd_rv{horizon}_log"] = np.log1p(forward_realized_variance(ret[target], horizon))

    if {"HYG", "SPY"}.issubset(ret.columns):
        panel["hyg_spy_downside_corr_fwd21"] = forward_downside_corr(ret["HYG"], ret["SPY"], 21)
    return panel


def run_hac_tests(panel: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    tests: list[HACTest] = []
    rows_meta: list[dict] = []
    for target in TARGETS:
        for horizon in HORIZONS:
            y_col = f"{target}_fwd_rv{horizon}_log"
            own_col = f"{target}_rv21_lag"
            if y_col not in panel or own_col not in panel:
                continue
            x_cols = ["signal_lag", own_col, "spy_rv21_lag", "vix_log_lag", "hyg_lqd_gap_21_lag"]
            df = panel[[y_col] + x_cols].replace([np.inf, -np.inf], np.nan).dropna()
            if len(df) < 500:
                continue
            beta, se = hac_regression(df[y_col], df[x_cols], maxlags=max(horizon, 21))
            signal_beta = float(beta[1])
            signal_se = float(se[1])
            t_stat = signal_beta / signal_se if signal_se > 0 else float("nan")
            p_value = normal_p_value(t_stat) if math.isfinite(t_stat) else float("nan")
            tests.append(
                HACTest(
                    target=target,
                    horizon=f"rv{horizon}",
                    n_obs=int(len(df)),
                    beta=signal_beta,
                    hac_t=float(t_stat),
                    hac_p=float(p_value),
                    expected_direction="positive",
                    passes_harvey_t3=bool(t_stat >= 3.0),
                )
            )
            rows_meta.append({"target": target, "horizon_days": horizon, "y_col": y_col, "x_cols": x_cols})

    if "hyg_spy_downside_corr_fwd21" in panel:
        y_col = "hyg_spy_downside_corr_fwd21"
        x_cols = ["signal_lag", "HYG_rv21_lag", "spy_rv21_lag", "vix_log_lag", "hyg_lqd_gap_21_lag"]
        df = panel[[y_col] + x_cols].replace([np.inf, -np.inf], np.nan).dropna()
        if len(df) >= 500:
            beta, se = hac_regression(df[y_col], df[x_cols], maxlags=21)
            t_stat = float(beta[1] / se[1]) if se[1] > 0 else float("nan")
            p_value = normal_p_value(t_stat) if math.isfinite(t_stat) else float("nan")
            tests.append(
                HACTest(
                    target="HYG_SPY",
                    horizon="downside_corr21",
                    n_obs=int(len(df)),
                    beta=float(beta[1]),
                    hac_t=t_stat,
                    hac_p=float(p_value),
                    expected_direction="positive",
                    passes_harvey_t3=bool(t_stat >= 3.0),
                )
            )
            rows_meta.append({"target": "HYG_SPY", "horizon_days": 21, "y_col": y_col, "x_cols": x_cols})

    raw = [test.__dict__ for test in tests]
    p_values = [row["hac_p"] for row in raw]
    q_values = bh_qvalues(p_values) if p_values else []
    for row, q_value in zip(raw, q_values):
        row["bh_q"] = q_value
        row["bonferroni_p"] = float(min(1.0, row["hac_p"] * len(raw)))
        row["passes_bonferroni_5pct"] = bool(row["bonferroni_p"] <= 0.05 and row["beta"] > 0)
    return raw, rows_meta


def fit_predict(train: pd.DataFrame, row: pd.Series, y_col: str, x_cols: list[str]) -> float:
    x_train = np.column_stack([np.ones(len(train)), train[x_cols].to_numpy(dtype=float)])
    y_train = train[y_col].to_numpy(dtype=float)
    beta = np.linalg.lstsq(x_train, y_train, rcond=None)[0]
    x_row = np.asarray([1.0] + [float(row[col]) for col in x_cols], dtype=float)
    return float(x_row @ beta)


def oos_test(panel: pd.DataFrame, meta: list[dict]) -> list[dict]:
    results: list[OOSResult] = []
    for spec in meta:
        y_col = spec["y_col"]
        x_cols_aug = spec["x_cols"]
        x_cols_base = [col for col in x_cols_aug if col != "signal_lag"]
        df = panel[[y_col] + x_cols_aug].replace([np.inf, -np.inf], np.nan).dropna()
        if len(df) < MIN_TRAIN + 252:
            continue
        preds_base: list[float] = []
        preds_aug: list[float] = []
        actual: list[float] = []
        for pos in range(MIN_TRAIN, len(df)):
            train = df.iloc[:pos]
            row = df.iloc[pos]
            preds_base.append(fit_predict(train, row, y_col, x_cols_base))
            preds_aug.append(fit_predict(train, row, y_col, x_cols_aug))
            actual.append(float(row[y_col]))
        actual_arr = np.asarray(actual)
        base_err = actual_arr - np.asarray(preds_base)
        aug_err = actual_arr - np.asarray(preds_aug)
        mse_base = float(np.mean(base_err**2))
        mse_aug = float(np.mean(aug_err**2))
        loss_diff = pd.Series(aug_err**2 - base_err**2)
        _, dm_t, dm_p = hac_mean_test(loss_diff, maxlags=max(5, int(spec["horizon_days"])))
        improvement = 100.0 * (1.0 - mse_aug / mse_base) if mse_base > 0 else float("nan")
        results.append(
            OOSResult(
                target=spec["target"],
                horizon=f"{spec['horizon_days']}d",
                n_oos=int(len(actual_arr)),
                mse_baseline=mse_base,
                mse_augmented=mse_aug,
                mse_improvement_pct=float(improvement),
                dm_t_aug_minus_base=float(dm_t),
                dm_p=float(dm_p),
                passes_harvey_t3=bool(dm_t <= -3.0),
            )
        )
    return [row.__dict__ for row in results]


def make_figures(panel: pd.DataFrame, hac_rows: list[dict]) -> dict[str, str]:
    FIG_DIR.mkdir(exist_ok=True)
    paths: dict[str, str] = {}

    fig, ax1 = plt.subplots(figsize=(11, 5.8))
    z = panel["run_pressure_index"].dropna()
    ax1.plot(z.index, z, color="#8a4f23", lw=1.3, label="Bond fund run-pressure proxy (z)")
    ax1.axhline(0.0, color="#555555", lw=0.8)
    ax1.set_ylabel("Proxy z-score")
    ax2 = ax1.twinx()
    if "HYG_fwd_rv21_log" in panel:
        hyg_rv = np.expm1(panel["HYG_fwd_rv21_log"]).rolling(21).mean()
        ax2.plot(hyg_rv.index, hyg_rv, color="#345f8c", alpha=0.65, lw=1.1, label="HYG forward RV21")
        ax2.set_ylabel("HYG forward annualized variance")
    ax1.set_title("K1538 run-pressure proxy and HYG forward realized variance")
    ax1.xaxis.set_major_locator(mdates.YearLocator(2))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax1.grid(alpha=0.2)
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", frameon=False)
    fig.tight_layout()
    path = FIG_DIR / "k1538_run_pressure_timeseries.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths["run_pressure_timeseries"] = str(path.relative_to(BASE_DIR))

    if hac_rows:
        labels = [f"{row['target']} {row['horizon']}" for row in hac_rows]
        values = [row["hac_t"] for row in hac_rows]
        colors = ["#2f7d5f" if val >= 3.0 else "#9f6b3f" if val > 0 else "#7a4b58" for val in values]
        fig, ax = plt.subplots(figsize=(11.5, 5.6))
        ax.bar(np.arange(len(values)), values, color=colors)
        ax.axhline(3.0, color="#222222", ls="--", lw=0.9, label="Harvey +3 gate")
        ax.axhline(0.0, color="#555555", lw=0.8)
        ax.set_xticks(np.arange(len(values)))
        ax.set_xticklabels(labels, rotation=35, ha="right")
        ax.set_ylabel("HAC t-stat on lagged run-pressure proxy")
        ax.set_title("K1538 predictive regressions: incremental run-pressure coefficient")
        ax.grid(axis="y", alpha=0.25)
        ax.legend(frameon=False)
        fig.tight_layout()
        path = FIG_DIR / "k1538_hac_tstats.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        paths["hac_tstats"] = str(path.relative_to(BASE_DIR))
    return paths


def main() -> int:
    np.random.seed(SEED)
    close, volume = download_yfinance(ETF_TICKERS)
    fred_features, fred_status = load_fred_features(close.index)
    panel = build_panel(close, volume, fred_features)
    hac_rows, meta = run_hac_tests(panel)
    oos_rows = oos_test(panel, meta)
    figures = make_figures(panel, hac_rows)
    panel.to_csv(PANEL_PATH, index_label="date")

    positive_hac = [
        row for row in hac_rows
        if row["beta"] > 0 and (row["passes_harvey_t3"] or row["passes_bonferroni_5pct"])
    ]
    positive_oos = [row for row in oos_rows if row["passes_harvey_t3"] and row["mse_improvement_pct"] > 0]
    if positive_hac and positive_oos:
        verdict = "POSITIVE_PROXY"
    elif positive_hac:
        verdict = "DIRECTIONAL_HAC_ONLY"
    elif any(row["beta"] > 0 and row["hac_t"] > 1.96 for row in hac_rows):
        verdict = "WEAK_DIRECTIONAL_PROXY"
    else:
        verdict = "NULL_PROXY"

    results = {
        "experiment_id": EXPERIMENT_ID,
        "task_id": TASK_ID,
        "title": "Bond mutual fund demandable-equity run proxy and credit ETF volatility",
        "verdict": verdict,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data": {
            "yfinance_source": "auto_adjust=True daily close and volume",
            "requested_start": START,
            "requested_end": END,
            "effective_start": panel.dropna(how="all").index.min().strftime("%Y-%m-%d"),
            "effective_end": panel.dropna(how="all").index.max().strftime("%Y-%m-%d"),
            "n_daily_rows": int(len(panel)),
            "tickers": ETF_TICKERS,
            "fred_status": fred_status,
        },
        "method": {
            "proxy_components": [
                "bond ETF dollar-volume shock z-score (AGG/BND/LQD/HYG)",
                "negative 5-day bond ETF basket return pressure",
                "HYG underperformance versus LQD as credit redemption pressure",
                "ETF Amihud-style illiquidity z-score (HYG/LQD/BKLN)",
                "FRED cash migration: money-market asset growth minus bank-deposit growth when available",
            ],
            "lookahead_guard": "run_pressure_index is used only through signal_lag = run_pressure_index.shift(1); targets begin at date t.",
            "controls": [
                "own lagged 21-day realized variance",
                "SPY lagged 21-day realized variance",
                "lagged log VIX",
                "lagged HYG-LQD credit underperformance",
            ],
            "formal_tests": [
                "OLS predictive regressions with Newey-West HAC standard errors",
                "Harvey-style |t|>=3 gate; expected direction is positive beta",
                "Bonferroni and BH q-values across all HAC target tests",
                "Expanding-window OOS MSE comparison with HAC DM test on squared-error loss difference",
            ],
        },
        "related_prior": [
            "K1332 private-credit BDC proxy: narrow credit-only PASS",
            "K1499 BIZD-minus-HYG NAV-discount proxy: narrow HYG 5d signal after controls",
            "This K1538 differs by targeting open-end bond-fund run pressure via broad bond ETF volume/cash migration proxies.",
        ],
        "literature_precheck": [
            {
                "title": "Ma, Xiao, and Zeng, Bank Debt, Mutual Fund Equity, and Swing Pricing in Liquidity Provision",
                "source": "Review of Financial Studies / Oxford Academic",
                "url": "https://academic.oup.com/rfs/advance-article-abstract/doi/10.1093/rfs/hhaf105/8343552",
            },
            {
                "title": "Jin, Kacperczyk, Kahraman, and Suntheim, Swing Pricing and Fragility in Open-End Mutual Funds",
                "source": "Review of Financial Studies",
                "url": "https://academic.oup.com/rfs/article/35/1/1/6162183",
            },
            {
                "title": "IMF, Fund Investor Types and Bond Market Volatility",
                "source": "Global Financial Stability Note 2025",
                "url": "https://meetings.imf.org/-/media/Files/Publications/gfs-notes/2025/English/GFSNEA2025002.ashx",
            },
            {
                "title": "Xiao / Zeng, Mutual Fund Liquidity Transformation and Reverse Flight to Liquidity",
                "source": "Cleveland Fed / Wharton draft",
                "url": "https://rodneywhitecenter.wharton.upenn.edu/wp-content/uploads/2020/12/21-20.Zeng2_.pdf",
            },
        ],
        "hac_regression_tests": hac_rows,
        "oos_forecast_tests": oos_rows,
        "positive_hac_gate_tests": positive_hac,
        "positive_oos_gate_tests": positive_oos,
        "figures": figures,
        "panel_csv": PANEL_PATH.name,
        "limitations": [
            "No ICI fund-level daily/weekly bond mutual fund flow microdata are used; this is a free ETF/FRED proxy diagnostic.",
            "ETF trading volume can reflect hedging and institutional ETF use, not only open-end mutual fund redemptions.",
            "FRED cash-migration series are low frequency and ffilled to daily dates, so they cannot identify intraday or daily fund runs.",
            "HYG/LQD/BKLN/TLT realized volatility is an ETF-level target, not underlying bond TRACE volatility.",
            "Positive predictive coefficients would be association, not causal evidence of fund-run fire sales.",
        ],
    }
    RESULTS_PATH.write_text(json.dumps(finite(results), ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(finite({
        "verdict": verdict,
        "n_daily_rows": results["data"]["n_daily_rows"],
        "positive_hac_gate_tests": len(positive_hac),
        "positive_oos_gate_tests": len(positive_oos),
        "top_hac": sorted(hac_rows, key=lambda row: row["hac_t"], reverse=True)[:5],
        "figures": figures,
    }), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
