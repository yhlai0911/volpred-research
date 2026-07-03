#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K1614 — Descriptive Volatility-Structure Diagnostic of Natural-Resource Real Assets

誠實的描述性 / 截面波動率結構診斷（NON-tradable，不做策略回測、不宣稱可交易訊號）。

核心問題：
  1. 農地 / 林地 / 水資源這一籃「實質資產」的已實現波動率(RV)是否形成一致 vol cluster？
  2. 市場高波動 regime 下，它們的 vol 是放大還是相對穩定（避風港特性）？
  3. 各檔對大盤(SPY) 的 vol beta 為何（<1 = vol 較大盤鈍）？

方法論誠實原則:
  - RV = rolling std of daily log returns, annualized (× sqrt(252))。純描述性。
  - 沒有預測性 / 可交易宣稱；因此沒有 signal→return 的 lookahead 風險。
    唯一涉及「時序方向」的是 vol beta 的 contemporaneous OLS（RV_asset_t ~ RV_SPY_t），
    這是描述性同期關係，不是預測。若要做任何 predictive lag，會明確 shift(1)（本實驗未做預測）。
  - 重疊窗口(rolling)自相關會膨脹樣本量 → Welch t-test p-value 被高估。
    因此: (a) 報標準 Welch t/p 但明確 caveat, (b) 報 Cohen's d 效果量（對 n 不敏感）,
    (c) 補非重疊(每 21 日)子樣本 Welch t-test 作 robustness。
  - RV level 相關天然偏高（共同市場趨勢）→ 額外報 ΔRV 差分相關作更嚴格共動指標。
  - Seed 固定 = 42（本描述性實驗無隨機程序，仍固定以符合規範）。

Run: uv run python experiments/k1614/k1614.py
Output: k1614_results.json + figures/*.png
"""

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)  # 固定 seed（本實驗無隨機程序，仍依規範固定）

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
DATA_DIR.mkdir(exist_ok=True)
FIG_DIR.mkdir(exist_ok=True)

START = "2015-01-01"
END = "2026-07-04"  # yfinance end is exclusive; intended last possible session is 2026-07-03

# 實質資產籃 (7) 三子群
FARMLAND = ["LAND", "FPI"]        # 農地 REIT
TIMBER = ["WY", "RYN"]            # 林地 REIT
WATER = ["PHO", "CGW", "FIW"]     # 水資源 ETF
REAL_ASSETS = FARMLAND + TIMBER + WATER  # 7

# 對照 proxy (3)
CONTROLS = ["SPY", "TIP", "DBC"]  # 大盤 / 通膨連結債 / 商品
ALL_TICKERS = REAL_ASSETS + CONTROLS

SUBGROUPS = {"farmland": FARMLAND, "timber": TIMBER, "water": WATER}

TRADING_DAYS = 252
RV_WINDOWS = {"rv21": 21, "rv63": 63}
PRIMARY = "rv21"  # 主分析用 21d RV
FORWARD_HORIZON = 21
EPS = 1.0e-12

PRICE_CACHE = DATA_DIR / "adjusted_close.csv"
USDM_CA_CACHE = DATA_DIR / "usdm_california_weekly.csv"
FRED_CACHE_TEMPLATE = "fred_{series_id}.csv"
USDM_CA_URL = (
    "https://usdmdataservices.unl.edu/api/StateStatistics/"
    "GetDroughtSeverityStatisticsByAreaPercent"
)
FRED_GRAPH_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"

LITERATURE_AND_DATA_CONTEXT = [
    {
        "citation": "Newell and Eves (2023), Inflation hedging effectiveness of farmland and timberland assets",
        "url": "https://www.sciencedirect.com/science/article/abs/pii/S1389934123000643",
        "role": "Motivates checking public-equity farmland/timberland inflation hedge claims rather than assuming private real-asset results transfer to ETFs/REITs.",
    },
    {
        "citation": "Liu, Hartzell and Hoesli, International Evidence on Real Estate Securities as an Inflation Hedge",
        "url": "https://ecommons.cornell.edu/bitstream/handle/1813/71540/Liu27_International_Evidence_on_Real_Estate_Securities.pdf",
        "role": "Warns that listed real-estate securities need not hedge inflation better than common stocks.",
    },
    {
        "citation": "Hong, Li and Xu (2019), Climate Risks and Market Efficiency, Journal of Econometrics",
        "url": "https://www.sciencedirect.com/science/article/abs/pii/S0304407618301817",
        "role": "Motivates drought as a climate-risk state variable relevant to food/natural-resource cash-flow risk.",
    },
    {
        "citation": "U.S. Drought Monitor web services and DSCI documentation",
        "url": "https://droughtmonitor.unl.edu/DmData/DataDownload/WebServiceInfo.aspx",
        "role": "Provides weekly D0-D4 drought category percentages and DSCI-style severity proxy.",
    },
]


# ----------------------------------------------------------------------------
# 資料抓取
# ----------------------------------------------------------------------------
def fetch_prices():
    """抓 adjusted close（auto_adjust=True，一致用於 log-return RV）。"""
    import yfinance as yf

    if PRICE_CACHE.exists():
        px = pd.read_csv(PRICE_CACHE, parse_dates=["Date"]).set_index("Date").sort_index()
        return px[[t for t in ALL_TICKERS if t in px.columns]]

    raw = yf.download(
        ALL_TICKERS,
        start=START,
        end=END,
        auto_adjust=True,     # adjusted close：一致口徑，純描述性 RV 適用
        progress=False,
        group_by="column",
    )
    # 多 ticker → MultiIndex columns，取 'Close' 層
    if isinstance(raw.columns, pd.MultiIndex):
        px = raw["Close"].copy()
    else:
        px = raw[["Close"]].copy()
        px.columns = ALL_TICKERS[:1]
    px = px[[t for t in ALL_TICKERS if t in px.columns]]
    px.index = pd.to_datetime(px.index)
    px = px.sort_index()
    px.to_csv(PRICE_CACHE, index_label="Date")
    return px


def _json_safe(value: Any) -> Any:
    """Convert numpy/pandas objects to JSON-safe values."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if pd.isna(value):
        return None
    return value


# ----------------------------------------------------------------------------
# RV 計算
# ----------------------------------------------------------------------------
def compute_rv(px):
    """log return + annualized rolling std RV（21d, 63d）。"""
    logret = np.log(px / px.shift(1))
    rv = {}
    for name, w in RV_WINDOWS.items():
        rv[name] = logret.rolling(w).std() * np.sqrt(TRADING_DAYS)
    return logret, rv


# ----------------------------------------------------------------------------
# Public macro / drought proxy construction
# ----------------------------------------------------------------------------
def trailing_zscore(series: pd.Series, window: int, min_periods: int) -> pd.Series:
    """Lag-safe trailing z-score: current value is standardized by prior history only."""
    mu = series.shift(1).rolling(window, min_periods=min_periods).mean()
    sd = series.shift(1).rolling(window, min_periods=min_periods).std()
    return (series - mu) / sd.replace(0, np.nan)


def fetch_fred_series(series_id: str) -> pd.DataFrame:
    cache = DATA_DIR / FRED_CACHE_TEMPLATE.format(series_id=series_id.lower())
    if cache.exists():
        frame = pd.read_csv(cache, parse_dates=["observation_date"])
    else:
        url = FRED_GRAPH_URL.format(series_id=series_id)
        frame = pd.read_csv(url)
        frame.to_csv(cache, index=False)
        frame["observation_date"] = pd.to_datetime(frame["observation_date"])
    frame = frame.rename(columns={series_id: "value"})
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["observation_date", "value"]).sort_values("observation_date")
    return frame


def prepare_monthly_inflation_release(series_id: str, release_delay_days: int, out_prefix: str) -> pd.DataFrame:
    frame = fetch_fred_series(series_id).copy()
    frame["log_mom"] = np.log(frame["value"] / frame["value"].shift(1))
    frame[f"{out_prefix}_mom_z"] = trailing_zscore(frame["log_mom"], window=36, min_periods=24)
    frame[f"{out_prefix}_mom"] = frame["log_mom"]
    frame["release_date"] = frame["observation_date"] + pd.offsets.MonthEnd(0) + pd.Timedelta(days=release_delay_days)
    return frame[["release_date", f"{out_prefix}_mom", f"{out_prefix}_mom_z"]].dropna(subset=["release_date"])


def merge_asof_release(index: pd.Index, release: pd.DataFrame, date_col: str, value_cols: list[str]) -> pd.DataFrame:
    dates = pd.DatetimeIndex(pd.to_datetime(index)).tz_localize(None).normalize().astype("datetime64[ns]")
    left = pd.DataFrame({"date": dates}).sort_values("date")
    right = release.copy()
    right["date"] = (
        pd.to_datetime(right[date_col]).dt.tz_localize(None).dt.normalize().astype("datetime64[ns]")
    )
    right = right[["date", *value_cols]].sort_values("date")
    merged = pd.merge_asof(left, right, on="date", direction="backward").set_index("date")
    merged = merged.reindex(dates)
    merged.index = pd.to_datetime(index)
    return merged[value_cols]


def build_macro_stress_panel(trading_index: pd.Index) -> pd.DataFrame:
    """Build lagged inflation-pressure proxies available before the target window.

    CPI/PPI are current-vintage FRED series, not consensus-surprise data. To avoid
    same-month lookahead, monthly values become available only after conservative
    release delays and are then shifted one trading day.
    """
    panel = pd.DataFrame(index=pd.to_datetime(trading_index).tz_localize(None).normalize())

    cpi_release = prepare_monthly_inflation_release("CPIAUCSL", release_delay_days=16, out_prefix="cpi")
    ppi_release = prepare_monthly_inflation_release("PPIACO", release_delay_days=20, out_prefix="ppi")
    cpi_daily = merge_asof_release(panel.index, cpi_release, "release_date", ["cpi_mom", "cpi_mom_z"])
    ppi_daily = merge_asof_release(panel.index, ppi_release, "release_date", ["ppi_mom", "ppi_mom_z"])
    panel[["cpi_mom_lag1", "cpi_mom_z_lag1"]] = cpi_daily[["cpi_mom", "cpi_mom_z"]].shift(1)
    panel[["ppi_mom_lag1", "ppi_mom_z_lag1"]] = ppi_daily[["ppi_mom", "ppi_mom_z"]].shift(1)

    breakeven = fetch_fred_series("T10YIE").copy()
    breakeven["date"] = pd.to_datetime(breakeven["observation_date"]).dt.normalize()
    breakeven = breakeven.set_index("date")["value"].sort_index()
    daily_breakeven = breakeven.reindex(panel.index).ffill()
    t10_change21 = daily_breakeven.diff(21)
    panel["t10yie_level_lag1"] = daily_breakeven.shift(1)
    panel["t10yie_change21_lag1"] = t10_change21.shift(1)
    panel["t10yie_change21_z_lag1"] = trailing_zscore(t10_change21, window=252, min_periods=126).shift(1)

    z_cols = ["cpi_mom_z_lag1", "ppi_mom_z_lag1", "t10yie_change21_z_lag1"]
    panel["inflation_pressure_lag1"] = panel[z_cols].mean(axis=1, skipna=True)
    return panel


def fetch_usdm_ca() -> pd.DataFrame:
    if USDM_CA_CACHE.exists():
        return pd.read_csv(
            USDM_CA_CACHE,
            parse_dates=["valid_start", "valid_end", "release_date"],
        ).sort_values("valid_start")

    import requests

    params = {
        "aoi": "06",
        "startdate": "1/1/2015",
        "enddate": "7/3/2026",
        "statisticsType": "1",
    }
    response = requests.get(USDM_CA_URL, params=params, headers={"Accept": "application/json"}, timeout=60)
    response.raise_for_status()
    frame = pd.DataFrame(response.json())
    frame = frame.rename(
        columns={
            "validStart": "valid_start",
            "validEnd": "valid_end",
            "stateAbbreviation": "state",
        }
    )
    for col in ["d0", "d1", "d2", "d3", "d4", "none"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["valid_start"] = pd.to_datetime(frame["valid_start"]).dt.normalize()
    frame["valid_end"] = pd.to_datetime(frame["valid_end"]).dt.normalize()
    frame["release_date"] = frame["valid_start"] + pd.Timedelta(days=2)
    frame["dsci"] = frame["d0"] + frame["d1"] + frame["d2"] + frame["d3"] + frame["d4"]
    frame = frame.sort_values("valid_start")
    frame["dsci_delta4w"] = frame["dsci"].diff(4)
    frame["dsci_delta4w_z"] = trailing_zscore(frame["dsci_delta4w"], window=52, min_periods=26)
    frame.to_csv(USDM_CA_CACHE, index=False)
    return frame


def build_drought_stress_panel(trading_index: pd.Index) -> pd.DataFrame:
    usdm = fetch_usdm_ca()
    value_cols = ["dsci", "dsci_delta4w", "dsci_delta4w_z", "d0", "d1", "d2", "d3", "d4"]
    daily = merge_asof_release(trading_index, usdm, "release_date", value_cols)
    panel = pd.DataFrame(index=daily.index)
    for col in value_cols:
        panel[f"ca_{col}_lag1"] = daily[col].shift(1)
    return panel


def forward_sum(series: pd.Series, horizon: int) -> pd.Series:
    return series.rolling(horizon, min_periods=horizon).sum().shift(-(horizon - 1))


def build_forward_targets(logret: pd.DataFrame, rv21: pd.DataFrame) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    spy_ret = logret["SPY"]
    for ticker in REAL_ASSETS:
        r = logret[ticker]
        frame = pd.DataFrame(index=logret.index)
        frame["forward_rv21"] = np.sqrt(forward_sum(r.pow(2), FORWARD_HORIZON) / FORWARD_HORIZON * TRADING_DAYS)
        frame["forward_downside21"] = np.sqrt(
            forward_sum(r.clip(upper=0).pow(2), FORWARD_HORIZON) / FORWARD_HORIZON * TRADING_DAYS
        )
        frame["forward_spy_corr21"] = r.rolling(FORWARD_HORIZON, min_periods=FORWARD_HORIZON).corr(spy_ret).shift(
            -(FORWARD_HORIZON - 1)
        )
        frame["lagged_asset_rv21"] = rv21[ticker].shift(1)
        frame["lagged_spy_rv21"] = rv21["SPY"].shift(1)
        out[ticker] = frame
    return out


def holm_adjust(p_values: list[float]) -> list[float]:
    m = len(p_values)
    order = np.argsort(np.array(p_values, dtype=float))
    adjusted = np.empty(m, dtype=float)
    running = 0.0
    for rank, original_idx in enumerate(order):
        raw = p_values[original_idx]
        adj = min(1.0, (m - rank) * raw)
        running = max(running, adj)
        adjusted[original_idx] = running
    return adjusted.tolist()


def stress_event_diagnostics(logret: pd.DataFrame, rv21: pd.DataFrame) -> dict[str, Any]:
    """Lagged public-proxy stress states vs next-21-day RV/downside/correlation."""
    import statsmodels.api as sm
    from scipy import stats

    macro = build_macro_stress_panel(logret.index)
    drought = build_drought_stress_panel(logret.index)
    stress_panel = pd.concat([macro, drought], axis=1)
    targets = build_forward_targets(logret, rv21)
    specs = {
        "inflation_pressure": {
            "signal_col": "inflation_pressure_lag1",
            "description": "Mean z-score of lagged CPI MoM, PPI MoM, and 21d breakeven-inflation change.",
        },
        "breakeven_21d_change": {
            "signal_col": "t10yie_change21_z_lag1",
            "description": "Lagged trailing z-score of 21-trading-day change in 10-year breakeven inflation.",
        },
        "ca_drought_intensification": {
            "signal_col": "ca_dsci_delta4w_z_lag1",
            "description": "Lagged California USDM DSCI 4-week change z-score; DSCI uses cumulative D0-D4 area percentages.",
        },
    }
    target_cols = ["forward_rv21", "forward_downside21", "forward_spy_corr21"]
    regressions: list[dict[str, Any]] = []
    regimes: dict[str, Any] = {}

    for spec_name, spec in specs.items():
        signal_col = spec["signal_col"]
        spec_out: dict[str, Any] = {
            "signal_col": signal_col,
            "description": spec["description"],
            "high_low_definition": "high >= 80th percentile, low <= 20th percentile of full-sample lagged signal",
            "assets": {},
        }
        for ticker, target_frame in targets.items():
            df = pd.concat([target_frame, stress_panel[[signal_col]]], axis=1)
            df = df.replace([np.inf, -np.inf], np.nan).dropna()
            if len(df) < 252:
                spec_out["assets"][ticker] = {"n": int(len(df)), "status": "insufficient_data"}
                continue
            q20, q80 = df[signal_col].quantile([0.2, 0.8])
            high = df[df[signal_col] >= q80]
            low = df[df[signal_col] <= q20]
            asset_out: dict[str, Any] = {
                "n": int(len(df)),
                "signal_q20": float(q20),
                "signal_q80": float(q80),
                "n_high": int(len(high)),
                "n_low": int(len(low)),
                "metrics": {},
            }
            nonoverlap = df.iloc[np.arange(0, len(df), FORWARD_HORIZON)]
            for target_col in target_cols:
                high_vals = high[target_col].dropna()
                low_vals = low[target_col].dropna()
                if len(high_vals) < 5 or len(low_vals) < 5:
                    continue
                tt = stats.ttest_ind(high_vals, low_vals, equal_var=False)
                d = cohens_d(high_vals.to_numpy(), low_vals.to_numpy())
                high_mean = float(high_vals.mean())
                low_mean = float(low_vals.mean())
                no_high = nonoverlap[nonoverlap[signal_col] >= q80][target_col].dropna()
                no_low = nonoverlap[nonoverlap[signal_col] <= q20][target_col].dropna()
                if len(no_high) >= 5 and len(no_low) >= 5:
                    no_tt = stats.ttest_ind(no_high, no_low, equal_var=False)
                    no_res = {
                        "t": float(no_tt.statistic),
                        "p": float(no_tt.pvalue),
                        "n_high": int(len(no_high)),
                        "n_low": int(len(no_low)),
                    }
                else:
                    no_res = None

                asset_out["metrics"][target_col] = {
                    "high_mean": high_mean,
                    "low_mean": low_mean,
                    "high_minus_low": high_mean - low_mean,
                    "high_low_ratio": (high_mean / low_mean if abs(low_mean) > EPS else None),
                    "welch_t": float(tt.statistic),
                    "welch_p": float(tt.pvalue),
                    "cohens_d": float(d),
                    "nonoverlap_robustness_welch": no_res,
                }

                reg_df = df[[target_col, signal_col, "lagged_asset_rv21", "lagged_spy_rv21"]].dropna().copy()
                if target_col in ("forward_rv21", "forward_downside21"):
                    reg_df = reg_df[reg_df[target_col] > 0]
                    y = np.log(reg_df[target_col] + EPS)
                else:
                    y = reg_df[target_col]
                x = pd.DataFrame(
                    {
                        signal_col: reg_df[signal_col],
                        "log_lagged_asset_rv21": np.log(reg_df["lagged_asset_rv21"] + EPS),
                        "log_lagged_spy_rv21": np.log(reg_df["lagged_spy_rv21"] + EPS),
                    },
                    index=reg_df.index,
                ).replace([np.inf, -np.inf], np.nan)
                reg_df = pd.concat([y.rename("y"), x], axis=1).dropna()
                if len(reg_df) >= 252:
                    fit = sm.OLS(reg_df["y"], sm.add_constant(reg_df[x.columns], has_constant="add")).fit(
                        cov_type="HAC",
                        cov_kwds={"maxlags": FORWARD_HORIZON - 1},
                    )
                    regressions.append(
                        {
                            "stress": spec_name,
                            "asset": ticker,
                            "target": target_col,
                            "n": int(len(reg_df)),
                            "signal_col": signal_col,
                            "beta_signal": float(fit.params[signal_col]),
                            "t_signal": float(fit.tvalues[signal_col]),
                            "p_signal": float(fit.pvalues[signal_col]),
                            "controls": ["log_lagged_asset_rv21", "log_lagged_spy_rv21"],
                            "hac_lag": FORWARD_HORIZON - 1,
                        }
                    )
            spec_out["assets"][ticker] = asset_out
        regimes[spec_name] = spec_out

    if regressions:
        adjusted = holm_adjust([r["p_signal"] for r in regressions])
        for row, holm_p in zip(regressions, adjusted):
            row["holm_p_signal"] = float(holm_p)
            row["safe_haven_gate_pass"] = bool(
                row["beta_signal"] < 0 and row["t_signal"] <= -3.0 and holm_p <= 0.05
            )
            row["risk_amplifier_gate_pass"] = bool(
                row["beta_signal"] > 0 and row["t_signal"] >= 3.0 and holm_p <= 0.05
            )

    safe_haven_passes = [r for r in regressions if r.get("safe_haven_gate_pass")]
    risk_amplifier_passes = [r for r in regressions if r.get("risk_amplifier_gate_pass")]
    negative_directional = [
        r for r in regressions
        if r["target"] in ("forward_rv21", "forward_downside21") and r["beta_signal"] < 0
    ]
    positive_directional = [
        r for r in regressions
        if r["target"] in ("forward_rv21", "forward_downside21") and r["beta_signal"] > 0
    ]
    if safe_haven_passes:
        verdict = "PARTIAL_SAFE_HAVEN_PUBLIC_PROXY_DIAGNOSTIC"
    elif risk_amplifier_passes:
        verdict = "ANTI_HEDGE_PUBLIC_PROXY_DIAGNOSTIC"
    elif negative_directional or positive_directional:
        verdict = "DIRECTIONAL_ONLY_PUBLIC_PROXY_DIAGNOSTIC"
    else:
        verdict = "NULL_PUBLIC_PROXY_DIAGNOSTIC"

    return {
        "verdict": verdict,
        "lookahead_policy": (
            "CPI/PPI become available only after conservative release delays; all stress columns are shifted one "
            "trading day. Targets are next-21-trading-day realized volatility, downside volatility, and return "
            "correlation, so event diagnostics do not use future realized volatility in the signal."
        ),
        "macro_proxy_caveat": (
            "FRED CPI/PPI are current-vintage release-lag proxies, not real-time consensus surprises. Results are "
            "public-proxy diagnostics and cannot be sold as implementable real-time inflation-surprise signals."
        ),
        "multiple_testing_gate": (
            "Regression signal gates require HAC t>=3 in the claimed direction and Holm-adjusted p<=0.05 across "
            "all stress × asset × target cells."
        ),
        "summary_counts": {
            "regression_cells": int(len(regressions)),
            "safe_haven_gate_pass_count": int(len(safe_haven_passes)),
            "risk_amplifier_gate_pass_count": int(len(risk_amplifier_passes)),
            "directional_negative_rv_downside_cells": int(len(negative_directional)),
            "directional_positive_rv_downside_cells": int(len(positive_directional)),
        },
        "regime_high_low": regimes,
        "hac_regressions": regressions,
    }


# ----------------------------------------------------------------------------
# (a) 描述統計表
# ----------------------------------------------------------------------------
def descriptive_stats(rv21):
    out = {}
    for t in ALL_TICKERS:
        s = rv21[t].dropna()
        if s.empty:
            out[t] = {"n": 0}
            continue
        current = float(s.iloc[-1])
        pct = float((s < current).mean() * 100.0)  # 當前值歷史百分位
        out[t] = {
            "n": int(s.shape[0]),
            "mean": float(s.mean()),
            "median": float(s.median()),
            "std": float(s.std()),
            "min": float(s.min()),
            "max": float(s.max()),
            "current": current,
            "current_date": str(s.index[-1].date()),
            "current_percentile": round(pct, 2),
        }
    return out


# ----------------------------------------------------------------------------
# (b) Vol cluster 一致性：7 檔實質資產 21d RV 相關矩陣
# ----------------------------------------------------------------------------
def cluster_consistency(rv21):
    sub = rv21[REAL_ASSETS].dropna()
    n_common = int(sub.shape[0])
    corr = sub.corr(method="pearson")

    # 平均 pairwise corr（off-diagonal）
    def avg_offdiag(cmat, cols):
        m = cmat.loc[cols, cols].values
        iu = np.triu_indices(len(cols), k=1)
        return float(np.mean(m[iu])) if len(iu[0]) else float("nan")

    overall_avg = avg_offdiag(corr, REAL_ASSETS)

    # 子群內平均 corr
    within = {g: (avg_offdiag(corr, cols) if len(cols) > 1 else None)
              for g, cols in SUBGROUPS.items()}

    # 子群間平均 corr（跨群 pair 平均）
    between = {}
    gkeys = list(SUBGROUPS.keys())
    for i in range(len(gkeys)):
        for j in range(i + 1, len(gkeys)):
            ga, gb = gkeys[i], gkeys[j]
            vals = [corr.loc[a, b] for a in SUBGROUPS[ga] for b in SUBGROUPS[gb]]
            between[f"{ga}_vs_{gb}"] = float(np.mean(vals))

    # robustness: ΔRV 差分相關（去共同趨勢後的短期 vol 衝擊共動）
    dsub = sub.diff().dropna()
    dcorr = dsub.corr(method="pearson")
    davg = avg_offdiag(dcorr, REAL_ASSETS)

    return {
        "n_common_obs": n_common,
        "corr_matrix": {a: {b: round(float(corr.loc[a, b]), 4) for b in REAL_ASSETS}
                        for a in REAL_ASSETS},
        "avg_pairwise_corr": round(overall_avg, 4),
        "within_subgroup_avg_corr": {k: (round(v, 4) if v is not None else None)
                                     for k, v in within.items()},
        "between_subgroup_avg_corr": {k: round(v, 4) for k, v in between.items()},
        "diff_rv_avg_pairwise_corr": round(davg, 4),
        "diff_rv_note": ("ΔRV(一階差分)相關去除共同 vol 趨勢，反映短期波動衝擊的真實共動；"
                         "遠低於 level 相關代表 level 相關多來自共同市場趨勢而非同步 shock。"),
    }, corr


# ----------------------------------------------------------------------------
# (c) 市場 regime 對照：SPY 21d RV 三分位
# ----------------------------------------------------------------------------
def cohens_d(a, b):
    na, nb = len(a), len(b)
    va, vb = np.var(a, ddof=1), np.var(b, ddof=1)
    sp = np.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    return float((np.mean(a) - np.mean(b)) / sp) if sp > 0 else float("nan")


def regime_analysis(rv21):
    from scipy import stats

    aligned = rv21[[*REAL_ASSETS, "SPY"]].dropna()
    spy = aligned["SPY"]
    q1, q2 = spy.quantile([1 / 3, 2 / 3])
    regime = pd.Series(index=aligned.index, dtype=object)
    regime[spy <= q1] = "low"
    regime[(spy > q1) & (spy <= q2)] = "mid"
    regime[spy > q2] = "high"

    counts = regime.value_counts().to_dict()
    # assert 各分位非空（K1128 教訓：degenerate tertile 防呆）
    for r in ("low", "mid", "high"):
        assert counts.get(r, 0) > 0, f"regime {r} empty — tertile degenerate"

    # 非重疊子樣本（每 21 列取一）供 robustness t-test
    idx_nonoverlap = np.arange(0, len(aligned), RV_WINDOWS["rv21"])
    nonoverlap_mask = np.zeros(len(aligned), dtype=bool)
    nonoverlap_mask[idx_nonoverlap] = True

    per_asset = {}
    for t in REAL_ASSETS:
        s = aligned[t]
        full_mean = float(s.mean())
        by_regime = {}
        for r in ("low", "mid", "high"):
            m = regime == r
            vals = s[m]
            by_regime[r] = {
                "mean_rv": round(float(vals.mean()), 4),
                "ratio_to_own_full_mean": round(float(vals.mean()) / full_mean, 4),
                "n": int(vals.shape[0]),
            }
        low_vals = s[regime == "low"].values
        high_vals = s[regime == "high"].values
        # 標準 Welch（p 因重疊窗口自相關被高估 — 見 caveat）
        tt = stats.ttest_ind(high_vals, low_vals, equal_var=False)
        d = cohens_d(high_vals, low_vals)
        # 非重疊 robustness Welch
        s_no = s[nonoverlap_mask]
        r_no = regime[nonoverlap_mask]
        low_no = s_no[r_no == "low"].values
        high_no = s_no[r_no == "high"].values
        if len(low_no) >= 3 and len(high_no) >= 3:
            tt_no = stats.ttest_ind(high_no, low_no, equal_var=False)
            no_res = {"t": round(float(tt_no.statistic), 4),
                      "p": round(float(tt_no.pvalue), 6),
                      "n_high": int(len(high_no)), "n_low": int(len(low_no))}
        else:
            no_res = None
        per_asset[t] = {
            "full_mean_rv": round(full_mean, 4),
            "by_regime": by_regime,
            "high_vs_low_welch_t": round(float(tt.statistic), 4),
            "high_vs_low_welch_p": float(tt.pvalue),
            "cohens_d_high_vs_low": round(d, 4),
            "high_low_ratio": round(by_regime["high"]["mean_rv"] / by_regime["low"]["mean_rv"], 4),
            "nonoverlap_robustness_welch": no_res,
        }

    return {
        "regime_definition": "SPY 21d RV full-sample tertiles (low/mid/high)",
        "spy_rv_tertile_cutoffs": {"q33": round(float(q1), 4), "q67": round(float(q2), 4)},
        "regime_counts": {k: int(v) for k, v in counts.items()},
        "n_aligned_obs": int(aligned.shape[0]),
        "caveat_overlapping_windows": (
            "21d rolling RV 每日值高度自相關 → 標準 Welch t-test 的有效樣本量遠小於 n，"
            "p-value 被系統性高估。請以 Cohen's d 效果量與非重疊子樣本 robustness t-test 為準。"),
        "per_asset": per_asset,
    }, regime, aligned


# ----------------------------------------------------------------------------
# (d) Vol beta：每檔實質資產 21d RV 對 SPY 21d RV 的 OLS
# ----------------------------------------------------------------------------
def vol_beta(rv21):
    aligned = rv21[[*REAL_ASSETS, "SPY"]].dropna()
    x = aligned["SPY"].values
    out = {}
    for t in REAL_ASSETS:
        y = aligned[t].values
        X = np.column_stack([np.ones_like(x), x])
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        yhat = X @ beta
        resid = y - yhat
        ss_res = float(np.sum(resid ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
        n, k = len(y), 2

        # HAC (Newey-West) SE — 重疊窗口 residual 高度自相關，OLS SE 會低估
        L = int(np.floor(4 * (n / 100.0) ** (2 / 9)))  # Newey-West rule of thumb
        Xres = X * resid[:, None]
        S = Xres.T @ Xres
        for lag in range(1, L + 1):
            w = 1 - lag / (L + 1)
            G = Xres[lag:].T @ Xres[:-lag]
            S += w * (G + G.T)
        XtX_inv = np.linalg.inv(X.T @ X)
        cov_hac = XtX_inv @ S @ XtX_inv
        se_slope_hac = float(np.sqrt(cov_hac[1, 1]))
        t_slope_hac = float(beta[1] / se_slope_hac) if se_slope_hac > 0 else float("nan")

        _slope = float(beta[1])
        if _slope < 1.0:
            _interp = "beta<1 = vol 對市場 vol 反應弱（較大盤鈍）"
        else:
            _interp = "beta>1 = vol 對市場 vol 反應強（放大大盤 vol 變動）"
        out[t] = {
            "vol_beta_slope": round(_slope, 4),
            "intercept": round(float(beta[0]), 4),
            "r_squared": round(float(r2), 4),
            "hac_se_slope": round(se_slope_hac, 4),
            "hac_t_slope": round(t_slope_hac, 2),
            "hac_lag": int(L),
            "n": int(n),
            "interpretation": _interp,
        }
    return {
        "spec": "OLS: RV_asset_t ~ 1 + RV_SPY_t (contemporaneous 21d RV, 描述性非預測)",
        "hac_note": "Newey-West HAC SE 校正重疊窗口 residual 自相關（OLS SE 會低估）",
        "per_asset": out,
    }, aligned


# ----------------------------------------------------------------------------
# 圖表
# ----------------------------------------------------------------------------
def make_figures(rv21, corr, regime_res, regime, aligned, stress_res=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Fig 1: 10 檔 21d RV 時序
    fig, ax = plt.subplots(figsize=(13, 7))
    cmap = plt.get_cmap("tab10")
    for i, t in enumerate(ALL_TICKERS):
        s = rv21[t].dropna()
        lw = 2.2 if t == "SPY" else 1.1
        alpha = 1.0 if t in REAL_ASSETS or t == "SPY" else 0.6
        ax.plot(s.index, s.values, label=t, color=cmap(i % 10), lw=lw, alpha=alpha)
    ax.set_title("K1614 — 21-Day Annualized Realized Volatility (2015–2026)\n"
                 "Natural-Resource Real Assets (7) vs Market/Inflation/Commodity Proxies (3)",
                 fontsize=12)
    ax.set_xlabel("Date"); ax.set_ylabel("Annualized RV")
    ax.legend(ncol=5, fontsize=8, loc="upper right")
    ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(FIG_DIR / "fig1_rv_timeseries.png", dpi=130)
    plt.close(fig)

    # Fig 2: 7 檔實質資產 RV 相關熱圖
    fig, ax = plt.subplots(figsize=(8, 7))
    m = corr.loc[REAL_ASSETS, REAL_ASSETS].values
    im = ax.imshow(m, cmap="RdYlGn_r", vmin=0, vmax=1)
    ax.set_xticks(range(len(REAL_ASSETS))); ax.set_xticklabels(REAL_ASSETS, rotation=45, ha="right")
    ax.set_yticks(range(len(REAL_ASSETS))); ax.set_yticklabels(REAL_ASSETS)
    for i in range(len(REAL_ASSETS)):
        for j in range(len(REAL_ASSETS)):
            ax.text(j, i, f"{m[i, j]:.2f}", ha="center", va="center",
                    color="black", fontsize=9)
    ax.set_title("K1614 — 21d RV Pearson Correlation\n"
                 "Real-Asset Basket (Farmland/Timber/Water)", fontsize=12)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout(); fig.savefig(FIG_DIR / "fig2_rv_corr_heatmap.png", dpi=130)
    plt.close(fig)

    # Fig 3: 各 regime 下實質資產平均 RV bar chart
    fig, ax = plt.subplots(figsize=(13, 7))
    regimes = ["low", "mid", "high"]
    x = np.arange(len(REAL_ASSETS))
    width = 0.26
    colors = {"low": "#2ca02c", "mid": "#ff7f0e", "high": "#d62728"}
    for k, r in enumerate(regimes):
        vals = [regime_res["per_asset"][t]["by_regime"][r]["mean_rv"] for t in REAL_ASSETS]
        ax.bar(x + (k - 1) * width, vals, width, label=f"{r} market-vol regime",
               color=colors[r])
    ax.set_xticks(x); ax.set_xticklabels(REAL_ASSETS)
    ax.set_ylabel("Mean 21d Annualized RV")
    ax.set_title("K1614 — Real-Asset Mean RV by SPY Volatility Regime\n"
                 "(SPY 21d RV full-sample tertiles)", fontsize=12)
    ax.legend(); ax.grid(axis="y", alpha=0.3)
    fig.tight_layout(); fig.savefig(FIG_DIR / "fig3_regime_bar.png", dpi=130)
    plt.close(fig)

    if stress_res is not None:
        stress_order = ["inflation_pressure", "breakeven_21d_change", "ca_drought_intensification"]
        labels = ["Inflation pressure", "Breakeven 21d", "CA drought 4w"]
        x = np.arange(len(REAL_ASSETS))
        width = 0.24
        fig, ax = plt.subplots(figsize=(13, 7))
        colors = ["#4c78a8", "#f58518", "#54a24b"]
        for i, (stress_name, label) in enumerate(zip(stress_order, labels)):
            assets = stress_res["regime_high_low"][stress_name]["assets"]
            vals = [
                assets[t]["metrics"]["forward_rv21"]["high_low_ratio"]
                if assets[t].get("metrics") else np.nan
                for t in REAL_ASSETS
            ]
            ax.bar(x + (i - 1) * width, vals, width=width, label=label, color=colors[i])
        ax.axhline(1.0, color="black", lw=1, alpha=0.6)
        ax.set_xticks(x); ax.set_xticklabels(REAL_ASSETS)
        ax.set_ylabel("High / Low Stress Ratio of Next-21d RV")
        ax.set_title(
            "K1614 — Public-Proxy Stress Regimes vs Forward 21d Realized Volatility\n"
            "Signals are lagged; ratios are descriptive high/low splits, not Holm-gated significance",
            fontsize=12,
        )
        ax.legend()
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout(); fig.savefig(FIG_DIR / "fig4_public_proxy_stress_forward_rv.png", dpi=130)
        plt.close(fig)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main():
    print("[K1614] fetching prices ...")
    px = fetch_prices()
    n_by_asset = {t: int(px[t].dropna().shape[0]) for t in ALL_TICKERS}
    print(f"[K1614] price obs per asset: {n_by_asset}")

    logret, rv = compute_rv(px)
    rv21 = rv[PRIMARY]

    print("[K1614] (a) descriptive stats ...")
    desc = descriptive_stats(rv21)

    print("[K1614] (b) cluster consistency ...")
    cluster, corr = cluster_consistency(rv21)

    print("[K1614] (c) regime analysis ...")
    regime_res, regime, aligned = regime_analysis(rv21)

    print("[K1614] (d) vol beta ...")
    beta_res, _ = vol_beta(rv21)

    print("[K1614] (e) lagged public inflation / drought stress diagnostics ...")
    stress_res = stress_event_diagnostics(logret, rv21)

    print("[K1614] figures ...")
    make_figures(rv21, corr, regime_res, regime, aligned, stress_res=stress_res)

    verdict = stress_res["verdict"]
    if verdict == "PARTIAL_SAFE_HAVEN_PUBLIC_PROXY_DIAGNOSTIC":
        summary = (
            "Some lagged public inflation/drought proxy cells pass a conservative safe-haven gate, but the result "
            "is cell-level only and not a broad basket claim."
        )
    elif verdict == "ANTI_HEDGE_PUBLIC_PROXY_DIAGNOSTIC":
        summary = (
            "Conservative lagged public-proxy tests reject a broad low-volatility safe-haven interpretation: "
            "at least one inflation/drought stress cell has Holm-surviving positive future-volatility exposure."
        )
    elif verdict == "DIRECTIONAL_ONLY_PUBLIC_PROXY_DIAGNOSTIC":
        summary = (
            "Lagged public inflation/drought proxies show mixed directional future-volatility associations, but no "
            "Holm-surviving safe-haven gate; keep the claim at directional/public-proxy diagnostic strength."
        )
    else:
        summary = (
            "Lagged public inflation/drought proxies do not produce a stable safe-haven or risk-amplifier signal "
            "after the conservative gate."
        )

    results = {
        "experiment_id": "k1614",
        "title": "Natural-Resource Real Assets: Volatility Structure, Inflation Pressure, and Drought Stress",
        "verdict": verdict,
        "summary": summary,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "claim_type": "PUBLIC-PROXY DIAGNOSTIC — non-tradable, no implementable signal claim",
        "metadata": {
            "data_source": "yfinance adjusted close + FRED public macro series + U.S. Drought Monitor California weekly statistics",
            "period": {"start": START, "end": END},
            "generated_by": "experiments/k1614/k1614.py",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "seed": SEED,
            "trading_days_per_year": TRADING_DAYS,
            "rv_windows": RV_WINDOWS,
            "primary_rv_window": PRIMARY,
            "n_obs_per_asset": n_by_asset,
            "real_asset_basket": REAL_ASSETS,
            "subgroups": SUBGROUPS,
            "control_proxies": CONTROLS,
            "forward_horizon_trading_days": FORWARD_HORIZON,
        },
        "literature_and_data_context": LITERATURE_AND_DATA_CONTEXT,
        "data_provenance_notes": {
            "FPI_2018_short_attack": (
                "FPI 最大單日 log-return = 2018-07-11 −0.4936 (~−39%)，為 Rota Fortunae "
                "做空報告攻擊之真實公司特定事件（非資料 artifact），驅動 FPI RV max≈1.87、"
                "低 regime 敏感度與低 vol-beta R²，強化 farmland idiosyncratic 之發現。"),
            "macro_proxy_realtime_limit": (
                "CPI/PPI 使用 FRED current-vintage series，加保守發布延遲與 shift(1)。這不是 consensus "
                "surprise，也不是 real-time vintage；只可作 public-proxy diagnostic。"),
            "drought_scope_limit": (
                "USDM 以 California statewide DSCI 作 drought/climate-risk proxy。這對水資源 ETF 與農地 "
                "REIT 有經濟直覺，但不是每檔資產的完整地理曝險。"),
        },
        "a_descriptive_stats_rv21": desc,
        "b_cluster_consistency": cluster,
        "c_regime_analysis": regime_res,
        "d_vol_beta": beta_res,
        "e_inflation_drought_stress_diagnostics": stress_res,
    }

    out_path = HERE / "k1614_results.json"
    with open(out_path, "w") as f:
        json.dump(_json_safe(results), f, indent=2, ensure_ascii=False)
    print(f"[K1614] wrote {out_path}")
    print(f"[K1614] verdict = {verdict}")
    print(f"[K1614] stress summary counts = {stress_res['summary_counts']}")
    print(f"[K1614] avg pairwise corr (7 real assets, level) = {cluster['avg_pairwise_corr']}")
    print(f"[K1614] avg pairwise corr (ΔRV diff) = {cluster['diff_rv_avg_pairwise_corr']}")
    for t in REAL_ASSETS:
        b = beta_res["per_asset"][t]
        print(f"[K1614]   {t}: vol_beta={b['vol_beta_slope']}, R2={b['r_squared']}, "
              f"HAC_t={b['hac_t_slope']}")


if __name__ == "__main__":
    main()
