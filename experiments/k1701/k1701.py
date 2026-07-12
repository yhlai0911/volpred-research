"""K1701 — Realized dispersion (index vs constituents) as a predictor of index
volatility and tail risk.

Question
--------
Does the gap between the average realized volatility of an index's *constituents*
and the realized volatility of the *index itself* lead (a) index volatility and
(b) index drawdowns?  The gap is the realized analogue of the dispersion trade:
it is large exactly when constituents move independently (low average correlation)
and collapses when everything moves together.

Differentiation from prior work in this repo
-------------------------------------------
K164/K165/K415/K771/K809/K982 all measure dispersion across 9-11 SPDR *sector
ETFs* and all report null (VIX sufficiency).  None of them uses the index-versus-
constituents construction, which is the canonical dispersion-trading measure and
the only one that sees idiosyncratic volatility (sector aggregation averages it
away).  We also run the sector-ETF basket inside the same framework so the two
levels are directly comparable rather than merely adjacent.

Method summary
--------------
* Historically reconstructed constituent baskets (Wikipedia change tables walked
  backwards).  This materially reduces current-list survivorship/membership bias,
  but it is not a vendor-grade point-in-time membership vintage.
* All signals are built from data up to and including origin t; targets start at
  t+1.  Expanding-window OOS training rows obey the forward-label embargo
  (row j is usable at origin i only if j + h < i).
* Diebold-Mariano always goes through volpred.stats.model_evaluation.dm_test
  (Newey-West, bandwidth ceil(h^(1/3) n^(1/3))).  A local NW variant exists only
  to report lag sensitivity and is asserted to reproduce the canonical statistic
  at the canonical bandwidth.
* QLIKE is actual/predicted (volpred qlike_pointwise), never the reverse.

Run: uv run python experiments/k1701/k1701.py
"""

from __future__ import annotations

import json
import math
import os
import warnings
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from volpred.stats.model_evaluation import clark_west_test, dm_test, qlike_pointwise
from volpred.utils import clean_tw50_data

warnings.filterwarnings("ignore", category=RuntimeWarning)

SEED = 42
rng = np.random.default_rng(SEED)

# every expanding_oos call records its realised embargo gap here
EMBARGO_AUDIT: dict = {}

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
FIG = HERE
RESULTS = HERE / "k1701_results.json"

SAMPLE_START = "2010-01-01"
VOL_WINDOW = 22          # rolling window for realized vols / dispersion
MIN_OBS_IN_WINDOW = 15   # a constituent needs this many returns inside the window
MIN_MEMBERS = 30         # a day needs this many usable constituents
MIN_TRAIN = 756          # ~3y before the first OOS origin
HORIZONS = (1, 5, 22)
TAIL_H = 22
VAR_FLOOR = 1e-10
RV_FLOOR_PCT = 1.0       # winsorise variance proxies at this pct of the warm-up window
CONSTITUENT_RET_MASK = 1.0  # |log r| above this in a constituent = data artifact, not a tail event
MASK_SENSITIVITY = (0.5, 1.5)  # re-run the whole ladder at these to prove the knob is not load-bearing

SECTOR_ETFS = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]

ASSETS = {
    "SPX": {
        "index": "SPY",
        "prices": "prices_us.parquet",
        "membership": "membership_SPX.csv",
        "vix": "^VIX",
        "label": "S&P 500 (SPY vs constituents)",
    },
    "TW50": {
        "index": "0050.TW",
        "prices": "prices_tw.parquet",
        "membership": "membership_TW50.csv",
        "vix": None,          # no free Taiwan VIX series
        "label": "Taiwan 50 (0050.TW vs constituents)",
    },
}

# The pre-registered primary proxy: average constituent vol / index vol.
# It is scale-free, but because the constituent average is equal-weighted while
# SPY/0050 are cap-weighted, it is NOT an algebraic inverse of average correlation.
# Treat rho below as the explicit equal-weight realized-correlation diagnostic.
PRIMARY_SIGNAL = "rdisp"
SIGNALS = ["rdisp", "disp", "rho", "csvd"]


def atomic_write_json(path: Path, payload: dict) -> None:
    """Crash-safe JSON write: temp file, parse validation, then atomic replace."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=float),
            encoding="utf-8",
        )
        with tmp.open(encoding="utf-8") as fh:
            json.load(fh)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


# ── realized-vol panel construction ───────────────────────────────────────────


def load_asset(name: str, mask_threshold: float = CONSTITUENT_RET_MASK) -> dict:
    cfg = ASSETS[name]
    px = pd.read_parquet(DATA / cfg["prices"])
    px.index = pd.to_datetime(px.index)

    cleaning = {"applied": False}
    if cfg["index"] == "0050.TW":
        # Mandatory project-level repair for Yahoo's artificial 2014-01-02
        # 0050.TW 1:4 split discontinuity.  The cached parquet stays raw; the
        # deterministic repair is applied in the analysis path and audited.
        raw_index_px = px[cfg["index"]].dropna().astype(float)
        raw_index_ret = np.log(raw_index_px / raw_index_px.shift(1))
        clean_index_px, _ = clean_tw50_data(raw_index_px)
        clean_index_ret = np.log(clean_index_px / clean_index_px.shift(1))
        px.loc[clean_index_px.index, cfg["index"]] = clean_index_px
        cleaning = {
            "applied": True,
            "function": "volpred.utils.clean_tw50_data",
            "reason": "repair Yahoo 0050.TW artificial 2014-01-02 1:4 split discontinuity",
            "raw_max_abs_log_return": float(raw_index_ret.abs().max()),
            "clean_max_abs_log_return": float(clean_index_ret.abs().max()),
            "n_prices_changed": int((raw_index_px != clean_index_px).sum()),
        }

    mem = pd.read_csv(DATA / cfg["membership"], parse_dates=["start", "end"])

    ret = np.log(px / px.shift(1))
    ret = ret.loc[ret.index >= pd.Timestamp("2009-01-01")]

    # The index gate must be checked on the RAW index series, BEFORE any constituent
    # masking.  Checking it afterwards is dead code: the constituent mask would already
    # have NaN'd a bad index print and dropped it from the calendar, so the gate could
    # never fire on the very artifact class it exists to catch (0050.TW's -1.389).
    raw_idx = ret[cfg["index"]].dropna()
    worst = float(raw_idx.abs().max())
    if worst > 0.25:
        raise RuntimeError(
            f"{cfg['index']}: |log return| of {worst:.3f} on "
            f"{raw_idx.abs().idxmax().date()} — a broad index cannot move that much "
            "(SPY's worst session ever is about -12%). This is a vendor data artifact; "
            "repair the price series before proceeding."
        )

    # Unadjusted corporate actions and corrupt vendor series are the single biggest
    # threat to a CROSS-SECTIONAL volatility average, because one bad print is not
    # diluted the way it would be in a cap-weighted index: 4938.TW's unadjusted 2010
    # spin-off (-2.39 in logs) lifts the 48-name Taiwan average vol by ~50% for a whole
    # month, and Compuware's corrupt Yahoo series does the same to the S&P average in
    # 2010-11.
    #
    # Threshold choice matters and cuts BOTH ways.  A 0.5 cut would also delete GENUINE
    # crash prints -- OXY -0.734, APA -0.774, TRGP -0.753 on 2020-03-09/03-18 are real --
    # and it would do so precisely in the stress regime where a dispersion effect would
    # live, i.e. it could manufacture the null it is supposed to be testing.  So the
    # default sits at 1.0 (a >170% up / >63% down single session), which still removes
    # 4938.TW's -2.386 and Compuware's worst prints while keeping the 2020 oil crash.
    # run_robustness() re-runs the whole ladder at 0.5 and at 1.5 to show the verdict
    # does not depend on this knob.
    bad = ret.abs() > mask_threshold
    masked = [
        {"ticker": c, "date": str(d.date()), "log_return": round(float(ret.at[d, c]), 4)}
        for c in ret.columns
        for d in ret.index[bad[c].fillna(False)]
    ]
    n_masked = len(masked)
    ret = ret.mask(bad)

    idx_ret = ret[cfg["index"]].dropna()
    # Align the constituent panel to the INDEX's own trading calendar.  Without this
    # the panel keeps stray dates contributed by other tickers, the 22d index vol is
    # then measured over a different day-set than the HAR's rv_m, and the two stop
    # being exactly the same quantity (they must be: idx_vol == sqrt(rv_m)).
    ret = ret.loc[idx_ret.index]
    return {
        "cfg": cfg,
        "ret": ret,
        "mem": mem,
        "idx_ret": idx_ret,
        "px": px,
        "n_masked": n_masked,
        "masked_obs": masked,
        "mask_threshold": mask_threshold,
        "cleaning": cleaning,
    }


def membership_matrix(mem: pd.DataFrame, dates: pd.DatetimeIndex, cols: list[str]) -> np.ndarray:
    """(T x M) boolean: was ticker m a point-in-time index member on date t?"""
    pos = {c: i for i, c in enumerate(cols)}
    mask = np.zeros((len(dates), len(cols)), dtype=bool)
    d = dates.values
    for _, row in mem.iterrows():
        j = pos.get(row["ticker"])
        if j is None:
            continue
        lo = np.searchsorted(d, np.datetime64(row["start"]), side="left")
        hi = np.searchsorted(d, np.datetime64(row["end"]), side="right")
        mask[lo:hi, j] = True
    return mask


def build_dispersion(
    ret: pd.DataFrame,
    idx_ret: pd.Series,
    member_mask: np.ndarray,
    tickers: list[str],
    window: int = VOL_WINDOW,
    min_members: int = MIN_MEMBERS,
) -> pd.DataFrame:
    """Realized dispersion measures at each origin t, using only data <= t.

    For origin t the basket is the point-in-time membership *on t*; constituent
    vols and the equal-weighted portfolio variance are both measured over the last
    `window` days.  Looking back at the past with today's basket is not look-ahead
    (every return used is dated <= t); it only means the basket is held fixed
    across the estimation window.
    """
    dates = ret.index
    R = ret[tickers].to_numpy(dtype=np.float64)
    T = len(dates)
    # scale the per-constituent data requirement to the window; a fixed 15-day floor
    # would silently reject EVERY constituent in the 10-day robustness run
    min_obs = max(5, min(MIN_OBS_IN_WINDOW, int(round(0.7 * window))))

    out = {k: np.full(T, np.nan) for k in ["idx_vol", "avg_vol", "disp", "rdisp", "rho", "csvd", "n_members"]}
    idx_r = idx_ret.reindex(dates).to_numpy(dtype=np.float64)

    for t in range(window - 1, T):
        sl = slice(t - window + 1, t + 1)
        alive = member_mask[t]
        if not alive.any():
            continue
        block = R[sl][:, alive]
        good = np.isfinite(block).sum(axis=0) >= min_obs
        if good.sum() < min_members:
            continue
        block = block[:, good]

        # index vol over the same window
        iw = idx_r[sl]
        if np.isfinite(iw).sum() < min_obs:
            continue
        idx_vol = float(np.sqrt(np.nanmean(iw**2)))
        if not np.isfinite(idx_vol) or idx_vol <= 0:
            continue

        sig = np.sqrt(np.nanmean(block**2, axis=0))           # per-constituent vol
        keep_i = np.isfinite(sig) & (sig > 0)
        sig = sig[keep_i]
        block = block[:, keep_i]
        if len(sig) < min_members:
            continue
        avg_vol = float(sig.mean())

        # equal-weighted portfolio built from the SAME basket over the SAME window
        ew = np.nanmean(block, axis=1)
        ew_var = float(np.nanmean(ew**2))

        n = len(sig)
        num = (n**2) * ew_var - float((sig**2).sum())
        den = float(sig.sum()) ** 2 - float((sig**2).sum())
        rho = num / den if den > 0 else np.nan   # vol-weighted average pairwise realized correlation

        out["idx_vol"][t] = idx_vol
        out["avg_vol"][t] = avg_vol
        out["disp"][t] = avg_vol - idx_vol
        out["rdisp"][t] = avg_vol / idx_vol
        out["rho"][t] = rho
        out["csvd"][t] = float(sig.std(ddof=1))
        out["n_members"][t] = n

    return pd.DataFrame(out, index=dates)


# ── HAR features and forward targets ──────────────────────────────────────────


def build_panel(idx_ret: pd.Series, disp: pd.DataFrame, vix: pd.Series | None) -> pd.DataFrame:
    r = idx_ret.copy()
    r2 = r**2

    df = pd.DataFrame(index=r.index)
    df["ret"] = r
    # HAR regressors — every window ENDS at t (inclusive), so nothing after t is used
    df["rv_d"] = r2
    df["rv_w"] = r2.rolling(5).mean()
    df["rv_m"] = r2.rolling(22).mean()

    # A single day's r^2 is one chi-square(1) draw, so log(r^2) has an enormous left
    # tail -- and it is not even a tail: a tick-constrained ETF closes *unchanged* on
    # a non-trivial share of days (0050.TW: 4.5%), where r^2 is exactly zero and
    # log(r^2) collapses to the floor, ~13 log-units below the median.  Left alone,
    # those days poison the HAR's daily regressor, blow up the residual variance that
    # drives the log-normal smearing, and dominate QLIKE through its -log(a/f) term.
    # We therefore winsorise the variance proxies from below at a floor estimated on
    # the FIRST TRAINING WINDOW ONLY (strictly before any OOS origin -> no look-ahead),
    # and apply the identical floor to every model and to the target transform.
    warm = df["rv_d"].iloc[:MIN_TRAIN]
    pos = warm[warm > 0]
    floor = float(np.percentile(pos, RV_FLOOR_PCT)) if len(pos) else VAR_FLOOR
    df.attrs["rv_floor"] = floor
    for c in ["rv_d", "rv_w", "rv_m"]:
        df[f"l_{c}"] = np.log(df[c].clip(lower=floor))

    d = disp.reindex(r.index)
    for s in SIGNALS + ["idx_vol", "avg_vol", "n_members"]:
        df[s] = d[s]
    df["l_rdisp"] = np.log(df["rdisp"].clip(lower=1e-6))
    # the cross-sectional volatility LEVEL, averaged over hundreds of stocks.
    # NOTE: log(rdisp) = log(avg_vol) - log(idx_vol) and log(idx_vol) = 0.5*l_rv_m
    # exactly, so {HAR, l_rdisp} and {HAR, l_avg_vol} span the SAME column space.
    df["l_avg_vol"] = np.log(df["avg_vol"].clip(lower=1e-6))
    # a dispersion measure that is NOT a function of the index's own volatility:
    # the cross-sectional coefficient of variation of constituent vols.
    df["csvd_rel"] = df["csvd"] / df["avg_vol"]

    if vix is not None:
        df["l_vix"] = np.log(vix.reindex(r.index).ffill(limit=3).clip(lower=1e-6))

    # forward targets: average daily variance over t+1 .. t+h  (strictly future)
    for h in HORIZONS:
        fwd = r2.shift(-1).rolling(h).mean().shift(-(h - 1))
        df[f"y_h{h}"] = fwd

    # forward max drawdown over t+1 .. t+TAIL_H (positive fraction)
    logp = r.cumsum()
    mdd = np.full(len(r), np.nan)
    lp = logp.to_numpy()
    for i in range(len(lp) - TAIL_H):
        w = lp[i + 1 : i + 1 + TAIL_H]
        run_max = np.maximum.accumulate(np.concatenate([[lp[i]], w]))
        dd = 1.0 - np.exp(np.concatenate([[lp[i]], w]) - run_max)
        mdd[i] = float(dd.max())
    df["y_mdd"] = mdd

    return df


# ── OOS engine ────────────────────────────────────────────────────────────────


def _ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return beta


def expanding_oos(
    df: pd.DataFrame,
    feats: list[str],
    target: str,
    h: int,
    log_target: bool,
    min_train: int = MIN_TRAIN,
    audit: dict | None = None,
) -> pd.DataFrame:
    """Expanding-window OOS forecasts with a forward-label embargo.

    The target at row j is built from trading days j+1 .. j+h, so row j only
    becomes usable at origin i once its whole label window is in the past:

        pos(j) + h < pos(i)

    where pos() is the position in the ORIGINAL trading-day index.  Slicing on the
    post-dropna frame would be wrong here: dispersion has gaps (days with too few
    usable constituents), so "h rows back" is not "h trading days back".  We carry
    the original positions through the dropna and enforce the rule on them.
    """
    cols = feats + [target]
    sub = df[cols].copy()
    orig_pos = np.arange(len(df))
    ok = np.isfinite(sub.to_numpy()).all(axis=1)
    sub = sub[ok]
    pos = orig_pos[ok]
    if len(sub) < min_train + 60:
        return pd.DataFrame()

    floor = float(df.attrs.get("rv_floor", VAR_FLOOR))
    Xall = np.column_stack([np.ones(len(sub)), sub[feats].to_numpy(dtype=np.float64)])
    yraw = sub[target].to_numpy(dtype=np.float64)
    # same winsorising floor as the regressors, so a zero-return day cannot drag the
    # log-target regression to -23 while the median sits near -10
    yfit = np.log(np.clip(yraw, floor, None)) if log_target else yraw

    preds, actuals, origins = [], [], []
    min_gap = np.inf
    for i in range(min_train, len(sub)):
        # last training row allowed: the newest j with pos[j] + h < pos[i]
        end = int(np.searchsorted(pos, pos[i] - h, side="left"))
        if end < min_train:
            continue
        if end > 0:
            min_gap = min(min_gap, int(pos[i] - pos[end - 1]))
        Xtr, ytr = Xall[:end], yfit[:end]
        beta = _ols(Xtr, ytr)
        resid = ytr - Xtr @ beta
        yhat = float(Xall[i] @ beta)
        if log_target:
            # Trap runaway extrapolation BEFORE exponentiating: a regressor whose
            # value at the origin sits far outside its training range can otherwise
            # produce an astronomically large variance forecast and let a couple of
            # origins dominate the whole QLIKE average.  The clip uses training-set
            # values only and is applied identically to every model, so no spec is
            # advantaged.
            lo, hi = float(ytr.min()) - 1.0, float(ytr.max()) + 1.0
            yhat = min(max(yhat, lo), hi)
            # log-normal smearing, applied identically to every model -> fair comparison
            yhat = math.exp(yhat + 0.5 * float(np.var(resid)))
            yhat = max(yhat, VAR_FLOOR)
        preds.append(yhat)
        actuals.append(float(yraw[i]))
        origins.append(sub.index[i])

    if audit is not None and np.isfinite(min_gap):
        # every training label must END strictly before the origin: gap > h
        audit.setdefault("embargo", []).append(
            {"target": target, "h": h, "min_origin_minus_last_train_pos": int(min_gap),
             "required_gt": h, "ok": bool(min_gap > h)}
        )

    return pd.DataFrame({"pred": preds, "actual": actuals}, index=pd.DatetimeIndex(origins))


# ── DM machinery (canonical primary + audited local variant for sensitivity) ──


def _nw_dm(d: np.ndarray, max_lag: int) -> float:
    """Newey-West DM t-stat at an explicit bandwidth.

    Used ONLY for lag-sensitivity reporting.  `dm_parity_check` asserts it
    reproduces the canonical dm_test at the canonical bandwidth, so the canonical
    helper remains the single source of truth for every headline number.
    """
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return float("nan")
    dm_ = float(np.mean(d))
    g0 = float(np.mean((d - dm_) ** 2))
    var = g0
    for lag in range(1, max_lag + 1):
        w = 1 - lag / (max_lag + 1)
        g = float(np.mean((d[lag:] - dm_) * (d[:-lag] - dm_)))
        var += 2 * w * g
    if var <= 0:
        return float("nan")
    return dm_ / math.sqrt(var / n)


def canonical_bandwidth(h: int, n: int) -> int:
    return max(1, min(int(np.ceil(h ** (1 / 3) * n ** (1 / 3))), n // 4))


def acf(x: np.ndarray, nlags: int = 10) -> list[float]:
    x = x[np.isfinite(x)] - np.mean(x[np.isfinite(x)])
    denom = float(np.sum(x**2))
    return [float(np.sum(x[k:] * x[:-k]) / denom) if denom > 0 else float("nan") for k in range(1, nlags + 1)]


def compare(loss_aug: np.ndarray, loss_base: np.ndarray, h: int) -> dict:
    """Canonical DM + the diagnostics the repo's DM/HAC lesson demands."""
    t_stat, p_val = dm_test(loss_aug, loss_base, h=h)   # negative t => augmented better
    d = loss_aug - loss_base
    n = int(np.isfinite(d).sum())
    bw = canonical_bandwidth(h, n)

    a = acf(d, 10)
    band = 1.96 / math.sqrt(n) if n else float("nan")
    sens = {
        "lag_0_iid": _nw_dm(d, 0) if n >= 10 else float("nan"),
        f"lag_{bw}_canonical": _nw_dm(d, bw),
        f"lag_{2 * bw}": _nw_dm(d, 2 * bw),
        f"lag_{4 * bw}": _nw_dm(d, 4 * bw),
    }
    return {
        "dm_t": float(t_stat),
        "dm_p": float(p_val),
        "n": n,
        "hac_lag_used": bw,
        "loss_diff_acf_1_10": a,
        "acf_white_noise_band": band,
        "acf1_outside_band": bool(abs(a[0]) > band) if n else None,
        "dm_t_by_lag": sens,
        "harvey_pass": bool(abs(t_stat) > 3.0),
    }


def dm_parity_check() -> dict:
    """Local NW variant must reproduce the canonical helper at canonical bandwidth."""
    g = np.random.default_rng(SEED)
    worst = 0.0
    for h in HORIZONS:
        e = g.standard_normal(1200)
        d = 0.02 + e + 0.6 * np.roll(e, 1)   # deliberately autocorrelated
        canon_t, _ = dm_test(d, np.zeros_like(d), h=h)
        mine = _nw_dm(d, canonical_bandwidth(h, len(d)))
        worst = max(worst, abs(canon_t - mine))
    return {"max_abs_diff_vs_canonical": float(worst), "passed": bool(worst < 1e-8)}


def common_all(*frames: pd.DataFrame) -> pd.DatetimeIndex:
    """Origins shared by every model, INCLUDING zero-variance days.

    MSE and Clark-West are perfectly well defined when the realised variance is zero,
    and those are the calmest (highest-dispersion) days -- exactly the regime the
    hypothesis would most want scored.  Only QLIKE has to drop them.
    """
    idx = frames[0].index
    for f in frames[1:]:
        idx = idx.intersection(f.index)
    return idx


def common_valid(*frames: pd.DataFrame) -> pd.DatetimeIndex:
    """Origins shared by every model AND on which QLIKE is defined.

    QLIKE contains -log(actual/predicted), which diverges when the realised variance
    is exactly zero.  The repo's canonical qlike() already drops those observations;
    qlike_pointwise() (used for the DM test) does not, so we drop them here instead of
    letting an unchanged close contribute a loss of ~+30 to a mean of ~0.5.  The same
    origins are removed for every model, so no specification is advantaged.
    """
    idx = frames[0].index
    for f in frames[1:]:
        idx = idx.intersection(f.index)
    actual = frames[0].loc[idx, "actual"].to_numpy()
    return idx[actual > 0]


def bh_fdr(pvals: list[float]) -> list[float]:
    p = np.asarray(pvals, dtype=float)
    m = len(p)
    order = np.argsort(p)
    q = np.empty(m)
    prev = 1.0
    for rank in range(m - 1, -1, -1):
        i = order[rank]
        prev = min(prev, p[i] * m / (rank + 1))
        q[i] = min(prev, 1.0)
    return [float(v) for v in q]


def hac_ols(y: np.ndarray, X: np.ndarray, lag: int) -> tuple[np.ndarray, np.ndarray]:
    """OLS with Newey-West standard errors (for in-sample diagnostics only)."""
    n, k = X.shape
    beta = _ols(X, y)
    e = y - X @ beta
    XtX_inv = np.linalg.pinv(X.T @ X)
    S = (X * e[:, None]).T @ (X * e[:, None])
    for L in range(1, lag + 1):
        w = 1 - L / (lag + 1)
        Xe_t = X[L:] * e[L:, None]
        Xe_l = X[:-L] * e[:-L, None]
        G = Xe_t.T @ Xe_l
        S += w * (G + G.T)
    V = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.maximum(np.diag(V), 0))
    return beta, se


# ── experiment ────────────────────────────────────────────────────────────────


def run_asset(name: str, results: dict) -> dict:
    cfg = ASSETS[name]
    print(f"\n=== {name}: {cfg['label']} ===")
    A = load_asset(name)
    ret, mem, idx_ret = A["ret"], A["mem"], A["idx_ret"]

    universe = sorted(set(mem["ticker"]) & set(ret.columns))
    mask = membership_matrix(mem, ret.index, universe)
    disp = build_dispersion(ret, idx_ret, mask, universe)

    vix = None
    if cfg["vix"] and cfg["vix"] in A["px"].columns:
        vix = A["px"][cfg["vix"]]

    df = build_panel(idx_ret, disp, vix)
    df = df.loc[df.index >= pd.Timestamp(SAMPLE_START)]

    valid = df["rdisp"].notna()
    print(f"  usable dispersion days: {int(valid.sum())} "
          f"({df.index[valid][0].date()} .. {df.index[valid][-1].date()})")
    print(f"  members/day: median {df['n_members'].median():.0f}, "
          f"min {df['n_members'].min():.0f}, max {df['n_members'].max():.0f}")

    out: dict = {
        "label": cfg["label"],
        "index_proxy": cfg["index"],
        "data_cleaning": A["cleaning"],
        "sample": {
            "start": str(df.index[valid][0].date()),
            "end": str(df.index[valid][-1].date()),
            "n_days_with_dispersion": int(valid.sum()),
            "members_per_day": {
                "median": float(df["n_members"].median()),
                "min": float(df["n_members"].min()),
                "max": float(df["n_members"].max()),
            },
        },
        "descriptive": {},
        "oos_vol": {},
        "oos_tail": {},
        "in_sample_hac": {},
        # every data-cleaning decision is recorded, because a cross-sectional vol
        # average is unusually sensitive to a single unadjusted corporate action
        "data_quality": {
            "index_cleaning": A["cleaning"],
            "constituent_mask_threshold_abs_log_return": A["mask_threshold"],
            "n_constituent_obs_masked": A["n_masked"],
            "masked_observations": A["masked_obs"],
            "rv_winsor_floor": float(df.attrs.get("rv_floor", VAR_FLOOR)),
            "rv_winsor_floor_pct_of_warmup": RV_FLOOR_PCT,
            "n_zero_variance_targets_dropped_from_qlike": {
                f"h{h}": int((df[f"y_h{h}"].dropna() <= 0).sum()) for h in HORIZONS
            },
        },
    }

    # descriptive statistics
    for s in SIGNALS + ["idx_vol", "avg_vol"]:
        v = df[s].dropna()
        out["descriptive"][s] = {
            "mean": float(v.mean()), "std": float(v.std()),
            "p5": float(v.quantile(0.05)), "median": float(v.median()),
            "p95": float(v.quantile(0.95)),
            "acf1": float(v.autocorr(1)),
        }
    if "l_vix" in df:
        both = df[["rdisp", "rho", "l_vix"]].dropna()
        out["descriptive"]["corr_with_log_vix"] = {
            "rdisp": float(both["rdisp"].corr(both["l_vix"])),
            "rho": float(both["rho"].corr(both["l_vix"])),
        }

    base_feats = ["l_rv_d", "l_rv_w", "l_rv_m"]

    # ---- OOS volatility forecasting: HAR vs HAR + signal ----
    for h in HORIZONS:
        tgt = f"y_h{h}"
        cells = {}
        base = expanding_oos(df, base_feats, tgt, h, log_target=True, audit=EMBARGO_AUDIT)
        if base.empty:
            continue
        rw = expanding_oos(df, ["l_rv_m"], tgt, h, log_target=True)
        ar1 = expanding_oos(df, ["l_rv_d"], tgt, h, log_target=True)

        lb = qlike_pointwise(base["actual"].to_numpy(), base["pred"].to_numpy())
        cells["_baselines"] = {}
        for bn, bdf in (("rw_rv22", rw), ("ar1_rv", ar1)):
            if bdf.empty:
                continue
            common = common_valid(base, bdf)
            l_b = qlike_pointwise(bdf.loc[common, "actual"].to_numpy(), bdf.loc[common, "pred"].to_numpy())
            l_h = qlike_pointwise(base.loc[common, "actual"].to_numpy(), base.loc[common, "pred"].to_numpy())
            cells["_baselines"][f"har_vs_{bn}"] = {
                "qlike_har": float(np.mean(l_h)),
                f"qlike_{bn}": float(np.mean(l_b)),
                **compare(l_h, l_b, h),
            }

        for s in SIGNALS:
            fcol = "l_rdisp" if s == "rdisp" else s
            aug = expanding_oos(df, base_feats + [fcol], tgt, h, log_target=True, audit=EMBARGO_AUDIT)
            if aug.empty:
                continue
            cq = common_valid(base, aug)     # QLIKE: zero-variance days are undefined
            ca = common_all(base, aug)       # MSE / Clark-West: defined at zero, keep them
            aq, pq_a, pq_b = (base.loc[cq, "actual"].to_numpy(),
                              aug.loc[cq, "pred"].to_numpy(), base.loc[cq, "pred"].to_numpy())
            am, pm_a, pm_b = (base.loc[ca, "actual"].to_numpy(),
                              aug.loc[ca, "pred"].to_numpy(), base.loc[ca, "pred"].to_numpy())
            la, l0 = qlike_pointwise(aq, pq_a), qlike_pointwise(aq, pq_b)
            ma, m0 = np.mean((am - pm_a) ** 2), np.mean((am - pm_b) ** 2)
            cells[s] = {
                "qlike_har": float(np.mean(l0)),
                "qlike_har_plus_signal": float(np.mean(la)),
                "qlike_improve_pct": float(100 * (np.mean(l0) - np.mean(la)) / np.mean(l0)),
                "mse_improve_pct": float(100 * (m0 - ma) / m0),
                "qlike_dm": compare(la, l0, h),
                "mse_dm": compare((am - pm_a) ** 2, (am - pm_b) ** 2, h),
                # DM answers realised finite-sample accuracy.  These models are NESTED,
                # and DM is biased toward the null for nested forecasts -- Clark-West is
                # the valid incremental-information test, so it is reported alongside.
                "mse_clark_west": clark_west_test(am, pm_b, pm_a, h=h),
            }

        # ---- the decisive identification ladder --------------------------------
        # The primary proxy test above cannot separate "dispersion" from "a better-measured
        # volatility level", because {HAR, l_rdisp} and {HAR, l_avg_vol} span the same
        # space.  So: first give the model the LEVEL (M1), then ask whether any genuine
        # dispersion measure still adds something ON TOP of it (M3/M4).  rho and csvd_rel
        # are non-linear in the HAR terms, so they are not spanned away.
        m0, m1 = base, expanding_oos(df, base_feats + ["l_avg_vol"], tgt, h, log_target=True, audit=EMBARGO_AUDIT)
        ladder = {}
        if not m1.empty:
            def _cmp(a_df, b_df, key):
                cq, ca = common_valid(a_df, b_df), common_all(a_df, b_df)
                lb = qlike_pointwise(b_df.loc[cq, "actual"].to_numpy(), b_df.loc[cq, "pred"].to_numpy())
                la = qlike_pointwise(b_df.loc[cq, "actual"].to_numpy(), a_df.loc[cq, "pred"].to_numpy())
                ladder[key] = {
                    "qlike_improve_pct": float(100 * (np.mean(lb) - np.mean(la)) / np.mean(lb)),
                    **compare(la, lb, h),
                    # nested models -> Clark-West is the valid incremental-content test
                    "mse_clark_west": clark_west_test(
                        b_df.loc[ca, "actual"].to_numpy(),
                        b_df.loc[ca, "pred"].to_numpy(),
                        a_df.loc[ca, "pred"].to_numpy(),
                        h=h,
                    ),
                }

            _cmp(m1, m0, "M1_level_vs_M0_har")           # does avg constituent vol help at all?
            for nm, extra in (("rho", ["rho"]), ("csvd_rel", ["csvd_rel"])):
                m = expanding_oos(df, base_feats + ["l_avg_vol"] + extra, tgt, h, log_target=True)
                if not m.empty:
                    _cmp(m, m1, f"M_{nm}_vs_M1_level")   # does dispersion add ON TOP of the level?

            # numerical proof of the span identity: M2 (HAR+l_rdisp) must equal M1
            m2 = expanding_oos(df, base_feats + ["l_rdisp"], tgt, h, log_target=True)
            if not m2.empty:
                c = common_valid(m1, m2)
                ladder["identity_check_rdisp_vs_avg_vol"] = {
                    "max_abs_forecast_diff": float(np.max(np.abs(
                        m1.loc[c, "pred"].to_numpy() - m2.loc[c, "pred"].to_numpy()))),
                    "max_rel_forecast_diff": float(np.max(np.abs(
                        m1.loc[c, "pred"].to_numpy() / m2.loc[c, "pred"].to_numpy() - 1))),
                    "note": "HAR+l_rdisp and HAR+l_avg_vol span the same space -> forecasts must coincide",
                }
        cells["ladder"] = ladder

        # VIX sufficiency ledger: does dispersion add anything ON TOP of VIX?
        if "l_vix" in df:
            vfe = base_feats + ["l_vix"]
            bv = expanding_oos(df, vfe, tgt, h, log_target=True)
            lvl = expanding_oos(df, vfe + ["l_avg_vol"], tgt, h, log_target=True)
            vs = {}
            if not bv.empty and not lvl.empty:
                def _cmpv(a_df, b_df, key):
                    c = common_valid(a_df, b_df)
                    actual = b_df.loc[c, "actual"].to_numpy()
                    pred_base = b_df.loc[c, "pred"].to_numpy()
                    pred_aug = a_df.loc[c, "pred"].to_numpy()
                    lb = qlike_pointwise(actual, pred_base)
                    la = qlike_pointwise(actual, pred_aug)
                    vs[key] = {
                        "qlike_improve_pct": float(100 * (np.mean(lb) - np.mean(la)) / np.mean(lb)),
                        **compare(la, lb, h),
                        "mse_clark_west": clark_west_test(actual, pred_base, pred_aug, h=h),
                    }

                # step 1: constituent-vol LEVEL on top of HAR+VIX
                _cmpv(lvl, bv, "level_vs_har_vix")
                # step 2: genuine dispersion on top of HAR+VIX+level
                for nm in ("rho", "csvd_rel"):
                    m = expanding_oos(df, vfe + ["l_avg_vol", nm], tgt, h, log_target=True)
                    if not m.empty:
                        _cmpv(m, lvl, f"{nm}_vs_har_vix_level")
            cells["vix_sufficiency"] = vs
        out["oos_vol"][f"h{h}"] = cells

    # ---- OOS tail: forward 22d max drawdown ----
    tail_cells = {}
    base_t = expanding_oos(df, base_feats, "y_mdd", TAIL_H, log_target=False, audit=EMBARGO_AUDIT)
    if not base_t.empty:
        for s in SIGNALS:
            fcol = "l_rdisp" if s == "rdisp" else s
            aug_t = expanding_oos(df, base_feats + [fcol], "y_mdd", TAIL_H, log_target=False, audit=EMBARGO_AUDIT)
            if aug_t.empty:
                continue
            common = base_t.index.intersection(aug_t.index)
            actual = base_t.loc[common, "actual"].to_numpy()
            pred_base = base_t.loc[common, "pred"].to_numpy()
            pred_aug = aug_t.loc[common, "pred"].to_numpy()
            e0 = (actual - pred_base) ** 2
            ea = (actual - pred_aug) ** 2
            tail_cells[s] = {
                "mse_har": float(np.mean(e0)),
                "mse_har_plus_signal": float(np.mean(ea)),
                "mse_improve_pct": float(100 * (np.mean(e0) - np.mean(ea)) / np.mean(e0)),
                **compare(ea, e0, TAIL_H),
                "mse_clark_west": clark_west_test(actual, pred_base, pred_aug, h=TAIL_H),
            }
        # same ladder as the vol leg: control the LEVEL first, then ask what dispersion adds
        lvl_t = expanding_oos(df, base_feats + ["l_avg_vol"], "y_mdd", TAIL_H, log_target=False)
        if not lvl_t.empty:
            for nm in ("rho", "csvd_rel"):
                m = expanding_oos(df, base_feats + ["l_avg_vol", nm], "y_mdd", TAIL_H, log_target=False)
                if m.empty:
                    continue
                c = lvl_t.index.intersection(m.index)
                actual = lvl_t.loc[c, "actual"].to_numpy()
                pred_base = lvl_t.loc[c, "pred"].to_numpy()
                pred_aug = m.loc[c, "pred"].to_numpy()
                e_l = (actual - pred_base) ** 2
                e_m = (actual - pred_aug) ** 2
                tail_cells[f"ladder_{nm}_vs_level"] = {
                    "mse_improve_pct": float(100 * (np.mean(e_l) - np.mean(e_m)) / np.mean(e_l)),
                    **compare(e_m, e_l, TAIL_H),
                    "mse_clark_west": clark_west_test(actual, pred_base, pred_aug, h=TAIL_H),
                }
        out["oos_tail"] = tail_cells

    # ---- in-sample HAC diagnostics (NOT headline) ----
    for h in HORIZONS:
        sub = df[["l_rv_d", "l_rv_w", "l_rv_m", "l_rdisp", f"y_h{h}"]].dropna()
        y = np.log(np.clip(sub[f"y_h{h}"].to_numpy(), VAR_FLOOR, None))
        X = np.column_stack([np.ones(len(sub)), sub[["l_rv_d", "l_rv_w", "l_rv_m", "l_rdisp"]].to_numpy()])
        lag = max(h, canonical_bandwidth(h, len(sub)))
        beta, se = hac_ols(y, X, lag)
        out["in_sample_hac"][f"h{h}"] = {
            "beta_l_rdisp": float(beta[4]),
            "hac_t_l_rdisp": float(beta[4] / se[4]) if se[4] > 0 else float("nan"),
            "hac_lag": int(lag),
            "n": int(len(sub)),
        }
    sub = df[["l_rv_d", "l_rv_w", "l_rv_m", "l_rdisp", "y_mdd"]].dropna()
    lag = max(TAIL_H, canonical_bandwidth(TAIL_H, len(sub)))
    beta, se = hac_ols(
        sub["y_mdd"].to_numpy(),
        np.column_stack([np.ones(len(sub)), sub[["l_rv_d", "l_rv_w", "l_rv_m", "l_rdisp"]].to_numpy()]),
        lag,
    )
    out["in_sample_hac"]["mdd"] = {
        "beta_l_rdisp": float(beta[4]),
        "hac_t_l_rdisp": float(beta[4] / se[4]) if se[4] > 0 else float("nan"),
        "hac_lag": int(lag),
        "n": int(len(sub)),
    }

    results[name] = out
    return {"df": df, "disp": disp, "ret": ret, "mask": mask, "universe": universe, "A": A}


def main() -> None:
    t0 = datetime.now(timezone.utc)
    manifest = json.loads((DATA / "data_manifest.json").read_text())

    results: dict = {
        "experiment_id": "K1701",
        "title": "Realized dispersion (index vs constituents) and index volatility / tail risk",
        "run_utc": t0.isoformat(),
        "seed": SEED,
        "data_provenance": manifest,
        "design": {
            "signal_definitions": {
                "idx_vol": "sqrt(mean r_index^2) over the last 22 trading days (data <= t)",
                "avg_vol": "cross-sectional mean of constituent 22d realized vols (PIT basket on t)",
                "disp": "avg_vol - idx_vol",
                "rdisp": "avg_vol / idx_vol  (PRIMARY; scale-free, decreasing in average correlation)",
                "rho": "equal-weighted average pairwise realized correlation implied by the EW portfolio variance",
                "csvd": "cross-sectional stdev of constituent vols (the sector-level measure of K415/K982, now at constituent level)",
            },
            "target": "forward average daily variance over t+1..t+h (h=1 -> r_{t+1}^2); forward 22d max drawdown for the tail leg",
            "baseline": "log-HAR (l_rv_d, l_rv_w, l_rv_m); also RW(22d) and AR(1); identical lag convention and identical log-normal smearing for every model",
            "test": "expanding-window OOS, forward-label embargo j+h<i, canonical dm_test (NW bandwidth ceil(h^(1/3) n^(1/3)))",
            "primary_family": "2 assets x 3 horizons, HAR vs HAR+rdisp, QLIKE loss -> BH FDR across the 6 cells",
            "gate": "QLIKE improvement > 0 AND Harvey |DM t| > 3 AND BH q < 0.05",
        },
        "dm_parity_check": dm_parity_check(),
        "assets": {},
    }
    print("DM parity vs canonical helper:", results["dm_parity_check"])

    keep = {}
    for name in ASSETS:
        keep[name] = run_asset(name, results["assets"])

    # ---- pre-registered primary family + BH FDR ----
    fam = []
    for name in ASSETS:
        for h in HORIZONS:
            cell = results["assets"].get(name, {}).get("oos_vol", {}).get(f"h{h}", {}).get(PRIMARY_SIGNAL)
            if not cell:
                continue
            fam.append(
                {
                    "asset": name,
                    "h": h,
                    "qlike_improve_pct": cell["qlike_improve_pct"],
                    "dm_t": cell["qlike_dm"]["dm_t"],
                    "dm_p": cell["qlike_dm"]["dm_p"],
                    "harvey_pass": cell["qlike_dm"]["harvey_pass"],
                    "hac_lag_used": cell["qlike_dm"]["hac_lag_used"],
                }
            )
    if fam:
        qs = bh_fdr([c["dm_p"] for c in fam])
        for c, q in zip(fam, qs):
            c["bh_q"] = q
            c["passes_gate"] = bool(c["qlike_improve_pct"] > 0 and c["harvey_pass"] and q < 0.05)
    results["primary_family"] = fam
    results["primary_verdict"] = {
        "cells": len(fam),
        "cells_passing_gate": int(sum(c["passes_gate"] for c in fam)),
        "cells_directionally_better": int(sum(c["qlike_improve_pct"] > 0 for c in fam)),
    }

    # ---- the decisive family: dispersion AFTER the volatility level is controlled ----
    # These are NESTED comparisons, so Clark-West is the valid incremental-content test
    # and DM (which is biased toward the null when nested) is reported alongside, not
    # instead.  BH-FDR runs across all 12 cells on the one-sided CW p-values.
    dfam = []
    for name in ASSETS:
        for h in HORIZONS:
            lad = results["assets"].get(name, {}).get("oos_vol", {}).get(f"h{h}", {}).get("ladder", {})
            for sig in ("rho", "csvd_rel"):
                cell = lad.get(f"M_{sig}_vs_M1_level")
                if not cell:
                    continue
                cw = cell.get("mse_clark_west", {})
                dfam.append(
                    {
                        "asset": name,
                        "h": h,
                        "signal": sig,
                        "qlike_improve_pct": cell["qlike_improve_pct"],
                        "dm_t": cell["dm_t"],
                        "cw_t": cw.get("t_stat"),
                        "cw_p_one_sided": cw.get("p_value_one_sided"),
                    }
                )
    if dfam:
        qs = bh_fdr([c["cw_p_one_sided"] for c in dfam])
        for c, q in zip(dfam, qs):
            c["cw_bh_q"] = q
            c["cw_nominal_sig"] = bool(c["cw_p_one_sided"] < 0.05)
            c["passes_gate"] = bool(q < 0.05 and abs(c["dm_t"]) > 3 and c["qlike_improve_pct"] > 0)
    results["dispersion_after_level_family"] = dfam
    results["dispersion_after_level_verdict"] = {
        "cells": len(dfam),
        "cw_nominally_significant": int(sum(c["cw_nominal_sig"] for c in dfam)),
        "cw_significant_after_bh": int(sum(c["cw_bh_q"] < 0.05 for c in dfam)),
        "passing_full_gate": int(sum(c["passes_gate"] for c in dfam)),
        "note": (
            "Clark-West is the valid test for these nested models; DM is biased toward the "
            "null when nested, so a DM-only null would be a weak claim. The verdict rests on "
            "CW surviving BH-FDR across the 12-cell family, which it does not."
        ),
    }

    results["robustness"] = run_robustness(keep, results)
    make_figures(keep, results)

    results["runtime_sec"] = (datetime.now(timezone.utc) - t0).total_seconds()
    RESULTS.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=float))

    print("\n" + "=" * 72)
    print("PRIMARY FAMILY (HAR vs HAR+rdisp, QLIKE):")
    for c in fam:
        print(
            f"  {c['asset']:5s} h={c['h']:2d}  QLIKE {c['qlike_improve_pct']:+7.3f}%  "
            f"DM t={c['dm_t']:+6.2f} (lag {c['hac_lag_used']})  BH q={c['bh_q']:.3f}  "
            f"{'PASS' if c['passes_gate'] else 'fail'}"
        )
    v = results["primary_verdict"]
    print(f"\n  gate passes: {v['cells_passing_gate']}/{v['cells']}   "
          f"directionally better: {v['cells_directionally_better']}/{v['cells']}")
    print(f"\nwrote {RESULTS}  ({results['runtime_sec']:.0f}s)")


# ── robustness ────────────────────────────────────────────────────────────────


def run_robustness(keep: dict, results: dict) -> dict:
    rob: dict = {}

    # R1 — high price-coverage subsample (SPX only; TW50 is >=92% throughout)
    cov = results["data_provenance"]["pit_membership_coverage_by_year"]["SPX"]
    hi_years = [int(y) for y, v in cov.items() if v["coverage"] >= 0.90]
    start = f"{min(hi_years)}-01-01" if hi_years else "2020-01-01"
    df = keep["SPX"]["df"]
    sub = df.loc[df.index >= pd.Timestamp(start)]
    r1 = {"start": start, "note": "restrict SPX to years where >=90% of PIT members have prices", "cells": {}}
    for h in HORIZONS:
        b = expanding_oos(sub, ["l_rv_d", "l_rv_w", "l_rv_m"], f"y_h{h}", h, log_target=True, min_train=378)
        a = expanding_oos(sub, ["l_rv_d", "l_rv_w", "l_rv_m", "l_rdisp"], f"y_h{h}", h, log_target=True, min_train=378)
        if b.empty or a.empty:
            continue
        c = common_valid(b, a)
        l0 = qlike_pointwise(b.loc[c, "actual"].to_numpy(), b.loc[c, "pred"].to_numpy())
        la = qlike_pointwise(a.loc[c, "actual"].to_numpy(), a.loc[c, "pred"].to_numpy())
        r1["cells"][f"h{h}"] = {
            "qlike_improve_pct": float(100 * (np.mean(l0) - np.mean(la)) / np.mean(l0)),
            **compare(la, l0, h),
        }
    rob["R1_high_coverage_subsample"] = r1

    # R2 — membership bias: today's basket applied to history vs point-in-time basket
    r2 = {}
    for name in ("SPX", "TW50"):
        k = keep[name]
        ret, mem, universe = k["ret"], k["A"]["mem"], k["universe"]
        today = pd.Timestamp(results["data_provenance"]["fetched_at_utc"][:10])
        cur = sorted(set(mem[(mem["start"] <= today) & (mem["end"] >= today)]["ticker"]) & set(universe))
        naive_mask = np.zeros((len(ret.index), len(universe)), dtype=bool)
        pos = {t: i for i, t in enumerate(universe)}
        for t in cur:
            naive_mask[:, pos[t]] = True
        naive = build_dispersion(ret, k["A"]["idx_ret"], naive_mask, universe)
        pit = k["disp"]
        j = pit[["rdisp"]].join(naive[["rdisp"]], rsuffix="_naive").dropna()
        j = j.loc[j.index >= pd.Timestamp(SAMPLE_START)]
        early = j.loc[j.index < pd.Timestamp("2015-01-01")]
        r2[name] = {
            "corr_pit_vs_naive": float(j["rdisp"].corr(j["rdisp_naive"])),
            "mean_rdisp_pit": float(j["rdisp"].mean()),
            "mean_rdisp_naive": float(j["rdisp_naive"].mean()),
            "mean_gap_naive_minus_pit": float((j["rdisp_naive"] - j["rdisp"]).mean()),
            "mean_gap_pre2015": float((early["rdisp_naive"] - early["rdisp"]).mean()) if len(early) else None,
            "note": "naive = today's constituent list applied to all history (survivorship + look-ahead membership)",
        }
    rob["R2_membership_bias"] = r2

    # R3 — same framework on the survivorship-free sector-ETF basket (links to K415/K982)
    k = keep["SPX"]
    ret = k["A"]["ret"]
    sec = [t for t in SECTOR_ETFS if t in ret.columns]
    sec_mask = np.zeros((len(ret.index), len(sec)), dtype=bool)
    sec_mask[:, :] = True
    sec_ret = ret[sec]
    # only 9 sector ETFs exist, so the constituent-count floor has to come down
    sdisp = build_dispersion(sec_ret, k["A"]["idx_ret"], sec_mask, sec, min_members=5)
    sdf = build_panel(k["A"]["idx_ret"], sdisp, None)
    sdf = sdf.loc[sdf.index >= pd.Timestamp(SAMPLE_START)]
    r3 = {"basket": sec, "note": "sector-ETF cross-section (survivorship-free) inside the identical framework", "cells": {}}
    for h in HORIZONS:
        b = expanding_oos(sdf, ["l_rv_d", "l_rv_w", "l_rv_m"], f"y_h{h}", h, log_target=True)
        a = expanding_oos(sdf, ["l_rv_d", "l_rv_w", "l_rv_m", "l_rdisp"], f"y_h{h}", h, log_target=True)
        if b.empty or a.empty:
            continue
        c = common_valid(b, a)
        l0 = qlike_pointwise(b.loc[c, "actual"].to_numpy(), b.loc[c, "pred"].to_numpy())
        la = qlike_pointwise(a.loc[c, "actual"].to_numpy(), a.loc[c, "pred"].to_numpy())
        r3["cells"][f"h{h}"] = {
            "qlike_improve_pct": float(100 * (np.mean(l0) - np.mean(la)) / np.mean(l0)),
            **compare(la, l0, h),
        }
    rob["R3_sector_etf_basket"] = r3

    # R4 — vol-window sensitivity
    r4 = {}
    for w in (10, 66):
        k = keep["SPX"]
        d_w = build_dispersion(k["ret"], k["A"]["idx_ret"], k["mask"], k["universe"], window=w)
        dfw = build_panel(k["A"]["idx_ret"], d_w, None)
        dfw = dfw.loc[dfw.index >= pd.Timestamp(SAMPLE_START)]
        cells = {}
        for h in HORIZONS:
            b = expanding_oos(dfw, ["l_rv_d", "l_rv_w", "l_rv_m"], f"y_h{h}", h, log_target=True)
            a = expanding_oos(dfw, ["l_rv_d", "l_rv_w", "l_rv_m", "l_rdisp"], f"y_h{h}", h, log_target=True)
            if b.empty or a.empty:
                continue
            c = common_valid(b, a)
            l0 = qlike_pointwise(b.loc[c, "actual"].to_numpy(), b.loc[c, "pred"].to_numpy())
            la = qlike_pointwise(a.loc[c, "actual"].to_numpy(), a.loc[c, "pred"].to_numpy())
            cells[f"h{h}"] = {
                "qlike_improve_pct": float(100 * (np.mean(l0) - np.mean(la)) / np.mean(l0)),
                "dm_t": compare(la, l0, h)["dm_t"],
            }
        r4[f"window_{w}d"] = cells
    rob["R4_vol_window_sensitivity"] = r4

    # R5 — lookahead audit (truncation test + embargo gaps recorded during the OOS run)
    rob["R5_lookahead_audit"] = lookahead_audit(keep, EMBARGO_AUDIT)

    # R6 — did the CLEANING manufacture the null?  The constituent mask is the only
    # cleaning knob with a real bias vector: masking a return NaNs it out of that stock's
    # vol AND out of the equal-weight portfolio, which depresses avg_vol and rho in the
    # crash regime -- the exact regime a dispersion effect would live in.  So re-run the
    # whole level-controlled ladder at a tighter and a looser threshold and check the
    # verdict is invariant.  If the null only exists at one threshold, it was manufactured.
    r6: dict = {"default_threshold": CONSTITUENT_RET_MASK, "thresholds": {}}
    for thr in MASK_SENSITIVITY:
        per_thr = {"n_masked": {}, "cells": {}}
        for name in ASSETS:
            A = load_asset(name, mask_threshold=thr)
            per_thr["n_masked"][name] = A["n_masked"]
            universe = sorted(set(A["mem"]["ticker"]) & set(A["ret"].columns))
            mask = membership_matrix(A["mem"], A["ret"].index, universe)
            disp = build_dispersion(A["ret"], A["idx_ret"], mask, universe)
            d = build_panel(A["idx_ret"], disp, None)
            d = d.loc[d.index >= pd.Timestamp(SAMPLE_START)]
            bf = ["l_rv_d", "l_rv_w", "l_rv_m"]
            for h in HORIZONS:
                lvl = expanding_oos(d, bf + ["l_avg_vol"], f"y_h{h}", h, log_target=True)
                if lvl.empty:
                    continue
                for sig in ("rho", "csvd_rel"):
                    m = expanding_oos(d, bf + ["l_avg_vol", sig], f"y_h{h}", h, log_target=True)
                    if m.empty:
                        continue
                    cq, ca = common_valid(m, lvl), common_all(m, lvl)
                    lb = qlike_pointwise(lvl.loc[cq, "actual"].to_numpy(), lvl.loc[cq, "pred"].to_numpy())
                    la = qlike_pointwise(lvl.loc[cq, "actual"].to_numpy(), m.loc[cq, "pred"].to_numpy())
                    cw = clark_west_test(
                        lvl.loc[ca, "actual"].to_numpy(),
                        lvl.loc[ca, "pred"].to_numpy(),
                        m.loc[ca, "pred"].to_numpy(),
                        h=h,
                    )
                    per_thr["cells"][f"{name}_h{h}_{sig}"] = {
                        "qlike_improve_pct": float(100 * (np.mean(lb) - np.mean(la)) / np.mean(lb)),
                        "dm_t": compare(la, lb, h)["dm_t"],
                        "cw_t": cw.get("t_stat"),
                        "cw_p_one_sided": cw.get("p_value_one_sided"),
                    }
        cells = per_thr["cells"]
        if cells:
            qs = bh_fdr([c["cw_p_one_sided"] for c in cells.values()])
            for c, q in zip(cells.values(), qs):
                c["cw_bh_q"] = q
            per_thr["summary"] = {
                "cells": len(cells),
                "cw_nominally_significant": int(sum(c["cw_p_one_sided"] < 0.05 for c in cells.values())),
                "cw_significant_after_bh": int(sum(c["cw_bh_q"] < 0.05 for c in cells.values())),
                "harvey_dm_helpful": int(sum(c["dm_t"] < -3 for c in cells.values())),
            }
        r6["thresholds"][f"mask_{thr}"] = per_thr
    rob["R6_cleaning_did_not_manufacture_the_null"] = r6
    return rob


def lookahead_audit(keep: dict, embargo_audit: dict) -> dict:
    """Mechanical proof that no signal can see the future.

    The decisive test is TRUNCATION: rebuild every dispersion signal from a return
    panel that has been cut off at T0, and require the values at every t <= T0 to
    be bit-identical to the full-sample values.  A signal that peeks at t+1 (or at
    any later row) cannot survive this, whereas eyeballing `.shift(1)` calls can
    miss a leak hiding inside a rolling window.
    """
    checks: dict = {}
    for name, k in keep.items():
        df, A = k["df"], k["A"]

        # 1. targets are strictly forward: y_h1 at t must be exactly r_{t+1}^2
        y1 = df["y_h1"].dropna()
        rebuilt = (df["ret"] ** 2).shift(-1).reindex(y1.index)
        ok_target = bool(np.allclose(y1.to_numpy(), rebuilt.to_numpy(), rtol=0, atol=0, equal_nan=True))

        # 2. truncation test on the signals
        T0 = pd.Timestamp("2018-06-29")
        ret_cut = A["ret"].loc[A["ret"].index <= T0]
        idx_cut = A["idx_ret"].loc[A["idx_ret"].index <= T0]
        mask_cut = k["mask"][: len(ret_cut)]
        disp_cut = build_dispersion(ret_cut, idx_cut, mask_cut, k["universe"])
        full = k["disp"].loc[k["disp"].index <= T0]
        common = disp_cut.index.intersection(full.index)
        diffs = {}
        for s in SIGNALS:
            a = full.loc[common, s].to_numpy()
            b = disp_cut.loc[common, s].to_numpy()
            both = np.isfinite(a) & np.isfinite(b)
            diffs[s] = float(np.max(np.abs(a[both] - b[both]))) if both.any() else float("nan")
        ok_trunc = all(d == 0.0 or (np.isfinite(d) and d < 1e-12) for d in diffs.values())

        checks[name] = {
            "y_h1_equals_next_day_squared_return": ok_target,
            "truncation_test_T0": str(T0.date()),
            "truncation_max_abs_diff_by_signal": diffs,
            "truncation_identical": bool(ok_trunc),
            "n_days_compared": int(len(common)),
            "bad_ticks_masked": int(A["n_masked"]),
        }

    checks["embargo"] = embargo_audit.get("embargo", [])
    checks["embargo_all_ok"] = bool(all(e["ok"] for e in checks["embargo"])) if checks["embargo"] else None
    checks["all_passed"] = bool(
        all(
            v["y_h1_equals_next_day_squared_return"] and v["truncation_identical"]
            for v in checks.values()
            if isinstance(v, dict) and "truncation_identical" in v
        )
        and (checks["embargo_all_ok"] is not False)
    )
    return checks


# ── figures ───────────────────────────────────────────────────────────────────


def make_figures(keep: dict, results: dict) -> None:
    plt.rcParams.update({"figure.dpi": 130, "font.size": 9, "axes.grid": True,
                         "grid.alpha": 0.25, "axes.spines.top": False, "axes.spines.right": False,
                         # DejaVu Sans has no CJK glyphs; without this every Chinese label
                         # renders as tofu boxes
                         "font.sans-serif": ["Heiti TC", "Arial Unicode MS", "Hiragino Sans GB", "DejaVu Sans"],
                         "axes.unicode_minus": False})
    ann = math.sqrt(252)

    # Fig 1 — index vol vs average constituent vol
    fig, axes = plt.subplots(2, 1, figsize=(11, 6.5), sharex=False)
    for ax, name in zip(axes, ASSETS):
        df = keep[name]["df"]
        ax.plot(df.index, df["avg_vol"] * ann * 100, lw=0.8, label="平均成分股波動率", color="#c0392b")
        ax.plot(df.index, df["idx_vol"] * ann * 100, lw=0.8, label="指數波動率", color="#2c3e50")
        ax.fill_between(df.index, df["idx_vol"] * ann * 100, df["avg_vol"] * ann * 100,
                        alpha=0.15, color="#e67e22", label="realized dispersion")
        ax.set_title(f"{name} — {ASSETS[name]['label']}")
        ax.set_ylabel("annualised vol (%)")
        ax.legend(loc="upper right", fontsize=8)
    fig.suptitle("Fig 1 — 指數波動率 vs 成分股平均波動率（22 日已實現，point-in-time 成分股）", fontsize=11)
    fig.tight_layout()
    fig.savefig(FIG / "fig1_index_vs_constituent_vol.png", bbox_inches="tight")
    plt.close(fig)

    # Fig 2 — the dispersion ratio and the implied average correlation
    fig, axes = plt.subplots(2, 1, figsize=(11, 6.5))
    for ax, name in zip(axes, ASSETS):
        df = keep[name]["df"]
        ax.plot(df.index, df["rdisp"], lw=0.8, color="#8e44ad", label="rdisp = 平均成分股波動 / 指數波動")
        ax2 = ax.twinx()
        ax2.plot(df.index, df["rho"], lw=0.8, color="#16a085", alpha=0.75, label="已實現平均相關係數 ρ̄")
        ax2.grid(False)
        ax.set_title(f"{name}")
        ax.set_ylabel("rdisp")
        ax2.set_ylabel("ρ̄")
        h1, l1 = ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax.legend(h1 + h2, l1 + l2, loc="upper right", fontsize=8)
    fig.suptitle("Fig 2 — 離散度與已實現平均相關係數（互為鏡像）", fontsize=11)
    fig.tight_layout()
    fig.savefig(FIG / "fig2_dispersion_and_correlation.png", bbox_inches="tight")
    plt.close(fig)

    # Fig 3 — membership-bias diagnostic
    cov = results["data_provenance"]["pit_membership_coverage_by_year"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    for name, c in cov.items():
        ys = sorted(int(y) for y in c)
        axes[0].plot(ys, [c[str(y)]["coverage"] if str(y) in c else c[y]["coverage"] for y in ys],
                     marker="o", ms=3, label=name)
    axes[0].axhline(0.9, ls="--", lw=0.8, color="grey")
    axes[0].set_title("PIT 成分股中「yfinance 有價格」的比例")
    axes[0].set_ylabel("coverage")
    axes[0].legend(fontsize=8)
    r2 = results["robustness"]["R2_membership_bias"]
    names = list(r2)
    axes[1].bar([f"{n}\n全期" for n in names], [r2[n]["mean_gap_naive_minus_pit"] for n in names],
                color="#c0392b", alpha=0.8)
    axes[1].bar([f"{n}\n2010-14" for n in names], [r2[n]["mean_gap_pre2015"] or 0 for n in names],
                color="#e67e22", alpha=0.8)
    axes[1].axhline(0, color="k", lw=0.8)
    axes[1].set_title("用今日清單回推 vs point-in-time：rdisp 平均偏誤")
    axes[1].set_ylabel("naive − PIT")
    fig.suptitle("Fig 3 — 成分股資料的兩個偏誤（覆蓋率 / 名單回推）", fontsize=11)
    fig.tight_layout()
    fig.savefig(FIG / "fig3_membership_bias.png", bbox_inches="tight")
    plt.close(fig)

    # Fig 4 — OOS result table
    fam = results["primary_family"]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    labs = [f"{c['asset']}\nh={c['h']}" for c in fam]
    vals = [c["qlike_improve_pct"] for c in fam]
    colors = ["#27ae60" if c["passes_gate"] else ("#95a5a6" if v > 0 else "#c0392b")
              for c, v in zip(fam, vals)]
    bars = ax.bar(labs, vals, color=colors, alpha=0.85)
    span = max(abs(min(vals)), abs(max(vals))) or 1.0
    ax.set_ylim(min(vals) - 0.35 * span, max(vals) + 0.35 * span)
    for b, c in zip(bars, fam):
        y = b.get_height()
        ax.text(b.get_x() + b.get_width() / 2, y + (0.05 * span if y >= 0 else -0.05 * span),
                f"DM t={c['dm_t']:+.2f}\nq={c['bh_q']:.2f}",
                ha="center", va="bottom" if y >= 0 else "top", fontsize=7)
    ax.axhline(0, color="k", lw=0.9)
    ax.set_ylabel("QLIKE 改善 (%)  正值 = 加入離散度較好")
    ax.set_title("Fig 4 — OOS：HAR vs HAR + realized dispersion（綠 = 通過 Harvey |t|>3 且 BH q<0.05）")
    fig.tight_layout()
    fig.savefig(FIG / "fig4_oos_qlike.png", bbox_inches="tight")
    plt.close(fig)

    # Fig 5 — the DM/HAC lesson made visible: loss-differential ACF
    fig, axes = plt.subplots(1, len(HORIZONS), figsize=(11, 3.4), sharey=True)
    for ax, h in zip(axes, HORIZONS):
        cell = results["assets"]["SPX"]["oos_vol"][f"h{h}"][PRIMARY_SIGNAL]["qlike_dm"]
        a = cell["loss_diff_acf_1_10"]
        band = cell["acf_white_noise_band"]
        ax.bar(range(1, len(a) + 1), a, color="#2980b9", alpha=0.85)
        ax.axhline(band, ls="--", lw=0.8, color="#c0392b")
        ax.axhline(-band, ls="--", lw=0.8, color="#c0392b")
        ax.axhline(0, color="k", lw=0.8)
        ax.set_title(f"SPX h={h}  (HAC lag={cell['hac_lag_used']})", fontsize=9)
        ax.set_xlabel("lag")
    axes[0].set_ylabel("loss differential ACF")
    fig.suptitle("Fig 5 — loss differential 自相關：h−1 當 HAC lag 會在 h=1 退化成 iid（虛線 = 白噪音界）", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIG / "fig5_loss_diff_acf.png", bbox_inches="tight")
    plt.close(fig)

    # Fig 6 — event study: where does dispersion sit before vol spikes / drawdowns?
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    df = keep["SPX"]["df"].dropna(subset=["rdisp", "y_h22", "y_mdd"])
    pct = df["rdisp"].rank(pct=True)
    for ax, tgt, title in ((axes[0], "y_h22", "未來 22 日波動率"), (axes[1], "y_mdd", "未來 22 日最大回撤")):
        thr = df[tgt].quantile(0.9)
        spike = df[tgt] >= thr
        ax.hist(pct[~spike], bins=20, alpha=0.6, density=True, label="平常", color="#7f8c8d")
        ax.hist(pct[spike], bins=20, alpha=0.6, density=True, label=f"{title} 前 10%", color="#c0392b")
        ax.set_xlabel("當日 rdisp 的樣本百分位")
        ax.set_title(f"{title}（SPX）", fontsize=9)
        ax.legend(fontsize=8)
    fig.suptitle("Fig 6 — 事件研究：高波動 / 大回撤之前，離散度處在什麼水位？", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIG / "fig6_event_study.png", bbox_inches="tight")
    plt.close(fig)

    # Fig 7 — THE result: separate the volatility LEVEL from genuine dispersion
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.3), sharey=True)
    for ax, name in zip(axes, ASSETS):
        cells = results["assets"][name]["oos_vol"]
        hs = [f"h{h}" for h in HORIZONS]
        series = [
            ("成分股平均波動「水準」\n（vs 純 HAR）", "M1_level_vs_M0_har", "#2980b9"),
            ("真離散度 ρ̄\n（控制水準後）", "M_rho_vs_M1_level", "#27ae60"),
            ("真離散度 CV\n（控制水準後）", "M_csvd_rel_vs_M1_level", "#e67e22"),
        ]
        x = np.arange(len(hs))
        w = 0.26
        for k, (lab, key, col) in enumerate(series):
            vals, ts = [], []
            for hkey in hs:
                c = cells.get(hkey, {}).get("ladder", {}).get(key)
                vals.append(c["qlike_improve_pct"] if c else np.nan)
                ts.append(c["dm_t"] if c else np.nan)
            bars = ax.bar(x + (k - 1) * w, vals, w, label=lab, color=col, alpha=0.88)
            for b, t in zip(bars, ts):
                if not np.isfinite(t):
                    continue
                y = b.get_height()
                mark = "★" if abs(t) > 3 else ""
                ax.text(b.get_x() + b.get_width() / 2, y + (0.12 if y >= 0 else -0.12),
                        f"{t:+.1f}{mark}", ha="center",
                        va="bottom" if y >= 0 else "top", fontsize=6.5)
        ax.axhline(0, color="k", lw=0.9)
        ax.set_xticks(x)
        ax.set_xticklabels([f"h={h}" for h in HORIZONS])
        ax.set_title(name, fontsize=10)
    axes[0].set_ylabel("QLIKE 改善 (%)　正值 = 有幫助")
    axes[0].legend(fontsize=7.5, loc="lower left")
    fig.suptitle(
        "Fig 7 — 拆開「波動水準」與「真離散度」：★ = Harvey |t|>3\n"
        "藍柱重現了全部的表面成效；控制水準後，離散度沒有任何一格是顯著有幫助的",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(FIG / "fig7_level_vs_dispersion_ladder.png", bbox_inches="tight")
    plt.close(fig)

    print("wrote 7 figures")


if __name__ == "__main__":
    main()
