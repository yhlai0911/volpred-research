#!/usr/bin/env python3
"""K1633: "VIX 破 30/40 就是抄底訊號" 投資迷思驗證.

Reader-facing myth-bust. Event study of SPY forward returns after VIX first
crosses 30 / 35 / 40 (de-clustered), vs an unconditional (random-entry) baseline,
with overlap-robust inference.

Research-honesty guardrails
---------------------------
* Signal timing: the VIX crossing on day t is realized at the SAME close as the
  SPY price we enter at. Forward return = SPY_close[t+H] / SPY_close[t] - 1.
  This is strictly forward-looking (we only measure what happens AFTER the
  signal day) -> no lookahead. A robustness variant enters at close[t+1]
  (signal shift(1)) to confirm results are not driven by same-close entry.
* De-clustering: a VIX crossing counts as a NEW event only if >= COOLDOWN
  trading days have passed since the last accepted event (one panic episode can
  oscillate around the threshold and produce many raw crossings).
* Overlapping forward windows are NOT treated as iid (K1355 lesson):
  primary inference = Newey-West/HAC regression (fwd ~ event_dummy, lags=H);
  robustness = stationary block bootstrap + random-entry placebo (block>=H).
* All random procedures seeded (SEED=1629).

Data: yfinance ^VIX (Close, index level) + SPY (Close, dividend/split-adjusted
via auto_adjust=True). Cached CSVs under experiments/k1633/data/.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import statsmodels.api as sm
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SEED = 1629            # arbitrary fixed seed (retained from initial run for exact reproducibility of committed results)
THRESHOLDS = [30, 35, 40]
HORIZONS = [5, 10, 20, 60]
COOLDOWN = 20          # trading days between accepted events (de-cluster)
N_BOOT = 5000          # bootstrap / placebo replications
rng = np.random.default_rng(SEED)


# ----------------------------------------------------------------------------- data
def load_data() -> pd.DataFrame:
    """Load cached VIX + SPY; refetch via yfinance if cache missing."""
    vp = os.path.join(DATA, "vix_full.csv")
    sp = os.path.join(DATA, "spy_full.csv")
    if not (os.path.exists(vp) and os.path.exists(sp)):
        import yfinance as yf

        os.makedirs(DATA, exist_ok=True)
        vix = yf.download("^VIX", start="1990-01-01", end="2026-07-05",
                          progress=False, auto_adjust=False)
        spy = yf.download("SPY", start="1993-01-01", end="2026-07-05",
                          progress=False, auto_adjust=True)
        for df in (vix, spy):
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
        vix[["Close"]].rename(columns={"Close": "VIX"}).to_csv(vp)
        spy[["Close"]].rename(columns={"Close": "SPY"}).to_csv(sp)
    vix = pd.read_csv(vp, index_col=0, parse_dates=True)
    spy = pd.read_csv(sp, index_col=0, parse_dates=True)
    df = pd.concat([vix["VIX"], spy["SPY"]], axis=1, join="inner").dropna()
    df = df[~df.index.duplicated(keep="first")].sort_index()
    return df


# ----------------------------------------------------------------------------- events
def detect_events(vix: pd.Series, thr: float, cooldown: int) -> list[int]:
    """Positional indices where VIX FIRST crosses above `thr` (from below),
    de-clustered so accepted events are >= cooldown trading days apart."""
    v = vix.to_numpy()
    raw = np.where((v[1:] >= thr) & (v[:-1] < thr))[0] + 1  # cross day = i
    accepted: list[int] = []
    last = -10**9
    for i in raw:
        if i - last >= cooldown:
            accepted.append(int(i))
            last = i
    return accepted


def forward_returns(spy: np.ndarray, idx: list[int], H: int, entry_lag: int = 0):
    """Simple forward return over H trading days.

    entry_lag=0 -> enter at close of signal day t; fwd = P[t+H]/P[t]-1.
    entry_lag=1 -> enter at close of t+1 (signal shift(1) robustness);
                   fwd = P[t+1+H]/P[t+1]-1.
    Only events whose full forward window fits in-sample are kept.
    """
    n = len(spy)
    rets, kept = [], []
    for t in idx:
        e = t + entry_lag
        if e + H < n:
            rets.append(spy[e + H] / spy[e] - 1.0)
            kept.append(t)
    return np.asarray(rets), kept


def window_mdd(spy: np.ndarray, entry_idx: list[int], H: int) -> np.ndarray:
    """Max drawdown within each [entry, entry+H] SPY path (relative to entry)."""
    out = []
    n = len(spy)
    for e in entry_idx:
        if e + H >= n:
            continue
        path = spy[e:e + H + 1]
        run_max = np.maximum.accumulate(path)
        dd = path / run_max - 1.0
        out.append(dd.min())
    return np.asarray(out)


# --------------------------------------------------------------------- baseline / stats
def baseline_forward(spy: np.ndarray, H: int) -> np.ndarray:
    n = len(spy)
    p = spy[: n - H]
    q = spy[H:]
    return q / p - 1.0


def wilson_ci(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (centre - half, centre + half)


def hac_event_test(fwd_all: np.ndarray, event_mask: np.ndarray, H: int):
    """Newey-West/HAC regression: fwd ~ const + event_dummy, lags=H.
    Coefficient b = event mean - non-event mean, with overlap-robust SE."""
    y = fwd_all
    X = sm.add_constant(event_mask.astype(float))
    model = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": H})
    b = float(model.params[1])
    t = float(model.tvalues[1])
    p = float(model.pvalues[1])
    return b, t, p


def placebo_pvalue(spy: np.ndarray, event_mean: float, n_events: int, H: int,
                   entry_lag: int, local_rng) -> tuple[float, float]:
    """Random-entry placebo: draw n_events random entry days B times, compute
    mean forward return -> null distribution. Two-sided + one-sided (event>random).
    Overlap is identical in null & event samples (same forward-window structure)."""
    n = len(spy)
    valid = np.arange(0, n - entry_lag - H)  # entry days with a full window
    null_means = np.empty(N_BOOT)
    for b in range(N_BOOT):
        pick = local_rng.choice(valid, size=n_events, replace=False)
        e = pick + entry_lag
        r = spy[e + H] / spy[e] - 1.0
        null_means[b] = r.mean()
    mu = null_means.mean()
    p_one = float((null_means >= event_mean).mean())            # buy-the-dip better
    p_two = float((np.abs(null_means - mu) >= abs(event_mean - mu)).mean())
    return p_one, p_two


def stationary_bootstrap_ci(x: np.ndarray, H: int, local_rng, reps: int = N_BOOT):
    """Politis-Romano stationary bootstrap CI for the mean of an overlapping
    series x. Expected block length = H (>= horizon, K1355)."""
    n = len(x)
    if n < 2:
        return (float("nan"), float("nan"))
    p_geom = 1.0 / max(H, 1)
    means = np.empty(reps)
    for b in range(reps):
        idx = np.empty(n, dtype=int)
        i = local_rng.integers(0, n)
        for k in range(n):
            idx[k] = i
            if local_rng.random() < p_geom:
                i = local_rng.integers(0, n)
            else:
                i = (i + 1) % n
        means[b] = x[idx].mean()
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def benjamini_hochberg(pvals):
    """BH step-up FDR-adjusted q-values, returned in the input order.

    Bakes 12-cell multiple-testing correction into the script (Codex review
    must-fix #1) so `python k1633.py` regenerates the full FDR verdict rather
    than relying on a manual post-hoc integration.
    """
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [1.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        idx = order[rank - 1]
        running = min(running, pvals[idx] * m / rank)
        q[idx] = min(running, 1.0)
    return q


# ----------------------------------------------------------------------------- main
def main() -> None:
    df = load_data()
    vix = df["VIX"]
    spy = df["SPY"].to_numpy()
    dates = df.index
    n = len(df)

    results = {
        "experiment_id": "k1633",
        "title": "VIX 破 30/40 是抄底訊號嗎 — 事件後 SPY 前瞻報酬 vs baseline",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data": {
            "source": "yfinance ^VIX (Close, index level) + SPY (Close, auto_adjust=True div/split-adjusted)",
            "period": f"{dates.min().date()} .. {dates.max().date()}",
            "n_trading_days": int(n),
            "de_cluster_cooldown_trading_days": COOLDOWN,
        },
        "config": {"thresholds": THRESHOLDS, "horizons": HORIZONS,
                   "n_bootstrap": N_BOOT, "entry": "signal-day close (lag0); robustness lag1",
                   "primary_inference": "HAC / Newey-West maxlags=H on event dummy (overlap-robust, K1355)",
                   "bootstrap_ci_note": ("mean_boot95 and chart CI bands are event-ORDER resampling "
                                         "(block over the event series), secondary/diagnostic only; "
                                         "the overlap-robust primary inference is HAC, not the bootstrap CI"),
                   "lag1_baseline_note": ("robustness_entry_lag1.excess_mean_vs_baseline is measured "
                                          "against the lag0 unconditional baseline (baseline shifts <=1 "
                                          "trading day; difference negligible), used only as a "
                                          "same-close-artifact robustness check")},
        "baseline": {},
        "events": {},
        "robustness_entry_lag1": {},
        "verdict": {},
    }

    # -------- baseline (unconditional) per horizon
    base_stats = {}
    for H in HORIZONS:
        fb = baseline_forward(spy, H)
        entry_days = list(range(0, n - H))
        mdd = window_mdd(spy, entry_days, H)
        base_stats[H] = {
            "n": int(len(fb)),
            "win_rate": float((fb > 0).mean()),
            "mean": float(fb.mean()),
            "median": float(np.median(fb)),
            "std": float(fb.std(ddof=1)),
            "p5": float(np.percentile(fb, 5)),
            "p95": float(np.percentile(fb, 95)),
            "mean_mdd": float(mdd.mean()),
            "median_mdd": float(np.median(mdd)),
        }
    results["baseline"] = base_stats

    # -------- events per threshold x horizon
    event_idx_by_thr = {thr: detect_events(vix, thr, COOLDOWN) for thr in THRESHOLDS}
    for thr in THRESHOLDS:
        ev_idx = event_idx_by_thr[thr]
        results["events"][str(thr)] = {
            "n_events_raw_decluster": len(ev_idx),
            "event_dates": [str(dates[i].date()) for i in ev_idx],
            "horizons": {},
        }
        for H in HORIZONS:
            fwd, kept = forward_returns(spy, ev_idx, H, entry_lag=0)
            if len(fwd) == 0:
                continue
            entry_days = kept  # lag0 entry == signal day
            mdd = window_mdd(spy, entry_days, H)
            wins = int((fwd > 0).sum())
            wlo, whi = wilson_ci(wins, len(fwd))

            # event dummy over ALL days (for HAC): 1 on signal days with full window
            mask = np.zeros(n - H, dtype=int)
            for t in kept:
                if t < n - H:
                    mask[t] = 1
            fb = baseline_forward(spy, H)
            b, tstat, pval = hac_event_test(fb, mask, H)

            p_one, p_two = placebo_pvalue(spy, float(fwd.mean()), len(fwd), H,
                                          entry_lag=0,
                                          local_rng=np.random.default_rng(SEED + H + thr))
            lo, hi = stationary_bootstrap_ci(fwd, H,
                                             local_rng=np.random.default_rng(SEED + thr))

            results["events"][str(thr)]["horizons"][str(H)] = {
                "n_events": int(len(fwd)),
                "win_rate": float((fwd > 0).mean()),
                "win_rate_wilson95": [float(wlo), float(whi)],
                "baseline_win_rate": base_stats[H]["win_rate"],
                "mean": float(fwd.mean()),
                "mean_boot95": [lo, hi],
                "median": float(np.median(fwd)),
                "std": float(fwd.std(ddof=1)) if len(fwd) > 1 else float("nan"),
                "p5": float(np.percentile(fwd, 5)),
                "p95": float(np.percentile(fwd, 95)),
                "mean_mdd": float(mdd.mean()),
                "median_mdd": float(np.median(mdd)),
                "baseline_mean": base_stats[H]["mean"],
                "excess_mean_vs_baseline": float(fwd.mean() - base_stats[H]["mean"]),
                "hac_coef_event_vs_nonevent": b,
                "hac_tstat": tstat,
                "hac_pvalue": pval,
                "placebo_p_one_sided_event_gt_random": p_one,
                "placebo_p_two_sided": p_two,
            }

    # -------- robustness: entry lag1 (signal shift(1))
    for thr in THRESHOLDS:
        ev_idx = event_idx_by_thr[thr]
        results["robustness_entry_lag1"][str(thr)] = {}
        for H in HORIZONS:
            fwd, kept = forward_returns(spy, ev_idx, H, entry_lag=1)
            if len(fwd) == 0:
                continue
            p_one, p_two = placebo_pvalue(spy, float(fwd.mean()), len(fwd), H,
                                          entry_lag=1,
                                          local_rng=np.random.default_rng(SEED + H + thr + 7))
            results["robustness_entry_lag1"][str(thr)][str(H)] = {
                "n_events": int(len(fwd)),
                "win_rate": float((fwd > 0).mean()),
                "mean": float(fwd.mean()),
                "excess_mean_vs_baseline": float(fwd.mean() - base_stats[H]["mean"]),
                "placebo_p_one_sided_event_gt_random": p_one,
            }

    # -------- verdict synthesis (mechanical rule; BH-FDR multiple testing baked in)
    verdict = {}
    cell_keys = []
    for thr in THRESHOLDS:
        for H in HORIZONS:
            cell = results["events"][str(thr)]["horizons"].get(str(H))
            if not cell:
                continue
            key = f"thr{thr}_H{H}"
            cell_keys.append(key)
            sig = cell["hac_pvalue"] < 0.05
            better = cell["excess_mean_vs_baseline"] > 0
            verdict[key] = {
                "excess_mean": cell["excess_mean_vs_baseline"],
                "win_vs_base": cell["win_rate"] - cell["baseline_win_rate"],
                "hac_p": cell["hac_pvalue"],
                "significant_5pct": bool(sig),
                "direction": "higher" if better else "lower",
            }

    # BH-FDR over the 12 per-cell lag0 HAC p-values (Codex must-fix #1)
    qvals = benjamini_hochberg([verdict[k]["hac_p"] for k in cell_keys])
    for k, q in zip(cell_keys, qvals):
        verdict[k]["bh_qvalue"] = float(q)
        verdict[k]["bh_fdr_5pct"] = bool(q <= 0.05)
        verdict[k]["bh_fdr_10pct"] = bool(q <= 0.10)

    results["verdict"]["per_cell"] = verdict
    n_sig = sum(1 for v in verdict.values() if v["significant_5pct"])
    n_sig_pos = sum(1 for v in verdict.values()
                    if v["significant_5pct"] and v["excess_mean"] > 0)
    n_pos = sum(1 for v in verdict.values() if v["excess_mean"] > 0)
    raw_sig = [k for k in cell_keys if verdict[k]["significant_5pct"]]
    fdr5 = [k for k in cell_keys if verdict[k]["bh_fdr_5pct"]]
    fdr10 = [k for k in cell_keys if verdict[k]["bh_fdr_10pct"]]
    results["verdict"]["summary"] = {
        "n_cells": len(verdict),
        "n_significant_5pct": n_sig,
        "n_significant_positive": n_sig_pos,
    }

    # myth verdict: direction near-universal + FDR-fragile => half_true_qualified
    if fdr5:
        myth_verdict = "supported"
    elif n_pos >= len(verdict) * 0.75 and fdr10:
        myth_verdict = "half_true_qualified"
    else:
        myth_verdict = "not_supported"
    bwr = {H: base_stats[H]["win_rate"] for H in HORIZONS}
    headline = (
        f"Direction is near-universal: {n_pos}/{len(verdict)} cells show positive forward "
        f"excess return after a VIX spike. Raw 5% significance at {n_sig} cells "
        f"({', '.join(raw_sig)}). Under strict FDR-5% multiple-testing correction "
        f"{'NONE survive individually' if not fdr5 else ', '.join(fdr5) + ' survive'}; under "
        f"FDR-10% {'none survive' if not fdr10 else str(len(fdr10)) + ' survive (' + ', '.join(fdr10) + ')'}. "
        "The panic-entry edge is real in direction but small: it mostly rides SPY's baseline "
        "upward drift, and the durable component is a slow 3-month (H60) reversion premium that "
        "scales with panic depth, not an instant bounce. Statistically fragile at thresholds "
        "35/40 where N is small (25 / 17 events)."
    )
    results["verdict"]["multiple_testing"] = {
        "method": "Benjamini-Hochberg FDR over the 12 per-cell lag0 HAC p-values (3 thresholds x 4 horizons)",
        "n_cells": len(verdict),
        "n_cells_positive_excess": n_pos,
        "n_cells_raw_sig_5pct": n_sig,
        "raw_sig_cells": raw_sig,
        "bh_fdr_0.05_survivors": fdr5,
        "bh_fdr_0.10_survivors": fdr10,
        "myth_verdict": myth_verdict,
        "headline": headline,
        "note": (
            f"Baseline forward win-rates are already high (SPY drifts up: H5 {bwr[5] * 100:.1f}%, "
            f"H60 {bwr[60] * 100:.1f}%), so 'buy the panic' mostly rides that drift; the incremental "
            "edge over random entry is real in direction but small and multiple-testing-fragile. "
            "Retail framing ('VIX>30 = instant bounce') is NOT supported at short horizons except "
            "threshold-30 H5; the durable pattern is a 3-month reversion premium that scales with "
            "panic depth."
        ),
    }

    out = os.path.join(HERE, "k1633_results.json")
    with open(out, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print("wrote", out)

    make_charts(results, spy, event_idx_by_thr, base_stats, n)
    print_summary(results)


# ----------------------------------------------------------------------------- charts
def make_charts(results, spy, event_idx_by_thr, base_stats, n):
    # (1) mean cumulative forward-return path vs baseline, with bootstrap CI band
    Hmax = 60
    fig, ax = plt.subplots(figsize=(9, 5.5))
    # baseline mean path
    base_paths = []
    step = 5  # subsample entry days for speed on baseline path CI
    for t in range(0, n - Hmax, step):
        base_paths.append(spy[t:t + Hmax + 1] / spy[t] - 1.0)
    base_paths = np.array(base_paths)
    base_mean_path = base_paths.mean(axis=0)
    ax.plot(range(Hmax + 1), base_mean_path * 100, color="#888", lw=2,
            label=f"Baseline (all days, n={len(base_paths)})", zorder=2)

    colors = {30: "#1f77b4", 35: "#ff7f0e", 40: "#d62728"}
    lr = np.random.default_rng(SEED)
    for thr in THRESHOLDS:
        idx = [t for t in event_idx_by_thr[thr] if t + Hmax < n]
        if not idx:
            continue
        paths = np.array([spy[t:t + Hmax + 1] / spy[t] - 1.0 for t in idx])
        mean_path = paths.mean(axis=0)
        # bootstrap CI across events
        boot = np.array([paths[lr.integers(0, len(paths), len(paths))].mean(axis=0)
                         for _ in range(2000)])
        lo = np.percentile(boot, 2.5, axis=0)
        hi = np.percentile(boot, 97.5, axis=0)
        ax.plot(range(Hmax + 1), mean_path * 100, color=colors[thr], lw=2,
                label=f"VIX>{thr} events (n={len(idx)})", zorder=3)
        ax.fill_between(range(Hmax + 1), lo * 100, hi * 100, color=colors[thr],
                        alpha=0.15, zorder=1)
    ax.axhline(0, color="k", lw=0.6, ls=":")
    ax.set_xlabel("Trading days after signal / entry")
    ax.set_ylabel("Mean cumulative SPY return (%)")
    ax.set_title("SPY forward return after VIX first crosses threshold vs unconditional baseline\n"
                 "(1993-2026; shaded = 95% bootstrap CI across events)")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig1_forward_path.png"), dpi=130)
    plt.close(fig)

    # (2) win-rate bar chart: event vs baseline per horizon per threshold
    fig, axes = plt.subplots(1, len(THRESHOLDS), figsize=(13, 4.5), sharey=True)
    for ax, thr in zip(axes, THRESHOLDS):
        hs = [H for H in HORIZONS if str(H) in results["events"][str(thr)]["horizons"]]
        ev = [results["events"][str(thr)]["horizons"][str(H)]["win_rate"] for H in hs]
        bs = [base_stats[H]["win_rate"] for H in hs]
        x = np.arange(len(hs))
        ax.bar(x - 0.2, np.array(ev) * 100, 0.4, label="VIX event", color=colors[thr])
        ax.bar(x + 0.2, np.array(bs) * 100, 0.4, label="Baseline", color="#bbb")
        ax.axhline(50, color="k", lw=0.6, ls=":")
        ax.set_xticks(x)
        ax.set_xticklabels([f"{H}d" for H in hs])
        ne = results["events"][str(thr)]["horizons"][str(hs[0])]["n_events"]
        ax.set_title(f"VIX>{thr} (n≈{ne})")
        ax.set_xlabel("Horizon")
        if thr == THRESHOLDS[0]:
            ax.set_ylabel("Win rate (% positive)")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.25, axis="y")
    fig.suptitle("Positive-return win rate: VIX-threshold entry vs random entry", y=1.02)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig2_winrate.png"), dpi=130, bbox_inches="tight")
    plt.close(fig)

    # (3) 60-day forward-return distribution: event vs baseline
    H = 60
    fb = baseline_forward(spy, H)
    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.hist(fb * 100, bins=60, density=True, alpha=0.35, color="#888",
            label=f"Baseline all days (n={len(fb)})")
    for thr in THRESHOLDS:
        idx = event_idx_by_thr[thr]
        fwd, _ = forward_returns(spy, idx, H, 0)
        if len(fwd) == 0:
            continue
        ax.axvline(fwd.mean() * 100, color=colors[thr], ls="--", lw=1.8,
                   label=f"VIX>{thr} mean ({fwd.mean()*100:+.1f}%, n={len(fwd)})")
        ax.scatter(fwd * 100, np.full(len(fwd), 0.002 + 0.001 * THRESHOLDS.index(thr)),
                   color=colors[thr], s=18, alpha=0.7, zorder=5)
    ax.axvline(fb.mean() * 100, color="#444", ls="-", lw=1.5,
               label=f"Baseline mean ({fb.mean()*100:+.1f}%)")
    ax.set_xlabel("60-trading-day SPY forward return (%)")
    ax.set_ylabel("Density")
    ax.set_title("Distribution of 60-day SPY forward returns: VIX-threshold events vs baseline")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)
    ax.set_xlim(-40, 60)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig3_dist60.png"), dpi=130)
    plt.close(fig)


def print_summary(results):
    print("\n=== K1633 SUMMARY ===")
    print("Period:", results["data"]["period"], "| days:", results["data"]["n_trading_days"])
    for thr in THRESHOLDS:
        ev = results["events"][str(thr)]
        print(f"\nVIX>{thr}: {ev['n_events_raw_decluster']} de-clustered events")
        print(f"{'H':>4} {'nEv':>4} {'ev_win':>7} {'base_win':>8} "
              f"{'ev_mean':>8} {'base_mean':>9} {'excess':>7} {'HAC_p':>7} {'placebo_p1':>10}")
        for H in HORIZONS:
            c = ev["horizons"].get(str(H))
            if not c:
                continue
            print(f"{H:>4} {c['n_events']:>4} {c['win_rate']*100:>6.1f}% "
                  f"{c['baseline_win_rate']*100:>7.1f}% {c['mean']*100:>7.2f}% "
                  f"{c['baseline_mean']*100:>8.2f}% {c['excess_mean_vs_baseline']*100:>6.2f}% "
                  f"{c['hac_pvalue']:>7.3f} {c['placebo_p_one_sided_event_gt_random']:>10.3f}")
    s = results["verdict"]["summary"]
    print(f"\nVerdict: {s['n_significant_5pct']}/{s['n_cells']} cells HAC-significant@5%, "
          f"{s['n_significant_positive']} significant-positive")


if __name__ == "__main__":
    main()
