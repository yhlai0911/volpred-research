"""K1367: Climate-news duration as a green/brown tail-risk proxy.

This is a public-data diagnostic for the backlog idea that climate-news
response duration, not just climate-news level, may predict green/brown tail
risk. It does not replicate the proprietary/full-text JBF 2025 response-time
data. It uses GDELT DOC daily article-count intensity and liquid ETF proxies.

Information set:
    Features at date t use news and market data through t-1.
    Target at date t is realized variance or return at t.

Seed: 42
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import yfinance as yf
from scipy import stats

from volpred.stats.model_evaluation import dm_test, qlike_pointwise


EXPERIMENT_ID = "K1367"
SEED = 42
np.random.seed(SEED)

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
FIG_DIR = ROOT / "figures"
RESULTS_PATH = ROOT / f"{EXPERIMENT_ID}_results.json"
FIG_PATH = FIG_DIR / "K1367_climate_duration_summary.png"
DATA_DIR.mkdir(exist_ok=True)
FIG_DIR.mkdir(exist_ok=True)

START = "2017-01-01"
OOS_START = "2021-01-01"
END = datetime.now(timezone.utc).strftime("%Y-%m-%d")
TICKERS = ["ICLN", "TAN", "XLE", "XOP", "XLU", "SPY", "^VIX"]
ASSETS = ["ICLN", "TAN", "XLE", "XOP", "XLU"]
GREEN_ASSETS = ["ICLN", "TAN"]
BROWN_ASSETS = ["XLE", "XOP"]
MIN_TRAIN = 756

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_QUERY = (
    '("climate change" OR "global warming" OR "climate risk" OR '
    '"climate policy" OR "net zero" OR decarbonization OR "carbon emissions" '
    'OR "carbon tax" OR "energy transition") sourceCountry:US'
)

REFERENCES = [
    {
        "name": "Journal of Banking & Finance 2025 response-time model",
        "url": "https://ideas.repec.org/a/eee/jbfina/v178y2025ics037842662500127x.html",
        "use": "Motivates daily and intraday climate-news duration / response-time measurement.",
    },
    {
        "name": "Engle, Giglio, Kelly, Lee, Stroebel (2020), RFS",
        "url": "https://academic.oup.com/rfs/article-abstract/33/3/1184/5735305",
        "use": "Climate-news innovations as a tradable hedge target.",
    },
    {
        "name": "Climate Change Concerns and Green vs Brown Stocks",
        "url": "https://pubsonline.informs.org/doi/10.1287/mnsc.2022.4636",
        "use": "Green-minus-brown returns react to unexpected climate-change concerns.",
    },
    {
        "name": "Albanese et al. (2025/2026), green-brown volatility spillovers",
        "url": "https://ideas.repec.org/p/ces/ceswps/_11747.html",
        "use": "Green/brown mean and volatility linkages around climate-policy and energy shocks.",
    },
]


@dataclass(frozen=True)
class ModelSpec:
    name: str
    features: list[str]


MODEL_SPECS = [
    ModelSpec("HAR", ["log_rv_lag1", "log_rv_week", "log_rv_month"]),
    ModelSpec(
        "HAR_DURATION",
        [
            "log_rv_lag1",
            "log_rv_week",
            "log_rv_month",
            "news_duration_signal",
            "response_abs_gap_signal",
        ],
    ),
    ModelSpec(
        "HAR_VIX",
        ["log_rv_lag1", "log_rv_week", "log_rv_month", "log_vix_var_lag1"],
    ),
    ModelSpec(
        "HAR_VIX_DURATION",
        [
            "log_rv_lag1",
            "log_rv_week",
            "log_rv_month",
            "log_vix_var_lag1",
            "news_duration_signal",
            "response_abs_gap_signal",
            "response_gap_signal",
        ],
    ),
]


def _save_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _gdelt_params() -> dict[str, str]:
    return {
        "query": GDELT_QUERY,
        "mode": "timelinevolraw",
        "format": "json",
        "STARTDATETIME": START.replace("-", "") + "000000",
        "ENDDATETIME": END.replace("-", "") + "000000",
        "TIMELINESMOOTH": "0",
    }


def fetch_gdelt_timeline() -> dict:
    cache = DATA_DIR / "gdelt_climate_timeline_raw.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))

    last_text = ""
    for attempt in range(4):
        if attempt:
            time.sleep(8 * attempt)
        response = requests.get(GDELT_URL, params=_gdelt_params(), timeout=90)
        last_text = response.text[:500]
        if response.status_code == 429:
            continue
        response.raise_for_status()
        payload = response.json()
        _save_json(cache, payload)
        return payload
    raise RuntimeError(f"GDELT fetch failed after retries; last response: {last_text}")


def parse_gdelt_daily(payload: dict) -> pd.DataFrame:
    timeline = payload.get("timeline") or []
    if not timeline:
        raise ValueError("GDELT payload has no timeline")
    rows = timeline[0].get("data") or []
    if not rows:
        raise ValueError("GDELT timeline has no data rows")

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_localize(None).dt.normalize()
    df["news_count"] = pd.to_numeric(df["value"], errors="coerce")
    df["gdelt_total"] = pd.to_numeric(df["norm"], errors="coerce")
    df = df[["date", "news_count", "gdelt_total"]].dropna().sort_values("date")
    df["news_share"] = df["news_count"] / df["gdelt_total"].replace(0, np.nan)
    df["log_news_share"] = np.log(df["news_share"].clip(lower=1e-12))

    prior = df["log_news_share"].shift(1)
    mean = prior.rolling(252, min_periods=60).mean()
    std = prior.rolling(252, min_periods=60).std(ddof=1)
    df["news_z"] = ((df["log_news_share"] - mean) / std.replace(0, np.nan)).clip(-8, 8)
    df["news_z_valid"] = df["news_z"].notna()
    df["news_active"] = df["news_z"] >= 1.0
    df["news_duration"] = spell_length(df["news_active"].fillna(False))
    out = df.set_index("date")
    out.to_csv(DATA_DIR / "gdelt_climate_daily.csv")
    return out


def load_yfinance_ohlcv() -> pd.DataFrame:
    cache = DATA_DIR / "yfinance_ohlcv.csv"
    if cache.exists():
        df = pd.read_csv(cache, header=[0, 1], index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        return df

    df = yf.download(
        TICKERS,
        start=START,
        end=END,
        auto_adjust=False,
        progress=False,
        group_by="ticker",
        threads=False,
    )
    if not isinstance(df.columns, pd.MultiIndex):
        raise ValueError("Expected yfinance multi-index columns")
    df = df.sort_index()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df.to_csv(cache)
    return df


def asset_ohlc(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if ticker not in raw.columns.get_level_values(0):
        raise ValueError(f"Ticker missing from yfinance data: {ticker}")
    out = raw[ticker].copy()
    required = ["Open", "High", "Low", "Close"]
    missing = [col for col in required if col not in out.columns]
    if missing:
        raise ValueError(f"{ticker} missing OHLC columns: {missing}")
    return out.dropna(subset=required)


def garman_klass_rv(asset: pd.DataFrame) -> pd.Series:
    op = asset["Open"].astype(float)
    hi = asset["High"].astype(float)
    lo = asset["Low"].astype(float)
    cl = asset["Close"].astype(float)
    valid = (op > 0) & (hi > 0) & (lo > 0) & (cl > 0)
    rv = pd.Series(np.nan, index=asset.index, dtype=float)
    rv.loc[valid] = (
        0.5 * np.log(hi.loc[valid] / lo.loc[valid]) ** 2
        - (2 * math.log(2) - 1) * np.log(cl.loc[valid] / op.loc[valid]) ** 2
    )
    return rv.clip(lower=1e-10)


def spell_length(active: pd.Series | np.ndarray) -> pd.Series:
    values = np.asarray(active, dtype=bool)
    lengths = np.zeros(len(values), dtype=int)
    current = 0
    for i, value in enumerate(values):
        current = current + 1 if value else 0
        lengths[i] = current
    index = active.index if isinstance(active, pd.Series) else None
    return pd.Series(lengths, index=index)


def prior_rolling_z(series: pd.Series, window: int = 126, min_periods: int = 42) -> pd.Series:
    prior = series.shift(1)
    mean = prior.rolling(window, min_periods=min_periods).mean()
    std = prior.rolling(window, min_periods=min_periods).std(ddof=1)
    return ((series - mean) / std.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)


def build_market_signals(raw: pd.DataFrame, gdelt: pd.DataFrame) -> pd.DataFrame:
    closes = {}
    returns = {}
    rvs = {}
    for ticker in ASSETS + ["SPY"]:
        asset = asset_ohlc(raw, ticker)
        closes[ticker] = asset["Close"].astype(float)
        returns[ticker] = np.log(closes[ticker]).diff()
        rvs[ticker] = garman_klass_rv(asset)

    index = pd.Index(sorted(set().union(*(s.index for s in closes.values()))), name="date")
    ret_df = pd.DataFrame({ticker: returns[ticker].reindex(index) for ticker in returns})
    rv_df = pd.DataFrame({ticker: rvs[ticker].reindex(index) for ticker in rvs})

    green_ret = ret_df[GREEN_ASSETS].mean(axis=1)
    brown_ret = ret_df[BROWN_ASSETS].mean(axis=1)
    green_abs_z = prior_rolling_z(green_ret.abs())
    brown_abs_z = prior_rolling_z(brown_ret.abs())

    gdelt_daily = gdelt.reindex(gdelt.index.union(index)).sort_index().ffill().reindex(index)
    active = gdelt_daily["news_active"].fillna(False).astype(bool)
    news_duration = gdelt_daily["news_duration"].fillna(0).astype(float)

    green_reacts = active & (green_abs_z > 0.5)
    brown_reacts = active & (brown_abs_z > 0.5)
    green_reaction_duration = spell_length(green_reacts)
    brown_reaction_duration = spell_length(brown_reacts)
    response_gap = green_reaction_duration - brown_reaction_duration

    signal = pd.DataFrame(index=index)
    signal["green_ret"] = green_ret
    signal["brown_ret"] = brown_ret
    signal["green_brown_spread_ret"] = green_ret - brown_ret
    signal["climate_news_z"] = gdelt_daily["news_z"]
    signal["news_duration_raw"] = news_duration
    signal["green_reaction_duration_raw"] = green_reaction_duration
    signal["brown_reaction_duration_raw"] = brown_reaction_duration
    signal["response_gap_raw"] = response_gap
    signal["response_abs_gap_raw"] = response_gap.abs()
    signal["news_duration_signal"] = signal["news_duration_raw"].shift(1)
    signal["response_gap_signal"] = signal["response_gap_raw"].shift(1)
    signal["response_abs_gap_signal"] = signal["response_abs_gap_raw"].shift(1)
    signal["climate_news_z_signal"] = signal["climate_news_z"].shift(1)
    signal["news_active_signal"] = active.shift(1).fillna(False).astype(int)
    signal["green_reacts_raw"] = green_reacts.astype(int)
    signal["brown_reacts_raw"] = brown_reacts.astype(int)
    signal = signal.replace([np.inf, -np.inf], np.nan)

    rv_df.to_csv(DATA_DIR / "asset_daily_rv.csv", index_label="date")
    signal.to_csv(DATA_DIR / "climate_duration_signals.csv", index_label="date")
    return signal


def build_asset_panel(raw: pd.DataFrame, signal: pd.DataFrame) -> pd.DataFrame:
    vix_close = asset_ohlc(raw, "^VIX")["Close"].astype(float)
    vix_var = (vix_close / 100.0).pow(2) / 252.0
    frames = []
    for ticker in ASSETS:
        asset = asset_ohlc(raw, ticker)
        close = asset["Close"].astype(float)
        ret = np.log(close).diff()
        rv = garman_klass_rv(asset)
        log_rv = np.log(rv)
        frame = pd.DataFrame(index=asset.index)
        frame["asset"] = ticker
        frame["ret"] = ret
        frame["target_rv"] = rv
        frame["target_log_rv"] = log_rv
        frame["log_rv_lag1"] = log_rv.shift(1)
        frame["log_rv_week"] = log_rv.shift(1).rolling(5).mean()
        frame["log_rv_month"] = log_rv.shift(1).rolling(22).mean()
        frame["log_vix_var_lag1"] = np.log(vix_var.reindex(frame.index).ffill().shift(1) + 1e-12)
        for col in [
            "news_duration_signal",
            "response_gap_signal",
            "response_abs_gap_signal",
            "climate_news_z_signal",
            "news_active_signal",
        ]:
            frame[col] = signal[col].reindex(frame.index)
        frames.append(frame)
    panel = pd.concat(frames).reset_index(names="date")
    panel = panel.replace([np.inf, -np.inf], np.nan)
    panel.to_csv(DATA_DIR / "model_panel.csv", index=False)
    return panel


def fit_predict_expanding(asset_df: pd.DataFrame, spec: ModelSpec) -> pd.DataFrame:
    cols = ["date", "target_rv", "target_log_rv"] + spec.features
    df = asset_df[cols].dropna().sort_values("date").reset_index(drop=True)
    rows: list[dict[str, object]] = []
    last_beta: np.ndarray | None = None
    for i in range(len(df)):
        date = pd.Timestamp(df.loc[i, "date"])
        if date < pd.Timestamp(OOS_START) or i < MIN_TRAIN:
            continue
        train = df.iloc[:i].dropna(subset=["target_log_rv"] + spec.features)
        if len(train) < MIN_TRAIN:
            continue
        if last_beta is None or i % 21 == 0:
            x_train = np.column_stack([np.ones(len(train)), train[spec.features].to_numpy(float)])
            y_train = train["target_log_rv"].to_numpy(float)
            last_beta = np.linalg.lstsq(x_train, y_train, rcond=None)[0]
        x_now = np.r_[1.0, df.loc[i, spec.features].to_numpy(float)]
        pred_log = float(np.dot(x_now, last_beta))
        pred_rv = float(np.exp(np.clip(pred_log, -30, 5)))
        rows.append(
            {
                "date": date,
                "model": spec.name,
                "target_rv": float(df.loc[i, "target_rv"]),
                "pred_rv": pred_rv,
            }
        )
    return pd.DataFrame(rows)


def run_forecasts(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    forecasts = []
    for asset in ASSETS:
        asset_df = panel.loc[panel["asset"] == asset].sort_values("date").copy()
        for spec in MODEL_SPECS:
            pred = fit_predict_expanding(asset_df, spec)
            if pred.empty:
                continue
            pred["asset"] = asset
            pred["loss"] = qlike_pointwise(pred["target_rv"].to_numpy(), pred["pred_rv"].to_numpy())
            forecasts.append(pred)
    if not forecasts:
        raise RuntimeError("No forecasts generated")
    forecast_df = pd.concat(forecasts, ignore_index=True)
    forecast_df.to_csv(DATA_DIR / "forecast_oos.csv", index=False)

    by_asset: dict[str, dict[str, object]] = {}
    for asset in ASSETS:
        asset_rows = forecast_df.loc[forecast_df["asset"] == asset]
        by_asset[asset] = {}
        for model in sorted(asset_rows["model"].unique()):
            m = asset_rows.loc[asset_rows["model"] == model]
            by_asset[asset][model] = {
                "n_oos": int(len(m)),
                "mean_qlike": float(m["loss"].mean()),
            }

    comparisons: dict[str, object] = {}
    for challenger, base in [("HAR_DURATION", "HAR"), ("HAR_VIX_DURATION", "HAR_VIX")]:
        comp_key = f"{challenger}_vs_{base}"
        asset_stats = {}
        pooled_model_losses = []
        pooled_base_losses = []
        for asset in ASSETS:
            pivot = forecast_df.loc[forecast_df["asset"] == asset].pivot_table(
                index="date", columns="model", values="loss", aggfunc="last"
            )
            if challenger not in pivot or base not in pivot:
                continue
            valid = pivot[[challenger, base]].dropna()
            if len(valid) < 20:
                continue
            t_stat, p_val = dm_test(valid[challenger].to_numpy(), valid[base].to_numpy(), h=1)
            improve = (valid[base].mean() - valid[challenger].mean()) / abs(valid[base].mean())
            asset_stats[asset] = {
                "n": int(len(valid)),
                "challenger_mean_qlike": float(valid[challenger].mean()),
                "base_mean_qlike": float(valid[base].mean()),
                "qlike_improvement_pct": float(100 * improve),
                "dm_t": float(t_stat),
                "dm_p": float(p_val),
            }
            pooled_model_losses.append(valid[challenger].rename(asset))
            pooled_base_losses.append(valid[base].rename(asset))
        model_loss = pd.concat(pooled_model_losses, axis=1).mean(axis=1)
        base_loss = pd.concat(pooled_base_losses, axis=1).mean(axis=1)
        pooled = pd.concat([model_loss.rename("challenger"), base_loss.rename("base")], axis=1).dropna()
        pooled_t, pooled_p = dm_test(pooled["challenger"].to_numpy(), pooled["base"].to_numpy(), h=1)
        comparisons[comp_key] = {
            "pooled_n_dates": int(len(pooled)),
            "pooled_challenger_mean_qlike": float(pooled["challenger"].mean()),
            "pooled_base_mean_qlike": float(pooled["base"].mean()),
            "pooled_qlike_improvement_pct": float(
                100 * (pooled["base"].mean() - pooled["challenger"].mean()) / abs(pooled["base"].mean())
            ),
            "pooled_dm_t": float(pooled_t),
            "pooled_dm_p": float(pooled_p),
            "assets_improved": int(
                sum(1 for s in asset_stats.values() if s["qlike_improvement_pct"] > 0)
            ),
            "by_asset": asset_stats,
        }
    return forecast_df, {"by_asset_model": by_asset, "comparisons": comparisons}


def future_corr(green: pd.Series, brown: pd.Series, horizon: int = 5) -> pd.Series:
    out = pd.Series(np.nan, index=green.index, dtype=float)
    for i in range(0, len(green) - horizon + 1):
        g = green.iloc[i : i + horizon]
        b = brown.iloc[i : i + horizon]
        valid = g.notna() & b.notna()
        if valid.sum() >= 4:
            out.iloc[i] = float(g[valid].corr(b[valid]))
    return out


def fisher_group_test(group: pd.Series, event: pd.Series) -> dict[str, object]:
    valid = group.notna() & event.notna()
    g = group[valid].astype(bool)
    e = event[valid].astype(bool)
    high_n = int(g.sum())
    low_n = int((~g).sum())
    high_events = int((g & e).sum())
    low_events = int(((~g) & e).sum())
    if min(high_n, low_n) == 0:
        return {
            "high_n": high_n,
            "low_n": low_n,
            "high_event_rate": None,
            "low_event_rate": None,
            "rate_lift": None,
            "fisher_p": None,
        }
    table = [[high_events, high_n - high_events], [low_events, low_n - low_events]]
    _, p_val = stats.fisher_exact(table, alternative="two-sided")
    high_rate = high_events / high_n
    low_rate = low_events / low_n
    return {
        "high_n": high_n,
        "low_n": low_n,
        "high_events": high_events,
        "low_events": low_events,
        "high_event_rate": float(high_rate),
        "low_event_rate": float(low_rate),
        "rate_lift": float(high_rate / low_rate) if low_rate > 0 else None,
        "fisher_p": float(p_val),
    }


def tail_and_corr_diagnostics(panel: pd.DataFrame, signal: pd.DataFrame) -> dict[str, object]:
    diagnostics: dict[str, object] = {}
    signal_oos = signal.loc[signal.index >= pd.Timestamp(OOS_START)].copy()
    high_news_duration = signal_oos["news_duration_signal"] >= 2
    high_response_gap = signal_oos["response_abs_gap_signal"] >= 2
    any_duration_signal = signal_oos["news_duration_signal"] >= 1

    for asset in ASSETS:
        rows = panel.loc[panel["asset"] == asset].copy()
        rows["date"] = pd.to_datetime(rows["date"])
        rows = rows.set_index("date").sort_index()
        rows = rows.loc[rows.index >= pd.Timestamp(OOS_START)]
        ret = rows["ret"]
        tail_threshold = ret.shift(1).rolling(756, min_periods=252).quantile(0.05)
        tail_event = ret <= tail_threshold
        loss_tail = ret.where(tail_event)
        diagnostics[asset] = {
            "tail_event_high_news_duration": fisher_group_test(high_news_duration.reindex(rows.index), tail_event),
            "tail_event_high_response_gap": fisher_group_test(high_response_gap.reindex(rows.index), tail_event),
            "tail_event_any_duration_signal": fisher_group_test(any_duration_signal.reindex(rows.index), tail_event),
            "es5_high_response_gap": safe_mean(loss_tail.loc[high_response_gap.reindex(rows.index).fillna(False)]),
            "es5_low_response_gap": safe_mean(loss_tail.loc[~high_response_gap.reindex(rows.index).fillna(False)]),
        }

    green = signal["green_ret"]
    brown = signal["brown_ret"]
    corr5 = future_corr(green, brown, horizon=5)
    corr_q75 = corr5.shift(1).rolling(756, min_periods=252).quantile(0.75)
    corr_spike = corr5 > corr_q75
    corr_valid = corr5.notna() & corr_q75.notna()
    corr_frame = pd.DataFrame(
        {
            "corr5": corr5,
            "corr_q75_prior": corr_q75,
            "corr_spike": corr_spike.where(corr_valid),
            "high_news_duration": high_news_duration.reindex(corr5.index),
            "high_response_gap": high_response_gap.reindex(corr5.index),
        }
    )
    corr_frame = corr_frame.loc[corr_frame.index >= pd.Timestamp(OOS_START)]
    corr_frame.to_csv(DATA_DIR / "green_brown_future_corr.csv", index_label="date")
    diagnostics["green_brown_corr_spike"] = {
        "high_news_duration": fisher_group_test(corr_frame["high_news_duration"], corr_frame["corr_spike"]),
        "high_response_gap": fisher_group_test(corr_frame["high_response_gap"], corr_frame["corr_spike"]),
        "valid_corr_n": int(corr_frame["corr_spike"].notna().sum()),
        "note": "5-day forward correlation windows overlap; treat as diagnostic.",
    }
    return diagnostics


def safe_mean(series: pd.Series) -> float | None:
    values = series.dropna()
    if values.empty:
        return None
    return float(values.mean())


def infer_verdict(forecast_results: dict[str, object], diagnostics: dict[str, object]) -> str:
    comp = forecast_results["comparisons"]["HAR_VIX_DURATION_vs_HAR_VIX"]
    qlike_pass = (
        comp["pooled_qlike_improvement_pct"] > 0
        and comp["pooled_dm_t"] < -3.0
        and comp["assets_improved"] >= 3
    )
    corr_lift = diagnostics["green_brown_corr_spike"]["high_response_gap"].get("rate_lift")
    corr_p = diagnostics["green_brown_corr_spike"]["high_response_gap"].get("fisher_p")
    corr_pass = corr_lift is not None and corr_lift > 1.25 and corr_p is not None and corr_p < 0.05
    if qlike_pass and corr_pass:
        return "CONDITIONAL_PASS_PROXY"
    if comp["pooled_qlike_improvement_pct"] > 0 or corr_pass:
        return "MIXED_WEAK_PROXY"
    return "NULL"


def make_figure(signal: pd.DataFrame, forecast_df: pd.DataFrame) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=False)

    s = signal.loc[signal.index >= pd.Timestamp("2020-01-01")]
    axes[0].plot(s.index, s["climate_news_z"], lw=0.9, color="#2f6f8f", label="Climate news z")
    axes[0].axhline(1.0, color="#a23b3b", lw=0.8, ls="--", label="Active threshold")
    axes[0].set_title("GDELT climate-news intensity")
    axes[0].legend(loc="upper right")

    axes[1].plot(s.index, s["news_duration_raw"], lw=0.9, label="News active spell")
    axes[1].plot(s.index, s["response_abs_gap_raw"], lw=0.9, label="Abs green/brown response duration gap")
    axes[1].set_title("Duration proxy")
    axes[1].legend(loc="upper right")

    comp_rows = []
    for asset in ASSETS:
        pivot = forecast_df.loc[forecast_df["asset"] == asset].pivot_table(
            index="date", columns="model", values="loss", aggfunc="last"
        )
        if "HAR_VIX_DURATION" in pivot and "HAR_VIX" in pivot:
            valid = pivot[["HAR_VIX_DURATION", "HAR_VIX"]].dropna()
            improve = 100 * (valid["HAR_VIX"].mean() - valid["HAR_VIX_DURATION"].mean()) / abs(
                valid["HAR_VIX"].mean()
            )
            comp_rows.append((asset, improve))
    labels = [x[0] for x in comp_rows]
    values = [x[1] for x in comp_rows]
    colors = ["#2c7a4b" if v > 0 else "#b1443c" for v in values]
    axes[2].bar(labels, values, color=colors)
    axes[2].axhline(0, color="black", lw=0.8)
    axes[2].set_ylabel("QLIKE improvement %")
    axes[2].set_title("HAR+VIX+duration vs HAR+VIX")

    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=160)
    plt.close(fig)


def main() -> None:
    gdelt = parse_gdelt_daily(fetch_gdelt_timeline())
    raw = load_yfinance_ohlcv()
    signal = build_market_signals(raw, gdelt)
    panel = build_asset_panel(raw, signal)
    forecast_df, forecast_results = run_forecasts(panel)
    diagnostics = tail_and_corr_diagnostics(panel, signal)
    make_figure(signal, forecast_df)
    verdict = infer_verdict(forecast_results, diagnostics)

    sample_dates = pd.to_datetime(panel["date"])
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "verdict": verdict,
        "seed": SEED,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "data": {
            "market_source": "yfinance daily OHLCV",
            "news_source": "GDELT DOC 2.0 TimelineVolRaw",
            "sample_start": str(sample_dates.min().date()),
            "sample_end": str(sample_dates.max().date()),
            "oos_start": OOS_START,
            "assets": ASSETS,
            "green_assets": GREEN_ASSETS,
            "brown_assets": BROWN_ASSETS,
            "gdelt_query": GDELT_QUERY,
            "gdelt_rows": int(len(gdelt)),
            "active_news_days": int(gdelt["news_active"].sum()),
        },
        "lookahead_policy": {
            "market_features": "log_rv and VIX features are shifted by one trading day.",
            "news_features": "news_duration_signal/response_gap_signal are explicit .shift(1) features.",
            "tail_thresholds": "tail event thresholds use prior rolling 756-day 5% quantiles.",
            "correlation_spike_threshold": "future 5d correlation spike uses prior rolling 756-day q75 threshold.",
        },
        "models": {
            "target": "daily Garman-Klass range variance",
            "oos_fit": "expanding OLS, refit every 21 trading rows, MIN_TRAIN=756",
            "success_gate": (
                "CONDITIONAL_PASS_PROXY requires HAR_VIX_DURATION pooled DM t<-3, "
                "positive pooled QLIKE improvement, >=3/5 assets improved, and a significant "
                "green/brown correlation-spike lift for high response-duration gap."
            ),
        },
        "forecast_results": forecast_results,
        "tail_and_corr_diagnostics": diagnostics,
        "references": REFERENCES,
        "artifacts": {
            "script": "experiments/K1367/K1367.py",
            "results": "experiments/K1367/K1367_results.json",
            "figure": "experiments/K1367/figures/K1367_climate_duration_summary.png",
            "data_dir": "experiments/K1367/data/",
        },
        "claim_ceiling": (
            "This is a free daily proxy diagnostic. It cannot validate or refute the "
            "JBF response-time model's proprietary daily/intraday duration data."
        ),
    }
    _save_json(RESULTS_PATH, payload)
    print(json.dumps({"ok": True, "experiment_id": EXPERIMENT_ID, "verdict": verdict}, indent=2))


if __name__ == "__main__":
    main()
