"""
K1466 — Vol decoupling of SE Asia / frontier EM ETFs (VNM, EIDO, THD, EPHE)
vs developed-market benchmarks (SPY, EFA) and broader EM (EEM).

Honest research code:
  - All rolling stats use past 21d realized vol / past 60d rolling corr (no peek).
  - Bootstrap seeded (seed=42).
  - VIX regime is concurrent (descriptive, not forecast).
  - yfinance: Adj Close; drop joint NaN; log returns.

Run: uv run python experiments/k1466/k1466.py
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

RNG_SEED = 42
HERE = Path(__file__).resolve().parent
FIG_DIR = HERE / "figs"
FIG_DIR.mkdir(exist_ok=True)

EM_TICKERS = ["VNM", "EIDO", "THD", "EPHE"]
BENCH_TICKERS = ["SPY", "EFA", "EEM"]
VIX_TICKER = "^VIX"
ALL = EM_TICKERS + BENCH_TICKERS

START = "2010-05-01"  # EIDO 2010-05; VNM 2009-08; THD 2008-03; EPHE 2010-09
END = "2026-06-10"


def fetch_prices() -> pd.DataFrame:
    print(f"[fetch] {ALL + [VIX_TICKER]} {START} -> {END}")
    data = yf.download(
        ALL + [VIX_TICKER],
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    # auto_adjust=True returns adjusted Close under 'Close'
    px = data["Close"].copy()
    px = px.dropna(how="all")
    print(f"[fetch] raw shape={px.shape}, first={px.index[0].date()}, last={px.index[-1].date()}")
    return px


def compute_returns(px: pd.DataFrame) -> pd.DataFrame:
    r = np.log(px / px.shift(1))
    return r.dropna(how="all")


def annualized_realized_vol(r: pd.Series, window: int = 21) -> pd.Series:
    """RV uses returns r_{t-window+1}..r_t (past info), reported at t."""
    return r.rolling(window).std() * np.sqrt(252)


def fisher_z(rho: float, n: int) -> float:
    return 0.5 * np.log((1 + rho) / (1 - rho)), 1.0 / np.sqrt(n - 3)


def fisher_z_test(rho1: float, n1: int, rho2: float, n2: int) -> tuple[float, float]:
    """H0: rho1 == rho2.  Returns (z, two-sided p)."""
    z1 = 0.5 * np.log((1 + rho1) / (1 - rho1))
    z2 = 0.5 * np.log((1 + rho2) / (1 - rho2))
    se = np.sqrt(1.0 / (n1 - 3) + 1.0 / (n2 - 3))
    z = (z1 - z2) / se
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    return float(z), float(p)


def block_bootstrap_diversification_ratio(
    em_returns: pd.DataFrame, block: int = 20, B: int = 1000, seed: int = RNG_SEED
) -> dict:
    """
    Diversification ratio = (Σ w_i σ_i) / σ_portfolio
    Equal-weight portfolio of EM ETFs.
    Returns mean, sd, 95% CI via stationary block bootstrap (Politis-Romano-ish: fixed block).
    """
    rng = np.random.default_rng(seed)
    arr = em_returns.dropna().to_numpy()
    n, k = arr.shape
    w = np.ones(k) / k
    nblocks = int(np.ceil(n / block))

    point_sigma_i = arr.std(axis=0) * np.sqrt(252)
    point_port = (arr @ w).std() * np.sqrt(252)
    point_DR = float(np.sum(w * point_sigma_i) / point_port)

    boots = np.empty(B)
    for b in range(B):
        starts = rng.integers(0, n - block + 1, size=nblocks)
        idx_blocks = [np.arange(s, s + block) for s in starts]
        idx = np.concatenate(idx_blocks)[:n]
        sample = arr[idx]
        s_i = sample.std(axis=0) * np.sqrt(252)
        s_p = (sample @ w).std() * np.sqrt(252)
        boots[b] = np.sum(w * s_i) / s_p
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return {
        "point": point_DR,
        "boot_mean": float(boots.mean()),
        "boot_sd": float(boots.std(ddof=1)),
        "ci_2_5": float(lo),
        "ci_97_5": float(hi),
        "B": B,
        "block": block,
        "n_obs": int(n),
        "weights": "equal",
    }


def descriptive_stats(r: pd.DataFrame) -> dict:
    out = {}
    for c in r.columns:
        s = r[c].dropna()
        rv = annualized_realized_vol(s, 21)
        out[c] = {
            "n_obs": int(s.shape[0]),
            "first_date": s.index[0].strftime("%Y-%m-%d"),
            "last_date": s.index[-1].strftime("%Y-%m-%d"),
            "ann_mean_vol_rv21": float(rv.mean()),
            "ann_median_vol_rv21": float(rv.median()),
            "ann_sd_of_rv21": float(rv.std()),
            "skew_daily_ret": float(stats.skew(s, bias=False)),
            "kurt_daily_ret_excess": float(stats.kurtosis(s, fisher=True, bias=False)),
            "acf1_daily_ret": float(s.autocorr(lag=1)),
            "acf1_rv21": float(rv.dropna().autocorr(lag=1)),
        }
    return out


def crisis_window_table(rv: pd.DataFrame) -> dict:
    crises = {
        "2015_china_crash": ("2015-06-01", "2015-09-30"),
        "2018_q4": ("2018-10-01", "2018-12-31"),
        "2020_covid": ("2020-02-15", "2020-05-31"),
        "2022_fed_hike": ("2022-02-01", "2022-07-31"),
        "2024_yen_carry": ("2024-07-15", "2024-08-31"),
    }
    table = {}
    for name, (s, e) in crises.items():
        sub = rv.loc[s:e]
        if sub.empty:
            continue
        table[name] = {
            c: {
                "peak_ann_vol": float(sub[c].max()) if sub[c].notna().any() else None,
                "mean_ann_vol": float(sub[c].mean()) if sub[c].notna().any() else None,
            }
            for c in sub.columns
        }
    return table


def regime_conditional_corr(r: pd.DataFrame, vix: pd.Series) -> dict:
    """Concurrent VIX regime. H0: corr in HIGH == corr in LOW."""
    df = r.join(vix.rename("VIX"), how="inner").dropna()
    high = df[df["VIX"] > 25]
    low = df[df["VIX"] < 15]
    out = {
        "n_high": int(high.shape[0]),
        "n_low": int(low.shape[0]),
        "vix_high_threshold": 25,
        "vix_low_threshold": 15,
        "pairs": {},
    }
    benchs = ["SPY", "EFA", "EEM"]
    for em in EM_TICKERS:
        for bench in benchs:
            if em not in df or bench not in df:
                continue
            rho_h = float(high[[em, bench]].corr().iloc[0, 1])
            rho_l = float(low[[em, bench]].corr().iloc[0, 1])
            z, p = fisher_z_test(rho_h, high.shape[0], rho_l, low.shape[0])
            out["pairs"][f"{em}_vs_{bench}"] = {
                "rho_high_vix": rho_h,
                "rho_low_vix": rho_l,
                "delta": rho_h - rho_l,
                "fisher_z": z,
                "p_value": p,
                "significant_5pct": bool(p < 0.05),
            }
    return out


def unconditional_corr(r: pd.DataFrame) -> dict:
    cols = EM_TICKERS + BENCH_TICKERS
    sub = r[cols].dropna()
    pearson = sub.corr(method="pearson").round(4)
    spearman = sub.corr(method="spearman").round(4)
    return {
        "n_obs": int(sub.shape[0]),
        "pearson": pearson.to_dict(),
        "spearman": spearman.to_dict(),
    }


def rolling_corr_summary(r: pd.DataFrame, bench: str = "SPY", win: int = 60) -> dict:
    out = {"benchmark": bench, "window_days": win, "per_em": {}}
    for em in EM_TICKERS:
        if em not in r.columns:
            continue
        rc = r[em].rolling(win).corr(r[bench])
        rc = rc.dropna()
        out["per_em"][em] = {
            "median": float(rc.median()),
            "iqr_25": float(rc.quantile(0.25)),
            "iqr_75": float(rc.quantile(0.75)),
            "min": float(rc.min()),
            "max": float(rc.max()),
            "n_obs": int(rc.shape[0]),
        }
    return out


# ---------- Plots ----------

def plot_vol_series(rv: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    for c in EM_TICKERS:
        if c in rv:
            ax.plot(rv.index, rv[c], lw=0.9, label=c)
    if "SPY" in rv:
        ax.plot(rv.index, rv["SPY"], color="k", lw=1.0, alpha=0.7, label="SPY")
    ax.set_title("K1466 — Annualized 21d Realized Vol: SE Asia EM vs SPY")
    ax.set_ylabel("Ann. Vol")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_rolling_corr(r: pd.DataFrame, bench: str, win: int, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    for em in EM_TICKERS:
        if em in r and bench in r:
            rc = r[em].rolling(win).corr(r[bench])
            ax.plot(rc.index, rc, lw=0.9, label=f"{em} vs {bench}")
    ax.axhline(0, color="k", lw=0.5)
    ax.set_title(f"K1466 — {win}-day Rolling Correlation with {bench}")
    ax.set_ylabel("Pearson rho")
    ax.legend(loc="lower left", fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_regime_bar(reg: dict, path: Path) -> None:
    pairs = [k for k in reg["pairs"] if k.endswith("_vs_SPY")]
    labels = [k.replace("_vs_SPY", "") for k in pairs]
    rho_h = [reg["pairs"][k]["rho_high_vix"] for k in pairs]
    rho_l = [reg["pairs"][k]["rho_low_vix"] for k in pairs]
    x = np.arange(len(labels))
    w = 0.35
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(x - w / 2, rho_l, w, label=f"VIX<15 (n={reg['n_low']})", color="#5b9bd5")
    ax.bar(x + w / 2, rho_h, w, label=f"VIX>25 (n={reg['n_high']})", color="#c0504d")
    for i, k in enumerate(pairs):
        p = reg["pairs"][k]["p_value"]
        marker = "*" if p < 0.05 else "ns"
        ax.text(i, max(rho_h[i], rho_l[i]) + 0.02, f"p={p:.3f}{marker}", ha="center", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Correlation with SPY")
    ax.set_title("K1466 — Regime-Conditional Correlation (Fisher z test)")
    ax.legend()
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_diversification_over_time(em_r: pd.DataFrame, path: Path, win: int = 252) -> None:
    w = np.ones(em_r.shape[1]) / em_r.shape[1]
    sigma_port = em_r.rolling(win).apply(lambda x: x.std() * np.sqrt(252), raw=False).mean(axis=1)
    # rolling DR
    rolling_DR = []
    arr = em_r.to_numpy()
    n = len(arr)
    idx_all = em_r.index
    for t in range(win, n):
        window = arr[t - win : t]
        s_i = window.std(axis=0) * np.sqrt(252)
        s_p = (window @ w).std() * np.sqrt(252)
        rolling_DR.append(np.sum(w * s_i) / s_p)
    dr_series = pd.Series(rolling_DR, index=idx_all[win:])
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(dr_series.index, dr_series.values, lw=1.0, color="#2e7d32")
    ax.axhline(1.0, color="k", lw=0.5, ls="--")
    ax.set_title("K1466 — 252-day Rolling Diversification Ratio (equal-weight 4 EM ETFs)")
    ax.set_ylabel("DR")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def main() -> dict:
    np.random.seed(RNG_SEED)
    px = fetch_prices()

    # restrict to ETFs we want; VIX kept separate
    vix = px[VIX_TICKER].copy()
    px_etf = px[ALL].copy()

    # common sample period for ETFs: from first date all are non-NaN
    first_valid = px_etf.dropna().index[0]
    print(f"[sample] common-start={first_valid.date()}")
    px_etf = px_etf.loc[first_valid:]
    px_etf = px_etf.dropna(how="any")

    r = compute_returns(px_etf)
    rv = px_etf.apply(lambda c: np.log(c / c.shift(1)).rolling(21).std() * np.sqrt(252))

    desc = descriptive_stats(r)
    crises = crisis_window_table(rv)
    uncond = unconditional_corr(r)
    roll = rolling_corr_summary(r, bench="SPY", win=60)
    regime = regime_conditional_corr(r, vix)
    div_ratio = block_bootstrap_diversification_ratio(r[EM_TICKERS])

    # Plots
    plot_vol_series(rv, FIG_DIR / "fig1_vol_series.png")
    plot_rolling_corr(r, "SPY", 60, FIG_DIR / "fig2_rolling_corr_spy.png")
    plot_regime_bar(regime, FIG_DIR / "fig3_regime_corr_bar.png")
    plot_diversification_over_time(r[EM_TICKERS], FIG_DIR / "fig4_diversification_ratio.png")

    # ---- Verdict logic ----
    # Decoupling claim survives if:
    #   (a) rolling 60d corr median with SPY clearly < EEM-SPY benchmark, AND
    #   (b) regime-conditional Fisher z does NOT show universal crisis convergence
    #   (c) diversification ratio bootstrap CI strictly > 1 (meaningful)
    em_spy_medians = [roll["per_em"][em]["median"] for em in EM_TICKERS if em in roll["per_em"]]
    eem_spy_median = float(r["EEM"].rolling(60).corr(r["SPY"]).median())
    em_below_eem = sum(1 for m in em_spy_medians if m < eem_spy_median)

    sig_crisis_jumps = sum(
        1
        for k, v in regime["pairs"].items()
        if k.endswith("_vs_SPY") and v["significant_5pct"] and v["delta"] > 0
    )

    dr_ci_above_1 = div_ratio["ci_2_5"] > 1.0

    # Heuristic verdict
    if em_below_eem >= 3 and dr_ci_above_1 and sig_crisis_jumps <= 2:
        verdict = "PASS"
        headline = "SE Asia frontier ETFs show partial vol decoupling: SPY correlation below EEM benchmark and diversification ratio bootstrap CI > 1."
    elif em_below_eem >= 2 and dr_ci_above_1:
        verdict = "CONDITIONAL_PASS"
        headline = "Mixed decoupling evidence: diversification ratio CI > 1 but only some EM ETFs sit below the EEM-SPY correlation benchmark."
    elif dr_ci_above_1 and em_below_eem <= 1:
        verdict = "NULL"
        headline = "No meaningful vol decoupling: ETFs co-move with SPY at or above EEM levels despite positive diversification ratio."
    else:
        verdict = "NULL"
        headline = "Diversification ratio bootstrap CI does not exclude 1; vol decoupling not demonstrated."

    results = {
        "k_id": "K1466",
        "verdict": verdict,
        "headline": headline,
        "rng_seed": RNG_SEED,
        "sample": {
            "start": str(first_valid.date()),
            "end": str(px_etf.index[-1].date()),
            "n_obs_returns": int(r.shape[0]),
            "tickers_em": EM_TICKERS,
            "tickers_bench": BENCH_TICKERS,
        },
        "descriptive": desc,
        "crisis_windows_ann_vol": crises,
        "unconditional_corr": uncond,
        "rolling_corr_60d_vs_spy": roll,
        "eem_spy_60d_rolling_corr_median": eem_spy_median,
        "n_em_below_eem_spy_corr_median": int(em_below_eem),
        "regime_conditional_corr": regime,
        "n_significant_crisis_corr_increases_vs_spy": int(sig_crisis_jumps),
        "diversification_ratio_bootstrap": div_ratio,
        "dr_ci_strictly_above_1": bool(dr_ci_above_1),
        "limitations": (
            "yfinance daily auto_adjust prices; thin trading on VNM/EIDO/THD/EPHE may bias vol "
            "estimates (stale-price noise inflates idiosyncratic vol, depresses synchronous corr). "
            "VIX regime classification is concurrent (descriptive, not a forecasting signal). "
            "DCC-GARCH deferred to future work. Bootstrap block size 20 chosen by convention; "
            "results robust to ±50% block size not formally verified."
        ),
        "key_numbers": {
            "rolling60_median_corr_vs_spy": {
                em: roll["per_em"].get(em, {}).get("median") for em in EM_TICKERS
            },
            "eem_spy_60d_median": eem_spy_median,
            "diversification_ratio_point": div_ratio["point"],
            "diversification_ratio_ci": [div_ratio["ci_2_5"], div_ratio["ci_97_5"]],
            "n_significant_crisis_corr_jumps": int(sig_crisis_jumps),
        },
    }

    (HERE / "k1466_results.json").write_text(json.dumps(results, indent=2, default=str))
    print(f"\n[VERDICT] {verdict}\n{headline}\n")
    print(f"[output] {HERE / 'k1466_results.json'}")
    return results


if __name__ == "__main__":
    main()
