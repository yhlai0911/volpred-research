#!/usr/bin/env python3
"""Image-rendered candlestick CNN vs numeric volatility baselines.

Research question:
Can a CNN trained on rasterized OHLCV candlestick images predict next-week
realized variance better than traditional numeric OHLC/HAR/GARCH baselines?

Guardrails:
- Frozen local OHLCV data; no network dependency.
- Feature date t uses only OHLCV information through t.
- Target is close-to-close realized variance over t+1..t+5.
- Seeds are fixed. CNN support requires panel DM t < -3 vs HAR-Ridge and
  broad asset-level support, not one-off visual wins.
"""
from __future__ import annotations

import json
import random
import sys
import time
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
from PIL import Image, ImageDraw
from arch import arch_model
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression, RidgeCV
from sklearn.metrics import accuracy_score, balanced_accuracy_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from statsmodels.stats.multitest import multipletests
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise  # noqa: E402


EXPERIMENT_ID = "research_image_rendered_candlestick_cnn_vol_vs"
SEED = 42
ASSETS = ["SPY", "QQQ", "IWM", "EEM", "GLD", "TLT", "SLV"]
DATA_PATH = (
    REPO_ROOT
    / "paper/leverage-direction/data/spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026.csv"
)
HERE = Path(__file__).resolve().parent
FIG_DIR = HERE / "figures"
DATA_DIR = HERE / "data"
RESULTS_PATH = HERE / f"{EXPERIMENT_ID}_results.json"
PRED_PATH = DATA_DIR / "oos_predictions.csv"
SUMMARY_PATH = DATA_DIR / "summary_table.csv"

WINDOW = 20
HORIZON = 5
IMAGE_SIZE = 48
SAMPLE_STRIDE = 2
TRAIN_END = pd.Timestamp("2018-12-31")
VALID_START = pd.Timestamp("2019-01-01")
VALID_END = pd.Timestamp("2020-12-31")
OOS_START = pd.Timestamp("2021-01-01")
OOS_END = pd.Timestamp("2026-06-30")
TRADING_DAYS = 252.0
VAR_FLOOR = 1e-8
VAR_CEIL = 10.0
EPOCHS = 12
PATIENCE = 3
BATCH_SIZE = 256

LITERATURE = [
    {
        "citation": "Bollerslev, Li, Li, and Li (2026), Journal of Financial Econometrics",
        "url": "https://academic.oup.com/jfec/article/24/1/nbaf023/8416248",
        "role": "numeric candlestick volatility estimator baseline; orthogonal to pixel-level image learning",
    },
    {
        "citation": "Duong et al. (2025), arXiv:2501.12239",
        "url": "https://arxiv.org/abs/2501.12239",
        "role": "pure candlestick chart image CNN direction and limitations",
    },
    {
        "citation": "Sezer and Ozbayoglu (2020), Financial Innovation",
        "url": "https://link.springer.com/article/10.1186/s40854-020-00187-0",
        "role": "candlestick/time-series image encoding with CNNs",
    },
    {
        "citation": "Dixon and Zeng (2026), Journal of Financial Markets",
        "url": "https://www.sciencedirect.com/science/article/pii/S1544612326001169",
        "role": "stock chart image-driven factors and asset-pricing relevance",
    },
]


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(1)
    try:
        torch.use_deterministic_algorithms(True)
    except Exception:
        pass


def safe_float(x: Any) -> float | None:
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


def adjusted_ohlcv(raw: pd.DataFrame, asset: str) -> pd.DataFrame:
    p = asset.lower().replace("-", "_")
    close = raw[f"{p}_close"].astype(float)
    adj_close = raw[f"{p}_adj_close"].astype(float)
    factor = (adj_close / close).replace([np.inf, -np.inf], np.nan)
    out = pd.DataFrame(
        {
            "open": raw[f"{p}_open"].astype(float) * factor,
            "high": raw[f"{p}_high"].astype(float) * factor,
            "low": raw[f"{p}_low"].astype(float) * factor,
            "close": adj_close,
            "volume": raw[f"{p}_volume"].astype(float),
        },
        index=raw.index,
    )
    out = out.replace([np.inf, -np.inf], np.nan).dropna()
    out = out[(out[["open", "high", "low", "close"]] > 0).all(axis=1)]
    return out


def realized_var_future(ret: pd.Series, pos: int, horizon: int) -> float | None:
    future = ret.iloc[pos + 1 : pos + 1 + horizon]
    if len(future) < horizon or future.isna().any():
        return None
    return float(future.pow(2).sum() * TRADING_DAYS / horizon)


def ohlc_numeric_features(frame: pd.DataFrame, ret: pd.Series, pos: int) -> dict[str, float]:
    win = frame.iloc[pos - WINDOW + 1 : pos + 1]
    rwin = ret.iloc[pos - WINDOW + 1 : pos + 1]
    eps = 1e-12
    log_hl = np.log(win["high"] / win["low"]).replace([np.inf, -np.inf], np.nan)
    log_co = np.log(win["close"] / win["open"]).replace([np.inf, -np.inf], np.nan)
    log_ho = np.log(win["high"] / win["open"]).replace([np.inf, -np.inf], np.nan)
    log_lo = np.log(win["low"] / win["open"]).replace([np.inf, -np.inf], np.nan)
    log_hc = np.log(win["high"] / win["close"]).replace([np.inf, -np.inf], np.nan)
    log_lc = np.log(win["low"] / win["close"]).replace([np.inf, -np.inf], np.nan)

    parkinson = (log_hl.pow(2) / (4.0 * np.log(2.0))).mean() * TRADING_DAYS
    gk = (0.5 * log_hl.pow(2) - (2.0 * np.log(2.0) - 1.0) * log_co.pow(2)).mean() * TRADING_DAYS
    rs = (log_hc * log_ho + log_lc * log_lo).mean() * TRADING_DAYS
    overnight = np.log(win["open"] / win["close"].shift(1)).replace([np.inf, -np.inf], np.nan)
    yz = (overnight.pow(2).mean() + 0.34 * log_co.pow(2).mean() + 0.66 * (rs / TRADING_DAYS)) * TRADING_DAYS

    volume = win["volume"].replace(0, np.nan)
    vol_log = np.log(volume)
    vol_z = (vol_log.iloc[-1] - vol_log.mean()) / (vol_log.std(ddof=1) + eps)

    return {
        "log_rv1": float(np.log(max(ret.iloc[pos] ** 2 * TRADING_DAYS, VAR_FLOOR))),
        "log_rv5": float(np.log(max(rwin.tail(5).pow(2).sum() * TRADING_DAYS / 5.0, VAR_FLOOR))),
        "log_rv20": float(np.log(max(rwin.pow(2).sum() * TRADING_DAYS / len(rwin), VAR_FLOOR))),
        "ret5": float(rwin.tail(5).sum()),
        "ret20": float(rwin.sum()),
        "abs_ret5": float(rwin.tail(5).abs().sum()),
        "neg_share20": float((rwin < 0).mean()),
        "log_parkinson20": float(np.log(max(parkinson, VAR_FLOOR))),
        "log_gk20": float(np.log(max(gk, VAR_FLOOR))),
        "log_rs20": float(np.log(max(rs, VAR_FLOOR))),
        "log_yz20": float(np.log(max(yz, VAR_FLOOR))),
        "volume_z20": float(np.nan_to_num(vol_z, nan=0.0, posinf=0.0, neginf=0.0)),
    }


FEATURE_COLS = [
    "log_rv1",
    "log_rv5",
    "log_rv20",
    "ret5",
    "ret20",
    "abs_ret5",
    "neg_share20",
    "log_parkinson20",
    "log_gk20",
    "log_rs20",
    "log_yz20",
    "volume_z20",
]


def render_candlestick(win: pd.DataFrame) -> np.ndarray:
    img = Image.new("RGB", (IMAGE_SIZE, IMAGE_SIZE), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    pad = 3
    vol_band = 8
    price_top = pad
    price_bottom = IMAGE_SIZE - pad - vol_band
    pmin = float(win["low"].min())
    pmax = float(win["high"].max())
    prange = max(pmax - pmin, 1e-9)
    step = (IMAGE_SIZE - 2 * pad) / len(win)
    body_half = max(1, int(step * 0.35))
    vmax = float(win["volume"].replace(0, np.nan).max())
    vmax = vmax if np.isfinite(vmax) and vmax > 0 else 1.0

    def y_price(price: float) -> int:
        y = price_top + (pmax - price) / prange * (price_bottom - price_top)
        return int(np.clip(round(y), price_top, price_bottom))

    for j, row in enumerate(win.itertuples(index=False)):
        x = int(round(pad + (j + 0.5) * step))
        o = float(row.open)
        h = float(row.high)
        l = float(row.low)
        c = float(row.close)
        v = float(row.volume)
        color = (36, 150, 85) if c >= o else (190, 65, 65)
        y_o, y_h, y_l, y_c = y_price(o), y_price(h), y_price(l), y_price(c)
        draw.line((x, y_h, x, y_l), fill=(35, 35, 35), width=1)
        y0, y1 = sorted((y_o, y_c))
        if y0 == y1:
            draw.line((x - body_half, y0, x + body_half, y1), fill=color, width=1)
        else:
            draw.rectangle((x - body_half, y0, x + body_half, y1), outline=color, fill=color)
        vh = int(np.clip(round((v / vmax) * (vol_band - 1)), 0, vol_band - 1))
        draw.rectangle(
            (x - body_half, IMAGE_SIZE - pad - vh, x + body_half, IMAGE_SIZE - pad),
            fill=(150, 170, 205),
        )
    return np.asarray(img, dtype=np.uint8).transpose(2, 0, 1)


def garch_forecasts(frame: pd.DataFrame, ret: pd.Series, train_end: pd.Timestamp) -> pd.Series:
    train = (ret.loc[:train_end] * 100.0).dropna()
    if len(train) < 500:
        return pd.Series(index=frame.index, dtype=float)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = arch_model(train, mean="Zero", vol="GARCH", p=1, q=1, dist="normal", rescale=False).fit(
            disp="off"
        )
    p = fit.params
    omega = float(p.get("omega", np.nan))
    alpha = float(p.get("alpha[1]", np.nan))
    beta = float(p.get("beta[1]", np.nan))
    if not np.isfinite([omega, alpha, beta]).all() or alpha + beta >= 0.999:
        beta = min(max(beta, 0.0), 0.995)
        alpha = min(max(alpha, 0.0), 0.20)
        omega = max(omega, 1e-8)

    r_pct = (ret * 100.0).reindex(frame.index)
    h = pd.Series(index=frame.index, dtype=float)
    first_var = float(train.var()) if len(train) else 1.0
    prev_h = max(first_var, 1e-8)
    prev_r2 = max(first_var, 1e-8)
    for dt in frame.index:
        h_t = omega + alpha * prev_r2 + beta * prev_h
        h.loc[dt] = h_t
        r = r_pct.loc[dt]
        if np.isfinite(r):
            prev_r2 = float(r * r)
        prev_h = h_t

    forecasts = pd.Series(index=frame.index, dtype=float)
    ab = alpha + beta
    for dt in frame.index:
        r = r_pct.loc[dt]
        h_now = h.loc[dt]
        if not np.isfinite(r) or not np.isfinite(h_now):
            continue
        h_next = omega + alpha * float(r * r) + beta * float(h_now)
        vals = [h_next]
        cur = h_next
        for _ in range(1, HORIZON):
            cur = omega + ab * cur
            vals.append(cur)
        forecasts.loc[dt] = float(np.sum(vals) / 10000.0 * TRADING_DAYS / HORIZON)
    return forecasts.clip(lower=VAR_FLOOR, upper=VAR_CEIL)


def build_dataset(raw: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    images: list[np.ndarray] = []
    feature_rows: list[dict[str, Any]] = []
    numeric_rows: list[list[float]] = []
    for asset in ASSETS:
        frame = adjusted_ohlcv(raw, asset)
        ret = np.log(frame["close"] / frame["close"].shift(1))
        garch_fc = garch_forecasts(frame, ret, TRAIN_END)
        for pos in range(WINDOW - 1, len(frame) - HORIZON, SAMPLE_STRIDE):
            feature_date = frame.index[pos]
            target_date = frame.index[pos + HORIZON]
            if feature_date > OOS_END:
                continue
            actual = realized_var_future(ret, pos, HORIZON)
            if actual is None or not np.isfinite(actual) or actual <= 0:
                continue
            win = frame.iloc[pos - WINDOW + 1 : pos + 1]
            feats = ohlc_numeric_features(frame, ret, pos)
            if not all(np.isfinite(feats[c]) for c in FEATURE_COLS):
                continue
            garch_var = safe_float(garch_fc.loc[feature_date])
            images.append(render_candlestick(win))
            numeric_rows.append([feats[c] for c in FEATURE_COLS])
            feature_rows.append(
                {
                    "asset": asset,
                    "feature_date": feature_date,
                    "target_date": target_date,
                    "actual_var": float(np.clip(actual, VAR_FLOOR, VAR_CEIL)),
                    "rolling22_var": float(np.clip(np.exp(feats["log_rv20"]), VAR_FLOOR, VAR_CEIL)),
                    "garch_var": float(np.clip(garch_var if garch_var is not None else np.nan, VAR_FLOOR, VAR_CEIL)),
                    **feats,
                }
            )
    X_img = np.stack(images).astype(np.uint8)
    X_num = np.asarray(numeric_rows, dtype=np.float32)
    meta = pd.DataFrame(feature_rows)
    return X_img, X_num, meta


class SmallCandleCNN(nn.Module):
    def __init__(self, n_classes: int = 3) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(3, 12, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(12, 24, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(24, 40, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d((1, 1)),
            nn.Flatten(),
            nn.Dropout(0.15),
            nn.Linear(40, n_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


def train_cnn_classifier(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
) -> SmallCandleCNN:
    device = torch.device("cpu")
    model = SmallCandleCNN(n_classes=3).to(device)
    counts = np.bincount(y_train, minlength=3).astype(float)
    weights = counts.sum() / np.maximum(counts, 1.0)
    weights = torch.tensor(weights / weights.mean(), dtype=torch.float32)
    criterion = nn.CrossEntropyLoss(weight=weights)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    train_ds = TensorDataset(
        torch.from_numpy(X_train).float() / 255.0,
        torch.from_numpy(y_train).long(),
    )
    val_x = torch.from_numpy(X_val).float().to(device) / 255.0
    val_y = torch.from_numpy(y_val).long().to(device)
    loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)
    best_state = None
    best_loss = float("inf")
    patience_left = PATIENCE
    for _epoch in range(EPOCHS):
        model.train()
        for xb, yb in loader:
            xb = xb.to(device)
            yb = yb.to(device)
            opt.zero_grad(set_to_none=True)
            loss = criterion(model(xb), yb)
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            val_loss = float(criterion(model(val_x), val_y).item())
        if val_loss < best_loss - 1e-4:
            best_loss = val_loss
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            patience_left = PATIENCE
        else:
            patience_left -= 1
            if patience_left <= 0:
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    return model


def predict_cnn_proba(model: SmallCandleCNN, X: np.ndarray) -> np.ndarray:
    model.eval()
    preds: list[np.ndarray] = []
    loader = DataLoader(torch.from_numpy(X).float() / 255.0, batch_size=BATCH_SIZE, shuffle=False)
    with torch.no_grad():
        for xb in loader:
            logits = model(xb)
            preds.append(torch.softmax(logits, dim=1).cpu().numpy())
    return np.vstack(preds)


def expected_var_from_probs(proba: np.ndarray, class_medians: np.ndarray) -> np.ndarray:
    return np.clip(proba @ class_medians, VAR_FLOOR, VAR_CEIL)


def bucketize(values: np.ndarray, q: np.ndarray) -> np.ndarray:
    return np.digitize(values, q, right=False).astype(int)


def eval_forecasts(pred: pd.DataFrame, model: str, actual_col: str = "actual_var") -> dict[str, Any]:
    actual = pred[actual_col].to_numpy(dtype=float)
    forecast = pred[f"pred_{model}"].to_numpy(dtype=float)
    losses = qlike_pointwise(actual, forecast)
    out = {
        "model": model,
        "mean_qlike": float(np.mean(losses)),
        "median_qlike": float(np.median(losses)),
        "log_mse": float(np.mean((np.log(forecast) - np.log(actual)) ** 2)),
        "spearman": safe_float(spearmanr(np.log(forecast), np.log(actual)).correlation),
        "bucket_accuracy": float(accuracy_score(pred["bucket_actual"], pred[f"bucket_{model}"])),
        "bucket_balanced_accuracy": float(
            balanced_accuracy_score(pred["bucket_actual"], pred[f"bucket_{model}"])
        ),
    }
    return out


def dm_record(loss1: np.ndarray, loss2: np.ndarray, h: int = HORIZON) -> dict[str, float | None]:
    t, p = dm_test(loss1, loss2, h=h)
    return {"t": safe_float(t), "p": safe_float(p)}


def summarize_oos(pred: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    models = ["CNNImage", "NumericLogit", "HAR_Ridge", "RollingMean20", "GARCH11"]
    pred = pred.copy()
    for model in models:
        pred[f"loss_{model}"] = qlike_pointwise(pred["actual_var"], pred[f"pred_{model}"])
    by_asset: list[dict[str, Any]] = []
    for asset, sub in pred.groupby("asset"):
        row: dict[str, Any] = {"asset": asset, "n_oos": int(len(sub))}
        model_metrics = {m: eval_forecasts(sub, m) for m in models}
        row["metrics"] = model_metrics
        row["best_mean_qlike_model"] = min(models, key=lambda m: model_metrics[m]["mean_qlike"])
        row["dm_cnn_minus_har"] = dm_record(
            sub["loss_CNNImage"].to_numpy(), sub["loss_HAR_Ridge"].to_numpy()
        )
        row["dm_cnn_minus_numeric_logit"] = dm_record(
            sub["loss_CNNImage"].to_numpy(), sub["loss_NumericLogit"].to_numpy()
        )
        by_asset.append(row)

    pvals = [r["dm_cnn_minus_har"]["p"] for r in by_asset]
    valid = [p if p is not None else 1.0 for p in pvals]
    _, holm, _, _ = multipletests(valid, method="holm")
    for r, hp in zip(by_asset, holm):
        r["dm_cnn_minus_har"]["holm_p"] = safe_float(hp)
        t = r["dm_cnn_minus_har"]["t"]
        r["strict_cnn_win_vs_har"] = bool(t is not None and t < -3.0 and hp < 0.05)

    daily = pred.groupby("target_date")[[f"loss_{m}" for m in models]].mean().dropna()
    panel_metrics = {m: eval_forecasts(pred, m) for m in models}
    panel = {
        "common_target_dates": int(len(daily)),
        "metrics": panel_metrics,
        "best_mean_qlike_model": min(models, key=lambda m: panel_metrics[m]["mean_qlike"]),
        "dm_cnn_minus_har": dm_record(daily["loss_CNNImage"].to_numpy(), daily["loss_HAR_Ridge"].to_numpy()),
        "dm_cnn_minus_numeric_logit": dm_record(
            daily["loss_CNNImage"].to_numpy(), daily["loss_NumericLogit"].to_numpy()
        ),
    }

    summary_rows = []
    for r in by_asset:
        row = {
            "asset": r["asset"],
            "n_oos": r["n_oos"],
            "best_mean_qlike_model": r["best_mean_qlike_model"],
            "cnn_mean_qlike": r["metrics"]["CNNImage"]["mean_qlike"],
            "har_mean_qlike": r["metrics"]["HAR_Ridge"]["mean_qlike"],
            "numeric_logit_mean_qlike": r["metrics"]["NumericLogit"]["mean_qlike"],
            "garch_mean_qlike": r["metrics"]["GARCH11"]["mean_qlike"],
            "cnn_bucket_accuracy": r["metrics"]["CNNImage"]["bucket_accuracy"],
            "numeric_logit_bucket_accuracy": r["metrics"]["NumericLogit"]["bucket_accuracy"],
            "dm_cnn_minus_har_t": r["dm_cnn_minus_har"]["t"],
            "dm_cnn_minus_har_p": r["dm_cnn_minus_har"]["p"],
            "dm_cnn_minus_har_holm_p": r["dm_cnn_minus_har"]["holm_p"],
            "strict_cnn_win_vs_har": r["strict_cnn_win_vs_har"],
        }
        summary_rows.append(row)
    return {"by_asset": by_asset, "panel": panel}, pd.DataFrame(summary_rows)


def make_figures(pred: pd.DataFrame, summary_table: pd.DataFrame, example_images: np.ndarray) -> list[str]:
    FIG_DIR.mkdir(exist_ok=True)
    paths: list[str] = []
    pred = pred.copy()
    for model in ["CNNImage", "HAR_Ridge"]:
        loss_col = f"loss_{model}"
        if loss_col not in pred.columns:
            pred[loss_col] = qlike_pointwise(pred["actual_var"], pred[f"pred_{model}"])

    plt.figure(figsize=(9, 5))
    colors = ["#2c7fb8" if x < 0 else "#d95f0e" for x in summary_table["dm_cnn_minus_har_t"]]
    plt.bar(summary_table["asset"], summary_table["dm_cnn_minus_har_t"], color=colors)
    plt.axhline(-3.0, color="black", linestyle="--", linewidth=1, label="Harvey -3")
    plt.axhline(3.0, color="black", linestyle="--", linewidth=1)
    plt.ylabel("DM t-stat: CNN image QLIKE loss minus HAR-Ridge")
    plt.title("Asset-level CNN image vs numeric HAR-Ridge")
    plt.legend()
    plt.tight_layout()
    path = FIG_DIR / "dm_cnn_vs_har_by_asset.png"
    plt.savefig(path, dpi=160)
    plt.close()
    paths.append(str(path))

    daily = pred.groupby("target_date")[["loss_CNNImage", "loss_HAR_Ridge"]].mean().dropna()
    daily["cum_diff"] = (daily["loss_CNNImage"] - daily["loss_HAR_Ridge"]).cumsum()
    plt.figure(figsize=(9, 5))
    plt.plot(pd.to_datetime(daily.index), daily["cum_diff"], color="#756bb1")
    plt.axhline(0.0, color="black", linewidth=1)
    plt.ylabel("Cumulative QLIKE loss diff: CNN - HAR-Ridge")
    plt.title("Panel cumulative loss difference")
    plt.tight_layout()
    path = FIG_DIR / "panel_cumulative_loss_diff.png"
    plt.savefig(path, dpi=160)
    plt.close()
    paths.append(str(path))

    n = min(6, len(example_images))
    if n > 0:
        fig, axes = plt.subplots(1, n, figsize=(2.1 * n, 2.2))
        if n == 1:
            axes = [axes]
        for ax, arr in zip(axes, example_images[:n]):
            ax.imshow(arr.transpose(1, 2, 0))
            ax.axis("off")
        fig.suptitle("Rendered 20-day OHLCV candlestick images")
        plt.tight_layout()
        path = FIG_DIR / "example_candlestick_images.png"
        plt.savefig(path, dpi=160)
        plt.close()
        paths.append(str(path))
    return paths


def _json_clean(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _json_clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_clean(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        val = float(obj)
        return None if not np.isfinite(val) else val
    if isinstance(obj, float) and not np.isfinite(obj):
        return None
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    return obj


def main() -> None:
    start = time.time()
    set_seed(SEED)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    raw = load_raw()
    X_img, X_num, meta = build_dataset(raw)
    meta["log_actual_var"] = np.log(meta["actual_var"].clip(lower=VAR_FLOOR))

    train_mask = meta["feature_date"] <= TRAIN_END
    val_mask = (meta["feature_date"] >= VALID_START) & (meta["feature_date"] <= VALID_END)
    oos_mask = (meta["target_date"] >= OOS_START) & (meta["target_date"] <= OOS_END)
    if train_mask.sum() < 1000 or val_mask.sum() < 250 or oos_mask.sum() < 500:
        raise RuntimeError("Insufficient train/validation/OOS rows after dataset construction.")

    train_log = meta.loc[train_mask, "log_actual_var"].to_numpy()
    bucket_q = np.quantile(train_log, [1 / 3, 2 / 3])
    y_all = bucketize(meta["log_actual_var"].to_numpy(), bucket_q)
    class_medians = np.array(
        [
            np.median(meta.loc[train_mask & (y_all == k), "actual_var"])
            for k in range(3)
        ],
        dtype=float,
    )
    class_medians = np.clip(class_medians, VAR_FLOOR, VAR_CEIL)

    idx_train = np.where(train_mask.to_numpy())[0]
    idx_val = np.where(val_mask.to_numpy())[0]
    idx_oos = np.where(oos_mask.to_numpy())[0]

    # Numeric models.
    numeric_logit = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=1000, class_weight="balanced"),
    )
    numeric_logit.fit(X_num[idx_train], y_all[idx_train])
    ridge = make_pipeline(StandardScaler(), RidgeCV(alphas=np.logspace(-4, 3, 20)))
    ridge.fit(X_num[idx_train], meta.loc[train_mask, "log_actual_var"].to_numpy())

    # Image CNN classifier.
    cnn = train_cnn_classifier(X_img[idx_train], y_all[idx_train], X_img[idx_val], y_all[idx_val])

    pred = meta.iloc[idx_oos].copy().reset_index(drop=True)
    pred["bucket_actual"] = y_all[idx_oos]
    proba_cnn = predict_cnn_proba(cnn, X_img[idx_oos])
    proba_num = numeric_logit.predict_proba(X_num[idx_oos])
    pred["pred_CNNImage"] = expected_var_from_probs(proba_cnn, class_medians)
    pred["pred_NumericLogit"] = expected_var_from_probs(proba_num, class_medians)
    pred["pred_HAR_Ridge"] = np.clip(np.exp(ridge.predict(X_num[idx_oos])), VAR_FLOOR, VAR_CEIL)
    pred["pred_RollingMean20"] = pred["rolling22_var"].clip(lower=VAR_FLOOR, upper=VAR_CEIL)
    pred["pred_GARCH11"] = pred["garch_var"].fillna(pred["rolling22_var"]).clip(lower=VAR_FLOOR, upper=VAR_CEIL)

    for model in ["CNNImage", "NumericLogit", "HAR_Ridge", "RollingMean20", "GARCH11"]:
        pred[f"bucket_{model}"] = bucketize(np.log(pred[f"pred_{model}"].to_numpy()), bucket_q)

    pred.to_csv(PRED_PATH, index=False)
    summary, summary_table = summarize_oos(pred)
    summary_table.to_csv(SUMMARY_PATH, index=False)
    figures = make_figures(pred, summary_table, X_img[idx_oos[:6]])

    strict_wins = sum(r["strict_cnn_win_vs_har"] for r in summary["by_asset"])
    panel_t = summary["panel"]["dm_cnn_minus_har"]["t"]
    panel_best = summary["panel"]["best_mean_qlike_model"]
    if strict_wins >= 4 and panel_best == "CNNImage" and panel_t is not None and panel_t < -3.0:
        verdict = "CNN_IMAGE_SURVIVES_HAR_GATE"
        conclusion = (
            "The rasterized candlestick CNN survives the strict HAR-Ridge information gate."
        )
    elif strict_wins > 0:
        verdict = "PARTIAL_SINGLE_ASSET_ONLY"
        conclusion = (
            "The image CNN has isolated asset-level wins but does not survive the panel HAR-Ridge gate."
        )
    else:
        verdict = "NULL_VS_NUMERIC_BASELINES"
        conclusion = (
            "Rasterized candlestick images do not deliver a robust OOS edge over numeric OHLC/HAR/GARCH baselines."
        )

    split_counts = {
        "train": int(train_mask.sum()),
        "validation": int(val_mask.sum()),
        "oos": int(oos_mask.sum()),
    }
    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Image-rendered candlestick CNN vs numeric volatility baselines",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runtime_seconds": safe_float(time.time() - start),
        "seed": SEED,
        "verdict": verdict,
        "conclusion": conclusion,
        "literature": LITERATURE,
        "data": {
            "source": str(DATA_PATH),
            "assets": ASSETS,
            "features": FEATURE_COLS,
            "sample_stride": SAMPLE_STRIDE,
            "image_size": IMAGE_SIZE,
            "window_days": WINDOW,
            "horizon_days": HORIZON,
            "split_counts": split_counts,
            "train_end": TRAIN_END.date().isoformat(),
            "validation_start": VALID_START.date().isoformat(),
            "validation_end": VALID_END.date().isoformat(),
            "oos_start": OOS_START.date().isoformat(),
            "oos_end": OOS_END.date().isoformat(),
            "bucket_logvar_quantiles": [float(x) for x in bucket_q],
            "class_median_variances": [float(x) for x in class_medians],
        },
        "models": {
            "CNNImage": "3-channel 48x48 rasterized 20-day OHLCV candlestick image classifier; class-probability expected variance forecast.",
            "NumericLogit": "multinomial logistic regression on numeric OHLC/HAR/range features; same RV buckets.",
            "HAR_Ridge": "Ridge regression on numeric OHLC/HAR/range features predicting log next-week variance.",
            "RollingMean20": "lagged 20-day close-to-close realized variance.",
            "GARCH11": "fixed-parameter GARCH(1,1) estimated pre-OOS, recursively filtered through OOS.",
        },
        "primary_gate": {
            "strict_asset_wins_vs_har": int(strict_wins),
            "panel_best_mean_qlike_model": panel_best,
            "panel_dm_cnn_minus_har_t": summary["panel"]["dm_cnn_minus_har"]["t"],
            "panel_dm_cnn_minus_har_p": summary["panel"]["dm_cnn_minus_har"]["p"],
            "support_rule": "support only if strict_asset_wins_vs_har >= 4, panel best model is CNNImage, and panel DM t < -3",
        },
        "summary": summary,
        "figures": figures,
        "output_files": {
            "predictions": str(PRED_PATH),
            "summary_table": str(SUMMARY_PATH),
        },
        "limitations": [
            "This is a daily OHLCV image pilot, not high-frequency realized-volatility modelling.",
            "CNN uses bucket classification and maps class probabilities to expected variance, so QLIKE forecasts are deliberately coarse.",
            "The visual representation may discard precise numerical scale information that numeric OHLC features retain.",
            "No transaction-cost or trading strategy claim is made.",
        ],
    }
    RESULTS_PATH.write_text(json.dumps(_json_clean(results), indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            _json_clean(
                {
                    "experiment_id": EXPERIMENT_ID,
                    "verdict": verdict,
                    "strict_wins_vs_har": strict_wins,
                    "panel_best": panel_best,
                    "panel_dm_cnn_minus_har": summary["panel"]["dm_cnn_minus_har"],
                    "conclusion": conclusion,
                }
            ),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
