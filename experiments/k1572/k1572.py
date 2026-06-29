"""K1572 -- Stage 2 DNN quantile VaR vs K1571 baseline plateau.

This experiment continues K1571 under the same information set:

* dependent assets: TLT and HYG
* OOS window: 2015-01-01 through 2026-06-26
* refit: monthly expanding
* covariates: [rv5, ief_mom, lqd_mom, credit_chg, vix]
* lag discipline: inherited from K1571 build_panel(), where all covariates are
  shifted by one day before being aligned to return_t.

The new model is a small feed-forward neural quantile regressor trained with
pinball loss. It is intentionally constrained to the same covariate set used by
LinearQR so the comparison measures non-linear functional-form value rather
than information-set advantage.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import random
import sys
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import matplotlib
import numpy as np
import pandas as pd
import torch
from torch import nn
from scipy.optimize import minimize

matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.simplefilter("ignore", category=RuntimeWarning)


SEED = 1571
HERE = Path(__file__).resolve().parent
K1571_PATH = HERE.parent / "k1571" / "k1571.py"
OOS_START = pd.Timestamp("2015-01-01")
ASSETS = ["TLT", "HYG"]
ALPHAS = [0.05, 0.01]
LINEAR_QR_FEATS = ["rv5", "ief_mom", "lqd_mom", "credit_chg", "vix"]
BASELINE_NAMES = ["HS250", "LinearQR", "HARQ", "CAViaR-SAV"]
COVARIATE_BASELINES = ["LinearQR", "HARQ", "CAViaR-SAV"]
DNN_NAME = "DNN-QR"


def _load_k1571_module():
    if not K1571_PATH.exists():
        raise FileNotFoundError(f"K1571 helper script not found: {K1571_PATH}")
    spec = importlib.util.spec_from_file_location("k1571_helpers", K1571_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not import K1571 helpers from {K1571_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


k1571 = _load_k1571_module()
ForecastSeries = k1571.ForecastSeries


def set_global_seed(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
    try:
        torch.use_deterministic_algorithms(True)
    except Exception:
        pass


@dataclass(frozen=True)
class DNNConfig:
    hidden_1: int = 16
    hidden_2: int = 8
    epochs: int = 120
    batch_size: int = 256
    learning_rate: float = 0.01
    weight_decay: float = 1e-4
    min_train_obs: int = 500
    device: str = "cpu"


class QuantileNet(nn.Module):
    def __init__(self, n_features: int, hidden_1: int, hidden_2: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(n_features, hidden_1),
            nn.ReLU(),
            nn.Linear(hidden_1, hidden_2),
            nn.ReLU(),
            nn.Linear(hidden_2, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


def pinball_loss_torch(
    pred: torch.Tensor, target: torch.Tensor, alpha: float
) -> torch.Tensor:
    err = target - pred
    return torch.maximum(alpha * err, (alpha - 1.0) * err).mean()


@dataclass
class FittedDNN:
    model: QuantileNet
    x_mean: np.ndarray
    x_std: np.ndarray
    y_mean: float
    y_std: float
    final_loss_scaled: float
    n_train: int


@dataclass(frozen=True)
class CAViaRWarmConfig:
    initial_starts: int = 3
    monthly_maxiter: int = 700
    xatol: float = 1e-5
    fatol: float = 1e-7


def _standardize_train(
    train: pd.DataFrame, feats: List[str]
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float, float]:
    x = train[feats].to_numpy(dtype=np.float32)
    y = train["y"].to_numpy(dtype=np.float32)
    x_mean = x.mean(axis=0)
    x_std = x.std(axis=0)
    x_std = np.where(x_std < 1e-12, 1.0, x_std)
    y_mean = float(y.mean())
    y_std = float(y.std())
    if not np.isfinite(y_std) or y_std < 1e-12:
        y_std = 1.0
    xs = ((x - x_mean) / x_std).astype(np.float32)
    ys = ((y - y_mean) / y_std).astype(np.float32)
    return xs, ys, x_mean, x_std, y_mean, y_std


def fit_dnn_quantile(
    train: pd.DataFrame,
    feats: List[str],
    alpha: float,
    cfg: DNNConfig,
    seed: int,
) -> FittedDNN:
    if len(train) < cfg.min_train_obs:
        raise ValueError(f"Insufficient DNN training rows: {len(train)}")

    set_global_seed(seed)
    xs, ys, x_mean, x_std, y_mean, y_std = _standardize_train(train, feats)
    device = torch.device(cfg.device)
    x_t = torch.as_tensor(xs, dtype=torch.float32, device=device)
    y_t = torch.as_tensor(ys, dtype=torch.float32, device=device)
    model = QuantileNet(len(feats), cfg.hidden_1, cfg.hidden_2).to(device)
    opt = torch.optim.AdamW(
        model.parameters(), lr=cfg.learning_rate, weight_decay=cfg.weight_decay
    )
    generator = torch.Generator(device="cpu")
    generator.manual_seed(seed)
    n = len(train)
    batch_size = min(cfg.batch_size, n)
    last_loss = float("nan")

    model.train()
    for _ in range(cfg.epochs):
        order = torch.randperm(n, generator=generator)
        for start in range(0, n, batch_size):
            idx = order[start : start + batch_size].to(device)
            pred = model(x_t[idx])
            loss = pinball_loss_torch(pred, y_t[idx], alpha)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
        last_loss = float(loss.detach().cpu().item())

    model.eval()
    return FittedDNN(
        model=model,
        x_mean=x_mean,
        x_std=x_std,
        y_mean=y_mean,
        y_std=y_std,
        final_loss_scaled=last_loss,
        n_train=n,
    )


def predict_dnn(fitted: FittedDNN, df: pd.DataFrame, feats: List[str]) -> np.ndarray:
    x = df[feats].to_numpy(dtype=np.float32)
    xs = ((x - fitted.x_mean) / fitted.x_std).astype(np.float32)
    with torch.no_grad():
        pred_scaled = fitted.model(
            torch.as_tensor(xs, dtype=torch.float32, device=next(fitted.model.parameters()).device)
        )
    pred = pred_scaled.detach().cpu().numpy() * fitted.y_std + fitted.y_mean
    return pred.astype(float)


def _refit_segments(index: pd.DatetimeIndex) -> Iterable[Tuple[pd.Timestamp, pd.DatetimeIndex]]:
    refit_dates = k1571._refit_dates(index)
    for i, start in enumerate(refit_dates):
        end = refit_dates[i + 1] if i + 1 < len(refit_dates) else None
        if end is None:
            seg = index[index >= start]
        else:
            seg = index[(index >= start) & (index < end)]
        if len(seg) > 0:
            yield start, seg


def run_dnn_quantile(
    panel: pd.DataFrame,
    alpha: float,
    cfg: DNNConfig,
    asset: str,
) -> Tuple[ForecastSeries, Dict[str, object]]:
    df = panel.dropna()
    var = pd.Series(index=df.index, dtype=float)
    fit_log = []
    refit_count = 0

    for start, seg_idx in _refit_segments(df.index):
        train = df[df.index < start]
        if len(train) < cfg.min_train_obs:
            continue
        seed = SEED + (1000 if asset == "HYG" else 0) + int(alpha * 10000) + refit_count
        fitted = fit_dnn_quantile(train, LINEAR_QR_FEATS, alpha, cfg, seed)
        var.loc[seg_idx] = predict_dnn(fitted, df.loc[seg_idx], LINEAR_QR_FEATS)
        fit_log.append(
            {
                "refit_date": str(start.date()),
                "n_train": fitted.n_train,
                "final_loss_scaled": fitted.final_loss_scaled,
            }
        )
        refit_count += 1

    var = var.dropna()
    y = df.loc[var.index, "y"]
    loss = (y - var).apply(
        lambda e: alpha * e if e >= 0 else (alpha - 1.0) * e
    )
    violations = (y < var).astype(int)
    meta = {
        "refit_count": refit_count,
        "first_forecast": str(var.index.min().date()) if len(var) else None,
        "last_forecast": str(var.index.max().date()) if len(var) else None,
        "fit_log_head": fit_log[:3],
        "fit_log_tail": fit_log[-3:],
    }
    return ForecastSeries(DNN_NAME, var, loss, violations), meta


def fit_caviar_warm(
    y_train: np.ndarray,
    alpha: float,
    start_params: np.ndarray,
    cfg: CAViaRWarmConfig,
) -> Tuple[np.ndarray, Dict[str, object]]:
    q0 = float(np.quantile(y_train[:250], alpha))

    def obj(params: np.ndarray) -> float:
        q = k1571._caviar_recursion(params, y_train, alpha, q0)
        return k1571._quantile_loss(q, y_train, alpha)

    res = minimize(
        obj,
        np.asarray(start_params, dtype=float),
        method="Nelder-Mead",
        options={
            "xatol": cfg.xatol,
            "fatol": cfg.fatol,
            "maxiter": cfg.monthly_maxiter,
            "disp": False,
        },
    )
    if res.success or np.isfinite(res.fun):
        return np.asarray(res.x, dtype=float), {
            "success": bool(res.success),
            "fun": float(res.fun),
            "nit": int(getattr(res, "nit", -1)),
            "message": str(res.message),
        }
    return np.asarray(start_params, dtype=float), {
        "success": False,
        "fun": float("nan"),
        "nit": int(getattr(res, "nit", -1)),
        "message": str(res.message),
    }


def run_caviar_warm(
    panel: pd.DataFrame,
    alpha: float,
    cfg: CAViaRWarmConfig,
) -> Tuple[ForecastSeries, Dict[str, object]]:
    """CAViaR-SAV with K1571's recurrence and monthly expanding refit.

    K1571 used six fresh starts at every monthly refit. K1572 keeps the same
    model, target, lag discipline and refit dates, then warm-starts each month
    from the prior month's parameters so the DNN experiment can be rerun within
    an hourly worker budget.
    """
    df = panel.dropna()
    refit_dates = k1571._refit_dates(df.index)
    train0 = df[df.index < OOS_START]
    if len(train0) < 500:
        raise ValueError(f"Insufficient pre-OOS data for CAViaR: {len(train0)}")

    params = k1571.fit_caviar(train0["y"].values, alpha, n_starts=cfg.initial_starts)
    q_in = k1571._caviar_recursion(
        params,
        train0["y"].values,
        alpha,
        np.quantile(train0["y"].values[:250], alpha),
    )
    q_prev = q_in[-1]
    y_prev = train0["y"].iloc[-1]

    var = pd.Series(index=df.index, dtype=float)
    refit_meta = []
    for ts in df[df.index >= OOS_START].index:
        if ts in refit_dates and ts != refit_dates[0]:
            train = df[df.index < ts]
            params, opt_meta = fit_caviar_warm(train["y"].values, alpha, params, cfg)
            q_in = k1571._caviar_recursion(
                params,
                train["y"].values,
                alpha,
                np.quantile(train["y"].values[:250], alpha),
            )
            q_prev = q_in[-1]
            y_prev = train["y"].iloc[-1]
            refit_meta.append(
                {
                    "refit_date": str(ts.date()),
                    "n_train": int(len(train)),
                    **opt_meta,
                }
            )
        var.loc[ts] = k1571.caviar_forecast_step(params, y_prev, q_prev)
        q_prev = var.loc[ts]
        y_prev = df.loc[ts, "y"]

    var = var.dropna()
    y = df.loc[var.index, "y"]
    loss = (y - var).apply(
        lambda e: alpha * e if e >= 0 else (alpha - 1.0) * e
    )
    violations = (y < var).astype(int)
    meta = {
        "optimizer": "warm_start_single_start_after_initial_multistart",
        "initial_starts": cfg.initial_starts,
        "monthly_maxiter": cfg.monthly_maxiter,
        "refit_count": int(len(refit_meta) + 1),
        "non_success_refits": int(sum(not row["success"] for row in refit_meta)),
        "fit_log_head": refit_meta[:3],
        "fit_log_tail": refit_meta[-3:],
    }
    return ForecastSeries("CAViaR-SAV", var, loss, violations), meta


def align_forecasts(forecasts: Dict[str, ForecastSeries]) -> Dict[str, ForecastSeries]:
    common = None
    for fs in forecasts.values():
        common = fs.loss.index if common is None else common.intersection(fs.loss.index)
    if common is None or len(common) == 0:
        raise ValueError("No common OOS index across forecasts")
    aligned = {}
    for name, fs in forecasts.items():
        aligned[name] = ForecastSeries(
            name=fs.name,
            var=fs.var.loc[common],
            loss=fs.loss.loc[common],
            violations=fs.violations.loc[common],
        )
    return aligned


def run_one(
    asset: str,
    alpha: float,
    panel: pd.DataFrame,
    cfg: DNNConfig,
    caviar_cfg: CAViaRWarmConfig,
) -> Tuple[Dict[str, ForecastSeries], Dict[str, object], Dict[str, object]]:
    forecasts: Dict[str, ForecastSeries] = {}
    forecasts["HS250"] = k1571.run_hs(panel, alpha, win=250)
    forecasts["LinearQR"] = k1571.run_quantreg(
        panel, alpha, k1571.LINEAR_QR_FEATS, "LinearQR"
    )
    forecasts["HARQ"] = k1571.run_quantreg(panel, alpha, k1571.HARQ_FEATS, "HARQ")
    forecasts["CAViaR-SAV"], caviar_meta = run_caviar_warm(panel, alpha, caviar_cfg)
    forecasts[DNN_NAME], dnn_meta = run_dnn_quantile(panel, alpha, cfg, asset)
    return align_forecasts(forecasts), dnn_meta, caviar_meta


def plateau_loss_series(forecasts: Dict[str, ForecastSeries]) -> pd.Series:
    return pd.concat(
        [forecasts[name].loss.rename(name) for name in COVARIATE_BASELINES], axis=1
    ).median(axis=1)


def summarize(forecasts: Dict[str, ForecastSeries], alpha: float) -> Dict[str, object]:
    per_model = {}
    for name, fs in forecasts.items():
        per_model[name] = {
            "mean_pinball": float(fs.loss.mean()),
            "sum_pinball": float(fs.loss.sum()),
            "kupiec": k1571.kupiec_pof(fs.violations, alpha),
            "christoffersen_ind": k1571.christoffersen_independence(fs.violations),
            "obs": int(len(fs.loss)),
        }

    plateau = plateau_loss_series(forecasts)
    per_model["PlateauMedianLoss"] = {
        "mean_pinball": float(plateau.mean()),
        "sum_pinball": float(plateau.sum()),
        "obs": int(len(plateau)),
        "definition": "pointwise median loss across LinearQR, HARQ, CAViaR-SAV",
    }

    dm_pairs = {}
    for baseline in BASELINE_NAMES:
        dm_pairs[f"{DNN_NAME}_vs_{baseline}"] = k1571.dm_test_hac(
            forecasts[DNN_NAME].loss, forecasts[baseline].loss
        )
    dm_pairs[f"{DNN_NAME}_vs_PlateauMedianLoss"] = k1571.dm_test_hac(
        forecasts[DNN_NAME].loss, plateau
    )
    dm_pairs["HARQ_vs_HS250"] = k1571.dm_test_hac(
        forecasts["HARQ"].loss, forecasts["HS250"].loss
    )
    dm_pairs["CAViaR-SAV_vs_HS250"] = k1571.dm_test_hac(
        forecasts["CAViaR-SAV"].loss, forecasts["HS250"].loss
    )
    dm_pairs["LinearQR_vs_HS250"] = k1571.dm_test_hac(
        forecasts["LinearQR"].loss, forecasts["HS250"].loss
    )

    dnn_mean = per_model[DNN_NAME]["mean_pinball"]
    plateau_mean = per_model["PlateauMedianLoss"]["mean_pinball"]
    hs_mean = per_model["HS250"]["mean_pinball"]
    return {
        "per_model": per_model,
        "dm_pairs": dm_pairs,
        "dnn_vs_plateau_mean_pinball_pct": float((dnn_mean / plateau_mean - 1.0) * 100.0),
        "dnn_vs_hs250_mean_pinball_pct": float((dnn_mean / hs_mean - 1.0) * 100.0),
    }


def plot_cumulative_loss(
    by_asset_alpha: Dict[Tuple[str, float], Dict[str, ForecastSeries]], out: Path
) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(13, 9), sharex=False)
    for i, asset in enumerate(ASSETS):
        for j, alpha in enumerate(ALPHAS):
            ax = axes[i, j]
            forecasts = by_asset_alpha[(asset, alpha)]
            for name, fs in forecasts.items():
                lw = 1.8 if name == DNN_NAME else 1.0
                ax.plot(fs.loss.index, fs.loss.cumsum(), label=name, lw=lw)
            plateau = plateau_loss_series(forecasts)
            ax.plot(
                plateau.index,
                plateau.cumsum(),
                label="PlateauMedianLoss",
                color="black",
                lw=1.4,
                ls="--",
            )
            ax.set_title(f"{asset} VaR({int(alpha * 100)}%) cumulative pinball")
            ax.grid(alpha=0.3)
            ax.legend(fontsize=7, loc="upper left")
    fig.suptitle("K1572 DNN quantile VaR vs K1571 baselines", y=1.01)
    fig.tight_layout()
    fig.savefig(out, dpi=140, bbox_inches="tight")
    plt.close(fig)


def plot_dnn_edges(results: Dict[str, object], out: Path) -> None:
    labels = []
    edge_plateau = []
    edge_hs = []
    p_plateau = []
    for key, summary in results["by_asset_alpha"].items():
        labels.append(key)
        edge_plateau.append(summary["dnn_vs_plateau_mean_pinball_pct"])
        edge_hs.append(summary["dnn_vs_hs250_mean_pinball_pct"])
        p_plateau.append(summary["dm_pairs"][f"{DNN_NAME}_vs_PlateauMedianLoss"]["p"])

    x = np.arange(len(labels))
    width = 0.36
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(x - width / 2, edge_plateau, width, label="DNN vs plateau median")
    ax.bar(x + width / 2, edge_hs, width, label="DNN vs HS250")
    ax.axhline(0.0, color="black", lw=0.8)
    for xi, val, pval in zip(x - width / 2, edge_plateau, p_plateau):
        text = "p=nan" if not np.isfinite(pval) else f"p={pval:.3f}"
        ax.text(xi, val, text, ha="center", va="bottom" if val >= 0 else "top", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Mean pinball difference (%)\nnegative means DNN lower loss")
    ax.set_title("K1572 DNN mean pinball edge")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(out, dpi=140, bbox_inches="tight")
    plt.close(fig)


def _finite_float(value):
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {k: _finite_float(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite_float(v) for v in value]
    return value


def aggregate_verdict(results: Dict[str, object]) -> Dict[str, object]:
    rows = []
    for key, summary in results["by_asset_alpha"].items():
        dm = summary["dm_pairs"][f"{DNN_NAME}_vs_PlateauMedianLoss"]
        edge = summary["dnn_vs_plateau_mean_pinball_pct"]
        rows.append(
            {
                "asset_alpha": key,
                "dnn_vs_plateau_pct": edge,
                "dm_stat": dm["stat"],
                "dm_p": dm["p"],
                "beats_plateau_5pct": bool(edge < 0 and dm["p"] < 0.05),
                "harvey_strict_abs_t_gt_3": bool(np.isfinite(dm["stat"]) and abs(dm["stat"]) > 3.0),
            }
        )
    beat_count = sum(r["beats_plateau_5pct"] for r in rows)
    strict_count = sum(r["harvey_strict_abs_t_gt_3"] and r["dnn_vs_plateau_pct"] < 0 for r in rows)
    if strict_count > 0:
        verdict = "DNN_STRONG_BEAT_SUBSET"
    elif beat_count > 0:
        verdict = "DNN_WEAK_BEAT_SUBSET"
    else:
        verdict = "NULL_OR_WORSE_VS_PLATEAU"
    return {
        "verdict": verdict,
        "beat_count_dm_p_lt_0_05": int(beat_count),
        "beat_count_harvey_abs_t_gt_3": int(strict_count),
        "rows": rows,
        "interpretation_rule": (
            "A real Stage 2 nonlinear advantage requires DNN lower mean pinball "
            "than PlateauMedianLoss and statistically significant DM; project "
            "strictness also reports the |t|>3 Harvey-style multiple-testing screen."
        ),
    }


def compare_against_k1571(results: Dict[str, object]) -> Dict[str, object]:
    path = HERE.parent / "k1571" / "k1571_results.json"
    if not path.exists():
        return {"available": False, "reason": "k1571_results.json missing"}
    with open(path) as f:
        parent = json.load(f)
    rows = {}
    for key, summary in results["by_asset_alpha"].items():
        parent_summary = parent.get("by_asset_alpha", {}).get(key, {})
        parent_models = parent_summary.get("per_model", {})
        rows[key] = {}
        for model in BASELINE_NAMES:
            current = summary["per_model"][model]["mean_pinball"]
            prior = parent_models.get(model, {}).get("mean_pinball")
            if prior is None:
                rows[key][model] = {"available": False}
                continue
            rows[key][model] = {
                "k1572_mean_pinball": float(current),
                "k1571_mean_pinball": float(prior),
                "pct_diff": float((current / prior - 1.0) * 100.0),
            }
    return {
        "available": True,
        "source": str(path.relative_to(HERE.parent.parent)),
        "metric": "mean_pinball",
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-fetch", action="store_true")
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=0.01)
    parser.add_argument("--caviar-initial-starts", type=int, default=3)
    parser.add_argument("--caviar-monthly-maxiter", type=int, default=700)
    parser.add_argument("--quick", action="store_true", help="short smoke run")
    args = parser.parse_args()

    cfg = DNNConfig(
        epochs=20 if args.quick else args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
    )
    caviar_cfg = CAViaRWarmConfig(
        initial_starts=args.caviar_initial_starts,
        monthly_maxiter=250 if args.quick else args.caviar_monthly_maxiter,
    )
    set_global_seed(SEED)
    close = k1571.fetch_data(force=args.force_fetch)
    print(f"[data] rows={len(close)} from={close.index.min().date()} to={close.index.max().date()}")

    results: Dict[str, object] = {
        "meta": {
            "experiment_id": "k1572",
            "parent_experiment_id": "k1571",
            "seed": SEED,
            "data_start": str(close.index.min().date()),
            "data_end": str(close.index.max().date()),
            "oos_start": str(OOS_START.date()),
            "assets_dependent": ASSETS,
            "assets_excluded_per_topic_cluster": ["SPY", "QQQ", "VIX"],
            "covariates_dnn": LINEAR_QR_FEATS,
            "covariate_lag": "K1571 build_panel shifts all features by 1 trading day",
            "refit_cadence": "monthly_expanding",
            "alphas": ALPHAS,
            "models": BASELINE_NAMES + [DNN_NAME, "PlateauMedianLoss"],
            "dnn_config": asdict(cfg),
            "caviar_warm_config": asdict(caviar_cfg),
            "caviar_baseline_note": (
                "CAViaR-SAV uses the K1571 recurrence and monthly expanding refit "
                "with warm-started optimization. baseline_validation_vs_k1571 "
                "reports mean-pinball drift from the Stage 1 canonical run."
            ),
            "baseline_helper": str(K1571_PATH.relative_to(HERE.parent.parent)),
        },
        "panels": {},
        "by_asset_alpha": {},
        "dnn_fit_meta": {},
        "caviar_fit_meta": {},
    }
    by_asset_alpha: Dict[Tuple[str, float], Dict[str, ForecastSeries]] = {}

    for asset in ASSETS:
        panel = k1571.build_panel(close, asset)
        print(
            f"[panel] {asset} rows={len(panel)} first={panel.index.min().date()} "
            f"last={panel.index.max().date()}"
        )
        results["panels"][asset] = {
            "rows": int(len(panel)),
            "first": str(panel.index.min().date()),
            "last": str(panel.index.max().date()),
            "features_shifted_by_1_day": True,
        }
        for alpha in ALPHAS:
            key = f"{asset}_{int(alpha * 100):02d}"
            print(f"[run] {key} cfg={cfg}")
            forecasts, dnn_meta, caviar_meta = run_one(
                asset, alpha, panel, cfg, caviar_cfg
            )
            by_asset_alpha[(asset, alpha)] = forecasts
            results["by_asset_alpha"][key] = summarize(forecasts, alpha)
            results["dnn_fit_meta"][key] = dnn_meta
            results["caviar_fit_meta"][key] = caviar_meta
            dnn_mean = results["by_asset_alpha"][key]["per_model"][DNN_NAME]["mean_pinball"]
            plateau_mean = results["by_asset_alpha"][key]["per_model"]["PlateauMedianLoss"]["mean_pinball"]
            dm = results["by_asset_alpha"][key]["dm_pairs"][f"{DNN_NAME}_vs_PlateauMedianLoss"]
            print(
                f"   {DNN_NAME} obs={len(forecasts[DNN_NAME].loss)} "
                f"mean_pl={dnn_mean:.8f} plateau={plateau_mean:.8f} "
                f"edge={(dnn_mean / plateau_mean - 1.0) * 100.0:+.2f}% "
                f"DM t={dm['stat']:.3f} p={dm['p']:.3f}"
            )

    results["aggregate_verdict"] = aggregate_verdict(results)
    results["baseline_validation_vs_k1571"] = compare_against_k1571(results)
    out_json = HERE / "k1572_results.json"
    with open(out_json, "w") as f:
        json.dump(_finite_float(results), f, indent=2)
    print(f"[write] {out_json}")

    plot_cumulative_loss(by_asset_alpha, HERE / "fig_k1572_cumulative_pinball.png")
    plot_dnn_edges(results, HERE / "fig_k1572_dnn_edges.png")
    print(f"[verdict] {results['aggregate_verdict']['verdict']}")
    print("[plots] saved")


if __name__ == "__main__":
    main()
