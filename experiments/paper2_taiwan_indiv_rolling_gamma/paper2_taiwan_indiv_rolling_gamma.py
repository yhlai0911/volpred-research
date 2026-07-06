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
TWII_ROLLING_GAMMA_TABLE = 0.272  # body_v3.tex TWII rolling row; untraceable (N120),
# provenance tracked separately; used here only to recompute the rolling ratio.


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


def rolling_last_window(returns: pd.Series, window: int = WINDOW) -> dict:
    if len(returns) < window:
        raise ValueError(f"only {len(returns)} obs < window {window}")
    last = returns.iloc[-window:]
    est = estimate_gjr(last)
    est["window"] = window
    est["window_start"] = str(last.index[0].date())
    est["window_end"] = str(last.index[-1].date())
    return est


def main() -> None:
    per_stock = {}
    for ticker, (name, src, col) in NINE_STOCKS.items():
        prices = _load_prices(ticker, src, col)
        r = log_returns(prices)
        est = rolling_last_window(r)
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

    # 0056 ETF (separate row + included in 10-security avg)
    et_ticker, et_name, et_src, et_col = ETF_0056
    et_est = rolling_last_window(log_returns(_load_prices(et_ticker, et_src, et_col)))
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

    gammas = [per_stock[t]["gamma"] for t in NINE_STOCKS]
    g9 = float(np.mean(gammas))
    g10 = float(np.mean(gammas + [et_est["gamma"]]))
    ratio9 = TWII_ROLLING_GAMMA_TABLE / g9
    ratio10 = TWII_ROLLING_GAMMA_TABLE / g10
    avg = {
        "gamma_mean_9stock": g9,
        "alpha_mean_9stock": float(np.mean([per_stock[t]["alpha"] for t in NINE_STOCKS])),
        "beta_mean_9stock": float(np.mean([per_stock[t]["beta"] for t in NINE_STOCKS])),
        "gamma_mean_10security_incl_0056": g10,
        "n_stocks_9": len(gammas),
        "legacy_gamma_mean_9stock": LEGACY_ROLLING_9STOCK_AVG_GAMMA,
        "legacy_gamma_mean_10security": 0.060,
        "gamma_mean_9stock_abs_diff_vs_legacy": abs(g9 - LEGACY_ROLLING_9STOCK_AVG_GAMMA),
        "twii_rolling_gamma_used": TWII_ROLLING_GAMMA_TABLE,
        "twii_rolling_gamma_note": "from body_v3.tex TWII row (untraceable N120); provenance tracked separately",
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
            "CONDITIONAL_PASS (Codex): the per-stock last-2000-obs windows are NOT "
            "calendar-aligned -- 2317/2454 end 2026-04-17, 2886 (k1302 snapshot) ends "
            "2025-01-22, k1302b stocks end 2026-05-15. See per_stock.window_end. The "
            "'legacy non-reproducible' conclusion is robust, but these reproducible "
            "values must be recomputed on calendar-aligned snapshots before becoming "
            "the paper's canonical rolling numbers."
        ),
        "rolling_averages_and_ratio": avg,
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
