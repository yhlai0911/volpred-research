"""K1337-v2: Yield-curve dV/dt vs SPY forward realized variance.

This is a corrective rerun of experiments/k1337 after Codex review found
forward-label lookahead in expanding OLS. The hard fix is that, when
forecasting row i, a training row j is admissible only if its forward target
window has fully ended before i: target_end_pos(j) < forecast_pos(i).

Outputs:
    experiments/k1337_v2/K1337_v2_results.json
    experiments/k1337_v2/K1337_v2_overview.png
    experiments/k1337_v2/K1337_v2_grid.png
"""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

SEED = 42
np.random.seed(SEED)

EXP_ID = "K1337_v2"
EXP_DIR = Path(__file__).resolve().parent
DATA_DIR = EXP_DIR / "data"
RESULTS_PATH = EXP_DIR / "K1337_v2_results.json"
FIG_OVERVIEW = EXP_DIR / "K1337_v2_overview.png"
FIG_GRID = EXP_DIR / "K1337_v2_grid.png"

START_DATE = "2014-01-01"
END_DATE = "2026-06-15"

MARKET_TICKERS = ["^VIX", "SPY", "XLF", "XLU"]
YIELD_TICKERS = ["^TNX", "^IRX", "^FVX"]
TICKERS = [*YIELD_TICKERS, *MARKET_TICKERS]
SLOPE_SPECS = [
    ("TNX_minus_IRX", "^TNX", "^IRX"),
    ("TNX_minus_FVX", "^TNX", "^FVX"),
]
N_WINDOWS = [5, 10, 20]
H_HORIZONS = [5, 10, 20]

REGIME_Q_HI = 0.80
REGIME_Q_LO = 0.20
ROLLING_REGIME_WINDOW = 252

HAR_INIT = 504
HAR_REFIT_EVERY = 21
BOOTSTRAP_REPS = 1000
BLOCK_LEN_FACTOR = 1.5

VAR_FLOOR = 1e-8
VAR_CEILING = 4.0  # annualized variance; 200% ann vol cap, applied to both models


@dataclass
class ForecastBundle:
    yhat: pd.Series
    first_forecast_date: str | None
    first_train_count: int
    min_train_count: int
    max_train_count: int
    n_refits: int


@dataclass
class SpecResult:
    spec_name: str
    N: int
    H: int
    n_obs: int
    baseline_qlike: float
    augmented_qlike: float
    improvement_pct: float
    dm_t: float
    dm_p: float
    boot_mean: float
    boot_ci_lo: float
    boot_ci_hi: float
    baseline_first_forecast_date: str | None
    augmented_first_forecast_date: str | None
    min_train_count: int
    max_train_count: int
    n_refits_baseline: int
    n_refits_augmented: int
    regime_table: dict[str, dict[str, float | int]]


def fetch_yfinance_close(ticker: str) -> pd.Series:
    """Download one ticker at a time; this is more reliable for Yahoo yield indexes."""
    best = pd.Series(dtype=float, name=ticker)
    for attempt in range(5):
        raw = yf.download(
            ticker,
            start=START_DATE,
            end=END_DATE,
            progress=False,
            auto_adjust=False,
            threads=False,
            timeout=20,
        )
        if raw.empty or "Close" not in raw:
            continue
        close = raw["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close = pd.to_numeric(close, errors="coerce")
        close.name = ticker
        if close.notna().sum() > best.notna().sum():
            best = close
        if best.notna().sum() >= 1000:
            return best
        print(f"[data] sparse {ticker} attempt={attempt + 1}, obs={best.notna().sum()}")
    return best


def cache_is_usable(close: pd.DataFrame) -> bool:
    """Reject partial yfinance caches with missing yield columns."""
    if not all(col in close.columns for col in TICKERS):
        return False
    min_market_obs = close[MARKET_TICKERS].notna().sum().min()
    min_yield_obs = close[YIELD_TICKERS].notna().sum().min()
    return bool(min_market_obs > 1000 and min_yield_obs > 1000)


def fetch_data() -> pd.DataFrame:
    """Load cached closes/yields or download each yfinance ticker separately."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = DATA_DIR / "close.csv"
    if cache_path.exists():
        close = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        close.index.name = "Date"
        if cache_is_usable(close):
            return close
        print("[data] cached close.csv failed completeness check; rebuilding")

    print(f"[data] downloading {TICKERS} one-by-one from yfinance")
    pieces: list[pd.Series] = []
    for ticker in TICKERS:
        s = fetch_yfinance_close(ticker)
        if s.notna().sum() < 1000:
            raise RuntimeError(f"yfinance download failed for {ticker}: obs={s.notna().sum()}")
        pieces.append(s)
    close = pd.concat(pieces, axis=1, sort=True).sort_index()
    close = close.loc[START_DATE:END_DATE]
    # Align yield observations to equity trading dates without using future data.
    equity_index = close["SPY"].dropna().index
    close = close.reindex(equity_index).ffill()
    missing = [t for t in TICKERS if t not in close.columns]
    if missing:
        raise RuntimeError(f"Missing downloaded tickers: {missing}")
    if not cache_is_usable(close):
        obs = close.notna().sum().to_dict()
        raise RuntimeError(f"Downloaded data failed completeness check: {obs}")
    close.to_csv(cache_path)
    return close


def build_features(close: pd.DataFrame) -> pd.DataFrame:
    """Build daily features on the original trading-day index."""
    close = close.sort_index().copy()
    feats = pd.DataFrame(index=close.index)
    feats["pos"] = np.arange(len(feats), dtype=int)

    for name, long_t, short_t in SLOPE_SPECS:
        feats[f"slope_{name}"] = close[long_t] - close[short_t]
        for N in N_WINDOWS:
            feats[f"dslope_{name}_N{N}"] = feats[f"slope_{name}"].diff(N)

    feats["spy_ret"] = np.log(close["SPY"]).diff()
    feats["vix"] = close["^VIX"]
    if "XLF" in close:
        feats["xlf_ret"] = np.log(close["XLF"]).diff()
    if "XLU" in close:
        feats["xlu_ret"] = np.log(close["XLU"]).diff()
    return feats


def realized_var_daily(returns: pd.Series) -> pd.Series:
    """Annualized daily variance proxy from close-to-close returns."""
    return returns.pow(2) * 252.0


def forward_target(returns: pd.Series, H: int) -> pd.DataFrame:
    """Forward annualized variance/vol target over returns [t+1, ..., t+H]."""
    arr = returns.to_numpy(dtype=float)
    n = len(returns)
    fwd_var = np.full(n, np.nan)
    target_end_pos = np.full(n, np.nan)
    for i in range(n - H):
        window = arr[i + 1 : i + 1 + H]
        if np.isfinite(window).sum() == H:
            fwd_var[i] = 252.0 * float(np.mean(window**2))
            target_end_pos[i] = i + H
    out = pd.DataFrame(index=returns.index)
    out[f"fwd_var_{H}"] = fwd_var
    out[f"fwd_vol_{H}"] = np.sqrt(fwd_var)
    out[f"target_end_pos_{H}"] = target_end_pos
    return out


def make_log_har_features(rv_daily: pd.Series) -> pd.DataFrame:
    """HAR features at date t using only RV information through t-1."""
    raw = pd.DataFrame(index=rv_daily.index)
    raw["rv_d"] = rv_daily
    raw["rv_w"] = rv_daily.rolling(5).mean()
    raw["rv_m"] = rv_daily.rolling(22).mean()
    lagged = raw.shift(1)
    out = pd.DataFrame(index=rv_daily.index)
    for col in ["rv_d", "rv_w", "rv_m"]:
        out[f"log_{col}"] = np.log(np.clip(lagged[col], VAR_FLOOR, VAR_CEILING))
    return out


def expanding_log_ols_forecast(
    model_df: pd.DataFrame,
    feature_cols: list[str],
    H: int,
    init: int = HAR_INIT,
    refit_every: int = HAR_REFIT_EVERY,
) -> ForecastBundle:
    """Causal expanding OLS in log-variance space.

    For a forecast row with original position i, rows are trainable only when
    target_end_pos < i. This is stricter than df.iloc[:i] and eliminates the
    forward-label overlap that invalidated K1337 v1.
    """
    required = ["target_var", "target_end_pos", "forecast_pos", *feature_cols]
    df = model_df.dropna(subset=required).copy()
    yhat = pd.Series(np.nan, index=df.index, name="yhat")
    if df.empty:
        return ForecastBundle(yhat, None, 0, 0, 0, 0)

    coef: np.ndarray | None = None
    last_fit_pos: int | None = None
    first_forecast_date: str | None = None
    first_train_count = 0
    train_counts: list[int] = []
    n_refits = 0

    for idx, row in df.iterrows():
        forecast_pos = int(row["forecast_pos"])
        train = df[df["target_end_pos"] < forecast_pos]
        if len(train) < init:
            continue

        if coef is None or last_fit_pos is None or forecast_pos - last_fit_pos >= refit_every:
            x_train = train[feature_cols].to_numpy(dtype=float)
            x_train = np.c_[np.ones(len(x_train)), x_train]
            y_train = np.log(np.clip(train["target_var"].to_numpy(dtype=float), VAR_FLOOR, VAR_CEILING))
            coef, *_ = np.linalg.lstsq(x_train, y_train, rcond=None)
            last_fit_pos = forecast_pos
            train_counts.append(len(train))
            n_refits += 1

        x_now = row[feature_cols].to_numpy(dtype=float)
        pred_log = float(np.r_[1.0, x_now] @ coef)
        pred_var = float(np.clip(math.exp(pred_log), VAR_FLOOR, VAR_CEILING))
        yhat.loc[idx] = pred_var
        if first_forecast_date is None:
            first_forecast_date = str(pd.Timestamp(idx).date())
            first_train_count = len(train)

    return ForecastBundle(
        yhat=yhat,
        first_forecast_date=first_forecast_date,
        first_train_count=int(first_train_count),
        min_train_count=int(min(train_counts)) if train_counts else 0,
        max_train_count=int(max(train_counts)) if train_counts else 0,
        n_refits=int(n_refits),
    )


def qlike(y_true: np.ndarray, y_pred: np.ndarray) -> np.ndarray:
    """Patton QLIKE variance loss: log(yhat) + y/yhat; lower is better."""
    yt = np.clip(np.asarray(y_true, dtype=float), VAR_FLOOR, VAR_CEILING)
    yp = np.clip(np.asarray(y_pred, dtype=float), VAR_FLOOR, VAR_CEILING)
    return np.log(yp) + yt / yp


def dm_test_hac(loss_diff: np.ndarray, lag: int) -> tuple[float, float]:
    """Diebold-Mariano mean loss-difference test with Newey-West HAC SE."""
    d = np.asarray(loss_diff, dtype=float)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 30:
        return float("nan"), float("nan")
    mean_d = float(np.mean(d))
    centered = d - mean_d
    var_d = float(np.mean(centered * centered))
    for k in range(1, min(lag, n - 1) + 1):
        weight = 1.0 - k / (lag + 1.0)
        cov = float(np.mean(centered[k:] * centered[:-k]))
        var_d += 2.0 * weight * cov
    se = math.sqrt(max(var_d, 1e-14) / n)
    t_stat = mean_d / se
    from scipy.stats import norm

    p_val = 2.0 * (1.0 - norm.cdf(abs(t_stat)))
    return float(t_stat), float(p_val)


def stationary_block_bootstrap_mean(
    loss_diff: np.ndarray,
    block_len: float,
    reps: int = BOOTSTRAP_REPS,
    seed: int = SEED,
) -> tuple[float, float, float, float]:
    """Stationary block bootstrap of mean loss difference."""
    d = np.asarray(loss_diff, dtype=float)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 30:
        return float("nan"), float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    p_geom = 1.0 / max(float(block_len), 1.0)
    means = np.empty(reps)
    for b in range(reps):
        sample = np.empty(n)
        sample_pos = 0
        idx = int(rng.integers(0, n))
        while sample_pos < n:
            sample[sample_pos] = d[idx]
            sample_pos += 1
            if rng.random() < p_geom:
                idx = int(rng.integers(0, n))
            else:
                idx = (idx + 1) % n
        means[b] = float(np.mean(sample))
    return (
        float(np.mean(d)),
        float(np.quantile(means, 0.025)),
        float(np.quantile(means, 0.975)),
        float(np.mean(means < 0.0)),
    )


def rolling_regime(signal_lagged: pd.Series, window: int = ROLLING_REGIME_WINDOW) -> pd.Series:
    """Classify lagged signal using trailing quantiles that exclude current row."""
    out = pd.Series(index=signal_lagged.index, dtype=object)
    vals = signal_lagged.to_numpy(dtype=float)
    for i in range(len(vals)):
        v = vals[i]
        if i < window or not np.isfinite(v):
            out.iloc[i] = "WARMUP"
            continue
        hist = vals[i - window : i]
        hist = hist[np.isfinite(hist)]
        if len(hist) < window // 2:
            out.iloc[i] = "WARMUP"
            continue
        q_hi = float(np.quantile(hist, REGIME_Q_HI))
        q_lo = float(np.quantile(hist, REGIME_Q_LO))
        if v >= q_hi:
            out.iloc[i] = "FAST_STEEPEN"
        elif v <= q_lo:
            out.iloc[i] = "FAST_FLATTEN"
        else:
            out.iloc[i] = "MID"
    return out


def regime_summary(
    feats: pd.DataFrame,
    sig_col: str,
    fwd: pd.DataFrame,
    H: int,
) -> dict[str, dict[str, float | int]]:
    """Forward-vol descriptive by lagged dslope regime."""
    lagged_signal = feats[sig_col].shift(1)
    regime = rolling_regime(lagged_signal)
    reg_df = pd.concat(
        [
            regime.rename("regime"),
            fwd[f"fwd_vol_{H}"].rename("fwd_vol"),
            fwd[f"fwd_var_{H}"].rename("fwd_var"),
            feats["vix"].shift(1).rename("vix_lag1"),
        ],
        axis=1,
    ).dropna()
    reg_df = reg_df[reg_df["regime"].isin(["FAST_STEEPEN", "FAST_FLATTEN", "MID"])]
    out: dict[str, dict[str, float | int]] = {}
    for label in ["FAST_STEEPEN", "FAST_FLATTEN", "MID"]:
        sub = reg_df[reg_df["regime"] == label]
        if sub.empty:
            continue
        out[label] = {
            "n": int(len(sub)),
            "fwd_vol_mean": float(sub["fwd_vol"].mean()),
            "fwd_vol_median": float(sub["fwd_vol"].median()),
            "fwd_vol_p90": float(sub["fwd_vol"].quantile(0.90)),
            "fwd_var_mean": float(sub["fwd_var"].mean()),
            "vix_lag1_mean": float(sub["vix_lag1"].mean()),
        }
    if "FAST_STEEPEN" in out and "MID" in out:
        out["FAST_STEEPEN_minus_MID"] = {
            "fwd_vol_mean_diff": float(out["FAST_STEEPEN"]["fwd_vol_mean"] - out["MID"]["fwd_vol_mean"]),
            "fwd_var_mean_diff": float(out["FAST_STEEPEN"]["fwd_var_mean"] - out["MID"]["fwd_var_mean"]),
        }
    if "FAST_FLATTEN" in out and "MID" in out:
        out["FAST_FLATTEN_minus_MID"] = {
            "fwd_vol_mean_diff": float(out["FAST_FLATTEN"]["fwd_vol_mean"] - out["MID"]["fwd_vol_mean"]),
            "fwd_var_mean_diff": float(out["FAST_FLATTEN"]["fwd_var_mean"] - out["MID"]["fwd_var_mean"]),
        }
    return out


def run_one_spec(feats: pd.DataFrame, spec_name: str, N: int, H: int) -> SpecResult:
    spy_ret = feats["spy_ret"]
    rv_daily = realized_var_daily(spy_ret)
    har = make_log_har_features(rv_daily)
    fwd = forward_target(spy_ret, H)

    sig_col = f"dslope_{spec_name}_N{N}"
    model_df = pd.concat(
        [
            feats["pos"].rename("forecast_pos"),
            fwd[f"fwd_var_{H}"].rename("target_var"),
            fwd[f"target_end_pos_{H}"].rename("target_end_pos"),
            har,
            feats[sig_col].shift(1).rename("dslope_lag1"),
        ],
        axis=1,
    )

    base_cols = ["log_rv_d", "log_rv_w", "log_rv_m"]
    aug_cols = [*base_cols, "dslope_lag1"]
    baseline = expanding_log_ols_forecast(model_df, base_cols, H)
    augmented = expanding_log_ols_forecast(model_df, aug_cols, H)

    eval_df = pd.concat(
        [
            model_df["target_var"].rename("y"),
            baseline.yhat.rename("baseline"),
            augmented.yhat.rename("augmented"),
        ],
        axis=1,
    ).dropna()
    if len(eval_df) < 30:
        return SpecResult(
            spec_name,
            N,
            H,
            int(len(eval_df)),
            float("nan"),
            float("nan"),
            float("nan"),
            float("nan"),
            float("nan"),
            float("nan"),
            float("nan"),
            float("nan"),
            baseline.first_forecast_date,
            augmented.first_forecast_date,
            min(baseline.min_train_count, augmented.min_train_count),
            max(baseline.max_train_count, augmented.max_train_count),
            baseline.n_refits,
            augmented.n_refits,
            {},
        )

    y = eval_df["y"].to_numpy(dtype=float)
    q_base = qlike(y, eval_df["baseline"].to_numpy(dtype=float))
    q_aug = qlike(y, eval_df["augmented"].to_numpy(dtype=float))
    d = q_aug - q_base
    base_mean = float(np.mean(q_base))
    aug_mean = float(np.mean(q_aug))
    improvement_pct = 100.0 * (base_mean - aug_mean) / abs(base_mean) if base_mean != 0 else float("nan")
    dm_t, dm_p = dm_test_hac(d, lag=max(H - 1, 1))
    boot_mean, boot_lo, boot_hi, _p_aug_better = stationary_block_bootstrap_mean(
        d,
        block_len=BLOCK_LEN_FACTOR * H,
        reps=BOOTSTRAP_REPS,
        seed=SEED + H + N,
    )

    return SpecResult(
        spec_name=spec_name,
        N=N,
        H=H,
        n_obs=int(len(eval_df)),
        baseline_qlike=base_mean,
        augmented_qlike=aug_mean,
        improvement_pct=float(improvement_pct),
        dm_t=dm_t,
        dm_p=dm_p,
        boot_mean=boot_mean,
        boot_ci_lo=boot_lo,
        boot_ci_hi=boot_hi,
        baseline_first_forecast_date=baseline.first_forecast_date,
        augmented_first_forecast_date=augmented.first_forecast_date,
        min_train_count=int(min(baseline.min_train_count, augmented.min_train_count)),
        max_train_count=int(max(baseline.max_train_count, augmented.max_train_count)),
        n_refits_baseline=baseline.n_refits,
        n_refits_augmented=augmented.n_refits,
        regime_table=regime_summary(feats, sig_col, fwd, H),
    )


def secondary_sector_diff(feats: pd.DataFrame) -> dict[str, dict[str, dict[str, float | int]]]:
    """Descriptive sector forward 10d RV by lagged TNX-IRX N=10 regime."""
    out: dict[str, dict[str, dict[str, float | int]]] = {}
    sig = feats["dslope_TNX_minus_IRX_N10"].shift(1)
    regime = rolling_regime(sig)
    for ticker, ret_col in [("SPY", "spy_ret"), ("XLF", "xlf_ret"), ("XLU", "xlu_ret")]:
        if ret_col not in feats:
            continue
        fwd = forward_target(feats[ret_col], 10)
        df = pd.concat([regime.rename("regime"), fwd["fwd_vol_10"].rename("fwd_vol")], axis=1).dropna()
        df = df[df["regime"].isin(["FAST_STEEPEN", "FAST_FLATTEN", "MID"])]
        ticker_out: dict[str, dict[str, float | int]] = {}
        for label in ["FAST_STEEPEN", "FAST_FLATTEN", "MID"]:
            sub = df[df["regime"] == label]
            if not sub.empty:
                ticker_out[label] = {
                    "n": int(len(sub)),
                    "fwd_vol_mean": float(sub["fwd_vol"].mean()),
                    "fwd_vol_median": float(sub["fwd_vol"].median()),
                }
        out[ticker] = ticker_out
    return out


def make_plots(feats: pd.DataFrame, results: list[SpecResult]) -> None:
    """Create overview and 18-cell result plot."""
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
    feats["slope_TNX_minus_IRX"].plot(ax=axes[0], color="C0", lw=1.0)
    axes[0].axhline(0, color="black", lw=0.5, alpha=0.5)
    axes[0].set_ylabel("10y - 3m")
    axes[0].set_title("K1337-v2: Yield curve slope, lagged dV/dt, and SPY RV")

    feats["dslope_TNX_minus_IRX_N10"].shift(1).plot(ax=axes[1], color="C1", lw=1.0)
    axes[1].axhline(0, color="black", lw=0.5, alpha=0.5)
    axes[1].set_ylabel("lagged 10d dslope")

    spy_rv20 = feats["spy_ret"].rolling(20).std() * math.sqrt(252.0)
    spy_rv20.plot(ax=axes[2], color="C3", lw=1.0)
    axes[2].set_ylabel("SPY 20d RV")
    fig.tight_layout()
    fig.savefig(FIG_OVERVIEW, dpi=120)
    plt.close(fig)

    rows: list[dict[str, Any]] = []
    for r in results:
        rows.append(
            {
                "spec": r.spec_name.replace("TNX_minus_", ""),
                "N": r.N,
                "H": r.H,
                "improvement_pct": r.improvement_pct,
                "dm_t": r.dm_t,
            }
        )
    plot_df = pd.DataFrame(rows)
    fig2, axes2 = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    for ax, value_col, title in [
        (axes2[0], "improvement_pct", "QLIKE improvement % (augmented vs baseline)"),
        (axes2[1], "dm_t", "DM t-stat (positive = augmented worse)"),
    ]:
        labels = [f"{row.spec}\nN{row.N}/H{row.H}" for row in plot_df.itertuples()]
        if value_col == "dm_t":
            colors = ["C3" if v > 0 else "C2" for v in plot_df[value_col]]
        else:
            colors = ["C2" if v > 0 else "C3" for v in plot_df[value_col]]
        ax.barh(range(len(plot_df)), plot_df[value_col], color=colors, alpha=0.85)
        ax.axvline(0, color="black", lw=0.8)
        ax.set_yticks(range(len(plot_df)))
        ax.set_yticklabels(labels, fontsize=8)
        ax.set_title(title)
    fig2.tight_layout()
    fig2.savefig(FIG_GRID, dpi=120)
    plt.close(fig2)


def finite_float(x: float) -> float | None:
    return None if not np.isfinite(x) else float(x)


def result_to_dict(r: SpecResult) -> dict[str, Any]:
    return {
        "spec_name": r.spec_name,
        "N": r.N,
        "H": r.H,
        "n_obs": r.n_obs,
        "baseline_log_har_qlike": finite_float(r.baseline_qlike),
        "augmented_log_har_dslope_qlike": finite_float(r.augmented_qlike),
        "improvement_pct": finite_float(r.improvement_pct),
        "dm_t": finite_float(r.dm_t),
        "dm_p": finite_float(r.dm_p),
        "boot_mean_diff": finite_float(r.boot_mean),
        "boot_ci95_lo": finite_float(r.boot_ci_lo),
        "boot_ci95_hi": finite_float(r.boot_ci_hi),
        "baseline_first_forecast_date": r.baseline_first_forecast_date,
        "augmented_first_forecast_date": r.augmented_first_forecast_date,
        "min_train_count": r.min_train_count,
        "max_train_count": r.max_train_count,
        "n_refits_baseline": r.n_refits_baseline,
        "n_refits_augmented": r.n_refits_augmented,
        "regime_table": r.regime_table,
    }


def main() -> None:
    close = fetch_data()
    feats = build_features(close)
    feats = feats.dropna(subset=["spy_ret"]).copy()
    print(f"[data] rows={len(feats)} range={feats.index.min().date()}..{feats.index.max().date()}")

    grid = [(spec_name, N, H) for spec_name, _, _ in SLOPE_SPECS for N in N_WINDOWS for H in H_HORIZONS]
    print(f"[grid] {len(grid)} specs")
    results: list[SpecResult] = []
    for spec_name, N, H in grid:
        print(f"[run] {spec_name} N={N} H={H}")
        res = run_one_spec(feats, spec_name, N, H)
        results.append(res)
        print(
            f"  n={res.n_obs} base={res.baseline_qlike:.6f} aug={res.augmented_qlike:.6f} "
            f"impr={res.improvement_pct:+.3f}% dm_t={res.dm_t:+.3f} "
            f"boot95=[{res.boot_ci_lo:+.6f},{res.boot_ci_hi:+.6f}]"
        )

    make_plots(feats, results)

    pass_specs = [
        r
        for r in results
        if np.isfinite(r.dm_t)
        and r.dm_t < -3.0
        and r.boot_ci_hi < 0.0
        and r.improvement_pct > 0.0
    ]
    cond_specs = [
        r
        for r in results
        if np.isfinite(r.dm_t)
        and -3.0 <= r.dm_t < -2.0
        and r.boot_ci_hi < 0.0
        and r.improvement_pct > 0.25
    ]
    if pass_specs:
        verdict = "PASS"
        verdict_logic = (
            f"{len(pass_specs)} spec(s) clear DM t < -3, bootstrap CI upper < 0, "
            "and positive QLIKE improvement."
        )
    elif cond_specs:
        verdict = "CONDITIONAL_PASS"
        verdict_logic = (
            f"{len(cond_specs)} spec(s) clear suggestive t < -2 and bootstrap CI upper < 0, "
            "but do not clear Harvey-style multi-test t < -3."
        )
    else:
        verdict = "NULL"
        verdict_logic = (
            "No corrected spec clears the pre-set incremental forecasting gate; "
            "yield-curve dV/dt does not improve the symmetric log-HAR baseline."
        )

    best_by_improvement = sorted(results, key=lambda r: (-np.nan_to_num(r.improvement_pct, nan=-999.0), r.dm_t))
    worst_by_improvement = sorted(results, key=lambda r: (np.nan_to_num(r.improvement_pct, nan=999.0), r.dm_t))
    out = {
        "experiment_id": EXP_ID,
        "parent_experiment_id": "K1337",
        "title": "Yield-curve steepening rate dV/dt vs SPY forward realized variance, corrected lookahead-free design",
        "date_run_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "seed": SEED,
        "data": {
            "source": "yfinance daily Close, auto_adjust=False",
            "tickers": TICKERS,
            "start_date": START_DATE,
            "end_date": END_DATE,
            "n_dates_after_spy_return": int(len(feats)),
            "first_date": str(feats.index.min().date()),
            "last_date": str(feats.index.max().date()),
            "cached_close_csv": "experiments/k1337_v2/data/close.csv",
        },
        "design": {
            "v1_failure_fixed": (
                "K1337 v1 used df.iloc[:i] training despite forward labels. "
                "K1337-v2 admits training row j only when target_end_pos(j) < forecast_pos(i), "
                "equivalent to j + H < i on the original trading-day index."
            ),
            "signals": "slope.diff(N) for TNX-IRX and TNX-FVX, with dslope.shift(1) used for model and regime labels.",
            "target": "fwd_var_H(t)=252*mean(r^2 over t+1..t+H); fwd_vol is sqrt(fwd_var).",
            "baseline": "Expanding OLS in log-variance space: log(fwd_var) ~ log_rv_d + log_rv_w + log_rv_m.",
            "augmented_model": "Same log-HAR model plus dslope_lag1. Both models use identical training cutoff, refit cadence, and clipping.",
            "model_clipping": f"Predicted annualized variance clipped to [{VAR_FLOOR}, {VAR_CEILING}] for both baseline and augmented.",
            "regime_definition": (
                f"Regime uses dslope.shift(1); rolling {ROLLING_REGIME_WINDOW}d quantile thresholds "
                "exclude the current row before classifying FAST_STEEPEN/FAST_FLATTEN/MID."
            ),
            "grid": f"{len(grid)} specs = {len(SLOPE_SPECS)} slope specs x {len(N_WINDOWS)} N windows x {len(H_HORIZONS)} horizons.",
            "dm_test": "Newey-West HAC on QLIKE loss diff, lag=max(H-1,1), negative t means augmented better.",
            "bootstrap": f"Stationary block bootstrap on QLIKE loss diff, reps={BOOTSTRAP_REPS}, block_len={BLOCK_LEN_FACTOR}*H, fixed seed offsets from {SEED}.",
            "warmup": HAR_INIT,
            "refit_every": HAR_REFIT_EVERY,
        },
        "results": [result_to_dict(r) for r in results],
        "summary": {
            "best_by_improvement": result_to_dict(best_by_improvement[0]) if best_by_improvement else None,
            "worst_by_improvement": result_to_dict(worst_by_improvement[0]) if worst_by_improvement else None,
            "n_specs": len(results),
            "n_pass_specs": len(pass_specs),
            "n_conditional_specs": len(cond_specs),
            "n_positive_improvement_specs": int(sum(r.improvement_pct > 0 for r in results if np.isfinite(r.improvement_pct))),
            "n_negative_improvement_specs": int(sum(r.improvement_pct < 0 for r in results if np.isfinite(r.improvement_pct))),
            "min_dm_t": finite_float(min((r.dm_t for r in results if np.isfinite(r.dm_t)), default=float("nan"))),
            "max_dm_t": finite_float(max((r.dm_t for r in results if np.isfinite(r.dm_t)), default=float("nan"))),
        },
        "secondary_sector_descriptive": secondary_sector_diff(feats),
        "figures": {
            "overview": str(FIG_OVERVIEW.relative_to(EXP_DIR)),
            "grid": str(FIG_GRID.relative_to(EXP_DIR)),
        },
        "literature": [
            "Corsi (2009), A Simple Approximate Long-Memory Model of Realized Volatility.",
            "Patton (2011), Volatility forecast comparison using imperfect volatility proxies.",
            "Diebold and Mariano (1995), Comparing Predictive Accuracy.",
            "Newey and West (1987), HAC covariance matrix.",
            "Harvey, Liu, and Zhu (2016), multiple-testing discipline for discovered factors.",
        ],
        "research_honesty_notes": [
            "K1337 v1 is preserved as a failed-design preliminary; v2 does not overwrite it.",
            "All model and regime signals use explicit dslope.shift(1).",
            "Forward-label OLS uses target_end_pos < forecast_pos, not df.iloc[:i].",
            "The 18-spec grid is pre-specified by the follow-up task; per-spec p-values are interpreted under a multi-test t-stat threshold.",
            "This is daily close data with squared-return variance proxy, not intraday realized variance.",
        ],
        "verdict": {
            "overall": verdict,
            "logic": verdict_logic,
        },
    }
    RESULTS_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    print(f"[done] verdict={verdict}")
    print(f"[done] wrote {RESULTS_PATH}")


if __name__ == "__main__":
    main()
