"""
K1487: GDELT novel-risk intensity as a daily realized-volatility leading signal.

This is a keyword-taxonomy pilot for the "LLM novel-risk intensity" backlog item.
It deliberately does not claim to be a full LLM classifier. The goal is to test
whether a transparent GDELT DOC TimelineVol proxy for novel-risk narratives adds
out-of-sample value to log-HAR volatility forecasts.

Information set:
    feature at trading day t = GDELT and market data through t-1.
    target h=1 = r_t^2.
    target h=5 = mean(r_t^2 ... r_{t+4}^2); training excludes overlapping
    targets not fully observed before forecast origin t.

Seed: 42
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise, spearman_corr


EXPERIMENT_ID = "K1487"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
FIG_DIR = ROOT / "figures"
DATA_DIR.mkdir(exist_ok=True)
FIG_DIR.mkdir(exist_ok=True)

SEED = 42
np.random.seed(SEED)

START_DATE = "2023-01-01"
END_DATE = "2026-06-13"  # exclusive for yfinance; GDELT uses 2026-06-12 23:59:59
OOS_START = "2025-01-01"
ASSETS = ["SPY", "QQQ", "HYG", "TLT"]
MARKET_SYMBOLS = ASSETS + ["^VIX"]
HORIZONS = [1, 5]

GDELT_START = "20230101000000"
GDELT_END = "20260612235959"
GDELT_API = "https://api.gdeltproject.org/api/v2/doc/doc"

THEMES = {
    "ai_infrastructure": '"artificial intelligence" OR "generative AI" OR "AI chips" OR Nvidia OR "data center"',
    "private_credit": '"private credit" OR "direct lending" OR "shadow banking"',
    "tariff_trade": "tariff OR tariffs OR \"trade war\" OR \"import duties\"",
    "cyber": "cyberattack OR cybersecurity OR ransomware OR \"data breach\"",
    "supply_chain": '"supply chain" OR "shipping disruption" OR "port strike" OR "Red Sea"',
}
GDELT_FETCH_FAILURES: dict[str, str] = {}

REFERENCES = [
    {
        "name": "GDELT DOC 2.0 API TimelineVol",
        "url": "https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/",
        "use": "Daily volume intensity proxy for theme-specific news coverage.",
    },
    {
        "name": "Tetlock (2007), Journal of Finance",
        "url": "https://doi.org/10.1111/j.1540-6261.2007.01232.x",
        "use": "Foundational media-content and market activity link.",
    },
    {
        "name": "Baker, Bloom, Davis (2016), QJE",
        "url": "https://academic.oup.com/qje/article/131/4/1593/2468873",
        "use": "Newspaper-frequency uncertainty index precedent.",
    },
    {
        "name": "RiskLabs, arXiv:2404.07452",
        "url": "https://arxiv.org/abs/2404.07452",
        "use": "LLM-based financial risk prediction motivation.",
    },
]


def fetch_gdelt_theme(theme: str, query: str) -> pd.Series:
    """Fetch or load cached GDELT DOC TimelineVol daily volume intensity."""
    cache_path = DATA_DIR / f"gdelt_{theme}.json"
    if cache_path.exists():
        payload = json.loads(cache_path.read_text())
    else:
        gdelt_query = f"({query}) sourceCountry:US"
        params = {
            "query": gdelt_query,
            "mode": "timelinevol",
            "format": "json",
            "startdatetime": GDELT_START,
            "enddatetime": GDELT_END,
        }
        url = f"{GDELT_API}?{urllib.parse.urlencode(params)}"
        payload = None
        last_error = None
        for attempt in range(5):
            if attempt > 0:
                time.sleep(6.5 * attempt)
            try:
                with urllib.request.urlopen(url, timeout=90) as resp:
                    text = resp.read().decode("utf-8")
                if text.startswith("Please limit requests"):
                    raise RuntimeError(text)
                payload = json.loads(text)
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    raise RuntimeError(f"HTTP 429 rate limit for {theme}") from exc
                last_error = repr(exc)
            except Exception as exc:  # noqa: BLE001 - record external API failure in result.
                last_error = repr(exc)
        if payload is None:
            raise RuntimeError(f"GDELT fetch failed for {theme}: {last_error}")
        cache_path.write_text(json.dumps(payload, indent=2))
        time.sleep(6.5)

    data = payload["timeline"][0]["data"]
    dates = pd.to_datetime([row["date"] for row in data]).tz_localize(None).normalize()
    values = [float(row["value"]) for row in data]
    out = pd.Series(values, index=dates, name=theme)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def load_gdelt_panel() -> pd.DataFrame:
    series = []
    for theme, query in THEMES.items():
        try:
            series.append(fetch_gdelt_theme(theme, query))
        except Exception as exc:  # noqa: BLE001 - external API availability is part of provenance.
            GDELT_FETCH_FAILURES[theme] = repr(exc)
    if not series:
        raise RuntimeError("No GDELT theme could be fetched or loaded from cache.")
    panel = pd.concat(series, axis=1)
    panel = panel.sort_index().fillna(0.0)
    panel.to_csv(DATA_DIR / "gdelt_theme_intensity.csv", index_label="date")
    return panel


def load_market_data() -> tuple[pd.DataFrame, pd.Series]:
    raw = yf.download(
        MARKET_SYMBOLS,
        start=START_DATE,
        end=END_DATE,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].copy()
    else:
        close = raw[["Close"]].copy()
        close.columns = MARKET_SYMBOLS[:1]
    close = close.dropna(how="all")
    missing = sorted(set(MARKET_SYMBOLS) - set(close.columns))
    if missing:
        raise RuntimeError(f"Missing yfinance close columns: {missing}")
    asset_close = close[ASSETS].dropna(how="any")
    vix = close["^VIX"].reindex(asset_close.index).ffill()
    return asset_close, vix


def expanding_z_lagged(series: pd.Series, min_periods: int = 60) -> pd.Series:
    lag = series.shift(1)
    mean = lag.expanding(min_periods=min_periods).mean()
    std = lag.expanding(min_periods=min_periods).std(ddof=1)
    return ((lag - mean) / std.replace(0, np.nan)).clip(-8, 8)


def build_feature_panel(asset: str, close: pd.Series, vix: pd.Series, gdelt: pd.DataFrame) -> pd.DataFrame:
    dates = close.index.normalize()
    gdelt_aligned = gdelt.reindex(dates).fillna(0.0)
    gdelt_aligned.index = close.index

    ret = np.log(close).diff()
    r2 = ret.pow(2)
    vix_var = (vix.reindex(close.index).ffill() / 100.0).pow(2) / 252.0

    df = pd.DataFrame(index=close.index)
    df["r2"] = r2
    df["log_rv_lag1"] = np.log(r2.shift(1) + 1e-12)
    df["log_rv_week"] = np.log(r2.shift(1).rolling(5).mean() + 1e-12)
    df["log_rv_month"] = np.log(r2.shift(1).rolling(22).mean() + 1e-12)
    df["log_vix_var_lag1"] = np.log(vix_var.shift(1) + 1e-12)

    theme_z_cols = []
    for theme in gdelt_aligned.columns:
        col = f"{theme}_z_lag1"
        df[col] = expanding_z_lagged(gdelt_aligned[theme])
        theme_z_cols.append(col)
    df["novel_avg_z_lag1"] = df[theme_z_cols].mean(axis=1)
    df["novel_max_z_lag1"] = df[theme_z_cols].max(axis=1)
    df["asset"] = asset
    return df


def make_model_specs(active_themes: list[str]) -> dict[str, list[str]]:
    theme_cols = [f"{theme}_z_lag1" for theme in active_themes]
    return {
        "HAR": ["log_rv_lag1", "log_rv_week", "log_rv_month"],
        "HAR_NovelComposite": ["log_rv_lag1", "log_rv_week", "log_rv_month", "novel_avg_z_lag1"],
        "HAR_VIX": ["log_rv_lag1", "log_rv_week", "log_rv_month", "log_vix_var_lag1"],
        "HAR_VIX_NovelComposite": [
            "log_rv_lag1",
            "log_rv_week",
            "log_rv_month",
            "log_vix_var_lag1",
            "novel_avg_z_lag1",
        ],
        "HAR_VIX_NovelThemes": [
            "log_rv_lag1",
            "log_rv_week",
            "log_rv_month",
            "log_vix_var_lag1",
            *theme_cols,
        ],
    }


def forward_mean_rv(r2: pd.Series, horizon: int) -> pd.Series:
    return r2.rolling(horizon).mean().shift(-(horizon - 1))


def fit_predict_log_ols(
    y_var: pd.Series,
    x: pd.DataFrame,
    split_idx: int,
    horizon: int,
    min_train: int = 360,
) -> pd.Series:
    """Expanding-window log-variance OLS with horizon-safe train cutoff."""
    forecasts = pd.Series(np.nan, index=y_var.index, dtype=float)
    y_log = np.log(y_var + 1e-12)
    x_mat = x.astype(float)
    n = len(y_var)
    last_origin = n - horizon

    for t in range(split_idx, last_origin + 1):
        # For horizon h, origin s target is only known by t if s+h-1 <= t-1.
        train_end_exclusive = t - horizon + 1
        if train_end_exclusive <= 0:
            continue
        y_train = y_log.iloc[:train_end_exclusive]
        x_train = x_mat.iloc[:train_end_exclusive]
        train = pd.concat([y_train.rename("y"), x_train], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
        if len(train) < min_train:
            continue
        x_now = x_mat.iloc[[t]].replace([np.inf, -np.inf], np.nan)
        if x_now.isna().any(axis=None):
            continue

        design = np.column_stack([np.ones(len(train)), train[x_mat.columns].to_numpy()])
        beta, *_ = np.linalg.lstsq(design, train["y"].to_numpy(), rcond=None)
        now_design = np.r_[1.0, x_now.iloc[0].to_numpy()]
        pred_log = float(now_design @ beta)
        forecasts.iloc[t] = float(np.exp(pred_log))
    return forecasts.clip(lower=1e-12)


def evaluate_asset(asset: str, panel: pd.DataFrame, horizon: int, model_specs: dict[str, list[str]]) -> dict:
    y = forward_mean_rv(panel["r2"], horizon)
    split_idx = panel.index.get_indexer([pd.Timestamp(OOS_START)], method="bfill")[0]

    forecasts = {}
    for model, cols in model_specs.items():
        forecasts[model] = fit_predict_log_ols(y, panel[cols], split_idx, horizon)

    metrics = {}
    losses = {}
    actual = y.copy()
    oos_mask = actual.index >= pd.Timestamp(OOS_START)
    for model, fc in forecasts.items():
        valid = oos_mask & actual.notna() & fc.notna() & (actual > 0) & (fc > 0)
        a = actual[valid].to_numpy()
        f = fc[valid].to_numpy()
        rho, rho_p = spearman_corr(a, f)
        metrics[model] = {
            "n_oos": int(valid.sum()),
            "qlike": qlike(a, f),
            "mse": float(np.mean((a - f) ** 2)) if len(a) else None,
            "spearman_rho": rho,
            "spearman_p": rho_p,
        }
        losses[model] = pd.Series(qlike_pointwise(actual[valid], fc[valid]), index=actual[valid].index)

    dm_tests = {}
    comparisons = [
        ("HAR_NovelComposite", "HAR"),
        ("HAR_VIX_NovelComposite", "HAR_VIX"),
        ("HAR_VIX_NovelThemes", "HAR_VIX"),
    ]
    for challenger, baseline in comparisons:
        joined = pd.concat([losses[challenger].rename("challenger"), losses[baseline].rename("baseline")], axis=1).dropna()
        if len(joined) < 30:
            t_stat, p_val = 0.0, 1.0
        else:
            t_stat, p_val = dm_test(joined["challenger"].to_numpy(), joined["baseline"].to_numpy(), h=horizon)
        base_q = metrics[baseline]["qlike"]
        chal_q = metrics[challenger]["qlike"]
        improvement = None
        if base_q and np.isfinite(base_q):
            improvement = (base_q - chal_q) / base_q * 100.0
        dm_tests[f"{challenger}_vs_{baseline}"] = {
            "dm_t_stat": float(t_stat),
            "p_value": float(p_val),
            "harvey_abs_t_gt_3": bool(abs(t_stat) > 3.0),
            "challenger_better_by_qlike": bool(chal_q < base_q),
            "qlike_improvement_pct": None if improvement is None else float(improvement),
            "n_pairwise": int(len(joined)),
            "interpretation": "Negative t means challenger has lower QLIKE loss.",
        }

    return {
        "asset": asset,
        "horizon_days": horizon,
        "oos_period": f"{panel.index[split_idx].date()} to {panel.index[-horizon].date()}",
        "metrics": metrics,
        "dm_tests": dm_tests,
    }


def make_figures(results: dict, panels: dict[str, pd.DataFrame]) -> None:
    rows = []
    for item in results["asset_horizon_results"]:
        asset = item["asset"]
        horizon = item["horizon_days"]
        for model, vals in item["metrics"].items():
            rows.append({"asset": asset, "horizon": horizon, "model": model, "qlike": vals["qlike"]})
    qdf = pd.DataFrame(rows)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=False)
    for ax, horizon in zip(axes, HORIZONS):
        pivot = qdf[qdf["horizon"] == horizon].pivot(index="asset", columns="model", values="qlike")
        pivot = pivot[["HAR", "HAR_NovelComposite", "HAR_VIX", "HAR_VIX_NovelComposite", "HAR_VIX_NovelThemes"]]
        pivot.plot(kind="bar", ax=ax, width=0.82)
        ax.set_title(f"OOS QLIKE, h={horizon}")
        ax.set_ylabel("QLIKE")
        ax.grid(axis="y", alpha=0.3)
        ax.legend(fontsize=7)
    plt.tight_layout()
    plt.savefig(FIG_DIR / "k1487_qlike_by_asset.png", dpi=150, bbox_inches="tight")
    plt.close()

    spy_panel = panels["SPY"]
    fig, ax1 = plt.subplots(figsize=(12, 4))
    ax1.plot(spy_panel.index, spy_panel["novel_avg_z_lag1"], color="tab:purple", label="Novel-risk avg z, lag1")
    ax1.axhline(0, color="black", linewidth=0.7)
    ax1.set_ylabel("GDELT novel-risk z")
    ax1.grid(alpha=0.25)
    ax2 = ax1.twinx()
    ax2.plot(spy_panel.index, np.sqrt(spy_panel["r2"].rolling(22).mean() * 252) * 100, color="tab:gray", alpha=0.55, label="SPY 22d RV")
    ax2.set_ylabel("SPY 22d annualized RV (%)")
    ax1.set_title("Lagged GDELT novel-risk intensity vs SPY realized volatility")
    lines, labels = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines + lines2, labels + labels2, loc="upper left")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "k1487_signal_vs_spy_rv.png", dpi=150, bbox_inches="tight")
    plt.close()


def main() -> dict:
    gdelt = load_gdelt_panel()
    close, vix = load_market_data()
    active_themes = list(gdelt.columns)
    model_specs = make_model_specs(active_themes)
    panels = {asset: build_feature_panel(asset, close[asset], vix, gdelt) for asset in ASSETS}

    asset_horizon_results = []
    for asset, panel in panels.items():
        for horizon in HORIZONS:
            asset_horizon_results.append(evaluate_asset(asset, panel, horizon, model_specs))

    # Summaries across all assets/horizons.
    dm_rows = []
    for item in asset_horizon_results:
        for comparison, vals in item["dm_tests"].items():
            dm_rows.append(
                {
                    "asset": item["asset"],
                    "horizon": item["horizon_days"],
                    "comparison": comparison,
                    **vals,
                }
            )
    dm_df = pd.DataFrame(dm_rows)
    q_rows = []
    for item in asset_horizon_results:
        for model, vals in item["metrics"].items():
            q_rows.append(
                {
                    "asset": item["asset"],
                    "horizon": item["horizon_days"],
                    "model": model,
                    "qlike": vals["qlike"],
                    "n_oos": vals["n_oos"],
                }
            )
    q_df = pd.DataFrame(q_rows)
    model_summary = (
        q_df.groupby(["horizon", "model"])
        .agg(mean_qlike=("qlike", "mean"), median_qlike=("qlike", "median"), mean_n_oos=("n_oos", "mean"))
        .reset_index()
        .to_dict(orient="records")
    )

    clean_dm = dm_df.replace([np.inf, -np.inf], np.nan)
    summary = {
        "n_assets": len(ASSETS),
        "assets": ASSETS,
        "horizons": HORIZONS,
        "sample_period": f"{close.index.min().date()} to {close.index.max().date()}",
        "gdelt_period": f"{gdelt.index.min().date()} to {gdelt.index.max().date()}",
        "oos_start": OOS_START,
        "novel_composite_vs_har_wins": int(
            clean_dm[
                (clean_dm["comparison"] == "HAR_NovelComposite_vs_HAR")
                & (clean_dm["challenger_better_by_qlike"])
            ].shape[0]
        ),
        "novel_composite_vs_har_harvey_passes": int(
            clean_dm[
                (clean_dm["comparison"] == "HAR_NovelComposite_vs_HAR")
                & (clean_dm["harvey_abs_t_gt_3"])
            ].shape[0]
        ),
        "novel_composite_vs_har_significant_wins": int(
            clean_dm[
                (clean_dm["comparison"] == "HAR_NovelComposite_vs_HAR")
                & (clean_dm["harvey_abs_t_gt_3"])
                & (clean_dm["challenger_better_by_qlike"])
            ].shape[0]
        ),
        "novel_composite_vs_har_significant_losses": int(
            clean_dm[
                (clean_dm["comparison"] == "HAR_NovelComposite_vs_HAR")
                & (clean_dm["harvey_abs_t_gt_3"])
                & (~clean_dm["challenger_better_by_qlike"])
            ].shape[0]
        ),
        "novel_beyond_vix_wins": int(
            clean_dm[
                (clean_dm["comparison"].isin(["HAR_VIX_NovelComposite_vs_HAR_VIX", "HAR_VIX_NovelThemes_vs_HAR_VIX"]))
                & (clean_dm["challenger_better_by_qlike"])
            ].shape[0]
        ),
        "novel_beyond_vix_harvey_passes": int(
            clean_dm[
                (clean_dm["comparison"].isin(["HAR_VIX_NovelComposite_vs_HAR_VIX", "HAR_VIX_NovelThemes_vs_HAR_VIX"]))
                & (clean_dm["harvey_abs_t_gt_3"])
            ].shape[0]
        ),
        "novel_beyond_vix_significant_wins": int(
            clean_dm[
                (clean_dm["comparison"].isin(["HAR_VIX_NovelComposite_vs_HAR_VIX", "HAR_VIX_NovelThemes_vs_HAR_VIX"]))
                & (clean_dm["harvey_abs_t_gt_3"])
                & (clean_dm["challenger_better_by_qlike"])
            ].shape[0]
        ),
        "novel_beyond_vix_significant_losses": int(
            clean_dm[
                (clean_dm["comparison"].isin(["HAR_VIX_NovelComposite_vs_HAR_VIX", "HAR_VIX_NovelThemes_vs_HAR_VIX"]))
                & (clean_dm["harvey_abs_t_gt_3"])
                & (~clean_dm["challenger_better_by_qlike"])
            ].shape[0]
        ),
        "best_dm_abs_t": None
        if clean_dm.empty
        else float(clean_dm["dm_t_stat"].abs().max()),
        "active_gdelt_themes": active_themes,
        "unavailable_gdelt_themes": sorted(GDELT_FETCH_FAILURES),
    }

    theme_stats = {
        theme: {
            "mean_volume_intensity_pct": float(gdelt[theme].mean()),
            "std_volume_intensity_pct": float(gdelt[theme].std()),
            "max_volume_intensity_pct": float(gdelt[theme].max()),
            "max_date": str(gdelt[theme].idxmax().date()),
        }
        for theme in active_themes
    }

    output = {
        "experiment_id": EXPERIMENT_ID,
        "title": "GDELT novel-risk intensity as daily RV leading signal",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data_sources": {
            "market": "yfinance adjusted close for SPY, QQQ, HYG, TLT, ^VIX",
            "novel_risk": "GDELT DOC 2.0 TimelineVol daily volume intensity, sourceCountry:US",
            "gdelt_fetch_failures": GDELT_FETCH_FAILURES,
        },
        "method": {
            "taxonomy": THEMES,
            "active_gdelt_themes": active_themes,
            "unavailable_gdelt_themes": sorted(GDELT_FETCH_FAILURES),
            "classification": "Transparent keyword taxonomy proxy; no LLM inference was used in this pilot.",
            "target": "close-to-close squared log return; h=5 uses forward 5-trading-day mean r^2",
            "models": model_specs,
            "lookahead_control": [
                "All GDELT theme features use explicit .shift(1) via expanding_z_lagged().",
                "VIX and HAR realized-vol features use .shift(1).",
                "For h=5, expanding training excludes forecast origins whose 5-day target is not fully observed before t.",
            ],
            "evaluation": "OOS QLIKE, MSE, Spearman rank correlation, DM test with volpred.stats.model_evaluation.dm_test; Harvey |t|>3 gate.",
        },
        "references": REFERENCES,
        "theme_descriptive_stats": theme_stats,
        "model_summary": model_summary,
        "asset_horizon_results": asset_horizon_results,
        "dm_summary_rows": clean_dm.to_dict(orient="records"),
        "summary": summary,
        "conclusion": build_conclusion(summary, clean_dm),
        "limitations": [
            "Keyword taxonomy is a transparent proxy, not a validated LLM classifier.",
            "GDELT TimelineVol is normalized news-share coverage, not raw article counts or sentiment.",
            "Daily close-to-close r^2 is a noisy volatility proxy; no intraday RV is used.",
            "Sample starts in 2023 to keep live GDELT API collection tractable for this hourly run.",
        ],
        "figures": [
            "figures/k1487_qlike_by_asset.png",
            "figures/k1487_signal_vs_spy_rv.png",
        ],
    }

    make_figures(output, panels)
    (ROOT / "k1487_results.json").write_text(json.dumps(output, indent=2, default=str))
    print(json.dumps(output["summary"], indent=2))
    print(output["conclusion"])
    return output


def build_conclusion(summary: dict, dm_df: pd.DataFrame) -> str:
    beyond_vix_sig_win = summary["novel_beyond_vix_significant_wins"]
    raw_sig_win = summary["novel_composite_vs_har_significant_wins"]
    sig_losses = summary["novel_beyond_vix_significant_losses"] + summary["novel_composite_vs_har_significant_losses"]
    if beyond_vix_sig_win > 0:
        return (
            "MIXED_POSITIVE: at least one GDELT novel-risk augmentation beats HAR+VIX "
            "with Harvey |t|>3. Treat as hypothesis-generating because taxonomy is keyword-only."
        )
    if raw_sig_win > 0:
        return (
            "WEAK_POSITIVE_BEFORE_VIX: novel-risk improves plain HAR in at least one asset/horizon, "
            "but no Harvey-significant evidence remains beyond VIX."
        )
    if not dm_df.empty and int(dm_df["challenger_better_by_qlike"].sum()) > 0:
        return (
            "NULL_WITH_SMALL_WINS: some QLIKE wins appear, but none pass Harvey |t|>3. "
            "Novel-risk keyword intensity is not a reliable OOS RV leading signal in this pilot."
        )
    if sig_losses > 0:
        return (
            "NULL_NEGATIVE: no novel-risk augmentation improves OOS QLIKE; at least one comparison is "
            "Harvey-significantly worse. Daily GDELT keyword intensity should not be treated as an RV "
            "leading signal in this pilot."
        )
    return (
        "NULL: GDELT novel-risk keyword intensity does not improve OOS QLIKE versus HAR or HAR+VIX "
        "under the pre-registered lagged information set."
    )


if __name__ == "__main__":
    main()
