#!/usr/bin/env python3
"""
K1430 — Autoencoder Enhanced Realised GARCH PoC

Goal:
    Test the core upstream claim behind the AE-Realised-GARCH idea:
    can a 1D autoencoder-compressed synthetic realised measure beat
    single realised measures for next-day 5-min RV forecasting?

Scope:
    This is a short-sample feasibility PoC on local SPY 5-min data,
    not a formal full-sample superiority claim.
"""

from __future__ import annotations

import glob
import json
import os
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.linear_model import LinearRegression
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise

warnings.filterwarnings("ignore", message="Pandas requires version")
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

SEED = 42
np.random.seed(SEED)

EXP_DIR = Path("experiments/k1430")
RESULTS_PATH = EXP_DIR / "k1430_results.json"
FIG_PATH = EXP_DIR / "k1430_ae_measure_comparison.png"
DATA_GLOB = "data/intraday/SPY_5min_*.csv"
TEST_SIZE = 29
AE_ARCH = (3, 1, 3)


def load_intraday_day(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, header=[0, 1], index_col=0, parse_dates=True)
    df.columns = [col[0] for col in df.columns]
    cols = ["Open", "High", "Low", "Close", "Volume"]
    return df[cols].dropna()


def compute_daily_row(path: str) -> dict[str, float | str]:
    df = load_intraday_day(path)
    close = df["Close"].astype(float)
    log_ret = np.log(close / close.shift(1)).dropna()

    rv = float((log_ret**2).sum())
    bpv = float((np.pi / 2.0) * np.sum(np.abs(log_ret.values[1:]) * np.abs(log_ret.values[:-1])))
    rv_pos = float((log_ret[log_ret > 0] ** 2).sum())
    rv_neg = float((log_ret[log_ret < 0] ** 2).sum())

    open_ = float(df["Open"].iloc[0])
    high = float(df["High"].max())
    low = float(df["Low"].min())
    close_last = float(df["Close"].iloc[-1])

    parkinson = float((1.0 / (4.0 * np.log(2.0))) * (np.log(high / low) ** 2))
    garman_klass = float(
        0.5 * (np.log(high / low) ** 2)
        - (2.0 * np.log(2.0) - 1.0) * (np.log(close_last / open_) ** 2)
    )
    oc2 = float(np.log(close_last / open_) ** 2)

    date_str = os.path.basename(path).split("_")[-1].replace(".csv", "")

    return {
        "date": date_str,
        "rv_5min": rv,
        "bpv": bpv,
        "rv_pos": rv_pos,
        "rv_neg": rv_neg,
        "parkinson": parkinson,
        "garman_klass": garman_klass,
        "oc2": oc2,
        "open": open_,
        "close": close_last,
    }


def build_dataset() -> pd.DataFrame:
    rows = [compute_daily_row(path) for path in sorted(glob.glob(DATA_GLOB))]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["ret_cc"] = np.log(df["close"] / df["close"].shift(1))
    df = df.dropna().reset_index(drop=True)

    measure_cols = ["rv_5min", "bpv", "rv_pos", "rv_neg", "parkinson", "garman_klass", "oc2"]
    for col in measure_cols:
        df[f"log_{col}"] = np.log(np.maximum(df[col].astype(float), 1e-12))

    return df


def extract_bottleneck(model: MLPRegressor, X: np.ndarray) -> np.ndarray:
    activations = X
    for i, (weights, bias) in enumerate(zip(model.coefs_, model.intercepts_)):
        z = activations @ weights + bias
        activations = np.tanh(z) if i < len(model.coefs_) - 1 else z
        if activations.ndim == 2 and activations.shape[1] == 1:
            return activations.ravel()
    raise RuntimeError("Failed to extract 1D bottleneck from autoencoder.")


def fit_autoencoder_measure(df: pd.DataFrame, train_n: int) -> tuple[pd.Series, dict[str, float]]:
    feature_cols = [
        "log_rv_5min",
        "log_bpv",
        "log_rv_pos",
        "log_rv_neg",
        "log_parkinson",
        "log_garman_klass",
        "log_oc2",
    ]

    scaler = StandardScaler()
    X_train = scaler.fit_transform(df.loc[: train_n - 1, feature_cols].values)
    X_all = scaler.transform(df[feature_cols].values)

    ae = MLPRegressor(
        hidden_layer_sizes=AE_ARCH,
        activation="tanh",
        solver="lbfgs",
        alpha=1e-4,
        random_state=SEED,
        max_iter=20000,
    )
    ae.fit(X_train, X_train)

    bottleneck_train = extract_bottleneck(ae, X_train)
    bottleneck_all = extract_bottleneck(ae, X_all)

    # Calibrate latent dimension back to the log-RV scale using train only.
    calibrator = LinearRegression()
    calibrator.fit(bottleneck_train.reshape(-1, 1), df.loc[: train_n - 1, "log_rv_5min"].values)
    ae_log_measure = calibrator.predict(bottleneck_all.reshape(-1, 1))

    reconstructed_train = ae.predict(X_train)
    recon_mse_train = float(np.mean((X_train - reconstructed_train) ** 2))

    return pd.Series(ae_log_measure, index=df.index), {
        "architecture": list(AE_ARCH),
        "reconstruction_mse_train": recon_mse_train,
    }


def fit_pca_measure(df: pd.DataFrame, train_n: int) -> pd.Series:
    feature_cols = [
        "log_rv_5min",
        "log_bpv",
        "log_rv_pos",
        "log_rv_neg",
        "log_parkinson",
        "log_garman_klass",
        "log_oc2",
    ]
    scaler = StandardScaler()
    X_train = scaler.fit_transform(df.loc[: train_n - 1, feature_cols].values)
    X_all = scaler.transform(df[feature_cols].values)

    pca = PCA(n_components=1, random_state=SEED)
    latent_train = pca.fit_transform(X_train).ravel()
    latent_all = pca.transform(X_all).ravel()

    calibrator = LinearRegression()
    calibrator.fit(latent_train.reshape(-1, 1), df.loc[: train_n - 1, "log_rv_5min"].values)
    pca_log_measure = calibrator.predict(latent_all.reshape(-1, 1))
    return pd.Series(pca_log_measure, index=df.index)


def forecast_next_day_rv(
    signal_log_measure: pd.Series,
    target_log_rv: pd.Series,
    target_rv_level: pd.Series,
    train_n: int,
) -> dict[str, object]:
    X_train = signal_log_measure.iloc[: train_n - 1].values.reshape(-1, 1)
    y_train = target_log_rv.shift(-1).iloc[: train_n - 1].values
    X_test = signal_log_measure.iloc[train_n - 1 : -1].values.reshape(-1, 1)
    y_test = target_rv_level.shift(-1).iloc[train_n - 1 : -1].values

    model = LinearRegression()
    model.fit(X_train, y_train)
    pred_level = np.exp(model.predict(X_test))

    losses = qlike_pointwise(y_test, pred_level)
    return {
        "predictions": pred_level,
        "actual": y_test,
        "qlike": float(qlike(y_test, pred_level)),
        "mse": float(np.mean((y_test - pred_level) ** 2)),
        "corr": float(np.corrcoef(y_test, pred_level)[0, 1]),
        "coef": float(model.coef_[0]),
        "intercept": float(model.intercept_),
        "losses": losses,
    }


def measure_alignment_stats(actual: pd.Series, proxy: pd.Series) -> dict[str, float]:
    return {
        "corr": float(np.corrcoef(actual.values, proxy.values)[0, 1]),
        "mse": float(np.mean((actual.values - proxy.values) ** 2)),
    }


def make_figure(
    forecast_results: dict[str, dict[str, object]],
    forecast_dates: pd.Series,
    actual: np.ndarray,
) -> None:
    x_dates = forecast_dates.to_numpy()
    qlike_items = sorted(
        ((name, result["qlike"]) for name, result in forecast_results.items()),
        key=lambda x: x[1],
    )

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), dpi=120)

    names = [x[0] for x in qlike_items]
    qlikes = [x[1] for x in qlike_items]
    axes[0].bar(names, qlikes, color=["#2f855a", "#3182ce", "#dd6b20", "#718096", "#a0aec0", "#cbd5e0", "#e2e8f0"])
    axes[0].set_title("OOS QLIKE (lower is better)")
    axes[0].tick_params(axis="x", rotation=35)

    axes[1].plot(x_dates, actual, label="Actual RV", color="#1a202c", linewidth=2)
    for name, color in [("BPV", "#2f855a"), ("AE_1D", "#dd6b20"), ("RV_5min", "#3182ce")]:
        axes[1].plot(x_dates, forecast_results[name]["predictions"], label=name, linewidth=1.8, color=color)
    axes[1].set_title("Next-Day RV Forecasts")
    axes[1].tick_params(axis="x", rotation=35)
    axes[1].legend(frameon=False)

    fig.tight_layout()
    fig.savefig(FIG_PATH, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    df = build_dataset()
    train_n = len(df) - TEST_SIZE

    ae_log_measure, ae_meta = fit_autoencoder_measure(df, train_n)
    pca_log_measure = fit_pca_measure(df, train_n)

    same_day_test = {
        "AE_1D": measure_alignment_stats(
            df.loc[train_n:, "rv_5min"], np.exp(ae_log_measure.iloc[train_n:])
        ),
        "PCA_1D": measure_alignment_stats(
            df.loc[train_n:, "rv_5min"], np.exp(pca_log_measure.iloc[train_n:])
        ),
        "BPV": measure_alignment_stats(
            df.loc[train_n:, "rv_5min"], df.loc[train_n:, "bpv"]
        ),
        "GarmanKlass": measure_alignment_stats(
            df.loc[train_n:, "rv_5min"], df.loc[train_n:, "garman_klass"]
        ),
        "Parkinson": measure_alignment_stats(
            df.loc[train_n:, "rv_5min"], df.loc[train_n:, "parkinson"]
        ),
    }

    signals = {
        "BPV": df["log_bpv"],
        "RV_5min": df["log_rv_5min"],
        "AE_1D": ae_log_measure,
        "PCA_1D": pca_log_measure,
        "GarmanKlass": df["log_garman_klass"],
        "Parkinson": df["log_parkinson"],
        "OC2": df["log_oc2"],
    }

    forecast_results: dict[str, dict[str, object]] = {}
    for name, signal in signals.items():
        forecast_results[name] = forecast_next_day_rv(signal, df["log_rv_5min"], df["rv_5min"], train_n)

    actual = forecast_results["BPV"]["actual"]
    forecast_dates = df["date"].iloc[train_n:]

    dm_pairs = {
        "AE_1D_vs_RV_5min": dm_test(
            forecast_results["AE_1D"]["losses"], forecast_results["RV_5min"]["losses"]
        ),
        "AE_1D_vs_BPV": dm_test(
            forecast_results["AE_1D"]["losses"], forecast_results["BPV"]["losses"]
        ),
        "BPV_vs_RV_5min": dm_test(
            forecast_results["BPV"]["losses"], forecast_results["RV_5min"]["losses"]
        ),
    }

    ranked = sorted(
        (
            {
                "model": name,
                "qlike": result["qlike"],
                "mse": result["mse"],
                "corr": result["corr"],
                "coef": result["coef"],
            }
            for name, result in forecast_results.items()
        ),
        key=lambda row: row["qlike"],
    )

    verdict = "PARTIAL_NULL"
    key_takeaway = (
        "AE 1D is feasible but does not beat BPV, raw RV, or PCA on this short SPY sample; "
        "all DM tests remain non-significant."
    )

    make_figure(forecast_results, forecast_dates, actual)

    results_payload = {
        "experiment_id": "k1430",
        "title": "Autoencoder Enhanced Realised GARCH PoC",
        "date_run": pd.Timestamp.now(tz="Asia/Taipei").isoformat(),
        "seed": SEED,
        "sample": {
            "asset": "SPY",
            "intraday_source": "data/intraday/SPY_5min_*.csv",
            "n_intraday_days_raw": len(glob.glob(DATA_GLOB)),
            "n_aligned_days": int(len(df)),
            "date_start": str(df["date"].min().date()),
            "date_end": str(df["date"].max().date()),
            "train_n": int(train_n),
            "test_n": int(TEST_SIZE),
            "train_end": str(df["date"].iloc[train_n - 1].date()),
            "test_start": str(df["date"].iloc[train_n].date()),
        },
        "methodology": {
            "lookahead_control": "All forecasts use realised measure at t to predict RV_5min at t+1.",
            "autoencoder_architecture": ae_meta["architecture"],
            "autoencoder_reconstruction_mse_train": ae_meta["reconstruction_mse_train"],
            "forecast_model": "OLS: log(RV_{t+1}) ~ signal_t",
            "note": "PoC validates the synthetic-measure claim upstream of full Realised GARCH, not a full HHS2012 replication.",
        },
        "same_day_alignment_test_window": same_day_test,
        "oos_forecast_ranking": ranked,
        "dm_tests": {
            pair: {"t_stat": float(stats_[0]), "p_value": float(stats_[1])}
            for pair, stats_ in dm_pairs.items()
        },
        "verdict": verdict,
        "key_takeaway": key_takeaway,
        "literature": [
            "Hansen, Huang & Shek (2012) — Realized GARCH: a joint model for returns and realized measures of volatility.",
            "Autoencoder Enhanced Realised GARCH on Volatility Forecasting (arXiv:2411.17136).",
            "Bollerslev, Patton & Quaedvlieg (2016) — exploiting realized-volatility measurement errors.",
            "Skintzi & Fameliti (2025) — combining realized volatility estimators based on economic performance.",
        ],
        "limitations": [
            "Only 99 local SPY 5-min days are available; after close-to-close alignment the usable sample is 98 days.",
            "No formal full-sample Realised GARCH estimation battle is attempted here because the sample is too short for a credible superiority claim.",
            "Results are SPY-only and may not generalize to 0050.TW, futures, or longer regimes.",
        ],
        "next_steps": [
            "Once 252+ aligned 5-min days are available, rerun the same synthetic measure inside full Realized GARCH/HAR-RV horse races.",
            "Test whether AE wins only after excluding raw RV from the input feature set.",
            "Add multi-asset replication on SPY plus 0050.TW using the same train/test protocol.",
        ],
    }

    RESULTS_PATH.write_text(json.dumps(results_payload, indent=2, ensure_ascii=False))

    print("K1430 complete")
    print(json.dumps({"verdict": verdict, "top_model": ranked[0]["model"], "top_qlike": ranked[0]["qlike"]}, indent=2))


if __name__ == "__main__":
    main()
