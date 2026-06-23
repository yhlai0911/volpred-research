"""K1367: Climate-news duration and green/brown tail-risk response.

This is a free-data proxy diagnostic, not a replication of the firm-level
daily/intraday response-time model in Fahmy (2025).  It uses GDELT DOC
TimelineVolRaw climate-news counts and daily ETF prices to test whether
longer climate-news attention duration or slower green/brown price response
predicts subsequent ETF realized risk.
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf
from scipy import stats


EXPERIMENT_ID = "K1367"
SEED = 42
START = "2017-01-01"
END = datetime.now(timezone.utc).strftime("%Y-%m-%d")

GREEN_TICKERS = ["ICLN", "TAN"]
BROWN_TICKERS = ["XLE", "XOP"]
OTHER_TICKERS = ["XLU", "SPY"]
TICKERS = GREEN_TICKERS + BROWN_TICKERS + OTHER_TICKERS

CORE_NEWS_Z = 1.5
ACTIVE_NEWS_Z = 0.5
REACTION_OBSERVE_DAYS = 3
MAX_RESPONSE_DAYS = 5
FORWARD_RISK_HORIZON = 5
FORWARD_CORR_HORIZON = 21
ROLLING_WINDOW = 252
MIN_ROLLING = 126
BOOT_REPS = 1000

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_PATH = HERE / f"{EXPERIMENT_ID}_results.json"
EVENT_FEATURES_PATH = HERE / f"{EXPERIMENT_ID}_event_features.csv"
MODEL_PANEL_PATH = HERE / f"{EXPERIMENT_ID}_model_panel.csv"
FIG_NEWS_PATH = HERE / f"{EXPERIMENT_ID}_news_duration_events.png"
FIG_COEF_PATH = HERE / f"{EXPERIMENT_ID}_coefficients.png"
FIG_DIAG_PATH = HERE / f"{EXPERIMENT_ID}_event_diagnostics.png"

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_QUERY = (
    '("climate change" OR "climate policy" OR "carbon emissions" OR '
    '"global warming" OR "clean energy transition" OR "net zero" OR '
    '"carbon tax")'
)

np.random.seed(SEED)


def json_default(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return None if not np.isfinite(obj) else float(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.date().isoformat()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return str(obj)


def save_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=json_default),
        encoding="utf-8",
    )


def gdelt_params(start: str, end: str) -> dict[str, str]:
    return {
        "query": GDELT_QUERY,
        "mode": "timelinevolraw",
        "format": "json",
        "STARTDATETIME": start.replace("-", "") + "000000",
        "ENDDATETIME": end.replace("-", "") + "000000",
        "TIMELINESMOOTH": "0",
    }


def fetch_gdelt_timeline() -> dict:
    """Fetch or load daily climate-news counts from GDELT DOC TimelineVolRaw."""
    cache = DATA_DIR / "gdelt_climate_timeline_raw.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))

    params = gdelt_params(START, END)
    last_response = ""
    for attempt in range(5):
        if attempt:
            time.sleep(8 * attempt)
        response = requests.get(
            GDELT_URL,
            params=params,
            timeout=90,
            headers={"User-Agent": "volpred-k1367/1.0"},
        )
        last_response = response.text[:500]
        if response.status_code == 429:
            continue
        response.raise_for_status()
        payload = response.json()
        save_json(cache, payload)
        return payload
    raise RuntimeError(f"GDELT fetch failed after retries; last response={last_response!r}")


def parse_gdelt_daily(payload: dict) -> pd.DataFrame:
    timeline = payload.get("timeline") or []
    if not timeline:
        raise ValueError("GDELT payload has no timeline")
    data = timeline[0].get("data") or []
    df = pd.DataFrame(data)
    if df.empty:
        raise ValueError("GDELT timeline has no rows")

    df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_convert(None).dt.normalize()
    df["news_count"] = pd.to_numeric(df["value"], errors="coerce")
    df["gdelt_total"] = pd.to_numeric(df["norm"], errors="coerce")
    df = df[["date", "news_count", "gdelt_total"]].dropna().sort_values("date")
    df["news_share"] = df["news_count"] / df["gdelt_total"].replace(0, np.nan)
    df["log_news_share"] = np.log(df["news_share"].clip(lower=1e-12))

    roll_mean = df["log_news_share"].shift(1).rolling(ROLLING_WINDOW, min_periods=60).mean()
    roll_std = df["log_news_share"].shift(1).rolling(ROLLING_WINDOW, min_periods=60).std()
    df["news_z"] = ((df["log_news_share"] - roll_mean) / roll_std).replace(
        [np.inf, -np.inf], np.nan
    )
    df["news_z"] = df["news_z"].clip(-8, 8)
    out = df.set_index("date").sort_index()
    out.to_csv(DATA_DIR / "gdelt_climate_daily.csv")
    return out


def build_news_events(gdelt: pd.DataFrame) -> pd.DataFrame:
    """Cluster climate-news attention episodes.

    Active clusters require news_z >= ACTIVE_NEWS_Z and are retained only if
    they contain at least one core day with news_z >= CORE_NEWS_Z.  The active
    cluster length is the observed duration/decay proxy.
    """
    rows: list[dict] = []
    active_dates: list[pd.Timestamp] = []

    for date, value in gdelt["news_z"].dropna().items():
        is_active = bool(value >= ACTIVE_NEWS_Z)
        if is_active:
            active_dates.append(date)
            continue
        if active_dates:
            rows.extend(_finalize_event_cluster(active_dates, gdelt))
            active_dates = []
    if active_dates:
        rows.extend(_finalize_event_cluster(active_dates, gdelt))

    events = pd.DataFrame(rows)
    if events.empty:
        raise ValueError("No GDELT climate-news duration events found")
    events = events.sort_values("start_date").reset_index(drop=True)
    events["event_id"] = [f"{EXPERIMENT_ID}_event_{i:03d}" for i in range(len(events))]
    return events


def _finalize_event_cluster(active_dates: list[pd.Timestamp], gdelt: pd.DataFrame) -> list[dict]:
    cluster = gdelt.loc[active_dates]
    if cluster["news_z"].max() < CORE_NEWS_Z:
        return []
    peak_date = cluster["news_z"].idxmax()
    start_date = active_dates[0]
    end_date = active_dates[-1]
    core_days = int((cluster["news_z"] >= CORE_NEWS_Z).sum())
    duration_days = int(len(active_dates))
    decay_days = int(max((end_date - peak_date).days, 0))
    return [
        {
            "start_date": start_date,
            "end_date": end_date,
            "peak_date": peak_date,
            "duration_days": duration_days,
            "core_days": core_days,
            "decay_days": decay_days,
            "peak_news_z": float(cluster["news_z"].max()),
            "mean_news_z": float(cluster["news_z"].mean()),
            "news_count_total": float(cluster["news_count"].sum()),
        }
    ]


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
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    if not isinstance(df.columns, pd.MultiIndex):
        raise ValueError("Expected yfinance multi-index columns for multiple tickers")
    df = df.sort_index()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df.to_csv(cache)
    return df


def close_prices(yfin: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for ticker in TICKERS:
        if ticker in yfin.columns.get_level_values(0):
            sub = yfin[ticker]
        else:
            sub = yfin.xs(ticker, axis=1, level=1)
        if "Close" not in sub.columns:
            raise ValueError(f"Missing Close column for {ticker}")
        frames.append(sub["Close"].rename(ticker))
    prices = pd.concat(frames, axis=1).dropna(how="all").sort_index()
    return prices.dropna(subset=["SPY"])


def first_trading_on_or_after(index: pd.DatetimeIndex, date: pd.Timestamp) -> int | None:
    loc = int(index.searchsorted(pd.Timestamp(date)))
    if loc >= len(index):
        return None
    return loc


def response_time_days(
    excess_returns: pd.Series,
    trading_index: pd.DatetimeIndex,
    start_loc: int,
    end_loc: int,
) -> float:
    """First day where cumulative absolute excess return exceeds lagged sigma."""
    if start_loc <= 0 or end_loc < start_loc:
        return float("nan")
    sigma = excess_returns.shift(1).rolling(60, min_periods=30).std().iloc[start_loc]
    if not np.isfinite(sigma) or sigma <= 0:
        return float("nan")
    threshold = max(float(sigma), 0.005)
    path = excess_returns.iloc[start_loc : end_loc + 1].fillna(0.0).cumsum().abs()
    crossed = np.flatnonzero(path.values >= threshold)
    if len(crossed):
        return float(crossed[0])
    return float(len(path))


def add_price_reaction_features(events: pd.DataFrame, returns: pd.DataFrame) -> pd.DataFrame:
    idx = returns.index
    green_excess = returns["green"] - returns["SPY"]
    brown_excess = returns["brown"] - returns["SPY"]
    enriched = []

    for row in events.to_dict("records"):
        start_loc = first_trading_on_or_after(idx, pd.Timestamp(row["start_date"]))
        end_loc = first_trading_on_or_after(idx, pd.Timestamp(row["end_date"]))
        if start_loc is None or end_loc is None:
            continue
        feature_loc = max(end_loc, min(len(idx) - 1, start_loc + REACTION_OBSERVE_DAYS - 1))
        response_end_loc = min(feature_loc, start_loc + MAX_RESPONSE_DAYS - 1)
        if feature_loc + FORWARD_CORR_HORIZON >= len(idx):
            continue

        green_response = response_time_days(green_excess, idx, start_loc, response_end_loc)
        brown_response = response_time_days(brown_excess, idx, start_loc, response_end_loc)
        if not np.isfinite(green_response) or not np.isfinite(brown_response):
            continue

        out = dict(row)
        out["start_trade_date"] = idx[start_loc]
        out["feature_date"] = idx[feature_loc]
        out["response_observed_through"] = idx[response_end_loc]
        out["green_response_days"] = green_response
        out["brown_response_days"] = brown_response
        out["reaction_gap_green_minus_brown"] = green_response - brown_response
        out["reaction_gap_abs"] = abs(green_response - brown_response)
        out["slow_response_days"] = max(green_response, brown_response)
        out["duration_score"] = (
            math.log1p(float(out["duration_days"]))
            + 0.5 * math.log1p(float(out["decay_days"]))
        )
        out["duration_reaction_score"] = out["duration_score"] * (1.0 + out["reaction_gap_abs"])
        enriched.append(out)

    out = pd.DataFrame(enriched).sort_values("feature_date").reset_index(drop=True)
    if out.empty:
        raise ValueError("No events left after ETF reaction-feature alignment")
    return out


def rolling_es_loss(returns: pd.Series, alpha: float = 0.05) -> pd.Series:
    def _es(values: np.ndarray) -> float:
        arr = values[np.isfinite(values)]
        if len(arr) < MIN_ROLLING:
            return float("nan")
        q = np.quantile(arr, alpha)
        tail = arr[arr <= q]
        if len(tail) == 0:
            return float("nan")
        return float(-tail.mean())

    return returns.shift(1).rolling(ROLLING_WINDOW, min_periods=MIN_ROLLING).apply(
        _es,
        raw=True,
    )


def forward_realized_variance(returns: pd.Series, horizon: int) -> pd.Series:
    return returns.pow(2).rolling(horizon).sum().shift(-(horizon - 1)) * (252.0 / horizon)


def forward_cumulative_return(returns: pd.Series, horizon: int) -> pd.Series:
    return returns.rolling(horizon).sum().shift(-(horizon - 1))


def forward_min_return(returns: pd.Series, horizon: int) -> pd.Series:
    return returns.rolling(horizon).min().shift(-(horizon - 1))


def build_market_panel(events: pd.DataFrame, returns: pd.DataFrame, gdelt: pd.DataFrame) -> pd.DataFrame:
    daily = pd.DataFrame(index=returns.index)

    grouped = (
        events.groupby("feature_date")
        [
            [
                "duration_score",
                "duration_reaction_score",
                "reaction_gap_abs",
                "slow_response_days",
                "peak_news_z",
                "duration_days",
                "decay_days",
            ]
        ]
        .mean()
    )
    daily = daily.join(grouped, how="left")

    signal = daily[
        [
            "duration_score",
            "duration_reaction_score",
            "reaction_gap_abs",
            "slow_response_days",
            "peak_news_z",
            "duration_days",
            "decay_days",
        ]
    ]
    # Lookahead guard: event features become usable only on the next trading day.
    signal_lagged = signal.shift(1)

    panel = pd.DataFrame(index=returns.index)
    for col in signal.columns:
        panel[f"{col}_lag1"] = signal_lagged[col]

    news = gdelt["news_z"].reindex(gdelt.index.union(returns.index)).sort_index().ffill()
    panel["daily_news_z_lag1"] = news.reindex(returns.index).shift(1)
    panel["spy_rv21_lag1"] = (
        returns["SPY"].pow(2).rolling(21, min_periods=10).sum().shift(1) * (252.0 / 21.0)
    )
    panel["abs_spy_ret_lag1"] = returns["SPY"].abs().shift(1)

    for name in ["green", "brown"]:
        ret = returns[name]
        fwd_rv = forward_realized_variance(ret, FORWARD_RISK_HORIZON)
        fwd_cum = forward_cumulative_return(ret, FORWARD_RISK_HORIZON)
        fwd_min = forward_min_return(ret, FORWARD_RISK_HORIZON)
        hist_var = ret.shift(1).rolling(ROLLING_WINDOW, min_periods=MIN_ROLLING).quantile(0.05)
        hist_es = rolling_es_loss(ret, alpha=0.05)
        panel[f"{name}_rv5"] = fwd_rv
        panel[f"{name}_left_tail_loss5"] = (-fwd_cum).clip(lower=0.0)
        panel[f"{name}_var5_breach"] = (fwd_min < hist_var).astype(float)
        panel[f"{name}_var5_breach"] = panel[f"{name}_var5_breach"].where(hist_var.notna())
        panel[f"{name}_es_gap5"] = ((-fwd_min) - hist_es).clip(lower=0.0)
        panel[f"{name}_es_gap5"] = panel[f"{name}_es_gap5"].where(hist_es.notna())

    future_corr = returns["green"].rolling(FORWARD_CORR_HORIZON).corr(returns["brown"]).shift(
        -(FORWARD_CORR_HORIZON - 1)
    )
    trailing_corr = (
        returns["green"].shift(1).rolling(63, min_periods=30).corr(returns["brown"].shift(1))
    )
    panel["green_brown_corr_spike21"] = future_corr - trailing_corr
    panel["green_brown_corr_level21"] = future_corr

    panel = panel.reset_index(names="date")
    panel.to_csv(MODEL_PANEL_PATH, index=False)
    return panel


def standardize_regressors(df: pd.DataFrame, predictors: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in predictors:
        std = out[col].std(ddof=0)
        if np.isfinite(std) and std > 0:
            out[col] = (out[col] - out[col].mean()) / std
    return out


def run_ols(panel: pd.DataFrame, target: str, predictors: list[str]) -> dict:
    df = panel[[target] + predictors].dropna()
    if len(df) < 20:
        return {"target": target, "n": int(len(df)), "status": "insufficient_sample"}
    reg = standardize_regressors(df, predictors)
    y = reg[target].astype(float)
    x = sm.add_constant(reg[predictors].astype(float), has_constant="add")
    fit = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": min(5, max(1, int(len(df) ** 0.5)))})
    coefs = {}
    for col in ["const"] + predictors:
        coefs[col] = {
            "coef": float(fit.params.get(col, np.nan)),
            "se_hac": float(fit.bse.get(col, np.nan)),
            "t_hac": float(fit.tvalues.get(col, np.nan)),
            "p_hac": float(fit.pvalues.get(col, np.nan)),
        }
    return {
        "target": target,
        "n": int(len(df)),
        "status": "ok",
        "r2": float(fit.rsquared),
        "predictors_scaled": "All non-constant regressors standardized within the regression sample.",
        "coefs": coefs,
    }


def bootstrap_diff(top: pd.Series, bottom: pd.Series) -> dict:
    top = top.dropna().astype(float)
    bottom = bottom.dropna().astype(float)
    if len(top) < 5 or len(bottom) < 5:
        return {"status": "insufficient_sample", "top_n": int(len(top)), "bottom_n": int(len(bottom))}
    rng = np.random.default_rng(SEED)
    diffs = []
    for _ in range(BOOT_REPS):
        top_sample = rng.choice(top.values, size=len(top), replace=True)
        bottom_sample = rng.choice(bottom.values, size=len(bottom), replace=True)
        diffs.append(float(np.mean(top_sample) - np.mean(bottom_sample)))
    t_stat, p_val = stats.ttest_ind(top, bottom, equal_var=False)
    return {
        "status": "ok",
        "top_n": int(len(top)),
        "bottom_n": int(len(bottom)),
        "top_mean": float(top.mean()),
        "bottom_mean": float(bottom.mean()),
        "diff": float(top.mean() - bottom.mean()),
        "welch_t": float(t_stat),
        "welch_p": float(p_val),
        "bootstrap_ci95": [float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))],
        "bootstrap_reps": BOOT_REPS,
    }


def event_diagnostics(panel: pd.DataFrame, targets: list[str]) -> dict:
    sample = panel.dropna(subset=["duration_score_lag1", "reaction_gap_abs_lag1"]).copy()
    if sample.empty:
        return {"status": "no_event_signal_rows"}
    duration_z = (sample["duration_score_lag1"] - sample["duration_score_lag1"].mean()) / sample[
        "duration_score_lag1"
    ].std(ddof=0)
    reaction_z = (sample["reaction_gap_abs_lag1"] - sample["reaction_gap_abs_lag1"].mean()) / sample[
        "reaction_gap_abs_lag1"
    ].std(ddof=0)
    sample["duration_reaction_composite"] = duration_z.fillna(0.0) + reaction_z.fillna(0.0)
    high_cut = sample["duration_reaction_composite"].quantile(2 / 3)
    low_cut = sample["duration_reaction_composite"].quantile(1 / 3)
    high = sample[sample["duration_reaction_composite"] >= high_cut]
    low = sample[sample["duration_reaction_composite"] <= low_cut]
    return {target: bootstrap_diff(high[target], low[target]) for target in targets}


def bonferroni_summary(regressions: dict[str, dict], focal_predictors: list[str]) -> dict:
    rows = []
    total_tests = len(regressions) * len(focal_predictors)
    for target, result in regressions.items():
        if result.get("status") != "ok":
            continue
        for predictor in focal_predictors:
            c = result["coefs"].get(predictor, {})
            p = c.get("p_hac")
            coef = c.get("coef")
            t_val = c.get("t_hac")
            if p is None or coef is None:
                continue
            rows.append(
                {
                    "target": target,
                    "predictor": predictor,
                    "coef": coef,
                    "t_hac": t_val,
                    "p_hac": p,
                    "p_bonferroni": min(float(p) * total_tests, 1.0),
                    "expected_positive": bool(coef > 0),
                    "harvey_t_ge_3": bool(np.isfinite(t_val) and abs(t_val) >= 3.0),
                }
            )
    strong = [
        row
        for row in rows
        if row["expected_positive"] and row["p_bonferroni"] < 0.05 and row["harvey_t_ge_3"]
    ]
    weak = [row for row in rows if row["expected_positive"] and row["harvey_t_ge_3"]]
    if len(strong) >= 2:
        verdict = "CONDITIONAL_PASS"
    elif weak:
        verdict = "WEAK_DIAGNOSTIC"
    else:
        verdict = "NULL_PROXY"
    return {
        "total_main_tests": int(total_tests),
        "rows": rows,
        "strong_positive_bonferroni_tests": strong,
        "weak_positive_harvey_tests": weak,
        "verdict": verdict,
    }


def plot_news_events(gdelt: pd.DataFrame, events: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(11, 4.8))
    plot = gdelt.loc[gdelt.index >= "2020-01-01", "news_z"].dropna()
    ax.plot(plot.index, plot.values, lw=0.8, color="#2f5d62", label="Climate-news z-score")
    ax.axhline(CORE_NEWS_Z, color="#b23a48", lw=1.0, ls="--", label="core event threshold")
    ax.axhline(ACTIVE_NEWS_Z, color="#777777", lw=0.9, ls=":", label="active duration threshold")
    recent_events = events[pd.to_datetime(events["end_date"]) >= pd.Timestamp("2020-01-01")]
    for _, row in recent_events.iterrows():
        ax.axvspan(row["start_date"], row["end_date"], color="#c9d6df", alpha=0.22, lw=0)
    ax.set_title("K1367 climate-news duration events from GDELT TimelineVolRaw")
    ax.set_ylabel("Rolling z-score of log article share")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG_NEWS_PATH, dpi=160)
    plt.close(fig)


def plot_coefficients(regressions: dict[str, dict], targets: list[str], focal_predictors: list[str]) -> None:
    rows = []
    for target in targets:
        result = regressions.get(target, {})
        if result.get("status") != "ok":
            continue
        for predictor in focal_predictors:
            c = result["coefs"].get(predictor, {})
            rows.append(
                {
                    "target": target,
                    "predictor": predictor,
                    "coef": c.get("coef", np.nan),
                    "se": c.get("se_hac", np.nan),
                }
            )
    df = pd.DataFrame(rows)
    if df.empty:
        return
    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    y_positions = np.arange(len(df))
    colors = np.where(df["predictor"].eq("duration_score_lag1"), "#2f5d62", "#b7791f")
    ax.barh(y_positions, df["coef"], color=colors, alpha=0.82)
    ax.errorbar(
        df["coef"],
        y_positions,
        xerr=1.96 * df["se"],
        fmt="none",
        ecolor="#222222",
        elinewidth=0.8,
        capsize=2,
    )
    ax.axvline(0, color="#222222", lw=0.8)
    labels = [f"{r.target}\n{r.predictor.replace('_lag1', '')}" for r in df.itertuples()]
    ax.set_yticks(y_positions, labels, fontsize=8)
    ax.set_title("K1367 HAC coefficients: lagged duration vs reaction-gap signals")
    ax.set_xlabel("Coefficient per 1-sd regressor move")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG_COEF_PATH, dpi=160)
    plt.close(fig)


def plot_diagnostics(diagnostics: dict[str, dict], targets: list[str]) -> None:
    rows = []
    for target in targets:
        result = diagnostics.get(target, {})
        if result.get("status") != "ok":
            continue
        rows.append(
            {
                "target": target,
                "bottom": result["bottom_mean"],
                "top": result["top_mean"],
                "ci_low": result["bootstrap_ci95"][0],
                "ci_high": result["bootstrap_ci95"][1],
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return
    fig, ax = plt.subplots(figsize=(10.5, 5.4))
    x = np.arange(len(df))
    width = 0.36
    ax.bar(x - width / 2, df["bottom"], width, label="bottom tercile", color="#7d8597")
    ax.bar(x + width / 2, df["top"], width, label="top tercile", color="#2f5d62")
    ax.set_xticks(x, df["target"], rotation=35, ha="right", fontsize=8)
    ax.set_title("K1367 event diagnostic: top vs bottom duration-reaction composite")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG_DIAG_PATH, dpi=160)
    plt.close(fig)


def main() -> None:
    gdelt = parse_gdelt_daily(fetch_gdelt_timeline())
    news_events = build_news_events(gdelt)

    yfin = load_yfinance_ohlcv()
    prices = close_prices(yfin)
    returns = np.log(prices / prices.shift(1)).dropna()
    returns["green"] = returns[GREEN_TICKERS].mean(axis=1)
    returns["brown"] = returns[BROWN_TICKERS].mean(axis=1)

    events = add_price_reaction_features(news_events, returns)
    events.to_csv(EVENT_FEATURES_PATH, index=False)

    panel = build_market_panel(events, returns, gdelt)
    targets = [
        "green_rv5",
        "brown_rv5",
        "green_left_tail_loss5",
        "brown_left_tail_loss5",
        "green_var5_breach",
        "brown_var5_breach",
        "green_es_gap5",
        "brown_es_gap5",
        "green_brown_corr_spike21",
    ]
    predictors = [
        "duration_score_lag1",
        "reaction_gap_abs_lag1",
        "peak_news_z_lag1",
        "spy_rv21_lag1",
        "abs_spy_ret_lag1",
    ]
    regressions = {target: run_ols(panel, target, predictors) for target in targets}
    diagnostics = event_diagnostics(panel, targets)
    multiple_test = bonferroni_summary(
        regressions,
        ["duration_score_lag1", "reaction_gap_abs_lag1"],
    )

    plot_news_events(gdelt, events)
    plot_coefficients(regressions, targets, ["duration_score_lag1", "reaction_gap_abs_lag1"])
    plot_diagnostics(diagnostics, targets)

    event_signal_rows = panel.dropna(subset=["duration_score_lag1"]).copy()
    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Climate-news duration and green/brown reaction-time proxy for tail risk",
        "verdict": multiple_test["verdict"],
        "data_sources": {
            "gdelt_doc_api": {
                "url": GDELT_URL,
                "mode": "TimelineVolRaw",
                "query": GDELT_QUERY,
                "start": START,
                "end": END,
                "cache": str(DATA_DIR / "gdelt_climate_timeline_raw.json"),
            },
            "yfinance": {
                "tickers": TICKERS,
                "start": START,
                "end": END,
                "cache": str(DATA_DIR / "yfinance_ohlcv.csv"),
            },
        },
        "methodology": {
            "seed": SEED,
            "lookahead_guard": "raw event features assigned at feature_date; signal_lagged = signal.shift(1) before target construction",
            "event_definition": {
                "core_news_z": CORE_NEWS_Z,
                "active_duration_news_z": ACTIVE_NEWS_Z,
                "duration_proxy": "active news-z cluster length containing at least one core day",
                "price_response_proxy": "first trading day where cumulative green/brown excess return crosses lagged 60d sigma",
            },
            "risk_horizons": {
                "forward_rv_left_tail_var_es_days": FORWARD_RISK_HORIZON,
                "forward_corr_days": FORWARD_CORR_HORIZON,
            },
            "success_criteria": (
                "At least two positive duration/reaction coefficients must pass "
                "Bonferroni p<0.05 and Harvey |t|>=3 across risk targets."
            ),
        },
        "sample": {
            "gdelt_rows": int(len(gdelt)),
            "gdelt_date_start": gdelt.index.min(),
            "gdelt_date_end": gdelt.index.max(),
            "raw_news_events": int(len(news_events)),
            "price_rows": int(len(returns)),
            "price_date_start": returns.index.min(),
            "price_date_end": returns.index.max(),
            "aligned_events": int(len(events)),
            "event_signal_rows_after_shift": int(len(event_signal_rows)),
        },
        "descriptive_statistics": {
            "news_event_duration_days": events["duration_days"].describe().to_dict(),
            "news_event_peak_z": events["peak_news_z"].describe().to_dict(),
            "reaction_gap_abs_days": events["reaction_gap_abs"].describe().to_dict(),
            "green_response_days": events["green_response_days"].describe().to_dict(),
            "brown_response_days": events["brown_response_days"].describe().to_dict(),
        },
        "regressions": regressions,
        "event_diagnostics": diagnostics,
        "multiple_testing": multiple_test,
        "outputs": {
            "event_features_csv": str(EVENT_FEATURES_PATH),
            "model_panel_csv": str(MODEL_PANEL_PATH),
            "news_duration_figure": str(FIG_NEWS_PATH),
            "coefficient_figure": str(FIG_COEF_PATH),
            "event_diagnostic_figure": str(FIG_DIAG_PATH),
        },
        "limitations": [
            "ETF baskets are public daily proxies, not firm-level green/brown portfolios.",
            "GDELT keyword counts measure news attention, not validated climate-event content or sentiment.",
            "Duration/decay is known only after the news cluster ends; the test is a lagged risk-prior diagnostic.",
            "Daily ETF prices cannot test the intraday ACD-GARCH mechanism in Fahmy (2025).",
            "A null proxy result cannot reject company-level or intraday climate-news response-time evidence.",
        ],
    }
    save_json(RESULTS_PATH, results)
    print(json.dumps({"ok": True, "results": str(RESULTS_PATH), "verdict": results["verdict"]}, indent=2))


if __name__ == "__main__":
    main()
