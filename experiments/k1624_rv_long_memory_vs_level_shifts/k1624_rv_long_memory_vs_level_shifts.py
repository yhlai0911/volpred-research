"""
K1624 — RV / vol-proxy apparent long memory: TRUE fractional integration
        vs SPURIOUS long memory from occasional level shifts / structural breaks.

Core question (Granger & Hyung 2004 JEF; Diebold & Inoue 2001; Perron & Qu 2010;
Shimotsu 2006 JBES): the high persistence (apparent long memory, d hat ~ 0.4) in
daily volatility proxies — is it genuine long-range dependence (fractional
integration), or an artefact of a short-memory process contaminated by occasional
mean/level shifts (regime changes)?

Identification strategy (Part 1):
  1. Estimate d (GPH log-periodogram + Local Whittle) at several bandwidths m.
     Spurious LM tends to give d hat that is unstable across m.
  2. Detect multiple mean/level shifts (ruptures PELT, l2 cost = Bai-Perron-style
     least-squares multiple mean breaks).
  3. DECISIVE diagnostic: remove segment means (break-adjust / demean) and RE-
     ESTIMATE d. If d hat collapses toward 0 -> persistence lived in the mean level
     shifts -> SPURIOUS. If d hat stays high & stable -> TRUE long memory.
  4. Formal test: Shimotsu (2006) split-sample d-homogeneity Wald test (b=2,4).
     Under true stationary I(d), subsample d estimates are homogeneous; under
     breaks they diverge and the full-sample d exceeds subsample d.

Hard caveat: standard break tests over-reject "no break" under true long memory
(size distortion). We therefore lean on the DIRECTION of the demean-then-reestimate
diagnostic (a large drop is hard to rationalise under true LM, whose persistence is
not carried by the mean level) plus Shimotsu, and treat the break test as auxiliary.

Forecasting implication (Part 2): 1-day-ahead OOS forecast of the log-vol proxy,
comparing (a) ARFIMA(0,d,0) [assumes true LM], (b) HAR [Corsi short-memory
baseline], (c) break-robust HAR with adaptive (rolling local-mean) intercept
[the "if it's shifts, an adaptive mean should win" hypothesis]. Evaluated with
QLIKE (canonical actual/predicted direction, via volpred helper) + Diebold-Mariano
with Harvey-Leybourne-Newbold (1997) small-sample correction.

Differentiation from existing K:
  - K442 (FIGARCH d=0.61): estimated d but never asked true-vs-spurious. This fills
    the identification gap.
  - K529/K806/K936/K1423/K1424/fae873b0 (rough vol, Hurst<0.5, ARRV): those are
    about PATH ROUGHNESS (local, H~0.1) which is a DIFFERENT (often opposite)
    concept from LONG MEMORY (ACF slow decay, d>0, long-range dependence). This
    experiment is strictly on the long-memory side; no rough-vol re-run.

Anti-lookahead: all OOS forecasts use only information dated <= t-1 to predict t.
Seed fixed. Package failure != model invalidity (K1213); estimators hand-coded
where needed.

Author: VolPred autonomous research agent. Data: yfinance daily OHLC.
"""

from __future__ import annotations

import json
import sys
import warnings
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")

# --- canonical QLIKE / DM helpers (per .claude/rules/experiments.md) ---
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from volpred.stats.model_evaluation import qlike, qlike_pointwise, dm_test  # noqa: E402

SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
LN2 = np.log(2.0)
GK_C = 2.0 * LN2 - 1.0  # Garman-Klass constant ~0.3863
# Data-INDEPENDENT variance floor for zero-move days (~1 basis-point daily move)^2.
# Fixed constant (not a full-sample statistic) so no lookahead leaks into OOS via the
# floor of a lagged zero-return day (Codex review 2026-07-04 HIGH finding fix).
VAR_FLOOR = 1e-8

# assets: (ticker, label, start)
ASSETS = [
    ("SPY", "SPY", "1990-01-01"),
    ("0050.TW", "TW0050", "2000-01-01"),
    ("^GSPC", "GSPC", "1985-01-01"),  # robustness (longest history)
]
PROXIES = ("range", "absret")  # range = Garman-Klass sigma^2 ; absret = r^2 (|r|)
# forecasting run on all assets x both proxies (cheap w/ monthly refit)

# ------------------------------------------------------------------ data


def fetch_ohlc(ticker: str, start: str, retries: int = 3):
    import yfinance as yf

    last_err = None
    for _ in range(retries):
        try:
            df = yf.download(
                ticker, start=start, end="2026-07-04", progress=False,
                auto_adjust=False,
            )
            if df is not None and len(df) > 100:
                if hasattr(df.columns, "get_level_values"):
                    df.columns = df.columns.get_level_values(0)
                return df[["Open", "High", "Low", "Close"]].dropna()
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"[data] {ticker} retry after {e!r}", file=sys.stderr)
    raise RuntimeError(f"failed to fetch {ticker}: {last_err}")


def build_proxies(df):
    """Return dict proxy -> (dates, y=log-vol, V=variance-scale actual).

    range  : Garman-Klass daily variance sigma^2_GK (always >=0 for valid OHLC).
    absret : squared daily log-return r^2 (Granger-Hyung use |r|).
    y_t = 0.5 * log(V_t)  (log-vol);  V_t = exp(2 y_t) is the variance-scale proxy.
    """
    O = np.log(df["Open"].to_numpy(float))
    H = np.log(df["High"].to_numpy(float))
    L = np.log(df["Low"].to_numpy(float))
    C = np.log(df["Close"].to_numpy(float))
    dates = np.array([d for d in df.index])

    out = {}

    # Garman-Klass sigma^2 (per-day integrated variance proxy)
    gk = 0.5 * (H - L) ** 2 - GK_C * (C - O) ** 2
    # for valid bars ln(H/L) >= |ln(C/O)| => gk >= 0; floor exact-zero-range days
    # with a FIXED (data-independent) constant to avoid any lookahead via the floor.
    floor_gk = VAR_FLOOR
    n_floor_gk = int(np.sum(gk <= 0))
    gk = np.maximum(gk, floor_gk)
    out["range"] = {
        "dates": dates,
        "y": 0.5 * np.log(gk),
        "V": gk,
        "n_floored": n_floor_gk,
        "floor": float(floor_gk),
        "label": "Garman-Klass sigma^2",
    }

    # squared log returns r^2 (=> |r| proxy)
    r = np.diff(C)
    r2 = r ** 2
    d2 = dates[1:]
    n_zero = int(np.sum(r == 0.0))
    floor_r2 = VAR_FLOOR  # fixed, data-independent (no lookahead via floor)
    r2f = np.maximum(r2, floor_r2)
    out["absret"] = {
        "dates": d2,
        "y": 0.5 * np.log(r2f),   # = log|r|
        "V": r2,                  # keep raw r^2 (with exact zeros) for eval masking
        "r": r,
        "n_zero_ret": n_zero,
        "floor": float(floor_r2),
        "label": "squared log-return r^2",
    }
    return out


# ------------------------------------------------------ spectral estimators


def _periodogram(x):
    """One-sided periodogram I(lambda_j), j=1..n//2, lambda_j=2*pi*j/n."""
    x = np.asarray(x, float)
    x = x - x.mean()
    n = len(x)
    fx = np.fft.fft(x)
    I = (np.abs(fx) ** 2) / (2.0 * np.pi * n)
    m_max = n // 2
    j = np.arange(1, m_max + 1)
    lam = 2.0 * np.pi * j / n
    return lam, I[1 : m_max + 1]


def gph_estimate(x, m):
    """Geweke-Porter-Hudak (1983) log-periodogram regression estimate of d.

    log I(lam_j) = c - d * log(4 sin^2(lam_j/2)) + u_j ,  u_j var = pi^2/6.
    Returns (d_hat, se, ci_lo, ci_hi).
    """
    lam, I = _periodogram(x)
    m = int(min(m, len(I)))
    lam = lam[:m]
    I = I[:m]
    good = I > 0
    lam, I = lam[good], I[good]
    if len(I) < 8:
        return np.nan, np.nan, np.nan, np.nan
    X = np.log(4.0 * np.sin(lam / 2.0) ** 2)
    Y = np.log(I)
    Xc = X - X.mean()
    Sxx = np.sum(Xc ** 2)
    slope = np.sum(Xc * (Y - Y.mean())) / Sxx
    d_hat = -slope
    se = np.sqrt((np.pi ** 2 / 6.0) / Sxx)
    return float(d_hat), float(se), float(d_hat - 1.96 * se), float(d_hat + 1.96 * se)


def local_whittle(x, m, d_bounds=(-0.49, 0.99)):
    """Robinson (1995) local Whittle estimate of d. se = 1/(2 sqrt(m))."""
    from scipy.optimize import minimize_scalar

    lam, I = _periodogram(x)
    m = int(min(m, len(I)))
    lam = lam[:m]
    I = I[:m]
    good = I > 0
    lam, I = lam[good], I[good]
    if len(I) < 8:
        return np.nan, np.nan, np.nan, np.nan
    logl = np.log(lam)

    def R(d):
        c = np.mean((lam ** (2.0 * d)) * I)
        return np.log(c) - 2.0 * d * np.mean(logl)

    res = minimize_scalar(R, bounds=d_bounds, method="bounded")
    d_hat = float(res.x)
    m_eff = len(I)
    se = 1.0 / (2.0 * np.sqrt(m_eff))
    return d_hat, se, d_hat - 1.96 * se, d_hat + 1.96 * se


# ------------------------------------------------------ break detection


def detect_breaks(y, pen_mult=1.0, min_size=60):
    """Bai-Perron-style multiple mean breaks via ruptures PELT (l2 cost).

    Penalty = pen_mult * log(n) * sigma2_hat (BIC-type). Returns break indices
    (interior change-points) and segment means.
    """
    import ruptures as rpt

    y = np.asarray(y, float)
    n = len(y)
    # noise scale from first differences (robust to level shifts)
    sigma2 = np.median(np.abs(np.diff(y))) ** 2 / 0.4549  # MAD->var for iid-ish
    sigma2 = max(sigma2, np.var(np.diff(y)) / 2.0, 1e-8)
    pen = pen_mult * np.log(n) * sigma2
    algo = rpt.Pelt(model="l2", min_size=min_size).fit(y)
    bkps = algo.predict(pen=pen)  # includes n as last element
    interior = [b for b in bkps if b < n]
    # segment means
    seg_bounds = [0] + interior + [n]
    seg_means = []
    demeaned = y.copy()
    for a, b in zip(seg_bounds[:-1], seg_bounds[1:]):
        mu = y[a:b].mean()
        seg_means.append(float(mu))
        demeaned[a:b] = y[a:b] - mu
    return interior, seg_means, demeaned, float(pen), float(sigma2)


# ------------------------------------------------------ Shimotsu test


def shimotsu_test(y, b, m_frac=0.65):
    """Shimotsu (2006) split-sample d-homogeneity Wald test.

    Split into b contiguous blocks; LW-estimate d on each block and full sample.
    Under true stationary I(d): sqrt(m)(d_a - d) -> N(0, 1/4) i.i.d. across blocks,
    so W = 4*m_block * sum_a (d_a - d_bar)^2 -> chi2_{b-1}. Large W (small p) =>
    subsample d's diverge => evidence AGAINST pure long memory (favours breaks).
    Also report d_full vs mean(d_block): d_full >> d_block is the level-shift signature.
    """
    from scipy.stats import chi2

    y = np.asarray(y, float)
    n = len(y)
    blk = n // b
    m_block = max(8, int(blk ** m_frac))
    d_blocks = []
    for a in range(b):
        seg = y[a * blk : (a + 1) * blk]
        d_a, *_ = local_whittle(seg, m_block)
        d_blocks.append(d_a)
    d_blocks = np.array(d_blocks, float)
    d_bar = float(np.nanmean(d_blocks))
    m_full = max(8, int(n ** m_frac))
    d_full, *_ = local_whittle(y, m_full)
    W = float(4.0 * m_block * np.nansum((d_blocks - d_bar) ** 2))
    p = float(1.0 - chi2.cdf(W, df=b - 1))
    return {
        "b": b,
        "m_block": m_block,
        "d_blocks": [float(x) for x in d_blocks],
        "d_bar": d_bar,
        "d_full": float(d_full),
        "W": W,
        "p_value": p,
        "reject_true_LM_5pct": bool(p < 0.05),
    }


# -------------------------------- parametric-bootstrap identification (DECISIVE)


def simulate_fracint(d, n, seed, burn=2000, K=1500):
    """Simulate a stationary true I(d) (ARFIMA(0,d,0)) path via truncated MA(inf).
    Scale-free (unit innovations); the pipeline downstream is scale-invariant.
    """
    rng = np.random.default_rng(seed)
    N = n + burn
    e = rng.standard_normal(N)
    K = min(K, N)
    psi = np.empty(K + 1)
    psi[0] = 1.0
    for k in range(1, K + 1):
        psi[k] = psi[k - 1] * (k - 1 + d) / k
    return np.convolve(e, psi)[:N][burn:burn + n]


def _ident_stats(y, m_bw):
    """Statistics used to discriminate true vs spurious long memory."""
    interior, _sm, dem, _pen, _s2 = detect_breaks(y, pen_mult=1.0)
    d_post = local_whittle(dem, m_bw)[0]
    s2 = shimotsu_test(y, 2)
    s4 = shimotsu_test(y, 4)
    return {
        "d_post": float(d_post),
        "n_breaks": int(len(interior)),
        "W2": float(s2["W"]),
        "W4": float(s4["W"]),
        "dfull_minus_dbar": float(s4["d_full"] - s4["d_bar"]),
    }


def bootstrap_identification(y, d_pre, B=200, seed=SEED):
    """Self-calibrating identification via a TRUE-LM parametric bootstrap.

    Standard break tests / demean-reestimate / Shimotsu all suffer finite-sample
    size distortion under genuine long memory (a real I(d) series wanders and gets
    over-segmented, collapsing d_post; Shimotsu over-rejects). We therefore compare
    the OBSERVED statistics to their distribution under a fitted true-LM null
    (ARFIMA(0, d_pre, 0)). One-sided bootstrap p-values in the SPURIOUS direction:
      - d_post: spurious removes REAL shifts -> residual short-memory -> d_post near
        0, HIGHER than the true-LM null (which over-differences to very negative d).
        p = P(null d_post >= observed d_post). small p => spurious.
      - Shimotsu W: spurious => larger W than null. p = P(null W >= obs W).
      - d_full - d_bar: level shifts inflate full-sample d above subsample d.
    Verdict: count significant (p<0.05) among {d_post, W4, d_full-d_bar}.
      >=2 -> spurious ; 0 -> true LM ; 1 -> mixed.
    """
    y = np.asarray(y, float)
    T = len(y)
    m_bw = max(16, int(T ** 0.6))
    obs = _ident_stats(y, m_bw)

    null = {k: [] for k in ("d_post", "n_breaks", "W2", "W4", "dfull_minus_dbar")}
    for b in range(B):
        xs = simulate_fracint(d_pre, T, seed + 1 + b)
        st = _ident_stats(xs, m_bw)
        for k in null:
            null[k].append(st[k])
    nn = {k: np.asarray(v, float) for k, v in null.items()}

    def p_upper(key):  # spurious => observed at UPPER tail of null
        return float(np.mean(nn[key] >= obs[key]))

    pvals = {
        "d_post": p_upper("d_post"),
        "W2": p_upper("W2"),
        "W4": p_upper("W4"),
        "dfull_minus_dbar": p_upper("dfull_minus_dbar"),
    }
    bands = {k: {"null_mean": float(nn[k].mean()),
                 "null_p05": float(np.percentile(nn[k], 5)),
                 "null_p95": float(np.percentile(nn[k], 95))} for k in nn}

    sig = sum(pvals[k] < 0.05 for k in ("d_post", "W4", "dfull_minus_dbar"))
    if sig >= 2:
        verdict = "spurious (level-shift-induced)"
    elif sig == 0:
        verdict = "true long memory"
    else:
        verdict = "mixed"

    return {
        "B": B,
        "observed": obs,
        "boot_p_spurious_direction": pvals,
        "null_bands": bands,
        "n_significant_of_3": int(sig),
        "verdict": verdict,
        "null_d_post_samples": [float(x) for x in nn["d_post"]],  # for plotting
    }


# ------------------------------------------------------ HLN-corrected DM


def dm_hln(loss1, loss2, h=1):
    """Diebold-Mariano with Harvey-Leybourne-Newbold (1997) small-sample
    correction. Base t from volpred canonical dm_test (Newey-West HAC).
    Negative t => model 1 better. p from t_{n-1}.
    """
    from scipy import stats

    d = np.asarray(loss1, float) - np.asarray(loss2, float)
    d = d[np.isfinite(d)]
    n = len(d)
    t_base, _ = dm_test(loss1, loss2, h=h)
    factor = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    t_hln = t_base * factor
    p_hln = 2.0 * (1.0 - stats.t.cdf(abs(t_hln), df=n - 1))
    return float(t_base), float(t_hln), float(p_hln), int(n)


# ------------------------------------------------------ forecasting models


def frac_diff_weights(d, K):
    """AR(inf) weights pi_k of (1-L)^d = sum_k pi_k L^k, pi_0=1.
    Forecast of fractionally integrated y*: yhat*_{t} = -sum_{k>=1} pi_k y*_{t-k}.
    """
    pi = np.empty(K + 1)
    pi[0] = 1.0
    for k in range(1, K + 1):
        pi[k] = pi[k - 1] * (k - 1 - d) / k
    return pi


def _har_design(y):
    """HAR regressors from lagged y: [1, daily(t-1), weekly avg, monthly avg].
    Row t uses only y[<=t-1]. Returns X (n x 4) with NaN for warmup rows.
    """
    n = len(y)
    X = np.full((n, 4), np.nan)
    X[:, 0] = 1.0
    for t in range(22, n):
        X[t, 1] = y[t - 1]
        X[t, 2] = np.mean(y[t - 5 : t])       # y[t-5..t-1]
        X[t, 3] = np.mean(y[t - 22 : t])      # y[t-22..t-1]
    return X


def run_forecasts(y, oos_len=1000, refit_every=21, arfima_K=1000,
                  lm_window=252, m_frac=0.6):
    """Expanding-window 1-step-ahead OOS forecasts of log-vol proxy y.

    Models: ARFIMA(0,d,0), HAR, break-robust HAR (rolling local-mean intercept).
    Returns dict of forecast arrays aligned to OOS target dates + the actuals.
    All predictors use info <= t-1 only. Parameters re-estimated every refit_every
    steps (monthly). Returns forecasts on log-vol scale.
    """
    y = np.asarray(y, float)
    n = len(y)
    oos_start = n - oos_len
    assert oos_start >= 1200, f"train too short: {oos_start}"

    Xhar = _har_design(y)

    fc = {"arfima": np.full(oos_len, np.nan),
          "har": np.full(oos_len, np.nan),
          "brk": np.full(oos_len, np.nan)}
    resid_var = {"arfima": np.nan, "har": np.nan, "brk": np.nan}
    s2_used = {k: np.full(oos_len, np.nan) for k in fc}
    actual = y[oos_start:oos_start + oos_len]

    # local mean series (trailing lm_window ending at t-1): known at forecast time
    lm = np.full(n, np.nan)
    for t in range(lm_window, n):
        lm[t] = np.mean(y[t - lm_window : t])

    d_path = np.full(oos_len, np.nan)

    beta_har = None
    beta_brk = None
    d_hat = None

    for i in range(oos_len):
        t = oos_start + i
        if i % refit_every == 0:
            train_y = y[:t]
            m_lw = max(16, int(t ** m_frac))
            d_hat, *_ = local_whittle(train_y, m_lw)
            d_hat = float(np.clip(d_hat, -0.49, 0.99))

            # --- HAR OLS on training rows ---
            rows = np.arange(22, t)
            Xtr = Xhar[rows]
            ytr = y[rows]
            ok = np.all(np.isfinite(Xtr), 1) & np.isfinite(ytr)
            beta_har, *_ = np.linalg.lstsq(Xtr[ok], ytr[ok], rcond=None)
            res_h = ytr[ok] - Xtr[ok] @ beta_har
            resid_var["har"] = float(np.var(res_h))

            # --- break-robust: HAR on deviations from rolling local mean ---
            dev = y - lm  # deviation series (NaN warmup)
            Xdev = _har_design(np.nan_to_num(dev, nan=0.0))  # regressors of dev
            # rebuild dev design properly using dev values
            Xdev = np.full((n, 4), np.nan)
            Xdev[:, 0] = 1.0
            for tt in range(lm_window + 22, t):
                Xdev[tt, 1] = dev[tt - 1]
                Xdev[tt, 2] = np.mean(dev[tt - 5 : tt])
                Xdev[tt, 3] = np.mean(dev[tt - 22 : tt])
            rows_b = np.arange(lm_window + 22, t)
            Xb = Xdev[rows_b]
            yb = dev[rows_b]
            okb = np.all(np.isfinite(Xb), 1) & np.isfinite(yb)
            beta_brk, *_ = np.linalg.lstsq(Xb[okb], yb[okb], rcond=None)
            res_b = yb[okb] - Xb[okb] @ beta_brk
            resid_var["brk"] = float(np.var(res_b))

            # --- ARFIMA in-sample residual variance for bias correction ---
            piK = frac_diff_weights(d_hat, arfima_K)
            mu_tr = float(np.mean(train_y))
            ys_tr = train_y - mu_tr
            # in-sample 1-step residuals over a recent slice (cost control)
            lo = max(arfima_K, t - 750)
            res_a = []
            for s in range(lo, t):
                kk = min(arfima_K, s)
                pred = -np.dot(piK[1 : kk + 1], ys_tr[s - 1 :: -1][:kk])
                res_a.append(ys_tr[s] - pred)
            resid_var["arfima"] = float(np.var(res_a)) if res_a else np.nan

        d_path[i] = d_hat

        # ARFIMA one-step forecast (uses realized past y only)
        mu_t = float(np.mean(y[:t]))
        ys = y[:t] - mu_t
        kk = min(arfima_K, t)
        piK = frac_diff_weights(d_hat, arfima_K)
        pred_dev = -np.dot(piK[1 : kk + 1], ys[t - 1 :: -1][:kk])
        fc["arfima"][i] = mu_t + pred_dev

        # HAR one-step
        xrow = Xhar[t]
        if np.all(np.isfinite(xrow)):
            fc["har"][i] = float(xrow @ beta_har)

        # break-robust one-step
        if np.isfinite(lm[t]):
            dev_lag1 = y[t - 1] - lm[t - 1]
            dev_w = np.mean(y[t - 5 : t] - lm[t - 5 : t]) if np.all(np.isfinite(lm[t - 5 : t])) else np.nan
            dev_m = np.mean(y[t - 22 : t] - lm[t - 22 : t]) if np.all(np.isfinite(lm[t - 22 : t])) else np.nan
            if np.isfinite(dev_lag1) and np.isfinite(dev_w) and np.isfinite(dev_m):
                dev_hat = float(np.array([1.0, dev_lag1, dev_w, dev_m]) @ beta_brk)
                fc["brk"][i] = lm[t] + dev_hat

        for k in fc:
            s2_used[k][i] = resid_var[k]

    return {
        "actual_logvol": actual,
        "fc_logvol": fc,
        "resid_var_path": s2_used,
        "d_path": d_path,
        "oos_start": oos_start,
        "oos_len": oos_len,
    }


def evaluate_forecasts(fcres, V_actual_oos, proxy):
    """Convert log-vol forecasts to variance scale with per-model lognormal bias
    correction exp(2*yhat + 2*s2), compute QLIKE vs variance-scale actual, DM-HLN.

    V_actual_oos: variance-scale realized proxy over OOS (r^2 or GK sigma^2).
    For absret, mask exact-zero-return days (actual r^2 == 0) consistently.
    """
    fc = fcres["fc_logvol"]
    s2 = fcres["resid_var_path"]
    names = ["arfima", "har", "brk"]
    var_fc = {}
    for k in names:
        var_fc[k] = np.exp(2.0 * fc[k] + 2.0 * s2[k])  # bias-corrected variance forecast

    a = np.asarray(V_actual_oos, float)
    mask = np.isfinite(a)
    if proxy == "absret":
        mask &= (a > 0)  # drop exact-zero-return days
    for k in names:
        mask &= np.isfinite(var_fc[k])

    a_m = a[mask]
    out = {"n_eval": int(mask.sum()), "qlike": {}, "mse_logvol": {}, "dm": {}}
    logvol_actual = fcres["actual_logvol"][mask]
    for k in names:
        out["qlike"][k] = float(qlike(a_m, var_fc[k][mask]))
        out["mse_logvol"][k] = float(np.mean((fcres["fc_logvol"][k][mask] - logvol_actual) ** 2))

    pl = {k: qlike_pointwise(a_m, var_fc[k][mask]) for k in names}
    for m1, m2 in [("arfima", "har"), ("brk", "har"), ("arfima", "brk")]:
        tb, thln, phln, nn = dm_hln(pl[m1], pl[m2], h=1)
        out["dm"][f"{m1}_vs_{m2}"] = {
            "t_base": tb, "t_hln": thln, "p_hln": phln, "n": nn,
            "harvey_sig": bool(abs(thln) > 3.0),
            "note": f"neg t => {m1} better (lower QLIKE)",
        }
    return out, var_fc, mask


# ------------------------------------------------------ plots


def plot_breaks(dates, y, interior, seg_means, title, path):
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.plot(dates, y, lw=0.5, color="#444", alpha=0.7, label="log-vol proxy")
    n = len(y)
    seg_bounds = [0] + list(interior) + [n]
    for j, (a, b) in enumerate(zip(seg_bounds[:-1], seg_bounds[1:])):
        ax.hlines(seg_means[j], dates[a], dates[b - 1], color="#d62728", lw=2.2,
                  label="segment mean" if j == 0 else None)
    for b in interior:
        ax.axvline(dates[b], color="#1f77b4", ls="--", lw=0.8, alpha=0.6)
    ax.set_title(title)
    ax.set_ylabel("log-vol")
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_d_vs_bandwidth(bw_labels, d_pre, d_post, ci_pre, ci_post, title, path):
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    x = np.arange(len(bw_labels))
    ax.errorbar(x - 0.06, d_pre, yerr=ci_pre, fmt="o-", color="#d62728", capsize=4,
                label="pre-demean (raw, LM+shifts)")
    ax.errorbar(x + 0.06, d_post, yerr=ci_post, fmt="s-", color="#2ca02c", capsize=4,
                label="post-demean (break-adjusted)")
    ax.axhline(0.0, color="k", lw=0.6)
    ax.axhline(0.5, color="gray", ls=":", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(bw_labels)
    ax.set_xlabel("bandwidth m")
    ax.set_ylabel("d hat (Local Whittle)")
    ax.set_title(title)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_periodogram(y_pre, y_post, title, path):
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    for yy, c, lab in [(y_pre, "#d62728", "raw"), (y_post, "#2ca02c", "break-adjusted")]:
        lam, I = _periodogram(yy)
        m = int(len(I) ** 0.8)
        ax.loglog(lam[:m], I[:m], ".", ms=2, alpha=0.35, color=c)
        # smoothed
        k = 25
        Ism = np.convolve(I[:m], np.ones(k) / k, mode="valid")
        ax.loglog(lam[: len(Ism)], Ism, "-", color=c, lw=1.8, label=lab)
    ax.set_xlabel("frequency lambda")
    ax.set_ylabel("periodogram I(lambda)")
    ax.set_title(title)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_null_dpost(null_samples, d_post_obs, d_pre, verdict, title, path):
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    ax.hist(null_samples, bins=30, color="#9ecae1", edgecolor="#3182bd",
            alpha=0.8, label="true-LM null d_post (break-adjusted)")
    ax.axvline(d_post_obs, color="#d62728", lw=2.5,
               label=f"observed d_post = {d_post_obs:.2f}")
    ax.axvline(d_pre, color="#2ca02c", lw=2.0, ls="--",
               label=f"raw d_pre = {d_pre:.2f}")
    ax.set_xlabel("d hat after break-adjustment")
    ax.set_ylabel("count (bootstrap paths)")
    ax.set_title(f"{title}\nverdict: {verdict}")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_oos_cumloss(dates_oos, pl_arfima, pl_har, pl_brk, title, path):
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(dates_oos, np.cumsum(pl_har - pl_arfima), color="#1f77b4",
            label="cum(QLIKE_HAR - QLIKE_ARFIMA)  (up => ARFIMA better)")
    ax.plot(dates_oos, np.cumsum(pl_har - pl_brk), color="#ff7f0e",
            label="cum(QLIKE_HAR - QLIKE_brkHAR)  (up => brkHAR better)")
    ax.axhline(0, color="k", lw=0.7)
    ax.set_title(title)
    ax.set_ylabel("cumulative QLIKE loss diff")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# ------------------------------------------------------ main


def main():
    ts0 = datetime.now(timezone.utc).isoformat()
    results = {
        "experiment_id": "k1624_rv_long_memory_vs_level_shifts",
        "seed": SEED,
        "run_utc": ts0,
        "data_source": "yfinance daily OHLC (auto_adjust=False), Close-to-close returns",
        "assets": {},
        "methodology": {
            "d_estimators": ["GPH log-periodogram (se=sqrt(pi^2/6 / Sxx))",
                             "Local Whittle (Robinson 1995, se=1/(2 sqrt(m)))"],
            "bandwidths": "m = T^0.5, T^0.6, T^0.7",
            "break_detection": "ruptures PELT, l2 cost (Bai-Perron style mean breaks), BIC-type penalty",
            "identification": "DECISIVE = true-LM parametric-bootstrap calibration (B=200) of {break-adjusted d_post, Shimotsu W(b=2,4), d_full-d_bar}; verdict from bootstrap p-values in the spurious direction. Shimotsu asymptotic chi2 reported for reference.",
            "identification_rationale": "break tests / demean-reestimate / Shimotsu ALL over-reject no-break (collapse d_post, inflate W) under GENUINE long memory because a true I(d) path wanders and gets over-segmented; the parametric bootstrap under a fitted ARFIMA(0,d_pre,0) null self-calibrates every one of these distortions. Validated on simulated true-I(0.4) (no reject) and short-memory+level-shift (strong reject).",
            "forecast": "expanding-window 1-step OOS, monthly refit; ARFIMA(0,d,0) vs HAR vs break-robust HAR (rolling local-mean intercept)",
            "loss": "QLIKE (actual/predicted, volpred canonical) + DM w/ Harvey-Leybourne-Newbold(1997) correction",
            "caveat": "raw demean-reestimate drop is NOT self-sufficient (contaminated by over-segmentation); verdict relies on bootstrap-calibrated comparison to the true-LM null. Break DATES are descriptive only.",
        },
    }

    bw_exps = [0.5, 0.6, 0.7]

    for ticker, label, start in ASSETS:
        print(f"\n===== {label} ({ticker}) =====", file=sys.stderr)
        df = fetch_ohlc(ticker, start)
        prox = build_proxies(df)
        asset_res = {
            "ticker": ticker,
            "period": [str(df.index[0].date()), str(df.index[-1].date())],
            "n_days": int(len(df)),
            "proxies": {},
        }

        for pxname in PROXIES:
            P = prox[pxname]
            y = np.asarray(P["y"], float)
            dates = P["dates"]
            T = len(y)
            bws = [max(16, int(T ** e)) for e in bw_exps]

            # --- Part 1: pre-demean d ---
            d_pre = {"gph": {}, "lw": {}}
            for e, m in zip(bw_exps, bws):
                dg, seg, lg, hg = gph_estimate(y, m)
                dl, sel, ll, hl = local_whittle(y, m)
                d_pre["gph"][f"m_T{e}"] = {"m": m, "d": dg, "se": seg, "ci": [lg, hg]}
                d_pre["lw"][f"m_T{e}"] = {"m": m, "d": dl, "se": sel, "ci": [ll, hl]}

            # --- break detection (primary + sensitivity) ---
            interior, seg_means, demeaned, pen, sig2 = detect_breaks(y, pen_mult=1.0)
            brk_sens = {}
            for pm in (0.5, 1.0, 2.0, 3.0):
                itr, _sm, _dm, _pen, _s2 = detect_breaks(y, pen_mult=pm)
                brk_sens[f"pen_x{pm}"] = len(itr)
            break_dates = [str(np.datetime64(dates[b], "D")) if not isinstance(dates[b], str) else str(dates[b]) for b in interior]
            try:
                break_dates = [str(dates[b].date()) for b in interior]
            except Exception:  # noqa: BLE001
                pass

            # --- post-demean d (DECISIVE) ---
            d_post = {"gph": {}, "lw": {}}
            for e, m in zip(bw_exps, bws):
                dg, seg, lg, hg = gph_estimate(demeaned, m)
                dl, sel, ll, hl = local_whittle(demeaned, m)
                d_post["gph"][f"m_T{e}"] = {"m": m, "d": dg, "se": seg, "ci": [lg, hg]}
                d_post["lw"][f"m_T{e}"] = {"m": m, "d": dl, "se": sel, "ci": [ll, hl]}

            # d drop at middle bandwidth (T^0.6)
            d_pre_mid = d_pre["lw"]["m_T0.6"]["d"]
            d_post_mid = d_post["lw"]["m_T0.6"]["d"]
            drop_frac = (d_pre_mid - d_post_mid) / d_pre_mid if d_pre_mid else np.nan

            # --- Shimotsu formal test (asymptotic chi2, reported for reference) ---
            shim = {f"b{b}": shimotsu_test(y, b) for b in (2, 4)}

            # --- DECISIVE: true-LM parametric-bootstrap identification ---
            # (self-calibrates the size distortion of break tests / demean-reestimate
            #  / Shimotsu under genuine long memory.)
            boot = bootstrap_identification(y, d_pre_mid, B=200, seed=SEED)
            verdict = boot["verdict"]

            asset_res["proxies"][pxname] = {
                "proxy_label": P["label"],
                "T": T,
                "n_floored_or_zero": P.get("n_floored", P.get("n_zero_ret", 0)),
                "d_pre_demean": d_pre,
                "n_breaks": len(interior),
                "break_dates": break_dates,
                "break_penalty": pen,
                "break_sensitivity_count": brk_sens,
                "d_post_demean": d_post,
                "d_pre_mid_T0.6": d_pre_mid,
                "d_post_mid_T0.6": d_post_mid,
                "d_drop_fraction_raw_T0.6": float(drop_frac) if np.isfinite(drop_frac) else None,
                "d_drop_note": "raw drop is CONTAMINATED by over-segmentation under true LM; use bootstrap calibration below for the verdict",
                "shimotsu_asymptotic": shim,
                "bootstrap_identification": {k: v for k, v in boot.items()
                                             if k != "null_d_post_samples"},
                "identification_verdict": verdict,
            }

            # --- plots (SPY primary; also 0050) ---
            if label in ("SPY", "TW0050"):
                tag = f"{label}_{pxname}"
                plot_breaks(dates, y, interior, seg_means,
                            f"{label} log-vol ({P['label']}) + {len(interior)} detected level shifts",
                            HERE / f"fig_breaks_{tag}.png")
                dpre = [d_pre["lw"][f"m_T{e}"]["d"] for e in bw_exps]
                dpost = [d_post["lw"][f"m_T{e}"]["d"] for e in bw_exps]
                cipre = [1.96 * d_pre["lw"][f"m_T{e}"]["se"] for e in bw_exps]
                cipost = [1.96 * d_post["lw"][f"m_T{e}"]["se"] for e in bw_exps]
                plot_d_vs_bandwidth([f"T^{e}\n(m={m})" for e, m in zip(bw_exps, bws)],
                                    dpre, dpost, cipre, cipost,
                                    f"{label} ({P['label']}): d hat pre vs post break-adjust",
                                    HERE / f"fig_d_bandwidth_{tag}.png")
                plot_periodogram(y, demeaned,
                                 f"{label} ({P['label']}): periodogram raw vs break-adjusted",
                                 HERE / f"fig_periodogram_{tag}.png")
                plot_null_dpost(boot["null_d_post_samples"], boot["observed"]["d_post"],
                                d_pre_mid, verdict,
                                f"{label} ({P['label']}): observed break-adjusted d vs true-LM null",
                                HERE / f"fig_null_dpost_{tag}.png")

            # --- Part 2: forecasting ---
            oos_len = 1000 if T > 2600 else max(500, T - 1600)
            try:
                fcres = run_forecasts(y, oos_len=oos_len)
                V_oos = P["V"][fcres["oos_start"]: fcres["oos_start"] + fcres["oos_len"]]
                ev, var_fc, mask = evaluate_forecasts(fcres, V_oos, pxname)
                asset_res["proxies"][pxname]["forecast"] = {
                    "oos_len": fcres["oos_len"],
                    "refit": "monthly (21d), expanding window",
                    "mean_d_used": float(np.nanmean(fcres["d_path"])),
                    **ev,
                }
                if label in ("SPY", "TW0050"):
                    dates_oos = dates[fcres["oos_start"]: fcres["oos_start"] + fcres["oos_len"]][mask]
                    a_m = np.asarray(V_oos, float)[mask]
                    pl_a = qlike_pointwise(a_m, var_fc["arfima"][mask])
                    pl_h = qlike_pointwise(a_m, var_fc["har"][mask])
                    pl_b = qlike_pointwise(a_m, var_fc["brk"][mask])
                    plot_oos_cumloss(dates_oos, pl_a, pl_h, pl_b,
                                     f"{label} ({P['label']}): OOS cumulative QLIKE loss differences",
                                     HERE / f"fig_oos_cumloss_{label}_{pxname}.png")
            except Exception as e:  # noqa: BLE001
                print(f"[forecast] {label}/{pxname} FAILED: {e!r}", file=sys.stderr)
                asset_res["proxies"][pxname]["forecast"] = {"error": repr(e)}

            bp = boot["boot_p_spurious_direction"]
            print(f"  {pxname}: d_pre(T0.6)={d_pre_mid:.3f} d_post_obs={boot['observed']['d_post']:.3f} "
                  f"breaks={len(interior)} bootP[dpost={bp['d_post']:.3f},W4={bp['W4']:.3f},"
                  f"gap={bp['dfull_minus_dbar']:.3f}] -> {verdict}",
                  file=sys.stderr)

        results["assets"][label] = asset_res

    # overall verdict tally
    verdicts = []
    for lab, ar in results["assets"].items():
        for px, pr in ar["proxies"].items():
            verdicts.append(pr["identification_verdict"])
    from collections import Counter
    results["verdict_tally"] = dict(Counter(verdicts))
    results["run_finished_utc"] = datetime.now(timezone.utc).isoformat()

    outpath = HERE / "k1624_rv_long_memory_vs_level_shifts_results.json"
    with open(outpath, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[done] wrote {outpath}", file=sys.stderr)
    print(json.dumps(results["verdict_tally"], indent=2))


if __name__ == "__main__":
    main()
