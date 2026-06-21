"""
k_vix_complacency_20260621
==========================
Honest empirical test of the popular "low VIX = complacency = imminent crash"
narrative.

Question under test
--------------------
Does a low VIX level actually PRECEDE worse forward S&P 500 drawdowns?
The popular fear narrative says low VIX is a contrarian crash-timing signal.
The academic prior (volatility persistence + the "volatility paradox" /
Minsky-Brunnermeier-Sannikov fragility view) says:
  - low VIX is a POOR crash-*timing* signal (vol is persistent; low-vol
    regimes last years), AND
  - low-vol regimes coincide with compressed risk premia + a fatter
    CONDITIONAL tail when a shock eventually hits.

Design notes (research-honesty)
-------------------------------
* Forward windows (forward 21d / 63d max-drawdown & realized vol) are forward
  BY DESIGN -- that IS the object of study, not lookahead. The REGIME LABEL at
  day t uses only VIX information available up to and including t (the close
  level on day t). No future information enters the label.
* The low-VIX percentile threshold is computed on the FULL history (it is a
  descriptive/unconditional benchmark of "what counts as low historically"),
  which is a mild in-sample look for the *threshold only* -- this is the
  standard way the narrative is stated ("VIX is in its bottom quintile") and we
  flag it explicitly. The sub-period split + fixed absolute thresholds
  (VIX<15, VIX<13) are immune to this and serve as the robustness anchor.
* Fixed RNG seed for the bootstrap CI.

Data: ^VIX and ^GSPC daily, yfinance, ~1990-01-01 -> today.
auto_adjust=False; multi-index columns handled explicitly.
"""

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

SEED = 20260621
rng = np.random.default_rng(SEED)

EXP_DIR = "/Users/yhlai0911/Desktop/volpred-research/experiments/k_vix_complacency_20260621"
START = "1990-01-01"
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# Forward windows in TRADING days
FWD = {"fwd21": 21, "fwd63": 63}


# ---------------------------------------------------------------------------
# 1. DATA
# ---------------------------------------------------------------------------
def _extract_close(df: pd.DataFrame, ticker: str) -> pd.Series:
    """Robustly pull the Close column whether or not yfinance returns a
    multi-index column frame."""
    if isinstance(df.columns, pd.MultiIndex):
        # ('Close', '^VIX') layout
        s = df["Close"][ticker]
    else:
        s = df["Close"]
    return s.astype(float).dropna()


def load_data():
    vix_raw = yf.download(
        "^VIX", start=START, end=TODAY, auto_adjust=False, progress=False
    )
    spx_raw = yf.download(
        "^GSPC", start=START, end=TODAY, auto_adjust=False, progress=False
    )
    vix = _extract_close(vix_raw, "^VIX").rename("vix")
    spx = _extract_close(spx_raw, "^GSPC").rename("spx")

    df = pd.concat([vix, spx], axis=1).dropna()
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    return df


# ---------------------------------------------------------------------------
# 2. FORWARD TAIL MEASURES (forward by design)
# ---------------------------------------------------------------------------
def forward_max_drawdown(prices: np.ndarray, h: int) -> np.ndarray:
    """For each t, the worst peak-to-trough return of SPX over the next h
    trading days, measured from price[t]. Returned as a NEGATIVE number
    (e.g. -0.20 = a 20% drawdown). NaN where the full window is unavailable."""
    n = len(prices)
    out = np.full(n, np.nan)
    for t in range(n):
        end = t + h
        if end >= n:
            break
        window = prices[t : end + 1]          # includes today as the anchor peak
        running_peak = np.maximum.accumulate(window)
        dd = window / running_peak - 1.0       # <= 0
        out[t] = dd.min()
    return out


def forward_realized_vol(log_ret: np.ndarray, h: int) -> np.ndarray:
    """Annualized realized vol of SPX log returns over the next h trading days
    (returns indexed t+1..t+h). NaN where window incomplete."""
    n = len(log_ret)
    out = np.full(n, np.nan)
    for t in range(n):
        end = t + h
        if end >= n:
            break
        fut = log_ret[t + 1 : end + 1]
        if len(fut) == h:
            out[t] = fut.std(ddof=1) * np.sqrt(252.0)
    return out


# ---------------------------------------------------------------------------
# 3. STATS HELPERS
# ---------------------------------------------------------------------------
def dist_stats(x: np.ndarray) -> dict:
    x = x[~np.isnan(x)]
    if len(x) == 0:
        return {k: None for k in ("n", "median", "mean", "p05", "p95", "worst")}
    return {
        "n": int(len(x)),
        "median": float(np.median(x)),
        "mean": float(np.mean(x)),
        "p05": float(np.percentile(x, 5)),
        "p95": float(np.percentile(x, 95)),
        # for drawdowns "worst" = most negative = min; for vol "worst" = max
        "min": float(np.min(x)),
        "max": float(np.max(x)),
    }


def mdd_stats(x: np.ndarray) -> dict:
    """Drawdown-oriented summary. mdd is negative; p95 here means the 95th
    percentile of the *magnitude* of drawdown (i.e. the 5th percentile of the
    signed series) so a bigger number = worse tail."""
    x = x[~np.isnan(x)]
    if len(x) == 0:
        return {k: None for k in ("n", "median", "p95", "worst")}
    mag = -x  # positive magnitudes
    return {
        "n": int(len(x)),
        "median": float(np.median(mag)),        # typical forward drawdown magnitude
        "p95": float(np.percentile(mag, 95)),    # bad-tail drawdown magnitude
        "worst": float(np.max(mag)),             # worst observed forward drawdown
    }


def _moving_block_resample(x: np.ndarray, block: int) -> np.ndarray:
    """Draw a moving-block bootstrap resample of length len(x). Block length
    ~= forward horizon so that overlapping forward-window serial dependence is
    respected (Codex review caveat: iid bootstrap understates CI width for
    overlapping 63d windows)."""
    n = len(x)
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=n_blocks)
    idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[:n]
    return x[idx]


def bootstrap_median_diff(low_signed: np.ndarray, base_signed: np.ndarray,
                          n_boot=2000, block=63):
    """Moving-block bootstrap 95% CI for
        (median forward-drawdown MAGNITUDE in low-VIX regime)
      - (median forward-drawdown MAGNITUDE in the BASELINE).
    Positive => low VIX precedes DEEPER forward drawdowns (the fear claim).
    `base_signed` is whatever baseline the caller passes (unconditional OR
    non-low-VIX); both are passed as the signed (negative) drawdown series."""
    low = -low_signed[~np.isnan(low_signed)]    # magnitudes
    base = -base_signed[~np.isnan(base_signed)]
    if len(low) < 60 or len(base) < 60:
        return None
    diffs = np.empty(n_boot)
    for b in range(n_boot):
        ls = _moving_block_resample(low, block)
        bs = _moving_block_resample(base, block)
        diffs[b] = np.median(ls) - np.median(bs)
    return {
        "point": float(np.median(low) - np.median(base)),
        "ci_lo": float(np.percentile(diffs, 2.5)),
        "ci_hi": float(np.percentile(diffs, 97.5)),
        "block_len": block,
        "n_boot": n_boot,
        "method": "moving_block_bootstrap",
    }


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    df = load_data()
    prices = df["spx"].to_numpy()
    vix = df["vix"].to_numpy()
    log_ret = np.concatenate([[np.nan], np.diff(np.log(prices))])

    # forward tail measures
    fwd = {}
    for name, h in FWD.items():
        fwd[f"mdd_{name}"] = forward_max_drawdown(prices, h)
        fwd[f"rv_{name}"] = forward_realized_vol(log_ret, h)
    for k, v in fwd.items():
        df[k] = v

    # ---- current VIX + percentile vs full history ----
    current_vix = float(df["vix"].iloc[-1])
    current_date = df.index[-1].strftime("%Y-%m-%d")
    pct = float((df["vix"] <= current_vix).mean() * 100.0)

    # ---- regime definitions ----
    # NOTE on lookahead (Codex review FAIL on the full-history percentile):
    #   * Full-history quintile/decile thresholds are DESCRIPTIVE benchmarks
    #     ("VIX is historically in its bottom quintile") and use the whole
    #     sample to define the threshold -- a mild in-sample look for the
    #     THRESHOLD only. We keep them but flag them.
    #   * `bottom_quintile_realtime` is the real-time-clean primary regime:
    #     at day t the label uses ONLY VIX up to t (expanding-window 20th pct,
    #     requiring >=252 prior obs). This is the lookahead-free anchor.
    #   * Fixed absolute thresholds (VIX<15, VIX<13) are inherently clean.
    q20 = float(df["vix"].quantile(0.20))   # bottom-quintile threshold (full hist)
    q10 = float(df["vix"].quantile(0.10))   # bottom-decile threshold (full hist)

    # expanding-window real-time 20th-percentile of VIX (uses only past+today)
    min_hist = 252
    rt_thresh = df["vix"].expanding(min_periods=min_hist).quantile(0.20)
    rt_low = (df["vix"] <= rt_thresh) & rt_thresh.notna()

    regimes = {
        "bottom_quintile_realtime": rt_low,          # PRIMARY, lookahead-free
        "bottom_quintile": df["vix"] <= q20,         # descriptive (full-hist thr)
        "bottom_decile": df["vix"] <= q10,           # descriptive (full-hist thr)
        "vix_lt_15": df["vix"] < 15.0,               # fixed absolute (clean)
        "vix_lt_13": df["vix"] < 13.0,               # fixed absolute (clean)
    }
    regime_defs = {
        "bottom_quintile_realtime": (
            "VIX <= expanding-window 20th pct (min 252 prior obs); "
            "real-time, lookahead-free PRIMARY regime"),
        "bottom_quintile": f"VIX <= {q20:.2f} (20th pct of FULL history; descriptive)",
        "bottom_decile": f"VIX <= {q10:.2f} (10th pct of FULL history; descriptive)",
        "vix_lt_15": "VIX < 15.0 (fixed absolute threshold)",
        "vix_lt_13": "VIX < 13.0 (fixed absolute threshold)",
    }
    PRIMARY = "bottom_quintile_realtime"

    # ---- conditional vs unconditional forward-tail distributions ----
    def regime_block(mask: pd.Series) -> dict:
        out = {}
        for name in FWD:
            mdd = df.loc[mask, f"mdd_{name}"].to_numpy()
            rv = df.loc[mask, f"rv_{name}"].to_numpy()
            out[name] = {
                "mdd": mdd_stats(mdd),
                "rv": dist_stats(rv),
            }
        out["n_days"] = int(mask.sum())
        out["n_days_with_fwd63"] = int(df.loc[mask, "mdd_fwd63"].notna().sum())
        return out

    uncond = regime_block(pd.Series(True, index=df.index))
    conditional = {name: regime_block(mask) for name, mask in regimes.items()}

    # ---- non-low-VIX baseline for the PRIMARY regime (clean low-vs-non-low
    #      contrast; addresses Codex caveat that unconditional NESTS the low
    #      days and attenuates the difference) ----
    primary_mask = regimes[PRIMARY]
    nonlow_mask = (~primary_mask) & df["vix"].notna()
    nonlow = regime_block(nonlow_mask)

    # ---- bootstrap: does low-VIX median forward drawdown differ?
    #      reported BOTH vs unconditional (narrative anchor) AND vs non-low
    #      (clean contrast). Moving-block bootstrap (block=63). ----
    boot = {}
    base63_uncond = df["mdd_fwd63"].to_numpy()
    base63_nonlow = df.loc[nonlow_mask, "mdd_fwd63"].to_numpy()
    for name, mask in regimes.items():
        low63 = df.loc[mask, "mdd_fwd63"].to_numpy()
        boot[name] = {
            "vs_unconditional": bootstrap_median_diff(low63, base63_uncond),
        }
    # clean low-vs-non-low only for the primary regime (non-overlapping subsets)
    boot[PRIMARY]["vs_non_low"] = bootstrap_median_diff(
        df.loc[primary_mask, "mdd_fwd63"].to_numpy(), base63_nonlow)

    # ---- tail-conditional-on-shock: when a >10% fwd63 drawdown DOES occur,
    #      how deep is it in low-VIX vs other regimes? (the 'fragility' test) ----
    def conditional_on_shock(mask, thr=0.10):
        s = -df.loc[mask, "mdd_fwd63"].to_numpy()
        s = s[~np.isnan(s)]
        shock = s[s >= thr]
        return {
            "p_shock_gt10pct": float((s >= thr).mean()) if len(s) else None,
            "median_depth_given_shock": float(np.median(shock)) if len(shock) else None,
            "n_shock": int(len(shock)),
            "n": int(len(s)),
        }

    shock = {
        "low_vix_realtime": conditional_on_shock(regimes[PRIMARY]),
        "low_vix_bottom_quintile_fullhist": conditional_on_shock(
            regimes["bottom_quintile"]),
        "high_vix_top_quintile": conditional_on_shock(
            df["vix"] >= df["vix"].quantile(0.80)
        ),
        "unconditional": conditional_on_shock(pd.Series(True, index=df.index)),
    }

    # ---- SENSITIVITY: sub-period split (pre-2008 / post-2008) ----
    split_date = "2008-01-01"
    pre = df.index < split_date
    post = df.index >= split_date
    subperiod = {}
    for label, pmask in (("pre_2008", pre), ("post_2008", post)):
        sub = df[pmask]
        if len(sub) == 0:
            continue
        # recompute local bottom-quintile threshold within the sub-period
        local_q20 = float(sub["vix"].quantile(0.20))
        lowmask = sub["vix"] <= local_q20
        low_mdd = sub.loc[lowmask, "mdd_fwd63"].to_numpy()
        all_mdd = sub["mdd_fwd63"].to_numpy()
        subperiod[label] = {
            "n": int(len(sub)),
            "date_range": [sub.index[0].strftime("%Y-%m-%d"),
                           sub.index[-1].strftime("%Y-%m-%d")],
            "local_bottom_quintile_threshold": local_q20,
            "low_vix_fwd63_mdd": mdd_stats(low_mdd),
            "uncond_fwd63_mdd": mdd_stats(all_mdd),
        }

    # ------------------------------------------------------------------
    # VERDICT (data-driven assembly; wording finalized in README)
    # ------------------------------------------------------------------
    lq = conditional[PRIMARY]["fwd63"]["mdd"]          # realtime low-VIX
    uq = uncond["fwd63"]["mdd"]
    nlq = nonlow["fwd63"]["mdd"]                        # non-low VIX baseline
    lq_rv = conditional[PRIMARY]["fwd63"]["rv"]["median"]
    uq_rv = uncond["fwd63"]["rv"]["median"]
    nlq_rv = nonlow["fwd63"]["rv"]["median"]

    timing_signal = (
        "low VIX does NOT precede deeper typical forward drawdowns"
        if lq["median"] <= uq["median"]
        else "low VIX precedes deeper typical forward drawdowns"
    )

    results = {
        "experiment_id": "k_vix_complacency_20260621",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data": {
            "source": "yfinance ^VIX & ^GSPC daily, auto_adjust=False",
            "start": START,
            "end_requested": TODAY,
            "history_start": df.index[0].strftime("%Y-%m-%d"),
            "history_end": current_date,
            "n_obs": int(len(df)),
            "n_obs_with_fwd63": int(df["mdd_fwd63"].notna().sum()),
        },
        "current_vix": {
            "level": current_vix,
            "date": current_date,
            "percentile_full_history": pct,
            "bottom_quintile_threshold": q20,
            "bottom_decile_threshold": q10,
            "is_low_regime_bottom_quintile": bool(current_vix <= q20),
        },
        "regime_definitions": regime_defs,
        "primary_regime": PRIMARY,
        "unconditional": uncond,
        "non_low_vix_baseline": nonlow,
        "conditional": conditional,
        "bootstrap_median_mdd_diff_fwd63": boot,
        "tail_conditional_on_shock_fwd63": shock,
        "sensitivity_subperiod": subperiod,
        "verdict_inputs": {
            "primary_regime": PRIMARY,
            "low_vix_fwd63_mdd_median": lq["median"],
            "uncond_fwd63_mdd_median": uq["median"],
            "nonlow_fwd63_mdd_median": nlq["median"],
            "low_vix_fwd63_mdd_p95": lq["p95"],
            "uncond_fwd63_mdd_p95": uq["p95"],
            "nonlow_fwd63_mdd_p95": nlq["p95"],
            "low_vix_fwd63_mdd_worst": lq["worst"],
            "uncond_fwd63_mdd_worst": uq["worst"],
            "nonlow_fwd63_mdd_worst": nlq["worst"],
            "low_vix_fwd63_rv_median": lq_rv,
            "uncond_fwd63_rv_median": uq_rv,
            "nonlow_fwd63_rv_median": nlq_rv,
            "timing_signal_finding": timing_signal,
        },
    }

    out_path = f"{EXP_DIR}/k_vix_complacency_20260621_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print("results ->", out_path)

    # ------------------------------------------------------------------
    # CHART
    # ------------------------------------------------------------------
    make_chart(df, q20, q10, current_vix, current_date, pct,
               conditional, uncond, shock, regimes)

    # console digest
    print(f"\nCurrent VIX {current_vix:.2f} on {current_date} "
          f"= {pct:.1f}th pctile of {len(df)} days since "
          f"{df.index[0].strftime('%Y-%m-%d')}")
    print(f"fwd63 MDD median  low-VIX(BQ)={lq['median']*100:.2f}%  "
          f"uncond={uq['median']*100:.2f}%  -> {timing_signal}")
    print(f"fwd63 MDD p95     low-VIX(BQ)={lq['p95']*100:.2f}%  "
          f"uncond={uq['p95']*100:.2f}%")
    print(f"fwd63 RV median   low-VIX(BQ)={lq_rv*100:.2f}%  "
          f"uncond={uq_rv*100:.2f}%")
    print(f"P(shock>10%|low-VIX rt)={shock['low_vix_realtime']['p_shock_gt10pct']:.3f} "
          f"vs P(shock>10%|high-VIX)={shock['high_vix_top_quintile']['p_shock_gt10pct']:.3f}")
    bq = boot[PRIMARY]
    if bq.get("vs_non_low"):
        v = bq["vs_non_low"]
        print(f"block-boot median MDD diff (low - non-low) = {v['point']*100:+.2f}% "
              f"CI[{v['ci_lo']*100:+.2f},{v['ci_hi']*100:+.2f}]%")
    return results


def make_chart(df, q20, q10, current_vix, current_date, pct,
               conditional, uncond, shock, regimes):
    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    fig.suptitle(
        "Does Low VIX Signal an Imminent Crash? Testing the 'Complacency' Narrative\n"
        f"^VIX & ^GSPC daily, {df.index[0]:%Y-%m-%d} to {current_date}  "
        f"(N={len(df):,} trading days)",
        fontsize=14, fontweight="bold",
    )

    # ---- (a) VIX history with percentile bands ----
    ax = axes[0, 0]
    ax.plot(df.index, df["vix"], lw=0.5, color="#1f3b6e", alpha=0.85)
    ax.axhline(q20, color="#2a9d8f", ls="--", lw=1.4,
               label=f"Bottom quintile (VIX {q20:.1f})")
    ax.axhline(q10, color="#0b6e4f", ls=":", lw=1.4,
               label=f"Bottom decile (VIX {q10:.1f})")
    ax.axhline(current_vix, color="#e63946", ls="-", lw=1.6,
               label=f"Current VIX {current_vix:.1f} ({pct:.0f}th pct)")
    ax.fill_between(df.index, 0, q20, color="#2a9d8f", alpha=0.10)
    ax.set_title("(a) VIX history with low-VIX bands", fontsize=11, loc="left")
    ax.set_ylabel("VIX")
    ax.set_ylim(0, 90)
    ax.legend(fontsize=8, loc="upper right")

    # ---- (b) forward-63d MAX DRAWDOWN distribution: low-VIX vs all ----
    ax = axes[0, 1]
    low_mdd = -df.loc[regimes["bottom_quintile_realtime"], "mdd_fwd63"].dropna() * 100
    all_mdd = -df["mdd_fwd63"].dropna() * 100
    bins = np.linspace(0, 60, 31)
    ax.hist(all_mdd, bins=bins, density=True, alpha=0.45, color="#888888",
            label=f"All days (median {np.median(all_mdd):.1f}%)")
    ax.hist(low_mdd, bins=bins, density=True, alpha=0.55, color="#2a9d8f",
            label=f"Low-VIX (real-time bottom quintile, median {np.median(low_mdd):.1f}%)")
    ax.axvline(np.median(all_mdd), color="#555555", ls="--", lw=1.2)
    ax.axvline(np.median(low_mdd), color="#0b6e4f", ls="--", lw=1.2)
    ax.set_title("(b) Forward 63-day max drawdown distribution",
                 fontsize=11, loc="left")
    ax.set_xlabel("Forward 63d max drawdown magnitude (%)")
    ax.set_ylabel("Density")
    ax.legend(fontsize=8)

    # ---- (c) median & p95 forward-63d MDD across regimes ----
    ax = axes[1, 0]
    order = ["unconditional", "vix_lt_15", "bottom_quintile_realtime",
             "vix_lt_13", "bottom_decile"]
    labels = ["All days", "VIX<15", "Bottom quintile\n(real-time)", "VIX<13",
              "Bottom\ndecile"]

    def get_mdd(name):
        if name == "unconditional":
            return uncond["fwd63"]["mdd"]
        return conditional[name]["fwd63"]["mdd"]

    med = [get_mdd(n)["median"] * 100 for n in order]
    p95 = [get_mdd(n)["p95"] * 100 for n in order]
    x = np.arange(len(order))
    w = 0.38
    ax.bar(x - w / 2, med, w, color="#457b9d", label="Median fwd63 MDD")
    ax.bar(x + w / 2, p95, w, color="#e76f51", label="p95 fwd63 MDD (bad tail)")
    for i, (m, p) in enumerate(zip(med, p95)):
        ax.text(i - w / 2, m + 0.3, f"{m:.1f}", ha="center", fontsize=7.5)
        ax.text(i + w / 2, p + 0.3, f"{p:.1f}", ha="center", fontsize=7.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_ylabel("Forward 63d max drawdown (%)")
    ax.set_title("(c) Typical (median) vs bad-tail (p95) forward drawdown by regime",
                 fontsize=11, loc="left")
    ax.legend(fontsize=8)

    # ---- (d) the fragility test: P(shock) and depth-given-shock ----
    ax = axes[1, 1]
    cats = ["Low-VIX\n(real-time BQ)", "Unconditional", "High-VIX\n(top quintile)"]
    keys = ["low_vix_realtime", "unconditional", "high_vix_top_quintile"]
    p_shock = [shock[k]["p_shock_gt10pct"] * 100 for k in keys]
    depth = [shock[k]["median_depth_given_shock"] * 100
             if shock[k]["median_depth_given_shock"] else 0 for k in keys]
    x = np.arange(len(cats))
    ax2 = ax.twinx()
    b1 = ax.bar(x - 0.2, p_shock, 0.4, color="#a8dadc",
                label="P(fwd63 drawdown >10%)")
    b2 = ax2.bar(x + 0.2, depth, 0.4, color="#1d3557",
                 label="Median depth | shock occurs")
    for i, v in enumerate(p_shock):
        ax.text(i - 0.2, v + 0.5, f"{v:.0f}%", ha="center", fontsize=8)
    for i, v in enumerate(depth):
        ax2.text(i + 0.2, v + 0.3, f"{v:.0f}%", ha="center", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(cats, fontsize=8.5)
    ax.set_ylabel("P(forward 63d drawdown > 10%)", color="#2a6f7f")
    ax2.set_ylabel("Median drawdown depth GIVEN shock", color="#1d3557")
    ax.set_title("(d) Crash FREQUENCY (low VIX = low) vs crash DEPTH given a shock",
                 fontsize=11, loc="left")
    lines = [b1, b2]
    ax.legend(lines, [l.get_label() for l in lines], fontsize=8, loc="upper center")

    fig.text(0.5, 0.005,
             "Forward windows are forward BY DESIGN (the question); regime label at t uses only VIX up to t. "
             "Verdict: low VIX is a poor crash-TIMING signal, not a fragility-free all-clear.",
             ha="center", fontsize=8.5, style="italic", color="#444444")
    fig.tight_layout(rect=[0, 0.02, 1, 0.96])
    out = f"{EXP_DIR}/k_vix_complacency_fwd_drawdown.png"
    fig.savefig(out, dpi=130)
    print("chart ->", out)


if __name__ == "__main__":
    main()
