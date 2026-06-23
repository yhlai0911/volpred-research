#!/usr/bin/env python3
"""K1540 reproducible closure for Friday/OPEX close-crowding proxy.

This script rebuilds the canonical K1540 summary from the saved research panels:

- yfinance daily adjusted OHLCV derived panel in ``data/daily_asset_panel.csv``
- date-level next-session target panel in ``data/date_panel.csv``
- expanding-OOS HAR vs auction-proxy forecasts in ``data/oos_forecasts.csv``
- local SPY 5-minute close-30 diagnostic in
  ``data/intraday_spy_close30_panel.csv``

The original backlog asked for true closing-auction concentration.  These
public-data panels cannot observe exchange auction prints or imbalance feeds, so
the verdict is intentionally limited to a daily/free-data proxy screen.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm

from volpred.stats.model_evaluation import dm_test, qlike_pointwise


HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
FIG = HERE / "figures"
FIG.mkdir(exist_ok=True)

SEED = 1540
BOOTSTRAP_REPS = 5000
HAC_LAGS = 5
HARVEY_T = 3.0

CANONICAL_RESULTS = HERE / "k1540_friday_triple_witching_closing_auction_concentration_results.json"
SHORT_RESULTS = HERE / "k1540_results.json"


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        value = float(obj)
        return None if not math.isfinite(value) else value
    if isinstance(obj, (pd.Timestamp,)):
        return obj.isoformat()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _clean(value: Any) -> float | None:
    try:
        fval = float(value)
    except (TypeError, ValueError):
        return None
    return fval if math.isfinite(fval) else None


def event_test(frame: pd.DataFrame, signal_col: str, target_col: str, rng: np.random.Generator) -> dict[str, Any]:
    data = frame[[signal_col, target_col]].dropna().copy()
    data[signal_col] = (data[signal_col] > 0).astype(float)
    event = data.loc[data[signal_col] == 1.0, target_col].to_numpy(dtype=float)
    control = data.loc[data[signal_col] == 0.0, target_col].to_numpy(dtype=float)
    diff = float(np.mean(event) - np.mean(control))
    ratio = float(np.mean(event) / np.mean(control)) if np.mean(control) != 0 else None

    x = sm.add_constant(data[[signal_col]], has_constant="add")
    model = sm.OLS(data[target_col].astype(float), x).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})

    boot = np.empty(BOOTSTRAP_REPS)
    for i in range(BOOTSTRAP_REPS):
        e = rng.choice(event, size=len(event), replace=True)
        c = rng.choice(control, size=len(control), replace=True)
        boot[i] = np.mean(e) - np.mean(c)
    ci = np.quantile(boot, [0.025, 0.975])
    if diff >= 0:
        p_boot = min(1.0, 2.0 * float(np.mean(boot <= 0.0)))
    else:
        p_boot = min(1.0, 2.0 * float(np.mean(boot >= 0.0)))

    return {
        "n_event": int(len(event)),
        "n_control": int(len(control)),
        "event_mean": _clean(np.mean(event)),
        "control_mean": _clean(np.mean(control)),
        "diff": _clean(diff),
        "ratio": _clean(ratio),
        "hac_t": _clean(model.tvalues.get(signal_col)),
        "hac_p": _clean(model.pvalues.get(signal_col)),
        "bootstrap_ci95": [_clean(ci[0]), _clean(ci[1])],
        "bootstrap_p_two_sided": _clean(p_boot),
        "harvey_significant": bool(abs(float(model.tvalues.get(signal_col, 0.0))) >= HARVEY_T),
    }


def load_panels() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    daily_asset = pd.read_csv(DATA / "daily_asset_panel.csv", parse_dates=["date"])
    date_panel = pd.read_csv(DATA / "date_panel.csv", parse_dates=["date"])
    oos = pd.read_csv(DATA / "oos_forecasts.csv", parse_dates=["date"])
    intraday = pd.read_csv(DATA / "intraday_spy_close30_panel.csv", parse_dates=["date"])
    return daily_asset, date_panel, oos, intraday


def build_event_studies(date_panel: pd.DataFrame) -> dict[str, Any]:
    rng = np.random.default_rng(SEED)
    specs = {
        "after_friday_next_day_oc_var": ("is_friday_signal", "oc_var"),
        "after_friday_reversal_return": ("is_friday_signal", "reversal_return"),
        "after_monthly_opex_next_day_oc_var": ("is_opex_signal", "oc_var"),
        "after_monthly_opex_reversal_return": ("is_opex_signal", "reversal_return"),
        "after_triple_witch_next_day_oc_var": ("is_triple_witch_signal", "oc_var"),
        "after_triple_witch_reversal_return": ("is_triple_witch_signal", "reversal_return"),
    }
    return {name: event_test(date_panel, signal, target, rng) for name, (signal, target) in specs.items()}


def build_oos(oos: pd.DataFrame) -> dict[str, Any]:
    actual = oos["actual_oc_var"].to_numpy(dtype=float)
    baseline = oos["forecast_baseline_har"].to_numpy(dtype=float)
    augmented = oos["forecast_augmented_auction_proxy"].to_numpy(dtype=float)
    base_loss = qlike_pointwise(actual, baseline)
    aug_loss = qlike_pointwise(actual, augmented)
    dm_t, dm_p = dm_test(aug_loss, base_loss, h=1)
    base_qlike = float(np.mean(base_loss))
    aug_qlike = float(np.mean(aug_loss))
    improve = (base_qlike - aug_qlike) / abs(base_qlike) * 100.0
    return {
        "n_oos": int(len(oos)),
        "first_oos": str(oos["date"].min().date()),
        "last_oos": str(oos["date"].max().date()),
        "baseline_har_qlike": _clean(base_qlike),
        "augmented_auction_proxy_qlike": _clean(aug_qlike),
        "qlike_improvement_pct": _clean(improve),
        "dm_hln_horizon": 1,
        "dm_t_augmented_minus_baseline": _clean(dm_t),
        "dm_p": _clean(dm_p),
        "harvey_significant_abs_t_gt_3": bool(abs(dm_t) >= HARVEY_T),
        "feature_sets": {
            "baseline": ["log_rv_lag1", "log_rv_lag5", "log_rv_lag22"],
            "augmented": [
                "log_rv_lag1",
                "log_rv_lag5",
                "log_rv_lag22",
                "is_friday_signal",
                "is_opex_signal",
                "is_triple_witch_signal",
                "volume_z_mean_signal",
                "range_z_mean_signal",
                "auction_crowding_raw_signal",
            ],
        },
        "qlike_direction": "actual/predicted - log(actual/predicted) - 1 via volpred.stats.model_evaluation",
        "split_rule": "expanding OOS; train rows are strictly before forecast date",
    }


def intraday_summary(intraday: pd.DataFrame) -> dict[str, Any]:
    opex = intraday[intraday["is_opex"] == 1]
    non_opex = intraday[intraday["is_opex"] == 0]
    return {
        "available": True,
        "source": "local data/intraday/SPY_5min_2026-*.csv yfinance-style snapshots",
        "n_days": int(len(intraday)),
        "first_day": str(intraday["date"].min().date()),
        "last_day": str(intraday["date"].max().date()),
        "n_opex_days": int(intraday["is_opex"].sum()),
        "n_triple_witch_days": int(intraday["is_triple_witch"].sum()),
        "median_close30_volume_share": _clean(intraday["close30_volume_share"].median()),
        "median_close30_absret_share": _clean(intraday["close30_absret_share"].median()),
        "opex_close30_volume_share_mean": _clean(opex["close30_volume_share"].mean()),
        "non_opex_close30_volume_share_mean": _clean(non_opex["close30_volume_share"].mean()),
        "opex_close30_volume_share_diff": _clean(
            opex["close30_volume_share"].mean() - non_opex["close30_volume_share"].mean()
        ),
        "interpretation_limit": "too few U.S. 5-minute days for inference; diagnostic only",
    }


def make_figures(event_study: dict[str, Any], oos: dict[str, Any]) -> list[str]:
    event_names = [
        "after_friday_next_day_oc_var",
        "after_monthly_opex_next_day_oc_var",
        "after_triple_witch_next_day_oc_var",
        "after_friday_reversal_return",
        "after_monthly_opex_reversal_return",
        "after_triple_witch_reversal_return",
    ]
    labels = ["Friday RV", "OPEX RV", "Triple RV", "Friday Rev", "OPEX Rev", "Triple Rev"]
    tvals = [event_study[name]["hac_t"] for name in event_names]
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.bar(labels, tvals, color="#4b6f8f")
    ax.axhline(HARVEY_T, color="#9b1c1c", ls="--", lw=1)
    ax.axhline(-HARVEY_T, color="#9b1c1c", ls="--", lw=1)
    ax.set_ylabel("HAC t-stat")
    ax.set_title("K1540 event-study t-stats")
    ax.tick_params(axis="x", rotation=25)
    fig.tight_layout()
    p1 = FIG / "fig_event_rv_reversal.png"
    fig.savefig(p1, dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    ax.bar(["Baseline HAR", "HAR + auction proxy"], [oos["baseline_har_qlike"], oos["augmented_auction_proxy_qlike"]], color=["#59656f", "#8f4f4f"])
    ax.set_ylabel("QLIKE, lower is better")
    ax.set_title(f"OOS QLIKE, improvement {oos['qlike_improvement_pct']:.2f}%")
    fig.tight_layout()
    p2 = FIG / "fig_oos_qlike.png"
    fig.savefig(p2, dpi=160)
    plt.close(fig)

    return [str(p1.relative_to(HERE)), str(p2.relative_to(HERE))]


def build_results() -> dict[str, Any]:
    daily_asset, date_panel, oos_panel, intraday = load_panels()
    event_study = build_event_studies(date_panel)
    oos = build_oos(oos_panel)
    intraday_diag = intraday_summary(intraday)
    figures = make_figures(event_study, oos)

    tickers = sorted(daily_asset["ticker"].dropna().unique().tolist())
    result = {
        "experiment_id": "K1540",
        "slug": "k1540_friday_triple_witching_closing_auction_concentration",
        "title": "Friday / triple-witching auction-crowding proxy for next-day RV and reversal",
        "status": "NULL_PROXY",
        "seed": SEED,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data": {
            "daily_source": "yfinance daily OHLCV, auto_adjust=True, cached in data/daily_ohlcv_auto_adjusted.csv",
            "daily_start": "2015-01-01",
            "daily_end_exclusive": "2026-06-23",
            "tickers_used": tickers,
            "n_asset_days": int(len(daily_asset)),
            "n_dates": int(date_panel["date"].nunique()),
            "first_date": str(date_panel["date"].min().date()),
            "last_date": str(date_panel["date"].max().date()),
            "event_calendar_rule": "monthly OPEX = third Friday; if not an SPY trading day, use previous SPY trading day in same month; triple-witch = Mar/Jun/Sep/Dec OPEX",
            "intraday_diagnostic": intraday_diag,
        },
        "lookahead_controls": {
            "event_flags_known_ex_ante": True,
            "daily_volume_range_proxy_available_after_close": True,
            "explicit_shift1_signal_columns": [
                "is_friday_signal",
                "is_opex_signal",
                "is_triple_witch_signal",
                "volume_z_mean_signal",
                "range_z_mean_signal",
                "auction_crowding_raw_signal",
            ],
            "oos_training_rule": "for forecast date t, regression is fit only on target rows with date < t",
        },
        "data_diagnostics": {
            "raw_fridays": int(date_panel["is_friday"].sum()),
            "raw_monthly_opex_days": int(date_panel["is_opex"].sum()),
            "raw_triple_witch_days": int(date_panel["is_triple_witch"].sum()),
            "target_days_after_friday": int((date_panel["is_friday_signal"] == 1).sum()),
            "target_days_after_monthly_opex": int((date_panel["is_opex_signal"] == 1).sum()),
            "target_days_after_triple_witch": int((date_panel["is_triple_witch_signal"] == 1).sum()),
            "mean_n_assets_per_date": _clean(date_panel["n_assets"].mean()),
        },
        "event_study_date_level": event_study,
        "oos_forecast": oos,
        "primary_verdict": {
            "claim_tested": "HAR + Friday/OPEX/triple-witch/daily crowding proxy improves next-day open-close variance forecast vs HAR baseline and/or produces next-day reversal.",
            "verdict": "FAIL_TO_SUPPORT",
            "reason": "Augmented model does not clear Harvey |t|>3 on QLIKE; event-study effects are descriptive and not robust enough for a publication claim.",
            "article_ready": False,
            "publication_guardrail": "Do not publish as a positive closing-auction signal. At most publish as free-data negative screen / data limitation note.",
        },
        "limitations": [
            "Daily OHLCV cannot observe actual closing-auction volume share or MOC imbalance.",
            "Local SPY 5-minute data covers only a short 2026 sample and is diagnostic only.",
            "Large-cap ticker list is current-name and therefore has survivorship bias.",
            "Quarterly triple-witching sample is small even over 2015-2026.",
        ],
        "references": [
            {
                "title": "Goyal, Jegadeesh, and Wu, Price Impact in Closing Auctions, Opening Auctions, and Continuous Markets",
                "source": "JFQA / Cambridge, online 2026",
                "url": "https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/price-impact-in-closing-auctions-opening-auctions-and-continuous-markets-a-benchmark-for-cost-of-trading-on-anomalies/0F72910A79C5B42CF6E85F55164CE846",
            },
            {
                "title": "Ni, Pearson, and Poteshman, Stock Price Clustering on Option Expiration Dates",
                "source": "Journal of Financial Economics, 2005",
                "url": "https://ideas.repec.org/a/eee/jfinec/v78y2005i1p49-87.html",
            },
            {
                "title": "Wu, Closing Auction, Passive Investing, and Stock Prices",
                "source": "SSRN working paper",
                "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3440239",
            },
        ],
        "artifacts": {
            "daily_cache": "data/daily_ohlcv_auto_adjusted.csv",
            "daily_asset_panel": "data/daily_asset_panel.csv",
            "date_panel": "data/date_panel.csv",
            "oos_forecasts": "data/oos_forecasts.csv",
            "intraday_panel": "data/intraday_spy_close30_panel.csv",
            "figures": figures,
        },
    }
    return result


def main() -> int:
    result = build_results()
    for path in (CANONICAL_RESULTS, SHORT_RESULTS):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False, default=_json_default)
    print(json.dumps(result["primary_verdict"], indent=2, ensure_ascii=False))
    print(f"[done] wrote {CANONICAL_RESULTS.name} and {SHORT_RESULTS.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
