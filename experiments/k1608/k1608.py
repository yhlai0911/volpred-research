"""K1608: Blockbuster movie attention shocks and next-week market RV.

This is a public-data proxy diagnostic, not a replication of Hong and Wei
(2025).  The experiment uses Wikipedia U.S. box-office number-one weekend
tables as the entertainment-attention proxy and yfinance daily prices for
market outcomes.

Lookahead guard:
- The shock score for weekend t uses the current weekend gross and a trailing
  52-week distribution shifted by one weekend.
- Outcomes are the next five trading days strictly after the weekend end date.
- Regression controls are measured before the target window or deterministic
  calendar proxies.  No same-week financial returns enter the shock definition.

Seed: 42 for all bootstrap inference.
"""
from __future__ import annotations

import json
import re
import time
import warnings
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf

warnings.filterwarnings("ignore", category=FutureWarning)

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
DATA_DIR.mkdir(exist_ok=True)
FIG_DIR.mkdir(exist_ok=True)

EXPERIMENT_ID = "k1608"
SEED = 42
START_YEAR = 2005
END_YEAR = 2026
TRAILING_WEEKS = 52
MIN_TRAILING_WEEKS = 26
SHOCK_Z = 1.5
BOOTSTRAP_REPS = 5000
MIN_PRE_DAYS = 15
HORIZON_DAYS = 5

BROAD_TICKERS = ["SPY", "QQQ", "IWM", "XLY"]
ENTERTAINMENT_TICKERS = ["DIS", "NFLX", "AMC", "CMCSA", "EA", "TTWO", "RBLX"]
ANALYSIS_ASSETS = ["SPY", "QQQ", "IWM", "XLY", "ENTERTAINMENT_BASKET", "DIS", "NFLX", "AMC"]
YF_TICKERS = BROAD_TICKERS + ENTERTAINMENT_TICKERS + ["^VIX"]

WIKI_URL = (
    "https://en.wikipedia.org/wiki/"
    "List_of_{year}_box_office_number-one_films_in_the_United_States"
)

LITERATURE = [
    {
        "citation": "Hong and Wei (2025), Review of Finance, 'Blockbuster or Bust? Silver Screen Effect and Stock Returns'",
        "url": "https://academic.oup.com/rof/article/29/2/603/7990917",
        "use_in_design": "Motivates blockbuster releases as exogenous entertainment mood shocks; this K tests a public proxy footprint on RV.",
    },
    {
        "citation": "Liu et al. (2024), Journal of Behavioral and Experimental Finance, 'When Hollywood movies steal the show...'",
        "url": "https://www.sciencedirect.com/science/article/pii/S1057521924004332",
        "use_in_design": "Motivates investor inattention / market-comovement channels around film releases.",
    },
    {
        "citation": "Da, Engelberg, and Gao (2011), Journal of Finance, 'In Search of Attention'",
        "url": "https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.2011.01679.x",
        "use_in_design": "Supports search / attention proxies as distinct from volume/news proxies; Google Trends is noted but not used here due API fragility.",
    },
    {
        "citation": "Edmans, Garcia, and Norli (2007), Journal of Finance, 'Sports Sentiment and Stock Returns'",
        "url": "https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2007.01262.x",
        "use_in_design": "Mood-event precedent; reinforces conservative event-window interpretation.",
    },
    {
        "citation": "Hirshleifer and Shumway (2003), Journal of Finance, 'Good Day Sunshine'",
        "url": "https://onlinelibrary.wiley.com/doi/abs/10.1111/1540-6261.00556",
        "use_in_design": "Classic mood-market relation; treated as motivation, not proof for this proxy.",
    },
]


def clean_ref_text(value: object) -> str:
    text = str(value)
    text = re.sub(r"\[[^\]]+\]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_money(value: object) -> float | None:
    text = clean_ref_text(value)
    match = re.search(r"\$?\s*([0-9][0-9,]+)", text)
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def parse_weekend_date(value: object, year: int) -> pd.Timestamp | None:
    text = clean_ref_text(value)
    if not re.search(r"\b\d{4}\b", text):
        text = f"{text}, {year}"
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).normalize()


def find_box_office_table(tables: list[pd.DataFrame]) -> pd.DataFrame:
    for table in tables:
        cols = [str(c).strip().lower() for c in table.columns]
        has_date = any("weekend" in c and "date" in c for c in cols)
        has_gross = any("gross" in c or "box office" in c for c in cols)
        has_film = any(c == "film" or "film" in c for c in cols)
        if has_date and has_gross and has_film:
            return table.copy()
    raise ValueError("could not locate weekend box-office table")


def fetch_box_office_year(year: int) -> tuple[pd.DataFrame, dict]:
    url = WIKI_URL.format(year=year)
    status = {"year": year, "url": url, "ok": False, "rows": 0, "error": None}
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "VolPredResearchBot/1.0 (academic proxy diagnostic)"},
            timeout=30,
        )
        response.raise_for_status()
        tables = pd.read_html(StringIO(response.text))
        table = find_box_office_table(tables)
        normalized = {str(c).strip().lower(): c for c in table.columns}
        date_col = next(c for key, c in normalized.items() if "weekend" in key and "date" in key)
        gross_col = next(c for key, c in normalized.items() if "gross" in key or "box office" in key)
        film_col = next(c for key, c in normalized.items() if "film" in key)

        records = []
        for _, row in table.iterrows():
            weekend_end = parse_weekend_date(row[date_col], year)
            gross = parse_money(row[gross_col])
            if weekend_end is None or gross is None:
                continue
            records.append(
                {
                    "year": year,
                    "weekend_end": weekend_end,
                    "film": clean_ref_text(row[film_col]),
                    "gross_usd": gross,
                    "source_url": url,
                }
            )
        out = pd.DataFrame(records)
        status.update(ok=True, rows=int(len(out)))
        return out, status
    except Exception as exc:  # noqa: BLE001
        status["error"] = f"{type(exc).__name__}: {exc}"
        return pd.DataFrame(), status


def build_box_office_panel() -> tuple[pd.DataFrame, list[dict]]:
    frames = []
    statuses = []
    for year in range(START_YEAR, END_YEAR + 1):
        frame, status = fetch_box_office_year(year)
        statuses.append(status)
        if not frame.empty:
            frames.append(frame)
        time.sleep(0.1)
    if not frames:
        raise RuntimeError("no Wikipedia box-office rows fetched")

    panel = pd.concat(frames, ignore_index=True)
    panel = panel.drop_duplicates(subset=["weekend_end"], keep="first")
    panel = panel.sort_values("weekend_end").reset_index(drop=True)
    panel["log_gross"] = np.log(panel["gross_usd"])

    trailing = panel["log_gross"].shift(1).rolling(TRAILING_WEEKS, min_periods=MIN_TRAILING_WEEKS)
    panel["gross_z_trailing52"] = (panel["log_gross"] - trailing.mean()) / trailing.std(ddof=1)
    panel["signal_available"] = panel["gross_z_trailing52"].notna()
    panel["blockbuster_shock"] = panel["signal_available"] & (panel["gross_z_trailing52"] >= SHOCK_Z)
    panel["gross_100m_nominal"] = panel["gross_usd"] >= 100_000_000
    return panel, statuses


def extract_close(raw: pd.DataFrame) -> pd.DataFrame:
    if isinstance(raw.columns, pd.MultiIndex):
        level0 = set(raw.columns.get_level_values(0))
        if "Close" in level0:
            close = raw["Close"].copy()
        elif "Adj Close" in level0:
            close = raw["Adj Close"].copy()
        else:
            raise ValueError(f"could not find Close columns in {raw.columns}")
    else:
        close = raw.to_frame(name=YF_TICKERS[0]) if isinstance(raw, pd.Series) else raw.copy()
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    close = close.sort_index()
    return close.dropna(axis=1, how="all")


def download_prices(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    raw = yf.download(
        YF_TICKERS,
        start=start.strftime("%Y-%m-%d"),
        end=(end + pd.Timedelta(days=7)).strftime("%Y-%m-%d"),
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    close = extract_close(raw)
    available = [c for c in close.columns if c in YF_TICKERS]
    close = close[available]
    if "SPY" not in close.columns:
        raise RuntimeError("SPY price history unavailable")
    return close


def make_returns(close: pd.DataFrame) -> pd.DataFrame:
    returns = np.log(close / close.shift(1))
    available_ent = [c for c in ENTERTAINMENT_TICKERS if c in returns.columns]
    ent_counts = returns[available_ent].notna().sum(axis=1)
    basket = returns[available_ent].mean(axis=1, skipna=True)
    returns["ENTERTAINMENT_BASKET"] = basket.where(ent_counts >= 3)
    return returns


def prior_value(series: pd.Series, when: pd.Timestamp) -> float | None:
    valid = series.loc[series.index <= when].dropna()
    if valid.empty:
        return None
    return float(valid.iloc[-1])


def macro_proxy_flags(target_days: Iterable[pd.Timestamp]) -> dict[str, int]:
    days = [pd.Timestamp(d) for d in target_days]
    nfp = any(d.weekday() == 4 and 1 <= d.day <= 7 for d in days)
    cpi = any(d.weekday() in (1, 2, 3) and 10 <= d.day <= 15 for d in days)
    fomc_months = {1, 3, 5, 6, 7, 9, 11, 12}
    fomc = any(d.weekday() == 2 and d.month in fomc_months and 14 <= d.day <= 21 for d in days)
    return {
        "nfp_proxy_week": int(nfp),
        "cpi_proxy_week": int(cpi),
        "fomc_proxy_week": int(fomc),
    }


def compute_asset_windows(
    movies: pd.DataFrame,
    returns: pd.DataFrame,
    close: pd.DataFrame,
    asset: str,
) -> pd.DataFrame:
    rows = []
    idx = returns.index
    asset_ret = returns[asset]
    spy_ret = returns["SPY"]
    vix_close = close["^VIX"] if "^VIX" in close.columns else pd.Series(dtype=float)

    for _, event in movies.iterrows():
        if not bool(event["signal_available"]):
            continue
        weekend_end = pd.Timestamp(event["weekend_end"])
        pos = idx.searchsorted(weekend_end, side="right")
        if pos + HORIZON_DAYS > len(idx) or pos < MIN_PRE_DAYS:
            continue

        target = asset_ret.iloc[pos : pos + HORIZON_DAYS].dropna()
        pre = asset_ret.iloc[max(0, pos - 20) : pos].dropna()
        spy_pre5 = spy_ret.iloc[max(0, pos - 5) : pos].dropna()
        spy_pre20 = spy_ret.iloc[max(0, pos - 20) : pos].dropna()
        if len(target) != HORIZON_DAYS or len(pre) < MIN_PRE_DAYS or len(spy_pre20) < MIN_PRE_DAYS:
            continue

        target_days = list(target.index)
        fwd_rv = float(target.std(ddof=1) * np.sqrt(252))
        prior_rv = float(pre.std(ddof=1) * np.sqrt(252))
        downside_semivar = float(np.mean(np.minimum(target.to_numpy(), 0.0) ** 2) * 252)
        span_days = int((target_days[-1] - weekend_end).days)
        macro_flags = macro_proxy_flags(target_days)

        rows.append(
            {
                "asset": asset,
                "weekend_end": weekend_end.strftime("%Y-%m-%d"),
                "target_start": target_days[0].strftime("%Y-%m-%d"),
                "target_end": target_days[-1].strftime("%Y-%m-%d"),
                "movie_year": int(event["year"]),
                "film": event["film"],
                "gross_usd": float(event["gross_usd"]),
                "gross_z_trailing52": float(event["gross_z_trailing52"]),
                "blockbuster_shock": int(bool(event["blockbuster_shock"])),
                "gross_100m_nominal": int(bool(event["gross_100m_nominal"])),
                "fwd5_return": float(target.sum()),
                "fwd5_rv_ann": fwd_rv,
                "prior20_rv_ann": prior_rv,
                "log_fwd5_rv_ratio": float(np.log((fwd_rv + 1e-8) / (prior_rv + 1e-8))),
                "downside_semivar_5d_ann": downside_semivar,
                "spy_prior5_return": float(spy_pre5.sum()) if len(spy_pre5) == 5 else np.nan,
                "spy_prior20_rv_ann": float(spy_pre20.std(ddof=1) * np.sqrt(252)),
                "vix_level_lag": prior_value(vix_close, weekend_end),
                "target_calendar_span_days": span_days,
                "holiday_or_closure_week": int(span_days > 6),
                "month": int(weekend_end.month),
                **macro_flags,
            }
        )
    return pd.DataFrame(rows)


def build_event_panel(movies: pd.DataFrame, returns: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for asset in ANALYSIS_ASSETS:
        if asset not in returns.columns:
            continue
        frame = compute_asset_windows(movies, returns, close, asset)
        if not frame.empty:
            frames.append(frame)
    if not frames:
        raise RuntimeError("no event-window rows produced")
    return pd.concat(frames, ignore_index=True)


def regression_hac(asset_df: pd.DataFrame, y_col: str) -> dict:
    controls = [
        "blockbuster_shock",
        "spy_prior5_return",
        "spy_prior20_rv_ann",
        "vix_level_lag",
        "holiday_or_closure_week",
        "nfp_proxy_week",
        "cpi_proxy_week",
        "fomc_proxy_week",
    ]
    sample = asset_df.dropna(subset=[y_col, *controls]).copy()
    if sample["blockbuster_shock"].nunique() < 2 or len(sample) < 80:
        return {"ok": False, "reason": "insufficient sample or no shock variation", "n": int(len(sample))}

    x = sample[controls].astype(float)
    month_dummies = pd.get_dummies(sample["month"], prefix="month", drop_first=True, dtype=float)
    x = pd.concat([x, month_dummies], axis=1)
    x = sm.add_constant(x, has_constant="add")
    y = sample[y_col].astype(float)
    fit = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": 4})

    coef = float(fit.params["blockbuster_shock"])
    se = float(fit.bse["blockbuster_shock"])
    return {
        "ok": True,
        "n": int(len(sample)),
        "n_shock": int(sample["blockbuster_shock"].sum()),
        "coef": coef,
        "se_hac_lag4": se,
        "t_hac_lag4": float(fit.tvalues["blockbuster_shock"]),
        "p_hac_lag4": float(fit.pvalues["blockbuster_shock"]),
        "ci95_low": coef - 1.96 * se,
        "ci95_high": coef + 1.96 * se,
        "r2": float(fit.rsquared),
    }


def year_cluster_bootstrap(asset_df: pd.DataFrame, y_col: str) -> dict:
    sample = asset_df.dropna(subset=[y_col, "blockbuster_shock"]).copy()
    if sample["blockbuster_shock"].nunique() < 2:
        return {"ok": False, "reason": "no shock variation"}
    sample["movie_year"] = sample["movie_year"].astype(int)
    observed = float(
        sample.loc[sample["blockbuster_shock"] == 1, y_col].mean()
        - sample.loc[sample["blockbuster_shock"] == 0, y_col].mean()
    )
    rng = np.random.default_rng(SEED)
    year_stats = []
    for year, group in sample.groupby("movie_year"):
        shock = group.loc[group["blockbuster_shock"] == 1, y_col].astype(float)
        non = group.loc[group["blockbuster_shock"] == 0, y_col].astype(float)
        year_stats.append(
            {
                "year": int(year),
                "shock_sum": float(shock.sum()),
                "shock_n": int(shock.count()),
                "non_sum": float(non.sum()),
                "non_n": int(non.count()),
            }
        )
    stats_df = pd.DataFrame(year_stats).sort_values("year")
    n_years = len(stats_df)
    draw = rng.integers(0, n_years, size=(BOOTSTRAP_REPS, n_years))
    shock_sum = stats_df["shock_sum"].to_numpy()[draw].sum(axis=1)
    shock_n = stats_df["shock_n"].to_numpy()[draw].sum(axis=1)
    non_sum = stats_df["non_sum"].to_numpy()[draw].sum(axis=1)
    non_n = stats_df["non_n"].to_numpy()[draw].sum(axis=1)
    valid = (shock_n > 0) & (non_n > 0)
    diffs_arr = shock_sum[valid] / shock_n[valid] - non_sum[valid] / non_n[valid]
    ci_low, ci_high = np.percentile(diffs_arr, [2.5, 97.5])
    p_two_sided = 2 * min(np.mean(diffs_arr <= 0), np.mean(diffs_arr >= 0))
    return {
        "ok": True,
        "n_boot": int(len(diffs_arr)),
        "observed_diff": observed,
        "ci95_low": float(ci_low),
        "ci95_high": float(ci_high),
        "p_sign_two_sided": float(min(1.0, p_two_sided)),
    }


def analyze_panel(panel: pd.DataFrame) -> dict:
    outcomes = ["fwd5_return", "log_fwd5_rv_ratio", "downside_semivar_5d_ann"]
    asset_results = {}
    for asset, asset_df in panel.groupby("asset"):
        asset_results[asset] = {}
        for outcome in outcomes:
            asset_results[asset][outcome] = {
                "ols_hac": regression_hac(asset_df, outcome),
                "year_cluster_bootstrap_diff_means": year_cluster_bootstrap(asset_df, outcome),
            }
    return asset_results


def make_figures(movies: pd.DataFrame, panel: pd.DataFrame, asset_results: dict) -> list[str]:
    paths: list[str] = []

    fig, ax = plt.subplots(figsize=(12, 5))
    plot_df = movies.loc[movies["signal_available"]].copy()
    ax.plot(plot_df["weekend_end"], plot_df["gross_z_trailing52"], color="#4263EB", linewidth=1.2)
    shock_df = plot_df.loc[plot_df["blockbuster_shock"]]
    ax.scatter(shock_df["weekend_end"], shock_df["gross_z_trailing52"], color="#E03131", s=24, label="shock")
    ax.axhline(SHOCK_Z, color="black", linewidth=0.9, linestyle="--", label=f"z >= {SHOCK_Z}")
    ax.set_title("Wikipedia U.S. weekend box-office gross shock score")
    ax.set_ylabel("log gross z-score vs trailing 52 weekends")
    ax.legend(frameon=False)
    fig.tight_layout()
    p = FIG_DIR / "fig1_box_office_shocks.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    paths.append(str(p))

    rows = []
    for asset in ["SPY", "QQQ", "IWM", "XLY", "ENTERTAINMENT_BASKET"]:
        for outcome in ["fwd5_return", "log_fwd5_rv_ratio"]:
            res = asset_results.get(asset, {}).get(outcome, {}).get("ols_hac", {})
            if res.get("ok"):
                rows.append({"asset": asset, "outcome": outcome, **res})
    coef_df = pd.DataFrame(rows)
    if not coef_df.empty:
        fig2, axes = plt.subplots(1, 2, figsize=(13, 5))
        labels = {
            "fwd5_return": "Next-5-trading-day return",
            "log_fwd5_rv_ratio": "log(next-5d RV / prior-20d RV)",
        }
        colors = {"fwd5_return": "#2F9E44", "log_fwd5_rv_ratio": "#F76707"}
        for ax2, outcome in zip(axes, ["fwd5_return", "log_fwd5_rv_ratio"], strict=True):
            sub = coef_df.loc[coef_df["outcome"] == outcome].copy()
            x = np.arange(len(sub))
            ax2.bar(x, sub["coef"], color=colors[outcome], alpha=0.82)
            err_low = sub["coef"] - sub["ci95_low"]
            err_high = sub["ci95_high"] - sub["coef"]
            ax2.errorbar(x, sub["coef"], yerr=[err_low, err_high], fmt="none", color="black", capsize=3)
            ax2.axhline(0, color="black", linewidth=0.8)
            ax2.set_xticks(x)
            ax2.set_xticklabels(sub["asset"], rotation=20, ha="right")
            ax2.set_title(labels[outcome])
            ax2.set_ylabel("shock coefficient, HAC lag-4 95% CI")
        fig2.tight_layout()
        p2 = FIG_DIR / "fig2_shock_coefficients.png"
        fig2.savefig(p2, dpi=150)
        plt.close(fig2)
        paths.append(str(p2))

    spy = panel.loc[panel["asset"] == "SPY"].copy()
    if not spy.empty:
        fig3, ax3 = plt.subplots(figsize=(7, 5))
        summary = spy.groupby("blockbuster_shock")[["fwd5_return", "log_fwd5_rv_ratio"]].mean()
        labels = ["non-shock", "shock"]
        x = np.arange(2)
        ax3.bar(x - 0.18, summary["fwd5_return"].reindex([0, 1]) * 100, width=0.36, label="return, %")
        ax3.bar(x + 0.18, summary["log_fwd5_rv_ratio"].reindex([0, 1]), width=0.36, label="log RV ratio")
        ax3.axhline(0, color="black", linewidth=0.8)
        ax3.set_xticks(x)
        ax3.set_xticklabels(labels)
        ax3.set_title("SPY raw next-week means by box-office shock")
        ax3.legend(frameon=False)
        fig3.tight_layout()
        p3 = FIG_DIR / "fig3_spy_raw_means.png"
        fig3.savefig(p3, dpi=150)
        plt.close(fig3)
        paths.append(str(p3))

    return paths


def summarize_verdict(asset_results: dict) -> dict:
    spy_return = asset_results.get("SPY", {}).get("fwd5_return", {}).get("ols_hac", {})
    spy_rv = asset_results.get("SPY", {}).get("log_fwd5_rv_ratio", {}).get("ols_hac", {})
    strong_return = spy_return.get("ok") and spy_return.get("coef", 0) > 0 and abs(spy_return.get("t_hac_lag4", 0)) >= 3
    strong_rv_down = spy_rv.get("ok") and spy_rv.get("coef", 0) < 0 and abs(spy_rv.get("t_hac_lag4", 0)) >= 3

    if strong_return and strong_rv_down:
        verdict = "PASS"
        claim = "SPY shows both positive next-week return and lower RV under the strict |t|>=3 gate."
    elif strong_return or strong_rv_down:
        verdict = "CONDITIONAL_PASS"
        claim = "Only one SPY channel clears the strict |t|>=3 gate; treat as partial evidence."
    else:
        verdict = "NULL"
        claim = "The public Wikipedia box-office proxy does not clear the strict SPY return/RV gate."

    return {
        "verdict": verdict,
        "claim": claim,
        "primary_gate": "SPY shock coefficient must have predicted sign and HAC |t| >= 3 for return and/or log RV ratio.",
        "spy_return_hac_t": spy_return.get("t_hac_lag4"),
        "spy_return_coef": spy_return.get("coef"),
        "spy_log_rv_ratio_hac_t": spy_rv.get("t_hac_lag4"),
        "spy_log_rv_ratio_coef": spy_rv.get("coef"),
    }


def main() -> None:
    run_at = datetime.now(timezone.utc).isoformat()
    movies, fetch_statuses = build_box_office_panel()

    price_start = movies["weekend_end"].min() - pd.Timedelta(days=80)
    price_end = pd.Timestamp(datetime.now(timezone.utc).date())
    close = download_prices(price_start, price_end)
    returns = make_returns(close)

    max_window_start = returns.dropna(how="all").index.max() - pd.Timedelta(days=10)
    movies = movies.loc[movies["weekend_end"] <= max_window_start].copy()
    panel = build_event_panel(movies, returns, close)

    movies.to_csv(DATA_DIR / "box_office_weekends.csv", index=False)
    close.to_csv(DATA_DIR / "yfinance_close.csv")
    panel.to_csv(DATA_DIR / "asset_event_panel.csv", index=False)

    asset_results = analyze_panel(panel)
    figure_paths = make_figures(movies, panel, asset_results)
    verdict = summarize_verdict(asset_results)

    data_quality = {
        "wiki_years_requested": [START_YEAR, END_YEAR],
        "wiki_years_ok": [s["year"] for s in fetch_statuses if s["ok"]],
        "wiki_year_failures": [s for s in fetch_statuses if not s["ok"]],
        "box_office_rows_total": int(len(movies)),
        "signal_available_rows": int(movies["signal_available"].sum()),
        "blockbuster_shock_rows": int(movies["blockbuster_shock"].sum()),
        "price_columns_available": list(close.columns),
        "event_panel_rows": int(len(panel)),
        "assets_with_rows": panel.groupby("asset").size().astype(int).to_dict(),
        "entertainment_basket_members_configured": ENTERTAINMENT_TICKERS,
        "google_trends_status": (
            "Not used. Prior project runs show pytrends is rate-limit fragile; this K keeps the "
            "reported result on reproducible Wikipedia + yfinance data and labels it a proxy diagnostic."
        ),
        "macro_calendar_control_status": (
            "Uses deterministic public-calendar proxies: first-Friday NFP, mid-month CPI window, "
            "and mid-month Wednesday FOMC-month proxy. These are controls, not exact historical releases."
        ),
    }

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Blockbuster movie / entertainment-attention shock as market mood and discretionary RV prior",
        "run_at": run_at,
        "seed": SEED,
        "verdict": verdict,
        "literature": LITERATURE,
        "hypothesis": {
            "primary": (
                "If blockbuster entertainment shocks improve broad investor mood or crowd attention away "
                "from markets, subsequent-week SPY returns may be higher and/or realized volatility lower."
            ),
            "secondary": (
                "Consumer-discretionary and entertainment-exposed assets may show larger return/RV footprint "
                "than broad market ETFs."
            ),
        },
        "data_sources": {
            "box_office": "Wikipedia annual 'List of YYYY box office number-one films in the United States' tables",
            "market_prices": "yfinance daily adjusted close via yf.download(auto_adjust=True)",
            "vix_control": "yfinance ^VIX close, lagged to last close before weekend end",
        },
        "methodology": {
            "shock_definition": (
                f"log(gross_usd) z-score relative to the prior {TRAILING_WEEKS} weekend number-one "
                f"gross observations, shifted by one weekend; shock if z >= {SHOCK_Z}; "
                f"minimum prior observations = {MIN_TRAILING_WEEKS}."
            ),
            "event_timing": (
                "Weekend end date is treated as the signal timestamp; outcomes are the next five "
                "trading days strictly after that date."
            ),
            "outcomes": [
                "fwd5_return: sum of next five daily log returns",
                "fwd5_rv_ann: annualized stdev of next five daily returns",
                "log_fwd5_rv_ratio: log(fwd5_rv_ann / prior20_rv_ann)",
                "downside_semivar_5d_ann: annualized mean squared negative returns over next five days",
            ],
            "controls": [
                "SPY prior five-day return momentum",
                "SPY prior 20-day realized volatility",
                "lagged VIX close",
                "holiday_or_closure_week",
                "first-Friday NFP proxy week",
                "mid-month CPI proxy week",
                "FOMC-month Wednesday proxy week",
                "month fixed effects",
            ],
            "inference": (
                "OLS with Newey-West/HAC lag 4 for weekly rows plus year-cluster bootstrap difference "
                f"in means ({BOOTSTRAP_REPS} reps, seed={SEED})."
            ),
            "lookahead_controls": [
                "gross_z_trailing52 uses .shift(1) trailing distribution",
                "outcomes start after weekend_end via searchsorted(..., side='right')",
                "financial controls are lagged to pre-target window",
            ],
        },
        "sample": {
            "calendar_start": str(movies["weekend_end"].min().date()),
            "calendar_end": str(movies["weekend_end"].max().date()),
            "n_weekends": int(len(movies)),
            "n_signal_available": int(movies["signal_available"].sum()),
            "n_blockbuster_shocks": int(movies["blockbuster_shock"].sum()),
            "n_assets": int(panel["asset"].nunique()),
        },
        "data_quality": data_quality,
        "asset_results": asset_results,
        "figures": figure_paths,
        "limitations": [
            "Wikipedia weekend number-one gross is an entertainment-attention proxy, not full release-level Box Office Mojo microdata.",
            "The shock uses reported weekend gross, so it is a Monday-after-weekend proxy rather than an ex-ante release-calendar-only signal.",
            "Google Trends is not used in the reported result because unofficial pytrends access is rate-limit fragile in this environment.",
            "Entertainment stock basket is current-listed/surviving and availability-weighted; it is not a point-in-time industry portfolio.",
            "Macro controls are deterministic calendar proxies, not exact historical announcement timestamps.",
            "This is an event-window diagnostic, not an OOS trading strategy or causal claim.",
        ],
    }

    out_path = HERE / f"{EXPERIMENT_ID}_results.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(json.dumps({"out": str(out_path), "verdict": verdict, "sample": results["sample"]}, indent=2))


if __name__ == "__main__":
    main()
