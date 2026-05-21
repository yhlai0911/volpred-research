"""
K1313: HAR-RV Probabilistic Quantile Forecasting vs GARCH-Normal VaR

SPY 2010-2024. Walk-forward OOS 2018-2024 (expanding window, refit every 21 days).
Three models: M1=HAR-OLS+Normal VaR, M2=HAR-QR direct quantile, M3=GARCH(1,1)-Normal.
Evaluation: Kupiec UC, Christoffersen CC, Pinball loss, DM test.

Lookahead verified: all RV predictors shift(1). Seed=42.
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from scipy import stats
from arch import arch_model
from statsmodels.regression.quantile_regression import QuantReg
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant

warnings.filterwarnings("ignore")

np.random.seed(42)

# ─────────────────────────────────────────────────────────────────────────────
# 1. DATA
# ─────────────────────────────────────────────────────────────────────────────

print("Downloading SPY data 2010-2024...")
raw = yf.download("SPY", start="2010-01-01", end="2024-12-31", auto_adjust=True, progress=False)

# Extract Close as 1-D Series (yfinance may return MultiIndex columns)
close = raw["Close"]
if isinstance(close, pd.DataFrame):
    close = close.iloc[:, 0]  # squeeze to Series

# Compute log returns and RV proxy
log_ret = np.log(close / close.shift(1))
rv = log_ret ** 2  # daily squared log return as RV proxy

df = pd.DataFrame({
    "ret": log_ret.values,
    "rv": rv.values,
}, index=raw.index)
df = df.dropna()

assert len(df) >= 2500, f"Need ≥2500 rows, got {len(df)}"
print(f"Total rows: {len(df)}")

# ─────────────────────────────────────────────────────────────────────────────
# 2. HAR PREDICTORS (Lookahead verified: all shift(1))
# ─────────────────────────────────────────────────────────────────────────────

rv_series = df["rv"]
df["rv_d"] = rv_series.shift(1)                   # lag-1: prev day rv
df["rv_w"] = rv_series.shift(1).rolling(5).mean() # lag-1 to lag-5 avg
df["rv_m"] = rv_series.shift(1).rolling(22).mean()# lag-1 to lag-22 avg

df = df.dropna()
print(f"After adding HAR lags (drop NaN): {len(df)} rows")

# OOS period
oos_start = pd.Timestamp("2018-01-01")
oos_mask = df.index >= oos_start
oos_idx = df.index[oos_mask]
assert len(oos_idx) >= 1500, f"Need ≥1500 OOS rows, got {len(oos_idx)}"
print(f"OOS rows: {len(oos_idx)}")

# ─────────────────────────────────────────────────────────────────────────────
# 3. UTILITY FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

TAUS = [0.01, 0.05, 0.10, 0.90, 0.95, 0.99]


def pinball_loss(y, q, tau):
    """Pinball (quantile) loss for scalar τ."""
    y = np.asarray(y, dtype=float)
    q = np.asarray(q, dtype=float)
    err = y - q
    return np.where(err >= 0, tau * err, (tau - 1) * err)


def kupiec_test(returns, var_forecasts, alpha):
    """
    Kupiec Unconditional Coverage (UC) test.
    LR = -2 * [n*log(alpha) + (T-n)*log(1-alpha)
               - n*log(n/T) - (T-n)*log(1-n/T)]
    Under H0: chi2(1). High p-value = model is correctly calibrated.
    """
    returns = np.asarray(returns, dtype=float)
    var_forecasts = np.asarray(var_forecasts, dtype=float)
    T = len(returns)
    hits = (returns < var_forecasts).astype(int)
    n = int(hits.sum())
    actual_cov = n / T

    if n == 0 or n == T:
        return {"stat": None, "p_value": None, "coverage": float(actual_cov),
                "n_violations": n, "T": T}

    # Kupiec LR
    lr = -2.0 * (
        n * np.log(alpha) + (T - n) * np.log(1.0 - alpha)
        - n * np.log(n / T) - (T - n) * np.log(1.0 - n / T)
    )
    p_value = float(1.0 - stats.chi2.cdf(lr, df=1))
    return {
        "stat": float(lr),
        "p_value": p_value,
        "coverage": float(actual_cov),
        "n_violations": n,
        "T": T,
    }


def christoffersen_test(returns, var_forecasts):
    """
    Christoffersen Independence test (CC = UC + Ind).
    Reports the independence component LR_ind ~ chi2(1).
    """
    returns = np.asarray(returns, dtype=float)
    var_forecasts = np.asarray(var_forecasts, dtype=float)
    hits = (returns < var_forecasts).astype(int)
    T = len(hits)
    n = int(hits.sum())
    actual_cov = n / T

    if n == 0 or n == T:
        return {"stat": None, "p_value": None, "coverage": float(actual_cov)}

    # Transition counts
    n00 = int(((hits[:-1] == 0) & (hits[1:] == 0)).sum())
    n01 = int(((hits[:-1] == 0) & (hits[1:] == 1)).sum())
    n10 = int(((hits[:-1] == 1) & (hits[1:] == 0)).sum())
    n11 = int(((hits[:-1] == 1) & (hits[1:] == 1)).sum())

    pi01 = n01 / (n00 + n01) if (n00 + n01) > 0 else 0.0
    pi11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0.0
    pi = n / T

    if (pi01 <= 0 or pi01 >= 1 or pi11 <= 0 or pi11 >= 1
            or pi <= 0 or pi >= 1):
        return {"stat": None, "p_value": None, "coverage": float(actual_cov)}

    with np.errstate(divide="ignore", invalid="ignore"):
        lr_ind = -2.0 * (
            n00 * np.log(1.0 - pi) + n01 * np.log(pi)
            + n10 * np.log(1.0 - pi) + n11 * np.log(pi)
            - n00 * np.log(1.0 - pi01) - n01 * np.log(pi01)
            - n10 * np.log(1.0 - pi11) - n11 * np.log(pi11)
        )

    if not np.isfinite(lr_ind):
        return {"stat": None, "p_value": None, "coverage": float(actual_cov)}

    p_value = float(1.0 - stats.chi2.cdf(lr_ind, df=1))
    return {
        "stat": float(lr_ind),
        "p_value": p_value,
        "coverage": float(actual_cov),
    }


def dm_test_hac(loss1, loss2, lag=10):
    """
    Diebold-Mariano test with HAC (Newey-West) standard error.
    d = loss1 - loss2. Negative t-stat => loss1 < loss2 => model1 better.
    """
    d = np.asarray(loss1, dtype=float) - np.asarray(loss2, dtype=float)
    T = len(d)
    d_bar = float(d.mean())

    # Newey-West HAC variance
    gamma0 = float(np.dot(d - d_bar, d - d_bar) / T)
    hac_var = gamma0
    for ell in range(1, lag + 1):
        w = 1.0 - ell / (lag + 1.0)
        gamma_l = float(np.dot(d[ell:] - d_bar, d[:-ell] - d_bar) / T)
        hac_var += 2.0 * w * gamma_l

    if hac_var <= 0:
        return {"t_stat": None, "p_value": None, "better": "NS"}

    se = np.sqrt(hac_var / T)
    t_stat = d_bar / se
    # Two-sided (large-sample Normal approximation)
    p_value = float(2.0 * (1.0 - stats.norm.cdf(abs(t_stat))))
    better = "NS"
    if p_value < 0.05:
        better = "M2" if t_stat < 0.0 else "M3"  # d = loss_M2 - loss_M3
    return {"t_stat": float(t_stat), "p_value": p_value, "better": better}


# ─────────────────────────────────────────────────────────────────────────────
# 4. WALK-FORWARD OOS (expanding window, refit every 21 trading days)
# ─────────────────────────────────────────────────────────────────────────────

REFIT_FREQ = 21  # refit every 21 trading days

# OOS storage
var_m1_5 = []
var_m1_1 = []
var_m2 = {tau: [] for tau in TAUS}
var_m3_5 = []
var_m3_1 = []
oos_returns = []

z_05 = float(stats.norm.ppf(0.05))  # ≈ -1.6449
z_01 = float(stats.norm.ppf(0.01))  # ≈ -2.3263

oos_dates = df.index[oos_mask]
n_oos = len(oos_dates)
n_refits = 0

print(f"\nRunning walk-forward OOS ({n_oos} days, refit every {REFIT_FREQ} days)...")

refit_positions = list(range(0, n_oos, REFIT_FREQ))

for batch_start in refit_positions:
    batch_end = min(batch_start + REFIT_FREQ, n_oos)
    t_fit_end = oos_dates[batch_start]  # IS ends strictly before this date

    # IS data: all rows before t_fit_end
    is_mask = df.index < t_fit_end
    df_is = df[is_mask].copy()

    # ── M1: HAR-OLS on log(rv) ─────────────────────────────────────────────
    log_rv_is = np.log(df_is["rv"].clip(lower=1e-12))
    log_rv_d_is = np.log(df_is["rv_d"].clip(lower=1e-12))
    log_rv_w_is = np.log(df_is["rv_w"].clip(lower=1e-12))
    log_rv_m_is = np.log(df_is["rv_m"].clip(lower=1e-12))

    X_ols = add_constant(
        pd.DataFrame({"rv_d": log_rv_d_is, "rv_w": log_rv_w_is, "rv_m": log_rv_m_is},
                     index=df_is.index)
    )
    m1_fit = OLS(log_rv_is, X_ols).fit()
    m1_coefs = m1_fit.params.values  # numpy array [const, rv_d, rv_w, rv_m]

    # ── M2: HAR-QR on raw returns ───────────────────────────────────────────
    ret_is = df_is["ret"].values
    X_qr = add_constant(
        pd.DataFrame({
            "sv_d": np.sqrt(df_is["rv_d"].clip(lower=0)),
            "sv_w": np.sqrt(df_is["rv_w"].clip(lower=0)),
            "sv_m": np.sqrt(df_is["rv_m"].clip(lower=0)),
        }, index=df_is.index)
    )
    m2_fits = {}
    for tau in TAUS:
        qr_fit = QuantReg(ret_is, X_qr).fit(q=tau, max_iter=2000)
        m2_fits[tau] = qr_fit.params  # [const, sv_d, sv_w, sv_m]

    # ── M3: GARCH(1,1)-Normal ───────────────────────────────────────────────
    ret_is_pct = df_is["ret"].values * 100.0  # arch convention: percentage scale
    garch_fit = None
    for method in ["SLSQP", "L-BFGS-B"]:
        try:
            garch_fit = arch_model(
                ret_is_pct, vol="GARCH", p=1, q=1, dist="Normal", rescale=False
            ).fit(disp="off", options={"maxiter": 1000})
            break
        except Exception:
            continue

    # Get batch-level one-step-ahead GARCH sigma forecast
    if garch_fit is not None:
        try:
            fc = garch_fit.forecast(horizon=1, reindex=False)
            sigma_garch_batch = float(np.sqrt(fc.variance.values[-1, 0])) / 100.0
        except Exception:
            sigma_garch_batch = float(garch_fit.conditional_volatility.iloc[-1]) / 100.0
    else:
        # Emergency fallback: rolling IS std
        sigma_garch_batch = float(df_is["ret"].std())

    n_refits += 1

    # ── OOS predictions for this batch ─────────────────────────────────────
    for i in range(batch_start, batch_end):
        t = oos_dates[i]
        row = df.loc[t]

        actual_ret = float(row["ret"])
        oos_returns.append(actual_ret)

        # M1: log(RV) OLS → exp(log_rv_pred/2) = predicted σ
        x_new_log = np.array([
            1.0,
            float(np.log(max(float(row["rv_d"]), 1e-12))),
            float(np.log(max(float(row["rv_w"]), 1e-12))),
            float(np.log(max(float(row["rv_m"]), 1e-12))),
        ])
        log_rv_pred = float(x_new_log @ m1_coefs)
        sigma_m1 = float(np.exp(log_rv_pred / 2.0))
        var_m1_5.append(z_05 * sigma_m1)
        var_m1_1.append(z_01 * sigma_m1)

        # M2: quantile regression directly on returns
        x_new_qr = np.array([
            1.0,
            float(np.sqrt(max(float(row["rv_d"]), 0.0))),
            float(np.sqrt(max(float(row["rv_w"]), 0.0))),
            float(np.sqrt(max(float(row["rv_m"]), 0.0))),
        ])
        for tau in TAUS:
            q_pred = float(x_new_qr @ m2_fits[tau])
            var_m2[tau].append(q_pred)

        # M3: GARCH batch forecast (same sigma for all 21 days in batch)
        var_m3_5.append(z_05 * sigma_garch_batch)
        var_m3_1.append(z_01 * sigma_garch_batch)

    if batch_start % (REFIT_FREQ * 5) == 0:
        pct_done = 100.0 * batch_start / n_oos
        print(f"  {pct_done:.0f}% done ({batch_start}/{n_oos})")

print(f"Walk-forward complete. Refits: {n_refits}, OOS points: {len(oos_returns)}")

# ─────────────────────────────────────────────────────────────────────────────
# 5. EVALUATION
# ─────────────────────────────────────────────────────────────────────────────

oos_ret_arr = np.array(oos_returns, dtype=float)
var_m1_5_arr = np.array(var_m1_5, dtype=float)
var_m1_1_arr = np.array(var_m1_1, dtype=float)
var_m3_5_arr = np.array(var_m3_5, dtype=float)
var_m3_1_arr = np.array(var_m3_1, dtype=float)
var_m2_05_arr = np.array(var_m2[0.05], dtype=float)
var_m2_01_arr = np.array(var_m2[0.01], dtype=float)

print(f"\nEvaluating models on {len(oos_ret_arr)} OOS observations...")

# ── M1 ────────────────────────────────────────────────────────────────────────
m1_kupiec_5 = kupiec_test(oos_ret_arr, var_m1_5_arr, alpha=0.05)
m1_kupiec_1 = kupiec_test(oos_ret_arr, var_m1_1_arr, alpha=0.01)
m1_cc = christoffersen_test(oos_ret_arr, var_m1_5_arr)
print(f"M1 UC@5%: coverage={m1_kupiec_5['coverage']:.4f}, "
      f"p={m1_kupiec_5['p_value'] if m1_kupiec_5['p_value'] is not None else 'NA'}")
print(f"M1 UC@1%: coverage={m1_kupiec_1['coverage']:.4f}, "
      f"p={m1_kupiec_1['p_value'] if m1_kupiec_1['p_value'] is not None else 'NA'}")

# ── M2 ────────────────────────────────────────────────────────────────────────
m2_kupiec_5 = kupiec_test(oos_ret_arr, var_m2_05_arr, alpha=0.05)
m2_kupiec_1 = kupiec_test(oos_ret_arr, var_m2_01_arr, alpha=0.01)
m2_cc = christoffersen_test(oos_ret_arr, var_m2_05_arr)

# Pinball losses
pinball_by_tau = {}
for tau in TAUS:
    q_arr = np.array(var_m2[tau], dtype=float)
    pb = pinball_loss(oos_ret_arr, q_arr, tau)
    pinball_by_tau[str(tau)] = float(np.mean(pb))
pinball_mean = float(np.mean(list(pinball_by_tau.values())))

print(f"M2 UC@5%: coverage={m2_kupiec_5['coverage']:.4f}, "
      f"p={m2_kupiec_5['p_value'] if m2_kupiec_5['p_value'] is not None else 'NA'}")
print(f"M2 UC@1%: coverage={m2_kupiec_1['coverage']:.4f}, "
      f"p={m2_kupiec_1['p_value'] if m2_kupiec_1['p_value'] is not None else 'NA'}")
print(f"M2 Pinball mean: {pinball_mean:.6f}")

# ── M3 ────────────────────────────────────────────────────────────────────────
m3_kupiec_5 = kupiec_test(oos_ret_arr, var_m3_5_arr, alpha=0.05)
m3_kupiec_1 = kupiec_test(oos_ret_arr, var_m3_1_arr, alpha=0.01)
m3_cc = christoffersen_test(oos_ret_arr, var_m3_5_arr)
print(f"M3 UC@5%: coverage={m3_kupiec_5['coverage']:.4f}, "
      f"p={m3_kupiec_5['p_value'] if m3_kupiec_5['p_value'] is not None else 'NA'}")
print(f"M3 UC@1%: coverage={m3_kupiec_1['coverage']:.4f}, "
      f"p={m3_kupiec_1['p_value'] if m3_kupiec_1['p_value'] is not None else 'NA'}")

# ── DM tests ──────────────────────────────────────────────────────────────────
pb_m2_05 = pinball_loss(oos_ret_arr, var_m2_05_arr, 0.05)
pb_m3_05 = pinball_loss(oos_ret_arr, var_m3_5_arr, 0.05)
dm_05 = dm_test_hac(pb_m2_05, pb_m3_05, lag=10)

pb_m2_01 = pinball_loss(oos_ret_arr, var_m2_01_arr, 0.01)
pb_m3_01 = pinball_loss(oos_ret_arr, var_m3_1_arr, 0.01)
dm_01 = dm_test_hac(pb_m2_01, pb_m3_01, lag=10)

print(f"\nDM @5%: t={dm_05['t_stat']}, p={dm_05['p_value']:.4f}, better={dm_05['better']}")
print(f"DM @1%: t={dm_01['t_stat']}, p={dm_01['p_value']:.4f}, better={dm_01['better']}")

# ─────────────────────────────────────────────────────────────────────────────
# 6. VERDICT
# ─────────────────────────────────────────────────────────────────────────────

m2_uc5_pass = (m2_kupiec_5["p_value"] is not None and m2_kupiec_5["p_value"] > 0.05)
dm05_sig = (dm_05["p_value"] is not None and dm_05["p_value"] < 0.05)
dm05_m2_better = (dm_05["better"] == "M2")

if m2_uc5_pass and dm05_sig and dm05_m2_better:
    verdict = "PASS"
elif m2_uc5_pass and not dm05_sig:
    verdict = "CONDITIONAL_PASS"
elif dm05_sig and dm05_m2_better and not m2_uc5_pass:
    verdict = "MIXED"
elif m2_uc5_pass and dm05_sig and not dm05_m2_better:
    verdict = "MIXED"
else:
    verdict = "NULL"

print(f"\nVerdict: {verdict}")

# ─────────────────────────────────────────────────────────────────────────────
# 7. CONCLUSION
# ─────────────────────────────────────────────────────────────────────────────

pv5 = f"{m2_kupiec_5['p_value']:.4f}" if m2_kupiec_5['p_value'] is not None else "NA"
pv5_m3 = f"{m3_kupiec_5['p_value']:.4f}" if m3_kupiec_5['p_value'] is not None else "NA"
dm_pv = f"{dm_05['p_value']:.4f}" if dm_05['p_value'] is not None else "NA"
dm_ts = f"{dm_05['t_stat']:.4f}" if dm_05['t_stat'] is not None else "NA"

conclusion = (
    f"HAR-QR achieves {m2_kupiec_5['coverage']:.4f} 5%-VaR coverage (target 0.05, "
    f"Kupiec p={pv5}) vs GARCH-Normal {m3_kupiec_5['coverage']:.4f} "
    f"(Kupiec p={pv5_m3}). "
    f"DM test at tau=0.05: t={dm_ts}, p={dm_pv} "
    f"(better={dm_05['better']}). Mean pinball loss={pinball_mean:.6f}."
)
print(f"Conclusion: {conclusion}")

# ─────────────────────────────────────────────────────────────────────────────
# 8. RESULTS JSON
# ─────────────────────────────────────────────────────────────────────────────

results = {
    "experiment_id": "K1313",
    "timestamp": datetime.utcnow().isoformat() + "Z",
    "data": {
        "asset": "SPY",
        "period": "2010-01-01/2024-12-31",
        "oos_period": "2018-01-01/2024-12-31",
        "n_oos": int(len(oos_ret_arr)),
        "n_refits": int(n_refits),
    },
    "models": {
        "M1_HAR_OLS": {
            "kupiec_5pct": m1_kupiec_5,
            "kupiec_1pct": m1_kupiec_1,
            "cc_test": m1_cc,
        },
        "M2_HAR_QR": {
            "kupiec_5pct": m2_kupiec_5,
            "kupiec_1pct": m2_kupiec_1,
            "cc_test": m2_cc,
            "pinball_loss_by_tau": pinball_by_tau,
            "pinball_mean": pinball_mean,
        },
        "M3_GARCH_Normal": {
            "kupiec_5pct": m3_kupiec_5,
            "kupiec_1pct": m3_kupiec_1,
            "cc_test": m3_cc,
        },
    },
    "dm_test": {
        "M2_vs_M3_tau05": dm_05,
        "M2_vs_M3_tau01": dm_01,
    },
    "verdict": verdict,
    "conclusion": conclusion,
    "lookahead_verified": True,
    "seed": 42,
}

import os
out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "K1313_results.json")
with open(out_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved to {out_path}")
print(f"Final verdict: {verdict}")
