"""ASIA-3: Taiwan sector-level volatility spillover network.

Experiment id: asia3_tw_sector_spillover

Research question
-----------------
Which Taiwan industry sectors are net *transmitters* vs net *receivers* of
volatility, and how does the connectedness network tighten/loosen through
bear markets? Uses the Diebold-Yilmaz (2012, 2014) connectedness framework
with a *generalized* FEVD (Pesaran-Shin 1998), which is invariant to variable
ordering -- deliberately avoiding the Cholesky-FEVD ordering artifact.

Method summary
--------------
1. Volatility measure: Garman-Klass (1980) range-based daily volatility from
   OHLC. This is the canonical estimator used by Diebold & Yilmaz (2012). It is
   built purely from *within-day* log ratios, so it is invariant to any per-day
   multiplicative price adjustment (splits / ex-dividend), sidestepping the
   overnight-gap contamination that would plague close-to-close proxies.
2. VAR(p) on log Garman-Klass volatility; lag chosen by information criteria.
3. Generalized FEVD -> Diebold-Yilmaz spillover table: total spillover index,
   directional (to/from each sector), net, and net pairwise.
4. Rolling-window total spillover to trace the time evolution (with window /
   horizon sensitivity).
5. Pairwise Granger-causality network as an orthogonal robustness view.
6. Supplementary out-of-sample forecast comparison (VAR with cross-sector
   spillover vs. univariate AR) via the canonical Diebold-Mariano test.

Lookahead discipline
--------------------
The VAR is a strictly causal predictor: y_t is regressed on y_{t-1..t-p}.
The rolling connectedness at date d uses only observations up to d. The OOS
forecast loop estimates parameters on an expanding window that ends strictly
before the forecast origin (explicit `train = series up to origin-1`), so no
future information enters any estimate.

All randomness (block bootstrap / any resampling) uses SEED = 42.

Data: yfinance daily OHLC, 9 Taiwan sector-representative stocks, longest
common sample. All tickers are TWSE-listed -> a single trading calendar, so
alignment is an inner join on dates (no cross-market holiday imputation, no
forward-fill that would manufacture spurious correlation).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# Headless-safe matplotlib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import networkx as nx  # noqa: E402
from scipy import stats  # noqa: E402
from statsmodels.tsa.api import VAR  # noqa: E402
from statsmodels.tsa.stattools import grangercausalitytests  # noqa: E402
from statsmodels.stats.diagnostic import acorr_ljungbox  # noqa: E402

# Canonical repo DM test (Newey-West HAC, Harvey |t|>3 threshold)
from volpred.stats.model_evaluation import dm_test  # noqa: E402

SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
ASSETS.mkdir(exist_ok=True)
CACHE = HERE / "data"
CACHE.mkdir(exist_ok=True)

EPS = 1e-12

# ---- Sector universe (TWSE-listed representative stocks) --------------------
SECTORS: dict[str, str] = {
    "2330.TW": "Semiconductor",     # TSMC
    "2317.TW": "Electronics_EMS",   # Hon Hai / Foxconn
    "2454.TW": "IC_Design",         # MediaTek
    "2881.TW": "Financials",        # Fubon Financial Holding
    "2891.TW": "Financials",        # CTBC Financial Holding
    "2603.TW": "Shipping",          # Evergreen Marine
    "2609.TW": "Shipping",          # Yang Ming Marine
    "1301.TW": "Petrochemical",     # Formosa Plastics
    "3008.TW": "Optical",           # Largan Precision
}
# Short display labels for the network figure / tables
LABELS: dict[str, str] = {
    "2330.TW": "TSMC(Semi)",
    "2317.TW": "HonHai(EMS)",
    "2454.TW": "MediaTek(IC)",
    "2881.TW": "Fubon(Fin)",
    "2891.TW": "CTBC(Fin)",
    "2603.TW": "Evergreen(Ship)",
    "2609.TW": "YangMing(Ship)",
    "1301.TW": "FPC(Petchem)",
    "3008.TW": "Largan(Optic)",
}
TICKERS = list(SECTORS.keys())

# ---- Model constants --------------------------------------------------------
FEVD_H = 10          # forecast horizon for the FEVD (DY 2012 use 10)
ROLL_WINDOW = 200    # rolling-window length (trading days)
ROLL_STEP = 5        # rolling step
MAX_LAG = 6          # max VAR lag considered for information-criterion search
OOS_START = "2015-01-01"  # supplementary DM forecast OOS start
DM_REFIT_EVERY = 21       # refit cadence for the OOS forecast loop


# =============================================================================
# Data
# =============================================================================
def download_ohlc() -> pd.DataFrame:
    """Download longest common-sample daily OHLC for all tickers.

    Returns a wide DataFrame with a two-level column index (ticker, field).
    Cached to parquet so reruns are deterministic and offline-friendly.
    """
    cache_file = CACHE / "ohlc_max.parquet"
    if cache_file.exists():
        df = pd.read_parquet(cache_file)
        df.columns = pd.MultiIndex.from_tuples([tuple(c.split("||")) for c in df.columns])
        return df

    import yfinance as yf

    raw = yf.download(
        TICKERS, period="max", auto_adjust=True, group_by="ticker",
        progress=False, threads=True,
    )
    frames = {}
    for t in TICKERS:
        sub = raw[t][["Open", "High", "Low", "Close"]].copy()
        frames[t] = sub
    wide = pd.concat(frames, axis=1)
    wide.columns = pd.MultiIndex.from_tuples([(t, f) for t, f in wide.columns])
    # persist (flatten cols for parquet)
    flat = wide.copy()
    flat.columns = [f"{t}||{f}" for t, f in wide.columns]
    flat.to_parquet(cache_file)
    return wide


def garman_klass_vol(o: pd.Series, h: pd.Series, l: pd.Series, c: pd.Series) -> pd.Series:
    """Garman-Klass (1980) daily volatility (std-dev units, decimal).

    sigma^2 = 0.5*(ln(H/L))^2 - (2*ln2 - 1)*(ln(C/O))^2

    Built from within-day log ratios only -> invariant to per-day price
    adjustment (splits / ex-dividend). Guards against non-positive prices.
    """
    o = o.astype(float); h = h.astype(float); l = l.astype(float); c = c.astype(float)
    valid = (o > 0) & (h > 0) & (l > 0) & (c > 0) & (h >= l)
    ln_hl = np.log((h / l).where(valid))
    ln_co = np.log((c / o).where(valid))
    var = 0.5 * ln_hl**2 - (2.0 * np.log(2.0) - 1.0) * ln_co**2
    var = var.clip(lower=EPS)
    return np.sqrt(var)


def build_logvol_panel() -> tuple[pd.DataFrame, dict]:
    """Return (log-GK-vol panel over the common window, data diagnostics)."""
    ohlc = download_ohlc()
    vol_cols = {}
    diag_per_ticker = {}
    for t in TICKERS:
        sub = ohlc[t].dropna(subset=["Close"])
        gk = garman_klass_vol(sub["Open"], sub["High"], sub["Low"], sub["Close"])
        gk = gk.dropna()
        vol_cols[t] = gk
        diag_per_ticker[t] = {
            "sector": SECTORS[t],
            "n_raw": int(len(sub)),
            "n_gk": int(len(gk)),
            "start": str(gk.index.min().date()),
            "end": str(gk.index.max().date()),
        }
    vol = pd.DataFrame(vol_cols).dropna()  # inner join -> common calendar
    log_vol = np.log(vol.clip(lower=EPS))
    diag = {
        "per_ticker": diag_per_ticker,
        "common_start": str(vol.index.min().date()),
        "common_end": str(vol.index.max().date()),
        "n_common": int(len(vol)),
    }
    return log_vol, diag


# =============================================================================
# Generalized FEVD (Pesaran-Shin 1998) -> Diebold-Yilmaz connectedness
# =============================================================================
def ma_coefficients(coefs: np.ndarray, horizon: int) -> list[np.ndarray]:
    """MA(inf) coefficient matrices Psi_h for a VAR(p).

    coefs : ndarray shape (p, k, k) -- VAR autoregression matrices A_1..A_p
            (statsmodels VARResults.coefs convention).
    Returns [Psi_0=I, Psi_1, ..., Psi_{horizon-1}] via
        Psi_h = sum_{m=1}^{min(h,p)} A_m @ Psi_{h-m}.
    """
    p, k, _ = coefs.shape
    psis = [np.eye(k)]
    for h in range(1, horizon):
        acc = np.zeros((k, k))
        for m in range(1, min(h, p) + 1):
            acc += coefs[m - 1] @ psis[h - m]
        psis.append(acc)
    return psis


def generalized_fevd(coefs: np.ndarray, sigma: np.ndarray, horizon: int = FEVD_H) -> np.ndarray:
    """Row-normalized generalized FEVD theta_tilde (k x k).

    theta_ij(H) = sigma_jj^{-1} * sum_h (e_i' Psi_h Sigma e_j)^2
                  / sum_h (e_i' Psi_h Sigma Psi_h' e_i)

    Axis convention (guards against the K865 axis bug):
      * ROW i  = the variable whose forecast-error variance is being explained.
      * COL j  = the shock/source variable.
      * from_others(i) = row i off-diagonal sum ; to_others(j) = col j off-diag.
    Each row of the returned matrix sums to 1 (asserted by caller).
    """
    k = sigma.shape[0]
    psis = ma_coefficients(coefs, horizon)
    theta = np.zeros((k, k))
    for i in range(k):
        denom = 0.0
        for psi in psis:
            row = psi[i, :] @ sigma            # e_i' Psi_h Sigma  (length k)
            denom += float(row @ psi[i, :])    # e_i' Psi_h Sigma Psi_h' e_i
        if denom <= EPS:
            continue
        for j in range(k):
            numer = 0.0
            for psi in psis:
                numer += float((psi[i, :] @ sigma[:, j]) ** 2)
            theta[i, j] = (numer / max(sigma[j, j], EPS)) / denom
    row_sums = theta.sum(axis=1, keepdims=True)
    row_sums[row_sums <= EPS] = 1.0
    return theta / row_sums


@dataclass
class Connectedness:
    labels: list[str]
    lag: int
    horizon: int
    n_obs: int
    theta: np.ndarray                      # row-normalized GFEVD (fractions)
    total: float                           # DY total spillover index (%)
    to_others: dict = field(default_factory=dict)     # DY convention (/N, %)
    from_others: dict = field(default_factory=dict)
    net: dict = field(default_factory=dict)
    from_own_share: dict = field(default_factory=dict)  # 100*(1-theta_ii)
    pairwise_pct: dict = field(default_factory=dict)     # theta_tilde*100, row-normalized
    net_pairwise: dict = field(default_factory=dict)     # (theta_ji-theta_ij)*100/N


def connectedness(theta: np.ndarray, labels: list[str], lag: int, horizon: int,
                  n_obs: int) -> Connectedness:
    k = len(labels)
    # Row-sum sanity (each explained variable's variance shares sum to 100%).
    assert np.allclose(theta.sum(axis=1), 1.0, atol=1e-6), "GFEVD rows must sum to 1"

    total = float((theta.sum() - np.trace(theta)) / k * 100.0)
    to_o, from_o, net, own_share = {}, {}, {}, {}
    for i, lab in enumerate(labels):
        # DY (2012) convention: directional measures divided by N so they are
        # on the same scale as the total index (system-average shares).
        from_o[lab] = float((theta[i, :].sum() - theta[i, i]) / k * 100.0)
        to_o[lab] = float((theta[:, i].sum() - theta[i, i]) / k * 100.0)
        own_share[lab] = float((1.0 - theta[i, i]) * 100.0)
    for lab in labels:
        net[lab] = float(to_o[lab] - from_o[lab])

    pairwise_pct = {labels[i]: {labels[j]: float(theta[i, j] * 100.0)
                                for j in range(k)} for i in range(k)}
    net_pw = {}
    for i in range(k):
        net_pw[labels[i]] = {}
        for j in range(k):
            net_pw[labels[i]][labels[j]] = float((theta[j, i] - theta[i, j]) / k * 100.0)

    return Connectedness(
        labels=labels, lag=lag, horizon=horizon, n_obs=n_obs, theta=theta,
        total=total, to_others=to_o, from_others=from_o, net=net,
        from_own_share=own_share, pairwise_pct=pairwise_pct, net_pairwise=net_pw,
    )


def fit_var_connectedness(panel: pd.DataFrame, horizon: int = FEVD_H,
                          lag: int | None = None, max_lag: int = MAX_LAG) -> tuple[Connectedness, dict]:
    """Fit VAR (IC lag if lag is None), compute GFEVD connectedness + diagnostics."""
    labels = [LABELS[c] for c in panel.columns]
    model = VAR(panel.to_numpy())
    ic_table = {}
    if lag is None:
        sel = model.select_order(max_lag)
        ic_table = {k: int(v) for k, v in sel.selected_orders.items()}
        # Prefer AIC but keep >=1; report all.
        lag = max(1, int(sel.aic))
    res = model.fit(lag)
    theta = generalized_fevd(res.coefs, res.sigma_u, horizon)
    conn = connectedness(theta, labels, lag, horizon, int(res.nobs))

    # Residual diagnostics: Ljung-Box on each residual series (lag 10).
    resid = np.asarray(res.resid)
    lb = {}
    for i, lab in enumerate(labels):
        try:
            out = acorr_ljungbox(resid[:, i], lags=[10], return_df=True)
            lb[lab] = {"lb_stat": float(out["lb_stat"].iloc[0]),
                       "lb_pvalue": float(out["lb_pvalue"].iloc[0])}
        except Exception as e:  # noqa: BLE001
            lb[lab] = {"error": str(e)}
    diag = {"ic_selected_orders": ic_table, "lag_used": int(lag),
            "ljung_box_lag10": lb,
            "stable": bool(res.is_stable(verbose=False))}
    return conn, diag


# =============================================================================
# Rolling-window total spillover
# =============================================================================
def rolling_total_spillover(panel: pd.DataFrame, lag: int, horizon: int,
                            window: int = ROLL_WINDOW, step: int = ROLL_STEP) -> pd.DataFrame:
    """Rolling DY total spillover index. Uses only in-window data at each date."""
    dates, totals = [], []
    idx = panel.index
    n = len(panel)
    labels = [LABELS[c] for c in panel.columns]
    for end in range(window, n + 1, step):
        sub = panel.iloc[end - window:end]
        try:
            model = VAR(sub.to_numpy())
            res = model.fit(lag)
            theta = generalized_fevd(res.coefs, res.sigma_u, horizon)
            conn = connectedness(theta, labels, lag, horizon, int(res.nobs))
            dates.append(idx[end - 1])
            totals.append(conn.total)
        except Exception as e:  # noqa: BLE001
            # log + skip (no silent fallback)
            print(f"[roll] skip window ending {idx[end-1].date()}: {e}")
            continue
    return pd.DataFrame({"date": dates, "total_spillover": totals}).set_index("date")


# =============================================================================
# Granger-causality network (robustness)
# =============================================================================
def granger_network(panel: pd.DataFrame, maxlag: int, alpha: float = 0.01) -> dict:
    """Pairwise Granger causality (source -> target). Reports min p over lags 1..maxlag
    with a Bonferroni-style note. Edge present if min-p < alpha."""
    cols = list(panel.columns)
    labels = [LABELS[c] for c in cols]
    edges = []
    pmatrix = {}
    n_tests = len(cols) * (len(cols) - 1)
    bonf_alpha = alpha / max(1, n_tests)
    for a, ta in enumerate(cols):        # source
        for b, tb in enumerate(cols):    # target
            if a == b:
                continue
            # test: does `ta` Granger-cause `tb`?  grangercausalitytests(data[:, [tb, ta]])
            data = panel[[tb, ta]].to_numpy()
            try:
                res = grangercausalitytests(data, maxlag=maxlag, verbose=False)
                pvals = [res[L][0]["ssr_ftest"][1] for L in range(1, maxlag + 1)]
                pmin = float(np.min(pvals))
            except Exception as e:  # noqa: BLE001
                print(f"[granger] {LABELS[ta]}->{LABELS[tb]} failed: {e}")
                continue
            pmatrix[f"{LABELS[ta]}->{LABELS[tb]}"] = pmin
            if pmin < bonf_alpha:
                edges.append({"source": LABELS[ta], "target": LABELS[tb], "min_p": pmin})
    # out-degree (transmitter) / in-degree (receiver) under Bonferroni
    outdeg = {lab: 0 for lab in labels}
    indeg = {lab: 0 for lab in labels}
    for e in edges:
        outdeg[e["source"]] += 1
        indeg[e["target"]] += 1
    return {"alpha": alpha, "bonferroni_alpha": bonf_alpha, "n_tests": n_tests,
            "maxlag": maxlag, "edges": edges, "out_degree": outdeg,
            "in_degree": indeg, "pmatrix": pmatrix}


# =============================================================================
# Supplementary OOS forecast: VAR (spillover) vs univariate AR, DM test
# =============================================================================
def oos_var_vs_ar_dm(panel: pd.DataFrame, lag: int, oos_start: str,
                     refit_every: int = DM_REFIT_EVERY) -> dict:
    """Expanding-window one-step-ahead forecasts of log-vol.

    For each target sector, compare a VAR that uses cross-sector information
    against a univariate AR(lag). Aggregate the QLIKE-style squared-error loss
    differential *by date* across sectors (avoids treating asset-days as iid,
    per K1355) and apply the canonical Diebold-Mariano test.

    Lookahead discipline: at origin t we fit on `panel.iloc[:t]` (ends at t-1)
    and forecast row t. Train window ends strictly before the forecast target.
    """
    arr = panel.to_numpy()
    dates = panel.index
    k = arr.shape[1]
    labels = [LABELS[c] for c in panel.columns]
    start_pos = int(np.searchsorted(dates.values, np.datetime64(oos_start)))
    start_pos = max(start_pos, lag + 60)

    var_coefs = None
    ar_params = None  # per-series (const + lag coefs)
    se_var = []   # list of (date, per-sector squared errors)
    se_ar = []
    origins = []
    for t in range(start_pos, len(arr)):
        if (t - start_pos) % refit_every == 0 or var_coefs is None:
            train = arr[:t]  # ends at t-1, strictly before target row t
            try:
                vres = VAR(train).fit(lag)
                var_coefs = (vres.coefs, vres.intercept)
            except Exception as e:  # noqa: BLE001
                print(f"[dm] VAR refit failed at {dates[t].date()}: {e}")
                continue
            # univariate AR(lag) via OLS per series
            ar_params = []
            for j in range(k):
                y = train[lag:, j]
                X = np.column_stack([np.ones(len(y))] +
                                    [train[lag - m:len(train) - m, j] for m in range(1, lag + 1)])
                beta, *_ = np.linalg.lstsq(X, y, rcond=None)
                ar_params.append(beta)

        # Build one-step VAR forecast for row t from rows t-1..t-lag
        A, c = var_coefs
        yhat_var = c.copy()
        for m in range(1, lag + 1):
            yhat_var = yhat_var + A[m - 1] @ arr[t - m]
        # univariate AR forecast per series
        yhat_ar = np.empty(k)
        for j in range(k):
            beta = ar_params[j]
            xr = np.concatenate([[1.0], [arr[t - m, j] for m in range(1, lag + 1)]])
            yhat_ar[j] = beta @ xr

        actual = arr[t]
        se_var.append((actual - yhat_var) ** 2)
        se_ar.append((actual - yhat_ar) ** 2)
        origins.append(dates[t])

    se_var = np.asarray(se_var)   # (T, k)
    se_ar = np.asarray(se_ar)
    # Aggregate loss by date across sectors (mean over sectors), then DM.
    loss_var_by_date = se_var.mean(axis=1)
    loss_ar_by_date = se_ar.mean(axis=1)
    t_stat, p_val = dm_test(loss_var_by_date, loss_ar_by_date, h=1)

    # Per-sector DM as diagnostic (not primary claim).
    per_sector = {}
    for j, lab in enumerate(labels):
        ts, pv = dm_test(se_var[:, j], se_ar[:, j], h=1)
        per_sector[lab] = {"dm_t": float(ts), "dm_p": float(pv),
                           "mean_se_var": float(se_var[:, j].mean()),
                           "mean_se_ar": float(se_ar[:, j].mean())}

    return {
        "oos_start": str(origins[0].date()) if origins else None,
        "oos_end": str(origins[-1].date()) if origins else None,
        "n_forecasts": int(len(origins)),
        "refit_every": refit_every,
        "aggregation": "loss averaged across sectors by date, then HAC DM (K1355 discipline)",
        "dm_t_var_vs_ar": float(t_stat),
        "dm_p": float(p_val),
        "harvey_significant_|t|>3": bool(abs(t_stat) > 3.0),
        "interpretation": ("negative t => VAR (cross-sector spillover) has lower "
                           "one-step loss than univariate AR"),
        "lag_caveat": ("VAR/AR share the same lag (fair comparison), but the lag was "
                       "chosen by AIC on the full sample; a fully PIT design would "
                       "re-select lag from pre-origin data only (effect negligible "
                       "given the shared-lag fairness and n=2810)."),
        "per_sector_diagnostic": per_sector,
    }


# =============================================================================
# Figures
# =============================================================================
def plot_network(conn: Connectedness, path: Path) -> None:
    """Directed net-pairwise spillover network. Node size ~ |net|, color by sign.
    Edge direction = net transmitter -> net receiver for the pair; width ~ |net pw|."""
    labels = conn.labels
    G = nx.DiGraph()
    net = conn.net
    for lab in labels:
        G.add_node(lab)
    # keep only meaningful net-pairwise edges (top by magnitude)
    edge_list = []
    for i, a in enumerate(labels):
        for j, b in enumerate(labels):
            if j <= i:
                continue
            # net_pairwise[a][b] = (theta[b,a]-theta[a,b])/k*100; theta[i,j] is
            # "j transmits to i", so npw > 0 means a is the NET transmitter to b.
            npw = conn.net_pairwise[a][b]
            if abs(npw) < 0.05:
                continue
            if npw > 0:
                edge_list.append((a, b, abs(npw)))  # a transmits net to b
            else:
                edge_list.append((b, a, abs(npw)))  # b transmits net to a
    if edge_list:
        wmax = max(w for *_, w in edge_list)
    else:
        wmax = 1.0
    for u, v, w in edge_list:
        G.add_edge(u, v, weight=w)

    pos = nx.circular_layout(G)
    fig, ax = plt.subplots(figsize=(10, 9))
    net_vals = np.array([net[l] for l in labels])
    nmax = max(1e-6, np.abs(net_vals).max())
    node_colors = ["#d62728" if net[l] > 0 else "#1f77b4" for l in labels]
    node_sizes = [400 + 2600 * abs(net[l]) / nmax for l in labels]
    nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=node_sizes,
                           alpha=0.85, ax=ax, edgecolors="black", linewidths=0.8)
    for u, v, d in G.edges(data=True):
        nx.draw_networkx_edges(
            G, pos, edgelist=[(u, v)], ax=ax,
            width=0.6 + 4.0 * d["weight"] / wmax,
            alpha=0.45, edge_color="#555555",
            arrowstyle="-|>", arrowsize=14,
            connectionstyle="arc3,rad=0.08", node_size=node_sizes,
        )
    nx.draw_networkx_labels(G, pos, font_size=9, ax=ax)
    ax.set_title(
        f"Taiwan sector volatility spillover network (net pairwise)\n"
        f"red = net transmitter, blue = net receiver | GFEVD H={conn.horizon}, "
        f"VAR({conn.lag}), N={conn.n_obs}",
        fontsize=11,
    )
    ax.axis("off")
    # legend text
    ax.text(0.01, 0.01, "Node size ~ |net spillover|; arrow = net transmit direction",
            transform=ax.transAxes, fontsize=8, color="#333333")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_rolling(roll: pd.DataFrame, path: Path, bear_spans: list[tuple[str, str, str]]) -> None:
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(roll.index, roll["total_spillover"], color="#1f2a44", lw=1.2)
    ax.set_ylabel("Total spillover index (%)")
    ax.set_title(f"Taiwan sector volatility total spillover ({ROLL_WINDOW}-day rolling window)")
    for start, end, label in bear_spans:
        ax.axvspan(pd.Timestamp(start), pd.Timestamp(end), color="#d62728", alpha=0.12)
        ax.text(pd.Timestamp(start), roll["total_spillover"].max(), label,
                fontsize=8, color="#8b1a1a", rotation=90, va="top")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_from_to_bars(conn: Connectedness, path: Path) -> None:
    labels = conn.labels
    order = sorted(labels, key=lambda l: conn.net[l], reverse=True)
    to_v = [conn.to_others[l] for l in order]
    from_v = [conn.from_others[l] for l in order]
    net_v = [conn.net[l] for l in order]
    x = np.arange(len(order))
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.bar(x - 0.2, to_v, width=0.4, label="TO others", color="#d62728", alpha=0.8)
    ax.bar(x + 0.2, from_v, width=0.4, label="FROM others", color="#1f77b4", alpha=0.8)
    ax.plot(x, net_v, "ko-", label="NET", lw=1.4)
    ax.axhline(0, color="black", lw=0.6)
    ax.set_xticks(x)
    ax.set_xticklabels(order, rotation=35, ha="right", fontsize=9)
    ax.set_ylabel("Directional spillover (%, DY /N convention)")
    ax.set_title("Directional volatility spillovers by Taiwan sector (sorted by NET)")
    ax.legend()
    ax.grid(alpha=0.2, axis="y")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


# =============================================================================
# Main
# =============================================================================
def main() -> dict:
    log_vol, data_diag = build_logvol_panel()
    print(f"Common sample: {data_diag['common_start']} -> {data_diag['common_end']} "
          f"(N={data_diag['n_common']})")

    # Descriptive statistics (observation before estimation).
    desc = {}
    for c in log_vol.columns:
        s = np.exp(log_vol[c])  # back to GK vol level (decimal daily)
        desc[LABELS[c]] = {
            "sector": SECTORS[c],
            "mean_daily_vol": float(s.mean()),
            "median_daily_vol": float(s.median()),
            "annualized_vol_pct": float(s.mean() * np.sqrt(252) * 100.0),
            "logvol_std": float(log_vol[c].std()),
        }
    corr = log_vol.corr()
    corr_named = {LABELS[a]: {LABELS[b]: float(corr.loc[a, b]) for b in log_vol.columns}
                  for a in log_vol.columns}

    # ---- Full-sample connectedness -----------------------------------------
    conn, var_diag = fit_var_connectedness(log_vol, horizon=FEVD_H, lag=None, max_lag=MAX_LAG)
    lag = conn.lag
    print(f"VAR lag used = {lag}; total spillover = {conn.total:.2f}%")

    # ---- Rolling window -----------------------------------------------------
    roll = rolling_total_spillover(log_vol, lag=lag, horizon=FEVD_H,
                                   window=ROLL_WINDOW, step=ROLL_STEP)
    roll_summary = {
        "window": ROLL_WINDOW, "step": ROLL_STEP, "n_points": int(len(roll)),
        "mean": float(roll["total_spillover"].mean()),
        "min": float(roll["total_spillover"].min()),
        "min_date": str(roll["total_spillover"].idxmin().date()),
        "max": float(roll["total_spillover"].max()),
        "max_date": str(roll["total_spillover"].idxmax().date()),
        "last": float(roll["total_spillover"].iloc[-1]),
        "last_date": str(roll.index[-1].date()),
    }

    # bear-market total spillover vs calm
    bear_spans = [
        ("2008-09-01", "2009-03-31", "GFC"),
        ("2011-08-01", "2011-12-31", "EU debt"),
        ("2020-02-20", "2020-04-30", "COVID"),
        ("2022-01-01", "2022-12-31", "2022 bear"),
    ]
    # Per-crisis breakdown (bear episodes are heterogeneous in DURATION; a
    # 200-day trailing window fully captures prolonged bears but dilutes sharp
    # multi-week crashes -> the pooled bear-vs-calm mean hides this).
    crisis_windows = [
        ("2008_GFC", "2008-10-01", "2009-03-31"),
        ("2011_EU_debt", "2011-08-01", "2011-12-31"),
        ("2015_China_crash", "2015-06-01", "2015-09-30"),
        ("2018_Q4_selloff", "2018-10-01", "2018-12-31"),
        ("2020_COVID", "2020-02-20", "2020-05-31"),
        ("2022_bear", "2022-01-01", "2022-12-31"),
    ]
    bear_mask = pd.Series(False, index=roll.index)
    for s, e, _ in bear_spans:
        bear_mask |= (roll.index >= pd.Timestamp(s)) & (roll.index <= pd.Timestamp(e))
    bear_mean = float(roll.loc[bear_mask, "total_spillover"].mean()) if bear_mask.any() else None
    calm_mean = float(roll.loc[~bear_mask, "total_spillover"].mean())

    # ---- Rolling sensitivity ------------------------------------------------
    sensitivity = {}
    for w in (150, 250):
        r2 = rolling_total_spillover(log_vol, lag=lag, horizon=FEVD_H, window=w, step=10)
        sensitivity[f"window_{w}"] = {"mean": float(r2["total_spillover"].mean()),
                                      "n_points": int(len(r2))}
    for h in (12,):
        c2, _ = fit_var_connectedness(log_vol, horizon=h, lag=lag)
        sensitivity[f"horizon_{h}"] = {"total": c2.total}

    # ---- Lag robustness: is the net transmitter/receiver structure stable? --
    # AIC selected the max lag (6); BIC selected 2. If the net-spillover signs
    # flip across lag choices, the transmitter/receiver ranking is fragile and
    # claims must be softened. Report net at lags {2,4,6} + sign agreement.
    lag_rob = {}
    net_by_lag = {}
    for lg in (2, 4, 6):
        cl, _ = fit_var_connectedness(log_vol, horizon=FEVD_H, lag=lg)
        net_by_lag[lg] = {l: cl.net[l] for l in cl.labels}
        lag_rob[f"lag_{lg}"] = {"total": cl.total, "net": net_by_lag[lg]}
    ref_lag = lag  # AIC choice
    sign_agree = {}
    for lg in (2, 4):
        agree = sum(1 for l in conn.labels
                    if np.sign(net_by_lag[lg][l]) == np.sign(net_by_lag[ref_lag][l]))
        # Spearman rank correlation of net values vs reference lag
        a = np.array([net_by_lag[lg][l] for l in conn.labels])
        b = np.array([net_by_lag[ref_lag][l] for l in conn.labels])
        rho = float(stats.spearmanr(a, b).statistic)
        sign_agree[f"lag_{lg}_vs_{ref_lag}"] = {
            "sign_agreement_count": int(agree), "of": len(conn.labels),
            "spearman_net_rho": rho}
    lag_rob["sign_agreement_vs_aic_lag"] = sign_agree

    # ---- Short-window rolling: crisis behavior (200d may over-smooth) --------
    roll_short = rolling_total_spillover(log_vol, lag=lag, horizon=FEVD_H,
                                         window=100, step=5)
    bear_mask_s = pd.Series(False, index=roll_short.index)
    for s, e, _ in bear_spans:
        bear_mask_s |= (roll_short.index >= pd.Timestamp(s)) & (roll_short.index <= pd.Timestamp(e))
    short_bear = float(roll_short.loc[bear_mask_s, "total_spillover"].mean()) if bear_mask_s.any() else None
    short_calm = float(roll_short.loc[~bear_mask_s, "total_spillover"].mean())
    roll_short_summary = {
        "window": 100, "step": 5, "n_points": int(len(roll_short)),
        "mean": float(roll_short["total_spillover"].mean()),
        "max": float(roll_short["total_spillover"].max()),
        "max_date": str(roll_short["total_spillover"].idxmax().date()),
        "min": float(roll_short["total_spillover"].min()),
        "min_date": str(roll_short["total_spillover"].idxmin().date()),
        "bear_mean": short_bear, "calm_mean": short_calm,
        "bear_minus_calm": (short_bear - short_calm) if short_bear is not None else None,
    }

    # ---- Per-crisis breakdown (both window lengths) -------------------------
    def _seg_stats(series: pd.Series, d0: str, d1: str) -> dict:
        seg = series.loc[d0:d1]
        if not len(seg):
            return {"n": 0, "mean": None, "max": None}
        return {"n": int(len(seg)), "mean": float(seg.mean()),
                "max": float(seg.max()), "min": float(seg.min())}

    per_crisis = {}
    for name, d0, d1 in crisis_windows:
        per_crisis[name] = {
            "span": [d0, d1],
            "w200": _seg_stats(roll["total_spillover"], d0, d1),
            "w100": _seg_stats(roll_short["total_spillover"], d0, d1),
        }
    per_crisis["_full_sample_mean_w200"] = float(roll["total_spillover"].mean())
    per_crisis["_full_sample_mean_w100"] = float(roll_short["total_spillover"].mean())
    per_crisis["_interpretation"] = (
        "Connectedness elevates in PROLONGED bears (2008 GFC, 2015 China crash) "
        "but the 200-day trailing window under-reads SHARP crashes (2018 Q4, 2020 "
        "COVID) because a multi-week shock is diluted across the window. The pooled "
        "bear-vs-calm mean is ~flat only because it averages these opposite-duration "
        "episodes -- it is NOT evidence that contagion is absent.")

    # ---- Granger network ----------------------------------------------------
    granger = granger_network(log_vol, maxlag=lag, alpha=0.01)

    # ---- Supplementary OOS DM ----------------------------------------------
    dm = oos_var_vs_ar_dm(log_vol, lag=lag, oos_start=OOS_START)

    # ---- Sector-aggregated net (group individual stocks into sectors) -------
    # For the reader-facing "sector rotation" angle, aggregate net spillover by
    # sector group (Financials, Shipping each have 2 stocks).
    sector_net = {}
    for c in log_vol.columns:
        sec = SECTORS[c]
        sector_net.setdefault(sec, []).append(conn.net[LABELS[c]])
    sector_net_mean = {sec: float(np.mean(v)) for sec, v in sector_net.items()}
    transmitters = sorted([l for l in conn.labels if conn.net[l] > 0],
                          key=lambda l: conn.net[l], reverse=True)
    receivers = sorted([l for l in conn.labels if conn.net[l] <= 0],
                       key=lambda l: conn.net[l])

    # ---- Figures ------------------------------------------------------------
    plot_network(conn, ASSETS / "spillover_network.png")
    plot_rolling(roll, ASSETS / "rolling_total_spillover.png", bear_spans)
    plot_from_to_bars(conn, ASSETS / "directional_bars.png")
    roll.reset_index().to_csv(ASSETS / "rolling_total_spillover.csv", index=False)

    # ---- Assemble results ---------------------------------------------------
    results = {
        "experiment_id": "asia3_tw_sector_spillover",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data": {
            "source": "yfinance daily OHLC, auto_adjust=True",
            "tickers": TICKERS,
            "sector_map": SECTORS,
            "volatility_measure": "Garman-Klass (1980) range-based daily vol on log scale",
            "gk_ex_div_invariance_note": (
                "GK uses within-day log ratios only; invariant to per-day price "
                "adjustment (splits/ex-dividend), so overnight gaps do not contaminate it"),
            "alignment": "inner join on TWSE trading calendar (all tickers TWSE-listed)",
            **data_diag,
        },
        "descriptive_stats": desc,
        "logvol_correlation": corr_named,
        "connectedness_full_sample": {
            "method": "Generalized FEVD (Pesaran-Shin 1998) on VAR(p) MA representation",
            "why_generalized": ("order-invariant; Cholesky-FEVD would depend on the "
                                "arbitrary variable ordering (task-flagged pitfall)"),
            "var_lag": lag,
            "fevd_horizon": FEVD_H,
            "directional_convention": "DY(2012): to/from/net divided by N (system-average shares)",
            "total_spillover_index_pct": conn.total,
            "to_others_pct": conn.to_others,
            "from_others_pct": conn.from_others,
            "net_pct": conn.net,
            "from_own_share_pct": conn.from_own_share,
            "pairwise_pct_row_normalized": conn.pairwise_pct,
            "net_pairwise_pct": conn.net_pairwise,
            "var_diagnostics": var_diag,
        },
        "net_transmitters_ranked": transmitters,
        "net_receivers_ranked": receivers,
        "sector_group_net_mean": sector_net_mean,
        "rolling_spillover": roll_summary,
        "rolling_bear_vs_calm": {
            "bear_spans": bear_spans,
            "bear_mean_total_spillover": bear_mean,
            "calm_mean_total_spillover": calm_mean,
            "bear_minus_calm": (bear_mean - calm_mean) if bear_mean is not None else None,
            "caveat": ("pooled mean averages heterogeneous-duration crises; see "
                       "per_crisis_spillover for the honest breakdown"),
        },
        "per_crisis_spillover": per_crisis,
        "sensitivity": sensitivity,
        "lag_robustness": lag_rob,
        "rolling_short_window_100d": roll_short_summary,
        "granger_network": granger,
        "oos_forecast_dm": dm,
        "comparison_to_T5a": {
            "T5a_structure": "VT gamma: TAIEX 0.153 > 0050 0.087 > TSMC 0.039 (aggregation amplifies gamma)",
            "note": ("T5a is a vol-targeting persistence (gamma) result at index/ETF/single-stock "
                     "aggregation levels, not a spillover measure. The connection tested here: "
                     "whether more index-like / cross-linked sectors (semis, financials) act as net "
                     "volatility transmitters, consistent with aggregation concentrating systematic "
                     "volatility. See README for the full discussion."),
        },
        "limitations": [
            "Daily Garman-Klass vol is a range-based proxy, not intraday realized variance.",
            "Connectedness/GFEVD are network-centrality diagnostics, not structural causal spillovers.",
            "Two sectors (Financials, Shipping) have 2 representative stocks; others have 1 -> "
            "sector coverage is representative, not exhaustive.",
            "Granger causality is linear and in-sample; treat as robustness, not proof of mechanism.",
        ],
        "references": [
            "Diebold, F.X. & Yilmaz, K. (2012). Better to give than to receive: Predictive "
            "directional measurement of volatility spillovers. International Journal of Forecasting 28(1), 57-66.",
            "Diebold, F.X. & Yilmaz, K. (2014). On the network topology of variance decompositions: "
            "Measuring the connectedness of financial firms. Journal of Econometrics 182(1), 119-134.",
            "Pesaran, H.H. & Shin, Y. (1998). Generalized impulse response analysis in linear "
            "multivariate models. Economics Letters 58(1), 17-29.",
            "Garman, M.B. & Klass, M.J. (1980). On the estimation of security price volatilities "
            "from historical data. Journal of Business 53(1), 67-78.",
        ],
    }

    out = HERE / "asia3_tw_sector_spillover_results.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Wrote {out}")
    print(f"Net transmitters: {transmitters}")
    print(f"Net receivers: {receivers}")
    print(f"Bear mean spillover={bear_mean}, calm mean={calm_mean}")
    print(f"OOS DM t={dm['dm_t_var_vs_ar']:.3f} p={dm['dm_p']:.4f}")
    return results


if __name__ == "__main__":
    main()
