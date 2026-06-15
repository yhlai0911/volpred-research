"""K1506: Treasury auction bid-to-cover weakness → MOVE realized vol event study.

Hypothesis:
    Weak Treasury auctions (low bid-to-cover ratio relative to its rolling
    12M baseline) signal dealer inventory pressure and information shock,
    which should be followed by elevated ^MOVE realized vol over the next
    5 trading days vs benign auctions.

Design:
    - Sample: 10Y Note + 30Y Bond auctions, 2015-01-01 ~ today.
    - Signal: z-score of bidToCoverRatio vs trailing 12-month rolling
      mean/std (strictly past, NO look-ahead).
    - Event categories:
        weak   : z < -1.5
        benign : abs(z) < 0.5
    - Realized vol: cumulative sqrt(sum log_ret^2) over T+1..T+5
      (auction information is fully known only after T's close, so forward
      window starts at T+1; this is the lookahead-safe convention).
    - Tests: Welch two-sample t-test, bootstrap 95% CI (seed=42, 5000 reps),
      Cohen's d.
    - Robustness: stratify by maturity (10Y / 30Y) and by VIX regime
      (high vs low using rolling 12M median of ^VIX at T).

Honest constraints:
    - Free-tier yfinance daily close only (no intraday RV).
    - ^MOVE history begins ~2002 on yfinance; auction sample drives the
      effective N.
    - Welch t-test used because weak/benign sub-sample variances may differ.
"""

from __future__ import annotations

import json
import math
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from scipy import stats

SEED = 42
np.random.seed(SEED)

ROOT = Path(__file__).resolve().parent
FIG_DIR = ROOT / "figures"
FIG_DIR.mkdir(exist_ok=True)

START_DATE = "2015-01-01"
END_DATE = date.today().isoformat()

WEAK_Z = -1.5
BENIGN_Z = 0.5
ROLL_MONTHS = 12  # months for z-score baseline

PRE_DAYS = 5
POST_DAYS = 5
BOOTSTRAP_REPS = 5000

UA = {"User-Agent": "Mozilla/5.0 (research; volpred K1506; contact: research@volpred.local)"}


# ---------------------------------------------------------------------------
# Data fetch
# ---------------------------------------------------------------------------

def fetch_auctions(term: str) -> pd.DataFrame:
    """Fetch all auctions of a given originalSecurityTerm from TreasuryDirect.

    term examples: '10-Year', '30-Year'.
    """
    url = (
        "https://www.treasurydirect.gov/TA_WS/securities/search"
        f"?format=json&type=Note&dateFieldName=auctionDate"
        f"&startDate={START_DATE}&endDate={END_DATE}"
    )
    # Note: TreasuryDirect 'type' must match the security type. Bonds use type=Bond.
    sec_type = "Note" if term.endswith("Year") and int(term.split("-")[0]) <= 10 else "Bond"
    url = (
        "https://www.treasurydirect.gov/TA_WS/securities/search"
        f"?format=json&type={sec_type}&dateFieldName=auctionDate"
        f"&startDate={START_DATE}&endDate={END_DATE}"
    )
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    data = r.json()
    df = pd.DataFrame(data)
    if df.empty:
        return df
    df = df[df["originalSecurityTerm"] == term].copy()
    df["auctionDate"] = pd.to_datetime(df["auctionDate"]).dt.tz_localize(None).dt.normalize()
    df["bidToCoverRatio"] = pd.to_numeric(df["bidToCoverRatio"], errors="coerce")
    df = df.dropna(subset=["bidToCoverRatio"])
    df = df.sort_values("auctionDate").reset_index(drop=True)
    df["term"] = term
    return df[["auctionDate", "term", "bidToCoverRatio", "cusip"]]


def fetch_yf(symbol: str) -> pd.DataFrame:
    df = yf.download(symbol, start=START_DATE, end=END_DATE, progress=False, auto_adjust=False)
    if df.empty:
        raise RuntimeError(f"yfinance returned empty for {symbol}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df[["Close"]].rename(columns={"Close": symbol})


# ---------------------------------------------------------------------------
# Signal construction
# ---------------------------------------------------------------------------

def build_signal(auctions: pd.DataFrame) -> pd.DataFrame:
    """Compute trailing 12M z-score of bid-to-cover per auction.

    Per maturity bucket, baseline uses ONLY past auctions (strict <T),
    so the z-score at row i depends solely on rows j<i within window.
    """
    out = []
    for term, grp in auctions.groupby("term"):
        grp = grp.sort_values("auctionDate").reset_index(drop=True)
        zs = []
        for i, row in grp.iterrows():
            cutoff_lo = row["auctionDate"] - pd.Timedelta(days=ROLL_MONTHS * 30 + 5)
            past = grp.iloc[:i]
            past = past[past["auctionDate"] >= cutoff_lo]
            if len(past) < 6:
                zs.append(np.nan)
                continue
            mu = past["bidToCoverRatio"].mean()
            sd = past["bidToCoverRatio"].std(ddof=1)
            if not sd or sd == 0 or np.isnan(sd):
                zs.append(np.nan)
            else:
                zs.append((row["bidToCoverRatio"] - mu) / sd)
        grp["z"] = zs
        out.append(grp)
    res = pd.concat(out, ignore_index=True).sort_values("auctionDate").reset_index(drop=True)
    return res


def classify(z: float) -> str:
    if np.isnan(z):
        return "skip"
    if z < WEAK_Z:
        return "weak"
    if abs(z) < BENIGN_Z:
        return "benign"
    return "other"


# ---------------------------------------------------------------------------
# Event-window vol
# ---------------------------------------------------------------------------

def compute_cum_vol(prices: pd.Series, start_day: pd.Timestamp, n_days: int) -> float:
    """Cumulative realized vol = sqrt(sum log_ret^2) over the next n_days trading days
    starting from start_day inclusive.

    Returns NaN if window is incomplete.
    """
    idx = prices.index
    pos = idx.searchsorted(start_day)
    if pos >= len(idx):
        return np.nan
    window = prices.iloc[pos: pos + n_days + 1]  # need n_days+1 prices for n_days returns
    if len(window) < n_days + 1:
        return np.nan
    log_ret = np.log(window).diff().dropna()
    if len(log_ret) < n_days:
        return np.nan
    return float(np.sqrt(np.sum(log_ret.values ** 2)))


# ---------------------------------------------------------------------------
# Bootstrap + tests
# ---------------------------------------------------------------------------

def bootstrap_mean_diff(weak: np.ndarray, benign: np.ndarray, reps: int = BOOTSTRAP_REPS, seed: int = SEED):
    rng = np.random.default_rng(seed)
    diffs = np.empty(reps)
    nw, nb = len(weak), len(benign)
    for i in range(reps):
        wb = rng.choice(weak, size=nw, replace=True)
        bb = rng.choice(benign, size=nb, replace=True)
        diffs[i] = wb.mean() - bb.mean()
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return float(lo), float(hi), diffs


def cohens_d(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = len(a), len(b)
    va, vb = a.var(ddof=1), b.var(ddof=1)
    pooled = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    if pooled == 0:
        return float("nan")
    return float((a.mean() - b.mean()) / pooled)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    print(f"[{datetime.now().isoformat(timespec='seconds')}] K1506 starting", flush=True)

    # 1. Auctions
    auc10 = fetch_auctions("10-Year")
    time.sleep(1)
    auc30 = fetch_auctions("30-Year")
    print(f"  fetched 10Y={len(auc10)} 30Y={len(auc30)} auctions", flush=True)

    auctions = pd.concat([auc10, auc30], ignore_index=True).sort_values("auctionDate").reset_index(drop=True)
    auctions = build_signal(auctions)
    auctions["category"] = auctions["z"].apply(classify)

    # 2. Prices
    move = fetch_yf("^MOVE")
    vix = fetch_yf("^VIX")
    move_s = move["^MOVE"].dropna()
    vix_s = vix["^VIX"].dropna()
    print(f"  MOVE rows={len(move_s)} ({move_s.index.min().date()}..{move_s.index.max().date()})", flush=True)

    # 3. Event window vols. SIGNAL is observed at close of auctionDate T.
    # signal_lag=1: forward vol window starts at T+1 (next trading day after T).
    rows = []
    for _, ev in auctions.iterrows():
        T = ev["auctionDate"]
        # find next trading day on/after T+1
        next_idx = move_s.index.searchsorted(T + pd.Timedelta(days=1))
        if next_idx >= len(move_s):
            continue
        T_plus_1 = move_s.index[next_idx]
        post_vol = compute_cum_vol(move_s, T_plus_1, POST_DAYS)
        # pre window (descriptive only, not part of test): T-5..T-1
        prev_idx = move_s.index.searchsorted(T) - 1
        if prev_idx >= PRE_DAYS:
            pre_start = move_s.index[prev_idx - PRE_DAYS + 1]
            pre_vol = compute_cum_vol(move_s, pre_start, PRE_DAYS)
        else:
            pre_vol = np.nan
        # VIX regime at T (using close on or before T)
        vix_pos = vix_s.index.searchsorted(T, side="right") - 1
        vix_at_T = vix_s.iloc[vix_pos] if vix_pos >= 0 else np.nan
        rows.append({
            "auctionDate": T,
            "term": ev["term"],
            "bidToCoverRatio": ev["bidToCoverRatio"],
            "z": ev["z"],
            "category": ev["category"],
            "pre_cum_vol": pre_vol,
            "post_cum_vol": post_vol,
            "vix_at_T": vix_at_T,
        })
    df = pd.DataFrame(rows)
    df = df.dropna(subset=["post_cum_vol"]).reset_index(drop=True)
    df.to_csv(ROOT / "k1506_events.csv", index=False)
    print(f"  events with valid post window: {len(df)}", flush=True)
    print(df["category"].value_counts().to_dict(), flush=True)

    # 4. Stats
    results = {
        "experiment_id": "K1506",
        "k_id": "K1506",
        "title": "K1506: Treasury auction bid-to-cover weakness → MOVE realized vol event study",
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "seed": SEED,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "signal_lag": 1,
        "weak_z_threshold": WEAK_Z,
        "benign_z_threshold": BENIGN_Z,
        "post_window_days": POST_DAYS,
        "bootstrap_reps": BOOTSTRAP_REPS,
        "n_auctions_total": int(len(auctions)),
        "n_events_with_post_window": int(len(df)),
        "n_events_weak": int((df["category"] == "weak").sum()),
        "n_events_benign": int((df["category"] == "benign").sum()),
        "n_events_other": int((df["category"] == "other").sum()),
        "n_events_skip": int((df["category"] == "skip").sum()),
    }

    weak = df.loc[df["category"] == "weak", "post_cum_vol"].values
    benign = df.loc[df["category"] == "benign", "post_cum_vol"].values

    results["mean_post_cum_vol_weak"] = float(np.mean(weak)) if len(weak) else None
    results["mean_post_cum_vol_benign"] = float(np.mean(benign)) if len(benign) else None
    results["std_post_cum_vol_weak"] = float(np.std(weak, ddof=1)) if len(weak) > 1 else None
    results["std_post_cum_vol_benign"] = float(np.std(benign, ddof=1)) if len(benign) > 1 else None

    # Primary spec (preregistered): z < -1.5 weak vs |z| < 0.5 benign.
    if len(weak) >= 30 and len(benign) >= 30:
        t_stat, p_two = stats.ttest_ind(weak, benign, equal_var=False)
        p_one_sided = p_two / 2 if t_stat > 0 else 1 - p_two / 2
        d = cohens_d(weak, benign)
        ci_lo, ci_hi, _ = bootstrap_mean_diff(weak, benign)
        results.update({
            "t_stat": float(t_stat),
            "p_value_two_sided": float(p_two),
            "p_value_one_sided_weak_gt_benign": float(p_one_sided),
            "cohen_d": float(d),
            "bootstrap_95ci_mean_diff": [ci_lo, ci_hi],
        })
        if p_two < 0.05 and t_stat > 0 and abs(d) >= 0.3:
            verdict = "PASS"
        elif p_two < 0.10 and t_stat > 0:
            verdict = "CONDITIONAL_PASS"
        else:
            verdict = "FAIL"
        results["verdict_primary"] = verdict
    else:
        # Even if undersampled, still run the test for transparency but flag it.
        if len(weak) >= 8 and len(benign) >= 8:
            t_stat, p_two = stats.ttest_ind(weak, benign, equal_var=False)
            d = cohens_d(weak, benign)
            results["primary_descriptive_t"] = float(t_stat)
            results["primary_descriptive_p"] = float(p_two)
            results["primary_descriptive_cohen_d"] = float(d)
        results["verdict_primary"] = "INSUFFICIENT_SAMPLE"
        results["note_insufficient"] = (
            f"weak={len(weak)} benign={len(benign)}; primary requires >=30 each"
        )

    # Secondary spec (relaxed): z < -1.0 weak, larger N but weaker signal-to-noise.
    weak2 = df.loc[df["z"] < -1.0, "post_cum_vol"].values
    benign2 = benign  # same benign group
    sec = {
        "weak_z_threshold": -1.0,
        "n_weak": int(len(weak2)),
        "n_benign": int(len(benign2)),
        "mean_weak": float(np.mean(weak2)) if len(weak2) else None,
        "mean_benign": float(np.mean(benign2)) if len(benign2) else None,
    }
    if len(weak2) >= 30 and len(benign2) >= 30:
        t2, p2 = stats.ttest_ind(weak2, benign2, equal_var=False)
        d2 = cohens_d(weak2, benign2)
        ci_lo2, ci_hi2, _ = bootstrap_mean_diff(weak2, benign2, seed=SEED + 1)
        sec.update({
            "t_stat": float(t2),
            "p_value_two_sided": float(p2),
            "cohen_d": float(d2),
            "bootstrap_95ci_mean_diff": [ci_lo2, ci_hi2],
        })
        if p2 < 0.05 and t2 > 0 and abs(d2) >= 0.3:
            sec["verdict"] = "PASS"
        elif p2 < 0.10 and t2 > 0:
            sec["verdict"] = "CONDITIONAL_PASS"
        else:
            sec["verdict"] = "FAIL"
    else:
        sec["verdict"] = "INSUFFICIENT_SAMPLE"
    results["secondary_spec_z_lt_neg1"] = sec

    # Overall verdict = primary if defined; else FAIL/INSUFFICIENT default to honest label.
    if results["verdict_primary"] in {"PASS", "CONDITIONAL_PASS"}:
        results["verdict"] = results["verdict_primary"]
    elif results["verdict_primary"] == "FAIL":
        results["verdict"] = "FAIL"
    elif sec.get("verdict") in {"PASS", "CONDITIONAL_PASS"}:
        results["verdict"] = f"SECONDARY_{sec['verdict']}"
    else:
        results["verdict"] = results["verdict_primary"]  # INSUFFICIENT_SAMPLE

    # 5. Robustness: per maturity
    per_term = {}
    for term in ["10-Year", "30-Year"]:
        sub = df[df["term"] == term]
        w = sub.loc[sub["category"] == "weak", "post_cum_vol"].values
        b = sub.loc[sub["category"] == "benign", "post_cum_vol"].values
        rec = {
            "n_weak": int(len(w)),
            "n_benign": int(len(b)),
            "mean_weak": float(np.mean(w)) if len(w) else None,
            "mean_benign": float(np.mean(b)) if len(b) else None,
        }
        if len(w) >= 15 and len(b) >= 15:
            t, p = stats.ttest_ind(w, b, equal_var=False)
            rec["t"] = float(t)
            rec["p"] = float(p)
            rec["cohen_d"] = cohens_d(w, b)
        per_term[term] = rec
    results["robustness_per_maturity"] = per_term

    # 6. Robustness: VIX regime split (median of trailing 12M VIX at T)
    df["vix_med_12m"] = df["vix_at_T"].rolling(window=min(252, max(20, len(df) // 4)), min_periods=20).median()
    # Fallback: if too few rows, use full-sample median
    df["vix_med_12m"] = df["vix_med_12m"].fillna(df["vix_at_T"].median())
    df["vix_regime"] = np.where(df["vix_at_T"] > df["vix_med_12m"], "high", "low")
    per_vix = {}
    for regime in ["high", "low"]:
        sub = df[df["vix_regime"] == regime]
        w = sub.loc[sub["category"] == "weak", "post_cum_vol"].values
        b = sub.loc[sub["category"] == "benign", "post_cum_vol"].values
        rec = {
            "n_weak": int(len(w)),
            "n_benign": int(len(b)),
            "mean_weak": float(np.mean(w)) if len(w) else None,
            "mean_benign": float(np.mean(b)) if len(b) else None,
        }
        if len(w) >= 10 and len(b) >= 10:
            t, p = stats.ttest_ind(w, b, equal_var=False)
            rec["t"] = float(t)
            rec["p"] = float(p)
        per_vix[regime] = rec
    results["robustness_per_vix_regime"] = per_vix

    # 7. Figures
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 4))
    colors = {"10-Year": "tab:blue", "30-Year": "tab:orange"}
    for term, grp in auctions.dropna(subset=["z"]).groupby("term"):
        ax.plot(grp["auctionDate"], grp["z"], "o-", color=colors.get(term, "k"), alpha=0.55, label=term, markersize=3)
    weak_mask = auctions["z"] < WEAK_Z
    ax.scatter(auctions.loc[weak_mask, "auctionDate"], auctions.loc[weak_mask, "z"],
               color="red", s=40, zorder=5, label="weak (z<-1.5)")
    ax.axhline(WEAK_Z, color="red", linestyle="--", alpha=0.5)
    ax.axhline(0, color="grey", linestyle=":", alpha=0.5)
    ax.set_title("K1506: Treasury auction bid-to-cover z-score (rolling 12M baseline)")
    ax.set_ylabel("z-score")
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig1_btc_zscore_timeseries.png", dpi=120)
    plt.close(fig)

    # Event-time plot: average MOVE cumulative vol around event
    event_window = list(range(-PRE_DAYS, POST_DAYS + 1))
    series_weak = []
    series_benign = []
    for _, ev in df.iterrows():
        T = ev["auctionDate"]
        center = move_s.index.searchsorted(T)
        if center == 0 or center >= len(move_s):
            continue
        lo = center - PRE_DAYS
        hi = center + POST_DAYS + 1
        if lo < 0 or hi > len(move_s):
            continue
        win = move_s.iloc[lo:hi]
        if len(win) != PRE_DAYS + POST_DAYS + 1:
            continue
        rets = np.log(win).diff().fillna(0.0).values
        cum_rv = np.sqrt(np.cumsum(rets ** 2))
        if ev["category"] == "weak":
            series_weak.append(cum_rv)
        elif ev["category"] == "benign":
            series_benign.append(cum_rv)

    fig, ax = plt.subplots(figsize=(10, 4))
    if series_weak:
        arr_w = np.vstack(series_weak)
        ax.plot(event_window, arr_w.mean(axis=0), "r-o", label=f"weak (N={len(series_weak)})")
        ax.fill_between(event_window,
                        arr_w.mean(axis=0) - arr_w.std(axis=0) / math.sqrt(len(arr_w)),
                        arr_w.mean(axis=0) + arr_w.std(axis=0) / math.sqrt(len(arr_w)),
                        color="red", alpha=0.15)
    if series_benign:
        arr_b = np.vstack(series_benign)
        ax.plot(event_window, arr_b.mean(axis=0), "b-o", label=f"benign (N={len(series_benign)})")
        ax.fill_between(event_window,
                        arr_b.mean(axis=0) - arr_b.std(axis=0) / math.sqrt(len(arr_b)),
                        arr_b.mean(axis=0) + arr_b.std(axis=0) / math.sqrt(len(arr_b)),
                        color="blue", alpha=0.15)
    ax.axvline(0, color="grey", linestyle="--", label="auction day T")
    ax.set_xlabel("event time (trading days; 0 = auction day)")
    ax.set_ylabel("cumulative MOVE realized vol")
    ax.set_title("K1506: average MOVE cumulative realized vol around auction (weak vs benign)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig2_event_time_move_cum_vol.png", dpi=120)
    plt.close(fig)

    # 8. Persist
    results["reviewer"] = None  # filled after Codex review
    results["reviewer_source"] = None
    with open(ROOT / "k1506_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(json.dumps({k: v for k, v in results.items() if k != "robustness_per_vix_regime"}, indent=2, default=str))
    return results


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print(f"FATAL: {type(e).__name__}: {e}", file=sys.stderr)
        raise
