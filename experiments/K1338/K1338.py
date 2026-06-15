"""K1338: Chinese financial-news sentiment vs 0050.TW volatility.

The task asks for a FinBERT-style Chinese-news sentiment increment on top of a
HAR-RV baseline. Public RSS/API history is the binding constraint, so this
script first performs a data-availability gate. It only runs the OOS QLIKE/DM
comparison if the news-history sample is large enough.

Outputs:
    experiments/K1338/K1338_results.json
    experiments/K1338/K1338_daily_sentiment.csv
    experiments/K1338/K1338_article_scores.csv
    experiments/K1338/K1338_sentiment_coverage.png
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise
from volpred.utils import clean_tw50_data


SEED = 42
np.random.seed(SEED)

EXP_ID = "K1338"
EXP_DIR = Path(__file__).resolve().parent
RESULTS_PATH = EXP_DIR / "K1338_results.json"
DAILY_SENTIMENT_PATH = EXP_DIR / "K1338_daily_sentiment.csv"
ARTICLE_SCORES_PATH = EXP_DIR / "K1338_article_scores.csv"
FIG_PATH = EXP_DIR / "K1338_sentiment_coverage.png"

LOCAL_TW50_PATH = Path("storage/macro/yf_0050.TW.csv")
TZ_TAIPEI = ZoneInfo("Asia/Taipei")

CNYES_CATEGORIES = ["tw_stock", "headline"]
CNYES_URL = "https://news.cnyes.com/api/v3/news/category/{category}?limit=30&page={page}"
CTEE_ENDPOINTS = [
    "https://www.ctee.com.tw/livenews/rss",
    "https://www.ctee.com.tw/wp-json/wp/v2/posts?per_page=10",
    "https://www.ctee.com.tw/category/stock/feed",
]

NTUSD_POS_URL = (
    "https://raw.githubusercontent.com/ntunlplab/NTUSD/main/data/"
    "%E6%AD%A3%E9%9D%A2%E8%A9%9E%E7%84%A1%E9%87%8D%E8%A4%87_9365%E8%A9%9E.txt"
)
NTUSD_NEG_URL = (
    "https://raw.githubusercontent.com/ntunlplab/NTUSD/main/data/"
    "%E8%B2%A0%E9%9D%A2%E8%A9%9E%E7%84%A1%E9%87%8D%E8%A4%87_11230%E8%A9%9E.txt"
)

MIN_MODEL_OBS = 252
MIN_TEST_OBS = 60
HAR_WARMUP = 252
VAR_FLOOR = 1e-10
VAR_CEILING = 4.0


FALLBACK_POSITIVE = {
    "上漲",
    "大漲",
    "勁揚",
    "強漲",
    "反彈",
    "回升",
    "創高",
    "新高",
    "利多",
    "看好",
    "成長",
    "增長",
    "獲利",
    "賺錢",
    "買超",
    "旺",
    "熱",
    "強勢",
    "擴產",
    "突破",
    "受惠",
    "復甦",
    "改善",
}

FALLBACK_NEGATIVE = {
    "下跌",
    "大跌",
    "重挫",
    "暴跌",
    "崩跌",
    "回落",
    "創低",
    "新低",
    "利空",
    "看壞",
    "衰退",
    "虧損",
    "賣超",
    "違約",
    "危機",
    "風險",
    "恐慌",
    "壓力",
    "疲弱",
    "下修",
    "裁員",
    "停滯",
    "疑慮",
}


@dataclass
class Lexicon:
    positive: set[str]
    negative: set[str]
    source: str
    pos_count: int
    neg_count: int
    diagnostics: list[dict[str, Any]]


def fetch_bytes(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "VolPredResearch/1.0",
            "Accept": "application/json,text/plain,text/xml,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "big5hkscs", "big5", "cp950"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def load_ntusd_words(url: str, polarity: str) -> tuple[set[str], dict[str, Any]]:
    diag: dict[str, Any] = {"source": url, "polarity": polarity}
    data = fetch_bytes(url)
    text = decode_text(data)
    words = {
        line.strip()
        for line in text.splitlines()
        if len(line.strip()) >= 2 and not line.strip().startswith("#")
    }
    diag.update({"ok": True, "words": len(words), "bytes": len(data)})
    return words, diag


def load_lexicon() -> Lexicon:
    diagnostics: list[dict[str, Any]] = []
    try:
        pos, pos_diag = load_ntusd_words(NTUSD_POS_URL, "positive")
        neg, neg_diag = load_ntusd_words(NTUSD_NEG_URL, "negative")
        diagnostics.extend([pos_diag, neg_diag])
        pos |= FALLBACK_POSITIVE
        neg |= FALLBACK_NEGATIVE
        return Lexicon(
            positive=pos,
            negative=neg,
            source="NTUSD GitHub + small finance-domain augmentation",
            pos_count=len(pos),
            neg_count=len(neg),
            diagnostics=diagnostics,
        )
    except Exception as exc:  # noqa: BLE001
        diagnostics.append({"ok": False, "source": "NTUSD", "error": repr(exc)})
        return Lexicon(
            positive=set(FALLBACK_POSITIVE),
            negative=set(FALLBACK_NEGATIVE),
            source="fallback small finance-domain lexicon",
            pos_count=len(FALLBACK_POSITIVE),
            neg_count=len(FALLBACK_NEGATIVE),
            diagnostics=diagnostics,
        )


def normalize_title(title: str) -> str:
    title = html.unescape(title or "")
    title = re.sub(r"<[^>]+>", "", title)
    title = re.sub(r"\s+", " ", title)
    return title.strip()


def score_title(title: str, lexicon: Lexicon) -> dict[str, Any]:
    text = normalize_title(title)
    pos_hits = sorted({w for w in lexicon.positive if w in text})
    neg_hits = sorted({w for w in lexicon.negative if w in text})
    pos_n = len(pos_hits)
    neg_n = len(neg_hits)
    score = (pos_n - neg_n) / math.sqrt(pos_n + neg_n + 1.0)
    return {
        "title_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        "pos_hits": pos_n,
        "neg_hits": neg_n,
        "score": score,
    }


def fetch_cnyes_category(category: str, sleep_s: float = 0.10) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    items: list[dict[str, Any]] = []
    diag: dict[str, Any] = {"source": "cnyes", "category": category, "ok": False}
    page = 1
    last_page = 1
    while page <= last_page:
        url = CNYES_URL.format(category=urllib.parse.quote(category), page=page)
        try:
            payload = json.loads(fetch_bytes(url).decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            diag.update({"error": repr(exc), "failed_page": page})
            break
        meta = payload.get("items") or {}
        data = meta.get("data") or []
        if not isinstance(data, list) or not data:
            break
        for row in data:
            if isinstance(row, dict):
                row = dict(row)
                row["_category_query"] = category
                items.append(row)
        last_page = int(meta.get("last_page") or page)
        page += 1
        time.sleep(sleep_s)
    if items:
        publish_dates = [
            datetime.fromtimestamp(int(x["publishAt"]), tz=TZ_TAIPEI).date().isoformat()
            for x in items
            if x.get("publishAt")
        ]
        diag.update(
            {
                "ok": True,
                "items": len(items),
                "pages": last_page,
                "min_date": min(publish_dates) if publish_dates else None,
                "max_date": max(publish_dates) if publish_dates else None,
                "unique_days": len(set(publish_dates)),
            }
        )
    return items, diag


def diagnose_ctee() -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for url in CTEE_ENDPOINTS:
        row: dict[str, Any] = {"source": "ctee", "url": url}
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "VolPredResearch/1.0",
                    "Accept": "application/rss+xml,application/json,text/html,*/*",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read(500)
                text = decode_text(data)
                row.update(
                    {
                        "ok": True,
                        "status": getattr(resp, "status", None),
                        "content_type": resp.headers.get("content-type"),
                        "looks_like_xml": text.lstrip().startswith("<?xml") or "<rss" in text[:200].lower(),
                    }
                )
        except urllib.error.HTTPError as exc:
            row.update({"ok": False, "status": exc.code, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            row.update({"ok": False, "error": repr(exc)})
        diagnostics.append(row)
    return diagnostics


def fetch_news_scores(lexicon: Lexicon) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    all_items: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for category in CNYES_CATEGORIES:
        items, diag = fetch_cnyes_category(category)
        all_items.extend(items)
        diagnostics.append(diag)
    diagnostics.extend(diagnose_ctee())

    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in all_items:
        news_id = str(item.get("newsId") or "")
        if not news_id or news_id in seen_ids:
            continue
        seen_ids.add(news_id)
        ts = item.get("publishAt")
        if not ts:
            continue
        published = datetime.fromtimestamp(int(ts), tz=TZ_TAIPEI)
        title = normalize_title(str(item.get("title") or ""))
        if not title:
            continue
        score = score_title(title, lexicon)
        rows.append(
            {
                "news_id": news_id,
                "source": str(item.get("source") or "cnyes"),
                "category_query": item.get("_category_query"),
                "category_name": item.get("categoryName"),
                "publish_at_utc": published.astimezone(UTC).isoformat(),
                "publish_date_taipei": published.date().isoformat(),
                **score,
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["publish_at_utc", "news_id"]).reset_index(drop=True)
    return df, diagnostics


def build_daily_sentiment(article_scores: pd.DataFrame) -> pd.DataFrame:
    if article_scores.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "article_count",
                "pos_hits",
                "neg_hits",
                "sentiment_mean",
                "sentiment_sum_scaled",
                "sentiment_z",
            ]
        )
    grouped = article_scores.groupby("publish_date_taipei")
    daily = grouped.agg(
        article_count=("news_id", "count"),
        pos_hits=("pos_hits", "sum"),
        neg_hits=("neg_hits", "sum"),
        sentiment_mean=("score", "mean"),
        sentiment_sum=("score", "sum"),
    )
    daily["sentiment_sum_scaled"] = daily["sentiment_sum"] / np.sqrt(daily["article_count"].clip(lower=1))
    # Prior-only expanding standardization. Full-sample z-scores would leak
    # future headline distribution into earlier forecasts once a long collector
    # history exists.
    prior_mean = daily["sentiment_sum_scaled"].expanding(min_periods=5).mean().shift(1)
    prior_std = daily["sentiment_sum_scaled"].expanding(min_periods=5).std(ddof=0).shift(1)
    daily["sentiment_z"] = (daily["sentiment_sum_scaled"] - prior_mean) / prior_std.replace(0.0, np.nan)
    daily = daily.drop(columns=["sentiment_sum"])
    daily.index.name = "date"
    return daily.reset_index()


def flatten_yfinance_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(col[0]) for col in df.columns]
    return df


def load_tw50_prices(news_min_date: str | None, news_max_date: str | None) -> tuple[pd.DataFrame, dict[str, Any]]:
    start = "2009-01-01"
    end = None
    if news_max_date:
        end_dt = pd.Timestamp(news_max_date) + pd.Timedelta(days=2)
        end = end_dt.strftime("%Y-%m-%d")
    diag: dict[str, Any] = {
        "ticker": "0050.TW",
        "primary_source": "yfinance",
        "fallback_source": str(LOCAL_TW50_PATH),
    }
    try:
        raw = yf.download(
            "0050.TW",
            start=start,
            end=end,
            progress=False,
            auto_adjust=False,
            threads=False,
            timeout=30,
        )
        raw = flatten_yfinance_columns(raw)
        if raw.empty or "Close" not in raw:
            raise RuntimeError("empty yfinance close")
        source = "yfinance_live"
    except Exception as exc:  # noqa: BLE001
        diag["yfinance_error"] = repr(exc)
        raw = pd.read_csv(LOCAL_TW50_PATH, header=[0, 1, 2], index_col=0, parse_dates=True)
        raw.columns = [col[0] for col in raw.columns]
        source = "local_storage_macro_yf_0050"

    close = pd.to_numeric(raw["Close"], errors="coerce").dropna()
    clean_close, clean_ret = clean_tw50_data(close)
    out = pd.DataFrame({"close": clean_close, "ret": clean_ret}).dropna()
    out["rv_daily"] = out["ret"].pow(2) * 252.0
    diag.update(
        {
            "used_source": source,
            "rows": int(len(out)),
            "first_date": out.index.min().date().isoformat() if len(out) else None,
            "last_date": out.index.max().date().isoformat() if len(out) else None,
            "news_price_overlap_possible": bool(
                news_min_date
                and news_max_date
                and len(out)
                and pd.Timestamp(news_min_date) <= out.index.max()
                and pd.Timestamp(news_max_date) >= out.index.min()
            ),
        }
    )
    return out, diag


def prepare_model_frame(prices: pd.DataFrame, daily_sentiment: pd.DataFrame) -> pd.DataFrame:
    px = prices.copy()
    px.index = pd.to_datetime(px.index).normalize()
    daily = daily_sentiment.copy()
    if daily.empty:
        daily = pd.DataFrame(columns=["date", "sentiment_z", "article_count"])
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.set_index("date").sort_index()

    model = px[["rv_daily"]].copy()
    model["log_rv_d_lag1"] = np.log(np.clip(model["rv_daily"].shift(1), VAR_FLOOR, VAR_CEILING))
    model["log_rv_w_lag1"] = np.log(np.clip(model["rv_daily"].rolling(5).mean().shift(1), VAR_FLOOR, VAR_CEILING))
    model["log_rv_m_lag1"] = np.log(np.clip(model["rv_daily"].rolling(22).mean().shift(1), VAR_FLOOR, VAR_CEILING))

    # Missing dates are missing news observations, not neutral sentiment. Keep
    # them as NaN so the OOS gate cannot silently inflate sample size with
    # years of price-only history.
    model["sentiment_z_raw"] = daily["sentiment_z"].reindex(model.index)
    model["article_count_raw"] = daily["article_count"].reindex(model.index)
    # Conservative timing: date-t return is predicted with date-(t-1) headlines.
    signal = model["sentiment_z_raw"].shift(1)
    model["sentiment_z_lag1"] = signal
    model["article_count_lag1"] = model["article_count_raw"].shift(1)
    model["target_var"] = model["rv_daily"]
    model["forecast_pos"] = np.arange(len(model), dtype=int)
    return model.dropna(subset=["target_var", "log_rv_d_lag1", "log_rv_w_lag1", "log_rv_m_lag1", "sentiment_z_lag1"])


def expanding_forecast(model_df: pd.DataFrame, feature_cols: list[str]) -> pd.Series:
    df = model_df.dropna(subset=["target_var", *feature_cols]).copy()
    yhat = pd.Series(np.nan, index=df.index, name="forecast")
    for i in range(len(df)):
        if i < HAR_WARMUP:
            continue
        train = df.iloc[:i]
        if len(train) < HAR_WARMUP:
            continue
        x_train = np.column_stack([np.ones(len(train)), train[feature_cols].to_numpy(dtype=float)])
        y_train = np.log(np.clip(train["target_var"].to_numpy(dtype=float), VAR_FLOOR, VAR_CEILING))
        coef = np.linalg.lstsq(x_train, y_train, rcond=None)[0]
        x_now = np.r_[1.0, df.iloc[i][feature_cols].to_numpy(dtype=float)]
        pred = float(np.exp(x_now @ coef))
        yhat.iloc[i] = float(np.clip(pred, VAR_FLOOR, VAR_CEILING))
    return yhat


def run_model_if_possible(model_df: pd.DataFrame) -> dict[str, Any]:
    baseline_cols = ["log_rv_d_lag1", "log_rv_w_lag1", "log_rv_m_lag1"]
    augmented_cols = [*baseline_cols, "sentiment_z_lag1"]
    usable = model_df.dropna(subset=["target_var", *augmented_cols]).copy()
    out: dict[str, Any] = {
        "status": "skipped",
        "reason": None,
        "min_model_obs": MIN_MODEL_OBS,
        "min_test_obs": MIN_TEST_OBS,
        "har_warmup": HAR_WARMUP,
        "usable_rows": int(len(usable)),
        "first_usable_date": usable.index.min().date().isoformat() if len(usable) else None,
        "last_usable_date": usable.index.max().date().isoformat() if len(usable) else None,
    }
    if len(usable) < MIN_MODEL_OBS + MIN_TEST_OBS:
        out["reason"] = "insufficient_news_price_overlap_for_oos_qlike_dm"
        return out

    base = expanding_forecast(usable, baseline_cols)
    aug = expanding_forecast(usable, augmented_cols)
    aligned = pd.DataFrame({"actual": usable["target_var"], "baseline": base, "augmented": aug}).dropna()
    if len(aligned) < MIN_TEST_OBS:
        out["reason"] = "insufficient_forecast_rows_after_warmup"
        out["forecast_rows"] = int(len(aligned))
        return out

    loss_base = qlike_pointwise(aligned["actual"].to_numpy(), aligned["baseline"].to_numpy())
    loss_aug = qlike_pointwise(aligned["actual"].to_numpy(), aligned["augmented"].to_numpy())
    dm_t, dm_p = dm_test(loss_aug, loss_base, h=1)
    base_qlike = qlike(aligned["actual"].to_numpy(), aligned["baseline"].to_numpy())
    aug_qlike = qlike(aligned["actual"].to_numpy(), aligned["augmented"].to_numpy())
    out.update(
        {
            "status": "ran",
            "reason": None,
            "forecast_rows": int(len(aligned)),
            "first_forecast_date": aligned.index.min().date().isoformat(),
            "last_forecast_date": aligned.index.max().date().isoformat(),
            "baseline_qlike": base_qlike,
            "augmented_qlike": aug_qlike,
            "improvement_pct": float(100.0 * (base_qlike - aug_qlike) / abs(base_qlike)),
            "dm_t_augmented_minus_baseline": dm_t,
            "dm_p": dm_p,
            "harvey_abs_t_gt_3": bool(abs(dm_t) > 3.0),
        }
    )
    return out


def make_figure(daily: pd.DataFrame, prices: pd.DataFrame) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=False)
    if daily.empty:
        axes[0].text(0.5, 0.5, "No machine-readable news items", ha="center", va="center")
        axes[0].set_axis_off()
    else:
        d = daily.copy()
        d["date"] = pd.to_datetime(d["date"])
        axes[0].bar(d["date"], d["article_count"], color="#6b7280", alpha=0.45, label="Article count")
        ax2 = axes[0].twinx()
        ax2.plot(d["date"], d["sentiment_z"], color="#0f766e", marker="o", label="Sentiment z")
        axes[0].set_title("K1338 public news coverage: CNYES API sample")
        axes[0].set_ylabel("articles")
        ax2.set_ylabel("sentiment z")
        axes[0].grid(True, alpha=0.25)

    if not prices.empty:
        recent = prices.tail(40).copy()
        axes[1].plot(recent.index, np.sqrt(recent["rv_daily"]) * 100.0, color="#1d4ed8", label="0050 daily abs vol proxy")
        axes[1].set_title("0050.TW daily volatility proxy around news sample")
        axes[1].set_ylabel("annualized daily vol (%)")
        axes[1].grid(True, alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=160)
    plt.close(fig)


def main() -> None:
    lexicon = load_lexicon()
    article_scores, source_diagnostics = fetch_news_scores(lexicon)
    daily = build_daily_sentiment(article_scores)

    news_min_date = daily["date"].min() if not daily.empty else None
    news_max_date = daily["date"].max() if not daily.empty else None
    prices, price_diag = load_tw50_prices(news_min_date, news_max_date)
    model_df = prepare_model_frame(prices, daily)
    model_result = run_model_if_possible(model_df)

    article_scores.to_csv(ARTICLE_SCORES_PATH, index=False)
    daily.to_csv(DAILY_SENTIMENT_PATH, index=False)
    make_figure(daily, prices)

    unique_days = int(daily["date"].nunique()) if not daily.empty else 0
    article_count = int(article_scores["news_id"].nunique()) if not article_scores.empty else 0
    if model_result["status"] == "ran":
        verdict = "CONDITIONAL_RESULT"
        conclusion = "OOS model ran; inspect QLIKE/DM statistics before using."
    else:
        verdict = "NULL_DATA_LIMITATION"
        conclusion = (
            "Public machine-readable CNYES/CTEE history available at run time is too short "
            "for an honest HAR+sentiment OOS QLIKE/DM test."
        )

    results = {
        "experiment_id": EXP_ID,
        "title": "Chinese financial-news sentiment vs 0050.TW volatility",
        "date_run_utc": datetime.now(UTC).isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "conclusion": conclusion,
        "data": {
            "news_sources_attempted": {
                "cnyes_api_categories": CNYES_CATEGORIES,
                "ctee_endpoints": CTEE_ENDPOINTS,
            },
            "news_article_rows": article_count,
            "news_unique_days_taipei": unique_days,
            "news_first_date_taipei": news_min_date,
            "news_last_date_taipei": news_max_date,
            "article_scores_csv": str(ARTICLE_SCORES_PATH.relative_to(EXP_DIR)),
            "daily_sentiment_csv": str(DAILY_SENTIMENT_PATH.relative_to(EXP_DIR)),
            "price_diagnostics": price_diag,
            "source_diagnostics": source_diagnostics,
        },
        "lexicon": {
            "source": lexicon.source,
            "positive_terms": lexicon.pos_count,
            "negative_terms": lexicon.neg_count,
            "diagnostics": lexicon.diagnostics,
            "scoring": "(positive_title_hits - negative_title_hits) / sqrt(total_hits + 1)",
        },
        "design": {
            "baseline_if_enough_data": "log-HAR daily variance: log(rv_t) ~ log_rv_d_lag1 + log_rv_w_lag1 + log_rv_m_lag1",
            "augmented_if_enough_data": "same baseline plus sentiment_z_lag1",
            "lookahead_policy": "model_df['sentiment_z_lag1'] = model_df['sentiment_z_raw'].shift(1); date-t target uses only prior-date news and prior realized variance.",
            "oos_gate": f"requires at least {MIN_MODEL_OBS}+{MIN_TEST_OBS} usable rows before DM/QLIKE is reported",
            "qlike_dm": "Patton QLIKE and Newey-West DM via volpred.stats.model_evaluation if gate passes",
        },
        "model_result": model_result,
        "artifacts": {
            "figure": str(FIG_PATH.relative_to(EXP_DIR)),
            "results_json": str(RESULTS_PATH.relative_to(EXP_DIR)),
        },
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "verdict": verdict, "results": str(RESULTS_PATH)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
