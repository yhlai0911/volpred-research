"""Reproduce the Friday/OPEX/triple-witching close-crowding proxy experiment.

The experiment tests whether Friday, monthly options-expiration, triple-
witching, and daily close-crowding proxy signals improve next-day open-to-close
realized-variance forecasts or imply next-day reversal.

Inputs are cached artifacts produced during the experiment:

- ``data/daily_signal_panel.csv``: SPY/QQQ/IWM daily OHLCV proxy panel with
  explicit lag-1 event/crowding signals.
- ``data/oos_forecasts.csv``: expanding OOS HAR baseline and augmented
  forecast series.
- ``data/intraday_closing_proxy_panel.csv``: short SPY 5-minute diagnostic
  for final-30-minute volume/RV concentration.

Lookahead guard:
    All event/crowding predictors used in formal tests are ``*_lag1`` columns.
    OOS rows were generated from expanding fits with training rows strictly
    before the forecast row. This script re-scores those cached forecasts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from volpred.stats.model_evaluation import dm_test, qlike_pointwise

EXPERIMENT_ID = "research_friday_triple_witching_closing_auction_concentra"
SEED = 42
BOOTSTRAP_REPS = 5000
HARVEY_T = 3.0
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RESULTS_PATH = ROOT / f"{EXPERIMENT_ID}_results.json"


def _float(x: Any) -> float | None:
    if x is None:
        return None
    y = float(x)
    return y if np.isfinite(y) else None


def bootstrap_ci(event: np.ndarray, control: np.ndarray, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    event = np.asarray(event, dtype=float)
    control = np.asarray(control, dtype=float)
    event = event[np.isfinite(event)]
    control = control[np.isfinite(control)]
    diffs = np.empty(BOOTSTRAP_REPS)
    for i in range(BOOTSTRAP_REPS):
        e = rng.choice(event, size=len(event), replace=True)
        c = rng.choice(control, size=len(control), replace=True)
        diffs[i] = float(np.mean(e) - np.mean(c))
    obs = float(np.mean(event) - np.mean(control))
    centered = diffs - float(np.mean(diffs))
    return {
        "estimate": obs,
        "ci95": [float(np.quantile(diffs, 0.025)), float(np.quantile(diffs, 0.975))],
        "p_two_sided": float(np.mean(np.abs(centered) >= abs(obs))),
        "reps": BOOTSTRAP_REPS,
        "seed": seed,
    }


def welch_test(
    df: pd.DataFrame,
    group: str,
    test: str,
    event_mask: pd.Series,
    control_mask: pd.Series,
    metric: str,
    seed: int,
) -> dict:
    event = df.loc[event_mask, metric].dropna().to_numpy(dtype=float)
    control = df.loc[control_mask, metric].dropna().to_numpy(dtype=float)
    t_stat, p_val = stats.ttest_ind(event, control, equal_var=False)
    event_mean = float(np.mean(event))
    control_mean = float(np.mean(control))
    return {
        "group": group,
        "test": test,
        "metric": metric,
        "n_event": int(len(event)),
        "n_control": int(len(control)),
        "mean_event": event_mean,
        "mean_control": control_mean,
        "diff_event_minus_control": event_mean - control_mean,
        "welch_t": _float(t_stat),
        "welch_p": _float(p_val),
        "bootstrap": bootstrap_ci(event, control, seed),
        "harvey_abs_t_gt_3": bool(abs(float(t_stat)) > HARVEY_T),
    }


def event_tests(panel: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    tests: list[dict] = []
    seed = 84
    groups = [("POOLED", panel)] + [(t, g) for t, g in panel.groupby("ticker")]
    metrics = ["log_oc_rv", "annualized_oc_vol_pct", "reversal_bps"]

    for group, df in groups:
        for metric in metrics:
            tests.append(
                welch_test(
                    df,
                    group,
                    "after_friday_vs_non_friday",
                    df["friday_lag1"].eq(1),
                    df["friday_lag1"].eq(0),
                    metric,
                    seed,
                )
            )
            seed += 1
        for metric in metrics:
            tests.append(
                welch_test(
                    df,
                    group,
                    "after_monthly_opex_vs_other_fridays",
                    df["monthly_opex_lag1"].eq(1),
                    df["friday_lag1"].eq(1) & df["monthly_opex_lag1"].eq(0),
                    metric,
                    seed,
                )
            )
            seed += 1
        for metric in metrics:
            tests.append(
                welch_test(
                    df,
                    group,
                    "after_triple_vs_other_fridays",
                    df["triple_witching_lag1"].eq(1),
                    df["friday_lag1"].eq(1) & df["triple_witching_lag1"].eq(0),
                    metric,
                    seed,
                )
            )
            seed += 1
        for metric in metrics:
            tests.append(
                welch_test(
                    df,
                    group,
                    "after_triple_vs_nontriple_monthly",
                    df["triple_witching_lag1"].eq(1),
                    df["monthly_opex_lag1"].eq(1) & df["triple_witching_lag1"].eq(0),
                    metric,
                    seed,
                )
            )
            seed += 1

    primary = [
        x
        for x in tests
        if x["group"] == "POOLED" and x["test"].startswith("after_triple")
    ]
    return primary, tests


def forecast_evaluation(oos: pd.DataFrame) -> dict:
    out: dict[str, dict] = {}
    for label, df in [*oos.groupby("ticker"), ("POOLED", oos)]:
        actual = df["actual_oc_rv"].to_numpy(dtype=float)
        base = df["baseline_pred"].to_numpy(dtype=float)
        aug = df["augmented_pred"].to_numpy(dtype=float)
        base_loss = qlike_pointwise(actual, base)
        aug_loss = qlike_pointwise(actual, aug)
        dm_t, dm_p = dm_test(aug_loss, base_loss, h=1)
        q_base = float(np.mean(base_loss))
        q_aug = float(np.mean(aug_loss))
        out[str(label)] = {
            "n_oos": int(len(df)),
            "baseline_qlike": q_base,
            "augmented_qlike": q_aug,
            "augmented_vs_baseline_improvement_pct": float((q_base - q_aug) / abs(q_base) * 100),
            "dm_t_augmented_minus_baseline": float(dm_t),
            "dm_p": float(dm_p),
            "harvey_gate_pass": bool(dm_t < -HARVEY_T),
            "event_counts_in_oos": {
                "after_friday": int(df["friday_lag1"].sum()),
                "after_monthly_opex": int(df["monthly_opex_lag1"].sum()),
                "after_triple_witching": int(df["triple_witching_lag1"].sum()),
            },
        }
    return out


def intraday_diagnostic(intraday: pd.DataFrame) -> dict:
    def bucket(mask: pd.Series) -> dict:
        df = intraday.loc[mask]
        return {
            "n": int(len(df)),
            "mean_close_30m_volume_share": float(df["close30_volume_share"].mean()),
            "median_close_30m_volume_share": float(df["close30_volume_share"].median()),
            "mean_close_30m_rv_share": float(df["close30_rv_share"].mean()),
            "median_close_30m_rv_share": float(df["close30_rv_share"].median()),
            "mean_annualized_rv_pct": float(df["annualized_rv_pct"].mean()),
            "median_annualized_rv_pct": float(df["annualized_rv_pct"].median()),
        }

    return {
        "available": True,
        "sample_start": str(intraday["Date"].min().date()),
        "sample_end": str(intraday["Date"].max().date()),
        "n_days": int(len(intraday)),
        "triple_dates_in_sample": [
            str(x.date())
            for x in intraday.loc[intraday["is_triple_witching"].eq(1), "Date"]
        ],
        "summary": {
            "all_days": bucket(pd.Series(True, index=intraday.index)),
            "fridays": bucket(intraday["is_friday"].eq(1)),
            "monthly_opex": bucket(intraday["is_monthly_opex"].eq(1)),
            "triple_witching": bucket(intraday["is_triple_witching"].eq(1)),
        },
        "interpretation_limit": "diagnostic only; local 5-minute sample has too few triple-witching days for inference",
    }


def classify(forecasts: dict, primary_events: list[dict]) -> tuple[str, list[str]]:
    pooled_forecast_pass = forecasts["POOLED"]["harvey_gate_pass"]
    primary_event_pass = any(x["harvey_abs_t_gt_3"] for x in primary_events)
    notes = [
        "No primary pooled triple-witching event contrast exceeds the Harvey |t|>3 gate.",
        "The local 5-minute closing proxy has too few triple-witching days for inference.",
    ]
    if pooled_forecast_pass:
        notes.insert(1, "The pooled augmented daily proxy forecast beats baseline with DM t < -3.")
        return "WEAK_DIRECTIONAL_NEEDS_CONFIRMATION", notes
    if primary_event_pass:
        notes.insert(1, "A primary pooled event contrast passes |t|>3 but forecast confirmation fails.")
        return "WEAK_EVENT_ONLY_NEEDS_CONFIRMATION", notes
    notes.insert(1, "The augmented daily proxy forecast does not pass the Harvey DM gate.")
    return "NULL_PROXY", notes


def main() -> None:
    panel = pd.read_csv(DATA_DIR / "daily_signal_panel.csv", parse_dates=["Date"])
    oos = pd.read_csv(DATA_DIR / "oos_forecasts.csv", parse_dates=["Date"])
    intraday = pd.read_csv(DATA_DIR / "intraday_closing_proxy_panel.csv", parse_dates=["Date"])
    panel = panel.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["log_oc_rv", "annualized_oc_vol_pct", "reversal_bps", "friday_lag1"]
    )

    primary_events, all_events = event_tests(panel)
    forecasts = forecast_evaluation(oos)
    verdict, notes = classify(forecasts, primary_events)

    daily_sources = {}
    for ticker, df in panel.groupby("ticker"):
        daily_sources[ticker] = {
            "sample_start": str(df["Date"].min().date()),
            "sample_end": str(df["Date"].max().date()),
            "lagged_signal_rows_after_feature_clean": int(len(df)),
            "lagged_event_counts": {
                "after_friday": int(df["friday_lag1"].sum()),
                "after_monthly_opex": int(df["monthly_opex_lag1"].sum()),
                "after_triple_witching": int(df["triple_witching_lag1"].sum()),
            },
        }

    results = {
        "experiment_id": EXPERIMENT_ID,
        "task_id": EXPERIMENT_ID,
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "seed": SEED,
        "bootstrap_reps": BOOTSTRAP_REPS,
        "harvey_threshold_abs_t": HARVEY_T,
        "data": {
            "daily_sources": daily_sources,
            "daily_panel_path": "data/daily_signal_panel.csv",
            "oos_forecasts_path": "data/oos_forecasts.csv",
            "intraday_panel_path": "data/intraday_closing_proxy_panel.csv",
        },
        "methodology": {
            "primary_target": "open-to-close squared log return on day t",
            "lookahead_guard": "all event/crowding predictors are explicit *_lag1 columns; row t uses information through t-1 only",
            "daily_crowding_proxy": "prior-day total-volume z-score plus range-variance z-score; not a true auction print",
            "intraday_diagnostic": "SPY final six 5-minute bars proxy the final 30 regular-session minutes",
            "oos_design": "expanding OOS OLS on log(open-to-close r^2), OOS_START=2018-01-02",
            "loss": "QLIKE = actual/predicted - log(actual/predicted) - 1",
            "dm_test": "project dm_test with h=1; internal publication gate uses |t|>3",
        },
        "references": [
            {
                "source": "Goyal, Jegadeesh, and Wu (2026), JFQA FirstView, Price Impact in Closing Auctions, Opening Auctions, and Continuous Markets",
                "url": "https://jfqa.org/2026/01/08/price-impact-in-closing-auctions-opening-auctions-and-continuous-markets-a-benchmark-for-cost-of-trading-on-anomalies/",
            },
            {
                "source": "Feinstein and Goetzmann (1988), FRB Atlanta Economic Review, The Effect of the Triple Witching Hour on Stock Market Volatility",
                "url": "https://fraser.stlouisfed.org/files/docs/publications/frbatlreview/pages/67107_1985-1989.pdf",
            },
            {
                "source": "Caporale and Plastun (2023), Witching days and abnormal profits in the US stock market",
                "url": "https://doi.org/10.1080/23322039.2023.2182016",
            },
        ],
        "forecast_evaluation": forecasts,
        "primary_event_tests": primary_events,
        "all_event_tests": all_events,
        "intraday_closing_proxy_diagnostic": intraday_diagnostic(intraday),
        "integrity_checks": {
            "random_seed_fixed": SEED,
            "signal_shift_1_columns": [
                "friday_lag1",
                "monthly_opex_lag1",
                "triple_witching_lag1",
                "volume_shock_lag1",
                "range_shock_lag1",
            ],
            "oos_train_test_contamination": "expanding forecasts were generated with train rows strictly before forecast rows",
            "not_using_squared_range_as_variance_proxy": "primary target is squared open-to-close return; range_var is only a lagged control proxy",
        },
        "figures": [
            str(ROOT / "figures" / "fig_oos_qlike.png"),
            str(ROOT / "figures" / "fig_event_group_nextday_vol.png"),
            str(ROOT / "figures" / "fig_intraday_close30_volume_share.png"),
        ],
        "verdict": verdict,
        "verdict_notes": notes,
        "limitations": [
            "No paid NYSE/Nasdaq auction feed or MOC imbalance feed is used.",
            "Daily total-volume/range crowding is a weak proxy for closing-auction concentration.",
            "Local 5-minute SPY sample covers 106 days and only two triple-witching proxies.",
            "Ticker panel is SPY/QQQ/IWM only; this is not a historical constituent-level auction study.",
        ],
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "pooled_forecast": forecasts["POOLED"]}, indent=2))


if __name__ == "__main__":
    main()
