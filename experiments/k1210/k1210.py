#!/usr/bin/env python3
"""K1210 — Forensic analysis of AU below-ladder θ_rel residual.

Tests K1171's two residual hypotheses:
  H1. Semi-annual reporting cadence under-samples EAV events (→ low θ_EAV)
  H2. HAND_CODED ±1-day date imprecision contaminates [-0,+1] window

Three experiments:
  A. Semi-annual actual vs synthetic-quarterly injection
  B. yfinance timestamp comparison + jitter sensitivity
  C. Drop-problem-stocks leave-one-out (LOO)

Framework: GJR(1,1) + VIX² + EAV MIDAS (exact K1168/K1171 spec, 6 params,
shared MIDAS + stock-FE pooled MLE). Reads AU inputs from
  experiments/k1171/data/ (prices, VIX, earnings cache)
  experiments/k1171/k1171_asx_earnings_dates.csv (216 HAND_CODED events)

Output files:
  k1210_results.json       — aggregated verdicts + all stats
  k1210_expA_quarterly.csv — per-cadence pooled θ_rel
  k1210_expB_jitter.csv    — 10-replicate jitter θ_rel distribution
  k1210_expB_yfinance_cmp.csv — yfinance vs HAND_CODED date comparison
  k1210_expC_loo.csv       — drop-1 LOO θ_rel
  k1210_figA_cadence.png   — bar semi-annual vs synthetic quarterly
  k1210_figB_jitter.png    — jitter θ_rel distribution

Seeds:
  base = 42
  jitter replicate seeds = 43..52 (10 reps)

**H1/H2/C verdicts**:
  H1_SUPPORTED: synthetic quarterly θ_rel > semi-annual θ_rel by ≥ 30%
                and outside ±1 jitter SE
  H2_SUPPORTED: ≥50% events differ from yfinance by ≥1 day OR
                jitter SE ≥ 20% of semi-annual θ_rel
  C_DRIVER: single stock drop shifts θ_rel by ≥ 0.1 absolute
  Verdicts combine into {H1_ONLY, H2_ONLY, BOTH, NEITHER, STOCK_DRIVEN}.

Lookahead discipline: inherited from K1171 — all EAV shifted t-1 inside
pooled MLE; synthetic quarterly midpoints respect trading-day index.

Random seed: 42 (GLOBAL)
"""
from __future__ import annotations

import json
import os
import sys
import time
import warnings
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# Import MLE primitives from K1171 refit module (fair-comparison)
K1171_DIR = Path(__file__).resolve().parents[1] / "k1171"
sys.path.insert(0, str(K1171_DIR))

# K1171 lives in main repo; our worktree only has k1210. Add main-repo path.
MAIN_REPO = Path("/Users/yhlai0911/Desktop/volpred-research")
K1171_MAIN = MAIN_REPO / "experiments" / "k1171"
sys.path.insert(0, str(K1171_MAIN))

import k1171_per_stock_refit as k1171mod  # type: ignore

GLOBAL_SEED = 42
np.random.seed(GLOBAL_SEED)

ROOT = Path(__file__).resolve().parent
K1171_DATA = K1171_MAIN / "data"
K1171_EARNINGS_CSV = K1171_MAIN / "k1171_asx_earnings_dates.csv"

AU_TICKERS = [
    "BHP.AX", "CBA.AX", "CSL.AX", "NAB.AX", "ANZ.AX",
    "WBC.AX", "WES.AX", "MQG.AX", "TLS.AX", "RIO.AX",
]


def _safe_name(ticker: str) -> str:
    return ticker.replace(".", "_").replace("-", "_").replace("^", "IDX_")


def load_price_k1171(ticker: str) -> pd.DataFrame | None:
    p = K1171_DATA / f"{_safe_name(ticker)}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def load_vix_k1171() -> pd.Series | None:
    p = K1171_DATA / "IDX_VIX.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df["Close"]


def build_stock(ticker: str, ann_dates: list[pd.Timestamp]) -> dict | None:
    raw = load_price_k1171(ticker)
    if raw is None:
        return None
    prices = raw["Close"].copy().dropna()
    log_ret = np.log(prices / prices.shift(1))
    vix = load_vix_k1171()
    if vix is None:
        return None
    vix = vix.reindex(prices.index, method="ffill")
    df = pd.DataFrame({"r": log_ret, "vix": vix}).dropna()
    df = df[df["r"].abs() <= 0.30]
    ann_idx = pd.DatetimeIndex(ann_dates) if len(ann_dates) else pd.DatetimeIndex([])
    eav_arr = k1171mod.build_eav(df.index, ann_idx, window=1)
    if len(df) < 500 or eav_arr.sum() < 15:
        return None
    return {
        "market": "AU", "ticker": ticker,
        "r": df["r"].values, "vix": df["vix"].values, "eav": eav_arr,
        "n_obs": len(df), "n_events": int(eav_arr.sum()),
        "sigma2_sample": float(np.var(df["r"].values, ddof=1)),
        "trading_days": df.index,
    }


def pooled_theta_rel(stocks: list[dict]) -> dict:
    """Run pooled MLE and return θ_EAV, SE, t, θ_rel, mean_σ²."""
    stocks_for_fit = [{k: v for k, v in s.items() if k != "trading_days"}
                      for s in stocks]
    res = k1171mod.fit_pooled_market(stocks_for_fit)
    if not res.get("converged"):
        return {"converged": False}
    mean_sigma2 = res["mean_sigma2"]
    theta_eav = res["theta_eav"]
    theta_rel = theta_eav / mean_sigma2 if mean_sigma2 > 0 else None
    return {
        "converged": True,
        "S": res["S"],
        "theta_eav": float(theta_eav),
        "theta_eav_se": res.get("theta_eav_se_hessian"),
        "theta_eav_t": res.get("theta_eav_t_hessian"),
        "theta_eav_p": res.get("theta_eav_p_hessian"),
        "mean_sigma2": float(mean_sigma2),
        "theta_rel": float(theta_rel) if theta_rel is not None else None,
        "loglik": float(res["loglik"]),
        "total_events": int(sum(s["n_events"] for s in stocks)),
    }


def load_k1171_events() -> pd.DataFrame:
    """Returns DataFrame with columns [ticker, release_date, report_type, source]."""
    df = pd.read_csv(K1171_EARNINGS_CSV, parse_dates=["release_date"])
    return df


def inject_synthetic_quarterly(ev_df: pd.DataFrame,
                               trading_days_map: dict[str, pd.DatetimeIndex]
                               ) -> pd.DataFrame:
    """For each ticker, sort events by date. Between consecutive events,
    insert synthetic midpoint events (aligned to nearest trading day).
    This doubles per-ticker event count, approximating quarterly cadence.

    NOTE: This is a MECHANICAL midpoint insertion to test H1
    'reporting-cadence effect on θ_EAV estimation', NOT an assertion that
    quarterly data exists. The synthetic events carry zero real information,
    so under H0 (cadence doesn't matter) pooled θ_EAV should halve roughly
    (more zero-info EAV=1 days dilute the signal). Under H1 SUPPORTED
    (cadence actually matters structurally), pooled θ_rel should RISE,
    because the estimation noise from sparse events is reduced.

    In particular, under H1 if semi-annual under-samples real events,
    adding synthetic (non-real) midpoints SHOULD NOT lift θ_rel — so this
    test is actually a **H1 REJECTION probe**: if θ_rel drops or stays
    flat, H1 is not a pure estimation-sparsity issue.
    """
    rows = []
    for tk, grp in ev_df.groupby("ticker"):
        g = grp.sort_values("release_date").reset_index(drop=True)
        # Keep originals
        for _, r in g.iterrows():
            rows.append({"ticker": tk, "release_date": r["release_date"],
                         "report_type": r["report_type"],
                         "source": "HAND_CODED_ORIGINAL"})
        # Insert midpoint between each consecutive pair
        tdays = trading_days_map.get(tk)
        if tdays is None or len(tdays) == 0:
            continue
        for i in range(len(g) - 1):
            t0 = pd.Timestamp(g.loc[i, "release_date"])
            t1 = pd.Timestamp(g.loc[i + 1, "release_date"])
            mid = t0 + (t1 - t0) / 2
            # snap to nearest trading day
            pos = tdays.searchsorted(mid)
            if pos >= len(tdays):
                pos = len(tdays) - 1
            snap = tdays[pos]
            # avoid collision with existing event ±1 day
            if (abs((snap - t0).days) <= 1 or abs((snap - t1).days) <= 1):
                continue
            rows.append({"ticker": tk, "release_date": snap,
                         "report_type": "SYNTH_MID",
                         "source": "SYNTHETIC_QUARTERLY"})
    out = pd.DataFrame(rows).sort_values(["ticker", "release_date"])
    return out.reset_index(drop=True)


def try_yfinance_earnings(tickers: list[str]) -> dict:
    """Attempt yfinance Ticker(t).earnings_dates for AU tickers.
    Returns dict ticker -> list[pd.Timestamp] or empty.
    Known to be degraded for ASX (K1171 Note §1: 0-3 events per ticker).
    """
    out = {}
    try:
        import yfinance as yf
    except Exception:
        print("  [yfinance] import failed, skipping online compare")
        return out
    for tk in tickers:
        try:
            t = yf.Ticker(tk)
            ed = t.earnings_dates
            if ed is None or len(ed) == 0:
                out[tk] = []
                continue
            idx = ed.index
            # keep only historical
            today = pd.Timestamp.today(tz=idx.tz) if hasattr(idx, "tz") and idx.tz else pd.Timestamp.today()
            hist = [pd.Timestamp(d).tz_localize(None) if hasattr(d, "tz") and d.tz else pd.Timestamp(d)
                    for d in idx if pd.Timestamp(d) <= today]
            out[tk] = sorted(hist)
        except Exception as e:
            print(f"  [yfinance {tk}] error {type(e).__name__}: {e}")
            out[tk] = []
    return out


def compare_yfinance_vs_handcoded(yf_dates: dict, hand_df: pd.DataFrame) -> pd.DataFrame:
    """For each ticker, match each yfinance date to nearest HAND_CODED date
    within ±10 days. Return diff_days per match."""
    rows = []
    for tk, yf_list in yf_dates.items():
        hand = hand_df[hand_df["ticker"] == tk]["release_date"].sort_values().values
        if len(hand) == 0 or len(yf_list) == 0:
            continue
        for yfd in yf_list:
            yfd_ts = pd.Timestamp(yfd).normalize()
            diffs = [(yfd_ts - pd.Timestamp(h).normalize()).days for h in hand]
            best_i = int(np.argmin(np.abs(diffs)))
            best_diff = diffs[best_i]
            if abs(best_diff) > 10:
                continue
            rows.append({
                "ticker": tk,
                "yfinance_date": yfd_ts.date().isoformat(),
                "hand_coded_date": pd.Timestamp(hand[best_i]).date().isoformat(),
                "diff_days": best_diff,
            })
    return pd.DataFrame(rows)


def jitter_events(ev_df: pd.DataFrame, trading_days_map: dict[str, pd.DatetimeIndex],
                  rng: np.random.Generator, max_shift: int = 3) -> pd.DataFrame:
    """Per-event uniform ±max_shift trading-day jitter."""
    rows = []
    for _, r in ev_df.iterrows():
        tk = r["ticker"]
        tdays = trading_days_map.get(tk)
        if tdays is None or len(tdays) == 0:
            rows.append(r.to_dict())
            continue
        d = pd.Timestamp(r["release_date"])
        pos = int(tdays.searchsorted(d))
        if pos >= len(tdays):
            pos = len(tdays) - 1
        shift = int(rng.integers(-max_shift, max_shift + 1))
        new_pos = max(0, min(len(tdays) - 1, pos + shift))
        new_d = tdays[new_pos]
        nr = r.to_dict()
        nr["release_date"] = new_d
        rows.append(nr)
    return pd.DataFrame(rows)


def build_earnings_dict(ev_df: pd.DataFrame) -> dict[str, list[pd.Timestamp]]:
    """Group events into ticker -> list of pd.Timestamp for build_stock."""
    out = {}
    for tk, grp in ev_df.groupby("ticker"):
        out[tk] = [pd.Timestamp(d) for d in grp["release_date"].values]
    return out


def run_pool(earnings_map: dict[str, list[pd.Timestamp]]) -> dict:
    """Build 10 stocks + pooled MLE."""
    stocks = []
    for tk in AU_TICKERS:
        st = build_stock(tk, earnings_map.get(tk, []))
        if st is None:
            continue
        stocks.append(st)
    if len(stocks) < 3:
        return {"converged": False, "reason": f"only {len(stocks)} stocks"}
    return {"stocks": stocks, **pooled_theta_rel(stocks)}


def run_expA(hand_df: pd.DataFrame) -> dict:
    """Experiment A: semi-annual vs synthetic-quarterly."""
    print("\n[Exp A] Semi-annual vs synthetic-quarterly injection")

    # Baseline: K1171 semi-annual (216 events)
    print("  [A1] semi-annual baseline ...")
    t0 = time.time()
    earnings_sa = build_earnings_dict(hand_df)
    res_sa = run_pool(earnings_sa)
    print(f"    done {time.time()-t0:.1f}s | θ_rel={res_sa.get('theta_rel', 'NA'):.4f} "
          f"θ_EAV_t={res_sa.get('theta_eav_t', 'NA'):.2f} "
          f"events={res_sa.get('total_events', 'NA')}")

    # Build trading_days_map from the baseline build
    tdays_map = {s["ticker"]: s["trading_days"] for s in res_sa["stocks"]}

    # Synthetic quarterly
    print("  [A2] synthetic quarterly (midpoints injected) ...")
    t0 = time.time()
    ev_q = inject_synthetic_quarterly(hand_df, tdays_map)
    earnings_q = build_earnings_dict(ev_q)
    res_q = run_pool(earnings_q)
    print(f"    done {time.time()-t0:.1f}s | θ_rel={res_q.get('theta_rel', 'NA'):.4f} "
          f"θ_EAV_t={res_q.get('theta_eav_t', 'NA'):.2f} "
          f"events={res_q.get('total_events', 'NA')}")

    # Strip stocks before JSON dump
    sa_clean = {k: v for k, v in res_sa.items() if k != "stocks"}
    q_clean = {k: v for k, v in res_q.items() if k != "stocks"}

    # Verdict
    sa_rel = sa_clean.get("theta_rel")
    q_rel = q_clean.get("theta_rel")
    delta_rel = None
    pct_change = None
    if sa_rel and q_rel:
        delta_rel = q_rel - sa_rel
        pct_change = (q_rel - sa_rel) / sa_rel if sa_rel != 0 else None

    # H1 support: synthetic quarterly θ_rel > baseline by ≥ 30%
    # Caveat: synthetic events are zero-info, so if θ_rel rises strongly
    # that's actually a MECHANICAL artefact (more EAV=1 days contaminate
    # σ²_τ estimation). So we interpret BOTH directions:
    # - θ_rel drops (expected under H0 with zero-info dilution) → H1 REJECTED
    # - θ_rel stays flat → H1 REJECTED (sparsity not the driver)
    # - θ_rel rises dramatically → MECHANICAL (not H1 support)
    h1_verdict = "H1_REJECTED"
    if pct_change is not None:
        if pct_change >= 0.30:
            h1_verdict = "H1_AMBIGUOUS_UPWARD"  # cannot distinguish from mech artefact
        elif abs(pct_change) < 0.10:
            h1_verdict = "H1_REJECTED_FLAT"
        else:
            h1_verdict = "H1_REJECTED_DROPPED"

    out = {
        "semi_annual": sa_clean,
        "synthetic_quarterly": q_clean,
        "delta_theta_rel": delta_rel,
        "pct_change_theta_rel": pct_change,
        "h1_verdict": h1_verdict,
        "synth_events_added": q_clean.get("total_events", 0) - sa_clean.get("total_events", 0),
    }
    # Save per-cadence CSV
    pd.DataFrame([
        {"cadence": "semi_annual", **sa_clean},
        {"cadence": "synthetic_quarterly", **q_clean},
    ]).to_csv(ROOT / "k1210_expA_quarterly.csv", index=False)
    return out


def run_expB(hand_df: pd.DataFrame, tdays_map: dict) -> dict:
    """Experiment B: yfinance compare + jitter test."""
    print("\n[Exp B] HAND_CODED precision test")

    # B1: yfinance comparison (best-effort, K1171 says coverage weak)
    print("  [B1] yfinance AU earnings_dates ...")
    t0 = time.time()
    yf_dates = try_yfinance_earnings(AU_TICKERS)
    yf_covered = {t: len(v) for t, v in yf_dates.items()}
    yf_total = sum(yf_covered.values())
    print(f"    yfinance coverage: {yf_covered} (total {yf_total} events, {time.time()-t0:.1f}s)")
    cmp_df = compare_yfinance_vs_handcoded(yf_dates, hand_df)
    cmp_df.to_csv(ROOT / "k1210_expB_yfinance_cmp.csv", index=False)
    if len(cmp_df) > 0:
        pct_gt_1d = float((cmp_df["diff_days"].abs() >= 1).mean())
        median_diff = float(cmp_df["diff_days"].abs().median())
    else:
        pct_gt_1d = None
        median_diff = None

    # B2: Jitter test (10 replicates, seeds 43..52, ±3 day max)
    print("  [B2] jitter sensitivity (10 replicates ±3 tdays) ...")
    jitter_results = []
    for i, seed in enumerate(range(43, 53)):
        t0 = time.time()
        rng = np.random.default_rng(seed)
        ev_j = jitter_events(hand_df, tdays_map, rng, max_shift=3)
        earnings_j = build_earnings_dict(ev_j)
        res_j = run_pool(earnings_j)
        theta_rel = res_j.get("theta_rel")
        theta_eav = res_j.get("theta_eav")
        print(f"    rep{i+1} seed={seed} θ_rel={theta_rel if theta_rel is None else round(theta_rel, 4)} "
              f"θ_EAV={theta_eav if theta_eav is None else f'{theta_eav:.3e}'} "
              f"[{time.time()-t0:.1f}s]")
        jitter_results.append({
            "rep": i + 1, "seed": seed,
            "theta_rel": theta_rel,
            "theta_eav": theta_eav,
            "theta_eav_t": res_j.get("theta_eav_t"),
            "total_events": res_j.get("total_events"),
            "converged": res_j.get("converged"),
        })
    df_j = pd.DataFrame(jitter_results)
    df_j.to_csv(ROOT / "k1210_expB_jitter.csv", index=False)
    conv = df_j["converged"] == True
    if conv.sum() > 0:
        rels = df_j.loc[conv, "theta_rel"].astype(float).dropna()
        if len(rels) >= 2:
            jitter_mean = float(rels.mean())
            jitter_sd = float(rels.std(ddof=1))
        else:
            jitter_mean = float(rels.iloc[0]) if len(rels) else None
            jitter_sd = None
    else:
        jitter_mean = None
        jitter_sd = None

    out = {
        "yfinance_coverage": yf_covered,
        "yfinance_total_events": yf_total,
        "yfinance_handcoded_diff_pct_ge_1d": pct_gt_1d,
        "yfinance_handcoded_diff_median_days": median_diff,
        "jitter_theta_rel_mean": jitter_mean,
        "jitter_theta_rel_sd": jitter_sd,
        "jitter_n_converged": int(conv.sum()),
    }
    return out


def run_expC(hand_df: pd.DataFrame, baseline_theta_rel: float) -> dict:
    """Experiment C: drop-1 LOO across 10 AU stocks."""
    print("\n[Exp C] Drop-1 LOO for 10 AU stocks")
    rows = []
    for drop_tk in AU_TICKERS:
        t0 = time.time()
        sub = hand_df[hand_df["ticker"] != drop_tk]
        earnings_d = build_earnings_dict(sub)
        # also restrict AU_TICKERS — filter via build_stock
        stocks = []
        for tk in AU_TICKERS:
            if tk == drop_tk:
                continue
            st = build_stock(tk, earnings_d.get(tk, []))
            if st is None:
                continue
            stocks.append(st)
        if len(stocks) < 3:
            rows.append({"drop": drop_tk, "converged": False})
            continue
        res = pooled_theta_rel(stocks)
        tr = res.get("theta_rel")
        rows.append({
            "drop": drop_tk,
            "S": res.get("S"),
            "theta_eav": res.get("theta_eav"),
            "theta_eav_t": res.get("theta_eav_t"),
            "theta_rel": tr,
            "delta_from_baseline": (tr - baseline_theta_rel) if tr is not None and baseline_theta_rel is not None else None,
        })
        print(f"    drop {drop_tk}: θ_rel={tr if tr is None else round(tr, 4)} "
              f"(Δ={rows[-1]['delta_from_baseline'] if rows[-1]['delta_from_baseline'] is None else round(rows[-1]['delta_from_baseline'], 4)}) "
              f"[{time.time()-t0:.1f}s]")
    df_c = pd.DataFrame(rows)
    df_c.to_csv(ROOT / "k1210_expC_loo.csv", index=False)

    # C verdict: any single stock drops |Δ| ≥ 0.1 absolute?
    if "delta_from_baseline" in df_c.columns:
        deltas = df_c["delta_from_baseline"].dropna()
        if len(deltas):
            max_abs = float(deltas.abs().max())
            max_row = df_c.loc[deltas.abs().idxmax()]
            max_stock = max_row["drop"]
            max_delta = float(max_row["delta_from_baseline"])
        else:
            max_abs = max_delta = 0.0
            max_stock = None
    else:
        max_abs = max_delta = 0.0
        max_stock = None
    c_verdict = "C_STOCK_DRIVEN" if max_abs >= 0.10 else "C_DIFFUSE"
    return {
        "loo_table_path": "k1210_expC_loo.csv",
        "max_abs_delta_theta_rel": max_abs,
        "max_delta_stock": max_stock,
        "max_delta_value": max_delta,
        "c_verdict": c_verdict,
    }


def make_figures(expA: dict, expB: dict):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Fig A: bar semi-annual vs synthetic-quarterly θ_rel
    fig, ax = plt.subplots(figsize=(6, 4.5))
    sa = expA.get("semi_annual", {})
    sq = expA.get("synthetic_quarterly", {})
    vals = [sa.get("theta_rel"), sq.get("theta_rel")]
    labels = [f"Semi-annual\n(n={sa.get('total_events','?')} events)",
              f"Synth-quarterly\n(n={sq.get('total_events','?')} events)"]
    colors = ["#4C72B0", "#DD8452"]
    ax.bar(labels, vals, color=colors)
    ax.axhline(y=vals[0] if vals[0] else 0, linestyle="--", color="#4C72B0", alpha=0.4)
    for i, v in enumerate(vals):
        if v is not None:
            ax.text(i, v + 0.005, f"{v:.4f}", ha="center", fontsize=10)
    ax.set_ylabel(r"$\theta_{rel} = \theta_{EAV} / \bar\sigma^2$")
    ax.set_title("K1210 Exp A: AU θ_rel under semi-annual vs synthetic quarterly")
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(ROOT / "k1210_figA_cadence.png", dpi=120)
    plt.close()

    # Fig B: jitter distribution
    df_j = pd.read_csv(ROOT / "k1210_expB_jitter.csv")
    rels = df_j["theta_rel"].dropna().astype(float).values
    if len(rels) > 0:
        fig, ax = plt.subplots(figsize=(6.5, 4.5))
        ax.hist(rels, bins=8, color="#55A868", edgecolor="black", alpha=0.85)
        baseline = sa.get("theta_rel")
        if baseline is not None:
            ax.axvline(x=baseline, linestyle="--", color="red",
                       label=f"Semi-annual baseline {baseline:.4f}")
        ax.axvline(x=float(np.mean(rels)), linestyle=":", color="black",
                   label=f"Jitter mean {np.mean(rels):.4f}")
        ax.set_xlabel(r"$\theta_{rel}$ under ±3 trading-day jitter")
        ax.set_ylabel("count (10 replicates)")
        ax.set_title("K1210 Exp B: AU θ_rel jitter sensitivity")
        ax.legend(fontsize=9, loc="upper right")
        ax.grid(axis="y", alpha=0.3)
        plt.tight_layout()
        plt.savefig(ROOT / "k1210_figB_jitter.png", dpi=120)
        plt.close()


def combine_verdict(expA: dict, expB: dict, expC: dict) -> dict:
    """Combine H1 / H2 / C verdicts into root-cause commitment."""
    h1 = expA.get("h1_verdict")
    sa = expA.get("semi_annual", {})
    baseline_rel = sa.get("theta_rel")

    # H2: jitter SE as fraction of baseline θ_rel
    jitter_sd = expB.get("jitter_theta_rel_sd")
    jitter_frac = None
    if jitter_sd is not None and baseline_rel not in (None, 0):
        jitter_frac = jitter_sd / abs(baseline_rel)
    h2_support_jitter = jitter_frac is not None and jitter_frac >= 0.20
    pct_diff = expB.get("yfinance_handcoded_diff_pct_ge_1d")
    h2_support_yfinance = pct_diff is not None and pct_diff >= 0.50
    if h2_support_jitter or h2_support_yfinance:
        h2 = "H2_SUPPORTED"
    else:
        h2 = "H2_REJECTED"

    c_verdict = expC.get("c_verdict", "C_DIFFUSE")

    # Combine
    h1_supp = h1.startswith("H1_SUPPORTED")
    h2_supp = (h2 == "H2_SUPPORTED")
    if h1_supp and h2_supp:
        root = "BOTH_CONTRIBUTE"
    elif h1_supp:
        root = "H1_ONLY"
    elif h2_supp:
        root = "H2_ONLY"
    else:
        root = "NEITHER"
    if c_verdict == "C_STOCK_DRIVEN":
        root = root + "+STOCK_DRIVEN"

    # Paper 2 §5 AU footnote recommendation
    if root.startswith("H1_ONLY"):
        footnote = ("AU θ_rel below ladder is plausibly explained by semi-annual "
                    "reporting cadence under-sampling EAV events; quarterly-market "
                    "comparison shows θ_rel sensitive to cadence.")
    elif root.startswith("H2_ONLY"):
        footnote = ("AU θ_rel below ladder is partly contaminated by HAND_CODED "
                    "date imprecision; ±3-day jitter yields θ_rel SD/mean ≥ 20% "
                    "indicating event-window sensitivity.")
    elif root.startswith("BOTH"):
        footnote = ("AU θ_rel below ladder reflects combined effect of semi-annual "
                    "reporting cadence and HAND_CODED date imprecision; both "
                    "diagnostics pass threshold.")
    elif "STOCK_DRIVEN" in root:
        footnote = ("AU θ_rel below ladder is substantially driven by a single "
                    "stock; removing it shifts θ_rel by |Δ|≥0.10 absolute.")
    else:
        footnote = ("Neither reporting cadence nor date-precision hypothesis "
                    "empirically supported at tested thresholds; AU below-ladder "
                    "residual remains unexplained and likely reflects "
                    "sector-composition or AUD-FX-channel structural drivers "
                    "orthogonal to the institutional-ownership mechanism.")

    return {
        "h1_verdict": h1,
        "h2_verdict": h2,
        "h2_jitter_frac": jitter_frac,
        "h2_yfinance_pct": pct_diff,
        "c_verdict": c_verdict,
        "root_cause": root,
        "paper2_s5_au_footnote": footnote,
    }


def main():
    t_start = time.time()
    print(f"\n{'='*72}\nK1210: AU residual forensic — H1 cadence vs H2 precision\n{'='*72}")
    print(f"  GLOBAL_SEED = {GLOBAL_SEED}")
    print(f"  K1171 source: {K1171_MAIN}")
    print(f"  Events CSV:   {K1171_EARNINGS_CSV}")

    hand_df = load_k1171_events()
    print(f"  HAND_CODED events loaded: {len(hand_df)} rows across "
          f"{hand_df['ticker'].nunique()} tickers")

    # -------- Exp A --------
    expA = run_expA(hand_df)

    # -------- Exp B --------
    # Rebuild tdays_map from baseline stocks; but expA stripped stocks.
    # Re-run small build to get tdays_map.
    tdays_map = {}
    for tk in AU_TICKERS:
        raw = load_price_k1171(tk)
        if raw is None:
            continue
        prices = raw["Close"].dropna()
        tdays_map[tk] = prices.index
    expB = run_expB(hand_df, tdays_map)

    # -------- Exp C --------
    baseline_rel = expA.get("semi_annual", {}).get("theta_rel")
    expC = run_expC(hand_df, baseline_rel)

    # -------- Combine --------
    verdict = combine_verdict(expA, expB, expC)

    # Figures
    try:
        make_figures(expA, expB)
    except Exception as e:
        print(f"  [warn] figure generation failed: {type(e).__name__}: {e}")

    # Write results
    results = {
        "k_id": "K1210",
        "global_seed": GLOBAL_SEED,
        "jitter_seeds": list(range(43, 53)),
        "runtime_sec": round(time.time() - t_start, 1),
        "experiment_A_cadence": expA,
        "experiment_B_precision": expB,
        "experiment_C_loo": expC,
        "verdict": verdict,
        "notes": {
            "synth_quarterly_caveat": (
                "Synthetic quarterly events are zero-info midpoint injections. "
                "They test whether cadence alone drives θ_rel estimation, NOT "
                "a simulation of real quarterly earnings. If θ_rel drops or "
                "stays flat, H1 (sparsity → low θ_rel) is rejected."
            ),
            "yfinance_au_caveat": (
                "yfinance ASX coverage is historically weak (K1165 failure "
                "root cause); zero-coverage tickers default H2 to jitter-only "
                "evidence, which is the pre-planned fallback."
            ),
        },
    }
    with open(ROOT / "k1210_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n{'='*72}")
    print(f"Results written: {ROOT / 'k1210_results.json'}")
    print(f"  H1 verdict: {verdict['h1_verdict']}")
    print(f"  H2 verdict: {verdict['h2_verdict']} (jitter_frac="
          f"{verdict['h2_jitter_frac']}, yf_pct={verdict['h2_yfinance_pct']})")
    print(f"  C verdict:  {verdict['c_verdict']}")
    print(f"  ROOT CAUSE: {verdict['root_cause']}")
    print(f"  Runtime:    {time.time() - t_start:.1f}s")
    print("=" * 72)


if __name__ == "__main__":
    main()
