"""
K1605 — Bank market-to-book / Tobin's Q divergence as a delayed-loss prior
for regional-bank realized volatility (RV).

Phase-1: data diagnostic + descriptive + first-look lead-lag.
Heavy formal estimation (panel HAC, DM, bootstrap, OOS refit) is deferred to
k1605_formal.py via the compute queue.

Hypothesis
----------
Regional banks' market-to-book (M/B) gap — market cap trading at a discount to
book equity (M/B < 1 or falling M/B) — reflects the market pricing in HTM/AFS
unrealized losses and credit deterioration that are NOT yet on the balance
sheet (the "delayed-loss channel"). A widening market-to-book DIVERGENCE (M/B
falling) is hypothesized to LEAD a rise in realized volatility of the stock and
of KRE/KBE.

Direction: LOW / FALLING M/B(t-1)  ->  HIGH forward RV(t+H).  Expect a NEGATIVE
sign on log(M/B) in predicting forward RV.

Lookahead protection (HEAD RISK #1)
-----------------------------------
Quarter-/year-end book equity is NOT public on the period-end date. 10-Q is due
~40 days after quarter end and 10-K ~60 days after fiscal-year end for large
accelerated filers. We align each book-equity figure to a CONSERVATIVE
filing-available date:
    quarterly figure -> quarter_end  + 45 calendar days
    annual figure    -> fiscal_year_end + 75 calendar days
On any trading day t we use only the most recent book equity whose
filing-available date <= t. All signals are additionally shift(1) so the signal
at date t uses information through t-1 only. Forward RV targets use returns
strictly in (t, t+H]. This guarantees signal timing precedes the target window.

Methodology guards
------------------
- Cross-asset pooled inference is NOT treated as iid asset-days (K1355). The
  primary cross-sectional test is Fama-MacBeth: run a cross-sectional
  regression EACH day, collect the slope b(t), then HAC (Newey-West, lag>=H) the
  time series of slopes. This aggregates by date before doing inference.
- Overlapping forward-RV windows induce MA(H-1) serial correlation; all
  time-series inference uses Newey-West with lag >= H.
- Price confound: daily M/B moves mostly via price, which is mechanically linked
  to RV (volatility clustering + persistence). Every predictive test therefore
  ALSO controls for trailing own-RV, so the reported M/B effect is INCREMENTAL
  to the standard volatility-persistence baseline.
- Survivorship bias: SVB / SBNY / FRC (2023 failures) are gone from the sample,
  biasing the cross-section toward the survivors and likely toward NULL. Flagged.
- Seeds fixed for any stochastic step.

Author: VolPred autonomous research system. Free data only (yfinance).
"""
from __future__ import annotations

import json
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

import yfinance as yf  # noqa: E402
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SEED = 20260702
np.random.seed(SEED)

HERE = __file__.rsplit("/", 1)[0]

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
# Representative currently-listed regional / mid-cap banks (KRE/KBE-style).
# NOTE ON SURVIVORSHIP: the 2023 failures (SIVB/SVB, SBNY, FRC) and merged names
# (e.g. PBCT into MTB, 2022) are intentionally NOT in this list because their
# fundamentals are no longer retrievable. This is a real survivorship bias that
# biases the sample toward survivors -> likely toward NULL. Documented in README.
BANKS = [
    "RF", "KEY", "CFG", "HBAN", "FITB", "MTB", "ZION", "CMA", "WAL", "PNC",
    "USB", "TFC", "FHN", "SNV", "CFR", "WBS", "VLY", "ONB", "CBSH", "BOKF",
    "EWBC", "WTFC", "UMBF", "FNB", "ASB", "BKU", "HWC", "PB", "RJF",
]
BANKS = sorted(set(BANKS))
ETFS = ["KRE", "KBE"]

END_DATE = datetime.now(timezone.utc).date().isoformat()
START_PRICE = "2020-01-01"       # daily prices back to here (RV history)
START_ANALYSIS = "2022-01-01"    # M/B analysis window (needs lag-safe book eq)

RV_TRAIL_WIN = 22                # trailing RV window (HAR-style control), days
HORIZONS = [5, 22]              # forward RV horizons
Q_LAG_DAYS = 45                  # 10-Q filing lag (conservative)
A_LAG_DAYS = 75                  # 10-K filing lag (conservative)
ANN = 252

# SVB / regional-bank stress window (for descriptive case study)
STRESS_START = "2023-03-01"
STRESS_END = "2023-05-31"


# ----------------------------------------------------------------------------
# Data fetch helpers
# ----------------------------------------------------------------------------
def fetch_prices(tickers):
    """Adjusted close daily prices; returns wide DataFrame."""
    px = {}
    fails = []
    for t in tickers:
        try:
            h = yf.Ticker(t).history(start=START_PRICE, end=None, auto_adjust=True)
            if h is None or len(h) < 250:
                fails.append((t, f"short n={0 if h is None else len(h)}"))
                continue
            s = h["Close"].copy()
            s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
            px[t] = s
        except Exception as e:  # noqa: BLE001
            fails.append((t, str(e)[:60]))
    return pd.DataFrame(px).sort_index(), fails


def _pick_equity_row(frame):
    for cand in ("Common Stock Equity", "Stockholders Equity",
                 "Total Equity Gross Minority Interest"):
        if cand in frame.index:
            return cand
    return None


def fetch_book_equity(tickers):
    """Build a lag-safe, filing-available book-equity STEP series per ticker.

    Combines annual (2021+) and quarterly (recent) Common Stock Equity. Each
    figure is stamped with a conservative filing-available date. Returns:
      book -> DataFrame indexed by AVAILABLE date, columns=tickers,
              value = book equity (USD) usable from that date onward.
      meta -> per-ticker diagnostic dict.
    """
    records = {}
    meta = {}
    for t in tickers:
        tk = yf.Ticker(t)
        pts = []  # (available_date, book_equity, source, period_end)
        # Annual
        try:
            bs = tk.balance_sheet
            row = _pick_equity_row(bs) if bs is not None and not bs.empty else None
            if row is not None:
                for col in bs.columns:
                    val = bs.loc[row, col]
                    if pd.notna(val):
                        fye = pd.Timestamp(col).normalize()
                        avail = fye + pd.Timedelta(days=A_LAG_DAYS)
                        pts.append((avail, float(val), "annual", fye))
        except Exception:  # noqa: BLE001
            pass
        # Quarterly (overrides annual where dates overlap; finer + fresher)
        try:
            qbs = tk.quarterly_balance_sheet
            row = _pick_equity_row(qbs) if qbs is not None and not qbs.empty else None
            if row is not None:
                for col in qbs.columns:
                    val = qbs.loc[row, col]
                    if pd.notna(val):
                        qe = pd.Timestamp(col).normalize()
                        avail = qe + pd.Timedelta(days=Q_LAG_DAYS)
                        pts.append((avail, float(val), "quarterly", qe))
        except Exception:  # noqa: BLE001
            pass
        if not pts:
            meta[t] = {"n_points": 0, "usable": False}
            continue
        df = pd.DataFrame(pts, columns=["avail", "book", "source", "period_end"])
        # If both annual & quarterly stamp the same period_end, keep quarterly.
        df = df.sort_values(["period_end", "source"])  # 'annual' < 'quarterly'
        df = df.drop_duplicates("period_end", keep="last")
        df = df.sort_values("avail").drop_duplicates("avail", keep="last")
        records[t] = df.set_index("avail")["book"]
        meta[t] = {
            "n_points": int(len(df)),
            "earliest_avail": df["avail"].min().date().isoformat(),
            "latest_avail": df["avail"].max().date().isoformat(),
            "earliest_period_end": df["period_end"].min().date().isoformat(),
            "usable": True,
        }
    book = pd.DataFrame(records).sort_index()
    return book, meta


def fetch_shares(tickers):
    """Lag-safe shares-outstanding STEP series (as-of filing timestamps)."""
    out = {}
    meta = {}
    for t in tickers:
        try:
            sh = yf.Ticker(t).get_shares_full(start="2018-01-01")
            if sh is None or len(sh) == 0:
                meta[t] = 0
                continue
            sh.index = pd.to_datetime(sh.index).tz_localize(None).normalize()
            sh = sh[~sh.index.duplicated(keep="last")].sort_index()
            out[t] = sh.astype(float)
            meta[t] = int(len(sh))
        except Exception:  # noqa: BLE001
            meta[t] = 0
    return out, meta


# ----------------------------------------------------------------------------
# Signal construction (lag-safe M/B)
# ----------------------------------------------------------------------------
def build_market_to_book(prices, book, shares, calendar):
    """Daily lag-safe log(M/B) per bank on the trading calendar.

    market_cap(t) = price(t) * shares_avail(t)       (step, as-of date)
    book_avail(t) = most recent filing-available book equity with avail <= t
    M/B(t) = market_cap(t) / book_avail(t)
    """
    logmb = {}
    for t in book.columns:
        if t not in prices.columns or t not in shares:
            continue
        px = prices[t].reindex(calendar).ffill()
        sh = shares[t].reindex(calendar).ffill()          # step, lag-safe
        be = book[t].reindex(calendar).ffill()            # step, filing-avail
        mcap = px * sh
        mb = mcap / be
        mb = mb.where(mb > 0)
        logmb[t] = np.log(mb)
    return pd.DataFrame(logmb)


# ----------------------------------------------------------------------------
# RV construction
# ----------------------------------------------------------------------------
def daily_log_returns(prices):
    return np.log(prices).diff()


def trailing_rv(rets, win=RV_TRAIL_WIN):
    """Annualized trailing realized vol over [t-win+1, t] (info known at t)."""
    return np.sqrt(ANN * (rets ** 2).rolling(win).mean())


def forward_rv(rets, h):
    """Annualized realized vol over (t, t+h]; strictly future returns.

    Implemented as a backward rolling sum of r^2 then shifted so the value at
    index t summarizes returns dated t+1..t+h.
    """
    r2 = rets ** 2
    fwd = r2.rolling(h).sum().shift(-h)  # value at t = sum r2 over t+1..t+h
    return np.sqrt(ANN / h * fwd)


def forward_downside_semivol(rets, h):
    neg2 = np.minimum(rets, 0.0) ** 2
    fwd = neg2.rolling(h).sum().shift(-h)
    return np.sqrt(ANN / h * fwd)


# ----------------------------------------------------------------------------
# Inference helpers
# ----------------------------------------------------------------------------
def newey_west_ols(y, X, lags):
    """OLS with Newey-West HAC SE. X has no intercept column; one is added.

    Returns dict of params, hac_se, t, and n.
    """
    y = np.asarray(y, float)
    X = np.asarray(X, float)
    if X.ndim == 1:
        X = X[:, None]
    n = len(y)
    Xd = np.column_stack([np.ones(n), X]) if X.size else np.ones((n, 1))
    k = Xd.shape[1]
    beta, *_ = np.linalg.lstsq(Xd, y, rcond=None)
    resid = y - Xd @ beta
    XtX_inv = np.linalg.pinv(Xd.T @ Xd)
    S = np.zeros((k, k))
    u = Xd * resid[:, None]
    S += u.T @ u
    for L in range(1, lags + 1):
        w = 1.0 - L / (lags + 1.0)
        G = u[L:].T @ u[:-L]
        S += w * (G + G.T)
    cov = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.diag(cov))
    with np.errstate(divide="ignore", invalid="ignore"):
        tvals = beta / se
    return {"beta": beta.tolist(), "se": se.tolist(), "t": tvals.tolist(),
            "n": int(n), "k": int(k)}


def fama_macbeth(panel_signal, panel_lagrv, panel_fwdrv, h, min_xs=6):
    """Fama-MacBeth cross-sectional regression, K1355-compliant.

    Each date t: regress fwdRV_i(t) on [signal_i(t), lagRV_i(t)] across banks i.
    Collect slope on signal. Then HAC (lag>=h) the time series of slopes.
    Runs two specs: (A) signal only, (B) signal + lagRV control.
    """
    dates = panel_signal.index
    slopes_A, slopes_B, ns = [], [], []
    for d in dates:
        sig = panel_signal.loc[d]
        y = panel_fwdrv.loc[d]
        lrv = panel_lagrv.loc[d]
        m = sig.notna() & y.notna() & lrv.notna()
        if int(m.sum()) < min_xs:
            continue
        s = sig[m].values
        yy = y[m].values
        lv = lrv[m].values
        XA = np.column_stack([np.ones(len(s)), s])
        bA, *_ = np.linalg.lstsq(XA, yy, rcond=None)
        XB = np.column_stack([np.ones(len(s)), s, lv])
        bB, *_ = np.linalg.lstsq(XB, yy, rcond=None)
        slopes_A.append(bA[1])
        slopes_B.append(bB[1])
        ns.append(int(m.sum()))
    slopes_A = np.array(slopes_A)
    slopes_B = np.array(slopes_B)

    def hac_mean(x):
        if len(x) < (h + 5):
            return None
        res = newey_west_ols(x, np.zeros((len(x), 0)), lags=h)
        return {"mean": float(res["beta"][0]), "hac_se": float(res["se"][0]),
                "t": float(res["t"][0]), "n_days": int(res["n"])}

    return {
        "spec_A_signal_only": hac_mean(slopes_A),
        "spec_B_control_lagRV": hac_mean(slopes_B),
        "n_days_used": int(len(slopes_A)),
        "avg_xs_n": float(np.mean(ns)) if ns else None,
        "median_slope_A": float(np.median(slopes_A)) if len(slopes_A) else None,
        "median_slope_B": float(np.median(slopes_B)) if len(slopes_B) else None,
    }


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    asof = datetime.now(timezone.utc).isoformat()
    print(f"[K1605] as-of {asof}")

    all_tickers = ETFS + BANKS
    prices, price_fails = fetch_prices(all_tickers)
    print(f"[prices] n_cols={prices.shape[1]}  n_dates={len(prices)}  fails={price_fails}")

    book, book_meta = fetch_book_equity(BANKS)
    shares, share_meta = fetch_shares(BANKS)
    usable_book = [t for t, m in book_meta.items() if m.get("usable")]
    print(f"[book] usable={len(usable_book)}/{len(BANKS)}  cols={list(book.columns)}")

    calendar = prices.index
    logmb = build_market_to_book(prices, book, shares, calendar)
    logmb = logmb.loc[logmb.index >= pd.Timestamp(START_ANALYSIS)]
    print(f"[M/B] banks_with_mb={logmb.shape[1]}  window={logmb.index.min().date()}..{logmb.index.max().date()}")

    rets = daily_log_returns(prices)
    lagrv = trailing_rv(rets)  # all tickers

    # ---- Diagnostics ----
    coverage = {t: int(logmb[t].notna().sum()) for t in logmb.columns}
    diagnostics = {
        "asof": asof,
        "end_date": END_DATE,
        "n_banks_requested": len(BANKS),
        "n_banks_price_ok": int(sum(1 for t in BANKS if t in prices.columns)),
        "n_banks_book_usable": len(usable_book),
        "n_banks_mb_built": int(logmb.shape[1]),
        "price_fails": price_fails,
        "book_meta_sample": {t: book_meta[t] for t in list(book_meta)[:6]},
        "mb_window": [str(logmb.index.min().date()), str(logmb.index.max().date())],
        "mb_coverage_days_median": int(np.median(list(coverage.values()))) if coverage else 0,
        "share_history_points_median": int(np.median([v for v in share_meta.values() if v])) if any(share_meta.values()) else 0,
        "survivorship_note": "SVB/SBNY/FRC (2023 failures) and merged names excluded; sample = survivors only -> bias toward NULL.",
        "price_confound_note": "Daily M/B varies mostly via price; all predictive tests control for trailing own-RV to isolate incremental fundamental info.",
    }

    # ---- Descriptive ----
    # HONESTY GUARD: yfinance's oldest annual book-equity column is often NaN, so
    # for most banks the earliest usable (10-K, +75d) book equity is the 2022
    # fiscal year, available only ~2023-03-16. Before that the cross-section is
    # near-empty (often a single off-fiscal-year name like RJF). Any median/frac
    # computed on the sparse early period is a sample-composition artifact, NOT a
    # regional-bank average. We therefore only report cross-sectional stats on
    # dates whose coverage >= MIN_XS_COVERAGE, and record the effective start.
    MIN_XS_COVERAGE = 10
    n_by_date = logmb.notna().sum(axis=1)
    populated = n_by_date >= MIN_XS_COVERAGE
    panel_start = str(n_by_date[populated].index.min().date()) if populated.any() else None

    xs_median_mb = logmb.median(axis=1)
    frac_below_book = (logmb < 0).mean(axis=1)  # fraction with M/B < 1
    # Coverage-gated views (only where >= MIN_XS_COVERAGE banks present)
    xs_median_g = xs_median_mb.where(populated)
    frac_below_g = frac_below_book.where(populated)

    descriptive = {
        "panel_effective_start": panel_start,
        "min_xs_coverage_for_stats": MIN_XS_COVERAGE,
        "sparse_early_period_note": (
            "Before ~2023-03-16 fewer than 10 banks have lag-safe book equity "
            "(yfinance oldest annual column mostly NaN -> earliest usable = 2022 "
            "10-K). Cross-sectional levels reported only from panel_effective_start."),
        "logmb_pooled_mean_gated": float(np.nanmean(logmb.where(populated).values)),
        "logmb_pooled_std_gated": float(np.nanstd(logmb.where(populated).values)),
        "mb_median_level_latest": float(np.exp(xs_median_g.dropna().iloc[-1])) if xs_median_g.notna().any() else None,
        "frac_below_book_latest": float(frac_below_g.dropna().iloc[-1]) if frac_below_g.notna().any() else None,
        "frac_below_book_max": float(frac_below_g.max()) if frac_below_g.notna().any() else None,
        "frac_below_book_max_date": str(frac_below_g.idxmax().date()) if frac_below_g.notna().any() else None,
    }

    # Stress case study — ONLY use windows with adequate coverage. The pre-window
    # (Jan-Feb 2023) is deliberately NOT compared on M/B because the panel is not
    # yet populated there; we report its coverage so the limitation is explicit.
    stress_mask = populated & (xs_median_mb.index >= pd.Timestamp(STRESS_START)) & (xs_median_mb.index <= pd.Timestamp(STRESS_END))
    pre_mask = (xs_median_mb.index >= pd.Timestamp("2023-01-01")) & (xs_median_mb.index < pd.Timestamp(STRESS_START))
    kre_trv = trailing_rv(rets)["KRE"].reindex(xs_median_mb.index) if "KRE" in prices.columns else None
    if stress_mask.any():
        descriptive["stress_2023"] = {
            "pre_window_coverage_banks_max": int(n_by_date[pre_mask].max()) if pre_mask.any() else 0,
            "pre_window_MB_not_reported_reason": "panel not populated (<10 banks) before ~2023-03-16",
            "stress_window_coverage_banks_min": int(n_by_date[stress_mask].min()),
            "median_MB_stress": float(np.exp(xs_median_mb[stress_mask].median())),
            "frac_below_book_stress_max": float(frac_below_book[stress_mask].max()),
            "frac_below_book_stress_max_date": str(frac_below_book[stress_mask].idxmax().date()),
            "kre_rv22_pre_median": float(kre_trv[pre_mask].median()) if kre_trv is not None and pre_mask.any() else None,
            "kre_rv22_stress_max": float(kre_trv[stress_mask].max()) if kre_trv is not None else None,
        }

    # ---- First-look lead-lag ----
    firstlook = {}

    # (1) Time-series: xs-median logMB(t-1) -> KRE/KBE forward RV(t+H)
    ts_results = {}
    for etf in ETFS:
        if etf not in prices.columns:
            continue
        per_etf = {}
        # Use coverage-gated cross-sectional median so the sparse early period
        # (single-name RJF) cannot contaminate the time-series signal.
        xs_med_sig = xs_median_mb.where(populated)
        sig = xs_med_sig.shift(1)
        sig_chg = xs_med_sig.diff(RV_TRAIL_WIN).shift(1)
        etf_lagrv = lagrv[etf]
        for h in HORIZONS:
            frv = forward_rv(rets[etf], h)
            df = pd.concat([sig.rename("sig"), sig_chg.rename("sigchg"),
                            etf_lagrv.rename("lagrv"), frv.rename("y")], axis=1)
            df = df.loc[df.index >= pd.Timestamp(START_ANALYSIS)].dropna()
            if len(df) < 60:
                per_etf[f"h{h}"] = {"n": int(len(df)), "note": "insufficient"}
                continue
            pear = float(np.corrcoef(df["sig"], df["y"])[0, 1])
            spear = float(pd.Series(df["sig"]).corr(pd.Series(df["y"]), method="spearman"))
            reg_level = newey_west_ols(df["y"].values, df[["sig", "lagrv"]].values, lags=h)
            reg_chg = newey_west_ols(df["y"].values, df[["sigchg", "lagrv"]].values, lags=h)
            per_etf[f"h{h}"] = {
                "n": int(len(df)),
                "pearson_sig_vs_fwdRV": pear,
                "spearman_sig_vs_fwdRV": spear,
                "reg_level_beta": reg_level["beta"],    # [const, logMB, lagRV]
                "reg_level_t": reg_level["t"],
                "reg_chg_beta": reg_chg["beta"],        # [const, dlogMB, lagRV]
                "reg_chg_t": reg_chg["t"],
                "hac_lag": h,
            }
        ts_results[etf] = per_etf
    firstlook["timeseries_etf"] = ts_results

    # (2) Fama-MacBeth cross-section (K1355-compliant)
    fm_results = {}
    banks_mb = list(logmb.columns)
    sig_panel = logmb.shift(1)
    lagrv_panel = lagrv[banks_mb].reindex(logmb.index)
    for h in HORIZONS:
        fwd_panel = pd.DataFrame({t: forward_rv(rets[t], h).reindex(logmb.index) for t in banks_mb})
        fm = fama_macbeth(sig_panel, lagrv_panel, fwd_panel, h)
        fm_results[f"h{h}"] = fm
    firstlook["fama_macbeth_xs"] = fm_results

    verdict = classify_verdict(firstlook)

    results = {
        "experiment_id": "k1605",
        "title": "Bank market-to-book divergence as a delayed-loss prior for regional-bank RV (Phase-1)",
        "asof": asof,
        "seed": SEED,
        "config": {
            "banks": BANKS, "etfs": ETFS,
            "start_price": START_PRICE, "start_analysis": START_ANALYSIS,
            "rv_trail_win": RV_TRAIL_WIN, "horizons": HORIZONS,
            "q_lag_days": Q_LAG_DAYS, "a_lag_days": A_LAG_DAYS,
        },
        "diagnostics": diagnostics,
        "descriptive": descriptive,
        "firstlook": firstlook,
        "verdict": verdict,
        "provenance": {
            "data_source": "yfinance (adjusted close, quarterly+annual balance_sheet, get_shares_full)",
            "free_data_only": True,
            "lookahead_protection": "book equity aligned to quarter_end+45d / fye+75d; signals shift(1); forward RV over (t,t+H]",
            "k1355_compliance": "Fama-MacBeth: cross-sectional slope per date, then HAC(lag>=H) on the date series",
            "price_confound_control": "trailing own-RV included in every predictive regression",
            "deferred_to_compute_queue": "panel HAC w/ full controls, DM test (MB-augmented vs RV-only forecast), block bootstrap CIs, OOS expanding refit",
        },
    }

    with open(f"{HERE}/k1605_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"[write] {HERE}/k1605_results.json")
    print(f"[verdict] {verdict['label']}: {verdict['reason']}")

    # Pass coverage-gated series to charts so the sparse (single-name) early
    # period is not drawn as if it were a regional-bank average.
    make_charts(logmb, xs_median_g, frac_below_g, prices, rets, firstlook)
    return results


def classify_verdict(firstlook):
    """Signal / weak / null based on first-look, honest and conservative."""
    hits = []
    for h, fm in firstlook.get("fama_macbeth_xs", {}).items():
        b = fm.get("spec_B_control_lagRV")
        if b and b.get("t") is not None:
            if b["mean"] < 0 and abs(b["t"]) > 2.0:
                hits.append(f"FM {h} controlled slope<0 t={b['t']:.2f}")
    for etf, per in firstlook.get("timeseries_etf", {}).items():
        for h, r in per.items():
            if "reg_level_t" in r:
                if r["reg_level_beta"][1] < 0 and abs(r["reg_level_t"][1]) > 2.0:
                    hits.append(f"{etf} {h} logMB beta<0 t={r['reg_level_t'][1]:.2f}")
    n = len(hits)
    if n >= 3:
        label = "signal"
    elif n >= 1:
        label = "weak"
    else:
        label = "null"
    return {"label": label, "n_significant_incremental": n, "hits": hits,
            "reason": f"{n} incremental (lagRV-controlled) tests with correct-sign |t|>2.0",
            "threshold_note": "Phase-1 first-look uses |t|>2; formal DM/Harvey |t|>3 deferred to compute queue"}


def make_charts(logmb, xs_median_mb, frac_below_book, prices, rets, firstlook):
    # Chart 1: cross-sectional M/B dispersion timeline with 2023 stress shaded
    fig, ax1 = plt.subplots(figsize=(11, 5))
    mb_med = np.exp(xs_median_mb.dropna())
    ax1.plot(mb_med.index, mb_med.values, color="#1f4e79", lw=1.6,
             label="Cross-sectional median M/B")
    ax1.axhline(1.0, color="grey", ls="--", lw=0.9)
    ax1.axvspan(pd.Timestamp(STRESS_START), pd.Timestamp(STRESS_END),
                color="#d62728", alpha=0.12, label="2023 regional-bank stress")
    ax1.set_ylabel("Median market-to-book (survivors)")
    ax1.set_xlabel("Date")
    ax2 = ax1.twinx()
    fb = frac_below_book.dropna()
    ax2.plot(fb.index, fb.values, color="#d62728", lw=1.0, alpha=0.7,
             label="Fraction trading below book")
    ax2.set_ylabel("Fraction with M/B < 1", color="#d62728")
    ax1.set_title("K1605 - Regional-bank cross-sectional M/B (lag-safe) over time")
    ax1.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(f"{HERE}/k1605_fig1_mb_dispersion.png", dpi=130)
    plt.close(fig)

    # Chart 2: scatter xs-median M/B(t-1) vs KRE forward RV(t+22)
    if "KRE" in prices.columns:
        h = 22
        sig = xs_median_mb.shift(1)
        frv = forward_rv(rets["KRE"], h)
        df = pd.concat([sig.rename("sig"), frv.rename("y")], axis=1)
        df = df.loc[df.index >= pd.Timestamp(START_ANALYSIS)].dropna()
        if len(df) > 30:
            fig, ax = plt.subplots(figsize=(7, 5.5))
            sc = ax.scatter(np.exp(df["sig"]), df["y"], s=10, alpha=0.4,
                            c=(df.index - df.index.min()).days, cmap="viridis")
            ax.set_xlabel("Cross-sectional median M/B (t-1)")
            ax.set_ylabel(f"KRE forward RV (t+1..t+{h}, annualized)")
            ax.set_title("K1605 - M/B level vs subsequent KRE realized vol")
            cbar = fig.colorbar(sc, ax=ax)
            cbar.set_label("days since window start")
            b = np.polyfit(df["sig"], df["y"], 1)
            xs = np.linspace(df["sig"].min(), df["sig"].max(), 50)
            ax.plot(np.exp(xs), np.polyval(b, xs), "r-", lw=1.3)
            fig.tight_layout()
            fig.savefig(f"{HERE}/k1605_fig2_scatter_kre.png", dpi=130)
            plt.close(fig)

    # Chart 3: Fama-MacBeth slopes summary bar
    fm = firstlook.get("fama_macbeth_xs", {})
    labels, meansA, meansB, tsB = [], [], [], []
    for h, r in fm.items():
        labels.append(h)
        a = r.get("spec_A_signal_only") or {}
        b = r.get("spec_B_control_lagRV") or {}
        meansA.append(a.get("mean", np.nan))
        meansB.append(b.get("mean", np.nan))
        tsB.append(b.get("t", np.nan))
    if labels:
        fig, ax = plt.subplots(figsize=(7, 5))
        x = np.arange(len(labels))
        ax.bar(x - 0.2, meansA, 0.4, label="signal only", color="#8c8c8c")
        ax.bar(x + 0.2, meansB, 0.4, label="+ lagRV control", color="#1f4e79")
        for i, t in enumerate(tsB):
            if not np.isnan(t):
                ax.annotate(f"t={t:.2f}", (x[i] + 0.2, meansB[i]),
                            ha="center", va="bottom", fontsize=8)
        ax.axhline(0, color="k", lw=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_ylabel("Fama-MacBeth avg cross-sectional slope (logMB -> forward RV)")
        ax.set_title("K1605 - Cross-sectional M/B slope on forward RV (HAC)")
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(f"{HERE}/k1605_fig3_fama_macbeth.png", dpi=130)
        plt.close(fig)
    print(f"[charts] wrote fig1/fig2/fig3 to {HERE}")


if __name__ == "__main__":
    main()
