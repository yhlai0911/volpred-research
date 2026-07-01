#!/usr/bin/env python3
"""K1595: Multi-Transformer-lite volatility forecast adjudication.

This is a bounded replication/adjudication of the Multi-Transformer volatility
forecasting idea. It uses local frozen yfinance-style OHLCV data only and asks a
strict question: does a small pooled Transformer ensemble add OOS QLIKE value
over simple HAR/Ridge/EWMA/GJR baselines when every forecast uses information
available at t-1?
"""

from __future__ import annotations

import json
import math
import random
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
from scipy import stats
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from volpred.stats.model_evaluation import dm_test, qlike_pointwise, spearman_corr  # noqa: E402


EXPERIMENT_ID = "k1595"
SEED = 1595
ASSETS = ["SPY", "QQQ", "IWM", "XLF", "XLE", "XLU"]
DATA_PATH = ROOT / "experiments" / "k1552" / "data" / "prices.parquet"
OUT_DIR = ROOT / "experiments" / EXPERIMENT_ID
FIG_DIR = OUT_DIR / "figures"

TRAIN_START = "2005-01-01"
TRAIN_END = "2011-12-31"
VALID_START = "2012-01-01"
VALID_END = "2015-12-31"
OOS_START = "2016-01-01"
OOS_END = "2026-06-26"

LOOKBACK = 22
EPS = 1e-10
EWMA_LAMBDA = 0.94
DEVICE = torch.device("cpu")

RAW_FEATURES = [
    "log_r2",
    "log_rv5",
    "log_rv22",
    "log_rv66",
    "abs_ret",
    "signed_ret",
    "range_log",
    "vix_log",
    "vix_chg",
    "spy_log_r2",
]

TABULAR_FEATURES = [
    "log_r2_l1",
    "log_rv5_l1",
    "log_rv22_l1",
    "log_rv66_l1",
    "abs_ret_l1",
    "signed_ret_l1",
    "range_log_l1",
    "vix_log_l1",
    "vix_chg_l1",
    "spy_log_r2_l1",
]

MODEL_ORDER = [
    "EWMA94",
    "HAR_LogOLS",
    "RidgeFactors",
    "GJR_GARCH_Annual",
    "TransformerLite",
    "MultiTransformerLite",
]


@dataclass
class SequenceData:
    x: np.ndarray
    y: np.ndarray
    asset_id: np.ndarray
    dates: np.ndarray
    assets: np.ndarray
    target_var: np.ndarray
    returns: np.ndarray


class TransformerVolRegressor(nn.Module):
    def __init__(
        self,
        input_dim: int,
        n_assets: int,
        lookback: int,
        d_model: int = 24,
        nhead: int = 4,
        dim_feedforward: int = 64,
        dropout: float = 0.10,
    ) -> None:
        super().__init__()
        self.input_proj = nn.Linear(input_dim, d_model)
        self.asset_emb = nn.Embedding(n_assets, d_model)
        self.pos_emb = nn.Parameter(torch.zeros(1, lookback, d_model))
        layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=dim_feedforward,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=1)
        self.head = nn.Sequential(
            nn.LayerNorm(d_model),
            nn.Linear(d_model, 16),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(16, 1),
        )

    def forward(self, x: torch.Tensor, asset_id: torch.Tensor) -> torch.Tensor:
        z = self.input_proj(x)
        z = z + self.asset_emb(asset_id).unsqueeze(1) + self.pos_emb
        z = self.encoder(z)
        pooled = z.mean(dim=1)
        return self.head(pooled).squeeze(-1)


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(1)


def to_float(x: object) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def read_prices() -> pd.DataFrame:
    if not DATA_PATH.exists():
        raise FileNotFoundError(DATA_PATH)
    prices = pd.read_parquet(DATA_PATH)
    prices.index = pd.to_datetime(prices.index)
    prices = prices.sort_index()
    return prices


def get_field(prices: pd.DataFrame, field: str) -> pd.DataFrame:
    if not isinstance(prices.columns, pd.MultiIndex):
        raise ValueError("Expected MultiIndex columns in frozen prices parquet.")
    out = prices[field].copy()
    out.index = pd.to_datetime(out.index)
    return out.sort_index()


def build_panels(prices: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    close = get_field(prices, "Close")
    high = get_field(prices, "High")
    low = get_field(prices, "Low")
    vix = close["^VIX"].replace(0, np.nan).ffill()
    vix_log = np.log(vix.clip(lower=EPS))
    vix_chg = vix_log.diff()
    spy_ret = np.log(close["SPY"]).diff()
    spy_log_r2 = np.log((spy_ret**2).clip(lower=EPS))

    panels: Dict[str, pd.DataFrame] = {}
    for asset in ASSETS:
        px = close[asset].replace(0, np.nan).ffill()
        ret = np.log(px).diff()
        r2 = (ret**2).clip(lower=EPS)
        range_var = (np.log(high[asset] / low[asset]) ** 2 / (4.0 * np.log(2))).replace(
            [np.inf, -np.inf], np.nan
        )
        df = pd.DataFrame(index=close.index)
        df["ret"] = ret
        df["target_var"] = r2
        df["target_log_var"] = np.log(r2.clip(lower=EPS))
        df["log_r2"] = np.log(r2.clip(lower=EPS))
        df["log_rv5"] = np.log(r2.rolling(5, min_periods=5).mean().clip(lower=EPS))
        df["log_rv22"] = np.log(r2.rolling(22, min_periods=22).mean().clip(lower=EPS))
        df["log_rv66"] = np.log(r2.rolling(66, min_periods=66).mean().clip(lower=EPS))
        df["abs_ret"] = ret.abs()
        df["signed_ret"] = ret
        df["range_log"] = np.log(range_var.clip(lower=EPS))
        df["vix_log"] = vix_log
        df["vix_chg"] = vix_chg
        df["spy_log_r2"] = spy_log_r2

        # Tabular baselines predict date t from explicitly lagged date t-1 features.
        for col in RAW_FEATURES:
            df[f"{col}_l1"] = df[col].shift(1)
        panels[asset] = df.replace([np.inf, -np.inf], np.nan)
    return panels


def build_sequences(panels: Dict[str, pd.DataFrame]) -> SequenceData:
    xs: List[np.ndarray] = []
    ys: List[float] = []
    asset_ids: List[int] = []
    dates: List[pd.Timestamp] = []
    assets: List[str] = []
    target_vars: List[float] = []
    returns: List[float] = []

    for asset_id, asset in enumerate(ASSETS):
        df = panels[asset]
        feats = df[RAW_FEATURES].to_numpy(dtype=np.float32)
        y = df["target_log_var"].to_numpy(dtype=np.float32)
        tv = df["target_var"].to_numpy(dtype=np.float64)
        ret = df["ret"].to_numpy(dtype=np.float64)
        idx = df.index.to_numpy()
        for i in range(LOOKBACK, len(df)):
            target_date = pd.Timestamp(idx[i])
            if target_date < pd.Timestamp(TRAIN_START) or target_date > pd.Timestamp(OOS_END):
                continue
            window = feats[i - LOOKBACK : i]
            if not np.isfinite(window).all():
                continue
            if not np.isfinite(y[i]) or not np.isfinite(tv[i]) or not np.isfinite(ret[i]):
                continue
            xs.append(window)
            ys.append(float(y[i]))
            asset_ids.append(asset_id)
            dates.append(target_date)
            assets.append(asset)
            target_vars.append(float(tv[i]))
            returns.append(float(ret[i]))

    return SequenceData(
        x=np.asarray(xs, dtype=np.float32),
        y=np.asarray(ys, dtype=np.float32),
        asset_id=np.asarray(asset_ids, dtype=np.int64),
        dates=np.asarray(dates, dtype="datetime64[ns]"),
        assets=np.asarray(assets, dtype=object),
        target_var=np.asarray(target_vars, dtype=np.float64),
        returns=np.asarray(returns, dtype=np.float64),
    )


def mask_dates(dates: np.ndarray, start: str, end: str) -> np.ndarray:
    d = pd.to_datetime(dates)
    return np.asarray((d >= pd.Timestamp(start)) & (d <= pd.Timestamp(end)), dtype=bool)


def standardize_sequences(
    seq: SequenceData,
    train_mask: np.ndarray,
) -> Tuple[np.ndarray, float, float, np.ndarray, np.ndarray]:
    flat = seq.x[train_mask].reshape(-1, seq.x.shape[-1])
    x_mean = np.nanmean(flat, axis=0).astype(np.float32)
    x_std = np.nanstd(flat, axis=0).astype(np.float32)
    x_std[x_std < 1e-6] = 1.0
    x_scaled = (seq.x - x_mean) / x_std

    y_mean = float(np.mean(seq.y[train_mask]))
    y_std = float(np.std(seq.y[train_mask]))
    if y_std < 1e-6:
        y_std = 1.0
    y_scaled = (seq.y - y_mean) / y_std
    return x_scaled.astype(np.float32), y_mean, y_std, x_mean, x_std


def train_transformer(
    x_train: np.ndarray,
    y_train: np.ndarray,
    aid_train: np.ndarray,
    x_valid: np.ndarray,
    y_valid: np.ndarray,
    aid_valid: np.ndarray,
    *,
    seed: int,
    max_epochs: int = 55,
    patience: int = 9,
) -> Tuple[TransformerVolRegressor, Dict[str, float]]:
    set_seed(seed)
    model = TransformerVolRegressor(
        input_dim=x_train.shape[-1],
        n_assets=len(ASSETS),
        lookback=LOOKBACK,
    ).to(DEVICE)
    opt = torch.optim.AdamW(model.parameters(), lr=0.0025, weight_decay=1e-4)
    loss_fn = nn.MSELoss()

    train_ds = TensorDataset(
        torch.tensor(x_train, dtype=torch.float32),
        torch.tensor(y_train, dtype=torch.float32),
        torch.tensor(aid_train, dtype=torch.long),
    )
    train_loader = DataLoader(train_ds, batch_size=256, shuffle=True, drop_last=False)
    x_val_t = torch.tensor(x_valid, dtype=torch.float32, device=DEVICE)
    y_val_t = torch.tensor(y_valid, dtype=torch.float32, device=DEVICE)
    aid_val_t = torch.tensor(aid_valid, dtype=torch.long, device=DEVICE)

    best_state = None
    best_val = float("inf")
    best_epoch = 0
    bad = 0
    for epoch in range(1, max_epochs + 1):
        model.train()
        train_losses = []
        for xb, yb, ab in train_loader:
            xb = xb.to(DEVICE)
            yb = yb.to(DEVICE)
            ab = ab.to(DEVICE)
            opt.zero_grad(set_to_none=True)
            pred = model(xb, ab)
            loss = loss_fn(pred, yb)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            train_losses.append(float(loss.detach().cpu()))

        model.eval()
        with torch.no_grad():
            val_loss = float(loss_fn(model(x_val_t, aid_val_t), y_val_t).detach().cpu())
        if val_loss < best_val - 1e-5:
            best_val = val_loss
            best_epoch = epoch
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            bad = 0
        else:
            bad += 1
        if bad >= patience:
            break

    if best_state is not None:
        model.load_state_dict(best_state)
    return model, {
        "seed": seed,
        "best_epoch": int(best_epoch),
        "best_valid_mse_scaled_logvar": float(best_val),
    }


def predict_transformer(
    model: TransformerVolRegressor,
    x: np.ndarray,
    aid: np.ndarray,
    y_mean: float,
    y_std: float,
) -> np.ndarray:
    model.eval()
    preds: List[np.ndarray] = []
    with torch.no_grad():
        for start in range(0, len(x), 1024):
            stop = start + 1024
            xb = torch.tensor(x[start:stop], dtype=torch.float32, device=DEVICE)
            ab = torch.tensor(aid[start:stop], dtype=torch.long, device=DEVICE)
            yp = model(xb, ab).detach().cpu().numpy()
            preds.append(yp)
    pred_scaled = np.concatenate(preds)
    pred_log_var = pred_scaled * y_std + y_mean
    return np.exp(np.clip(pred_log_var, np.log(EPS), np.log(0.25)))


def fit_tabular_baselines(panels: Dict[str, pd.DataFrame], out: pd.DataFrame) -> pd.DataFrame:
    for asset in ASSETS:
        df = panels[asset].copy()
        train_mask = (df.index >= TRAIN_START) & (df.index <= VALID_END)
        oos_mask = (df.index >= OOS_START) & (df.index <= OOS_END)
        target = df["target_log_var"]

        har_cols = ["log_r2_l1", "log_rv5_l1", "log_rv22_l1"]
        har_train = train_mask & df[har_cols].notna().all(axis=1) & target.notna()
        har_oos = oos_mask & df[har_cols].notna().all(axis=1)
        har = LinearRegression()
        har.fit(df.loc[har_train, har_cols], target.loc[har_train])
        har_pred = np.exp(np.clip(har.predict(df.loc[har_oos, har_cols]), np.log(EPS), np.log(0.25)))

        ridge_train = train_mask & df[TABULAR_FEATURES].notna().all(axis=1) & target.notna()
        ridge_oos = oos_mask & df[TABULAR_FEATURES].notna().all(axis=1)
        ridge = make_pipeline(StandardScaler(), Ridge(alpha=10.0))
        ridge.fit(df.loc[ridge_train, TABULAR_FEATURES], target.loc[ridge_train])
        ridge_pred = np.exp(
            np.clip(ridge.predict(df.loc[ridge_oos, TABULAR_FEATURES]), np.log(EPS), np.log(0.25))
        )

        asset_rows = out["asset"] == asset
        har_map = pd.Series(har_pred, index=df.loc[har_oos].index)
        ridge_map = pd.Series(ridge_pred, index=df.loc[ridge_oos].index)
        out.loc[asset_rows, "HAR_LogOLS"] = out.loc[asset_rows, "date"].map(har_map).to_numpy()
        out.loc[asset_rows, "RidgeFactors"] = out.loc[asset_rows, "date"].map(ridge_map).to_numpy()

    return out


def ewma_forecast(panel: pd.DataFrame) -> pd.Series:
    r2 = panel["target_var"].copy()
    pred = pd.Series(np.nan, index=panel.index, dtype=float)
    pre = r2.loc[: pd.Timestamp(OOS_START) - pd.Timedelta(days=1)].dropna()
    if len(pre) < 252:
        return pred
    h = float(pre.tail(252).mean())
    prev_r2 = float(pre.iloc[-1])
    for dt in panel.index[(panel.index >= OOS_START) & (panel.index <= OOS_END)]:
        h = EWMA_LAMBDA * h + (1.0 - EWMA_LAMBDA) * prev_r2
        pred.loc[dt] = max(h, EPS)
        if np.isfinite(r2.loc[dt]):
            prev_r2 = float(r2.loc[dt])
    return pred


def gjr_garch_annual_forecast(panel: pd.DataFrame) -> pd.Series:
    pred = pd.Series(np.nan, index=panel.index, dtype=float)
    try:
        from arch import arch_model
    except Exception as exc:  # pragma: no cover - arch is installed in repo env.
        warnings.warn(f"arch unavailable: {exc}")
        return pred

    ret = panel["ret"].dropna()
    oos_years = sorted(pd.Index(ret.loc[OOS_START:OOS_END].index.year).unique())
    for year in oos_years:
        seg_idx = ret.loc[f"{year}-01-01" : f"{year}-12-31"].loc[:OOS_END].index
        seg_idx = seg_idx[seg_idx >= pd.Timestamp(OOS_START)]
        if len(seg_idx) == 0:
            continue
        train = ret.loc[TRAIN_START : seg_idx[0] - pd.Timedelta(days=1)].dropna()
        if len(train) < 1000:
            continue
        y = train * 100.0
        try:
            model = arch_model(
                y,
                mean="Zero",
                vol="GARCH",
                p=1,
                o=1,
                q=1,
                dist="normal",
                rescale=False,
            )
            res = model.fit(disp="off", show_warning=False, options={"maxiter": 400})
            params = res.params
            omega = float(params.get("omega", np.nan))
            alpha = float(params.get("alpha[1]", 0.0))
            gamma = float(params.get("gamma[1]", 0.0))
            beta = float(params.get("beta[1]", 0.0))
            h_prev = float(res.conditional_volatility.iloc[-1] ** 2)
            prev_ret = float(y.iloc[-1])
        except Exception as exc:
            warnings.warn(f"GJR fit failed for {seg_idx[0].date()}: {exc}")
            continue

        for dt in seg_idx:
            h = omega + alpha * prev_ret**2 + gamma * prev_ret**2 * (prev_ret < 0) + beta * h_prev
            if math.isfinite(h) and h > 0:
                pred.loc[dt] = max(h / 10000.0, EPS)
                h_prev = h
            if dt in ret.index and math.isfinite(float(ret.loc[dt])):
                prev_ret = float(ret.loc[dt] * 100.0)
    return pred


def add_recursive_baselines(panels: Dict[str, pd.DataFrame], out: pd.DataFrame) -> pd.DataFrame:
    for asset in ASSETS:
        panel = panels[asset]
        ewma = ewma_forecast(panel)
        gjr = gjr_garch_annual_forecast(panel)
        asset_rows = out["asset"] == asset
        out.loc[asset_rows, "EWMA94"] = out.loc[asset_rows, "date"].map(ewma).to_numpy()
        out.loc[asset_rows, "GJR_GARCH_Annual"] = out.loc[asset_rows, "date"].map(gjr).to_numpy()
    return out


def build_forecast_frame(seq: SequenceData, oos_mask: np.ndarray) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(seq.dates[oos_mask]),
            "asset": seq.assets[oos_mask],
            "asset_id": seq.asset_id[oos_mask],
            "ret": seq.returns[oos_mask],
            "actual_var": seq.target_var[oos_mask],
        }
    )
    for model in MODEL_ORDER:
        out[model] = np.nan
    return out


def holm_adjust(pvals: Iterable[float]) -> List[float]:
    p = np.asarray([float(x) if x is not None and np.isfinite(x) else 1.0 for x in pvals])
    m = len(p)
    order = np.argsort(p)
    adjusted = np.empty(m, dtype=float)
    running = 0.0
    for rank, idx in enumerate(order):
        val = min(1.0, (m - rank) * p[idx])
        running = max(running, val)
        adjusted[idx] = running
    return adjusted.tolist()


def evaluate(forecasts: pd.DataFrame) -> Dict[str, object]:
    clean = forecasts.copy()
    for model in MODEL_ORDER:
        clean[f"loss_{model}"] = qlike_pointwise(clean["actual_var"].to_numpy(), clean[model].to_numpy())

    metrics: List[Dict[str, object]] = []
    dm_records: List[Dict[str, object]] = []
    for asset in ASSETS:
        sub = clean[clean["asset"] == asset].copy()
        for model in MODEL_ORDER:
            valid = sub[["actual_var", model, f"loss_{model}"]].replace([np.inf, -np.inf], np.nan).dropna()
            if len(valid) < 252:
                continue
            rho, rho_p = spearman_corr(valid["actual_var"].to_numpy(), valid[model].to_numpy())
            metrics.append(
                {
                    "asset": asset,
                    "model": model,
                    "n": int(len(valid)),
                    "mean_qlike": float(valid[f"loss_{model}"].mean()),
                    "median_qlike": float(valid[f"loss_{model}"].median()),
                    "mse": float(np.mean((valid["actual_var"].to_numpy() - valid[model].to_numpy()) ** 2)),
                    "spearman": to_float(rho),
                    "spearman_p": to_float(rho_p),
                    "mean_forecast_var": float(valid[model].mean()),
                    "mean_actual_var": float(valid["actual_var"].mean()),
                }
            )

        for base in [m for m in MODEL_ORDER if m != "MultiTransformerLite"]:
            pair = sub[[f"loss_MultiTransformerLite", f"loss_{base}"]].replace(
                [np.inf, -np.inf], np.nan
            ).dropna()
            if len(pair) < 252:
                continue
            stat, p = dm_test(
                pair["loss_MultiTransformerLite"].to_numpy(),
                pair[f"loss_{base}"].to_numpy(),
                h=1,
            )
            dm_records.append(
                {
                    "scope": "asset",
                    "asset": asset,
                    "pair": f"MultiTransformerLite_minus_{base}",
                    "baseline": base,
                    "n": int(len(pair)),
                    "dm_stat": float(stat),
                    "p": float(p),
                    "strict_harvey_abs_t_gt_3": bool(abs(stat) > 3.0),
                    "direction_favors_multitransformer": bool(stat < 0),
                }
            )

    p_adj = holm_adjust([r["p"] for r in dm_records])
    for rec, adj in zip(dm_records, p_adj):
        rec["holm_p"] = float(adj)
        rec["strict_holm_win"] = bool(
            rec["direction_favors_multitransformer"]
            and rec["strict_harvey_abs_t_gt_3"]
            and rec["holm_p"] < 0.05
        )

    pooled_dm: List[Dict[str, object]] = []
    for base in [m for m in MODEL_ORDER if m != "MultiTransformerLite"]:
        pair = clean[[f"loss_MultiTransformerLite", f"loss_{base}"]].replace(
            [np.inf, -np.inf], np.nan
        ).dropna()
        stat, p = dm_test(
            pair["loss_MultiTransformerLite"].to_numpy(),
            pair[f"loss_{base}"].to_numpy(),
            h=1,
        )
        pooled_dm.append(
            {
                "scope": "pooled_asset_day_diagnostic",
                "pair": f"MultiTransformerLite_minus_{base}",
                "baseline": base,
                "n": int(len(pair)),
                "dm_stat": float(stat),
                "p": float(p),
                "direction_favors_multitransformer": bool(stat < 0),
                "caveat": "Pooled asset-day DM is diagnostic only; per-asset Holm tests are primary.",
            }
        )

    metric_df = pd.DataFrame(metrics)
    best_by_asset = []
    for asset in ASSETS:
        sub = metric_df[metric_df["asset"] == asset].sort_values("mean_qlike")
        if len(sub):
            best_by_asset.append({"asset": asset, "best_model": sub.iloc[0]["model"]})

    mt_best_cells = sum(1 for r in best_by_asset if r["best_model"] == "MultiTransformerLite")
    mt_wins_all = sum(1 for r in dm_records if r["strict_holm_win"])
    mt_wins_vs_gjr = sum(
        1
        for r in dm_records
        if r["baseline"] == "GJR_GARCH_Annual" and r["strict_holm_win"]
    )
    mt_losses_strict = sum(
        1
        for r in dm_records
        if (not r["direction_favors_multitransformer"])
        and r["strict_harvey_abs_t_gt_3"]
        and r["holm_p"] < 0.05
    )

    if mt_best_cells >= 4 and mt_wins_vs_gjr >= 3 and mt_losses_strict == 0:
        verdict = "PASS"
    elif mt_best_cells >= 2 and mt_wins_all > 0 and mt_losses_strict == 0:
        verdict = "WEAK_PARTIAL"
    else:
        verdict = "NULL_OR_NEGATIVE"

    return {
        "metrics": metrics,
        "dm_tests": dm_records,
        "pooled_asset_day_dm_diagnostic": pooled_dm,
        "best_by_asset": best_by_asset,
        "conclusion": {
            "verdict": verdict,
            "mt_best_mean_qlike_assets": int(mt_best_cells),
            "mt_strict_holm_wins_all_pairs": int(mt_wins_all),
            "mt_strict_holm_wins_vs_gjr": int(mt_wins_vs_gjr),
            "mt_strict_holm_losses": int(mt_losses_strict),
            "primary_inference": "per-asset Holm-adjusted DM tests; pooled asset-day DM is diagnostic only",
        },
    }


def plot_results(forecasts: pd.DataFrame, eval_res: Dict[str, object]) -> List[str]:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    metrics = pd.DataFrame(eval_res["metrics"])
    paths: List[str] = []

    pivot = metrics.pivot(index="asset", columns="model", values="mean_qlike")
    rel = pivot.sub(pivot["HAR_LogOLS"], axis=0)
    fig, ax = plt.subplots(figsize=(12, 6))
    rel[MODEL_ORDER].plot(kind="bar", ax=ax)
    ax.axhline(0, color="black", lw=0.9)
    ax.set_title("K1595 mean QLIKE relative to HAR_LogOLS (lower is better)")
    ax.set_ylabel("Mean QLIKE difference")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    p = FIG_DIR / "fig1_relative_qlike_vs_har.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    paths.append(str(p.relative_to(OUT_DIR)))

    fig, axes = plt.subplots(3, 2, figsize=(13, 9), sharex=False)
    axes = axes.ravel()
    for ax, asset in zip(axes, ASSETS):
        sub = forecasts[forecasts["asset"] == asset].sort_values("date")
        loss_mt = qlike_pointwise(sub["actual_var"].to_numpy(), sub["MultiTransformerLite"].to_numpy())
        loss_gjr = qlike_pointwise(sub["actual_var"].to_numpy(), sub["GJR_GARCH_Annual"].to_numpy())
        diff = pd.Series(loss_mt - loss_gjr, index=sub["date"]).replace([np.inf, -np.inf], np.nan)
        ax.plot(diff.cumsum(), lw=1.2)
        ax.axhline(0, color="black", lw=0.8)
        ax.set_title(asset)
        ax.grid(alpha=0.25)
    fig.suptitle("Cumulative QLIKE loss difference: MultiTransformerLite minus GJR_GARCH_Annual")
    fig.tight_layout()
    p = FIG_DIR / "fig2_cumulative_loss_diff_vs_gjr.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    paths.append(str(p.relative_to(OUT_DIR)))

    high_vix_rows = []
    for asset in ASSETS:
        sub = forecasts[forecasts["asset"] == asset].copy()
        # Reconstruct high-volatility proxy from realized cross-section: top quartile asset r2.
        threshold = sub["actual_var"].quantile(0.75)
        for regime, reg_sub in [
            ("low_mid_realized", sub[sub["actual_var"] <= threshold]),
            ("high_realized", sub[sub["actual_var"] > threshold]),
        ]:
            for model in ["HAR_LogOLS", "GJR_GARCH_Annual", "MultiTransformerLite"]:
                loss = qlike_pointwise(reg_sub["actual_var"].to_numpy(), reg_sub[model].to_numpy())
                high_vix_rows.append(
                    {
                        "asset": asset,
                        "regime": regime,
                        "model": model,
                        "mean_qlike": np.nanmean(loss),
                    }
                )
    reg = pd.DataFrame(high_vix_rows)
    fig, ax = plt.subplots(figsize=(11, 6))
    reg_pivot = reg.groupby(["regime", "model"])["mean_qlike"].mean().unstack("model")
    reg_pivot.plot(kind="bar", ax=ax)
    ax.set_title("Average QLIKE by realized-volatility regime")
    ax.set_ylabel("Mean QLIKE")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    p = FIG_DIR / "fig3_regime_qlike.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    paths.append(str(p.relative_to(OUT_DIR)))
    return paths


def main() -> None:
    set_seed(SEED)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    prices = read_prices()
    panels = build_panels(prices)
    seq = build_sequences(panels)

    train_mask = mask_dates(seq.dates, TRAIN_START, TRAIN_END)
    valid_mask = mask_dates(seq.dates, VALID_START, VALID_END)
    oos_mask = mask_dates(seq.dates, OOS_START, OOS_END)
    fit_mask = train_mask | valid_mask
    if train_mask.sum() < 1000 or valid_mask.sum() < 500 or oos_mask.sum() < 1000:
        raise RuntimeError("Insufficient train/valid/OOS sequences.")

    x_scaled, y_mean, y_std, x_mean, x_std = standardize_sequences(seq, train_mask)
    y_scaled = (seq.y - y_mean) / y_std
    forecasts = build_forecast_frame(seq, oos_mask)

    single, single_info = train_transformer(
        x_scaled[train_mask],
        y_scaled[train_mask],
        seq.asset_id[train_mask],
        x_scaled[valid_mask],
        y_scaled[valid_mask],
        seq.asset_id[valid_mask],
        seed=SEED,
    )
    forecasts["TransformerLite"] = predict_transformer(
        single,
        x_scaled[oos_mask],
        seq.asset_id[oos_mask],
        y_mean,
        y_std,
    )

    ensemble_preds = []
    ensemble_info = []
    for seed in [SEED + 11, SEED + 23, SEED + 37]:
        model, info = train_transformer(
            x_scaled[train_mask],
            y_scaled[train_mask],
            seq.asset_id[train_mask],
            x_scaled[valid_mask],
            y_scaled[valid_mask],
            seq.asset_id[valid_mask],
            seed=seed,
        )
        ensemble_info.append(info)
        ensemble_preds.append(
            predict_transformer(model, x_scaled[oos_mask], seq.asset_id[oos_mask], y_mean, y_std)
        )
    forecasts["MultiTransformerLite"] = np.mean(np.column_stack(ensemble_preds), axis=1)

    forecasts = fit_tabular_baselines(panels, forecasts)
    forecasts = add_recursive_baselines(panels, forecasts)
    for model in MODEL_ORDER:
        forecasts[model] = forecasts[model].clip(lower=EPS, upper=0.25)
    forecasts = forecasts.sort_values(["asset", "date"]).reset_index(drop=True)

    eval_res = evaluate(forecasts)
    fig_paths = plot_results(forecasts, eval_res)

    forecast_path = OUT_DIR / "k1595_oos_forecasts.csv"
    forecasts.to_csv(forecast_path, index=False)

    result = {
        "experiment_id": EXPERIMENT_ID,
        "task_id": "research_multi_transformer_vol_forecast",
        "created_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "data": {
            "source": str(DATA_PATH.relative_to(ROOT)),
            "assets": ASSETS,
            "rows_in_price_cache": int(len(prices)),
            "train_window": [TRAIN_START, TRAIN_END],
            "validation_window": [VALID_START, VALID_END],
            "oos_window": [OOS_START, OOS_END],
            "lookback_days": LOOKBACK,
            "oos_rows": int(len(forecasts)),
            "oos_rows_by_asset": {k: int(v) for k, v in forecasts.groupby("asset").size().items()},
        },
        "method": {
            "transformer_scope": "MultiTransformerLite: pooled 3-seed ensemble of small Transformer encoders; not a full Mishra/Ramos replication",
            "target": "next-day close-to-close squared log return",
            "loss": "Patton QLIKE actual/predicted - log(actual/predicted) - 1",
            "lookahead_control": [
                "tabular baselines use explicit *_l1 shifted features",
                "Transformer sequences for target date t use only rows [t-22, t-1]",
                "feature standardization is fit on 2005-2011 training rows only",
                "OOS starts after validation ends; no OOS row is used in model fitting",
                "GJR annual recursion forecasts date t from fitted params, h_{t-1}, and return_{t-1}",
            ],
            "baselines": MODEL_ORDER,
            "single_transformer_training": single_info,
            "ensemble_training": ensemble_info,
            "x_mean": [float(x) for x in x_mean],
            "x_std": [float(x) for x in x_std],
            "y_mean": float(y_mean),
            "y_std": float(y_std),
        },
        "evaluation": eval_res,
        "artifacts": {
            "forecasts_csv": str(forecast_path.relative_to(OUT_DIR)),
            "figures": fig_paths,
        },
        "literature_checked": [
            {
                "title": "Volatility forecasting and assessing risk of financial markets using multi-transformer neural network based architecture",
                "venue": "Engineering Applications of Artificial Intelligence 133:108223",
                "doi": "10.1016/j.engappai.2024.108223",
                "url": "https://doi.org/10.1016/j.engappai.2024.108223",
            },
            {
                "title": "Multi-Transformer: A New Neural Network-Based Architecture for Forecasting S&P Volatility",
                "venue": "Mathematics 9(15):1794",
                "doi": "10.3390/math9151794",
                "url": "https://www.mdpi.com/2227-7390/9/15/1794",
            },
            {
                "title": "A Time Series is Worth 64 Words: Long-term Forecasting with Transformers",
                "venue": "ICLR 2023 / arXiv:2211.14730",
                "url": "https://arxiv.org/abs/2211.14730",
            },
            {
                "title": "Volatility forecast comparison using imperfect volatility proxies",
                "venue": "Journal of Econometrics 160(1):246-256",
                "url": "https://public.econ.duke.edu/~ap172/Patton_vol_proxies_JoE_2011.pdf",
            },
        ],
    }

    result_path = OUT_DIR / "k1595_results.json"
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "result_file": str(result_path),
                "verdict": eval_res["conclusion"]["verdict"],
                "mt_best_mean_qlike_assets": eval_res["conclusion"]["mt_best_mean_qlike_assets"],
                "mt_strict_holm_wins_all_pairs": eval_res["conclusion"][
                    "mt_strict_holm_wins_all_pairs"
                ],
                "mt_strict_holm_wins_vs_gjr": eval_res["conclusion"][
                    "mt_strict_holm_wins_vs_gjr"
                ],
                "mt_strict_holm_losses": eval_res["conclusion"]["mt_strict_holm_losses"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
