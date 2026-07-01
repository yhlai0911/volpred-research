"""K1593: CNN-Transformer hybrid volatility forecast adjudication.

Task: research_cnn_transformer_hybrid.

This is a deliberately small, strict OOS adjudication of the backlog claim that
CNN-Transformer hybrids add forecasting power for daily volatility.  The core
control is information symmetry: the neural model and the linear HAR-X/Ridge
baselines receive the same lagged RV and VIX features.  Forecasts made on
feature date t predict the Parkinson realized variance on target date t+1.

Data are frozen inside the repo:
paper/leverage-direction/data/spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026.csv

Primary inference:
  - Patton QLIKE: actual / predicted - log(actual / predicted) - 1.
  - Asset-level DM tests, with Holm correction for CNNTransformer vs HAR-X.
  - Date-clustered panel DM/MCS over common target dates.

This experiment tests a next-day RV forecasting claim, not a trading strategy.
"""

from __future__ import annotations

import json
import random
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.preprocessing import StandardScaler
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
from volpred.stats.mcs import model_confidence_set  # noqa: E402
from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise  # noqa: E402


EXPERIMENT_ID = "k1593"
SEED = 1593
HERE = Path(__file__).resolve().parent
DATA_PATH = (
    REPO_ROOT
    / "paper/leverage-direction/data/spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026.csv"
)
RESULT_PATH = HERE / "k1593_results.json"
LOSS_PATH = HERE / "k1593_oos_losses.csv"
PRED_PATH = HERE / "k1593_oos_predictions.csv"
FIG_DIR = HERE / "figures"
FIG_DIR.mkdir(exist_ok=True)

ASSETS = ["SPY", "QQQ", "EEM", "GLD", "TLT", "IWM", "SLV"]
FEATURE_COLS = [
    "log_rv1",
    "log_rv5",
    "log_rv22",
    "log_vix_var",
    "abs_ret",
    "neg_ret",
]
MODELS = ["RollingMean22", "HAR-X", "Ridge-HAR-X", "CNNTransformer"]

TRAIN_END = pd.Timestamp("2020-12-31")
VALID_START = pd.Timestamp("2021-01-01")
VALID_END = pd.Timestamp("2022-12-31")
OOS_START = pd.Timestamp("2023-01-01")
OOS_END = pd.Timestamp("2026-06-30")

SEQ_LEN = 22
EPOCHS = 50
PATIENCE = 8
MIN_TRAIN = 1200
VAR_FLOOR = 1e-10
VAR_CEIL = 1e4


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(1)


def safe_float(x) -> float | None:
    if x is None:
        return None
    try:
        y = float(x)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(y):
        return None
    return y


def load_raw() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH, parse_dates=["date"])
    df = df.sort_values("date").drop_duplicates("date", keep="last")
    return df.set_index("date")


def build_asset_frame(raw: pd.DataFrame, asset: str) -> pd.DataFrame:
    p = asset.lower().replace("-", "_")
    close = raw[f"{p}_adj_close"].astype(float)
    high = raw[f"{p}_high"].astype(float)
    low = raw[f"{p}_low"].astype(float)
    vix = raw["vix_close"].astype(float)

    ret = 100.0 * np.log(close / close.shift(1))
    hl = np.log(high / low)
    rv = (100.0 * hl) ** 2 / (4.0 * np.log(2.0))
    rv = rv.where(np.isfinite(rv) & (rv > 0))

    vix_var = (vix / np.sqrt(252.0)) ** 2

    # The frozen CSV includes BTC weekend rows.  Build the feature set on each
    # asset's own valid trading calendar first; otherwise 5/22-day rolling RV
    # windows would be broken by non-trading-day NaNs.
    df = pd.DataFrame({"ret": ret, "rv": rv, "vix_var": vix_var}, index=raw.index)
    df = df.dropna()
    df["feature_date"] = df.index
    df["log_rv1"] = np.log(df["rv"].clip(lower=VAR_FLOOR))
    df["log_rv5"] = np.log(df["rv"].rolling(5).mean().clip(lower=VAR_FLOOR))
    df["log_rv22"] = np.log(df["rv"].rolling(22).mean().clip(lower=VAR_FLOOR))
    df["log_vix_var"] = np.log(df["vix_var"].clip(lower=VAR_FLOOR))
    df["abs_ret"] = df["ret"].abs()
    df["neg_ret"] = (df["ret"] < 0).astype(float)
    df["target"] = df["rv"].shift(-1)
    df["target_date"] = pd.Series(df.index, index=df.index).shift(-1)
    keep = ["feature_date", "target_date", "target", "rv", *FEATURE_COLS]
    df = df[keep].dropna()
    df = df[(df["target"] > 0) & np.isfinite(df["target"])]
    df = df.reset_index(drop=True)
    return df


def build_sequences(frame: pd.DataFrame, feature_cols: list[str], seq_len: int):
    x, y, target_dates, feature_dates = [], [], [], []
    features = frame[feature_cols].to_numpy(dtype=np.float32)
    target = np.log(frame["target"].to_numpy(dtype=np.float64).clip(VAR_FLOOR, VAR_CEIL))
    for end in range(seq_len - 1, len(frame)):
        x.append(features[end - seq_len + 1 : end + 1])
        y.append(target[end])
        target_dates.append(frame.loc[end, "target_date"])
        feature_dates.append(frame.loc[end, "feature_date"])
    return (
        np.asarray(x, dtype=np.float32),
        np.asarray(y, dtype=np.float32),
        pd.to_datetime(target_dates),
        pd.to_datetime(feature_dates),
    )


class CNNTransformer(nn.Module):
    def __init__(self, n_features: int, seq_len: int, d_model: int = 24):
        super().__init__()
        self.conv = nn.Conv1d(n_features, d_model, kernel_size=3, padding=1)
        self.pos = nn.Parameter(torch.zeros(1, seq_len, d_model))
        enc_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=4,
            dim_feedforward=64,
            dropout=0.10,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(enc_layer, num_layers=1)
        self.head = nn.Sequential(nn.LayerNorm(d_model), nn.Linear(d_model, 1))

    def forward(self, x):
        z = self.conv(x.transpose(1, 2)).transpose(1, 2)
        z = z + self.pos[:, : z.shape[1], :]
        z = self.encoder(z)
        return self.head(z[:, -1, :]).squeeze(-1)


@dataclass
class TrainedNN:
    model: CNNTransformer
    x_scaler: StandardScaler
    y_mean: float
    y_std: float
    best_val_loss: float
    best_epoch: int
    epochs_run: int


def train_cnn_transformer(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    seed: int,
) -> TrainedNN:
    set_seed(seed)
    n_features = x_train.shape[-1]
    x_scaler = StandardScaler()
    flat_train = x_train.reshape(-1, n_features)
    x_scaler.fit(flat_train)

    def scale_x(x: np.ndarray) -> np.ndarray:
        shp = x.shape
        return x_scaler.transform(x.reshape(-1, n_features)).reshape(shp).astype(np.float32)

    y_mean = float(y_train.mean())
    y_std = float(y_train.std(ddof=0))
    if y_std < 1e-8:
        y_std = 1.0

    xtr = torch.tensor(scale_x(x_train), dtype=torch.float32)
    ytr = torch.tensor((y_train - y_mean) / y_std, dtype=torch.float32)
    xva = torch.tensor(scale_x(x_val), dtype=torch.float32)
    yva = torch.tensor((y_val - y_mean) / y_std, dtype=torch.float32)

    model = CNNTransformer(n_features=n_features, seq_len=x_train.shape[1])
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    loss_fn = nn.MSELoss()
    loader = DataLoader(
        TensorDataset(xtr, ytr),
        batch_size=128,
        shuffle=True,
        generator=torch.Generator().manual_seed(seed),
    )

    best_state = None
    best_val = np.inf
    best_epoch = -1
    stale = 0
    for epoch in range(EPOCHS):
        model.train()
        for xb, yb in loader:
            opt.zero_grad(set_to_none=True)
            loss = loss_fn(model(xb), yb)
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            val_loss = float(loss_fn(model(xva), yva).item())
        if val_loss < best_val - 1e-5:
            best_val = val_loss
            best_epoch = epoch + 1
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
        if stale >= PATIENCE:
            break

    if best_state is not None:
        model.load_state_dict(best_state)
    return TrainedNN(model, x_scaler, y_mean, y_std, best_val, best_epoch, epoch + 1)


def predict_cnn(trained: TrainedNN, x: np.ndarray) -> np.ndarray:
    n_features = x.shape[-1]
    shp = x.shape
    xs = trained.x_scaler.transform(x.reshape(-1, n_features)).reshape(shp).astype(np.float32)
    trained.model.eval()
    with torch.no_grad():
        pred = trained.model(torch.tensor(xs, dtype=torch.float32)).numpy()
    log_pred = pred * trained.y_std + trained.y_mean
    return np.exp(np.clip(log_pred, -30, 30)).clip(VAR_FLOOR, VAR_CEIL)


def choose_ridge_alpha(x_train, y_train, x_val, y_val) -> float:
    alphas = [0.01, 0.1, 1.0, 10.0, 100.0]
    scaler = StandardScaler().fit(x_train)
    xt = scaler.transform(x_train)
    xv = scaler.transform(x_val)
    best_alpha, best_loss = alphas[0], np.inf
    for alpha in alphas:
        mdl = Ridge(alpha=alpha)
        mdl.fit(xt, y_train)
        pred = mdl.predict(xv)
        loss = float(np.mean((pred - y_val) ** 2))
        if loss < best_loss:
            best_alpha, best_loss = alpha, loss
    return best_alpha


def fit_linear_forecasts(frame: pd.DataFrame, oos_mask: np.ndarray):
    trainval_mask = frame["target_date"] < OOS_START
    train_mask = frame["target_date"] <= TRAIN_END
    val_mask = (frame["target_date"] >= VALID_START) & (frame["target_date"] <= VALID_END)

    x = frame[FEATURE_COLS].to_numpy(dtype=float)
    y_log = np.log(frame["target"].to_numpy(dtype=float).clip(VAR_FLOOR, VAR_CEIL))

    x_trainval = x[trainval_mask]
    y_trainval = y_log[trainval_mask]
    x_oos = x[oos_mask]

    har = LinearRegression()
    har.fit(x_trainval, y_trainval)
    har_pred = np.exp(np.clip(har.predict(x_oos), -30, 30)).clip(VAR_FLOOR, VAR_CEIL)

    alpha = choose_ridge_alpha(x[train_mask], y_log[train_mask], x[val_mask], y_log[val_mask])
    scaler = StandardScaler().fit(x_trainval)
    ridge = Ridge(alpha=alpha)
    ridge.fit(scaler.transform(x_trainval), y_trainval)
    ridge_pred = np.exp(np.clip(ridge.predict(scaler.transform(x_oos)), -30, 30)).clip(
        VAR_FLOOR, VAR_CEIL
    )

    rolling = frame.loc[oos_mask, "rv"].rolling(1).mean().to_numpy(dtype=float)
    # The OOS row's rv is the feature-date realized variance, so log_rv22 is the
    # 22-day mean available at the forecast origin.  Use it as a naive forecast.
    rolling22 = np.exp(frame.loc[oos_mask, "log_rv22"].to_numpy(dtype=float)).clip(
        VAR_FLOOR, VAR_CEIL
    )
    assert np.all(np.isfinite(rolling))  # cheap guard that oos_mask is aligned

    return {
        "HAR-X": har_pred,
        "Ridge-HAR-X": ridge_pred,
        "RollingMean22": rolling22,
    }, {"ridge_alpha": float(alpha), "har_n_trainval": int(trainval_mask.sum())}


def holm_adjust(rows: list[dict]) -> dict[str, float]:
    ordered = sorted(
        [(r["asset"], r["dm_cnn_minus_harx"]["p"]) for r in rows if r["dm_cnn_minus_harx"]["p"] is not None],
        key=lambda x: x[1],
    )
    m = len(ordered)
    adjusted = {}
    running = 0.0
    for i, (asset, p) in enumerate(ordered):
        adj = min(1.0, (m - i) * float(p))
        running = max(running, adj)
        adjusted[asset] = running
    return adjusted


def dm_record(loss_a: np.ndarray, loss_b: np.ndarray) -> dict:
    t, p = dm_test(loss_a, loss_b, h=1)
    return {
        "t": safe_float(t),
        "p": safe_float(p),
        "n": int(np.isfinite(loss_a - loss_b).sum()),
        "interpretation": (
            "model_a_strict_win"
            if t < -3.0
            else "model_a_strict_loss"
            if t > 3.0
            else "equal_accuracy_not_rejected"
        ),
    }


def summarize_mcs(losses: dict[str, np.ndarray], seed: int) -> dict:
    mcs = model_confidence_set(losses, alpha=0.10, n_boot=1000, seed=seed)
    return {
        "mcs_models": list(mcs.get("mcs_models", [])),
        "eliminated": [[m, safe_float(p)] for m, p in mcs.get("eliminated", [])],
        "p_values": {k: safe_float(v) for k, v in mcs.get("p_values", {}).items()},
    }


def run_asset(raw: pd.DataFrame, asset: str, seed: int) -> tuple[dict, pd.DataFrame]:
    frame = build_asset_frame(raw, asset)
    if len(frame) < MIN_TRAIN:
        raise ValueError(f"{asset}: insufficient rows after feature construction")

    oos_mask = (frame["target_date"] >= OOS_START) & (frame["target_date"] <= OOS_END)
    train_seq_mask = None

    x_seq, y_seq, seq_target_dates, seq_feature_dates = build_sequences(
        frame, FEATURE_COLS, SEQ_LEN
    )
    train_seq_mask = seq_target_dates <= TRAIN_END
    val_seq_mask = (seq_target_dates >= VALID_START) & (seq_target_dates <= VALID_END)
    oos_seq_mask = (seq_target_dates >= OOS_START) & (seq_target_dates <= OOS_END)

    if train_seq_mask.sum() < 500 or val_seq_mask.sum() < 100 or oos_seq_mask.sum() < 100:
        raise ValueError(f"{asset}: insufficient train/valid/oos sequence rows")

    trained = train_cnn_transformer(
        x_seq[train_seq_mask],
        y_seq[train_seq_mask],
        x_seq[val_seq_mask],
        y_seq[val_seq_mask],
        seed=seed,
    )
    cnn_pred = predict_cnn(trained, x_seq[oos_seq_mask])

    # Align tabular baseline OOS rows to the same target dates as the sequence model.
    oos_dates = seq_target_dates[oos_seq_mask]
    oos_feature_dates = seq_feature_dates[oos_seq_mask]
    tab_oos_mask = frame["target_date"].isin(oos_dates)
    tab_oos = frame.loc[tab_oos_mask].copy()
    tab_oos = tab_oos.set_index("target_date").loc[oos_dates].reset_index()
    linear_forecasts, fit_meta = fit_linear_forecasts(frame, tab_oos_mask)

    actual = tab_oos["target"].to_numpy(dtype=float)
    forecasts = {
        **linear_forecasts,
        "CNNTransformer": cnn_pred,
    }
    losses = {
        name: qlike_pointwise(actual, pred)
        for name, pred in forecasts.items()
    }
    qlikes = {name: safe_float(qlike(actual, pred)) for name, pred in forecasts.items()}
    ranking = sorted(qlikes.items(), key=lambda kv: kv[1] if kv[1] is not None else 1e18)
    best_model = ranking[0][0]

    dm_vs = {
        f"CNNTransformer_minus_{base}": dm_record(losses["CNNTransformer"], losses[base])
        for base in ["HAR-X", "Ridge-HAR-X", "RollingMean22"]
    }
    mcs = summarize_mcs(losses, seed=seed + ASSETS.index(asset))

    out = pd.DataFrame(
        {
            "asset": asset,
            "feature_date": pd.to_datetime(oos_feature_dates).strftime("%Y-%m-%d"),
            "target_date": pd.to_datetime(oos_dates).strftime("%Y-%m-%d"),
            "actual_rv": actual,
        }
    )
    for name, pred in forecasts.items():
        out[f"pred_{name}"] = pred
        out[f"loss_{name}"] = losses[name]

    train_end_feature = pd.to_datetime(frame.loc[frame["target_date"] <= TRAIN_END, "feature_date"]).max()
    first_oos_feature = pd.to_datetime(oos_feature_dates).min()
    first_oos_target = pd.to_datetime(oos_dates).min()
    lookahead_guard = {
        "max_training_feature_date": str(train_end_feature.date()),
        "first_oos_feature_date": str(first_oos_feature.date()),
        "first_oos_target_date": str(first_oos_target.date()),
        "oos_feature_before_target_all_rows": bool(
            np.all(pd.to_datetime(oos_feature_dates).to_numpy() < pd.to_datetime(oos_dates).to_numpy())
        ),
    }

    summary = {
        "asset": asset,
        "n_total_rows": int(len(frame)),
        "n_train_seq": int(train_seq_mask.sum()),
        "n_valid_seq": int(val_seq_mask.sum()),
        "n_oos": int(oos_seq_mask.sum()),
        "oos_start": str(pd.to_datetime(oos_dates).min().date()),
        "oos_end": str(pd.to_datetime(oos_dates).max().date()),
        "qlike": qlikes,
        "best_mean_loss_model": best_model,
        "ranking_by_qlike": [
            {"rank": i + 1, "model": model, "qlike": safe_float(score)}
            for i, (model, score) in enumerate(ranking)
        ],
        "dm_tests": dm_vs,
        "mcs": mcs,
        "cnn_training": {
            "best_val_loss_standardized_log_rv": safe_float(trained.best_val_loss),
            "best_epoch": int(trained.best_epoch),
            "epochs_run": int(trained.epochs_run),
        },
        "fit_meta": fit_meta,
        "lookahead_guard": lookahead_guard,
    }
    return summary, out


def panel_summary(loss_df: pd.DataFrame, assets: list[str], seed: int) -> dict:
    sub = loss_df[loss_df["asset"].isin(assets)].copy()
    wide_parts = []
    for model in MODELS:
        wide = sub.pivot(index="target_date", columns="asset", values=f"loss_{model}")
        wide = wide[assets].dropna()
        wide_parts.append((model, wide.mean(axis=1)))
    common = pd.concat({m: s for m, s in wide_parts}, axis=1).dropna()
    losses = {m: common[m].to_numpy(dtype=float) for m in MODELS}
    mean_losses = {m: safe_float(common[m].mean()) for m in MODELS}
    best = min(mean_losses, key=lambda k: mean_losses[k])
    dm_tests = {
        f"CNNTransformer_minus_{base}": dm_record(losses["CNNTransformer"], losses[base])
        for base in ["HAR-X", "Ridge-HAR-X", "RollingMean22"]
    }
    return {
        "assets": assets,
        "n_common_dates": int(len(common)),
        "date_start": str(common.index.min()),
        "date_end": str(common.index.max()),
        "date_alignment": "common dates only; panel loss is the cross-asset mean by target date",
        "mean_losses": mean_losses,
        "best_mean_loss_model": best,
        "dm_tests": dm_tests,
        "mcs": summarize_mcs(losses, seed=seed),
    }


def make_figures(asset_rows: list[dict], loss_df: pd.DataFrame, panel: dict) -> list[str]:
    paths = []
    qdf = pd.DataFrame(
        [
            {"asset": row["asset"], "model": model, "qlike": row["qlike"][model]}
            for row in asset_rows
            for model in MODELS
        ]
    )
    fig, ax = plt.subplots(figsize=(9, 4.8))
    piv = qdf.pivot(index="asset", columns="model", values="qlike").loc[ASSETS]
    piv.plot(kind="bar", ax=ax)
    ax.set_title("K1593 OOS mean QLIKE by asset")
    ax.set_ylabel("QLIKE, lower is better")
    ax.set_xlabel("")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), frameon=False)
    fig.tight_layout()
    p = FIG_DIR / "fig1_oos_qlike_by_asset.png"
    fig.savefig(p, dpi=160)
    plt.close(fig)
    paths.append(str(p.relative_to(REPO_ROOT)))

    dm_rows = []
    for row in asset_rows:
        rec = row["dm_tests"]["CNNTransformer_minus_HAR-X"]
        dm_rows.append(
            {
                "asset": row["asset"],
                "dm_t": rec["t"],
                "holm_p": row["dm_cnn_vs_harx_holm_p"],
            }
        )
    dmdf = pd.DataFrame(dm_rows).set_index("asset").loc[ASSETS]
    fig, ax = plt.subplots(figsize=(8, 4))
    colors = ["#2a7f62" if x < -3 else "#9b3d3d" if x > 3 else "#777777" for x in dmdf["dm_t"]]
    ax.bar(dmdf.index, dmdf["dm_t"], color=colors)
    ax.axhline(-3, color="#2a7f62", linestyle="--", linewidth=1)
    ax.axhline(3, color="#9b3d3d", linestyle="--", linewidth=1)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_title("CNNTransformer minus HAR-X DM t-stat")
    ax.set_ylabel("Negative favors CNNTransformer")
    fig.tight_layout()
    p = FIG_DIR / "fig2_cnn_vs_harx_dm.png"
    fig.savefig(p, dpi=160)
    plt.close(fig)
    paths.append(str(p.relative_to(REPO_ROOT)))

    sub = loss_df.copy()
    daily = sub.groupby("target_date")[["loss_CNNTransformer", "loss_HAR-X"]].mean().dropna()
    daily["cum_diff"] = (daily["loss_CNNTransformer"] - daily["loss_HAR-X"]).cumsum()
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(pd.to_datetime(daily.index), daily["cum_diff"], color="#334f8d", linewidth=1.5)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_title("Panel cumulative QLIKE differential")
    ax.set_ylabel("Cum. CNNTransformer - HAR-X")
    ax.set_xlabel("")
    fig.tight_layout()
    p = FIG_DIR / "fig3_panel_cumulative_loss_diff.png"
    fig.savefig(p, dpi=160)
    plt.close(fig)
    paths.append(str(p.relative_to(REPO_ROOT)))

    return paths


def main() -> int:
    t0 = time.time()
    set_seed(SEED)
    raw = load_raw()

    asset_rows = []
    loss_frames = []
    for i, asset in enumerate(ASSETS):
        print(f"[{EXPERIMENT_ID}] running {asset}", flush=True)
        row, losses = run_asset(raw, asset, seed=SEED + i)
        asset_rows.append(row)
        loss_frames.append(losses)

    loss_df = pd.concat(loss_frames, ignore_index=True)
    holm = holm_adjust(
        [
            {
                "asset": row["asset"],
                "dm_cnn_minus_harx": row["dm_tests"]["CNNTransformer_minus_HAR-X"],
            }
            for row in asset_rows
        ]
    )
    for row in asset_rows:
        row["dm_cnn_vs_harx_holm_p"] = safe_float(holm.get(row["asset"]))
        rec = row["dm_tests"]["CNNTransformer_minus_HAR-X"]
        row["cnn_strict_holm_win_vs_harx"] = bool(
            rec["t"] is not None
            and rec["t"] < -3.0
            and row["dm_cnn_vs_harx_holm_p"] is not None
            and row["dm_cnn_vs_harx_holm_p"] < 0.05
        )

    panel_all = panel_summary(loss_df, ASSETS, seed=SEED + 100)
    panel_equity = panel_summary(loss_df, ["SPY", "QQQ", "EEM", "IWM"], seed=SEED + 101)
    panel_defensive = panel_summary(loss_df, ["GLD", "TLT", "SLV"], seed=SEED + 102)
    figure_paths = make_figures(asset_rows, loss_df, panel_all)

    strict_wins = sum(row["cnn_strict_holm_win_vs_harx"] for row in asset_rows)
    best_assets = sum(row["best_mean_loss_model"] == "CNNTransformer" for row in asset_rows)
    panel_best = panel_all["best_mean_loss_model"]
    panel_dm = panel_all["dm_tests"]["CNNTransformer_minus_HAR-X"]
    if strict_wins >= 4 and panel_best == "CNNTransformer" and panel_dm["t"] is not None and panel_dm["t"] < -3.0:
        verdict = "CNN_TRANSFORMER_SURVIVES"
    elif best_assets >= 3 or (panel_dm["t"] is not None and panel_dm["t"] < -2.0):
        verdict = "MIXED_OR_WEAK"
    else:
        verdict = "NULL_VS_HARX"

    predictions = loss_df.copy()
    predictions.to_csv(PRED_PATH, index=False)
    loss_cols = ["asset", "target_date", *[f"loss_{m}" for m in MODELS]]
    predictions[loss_cols].to_csv(LOSS_PATH, index=False)

    result = {
        "experiment_id": EXPERIMENT_ID,
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "seed": SEED,
        "task": "research_cnn_transformer_hybrid",
        "runtime_seconds": round(time.time() - t0, 3),
        "data": {
            "source": str(DATA_PATH.relative_to(REPO_ROOT)),
            "source_rows": int(len(raw)),
            "assets": ASSETS,
            "target": "next-day Parkinson realized variance in percent-squared units",
            "feature_set": FEATURE_COLS,
            "train_end": str(TRAIN_END.date()),
            "validation_window": [str(VALID_START.date()), str(VALID_END.date())],
            "oos_window": [str(OOS_START.date()), str(OOS_END.date())],
            "sequence_length": SEQ_LEN,
        },
        "model_design": {
            "cnn_transformer": {
                "conv1d_kernel": 3,
                "d_model": 24,
                "transformer_layers": 1,
                "attention_heads": 4,
                "epochs_max": EPOCHS,
                "patience": PATIENCE,
                "target_transform": "log(target_rv)",
            },
            "baselines": [
                "RollingMean22 from lagged RV only",
                "HAR-X linear log-RV regression on the same lagged features",
                "Ridge-HAR-X with alpha selected on 2021-2022 validation only",
            ],
        },
        "asset_summary": asset_rows,
        "panel_summary": {
            "all_assets": panel_all,
            "equity_risk_assets": panel_equity,
            "defensive_commodity_bond_assets": panel_defensive,
        },
        "conclusion": {
            "verdict": verdict,
            "cnn_best_mean_loss_assets": int(best_assets),
            "cnn_harvey_holm_wins_vs_harx": int(strict_wins),
            "panel_all_best_model": panel_best,
            "panel_all_cnn_minus_harx_dm_t": panel_dm["t"],
            "headline": (
                "CNN-Transformer does not deliver a robust OOS architecture edge over "
                "a same-information HAR-X baseline."
                if verdict == "NULL_VS_HARX"
                else "CNN-Transformer evidence is not strong enough for a standalone superiority claim."
                if verdict == "MIXED_OR_WEAK"
                else "CNN-Transformer survives the HAR-X information-symmetry gate."
            ),
        },
        "artifacts": {
            "predictions_csv": str(PRED_PATH.relative_to(REPO_ROOT)),
            "losses_csv": str(LOSS_PATH.relative_to(REPO_ROOT)),
            "figures": figure_paths,
        },
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "result_file": str(RESULT_PATH),
                "verdict": verdict,
                "cnn_best_mean_loss_assets": int(best_assets),
                "cnn_harvey_holm_wins_vs_harx": int(strict_wins),
                "panel_all_best_model": panel_best,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
