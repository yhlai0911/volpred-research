"""research_1_1_realized_vol_har: Yahoo Finance RSS text vs HAR-RV feasibility.

This experiment is intentionally conservative. The task asks whether free
financial-news text can beat a HAR realized-volatility baseline at 1/5/22-day
horizons. A valid answer requires historical daily headline coverage and a
lookahead-safe forward-label training cutoff. Yahoo's public RSS endpoint only
exposes a short current snapshot at run time, so the script records the data
availability boundary and runs a HAR baseline sanity check on SPY daily data.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import ssl
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.request import Request, urlopen

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.linear_model import LinearRegression


EXPERIMENT_ID = "research_1_1_realized_vol_har"
ROOT = Path(__file__).resolve().parent
RESULTS_FILE = ROOT / f"{EXPERIMENT_ID}_results.json"
FIGURE_FILE = ROOT / "figures" / "news_coverage_and_har_baseline.png"
NEWS_FILE = ROOT / "data" / "yahoo_rss_headlines.csv"

START = "2006-01-01"
END = "2026-06-16"
OOS_START = "2015-01-02"
HORIZONS = [1, 5, 22]
MIN_TRAIN_ROWS = 252
MIN_OOS_ROWS = 60
RANDOM_SEED = 20260616

RSS_FEEDS = {
    "spy": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=SPY&region=US&lang=en-US",
    "sp500": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC&region=US&lang=en-US",
    "market_index": "https://finance.yahoo.com/news/rssindex",
}

STRESS_WORDS = {
    "crash", "fall", "falls", "fell", "drop", "drops", "slump", "selloff",
    "risk", "risks", "warning", "warns", "fear", "fears", "tariff", "war",
    "recession", "inflation", "fed", "rates", "oil", "volatility",
}


@dataclass
class ForecastResult:
    horizon: int
    n_forecasts: int
    qlike: float
    mse: float
    mean_actual_var: float
    mean_pred_var: float
    oos_start: str
    oos_end: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dependency_status() -> dict[str, bool]:
    modules = [
        "transformers",
        "torch",
        "feedparser",
        "bs4",
        "sklearn",
        "statsmodels",
        "yfinance",
    ]
    return {name: importlib.util.find_spec(name) is not None for name in modules}


def fetch_url(url: str, timeout: int = 30) -> bytes:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) VolPred/1.0",
            "Accept": "application/rss+xml,application/xml,text/xml,*/*",
        },
    )
    ctx = ssl.create_default_context()
    with urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read()


def parse_pubdate(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except Exception:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def score_title(title: str) -> dict[str, float]:
    words = re.findall(r"[A-Za-z]+", title.lower())
    if not words:
        return {"word_count": 0, "stress_hits": 0, "stress_share": 0.0}
    hits = sum(1 for word in words if word in STRESS_WORDS)
    return {
        "word_count": len(words),
        "stress_hits": hits,
        "stress_share": hits / math.sqrt(len(words)),
    }


def fetch_yahoo_rss() -> tuple[pd.DataFrame, dict[str, dict[str, object]]]:
    rows: list[dict[str, object]] = []
    feed_status: dict[str, dict[str, object]] = {}

    for feed_name, url in RSS_FEEDS.items():
        try:
            raw = fetch_url(url)
            root = ET.fromstring(raw)
            items = root.findall(".//item")
            feed_status[feed_name] = {
                "url": url,
                "ok": True,
                "items": len(items),
                "bytes": len(raw),
            }
            for item in items:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub_dt = parse_pubdate(item.findtext("pubDate"))
                if not title or pub_dt is None:
                    continue
                score = score_title(title)
                rows.append(
                    {
                        "feed": feed_name,
                        "published_at_utc": pub_dt.isoformat(),
                        "date_utc": pub_dt.date().isoformat(),
                        "title": title,
                        "link": link,
                        **score,
                    }
                )
        except Exception as exc:
            feed_status[feed_name] = {
                "url": url,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }

    if not rows:
        return pd.DataFrame(), feed_status

    news = pd.DataFrame(rows)
    news = news.drop_duplicates(subset=["title", "link"]).sort_values("published_at_utc")
    NEWS_FILE.parent.mkdir(parents=True, exist_ok=True)
    news.to_csv(NEWS_FILE, index=False)
    return news, feed_status


def aggregate_news(news: pd.DataFrame) -> pd.DataFrame:
    if news.empty:
        return pd.DataFrame()
    daily = (
        news.groupby("date_utc")
        .agg(
            headline_count=("title", "size"),
            feed_count=("feed", "nunique"),
            avg_word_count=("word_count", "mean"),
            stress_hits=("stress_hits", "sum"),
            stress_share=("stress_share", "mean"),
        )
        .reset_index()
    )
    daily["date_utc"] = pd.to_datetime(daily["date_utc"])
    return daily.set_index("date_utc").sort_index()


def download_spy() -> pd.DataFrame:
    raw = yf.download("SPY", start=START, end=END, progress=False, auto_adjust=True)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    if raw.empty:
        raise RuntimeError("SPY download returned no rows")
    px = raw[["Close"]].rename(columns={"Close": "close"}).copy()
    px.index = pd.to_datetime(px.index).tz_localize(None)
    px["log_ret"] = np.log(px["close"] / px["close"].shift(1))
    px["rv"] = px["log_ret"].pow(2)
    return px.dropna()


def build_har_panel(market: pd.DataFrame, horizon: int) -> pd.DataFrame:
    panel = market[["rv"]].copy()
    eps = 1e-10
    panel["rv_d_lag1"] = panel["rv"].shift(1)
    panel["rv_w_lag1"] = panel["rv"].rolling(5).mean().shift(1)
    panel["rv_m_lag1"] = panel["rv"].rolling(22).mean().shift(1)
    # Target at forecast origin t is average realized variance over t..t+h-1.
    panel["target"] = panel["rv"].rolling(horizon).mean().shift(-(horizon - 1))
    panel["target_end_pos"] = np.arange(len(panel)) + horizon - 1
    for col in ["rv_d_lag1", "rv_w_lag1", "rv_m_lag1", "target"]:
        panel[f"log_{col}"] = np.log(panel[col].clip(lower=eps))
    return panel.dropna()


def qlike(actual: np.ndarray, pred: np.ndarray) -> np.ndarray:
    pred = np.clip(pred, 1e-10, None)
    actual = np.clip(actual, 1e-10, None)
    return np.log(pred) + actual / pred


def expanding_har_forecast(market: pd.DataFrame, horizon: int) -> ForecastResult | None:
    panel = build_har_panel(market, horizon)
    if panel.empty:
        return None

    feature_cols = ["log_rv_d_lag1", "log_rv_w_lag1", "log_rv_m_lag1"]
    oos_positions = np.flatnonzero(panel.index >= pd.Timestamp(OOS_START))
    preds: list[float] = []
    actuals: list[float] = []
    dates: list[pd.Timestamp] = []

    for pos in oos_positions:
        forecast_date = panel.index[pos]
        train = panel.iloc[:pos]
        # K1337 guard: training forward labels must end before forecast origin.
        train = train[train["target_end_pos"] < pos]
        train = train.dropna(subset=feature_cols + ["log_target"])
        if len(train) < MIN_TRAIN_ROWS:
            continue

        row = panel.iloc[[pos]]
        if row[feature_cols + ["target"]].isna().any(axis=None):
            continue

        model = LinearRegression()
        model.fit(train[feature_cols].values, train["log_target"].values)
        pred_log = float(model.predict(row[feature_cols].values)[0])
        preds.append(float(np.exp(pred_log)))
        actuals.append(float(row["target"].iloc[0]))
        dates.append(forecast_date)

    if len(preds) < MIN_OOS_ROWS:
        return None

    pred_arr = np.asarray(preds)
    actual_arr = np.asarray(actuals)
    loss = qlike(actual_arr, pred_arr)
    return ForecastResult(
        horizon=horizon,
        n_forecasts=len(preds),
        qlike=float(np.mean(loss)),
        mse=float(np.mean((actual_arr - pred_arr) ** 2)),
        mean_actual_var=float(np.mean(actual_arr)),
        mean_pred_var=float(np.mean(pred_arr)),
        oos_start=dates[0].date().isoformat(),
        oos_end=dates[-1].date().isoformat(),
    )


def make_figure(news_daily: pd.DataFrame, har_results: list[ForecastResult]) -> None:
    FIGURE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))

    if news_daily.empty:
        axes[0].text(0.5, 0.5, "No RSS headlines fetched", ha="center", va="center")
        axes[0].set_axis_off()
    else:
        date_labels = [idx.date().isoformat() for idx in news_daily.index]
        axes[0].bar(date_labels, news_daily["headline_count"].values, color="#2f6f73")
        axes[0].set_title("Yahoo RSS coverage by UTC date")
        axes[0].set_xlabel("date")
        axes[0].set_ylabel("headlines")
        axes[0].tick_params(axis="x", labelrotation=30)

    if har_results:
        horizons = [str(r.horizon) for r in har_results]
        losses = [r.qlike for r in har_results]
        axes[1].bar(horizons, losses, color="#9b5f2a")
        axes[1].set_title("SPY HAR baseline QLIKE sanity check")
        axes[1].set_xlabel("horizon (trading days)")
        axes[1].set_ylabel("mean QLIKE loss")
    else:
        axes[1].text(0.5, 0.5, "HAR baseline unavailable", ha="center", va="center")
        axes[1].set_axis_off()

    fig.tight_layout()
    fig.savefig(FIGURE_FILE, dpi=150)
    plt.close(fig)


def main() -> dict[str, object]:
    np.random.seed(RANDOM_SEED)
    deps = dependency_status()
    news, feed_status = fetch_yahoo_rss()
    news_daily = aggregate_news(news)
    market = download_spy()
    har_results = [
        result for h in HORIZONS if (result := expanding_har_forecast(market, h)) is not None
    ]
    make_figure(news_daily, har_results)

    unique_news_days = int(news_daily.shape[0]) if not news_daily.empty else 0
    news_span_days = 0
    if unique_news_days:
        news_span_days = int((news_daily.index.max() - news_daily.index.min()).days) + 1

    can_fit_text_model = (
        unique_news_days >= (MIN_TRAIN_ROWS + MIN_OOS_ROWS + max(HORIZONS))
        and deps.get("transformers", False)
    )

    skipped_reason = []
    if unique_news_days < (MIN_TRAIN_ROWS + MIN_OOS_ROWS + max(HORIZONS)):
        skipped_reason.append(
            "Yahoo public RSS snapshot has too few historical headline days for a "
            "252-row train + 60-row OOS text regression gate."
        )
    if not deps.get("transformers", False):
        skipped_reason.append(
            "transformers/FinBERT is not installed in the current runtime; no "
            "pretrained embedding result is claimed."
        )

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Free financial-news text vs HAR realized-volatility baseline",
        "run_at_utc": utc_now(),
        "verdict": "NULL_DATA_LIMITATION",
        "random_seed": RANDOM_SEED,
        "data_sources": {
            "market": "yfinance SPY adjusted close",
            "news": RSS_FEEDS,
            "news_snapshot_file": str(NEWS_FILE.relative_to(ROOT)),
        },
        "sample": {
            "market_start": market.index.min().date().isoformat(),
            "market_end": market.index.max().date().isoformat(),
            "market_rows": int(len(market)),
            "oos_start": OOS_START,
            "news_items": int(len(news)),
            "unique_news_days": unique_news_days,
            "news_span_days": news_span_days,
            "news_start": news_daily.index.min().date().isoformat() if unique_news_days else None,
            "news_end": news_daily.index.max().date().isoformat() if unique_news_days else None,
        },
        "dependency_status": deps,
        "feed_status": feed_status,
        "news_daily_summary": (
            news_daily.reset_index()
            .assign(date_utc=lambda df: df["date_utc"].dt.date.astype(str))
            .to_dict(orient="records")
            if not news_daily.empty
            else []
        ),
        "lookahead_controls": {
            "market_features": "rv_d/rv_w/rv_m are shifted by one trading day.",
            "forward_label_guard": "For horizon h, expanding training keeps only rows with target_end_pos < forecast_pos.",
            "news_features": "No predictive news model was fit; a future run must use publication timestamp <= t-1 close for date-t forecasts.",
        },
        "har_baseline_sanity": [
            {
                "horizon": r.horizon,
                "n_forecasts": r.n_forecasts,
                "qlike": round(r.qlike, 6),
                "mse": r.mse,
                "mean_actual_var": r.mean_actual_var,
                "mean_pred_var": r.mean_pred_var,
                "oos_start": r.oos_start,
                "oos_end": r.oos_end,
            }
            for r in har_results
        ],
        "text_model_attempted": False,
        "can_fit_text_model": can_fit_text_model,
        "skipped_reason": skipped_reason,
        "success_criteria": {
            "minimum_news_days": MIN_TRAIN_ROWS + MIN_OOS_ROWS + max(HORIZONS),
            "minimum_train_rows": MIN_TRAIN_ROWS,
            "minimum_oos_rows": MIN_OOS_ROWS,
            "dm_harvey_gate": "|DM t| > 3.0 if a challenger is evaluated",
        },
        "related_project_findings": [
            "K1487: GDELT daily novel-risk intensity did not improve RV forecasts beyond HAR/VIX.",
            "K1338: Chinese financial-news sentiment pipeline was blocked by only 11 public API days.",
            "K531: FRED sentiment/uncertainty proxies did not improve volatility prediction beyond VIX.",
        ],
        "external_literature": [
            "Corsi (2009), A Simple Approximate Long-Memory Model of Realized Volatility.",
            "Tetlock (2007), Giving Content to Investor Sentiment.",
            "Manela and Moreira (2017), News Implied Volatility and Disaster Concerns.",
            "Parvini and Assa (2025), Textual Regression for Realized Volatility.",
        ],
        "figure": str(FIGURE_FILE.relative_to(ROOT)),
        "conclusion": (
            "The requested Yahoo-RSS plus FinBERT/BERT horserace cannot be made "
            "honestly from the current public RSS snapshot. The HAR baseline is "
            "reproducible and lookahead-safe, but the text leg needs either a "
            "persistent daily collector or a historical/licensed headline archive "
            "before any claim that text beats HAR can be tested."
        ),
    }

    RESULTS_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return results


if __name__ == "__main__":
    out = main()
    print(json.dumps({
        "experiment_id": out["experiment_id"],
        "verdict": out["verdict"],
        "news_items": out["sample"]["news_items"],
        "unique_news_days": out["sample"]["unique_news_days"],
        "har_horizons": [r["horizon"] for r in out["har_baseline_sanity"]],
        "text_model_attempted": out["text_model_attempted"],
    }, indent=2))
