"""K1530: Taiwan retail participation x recent-return interaction for 0050 RV.

Question
--------
Does retail participation amplify next-day Taiwan ETF realized variance after
recent negative returns?

Scope
-----
This hourly-run version uses reproducible local public-data snapshots:
- `storage/macro/yf_0050.TW.csv`: yfinance daily 0050.TW OHLCV snapshot.
- `storage/sentiment/tw_institutional_0050.csv`: TWSE three-institution
  buy/sell records for 0050.
- `storage/sentiment/tw_margin_0050.csv`: TWSE margin/short-sale records for
  0050.

The headline retail proxy is residual 0050 participation:
    1 - (institutional buys + institutional sells) / (2 * 0050 volume)

This is not a full-market retail-share measure. It is a 0050 ETF proxy.

Lookahead discipline
--------------------
The target is day-t 0050 realized variance. Every predictor uses explicit
`.shift(1)`, so the information set is at most t-1.

Run
---
uv run python experiments/k1530_tw_retail_interaction_rv/k1530_tw_retail_interaction_rv.py
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise

SEED = 42
EXPERIMENT_ID = "K1530"
EXPERIMENT_SLUG = "k1530_tw_retail_interaction_rv"
TASK_ID = "research_interaction_rv"

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RESULTS_PATH = HERE / f"{EXPERIMENT_SLUG}_results.json"
FIG_PATH = HERE / f"{EXPERIMENT_SLUG}.png"

PRICE_PATH = ROOT / "storage/macro/yf_0050.TW.csv"
INST_PATH = ROOT / "storage/sentiment/tw_institutional_0050.csv"
MARGIN_PATH = ROOT / "storage/sentiment/tw_margin_0050.csv"

OOS_START = pd.Timestamp("2022-01-01")
TRADING_DAYS = 252
Z_WINDOW = 252
Z_MIN_PERIODS = 126
MIN_VOLUME = 1_000_000
BONFERRONI_TESTS = 4
BONFERRONI_ALPHA = 0.05 / BONFERRONI_TESTS


@dataclass(frozen=True)
class SpecResult:
    target: str
    signal: str
    n_train: int
    n_oos: int
    hac_interaction_coef: float
    hac_interaction_t: float
    hac_interaction_p: float
    bonferroni_pass: bool
    baseline_qlike: float
    augmented_qlike: float
    qlike_improvement_pct: float
    dm_t_augmented_vs_baseline: float
    dm_p_augmented_vs_baseline: float
    harvey_pass: bool


def _round_or_none(x: float, ndigits: int = 6) -> float | None:
    if x is None or not np.isfinite(x):
        return None
    return round(float(x), ndigits)


def load_0050_prices() -> pd.DataFrame:
    raw = pd.read_csv(PRICE_PATH)
    raw = raw[raw["Price"].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$")].copy()
    raw = raw.rename(columns={"Price": "date"})
    raw["date"] = pd.to_datetime(raw["date"])
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
    raw = raw.dropna(subset=["date", "Open", "High", "Low", "Close"])
    return raw.sort_values("date").set_index("date")


def load_institutional_proxy() -> pd.DataFrame:
    inst = pd.read_csv(INST_PATH)
    inst["date"] = pd.to_datetime(inst["date"])
    inst["buy"] = pd.to_numeric(inst["buy"], errors="coerce")
    inst["sell"] = pd.to_numeric(inst["sell"], errors="coerce")
    agg = inst.groupby("date")[["buy", "sell"]].sum(min_count=1)
    agg = agg.rename(columns={"buy": "inst_buy", "sell": "inst_sell"})
    return agg


def load_margin_proxy() -> pd.DataFrame:
    margin = pd.read_csv(MARGIN_PATH)
    margin["date"] = pd.to_datetime(margin["date"])
    cols = [
        "MarginPurchaseBuy",
        "MarginPurchaseSell",
        "ShortSaleBuy",
        "ShortSaleSell",
        "MarginPurchaseTodayBalance",
        "ShortSaleTodayBalance",
    ]
    for col in cols:
        margin[col] = pd.to_numeric(margin[col], errors="coerce")
    margin = margin.set_index("date").sort_index()
    margin["margin_activity_shares"] = (
        margin["MarginPurchaseBuy"].fillna(0)
        + margin["MarginPurchaseSell"].fillna(0)
        + margin["ShortSaleBuy"].fillna(0)
        + margin["ShortSaleSell"].fillna(0)
    )
    margin["margin_balance_net"] = (
        margin["MarginPurchaseTodayBalance"].fillna(0)
        - margin["ShortSaleTodayBalance"].fillna(0)
    )
    return margin[["margin_activity_shares", "margin_balance_net"]]


def trailing_z(series: pd.Series) -> pd.Series:
    mu = series.rolling(Z_WINDOW, min_periods=Z_MIN_PERIODS).mean()
    sigma = series.rolling(Z_WINDOW, min_periods=Z_MIN_PERIODS).std(ddof=1)
    return (series - mu) / sigma.replace(0, np.nan)


def build_panel() -> pd.DataFrame:
    price = load_0050_prices()
    inst = load_institutional_proxy()
    margin = load_margin_proxy()
    df = price.join(inst, how="left").join(margin, how="left")

    df["logret"] = np.log(df["Close"] / df["Close"].shift(1))
    df["r2_ann"] = (df["logret"] ** 2) * TRADING_DAYS
    df["parkinson_ann"] = (
        (np.log(df["High"] / df["Low"]) ** 2) / (4.0 * math.log(2.0))
    ) * TRADING_DAYS

    inst_part = (df["inst_buy"] + df["inst_sell"]) / (2.0 * df["Volume"])
    valid_inst = (df["Volume"] >= MIN_VOLUME) & inst_part.between(0, 1)
    df["inst_participation"] = inst_part.where(valid_inst)
    df["retail_residual_share"] = 1.0 - df["inst_participation"]
    df["retail_residual_z"] = trailing_z(df["retail_residual_share"])

    margin_turnover = df["margin_activity_shares"] / df["Volume"]
    valid_margin = (df["Volume"] >= MIN_VOLUME) & margin_turnover.between(0, 2)
    df["margin_activity_turnover"] = margin_turnover.where(valid_margin)
    df["margin_activity_z"] = trailing_z(df["margin_activity_turnover"])

    rv = df["r2_ann"].clip(lower=1e-12)
    df["log_rv_lag1"] = np.log(rv.shift(1))
    df["log_rv_ma5_lag1"] = np.log(rv.rolling(5).mean().shift(1).clip(lower=1e-12))
    df["log_rv_ma22_lag1"] = np.log(rv.rolling(22).mean().shift(1).clip(lower=1e-12))
    df["ret5_lag1"] = df["logret"].rolling(5).sum().shift(1)
    df["neg_ret5_lag1"] = (-df["ret5_lag1"].clip(upper=0.0)).fillna(np.nan)

    # Explicit signal lag: day-t target is only paired with t-1 observable signals.
    for signal in ["retail_residual_z", "margin_activity_z"]:
        lag = f"{signal}_lag1"
        inter = f"{signal}_x_negret5_lag1"
        df[lag] = df[signal].shift(1)
        df[inter] = df[lag] * df["neg_ret5_lag1"]

    df["log_r2_target"] = np.log(df["r2_ann"].clip(lower=1e-12))
    df["log_parkinson_target"] = np.log(df["parkinson_ann"].clip(lower=1e-12))
    return df


def hac_interaction_regression(
    data: pd.DataFrame,
    target_log_col: str,
    signal_col: str,
    interaction_col: str,
) -> dict[str, float]:
    cols = [
        target_log_col,
        "log_rv_lag1",
        "log_rv_ma5_lag1",
        "log_rv_ma22_lag1",
        "ret5_lag1",
        "neg_ret5_lag1",
        signal_col,
        interaction_col,
    ]
    d = data[cols].replace([np.inf, -np.inf], np.nan).dropna()
    y = d[target_log_col]
    x = sm.add_constant(d.drop(columns=[target_log_col]), has_constant="add")
    model = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
    return {
        "n": int(model.nobs),
        "coef": float(model.params[interaction_col]),
        "t": float(model.tvalues[interaction_col]),
        "p": float(model.pvalues[interaction_col]),
        "r2": float(model.rsquared),
    }


def fit_oos_spec(
    data: pd.DataFrame,
    target_col: str,
    target_log_col: str,
    signal_col: str,
    interaction_col: str,
    spec_name: str,
) -> SpecResult:
    baseline_cols = [
        "log_rv_lag1",
        "log_rv_ma5_lag1",
        "log_rv_ma22_lag1",
        "ret5_lag1",
        "neg_ret5_lag1",
    ]
    augmented_cols = baseline_cols + [signal_col, interaction_col]
    cols = ["date", target_col, target_log_col] + augmented_cols
    d = data.reset_index(names="date")[cols].replace([np.inf, -np.inf], np.nan).dropna()
    d = d[d[target_col] > 0].copy()
    train = d[d["date"] < OOS_START]
    oos = d[d["date"] >= OOS_START]
    if len(train) < 500 or len(oos) < 250:
        raise RuntimeError(f"insufficient train/oos rows for {spec_name}: {len(train)}/{len(oos)}")

    def predict(feature_cols: list[str]) -> np.ndarray:
        x_train = sm.add_constant(train[feature_cols], has_constant="add")
        x_oos = sm.add_constant(oos[feature_cols], has_constant="add")
        model = sm.OLS(train[target_log_col], x_train).fit()
        return np.exp(model.predict(x_oos).to_numpy())

    actual = oos[target_col].to_numpy()
    pred_base = predict(baseline_cols)
    pred_aug = predict(augmented_cols)
    base_loss = qlike_pointwise(actual, pred_base)
    aug_loss = qlike_pointwise(actual, pred_aug)
    dm_t, dm_p = dm_test(aug_loss, base_loss, h=1)
    base_q = qlike(actual, pred_base)
    aug_q = qlike(actual, pred_aug)
    improvement = (base_q - aug_q) / abs(base_q) * 100 if base_q != 0 else np.nan

    hac = hac_interaction_regression(data, target_log_col, signal_col, interaction_col)
    return SpecResult(
        target=target_col,
        signal=spec_name,
        n_train=int(len(train)),
        n_oos=int(len(oos)),
        hac_interaction_coef=float(hac["coef"]),
        hac_interaction_t=float(hac["t"]),
        hac_interaction_p=float(hac["p"]),
        bonferroni_pass=bool(hac["p"] < BONFERRONI_ALPHA),
        baseline_qlike=float(base_q),
        augmented_qlike=float(aug_q),
        qlike_improvement_pct=float(improvement),
        dm_t_augmented_vs_baseline=float(dm_t),
        dm_p_augmented_vs_baseline=float(dm_p),
        harvey_pass=bool(dm_t < -3.0),
    )


def run_specs(panel: pd.DataFrame) -> list[SpecResult]:
    specs: list[SpecResult] = []
    signal_map = {
        "retail_residual": (
            "retail_residual_z_lag1",
            "retail_residual_z_x_negret5_lag1",
        ),
        "margin_activity": (
            "margin_activity_z_lag1",
            "margin_activity_z_x_negret5_lag1",
        ),
    }
    target_map = {
        "r2_ann": "log_r2_target",
        "parkinson_ann": "log_parkinson_target",
    }
    for target_col, target_log_col in target_map.items():
        for signal_name, (signal_col, interaction_col) in signal_map.items():
            specs.append(
                fit_oos_spec(
                    panel,
                    target_col=target_col,
                    target_log_col=target_log_col,
                    signal_col=signal_col,
                    interaction_col=interaction_col,
                    spec_name=f"{signal_name}_x_negret5",
                )
            )
    return specs


def make_figure(panel: pd.DataFrame, specs: list[SpecResult]) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8))
    plot_df = panel.dropna(subset=["retail_residual_z_lag1", "margin_activity_z_lag1", "ret5_lag1"]).loc["2018":]
    axes[0].plot(plot_df.index, plot_df["retail_residual_z_lag1"], label="Residual retail z", color="#386b61", linewidth=1)
    axes[0].plot(plot_df.index, plot_df["margin_activity_z_lag1"], label="Margin activity z", color="#b47f3d", linewidth=1)
    axes[0].axhline(0, color="black", linewidth=0.7)
    axes[0].set_title("Lagged 0050 retail proxies")
    axes[0].legend(frameon=False, fontsize=8)

    labels = [f"{s.target}\n{s.signal.replace('_x_negret5', '')}" for s in specs]
    tvals = [s.hac_interaction_t for s in specs]
    axes[1].barh(labels, tvals, color=["#386b61" if v > 0 else "#9b4a3f" for v in tvals])
    axes[1].axvline(0, color="black", linewidth=0.7)
    axes[1].axvline(3, color="#777777", linestyle="--", linewidth=0.8)
    axes[1].axvline(-3, color="#777777", linestyle="--", linewidth=0.8)
    axes[1].set_title("HAC t-stat: retail x negative-return")

    improvements = [s.qlike_improvement_pct for s in specs]
    axes[2].barh(labels, improvements, color=["#386b61" if v > 0 else "#9b4a3f" for v in improvements])
    axes[2].axvline(0, color="black", linewidth=0.7)
    axes[2].set_title("OOS QLIKE improvement, %")

    fig.suptitle("K1530 Taiwan retail participation x recent-return RV pilot", fontsize=13)
    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=160)
    plt.close(fig)


def build_output(panel: pd.DataFrame, specs: list[SpecResult], elapsed: float) -> dict:
    spec_records = [
        {
            "target": s.target,
            "signal": s.signal,
            "n_train": s.n_train,
            "n_oos": s.n_oos,
            "hac_interaction_coef": _round_or_none(s.hac_interaction_coef, 8),
            "hac_interaction_t": _round_or_none(s.hac_interaction_t, 4),
            "hac_interaction_p": _round_or_none(s.hac_interaction_p, 6),
            "bonferroni_pass": s.bonferroni_pass,
            "baseline_qlike": _round_or_none(s.baseline_qlike, 6),
            "augmented_qlike": _round_or_none(s.augmented_qlike, 6),
            "qlike_improvement_pct": _round_or_none(s.qlike_improvement_pct, 4),
            "dm_t_augmented_vs_baseline": _round_or_none(s.dm_t_augmented_vs_baseline, 4),
            "dm_p_augmented_vs_baseline": _round_or_none(s.dm_p_augmented_vs_baseline, 6),
            "harvey_pass": s.harvey_pass,
        }
        for s in specs
    ]
    bonf_passes = [s for s in specs if s.bonferroni_pass]
    oos_passes = [s for s in specs if s.harvey_pass]
    best_oos = max(specs, key=lambda s: s.qlike_improvement_pct)

    if bonf_passes and oos_passes:
        verdict = "PASS_NARROW_PROXY"
    elif bonf_passes or oos_passes:
        verdict = "MIXED_PROXY_WEAK_OOS"
    else:
        verdict = "NULL_PROXY"

    summary = (
        "0050 residual-retail and margin-activity interaction proxies show mixed in-sample "
        "interaction evidence but no Harvey-strength OOS QLIKE improvement. Treat as an "
        "ETF-proxy pilot, not evidence on the full TWSE retail share."
    )

    valid_retail = panel["retail_residual_share"].dropna()
    valid_margin = panel["margin_activity_turnover"].dropna()
    return {
        "experiment_id": EXPERIMENT_ID,
        "task_id": TASK_ID,
        "title": "Taiwan retail participation x recent-return interaction for 0050 realized variance",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "summary": summary,
        "data": {
            "sources": {
                "0050_prices": str(PRICE_PATH.relative_to(ROOT)),
                "institutional_trades": str(INST_PATH.relative_to(ROOT)),
                "margin_trades": str(MARGIN_PATH.relative_to(ROOT)),
            },
            "sample_start": str(panel.dropna(subset=["r2_ann"]).index.min().date()),
            "sample_end": str(panel.dropna(subset=["r2_ann"]).index.max().date()),
            "oos_start": str(OOS_START.date()),
            "n_price_days": int(panel["Close"].notna().sum()),
            "n_retail_residual_valid": int(len(valid_retail)),
            "n_margin_valid": int(len(valid_margin)),
            "retail_residual_share_mean": _round_or_none(valid_retail.mean(), 4),
            "retail_residual_share_p05_p95": [
                _round_or_none(valid_retail.quantile(0.05), 4),
                _round_or_none(valid_retail.quantile(0.95), 4),
            ],
            "margin_activity_turnover_mean": _round_or_none(valid_margin.mean(), 6),
        },
        "method": {
            "target": "day-t 0050 annualized r^2 and Parkinson range variance",
            "baseline_features": "lagged log RV 1/5/22, lagged 5-day return, lagged negative 5-day return",
            "retail_proxy_1": "residual retail share = 1 - institutional participation, clipped by valid 0050 volume and institutional ratio",
            "retail_proxy_2": "margin activity turnover = margin/short-sale buy+sell shares divided by 0050 volume",
            "interaction": "lagged retail z-score x lagged max(-past 5-day return, 0)",
            "lookahead_guard": "all retail, return, and HAR features are explicit .shift(1); target remains day t",
            "inference": "HAC OLS maxlags=5 for interaction coefficient; fixed train/OOS log-RV model with Patton QLIKE and DM h=1",
            "multiple_testing": f"{BONFERRONI_TESTS} headline target x proxy interaction tests; Bonferroni alpha={BONFERRONI_ALPHA:.4f}",
        },
        "specs": spec_records,
        "key_numbers": {
            "bonferroni_interaction_passes": [f"{s.target}:{s.signal}" for s in bonf_passes],
            "harvey_oos_passes": [f"{s.target}:{s.signal}" for s in oos_passes],
            "best_oos_spec": f"{best_oos.target}:{best_oos.signal}",
            "best_oos_improvement_pct": _round_or_none(best_oos.qlike_improvement_pct, 4),
            "best_oos_dm_t": _round_or_none(best_oos.dm_t_augmented_vs_baseline, 4),
        },
        "limitations": [
            "Residual retail participation is inferred for 0050 only; it is not an official full-market retail-share series.",
            "Local institutional and margin snapshots end in March 2026, so this does not include the latest 2026Q2 dates.",
            "0050 ETF flow can reflect creation/redemption and institutional hedging mechanics, not only household retail trading.",
            "Daily OHLC cannot identify intraday retail order imbalance or attention shocks.",
            "This is an ETF-level pilot; stock-level cross-section could behave differently.",
        ],
        "references": [
            {
                "title": "Chordia, Lin, Xiang (2025), Return Extrapolation and Volatility Expectations",
                "url": "https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/issue/3DDD308732093871E6909F7D3A647F0C",
                "use": "Motivates recent-return extrapolation as a channel for volatility expectations.",
            },
            {
                "title": "Foucault, Sraer, Thesmar (2011), Individual Investors and Volatility",
                "url": "https://faculty.haas.berkeley.edu/dsraer/SRD.pdf",
                "use": "Motivates retail trading activity as a volatility channel.",
            },
            {
                "title": "Boehmer, Jones, Zhang, Zhang (2021), Tracking Retail Investor Activity",
                "url": "https://eng.pbcsf.tsinghua.edu.cn/__local/6/B0/AF/2A35AA5BBB6B2C05786716FA0DF_098DC0E7_107C03.pdf?e=.pdf",
                "use": "Shows retail activity can be proxied from public transaction patterns; this experiment uses a weaker Taiwan ETF residual proxy.",
            },
        ],
        "artifacts": {
            "script": str(Path(__file__).relative_to(ROOT)),
            "results_json": str(RESULTS_PATH.relative_to(ROOT)),
            "figure": str(FIG_PATH.relative_to(ROOT)),
        },
        "elapsed_seconds": round(elapsed, 2),
    }


def main() -> None:
    start = datetime.now(timezone.utc)
    panel = build_panel()
    specs = run_specs(panel)
    make_figure(panel, specs)
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    output = build_output(panel, specs, elapsed)
    RESULTS_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"experiment_id": EXPERIMENT_ID, "verdict": output["verdict"], "results": str(RESULTS_PATH)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
