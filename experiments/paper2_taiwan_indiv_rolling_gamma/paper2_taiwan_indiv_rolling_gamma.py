"""
paper2_taiwan_indiv_rolling_gamma
=================================
Provenance re-estimation for Taiwan-VT Paper 2, Table `tab:gamma`
individual-stock rolling-window (w=2000) GJR-GARCH gamma rows.

MOTIVATION
----------
paper/taiwan-vt/reviews/audit_step1_2.md flagged that the three
individual-stock rows currently in body_v3.tex L152-154 ---
Hon Hai (2317) gamma=0.052/t=1.14, MediaTek (2454) gamma=0.044/t=0.96,
Mega Financial (2886) gamma=0.179/t=2.42 --- are UNTRACEABLE: they trace
only to knowledge entry N121 (derived from a since-deleted K530 run), with
no surviving source JSON. Research-honesty rule (Table row -> JSON source
must be traceable) requires a reproducible binding.

This script re-estimates those three rows under a documented, fully
reproducible specification (matching K892's arch-package MLE method used for
the other rolling-window rows in the same table) so the values can be bound
to a real results JSON. If the re-estimated values differ materially from
the legacy N121 numbers, the paper table must be updated to the traceable
values (do NOT keep untraceable numbers).

SPEC (identical to K892 estimate_gjr_garch)
-------------------------------------------
- GJR-GARCH(1,1), Constant mean, Normal innovations, via `arch` package MLE.
- Returns in percentage points (r*100) for numerical stability.
- gamma_t = arch package robust t-value (MLE robust SE; the table note calls
  these "Newey-West HAC" -- we report the arch robust t honestly and flag the
  wording discrepancy in the results JSON `note`).
- Rolling window w=2000; the reported row = the LAST (most recent) 2000-obs
  window, matching K892's `rolling_w2000.last_window` convention.
- Persistence = alpha + 0.5*gamma + beta (matches table note & K892).

DATA (all offline snapshots -- reproducible, no network)
--------------------------------------------------------
- 2317 (Hon Hai)  : paper/taiwan-vt/data/..._2008-2026.csv col `2317_tw_adj_close`
- 2454 (MediaTek) : same CSV col `2454_tw_adj_close`
- 2886 (Mega Fin) : experiments/k1302/data/2886_tw.csv col `adj_close`
  (the paper's individual-stock CSV does not include 2886; the k1302
  snapshot is the canonical yfinance adj-close source used for K1302's
  full-sample 2886 estimate.)

Sample window: 2008-01-01 .. 2026 (full available), matching the table note
"Individual stocks use the full available sample (2008-2026)".

No randomness (deterministic MLE); no seed needed. No lookahead: gamma is an
in-sample descriptive estimate on the last window, not a forecast/signal.
"""
import json
import os
from datetime import datetime, timezone

import arch
import numpy as np
import pandas as pd
from arch import arch_model

REPO = "/Users/yhlai0911/volpred-research"
PAPER_CSV = os.path.join(
    REPO,
    "paper/taiwan-vt/data/"
    "0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv",
)
K1302_DATA = os.path.join(REPO, "experiments/k1302/data")
K1302B_DATA = os.path.join(REPO, "experiments/k1302b/data")
OUT = os.path.join(
    REPO,
    "experiments/paper2_taiwan_indiv_rolling_gamma/"
    "paper2_taiwan_indiv_rolling_gamma_results.json",
)
WINDOW = 2000
SAMPLE_START = "2008-01-01"

# Legacy (untraceable) N121 values currently in body_v3.tex tab:gamma, for the
# three DISPLAYED individual-stock rows. The other 6 stocks contribute only to
# the 9-stock average (also legacy-untraceable at 0.054).
LEGACY = {
    "2317.TW": {"gamma": 0.052, "gamma_t": 1.14, "alpha": 0.028, "beta": 0.939, "persistence": 0.985},
    "2454.TW": {"gamma": 0.044, "gamma_t": 0.96, "alpha": 0.033, "beta": 0.935, "persistence": 0.984},
    "2886.TW": {"gamma": 0.179, "gamma_t": 2.42, "alpha": 0.015, "beta": 0.901, "persistence": 0.977},
}
LEGACY_ROLLING_9STOCK_AVG_GAMMA = 0.054  # body_v3.tex, untraceable

# Canonical 9-stock set (matches K1302 + K1302b full-sample average; excludes
# 2330 TSMC and 0056 ETF). name + offline snapshot source per stock.
NINE_STOCKS = {
    "2317.TW": ("Hon Hai", "paper_csv", "2317_tw_adj_close"),
    "2454.TW": ("MediaTek", "paper_csv", "2454_tw_adj_close"),
    "2383.TW": ("Elite Material", "k1302", "adj_close"),
    "2886.TW": ("Mega Financial", "k1302", "adj_close"),
    "2412.TW": ("Chunghwa Telecom", "k1302b", "Close"),
    "2881.TW": ("Fubon", "k1302b", "Close"),
    "2882.TW": ("Cathay Financial", "k1302b", "Close"),
    "2885.TW": ("Yuanta", "k1302b", "Close"),
    "2891.TW": ("CTBC", "k1302b", "Close"),
}
DISPLAYED = ["2317.TW", "2454.TW", "2886.TW"]  # rows shown in the paper table

# 0056 is a diversified ETF shown separately; excluded from the 9-stock average
# but included in the 10-security average. Data is in the paper CSV. Legacy
# rolling gamma = 0.112 (t=1.87), also untraceable.
ETF_0056 = ("0056.TW", "Yuanta High Div. ETF", "paper_csv", "0056_tw_adj_close")

# Index rows for the rolling ratio base. body_v3.tex currently carries an
# untraceable TWII rolling gamma = 0.272 (N120); the 0050 row was also
# untraceable. Both are now RECOMPUTED on the SAME calendar-aligned window
# (common_end below) so the amplification ratio has a fully reproducible base.
# 2026-07-09: calendar-aligned recompute gives TWII gamma=0.158 (t=2.57),
# 0050 gamma=0.079 (t=1.90) -- the legacy 0.272 does NOT reproduce.
INDEX_ROWS = {
    "TWII": ("Taiwan Weighted Index", "paper_csv", "twii_adj_close"),
    "0050.TW": ("Yuanta Taiwan 50 ETF", "paper_csv", "0050_tw_adj_close"),
}
TWII_ROLLING_GAMMA_LEGACY = 0.272  # body_v3.tex TWII rolling row; untraceable (N120),
# does NOT reproduce under calendar-aligned recompute; retained only for comparison.


def _load_prices(ticker: str, src: str, col: str) -> pd.Series:
    if src == "paper_csv":
        df = pd.read_csv(PAPER_CSV, parse_dates=["date"])
        s = df.set_index("date")[col]
    elif src == "k1302":
        df = pd.read_csv(os.path.join(K1302_DATA, f"{ticker[:4]}_tw.csv"), parse_dates=["date"])
        s = df.set_index("date")[col]
    elif src == "k1302b":
        df = pd.read_csv(os.path.join(K1302B_DATA, f"{ticker[:4]}_tw.csv"), parse_dates=["Date"])
        s = df.set_index("Date")[col]
    else:
        raise ValueError(src)
    s = s.dropna()
    s = s[s.index >= pd.Timestamp(SAMPLE_START)]
    return s.astype(float)


def log_returns(prices: pd.Series) -> pd.Series:
    r = np.log(prices / prices.shift(1)).dropna()
    return r


def estimate_gjr(returns: pd.Series) -> dict:
    """GJR-GARCH(1,1) MLE via arch, identical spec to K892."""
    ret_pct = returns * 100.0
    am = arch_model(ret_pct, vol="GARCH", p=1, o=1, q=1, dist="normal", mean="Constant")
    res = am.fit(disp="off", options={"maxiter": 5000})
    p, t = res.params, res.tvalues
    alpha = float(p.get("alpha[1]", np.nan))
    gamma = float(p.get("gamma[1]", np.nan))
    beta = float(p.get("beta[1]", np.nan))
    return {
        "omega": float(p.get("omega", np.nan)),
        "alpha": alpha,
        "gamma": gamma,
        "beta": beta,
        "gamma_t": float(t.get("gamma[1]", np.nan)),
        "alpha_t": float(t.get("alpha[1]", np.nan)),
        "beta_t": float(t.get("beta[1]", np.nan)),
        "persistence": alpha + 0.5 * gamma + beta,
        "n_obs": int(len(returns)),
        "convergence": int(res.convergence_flag),
        "log_likelihood": float(res.loglikelihood),
    }


def rolling_last_window(
    returns: pd.Series, window: int = WINDOW, end_cutoff: pd.Timestamp | None = None
) -> dict:
    """Last 2000-obs window ending on/before `end_cutoff` (calendar alignment).

    Codex CONDITIONAL_PASS caveat: the per-stock last-2000-obs windows must be
    calendar-aligned (share a common end date) before becoming the paper's
    canonical rolling numbers. `end_cutoff` truncates the return series to a
    common terminal date first, so every security's window ends on the same
    (or nearest prior) trading day.
    """
    if end_cutoff is not None:
        returns = returns[returns.index <= end_cutoff]
    if len(returns) < window:
        raise ValueError(f"only {len(returns)} obs < window {window}")
    last = returns.iloc[-window:]
    est = estimate_gjr(last)
    est["window"] = window
    est["window_start"] = str(last.index[0].date())
    est["window_end"] = str(last.index[-1].date())
    return est


def main() -> None:
    # --- Calendar alignment (Codex CONDITIONAL_PASS caveat) ---------------
    # Pre-load every return series, then derive the COMMON terminal date as the
    # earliest last-obs date across all 10 securities. This is the latest end
    # date achievable from the offline snapshots without any network re-fetch,
    # so the "fully reproducible, no network" guarantee is preserved. It is
    # bound by the k1302 snapshots for 2383/2886 (end 2025-01-22). Every
    # security's last-2000-obs window is then taken ending on/before this date.
    et_ticker, et_name, et_src, et_col = ETF_0056
    returns_cache: dict[str, pd.Series] = {}
    for ticker, (name, src, col) in NINE_STOCKS.items():
        returns_cache[ticker] = log_returns(_load_prices(ticker, src, col))
    returns_cache[et_ticker] = log_returns(
        _load_prices(et_ticker, et_src, et_col)
    )
    common_end = min(r.index[-1] for r in returns_cache.values())
    print(f"[calendar-align] COMMON_END = {common_end.date()} "
          f"(min last-obs across all 10 securities)")

    per_stock = {}
    for ticker, (name, src, col) in NINE_STOCKS.items():
        r = returns_cache[ticker]
        est = rolling_last_window(r, end_cutoff=common_end)
        est["name"] = name
        est["ticker"] = ticker
        est["price_source"] = f"{src}:{col}"
        if ticker in LEGACY:
            leg = LEGACY[ticker]
            est["legacy_n121"] = leg
            est["gamma_abs_diff_vs_legacy"] = abs(est["gamma"] - leg["gamma"])
            est["matches_legacy_rounded"] = (
                round(est["gamma"], 3) == round(leg["gamma"], 3)
                and round(est["gamma_t"], 2) == round(leg["gamma_t"], 2)
            )
        per_stock[ticker] = est
        legtxt = (
            f"| legacy g={LEGACY[ticker]['gamma']} t={LEGACY[ticker]['gamma_t']}"
            if ticker in LEGACY else "| (not displayed; avg-only)"
        )
        print(
            f"{ticker} {name:17s} gamma={est['gamma']:.4f} (t={est['gamma_t']:.2f})  "
            f"a={est['alpha']:.4f} b={est['beta']:.4f} pers={est['persistence']:.4f}  {legtxt}"
        )

    # 0056 ETF (separate row + included in 10-security avg); calendar-aligned
    et_est = rolling_last_window(returns_cache[et_ticker], end_cutoff=common_end)
    et_est["name"] = et_name
    et_est["ticker"] = et_ticker
    et_est["price_source"] = f"{et_src}:{et_col}"
    et_est["legacy_gamma"] = 0.112
    et_est["legacy_gamma_t"] = 1.87
    print(
        f"{et_ticker} {et_name:17s} gamma={et_est['gamma']:.4f} (t={et_est['gamma_t']:.2f})  "
        f"a={et_est['alpha']:.4f} b={et_est['beta']:.4f} pers={et_est['persistence']:.4f}  "
        f"| legacy g=0.112 t=1.87 (ETF)"
    )

    # --- Index rows (0050 / TWII) recomputed on the SAME calendar-aligned window
    # so the amplification ratio has a fully reproducible base (replaces the
    # untraceable body_v3.tex TWII 0.272 / 0050 rows). ------------------------
    index_rows = {}
    for idx_key, (idx_name, idx_src, idx_col) in INDEX_ROWS.items():
        idx_ret = log_returns(_load_prices(idx_key, idx_src, idx_col))
        iest = rolling_last_window(idx_ret, end_cutoff=common_end)
        iest["name"] = idx_name
        iest["ticker"] = idx_key
        iest["price_source"] = f"{idx_src}:{idx_col}"
        index_rows[idx_key] = iest
        print(
            f"[index] {idx_key} {idx_name:24s} gamma={iest['gamma']:.4f} (t={iest['gamma_t']:.2f})  "
            f"a={iest['alpha']:.4f} b={iest['beta']:.4f} pers={iest['persistence']:.4f}"
        )
    twii_gamma = float(index_rows["TWII"]["gamma"])  # reproducible base

    gammas = [per_stock[t]["gamma"] for t in NINE_STOCKS]
    g9 = float(np.mean(gammas))
    g10 = float(np.mean(gammas + [et_est["gamma"]]))
    # Ratio now uses the REPRODUCIBLE calendar-aligned TWII gamma, not the
    # untraceable legacy 0.272.
    ratio9 = twii_gamma / g9
    ratio10 = twii_gamma / g10
    avg = {
        "gamma_mean_9stock": g9,
        "alpha_mean_9stock": float(np.mean([per_stock[t]["alpha"] for t in NINE_STOCKS])),
        "beta_mean_9stock": float(np.mean([per_stock[t]["beta"] for t in NINE_STOCKS])),
        "gamma_mean_10security_incl_0056": g10,
        "n_stocks_9": len(gammas),
        "legacy_gamma_mean_9stock": LEGACY_ROLLING_9STOCK_AVG_GAMMA,
        "legacy_gamma_mean_10security": 0.060,
        "gamma_mean_9stock_abs_diff_vs_legacy": abs(g9 - LEGACY_ROLLING_9STOCK_AVG_GAMMA),
        "twii_rolling_gamma_reproducible": twii_gamma,
        "twii_rolling_gamma_legacy_untraceable": TWII_ROLLING_GAMMA_LEGACY,
        "twii_rolling_gamma_note": (
            "TWII rolling gamma RECOMPUTED on the calendar-aligned window "
            f"(gamma={twii_gamma:.4f}); the legacy body_v3.tex value 0.272 (N120) "
            "does NOT reproduce and is retained only for comparison."
        ),
        "ratio_base": "reproducible calendar-aligned TWII gamma",
        "amplification_ratio_9stock": ratio9,
        "amplification_ratio_10security": ratio10,
        "legacy_ratio_9stock": 5.0,
        "legacy_ratio_10security": 4.5,
    }
    result_etf = et_est
    print(
        f"\n9-stock rolling avg gamma={g9:.4f} (legacy 0.054)  ratio={ratio9:.1f}x (legacy 5.0x)\n"
        f"10-security rolling avg gamma={g10:.4f} (legacy 0.060)  ratio={ratio10:.1f}x (legacy 4.5x)"
    )

    displayed_match = all(per_stock[t].get("matches_legacy_rounded", False) for t in DISPLAYED)
    all_match = displayed_match
    result = {
        "experiment_id": "paper2_taiwan_indiv_rolling_gamma",
        "title": "Provenance re-estimation of Taiwan-VT individual-stock rolling-w2000 GJR gamma",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "purpose": (
            "Bind body_v3.tex tab:gamma individual-stock rows (Hon Hai/MediaTek/"
            "Mega) to a reproducible source JSON, replacing untraceable N121 values "
            "(audit_step1_2.md). Re-estimated under K892's arch-MLE GJR(1,1) "
            "rolling-w2000 last-window spec."
        ),
        "method": "GJR-GARCH(1,1) MLE (arch pkg), Constant mean, Normal innov, returns*100; rolling w=2000 last window; robust t-values; persistence=alpha+0.5*gamma+beta",
        "data_source": {
            t: f"{src}:{col}" for t, (nm, src, col) in NINE_STOCKS.items()
        },
        "data_source_note": (
            "2317/2454 from paper CSV adj_close; 2383/2886 from k1302 yfinance "
            "adj_close snapshots; 2412/2881/2882/2885/2891 from k1302b snapshots "
            "(Close col). Mixed adj/close is inherited from the canonical K1302/"
            "K1302b data package and documented for transparency."
        ),
        "sample_window_start": SAMPLE_START,
        "window": WINDOW,
        "arch_version": arch.__version__,
        "covariance_type": "arch default robust (White/Bollerslev-Wooldridge); gamma point estimates unaffected by SE choice",
        "codex_caveat_calendar_alignment": (
            "RESOLVED (2026-07-07): the Codex CONDITIONAL_PASS caveat required "
            "recomputing on calendar-aligned snapshots. All 10 securities' last-"
            "2000-obs windows are now truncated to a COMMON terminal date = "
            f"{str(common_end.date())}, the earliest last-obs across all offline "
            "snapshots (bound by the k1302 2383/2886 snapshots ending 2025-01-22). "
            "This is the latest common end date achievable offline with no network "
            "re-fetch, preserving the 'fully reproducible, no network' guarantee. "
            "See per_stock.window_end -- all rows now share this end date (or the "
            "nearest prior trading day per security). These are the paper's "
            "canonical calendar-aligned rolling numbers."
        ),
        "calendar_alignment_common_end": str(common_end.date()),
        "rolling_averages_and_ratio": avg,
        "index_rows": index_rows,
        "etf_0056": result_etf,
        "displayed_rows_match_legacy_rounded": all_match,
        "lookahead_free_certification": (
            "gamma is in-sample MLE on the last 2000-obs window; no forecast, no "
            "OOS split, no signal generation; deterministic MLE (no seed needed)."
        ),
        "provenance_note": (
            "The table note labels individual-stock t-stats 'Newey-West HAC'; the "
            "actual reproducible estimator (matching the rest of the rolling-window "
            "rows via K892) is the arch-package robust MLE t-value. Reported t-values "
            "here are arch robust t. If exact NW-HAC is required, re-run with an "
            "explicit HAC covariance and update the note accordingly."
        ),
        "per_stock": per_stock,
    }
    with open(OUT, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nall_match_legacy_rounded = {all_match}")
    print(f"written: {OUT}")


if __name__ == "__main__":
    main()
