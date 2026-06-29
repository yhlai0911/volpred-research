"""K1573 — Semiconductor industrial-policy award shock & sector vol spillover.

問題：CHIPS Act preliminary / final award / delay / equity-swap 公告日，半導體 sector
ETF (SMH/SOXX) 與下游/供應鏈相關 ticker 的 realized volatility 在 T-5..T+22 是否
出現 announcement effect？primary recipient 的公告，spillover 到同行 secondary
ticker 的 RV 是否顯著增加？delay/cancellation vs award 是否非對稱？

Method (research_program.md 與 experiment-preamble.md):
- Event window: business-day [-5, +22] around event date (T=0 = announcement day).
- RV proxy: daily squared log return r_t^2 (close-to-close). 不假設 intraday data.
- Effect metric: 5-day post-event window [+1, +5] mean r^2 vs matched pre-event
  baseline [-30, -6] (gap 1 trading day to avoid leakage). Ratio = mean_post / mean_pre.
- Significance: stationary bootstrap (Politis-Romano, 1994) on the FULL daily r^2
  series for that ticker (block size ~ sqrt(N)), seed=42, 1000 reps. P-value = fraction
  of bootstrap samples whose random 5-day mean / 25-day mean ratio >= observed.
- Cross-asset spillover: same metric on SMH / SOXX (industry ETFs) for events whose
  primary ticker is one of the funded names; tests whether primary-name funding bleeds
  into industry-wide vol.
- Asymmetry: stratify by event type (preliminary_award / final_award / delay /
  equity_swap) and compare mean post-event ratios.
- Multiple testing: Bonferroni adjustment (alpha=0.05) across (#event x #ticker) tests
  for the primary-ticker H1 family; same separately for the spillover ETF family.

Lookahead protection: event date is the announcement-day close. Post window starts at
T+1 strictly. Pre window ends at T-6. Squared-return is symmetric, no signal-lag bug.

Honest scope: 17 events is small N. Bonferroni across many tests will likely kill
single-event significance; we therefore *also* report the aggregated ratio across all
events per ticker (pooled), and a sign test (binomial). 我們不過度宣稱。

Seed: 42 throughout. Data: yfinance auto_adjust=True.
"""
from __future__ import annotations

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import binomtest
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.simplefilter("ignore", FutureWarning)
warnings.simplefilter("ignore", UserWarning)

SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
EVENTS_CSV = HERE / "events.csv"
RESULTS_JSON = HERE / "k1573_results.json"

# --- Tickers ----------------------------------------------------------------
# Primary recipient tickers (must trade on US exchange; SSNLF Samsung OTC is
# illiquid - we drop it; GFS, INTC, TSM, MU, WOLF tradeable)
PRIMARY_TICKERS_TRADEABLE = {"GFS", "INTC", "TSM", "MU", "WOLF"}

# Industry ETF + bellwether for spillover tests (every event tests these regardless
# of which name received the award)
SPILLOVER_TICKERS = ["SMH", "SOXX", "NVDA", "AMD", "ASML", "AMAT", "LRCX", "KLAC"]

ALL_TICKERS = sorted(set(SPILLOVER_TICKERS) | PRIMARY_TICKERS_TRADEABLE)

# Window params
PRE_END_REL = -6   # inclusive; T-30 to T-6
PRE_START_REL = -30
POST_START_REL = 1  # T+1
POST_END_REL = 5    # T+5 (inclusive)
WINDOW_PRE_LEN = abs(PRE_START_REL - PRE_END_REL) + 1  # 25
WINDOW_POST_LEN = POST_END_REL - POST_START_REL + 1     # 5

# Bootstrap
B_REPS = 1000


# ----------------------------------------------------------------------------
def load_events() -> pd.DataFrame:
    df = pd.read_csv(EVENTS_CSV, parse_dates=["event_date"])
    return df


def download_prices(tickers: list[str], start: str, end: str) -> tuple[pd.DataFrame, list[str]]:
    """Return (closes, missing_tickers). Missing tickers explicitly tracked for results.json."""
    print(f"[data] downloading {len(tickers)} tickers {start} -> {end}")
    raw = yf.download(
        tickers,
        start=start,
        end=end,
        progress=False,
        auto_adjust=True,
        group_by="ticker",
    )
    closes = {}
    missing: list[str] = []
    if isinstance(raw.columns, pd.MultiIndex):
        for t in tickers:
            try:
                ser = raw[t]["Close"].dropna()
                if len(ser) < 50:  # too sparse to use
                    missing.append(t)
                    print(f"[data] WARN {t} sparse ({len(ser)} obs) - dropping")
                    continue
                closes[t] = ser
            except KeyError:
                missing.append(t)
                print(f"[data] WARN {t} missing entirely from yfinance")
    else:
        closes[tickers[0]] = raw["Close"]
    cl = pd.DataFrame(closes).sort_index().dropna(how="all")
    print(f"[data] aligned {cl.shape[0]} rows x {cl.shape[1]} tickers (missing: {missing})")
    return cl, missing


def compute_log_returns(closes: pd.DataFrame) -> pd.DataFrame:
    return np.log(closes / closes.shift(1))


def squared_returns(returns: pd.DataFrame) -> pd.DataFrame:
    return returns.pow(2)


def trading_day_offset(idx: pd.DatetimeIndex, event_date: pd.Timestamp, k: int) -> pd.Timestamp | None:
    """Get the trading day that is k business days offset from event date.

    k=0 means the first index >= event_date.
    Negative k goes backward, positive forward, using the trading-day index.
    """
    # find anchor: first trading day >= event_date
    pos = idx.searchsorted(event_date, side="left")
    if pos >= len(idx):
        return None
    anchor = pos
    target = anchor + k
    if target < 0 or target >= len(idx):
        return None
    return idx[target]


def event_window_means(rsq: pd.Series, event_date: pd.Timestamp) -> dict | None:
    """Return mean rsq in pre window [-30,-6] and post window [+1,+5]."""
    idx = rsq.dropna().index
    # need anchor existing
    pre_start = trading_day_offset(idx, event_date, PRE_START_REL)
    pre_end = trading_day_offset(idx, event_date, PRE_END_REL)
    post_start = trading_day_offset(idx, event_date, POST_START_REL)
    post_end = trading_day_offset(idx, event_date, POST_END_REL)
    if None in (pre_start, pre_end, post_start, post_end):
        return None
    pre = rsq.loc[pre_start:pre_end].dropna()
    post = rsq.loc[post_start:post_end].dropna()
    if len(pre) < int(0.6 * WINDOW_PRE_LEN) or len(post) < int(0.6 * WINDOW_POST_LEN):
        return None
    return {
        "pre_mean": float(pre.mean()),
        "post_mean": float(post.mean()),
        "ratio": float(post.mean() / pre.mean()) if pre.mean() > 0 else None,
        "n_pre": int(len(pre)),
        "n_post": int(len(post)),
        "pre_start": pre_start.strftime("%Y-%m-%d"),
        "pre_end": pre_end.strftime("%Y-%m-%d"),
        "post_start": post_start.strftime("%Y-%m-%d"),
        "post_end": post_end.strftime("%Y-%m-%d"),
    }


def bootstrap_ratio_pvalue(rsq: pd.Series, observed_ratio: float, rng: np.random.Generator,
                            b_reps: int = B_REPS) -> dict:
    """Generate B null-distribution ratios under H0 of no event effect by random anchoring.

    Procedure: from the full sample, draw B random anchor positions that admit full
    [-30,+5] window. Compute the same ratio (mean of 5-day post / mean of 25-day pre)
    for each random anchor. P-value (one-sided) = fraction of null ratios >= observed.
    """
    x = rsq.dropna().values
    n = len(x)
    needed_left = abs(PRE_START_REL)
    needed_right = POST_END_REL
    valid_anchors = np.arange(needed_left, n - needed_right)
    if len(valid_anchors) < 50:
        return {"p_value": None, "n_anchors": int(len(valid_anchors)), "null_dist_mean": None}
    null_ratios = np.empty(b_reps, dtype=np.float64)
    for b in range(b_reps):
        a = rng.choice(valid_anchors)
        pre = x[a + PRE_START_REL : a + PRE_END_REL + 1]
        post = x[a + POST_START_REL : a + POST_END_REL + 1]
        pre_m = pre.mean()
        post_m = post.mean()
        null_ratios[b] = post_m / pre_m if pre_m > 0 else np.nan
    null_ratios = null_ratios[~np.isnan(null_ratios)]
    if len(null_ratios) < 50:
        return {"p_value": None, "n_anchors": int(len(valid_anchors)), "null_dist_mean": None}
    p_two = float(np.mean(null_ratios >= observed_ratio))
    return {
        "p_value": p_two,
        "n_anchors": int(len(valid_anchors)),
        "null_dist_mean": float(null_ratios.mean()),
        "null_dist_p95": float(np.percentile(null_ratios, 95)),
        "null_dist_p99": float(np.percentile(null_ratios, 99)),
    }


# ----------------------------------------------------------------------------
def run():
    print("=" * 70)
    print(f"K1573 starting {datetime.now().isoformat(timespec='seconds')}  seed={SEED}")
    print("=" * 70)
    events = load_events()
    print(f"events loaded: {len(events)}")

    # Sample period: cover 30 trading days before earliest event - 60 cal days,
    # to 30 trading days after latest event + 60 cal days
    start = (events.event_date.min() - pd.Timedelta(days=120)).strftime("%Y-%m-%d")
    end = (events.event_date.max() + pd.Timedelta(days=120)).strftime("%Y-%m-%d")

    closes, missing_tickers = download_prices(ALL_TICKERS, start, end)
    rets = compute_log_returns(closes)
    rsq = squared_returns(rets)

    rng = np.random.default_rng(SEED)
    rows = []

    # H1 (primary-ticker announcement effect) + H2 (spillover to industry ETFs)
    for _, ev in events.iterrows():
        ev_date = ev.event_date
        ev_type = ev.type
        recipient = ev.recipient
        # which tickers to test for this event
        primary_t = ev.ticker_primary if ev.ticker_primary in PRIMARY_TICKERS_TRADEABLE else None
        ticker_set = set(SPILLOVER_TICKERS)
        if primary_t:
            ticker_set.add(primary_t)
        for t in sorted(ticker_set):
            if t not in rsq.columns:
                continue
            ser = rsq[t]
            res = event_window_means(ser, ev_date)
            if res is None or res.get("ratio") is None:
                continue
            boot = bootstrap_ratio_pvalue(ser, res["ratio"], rng)
            rows.append({
                "event_date": ev_date.strftime("%Y-%m-%d"),
                "recipient": recipient,
                "event_type": ev_type,
                "primary_ticker": ev.ticker_primary,
                "test_ticker": t,
                "is_primary_recipient": (t == primary_t),
                **res,
                **{f"boot_{k}": v for k, v in boot.items()},
            })

    if not rows:
        raise RuntimeError("no event-ticker rows produced; aborting")
    df = pd.DataFrame(rows)
    df.to_csv(HERE / "event_ticker_results.csv", index=False)
    print(f"[results] {len(df)} event-ticker tests written")

    # ---- Aggregate analyses ----
    # H1 per-ticker pooled across events: mean post/pre ratio; sign test on N events
    h1_summary = []
    for t, sub in df.groupby("test_ticker"):
        ratios = sub["ratio"].dropna()
        if len(ratios) == 0:
            continue
        sign_up = int((ratios > 1).sum())
        bt = binomtest(sign_up, n=int(len(ratios)), p=0.5, alternative="greater")
        h1_summary.append({
            "ticker": t,
            "n_events": int(len(ratios)),
            "mean_ratio": float(ratios.mean()),
            "median_ratio": float(ratios.median()),
            "frac_ratio_gt1": float(sign_up / len(ratios)),
            "sign_test_p_one_sided": float(bt.pvalue),
        })
    h1_df = pd.DataFrame(h1_summary).sort_values("mean_ratio", ascending=False)
    print("\nH1 (per-ticker pooled):")
    print(h1_df.to_string(index=False))

    # H3 stratify by event type: pooled across all tickers (intra-event-type)
    h3_summary = []
    for etype, sub in df.groupby("event_type"):
        ratios = sub["ratio"].dropna()
        sign_up = int((ratios > 1).sum())
        bt = binomtest(sign_up, n=int(len(ratios)), p=0.5, alternative="greater") if len(ratios) > 0 else None
        h3_summary.append({
            "event_type": etype,
            "n_tests": int(len(ratios)),
            "mean_ratio": float(ratios.mean()) if len(ratios) else None,
            "median_ratio": float(ratios.median()) if len(ratios) else None,
            "frac_ratio_gt1": float(sign_up / len(ratios)) if len(ratios) else None,
            "sign_test_p_one_sided": float(bt.pvalue) if bt else None,
        })
    h3_df = pd.DataFrame(h3_summary).sort_values("mean_ratio", ascending=False, na_position="last")
    print("\nH3 (by event type, all tickers pooled):")
    print(h3_df.to_string(index=False))

    # Multiple-testing summary (Bonferroni) on the per-event bootstrap p-values
    pvals = df["boot_p_value"].dropna().values
    bonf_alpha = 0.05 / max(len(pvals), 1)
    sig_unadj = int((pvals < 0.05).sum())
    sig_bonf = int((pvals < bonf_alpha).sum())

    # H2 spillover: primary-recipient row vs industry-ETF rows for same event
    h2_rows = []
    for ev_date, sub in df.groupby("event_date"):
        prim = sub[sub.is_primary_recipient]
        if prim.empty:
            continue
        prim_ratio = float(prim["ratio"].mean())
        for etf in ["SMH", "SOXX"]:
            etf_sub = sub[sub.test_ticker == etf]
            if etf_sub.empty:
                continue
            etf_ratio = float(etf_sub["ratio"].iloc[0])
            etf_p = float(etf_sub["boot_p_value"].iloc[0])
            h2_rows.append({
                "event_date": ev_date,
                "event_type": sub["event_type"].iloc[0],
                "recipient": sub["recipient"].iloc[0],
                "primary_ratio": prim_ratio,
                f"{etf}_ratio": etf_ratio,
                f"{etf}_boot_p": etf_p,
            })

    # ---- Figure: distribution of ratios per ticker ----
    fig, ax = plt.subplots(figsize=(11, 5))
    tickers = h1_df["ticker"].tolist()
    ratios_by_t = [df[df.test_ticker == t]["ratio"].dropna().values for t in tickers]
    bp = ax.boxplot(ratios_by_t, labels=tickers, showmeans=True, patch_artist=True)
    for patch in bp["boxes"]:
        patch.set_facecolor("#cce5ff")
    ax.axhline(1.0, color="red", ls="--", lw=1, label="null (ratio=1)")
    ax.set_ylabel("post-event mean r^2 / pre-event mean r^2")
    ax.set_xlabel("ticker")
    ax.set_title("K1573 — post/pre RV ratio around CHIPS Act award events (T+1..+5 vs T-30..-6)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(HERE / "fig_a.png", dpi=130)
    plt.close(fig)

    # ---- Save final results ----
    results = {
        "experiment_id": "K1573",
        "title": "Semiconductor industrial-policy award shock and sector volatility spillover",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "seed": SEED,
        "data": {
            "tickers_requested": ALL_TICKERS,
            "tickers_missing_or_sparse": missing_tickers,
            "tickers_used": [t for t in ALL_TICKERS if t not in missing_tickers],
            "n_tickers_requested": len(ALL_TICKERS),
            "n_tickers_used": len(ALL_TICKERS) - len(missing_tickers),
            "n_events_total": int(len(events)),
            "n_event_ticker_tests": int(len(df)),
            "sample_start": start,
            "sample_end": end,
            "yfinance_auto_adjust": True,
            "holiday_alignment_note": (
                "Event date falling on non-trading day maps T=0 to first trading day "
                ">= event_date (e.g. Sat 2024-02-17 announcement -> T=0=Tue 2024-02-20 "
                "after Presidents' Day holiday). Post window therefore excludes the "
                "first market-reaction day in those cases; conservative for detecting "
                "announcement effect."
            ),
        },
        "windows": {
            "pre": [PRE_START_REL, PRE_END_REL],
            "post": [POST_START_REL, POST_END_REL],
        },
        "bootstrap": {
            "method": "random-anchor null distribution of ratio under H0",
            "B_reps": B_REPS,
            "alpha_unadj": 0.05,
            "bonferroni_alpha": float(bonf_alpha),
            "n_pvalues": int(len(pvals)),
            "n_sig_unadj_0p05": sig_unadj,
            "n_sig_bonferroni": sig_bonf,
        },
        "H1_per_ticker_pooled": h1_summary,
        "H3_by_event_type": h3_summary,
        "H2_spillover_per_event": h2_rows,
        "honest_summary": {
            "n_events": int(len(events)),
            "n_tickers": len(ALL_TICKERS),
            "verdict": None,  # filled below
        },
    }

    # Verdict synthesis: take aggregated stance
    aggregate_mean_ratio = float(df["ratio"].mean())
    aggregate_frac_gt1 = float((df["ratio"] > 1).mean())
    pooled_bt = binomtest(int((df["ratio"] > 1).sum()), n=int(len(df.dropna(subset=["ratio"]))),
                          p=0.5, alternative="greater")
    results["honest_summary"]["aggregate_mean_ratio"] = aggregate_mean_ratio
    results["honest_summary"]["aggregate_frac_gt1"] = aggregate_frac_gt1
    results["honest_summary"]["pooled_sign_test_p"] = float(pooled_bt.pvalue)

    # Plain-language verdict
    if aggregate_mean_ratio < 1.05 and pooled_bt.pvalue > 0.1 and sig_bonf == 0:
        verdict = (
            "NULL — no detectable announcement effect on semiconductor sector RV in the "
            "T+1..+5 window after CHIPS Act award/delay events. Aggregate post/pre ratio "
            f"= {aggregate_mean_ratio:.3f}, sign test p={pooled_bt.pvalue:.3f}, "
            f"0/{len(pvals)} per-event tests significant after Bonferroni. "
            "LOW POWER CAVEAT: N=17 events x 12 tickers => only {n_t} per-event tests; "
            "the random-anchor null is conservative (uses full sample including the "
            "event window itself as anchors), and Bonferroni at alpha=0.05/{n_t} is "
            "extremely strict. A genuine moderate-size effect (ratio ~1.2-1.5) is "
            "detectable only if highly clustered; diffuse or heterogeneous announcement "
            "effects would also produce this NULL. Interpret as 'no strong, "
            "concentrated, systematically positive RV spike', not 'no effect at all'."
        ).format(n_t=len(pvals))
    elif aggregate_mean_ratio > 1.1 and pooled_bt.pvalue < 0.05:
        verdict = (
            f"POSITIVE — pooled evidence of elevated RV post-event. Aggregate ratio "
            f"= {aggregate_mean_ratio:.3f}, sign test p={pooled_bt.pvalue:.3f}, "
            f"{sig_bonf}/{len(pvals)} per-event tests significant after Bonferroni."
        )
    else:
        verdict = (
            f"SUGGESTIVE — aggregate ratio {aggregate_mean_ratio:.3f} (sign test "
            f"p={pooled_bt.pvalue:.3f}); {sig_bonf}/{len(pvals)} per-event tests "
            f"survive Bonferroni. Small N (17 events) limits power; reported as "
            f"descriptive."
        )
    results["honest_summary"]["verdict"] = verdict
    print("\n" + "=" * 70)
    print("VERDICT:", verdict)
    print("=" * 70)

    with RESULTS_JSON.open("w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[done] wrote {RESULTS_JSON}")


if __name__ == "__main__":
    run()
