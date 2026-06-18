"""K1351: Oil-volatility spillover into U.S. equity volatility.

Research question:
  Do lagged oil-volatility shocks from CL=F / USO add out-of-sample predictive
  value for next-day SPY / XLE / XOP variance beyond each target's own HAR-RV
  state?

Method guards:
  - All oil signals use an explicit `.shift(1)` before being aligned with the
    target variance at date t.
  - Forecasts are expanding-window OOS forecasts. For target date t, training
    rows are strictly earlier than t.
  - Random procedures use seed=42.
  - Success requires OOS QLIKE improvement >= 1%, Newey-West/Harvey t > 3.0,
    and a positive stationary-bootstrap CI for the mean loss improvement.

Outputs:
  - k1351_results.json
  - fig_k1351_oos_qlike.png
  - fig_k1351_oil_vol_context.png
"""

from __future__ import annotations

import json
import math
import sys
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

SEED = 42
np.random.seed(SEED)

EXPERIMENT_ID = "K1351"
OUT_DIR = Path(__file__).resolve().parent
DATA_DIR = OUT_DIR / "data"
RESULTS_PATH = OUT_DIR / "k1351_results.json"
FIG_OOS = OUT_DIR / "fig_k1351_oos_qlike.png"
FIG_CONTEXT = OUT_DIR / "fig_k1351_oil_vol_context.png"

START_DATE = "2010-01-01"
END_DATE = "2026-06-19"  # yfinance end is exclusive; sample end is reported from data.
OOS_START = pd.Timestamp("2018-01-01")
OIL_SOURCES = ["CL=F", "USO"]
TARGETS = ["SPY", "XLE", "XOP"]
TICKERS = [*OIL_SOURCES, *TARGETS]

MIN_TRAIN_OBS = 756
REFIT_EVERY = 21
HARVEY_T = 3.0
IMPROVEMENT_GATE_PCT = 1.0
BOOTSTRAP_REPS = 1000
BOOTSTRAP_BLOCK_LEN = 5.0
VAR_FLOOR = 1e-10
VAR_CEILING = 25.0

RELATED_PRIOR = [
    {
        "id": "K628b",
        "note": "Cross-asset Diebold-Yilmaz / Granger network included USO but used smoothed network spillovers, not OOS HAR-X forecasting.",
    },
    {
        "id": "trending_2026_06_12_oil_vix_spillover",
        "note": "Descriptive Iran-war oil/VIX diagnostic found weak next-day oil-to-equity lead-lag correlations.",
    },
    {
        "id": "K1481",
        "note": "Inventory-surprise crude-RV pilot focused on forecasting CL=F itself, not equity variance spillover.",
    },
]

LITERATURE = [
    {
        "citation": "Arouri, Jouini, and Nguyen (2011), Journal of International Money and Finance 30(7), 1387-1405.",
        "url": "https://ideas.repec.org/a/eee/jimfin/v30y2011i7p1387-1405.html",
        "role": "Sector-level oil-stock volatility transmission motivates testing XLE/XOP separately from SPY.",
    },
    {
        "citation": "Diebold and Yilmaz (2012), International Journal of Forecasting 28(1), 57-66.",
        "url": "https://econpapers.repec.org/article/eeeintfor/v_3a28_3ay_3a2012_3ai_3a1_3ap_3a57-66.htm",
        "role": "General directional volatility-spillover framing; K1351 uses a simpler forecasting test.",
    },
    {
        "citation": "Degiannakis, Filis, and Arora (2017), EIA working paper, Oil Prices and Stock Markets.",
        "url": "https://www.eia.gov/workingpapers/pdf/oil_prices_stockmarkets.pdf",
        "role": "Survey notes heterogeneous sector effects and evidence that oil volatility can transmit to stock volatility.",
    },
    {
        "citation": "Malik and Hammoudeh (2007), International Review of Economics & Finance 16(3), 357-368.",
        "url": "https://www.sciencedirect.com/science/article/pii/S105905600500076X",
        "role": "Early oil/equity shock and volatility-transmission evidence; used as background, not as a replicated model.",
    },
]


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
    oil_source: str
    target: str
    n_obs: int
    eval_start: str | None
    eval_end: str | None
    baseline_qlike: float
    augmented_qlike: float
    qlike_improvement_pct: float
    mean_loss_improvement: float
    hac_t: float
    hac_p: float
    bootstrap_ci_low: float
    bootstrap_ci_high: float
    bootstrap_prob_improvement_positive: float
    first_forecast_date: str | None
    first_train_count: int
    min_train_count: int
    max_train_count: int
    n_refits_baseline: int
    n_refits_augmented: int
    high_oil_vol_regime: dict[str, float | int]
    pass_gate: bool


def finite_float(value: Any) -> float | None:
    try:
        value_f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value_f):
        return None
    return value_f


def safe_ticker_name(ticker: str) -> str:
    return ticker.replace("^", "").replace("=", "_").replace(".", "_").replace("/", "_")


def extract_close(raw: pd.DataFrame, ticker: str) -> pd.Series:
    if raw is None or raw.empty:
        return pd.Series(dtype=float, name=ticker)
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        if "Close" in df.columns.get_level_values(0):
            close = df["Close"]
        elif "Close" in df.columns.get_level_values(-1):
            close = df.xs("Close", axis=1, level=-1)
        else:
            return pd.Series(dtype=float, name=ticker)
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
    else:
        if "Close" not in df.columns:
            return pd.Series(dtype=float, name=ticker)
        close = df["Close"]
    close = pd.to_numeric(close, errors="coerce")
    close.name = ticker
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close.dropna()


def fallback_from_trending_cache(ticker: str) -> pd.Series:
    cache = OUT_DIR.parent / "trending_2026_06_12_oil_vix_spillover" / "close_prices.csv"
    if not cache.exists():
        return pd.Series(dtype=float, name=ticker)
    try:
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
    except Exception:
        return pd.Series(dtype=float, name=ticker)
    if ticker not in df.columns:
        return pd.Series(dtype=float, name=ticker)
    s = pd.to_numeric(df[ticker], errors="coerce").dropna()
    s.name = ticker
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s


def fetch_close(ticker: str) -> pd.Series:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = DATA_DIR / f"{safe_ticker_name(ticker)}.csv"
    if cache_path.exists():
        try:
            cached = pd.read_csv(cache_path, index_col=0, parse_dates=True)
            if "Close" in cached.columns and cached["Close"].notna().sum() > 1000:
                s = pd.to_numeric(cached["Close"], errors="coerce").dropna()
                s.name = ticker
                s.index = pd.to_datetime(s.index).tz_localize(None)
                return s
        except Exception:
            pass

    best = pd.Series(dtype=float, name=ticker)
    for attempt in range(3):
        try:
            raw = yf.download(
                ticker,
                start=START_DATE,
                end=END_DATE,
                auto_adjust=True,
                progress=False,
                threads=False,
                timeout=30,
            )
            s = extract_close(raw, ticker)
            if s.notna().sum() > best.notna().sum():
                best = s
            if best.notna().sum() > 1000:
                best.to_frame("Close").to_csv(cache_path)
                return best
        except Exception as exc:  # pragma: no cover - network path
            print(f"[data] download failed {ticker} attempt={attempt + 1}: {exc}", file=sys.stderr)

    fallback = fallback_from_trending_cache(ticker)
    if fallback.notna().sum() > best.notna().sum():
        best = fallback
    if best.notna().sum() <= 1000:
        raise RuntimeError(f"Insufficient close data for {ticker}: obs={best.notna().sum()}")
    best.to_frame("Close").to_csv(cache_path)
    return best


def fetch_close_panel() -> pd.DataFrame:
    pieces = [fetch_close(ticker) for ticker in TICKERS]
    close = pd.concat(pieces, axis=1, sort=True).sort_index()
    close = close.loc[START_DATE:END_DATE]
    if close[TARGETS].notna().sum().min() <= 1000:
        raise RuntimeError(f"Target ticker coverage too sparse: {close[TARGETS].notna().sum().to_dict()}")

    # Use SPY's equity-trading calendar and carry oil futures only from the past.
    equity_index = close["SPY"].dropna().index
    close = close.reindex(equity_index).ffill()
    close = close.dropna(subset=TICKERS)
    if close.empty:
        raise RuntimeError("No common close panel after alignment.")
    close.to_csv(DATA_DIR / "close_panel.csv")
    return close


def close_to_close_returns(close: pd.DataFrame) -> pd.DataFrame:
    """Use simple returns because CL=F briefly traded negative in April 2020."""
    return close.pct_change(fill_method=None)


def annualized_daily_variance(returns: pd.Series) -> pd.Series:
    return returns.pow(2) * 252.0


def log_var(series: pd.Series) -> pd.Series:
    return np.log(series.astype(float).clip(lower=VAR_FLOOR, upper=VAR_CEILING))


def build_model_frame(close: pd.DataFrame, oil_source: str, target: str) -> pd.DataFrame:
    ret = close_to_close_returns(close)
    target_rv = annualized_daily_variance(ret[target])
    oil_rv = annualized_daily_variance(ret[oil_source])

    target_raw = pd.DataFrame(index=close.index)
    target_raw["target_rv_lag1"] = target_rv
    target_raw["target_rv_lag5"] = target_rv.rolling(5).mean()
    target_raw["target_rv_lag22"] = target_rv.rolling(22).mean()
    target_signal = target_raw.shift(1)

    oil_raw = pd.DataFrame(index=close.index)
    oil_raw["oil_rv_lag1"] = oil_rv
    oil_raw["oil_rv_lag5"] = oil_rv.rolling(5).mean()
    oil_raw["oil_rv_lag22"] = oil_rv.rolling(22).mean()
    oil_raw["oil_vov_lag22"] = oil_rv.rolling(22).std()

    # Critical lookahead guard: every oil feature is known only through t-1.
    oil_signal = oil_raw.shift(1)

    df = pd.DataFrame(index=close.index)
    df["target_var"] = target_rv
    for col in target_signal.columns:
        df[f"log_{col}"] = log_var(target_signal[col])
    for col in oil_signal.columns:
        df[f"log_{col}"] = log_var(oil_signal[col])

    oil_rv_lag1 = oil_rv.shift(1)
    oil_threshold = oil_rv_lag1.rolling(252).quantile(0.95).shift(1)
    df["high_oil_vol"] = (oil_rv_lag1 > oil_threshold).astype(float)
    return df


def expanding_log_ols_forecast(
    model_df: pd.DataFrame,
    feature_cols: list[str],
    min_train_obs: int = MIN_TRAIN_OBS,
    refit_every: int = REFIT_EVERY,
) -> ForecastBundle:
    required = ["target_var", *feature_cols]
    df = model_df.dropna(subset=required).copy()
    yhat = pd.Series(np.nan, index=df.index, name="yhat")
    if df.empty:
        return ForecastBundle(yhat, None, 0, 0, 0, 0)

    coef: np.ndarray | None = None
    last_refit_pos: int | None = None
    first_forecast_date: str | None = None
    first_train_count = 0
    train_counts: list[int] = []
    n_refits = 0

    for pos, (idx, row) in enumerate(df.iterrows()):
        if pd.Timestamp(idx) < OOS_START:
            continue
        train = df.iloc[:pos].copy()
        if len(train) < min_train_obs:
            continue
        if coef is None or last_refit_pos is None or pos - last_refit_pos >= refit_every:
            x_train = train[feature_cols].to_numpy(dtype=float)
            x_train = np.c_[np.ones(len(x_train)), x_train]
            y_train = log_var(train["target_var"]).to_numpy(dtype=float)
            coef, *_ = np.linalg.lstsq(x_train, y_train, rcond=None)
            last_refit_pos = pos
            n_refits += 1
            train_counts.append(len(train))

        x_now = row[feature_cols].to_numpy(dtype=float)
        pred_log = float(np.r_[1.0, x_now] @ coef)
        pred_var = float(np.clip(math.exp(pred_log), VAR_FLOOR, VAR_CEILING))
        yhat.loc[idx] = pred_var
        if first_forecast_date is None:
            first_forecast_date = str(pd.Timestamp(idx).date())
            first_train_count = int(len(train))

    return ForecastBundle(
        yhat=yhat,
        first_forecast_date=first_forecast_date,
        first_train_count=int(first_train_count),
        min_train_count=int(min(train_counts)) if train_counts else 0,
        max_train_count=int(max(train_counts)) if train_counts else 0,
        n_refits=int(n_refits),
    )


def qlike_ratio_loss(y_true: np.ndarray, y_pred: np.ndarray) -> np.ndarray:
    """Non-negative Patton-style QLIKE ratio loss; lower is better."""
    yt = np.clip(np.asarray(y_true, dtype=float), VAR_FLOOR, VAR_CEILING)
    yp = np.clip(np.asarray(y_pred, dtype=float), VAR_FLOOR, VAR_CEILING)
    ratio = np.clip(yt / yp, VAR_FLOOR, 1.0 / VAR_FLOOR)
    return ratio - np.log(ratio) - 1.0


def newey_west_mean_t(diff: np.ndarray, lag: int | None = None) -> tuple[float, float, int]:
    x = np.asarray(diff, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 30:
        return float("nan"), float("nan"), int(n)
    if lag is None:
        lag = max(1, int(np.floor(n ** (1.0 / 3.0))))
    mean_x = float(np.mean(x))
    centered = x - mean_x
    var_x = float(np.mean(centered * centered))
    for k in range(1, min(lag, n - 1) + 1):
        weight = 1.0 - k / (lag + 1.0)
        cov = float(np.mean(centered[k:] * centered[:-k]))
        var_x += 2.0 * weight * cov
    se = math.sqrt(max(var_x, 1e-14) / n)
    t_stat = mean_x / se
    p_val = 2.0 * (1.0 - stats.norm.cdf(abs(t_stat)))
    return float(t_stat), float(p_val), int(n)


def stationary_bootstrap_ci(
    diff: np.ndarray,
    block_len: float = BOOTSTRAP_BLOCK_LEN,
    reps: int = BOOTSTRAP_REPS,
    seed: int = SEED,
) -> tuple[float, float, float]:
    x = np.asarray(diff, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 30:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    p_geom = 1.0 / max(block_len, 1.0)
    means = np.empty(reps)
    for b in range(reps):
        sample = np.empty(n)
        i = 0
        j = int(rng.integers(0, n))
        while i < n:
            sample[i] = x[j]
            i += 1
            if rng.random() < p_geom:
                j = int(rng.integers(0, n))
            else:
                j = (j + 1) % n
        means[b] = float(sample.mean())
    return (
        float(np.quantile(means, 0.025)),
        float(np.quantile(means, 0.975)),
        float(np.mean(means > 0.0)),
    )


def high_oil_vol_summary(eval_df: pd.DataFrame) -> dict[str, float | int]:
    df = eval_df.dropna(subset=["y", "high_oil_vol"]).copy()
    high = df[df["high_oil_vol"] > 0.0]["y"]
    normal = df[df["high_oil_vol"] <= 0.0]["y"]
    if len(high) < 10 or len(normal) < 30:
        return {
            "n_high": int(len(high)),
            "n_normal": int(len(normal)),
            "mean_var_high": float("nan"),
            "mean_var_normal": float("nan"),
            "ratio_high_to_normal": float("nan"),
            "hac_t_high_minus_normal": float("nan"),
        }
    diff = high.to_numpy(dtype=float) - float(normal.mean())
    t_stat, p_val, _ = newey_west_mean_t(diff, lag=5)
    return {
        "n_high": int(len(high)),
        "n_normal": int(len(normal)),
        "mean_var_high": float(high.mean()),
        "mean_var_normal": float(normal.mean()),
        "ratio_high_to_normal": float(high.mean() / normal.mean()),
        "hac_t_high_minus_normal": float(t_stat),
        "hac_p_high_minus_normal": float(p_val),
    }


def run_one_spec(close: pd.DataFrame, oil_source: str, target: str) -> SpecResult:
    model_df = build_model_frame(close, oil_source, target)
    base_cols = ["log_target_rv_lag1", "log_target_rv_lag5", "log_target_rv_lag22"]
    aug_cols = [
        *base_cols,
        "log_oil_rv_lag1",
        "log_oil_rv_lag5",
        "log_oil_rv_lag22",
        "log_oil_vov_lag22",
    ]
    baseline = expanding_log_ols_forecast(model_df, base_cols)
    augmented = expanding_log_ols_forecast(model_df, aug_cols)

    eval_df = pd.concat(
        [
            model_df["target_var"].rename("y"),
            model_df["high_oil_vol"],
            baseline.yhat.rename("baseline"),
            augmented.yhat.rename("augmented"),
        ],
        axis=1,
    ).dropna(subset=["y", "baseline", "augmented"])

    if len(eval_df) < 30:
        return SpecResult(
            oil_source=oil_source,
            target=target,
            n_obs=int(len(eval_df)),
            eval_start=None,
            eval_end=None,
            baseline_qlike=float("nan"),
            augmented_qlike=float("nan"),
            qlike_improvement_pct=float("nan"),
            mean_loss_improvement=float("nan"),
            hac_t=float("nan"),
            hac_p=float("nan"),
            bootstrap_ci_low=float("nan"),
            bootstrap_ci_high=float("nan"),
            bootstrap_prob_improvement_positive=float("nan"),
            first_forecast_date=baseline.first_forecast_date,
            first_train_count=baseline.first_train_count,
            min_train_count=min(baseline.min_train_count, augmented.min_train_count),
            max_train_count=max(baseline.max_train_count, augmented.max_train_count),
            n_refits_baseline=baseline.n_refits,
            n_refits_augmented=augmented.n_refits,
            high_oil_vol_regime={},
            pass_gate=False,
        )

    y = eval_df["y"].to_numpy(dtype=float)
    q_base = qlike_ratio_loss(y, eval_df["baseline"].to_numpy(dtype=float))
    q_aug = qlike_ratio_loss(y, eval_df["augmented"].to_numpy(dtype=float))
    base_mean = float(np.mean(q_base))
    aug_mean = float(np.mean(q_aug))
    improvement = q_base - q_aug
    mean_improvement = float(np.mean(improvement))
    improvement_pct = 100.0 * (base_mean - aug_mean) / abs(base_mean) if base_mean != 0 else float("nan")
    hac_t, hac_p, _ = newey_west_mean_t(improvement)
    ci_low, ci_high, prob_pos = stationary_bootstrap_ci(
        improvement,
        seed=SEED + 10 * OIL_SOURCES.index(oil_source) + TARGETS.index(target),
    )
    pass_gate = bool(
        np.isfinite(improvement_pct)
        and improvement_pct >= IMPROVEMENT_GATE_PCT
        and np.isfinite(hac_t)
        and hac_t > HARVEY_T
        and np.isfinite(ci_low)
        and ci_low > 0.0
    )

    return SpecResult(
        oil_source=oil_source,
        target=target,
        n_obs=int(len(eval_df)),
        eval_start=str(pd.Timestamp(eval_df.index.min()).date()),
        eval_end=str(pd.Timestamp(eval_df.index.max()).date()),
        baseline_qlike=base_mean,
        augmented_qlike=aug_mean,
        qlike_improvement_pct=float(improvement_pct),
        mean_loss_improvement=mean_improvement,
        hac_t=float(hac_t),
        hac_p=float(hac_p),
        bootstrap_ci_low=float(ci_low),
        bootstrap_ci_high=float(ci_high),
        bootstrap_prob_improvement_positive=float(prob_pos),
        first_forecast_date=baseline.first_forecast_date,
        first_train_count=int(min(baseline.first_train_count, augmented.first_train_count)),
        min_train_count=int(min(baseline.min_train_count, augmented.min_train_count)),
        max_train_count=int(max(baseline.max_train_count, augmented.max_train_count)),
        n_refits_baseline=int(baseline.n_refits),
        n_refits_augmented=int(augmented.n_refits),
        high_oil_vol_regime=high_oil_vol_summary(eval_df),
        pass_gate=pass_gate,
    )


def plot_oos_results(results: list[SpecResult]) -> None:
    labels = [f"{r.oil_source}->{r.target}" for r in results]
    improvements = [r.qlike_improvement_pct for r in results]
    tstats = [r.hac_t for r in results]
    colors = ["#2ca02c" if (np.isfinite(v) and v > 0) else "#d62728" for v in improvements]

    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    x = np.arange(len(labels))
    axes[0].bar(x, improvements, color=colors, alpha=0.85)
    axes[0].axhline(0, color="black", lw=0.8)
    axes[0].axhline(IMPROVEMENT_GATE_PCT, color="#555555", lw=1.0, ls="--", label="+1% gate")
    axes[0].set_ylabel("QLIKE improvement (%)")
    axes[0].set_title("K1351 OOS HAR-X oil-volatility increment")
    axes[0].legend(loc="best")

    axes[1].bar(x, tstats, color=colors, alpha=0.85)
    axes[1].axhline(0, color="black", lw=0.8)
    axes[1].axhline(HARVEY_T, color="#555555", lw=1.0, ls="--", label="Harvey t > 3")
    axes[1].axhline(-HARVEY_T, color="#555555", lw=1.0, ls=":", label="|t| = 3")
    axes[1].set_ylabel("HAC t-stat")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(labels, rotation=35, ha="right")
    axes[1].legend(loc="best")
    fig.tight_layout()
    fig.savefig(FIG_OOS, dpi=140)
    plt.close(fig)


def plot_context(close: pd.DataFrame) -> None:
    ret = close_to_close_returns(close)
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    for ticker, color in [("CL=F", "#1f77b4"), ("USO", "#ff7f0e")]:
        vol22 = ret[ticker].rolling(22).std() * math.sqrt(252.0)
        axes[0].plot(vol22.index, vol22, lw=1.0, label=ticker, color=color)
    axes[0].set_ylabel("22d ann. vol")
    axes[0].set_title("Oil volatility context")
    axes[0].legend(loc="best")

    for ticker, color in [("SPY", "#2ca02c"), ("XLE", "#d62728"), ("XOP", "#9467bd")]:
        vol22 = ret[ticker].rolling(22).std() * math.sqrt(252.0)
        axes[1].plot(vol22.index, vol22, lw=1.0, label=ticker, color=color)
    axes[1].set_ylabel("22d ann. vol")
    axes[1].set_title("Equity / energy-equity volatility context")
    axes[1].legend(loc="best")
    fig.tight_layout()
    fig.savefig(FIG_CONTEXT, dpi=140)
    plt.close(fig)


def serialize_result(result: SpecResult) -> dict[str, Any]:
    raw = asdict(result)
    for key, value in list(raw.items()):
        if isinstance(value, float):
            raw[key] = finite_float(value)
    if isinstance(raw.get("high_oil_vol_regime"), dict):
        raw["high_oil_vol_regime"] = {
            key: finite_float(value) if isinstance(value, float) else value
            for key, value in raw["high_oil_vol_regime"].items()
        }
    return raw


def verdict_from_results(results: list[SpecResult]) -> tuple[str, list[str]]:
    passing = [r for r in results if r.pass_gate]
    messages: list[str] = []
    if not passing:
        return "NULL_NO_HARVEY_PASS", ["No CL=F/USO -> SPY/XLE/XOP spec passed the pre-registered QLIKE + Harvey + bootstrap gate."]

    by_target: dict[str, list[SpecResult]] = {}
    for r in passing:
        by_target.setdefault(r.target, []).append(r)
    robust_targets = [target for target, specs in by_target.items() if {s.oil_source for s in specs} == set(OIL_SOURCES)]
    if robust_targets:
        messages.append(f"Both oil proxies passed for target(s): {', '.join(sorted(robust_targets))}.")
        return "CONDITIONAL_PASS_ROBUST_BY_PROXY", messages

    messages.extend(
        [
            f"{r.oil_source}->{r.target} passed individually, but the paired oil-proxy robustness gate did not pass."
            for r in passing
        ]
    )
    return "MIXED_SINGLE_PROXY_PASS", messages


def main() -> None:
    close = fetch_close_panel()
    print(
        f"[data] panel rows={len(close)} sample={close.index.min().date()}->{close.index.max().date()}",
        flush=True,
    )

    results = [run_one_spec(close, oil_source, target) for oil_source in OIL_SOURCES for target in TARGETS]
    plot_oos_results(results)
    plot_context(close)

    verdict, verdict_notes = verdict_from_results(results)
    best = sorted(
        results,
        key=lambda r: (
            -np.nan_to_num(r.qlike_improvement_pct, nan=-999.0),
            -np.nan_to_num(r.hac_t, nan=-999.0),
        ),
    )[0]
    worst = sorted(results, key=lambda r: np.nan_to_num(r.qlike_improvement_pct, nan=999.0))[0]

    payload: dict[str, Any] = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Oil-volatility spillover to SPY / XLE / XOP variance via OOS HAR-X",
        "created_by": "codex",
        "seed": SEED,
        "data_source": "Yahoo Finance via yfinance adjusted close; CL=F is aligned to SPY trading days with past-only ffill.",
        "sample": {
            "requested_start": START_DATE,
            "requested_end_exclusive": END_DATE,
            "actual_start": str(close.index.min().date()),
            "actual_end": str(close.index.max().date()),
            "n_common_trading_days": int(len(close)),
            "tickers": TICKERS,
        },
        "method": {
            "target": "next-day close-to-close annualized squared simple return at date t; simple returns avoid invalid CL=F log returns during the April 2020 negative oil-price episode.",
            "baseline": "Expanding-window log-HAR using target RV lag1, lag5, lag22, all shifted one trading day.",
            "augmented": "Baseline plus oil RV lag1, lag5, lag22 and oil vol-of-vol lag22 from CL=F or USO, all shifted one trading day.",
            "oos_start": str(OOS_START.date()),
            "min_train_obs": MIN_TRAIN_OBS,
            "refit_every_days": REFIT_EVERY,
            "loss": "Non-negative QLIKE ratio loss y/h - log(y/h) - 1; lower is better.",
            "test": "Newey-West HAC t-stat on pointwise loss improvement (baseline loss - augmented loss); positive t means oil-vol HAR-X is better.",
            "success_gate": f"improvement >= {IMPROVEMENT_GATE_PCT}%, HAC t > {HARVEY_T}, bootstrap 95% CI lower bound > 0.",
        },
        "lookahead_guard": [
            "Every oil feature is created as oil_raw.shift(1) before target-date alignment.",
            "Every target HAR feature is shifted one trading day before target-date alignment.",
            "For forecast row t, expanding OLS training rows are df.iloc[:pos], strictly earlier than t.",
        ],
        "related_prior_work": RELATED_PRIOR,
        "literature": LITERATURE,
        "results": [serialize_result(r) for r in results],
        "summary": {
            "verdict": verdict,
            "verdict_notes": verdict_notes,
            "n_specs": int(len(results)),
            "n_pass_gate": int(sum(r.pass_gate for r in results)),
            "best_spec": serialize_result(best),
            "worst_spec": serialize_result(worst),
            "figures": [FIG_OOS.name, FIG_CONTEXT.name],
        },
        "limitations": [
            "Daily close-to-close squared return is a noisy RV proxy and is not intraday realized variance.",
            "USO is an ETF with roll/contango effects, so CL=F and USO are intentionally treated as separate proxies.",
            "This experiment tests predictive incremental value, not a structural GARCH spillover model.",
            "Positive sector results would still need crisis/regime robustness before entering strategy registry decisions.",
        ],
    }
    RESULTS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    print(f"[result] verdict={verdict}", flush=True)
    for r in results:
        print(
            f"[result] {r.oil_source}->{r.target}: n={r.n_obs} "
            f"impr={r.qlike_improvement_pct:+.3f}% t={r.hac_t:+.3f} pass={r.pass_gate}",
            flush=True,
        )
    print(f"[write] {RESULTS_PATH}", flush=True)


if __name__ == "__main__":
    main()
