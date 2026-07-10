#!/usr/bin/env python3
"""
K1677 - Fraud / enforcement contagion: peer-volatility spillover.

Research question
-----------------
When a firm's fraud / legal-enforcement shock becomes public (SEC/DOJ charge,
restatement, or a short-seller report that triggered enforcement), do the
firm's SAME-SECTOR PEERS (excluding the focal firm) show, in the t+1..t+10
window, abnormal (a) realized volatility, (b) left-tail risk (downside
semivariance / worst day), and (c) illiquidity (Corwin-Schultz high-low
spread, Amihud) relative to their own recent baseline and to the market?

Honesty / design notes
-----------------------
* Event set is a HAND-CURATED sample of publicly documented US fraud/enforcement
  REVELATION events (experiments/K1677/events.csv). It is NOT the full SEC AAER
  population. Curating salient events biases *toward* finding contagion; the
  placebo control nets out basket-specific volatility clustering but NOT this
  selection. Any positive result must be read as "conditional on salient
  enforcement events" not "enforcement causes contagion on average".
* Event date = first widely-reported public revelation (AAER release dates are
  poor market-event dates, Karpoff-Lee-Martin 2008). t0 = first trading day
  on/after event_date. Windows use ONLY post-event realized data (t+1..t+10);
  no lookahead: measurement window is strictly after t0.
* Contagion target = equal-weighted basket of same-sector liquid PEERS EXCLUDING
  the focal firm (a sector ETF would be contaminated by the focal firm's own
  crash). Focal firm price is never used, so delisted focals are fine.
* Controls: (1) market-adjust vs SPY; (2) per-basket placebo of 200 random
  non-event origins (seed=42) -> standardized abnormality z.
* Aggregation (K1355): ONE number per event (basket mean), then across-event
  t-test / Wilcoxon / bootstrap. No same-day cross-asset iid pooling.

Reproducibility
---------------
* seed = 42 everywhere random is used.
* Prices downloaded via yfinance and cached to experiments/K1677/data/.
* Run:  uv run python experiments/K1677/K1677.py
"""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
DATA.mkdir(exist_ok=True)
RESULTS = HERE / "K1677_results.json"
EVENTS_CSV = HERE / "events.csv"

# window params (trading days, relative to t0 index)
PRE_START = -60      # inclusive
PRE_END = -11        # exclusive upper bound -> pre = [-60, -11): 49 days ending well before event
POST_START = 1       # t+1
POST_END = 11        # exclusive -> t+1..t+10 (10 days)
N_PLACEBO = 200
EXCLUDE_HALO = 30    # trading days around an event's own t0 excluded from placebo pool
MIN_PEERS = 2        # need >=2 peers with full window else event dropped from peer-basket test
DL_START = "1998-01-01"
DL_END = "2025-12-31"


def log(msg):
    print(f"[K1677] {msg}", flush=True)


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def load_events() -> pd.DataFrame:
    ev = pd.read_csv(EVENTS_CSV)
    ev["event_date"] = pd.to_datetime(ev["event_date"])
    ev["peers"] = ev["peers"].apply(lambda s: [t.strip() for t in str(s).split(";") if t.strip()])
    return ev


def all_tickers(ev: pd.DataFrame) -> list[str]:
    s = set(["SPY"])
    for peers in ev["peers"]:
        s.update(peers)
    return sorted(s)


def download_prices(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """Download OHLCV (auto_adjust=False) per ticker; cache to CSV; return dict of DataFrames.

    Returns per-ticker frame with columns: adjclose, high, low, close, volume (raw).
    """
    import yfinance as yf
    out: dict[str, pd.DataFrame] = {}
    for t in tickers:
        cache = DATA / f"px_{t.replace('/', '-')}.csv"
        if cache.exists():
            df = pd.read_csv(cache, index_col=0, parse_dates=True)
            if len(df) > 50:
                out[t] = df
                continue
        try:
            raw = yf.download(t, start=DL_START, end=DL_END, progress=False,
                              auto_adjust=False, actions=False)
        except Exception as e:  # network / delisted
            log(f"download failed {t}: {e}")
            continue
        if raw is None or len(raw) == 0:
            log(f"no data {t}")
            continue
        # flatten possible multiindex columns
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [c[0] for c in raw.columns]
        cols = {}
        adj = "Adj Close" if "Adj Close" in raw.columns else "Close"
        cols["adjclose"] = raw[adj]
        cols["high"] = raw["High"]
        cols["low"] = raw["Low"]
        cols["close"] = raw["Close"]
        cols["volume"] = raw["Volume"]
        df = pd.DataFrame(cols).dropna(subset=["adjclose"])
        if len(df) < 50:
            log(f"too short {t} ({len(df)})")
            continue
        df.to_csv(cache)
        out[t] = df
    return out


# --------------------------------------------------------------------------- #
# Per-basket measures
# --------------------------------------------------------------------------- #
def basket_returns(px: dict[str, pd.DataFrame], peers: list[str]) -> tuple[pd.Series, list[str]]:
    """Equal-weight daily log-return of available peers, aligned on common calendar."""
    rets = {}
    for p in peers:
        if p in px:
            r = np.log(px[p]["adjclose"]).diff()
            rets[p] = r
    if not rets:
        return pd.Series(dtype=float), []
    R = pd.DataFrame(rets)
    used = list(R.columns)
    basket = R.mean(axis=1, skipna=True)  # equal weight across available peers each day
    return basket.dropna(), used


def corwin_schultz_spread(high: pd.Series, low: pd.Series) -> float:
    """Corwin & Schultz (2012) 2-day high-low spread estimator; mean over the window.
    Returns proportional spread (>=0). NaN if <2 obs."""
    h = np.log(high.values.astype(float))
    l = np.log(low.values.astype(float))
    n = len(h)
    if n < 2:
        return np.nan
    const = 3.0 - 2.0 * np.sqrt(2.0)
    spreads = []
    for t in range(n - 1):
        beta = (h[t] - l[t]) ** 2 + (h[t + 1] - l[t + 1]) ** 2
        hmax = max(h[t], h[t + 1])
        lmin = min(l[t], l[t + 1])
        gamma = (hmax - lmin) ** 2
        alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / const - np.sqrt(gamma / const)
        s = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
        spreads.append(max(s, 0.0))
    if not spreads:
        return np.nan
    return float(np.nanmean(spreads))


def peer_spread_window(px: dict[str, pd.DataFrame], peers_used: list[str],
                       calendar: pd.DatetimeIndex, lo: int, hi: int) -> float:
    """Average Corwin-Schultz spread across peers over calendar[lo:hi]."""
    win_dates = calendar[lo:hi]
    vals = []
    for p in peers_used:
        d = px[p]
        sub = d.reindex(win_dates)
        cs = corwin_schultz_spread(sub["high"].dropna(), sub["low"].dropna())
        if not np.isnan(cs):
            vals.append(cs)
    return float(np.nanmean(vals)) if vals else np.nan


def peer_amihud_window(px: dict[str, pd.DataFrame], peers_used: list[str],
                       calendar: pd.DatetimeIndex, lo: int, hi: int) -> float:
    """Average Amihud illiquidity (|ret|/dollarvol, scaled 1e9) across peers."""
    win_dates = calendar[lo:hi]
    vals = []
    for p in peers_used:
        d = px[p]
        sub = d.reindex(win_dates)
        r = np.log(sub["adjclose"]).diff().abs()
        dv = (sub["close"] * sub["volume"]).replace(0, np.nan)
        il = (r / dv * 1e9).replace([np.inf, -np.inf], np.nan).dropna()
        if len(il) > 0:
            vals.append(float(il.mean()))
    return float(np.nanmean(vals)) if vals else np.nan


def rv(returns: np.ndarray) -> float:
    if len(returns) < 2:
        return np.nan
    return float(np.std(returns, ddof=1) * np.sqrt(252))


def downside_semivar(returns: np.ndarray) -> float:
    neg = returns[returns < 0]
    if len(neg) == 0:
        return 0.0
    return float(np.mean(neg ** 2))


def window_metrics(basket: pd.Series, t0_idx: int) -> dict | None:
    """Compute pre/post RV, semivar, worst day for the basket around index t0_idx."""
    n = len(basket)
    if t0_idx + PRE_START < 0 or t0_idx + POST_END > n:
        return None
    vals = basket.values
    pre = vals[t0_idx + PRE_START: t0_idx + PRE_END]
    post = vals[t0_idx + POST_START: t0_idx + POST_END]
    pre = pre[~np.isnan(pre)]
    post = post[~np.isnan(post)]
    if len(pre) < 20 or len(post) < 5:
        return None
    rv_pre, rv_post = rv(pre), rv(post)
    sv_pre, sv_post = downside_semivar(pre), downside_semivar(post)
    if rv_pre <= 0 or rv_post <= 0:
        return None
    return {
        "rv_pre": rv_pre, "rv_post": rv_post,
        "log_rv_ratio": float(np.log(rv_post / rv_pre)),
        "sv_pre": sv_pre, "sv_post": sv_post,
        "log_sv_ratio": float(np.log((sv_post + 1e-12) / (sv_pre + 1e-12))),
        "worst_day_post": float(np.min(post)),
        "pre_daily_std": float(np.std(pre, ddof=1)),
        "n_pre": int(len(pre)), "n_post": int(len(post)),
    }


def placebo_distribution(basket: pd.Series, event_t0_idx: int, metric: str,
                         rng: np.random.Generator) -> tuple[float, float, int]:
    """Distribution of `metric` (log_rv_ratio / log_sv_ratio / worst_day_post)
    over random non-event origins in this basket's own history."""
    n = len(basket)
    lo = -PRE_START               # need this many days before
    hi = n - POST_END             # and after
    valid = [i for i in range(lo, hi)
             if abs(i - event_t0_idx) > EXCLUDE_HALO]
    if len(valid) < 30:
        return np.nan, np.nan, 0
    k = min(N_PLACEBO, len(valid))
    picks = rng.choice(valid, size=k, replace=False)
    out = []
    for i in picks:
        m = window_metrics(basket, int(i))
        if m is not None:
            out.append(m[metric])
    out = np.array(out, dtype=float)
    out = out[~np.isnan(out)]
    if len(out) < 20:
        return np.nan, np.nan, len(out)
    return float(np.mean(out)), float(np.std(out, ddof=1)), len(out)


# --------------------------------------------------------------------------- #
# Aggregate stats
# --------------------------------------------------------------------------- #
def agg_test(x: np.ndarray, rng: np.random.Generator, n_boot: int = 10000) -> dict:
    from scipy import stats
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 3:
        return {"n": int(n), "mean": None, "note": "too few obs"}
    mean = float(np.mean(x))
    se = float(np.std(x, ddof=1) / np.sqrt(n))
    t, p = stats.ttest_1samp(x, 0.0)
    try:
        w_stat, w_p = stats.wilcoxon(x)
        w_p = float(w_p)
    except Exception:
        w_p = None
    # bootstrap CI of the mean
    boot = rng.choice(x, size=(n_boot, n), replace=True).mean(axis=1)
    ci = np.percentile(boot, [2.5, 97.5])
    n_pos = int(np.sum(x > 0))
    # sign test
    sign_p = float(stats.binomtest(n_pos, n, 0.5).pvalue)
    return {
        "n": int(n), "mean": mean, "se": se,
        "t_stat": float(t), "p_ttest": float(p),
        "p_wilcoxon": w_p, "p_sign": sign_p,
        "boot95_lo": float(ci[0]), "boot95_hi": float(ci[1]),
        "n_positive": n_pos, "frac_positive": float(n_pos / n),
    }


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    log("loading events")
    ev = load_events()
    tickers = all_tickers(ev)
    log(f"{len(ev)} events, {len(tickers)} unique tickers")
    px = download_prices(tickers)
    log(f"downloaded {len(px)}/{len(tickers)} tickers")

    spy = px.get("SPY")
    if spy is None:
        log("FATAL: SPY unavailable")
        sys.exit(1)
    spy_ret = np.log(spy["adjclose"]).diff().dropna()

    rng = np.random.default_rng(SEED)

    per_event = []
    dropped = []
    for _, row in ev.iterrows():
        eid = row["event_id"]
        basket, used = basket_returns(px, row["peers"])
        if len(used) < MIN_PEERS or len(basket) < 200:
            dropped.append({"event_id": eid, "reason": f"peers_available={len(used)}"})
            continue
        cal = basket.index
        # t0 = first trading day on/after event_date within basket calendar
        after = cal[cal >= row["event_date"]]
        if len(after) == 0:
            dropped.append({"event_id": eid, "reason": "event_date_after_data"})
            continue
        t0 = after[0]
        t0_idx = cal.get_loc(t0)
        if isinstance(t0_idx, slice) or not isinstance(t0_idx, (int, np.integer)):
            dropped.append({"event_id": eid, "reason": "t0_index"})
            continue
        m = window_metrics(basket, int(t0_idx))
        if m is None:
            dropped.append({"event_id": eid, "reason": "insufficient_window"})
            continue

        # market (SPY) same-window abnormality, aligned to basket trading calendar
        spy_aligned = spy_ret.reindex(cal)
        spy_m = window_metrics(spy_aligned, int(t0_idx))

        # placebo (per basket) for RV, semivar, worst-day
        pl_mu_rv, pl_sd_rv, pl_n_rv = placebo_distribution(basket, int(t0_idx), "log_rv_ratio", rng)
        pl_mu_sv, pl_sd_sv, _ = placebo_distribution(basket, int(t0_idx), "log_sv_ratio", rng)
        pl_mu_wd, pl_sd_wd, _ = placebo_distribution(basket, int(t0_idx), "worst_day_post", rng)

        # spread (Corwin-Schultz) and Amihud pre/post on peer level (raw OHLC)
        lo_pre, hi_pre = int(t0_idx) + PRE_START, int(t0_idx) + PRE_END
        lo_post, hi_post = int(t0_idx) + POST_START, int(t0_idx) + POST_END
        cs_pre = peer_spread_window(px, used, cal, lo_pre, hi_pre)
        cs_post = peer_spread_window(px, used, cal, lo_post, hi_post)
        am_pre = peer_amihud_window(px, used, cal, lo_pre, hi_pre)
        am_post = peer_amihud_window(px, used, cal, lo_post, hi_post)

        def logratio(a, b):
            if a is None or b is None or np.isnan(a) or np.isnan(b) or a <= 0 or b <= 0:
                return None
            return float(np.log(b / a))

        rec = {
            "event_id": eid,
            "focal": row["focal"],
            "event_date": row["event_date"].strftime("%Y-%m-%d"),
            "t0": t0.strftime("%Y-%m-%d"),
            "sector": row["sector"],
            "event_type": row["event_type"],
            "peers_used": used,
            "n_peers": len(used),
            # RV
            "rv_pre": m["rv_pre"], "rv_post": m["rv_post"],
            "log_rv_ratio": m["log_rv_ratio"],
            "spy_log_rv_ratio": (spy_m["log_rv_ratio"] if spy_m else None),
            "mktadj_log_rv_ratio": (m["log_rv_ratio"] - spy_m["log_rv_ratio"]) if spy_m else None,
            "placebo_z_rv": ((m["log_rv_ratio"] - pl_mu_rv) / pl_sd_rv)
                            if (pl_sd_rv and pl_sd_rv > 0) else None,
            # tail
            "log_sv_ratio": m["log_sv_ratio"],
            "spy_log_sv_ratio": (spy_m["log_sv_ratio"] if spy_m else None),
            "mktadj_log_sv_ratio": (m["log_sv_ratio"] - spy_m["log_sv_ratio"]) if spy_m else None,
            "placebo_z_sv": ((m["log_sv_ratio"] - pl_mu_sv) / pl_sd_sv)
                            if (pl_sd_sv and pl_sd_sv > 0) else None,
            "worst_day_post": m["worst_day_post"],
            "placebo_z_worstday": ((m["worst_day_post"] - pl_mu_wd) / pl_sd_wd)
                                  if (pl_sd_wd and pl_sd_wd > 0) else None,
            # liquidity
            "cs_spread_pre": cs_pre, "cs_spread_post": cs_post,
            "log_cs_ratio": logratio(cs_pre, cs_post),
            "amihud_pre": am_pre, "amihud_post": am_post,
            "log_amihud_ratio": logratio(am_pre, am_post),
            "placebo_n_rv": pl_n_rv,
        }
        per_event.append(rec)

    n_ev = len(per_event)
    log(f"usable events: {n_ev}; dropped: {len(dropped)}")

    # aggregate
    def col(key):
        return np.array([r[key] for r in per_event if r.get(key) is not None], dtype=float)

    agg_rng = np.random.default_rng(SEED)
    aggregates = {
        "rv_mktadj": agg_test(col("mktadj_log_rv_ratio"), agg_rng),
        "rv_placebo_z": agg_test(col("placebo_z_rv"), agg_rng),
        "rv_raw_logratio": agg_test(col("log_rv_ratio"), agg_rng),
        "semivar_mktadj": agg_test(col("mktadj_log_sv_ratio"), agg_rng),
        "semivar_placebo_z": agg_test(col("placebo_z_sv"), agg_rng),
        "worstday_placebo_z": agg_test(col("placebo_z_worstday"), agg_rng),
        "spread_cs_logratio": agg_test(col("log_cs_ratio"), agg_rng),
        "amihud_logratio": agg_test(col("log_amihud_ratio"), agg_rng),
    }

    # Benjamini-Hochberg FDR across the aggregate test families (multiple-testing honesty)
    fam_ps = {k: v.get("p_ttest") for k, v in aggregates.items() if v.get("p_ttest") is not None}
    if fam_ps:
        from scipy import stats as _st
        keys = list(fam_ps.keys())
        pvals = np.array([fam_ps[k] for k in keys])
        order = np.argsort(pvals)
        m = len(pvals)
        bh = np.empty(m)
        prev = 1.0
        # standard BH adjusted p (monotone)
        for rank in range(m - 1, -1, -1):
            i = order[rank]
            adj = pvals[i] * m / (rank + 1)
            prev = min(prev, adj)
            bh[i] = min(prev, 1.0)
        fdr = {keys[i]: float(bh[i]) for i in range(m)}
        for k in keys:
            aggregates[k]["p_bh_fdr"] = fdr[k]
        aggregates_fdr_note = ("BH-FDR adjusted p across %d families; none/those <0.05 flagged" % m)
    else:
        aggregates_fdr_note = "no valid p-values for FDR"

    # simple event-type / sector breakdown for RV mkt-adj (diagnostic only)
    by_type = {}
    for r in per_event:
        v = r.get("mktadj_log_rv_ratio")
        if v is None:
            continue
        by_type.setdefault(r["event_type"], []).append(v)
    type_means = {k: {"n": len(v), "mean_mktadj_log_rv": float(np.mean(v))}
                  for k, v in by_type.items()}

    # verdict logic
    prv = aggregates["rv_placebo_z"]
    mrv = aggregates["rv_mktadj"]
    headline_p = prv.get("p_ttest")
    verdict = _verdict(n_ev, mrv, prv)

    results = {
        "experiment_id": "K1677",
        "title": "Fraud / enforcement contagion: peer-volatility spillover",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "seed": SEED,
        "config": {
            "pre_window": [PRE_START, PRE_END], "post_window": [POST_START, POST_END],
            "n_placebo": N_PLACEBO, "min_peers": MIN_PEERS,
            "peer_basket": "equal-weight same-sector peers EXCLUDING focal firm",
            "contagion_measures": ["realized_vol", "downside_semivariance", "worst_day",
                                   "corwin_schultz_spread", "amihud_illiquidity"],
            "controls": ["market_adjust_vs_SPY", "per_basket_placebo_200_random_origins"],
        },
        "data_source": "yfinance daily OHLCV (auto_adjust=False); cached in experiments/K1677/data/",
        "event_set_source": "hand-curated public fraud/enforcement revelation events; experiments/K1677/events.csv",
        "n_events_input": int(len(ev)),
        "n_events_usable": int(n_ev),
        "dropped_events": dropped,
        "verdict": verdict,
        "multiple_testing": aggregates_fdr_note,
        "aggregates": aggregates,
        "by_event_type_mktadj_log_rv": type_means,
        "per_event": per_event,
        "honesty_caveats": [
            "Curated salient-event sample, NOT full AAER population -> selection bias TOWARD contagion.",
            "Placebo nets out basket clustering/baseline but NOT event-selection.",
            "8 aggregate test families; treat single p-values with multiple-testing skepticism (Bonferroni alpha ~0.006).",
            "10-day post window is short; tail quantiles beyond semivariance/worst-day not estimable.",
            "A few events cluster in time (2019-2021); market-adjustment mitigates common shocks but residual dependence possible.",
            "Event dates are hand-compiled from public reporting (+/- ~1 trading day); t0 = first trading day on/after.",
        ],
    }

    with open(RESULTS, "w") as f:
        json.dump(results, f, indent=2, default=float)
    log(f"wrote {RESULTS}")

    # event table CSV
    pd.DataFrame(per_event).drop(columns=["peers_used"]).to_csv(HERE / "K1677_event_table.csv", index=False)

    _make_figure(per_event, aggregates)

    # console summary
    log("=== SUMMARY ===")
    log(f"usable N = {n_ev}")
    for k, a in aggregates.items():
        if a.get("mean") is not None:
            log(f"{k:22s} mean={a['mean']:+.4f} t={a.get('t_stat'):+.2f} "
                f"p={a.get('p_ttest'):.3f} pos={a.get('n_positive')}/{a['n']}")
    log(f"VERDICT: {verdict}")


def _verdict(n_ev, mrv, prv):
    if n_ev < 10:
        return "BLOCKED_INSUFFICIENT_EVENTS"
    p_m = mrv.get("p_ttest")
    p_p = prv.get("p_ttest")
    mean_m = mrv.get("mean")
    if p_m is None or p_p is None:
        return "NULL_INSUFFICIENT_STATS"
    strong = (mean_m is not None and mean_m > 0 and p_m < 0.006 and p_p < 0.006)
    moderate = (mean_m is not None and mean_m > 0 and (p_m < 0.05 or p_p < 0.05))
    if strong:
        base = "CONTAGION_SIGNAL"
    elif moderate:
        base = "SUGGESTIVE_CONTAGION"
    else:
        base = "NULL_NO_ROBUST_PEER_CONTAGION"
    if n_ev < 30:
        base += "_UNDERPOWERED"
    return base


def _make_figure(per_event, aggregates):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        log(f"matplotlib unavailable: {e}")
        return
    ev = [r for r in per_event if r.get("mktadj_log_rv_ratio") is not None]
    ev = sorted(ev, key=lambda r: r["mktadj_log_rv_ratio"])
    labels = [f"{r['focal']} {r['event_date'][:4]}" for r in ev]
    vals = [r["mktadj_log_rv_ratio"] for r in ev]
    fig, ax = plt.subplots(figsize=(8, max(5, 0.32 * len(ev))))
    colors = ["#c0392b" if v > 0 else "#2c7fb8" for v in vals]
    ax.barh(range(len(ev)), vals, color=colors)
    ax.set_yticks(range(len(ev)))
    ax.set_yticklabels(labels, fontsize=8)
    ax.axvline(0, color="k", lw=0.8)
    a = aggregates["rv_mktadj"]
    ax.axvline(a["mean"], color="green", ls="--", lw=1.2,
               label=f"mean={a['mean']:+.3f} (p={a['p_ttest']:.3f}, N={a['n']})")
    ax.set_xlabel("Peer-basket market-adjusted log(RV_post/RV_pre), t+1..t+10")
    ax.set_title("K1677: Fraud/enforcement peer-volatility contagion by event")
    ax.legend(fontsize=8, loc="lower right")
    fig.tight_layout()
    fig.savefig(HERE / "K1677_contagion_by_event.png", dpi=130)
    log("wrote figure K1677_contagion_by_event.png")


if __name__ == "__main__":
    main()
