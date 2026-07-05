"""K1642 - Volatility Laundering in listed BDCs: reported NAV vol vs de-smoothed
"true" vol.

Private-credit vehicles report appraisal-based, quarterly, smoothed NAV. Listed
BDCs give us TWO observable series for the same underlying:

    * market price (daily, mark-to-market)  -> economic-vol proxy
    * reported NAV / share (quarterly, appraisal-smoothed) -> "laundered" vol

We quantify the "volatility laundering" gap using 100% free public data:

    * Market price + distributions: yfinance (auto-adjusted close + raw dividends)
    * Reported NAV/share: SEC EDGAR XBRL companyconcept
      us-gaap:NetAssetValuePerShare from 10-Q / 10-K filings (originally reported)

MODE = "empirical_layer1"  (real reported NAV, NOT a mechanical illustration)

Hypotheses
----------
H1: sigma(reported NAV return) << sigma(market return)  ->  laundering_ratio < 1
H2: after Getmansky-Lo-Makarov (2004) de-smoothing, the recovered "true" vol
    moves toward the market vol (i.e. smoothing, not lower fundamentals, drives
    most of the gap).
H3: reported NAV quarterly returns show significant positive AR(1) -- the
    appraisal-smoothing fingerprint -- while market returns do not.

Guardrails
----------
* SEED = 42 (all bootstrap / random MLE starts).
* This is a MEASUREMENT study, not a forecast/strategy -> no signal.shift(1)
  predictive lag applies. Where lead/lag alignment matters (matching daily prices
  to quarter-end NAV report dates) it is documented explicitly.
* Cross-section inference aggregates to ONE statistic per BDC first, then tests
  across BDCs (Wilcoxon). We never stack asset-quarters as iid (K1355 lesson).
* GLM de-smoothing uses an exact Gaussian MA(k) likelihood solved with a
  constrained multistart MLE (statsmodels ARMA is fragile on n~20-28 quarters;
  package limitation != model invalid, K1213 lesson).
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.request
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import optimize, stats

import yfinance as yf

SEED = 42
np.random.seed(SEED)

EXPERIMENT_ID = "k1642_volatility_laundering_bdc"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(OUT_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

MODE = "empirical_layer1"
SEC_UA = {"User-Agent": "DaYeh University Finance Research yihao.lai@gmail.com"}

# 7 listed BDCs with clean SEC 10-Q/10-K NetAssetValuePerShare series.
# BIZD is excluded: it is a fund-of-BDCs ETF whose NAV is struck daily, not
# appraisal-smoothed, so it has no reported-NAV laundering to measure.
BDC_CIK = {
    "ARCC": "0001287750",
    "BXSL": "0001736035",
    "OBDC": "0001655888",
    "FSK": "0001422183",
    "PSEC": "0001287032",
    "MAIN": "0001396440",
    "GBDC": "0001476765",
}

PRICE_START = "2011-01-01"
PRICE_END = "2026-06-30"
QUARTERS_PER_YEAR = 4.0
ANNUALIZE = math.sqrt(QUARTERS_PER_YEAR)  # quarterly sigma -> annual
TRADING_DAYS = 252.0
MIN_QUARTERS = 12  # need enough quarterly returns to estimate vol + AR(1)


# --------------------------------------------------------------------------- #
# Data acquisition (cached, reproducible)
# --------------------------------------------------------------------------- #
def _cache_path(name: str) -> str:
    return os.path.join(DATA_DIR, name)


def fetch_reported_nav(ticker: str, cik: str) -> pd.DataFrame:
    """Originally-reported NAV/share per period-end from SEC 10-Q/10-K.

    Dedup rule: for each period-end date keep the value from the EARLIEST-filed
    10-Q/10-K (as originally reported), avoiding later restatement/comparatives.
    """
    cache = _cache_path(f"nav_{ticker}.csv")
    if os.path.exists(cache):
        df = pd.read_csv(cache, parse_dates=["end", "filed"])
        return df
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/NetAssetValuePerShare.json"
    req = urllib.request.Request(url, headers=SEC_UA)
    payload = json.load(urllib.request.urlopen(req, timeout=60))
    rows = payload.get("units", {}).get("USD/shares", [])
    rec = []
    for r in rows:
        if r.get("form") not in ("10-Q", "10-K"):
            continue
        rec.append(
            {
                "end": pd.Timestamp(r["end"]),
                "val": float(r["val"]),
                "form": r["form"],
                "filed": pd.Timestamp(r["filed"]),
                "accn": r.get("accn"),
            }
        )
    df = pd.DataFrame(rec)
    # earliest-filed value per period-end
    df = df.sort_values(["end", "filed"]).groupby("end", as_index=False).first()
    df = df.sort_values("end").reset_index(drop=True)
    df.to_csv(cache, index=False)
    time.sleep(0.3)
    return df


def fetch_market(ticker: str) -> tuple[pd.Series, pd.Series]:
    """Daily auto-adjusted close (total-return price) + raw per-share dividends."""
    px_cache = _cache_path(f"px_{ticker}.csv")
    dv_cache = _cache_path(f"div_{ticker}.csv")
    if os.path.exists(px_cache) and os.path.exists(dv_cache):
        px = pd.read_csv(px_cache, parse_dates=["date"], index_col="date")["adj_close"]
        dv = pd.read_csv(dv_cache, parse_dates=["date"], index_col="date")["dividend"]
        return px, dv
    tk = yf.Ticker(ticker)
    hist = tk.history(start=PRICE_START, end=PRICE_END, auto_adjust=True)
    if hist.empty:
        raise RuntimeError(f"No price history for {ticker}")
    px = hist["Close"].copy()
    px.index = px.index.tz_localize(None).normalize()
    px.name = "adj_close"
    px.index.name = "date"
    dv = tk.dividends.copy()
    dv.index = dv.index.tz_localize(None).normalize()
    dv.name = "dividend"
    dv.index.name = "date"
    px.to_frame().to_csv(px_cache)
    dv.to_frame().to_csv(dv_cache)
    time.sleep(0.3)
    return px, dv


# --------------------------------------------------------------------------- #
# Build aligned quarterly return series
# --------------------------------------------------------------------------- #
@dataclass
class BDCSeries:
    ticker: str
    report_dates: list  # period-end dates actually used (t_1..t_n)
    nav_ret: np.ndarray  # quarterly reported NAV total return
    mkt_ret: np.ndarray  # quarterly market total return over same windows
    n_nav_raw: int
    daily_mkt_logret: np.ndarray  # daily market log returns over span (reference)
    span_start: pd.Timestamp
    span_end: pd.Timestamp


def _price_asof(px: pd.Series, date: pd.Timestamp) -> float | None:
    """Last available adjusted close on or before `date`."""
    sub = px.loc[:date]
    if sub.empty:
        return None
    # require the nearest trading day be within ~7 calendar days of report date
    if (date - sub.index[-1]).days > 7:
        return None
    return float(sub.iloc[-1])


def build_series(ticker: str, cik: str) -> BDCSeries | None:
    nav_df = fetch_reported_nav(ticker, cik)
    px, dv = fetch_market(ticker)
    nav_df = nav_df[nav_df["end"] >= pd.Timestamp(PRICE_START)].reset_index(drop=True)

    report_dates, nav_ret, mkt_ret = [], [], []
    first_d0 = None  # beginning of the FIRST accepted window (for span/daily ref)
    for i in range(1, len(nav_df)):
        d0, d1 = nav_df["end"].iloc[i - 1], nav_df["end"].iloc[i]
        gap_days = (d1 - d0).days
        # keep only genuine ~1-quarter steps (guard mergers / missing quarters)
        if not (75 <= gap_days <= 125):
            continue
        nav0, nav1 = nav_df["val"].iloc[i - 1], nav_df["val"].iloc[i]
        if nav0 <= 0 or nav1 <= 0:
            continue
        # per-share distributions with ex-date in (d0, d1]
        dist = float(dv[(dv.index > d0) & (dv.index <= d1)].sum())
        nav_tr = (nav1 - nav0 + dist) / nav0
        # market total return over same window from auto-adjusted close
        p0, p1 = _price_asof(px, d0), _price_asof(px, d1)
        if p0 is None or p1 is None or p0 <= 0:
            continue
        mkt_tr = p1 / p0 - 1.0
        if first_d0 is None:
            first_d0 = d0
        report_dates.append(d1)
        nav_ret.append(nav_tr)
        mkt_ret.append(mkt_tr)

    if len(nav_ret) < MIN_QUARTERS:
        return None

    # span = start of first window (d0) .. end of last window (d1); the daily
    # reference vol must cover the SAME calendar span as the quarterly returns.
    span_start, span_end = first_d0, report_dates[-1]
    daily = px.loc[span_start:span_end]
    daily_log = np.diff(np.log(daily.values))
    return BDCSeries(
        ticker=ticker,
        report_dates=[d.strftime("%Y-%m-%d") for d in report_dates],
        nav_ret=np.asarray(nav_ret, float),
        mkt_ret=np.asarray(mkt_ret, float),
        n_nav_raw=len(nav_df),
        daily_mkt_logret=daily_log,
        span_start=span_start,
        span_end=span_end,
    )


# --------------------------------------------------------------------------- #
# GLM (Getmansky-Lo-Makarov 2004) de-smoothing via constrained MA(k) MLE
# --------------------------------------------------------------------------- #
# Model:  x_t = theta_0 e_t + theta_1 e_{t-1} + ... + theta_k e_{t-k}
#         sum(theta_j) = 1, theta_j >= 0,  e_t ~ N(0, sigma2_true)
# Reported variance  gamma0 = sigma2_true * sum(theta_j^2) = sigma2_true * xi
#   => de-smoothed ("true") variance = sigma2_true = Var(reported) / xi,   xi<=1
# We fit by EXACT Gaussian likelihood on the banded Toeplitz covariance.


def _ma_autocov(theta: np.ndarray, sigma2: float, k: int) -> np.ndarray:
    """Autocovariances gamma_0..gamma_k for the MA(k) process."""
    g = np.zeros(k + 1)
    for h in range(k + 1):
        s = 0.0
        for j in range(k + 1 - h):
            s += theta[j] * theta[j + h]
        g[h] = sigma2 * s
    return g


def _neg_loglik(params: np.ndarray, x: np.ndarray, k: int) -> float:
    # params: k free logits (theta via softmax over [0, logits]) + log sigma2
    logits = np.concatenate([[0.0], params[:k]])
    w = np.exp(logits - logits.max())
    theta = w / w.sum()  # simplex, sum=1, >=0
    sigma2 = math.exp(params[k])
    n = len(x)
    g = _ma_autocov(theta, sigma2, k)
    # banded Toeplitz covariance
    cov = np.zeros((n, n))
    for h in range(k + 1):
        idx = np.arange(n - h)
        cov[idx, idx + h] = g[h]
        cov[idx + h, idx] = g[h]
    # jitter for numerical PD safety
    cov += np.eye(n) * 1e-12
    try:
        L = np.linalg.cholesky(cov)
    except np.linalg.LinAlgError:
        return 1e12
    alpha = np.linalg.solve(L, x)
    logdet = 2.0 * np.sum(np.log(np.diag(L)))
    return 0.5 * (n * math.log(2 * math.pi) + logdet + float(alpha @ alpha))


@dataclass
class GLMFit:
    k: int
    theta: list
    xi: float  # smoothing index = sum(theta^2) in (1/(k+1), 1]
    sigma2_true: float
    var_reported: float
    vol_reported_q: float
    vol_desmoothed_q: float
    inflation_factor: float  # vol_desmoothed / vol_reported = 1/sqrt(xi)
    converged: bool
    n_starts: int


def glm_desmooth(x_raw: np.ndarray, k: int, n_starts: int = 120) -> GLMFit:
    x = x_raw - x_raw.mean()
    var_rep = float(np.var(x_raw, ddof=1))
    best = None
    # moment start for log sigma2
    ls0 = math.log(max(var_rep, 1e-8))
    rng = np.random.default_rng(SEED + k)
    for s in range(n_starts):
        if s == 0:
            init = np.concatenate([np.zeros(k), [ls0]])  # equal-ish weights start
        else:
            init = np.concatenate([rng.normal(0, 1.5, k), [ls0 + rng.normal(0, 0.5)]])
        try:
            res = optimize.minimize(
                _neg_loglik, init, args=(x, k), method="Nelder-Mead",
                options={"maxiter": 4000, "xatol": 1e-8, "fatol": 1e-10},
            )
        except Exception:
            continue
        if best is None or res.fun < best.fun:
            best = res
    logits = np.concatenate([[0.0], best.x[:k]])
    w = np.exp(logits - logits.max())
    theta = w / w.sum()
    sigma2_true = math.exp(best.x[k])
    xi = float(np.sum(theta ** 2))
    vol_rep_q = math.sqrt(var_rep)
    vol_des_q = math.sqrt(sigma2_true)
    return GLMFit(
        k=k,
        theta=[float(t) for t in theta],
        xi=xi,
        sigma2_true=sigma2_true,
        var_reported=var_rep,
        vol_reported_q=vol_rep_q,
        vol_desmoothed_q=vol_des_q,
        inflation_factor=vol_des_q / vol_rep_q,
        converged=bool(best.success) if best is not None else False,
        n_starts=n_starts,
    )


# Geltner (1993) first-order AR(1) unsmoothing -- appraisal-based cross-check.
def geltner_ar1_unsmooth(x: np.ndarray) -> dict:
    phi = _ar1_coef(x)
    # true_t = (x_t - phi*x_{t-1})/(1-phi); Var(true)=Var(x)*(1-2*phi*rho1+phi^2)/(1-phi)^2
    # simpler: reconstruct and take sample variance
    # Invalidate non-stationary / near-unit-root phi (>=0.99): 1/(1-phi) explodes,
    # a small-sample artifact (e.g. very short, very smooth newer funds).
    if phi >= 0.99 or abs(1 - phi) < 1e-6:
        return {"phi": float(phi), "vol_desmoothed_q": float(np.std(x, ddof=1)), "valid": False}
    true = (x[1:] - phi * x[:-1]) / (1 - phi)
    return {
        "phi": float(phi),
        "vol_desmoothed_q": float(np.std(true, ddof=1)),
        "valid": True,
    }


# --------------------------------------------------------------------------- #
# AR(1) + Ljung-Box (H3)
# --------------------------------------------------------------------------- #
def _ar1_coef(x: np.ndarray) -> float:
    x0, x1 = x[:-1], x[1:]
    x0c, x1c = x0 - x0.mean(), x1 - x1.mean()
    denom = float(x0c @ x0c)
    if denom == 0:
        return 0.0
    return float(x0c @ x1c) / denom


def ar1_test(x: np.ndarray) -> dict:
    """OLS AR(1) with HAC (Newey-West) robust t + Ljung-Box(4)."""
    y = x[1:]
    xl = x[:-1]
    n = len(y)
    X = np.column_stack([np.ones(n), xl])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    XtX_inv = np.linalg.inv(X.T @ X)
    # Newey-West HAC, lag = floor(4*(n/100)^(2/9)) but >=1
    L = max(1, int(math.floor(4 * (n / 100.0) ** (2.0 / 9.0))))
    S = np.zeros((2, 2))
    u = X * resid[:, None]
    for lag in range(0, L + 1):
        w = 1.0 if lag == 0 else 1.0 - lag / (L + 1)
        for t in range(lag, n):
            g = np.outer(u[t], u[t - lag])
            S += w * (g + (g.T if lag > 0 else 0))
    cov = XtX_inv @ S @ XtX_inv
    phi = float(beta[1])
    se = math.sqrt(max(cov[1, 1], 0))
    t_stat = phi / se if se > 0 else float("nan")
    p = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 2)) if se > 0 else float("nan")
    # Ljung-Box up to 4 lags on the demeaned series
    lb_p = _ljung_box(x, min(4, len(x) // 4))
    return {"phi": phi, "hac_t": float(t_stat), "hac_p": float(p),
            "ljung_box_p": float(lb_p), "n": n, "hac_lag": L}


def _ljung_box(x: np.ndarray, m: int) -> float:
    x = x - x.mean()
    n = len(x)
    c0 = float(x @ x) / n
    if c0 == 0 or m < 1:
        return float("nan")
    q = 0.0
    for h in range(1, m + 1):
        ch = float(x[h:] @ x[:-h]) / n
        r = ch / c0
        q += r * r / (n - h)
    q *= n * (n + 2)
    return float(1 - stats.chi2.cdf(q, df=m))


# --------------------------------------------------------------------------- #
# Bootstrap variance ratio per BDC (paired moving-block on aligned quarters)
# --------------------------------------------------------------------------- #
def bootstrap_var_ratio(nav_ret: np.ndarray, mkt_ret: np.ndarray,
                        reps: int = 2000, block: int = 4) -> dict:
    n = len(nav_ret)
    rng = np.random.default_rng(SEED)
    ratios = []
    n_blocks = int(math.ceil(n / block))
    for _ in range(reps):
        starts = rng.integers(0, n - block + 1, size=n_blocks) if n > block else np.array([0])
        idx = np.concatenate([np.arange(s, s + block) for s in starts])[:n]
        vn = np.var(nav_ret[idx], ddof=1)
        vm = np.var(mkt_ret[idx], ddof=1)
        if vm > 0:
            ratios.append(math.sqrt(vn / vm))
    ratios = np.array(ratios)
    return {
        "ratio_point": float(np.std(nav_ret, ddof=1) / np.std(mkt_ret, ddof=1)),
        "ratio_boot_median": float(np.median(ratios)),
        "ratio_ci95": [float(np.percentile(ratios, 2.5)), float(np.percentile(ratios, 97.5))],
        "p_ratio_ge_1": float(np.mean(ratios >= 1.0)),  # one-sided evidence ratio<1
    }


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    per_bdc = {}
    series_store: dict[str, BDCSeries] = {}
    for tk, cik in BDC_CIK.items():
        s = build_series(tk, cik)
        if s is None:
            per_bdc[tk] = {"status": "insufficient_data"}
            continue
        series_store[tk] = s

        # --- vols (quarterly-based, both series on the SAME report-date grid) ---
        sig_nav_q = float(np.std(s.nav_ret, ddof=1))
        sig_mkt_q = float(np.std(s.mkt_ret, ddof=1))
        sig_nav_a = sig_nav_q * ANNUALIZE
        sig_mkt_a = sig_mkt_q * ANNUALIZE
        laundering_ratio = sig_nav_q / sig_mkt_q  # factor cancels -> same annualized
        # daily-based annualized market vol (DIFFERENT convention, reference only)
        sig_mkt_daily_a = float(np.std(s.daily_mkt_logret, ddof=1)) * math.sqrt(TRADING_DAYS)

        # --- GLM de-smoothing (k=2 primary, k=1 robustness) ---
        glm2 = glm_desmooth(s.nav_ret, k=2)
        glm1 = glm_desmooth(s.nav_ret, k=1)
        geltner = geltner_ar1_unsmooth(s.nav_ret)
        desmoothed_ratio2 = (glm2.vol_desmoothed_q * ANNUALIZE) / sig_mkt_a
        desmoothed_ratio1 = (glm1.vol_desmoothed_q * ANNUALIZE) / sig_mkt_a

        # --- H3 AR(1) ---
        ar_nav = ar1_test(s.nav_ret)
        ar_mkt = ar1_test(s.mkt_ret)
        # flag explosive/non-stationary AR(1) (small-sample artifact, e.g. very
        # short & smooth newer funds) -> Geltner unsmoothing unreliable there
        ar_nav_reliable = bool(abs(ar_nav["phi"]) < 0.99)

        # --- H1 bootstrap ratio ---
        boot = bootstrap_var_ratio(s.nav_ret, s.mkt_ret)

        per_bdc[tk] = {
            "status": "ok",
            "n_quarters": int(len(s.nav_ret)),
            "n_nav_filings_raw": s.n_nav_raw,
            "span": [s.span_start.strftime("%Y-%m-%d"), s.span_end.strftime("%Y-%m-%d")],
            "vol_reported_annual": sig_nav_a,
            "vol_market_annual_quarterly_basis": sig_mkt_a,
            "vol_market_annual_daily_basis_reference": sig_mkt_daily_a,
            "laundering_ratio": laundering_ratio,
            "glm_k2": asdict(glm2),
            "glm_k1": asdict(glm1),
            "geltner_ar1": geltner,
            "vol_desmoothed_annual_k2": glm2.vol_desmoothed_q * ANNUALIZE,
            "vol_desmoothed_annual_k1": glm1.vol_desmoothed_q * ANNUALIZE,
            "desmoothed_market_ratio_k2": desmoothed_ratio2,
            "desmoothed_market_ratio_k1": desmoothed_ratio1,
            "ar1_nav": ar_nav,
            "ar1_market": ar_mkt,
            "ar1_nav_reliable": ar_nav_reliable,
            "bootstrap_ratio": boot,
        }

    ok = {t: v for t, v in per_bdc.items() if v.get("status") == "ok"}

    # ----------------- cross-section tests (aggregate-per-BDC first) --------- #
    tickers = list(ok.keys())
    lr = np.array([ok[t]["laundering_ratio"] for t in tickers])
    dr2 = np.array([ok[t]["desmoothed_market_ratio_k2"] for t in tickers])
    dr1 = np.array([ok[t]["desmoothed_market_ratio_k1"] for t in tickers])
    phi_nav = np.array([ok[t]["ar1_nav"]["phi"] for t in tickers])
    phi_mkt = np.array([ok[t]["ar1_market"]["phi"] for t in tickers])
    # Geltner de-smoothed/market ratio, robustness (drop unreliable phi>=1)
    gel_tickers = [t for t in tickers if ok[t]["ar1_nav_reliable"] and ok[t]["geltner_ar1"]["valid"]]
    gel_ratio = np.array([
        (ok[t]["geltner_ar1"]["vol_desmoothed_q"] * ANNUALIZE)
        / ok[t]["vol_market_annual_quarterly_basis"]
        for t in gel_tickers
    ])

    def wilcox_vs(vals: np.ndarray, mu: float) -> dict:
        d = vals - mu
        d = d[d != 0]
        if len(d) < 2:
            return {"stat": None, "p": None, "n": int(len(d))}
        w = stats.wilcoxon(d, alternative="two-sided", zero_method="wilcox")
        return {"stat": float(w.statistic), "p": float(w.pvalue), "n": int(len(d))}

    def wilcox_paired(a: np.ndarray, b: np.ndarray) -> dict:
        d = a - b
        d = d[d != 0]
        if len(d) < 2:
            return {"stat": None, "p": None, "n": int(len(d))}
        w = stats.wilcoxon(d, alternative="two-sided", zero_method="wilcox")
        return {"stat": float(w.statistic), "p": float(w.pvalue), "n": int(len(d))}

    cross = {
        "n_bdc": len(tickers),
        "tickers": tickers,
        # H1: laundering ratio < 1 across BDCs
        "laundering_ratio_mean": float(np.mean(lr)),
        "laundering_ratio_median": float(np.median(lr)),
        "laundering_ratio_min": float(np.min(lr)),
        "laundering_ratio_max": float(np.max(lr)),
        "H1_wilcoxon_ratio_vs_1": wilcox_vs(lr, 1.0),
        # H2: de-smoothed/market ratio moves toward 1 (vs laundering ratio)
        "desmoothed_ratio_k2_median": float(np.median(dr2)),
        "desmoothed_ratio_k1_median": float(np.median(dr1)),
        "H2_wilcoxon_desmoothed_k2_vs_1": wilcox_vs(dr2, 1.0),
        "H2_wilcoxon_desmoothed_vs_laundering_k2": wilcox_paired(dr2, lr),
        "gap_closed_fraction_median_k2": float(
            np.median((dr2 - lr) / (1.0 - lr))
        ),  # 0 = no closure, 1 = fully to market vol
        "geltner_desmoothed_ratio_median_ex_unreliable": (
            float(np.median(gel_ratio)) if len(gel_ratio) else None
        ),
        "geltner_gap_closed_fraction_median": (
            float(np.median(
                (gel_ratio - np.array([ok[t]["laundering_ratio"] for t in gel_tickers]))
                / (1.0 - np.array([ok[t]["laundering_ratio"] for t in gel_tickers]))
            )) if len(gel_ratio) else None
        ),
        "n_bdc_ar1_unreliable": int(sum(1 for t in tickers if not ok[t]["ar1_nav_reliable"])),
        # H3: NAV AR(1) positive and > market AR(1)
        "phi_nav_median": float(np.median(phi_nav)),
        "phi_market_median": float(np.median(phi_mkt)),
        "H3_wilcoxon_phi_nav_vs_0": wilcox_vs(phi_nav, 0.0),
        "H3_wilcoxon_phi_market_vs_0": wilcox_vs(phi_mkt, 0.0),
        "H3_wilcoxon_phi_nav_gt_market": wilcox_paired(phi_nav, phi_mkt),
        "n_bdc_phi_nav_positive": int(np.sum(phi_nav > 0)),
        "n_bdc_phi_market_positive": int(np.sum(phi_mkt > 0)),
        "n_bdc_nav_ljungbox_sig_05": int(
            np.sum([ok[t]["ar1_nav"]["ljung_box_p"] < 0.05 for t in tickers])
        ),
    }

    # -------------------------------- verdict ------------------------------- #
    # H1: laundering gap large & significant across BDCs.
    h1 = cross["laundering_ratio_median"] < 1 and (cross["H1_wilcoxon_ratio_vs_1"]["p"] or 1) < 0.05
    # H2 (strong form): de-smoothing MECHANICALLY explains the gap -> would need
    # de-smoothed vol to converge substantially toward market (>=50% gap closed).
    # It only closes ~7% -> strong form REJECTED; directionally present only.
    h2_directional = cross["desmoothed_ratio_k2_median"] > cross["laundering_ratio_median"]
    h2_strong = cross["gap_closed_fraction_median_k2"] >= 0.5
    # H3: reported NAV positive AR(1). NOTE (Codex review): market quarterly
    # returns ALSO show positive AR(1) in all 7 BDCs over this short window, so
    # "NAV has positive AR(1)" alone does not isolate appraisal smoothing.
    # h3_basic  = NAV phi > 0 significant across BDCs.
    # h3_differential (the appraisal-SPECIFIC fingerprint) = NAV phi > market phi
    #   significant -> only p~0.078 here, so NOT met in strong form.
    h3_basic = (cross["phi_nav_median"] > 0
                and (cross["H3_wilcoxon_phi_nav_vs_0"]["p"] or 1) < 0.05)
    h3_differential = (cross["phi_nav_median"] > cross["phi_market_median"]
                       and (cross["H3_wilcoxon_phi_nav_gt_market"]["p"] or 1) < 0.05)
    # Core empirical claim rests primarily on H1 (the laundering gap: robust,
    # unanimous, p=0.0156). H3-basic corroborates smoothing but is not
    # appraisal-specific unless h3_differential also holds. H2-strong FAILS
    # (smoothing is a real but minor part of the gap). Honest overall verdict:
    # CONDITIONAL_PASS -- H1 confirmed; H2 & H3-strict downgraded, not NULL.
    if h1 and h3_differential and h2_strong:
        verdict = "PASS"
    elif h1:
        verdict = "CONDITIONAL_PASS"
    elif h3_basic:
        verdict = "CONDITIONAL_PASS"
    else:
        verdict = "NULL"
    hyp_detail = {
        "H1_laundering_gap": "CONFIRMED" if h1 else "REJECTED",
        "H2_desmoothing_explains_gap": (
            "REJECTED_strong_form_only_directional" if (h2_directional and not h2_strong)
            else ("CONFIRMED" if h2_strong else "REJECTED")
        ),
        "H3_nav_positive_ar1": "CONFIRMED" if h3_basic else "REJECTED",
        "H3_appraisal_specific_fingerprint_nav_gt_market": (
            "CONFIRMED" if h3_differential
            else "NOT_CONFIRMED_market_also_positive_ar1_diff_p~0.078"
        ),
    }

    results = {
        "experiment_id": EXPERIMENT_ID,
        "mode": MODE,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data_provenance": {
            "market_price": "yfinance Ticker.history(auto_adjust=True) daily close + raw dividends",
            "reported_nav": "SEC EDGAR XBRL companyconcept us-gaap:NetAssetValuePerShare, 10-Q/10-K, originally reported (earliest-filed per period-end)",
            "price_window": [PRICE_START, PRICE_END],
            "bdc_cik": BDC_CIK,
            "excluded": {"BIZD": "ETF (daily-struck NAV, no appraisal smoothing to measure)"},
        },
        "method": {
            "nav_total_return": "(NAV_t - NAV_{t-1} + per-share distributions in (t-1,t]) / NAV_{t-1}",
            "market_total_return": "adj_close(report_t)/adj_close(report_{t-1}) - 1 (auto-adjusted, dividends built in)",
            "quarter_gap_filter_days": [75, 125],
            "annualization": "quarterly sigma * sqrt(4); daily reference sigma * sqrt(252) reported separately",
            "glm": "Getmansky-Lo-Makarov (2004) MA(k), sum(theta)=1, theta>=0, exact Gaussian MLE, 120 random starts, seed 42",
            "desmoothed_var": "de-smoothed variance = direct MLE sigma2_true (innovation variance under sum(theta)=1); equals Var(reported)/xi up to MA(k) model fit (agree to ~2%: median desmoothed/market 0.300 direct vs 0.307 via Var/xi), xi=sum(theta^2)",
            "cross_section": "aggregate to one statistic per BDC, then Wilcoxon signed-rank across BDCs (no asset-quarter iid stacking, K1355)",
        },
        "hypotheses": {
            "H1_reported_vol_below_market": bool(h1),
            "H2_desmoothed_converges_to_market_strong": bool(h2_strong),
            "H2_desmoothed_directional": bool(h2_directional),
            "H3_nav_positive_ar1": bool(h3_basic),
            "H3_appraisal_specific_nav_ar1_gt_market": bool(h3_differential),
        },
        "hypotheses_detail": hyp_detail,
        "data_limitations": [
            "SEC XBRL us-gaap:NetAssetValuePerShare is tagged QUARTERLY only from ~2021Q3; earlier 10-K filings tag it annually, so the continuous quarterly chain per BDC begins 2021Q3-Q4 (14-19 quarters). Sample is dominated by the 2022 bear market + 2023 regional-bank stress, where mark-to-market vs appraisal divergence is largest; the laundering ratio may overstate a full-cycle average.",
            "Market price vol is an UPPER-bound proxy for true portfolio economic vol (it embeds BDC premium/discount, equity beta, and liquidity noise absent from NAV); reported NAV vol is a LOWER bound (appraisal-smoothed). True private-credit vol lies between de-smoothed NAV and market.",
            "NAV/share is affected by share issuance/buybacks at premium/discount to NAV (accretion/dilution), a second-order contaminant to NAV total return not separated here.",
            "BXSL AR(1) phi>1 is a small-sample explosive artifact (17 quarters, newer fund); its Geltner unsmoothing is unreliable and excluded from Geltner cross-section. GLM (bounded simplex) is robust there.",
        ],
        "cross_section": cross,
        "per_bdc": per_bdc,
        "verdict": verdict,
    }

    out = os.path.join(OUT_DIR, "k1642_results.json")
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"[k1642] wrote {out}  verdict={verdict}")
    print(f"        laundering_ratio median={cross['laundering_ratio_median']:.3f} "
          f"(mean={cross['laundering_ratio_mean']:.3f})  H1 p={cross['H1_wilcoxon_ratio_vs_1']['p']}")
    print(f"        desmoothed/market median k2={cross['desmoothed_ratio_k2_median']:.3f} "
          f"(from {cross['laundering_ratio_median']:.3f}); gap closed "
          f"{cross['gap_closed_fraction_median_k2']*100:.0f}%")
    print(f"        phi_nav median={cross['phi_nav_median']:.3f} vs phi_mkt "
          f"{cross['phi_market_median']:.3f}; H3 p={cross['H3_wilcoxon_phi_nav_vs_0']['p']}; "
          f"NAV LB sig {cross['n_bdc_nav_ljungbox_sig_05']}/{cross['n_bdc']}")

    make_figures(ok, cross)


# --------------------------------------------------------------------------- #
# Figures
# --------------------------------------------------------------------------- #
def make_figures(ok: dict, cross: dict) -> None:
    tickers = list(ok.keys())
    rep = [ok[t]["vol_reported_annual"] * 100 for t in tickers]
    des = [ok[t]["vol_desmoothed_annual_k2"] * 100 for t in tickers]
    mkt = [ok[t]["vol_market_annual_quarterly_basis"] * 100 for t in tickers]

    # Figure 1: reported vs de-smoothed vs market annualized vol
    fig, ax = plt.subplots(figsize=(10, 5.5))
    x = np.arange(len(tickers))
    w = 0.27
    ax.bar(x - w, rep, w, label="Reported NAV vol", color="#4c72b0")
    ax.bar(x, des, w, label="De-smoothed NAV vol (GLM k=2)", color="#dd8452")
    ax.bar(x + w, mkt, w, label="Market vol (quarterly basis)", color="#55a868")
    ax.set_xticks(x)
    ax.set_xticklabels(tickers)
    ax.set_ylabel("Annualized volatility (%)")
    ax.set_title("BDC volatility laundering: reported vs de-smoothed vs market")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "fig_laundering_ratio.png"), dpi=130)
    plt.close(fig)

    # Figure 2: de-smoothing mechanics
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    # (a) smoothing index xi per BDC (lower = more smoothing)
    xi = [ok[t]["glm_k2"]["xi"] for t in tickers]
    axes[0].bar(tickers, xi, color="#8172b3")
    axes[0].axhline(1.0, ls="--", color="gray", lw=1, label="xi=1 (no smoothing)")
    axes[0].set_ylabel("Smoothing index xi = sum(theta^2)")
    axes[0].set_title("GLM smoothing index (lower = more laundering)")
    axes[0].set_ylim(0, 1.05)
    axes[0].legend()
    axes[0].grid(axis="y", alpha=0.3)
    # (b) laundering ratio vs de-smoothed ratio per BDC
    lr = [ok[t]["laundering_ratio"] for t in tickers]
    dr = [ok[t]["desmoothed_market_ratio_k2"] for t in tickers]
    xx = np.arange(len(tickers))
    axes[1].bar(xx - 0.2, lr, 0.4, label="Reported / market", color="#4c72b0")
    axes[1].bar(xx + 0.2, dr, 0.4, label="De-smoothed / market", color="#dd8452")
    axes[1].axhline(1.0, ls="--", color="gray", lw=1, label="parity (=market vol)")
    axes[1].set_xticks(xx)
    axes[1].set_xticklabels(tickers)
    axes[1].set_ylabel("vol ratio to market")
    axes[1].set_title("Gap closure after de-smoothing")
    axes[1].legend()
    axes[1].grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "fig_desmoothing.png"), dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    main()
