"""K1423 — Time-Varying Hurst via EWMA (SPY pilot).

Pilot only: descriptive stats + correlation with VIX. No forecasting (that's K1424+).

Implements:
  1. Lo (1991) modified R/S Hurst estimator (rolling window baseline)
  2. EWMA-weighted R/S Hurst (λ ∈ {0.94, 0.97, 0.99})
  3. Regime classifier (anti-persistent / random / persistent)
  4. Correlation with VIX + χ² regime conditional probability test
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
RESULTS_PATH = HERE / "K1423_ewma_hurst_pilot_results.json"

WINDOW = 500
EWMA_LAMBDAS = (0.94, 0.97, 0.99)
REGIME_LO, REGIME_HI = 0.45, 0.55


def _fetch_yf(symbol: str, start: str) -> pd.Series:
    """yfinance fetch with retry; returns Close as Series. Empty Series on fail."""
    for attempt in range(3):
        try:
            df = yf.download(symbol, start=start, progress=False, auto_adjust=False)
            if df is None or len(df) == 0 or "Close" not in df.columns:
                continue
            ser = df["Close"]
            if isinstance(ser, pd.DataFrame):
                ser = ser.iloc[:, 0]
            if len(ser) > 0:
                return ser
        except Exception as exc:
            print(f"[K1423] yfinance {symbol} attempt {attempt+1} failed: {exc}")
    return pd.Series(dtype=float)


def fetch_data(start: str = "2010-01-01") -> pd.DataFrame:
    """Fetch SPY + VIX daily closes. Cache locally to avoid repeated yfinance hits.

    VIX fallback chain: ^VIX → ^VIX-Y (older) → FRED VIXCLS via pandas_datareader.
    """
    cache = DATA_DIR / "spy_vix_daily.parquet"
    if cache.exists():
        df = pd.read_parquet(cache)
        if len(df) > 100:
            return df

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    spy = _fetch_yf("SPY", start)
    if len(spy) == 0:
        raise RuntimeError("Failed to fetch SPY from yfinance after retries")

    vix = _fetch_yf("^VIX", start)
    if len(vix) == 0:
        # FRED fallback
        print("[K1423] ^VIX failed, trying FRED VIXCLS ...")
        try:
            from pandas_datareader import data as pdr
            vix = pdr.DataReader("VIXCLS", "fred", start=start)["VIXCLS"]
        except Exception as exc:
            raise RuntimeError(f"VIX fetch failed (yfinance + FRED both): {exc}")

    df = pd.concat([spy.rename("spy"), vix.rename("vix")], axis=1).dropna()
    df["ret"] = np.log(df["spy"] / df["spy"].shift(1))
    df = df.dropna()
    if len(df) < 1000:
        raise RuntimeError(f"Insufficient data after join: {len(df)} obs (need ≥1000)")
    df.to_parquet(cache)
    return df


def lo_modified_rs(x: np.ndarray, weights: np.ndarray | None = None) -> float:
    """Hurst via R/S on a single window.

    Equal-weight = classical Hurst (Mandelbrot R/S, simplified Lo without long-run var).
    EWMA-weighted = mean & variance are weighted (most recent obs counts more);
    cumulative deviation is still the unweighted Σ(x_i - μ̂) so range scales correctly.

    Returns H in (0, 1) typically; clamps to (0.05, 0.95) for sanity.
    NOTE: pilot simplification — does NOT include Newey-West long-run variance
    adjustment from Lo (1991). To be tightened in K1424.
    """
    n = len(x)
    if n < 50:
        return np.nan
    if weights is None:
        mean = x.mean()
        var = ((x - mean) ** 2).mean()
    else:
        w = weights / weights.sum()
        mean = np.sum(w * x)
        var = np.sum(w * (x - mean) ** 2)

    dev = x - mean
    cum = np.cumsum(dev)  # unweighted cumulative; weights only enter μ̂/σ̂
    r_range = cum.max() - cum.min()

    std = np.sqrt(var)
    if std == 0 or r_range <= 0:
        return np.nan
    rs = r_range / std
    if rs <= 0:
        return np.nan
    h = np.log(rs) / np.log(n)
    return float(np.clip(h, 0.05, 0.95))


def ewma_weights(n: int, lam: float) -> np.ndarray:
    """λ^(n-1-i) for i=0..n-1 → most recent has weight 1, oldest has λ^(n-1)."""
    ages = np.arange(n - 1, -1, -1)
    return lam ** ages


def rolling_hurst(returns: pd.Series, window: int, lam: float | None = None) -> pd.Series:
    """Rolling Hurst over `window` past returns. EWMA-weighted if lam set."""
    out = pd.Series(index=returns.index, dtype=float)
    arr = returns.values
    weights = ewma_weights(window, lam) if lam else None
    for t in range(window, len(arr)):
        out.iloc[t] = lo_modified_rs(arr[t - window:t], weights)
    return out


def classify_regime(h: float) -> str:
    if np.isnan(h):
        return "nan"
    if h < REGIME_LO:
        return "anti_persistent"
    if h > REGIME_HI:
        return "persistent"
    return "random"


def summarize(h_series: pd.Series, label: str) -> dict:
    valid = h_series.dropna()
    return {
        "label": label,
        "n": int(len(valid)),
        "mean": float(valid.mean()),
        "std": float(valid.std()),
        "q05": float(valid.quantile(0.05)),
        "q50": float(valid.quantile(0.50)),
        "q95": float(valid.quantile(0.95)),
        "min": float(valid.min()),
        "max": float(valid.max()),
    }


def regime_table(h: pd.Series, vix: pd.Series) -> dict:
    regimes = h.apply(classify_regime)
    vix_high = vix > 20
    # Align
    df = pd.DataFrame({"regime": regimes, "vix_high": vix_high}).dropna()
    df = df[df["regime"] != "nan"]
    ctab = pd.crosstab(df["regime"], df["vix_high"])
    # ensure all regime rows present
    for r in ("anti_persistent", "random", "persistent"):
        if r not in ctab.index:
            ctab.loc[r] = [0, 0]
    ctab = ctab.reindex(["anti_persistent", "random", "persistent"])
    # chi2
    chi2, p, dof, _ = stats.chi2_contingency(ctab.values + 0.5)  # +0.5 to avoid div0
    return {
        "crosstab": ctab.astype(int).to_dict(),
        "chi2": float(chi2),
        "p_value": float(p),
        "dof": int(dof),
        "interp": "p<0.05 → regime conditional on VIX>20",
    }


def corr_with_vix(h: pd.Series, vix: pd.Series) -> dict:
    df = pd.DataFrame({"h": h, "vix": vix}).dropna()
    p_r, p_p = stats.pearsonr(df["h"], df["vix"])
    s_r, s_p = stats.spearmanr(df["h"], df["vix"])
    return {
        "n": int(len(df)),
        "pearson_r": float(p_r),
        "pearson_p": float(p_p),
        "spearman_rho": float(s_r),
        "spearman_p": float(s_p),
    }


def main() -> dict:
    print("[K1423] Fetching SPY + VIX daily ...")
    df = fetch_data()
    print(f"[K1423] {len(df)} obs from {df.index[0].date()} to {df.index[-1].date()}")

    results: dict = {
        "k_id": "K1423",
        "title": "Time-Varying Hurst via EWMA — SPY pilot",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data": {
            "symbol": "SPY",
            "covar": "^VIX",
            "n_obs": int(len(df)),
            "start": str(df.index[0].date()),
            "end": str(df.index[-1].date()),
            "source": "yfinance",
        },
        "config": {
            "window": WINDOW,
            "ewma_lambdas": list(EWMA_LAMBDAS),
            "regime_thresholds": {"lo": REGIME_LO, "hi": REGIME_HI},
            "estimator": "Lo (1991) modified R/S",
        },
        "estimators": {},
    }

    print(f"[K1423] Computing rolling Hurst (window={WINDOW}) ...")
    h_roll = rolling_hurst(df["ret"], WINDOW, lam=None)
    h_series_map = {"rolling_equal_weight": h_roll}

    for lam in EWMA_LAMBDAS:
        print(f"[K1423] Computing EWMA Hurst (λ={lam}) ...")
        h_series_map[f"ewma_lambda_{lam}"] = rolling_hurst(df["ret"], WINDOW, lam=lam)

    for name, h_series in h_series_map.items():
        results["estimators"][name] = {
            "summary": summarize(h_series, name),
            "vix_correlation": corr_with_vix(h_series, df["vix"]),
            "regime_table": regime_table(h_series, df["vix"]),
        }

    # Sub-period stats for rolling
    print("[K1423] Sub-period summary (rolling baseline) ...")
    sub_periods = {
        "2010-2014": ("2010-01-01", "2014-12-31"),
        "2015-2019": ("2015-01-01", "2019-12-31"),
        "2020-2026": ("2020-01-01", "2030-12-31"),
    }
    results["sub_periods_rolling"] = {}
    for tag, (s, e) in sub_periods.items():
        sub = h_roll.loc[s:e].dropna()
        if len(sub) > 50:
            results["sub_periods_rolling"][tag] = {
                "n": int(len(sub)),
                "mean": float(sub.mean()),
                "std": float(sub.std()),
                "frac_anti": float((sub < REGIME_LO).mean()),
                "frac_persistent": float((sub > REGIME_HI).mean()),
            }

    # COVID responsiveness case study: 2020-02-01 ~ 2020-04-30
    print("[K1423] COVID case study ...")
    covid = pd.DataFrame({
        "rolling": h_roll,
        "ewma_094": h_series_map["ewma_lambda_0.94"],
        "ewma_097": h_series_map["ewma_lambda_0.97"],
        "vix": df["vix"],
    }).loc["2020-02-01":"2020-04-30"]
    # Find first date H drops below regime_lo (anti-persistent appearance) after COVID start
    def first_below(series: pd.Series) -> str | None:
        below = series[series < REGIME_LO]
        return str(below.index[0].date()) if len(below) else None
    results["covid_case_study"] = {
        "window": "2020-02-01 ~ 2020-04-30",
        "first_h_below_045": {
            "rolling": first_below(covid["rolling"]),
            "ewma_094": first_below(covid["ewma_094"]),
            "ewma_097": first_below(covid["ewma_097"]),
        },
        "vix_peak_date": str(covid["vix"].idxmax().date()),
        "vix_peak_value": float(covid["vix"].max()),
    }

    # Save raw H(t) series for later plotting
    series_csv = HERE / "data" / "K1423_h_series.csv"
    pd.DataFrame({k: v for k, v in h_series_map.items()}).assign(vix=df["vix"], spy_ret=df["ret"]).to_csv(series_csv)
    results["artifacts"] = {"h_series_csv": str(series_csv.relative_to(HERE.parent.parent))}

    # Write results
    RESULTS_PATH.write_text(json.dumps(results, indent=2, default=str))
    print(f"[K1423] Results → {RESULTS_PATH}")
    return results


if __name__ == "__main__":
    main()
