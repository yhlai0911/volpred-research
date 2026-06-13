from __future__ import annotations

import json
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise

try:
    from xgboost import XGBRegressor

    HAS_XGBOOST = True
except Exception:
    XGBRegressor = None
    HAS_XGBOOST = False


warnings.filterwarnings("ignore")

EXPERIMENT_ID = "k_explainable_ensemble_vol_gate_2026_06_14"
ROOT = Path(__file__).resolve().parent
RESULTS_PATH = ROOT / f"{EXPERIMENT_ID}_results.json"
PREDICTIONS_PATH = ROOT / "walk_forward_predictions.csv"
IMPORTANCE_PATH = ROOT / "feature_importance_by_fold.csv"

SEED = 42
DATA_START = "2006-01-01"
DATA_END = "2026-06-14"
TARGET_HORIZON = 5
TRAIN_WINDOW = 2000
TEST_YEARS = list(range(2016, 2026))
EPS = 1e-10
TOP_K = 5

TICKERS = {
    "SPY": "SPY",
    "VIX": "^VIX",
    "TLT": "TLT",
    "HYG": "HYG",
    "LQD": "LQD",
    "GLD": "GLD",
    "EEM": "EEM",
    "XLK": "XLK",
    "XLF": "XLF",
}


@dataclass
class LiteratureItem:
    title: str
    source: str
    year: int
    takeaway: str
    url: str


LITERATURE = [
    LiteratureItem(
        title="Ensemble Learning in Investment: An Overview",
        source="CFA Institute Research and Policy Center",
        year=2025,
        takeaway=(
            "Ensembles can improve supervised finance models, but investment use still "
            "requires explainability, governance, and risk controls rather than accuracy alone."
        ),
        url="https://rpc.cfainstitute.org/research/foundation/2025/chapter-4-ensemble-learning-investment",
    ),
    LiteratureItem(
        title="Explainable AI in Finance: Meeting Stakeholder Needs",
        source="CFA Institute Research and Policy Center",
        year=2025,
        takeaway=(
            "Financial AI systems need transparent explanations that are stable enough for "
            "oversight, model validation, and stakeholder trust."
        ),
        url="https://rpc.cfainstitute.org/research/reports/2025/explainable-ai-in-finance",
    ),
    LiteratureItem(
        title="Volatility Forecast Comparison Using Imperfect Volatility Proxies",
        source="Journal of Econometrics",
        year=2011,
        takeaway="QLIKE is a proxy-robust loss for volatility forecast comparison under Patton's assumptions.",
        url="https://ideas.repec.org/a/eee/econom/v160y2011i1p246-256.html",
    ),
    LiteratureItem(
        title="A Simple Approximate Long-Memory Model of Realized Volatility",
        source="Journal of Financial Econometrics",
        year=2009,
        takeaway="HAR-RV motivates parsimonious daily/weekly/monthly realized-volatility features.",
        url="https://papers.ssrn.com/sol3/papers.cfm?abstract_id=626064",
    ),
]


def download_prices() -> pd.DataFrame:
    raw = yf.download(
        list(TICKERS.values()),
        start=DATA_START,
        end=DATA_END,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned an empty panel")

    prices = pd.DataFrame(index=raw.index)
    for name, ticker in TICKERS.items():
        if isinstance(raw.columns, pd.MultiIndex):
            sub = raw[ticker]
            col = "Close" if "Close" in sub.columns else sub.columns[0]
            prices[name] = sub[col]
        else:
            col = "Close" if "Close" in raw.columns else raw.columns[0]
            prices[name] = raw[col]
    prices = prices.dropna(how="all").ffill()
    return prices.dropna(subset=["SPY", "VIX"])


def future_mean(values: pd.Series, horizon: int) -> pd.Series:
    pieces = [values.shift(-step) for step in range(1, horizon + 1)]
    return pd.concat(pieces, axis=1).mean(axis=1)


def future_end_date(index: pd.DatetimeIndex, horizon: int) -> pd.Series:
    end_dates = []
    for pos in range(len(index)):
        end_pos = pos + horizon
        end_dates.append(index[end_pos] if end_pos < len(index) else pd.NaT)
    return pd.Series(end_dates, index=index)


def build_dataset(prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    log_prices = np.log(prices)
    returns = log_prices.diff()
    spy_ret = returns["SPY"]
    spy_r2 = spy_ret.pow(2)

    df = pd.DataFrame(index=prices.index)
    df["target_var5"] = future_mean(spy_r2, TARGET_HORIZON)
    df["target_end_date"] = future_end_date(prices.index, TARGET_HORIZON)

    df["spy_r2_1d"] = spy_r2
    df["spy_abs_1d"] = spy_ret.abs()
    df["spy_neg_r2_1d"] = spy_r2.where(spy_ret < 0.0, 0.0)
    df["spy_ret_1d"] = spy_ret
    for window in [5, 10, 22, 63, 126]:
        df[f"spy_rv_{window}d"] = spy_r2.rolling(window).mean()
        df[f"spy_abs_{window}d"] = spy_ret.abs().rolling(window).mean()
        df[f"spy_ret_{window}d"] = spy_ret.rolling(window).sum()
    df["spy_ewma94_var"] = spy_r2.ewm(alpha=0.06, adjust=False).mean()
    df["rv_ratio_5_22"] = df["spy_rv_5d"] / df["spy_rv_22d"]
    df["rv_ratio_22_63"] = df["spy_rv_22d"] / df["spy_rv_63d"]

    vix = prices["VIX"] / 100.0
    df["vix_daily_var"] = vix.pow(2) / 252.0
    df["vix_log_chg_1d"] = np.log(prices["VIX"]).diff()
    df["vix_log_chg_5d"] = np.log(prices["VIX"]).diff(5)
    df["vix_rv22_spread"] = df["vix_daily_var"] - df["spy_rv_22d"]
    df["vix_z_63d"] = (prices["VIX"] - prices["VIX"].rolling(63).mean()) / prices["VIX"].rolling(63).std()

    for name in ["TLT", "HYG", "LQD", "GLD", "EEM", "XLK", "XLF"]:
        asset_ret = returns[name]
        df[f"{name.lower()}_ret_5d"] = asset_ret.rolling(5).sum()
        df[f"{name.lower()}_ret_22d"] = asset_ret.rolling(22).sum()
        df[f"{name.lower()}_rv_22d"] = asset_ret.pow(2).rolling(22).mean()

    df["credit_hyg_lqd_ret_5d"] = returns["HYG"].rolling(5).sum() - returns["LQD"].rolling(5).sum()
    df["credit_hyg_lqd_ret_22d"] = returns["HYG"].rolling(22).sum() - returns["LQD"].rolling(22).sum()
    df["xlk_xlf_ret_22d"] = returns["XLK"].rolling(22).sum() - returns["XLF"].rolling(22).sum()

    feature_cols = [col for col in df.columns if col not in {"target_var5", "target_end_date"}]
    clean = df.dropna(subset=feature_cols + ["target_var5", "target_end_date"]).copy()
    clean = clean[clean["target_var5"] > 0.0]
    return clean[feature_cols], clean["target_var5"].clip(lower=EPS), clean["target_end_date"]


def make_models() -> dict[str, object]:
    models: dict[str, object] = {
        "har_ridge": Pipeline(
            [
                ("impute", SimpleImputer(strategy="median")),
                ("scale", StandardScaler()),
                ("model", Ridge(alpha=5.0)),
            ]
        ),
        "random_forest": Pipeline(
            [
                ("impute", SimpleImputer(strategy="median")),
                (
                    "model",
                    RandomForestRegressor(
                        n_estimators=300,
                        max_depth=5,
                        min_samples_leaf=25,
                        max_features="sqrt",
                        random_state=SEED,
                        n_jobs=-1,
                    ),
                ),
            ]
        ),
        "hist_gradient_boosting": Pipeline(
            [
                ("impute", SimpleImputer(strategy="median")),
                (
                    "model",
                    HistGradientBoostingRegressor(
                        max_iter=250,
                        max_leaf_nodes=15,
                        min_samples_leaf=30,
                        learning_rate=0.03,
                        l2_regularization=1.0,
                        random_state=SEED,
                    ),
                ),
            ]
        ),
    }
    if HAS_XGBOOST and XGBRegressor is not None:
        models["xgboost"] = Pipeline(
            [
                ("impute", SimpleImputer(strategy="median")),
                (
                    "model",
                    XGBRegressor(
                        n_estimators=300,
                        max_depth=3,
                        learning_rate=0.03,
                        subsample=0.85,
                        colsample_bytree=0.85,
                        min_child_weight=20,
                        reg_lambda=5.0,
                        objective="reg:squarederror",
                        random_state=SEED,
                        n_jobs=2,
                        verbosity=0,
                    ),
                ),
            ]
        )
    return models


def predict_var(model: object, x: pd.DataFrame, bounds: tuple[float, float] | None = None) -> np.ndarray:
    pred_log = np.asarray(model.predict(x), dtype=float)
    pred = np.exp(np.clip(pred_log, np.log(EPS), np.log(0.05)))
    if bounds is not None:
        pred = np.clip(pred, bounds[0], bounds[1])
    return pred


def ensemble_predict(
    models: dict[str, object],
    x: pd.DataFrame,
    bounds: tuple[float, float] | None = None,
) -> np.ndarray:
    member_names = [name for name in models if name != "har_ridge"]
    preds = [predict_var(models[name], x, bounds) for name in member_names]
    return np.mean(np.column_stack(preds), axis=1)


def permutation_importance_for_ensemble(
    models: dict[str, object],
    x_test: pd.DataFrame,
    y_test: pd.Series,
    feature_cols: list[str],
    bounds: tuple[float, float],
    seed: int,
) -> dict[str, float]:
    rng = np.random.default_rng(seed)
    base_pred = ensemble_predict(models, x_test, bounds)
    base_loss = qlike(y_test.to_numpy(), base_pred)
    importances: dict[str, float] = {}
    for feature in feature_cols:
        x_perm = x_test.copy()
        shuffled = x_perm[feature].to_numpy().copy()
        rng.shuffle(shuffled)
        x_perm[feature] = shuffled
        perm_loss = qlike(y_test.to_numpy(), ensemble_predict(models, x_perm, bounds))
        importances[feature] = float(perm_loss - base_loss)
    return importances


def rank_features(importances: dict[str, float]) -> dict[str, int]:
    ordered = sorted(importances.items(), key=lambda kv: (-kv[1], kv[0]))
    return {feature: rank + 1 for rank, (feature, _) in enumerate(ordered)}


def run_walk_forward(x: pd.DataFrame, y: pd.Series, target_end: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    pred_rows = []
    importance_rows = []
    feature_cols = list(x.columns)
    y_log = np.log(y.clip(lower=EPS))

    for year in TEST_YEARS:
        test_start = pd.Timestamp(f"{year}-01-01")
        test_end = pd.Timestamp(f"{year + 1}-01-01")
        train_mask = target_end < test_start
        test_mask = (x.index >= test_start) & (x.index < test_end)
        train_idx = x.index[train_mask]
        if len(train_idx) > TRAIN_WINDOW:
            train_idx = train_idx[-TRAIN_WINDOW:]
        test_idx = x.index[test_mask]
        if len(train_idx) < 1000 or len(test_idx) < 100:
            continue

        x_train = x.loc[train_idx]
        y_train_log = y_log.loc[train_idx]
        x_test = x.loc[test_idx]
        y_test = y.loc[test_idx]

        models = make_models()
        for model in models.values():
            model.fit(x_train, y_train_log)

        # Same train-only variance bounds for every model. This prevents a trivial
        # QLIKE win caused by one model predicting near-zero variance in a crash year.
        pred_floor = max(float(y.loc[train_idx].quantile(0.01)), EPS)
        pred_cap = max(float(y.loc[train_idx].quantile(0.99) * 5.0), pred_floor * 10.0)
        bounds = (pred_floor, pred_cap)

        model_preds = {name: predict_var(model, x_test, bounds) for name, model in models.items()}
        model_preds["ensemble"] = ensemble_predict(models, x_test, bounds)

        for pos, date in enumerate(test_idx):
            row = {
                "date": date,
                "year": year,
                "actual": float(y.loc[date]),
            }
            for name, pred in model_preds.items():
                row[f"pred_{name}"] = float(pred[pos])
            pred_rows.append(row)

        importances = permutation_importance_for_ensemble(models, x_test, y_test, feature_cols, bounds, SEED + year)
        ranks = rank_features(importances)
        for feature in feature_cols:
            importance_rows.append(
                {
                    "year": year,
                    "feature": feature,
                    "importance": importances[feature],
                    "rank": ranks[feature],
                }
            )

    return pd.DataFrame(pred_rows), pd.DataFrame(importance_rows)


def summarize_performance(preds: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    model_names = sorted(col.replace("pred_", "") for col in preds.columns if col.startswith("pred_"))
    actual = preds["actual"].to_numpy()

    overall = {}
    for name in model_names:
        pred = preds[f"pred_{name}"].to_numpy()
        overall[name] = {
            "qlike": qlike(actual, pred),
            "mse": float(np.mean((actual - pred) ** 2)),
            "spearman": {
                "rho": float(stats.spearmanr(actual, pred).statistic),
                "p": float(stats.spearmanr(actual, pred).pvalue),
            },
        }

    baseline_loss = qlike_pointwise(actual, preds["pred_har_ridge"].to_numpy())
    ensemble_loss = qlike_pointwise(actual, preds["pred_ensemble"].to_numpy())
    t_stat, p_value = dm_test(ensemble_loss, baseline_loss, h=TARGET_HORIZON)
    improvement = (overall["har_ridge"]["qlike"] - overall["ensemble"]["qlike"]) / overall["har_ridge"]["qlike"]
    overall["ensemble_vs_har_ridge_dm"] = {
        "dm_t_ensemble_minus_har": float(t_stat),
        "p_value": float(p_value),
        "mean_loss_har_minus_ensemble": float(np.mean(baseline_loss - ensemble_loss)),
        "qlike_improvement_pct": float(improvement * 100.0),
        "harvey_pass_abs_t_gt_3": bool(abs(t_stat) > 3.0),
    }

    yearly_rows = []
    for year, group in preds.groupby("year"):
        row = {"year": int(year), "n": int(len(group))}
        y_year = group["actual"].to_numpy()
        for name in model_names:
            row[f"qlike_{name}"] = qlike(y_year, group[f"pred_{name}"].to_numpy())
        row["ensemble_improvement_pct"] = (
            (row["qlike_har_ridge"] - row["qlike_ensemble"]) / row["qlike_har_ridge"] * 100.0
        )
        yearly_rows.append(row)
    return overall, pd.DataFrame(yearly_rows)


def subset_comparison(preds: pd.DataFrame, mask: pd.Series) -> dict:
    subset = preds.loc[mask].copy()
    actual = subset["actual"].to_numpy()
    har_pred = subset["pred_har_ridge"].to_numpy()
    ensemble_pred = subset["pred_ensemble"].to_numpy()
    har_loss = qlike_pointwise(actual, har_pred)
    ensemble_loss = qlike_pointwise(actual, ensemble_pred)
    t_stat, p_value = dm_test(ensemble_loss, har_loss, h=TARGET_HORIZON)
    q_har = qlike(actual, har_pred)
    q_ensemble = qlike(actual, ensemble_pred)
    return {
        "n": int(len(subset)),
        "years": [int(y) for y in sorted(subset["year"].unique())],
        "qlike_har_ridge": q_har,
        "qlike_ensemble": q_ensemble,
        "qlike_improvement_pct": float((q_har - q_ensemble) / q_har * 100.0),
        "dm_t_ensemble_minus_har": float(t_stat),
        "p_value": float(p_value),
        "harvey_pass_abs_t_gt_3": bool(abs(t_stat) > 3.0),
    }


def robustness_checks(preds: pd.DataFrame, yearly: pd.DataFrame) -> dict:
    checks = {
        "positive_improvement_years": int((yearly["ensemble_improvement_pct"] > 0.0).sum()),
        "total_years": int(len(yearly)),
        "median_yearly_improvement_pct": float(yearly["ensemble_improvement_pct"].median()),
        "worst_har_year": int(yearly.sort_values("qlike_har_ridge", ascending=False).iloc[0]["year"]),
        "excluding_2020": subset_comparison(preds, preds["year"] != 2020),
    }
    return checks


def summarize_stability(importances: pd.DataFrame) -> dict:
    pivot_imp = importances.pivot(index="year", columns="feature", values="importance").sort_index()
    pivot_rank = importances.pivot(index="year", columns="feature", values="rank").sort_index()
    years = list(pivot_imp.index)

    adjacent = []
    for left, right in zip(years[:-1], years[1:]):
        left_imp = pivot_imp.loc[left]
        right_imp = pivot_imp.loc[right]
        rho = stats.spearmanr(left_imp, right_imp).statistic
        left_top = set(pivot_rank.loc[left].sort_values().head(TOP_K).index)
        right_top = set(pivot_rank.loc[right].sort_values().head(TOP_K).index)
        jaccard = len(left_top & right_top) / len(left_top | right_top)
        rank_drift = (pivot_rank.loc[left] - pivot_rank.loc[right]).abs().mean() / len(pivot_rank.columns)
        adjacent.append(
            {
                "left_year": int(left),
                "right_year": int(right),
                "spearman_importance": float(rho),
                "top5_jaccard": float(jaccard),
                "mean_abs_rank_drift_normalized": float(rank_drift),
                "left_top5": sorted(left_top),
                "right_top5": sorted(right_top),
            }
        )

    aggregate_importance = pivot_imp.mean(axis=0).sort_values(ascending=False)
    aggregate_rank = aggregate_importance.rank(ascending=False, method="first").astype(int)
    return {
        "n_folds": int(len(years)),
        "years": [int(y) for y in years],
        "aggregate_top10": [
            {
                "feature": feature,
                "mean_importance": float(aggregate_importance.loc[feature]),
                "aggregate_rank": int(aggregate_rank.loc[feature]),
            }
            for feature in aggregate_importance.head(10).index
        ],
        "adjacent_fold_stability": adjacent,
        "mean_adjacent_spearman": float(np.nanmean([row["spearman_importance"] for row in adjacent])),
        "mean_top5_jaccard": float(np.nanmean([row["top5_jaccard"] for row in adjacent])),
        "mean_abs_rank_drift_normalized": float(
            np.nanmean([row["mean_abs_rank_drift_normalized"] for row in adjacent])
        ),
    }


def gate_decision(performance: dict, stability: dict) -> dict:
    dm = performance["ensemble_vs_har_ridge_dm"]
    average_gain = dm["qlike_improvement_pct"] > 2.0
    performance_pass = dm["qlike_improvement_pct"] > 2.0 and dm["dm_t_ensemble_minus_har"] < -3.0
    stability_pass = (
        stability["mean_adjacent_spearman"] >= 0.35
        and stability["mean_top5_jaccard"] >= 0.35
        and stability["mean_abs_rank_drift_normalized"] <= 0.25
    )
    if performance_pass and stability_pass:
        verdict = "DEPLOYABLE_CANDIDATE_PASS"
    elif performance_pass and not stability_pass:
        verdict = "NOT_DEPLOYABLE_UNSTABLE_IMPORTANCE"
    elif average_gain and not stability_pass:
        verdict = "NOT_DEPLOYABLE_AVERAGE_GAIN_UNSTABLE_NOT_HARVEY_SIGNIFICANT"
    elif average_gain:
        verdict = "AVERAGE_GAIN_NOT_HARVEY_SIGNIFICANT"
    else:
        verdict = "NULL_NO_HAR_QLIKE_EDGE"
    return {
        "verdict": verdict,
        "average_gain": bool(average_gain),
        "performance_pass": bool(performance_pass),
        "stability_pass": bool(stability_pass),
        "rules": {
            "performance_pass": "ensemble QLIKE improvement > 2% and DM t(ensemble - HAR) < -3",
            "stability_pass": "mean adjacent Spearman >= 0.35, top5 Jaccard >= 0.35, normalized rank drift <= 0.25",
        },
    }


def write_plots(yearly: pd.DataFrame, importances: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(yearly["year"], yearly["qlike_har_ridge"], marker="o", label="HAR/Ridge baseline")
    ax.plot(yearly["year"], yearly["qlike_ensemble"], marker="o", label="Tree ensemble")
    ax.set_title("Walk-forward QLIKE by OOS year")
    ax.set_xlabel("OOS year")
    ax.set_ylabel("QLIKE, lower is better")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(ROOT / "fig_qlike_by_year.png", dpi=160)
    plt.close(fig)

    agg = importances.groupby("feature")["importance"].mean().sort_values(ascending=False).head(12)
    fig, ax = plt.subplots(figsize=(9, 6))
    agg.sort_values().plot(kind="barh", ax=ax, color="#315c72")
    ax.set_title("Mean walk-forward permutation importance")
    ax.set_xlabel("Increase in QLIKE after permutation")
    fig.tight_layout()
    fig.savefig(ROOT / "fig_mean_permutation_importance.png", dpi=160)
    plt.close(fig)

    top_features = list(agg.index)
    rank_pivot = importances[importances["feature"].isin(top_features)].pivot(
        index="feature", columns="year", values="rank"
    )
    rank_pivot = rank_pivot.loc[top_features]
    fig, ax = plt.subplots(figsize=(10, 6))
    im = ax.imshow(rank_pivot.values, aspect="auto", cmap="viridis_r")
    ax.set_xticks(np.arange(len(rank_pivot.columns)))
    ax.set_xticklabels([str(int(c)) for c in rank_pivot.columns], rotation=45)
    ax.set_yticks(np.arange(len(rank_pivot.index)))
    ax.set_yticklabels(rank_pivot.index)
    ax.set_title("Feature rank drift across walk-forward folds")
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Rank, lower is more important")
    fig.tight_layout()
    fig.savefig(ROOT / "fig_feature_rank_drift.png", dpi=160)
    plt.close(fig)


def main() -> None:
    np.random.seed(SEED)
    prices = download_prices()
    x, y, target_end = build_dataset(prices)
    preds, importances = run_walk_forward(x, y, target_end)
    if preds.empty:
        raise RuntimeError("No walk-forward predictions were produced")
    preds.to_csv(PREDICTIONS_PATH, index=False)
    importances.to_csv(IMPORTANCE_PATH, index=False)

    performance, yearly = summarize_performance(preds)
    robustness = robustness_checks(preds, yearly)
    stability = summarize_stability(importances)
    gate = gate_decision(performance, stability)
    write_plots(yearly, importances)

    results = {
        "experiment_id": EXPERIMENT_ID,
        "created_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "seed": SEED,
        "data": {
            "source": "yfinance",
            "data_pulled_at": pd.Timestamp.now(tz="UTC").isoformat(),
            "tickers": TICKERS,
            "start": DATA_START,
            "end": DATA_END,
            "first_feature_date": str(x.index.min().date()),
            "last_feature_date": str(x.index.max().date()),
            "n_feature_rows": int(len(x)),
            "target": f"SPY forward {TARGET_HORIZON}-trading-day mean squared log return",
            "target_horizon": TARGET_HORIZON,
            "train_window": TRAIN_WINDOW,
            "test_years": TEST_YEARS,
            "leakage_control": (
                "For each OOS year, training rows require target_end_date < OOS start, "
                "so forward 5-day targets never cross the test boundary."
            ),
            "forecast_bounds": (
                "Each fold applies the same train-only 1% target quantile floor and 5x 99% target "
                "quantile cap to all model variance forecasts to prevent near-zero QLIKE artifacts."
            ),
            "packages": {
                "numpy": np.__version__,
                "pandas": pd.__version__,
                "sklearn": __import__("sklearn").__version__,
                "xgboost_available": HAS_XGBOOST,
                "yfinance": yf.__version__,
            },
        },
        "literature": [asdict(item) for item in LITERATURE],
        "methods": {
            "baseline": "Ridge on HAR/GJR-style features, trained on log variance",
            "ensemble_members": [
                name for name in ["random_forest", "xgboost", "hist_gradient_boosting"] if name in performance
            ],
            "importance_method": (
                "Walk-forward permutation importance on the ensemble. SHAP and LightGBM were not available "
                "in this environment, so this is an XAI rank-stability proxy rather than literal SHAP."
            ),
            "primary_loss": "Patton QLIKE on forward 5-day mean squared return",
            "dm_test": "volpred.stats.model_evaluation.dm_test with h=5 HAC for overlapping target",
        },
        "performance": performance,
        "yearly_performance": yearly.to_dict(orient="records"),
        "robustness": robustness,
        "feature_stability": stability,
        "gate": gate,
        "files": {
            "results": str(RESULTS_PATH.name),
            "predictions": str(PREDICTIONS_PATH.name),
            "importance_by_fold": str(IMPORTANCE_PATH.name),
            "figures": [
                "fig_qlike_by_year.png",
                "fig_mean_permutation_importance.png",
                "fig_feature_rank_drift.png",
            ],
        },
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({"verdict": gate["verdict"], "performance": performance["ensemble_vs_har_ridge_dm"]}, indent=2))


if __name__ == "__main__":
    main()
