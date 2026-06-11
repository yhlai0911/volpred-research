"""
K1473: HAR vs lightweight deep learning across 1/5/22-day horizons.

This is an honest proxy version of the queued "5-minute RV" task. The repo
does not expose one canonical long-sample intraday RV panel for the requested
setup, so the target is future daily squared log returns averaged over horizon.
"""

from __future__ import annotations

import json
import random
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm

try:
    import torch
    import torch.nn as nn
except ImportError as exc:
    raise ImportError("PyTorch is required for K1473.") from exc

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


EXPERIMENT_ID = "K1473"
SEED = 42
ASSETS = {
    "SPY": REPO_ROOT / "experiments" / "k1206" / "data" / "SPY.csv",
    "QQQ": REPO_ROOT / "experiments" / "k1206" / "data" / "QQQ.csv",
}
HORIZONS = [1, 5, 22]
OOS_START = pd.Timestamp("2021-01-04")
SEQ_LEN = 22
TRAIN_EPOCHS = 8
BATCH_SIZE = 64
LEARNING_RATE = 1e-3
VAL_FRAC = 0.2
DEVICE = torch.device("cpu")

RESULTS_PATH = ROOT / "k1473_results.json"
FIG_PATH = ROOT / "k1473_horizon_qlike.png"


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


@dataclass
class ModelMetrics:
    qlike: float
    rel_improvement_pct: float
    dm_t_vs_har: float | None
    dm_p_vs_har: float | None


class LSTMForecaster(nn.Module):
    def __init__(self, hidden_size: int = 12) -> None:
        super().__init__()
        self.lstm = nn.LSTM(input_size=1, hidden_size=hidden_size, batch_first=True)
        self.head = nn.Sequential(
            nn.Linear(hidden_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        return self.head(out[:, -1, :]).squeeze(-1)


class TinyTransformerForecaster(nn.Module):
    def __init__(self, d_model: int = 12, nhead: int = 3) -> None:
        super().__init__()
        self.proj = nn.Linear(1, d_model)
        layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=32,
            dropout=0.0,
            batch_first=True,
            activation="gelu",
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=1)
        self.head = nn.Linear(d_model, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        z = self.proj(x)
        z = self.encoder(z)
        return self.head(z[:, -1, :]).squeeze(-1)


def load_asset(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)
    close = df["Close"].astype(float)
    log_ret = np.log(close).diff()
    rv = log_ret.pow(2)
    out = pd.DataFrame({"Date": df["Date"], "rv": rv})
    out["log_rv"] = np.log(out["rv"].clip(lower=1e-12))
    return out.dropna().reset_index(drop=True)


def forward_mean(series: pd.Series, horizon: int) -> pd.Series:
    shifted = [series.shift(-i) for i in range(horizon)]
    return pd.concat(shifted, axis=1).mean(axis=1)


def build_har_frame(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    panel = df.copy()
    panel["target_rv"] = forward_mean(panel["rv"], horizon)
    panel["log_target"] = np.log(panel["target_rv"].clip(lower=1e-12))
    panel["har_1"] = panel["rv"].shift(1)
    panel["har_5"] = panel["rv"].shift(1).rolling(5).mean()
    panel["har_22"] = panel["rv"].shift(1).rolling(22).mean()
    panel = panel.dropna().reset_index(drop=True)
    return panel


def make_sequences(panel: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    seqs, targets, dates = [], [], []
    values = panel["log_rv"].to_numpy()
    for idx in range(SEQ_LEN, len(panel)):
        seqs.append(values[idx - SEQ_LEN:idx])
        targets.append(panel.loc[idx, "log_target"])
        dates.append(panel.loc[idx, "Date"].to_datetime64())
    return (
        np.asarray(seqs, dtype=np.float32)[..., None],
        np.asarray(targets, dtype=np.float32),
        np.asarray(dates),
    )


def train_nn(
    model: nn.Module,
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
) -> nn.Module:
    model = model.to(DEVICE)
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    criterion = nn.MSELoss()

    train_ds = torch.utils.data.TensorDataset(
        torch.from_numpy(x_train), torch.from_numpy(y_train)
    )
    train_loader = torch.utils.data.DataLoader(
        train_ds, batch_size=BATCH_SIZE, shuffle=True
    )

    best_state = None
    best_val = float("inf")
    patience = 0

    for _ in range(TRAIN_EPOCHS):
        model.train()
        for xb, yb in train_loader:
            xb = xb.to(DEVICE)
            yb = yb.to(DEVICE)
            optimizer.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            optimizer.step()

        model.eval()
        with torch.no_grad():
            val_pred = model(torch.from_numpy(x_val).to(DEVICE)).cpu().numpy()
        val_loss = float(np.mean((val_pred - y_val) ** 2))
        if val_loss < best_val - 1e-8:
            best_val = val_loss
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            patience = 0
        else:
            patience += 1
            if patience >= 3:
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    return model.eval()


def predict_nn(model: nn.Module, x: np.ndarray) -> np.ndarray:
    with torch.no_grad():
        pred = model(torch.from_numpy(x).to(DEVICE)).cpu().numpy()
    return np.exp(pred).clip(min=1e-12)


def evaluate_asset_horizon(asset: str, raw_df: pd.DataFrame, horizon: int) -> dict:
    panel = build_har_frame(raw_df, horizon)

    har_train = panel[panel["Date"] < OOS_START].copy()
    har_test = panel[panel["Date"] >= OOS_START].copy()
    har_fit = sm.OLS(
        har_train["log_target"],
        sm.add_constant(har_train[["har_1", "har_5", "har_22"]], has_constant="add"),
    ).fit()
    har_pred = np.exp(
        har_fit.predict(
            sm.add_constant(har_test[["har_1", "har_5", "har_22"]], has_constant="add")
        )
    ).clip(lower=1e-12)
    actual = har_test["target_rv"].to_numpy()

    x_all, y_all, seq_dates = make_sequences(panel)
    train_mask = pd.to_datetime(seq_dates) < OOS_START
    test_mask = pd.to_datetime(seq_dates) >= OOS_START

    x_train_all = x_all[train_mask]
    y_train_all = y_all[train_mask]
    x_test = x_all[test_mask]
    y_test = y_all[test_mask]
    test_dates = pd.to_datetime(seq_dates[test_mask])

    split = int(np.floor(len(x_train_all) * (1 - VAL_FRAC)))
    x_train, x_val = x_train_all[:split], x_train_all[split:]
    y_train, y_val = y_train_all[:split], y_train_all[split:]

    mean = float(x_train.mean())
    std = float(x_train.std())
    std = std if std > 1e-8 else 1.0
    x_train = (x_train - mean) / std
    x_val = (x_val - mean) / std
    x_test = (x_test - mean) / std

    set_seed(SEED + horizon)
    lstm = train_nn(LSTMForecaster(), x_train, y_train, x_val, y_val)
    set_seed(SEED + 100 + horizon)
    transformer = train_nn(TinyTransformerForecaster(), x_train, y_train, x_val, y_val)

    lstm_pred = predict_nn(lstm, x_test)
    transformer_pred = predict_nn(transformer, x_test)

    har_eval = har_test[har_test["Date"].isin(test_dates)].copy()
    actual = har_eval["target_rv"].to_numpy()
    har_pred = np.asarray(har_pred[har_test["Date"].isin(test_dates)], dtype=float)

    har_loss = qlike_pointwise(actual, har_pred)
    har_qlike = qlike(actual, har_pred)

    results = {
        "sample": {
            "asset": asset,
            "horizon": horizon,
            "train_n": int(train_mask.sum()),
            "test_n": int(test_mask.sum()),
            "oos_start": str(test_dates.min().date()),
            "oos_end": str(test_dates.max().date()),
        },
        "models": {
            "har": asdict(
                ModelMetrics(
                    qlike=float(har_qlike),
                    rel_improvement_pct=0.0,
                    dm_t_vs_har=None,
                    dm_p_vs_har=None,
                )
            )
        },
    }

    for name, pred in [("lstm1", lstm_pred), ("tiny_transformer", transformer_pred)]:
        loss = qlike_pointwise(actual, pred)
        model_qlike = qlike(actual, pred)
        dm_t, dm_p = dm_test(loss, har_loss, h=horizon)
        rel = (har_qlike - model_qlike) / har_qlike * 100.0
        results["models"][name] = asdict(
            ModelMetrics(
                qlike=float(model_qlike),
                rel_improvement_pct=float(rel),
                dm_t_vs_har=float(dm_t),
                dm_p_vs_har=float(dm_p),
            )
        )

    return results


def make_chart(results: dict) -> None:
    fig, axes = plt.subplots(1, len(HORIZONS), figsize=(12, 4), sharey=True)
    colors = {"lstm1": "#bd632f", "tiny_transformer": "#2f6c8f"}

    for ax, horizon in zip(axes, HORIZONS):
        labels = []
        lstm_vals = []
        tr_vals = []
        for asset in ASSETS:
            labels.append(asset)
            model_block = results["assets"][asset][f"h{horizon}"]["models"]
            lstm_vals.append(model_block["lstm1"]["rel_improvement_pct"])
            tr_vals.append(model_block["tiny_transformer"]["rel_improvement_pct"])

        x = np.arange(len(labels))
        width = 0.32
        ax.bar(x - width / 2, lstm_vals, width=width, color=colors["lstm1"], label="LSTM1")
        ax.bar(
            x + width / 2,
            tr_vals,
            width=width,
            color=colors["tiny_transformer"],
            label="TinyTransformer",
        )
        ax.axhline(0.0, color="black", linewidth=1)
        ax.set_title(f"Horizon {horizon}")
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_ylabel("Relative QLIKE vs HAR (%)")

    axes[0].legend(frameon=False)
    fig.suptitle("K1473: HAR vs DL Across Horizons")
    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=160)
    plt.close(fig)


def main() -> None:
    set_seed(SEED)
    started = time.time()

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "HAR vs lightweight deep learning across horizons (honest proxy)",
        "task_origin": "research_vs_har_horizon",
        "seed": SEED,
        "oos_start": str(OOS_START.date()),
        "data_paths": {k: str(v.relative_to(REPO_ROOT)) for k, v in ASSETS.items()},
        "proxy_notice": (
            "Queued task requested 5-minute realized volatility. This run uses a daily "
            "squared-return proxy because no canonical long-sample intraday RV panel is "
            "pinned locally for the requested setup."
        ),
        "methodology": {
            "target": "future mean daily squared log return over horizon h",
            "horizons": HORIZONS,
            "baseline": "HAR OLS on lagged variance proxies (1/5/22)",
            "challengers": ["small LSTM", "tiny Transformer encoder"],
            "timing_rule": "all features/sequences stop at t-1; target begins at t",
            "evaluation": ["QLIKE", "Diebold-Mariano vs HAR"],
        },
        "assets": {},
    }

    strong_wins = []
    summary_rows = []

    for asset, path in ASSETS.items():
        raw_df = load_asset(path)
        asset_block = {}
        for horizon in HORIZONS:
            out = evaluate_asset_horizon(asset, raw_df, horizon)
            asset_block[f"h{horizon}"] = out
            for model_name in ["lstm1", "tiny_transformer"]:
                metrics = out["models"][model_name]
                summary_rows.append(
                    {
                        "asset": asset,
                        "horizon": horizon,
                        "model": model_name,
                        "rel_improvement_pct": metrics["rel_improvement_pct"],
                        "dm_t_vs_har": metrics["dm_t_vs_har"],
                    }
                )
                if metrics["rel_improvement_pct"] > 0 and metrics["dm_t_vs_har"] < -3.0:
                    strong_wins.append(
                        {
                            "asset": asset,
                            "horizon": horizon,
                            "model": model_name,
                            "rel_improvement_pct": metrics["rel_improvement_pct"],
                            "dm_t_vs_har": metrics["dm_t_vs_har"],
                        }
                    )
        results["assets"][asset] = asset_block

    results["summary_rows"] = summary_rows
    results["strong_wins_vs_har"] = strong_wins
    has_h1_win = any(row["horizon"] == 1 for row in strong_wins)
    has_longer_win = any(row["horizon"] in {5, 22} for row in strong_wins)
    if has_h1_win and has_longer_win:
        verdict = (
            "DL gains appear in this proxy setup, but not only at medium/long horizons; "
            "the queued boundary claim is not supported."
        )
    elif has_longer_win:
        verdict = (
            "Only medium/long-horizon DL wins appear in this proxy setup; the queued "
            "boundary claim receives partial support."
        )
    elif has_h1_win:
        verdict = (
            "Any strong DL gains already show up at h=1, so the queued "
            "'only medium/long horizon' claim is not supported."
        )
    else:
        verdict = "HAR dominates all tested horizons in this proxy setup."
    results["headline_verdict"] = verdict
    results["runtime_seconds"] = round(time.time() - started, 2)

    make_chart(results)
    RESULTS_PATH.write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
