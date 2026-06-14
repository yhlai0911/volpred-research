from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
import warnings
from statsmodels.tsa.api import VAR
from statsmodels.tools.sm_exceptions import ValueWarning

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


HERE = Path(__file__).resolve().parent
RESULTS_PATH = HERE / "research_rp_f2b1b83d49_results.json"
FIG_QI_PATH = HERE / "fig_qlike_delta_heatmap.png"
FIG_ASYM_PATH = HERE / "fig_asym_spillover_timeseries.png"

START = "2010-01-01"
END = "2026-06-14"
TICKERS = {
    "SPY": "SPY",
    "EWJ": "EWJ",
    "EWG": "EWG",
    "EWU": "EWU",
    "EEM": "EEM",
}
HORIZONS = [1, 5, 22]
ROLL_WINDOWS = [1, 5, 22]
ASYM_WINDOW = 252
ASYM_STEP = 5
VAR_LAG = 1
FEVD_H = 5
INITIAL_TRAIN = 756
EPS = 1e-12

warnings.filterwarnings("ignore", category=ValueWarning)


@dataclass
class ForecastResult:
    qlike_score: float
    mse: float
    mean_pred: float
    n_test: int
    preds: np.ndarray
    actual: np.ndarray
    dates: list[str]
    final_betas: dict[str, float]


def result_frame(fr: ForecastResult) -> pd.DataFrame:
    return pd.DataFrame(
        {"actual": fr.actual, "pred": fr.preds},
        index=pd.to_datetime(fr.dates),
    ).sort_index()


def aligned_losses(a: ForecastResult, b: ForecastResult) -> tuple[np.ndarray, np.ndarray]:
    df_a = result_frame(a)
    df_a["loss_a"] = qlike_pointwise(df_a["actual"].to_numpy(), df_a["pred"].to_numpy())
    df_b = result_frame(b)
    df_b["loss_b"] = qlike_pointwise(df_b["actual"].to_numpy(), df_b["pred"].to_numpy())
    merged = df_a[["loss_a"]].join(df_b[["loss_b"]], how="inner")
    return merged["loss_a"].to_numpy(dtype=float), merged["loss_b"].to_numpy(dtype=float)


def download_prices() -> pd.DataFrame:
    raw = yf.download(
        list(TICKERS.values()),
        start=START,
        end=END,
        progress=False,
        auto_adjust=True,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned empty panel")
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].copy()
    else:
        close = raw.copy()
    close = close.rename(columns={v: k for k, v in TICKERS.items()})
    close = close.dropna(how="all").ffill().dropna()
    return close


def generalized_spillover(window_df: pd.DataFrame, var_lag: int = VAR_LAG, forecast_h: int = FEVD_H) -> dict[str, float]:
    model = VAR(window_df)
    result = model.fit(maxlags=var_lag, ic=None, trend="c")
    sigma = np.asarray(result.sigma_u)
    irf = result.irf(forecast_h)
    ma_coefs = irf.irfs
    n = window_df.shape[1]
    names = list(window_df.columns)
    theta = np.zeros((n, n), dtype=float)

    for i in range(n):
        denom = 0.0
        for h in range(forecast_h):
            psi_h = ma_coefs[h]
            denom += float(psi_h[i, :] @ sigma @ psi_h[i, :])
        if denom <= 0:
            continue
        for j in range(n):
            numer = 0.0
            for h in range(forecast_h):
                psi_h = ma_coefs[h]
                numer += float((psi_h[i, :] @ sigma[:, j]) ** 2)
            theta[i, j] = (1.0 / sigma[j, j]) * numer / denom if sigma[j, j] > 0 else 0.0

    row_sums = theta.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0
    theta_norm = theta / row_sums
    from_others = {}
    for i, name in enumerate(names):
        from_others[name] = float(theta_norm[i, :].sum() - theta_norm[i, i])
    return from_others


def compute_asym_spillover(returns: pd.DataFrame) -> pd.DataFrame:
    pos_var = returns.clip(lower=0.0) ** 2
    neg_var = (-returns.clip(upper=0.0)) ** 2
    output = pd.DataFrame(index=returns.index, columns=returns.columns, dtype=float)
    endpoints: list[pd.Timestamp] = []

    for end_idx in range(ASYM_WINDOW, len(returns) + 1, ASYM_STEP):
        end_date = returns.index[end_idx - 1]
        pos_win = pos_var.iloc[end_idx - ASYM_WINDOW:end_idx].dropna()
        neg_win = neg_var.iloc[end_idx - ASYM_WINDOW:end_idx].dropna()
        if len(pos_win) < ASYM_WINDOW or len(neg_win) < ASYM_WINDOW:
            continue
        try:
            pos_from = generalized_spillover(pos_win)
            neg_from = generalized_spillover(neg_win)
        except Exception:
            continue
        for asset in returns.columns:
            output.loc[end_date, asset] = neg_from[asset] - pos_from[asset]
        endpoints.append(end_date)

    output = output.sort_index().ffill()
    return output


def build_target(r2: pd.Series, horizon: int) -> pd.Series:
    vals = r2.to_numpy(dtype=float)
    out = np.full(len(vals), np.nan, dtype=float)
    for i in range(len(vals) - horizon):
        future = vals[i + 1:i + 1 + horizon]
        if np.all(np.isfinite(future)):
            out[i] = float(np.mean(future))
    return pd.Series(out, index=r2.index, name=f"target_{horizon}")


def build_asset_frame(asset: str, returns: pd.DataFrame, asym_spill: pd.DataFrame) -> pd.DataFrame:
    r = returns[asset].copy()
    r2 = r.pow(2)
    abs_r = r.abs()
    jump_threshold = abs_r.rolling(252).quantile(0.95)
    jump_proxy = r2.where(abs_r > jump_threshold, 0.0)
    asym_raw = asym_spill[asset]
    asym_mean = asym_raw.rolling(252).mean()
    asym_std = asym_raw.rolling(252).std()
    asym_z = ((asym_raw - asym_mean) / asym_std.replace(0.0, np.nan)).clip(-3.0, 3.0)
    frame = pd.DataFrame(
        {
            "ret": r,
            "r2": r2,
            "rv_1": r2.rolling(1).mean(),
            "rv_5": r2.rolling(5).mean(),
            "rv_22": r2.rolling(22).mean(),
            "jump_proxy": jump_proxy,
            "asym_spill": asym_z,
        }
    )
    for col in ["rv_1", "rv_5", "rv_22", "jump_proxy", "asym_spill"]:
        frame[col] = frame[col].shift(1)
    for horizon in HORIZONS:
        frame[f"target_{horizon}"] = build_target(r2, horizon)
    return frame


def fit_ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    X1 = np.column_stack([np.ones(len(X)), X])
    return np.linalg.lstsq(X1, y, rcond=None)[0]


def predict_ols(beta: np.ndarray, x: np.ndarray, floor_value: float) -> float:
    pred = float(np.r_[1.0, x] @ beta)
    return max(pred, floor_value, EPS)


def run_expanding_forecast(df: pd.DataFrame, feature_cols: list[str], target_col: str) -> ForecastResult:
    use = df[feature_cols + [target_col]].dropna().copy()
    if len(use) <= INITIAL_TRAIN + 50:
        raise RuntimeError(f"not enough rows for {target_col} {feature_cols}")

    preds = []
    actual = []
    dates: list[str] = []
    final_beta = None

    for idx in range(INITIAL_TRAIN, len(use)):
        train = use.iloc[:idx]
        test = use.iloc[idx]
        X_train = train[feature_cols].to_numpy(dtype=float)
        y_train = train[target_col].to_numpy(dtype=float)
        beta = fit_ols(X_train, y_train)
        floor_value = max(EPS, float(np.nanpercentile(y_train, 1)) * 0.1)
        pred = predict_ols(beta, test[feature_cols].to_numpy(dtype=float), floor_value)
        preds.append(pred)
        actual.append(float(test[target_col]))
        dates.append(str(use.index[idx].date()))
        final_beta = beta

    preds_arr = np.asarray(preds, dtype=float)
    actual_arr = np.asarray(actual, dtype=float)
    mse = float(np.mean((actual_arr - preds_arr) ** 2))
    beta_names = ["const"] + feature_cols
    final_betas = {name: float(val) for name, val in zip(beta_names, final_beta)}
    return ForecastResult(
        qlike_score=qlike(actual_arr, preds_arr),
        mse=mse,
        mean_pred=float(np.mean(preds_arr)),
        n_test=int(len(preds_arr)),
        preds=preds_arr,
        actual=actual_arr,
        dates=dates,
        final_betas=final_betas,
    )


def summarize_data(prices: pd.DataFrame, returns: pd.DataFrame) -> dict:
    out = {
        "price_start": str(prices.index[0].date()),
        "price_end": str(prices.index[-1].date()),
        "n_prices": int(len(prices)),
        "n_returns": int(len(returns)),
        "assets": {},
    }
    for asset in returns.columns:
        s = returns[asset]
        out["assets"][asset] = {
            "n": int(s.notna().sum()),
            "mean_return": float(s.mean()),
            "std_return": float(s.std()),
            "mean_abs_return": float(s.abs().mean()),
        }
    return out


def aggregate_results(all_results: dict) -> dict:
    by_horizon: dict[str, dict[str, dict[str, float]]] = {}
    for horizon in HORIZONS:
        key_h = str(horizon)
        by_horizon[key_h] = {}
        baseline_qs = [all_results[a][key_h]["models"]["HAR-RV"]["qlike"] for a in TICKERS]
        for model in ["HAR-J", "HAR-AS", "HAR-J-AS"]:
            deltas = []
            harvey = 0
            wins = 0
            for asset in TICKERS:
                asset_pack = all_results[asset][key_h]
                base_q = asset_pack["models"]["HAR-RV"]["qlike"]
                mod_q = asset_pack["models"][model]["qlike"]
                deltas.append((base_q - mod_q) / base_q if base_q > 0 else math.nan)
                if mod_q < base_q:
                    wins += 1
                if asset_pack["dm_vs_baseline"][model]["harvey_pass"]:
                    harvey += 1
            by_horizon[key_h][model] = {
                "mean_qlike_delta_pct": float(np.nanmean(deltas) * 100.0),
                "asset_win_count": int(wins),
                "harvey_pass_count": int(harvey),
                "baseline_mean_qlike": float(np.mean(baseline_qs)),
            }
    return by_horizon


def plot_qlike_heatmap(all_results: dict) -> None:
    rows = []
    labels = []
    for asset in TICKERS:
        for horizon in HORIZONS:
            base_q = all_results[asset][str(horizon)]["models"]["HAR-RV"]["qlike"]
            row = []
            for model in ["HAR-J", "HAR-AS", "HAR-J-AS"]:
                mod_q = all_results[asset][str(horizon)]["models"][model]["qlike"]
                row.append((base_q - mod_q) / base_q * 100.0)
            rows.append(row)
            labels.append(f"{asset} h={horizon}")
    arr = np.asarray(rows, dtype=float)
    fig, ax = plt.subplots(figsize=(8, 10))
    im = ax.imshow(arr, cmap="RdBu_r", aspect="auto", vmin=-3, vmax=3)
    ax.set_xticks(range(3))
    ax.set_xticklabels(["HAR-J", "HAR-AS", "HAR-J-AS"])
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_title("QLIKE delta vs HAR-RV baseline (%)")
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label("Improvement (+) / Deterioration (-)")
    fig.tight_layout()
    fig.savefig(FIG_QI_PATH, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_asym_spillover(asym_spill: pd.DataFrame) -> None:
    fig, axes = plt.subplots(len(TICKERS), 1, figsize=(10, 9), sharex=True)
    for ax, asset in zip(axes, TICKERS):
        s = asym_spill[asset].dropna()
        ax.plot(s.index, s.values, color="#2f4f4f", linewidth=1.0)
        ax.axhline(0.0, color="gray", linestyle="--", linewidth=0.8)
        ax.set_ylabel(asset)
    axes[0].set_title("Bad-minus-good directional spillover from others")
    fig.tight_layout()
    fig.savefig(FIG_ASYM_PATH, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    prices = download_prices()
    returns = np.log(prices).diff().dropna()
    asym_spill = compute_asym_spillover(returns)

    data_summary = summarize_data(prices, returns)
    all_results: dict[str, dict] = {}

    for asset in TICKERS:
        frame = build_asset_frame(asset, returns, asym_spill)
        all_results[asset] = {}
        for horizon in HORIZONS:
            target_col = f"target_{horizon}"
            model_cols = {
                "HAR-RV": ["rv_1", "rv_5", "rv_22"],
                "HAR-J": ["rv_1", "rv_5", "rv_22", "jump_proxy"],
                "HAR-AS": ["rv_1", "rv_5", "rv_22", "asym_spill"],
                "HAR-J-AS": ["rv_1", "rv_5", "rv_22", "jump_proxy", "asym_spill"],
            }
            horizon_pack = {"models": {}, "dm_vs_baseline": {}}
            cache: dict[str, ForecastResult] = {}
            for model_name, cols in model_cols.items():
                fr = run_expanding_forecast(frame, cols, target_col)
                cache[model_name] = fr
            common_index = None
            aligned_frames = {}
            for model_name, fr in cache.items():
                rf = result_frame(fr)
                aligned_frames[model_name] = rf
                common_index = rf.index if common_index is None else common_index.intersection(rf.index)
            common_index = common_index.sort_values()
            for model_name, fr in cache.items():
                rf = aligned_frames[model_name].loc[common_index]
                actual_aligned = rf["actual"].to_numpy(dtype=float)
                pred_aligned = rf["pred"].to_numpy(dtype=float)
                horizon_pack["models"][model_name] = {
                    "qlike": qlike(actual_aligned, pred_aligned),
                    "mse": float(np.mean((actual_aligned - pred_aligned) ** 2)),
                    "mean_prediction": float(np.mean(pred_aligned)),
                    "n_test": int(len(pred_aligned)),
                    "final_betas": fr.final_betas,
                }
            baseline = cache["HAR-RV"]
            for model_name in ["HAR-J", "HAR-AS", "HAR-J-AS"]:
                fr = cache[model_name]
                losses, base_losses = aligned_losses(fr, baseline)
                dm_t, dm_p = dm_test(losses, base_losses, h=horizon)
                horizon_pack["dm_vs_baseline"][model_name] = {
                    "t_stat": float(dm_t),
                    "p_value": float(dm_p),
                    "harvey_pass": bool(abs(dm_t) > 3.0),
                    "better_than_baseline": bool(fr.qlike_score < baseline.qlike_score),
                    "qlike_delta_pct": float((baseline.qlike_score - fr.qlike_score) / baseline.qlike_score * 100.0),
                }
            all_results[asset][str(horizon)] = horizon_pack

    aggregate = aggregate_results(all_results)
    plot_qlike_heatmap(all_results)
    plot_asym_spillover(asym_spill)

    key_findings = []
    for horizon in HORIZONS:
        agg = aggregate[str(horizon)]
        best = max(agg.items(), key=lambda kv: kv[1]["mean_qlike_delta_pct"])
        key_findings.append(
            f"h={horizon}: best average delta = {best[0]} {best[1]['mean_qlike_delta_pct']:+.3f}% "
            f"(wins {best[1]['asset_win_count']}/5, Harvey {best[1]['harvey_pass_count']}/5)"
        )

    results = {
        "experiment_id": "research_rp_f2b1b83d49",
        "title": "Jump proxy x sign-asymmetry spillover controls in HAR with daily ETF proxies",
        "timestamp": pd.Timestamp.now("UTC").isoformat(),
        "data": {
            "source": "yfinance adjusted close",
            "tickers": TICKERS,
            "sample": data_summary,
        },
        "methodology": {
            "target": "future mean squared log return over 1/5/22 trading days",
            "baseline_model": "HAR-RV proxy on lagged 1/5/22 averages of daily squared returns",
            "jump_proxy": "lagged daily squared return on days where |r_t| exceeds its trailing 252-day 95th percentile",
            "asym_spillover_proxy": "rolling bad-minus-good directional spillover from others via generalized FEVD on positive vs negative semivariance panels",
            "spillover_window": ASYM_WINDOW,
            "spillover_step": ASYM_STEP,
            "spillover_var_lag": VAR_LAG,
            "fevd_horizon": FEVD_H,
            "oos_scheme": f"expanding window with initial train {INITIAL_TRAIN}",
            "loss": "QLIKE on daily squared-return proxy",
            "dm_test": "volpred.stats.model_evaluation.dm_test (HAC / Newey-West style)",
            "lookahead_guard": "all predictors explicitly shifted by 1 trading day",
        },
        "literature": [
            {
                "title": "Forecasting the Realized Volatility of Stock Markets: The Roles of Jumps and Asymmetric Spillovers",
                "authors": "Al Rababaa, Mensi, McMillan, Kang",
                "year": 2025,
                "doi": "10.1002/for.3219",
                "url": "https://onlinelibrary.wiley.com/doi/abs/10.1002/for.3219",
            },
            {
                "title": "Asymmetric Volatility Connectedness on the Forex Market",
                "authors": "Barunik, Kocenda, Vacha",
                "year": 2017,
                "doi": "10.1016/j.jimonfin.2017.06.003",
                "url": "https://doi.org/10.1016/j.jimonfin.2017.06.003",
            },
            {
                "title": "Good Volatility, Bad Volatility: Signed Jumps and the Persistence of Volatility",
                "authors": "Patton, Sheppard",
                "year": 2015,
                "doi": "10.1162/REST_a_00503",
                "url": "https://direct.mit.edu/rest/article/97/3/683/58249/Good-Volatility-Bad-Volatility-Signed-Jumps-and",
            },
            {
                "title": "A Simple Approximate Long-Memory Model of Realized Volatility",
                "authors": "Corsi",
                "year": 2009,
                "doi": "10.1093/jjfinec/nbp001",
                "url": "https://doi.org/10.1093/jjfinec/nbp001",
            },
        ],
        "results": all_results,
        "aggregate": aggregate,
        "key_findings": key_findings,
        "artifacts": {
            "qlike_heatmap": FIG_QI_PATH.name,
            "asym_spillover_timeseries": FIG_ASYM_PATH.name,
        },
        "limitations": [
            "This uses daily squared-return proxies rather than 5-minute realized variance, so it is a low-frequency approximation of the paper design.",
            "The jump regressor is an exceedance proxy, not a formal BNS jump decomposition.",
            "Directional spillovers are estimated with fixed VAR lag 1 and rolling step 5 for tractability.",
        ],
    }
    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps({"ok": True, "results_path": str(RESULTS_PATH)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
