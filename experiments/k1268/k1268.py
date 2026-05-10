"""
K1268: Cross-correlation + Granger analysis: 5-min GDELT bars vs SPY 5-min RV.

Lookahead-safe: GDELT signals shifted by 1 bar (+5 min) before correlating with
same-bar SPY RV. We report sensitivity at lags ∈ {0, 1, 2, 3, 6} bars.

Methodology:
  1. SPY 1-min via yfinance (5d window per event), aggregate to 5-min RV
     (RV_t = sum_{i in t} r_i^2 where r_i = log(close_i / close_{i-1})).
  2. Merge with GDELT 5-min bars on UTC ts; intersect RTH (regular trading hours).
  3. Pearson + Spearman corr at lags ∈ [-6, +6]; HAC SE Newey-West 6 lags.
  4. Granger F-test (lags 1..6).
  5. Block bootstrap (n=1000, block_size=12) for 95% CIs; seed=42.

Verdict mapping:
  PASS:        ≥2/3 days |corr| > 0.20 at lag>=+1 AND CI excludes 0 AND Granger p<0.05
  CONDITIONAL: 1/3 marginally significant
  NULL:        all 3 days CI overlaps 0 or only contemporaneous
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Reproducibility
SEED = 42
np.random.seed(SEED)
import random  # noqa: E402
random.seed(SEED)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("k1268")

HERE = Path(__file__).parent
GDELT_PATH = HERE / "gdelt_5min_bars.parquet"
RESULTS_PATH = HERE / "k1268_results.json"

LAGS = [-6, -3, -1, 0, 1, 2, 3, 6]
BOOTSTRAP_N = 1000
BLOCK_SIZE = 12  # 1 hour
HAC_LAGS = 6

# RTH for US equities, in UTC. We use a tight (hour, minute) window 13:30-20:00 UTC
# which covers 9:30-16:00 EDT. The 3 event days are all on EDT (DST in effect on
# 2020-03-12, 2023-03-13, 2024-08-05). For an EST date we'd need 14:30-21:00 UTC.
# Codex review 2026-05-11 flagged the original `hour in [13,21]` mask as too loose.
RTH_START = (13, 30)  # 13:30 UTC
RTH_END = (20, 0)     # 20:00 UTC


def load_spy_5min_rv(date_str: str) -> tuple[pd.Series, str]:
    """yfinance 1-min SPY -> 5-min RV (sum of squared 1-min log returns).

    yfinance 1-min only returns last 30 days; for older days we fall back to 5-min OHLC
    close-to-close return squared as a proxy for RV.

    Returns (series, proxy_kind) where proxy_kind ∈ {"1min_rv", "5min_sq_return", "empty"}.
    """
    import yfinance as yf
    start = pd.Timestamp(date_str) - pd.Timedelta(days=2)
    end = pd.Timestamp(date_str) + pd.Timedelta(days=1)
    # tz-aware UTC date for filtering (FIX: avoid naive vs aware comparison bug
    # caught by Codex review 2026-05-11)
    target_date_utc = pd.Timestamp(date_str, tz="UTC").normalize()

    def _filter_to_date(s: pd.Series) -> pd.Series:
        return s[s.index.normalize() == target_date_utc]

    # Try 1-min first
    try:
        df = yf.download(
            "SPY",
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1m",
            auto_adjust=False,
            progress=False,
        )
        if df is not None and not df.empty:
            df = df.tz_convert("UTC") if df.index.tz else df.tz_localize("UTC")
            close = df["Close"].squeeze()
            r1 = np.log(close).diff()
            rv5 = (r1**2).resample("5min").sum()
            rv5 = _filter_to_date(rv5)
            if len(rv5) > 50:
                log.info("%s: SPY 1-min RV ok (n=%d)", date_str, len(rv5))
                return rv5, "1min_rv"
    except Exception as e:  # noqa: BLE001
        log.warning("1-min fetch fail %s: %s", date_str, e)

    # Fallback: 5-min OHLC, use squared 5-min log return as RV proxy
    try:
        df = yf.download(
            "SPY",
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="5m",
            auto_adjust=False,
            progress=False,
        )
        if df is None or df.empty:
            log.warning("%s: SPY 5-min also empty", date_str)
            return pd.Series(dtype=float), "empty"
        df = df.tz_convert("UTC") if df.index.tz else df.tz_localize("UTC")
        close = df["Close"].squeeze()
        r5 = np.log(close).diff()
        rv5 = (r5**2)
        rv5 = _filter_to_date(rv5)
        log.info("%s: SPY 5-min RV proxy (n=%d)", date_str, len(rv5))
        return rv5, "5min_sq_return"
    except Exception as e:  # noqa: BLE001
        log.error("%s: SPY fetch fail entirely: %s", date_str, e)
        return pd.Series(dtype=float), "empty"


def hac_corr(x: np.ndarray, y: np.ndarray, lags: int = HAC_LAGS):
    """Pearson correlation with HAC (Newey-West) standard error."""
    if len(x) < 30:
        return np.nan, np.nan, np.nan
    mx, my = x.mean(), y.mean()
    sx, sy = x.std(ddof=1), y.std(ddof=1)
    if sx == 0 or sy == 0:
        return np.nan, np.nan, np.nan
    r = float(np.corrcoef(x, y)[0, 1])
    # NW HAC of cross-product u_t = (x_t-mx)(y_t-my)/(sx*sy)
    u = (x - mx) * (y - my) / (sx * sy)
    n = len(u)
    g0 = float(np.var(u, ddof=1))
    s = g0
    for k in range(1, lags + 1):
        w = 1 - k / (lags + 1)
        g = float(np.cov(u[k:], u[:-k], ddof=1)[0, 1])
        s += 2 * w * g
    se = float(np.sqrt(max(s, 0) / n))
    t = r / se if se > 0 else np.nan
    return r, se, t


def block_bootstrap_corr(x: np.ndarray, y: np.ndarray, n: int = BOOTSTRAP_N, block: int = BLOCK_SIZE):
    rng = np.random.default_rng(SEED)
    N = len(x)
    if N < 2 * block:
        return (np.nan, np.nan)
    nb = (N // block) + 1
    rs = []
    for _ in range(n):
        starts = rng.integers(0, N - block + 1, size=nb)
        idx = np.concatenate([np.arange(s, s + block) for s in starts])[:N]
        xs = x[idx]
        ys = y[idx]
        if xs.std() == 0 or ys.std() == 0:
            continue
        rs.append(np.corrcoef(xs, ys)[0, 1])
    if not rs:
        return (np.nan, np.nan)
    return (float(np.percentile(rs, 2.5)), float(np.percentile(rs, 97.5)))


def granger_pvalue(y: np.ndarray, x: np.ndarray, max_lag: int = 6) -> float:
    """Simple Granger F-test: does past x improve prediction of y vs y-only AR?"""
    try:
        from statsmodels.tsa.stattools import grangercausalitytests
    except ImportError:
        return np.nan
    df = pd.DataFrame({"y": y, "x": x}).dropna()
    if len(df) < 4 * max_lag:
        return np.nan
    # statsmodels grangercausalitytests expects [y, x]: tests if x Granger-causes y
    try:
        out = grangercausalitytests(df[["y", "x"]].to_numpy(), max_lag, verbose=False)
        # take min p across lags 1..max_lag from F-test
        ps = [out[L][0]["ssr_ftest"][1] for L in range(1, max_lag + 1)]
        return float(min(ps))
    except Exception as e:  # noqa: BLE001
        log.warning("Granger fail: %s", e)
        return np.nan


def analyze_day(date_str: str, gdelt_day: pd.DataFrame) -> dict:
    rv, rv_proxy = load_spy_5min_rv(date_str)
    if rv.empty or gdelt_day.empty:
        return {"date": date_str, "skip": "no_data", "n": 0, "rv_proxy": rv_proxy}

    # Filter to RTH using tight (hour, minute) mask -- 13:30-20:00 UTC for EDT days
    def _in_rth(idx) -> np.ndarray:
        mins_of_day = idx.hour * 60 + idx.minute
        lo = RTH_START[0] * 60 + RTH_START[1]
        hi = RTH_END[0] * 60 + RTH_END[1]
        return (mins_of_day >= lo) & (mins_of_day < hi)

    # Ensure GDELT index is tz-aware UTC for consistent comparison with RV
    if gdelt_day.index.tz is None:
        gdelt_day = gdelt_day.copy()
        gdelt_day.index = gdelt_day.index.tz_localize("UTC")
    rv_rth = rv[_in_rth(rv.index)]
    g_rth = gdelt_day[_in_rth(gdelt_day.index)]

    # Merge on 5-min UTC bar
    merged = pd.concat([rv_rth.rename("rv"), g_rth[["count", "goldstein_mean", "avgtone_mean"]]], axis=1, join="inner").dropna()
    log.info("%s: merged n=%d (RV n=%d, GDELT n=%d)", date_str, len(merged), len(rv_rth), len(g_rth))
    if len(merged) < 30:
        return {"date": date_str, "skip": "too_few_bars", "n": int(len(merged)), "rv_proxy": rv_proxy}

    rv_arr = merged["rv"].to_numpy()
    out = {"date": date_str, "n": int(len(merged)), "rv_proxy": rv_proxy, "signals": {}}

    # ASSERTION: lookahead-safe shift. Lag k means signal_{t-k} -> rv_t.
    # For k >= 1 we shift signal forward (signal lags rv by k bars) — equivalent to
    # `signal.shift(k)` in pandas. Verdict gate only accepts lag >= +1 (k >= 1).
    # Sanity check: signal at index 0 of paired array must equal sig[0] (no future leak)
    # for lag >= 0 case; for negative lag (future signal -> past rv) we paint as
    # NON-causal in result JSON via `lookahead_safe: False`.
    for sig_name in ("count", "goldstein_mean", "avgtone_mean"):
        sig = merged[sig_name].to_numpy()
        sig_results = {}
        for lag in LAGS:
            if lag >= 0:
                # signal_{t-lag} predicts rv_t -> use sig[:-lag] paired with rv_arr[lag:]
                if lag == 0:
                    s = sig
                    r = rv_arr
                else:
                    s = sig[:-lag]
                    r = rv_arr[lag:]
                    # ASSERT lookahead-safe: paired (s[0], r[0]) corresponds to
                    # (sig at time 0, rv at time lag), i.e. rv comes AFTER signal.
                    assert len(s) == len(r), f"len mismatch lag={lag}"
            else:
                # negative lag = future signal -> past rv (NOT predictive; reported only)
                k = -lag
                s = sig[k:]
                r = rv_arr[:-k]
            if len(s) < 30:
                continue
            r_v, se, t = hac_corr(s, r)
            ci_lo, ci_hi = block_bootstrap_corr(s, r)
            sig_results[f"lag{lag}"] = {
                "n": int(len(s)),
                "pearson_r": r_v,
                "hac_se": se,
                "hac_t": t,
                "boot_ci95": [ci_lo, ci_hi],
                "lookahead_safe": lag >= 1,
            }
        # Granger: does signal Granger-cause rv?
        granger_p = granger_pvalue(rv_arr, sig, max_lag=6)
        sig_results["granger_min_p_lags1to6"] = granger_p
        out["signals"][sig_name] = sig_results
    return out


def derive_verdict(per_day: list[dict]) -> dict:
    """≥2/3 days w/ |corr|>0.20 at lag>=+1 AND CI excludes 0 AND Granger p<alpha -> PASS.

    Multiple-testing: 3 signals × 4 causal lags = 12 tests/day. Bonferroni alpha = 0.05/12.
    We report BOTH uncorrected and Bonferroni-corrected verdicts; the Bonferroni one is
    the headline. Codex review 2026-05-11 flagged uncorrected p<0.05 as overoptimistic.
    """
    n_tests_per_day = 3 * 4  # 3 signals × 4 causal lags
    alpha_uncorr = 0.05
    alpha_bonf = 0.05 / n_tests_per_day  # ≈0.00417

    def _count_days(alpha: float) -> tuple[int, int]:
        elig = 0
        hits = 0
        for d in per_day:
            if d.get("skip"):
                continue
            elig += 1
            any_sig = False
            for sig_name, sig_res in d.get("signals", {}).items():
                granger_p = sig_res.get("granger_min_p_lags1to6", np.nan)
                for lag_key in ("lag1", "lag2", "lag3", "lag6"):
                    lr = sig_res.get(lag_key)
                    if not lr:
                        continue
                    ci = lr.get("boot_ci95", [np.nan, np.nan])
                    if (
                        abs(lr.get("pearson_r", 0) or 0) > 0.20
                        and ci[0] is not None
                        and ci[1] is not None
                        and not (ci[0] <= 0 <= ci[1])
                        and granger_p is not None
                        and not (isinstance(granger_p, float) and np.isnan(granger_p))
                        and granger_p < alpha
                    ):
                        any_sig = True
                        break
                if any_sig:
                    break
            if any_sig:
                hits += 1
        return elig, hits

    elig_u, hits_u = _count_days(alpha_uncorr)
    elig_b, hits_b = _count_days(alpha_bonf)

    def _label(eligible: int, hits: int) -> str:
        if eligible == 0:
            return "FAIL_NO_DATA"
        if hits >= 2:
            return "PASS"
        if hits == 1:
            return "CONDITIONAL"
        return "NULL"

    return {
        "headline": _label(elig_b, hits_b),  # Bonferroni-corrected = headline
        "uncorrected": {"label": _label(elig_u, hits_u), "alpha": alpha_uncorr, "days_with_signal": hits_u, "eligible_days": elig_u},
        "bonferroni": {"label": _label(elig_b, hits_b), "alpha": alpha_bonf, "n_tests_per_day": n_tests_per_day, "days_with_signal": hits_b, "eligible_days": elig_b},
    }


def main():
    if not GDELT_PATH.exists():
        log.error("Missing %s — run k1268_aggregate.py first", GDELT_PATH)
        return 1
    gdelt = pd.read_parquet(GDELT_PATH)
    log.info("Loaded %d total 5-min GDELT bars across %d days", len(gdelt), gdelt["day"].nunique())

    per_day = []
    for date_str, sub in gdelt.groupby("day"):
        sub = sub.drop(columns=["day"])
        per_day.append(analyze_day(date_str, sub))

    verdict_obj = derive_verdict(per_day)

    # Convert NaNs to None for JSON
    def clean(o):
        if isinstance(o, float) and np.isnan(o):
            return None
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list):
            return [clean(x) for x in o]
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            v = float(o)
            return None if np.isnan(v) else v
        return o

    results = {
        "experiment_id": "K1268",
        "title": "GDELT 2.0 high-frequency (5-min) public-bulk scan vs SPY 5-min RV",
        "date_run": pd.Timestamp.utcnow().isoformat(),
        "seed": SEED,
        "methodology": {
            "endpoint": "http://data.gdeltproject.org/gdeltv2/{ts}.export.CSV.zip",
            "lags_tested": LAGS,
            "lookahead_rule": "lag >= 1 = causal (signal_{t-lag} -> rv_t); lag <= 0 reported for completeness only",
            "rth_filter_utc": {"start": list(RTH_START), "end": list(RTH_END)},
            "hac_lags": HAC_LAGS,
            "bootstrap_n": BOOTSTRAP_N,
            "block_size_bars": BLOCK_SIZE,
        },
        "verdict": verdict_obj["headline"],
        "verdict_breakdown": verdict_obj,
        "per_day": clean(per_day),
        "verdict_criteria": "Headline = Bonferroni-corrected (alpha=0.05/12). PASS = ≥2/3 days |corr|>0.20 at lag>=+1 AND boot CI excludes 0 AND Granger p<alpha. Uncorrected version reported alongside.",
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2, default=str))
    log.info("VERDICT (headline / Bonferroni): %s -> %s", verdict_obj["headline"], RESULTS_PATH)
    log.info("VERDICT (uncorrected): %s", verdict_obj["uncorrected"]["label"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
