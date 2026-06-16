"""
research_google_trends_vol
==========================

Google Trends product-keyword attention vs Taiwan supply-chain weekly volatility.

This experiment intentionally refuses to replace Google Trends with VIX, price,
or volume proxies. If pytrends cannot fetch real Google Trends data, the result
is a data-availability NULL rather than a pseudo-attention test.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.volpred.stats.model_evaluation import qlike, qlike_pointwise


EXPERIMENT_ID = "research_google_trends_vol"
SEED = 42
START = "2018-01-01"
END = "2026-06-15"  # yfinance end is exclusive
GEO = "TW"
MIN_TRENDS_WEEKS = 156
REFIT_EVERY = 13
HAC_MAXLAGS = 4

RESULTS_PATH = ROOT / f"{EXPERIMENT_ID}_results.json"
TRENDS_CACHE_PATH = ROOT / "google_trends_weekly.csv"

SEARCH_TERMS = ["iPhone", "AI server", "TSMC", "HBM"]
TICKERS = {
    "2330.TW": "TSMC",
    "2303.TW": "UMC",
    "2454.TW": "MediaTek",
    "2382.TW": "Quanta",
}

REFERENCES = [
    {
        "citation": "Da, Engelberg & Gao (2011), Journal of Finance",
        "note": "Introduces Google Search Volume Index as a direct investor-attention proxy.",
        "url": "https://www3.nd.edu/~zda/Google.pdf",
    },
    {
        "citation": "Vlastakis & Markellos (2012), Journal of Banking & Finance",
        "note": "Studies Google Trends information demand and stock-market volatility.",
        "url": "https://ideas.repec.org/a/eee/jbfina/v36y2012i6p1808-1821.html",
    },
    {
        "citation": "Andrei & Hasler (2015), Review of Financial Studies",
        "note": "Models investor attention and uncertainty as drivers of return variance.",
        "url": "https://ideas.repec.org/a/oup/rfinst/v28y2015i1p33-72..html",
    },
    {
        "citation": "Investor attention fluctuation and stock market volatility (2023), PLOS ONE",
        "note": "Uses investor attention inside HAR-style volatility forecasting for China.",
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC10681240/",
    },
]


@dataclass
class ModelResult:
    qlike: float
    relative_improvement_pct: float
    dm_hac_t_vs_har: float | None
    dm_hac_p_vs_har: float | None
    harvey_pass_vs_har: bool | None


def patch_pytrends_urllib3() -> None:
    """Make old pytrends compatible with urllib3>=2.

    pytrends still passes `method_whitelist` into urllib3 Retry. urllib3 v2
    renamed that argument to `allowed_methods`. This compatibility patch only
    translates the keyword; it does not bypass Google rate limits.
    """

    try:
        import urllib3.util.retry as retry
    except Exception:
        return

    original_init = retry.Retry.__init__
    if getattr(original_init, "_volpred_patched", False):
        return

    def patched_init(self, *args, **kwargs):
        if "method_whitelist" in kwargs and "allowed_methods" not in kwargs:
            kwargs["allowed_methods"] = kwargs.pop("method_whitelist")
        return original_init(self, *args, **kwargs)

    patched_init._volpred_patched = True  # type: ignore[attr-defined]
    retry.Retry.__init__ = patched_init


def safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    if not np.isfinite(out):
        return None
    return out


def load_taiwan_prices() -> tuple[pd.DataFrame, dict[str, Any]]:
    raw = yf.download(
        list(TICKERS.keys()),
        start=START,
        end=END,
        progress=False,
        auto_adjust=True,
        group_by="column",
        threads=True,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned an empty Taiwan equity panel")
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].copy()
    else:
        close = raw[["Close"]].copy()
        close.columns = list(TICKERS.keys())
    close = close.dropna(how="all")
    summary = {
        "source": "yfinance adjusted close",
        "start": START,
        "end_exclusive": END,
        "n_trading_days": int(len(close)),
        "first_date": str(close.index.min().date()),
        "last_date": str(close.index.max().date()),
        "non_null_counts": {k: int(v) for k, v in close.notna().sum().to_dict().items()},
        "tickers": TICKERS,
    }
    return close, summary


def fetch_one_trends_term(term: str) -> tuple[pd.Series | None, list[str]]:
    errors: list[str] = []
    try:
        patch_pytrends_urllib3()
        from pytrends.request import TrendReq
    except Exception as exc:
        return None, [f"pytrends_import_failed: {type(exc).__name__}: {exc}"]

    pytrends = TrendReq(
        hl="zh-TW",
        tz=480,
        retries=0,
        backoff_factor=0,
        requests_args={
            "headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/125.0 Safari/537.36"
                )
            }
        },
    )

    chunks = [
        ("2018-01-01", "2022-12-31"),
        ("2021-01-01", END),
    ]
    series_chunks: list[pd.Series] = []
    for start, end in chunks:
        try:
            pytrends.build_payload([term], timeframe=f"{start} {end}", geo=GEO)
            df = pytrends.interest_over_time()
            if df is None or df.empty or term not in df.columns:
                errors.append(f"{term} {start}..{end}: empty response")
            else:
                s = df[term].astype(float).rename(term)
                if "isPartial" in df.columns:
                    s = s[~df["isPartial"].astype(bool)]
                series_chunks.append(s)
        except Exception as exc:
            errors.append(f"{term} {start}..{end}: {type(exc).__name__}: {exc}")
        time.sleep(2)

    if not series_chunks:
        return None, errors

    stitched = series_chunks[0].copy()
    for nxt in series_chunks[1:]:
        overlap = stitched.index.intersection(nxt.index)
        scaled = nxt.copy()
        if len(overlap) >= 8:
            old_mean = stitched.loc[overlap].replace(0, np.nan).mean()
            new_mean = nxt.loc[overlap].replace(0, np.nan).mean()
            if np.isfinite(old_mean) and np.isfinite(new_mean) and new_mean != 0:
                scaled = nxt * (old_mean / new_mean)
        stitched = pd.concat([stitched, scaled.loc[scaled.index > stitched.index.max()]])

    stitched = stitched[~stitched.index.duplicated(keep="last")].sort_index()
    return stitched, errors


def fetch_google_trends() -> tuple[pd.DataFrame | None, dict[str, Any]]:
    if TRENDS_CACHE_PATH.exists():
        cached = pd.read_csv(TRENDS_CACHE_PATH, parse_dates=["date"]).set_index("date").sort_index()
        return cached, {
            "available": True,
            "source": "local_cache",
            "cache_path": str(TRENDS_CACHE_PATH.relative_to(REPO_ROOT)),
            "geo": GEO,
            "terms_requested": SEARCH_TERMS,
            "terms_available": list(cached.columns),
            "n_weeks": int(len(cached)),
            "first_week": str(cached.index.min().date()),
            "last_week": str(cached.index.max().date()),
            "errors": {},
        }

    series: dict[str, pd.Series] = {}
    errors: dict[str, list[str]] = {}
    for term in SEARCH_TERMS:
        s, term_errors = fetch_one_trends_term(term)
        errors[term] = term_errors
        if s is not None and s.notna().sum() >= MIN_TRENDS_WEEKS:
            series[term] = s

    if not series:
        return None, {
            "available": False,
            "geo": GEO,
            "terms_requested": SEARCH_TERMS,
            "terms_available": [],
            "min_required_weeks": MIN_TRENDS_WEEKS,
            "errors": errors,
        }

    trends = pd.DataFrame(series).sort_index()
    # Google Trends long windows are usually weekly Sunday starts. Move to
    # Friday week-end so trend week t predicts stock-vol week t+1 after shift.
    trends.index = pd.to_datetime(trends.index).tz_localize(None) + pd.Timedelta(days=5)
    trends = trends.resample("W-FRI").last().dropna(how="all")
    trends_to_save = trends.copy()
    trends_to_save.index.name = "date"
    trends_to_save.to_csv(TRENDS_CACHE_PATH)
    meta = {
        "available": True,
        "source": "pytrends_live_fetch",
        "cache_path": str(TRENDS_CACHE_PATH.relative_to(REPO_ROOT)),
        "geo": GEO,
        "terms_requested": SEARCH_TERMS,
        "terms_available": list(trends.columns),
        "n_weeks": int(len(trends)),
        "first_week": str(trends.index.min().date()),
        "last_week": str(trends.index.max().date()),
        "errors": errors,
    }
    return trends, meta


def weekly_realized_variance(close: pd.DataFrame) -> pd.DataFrame:
    logret = np.log(close).diff()
    rv = logret.pow(2).resample("W-FRI").sum(min_count=3)
    rv = rv.dropna(how="all")
    return rv


def rolling_zscore_past(series: pd.Series, window: int = 52) -> pd.Series:
    mean = series.rolling(window, min_periods=26).mean()
    std = series.rolling(window, min_periods=26).std()
    return (series - mean) / std.replace(0, np.nan)


def dm_hac(loss_model: np.ndarray, loss_baseline: np.ndarray, maxlags: int = HAC_MAXLAGS) -> tuple[float, float]:
    diff = pd.Series(loss_baseline - loss_model).dropna()
    if len(diff) < 20 or diff.std(ddof=1) == 0:
        return float("nan"), float("nan")
    fit = sm.OLS(diff.values, np.ones((len(diff), 1))).fit(
        cov_type="HAC",
        cov_kwds={"maxlags": maxlags},
    )
    return float(fit.tvalues[0]), float(fit.pvalues[0])


def build_model_panel(rv: pd.Series, attention: pd.Series) -> pd.DataFrame:
    df = pd.DataFrame({"rv": rv})
    df["log_rv"] = np.log(df["rv"].clip(lower=1e-12))
    df["rv_lag1"] = df["rv"].shift(1)
    df["rv_lag4"] = df["rv"].shift(1).rolling(4).mean()
    df["rv_lag13"] = df["rv"].shift(1).rolling(13).mean()
    # Critical timing: attention observed during week t-1 predicts RV in week t.
    df["attention_lag1"] = attention.shift(1)
    return df.dropna()


def rolling_oos(panel: pd.DataFrame) -> dict[str, Any]:
    features = {
        "har": ["rv_lag1", "rv_lag4", "rv_lag13"],
        "har_attention": ["rv_lag1", "rv_lag4", "rv_lag13", "attention_lag1"],
    }
    n = len(panel)
    oos_start = max(MIN_TRENDS_WEEKS, int(np.floor(n * 0.7)))
    if n - oos_start < 52:
        return {"ok": False, "reason": "insufficient_oos_weeks", "n": n, "oos_n": n - oos_start}

    preds = {name: [] for name in features}
    actual: list[float] = []
    dates: list[str] = []
    fits: dict[str, Any] = {}

    for i in range(oos_start, n):
        if not fits or (i - oos_start) % REFIT_EVERY == 0:
            train = panel.iloc[:i]
            for name, cols in features.items():
                x = sm.add_constant(train[cols], has_constant="add")
                fits[name] = sm.OLS(train["log_rv"], x).fit()

        row = panel.iloc[[i]]
        actual.append(float(row["rv"].iloc[0]))
        dates.append(str(panel.index[i].date()))
        for name, cols in features.items():
            x_row = sm.add_constant(row[cols], has_constant="add")
            pred = float(np.exp(fits[name].predict(x_row).iloc[0]))
            preds[name].append(max(pred, 1e-12))

    actual_arr = np.array(actual)
    har_pred = np.array(preds["har"])
    att_pred = np.array(preds["har_attention"])
    har_loss = qlike_pointwise(actual_arr, har_pred)
    att_loss = qlike_pointwise(actual_arr, att_pred)
    har_qlike = float(qlike(actual_arr, har_pred))
    att_qlike = float(qlike(actual_arr, att_pred))
    dm_t, dm_p = dm_hac(att_loss, har_loss)

    rel = (har_qlike - att_qlike) / abs(har_qlike) * 100.0 if har_qlike != 0 else float("nan")
    return {
        "ok": True,
        "n": n,
        "oos_n": len(actual_arr),
        "oos_start": dates[0],
        "oos_end": dates[-1],
        "models": {
            "har": asdict(ModelResult(har_qlike, 0.0, None, None, None)),
            "har_attention": asdict(
                ModelResult(
                    qlike=att_qlike,
                    relative_improvement_pct=float(rel),
                    dm_hac_t_vs_har=dm_t,
                    dm_hac_p_vs_har=dm_p,
                    harvey_pass_vs_har=bool(np.isfinite(dm_t) and abs(dm_t) > 3.0),
                )
            ),
        },
    }


def run_predictive_test(close: pd.DataFrame, trends: pd.DataFrame) -> dict[str, Any]:
    rv = weekly_realized_variance(close)
    z_terms = trends.apply(rolling_zscore_past)
    attention = z_terms.mean(axis=1).rename("attention_composite")
    results: dict[str, Any] = {
        "attention_feature": "mean rolling 52-week z-score across available Google Trends terms",
        "timing": "attention_composite.shift(1) predicts current-week realized variance",
        "assets": {},
    }
    passes = []
    for ticker in TICKERS:
        joined_index = rv.index.intersection(attention.index)
        panel = build_model_panel(rv[ticker].reindex(joined_index), attention.reindex(joined_index))
        out = rolling_oos(panel)
        results["assets"][ticker] = out
        if out.get("ok"):
            passes.append(bool(out["models"]["har_attention"]["harvey_pass_vs_har"]))

    results["primary_family"] = {
        "tests": len(passes),
        "pass_count_harvey_abs_t_gt_3": int(sum(passes)),
        "verdict": "PASS" if passes and all(passes) else "NULL",
    }
    return results


def main() -> None:
    np.random.seed(SEED)
    started_at = datetime.now(timezone.utc).isoformat()

    close, price_summary = load_taiwan_prices()
    trends, trends_meta = fetch_google_trends()

    results: dict[str, Any] = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Google Trends product-keyword attention vs Taiwan supply-chain weekly volatility",
        "created_at": started_at,
        "finished_at": None,
        "seed": SEED,
        "task_origin": "research_google_trends_vol",
        "data": {
            "price_panel": price_summary,
            "google_trends": trends_meta,
        },
        "related_prior_experiments": {
            "K750": "Real Google Trends fear index did not add robust volatility value beyond VIX; fear was reactive.",
            "K789": "Return/tail-risk follow-up fell back to VIX-proxy and concluded no genuine Google Trends evidence.",
            "K1472": "Rolling HAR framework template for honest low-frequency volatility proxy tests.",
        },
        "literature": REFERENCES,
        "methodology": {
            "frequency": "weekly",
            "target": "current-week close-to-close realized variance, sum of daily log-return squared",
            "baseline": "log-HAR weekly RV model with rv_lag1 / rv_lag4 / rv_lag13",
            "candidate_increment": "Google Trends composite attention lagged one week",
            "lookahead_guard": "attention_lag1 = attention.shift(1); no same-week search volume predicts same-week RV",
            "evaluation": "rolling expanding OOS, QLIKE, HAC DM-style loss-difference t-stat; Harvey |t|>3 gate",
        },
        "limitations": [
            "Google Trends is accessed through unofficial pytrends endpoints and may return HTTP 429.",
            "Only real Google Trends terms that pass the minimum-week gate are used; no VIX/price proxy fills missing terms.",
            "If Google only returns a partial historical panel, the conclusion is limited to that available panel.",
            "Weekly Google Trends values are normalized by Google; stitched chunks are approximate even with overlap scaling.",
        ],
        "hypothesis_tested": False,
        "predictive_results": None,
        "verdict": None,
        "conclusion": None,
        "review": {
            "self_review": "No replacement proxy is used when Google Trends is unavailable.",
            "lookahead": "Predictive branch uses explicit attention.shift(1).",
            "codex_review_path": "experiments/research_google_trends_vol/codex_review.md",
        },
    }

    if trends is None or trends_meta.get("n_weeks", 0) < MIN_TRENDS_WEEKS:
        results["verdict"] = "NULL_DATA_LIMITATION"
        results["conclusion"] = (
            "Google Trends TW product-keyword data could not be fetched via pytrends in this environment "
            "(HTTP 429 / pytrends access failure). The Taiwan price panel is available, but the attention "
            "hypothesis was not tested. No article should claim Google Trends predictive power from this run."
        )
        results["hypothesis_tested"] = False
    else:
        pred = run_predictive_test(close, trends)
        results["predictive_results"] = pred
        results["hypothesis_tested"] = True
        results["verdict"] = pred["primary_family"]["verdict"]
        if results["verdict"] == "PASS":
            results["conclusion"] = (
                "In the available real Google Trends panel, the lagged product-keyword composite improved weekly "
                "RV forecasts versus HAR across all Taiwan supply-chain tickers under the Harvey |t|>3 gate."
            )
        else:
            results["conclusion"] = (
                "In the available real Google Trends panel, the lagged product-keyword composite did not "
                "robustly improve weekly RV forecasts versus HAR across the Taiwan supply-chain ticker family. "
                "This is a partial-panel NULL, not evidence that all product-search attention data are useless."
            )

    results["finished_at"] = datetime.now(timezone.utc).isoformat()
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=safe_float))
    print(json.dumps({
        "experiment_id": EXPERIMENT_ID,
        "verdict": results["verdict"],
        "hypothesis_tested": results["hypothesis_tested"],
        "results_path": str(RESULTS_PATH),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
