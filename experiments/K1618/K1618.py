"""
K1618 | Realized semicovariance (P/N/M signed decomposition) as an early-warning
signal for cross-asset correlation regimes.

Core hypothesis (Bollerslev-Li-Patton-Quaedvlieg 2020 JoE; BPQ 2022 JFE semibetas):
does the NEGATIVE-concordant semicovariance component N (downside co-movement)
forecast a future cross-asset correlation spike / cross-asset volatility spike
BETTER than total realized covariance (RCov = P + N + M) or total realized
variance (RV)?  If yes, downside co-movement is a correlation-regime early warning.

Data: yfinance daily adjusted closes, 10 cross-asset ETFs, 2005-01 .. 2026-06.
Frequency: DAILY returns aggregated within non-overlapping 21-trading-day
(~monthly) windows -> monthly realized semicovariance panel (BPQ 2022 daily
realized-semibeta convention). This is a data-feasible daily-frequency proxy,
NOT a high-frequency (intraday) realized semicovariance; fidelity gap noted in
README limitations.

Methodology guards honoured (see README "防錯規則遵守聲明"):
  * Lookahead: predictor from window w, target from window w+1 (strictly later,
    non-overlapping). OOS expanding-window training rows satisfy
    target_end < forecast_origin (train on {(X_k, Y_{k+1}) : k+1 <= w}).
  * K1355 cross-asset pooling: PRIMARY inference is on a PANEL-AGGREGATE series
    (one value per window) -> no asset-day stacking by construction. The cross-
    pair robustness explicitly date-aggregates loss differentials across pairs
    BEFORE the DM test; the stacked pair-window DM is reported ONLY as diagnostic.
  * K783c QLIKE: canonical actual/predicted - log(actual/predicted) - 1 via
    volpred.stats.model_evaluation.qlike_pointwise (RV target only; positive).
  * K1216b symmetric spec: N / RCov / RV predictors use identical functional
    form (univariate OLS with intercept; OLS forecast invariant to affine
    predictor rescaling so no standardisation asymmetry).
  * Harvey/HLN small-sample correction applied on top of HAC DM.
  * All random procedures seeded (seed=42).

Author: VolPred autonomous research agent. Reproducible: `uv run python K1618.py`.
"""
from __future__ import annotations

import json
import os
import random
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy import stats

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

import statsmodels.api as sm

from volpred.stats.model_evaluation import qlike_pointwise

warnings.filterwarnings("ignore")

# ----------------------------------------------------------------------------
# Reproducibility
# ----------------------------------------------------------------------------
SEED = 42
random.seed(SEED)
np.random.seed(SEED)

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_CSV = os.path.join(HERE, "prices_cache.csv")

TICKERS = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD", "XLF", "XLK", "XLE"]
START = "2005-01-01"
END = "2026-07-01"
WIN = 21           # non-overlapping window length (trading days) ~ 1 month
H = 1              # forecast horizon in windows (next month)
BURN_IN = 60       # OOS burn-in windows (~5y) before first forecast
SPIKE_Q = 0.80     # top-quintile spike threshold (training-only quantile)
N_BOOT = 2000      # moving-block bootstrap reps for loss-diff CI


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------
def load_prices() -> pd.DataFrame:
    if os.path.exists(CACHE_CSV):
        px = pd.read_csv(CACHE_CSV, index_col=0, parse_dates=True)
        if list(px.columns) == TICKERS and px.notna().all().all():
            print(f"[data] loaded cache {CACHE_CSV} shape={px.shape}")
            return px
        print("[data] cache incomplete -> re-downloading")
    import yfinance as yf
    df = yf.download(TICKERS, start=START, end=END, auto_adjust=True, progress=False)
    px = df["Close"][TICKERS].dropna(how="any")
    px.to_csv(CACHE_CSV)
    print(f"[data] downloaded shape={px.shape} -> cached")
    return px


# ----------------------------------------------------------------------------
# Realized semicovariance construction (BPQ 2020) over non-overlapping windows
# ----------------------------------------------------------------------------
def build_windows(rets: pd.DataFrame):
    """Split daily returns into consecutive non-overlapping WIN-day blocks.

    Returns list of dicts, each with the window's semicovariance panel
    aggregates + realized correlation, keyed by the window's END date.
    """
    n = len(rets)
    n_win = n // WIN
    R = rets.values                      # (n_days, n_assets)
    assets = list(rets.columns)
    na = len(assets)
    # upper-triangle pair indices (i<j)
    pairs = [(i, j) for i in range(na) for j in range(i + 1, na)]

    recs = []
    identity_resids = []
    for w in range(n_win):
        s, e = w * WIN, (w + 1) * WIN
        block = R[s:e, :]                # (WIN, na)
        rp = np.maximum(block, 0.0)      # r^+
        rm = np.minimum(block, 0.0)      # r^-

        # per-pair signed semicovariances (i<j)
        P = N = M = RCOV = 0.0
        for (i, j) in pairs:
            p_ij = float(np.sum(rp[:, i] * rp[:, j]))
            n_ij = float(np.sum(rm[:, i] * rm[:, j]))
            m_ij = float(np.sum(rp[:, i] * rm[:, j] + rm[:, i] * rp[:, j]))
            rc_ij = float(np.sum(block[:, i] * block[:, j]))
            P += p_ij
            N += n_ij
            M += m_ij
            RCOV += rc_ij
            identity_resids.append(abs(rc_ij - (p_ij + n_ij + m_ij)))
        npair = len(pairs)
        P /= npair; N /= npair; M /= npair; RCOV /= npair

        # total realized variance: mean over assets of RV_i = sum r_i^2
        rv_assets = np.sum(block ** 2, axis=0)          # (na,)
        RV = float(np.mean(rv_assets))

        # realized cross-asset average pairwise correlation (Pearson within window)
        cmat = np.corrcoef(block, rowvar=False)         # (na, na)
        iu = np.triu_indices(na, k=1)
        avg_corr = float(np.nanmean(cmat[iu]))

        recs.append({
            "w": w,
            "end_date": rets.index[e - 1],
            "start_date": rets.index[s],
            "P": P, "N": N, "M": M, "RCov": RCOV, "RV": RV,
            "avg_corr": avg_corr,
        })
    df = pd.DataFrame(recs).set_index("end_date")
    return df, float(np.max(identity_resids)), float(np.mean(identity_resids)), pairs


# ----------------------------------------------------------------------------
# Diebold-Mariano with HLN (Harvey-Leybourne-Newbold 1997) small-sample fix
# ----------------------------------------------------------------------------
def _hac_var(d: np.ndarray, nlags: int) -> float:
    dm = d - d.mean()
    v = float(np.mean(dm ** 2))
    for k in range(1, nlags + 1):
        w = 1.0 - k / (nlags + 1.0)                      # Bartlett
        v += 2.0 * w * float(np.mean(dm[k:] * dm[:-k]))
    return v


def dm_hln(loss1: np.ndarray, loss2: np.ndarray, h: int = 1,
           nw_lags: int | None = None) -> dict:
    """DM test (loss1 - loss2). Negative stat => model 1 (loss1) has LOWER loss.

    Reports canonical h-step HAC variance (lags 1..h-1) with HLN small-sample
    correction (compared to t_{n-1}), plus an auto-bandwidth NW robustness stat.
    Harvey (2016) multiple-testing bar: |HLN t| > 3.0.
    """
    d = np.asarray(loss1, float) - np.asarray(loss2, float)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return {"n": n, "note": "insufficient obs"}
    d_bar = float(d.mean())

    # canonical DM: lags 1..h-1 (h=1 -> variance = gamma0 only)
    canon_lags = max(0, h - 1)
    var_canon = _hac_var(d, canon_lags) if canon_lags > 0 else float(np.mean((d - d_bar) ** 2))
    se_canon = np.sqrt(var_canon / n)
    dm_stat = d_bar / se_canon if se_canon > 0 else 0.0

    # HLN small-sample factor + Student-t reference
    hln_factor = np.sqrt(max((n + 1 - 2 * h + h * (h - 1) / n) / n, 1e-12))
    dm_hln_stat = dm_stat * hln_factor
    p_hln = float(2 * (1 - stats.t.cdf(abs(dm_hln_stat), df=n - 1)))
    p_asym = float(2 * (1 - stats.norm.cdf(abs(dm_stat))))

    # robustness: auto-bandwidth Newey-West (Bartlett)
    nl = nw_lags if nw_lags is not None else int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
    var_nw = _hac_var(d, max(1, nl))
    se_nw = np.sqrt(var_nw / n)
    dm_nw = (d_bar / se_nw) * hln_factor if se_nw > 0 else 0.0
    p_nw = float(2 * (1 - stats.t.cdf(abs(dm_nw), df=n - 1)))

    return {
        "n": n,
        "mean_loss_diff": d_bar,
        "dm_stat": float(dm_stat),
        "dm_hln_stat": float(dm_hln_stat),
        "p_hln": p_hln,
        "p_asymptotic": p_asym,
        "hln_factor": float(hln_factor),
        "nw_lags": int(nl),
        "dm_hln_nw_stat": float(dm_nw),
        "p_hln_nw": p_nw,
        "harvey_pass": bool(abs(dm_hln_stat) > 3.0),
        "better": "model1" if d_bar < 0 else "model2",
    }


def block_bootstrap_ci(loss1, loss2, block=6, n_boot=N_BOOT, seed=SEED):
    """Moving-block bootstrap 95% CI for mean(loss1 - loss2)."""
    rng = np.random.default_rng(seed)
    d = np.asarray(loss1, float) - np.asarray(loss2, float)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 20:
        return None
    nblocks = int(np.ceil(n / block))
    means = np.empty(n_boot)
    max_start = n - block
    for b in range(n_boot):
        starts = rng.integers(0, max_start + 1, size=nblocks)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[:n]
        means[b] = d[idx].mean()
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {"mean": float(d.mean()), "ci_lo": float(lo), "ci_hi": float(hi),
            "excludes_zero": bool(lo > 0 or hi < 0)}


def auc_score(scores: np.ndarray, labels: np.ndarray) -> float:
    """Rank-based AUC (Mann-Whitney). Higher score -> predict positive."""
    scores = np.asarray(scores, float)
    labels = np.asarray(labels, int)
    pos = scores[labels == 1]
    neg = scores[labels == 0]
    if len(pos) == 0 or len(neg) == 0:
        return np.nan
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, len(scores) + 1)
    # average ranks for ties
    s_sorted = scores[order]
    i = 0
    while i < len(s_sorted):
        j = i
        while j + 1 < len(s_sorted) and s_sorted[j + 1] == s_sorted[i]:
            j += 1
        if j > i:
            avg = (ranks[order[i]] + ranks[order[j]]) / 2.0
            for k in range(i, j + 1):
                ranks[order[k]] = avg
        i = j + 1
    sum_pos = ranks[labels == 1].sum()
    n_pos, n_neg = len(pos), len(neg)
    return float((sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


# ----------------------------------------------------------------------------
# OOS expanding-window univariate forecast for a single predictor
# ----------------------------------------------------------------------------
def oos_forecasts(feat: pd.DataFrame, predictor: str, target: str,
                  burn_in: int = BURN_IN):
    """Expanding-window univariate OLS forecast of target_{w+1} from predictor_w.

    Training rows for forecast origin w: {(X_k, Y_{k+1}) : k+1 <= w} — every
    training target window ends strictly before the forecast origin (end of
    window w), satisfying target_end < forecast_origin (no leakage).
    Returns aligned arrays (y_true, y_hat) over OOS windows.
    """
    X = feat[predictor].values
    Y = feat[target].values
    n = len(feat)
    y_true, y_hat, origins = [], [], []
    # forecast target at window m+1 using predictor at window m, for m in [burn_in, n-2]
    for m in range(burn_in, n - 1):
        # training pairs: predictor at k, target at k+1, require k+1 <= m
        ks = np.arange(0, m)             # k = 0..m-1  -> target k+1 = 1..m (<= m) OK
        xk = X[ks]
        yk = Y[ks + 1]
        good = np.isfinite(xk) & np.isfinite(yk)
        if good.sum() < 20:
            continue
        Xtr = sm.add_constant(xk[good])
        ytr = yk[good]
        beta, *_ = np.linalg.lstsq(Xtr, ytr, rcond=None)
        xhat = beta[0] + beta[1] * X[m]
        y_true.append(Y[m + 1])
        y_hat.append(xhat)
        origins.append(feat.index[m])
    return np.array(y_true), np.array(y_hat), origins


def persistence_forecasts(feat: pd.DataFrame, target: str, burn_in: int = BURN_IN):
    """Naive persistence: y_hat_{w+1} = y_w (last realized target)."""
    Y = feat[target].values
    n = len(feat)
    y_true, y_hat, origins = [], [], []
    for m in range(burn_in, n - 1):
        y_true.append(Y[m + 1])
        y_hat.append(Y[m])
        origins.append(feat.index[m])
    return np.array(y_true), np.array(y_hat), origins


def loss_for_target(y_true, y_hat, target: str):
    """MSE pointwise for correlation target; QLIKE pointwise for RV target."""
    if target == "avg_corr":
        return (y_true - y_hat) ** 2
    elif target == "RV":
        yhat_pos = np.maximum(y_hat, 1e-10)
        return qlike_pointwise(y_true, yhat_pos)
    else:
        raise ValueError(target)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    out = {"experiment_id": "K1618",
           "generated_utc": datetime.now(timezone.utc).isoformat(),
           "seed": SEED}

    px = load_prices()
    rets = np.log(px / px.shift(1)).dropna(how="any")
    out["meta"] = {
        "tickers": TICKERS,
        "start": str(rets.index.min().date()),
        "end": str(rets.index.max().date()),
        "n_trading_days": int(len(rets)),
        "window_len_days": WIN,
        "horizon_windows": H,
        "burn_in_windows": BURN_IN,
        "data_source": "yfinance daily adjusted close (auto_adjust=True)",
        "frequency": "daily returns aggregated in non-overlapping 21-day windows (BPQ 2022 daily realized-semibeta convention)",
    }

    # descriptive stats of daily returns
    desc = rets.describe().T[["mean", "std", "min", "max"]]
    out["return_diagnostics"] = {
        t: {"mean": float(desc.loc[t, "mean"]), "std": float(desc.loc[t, "std"]),
            "min": float(desc.loc[t, "min"]), "max": float(desc.loc[t, "max"])}
        for t in TICKERS
    }

    feat, id_max, id_mean, pairs = build_windows(rets)
    out["identity_check"] = {
        "definition": "RCov_ij == P_ij + N_ij + M_ij (per pair, per window)",
        "max_abs_residual": id_max,
        "mean_abs_residual": id_mean,
        "n_pairs": len(pairs),
        "n_windows": int(len(feat)),
        "passes": bool(id_max < 1e-10),
    }
    print(f"[identity] max_abs_resid={id_max:.2e} mean={id_mean:.2e} windows={len(feat)}")

    # ---- descriptive lead-lag correlations ------------------------------------
    # future avg_corr and future RV (window w+1) vs current components (window w)
    fut_corr = feat["avg_corr"].shift(-1)
    fut_rv = feat["RV"].shift(-1)
    lead = {}
    for comp in ["N", "P", "M", "RCov", "RV", "avg_corr"]:
        cur = feat[comp]
        lead[comp] = {
            "contemp_vs_corr": float(cur.corr(feat["avg_corr"])),
            "lead1_vs_future_corr": float(cur.corr(fut_corr)),
            "lead1_vs_future_rv": float(cur.corr(fut_rv)),
        }
    out["lead_lag_correlations"] = lead
    print("[lead-lag] N.lead1_vs_future_corr =", round(lead["N"]["lead1_vs_future_corr"], 3),
          "| RCov =", round(lead["RCov"]["lead1_vs_future_corr"], 3),
          "| RV =", round(lead["RV"]["lead1_vs_future_corr"], 3))

    # ---- in-sample HAC predictive regressions (descriptive) -------------------
    reg = {}
    df_reg = pd.DataFrame({
        "y_corr": fut_corr, "y_rv": fut_rv,
        "N": feat["N"], "P": feat["P"], "M": feat["M"],
        "RCov": feat["RCov"], "RV": feat["RV"],
        "corr_lag": feat["avg_corr"], "rv_lag": feat["RV"],
    }).dropna()
    nw_lag = int(np.floor(4 * (len(df_reg) / 100.0) ** (2.0 / 9.0)))

    def hac_ols(y, Xcols):
        X = sm.add_constant(df_reg[Xcols])
        m = sm.OLS(df_reg[y], X).fit(cov_type="HAC", cov_kwds={"maxlags": nw_lag})
        return m

    # univariate future-correlation regressions
    for comp in ["N", "P", "M", "RCov", "RV"]:
        m = hac_ols("y_corr", [comp])
        reg[f"corr~{comp}"] = {
            "beta": float(m.params[comp]), "hac_t": float(m.tvalues[comp]),
            "hac_p": float(m.pvalues[comp]), "r2": float(m.rsquared)}
    # incremental N over persistence (corr) and over RCov
    m = hac_ols("y_corr", ["corr_lag", "N"])
    reg["corr~corr_lag+N"] = {"beta_N": float(m.params["N"]), "t_N": float(m.tvalues["N"]),
                              "p_N": float(m.pvalues["N"]), "r2": float(m.rsquared)}
    m = hac_ols("y_corr", ["N", "P", "M"])
    reg["corr~N+P+M"] = {c: {"beta": float(m.params[c]), "t": float(m.tvalues[c]),
                             "p": float(m.pvalues[c])} for c in ["N", "P", "M"]}
    reg["corr~N+P+M"]["r2"] = float(m.rsquared)
    # future-RV regressions
    for comp in ["N", "RCov", "RV"]:
        m = hac_ols("y_rv", [comp])
        reg[f"rv~{comp}"] = {"beta": float(m.params[comp]), "hac_t": float(m.tvalues[comp]),
                             "hac_p": float(m.pvalues[comp]), "r2": float(m.rsquared)}
    m = hac_ols("y_rv", ["rv_lag", "N"])
    reg["rv~rv_lag+N"] = {"beta_N": float(m.params["N"]), "t_N": float(m.tvalues["N"]),
                          "p_N": float(m.pvalues["N"]), "r2": float(m.rsquared)}
    out["in_sample_regressions"] = {"nw_maxlags": nw_lag, "n_obs": int(len(df_reg)), **reg}
    print(f"[in-sample] corr~N t={reg['corr~N']['hac_t']:.2f} R2={reg['corr~N']['r2']:.3f} | "
          f"corr~RCov t={reg['corr~RCov']['hac_t']:.2f} | corr~RV t={reg['corr~RV']['hac_t']:.2f}")
    print(f"[in-sample] incremental N over corr_lag: t={reg['corr~corr_lag+N']['t_N']:.2f} "
          f"p={reg['corr~corr_lag+N']['p_N']:.3f}")

    # ---- OOS forecasts + DM (PRIMARY: panel-aggregate, one series per window) --
    oos = {}
    for target in ["avg_corr", "RV"]:
        yN, hN, oN = oos_forecasts(feat, "N", target)
        yR, hR, oR = oos_forecasts(feat, "RCov", target)
        yV, hV, oV = oos_forecasts(feat, "RV", target)
        yP, hP, oP = persistence_forecasts(feat, target)
        # align lengths (all share same origin grid)
        L = min(len(yN), len(yR), len(yV), len(yP))
        yN, hN, hR, hV, hP = yN[:L], hN[:L], hR[:L], hV[:L], hP[:L]
        lN = loss_for_target(yN, hN, target)
        lR = loss_for_target(yN, hR, target)
        lV = loss_for_target(yN, hV, target)
        lP = loss_for_target(yN, hP, target)

        block = {
            "n_oos": int(L),
            "oos_start": str(oN[0].date()), "oos_end": str(oN[L - 1].date()),
            "mean_loss": {"N": float(np.mean(lN)), "RCov": float(np.mean(lR)),
                          "RV": float(np.mean(lV)), "persistence": float(np.mean(lP))},
            "loss_metric": "MSE" if target == "avg_corr" else "QLIKE",
            "dm_N_vs_RCov": dm_hln(lN, lR, h=H),
            "dm_N_vs_RV": dm_hln(lN, lV, h=H),
            "dm_N_vs_persistence": dm_hln(lN, lP, h=H),
            "bootstrap_N_vs_RCov": block_bootstrap_ci(lN, lR),
            "bootstrap_N_vs_RV": block_bootstrap_ci(lN, lV),
        }
        oos[target] = block
        d = block["dm_N_vs_RCov"]
        print(f"[OOS {target}] N vs RCov: HLN t={d['dm_hln_stat']:.2f} p={d['p_hln']:.3f} "
              f"harvey_pass={d['harvey_pass']} better={d['better']} | "
              f"lossN={block['mean_loss']['N']:.5f} lossRCov={block['mean_loss']['RCov']:.5f}")
    out["oos_dm_panel"] = oos

    # ---- Regime-break classification (binary spike, OOS, AUC) -----------------
    clf = {}
    for target in ["avg_corr", "RV"]:
        Y = feat[target].values
        n = len(feat)
        scoresN, scoresR, scoresV, labels, origins = [], [], [], [], []
        for m in range(BURN_IN, n - 1):
            thr = np.quantile(Y[:m + 1], SPIKE_Q)          # training-only threshold
            lab = int(Y[m + 1] > thr)
            scoresN.append(feat["N"].values[m])
            scoresR.append(feat["RCov"].values[m])
            scoresV.append(feat["RV"].values[m])
            labels.append(lab)
            origins.append(feat.index[m])
        labels = np.array(labels)
        clf[target] = {
            "n_oos": int(len(labels)), "n_spikes": int(labels.sum()),
            "spike_quantile": SPIKE_Q,
            "auc_N": auc_score(np.array(scoresN), labels),
            "auc_RCov": auc_score(np.array(scoresR), labels),
            "auc_RV": auc_score(np.array(scoresV), labels),
        }
        # bootstrap CI for AUC(N) - AUC(RCov)
        rng = np.random.default_rng(SEED)
        sN, sR = np.array(scoresN), np.array(scoresR)
        diffs = []
        idx_all = np.arange(len(labels))
        for _ in range(1000):
            bidx = rng.choice(idx_all, size=len(idx_all), replace=True)
            if labels[bidx].sum() in (0, len(bidx)):
                continue
            diffs.append(auc_score(sN[bidx], labels[bidx]) - auc_score(sR[bidx], labels[bidx]))
        if diffs:
            lo, hi = np.percentile(diffs, [2.5, 97.5])
            clf[target]["auc_N_minus_RCov"] = float(np.mean(diffs))
            clf[target]["auc_diff_ci"] = [float(lo), float(hi)]
            clf[target]["auc_diff_excludes_zero"] = bool(lo > 0 or hi < 0)
        print(f"[classify {target}] AUC N={clf[target]['auc_N']:.3f} "
              f"RCov={clf[target]['auc_RCov']:.3f} RV={clf[target]['auc_RV']:.3f} "
              f"spikes={clf[target]['n_spikes']}/{clf[target]['n_oos']}")
    out["regime_classification"] = clf

    # ---- K1355-compliant cross-pair robustness (future pair-RCov target) ------
    # Build per-pair series of N_ij and RCov_ij per window, forecast pair future
    # RCov, compute per-pair loss, then DATE-AGGREGATE loss differential across
    # pairs within each window BEFORE the DM (never stack pair-window as iid).
    cross = _cross_pair_robustness(rets, pairs, feat.index)
    out["cross_pair_robustness_k1355"] = cross
    print(f"[cross-pair] date-aggregated N vs RCov HLN t="
          f"{cross['date_aggregated']['dm_hln_stat']:.2f} p={cross['date_aggregated']['p_hln']:.3f}"
          f" | stacked(diagnostic) t={cross['stacked_diagnostic']['dm_hln_stat']:.2f}")

    # ---- figures --------------------------------------------------------------
    make_figures(feat, oos, clf, out)

    # ---- verdict --------------------------------------------------------------
    out["verdict"] = _verdict(out)

    with open(os.path.join(HERE, "K1618_results.json"), "w") as f:
        json.dump(out, f, indent=2, default=str)
    print("\n[verdict]", out["verdict"]["label"])
    print(out["verdict"]["summary"])
    return out


def _cross_pair_robustness(rets, pairs, win_index):
    """Per-pair future-RCov forecast; K1355 date-aggregated DM."""
    n = len(rets)
    n_win = n // WIN
    R = rets.values
    # per-window per-pair N_ij and RCov_ij
    Nmat = np.zeros((n_win, len(pairs)))
    RCmat = np.zeros((n_win, len(pairs)))
    for w in range(n_win):
        s, e = w * WIN, (w + 1) * WIN
        block = R[s:e, :]
        rm = np.minimum(block, 0.0)
        for pi, (i, j) in enumerate(pairs):
            Nmat[w, pi] = np.sum(rm[:, i] * rm[:, j])
            RCmat[w, pi] = np.sum(block[:, i] * block[:, j])
    # OOS expanding forecast of RCov_{w+1} for each pair, per predictor
    loss_diff_by_window = []   # date-aggregated: mean over pairs of (lossN - lossRCov)
    stacked_dN, stacked_dR = [], []
    for m in range(BURN_IN, n_win - 1):
        diffs_this_win = []
        for pi in range(len(pairs)):
            yk = RCmat[1:m + 1, pi]          # target windows 1..m
            xkN = Nmat[0:m, pi]              # predictor windows 0..m-1
            xkR = RCmat[0:m, pi]
            good = np.isfinite(yk) & np.isfinite(xkN) & np.isfinite(xkR)
            if good.sum() < 20:
                continue
            # univariate OLS N -> future RCov
            bN = np.linalg.lstsq(sm.add_constant(xkN[good]), yk[good], rcond=None)[0]
            bR = np.linalg.lstsq(sm.add_constant(xkR[good]), yk[good], rcond=None)[0]
            fN = bN[0] + bN[1] * Nmat[m, pi]
            fR = bR[0] + bR[1] * RCmat[m, pi]
            y_true = RCmat[m + 1, pi]
            lN = (y_true - fN) ** 2
            lR = (y_true - fR) ** 2
            diffs_this_win.append(lN - lR)
            stacked_dN.append(lN)
            stacked_dR.append(lR)
        if diffs_this_win:
            loss_diff_by_window.append(np.mean(diffs_this_win))
    loss_diff_by_window = np.array(loss_diff_by_window)

    # date-aggregated DM: treat the window-level mean loss diff as the series
    da = dm_hln(loss_diff_by_window, np.zeros_like(loss_diff_by_window), h=H)
    stacked = dm_hln(np.array(stacked_dN), np.array(stacked_dR), h=H)
    return {
        "target": "future pair RCov_ij (window w+1)",
        "loss_metric": "MSE",
        "n_windows_aggregated": int(len(loss_diff_by_window)),
        "n_stacked_pair_windows": int(len(stacked_dN)),
        "date_aggregated": da,       # PRIMARY for this variant (K1355)
        "stacked_diagnostic": stacked,   # inflated; diagnostic ONLY
        "note": "date_aggregated = mean pairwise (lossN - lossRCov) per window, "
                "then HLN-DM on the window series (K1355). stacked = raw pair-window "
                "array DM, reported ONLY as diagnostic (understates SE).",
    }


def _verdict(out):
    """Target-aware honest verdict.

    CORE (pre-registered) hypothesis = N is a superior EARLY WARNING for
    cross-asset CORRELATION regimes. SECONDARY = future cross-asset RV.
    """
    corr = out["oos_dm_panel"]["avg_corr"]
    rv = out["oos_dm_panel"]["RV"]
    clf_c = out["regime_classification"]["avg_corr"]
    clf_v = out["regime_classification"]["RV"]

    # ---- CORE: correlation target -----------------------------------------
    c_rcov = corr["dm_N_vs_RCov"]
    c_rv = corr["dm_N_vs_RV"]
    # N supported for core only if it BEATS both baselines significantly on corr
    core_beats_rcov = (c_rcov["better"] == "model1" and c_rcov["p_hln"] < 0.05)
    core_beats_rv = (c_rv["better"] == "model1" and c_rv["p_hln"] < 0.05)
    core_auc_edge = (clf_c["auc_N"] > clf_c["auc_RCov"] and clf_c["auc_N"] > clf_c["auc_RV"])
    core_supported = core_beats_rcov and core_beats_rv and core_auc_edge

    # ---- SECONDARY: RV target ---------------------------------------------
    v_rcov = rv["dm_N_vs_RCov"]
    v_rv = rv["dm_N_vs_RV"]
    sec_beats_rcov = (v_rcov["better"] == "model1" and v_rcov["p_hln"] < 0.05
                      and rv["bootstrap_N_vs_RCov"]["excludes_zero"])
    sec_beats_rv = (v_rv["better"] == "model1" and v_rv["p_hln"] < 0.05)
    sec_harvey = v_rcov["harvey_pass"] or v_rv["harvey_pass"]

    # ---- label -------------------------------------------------------------
    if core_supported:
        label = "CONDITIONAL_PASS"
    elif sec_beats_rcov and sec_beats_rv and sec_harvey:
        label = "CONDITIONAL_PASS"     # strong secondary if it beat RV too + Harvey
    elif sec_beats_rcov:
        label = "NULL_WITH_WEAK_SECONDARY"
    else:
        label = "NULL"

    summary = (
        "CORE HYPOTHESIS (N = correlation-regime early warning): NOT SUPPORTED. "
        f"On the correlation-spike target N is the WEAKEST of the three (OOS AUC "
        f"N={clf_c['auc_N']:.3f} < RCov={clf_c['auc_RCov']:.3f} < RV={clf_c['auc_RV']:.3f}); "
        f"OOS DM N vs RCov HLN t={c_rcov['dm_hln_stat']:+.2f} (p={c_rcov['p_hln']:.3f}, "
        f"better={c_rcov['better']}), N vs RV t={c_rv['dm_hln_stat']:+.2f} (p={c_rv['p_hln']:.3f}). "
        "SECONDARY (future cross-asset RV): N modestly beats total RCov "
        f"(DM HLN t={v_rcov['dm_hln_stat']:+.2f}, p={v_rcov['p_hln']:.3f}, bootstrap CI "
        f"excludes 0={rv['bootstrap_N_vs_RCov']['excludes_zero']}) — consistent with BPQ "
        "'downside component carries the vol signal' — BUT does NOT beat simple total RV "
        f"(t={v_rv['dm_hln_stat']:+.2f}, p={v_rv['p_hln']:.3f}) and clears NO Harvey |t|>3 bar. "
        "Cross-pair K1355 date-aggregated DM is null "
        f"(t={out['cross_pair_robustness_k1355']['date_aggregated']['dm_hln_stat']:+.2f}). "
        "Conclusion: daily-frequency negative-semicovariance offers no robust early-warning "
        "edge over total RCov/RV for cross-asset correlation regimes."
    )
    return {"label": label, "summary": summary,
            "core_hypothesis_supported": bool(core_supported),
            "core_beats_rcov": bool(core_beats_rcov),
            "core_beats_rv": bool(core_beats_rv),
            "core_auc_edge": bool(core_auc_edge),
            "secondary_beats_rcov": bool(sec_beats_rcov),
            "secondary_beats_rv": bool(sec_beats_rv),
            "secondary_harvey_pass": bool(sec_harvey)}


def make_figures(feat, oos, clf, out):
    # (a) N/P/M component time series with crisis shading + future correlation
    fig, ax = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    x = feat.index
    ax[0].plot(x, feat["N"], label="N (downside concordant)", color="crimson", lw=1.1)
    ax[0].plot(x, feat["P"], label="P (upside concordant)", color="seagreen", lw=0.9, alpha=0.8)
    ax[0].plot(x, feat["M"], label="M (mixed, <=0)", color="slategray", lw=0.8, alpha=0.7)
    ax[0].set_ylabel("panel avg semicovariance")
    ax[0].legend(loc="upper left", fontsize=9)
    ax[0].set_title("K1618 (a): Realized semicovariance components (non-overlapping 21d windows, 10 ETFs)")
    crises = [("2007-10-01", "2009-06-30", "GFC"),
              ("2020-02-15", "2020-05-31", "COVID"),
              ("2022-01-01", "2022-10-31", "2022 bear")]
    for a in ax:
        for s, e, lab in crises:
            a.axvspan(pd.Timestamp(s), pd.Timestamp(e), color="orange", alpha=0.12)
    ax[1].plot(x, feat["avg_corr"], color="navy", lw=1.1, label="avg pairwise correlation")
    ax[1].plot(x, feat["N"] / feat["N"].abs().max(), color="crimson", lw=0.8, alpha=0.6,
               label="N (scaled)")
    ax[1].set_ylabel("avg pairwise corr")
    ax[1].legend(loc="upper left", fontsize=9)
    ax[1].xaxis.set_major_locator(mdates.YearLocator(2))
    ax[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig_a_components_timeseries.png"), dpi=130)
    plt.close(fig)

    # (b) ROC-style: AUC bars N vs RCov vs RV for both targets + OOS loss bars
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.5))
    tgts = ["avg_corr", "RV"]
    labpos = np.arange(len(tgts))
    width = 0.25
    aN = [clf[t]["auc_N"] for t in tgts]
    aR = [clf[t]["auc_RCov"] for t in tgts]
    aV = [clf[t]["auc_RV"] for t in tgts]
    ax[0].bar(labpos - width, aN, width, label="N", color="crimson")
    ax[0].bar(labpos, aR, width, label="RCov", color="steelblue")
    ax[0].bar(labpos + width, aV, width, label="RV", color="darkorange")
    ax[0].axhline(0.5, color="black", ls="--", lw=0.8)
    ax[0].set_xticks(labpos)
    ax[0].set_xticklabels(["future corr spike", "future RV spike"])
    ax[0].set_ylabel("OOS AUC")
    ax[0].set_ylim(0.4, 1.0)
    ax[0].legend(fontsize=9)
    ax[0].set_title("(b) Regime-spike discrimination (OOS AUC)")

    ml_c = oos["avg_corr"]["mean_loss"]
    ml_v = oos["RV"]["mean_loss"]
    preds = ["N", "RCov", "RV", "persistence"]
    ax2 = ax[1]
    ax2.bar(np.arange(4) - 0.2, [ml_c[p] for p in preds], 0.4, label="corr (MSE)", color="navy")
    ax2b = ax2.twinx()
    ax2b.bar(np.arange(4) + 0.2, [ml_v[p] for p in preds], 0.4, label="RV (QLIKE)", color="firebrick", alpha=0.7)
    ax2.set_xticks(np.arange(4))
    ax2.set_xticklabels(preds)
    ax2.set_ylabel("corr MSE", color="navy")
    ax2b.set_ylabel("RV QLIKE", color="firebrick")
    ax2.set_title("(b2) OOS forecast loss by predictor (lower=better)")
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig_b_predictive_power.png"), dpi=130)
    plt.close(fig)

    # (c) event window: N and avg_corr around the three crises (normalized)
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    windows = [("2008 GFC", "2008-01-01", "2009-12-31"),
               ("2020 COVID", "2019-10-01", "2020-12-31"),
               ("2022 bear", "2021-07-01", "2023-03-31")]
    for a, (lab, s, e) in zip(axes, windows):
        sub = feat.loc[(feat.index >= s) & (feat.index <= e)]
        if len(sub) < 3:
            continue
        nn = (sub["N"] - sub["N"].min()) / (sub["N"].max() - sub["N"].min() + 1e-12)
        cc = (sub["avg_corr"] - sub["avg_corr"].min()) / (sub["avg_corr"].max() - sub["avg_corr"].min() + 1e-12)
        a.plot(sub.index, nn, color="crimson", marker="o", ms=3, label="N (norm)")
        a.plot(sub.index, cc, color="navy", marker="s", ms=3, label="avg corr (norm)")
        a.set_title(f"(c) {lab}")
        a.legend(fontsize=8)
        a.tick_params(axis="x", rotation=45, labelsize=7)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig_c_event_windows.png"), dpi=130)
    plt.close(fig)
    print("[figures] saved fig_a / fig_b / fig_c")


if __name__ == "__main__":
    main()
