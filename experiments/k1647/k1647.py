"""
K1647: Oil realized-volatility spillover to equity realized volatility
       (CL=F / USO  ->  SPY / XLE), bidirectional, VIX-controlled.

Research question
-----------------
Does a shock to CRUDE OIL's *realized volatility* lead / transmit to the
*realized volatility* of the broad equity market (SPY) and of energy-sector
equities (XLE)? This is a VOL-LEVEL (RV -> RV) spillover question, NOT a
price-return question. We test both directions (oil vol -> equity vol and
equity vol -> oil vol) and ask whether any oil->equity vol linkage survives
controlling for VIX.

Differentiation vs prior K
--------------------------
- K422 (Commodity Vol Spillover Network): CL=F -> ES=F (SPX futures). Found
  Oil->SPX Granger p<1e-4 but Oil->equity vol NS after VIX control (partial r).
  K422 did NOT test XLE (energy-sector equity) and did NOT compare CL=F vs USO.
- Diebold-Yilmaz 9-asset study: USO included but "most isolated (TO=1.9%)";
  no XLE, no oil-focused directional test.
- K1439: USO only as a bucket in a USD-regime study (different question).
K1647's novel contribution: (a) XLE energy-sector equity as a target that is
DIRECTLY oil-exposed (should show stronger linkage than broad SPY if any real
transmission exists); (b) explicit CL=F (futures) vs USO (ETF) dual oil proxy;
(c) bidirectional net spillover via generalized (order-invariant) FEVD.

Method
------
Data: yfinance daily OHLC, 2010-01-01 .. today. Assets: CL=F, USO, SPY, XLE, ^VIX.
Vol proxy:
  - RV21: 21-day rolling std of daily log returns, annualized (sqrt(252)).
  - Parkinson range vol (robustness): from daily High/Low.
  We analyse log(vol) (right-skewed -> log for near-stationarity/normality).
Lag / lookahead policy (HIGHEST-PRIORITY RISK):
  - Core test = one-step PREDICTIVE regression:
        eq_logRV[t] = a + b*oil_logRV[t-1] + c*eq_logRV[t-1] (+ d*VIX_logRV[t-1]) + e
    Predictor is EXPLICITLY .shift(1) -> uses only info known at t-1 to predict t.
    b>0 & significant (HAC/Newey-West) => oil vol leads equity vol.
  - Reverse regression symmetric: oil_logRV[t] on eq_logRV[t-1].
  - Granger F-tests (statsmodels, uses internal lags) as supporting evidence.
  - Diebold-Yilmaz spillover index on the VAR of log-RV series (VAR uses lags
    by construction; DY is inherently a lagged/dynamic decomposition).
Inference:
  - HAC (Newey-West) standard errors on all predictive regressions
    (vol series are strongly autocorrelated -> plain OLS SE too optimistic).
  - SPY and XLE analysed SEPARATELY (two regressions), NEVER pooled as
    asset-day iid (K1355 lesson: same-day cross-asset shocks share market
    factor -> pooling understates SE).
  - seed=42 for the stationary bootstrap CI on b.

Outputs: experiments/k1647/k1647_results.json + figures.
"""
import json
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import statsmodels.api as sm
from statsmodels.tsa.stattools import grangercausalitytests, adfuller
from statsmodels.tsa.api import VAR

warnings.filterwarnings("ignore")
SEED = 42
np.random.seed(SEED)

START = "2010-01-01"
RV_WINDOW = 21
ANN = np.sqrt(252.0)
HAC_LAGS = 21  # = RV_WINDOW: overlapping 21d RV windows induce ~MA(20) residuals -> HAC must span the window
DY_HORIZON = 10
GRANGER_MAXLAG = 5

TICKERS = {"CL": "CL=F", "USO": "USO", "SPY": "SPY", "XLE": "XLE", "VIX": "^VIX"}

print("=" * 78)
print("K1647: Oil RV spillover to equity RV (CL=F/USO -> SPY/XLE)")
print("=" * 78)

# ---------------------------------------------------------------- data
raw = {}
for name, t in TICKERS.items():
    df = yf.download(t, start=START, progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw[name] = df[["High", "Low", "Close"]].dropna()
    print(f"  {name:4s} ({t:5s}): {len(raw[name])} rows "
          f"{raw[name].index.min().date()}..{raw[name].index.max().date()}")

# CL=F 2020-04-20 negative settle -> log return undefined. Flag & drop nonpositive Close.
cl_nonpos = int((raw["CL"]["Close"] <= 0).sum())
print(f"\n  CL=F non-positive Close rows (2020 negative-oil artifact): {cl_nonpos} "
      f"-> dropped for log-return vol (documented, not imputed)")
for name in raw:
    raw[name] = raw[name][raw[name]["Close"] > 0]


def realized_vol(df):
    """21d rolling std of daily log close-to-close returns, annualized."""
    r = np.log(df["Close"]).diff()
    return r.rolling(RV_WINDOW).std() * ANN


def parkinson_vol(df):
    """Parkinson range vol (annualized), 21d rolling mean of daily range variance."""
    hl = np.log(df["High"] / df["Low"]) ** 2
    daily_var = hl / (4.0 * np.log(2.0))
    return np.sqrt(daily_var.rolling(RV_WINDOW).mean()) * ANN


rv = pd.DataFrame({k: realized_vol(v) for k, v in raw.items()})
pk = pd.DataFrame({k: parkinson_vol(v) for k, v in raw.items()})

# log-vol, align, drop warmup
logrv = np.log(rv).replace([np.inf, -np.inf], np.nan).dropna()
logpk = np.log(pk).replace([np.inf, -np.inf], np.nan).dropna()
common = logrv.index.intersection(logpk.index)
logrv = logrv.loc[common]
logpk = logpk.loc[common]
N = len(logrv)
period = f"{common.min().date()}..{common.max().date()}"
print(f"\n  Aligned log-RV panel: N={N} trading days, {period}")

results = {
    "experiment": "K1647",
    "title": "Oil RV spillover to equity RV (CL=F/USO -> SPY/XLE), bidirectional, VIX-controlled",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "seed": SEED,
    "data": {
        "source": "yfinance daily OHLC",
        "tickers": TICKERS,
        "period": period,
        "n_days": N,
        "rv_window": RV_WINDOW,
        "vol_proxy": "log(21d rolling std of daily log returns, annualized)",
        "cl_negative_oil_rows_dropped": cl_nonpos,
        "lag_policy": "predictor .shift(1); one-step predictive regression",
        "inference": "Newey-West HAC (lags=%d); SPY/XLE analysed separately (no asset-day pooling)" % HAC_LAGS,
    },
}

# ---------------------------------------------------------------- stationarity
adf = {}
for c in logrv.columns:
    stat, p = adfuller(logrv[c].values, autolag="AIC")[:2]
    adf[c] = {"adf_stat": float(stat), "p_value": float(p),
              "stationary_5pct": bool(p < 0.05)}
results["adf_log_rv"] = adf
print("\n  ADF (log-RV):", {k: round(v["p_value"], 4) for k, v in adf.items()})

# contemporaneous corr
results["contemp_logrv_corr"] = {
    f"{a}-{b}": float(logrv[a].corr(logrv[b]))
    for a, b in [("CL", "SPY"), ("CL", "XLE"), ("USO", "SPY"), ("USO", "XLE"),
                 ("CL", "USO"), ("SPY", "XLE")]
}


# ------------------------------------------------ one-step predictive regression
def stationary_bootstrap_b(y, X_cols_df, b_idx, n_boot=1000, mean_block=20, seed=SEED):
    """Politis-Romano stationary bootstrap CI for coefficient b_idx."""
    rng = np.random.default_rng(seed)
    n = len(y)
    Xy = np.column_stack([X_cols_df.values, y.values])
    p = 1.0 / mean_block
    bs = []
    kcol = X_cols_df.shape[1]
    for _ in range(n_boot):
        idx = np.empty(n, dtype=int)
        i = 0
        while i < n:
            start = rng.integers(0, n)
            L = rng.geometric(p)
            for j in range(L):
                if i >= n:
                    break
                idx[i] = (start + j) % n
                i += 1
        samp = Xy[idx]
        Xb = np.column_stack([np.ones(n), samp[:, :kcol]])
        yb = samp[:, kcol]
        try:
            beta = np.linalg.lstsq(Xb, yb, rcond=None)[0]
            bs.append(beta[b_idx + 1])  # +1 for const
        except Exception:
            pass
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return float(lo), float(hi)


def predictive_reg(target, oil, control_vix=False, data=logrv):
    """target_logRV[t] ~ oil_logRV[t-1] + target_logRV[t-1] (+ VIX_logRV[t-1]).
    Returns HAC inference on the oil (spillover) coefficient b."""
    y = data[target]
    Xd = {
        f"{oil}_lag1": data[oil].shift(1),          # <-- explicit shift(1): oil vol at t-1
        f"{target}_lag1": data[target].shift(1),     # own-vol AR(1) control
    }
    if control_vix:
        Xd["VIX_lag1"] = data["VIX"].shift(1)
    X = pd.DataFrame(Xd)
    d = pd.concat([y.rename("y"), X], axis=1).dropna()
    Xc = sm.add_constant(d[list(Xd.keys())])
    m = sm.OLS(d["y"], Xc).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
    b_name = f"{oil}_lag1"
    b = float(m.params[b_name])
    se = float(m.bse[b_name])
    tval = float(m.tvalues[b_name])
    pval = float(m.pvalues[b_name])
    lo, hi = stationary_bootstrap_b(d["y"], d[list(Xd.keys())],
                                    b_idx=list(Xd.keys()).index(b_name))
    return {
        "coef_oil_lag1": b, "hac_se": se, "hac_t": tval, "hac_p": pval,
        "boot_ci95": [lo, hi], "boot_sig": bool(lo * hi > 0),
        "n_obs": int(m.nobs), "r2": float(m.rsquared),
        "sig_5pct": bool(pval < 0.05),
    }


print("\n  --- One-step predictive regressions (oil_logRV[t-1] -> equity_logRV[t]) ---")
pred = {"oil_to_equity": {}, "equity_to_oil": {}}
for oil in ["CL", "USO"]:
    for eq in ["SPY", "XLE"]:
        base = predictive_reg(eq, oil, control_vix=False)
        vix = predictive_reg(eq, oil, control_vix=True)
        pred["oil_to_equity"][f"{oil}->{eq}"] = {"no_control": base, "vix_controlled": vix}
        print(f"    {oil}->{eq}: b={base['coef_oil_lag1']:+.4f} "
              f"HAC-t={base['hac_t']:+.2f} p={base['hac_p']:.4f} "
              f"| +VIX: b={vix['coef_oil_lag1']:+.4f} p={vix['hac_p']:.4f}")

# reverse: equity vol -> oil vol
for eq in ["SPY", "XLE"]:
    for oil in ["CL", "USO"]:
        rev = predictive_reg(oil, eq, control_vix=False)
        pred["equity_to_oil"][f"{eq}->{oil}"] = rev
        print(f"    {eq}->{oil}: b={rev['coef_oil_lag1']:+.4f} "
              f"HAC-t={rev['hac_t']:+.2f} p={rev['hac_p']:.4f}")
results["predictive_regressions"] = pred


# ---------------------------------------------------------------- Granger
def granger_minp(cause, effect, data=logrv):
    """Min p across lags 1..GRANGER_MAXLAG. data[[effect, cause]] order per statsmodels."""
    sub = data[[effect, cause]].dropna()
    res = grangercausalitytests(sub.values, maxlag=GRANGER_MAXLAG, verbose=False)
    # statsmodels can return numpy int64 lag keys -> coerce to python int for JSON
    ps = {int(lag): float(res[lag][0]["ssr_ftest"][1]) for lag in res}
    best = min(ps, key=ps.get)
    return {"min_p": ps[best], "best_lag": int(best), "p_by_lag": ps}


granger = {}
for oil in ["CL", "USO"]:
    for eq in ["SPY", "XLE"]:
        granger[f"{oil}->{eq}"] = granger_minp(oil, eq)
        granger[f"{eq}->{oil}"] = granger_minp(eq, oil)
results["granger"] = granger
print("\n  --- Granger min-p ---")
for k, v in granger.items():
    print(f"    {k}: min_p={v['min_p']:.4f} (lag {v['best_lag']})")


# ------------------------------------------------ Diebold-Yilmaz generalized FEVD
def diebold_yilmaz(data, order, horizon=DY_HORIZON, maxlag_var=5):
    """Generalized (order-invariant, KPPS/Pesaran-Shin) FEVD spillover table."""
    d = data[order].dropna()
    var = VAR(d.values)
    lag = var.select_order(maxlags=maxlag_var).aic
    lag = max(1, int(lag))
    fit = var.fit(lag)
    Sigma = fit.sigma_u
    A = fit.ma_rep(maxn=horizon)  # (horizon+1, k, k)
    k = d.shape[1]
    theta = np.zeros((k, k))
    for i in range(k):
        ei = np.zeros(k); ei[i] = 1.0
        denom = 0.0
        for h in range(horizon + 1):
            denom += (ei @ A[h] @ Sigma @ A[h].T @ ei)
        for j in range(k):
            ej = np.zeros(k); ej[j] = 1.0
            sigjj = Sigma[j, j]
            num = 0.0
            for h in range(horizon + 1):
                num += (ei @ A[h] @ Sigma @ ej) ** 2
            theta[i, j] = (num / sigjj) / denom
    # row-normalize
    theta_n = theta / theta.sum(axis=1, keepdims=True)
    total = 100.0 * (theta_n.sum() - np.trace(theta_n)) / k
    to_others = 100.0 * (theta_n.sum(axis=0) - np.diag(theta_n)) / k   # col sum ex-diag
    from_others = 100.0 * (theta_n.sum(axis=1) - np.diag(theta_n)) / k  # row sum ex-diag
    net = to_others - from_others
    return {
        "order": order, "var_lag": lag, "horizon": horizon,
        "total_spillover_pct": float(total),
        "to_others_pct": {order[i]: float(to_others[i]) for i in range(k)},
        "from_others_pct": {order[i]: float(from_others[i]) for i in range(k)},
        "net_pct": {order[i]: float(net[i]) for i in range(k)},
        "fevd_table": {order[i]: {order[j]: float(theta_n[i, j]) for j in range(k)}
                       for i in range(k)},
    }


dy_order = ["CL", "USO", "SPY", "XLE"]
dy = diebold_yilmaz(logrv, dy_order)
results["diebold_yilmaz"] = dy
print("\n  --- Diebold-Yilmaz (log-RV, generalized FEVD) ---")
print(f"    Total spillover index: {dy['total_spillover_pct']:.1f}%  (VAR lag {dy['var_lag']})")
print(f"    Net spillover: " + ", ".join(
    f"{a}={dy['net_pct'][a]:+.1f}%" for a in dy_order))

# directional oil->equity share (from FEVD): how much of SPY/XLE FEV comes from oil
oil_to_eq_share = {
    eq: {oil: 100.0 * dy["fevd_table"][eq][oil] for oil in ["CL", "USO"]}
    for eq in ["SPY", "XLE"]
}
results["diebold_yilmaz"]["oil_to_equity_fev_share_pct"] = oil_to_eq_share
print("    Oil share of equity FEV: " + ", ".join(
    f"{oil}->{eq}={oil_to_eq_share[eq][oil]:.1f}%"
    for eq in ["SPY", "XLE"] for oil in ["CL", "USO"]))

# ---------------------------------------------------------------- Parkinson robustness
pk_pred = {}
for oil in ["CL", "USO"]:
    for eq in ["SPY", "XLE"]:
        pk_pred[f"{oil}->{eq}"] = predictive_reg(eq, oil, control_vix=False, data=logpk)
results["parkinson_robustness"] = {
    "note": "Parkinson range-vol proxy, same one-step predictive spec",
    "oil_to_equity": pk_pred,
}
print("\n  --- Parkinson robustness (oil->equity, b/HAC-p) ---")
for k, v in pk_pred.items():
    print(f"    {k}: b={v['coef_oil_lag1']:+.4f} p={v['hac_p']:.4f}")

# ---------------------------------------------------------------- verdict logic
def sig(d):
    return d["sig_5pct"] and d["boot_sig"]


oil_eq_sig_raw = {k: sig(v["no_control"]) for k, v in pred["oil_to_equity"].items()}
oil_eq_sig_vix = {k: sig(v["vix_controlled"]) for k, v in pred["oil_to_equity"].items()}
eq_oil_sig = {k: sig(v) for k, v in pred["equity_to_oil"].items()}

verdict = {
    "oil_to_equity_sig_before_vix": oil_eq_sig_raw,
    "oil_to_equity_sig_after_vix": oil_eq_sig_vix,
    "equity_to_oil_sig": eq_oil_sig,
    "any_oil_to_equity_survives_vix": any(oil_eq_sig_vix.values()),
    "dominant_direction": "oil->equity" if (
        sum(oil_eq_sig_raw.values()) > sum(eq_oil_sig.values())) else (
        "equity->oil" if sum(eq_oil_sig.values()) > sum(oil_eq_sig_raw.values())
        else "symmetric_or_null"),
}
results["verdict"] = verdict
print("\n  --- VERDICT ---")
print(f"    oil->equity sig (raw): {oil_eq_sig_raw}")
print(f"    oil->equity sig (after VIX control): {oil_eq_sig_vix}")
print(f"    equity->oil sig: {eq_oil_sig}")
print(f"    any oil->equity survives VIX: {verdict['any_oil_to_equity_survives_vix']}")
print(f"    dominant direction: {verdict['dominant_direction']}")

# ---------------------------------------------------------------- save + figures
with open("experiments/k1647/k1647_results.json", "w") as f:
    json.dump(results, f, indent=2)
print("\n  Saved experiments/k1647/k1647_results.json")

# figures
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# fig1: log-RV series
fig, ax = plt.subplots(figsize=(12, 5))
for c, col in zip(["CL", "USO", "SPY", "XLE"],
                  ["#c0392b", "#e67e22", "#2c3e50", "#27ae60"]):
    ax.plot(logrv.index, logrv[c], label=c, lw=0.8, color=col, alpha=0.85)
ax.set_title(f"Log realized volatility (21d), {period}")
ax.set_ylabel("log annualized RV"); ax.legend(ncol=4); ax.grid(alpha=0.3)
fig.tight_layout(); fig.savefig("experiments/k1647/fig_logrv_series.png", dpi=110)
plt.close(fig)

# fig2: net spillover bar
fig, ax = plt.subplots(figsize=(7, 4.5))
nets = [dy["net_pct"][a] for a in dy_order]
colors = ["#27ae60" if n > 0 else "#c0392b" for n in nets]
ax.bar(dy_order, nets, color=colors)
ax.axhline(0, color="k", lw=0.8)
ax.set_title(f"Diebold-Yilmaz NET vol spillover (total={dy['total_spillover_pct']:.0f}%)")
ax.set_ylabel("net = to - from (%)"); ax.grid(alpha=0.3, axis="y")
fig.tight_layout(); fig.savefig("experiments/k1647/fig_net_spillover.png", dpi=110)
plt.close(fig)

# fig3: oil->equity coefficient dot plot (raw vs vix-controlled)
fig, ax = plt.subplots(figsize=(8, 4.5))
labels = list(pred["oil_to_equity"].keys())
xs = np.arange(len(labels))
raw_b = [pred["oil_to_equity"][k]["no_control"]["coef_oil_lag1"] for k in labels]
raw_ci = [pred["oil_to_equity"][k]["no_control"]["boot_ci95"] for k in labels]
vix_b = [pred["oil_to_equity"][k]["vix_controlled"]["coef_oil_lag1"] for k in labels]
vix_ci = [pred["oil_to_equity"][k]["vix_controlled"]["boot_ci95"] for k in labels]
for i, (b, ci) in enumerate(zip(raw_b, raw_ci)):
    ax.errorbar(i - 0.12, b, yerr=[[b - ci[0]], [ci[1] - b]], fmt="o",
                color="#2980b9", capsize=3, label="no control" if i == 0 else "")
for i, (b, ci) in enumerate(zip(vix_b, vix_ci)):
    ax.errorbar(i + 0.12, b, yerr=[[b - ci[0]], [ci[1] - b]], fmt="s",
                color="#e67e22", capsize=3, label="+VIX control" if i == 0 else "")
ax.axhline(0, color="k", lw=0.8, ls="--")
ax.set_xticks(xs); ax.set_xticklabels(labels, rotation=20)
ax.set_ylabel("oil_logRV[t-1] coef (spillover b)")
ax.set_title("Oil->equity vol spillover coefficient (95% stationary-bootstrap CI)")
ax.legend(); ax.grid(alpha=0.3, axis="y")
fig.tight_layout(); fig.savefig("experiments/k1647/fig_oil_to_equity_coef.png", dpi=110)
plt.close(fig)

print("  Saved 3 figures.")
print("=" * 78)
print("DONE")
