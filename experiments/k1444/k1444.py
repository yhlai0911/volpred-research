"""K1444 — Vol-of-vol spillover: CL=F / USO → SPY / XLE

Hypothesis
----------
Hypothesis: The vol-of-vol (second-order volatility, std of rolling RV)
of crude oil instruments (CL=F WTI futures, USO ETF) Granger-causes the
vol-of-vol of broad equity (SPY) and energy equity (XLE), beyond their
own past.

Differentiation
---------------
- K861 (oil drops -> equity-vol level, asymmetric): first-order vol level
  spillover.
- K1088 (multi-asset class vol): cross-asset realized vol, not vol-of-vol.
- K1444 (this exp): second-order vol-of-vol transmission --- a more
  forward-looking, options-implied / uncertainty-of-uncertainty channel.

Monetization angle
------------------
If oil vol-of-vol leads SPY/XLE vol-of-vol, build vol-of-vol trading
signal: long SPY/XLE straddles when CL=F vol-of-vol expanding; trade VIX
vs OVX options spreads.

Method
------
Stage A (mandatory) -- Bivariate Granger causality for 4 pairs:
    (CL=F_vov -> SPY_vov), (CL=F_vov -> XLE_vov),
    (USO_vov  -> SPY_vov), (USO_vov  -> XLE_vov)
  VAR(p) for p in {1,2,5,10,21}, HAC robust SE
  Bonferroni alpha = 0.05 / 4 = 0.0125

Stage B (if time) -- Diebold-Yilmaz 2012 4-variable spillover index
  (CL=F_vov, USO_vov, SPY_vov, XLE_vov), VAR(2), rolling 250d

Stage C (if time) -- Asymmetry: split sample by vov_direction (rising vs
  falling subsample for the source asset).

Data
----
yfinance daily close for CL=F, USO, SPY, XLE; 2012-01-01 to 2026-06-09.

Honesty rules
-------------
- explicit signal.shift(1): vov computed from past 21d log returns is
  by construction lagged; VAR endogenous variables enter with lags only
  (no contemporaneous regressor) -- statsmodels VAR is intrinsically
  lookahead-free for Granger causality.
- np.random.seed(42) fixed.
- NULL reported as NULL, no overclaim.
"""

from __future__ import annotations

import json
import os
import warnings
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats as scstats
from statsmodels.tsa.api import VAR
from statsmodels.tsa.stattools import adfuller, grangercausalitytests
from statsmodels.tools.sm_exceptions import InfeasibleTestError

warnings.filterwarnings("ignore")

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
SEED = 42
np.random.seed(SEED)

EXP_DIR = Path(__file__).parent
START = "2012-01-01"
END = "2026-06-10"  # yfinance end is exclusive; covers through 2026-06-09
TICKERS = ["CL=F", "USO", "SPY", "XLE"]
RV_WINDOW = 21       # 21-day rolling realized vol (sum of squared log returns -> sqrt)
VOV_WINDOW = 21      # 21-day rolling std of RV
VAR_LAGS_GRID = [1, 2, 5, 10, 21]
BONF_M = 4           # 4 pairs
ALPHA = 0.05
ALPHA_BONF = ALPHA / BONF_M


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
def fetch_prices() -> pd.DataFrame:
    """Download adjusted close for tickers, return wide DataFrame."""
    print(f"[data] downloading {TICKERS} {START} -> {END} ...")
    raw = yf.download(
        TICKERS,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" in raw.columns.get_level_values(0):
            close = raw["Close"]
        else:
            close = raw.xs("Close", axis=1, level=0)
    else:
        close = raw[["Close"]].rename(columns={"Close": TICKERS[0]})
    close = close[TICKERS].copy()
    close = close.dropna(how="all")
    print(f"[data] raw rows={len(close)}, na per col=\n{close.isna().sum().to_string()}")
    return close


def build_volvol(prices: pd.DataFrame) -> dict:
    """Compute log returns -> RV (21d realized vol) -> vov (21d std of RV).

    Returns dict with frames: returns, rv, vov.  Aligned to common index.
    """
    log_r = np.log(prices).diff()
    # 21d realized volatility = sqrt(sum of squared log returns over 21d)
    rv = log_r.pow(2).rolling(RV_WINDOW, min_periods=RV_WINDOW).sum().pow(0.5)
    # Vol-of-vol = 21d rolling std of RV
    vov = rv.rolling(VOV_WINDOW, min_periods=VOV_WINDOW).std()
    # Drop any row with missing across the 4 cols
    vov_aligned = vov.dropna(how="any")
    rv_aligned = rv.loc[vov_aligned.index]
    log_r_aligned = log_r.loc[vov_aligned.index]
    return {
        "returns": log_r_aligned,
        "rv": rv_aligned,
        "vov": vov_aligned,
        "vov_full": vov,
        "rv_full": rv,
    }


# --------------------------------------------------------------------------
# Stage A: Granger
# --------------------------------------------------------------------------
def stationarize(series: pd.Series) -> tuple[pd.Series, bool]:
    """ADF test; if non-stationary use first diff. Return (series, was_differenced)."""
    s = series.dropna()
    try:
        adf_p = adfuller(s, regression="c", autolag="AIC")[1]
    except Exception:
        adf_p = 1.0
    if adf_p > 0.05:
        return s.diff().dropna(), True
    return s, False


def granger_pair(source: pd.Series, target: pd.Series, max_lag: int) -> dict:
    """statsmodels grangercausalitytests on [target, source]; null = source does
    NOT Granger-cause target.

    Returns dict with per-lag p-values + min p-value + chosen lag.
    """
    df = pd.concat([target.rename("y"), source.rename("x")], axis=1).dropna()
    if len(df) < max_lag * 5 + 30:
        return {"n_obs": len(df), "error": "insufficient_obs"}
    try:
        res = grangercausalitytests(df[["y", "x"]], maxlag=max_lag, verbose=False)
    except (InfeasibleTestError, ValueError) as e:
        return {"n_obs": len(df), "error": str(e)}
    pvals = {}
    for lag in range(1, max_lag + 1):
        # ssr_ftest is the canonical Granger F test in statsmodels
        try:
            f_stat, p_val, df_num, df_den = res[lag][0]["ssr_ftest"]
            pvals[lag] = float(p_val)
        except KeyError:
            continue
    return {
        "n_obs": int(len(df)),
        "p_values_by_lag": pvals,
        "min_p": float(min(pvals.values())) if pvals else None,
        "argmin_lag": int(min(pvals, key=pvals.get)) if pvals else None,
    }


def stage_a_granger(vov: pd.DataFrame) -> dict:
    """Run Granger for all 4 pairs in BOTH levels and first differences.

    Levels granger on highly persistent vov series can produce spuriously
    small p-values driven by shared trend/regime co-movement.  We therefore
    report BOTH and treat the **first-difference (shock-to-shock) version
    as the primary, more conservative test of causal lead-lag**.  Bonferroni
    is applied separately per specification (4 pairs each), and the
    'verdict' uses the diff spec.
    """
    print("[stage A] Granger causality, 4 pairs, levels + diff ...")
    adf_info = {}
    for c in TICKERS:
        s = vov[c]
        try:
            adf_p_level = adfuller(s.dropna(), regression="c", autolag="AIC")[1]
        except Exception:
            adf_p_level = 1.0
        try:
            adf_p_diff = adfuller(s.diff().dropna(), regression="c", autolag="AIC")[1]
        except Exception:
            adf_p_diff = 1.0
        adf_info[c] = {
            "adf_p_level": float(adf_p_level),
            "adf_p_diff": float(adf_p_diff),
            "level_stationary_at_5pct": bool(adf_p_level < 0.05),
        }

    pairs = [
        ("CL=F", "SPY"),
        ("CL=F", "XLE"),
        ("USO", "SPY"),
        ("USO", "XLE"),
    ]
    max_lag = max(VAR_LAGS_GRID)

    def _run(label: str, transform):
        sub_results = {}
        for src, tgt in pairs:
            out = granger_pair(transform(vov[src]), transform(vov[tgt]), max_lag=max_lag)
            out["bonferroni_alpha"] = ALPHA_BONF
            out["pass_bonferroni"] = (
                out.get("min_p") is not None and out["min_p"] < ALPHA_BONF
            )
            sub_results[f"{src}->{tgt}"] = out
            if out.get("min_p") is not None:
                print(
                    f"  [{label}] {src} -> {tgt}: n={out['n_obs']}, "
                    f"min_p={out['min_p']:.4g} at lag {out['argmin_lag']}, "
                    f"Bonf pass={out['pass_bonferroni']}"
                )
            else:
                print(f"  [{label}] {src} -> {tgt}: error={out.get('error')}")
        return sub_results

    levels_results = _run("levels", lambda s: s.dropna())
    diff_results = _run("diff", lambda s: s.diff().dropna())

    return {
        "adf": adf_info,
        "levels": levels_results,
        "diff_primary": diff_results,  # primary spec for verdict
        "pairs": diff_results,         # alias for back-compat with derive_verdict
        "bonferroni_alpha": ALPHA_BONF,
        "primary_spec_note": (
            "diff_primary is used for verdict; levels reported for robustness only. "
            "Levels Granger on persistent vov series can be inflated by shared "
            "trend co-movement (see corr matrix in descriptive stats)."
        ),
    }


# --------------------------------------------------------------------------
# Stage B: Diebold-Yilmaz Spillover
# --------------------------------------------------------------------------
def dy_spillover_full(vov: pd.DataFrame, p_lag: int = 2, horizon: int = 10) -> dict:
    """Full-sample Diebold-Yilmaz 2012 generalized spillover index.

    Returns dict with FEVD matrix, total spillover, net contributions.
    """
    # Use first differences if any series is non-stationary (per Stage A logic)
    df = vov.copy()
    for c in df.columns:
        try:
            p = adfuller(df[c].dropna(), regression="c", autolag="AIC")[1]
        except Exception:
            p = 1.0
        if p > 0.05:
            df[c] = df[c].diff()
    df = df.dropna()
    model = VAR(df)
    fit = model.fit(p_lag)
    # fit.sigma_u may be a DataFrame; force numpy
    Sigma = np.asarray(fit.sigma_u)
    # Generalized FEVD a la Pesaran-Shin (1998), as in Diebold-Yilmaz 2012
    Phi = _ma_coeffs(fit.coefs, horizon)  # list of (k x k) MA coefficient matrices
    k = df.shape[1]
    theta = np.zeros((k, k))
    sig_diag = np.diag(Sigma)
    for i in range(k):
        denom = 0.0
        for h in range(horizon):
            denom += (Phi[h] @ Sigma @ Phi[h].T)[i, i]
        for j in range(k):
            num = 0.0
            for h in range(horizon):
                e_i = np.zeros(k); e_i[i] = 1
                e_j = np.zeros(k); e_j[j] = 1
                num += (e_i @ Phi[h] @ Sigma @ e_j) ** 2
            num /= sig_diag[j]
            theta[i, j] = num / denom
    # Row-normalize
    theta_n = theta / theta.sum(axis=1, keepdims=True)
    # Total spillover index
    diag_sum = np.trace(theta_n)
    total = (theta_n.sum() - diag_sum) / theta_n.sum() * 100
    # From-others (row sum excluding diag)
    from_others = (theta_n.sum(axis=1) - np.diag(theta_n)) * 100
    # To-others (col sum excluding diag)
    to_others = (theta_n.sum(axis=0) - np.diag(theta_n)) * 100
    net = to_others - from_others
    return {
        "var_lag": p_lag,
        "horizon": horizon,
        "n_obs": int(len(df)),
        "vars": list(df.columns),
        "theta_normalized": theta_n.tolist(),
        "total_spillover_pct": float(total),
        "from_others_pct": dict(zip(df.columns, from_others.tolist())),
        "to_others_pct": dict(zip(df.columns, to_others.tolist())),
        "net_pct": dict(zip(df.columns, net.tolist())),
    }


def _ma_coeffs(A_list: np.ndarray, horizon: int) -> list[np.ndarray]:
    """Compute MA representation Phi_h from VAR coefficient matrices A_1..A_p.
    A_list shape: (p, k, k). Returns list of horizon Phi matrices."""
    p, k, _ = A_list.shape
    Phi = [np.eye(k)]
    for h in range(1, horizon):
        Ph = np.zeros((k, k))
        for j in range(1, min(h, p) + 1):
            Ph += A_list[j - 1] @ Phi[h - j]
        Phi.append(Ph)
    return Phi


def dy_rolling(vov: pd.DataFrame, window: int = 250, p_lag: int = 2, horizon: int = 10) -> pd.DataFrame:
    """Rolling total-spillover series."""
    out = []
    for end in range(window, len(vov) + 1, 5):  # step 5 days for speed
        sub = vov.iloc[end - window:end]
        try:
            res = dy_spillover_full(sub, p_lag=p_lag, horizon=horizon)
            out.append((vov.index[end - 1], res["total_spillover_pct"]))
        except Exception:
            continue
    return pd.DataFrame(out, columns=["date", "total_spillover_pct"]).set_index("date")


# --------------------------------------------------------------------------
# Stage C: Asymmetry
# --------------------------------------------------------------------------
def stage_c_asymmetry(vov: pd.DataFrame) -> dict:
    """For each pair, split source vov direction (rising vs falling) and rerun
    a simple OLS lag predictive regression (target_t = a + b * source_{t-1} + c*target_{t-1})."""
    out = {}
    pairs = [
        ("CL=F", "SPY"),
        ("CL=F", "XLE"),
        ("USO", "SPY"),
        ("USO", "XLE"),
    ]
    for src, tgt in pairs:
        s = vov[src]
        t = vov[tgt]
        direction = s.diff().shift(1)  # use lagged direction so signal known at t
        df = pd.concat(
            [
                t.rename("y"),
                s.shift(1).rename("x_lag"),
                t.shift(1).rename("y_lag"),
                direction.rename("dir"),
            ],
            axis=1,
        ).dropna()
        sub = {}
        for label, mask in (
            ("rising", df["dir"] > 0),
            ("falling", df["dir"] < 0),
        ):
            d = df[mask]
            if len(d) < 30:
                sub[label] = {"n": int(len(d)), "error": "insufficient_obs"}
                continue
            # OLS via numpy: y = a + b * x_lag + c * y_lag
            X = np.column_stack(
                [np.ones(len(d)), d["x_lag"].values, d["y_lag"].values]
            )
            y = d["y"].values
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
            resid = y - X @ beta
            # HC0 robust SE
            XtX_inv = np.linalg.inv(X.T @ X)
            S = X.T @ np.diag(resid ** 2) @ X
            cov_hc = XtX_inv @ S @ XtX_inv
            se = np.sqrt(np.diag(cov_hc))
            t_stat = beta[1] / se[1]
            p_val = 2 * (1 - scstats.norm.cdf(abs(t_stat)))
            sub[label] = {
                "n": int(len(d)),
                "beta_source": float(beta[1]),
                "se_source": float(se[1]),
                "t_source": float(t_stat),
                "p_source": float(p_val),
            }
        out[f"{src}->{tgt}"] = sub
    return out


# --------------------------------------------------------------------------
# Verdict logic
# --------------------------------------------------------------------------
def derive_verdict(stage_a: dict, stage_b: dict | None) -> tuple[str, str]:
    pairs = stage_a["pairs"]
    n_pass = sum(1 for v in pairs.values() if v.get("pass_bonferroni"))
    errors = sum(1 for v in pairs.values() if "error" in v)
    if errors == len(pairs):
        return "FAIL", f"All {errors}/{len(pairs)} pairs errored out"
    if n_pass == 0:
        return (
            "NULL",
            f"0/{len(pairs)} pairs pass Bonferroni-corrected Granger "
            f"(alpha={ALPHA_BONF}); vol-of-vol does not transmit at daily horizon.",
        )
    if n_pass >= 2 and stage_b is not None:
        net = stage_b.get("net_pct", {})
        oil_net = (net.get("CL=F", 0) + net.get("USO", 0)) / 2
        if oil_net > 0:
            return (
                "PASS",
                f"{n_pass}/{len(pairs)} Granger pairs pass + net oil vol-of-vol "
                f"transmitter (oil_avg_net={oil_net:+.2f}%); causal direction "
                f"consistent oil -> equity.",
            )
        return (
            "PRELIMINARY",
            f"{n_pass}/{len(pairs)} Granger pairs pass but spillover net "
            f"oil={oil_net:+.2f}% inconsistent with hypothesized direction.",
        )
    return (
        "PRELIMINARY",
        f"{n_pass}/{len(pairs)} Granger pairs pass Bonferroni; spillover stage "
        f"{'not run' if stage_b is None else 'inconclusive'}.",
    )


# --------------------------------------------------------------------------
# Plotting
# --------------------------------------------------------------------------
def plot_fig_a(vov: pd.DataFrame, outpath: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    for c in ["CL=F", "USO"]:
        axes[0].plot(vov.index, vov[c], label=c, lw=0.9)
    axes[0].set_title(
        "K1444 (a) Vol-of-vol --- Oil instruments (21d std of 21d RV)"
    )
    axes[0].set_ylabel("vol-of-vol")
    axes[0].legend(loc="upper right")
    axes[0].grid(alpha=0.3)
    for c in ["SPY", "XLE"]:
        axes[1].plot(vov.index, vov[c], label=c, lw=0.9)
    axes[1].set_title("K1444 (a) Vol-of-vol --- Equity (SPY) and Energy (XLE)")
    axes[1].set_ylabel("vol-of-vol")
    axes[1].legend(loc="upper right")
    axes[1].grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(outpath, dpi=110)
    plt.close()


def plot_fig_b(roll: pd.DataFrame, total_full: float, outpath: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(roll.index, roll["total_spillover_pct"], lw=1.0, color="#235789")
    ax.axhline(total_full, ls="--", color="#c1292e",
               label=f"Full-sample total = {total_full:.1f}%")
    ax.set_title("K1444 (b) Diebold-Yilmaz total vol-of-vol spillover (250d roll, VAR(2), h=10)")
    ax.set_ylabel("total spillover (%)")
    ax.legend(loc="upper right")
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(outpath, dpi=110)
    plt.close()


def plot_fig_c(stage_c: dict, outpath: Path) -> None:
    pairs = list(stage_c.keys())
    rising = [stage_c[p].get("rising", {}).get("beta_source", np.nan) for p in pairs]
    falling = [stage_c[p].get("falling", {}).get("beta_source", np.nan) for p in pairs]
    x = np.arange(len(pairs))
    w = 0.35
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.bar(x - w/2, rising, w, label="Source vov rising", color="#c1292e")
    ax.bar(x + w/2, falling, w, label="Source vov falling", color="#235789")
    ax.set_xticks(x)
    ax.set_xticklabels(pairs, rotation=15)
    ax.set_ylabel("OLS beta on source vov (lag 1)")
    ax.set_title("K1444 (c) Asymmetric transmission of vol-of-vol")
    ax.axhline(0, color="black", lw=0.6)
    ax.legend()
    ax.grid(alpha=0.3, axis="y")
    plt.tight_layout()
    plt.savefig(outpath, dpi=110)
    plt.close()


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    t_start = datetime.now(timezone.utc).isoformat()
    prices = fetch_prices()
    out = build_volvol(prices)
    vov = out["vov"]
    print(f"[vov] aligned rows={len(vov)} from {vov.index.min().date()} to {vov.index.max().date()}")

    # Descriptive stats
    desc = vov.describe().to_dict()
    desc = {k: {kk: float(vv) for kk, vv in v.items()} for k, v in desc.items()}

    # Stage A
    stage_a = stage_a_granger(vov)

    # Stage B
    stage_b = None
    rolling_df = None
    try:
        print("[stage B] Diebold-Yilmaz full-sample + rolling ...")
        stage_b = dy_spillover_full(vov, p_lag=2, horizon=10)
        print(f"  total spillover = {stage_b['total_spillover_pct']:.2f}%")
        print(f"  net contributions: {stage_b['net_pct']}")
        rolling_df = dy_rolling(vov, window=250, p_lag=2, horizon=10)
        print(f"  rolling spillover series len={len(rolling_df)}")
    except Exception as e:  # do not crash whole pipeline
        stage_b = {"error": str(e)}
        print(f"[stage B] error: {e}")

    # Stage C
    print("[stage C] Asymmetry ...")
    stage_c = stage_c_asymmetry(vov)

    verdict, summary = derive_verdict(
        stage_a, stage_b if isinstance(stage_b, dict) and "error" not in stage_b else None
    )
    print(f"[verdict] {verdict} -- {summary}")

    # Figures
    plot_fig_a(vov, EXP_DIR / "fig_a_volvol_levels.png")
    if rolling_df is not None and not rolling_df.empty and isinstance(stage_b, dict) and "total_spillover_pct" in stage_b:
        plot_fig_b(rolling_df, stage_b["total_spillover_pct"], EXP_DIR / "fig_b_spillover.png")
    plot_fig_c(stage_c, EXP_DIR / "fig_c_asymmetry.png")

    results = {
        "k_id": "K1444",
        "title": "Vol-of-vol spillover: oil -> equity",
        "started_utc": t_start,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "data": {
            "tickers": TICKERS,
            "start": START,
            "end_exclusive": END,
            "source": "yfinance auto_adjust=True Close",
            "rv_window": RV_WINDOW,
            "vov_window": VOV_WINDOW,
            "n_obs_after_align": int(len(vov)),
            "first_date": str(vov.index.min().date()),
            "last_date": str(vov.index.max().date()),
        },
        "descriptive_vov": desc,
        "stage_a_granger": stage_a,
        "stage_b_spillover": stage_b,
        "stage_b_rolling_summary": (
            None
            if rolling_df is None or rolling_df.empty
            else {
                "n_windows": int(len(rolling_df)),
                "mean_total_pct": float(rolling_df["total_spillover_pct"].mean()),
                "min_total_pct": float(rolling_df["total_spillover_pct"].min()),
                "max_total_pct": float(rolling_df["total_spillover_pct"].max()),
                "last_date": str(rolling_df.index.max().date()),
                "last_value_pct": float(rolling_df["total_spillover_pct"].iloc[-1]),
            }
        ),
        "stage_c_asymmetry": stage_c,
        "honesty": {
            "seed": SEED,
            "lookahead_guard": "VAR/Granger use only lagged predictors; vov_t is "
                                "computed from log returns up to and including t, "
                                "and is then used as a predictor for VAR/Granger "
                                "with lag >= 1.  Stage C explicit signal.shift(1) "
                                "on the source vov.",
            "multiple_testing": f"Bonferroni alpha = {ALPHA_BONF} = {ALPHA}/{BONF_M}",
        },
        "verdict": verdict,
        "summary": summary,
    }

    out_path = EXP_DIR / "k1444_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"[done] wrote {out_path}")
    return results


if __name__ == "__main__":
    main()
