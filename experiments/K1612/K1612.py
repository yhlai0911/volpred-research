"""K1612: FOMC language complexity and post-release volatility.

Question
--------
Do FOMC statement / minutes readability and risk-hedging tone predict
post-release SPY volatility persistence and VIX term-structure changes?

Design
------
Official Federal Reserve FOMC calendar links are scraped from the public
calendar page.  Each document is treated as observable only at its public
release date:

* statements: meeting date / statement release date
* minutes: the "Released Month DD, YYYY" date shown in the Fed calendar

Forward volatility targets start on the next trading day after the release
date.  Same-day returns are not used as targets.

Seed: 42 for bootstrap inference.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf
from bs4 import BeautifulSoup


EXPERIMENT_ID = "K1612"
SEED = 42
BOOTSTRAP_REPS = 3000
FED_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
MARKET_START = "2020-12-15"
MARKET_END = "2026-07-03"
TICKERS = ["SPY", "^VIX", "^VIX3M", "^VIX9D"]
USER_AGENT = "VolPred research bot; contact: local experiment K1612"

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
TEXT_DIR = DATA_DIR / "fed_texts"
FIG_DIR = HERE / "figures"
for directory in [DATA_DIR, TEXT_DIR, FIG_DIR]:
    directory.mkdir(exist_ok=True)


LITERATURE = [
    {
        "citation": "Hansen, McMahon, and Prat (2018), Quarterly Journal of Economics, 'Transparency and Deliberation Within the FOMC'",
        "url": "https://doi.org/10.1093/qje/qjx045",
        "use_in_design": "Motivates treating FOMC text as measurable communication rather than only a policy-rate event.",
    },
    {
        "citation": "Rosa (2013), Federal Reserve Bank of New York Economic Policy Review, 'Do FOMC minutes matter to markets?'",
        "url": "https://www.newyorkfed.org/research/epr/2013/1212rosa.html",
        "use_in_design": "Motivates a separate minutes-release event window instead of assigning minutes information to the earlier meeting day.",
    },
    {
        "citation": "Doh, Kim, and Yang (2020), Federal Reserve Bank of Kansas City, 'How You Say It Matters: Text Analysis of FOMC Statements Using Natural Language Processing'",
        "url": "https://www.kansascityfed.org/research/economic-bulletin/how-you-say-it-matters-text-analysis-fomc-statements-using-natural-language-processing-2020/",
        "use_in_design": "Motivates tone / uncertainty dictionaries as public-text predictors.",
    },
    {
        "citation": "St. Louis Fed Economic Synopses (2014), 'The Rising Complexity of the FOMC Statement'",
        "url": "https://fraser.stlouisfed.org/title/economic-synopses-6715/rising-complexity-fomc-statement-624437",
        "use_in_design": "Motivates measuring readability and length as first-order statement characteristics.",
    },
]


HEDGE_WORDS = {
    "appear",
    "appeared",
    "appears",
    "approximately",
    "around",
    "broadly",
    "could",
    "generally",
    "largely",
    "likely",
    "may",
    "might",
    "roughly",
    "seem",
    "seemed",
    "seems",
    "some",
    "somewhat",
    "suggest",
    "suggested",
    "suggests",
    "unclear",
    "would",
}

RISK_UNCERTAINTY_WORDS = {
    "adverse",
    "concern",
    "concerns",
    "downside",
    "elevated",
    "inflation",
    "pressures",
    "risk",
    "risks",
    "uncertain",
    "uncertainties",
    "uncertainty",
    "volatile",
    "volatility",
    "weak",
    "weaker",
}

STATEMENT_RE = re.compile(r"monetary(\d{8})a\.htm$")
MINUTES_RE = re.compile(r"fomcminutes(\d{8})\.htm$")
WORD_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)?")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class FedDocument:
    meeting_date: str
    release_date: str
    document_type: str
    url: str
    source_parent_text: str


def request_bytes(url: str) -> bytes:
    response = requests.get(
        url,
        timeout=45,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    return response.content


def parse_release_date(parent_text: str) -> str | None:
    match = re.search(r"Released\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", parent_text)
    if not match:
        return None
    dt = datetime.strptime(match.group(1), "%B %d, %Y")
    return dt.strftime("%Y-%m-%d")


def parse_fed_calendar() -> pd.DataFrame:
    soup = BeautifulSoup(request_bytes(FED_CALENDAR_URL), "html.parser")
    docs: dict[tuple[str, str], FedDocument] = {}

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        anchor_text = " ".join(anchor.get_text(" ", strip=True).split())
        parent_text = " ".join(anchor.parent.get_text(" ", strip=True).split())
        full_url = urljoin(FED_CALENDAR_URL, href)

        statement_match = STATEMENT_RE.search(href)
        if statement_match and anchor_text == "HTML" and "Statement:" in parent_text:
            raw_date = statement_match.group(1)
            meeting_date = datetime.strptime(raw_date, "%Y%m%d").strftime("%Y-%m-%d")
            docs[(meeting_date, "statement")] = FedDocument(
                meeting_date=meeting_date,
                release_date=meeting_date,
                document_type="statement",
                url=full_url,
                source_parent_text=parent_text,
            )
            continue

        minutes_match = MINUTES_RE.search(href)
        if minutes_match and anchor_text == "HTML" and "Minutes:" in parent_text:
            release_date = parse_release_date(parent_text)
            if not release_date:
                continue
            raw_date = minutes_match.group(1)
            meeting_date = datetime.strptime(raw_date, "%Y%m%d").strftime("%Y-%m-%d")
            docs[(meeting_date, "minutes")] = FedDocument(
                meeting_date=meeting_date,
                release_date=release_date,
                document_type="minutes",
                url=full_url,
                source_parent_text=parent_text,
            )

    rows = [
        {
            "meeting_date": doc.meeting_date,
            "release_date": doc.release_date,
            "document_type": doc.document_type,
            "url": doc.url,
            "source_parent_text": doc.source_parent_text,
        }
        for doc in docs.values()
    ]
    calendar = pd.DataFrame(rows).sort_values(["release_date", "document_type"])
    calendar.to_csv(DATA_DIR / "fed_document_calendar.csv", index=False)
    return calendar


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"Last Update:.*$", "", text)
    return text.strip()


def fetch_document_text(row: pd.Series) -> str:
    filename = f"{row.meeting_date}_{row.document_type}.txt"
    path = TEXT_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8")

    soup = BeautifulSoup(request_bytes(row.url), "html.parser")
    article = soup.select_one("div#article") or soup.select_one("article") or soup.select_one("main")
    if article is None:
        raise RuntimeError(f"Could not locate article text for {row.url}")
    for tag in article.select("script, style, noscript"):
        tag.decompose()
    text = clean_text(article.get_text(" ", strip=True))
    path.write_text(text, encoding="utf-8")
    return text


def syllable_count(word: str) -> int:
    word = re.sub(r"[^a-z]", "", word.lower())
    if not word:
        return 0
    groups = re.findall(r"[aeiouy]+", word)
    count = len(groups)
    if word.endswith("e") and count > 1 and not word.endswith(("le", "ue")):
        count -= 1
    return max(count, 1)


def zscore(series: pd.Series) -> pd.Series:
    std = series.std(ddof=0)
    if not np.isfinite(std) or std == 0:
        return pd.Series(np.zeros(len(series)), index=series.index)
    return (series - series.mean()) / std


def extract_text_metrics(calendar: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for _, row in calendar.iterrows():
        text = fetch_document_text(row)
        words = [w.lower() for w in WORD_RE.findall(text)]
        sentences = [s for s in SENTENCE_RE.split(text) if WORD_RE.search(s)]
        n_words = len(words)
        n_sentences = max(len(sentences), 1)
        n_syllables = sum(syllable_count(w) for w in words)
        unique_words = len(set(words))

        fk_grade = (
            0.39 * (n_words / n_sentences)
            + 11.8 * (n_syllables / max(n_words, 1))
            - 15.59
        )
        flesch_ease = (
            206.835
            - 1.015 * (n_words / n_sentences)
            - 84.6 * (n_syllables / max(n_words, 1))
        )
        hedge_count = sum(1 for word in words if word in HEDGE_WORDS)
        risk_count = sum(1 for word in words if word in RISK_UNCERTAINTY_WORDS)

        rows.append(
            {
                "meeting_date": row.meeting_date,
                "release_date": row.release_date,
                "document_type": row.document_type,
                "url": row.url,
                "word_count": int(n_words),
                "sentence_count": int(n_sentences),
                "avg_sentence_length": float(n_words / n_sentences),
                "syllable_per_word": float(n_syllables / max(n_words, 1)),
                "flesch_kincaid_grade": float(fk_grade),
                "flesch_reading_ease": float(flesch_ease),
                "lexical_diversity": float(unique_words / max(n_words, 1)),
                "hedge_count": int(hedge_count),
                "risk_uncertainty_count": int(risk_count),
                "hedge_per_1000": float(1000 * hedge_count / max(n_words, 1)),
                "risk_uncertainty_per_1000": float(1000 * risk_count / max(n_words, 1)),
            }
        )

    metrics = pd.DataFrame(rows).sort_values(["release_date", "document_type"])
    for column in [
        "word_count",
        "avg_sentence_length",
        "flesch_kincaid_grade",
        "flesch_reading_ease",
        "lexical_diversity",
        "hedge_per_1000",
        "risk_uncertainty_per_1000",
    ]:
        metrics[f"{column}_z_within_type"] = metrics.groupby("document_type")[column].transform(zscore)

    metrics["complexity_z"] = metrics[
        [
            "word_count_z_within_type",
            "avg_sentence_length_z_within_type",
            "flesch_kincaid_grade_z_within_type",
            "lexical_diversity_z_within_type",
        ]
    ].mean(axis=1)
    metrics["hedged_risk_tone_z"] = metrics[
        ["hedge_per_1000_z_within_type", "risk_uncertainty_per_1000_z_within_type"]
    ].mean(axis=1)
    metrics.to_csv(DATA_DIR / "fed_document_text_metrics.csv", index=False)
    return metrics


def download_market_data() -> pd.DataFrame:
    raw = yf.download(
        TICKERS,
        start=MARKET_START,
        end=MARKET_END,
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].copy()
    else:
        close = raw.copy()
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    close = close.sort_index()
    close.to_csv(DATA_DIR / "yfinance_market_close.csv")
    return close


def build_market_features(close: pd.DataFrame) -> pd.DataFrame:
    market = pd.DataFrame(index=close.index)
    market["spy_close"] = close["SPY"]
    market["spy_log_return"] = np.log(close["SPY"] / close["SPY"].shift(1))
    market["lag_rv22_ann"] = market["spy_log_return"].rolling(22).std().shift(1) * math.sqrt(252)
    market["vix_close"] = close["^VIX"]
    market["vix_dec"] = close["^VIX"] / 100
    market["vix9d_vix"] = close["^VIX9D"] / close["^VIX"]
    market["vix_vix3m"] = close["^VIX"] / close["^VIX3M"]
    market = market.replace([np.inf, -np.inf], np.nan)
    market.to_csv(DATA_DIR / "market_features_daily.csv")
    return market


def next_market_position(index: pd.DatetimeIndex, release_date: str) -> int | None:
    release_ts = pd.Timestamp(release_date)
    positions = np.flatnonzero(index >= release_ts)
    if len(positions) == 0:
        return None
    return int(positions[0])


def realized_vol(returns: pd.Series) -> float:
    values = returns.dropna().to_numpy(dtype=float)
    if len(values) < 2:
        return float("nan")
    return float(np.std(values, ddof=1) * math.sqrt(252))


def build_event_panel(metrics: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    index = market.index
    for _, row in metrics.iterrows():
        pos = next_market_position(index, row.release_date)
        if pos is None:
            continue
        event_date = index[pos]
        event_features = market.iloc[pos]
        out = row.to_dict()
        out["event_market_date"] = event_date.strftime("%Y-%m-%d")
        out["days_from_release_to_market_date"] = int((event_date - pd.Timestamp(row.release_date)).days)

        for column in ["lag_rv22_ann", "vix_close", "vix_dec", "vix9d_vix", "vix_vix3m"]:
            out[column] = float(event_features[column]) if pd.notna(event_features[column]) else np.nan

        for horizon in [5, 22]:
            future = market.iloc[pos + 1 : pos + 1 + horizon]
            if len(future) < horizon:
                out[f"fwd{horizon}_spy_rv_ann"] = np.nan
                out[f"fwd{horizon}_mean_vix9d_vix"] = np.nan
                out[f"fwd{horizon}_mean_vix_vix3m"] = np.nan
                out[f"delta_vix9d_vix_{horizon}d"] = np.nan
                out[f"delta_vix_vix3m_{horizon}d"] = np.nan
                continue
            out[f"fwd{horizon}_spy_rv_ann"] = realized_vol(future["spy_log_return"])
            out[f"fwd{horizon}_mean_vix9d_vix"] = float(future["vix9d_vix"].mean())
            out[f"fwd{horizon}_mean_vix_vix3m"] = float(future["vix_vix3m"].mean())
            out[f"delta_vix9d_vix_{horizon}d"] = float(
                future["vix9d_vix"].iloc[-1] - event_features["vix9d_vix"]
            )
            out[f"delta_vix_vix3m_{horizon}d"] = float(
                future["vix_vix3m"].iloc[-1] - event_features["vix_vix3m"]
            )
        rows.append(out)

    panel = pd.DataFrame(rows).sort_values(["event_market_date", "document_type"])
    panel["is_minutes"] = (panel["document_type"] == "minutes").astype(int)
    panel.to_csv(DATA_DIR / "event_panel.csv", index=False)
    return panel


def ols_hac(
    df: pd.DataFrame,
    target: str,
    metric: str,
    controls: Iterable[str],
    sample_label: str,
) -> dict:
    columns = [target, metric, *controls]
    work = df.dropna(subset=columns).copy()
    if len(work) < len(columns) + 5:
        return {
            "sample": sample_label,
            "target": target,
            "metric": metric,
            "n": int(len(work)),
            "status": "insufficient_sample",
        }

    y = work[target].astype(float)
    x = sm.add_constant(work[[metric, *controls]].astype(float))
    model = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": 1})
    return {
        "sample": sample_label,
        "target": target,
        "metric": metric,
        "n": int(len(work)),
        "controls": list(controls),
        "coef": float(model.params[metric]),
        "hac_t": float(model.tvalues[metric]),
        "p_value": float(model.pvalues[metric]),
        "r2": float(model.rsquared),
        "status": "ok",
    }


def bootstrap_high_low(
    df: pd.DataFrame,
    target: str,
    metric: str,
    sample_label: str,
    reps: int = BOOTSTRAP_REPS,
    seed: int = SEED,
) -> dict:
    work = df.dropna(subset=[target, metric]).copy()
    if len(work) < 18:
        return {
            "sample": sample_label,
            "target": target,
            "metric": metric,
            "n": int(len(work)),
            "status": "insufficient_sample",
        }
    lo = work[metric].quantile(1 / 3)
    hi = work[metric].quantile(2 / 3)
    low = work.loc[work[metric] <= lo, target].to_numpy(dtype=float)
    high = work.loc[work[metric] >= hi, target].to_numpy(dtype=float)
    if len(low) < 5 or len(high) < 5:
        return {
            "sample": sample_label,
            "target": target,
            "metric": metric,
            "n": int(len(work)),
            "status": "insufficient_terciles",
        }
    rng = np.random.default_rng(seed)
    obs = float(np.mean(high) - np.mean(low))
    boot = np.empty(reps, dtype=float)
    for i in range(reps):
        boot[i] = np.mean(rng.choice(high, size=len(high), replace=True)) - np.mean(
            rng.choice(low, size=len(low), replace=True)
        )
    left_tail = int(np.sum(boot <= 0))
    right_tail = int(np.sum(boot >= 0))
    min_tail = min(left_tail, right_tail)
    p_two_sided = float(2 * min_tail / reps)
    p_is_upper_bound = False
    if min_tail == 0:
        p_two_sided = float(2 / reps)
        p_is_upper_bound = True
    return {
        "sample": sample_label,
        "target": target,
        "metric": metric,
        "n": int(len(work)),
        "n_low": int(len(low)),
        "n_high": int(len(high)),
        "low_tercile_mean": float(np.mean(low)),
        "high_tercile_mean": float(np.mean(high)),
        "high_minus_low": obs,
        "ci95": [float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))],
        "p_two_sided": p_two_sided,
        "p_is_upper_bound": p_is_upper_bound,
        "status": "ok",
    }


def run_inference(panel: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    targets = [
        "fwd5_spy_rv_ann",
        "fwd22_spy_rv_ann",
        "delta_vix9d_vix_5d",
        "delta_vix_vix3m_22d",
    ]
    metrics = ["complexity_z", "hedged_risk_tone_z"]
    sample_specs = {
        "all_documents_release_aligned": (
            panel,
            ["lag_rv22_ann", "vix_dec", "vix9d_vix", "is_minutes"],
        ),
        "statement_only_meeting_day": (
            panel.loc[panel["document_type"] == "statement"].copy(),
            ["lag_rv22_ann", "vix_dec", "vix9d_vix"],
        ),
        "minutes_only_release_day": (
            panel.loc[panel["document_type"] == "minutes"].copy(),
            ["lag_rv22_ann", "vix_dec", "vix9d_vix"],
        ),
    }
    regressions: list[dict] = []
    bootstraps: list[dict] = []
    for sample_label, (sample_df, controls) in sample_specs.items():
        for metric in metrics:
            for target in targets:
                regressions.append(ols_hac(sample_df, target, metric, controls, sample_label))
                bootstraps.append(bootstrap_high_low(sample_df, target, metric, sample_label))
    pd.DataFrame(regressions).to_csv(DATA_DIR / "regression_results.csv", index=False)
    pd.DataFrame(bootstraps).to_csv(DATA_DIR / "bootstrap_high_low_results.csv", index=False)
    return regressions, bootstraps


def summarize_significance(regressions: list[dict]) -> dict:
    ok = [r for r in regressions if r.get("status") == "ok"]
    primary = [
        r
        for r in ok
        if r["sample"] in {"all_documents_release_aligned", "statement_only_meeting_day"}
        and r["target"] in {"fwd22_spy_rv_ann", "delta_vix_vix3m_22d"}
    ]
    significant = [r for r in primary if r["p_value"] < 0.05]
    strong = [
        r
        for r in significant
        if abs(r["hac_t"]) >= 2.5 and r["sample"] == "statement_only_meeting_day"
    ]
    if strong:
        verdict = "MIXED_PREDICTIVE_SIGNAL_LOW_POWER"
    elif significant:
        verdict = "WEAK_MIXED_SIGNAL_NEEDS_CONFIRMATION"
    else:
        verdict = "NULL_LOW_POWER_RELEASE_ALIGNED"
    return {
        "verdict": verdict,
        "n_primary_tests": int(len(primary)),
        "n_primary_p_lt_0_05": int(len(significant)),
        "primary_p_lt_0_05": significant,
    }


def make_figures(panel: pd.DataFrame, regressions: list[dict], bootstraps: list[dict]) -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 150,
            "savefig.dpi": 150,
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )

    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    for document_type, marker in [("statement", "o"), ("minutes", "s")]:
        subset = panel.loc[panel["document_type"] == document_type].copy()
        dates = pd.to_datetime(subset["release_date"])
        axes[0].plot(dates, subset["complexity_z"], marker=marker, label=document_type)
        axes[1].plot(dates, subset["hedged_risk_tone_z"], marker=marker, label=document_type)
    axes[0].axhline(0, color="#666666", linewidth=0.8)
    axes[1].axhline(0, color="#666666", linewidth=0.8)
    axes[0].set_title("FOMC document complexity z-score by release date")
    axes[1].set_title("FOMC hedged / risk-tone z-score by release date")
    axes[0].set_ylabel("Complexity z")
    axes[1].set_ylabel("Tone z")
    axes[1].set_xlabel("Release date")
    axes[0].legend(frameon=False, ncol=2)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig1_text_metrics_by_release.png")
    plt.close(fig)

    reg_df = pd.DataFrame([r for r in regressions if r.get("status") == "ok"])
    show = reg_df.loc[
        (reg_df["sample"] == "all_documents_release_aligned")
        & reg_df["target"].isin(["fwd22_spy_rv_ann", "delta_vix_vix3m_22d"])
    ].copy()
    show["label"] = show["metric"].str.replace("_", " ") + " / " + show["target"]
    fig, ax = plt.subplots(figsize=(11, 5))
    colors = ["#2F5D8C" if p >= 0.05 else "#A6423A" for p in show["p_value"]]
    ax.barh(np.arange(len(show)), show["hac_t"], color=colors)
    ax.axvline(0, color="#555555", linewidth=1)
    ax.axvline(1.96, color="#999999", linewidth=0.8, linestyle="--")
    ax.axvline(-1.96, color="#999999", linewidth=0.8, linestyle="--")
    ax.set_yticks(np.arange(len(show)))
    ax.set_yticklabels(show["label"])
    ax.set_xlabel("HAC t-statistic")
    ax.set_title("Release-aligned regression t-statistics")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig2_regression_tstats.png")
    plt.close(fig)

    boot_df = pd.DataFrame([b for b in bootstraps if b.get("status") == "ok"])
    boot_show = boot_df.loc[
        (boot_df["sample"] == "all_documents_release_aligned")
        & (boot_df["target"].isin(["fwd22_spy_rv_ann", "delta_vix_vix3m_22d"]))
    ].copy()
    boot_show["label"] = boot_show["metric"].str.replace("_", " ") + " / " + boot_show["target"]
    fig, ax = plt.subplots(figsize=(11, 5.5))
    y = np.arange(len(boot_show))
    means = boot_show["high_minus_low"].to_numpy(dtype=float)
    left = means - np.array([ci[0] for ci in boot_show["ci95"]], dtype=float)
    right = np.array([ci[1] for ci in boot_show["ci95"]], dtype=float) - means
    ax.errorbar(means, y, xerr=[left, right], fmt="o", color="#2F5D8C", ecolor="#9AA9B5")
    ax.axvline(0, color="#555555", linewidth=1)
    ax.set_yticks(y)
    ax.set_yticklabels(boot_show["label"])
    ax.set_xlabel("Top tercile minus bottom tercile")
    ax.set_title("Bootstrap high-low differences, 3,000 reps")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig3_bootstrap_high_low.png")
    plt.close(fig)


def finite_or_none(value):
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {k: finite_or_none(v) for k, v in value.items()}
    if isinstance(value, list):
        return [finite_or_none(v) for v in value]
    return value


def main() -> None:
    calendar = parse_fed_calendar()
    text_metrics = extract_text_metrics(calendar)
    close = download_market_data()
    market = build_market_features(close)
    panel = build_event_panel(text_metrics, market)
    regressions, bootstraps = run_inference(panel)
    significance = summarize_significance(regressions)
    make_figures(panel, regressions, bootstraps)

    market_coverage = {}
    for ticker in TICKERS:
        series = close[ticker].dropna()
        market_coverage[ticker] = {
            "n_obs": int(len(series)),
            "first_date": str(series.index.min().date()) if len(series) else None,
            "last_date": str(series.index.max().date()) if len(series) else None,
        }

    sample_counts = {
        "calendar_documents": int(len(calendar)),
        "statement_documents": int((calendar["document_type"] == "statement").sum()),
        "minutes_documents": int((calendar["document_type"] == "minutes").sum()),
        "event_panel_rows": int(len(panel)),
        "rows_with_fwd5_rv": int(panel["fwd5_spy_rv_ann"].notna().sum()),
        "rows_with_fwd22_rv": int(panel["fwd22_spy_rv_ann"].notna().sum()),
        "first_release_date": str(panel["release_date"].min()) if len(panel) else None,
        "last_release_date": str(panel["release_date"].max()) if len(panel) else None,
    }

    text_summary = (
        text_metrics.groupby("document_type")
        .agg(
            n=("word_count", "size"),
            median_word_count=("word_count", "median"),
            median_flesch_kincaid_grade=("flesch_kincaid_grade", "median"),
            median_hedge_per_1000=("hedge_per_1000", "median"),
            median_risk_uncertainty_per_1000=("risk_uncertainty_per_1000", "median"),
        )
        .reset_index()
        .to_dict(orient="records")
    )

    results = {
        "experiment_id": EXPERIMENT_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "bootstrap_reps": BOOTSTRAP_REPS,
        "fed_calendar_url": FED_CALENDAR_URL,
        "market_data_source": "yfinance adjusted close via yf.download(auto_adjust=True)",
        "market_start": MARKET_START,
        "market_end": MARKET_END,
        "literature": LITERATURE,
        "lookahead_policy": {
            "documents_are_observed_at": "release_date",
            "statements_release_date": "meeting_date from official Fed statement URL",
            "minutes_release_date": "official Fed calendar 'Released Month DD, YYYY' parent text",
            "forward_targets_start": "next trading day after event_market_date",
            "lagged_vol_control": "22-trading-day SPY realized volatility shifted by one day",
        },
        "sample_counts": sample_counts,
        "market_coverage": market_coverage,
        "text_metric_summary": text_summary,
        "regressions": regressions,
        "bootstrap_high_low": bootstraps,
        "significance_summary": significance,
        "verdict": significance["verdict"],
        "output_files": {
            "calendar_csv": str(DATA_DIR / "fed_document_calendar.csv"),
            "text_metrics_csv": str(DATA_DIR / "fed_document_text_metrics.csv"),
            "event_panel_csv": str(DATA_DIR / "event_panel.csv"),
            "regression_csv": str(DATA_DIR / "regression_results.csv"),
            "bootstrap_csv": str(DATA_DIR / "bootstrap_high_low_results.csv"),
            "figures": [
                str(FIG_DIR / "fig1_text_metrics_by_release.png"),
                str(FIG_DIR / "fig2_regression_tstats.png"),
                str(FIG_DIR / "fig3_bootstrap_high_low.png"),
            ],
        },
        "limitations": [
            "The official calendar page available in this runtime provides HTML statement/minutes links for 2021-2026, so sample size is modest.",
            "Minutes are tested at their public release dates, not at the earlier meeting dates; this avoids lookahead but differs from a pure meeting-day event study.",
            "Readability metrics are deterministic public-text proxies, not a structural model of Federal Reserve intent.",
            "HAC maxlags=1 and bootstrap terciles are low-power safeguards for an event-level sample, not proof of absence.",
        ],
    }
    with open(HERE / "K1612_results.json", "w", encoding="utf-8") as f:
        json.dump(finite_or_none(results), f, indent=2, ensure_ascii=False)

    print(json.dumps(finite_or_none(significance), indent=2, ensure_ascii=False))
    print(f"Wrote {HERE / 'K1612_results.json'}")


if __name__ == "__main__":
    main()
