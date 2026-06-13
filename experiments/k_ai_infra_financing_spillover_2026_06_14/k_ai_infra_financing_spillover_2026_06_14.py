from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from scipy import stats

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


EXPERIMENT_ID = "k_ai_infra_financing_spillover_2026_06_14"
OUTPUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = OUTPUT_DIR / f"{EXPERIMENT_ID}_results.json"
FIG_EVENT_PATH = OUTPUT_DIR / "fig_event_window_ratios.png"
FIG_OOS_PATH = OUTPUT_DIR / "fig_oos_qlike.png"

START_DATE = "2015-01-01"
CAP_DATE = "2026-06-13"
TICKERS = ["QQQ", "XLU", "PAVE", "HYG", "LQD", "MSFT", "NVDA", "SMH"]
AI_MEMBERS = ["MSFT", "NVDA", "SMH"]
INFRA_MEMBERS = ["XLU", "PAVE"]
CREDIT_MEMBERS = ["HYG", "LQD"]
ROLLING_SPLIT = 0.75
MIN_TRAIN_OBS = 756
HORIZONS = [0, 1, 2, 5]


@dataclass
class EventResult:
    horizon_days: int
    event_mean: float
    normal_mean: float
    ratio: float
    t_stat: float
    p_value: float


def fetch_close_panel() -> pd.DataFrame:
    data = yf.download(
        TICKERS,
        start=START_DATE,
        end=CAP_DATE,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=False,
    )
    close = pd.DataFrame({ticker: data[ticker]["Close"] for ticker in TICKERS})
    close = close.dropna().sort_index()
    close.index = pd.to_datetime(close.index)
    return close


def build_dataset(close: pd.DataFrame) -> pd.DataFrame:
    ret = np.log(close).diff().dropna()
    df = pd.DataFrame(index=ret.index)
    df["ai_ret"] = ret[AI_MEMBERS].mean(axis=1)
    df["infra_ret"] = ret[INFRA_MEMBERS].mean(axis=1)
    df["credit_ret"] = ret[CREDIT_MEMBERS].mean(axis=1)
    df["qqq_ret"] = ret["QQQ"]

    for name in ["ai", "infra", "credit", "qqq"]:
        rv = df[f"{name}_ret"] ** 2
        df[f"{name}_rv"] = rv
        df[f"log_{name}_rv"] = np.log(rv.clip(lower=1e-12))
        df[f"log_{name}_rv_lag1"] = df[f"log_{name}_rv"].shift(1)
        df[f"log_{name}_rv_lag5"] = np.log(rv.rolling(5).mean().shift(1).clip(lower=1e-12))
        df[f"log_{name}_rv_lag22"] = np.log(rv.rolling(22).mean().shift(1).clip(lower=1e-12))

    threshold = df["ai_ret"].rolling(252).quantile(0.95).shift(1)
    df["ai_positive_shock"] = df["ai_ret"] > threshold
    df["ai_positive_shock_int"] = df["ai_positive_shock"].astype(int)
    df["target_log_qqq_rv_t1"] = df["log_qqq_rv"].shift(-1)
    return df


def event_study(df: pd.DataFrame) -> dict[str, list[EventResult]]:
    out: dict[str, list[EventResult]] = {}
    shock_mask = df["ai_positive_shock"].fillna(False)
    for target in ["infra_rv", "credit_rv", "qqq_rv"]:
        results: list[EventResult] = []
        for horizon in HORIZONS:
            shifted = df[target].shift(-horizon)
            event_vals = shifted[shock_mask].dropna()
            normal_vals = shifted[~shock_mask].dropna()
            t_stat, p_val = stats.ttest_ind(event_vals, normal_vals, equal_var=False)
            results.append(
                EventResult(
                    horizon_days=horizon,
                    event_mean=float(event_vals.mean()),
                    normal_mean=float(normal_vals.mean()),
                    ratio=float(event_vals.mean() / normal_vals.mean()),
                    t_stat=float(t_stat),
                    p_value=float(p_val),
                )
            )
        out[target] = results
    return out


def fit_hac_regressions(df: pd.DataFrame) -> dict:
    reg = df[
        [
            "target_log_qqq_rv_t1",
            "log_qqq_rv_lag1",
            "log_qqq_rv_lag5",
            "log_qqq_rv_lag22",
            "log_infra_rv_lag1",
            "log_credit_rv_lag1",
            "ai_positive_shock_int",
        ]
    ].dropna()
    y = reg["target_log_qqq_rv_t1"]

    x_base = sm.add_constant(reg[["log_qqq_rv_lag1", "log_qqq_rv_lag5", "log_qqq_rv_lag22"]])
    x_aug = sm.add_constant(
        reg[
            [
                "log_qqq_rv_lag1",
                "log_qqq_rv_lag5",
                "log_qqq_rv_lag22",
                "log_infra_rv_lag1",
                "log_credit_rv_lag1",
                "ai_positive_shock_int",
            ]
        ]
    )

    base = sm.OLS(y, x_base).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
    aug = sm.OLS(y, x_aug).fit(cov_type="HAC", cov_kwds={"maxlags": 5})

    return {
        "n_obs": int(len(reg)),
        "baseline_r2": float(base.rsquared),
        "augmented_r2": float(aug.rsquared),
        "delta_r2": float(aug.rsquared - base.rsquared),
        "augmented_params": {
            col: {
                "coef": float(aug.params[col]),
                "std_err": float(aug.bse[col]),
                "z_stat": float(aug.tvalues[col]),
                "p_value": float(aug.pvalues[col]),
            }
            for col in aug.params.index
        },
    }


def rolling_oos(df: pd.DataFrame) -> dict:
    model_features = {
        "har": ["log_qqq_rv_lag1", "log_qqq_rv_lag5", "log_qqq_rv_lag22"],
        "har_ai": ["log_qqq_rv_lag1", "log_qqq_rv_lag5", "log_qqq_rv_lag22", "log_ai_rv_lag1"],
        "har_infra": [
            "log_qqq_rv_lag1",
            "log_qqq_rv_lag5",
            "log_qqq_rv_lag22",
            "log_infra_rv_lag1",
        ],
        "har_credit": [
            "log_qqq_rv_lag1",
            "log_qqq_rv_lag5",
            "log_qqq_rv_lag22",
            "log_credit_rv_lag1",
        ],
        "har_all": [
            "log_qqq_rv_lag1",
            "log_qqq_rv_lag5",
            "log_qqq_rv_lag22",
            "log_ai_rv_lag1",
            "log_infra_rv_lag1",
            "log_credit_rv_lag1",
        ],
    }
    reg = df[
        [
            "target_log_qqq_rv_t1",
            "log_qqq_rv_lag1",
            "log_qqq_rv_lag5",
            "log_qqq_rv_lag22",
            "log_ai_rv_lag1",
            "log_infra_rv_lag1",
            "log_credit_rv_lag1",
            "ai_positive_shock_int",
        ]
    ].dropna()
    split = int(len(reg) * ROLLING_SPLIT)
    actual: list[float] = []
    forecasts = {name: [] for name in model_features}

    for i in range(split, len(reg)):
        train = reg.iloc[:i]
        if len(train) < MIN_TRAIN_OBS:
            continue
        test = reg.iloc[i : i + 1]
        y_train = train["target_log_qqq_rv_t1"].to_numpy()
        actual.append(float(np.exp(test["target_log_qqq_rv_t1"].iloc[0])))
        for name, features in model_features.items():
            x_train = np.column_stack([np.ones(len(train))] + [train[f].to_numpy() for f in features])
            beta = np.linalg.lstsq(x_train, y_train, rcond=None)[0]
            x_test = np.array([1.0] + [float(test[f].iloc[0]) for f in features])
            forecasts[name].append(float(np.exp(x_test @ beta)))

    actual_arr = np.array(actual)
    qlike_scores = {name: float(qlike(actual_arr, np.array(preds))) for name, preds in forecasts.items()}
    base_loss = qlike_pointwise(actual_arr, np.array(forecasts["har"]))
    dm_vs_har = {}
    for name, preds in forecasts.items():
        if name == "har":
            continue
        loss = qlike_pointwise(actual_arr, np.array(preds))
        t_stat, p_val = dm_test(loss, base_loss)
        dm_vs_har[name] = {"t_stat": float(t_stat), "p_value": float(p_val)}

    return {
        "n_oos": int(len(actual_arr)),
        "qlike": qlike_scores,
        "dm_vs_har": dm_vs_har,
    }


def make_figures(event_results: dict[str, list[EventResult]], oos_results: dict) -> None:
    labels = ["Infra", "Credit", "QQQ"]
    keys = ["infra_rv", "credit_rv", "qqq_rv"]
    x = np.arange(len(HORIZONS))
    width = 0.22

    fig, ax = plt.subplots(figsize=(9, 5))
    for i, key in enumerate(keys):
        ratios = [item.ratio for item in event_results[key]]
        ax.bar(x + (i - 1) * width, ratios, width=width, label=labels[i])
    ax.axhline(1.0, color="black", linewidth=1, linestyle="--")
    ax.set_xticks(x, [f"t+{h}" if h else "t" for h in HORIZONS])
    ax.set_ylabel("Shock / Normal RV Ratio")
    ax.set_title("AI Positive Shock Event Windows")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIG_EVENT_PATH, dpi=180)
    plt.close(fig)

    names = list(oos_results["qlike"].keys())
    values = [oos_results["qlike"][name] for name in names]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(names, values, color=["#1f77b4", "#8c564b", "#2ca02c", "#ff7f0e", "#9467bd"])
    ax.set_ylabel("QLIKE")
    ax.set_title("OOS QLIKE by Model (Lower Is Better)")
    fig.tight_layout()
    fig.savefig(FIG_OOS_PATH, dpi=180)
    plt.close(fig)


def build_results(close: pd.DataFrame, df: pd.DataFrame) -> dict:
    event_results = event_study(df)
    regression_results = fit_hac_regressions(df)
    oos_results = rolling_oos(df)
    make_figures(event_results, oos_results)

    verdict = (
        "NULL_FOR_LEAD_LAG_TRANSMISSION"
        if min(oos_results["qlike"], key=oos_results["qlike"].get) == "har"
        else "MIXED"
    )

    return {
        "experiment_id": EXPERIMENT_ID,
        "title": "AI infrastructure financing spillover pilot",
        "status": verdict,
        "data_source": "yfinance adjusted close",
        "sample_start": close.index.min().strftime("%Y-%m-%d"),
        "sample_end": close.index.max().strftime("%Y-%m-%d"),
        "n_price_obs": int(len(close)),
        "shock_days": int(df["ai_positive_shock"].sum()),
        "shock_definition": (
            "AI basket same-day return above its own lagged 252-day 95th percentile; "
            "descriptive event label, not a tradable same-day signal."
        ),
        "baskets": {
            "ai": AI_MEMBERS,
            "infra": INFRA_MEMBERS,
            "credit": CREDIT_MEMBERS,
            "nasdaq_target": ["QQQ"],
        },
        "event_study": {
            key: [asdict(item) for item in items]
            for key, items in event_results.items()
        },
        "harx_regression": regression_results,
        "oos_model_comparison": oos_results,
        "summary": {
            "same_day_ratio_infra": event_results["infra_rv"][0].ratio,
            "same_day_ratio_credit": event_results["credit_rv"][0].ratio,
            "same_day_ratio_qqq": event_results["qqq_rv"][0].ratio,
            "t_plus_1_ratio_infra": event_results["infra_rv"][1].ratio,
            "t_plus_1_ratio_credit": event_results["credit_rv"][1].ratio,
            "t_plus_1_ratio_qqq": event_results["qqq_rv"][1].ratio,
            "baseline_qlike": oos_results["qlike"]["har"],
            "best_model": min(oos_results["qlike"], key=oos_results["qlike"].get),
            "best_model_qlike": min(oos_results["qlike"].values()),
            "delta_r2_harx": regression_results["delta_r2"],
        },
        "research_honesty_notes": [
            "This is a public-market proxy for AI infrastructure financing stress, not direct private-credit or project-finance exposure.",
            "AI positive shocks are defined from same-day basket returns, so same-day event-window evidence is descriptive rather than ex-ante tradable.",
            "Daily close-to-close squared returns are a noisy RV proxy; no intraday or options data are used.",
        ],
        "artifacts": {
            "event_figure": str(FIG_EVENT_PATH.name),
            "oos_figure": str(FIG_OOS_PATH.name),
        },
    }


def main() -> None:
    close = fetch_close_panel()
    df = build_dataset(close)
    results = build_results(close, df)
    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
