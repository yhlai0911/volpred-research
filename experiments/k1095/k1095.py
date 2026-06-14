"""K1095: Taiwan Event-Switched VT Strategy

Hypothesis: Combine the strengths of 8.63/VIX (best overall Taiwan VT per K991/
K1094) and A4f-VT (best on event windows per K1062 Part D) by switching between
them based on whether the current date is inside a top-10-constituent earnings
[-5, +5] window.

Strategies:
  A. Pure 8.63/VIX
     w_t = clip(8.63 / VIX_{t-1}, 0.0, 1.5)
  B. Pure A4f-VT
     w_t = clip(target_sigma / A4f_sigma_hat_t, 0.0, 1.5)
     where A4f_sigma_hat_t uses information from t-1 (train up to t-1, one-step
     forecast of sigma^2_t), which is the standard VT convention.
  C. Event-switched
     if in_event_window(t): weight_t = A4f-VT weight
     else: weight_t = 8.63/VIX weight

Lag convention (no lookahead):
  - VIX used is VIX_{t-1} (shifted).
  - A4f forecast for sigma^2_t is fit using returns up to t-1 and VIX up to t-1.
  - Event-window membership uses earnings-announce dates mapped to trading days
    that are known by t-1 (earnings-date file is historical metadata).
  - Strategy weights are shifted by 1 day before multiplying by today's return.

Data:
  - 0050.TW daily close via yfinance, cleaned with volpred.utils.clean_tw50_data
    (K928/K933 requirement).
  - ^VIX daily close via yfinance.
  - 財報公告日.txt for earnings dates (Big5 encoding, same loader as K1062).

Sample period: 2009-01 .. 2025-12 (OOS starts after WINDOW days for A4f).
Transaction cost: 20 bps per one-way trade (whenever weight changes), as in
evaluate_new_strategy.py convention.

Random seed: 42.

Notes from error_log:
  - Lookahead-bias: always shift(1) on signals.
  - 0050.TW: must use clean_tw50_data.
  - Sharpe > 2x baseline => suspect bug.
  - Event window defined on trading-day grid, not calendar days.
  - A4f implementation reused from K1062 (custom MLE, quarterly refit).
"""

from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import optimize, stats

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATA_FILE = PROJECT_ROOT / "財報公告日.txt"
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from volpred.utils import clean_tw50_data  # noqa: E402

warnings.filterwarnings("ignore")

np.random.seed(42)

RESULTS_JSON = SCRIPT_DIR / "k1095_results.json"
TSTAMP = datetime.now(timezone.utc).isoformat()
START_TIME = time.time()

# -----------------------------------------------------------------------------
# Parameters
# -----------------------------------------------------------------------------
K_VIX = 8.63                       # 8.63/VIX constant (K991-validated)
W_MIN, W_MAX = 0.0, 1.5            # weight clip
TARGET_SIGMA_ANNUAL = 0.15         # A4f-VT target annualized sigma
TRADING_DAYS_PER_YEAR = 252
TARGET_SIGMA_DAILY = TARGET_SIGMA_ANNUAL / np.sqrt(TRADING_DAYS_PER_YEAR)
WINDOW = 2000                      # A4f training window
REFIT_EVERY = 63                   # quarterly refit
TX_COST = 0.0020                   # 20 bps one-way (conservative)

START_DATE = "2009-01-01"
END_DATE = "2025-12-31"

# Top 10 constituents of 0050.TW for event-window definition.
# Same 10 stocks as K1060/K1068 (major weight, well-known).
TOP10 = {
    "2330": "TSMC",
    "2454": "MediaTek",
    "2317": "Hon Hai",
    "2308": "Delta",
    "2303": "UMC",
    "2412": "Chunghwa Telecom",
    "2882": "Cathay Holdings",
    "2891": "CTBC Financial",
    "2881": "Fubon Financial",
    "2002": "China Steel",
}

# Event windows to test for sensitivity.
WINDOWS_TO_TEST = [(-3, 3), (-5, 5), (-10, 10)]
BASELINE_WINDOW = (-5, 5)   # "headline" window used for Strategy C.


# -----------------------------------------------------------------------------
# Earnings data loader (same convention as K1062)
# -----------------------------------------------------------------------------
def load_earnings_dates(path: Path) -> pd.DataFrame:
    records = []
    with open(path, "rb") as f:
        raw = f.read()
    try:
        txt = raw.decode("big5", errors="replace")
    except Exception:
        txt = raw.decode("utf-8", errors="replace")
    for line in txt.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        code = parts[0].strip()
        name = parts[1].strip()
        ym = parts[2].strip()
        date_str = parts[3].strip()
        if not date_str:
            continue
        try:
            dt = datetime.strptime(date_str, "%Y/%m/%d")
        except ValueError:
            continue
        records.append(
            {"code": code, "name": name, "ym": ym, "announce_date": dt}
        )
    return pd.DataFrame(records)


print("[Part 0] Loading earnings data ...")
ea_df = load_earnings_dates(DATA_FILE)
print(f"  Total announcement records parsed: {len(ea_df):,}")

top10_df = ea_df[ea_df["code"].isin(TOP10.keys())].copy()
top10_df["announce_date"] = pd.to_datetime(top10_df["announce_date"])
top10_df = top10_df.sort_values("announce_date")
print(f"  Top-10 announcements: {len(top10_df)}")


# -----------------------------------------------------------------------------
# Price / VIX data
# -----------------------------------------------------------------------------
print("[Part 1] Downloading 0050.TW + VIX ...")
tw = yf.download("0050.TW", start=START_DATE, end=END_DATE, auto_adjust=True,
                 progress=False)
vx = yf.download("^VIX", start=START_DATE, end=END_DATE, auto_adjust=True,
                 progress=False)

if isinstance(tw.columns, pd.MultiIndex):
    tw.columns = tw.columns.get_level_values(0)
if isinstance(vx.columns, pd.MultiIndex):
    vx.columns = vx.columns.get_level_values(0)

tw_close = tw["Close"].dropna()
vix_close = vx["Close"].dropna()

# clean_tw50_data: normalize splits
tw_close_clean, tw_ret_clean = clean_tw50_data(tw_close)
# index: make timezone-naive for alignment
tw_close_clean.index = pd.to_datetime(tw_close_clean.index).tz_localize(None)
tw_ret_clean.index = pd.to_datetime(tw_ret_clean.index).tz_localize(None)
vix_close.index = pd.to_datetime(vix_close.index).tz_localize(None)

# Build merged frame on 0050 trading calendar
df = pd.DataFrame({"price": tw_close_clean, "r": tw_ret_clean})
df["VIX"] = vix_close.reindex(df.index).ffill()
df = df.dropna()
print(f"  0050.TW trading days: {len(df)} ({df.index[0].date()} .. {df.index[-1].date()})")


# -----------------------------------------------------------------------------
# Event window membership on trading-day grid
# -----------------------------------------------------------------------------
def map_to_trading_day(announce_dates, trading_idx):
    """Map calendar announce date to first trading day >= announce date
    (Taiwan earnings typically announced after close, so earnings day N
    becomes T+0 trading day = the first trading day >= N+1? We adopt the
    K1062/K1068 convention: T+0 = first trading day >= announce_date, same
    as the published event-study literature for Taiwan)."""
    out_positions = []
    for d in announce_dates:
        d = pd.Timestamp(d).tz_localize(None)
        loc = trading_idx.searchsorted(d, side="left")
        if loc < len(trading_idx):
            out_positions.append(loc)
    return np.array(out_positions)


trading_idx = df.index
t0_positions = map_to_trading_day(top10_df["announce_date"].values, trading_idx)
print(f"  Top-10 events mapped to trading days: {len(t0_positions)}")


def make_event_mask(positions, lower, upper, n_total):
    """Build boolean mask: True on days that are within [lower, upper] of any
    event's T+0 trading-day position."""
    mask = np.zeros(n_total, dtype=bool)
    for pos in positions:
        lo = max(0, pos + lower)
        hi = min(n_total - 1, pos + upper)
        mask[lo:hi + 1] = True
    return mask


event_mask_baseline = make_event_mask(t0_positions, *BASELINE_WINDOW, len(df))
df["is_event"] = event_mask_baseline
print(
    f"  Event days (+-5): {int(event_mask_baseline.sum())} "
    f"({100*event_mask_baseline.mean():.1f}% of sample)"
)

# pre-compute masks for each window to test
event_masks_all = {
    f"{lo:+d}_{hi:+d}": make_event_mask(t0_positions, lo, hi, len(df))
    for (lo, hi) in WINDOWS_TO_TEST
}


# -----------------------------------------------------------------------------
# GJR / A4f model code (custom MLE, reused from K1062)
# -----------------------------------------------------------------------------
def gjr_negll(params, returns):
    omega, alpha, gamma, beta = params
    if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0:
        return 1e10
    if alpha + gamma / 2.0 + beta >= 0.999:
        return 1e10
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns[: min(250, n)])
    ll = 0.0
    for t in range(1, n):
        asym = gamma * returns[t - 1] ** 2 if returns[t - 1] < 0 else 0.0
        h[t] = omega + alpha * returns[t - 1] ** 2 + asym + beta * h[t - 1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(h[t]) + returns[t] ** 2 / h[t])
    return -ll


def fit_a4f(returns, vix_vals):
    n = len(returns)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]

    def neg_ll(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        tau = np.maximum(theta0 + theta1 * vix_lag ** 2, 1e-16)
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10
        eg = omega_g / (1.0 - persist)
        g = np.empty(n)
        g[0] = eg
        for t in range(1, n):
            u_prev = returns[t - 1] / np.sqrt(tau[t])
            asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev ** 2 + asym + beta * g[t - 1]
            if g[t] < 1e-10:
                g[t] = 1e-10
        ll = 0.0
        for t in range(n):
            s2 = tau[t] * g[t]
            if s2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(s2) + returns[t] ** 2 / s2)
        return -ll

    var0 = np.var(returns)
    vix2m = np.mean(vix_lag ** 2) + 1e-8
    best_ll, best = np.inf, None
    starts = [
        [var0 * 0.1,  var0 / vix2m,        0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix2m * 0.5,  0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2,  var0 / vix2m * 1.5,  0.02, 0.08, 0.10, 0.80],
        [var0 * 0.01, var0 / vix2m * 2.0,  0.08, 0.04, 0.06, 0.85],
    ]
    bounds = [
        (-1e-2, 1e-2), (1e-8, 1e-3), (1e-6, 1.0),
        (1e-4, 0.3),   (1e-4, 0.3),  (0.5, 0.999),
    ]
    for s in starts:
        try:
            res = optimize.minimize(
                neg_ll, s, method="L-BFGS-B", bounds=bounds,
                options={"maxiter": 500},
            )
            if res.fun < best_ll:
                best_ll, best = res.fun, res.x
        except Exception:
            continue
    return best


# -----------------------------------------------------------------------------
# Generate one-step-ahead A4f forecast sigma^2_t for each OOS day
# -----------------------------------------------------------------------------
print("[Part 2] Generating A4f one-step forecasts (quarterly refit) ...")
ret = df["r"].values
vix = df["VIX"].values
n_total = len(df)

# OOS = first day with at least WINDOW days of training
oos_start_idx = WINDOW
oos_indices = np.arange(oos_start_idx, n_total)
n_oos = len(oos_indices)
print(f"  OOS: {df.index[oos_start_idx].date()} .. {df.index[-1].date()} (N={n_oos})")

a4f_fc = np.full(n_total, np.nan)
a4f_params = None
a4f_g = None
refit_count = 0

for t_idx, abs_idx in enumerate(oos_indices):
    if t_idx % 500 == 0 and t_idx > 0:
        print(f"    step {t_idx}/{n_oos} (elapsed {time.time()-START_TIME:.0f}s)")
    refit = (t_idx % REFIT_EVERY == 0) or (t_idx == 0)
    if refit:
        refit_count += 1
        train_start = max(0, abs_idx - WINDOW)
        tr_ret = ret[train_start:abs_idx]
        tr_vix = vix[train_start:abs_idx]
        a4f_params = fit_a4f(tr_ret, tr_vix)
        if a4f_params is not None:
            theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = a4f_params
            n_tr = len(tr_ret)
            vix_lag_tr = np.empty(n_tr)
            vix_lag_tr[0] = tr_vix[0]
            vix_lag_tr[1:] = tr_vix[:-1]
            tau_tr = np.maximum(theta0 + theta1 * vix_lag_tr ** 2, 1e-16)
            persist = alpha_p + gamma_p / 2.0 + beta_p
            g = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
            for i in range(1, n_tr):
                u_prev = tr_ret[i - 1] / np.sqrt(tau_tr[i])
                asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
                g = omega_g + alpha_p * u_prev ** 2 + asym + beta_p * g
                g = max(g, 1e-10)
            a4f_g = g

    if a4f_params is not None:
        theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = a4f_params
        v_lag = vix[abs_idx - 1]
        tau_t = max(theta0 + theta1 * v_lag ** 2, 1e-16)
        r_prev = ret[abs_idx - 1]
        u_prev = r_prev / np.sqrt(tau_t)
        asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev ** 2 + asym + beta_p * a4f_g
        g_new = max(g_new, 1e-10)
        a4f_fc[abs_idx] = tau_t * g_new
        a4f_g = g_new

print(f"  Forecasting done: {refit_count} refits in {time.time()-START_TIME:.0f}s")
df["a4f_var"] = a4f_fc
df["a4f_sigma"] = np.sqrt(np.maximum(df["a4f_var"], 1e-10))


# -----------------------------------------------------------------------------
# Signal construction (no lookahead: shift(1))
# -----------------------------------------------------------------------------
# 8.63/VIX weight: uses VIX_{t-1}, then clip. Shift(1) applied after formula.
vix_prev = df["VIX"].shift(1)
w_vix = (K_VIX / vix_prev).clip(W_MIN, W_MAX)

# A4f-VT weight: target_sigma / forecast_sigma_t. The forecast uses info up to
# t-1 (we already use r_{t-1} and vix_{t-1} in the forecast). But as an extra
# safety: evaluate weight on df.index date, and shift(1) is applied when
# computing the strategy return (so weight active on day t uses info from
# t-1). This is equivalent to the standard VT convention.
# To be explicit about lag, we further shift the weight by 1 day.
w_a4f = (TARGET_SIGMA_DAILY / df["a4f_sigma"]).clip(W_MIN, W_MAX)

# Event-switched weight: use 8.63/VIX on non-event, A4f-VT on event-window
# days. Event mask is the baseline (+-5, +-5) window.
is_event = df["is_event"]
w_switch = w_vix.copy()
w_switch[is_event & w_a4f.notna()] = w_a4f[is_event & w_a4f.notna()]

# Build the final DataFrame after A4f becomes available
strategy_start_idx = oos_start_idx
strat_df = pd.DataFrame(index=df.index[strategy_start_idx:])
strat_df["r"] = df["r"].iloc[strategy_start_idx:]
strat_df["is_event"] = df["is_event"].iloc[strategy_start_idx:]
strat_df["VIX"] = df["VIX"].iloc[strategy_start_idx:]
strat_df["a4f_sigma"] = df["a4f_sigma"].iloc[strategy_start_idx:]
strat_df["w_vix_raw"] = w_vix.iloc[strategy_start_idx:]
strat_df["w_a4f_raw"] = w_a4f.iloc[strategy_start_idx:]
strat_df["w_switch_raw"] = w_switch.iloc[strategy_start_idx:]

# Apply the additional shift(1) so that today's weight is strictly a function
# of yesterday's info (belt-and-braces against lookahead).
strat_df["w_vix"] = strat_df["w_vix_raw"].shift(1)
strat_df["w_a4f"] = strat_df["w_a4f_raw"].shift(1)
strat_df["w_switch"] = strat_df["w_switch_raw"].shift(1)
strat_df = strat_df.dropna(subset=["w_vix", "w_a4f", "w_switch", "r"])


# -----------------------------------------------------------------------------
# Build strategy returns with transaction costs
# -----------------------------------------------------------------------------
def strat_return(w: pd.Series, r: pd.Series, tx: float) -> tuple[pd.Series, pd.Series]:
    """Return gross and net (after TX) returns.
    TX applied on abs(delta_w) * tx."""
    gross = w * r
    dw = w.diff().fillna(w.iloc[0]).abs()
    cost = dw * tx
    net = gross - cost
    return gross, net


gA, nA = strat_return(strat_df["w_vix"], strat_df["r"], TX_COST)
gB, nB = strat_return(strat_df["w_a4f"], strat_df["r"], TX_COST)
gC, nC = strat_return(strat_df["w_switch"], strat_df["r"], TX_COST)

strat_df["retA_g"], strat_df["retA_n"] = gA, nA
strat_df["retB_g"], strat_df["retB_n"] = gB, nB
strat_df["retC_g"], strat_df["retC_n"] = gC, nC


# -----------------------------------------------------------------------------
# Metrics
# -----------------------------------------------------------------------------
def metrics(rets: pd.Series, label: str) -> dict:
    rets = rets.dropna()
    if len(rets) < 10:
        return {"label": label, "n": len(rets)}
    mu = rets.mean()
    sd = rets.std(ddof=1)
    ann_ret = (1 + rets).prod() ** (TRADING_DAYS_PER_YEAR / len(rets)) - 1
    ann_sd = sd * np.sqrt(TRADING_DAYS_PER_YEAR)
    sharpe = mu / sd * np.sqrt(TRADING_DAYS_PER_YEAR) if sd > 0 else np.nan
    equity = (1 + rets).cumprod()
    peak = equity.cummax()
    dd = (equity / peak - 1)
    mdd = dd.min()
    calmar = ann_ret / abs(mdd) if mdd < 0 else np.nan
    downside = rets[rets < 0].std(ddof=1)
    sortino = mu / downside * np.sqrt(TRADING_DAYS_PER_YEAR) if downside > 0 else np.nan
    hit = (rets > 0).mean()
    return {
        "label": label,
        "n": int(len(rets)),
        "mean_daily": float(mu),
        "std_daily": float(sd),
        "ann_ret": float(ann_ret),
        "ann_vol": float(ann_sd),
        "sharpe": float(sharpe),
        "mdd": float(mdd),
        "calmar": float(calmar) if not np.isnan(calmar) else None,
        "sortino": float(sortino),
        "hit_rate": float(hit),
    }


mA_g = metrics(strat_df["retA_g"], "Pure 8.63/VIX (gross)")
mA_n = metrics(strat_df["retA_n"], "Pure 8.63/VIX (net TX)")
mB_g = metrics(strat_df["retB_g"], "Pure A4f-VT (gross)")
mB_n = metrics(strat_df["retB_n"], "Pure A4f-VT (net TX)")
mC_g = metrics(strat_df["retC_g"], "Event-switched (gross)")
mC_n = metrics(strat_df["retC_n"], "Event-switched (net TX)")

# buy-and-hold baseline
bh = strat_df["r"]
mBH = metrics(bh, "Buy-and-Hold 0050.TW")


# -----------------------------------------------------------------------------
# Sharpe decomposition: event vs non-event window
# -----------------------------------------------------------------------------
event_sel = strat_df["is_event"]
nonevent_sel = ~strat_df["is_event"]

decomp = {}
for label, rets_col in [
    ("pure_vix_net", "retA_n"),
    ("pure_a4f_net", "retB_n"),
    ("switch_net", "retC_n"),
    ("buy_hold", "r"),
]:
    decomp[label] = {
        "event": metrics(strat_df.loc[event_sel, rets_col], f"{label}_event"),
        "nonevent": metrics(strat_df.loc[nonevent_sel, rets_col], f"{label}_nonevent"),
    }


# -----------------------------------------------------------------------------
# Turnover
# -----------------------------------------------------------------------------
def turnover(w: pd.Series) -> float:
    return float(w.diff().abs().sum() / (len(w) / TRADING_DAYS_PER_YEAR))


turn = {
    "pure_vix": turnover(strat_df["w_vix"]),
    "pure_a4f": turnover(strat_df["w_a4f"]),
    "switch": turnover(strat_df["w_switch"]),
}


# -----------------------------------------------------------------------------
# Window sensitivity: re-run switching strategy with (-3,3), (-5,5), (-10,10)
# -----------------------------------------------------------------------------
window_sens = {}
for (lo, hi) in WINDOWS_TO_TEST:
    key = f"{lo:+d}_{hi:+d}"
    mask_full = event_masks_all[key][strategy_start_idx:]
    mask_series = pd.Series(mask_full, index=df.index[strategy_start_idx:]).reindex(
        strat_df.index
    )
    w_sw_k = strat_df["w_vix_raw"].copy()
    w_sw_k[mask_series & strat_df["w_a4f_raw"].notna()] = strat_df["w_a4f_raw"][
        mask_series & strat_df["w_a4f_raw"].notna()
    ]
    w_sw_k = w_sw_k.shift(1).reindex(strat_df.index)
    g_k, n_k = strat_return(w_sw_k, strat_df["r"], TX_COST)
    m_k = metrics(n_k, f"switch_net_{key}")
    m_k["event_coverage"] = float(mask_series.mean())
    window_sens[key] = m_k


# -----------------------------------------------------------------------------
# HAC t-test on daily return differences: Switched vs Pure 8.63/VIX, Switched vs Pure A4f-VT
# NOTE: 2026-06-14 Codex review (mile_c11a2ced) 指出原 dm_test() 並非 Diebold-Mariano 或
# Harvey-Leybourne-Newbold forecast-comparison test (不比較 forecast loss differentials)，
# 而是日報酬差的 Newey-West HAC t-test。已 rename 並修正 docstring，避免在 README/article
# 過度宣稱 "DM test"。後續若需正式 forecast-comparison 比較請用 dm.dm_test 或 hln_test。
# -----------------------------------------------------------------------------
def hac_diff_return_test(r1: pd.Series, r2: pd.Series) -> dict:
    """HAC t-test on daily return differences (positive t favors r1).
    Newey-West correction for autocorrelation (bandwidth = n^(1/4)).
    NOT a Diebold-Mariano / HLN forecast-comparison test."""
    diff = (r1 - r2).dropna()
    if len(diff) < 10:
        return {"n": len(diff), "t": None, "p": None}
    n = len(diff)
    mean_d = diff.mean()
    # Newey-West with bandwidth n^(1/4)
    bw = max(1, int(n ** 0.25))
    gamma0 = ((diff - mean_d) ** 2).mean()
    var_hac = gamma0
    for k in range(1, bw + 1):
        cov_k = ((diff.iloc[:-k] - mean_d) * (diff.iloc[k:].values - mean_d)).mean()
        var_hac += 2 * (1 - k / (bw + 1)) * cov_k
    if var_hac <= 0:
        var_hac = gamma0
    se = np.sqrt(var_hac / n)
    t_stat = mean_d / se if se > 0 else np.nan
    p_two = 2 * (1 - stats.norm.cdf(abs(t_stat))) if not np.isnan(t_stat) else None
    return {
        "n": int(n),
        "mean_diff": float(mean_d),
        "se": float(se),
        "t": float(t_stat),
        "p_two_sided": float(p_two) if p_two is not None else None,
    }


hac_diff = {
    "switch_vs_vix": hac_diff_return_test(strat_df["retC_n"], strat_df["retA_n"]),
    "switch_vs_a4f": hac_diff_return_test(strat_df["retC_n"], strat_df["retB_n"]),
    "a4f_vs_vix": hac_diff_return_test(strat_df["retB_n"], strat_df["retA_n"]),
}
dm = hac_diff  # backward-compatible alias (results JSON key)


# -----------------------------------------------------------------------------
# Assemble final results
# -----------------------------------------------------------------------------
results = {
    "experiment_id": "K1095",
    "title": "Taiwan Event-Switched VT (8.63/VIX + A4f at earnings events)",
    "timestamp_utc": TSTAMP,
    "runtime_sec": round(time.time() - START_TIME, 1),
    "random_seed": 42,
    "data": {
        "asset": "0050.TW",
        "vix": "^VIX",
        "earnings_file": "財報公告日.txt (Big5)",
        "clean_tw50_data": True,
        "start": str(df.index[0].date()),
        "end": str(df.index[-1].date()),
        "n_trading_days": int(len(df)),
        "n_top10_events": int(len(t0_positions)),
        "event_coverage_baseline": float(event_mask_baseline.mean()),
        "oos_start": str(df.index[oos_start_idx].date()),
        "n_oos": int(n_oos),
        "strategy_n_obs": int(len(strat_df)),
        "top10_constituents": TOP10,
    },
    "parameters": {
        "k_vix": K_VIX,
        "w_min": W_MIN,
        "w_max": W_MAX,
        "target_sigma_annual": TARGET_SIGMA_ANNUAL,
        "window": WINDOW,
        "refit_every": REFIT_EVERY,
        "tx_cost_oneway": TX_COST,
        "baseline_event_window": BASELINE_WINDOW,
    },
    "strategies": {
        "pure_vix_gross": mA_g,
        "pure_vix_net": mA_n,
        "pure_a4f_gross": mB_g,
        "pure_a4f_net": mB_n,
        "switch_gross": mC_g,
        "switch_net": mC_n,
        "buy_hold": mBH,
    },
    "event_nonevent_decomposition": decomp,
    "turnover_annual": turn,
    "window_sensitivity": window_sens,
    "dm_tests": dm,
    "files": {
        "script": "experiments/k1095/k1095.py",
        "results_json": "experiments/k1095/k1095_results.json",
    },
}

with open(RESULTS_JSON, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)
print(f"\n[Saved] {RESULTS_JSON}")


# -----------------------------------------------------------------------------
# Charts
# -----------------------------------------------------------------------------
print("\n[Charts] Drawing ...")

# Chart 1: Strategy comparison (Sharpe / MDD / AnnRet)
fig, ax = plt.subplots(1, 3, figsize=(15, 5))
labels = ["8.63/VIX", "A4f-VT", "Switch", "BH"]
sharpes = [mA_n["sharpe"], mB_n["sharpe"], mC_n["sharpe"], mBH["sharpe"]]
mdds = [mA_n["mdd"], mB_n["mdd"], mC_n["mdd"], mBH["mdd"]]
arets = [mA_n["ann_ret"], mB_n["ann_ret"], mC_n["ann_ret"], mBH["ann_ret"]]
colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#7f7f7f"]
ax[0].bar(labels, sharpes, color=colors); ax[0].set_title("Sharpe (net TX)")
ax[0].axhline(0, color="k", lw=0.5)
for i, v in enumerate(sharpes):
    ax[0].text(i, v, f"{v:.3f}", ha="center", va="bottom")
ax[1].bar(labels, mdds, color=colors); ax[1].set_title("MDD")
for i, v in enumerate(mdds):
    ax[1].text(i, v, f"{v:.1%}", ha="center", va="top")
ax[2].bar(labels, arets, color=colors); ax[2].set_title("Ann. return (net TX)")
for i, v in enumerate(arets):
    ax[2].text(i, v, f"{v:.1%}", ha="center", va="bottom")
plt.suptitle("K1095: Pure VIX vs Pure A4f vs Event-Switched VT (0050.TW)")
plt.tight_layout()
plt.savefig(SCRIPT_DIR / "k1095_strategy_comparison.png", dpi=120, bbox_inches="tight")
plt.close()

# Chart 2: Event vs non-event Sharpe decomposition
fig, ax = plt.subplots(figsize=(10, 5))
keys = ["pure_vix_net", "pure_a4f_net", "switch_net", "buy_hold"]
nice = ["8.63/VIX", "A4f-VT", "Switch", "BH"]
x = np.arange(len(keys))
width = 0.4
ev_sh = [decomp[k]["event"].get("sharpe", 0) or 0 for k in keys]
ne_sh = [decomp[k]["nonevent"].get("sharpe", 0) or 0 for k in keys]
ax.bar(x - width / 2, ev_sh, width, label="Event days (+-5)", color="#d62728")
ax.bar(x + width / 2, ne_sh, width, label="Non-event days", color="#2ca02c")
ax.set_xticks(x); ax.set_xticklabels(nice); ax.set_ylabel("Sharpe (net TX)")
ax.legend(); ax.axhline(0, color="k", lw=0.5)
for i in range(len(keys)):
    ax.text(i - width / 2, ev_sh[i], f"{ev_sh[i]:.2f}", ha="center", va="bottom", fontsize=8)
    ax.text(i + width / 2, ne_sh[i], f"{ne_sh[i]:.2f}", ha="center", va="bottom", fontsize=8)
ax.set_title("K1095: Sharpe decomposition — Event vs Non-event days")
plt.tight_layout()
plt.savefig(SCRIPT_DIR / "k1095_event_nonevent_decomp.png", dpi=120, bbox_inches="tight")
plt.close()

# Chart 3: Window sensitivity (switching strategy under different windows)
fig, ax = plt.subplots(figsize=(8, 5))
keys_sens = [f"{lo:+d}_{hi:+d}" for (lo, hi) in WINDOWS_TO_TEST]
sens_sh = [window_sens[k]["sharpe"] for k in keys_sens]
covs = [window_sens[k]["event_coverage"] for k in keys_sens]
ax.bar(keys_sens, sens_sh, color="#1f77b4")
ax.axhline(mA_n["sharpe"], color="red", ls="--", label=f"Pure VIX Sharpe = {mA_n['sharpe']:.3f}")
ax.axhline(mB_n["sharpe"], color="orange", ls="--", label=f"Pure A4f Sharpe = {mB_n['sharpe']:.3f}")
for i, (v, c) in enumerate(zip(sens_sh, covs)):
    ax.text(i, v, f"{v:.3f}\n(cov={c:.0%})", ha="center", va="bottom")
ax.set_title("K1095: Switching-strategy Sharpe across event-window widths")
ax.set_xlabel("Event window (days relative to earnings announcement)")
ax.set_ylabel("Sharpe (net TX)")
ax.legend()
plt.tight_layout()
plt.savefig(SCRIPT_DIR / "k1095_window_sensitivity.png", dpi=120, bbox_inches="tight")
plt.close()

# Chart 4: Cumulative equity curves
fig, ax = plt.subplots(figsize=(12, 6))
eq = (1 + strat_df[["retA_n", "retB_n", "retC_n", "r"]]).cumprod()
ax.plot(eq.index, eq["retA_n"], label=f"Pure 8.63/VIX (Sharpe={mA_n['sharpe']:.2f})", color="#1f77b4")
ax.plot(eq.index, eq["retB_n"], label=f"Pure A4f-VT (Sharpe={mB_n['sharpe']:.2f})", color="#ff7f0e")
ax.plot(eq.index, eq["retC_n"], label=f"Event-Switched (Sharpe={mC_n['sharpe']:.2f})", color="#2ca02c")
ax.plot(eq.index, eq["r"], label=f"0050.TW BH (Sharpe={mBH['sharpe']:.2f})", color="#7f7f7f", alpha=0.7)
ax.set_yscale("log")
ax.set_title("K1095: Cumulative equity curves (OOS, net of 20 bp TX)")
ax.set_ylabel("Cumulative return (log scale)")
ax.legend(loc="upper left")
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig(SCRIPT_DIR / "k1095_equity_curves.png", dpi=120, bbox_inches="tight")
plt.close()

print(f"\n[Done] Total runtime: {time.time() - START_TIME:.0f}s")
print(f"  Pure 8.63/VIX  Sharpe (net): {mA_n['sharpe']:.4f}")
print(f"  Pure A4f-VT    Sharpe (net): {mB_n['sharpe']:.4f}")
print(f"  Event-Switched Sharpe (net): {mC_n['sharpe']:.4f}")
print(f"  Buy-and-Hold   Sharpe      : {mBH['sharpe']:.4f}")
print(f"  DM switch vs VIX: t={dm['switch_vs_vix']['t']:.2f}, p={dm['switch_vs_vix']['p_two_sided']:.3f}")
print(f"  DM switch vs A4f: t={dm['switch_vs_a4f']['t']:.2f}, p={dm['switch_vs_a4f']['p_two_sided']:.3f}")
