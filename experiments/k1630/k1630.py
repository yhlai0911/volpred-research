"""
K1630 — "Sell in May and go away" / Halloween Indicator myth verification.

Research question
-----------------
Are November-April ("winter") monthly returns significantly higher than
May-October ("summer") monthly returns? Focus: does the effect still hold in
the LAST ~15 YEARS (2011-01 onward) for Taiwan (TAIEX) and the US (S&P 500),
versus the full historical sample?

Design / provenance
--------------------
* US index  : S&P 500 price index  (^GSPC) daily Close, snapshot from
              experiments/k1410/data/GSPC.csv  -> data/GSPC_snapshot.csv
* TW index  : TAIEX price index     (^TWII) daily Close, snapshot ->
              data/TWII_snapshot.csv
* ETF robustness (total return, AdjClose): SPY (2016+), 0050.TW (2009+) from
  data/cache/price_cache.db -> data/SPY_snapshot.csv, data/0050TW_snapshot.csv

Method
------
1. Calendar-month SIMPLE returns from daily Close (month-end resample, pct_change).
2. Season dummy D = 1 if month in {Nov,Dec,Jan,Feb,Mar,Apr} else 0 (winter/summer half).
3. OLS  r_m = alpha + beta*D + eps  with Newey-West HAC SE (auto lag + L=12).
   beta = mean(Nov-Apr) - mean(May-Oct). beta>0 & significant => Halloween effect.
4. Welch two-sample t-test (unequal variance) as corroboration.
5. Halloween-timing strategy (hold index Nov-Apr, cash=0 May-Oct) vs buy-and-hold.
6. Circular block bootstrap (block=12 months, seed=1630, 2000 reps) 95% CI for mean diff.

Lookahead / timing legality
---------------------------
* A calendar-month return is fully realized at month-end; the SEASON label is a
  deterministic function of the calendar month, known ex-ante. The regression
  r_m ~ D therefore has NO lookahead.
* Strategy switching (enter at end-Oct, exit at end-Apr) is calendar-determined
  and ex-ante known; no future information is used. strat_ret[m] = idx_ret[m] if
  month(m) in winter else 0 (cash). Entry/exit assumed at month-end close.

All random procedures use a fixed seed (1630).
"""

import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import scipy.stats as sstats
import statsmodels.api as sm
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

SEED = 1630
np.random.seed(SEED)
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
WINTER = [11, 12, 1, 2, 3, 4]  # Nov-Apr (Halloween "hold" half)
LAST15_START = "2011-01-01"

# ---------------------------------------------------------------- data loading


def load_close(path, close_col="Close"):
    df = pd.read_csv(path)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.dropna(subset=[close_col])
    df = df[df[close_col] > 0]
    df = df.sort_values("Date").set_index("Date")
    return df[close_col].astype(float)


def monthly_returns(close):
    """Simple calendar-month returns from daily Close (month-end resample)."""
    m = close.resample("ME").last()
    r = m.pct_change(fill_method=None).dropna()
    out = pd.DataFrame({"ret": r})
    out["month"] = out.index.month
    out["winter"] = out["month"].isin(WINTER).astype(int)
    return out


# ---------------------------------------------------------------- statistics


def nw_auto_lag(T):
    return int(np.floor(4 * (T / 100.0) ** (2.0 / 9.0)))


def season_stats(df):
    w = df[df.winter == 1]["ret"].values
    s = df[df.winter == 0]["ret"].values

    def grp(x):
        mu = float(np.mean(x))
        sd = float(np.std(x, ddof=1))
        return {
            "n": int(len(x)),
            "mean_monthly": mu,
            "std_monthly": sd,
            "mean_ann_pct": mu * 12 * 100,
            "sharpe_ann": float(mu / sd * np.sqrt(12)) if sd > 0 else None,
        }

    nov_apr, may_oct = grp(w), grp(s)

    # OLS with HAC (Newey-West)
    y = df["ret"].values
    X = sm.add_constant(df["winter"].values.astype(float))
    T = len(y)
    L_auto = nw_auto_lag(T)
    res_auto = sm.OLS(y, X).fit(
        cov_type="HAC", cov_kwds={"maxlags": L_auto, "use_correction": True}
    )
    res_l12 = sm.OLS(y, X).fit(
        cov_type="HAC", cov_kwds={"maxlags": 12, "use_correction": True}
    )
    beta = float(res_auto.params[1])
    hac = {
        "beta_mean_diff_monthly": beta,
        "beta_ann_pct": beta * 12 * 100,
        "nw_lag_auto": L_auto,
        "se_hac_auto": float(res_auto.bse[1]),
        "t_hac_auto": float(res_auto.tvalues[1]),
        "p_hac_auto": float(res_auto.pvalues[1]),
        "se_hac_l12": float(res_l12.bse[1]),
        "t_hac_l12": float(res_l12.tvalues[1]),
        "p_hac_l12": float(res_l12.pvalues[1]),
    }

    # Welch t-test (unequal variance)
    tw, pw = sstats.ttest_ind(w, s, equal_var=False)
    welch = {"t": float(tw), "p": float(pw)}

    return nov_apr, may_oct, hac, welch


def block_bootstrap_meandiff(df, block=12, reps=2000, seed=SEED):
    """Circular block bootstrap CI for mean(Nov-Apr) - mean(May-Oct).

    Resamples (return, season-label) pairs in contiguous blocks so that serial
    dependence (incl. annual seasonal structure) is preserved.
    """
    rng = np.random.default_rng(seed)
    r = df["ret"].values
    w = df["winter"].values.astype(bool)
    n = len(r)
    n_blocks = int(np.ceil(n / block))
    diffs = []
    for _ in range(reps):
        starts = rng.integers(0, n, size=n_blocks)
        idx = np.concatenate([(s + np.arange(block)) % n for s in starts])[:n]
        rr, ww = r[idx], w[idx]
        if ww.sum() == 0 or (~ww).sum() == 0:
            continue
        diffs.append(rr[ww].mean() - rr[~ww].mean())
    diffs = np.array(diffs)
    lo, med, hi = np.percentile(diffs, [2.5, 50, 97.5])
    return {
        "point_mean_diff": float(r[w].mean() - r[~w].mean()),
        "boot_median": float(med),
        "ci95_low": float(lo),
        "ci95_high": float(hi),
        "reps_used": int(len(diffs)),
        "block_len": block,
        "ci_excludes_zero": bool(lo > 0 or hi < 0),
    }


def strategy_metrics(df):
    """Halloween-timing (hold Nov-Apr, cash May-Oct) vs buy-and-hold."""
    idx = df["ret"].values
    strat = np.where(df["winter"].values == 1, idx, 0.0)

    def perf(rets):
        rets = np.asarray(rets, float)
        n = len(rets)
        wealth = np.cumprod(1 + rets)
        cagr = float(wealth[-1] ** (12.0 / n) - 1) if n > 0 else None
        vol = float(np.std(rets, ddof=1) * np.sqrt(12))
        mu = float(np.mean(rets))
        sd = float(np.std(rets, ddof=1))
        sharpe = float(mu / sd * np.sqrt(12)) if sd > 0 else None
        peak = np.maximum.accumulate(wealth)
        mdd = float(np.min(wealth / peak - 1))
        return {
            "cagr_pct": cagr * 100 if cagr is not None else None,
            "ann_vol_pct": vol * 100,
            "sharpe_ann": sharpe,
            "mdd_pct": mdd * 100,
            "final_wealth_mult": float(wealth[-1]),
            "n_months": n,
        }

    return {"halloween_timing": perf(strat), "buy_and_hold": perf(idx)}


# ---------------------------------------------------------------- driver


def analyze(name, close, label):
    full = monthly_returns(close)
    last15 = full[full.index >= LAST15_START]
    out = {"asset": name, "series_label": label,
           "data_start": str(full.index.min().date()),
           "data_end": str(full.index.max().date())}
    for tag, d in [("full", full), ("last15y", last15)]:
        na, mo, hac, welch = season_stats(d)
        boot = block_bootstrap_meandiff(d)
        strat = strategy_metrics(d)
        out[tag] = {
            "period": f"{d.index.min().date()}..{d.index.max().date()}",
            "n_months_total": int(len(d)),
            "nov_apr": na,
            "may_oct": mo,
            "hac_regression": hac,
            "welch_ttest": welch,
            "block_bootstrap": boot,
            "strategy": strat,
            "halloween_significant_5pct": bool(hac["p_hac_auto"] < 0.05 and hac["beta_mean_diff_monthly"] > 0),
        }
    return out, full, last15


def main():
    us_close = load_close(os.path.join(DATA, "GSPC_snapshot.csv"))
    tw_close = load_close(os.path.join(DATA, "TWII_snapshot.csv"))
    spy = pd.read_csv(os.path.join(DATA, "SPY_snapshot.csv"))
    spy["Date"] = pd.to_datetime(spy["Date"])
    spy_ac = spy.dropna(subset=["AdjClose"]).sort_values("Date").set_index("Date")["AdjClose"].astype(float)
    tw50 = pd.read_csv(os.path.join(DATA, "0050TW_snapshot.csv"))
    tw50["Date"] = pd.to_datetime(tw50["Date"])
    tw50_ac = tw50.dropna(subset=["AdjClose"]).sort_values("Date").set_index("Date")["AdjClose"].astype(float)

    us_res, us_full, us_15 = analyze("US_SP500", us_close, "S&P 500 price index (^GSPC) daily Close")
    tw_res, tw_full, tw_15 = analyze("TW_TAIEX", tw_close, "TAIEX price index (^TWII) daily Close")
    spy_res, _, _ = analyze("US_SPY_ETF", spy_ac, "SPY ETF total-return (AdjClose) — 2016+ only")
    tw50_res, _, _ = analyze("TW_0050_ETF", tw50_ac, "0050.TW ETF total-return (AdjClose) — 2009+")

    # --------------------------------------------------------- verdict text
    def verdict_line(res, tag):
        b = res[tag]
        h = b["hac_regression"]
        sig = b["halloween_significant_5pct"]
        return {
            "beta_monthly_pp": round(h["beta_mean_diff_monthly"] * 100, 3),
            "beta_ann_pp": round(h["beta_ann_pct"], 2),
            "p_hac_auto": round(h["p_hac_auto"], 4),
            "significant_5pct_positive": sig,
            "boot_ci95_monthly_pp": [round(b["block_bootstrap"]["ci95_low"] * 100, 3),
                                      round(b["block_bootstrap"]["ci95_high"] * 100, 3)],
            "boot_ci_excludes_zero": b["block_bootstrap"]["ci_excludes_zero"],
        }

    verdict = {
        "US_SP500": {"full": verdict_line(us_res, "full"), "last15y": verdict_line(us_res, "last15y")},
        "TW_TAIEX": {"full": verdict_line(tw_res, "full"), "last15y": verdict_line(tw_res, "last15y")},
        "summary": (
            "Halloween effect: sign (Nov-Apr minus May-Oct monthly mean) and 5% HAC "
            "significance per market/sample. See per-market blocks; 'significant_5pct_positive' "
            "is the primary verdict flag."
        ),
    }

    results = {
        "experiment_id": "k1630",
        "title": "Sell in May / Halloween Indicator — TW & US, full sample vs last 15 years",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "method": {
            "return_type": "simple calendar-month returns (month-end resample, pct_change)",
            "winter_half_months": WINTER,
            "last15y_start": LAST15_START,
            "hac": "Newey-West; primary lag = floor(4*(T/100)^(2/9)); robustness L=12",
            "bootstrap": "circular block bootstrap, block=12 months, 2000 reps, seed=1630",
            "strategy": "Halloween timing = hold index Nov-Apr, cash(0%) May-Oct; vs buy-and-hold; entry/exit at month-end close",
            "cash_rate_note": "cash=0% (conservative for Halloween; using T-bill would raise Halloween-strategy return)",
        },
        "data_provenance": {
            "US_SP500": "^GSPC daily Close, snapshot of experiments/k1410/data/GSPC.csv",
            "TW_TAIEX": "^TWII daily Close, snapshot of experiments/k1410/data/TWII.csv",
            "US_SPY_ETF": "SPY AdjClose from data/cache/price_cache.db (2016+ only)",
            "TW_0050_ETF": "0050.TW AdjClose from data/cache/price_cache.db (2009+)",
        },
        "verdict": verdict,
        "results": {
            "US_SP500": us_res,
            "TW_TAIEX": tw_res,
            "US_SPY_ETF_robustness": spy_res,
            "TW_0050_ETF_robustness": tw50_res,
        },
    }

    with open(os.path.join(HERE, "k1630_results.json"), "w") as f:
        json.dump(results, f, indent=2)
    print("results written")

    make_figures(us_full, tw_full, us_15, tw_15, us_res, tw_res)
    print("figures written")

    # console summary
    for mk, r in [("US", us_res), ("TW", tw_res)]:
        for tg in ["full", "last15y"]:
            b = r[tg]
            h = b["hac_regression"]
            print(f"{mk} {tg:8s} beta={h['beta_mean_diff_monthly']*100:+.3f}pp/mo "
                  f"p_HAC={h['p_hac_auto']:.3f} sig={b['halloween_significant_5pct']} "
                  f"NovApr={b['nov_apr']['mean_monthly']*100:+.3f} MayOct={b['may_oct']['mean_monthly']*100:+.3f} "
                  f"N={b['n_months_total']}")


# ---------------------------------------------------------------- figures


def _month_avg(df):
    return df.groupby("month")["ret"].mean().reindex(range(1, 13)) * 100


def make_figures(us_full, tw_full, us_15, tw_15, us_res, tw_res):
    mnames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    # (a) 12-month average monthly return bar chart, US & TW (full sample)
    fig, axes = plt.subplots(2, 1, figsize=(10, 8))
    for ax, df, ttl in [(axes[0], us_full, "US S&P 500 (^GSPC)"),
                        (axes[1], tw_full, "TW TAIEX (^TWII)")]:
        avg = _month_avg(df)
        colors = ["#2e7d32" if m in WINTER else "#ef6c00" for m in range(1, 13)]
        ax.bar(mnames, avg.values, color=colors)
        ax.axhline(0, color="k", lw=0.6)
        ax.set_title(f"{ttl} — avg monthly return by calendar month (full sample)")
        ax.set_ylabel("avg return (%)")
        ax.grid(axis="y", alpha=0.3)
    from matplotlib.patches import Patch
    axes[0].legend(handles=[Patch(color="#2e7d32", label="Nov-Apr (hold)"),
                            Patch(color="#ef6c00", label="May-Oct (sell)")], loc="upper right")
    plt.tight_layout()
    plt.savefig(os.path.join(HERE, "fig_a_monthly_bars.png"), dpi=130)
    plt.close()

    # (b) Halloween timing vs buy-and-hold cumulative curves (full sample)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for ax, df, ttl in [(axes[0], us_full, "US S&P 500"), (axes[1], tw_full, "TW TAIEX")]:
        idx = df["ret"].values
        strat = np.where(df["winter"].values == 1, idx, 0.0)
        w_bh = np.cumprod(1 + idx)
        w_hl = np.cumprod(1 + strat)
        ax.plot(df.index, w_bh, label="Buy & Hold", color="#1565c0")
        ax.plot(df.index, w_hl, label="Halloween timing (Nov-Apr in, May-Oct cash)", color="#2e7d32")
        ax.set_yscale("log")
        ax.set_title(f"{ttl}: cumulative wealth (log scale)")
        ax.set_ylabel("growth of $1 (log)")
        ax.legend(loc="upper left", fontsize=8)
        ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(HERE, "fig_b_cumulative.png"), dpi=130)
    plt.close()

    # (c) full vs last-15y effect comparison: beta (Nov-Apr minus May-Oct) with bootstrap 95% CI
    fig, ax = plt.subplots(figsize=(9, 5.5))
    groups = [("US full", us_res["full"]), ("US 15y", us_res["last15y"]),
              ("TW full", tw_res["full"]), ("TW 15y", tw_res["last15y"])]
    xs = np.arange(len(groups))
    betas = [g[1]["hac_regression"]["beta_mean_diff_monthly"] * 100 for g in groups]
    los = [g[1]["block_bootstrap"]["ci95_low"] * 100 for g in groups]
    his = [g[1]["block_bootstrap"]["ci95_high"] * 100 for g in groups]
    err_low = [b - l for b, l in zip(betas, los)]
    err_high = [h - b for b, h in zip(betas, his)]
    colors = ["#1565c0", "#64b5f6", "#c62828", "#ef9a9a"]
    ax.bar(xs, betas, color=colors)
    ax.errorbar(xs, betas, yerr=[err_low, err_high], fmt="none", ecolor="k", capsize=5, lw=1.2)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xticks(xs)
    ax.set_xticklabels([g[0] for g in groups])
    ax.set_ylabel("Nov-Apr minus May-Oct, monthly mean (%)")
    ax.set_title("Halloween effect size (with block-bootstrap 95% CI): full vs last 15 years")
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(HERE, "fig_c_full_vs_15y.png"), dpi=130)
    plt.close()


if __name__ == "__main__":
    main()
