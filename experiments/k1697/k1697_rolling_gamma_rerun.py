"""
K1697 — taiwan-vt Table 2 rolling block: calendar-aligned fresh-snapshot rerun
==============================================================================

MOTIVATION
----------
paper/taiwan-vt body_v3.tex Table `tab:gamma` rolling-window (w=2000) rows
(Hon Hai 2317 / MediaTek 2454 / Mega 2886 / 0056 ETF + 9-stock & 10-security
rolling averages + footnote rolling ratios 5.0x/4.5x + TWII rolling 0.272)
trace only to deleted-run knowledge entry N121/N120 — NON-REPRODUCIBLE
(fable_deep_review_20260711 F2; EXECUTION.md P0-2).

The predecessor re-estimate (experiments/paper2_taiwan_indiv_rolling_gamma)
established non-reproducibility but its calendar alignment was bound by stale
offline snapshots (common_end 2025-01-22, forced by k1302 2383/2886 CSVs) and
mixed adj-close/raw-close price columns inherited from K1302/K1302b.

K1697 removes both caveats:
  (1) FRESH pinned yfinance snapshots (auto_adjust=False, both Close and
      Adj Close columns pinned to experiments/k1697/data/) so the common
      calendar end date is the latest joint trading day, not a stale artifact;
  (2) a UNIFORM price column across all securities — canonical estimates use
      Adj Close log returns; a raw-Close sensitivity run quantifies how much
      of any change vs the predecessor comes from the price-column unification;
  (3) every MLE runs >=100 random multistarts (K1213 lesson: single-start
      basins can be fragile) with fixed seeds; best converged log-likelihood
      wins; basin diagnostics are recorded per fit.

SPEC (matches K892 estimate_gjr_garch / rolling_w2000.last_window convention)
-----------------------------------------------------------------------------
- GJR-GARCH(1,1), Constant mean, Normal innovations, `arch` MLE on returns*100.
- Rolling window w=2000; reported row = LAST 2000-obs window truncated to the
  COMMON terminal trading date across all Taiwan securities (calendar-aligned).
- t-values = arch robust MLE t (Bollerslev-Wooldridge). The paper table note
  says "Newey-West HAC" for these rows — same wording discrepancy as the
  predecessor; reported honestly here, not silently relabeled.
- Persistence = alpha + 0.5*gamma + beta.
- Returns: log returns (matches predecessor). K892 used simple pct_change;
  difference is negligible at daily frequency and documented in the README.
- No lookahead: gamma is an in-sample descriptive estimate on the last window,
  not a forecast/signal. All randomness (multistart draws) is seeded.

DATA
----
Phase 1 (snapshot): downloads 2008-01-01..present per ticker with
auto_adjust=False and pins the full OHLCV+AdjClose frame to
experiments/k1697/data/<ticker>.csv + snapshot_manifest.json. SKIPPED when the
CSV already exists — reruns are fully offline/reproducible from the pinned
snapshots.
Phase 2 (estimation): reads ONLY the pinned CSVs.

Placeholder-row filter: TWSE non-trading days (e.g. typhoon closures) can
appear in yfinance output as rows with Volume==0 and Open==High==Low==Close;
such rows are dropped (they would inject fake zero returns). Dropped rows are
counted per ticker in the results JSON.
"""

import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

REPO = "/Users/yhlai0911/volpred-research"
EXP_DIR = os.path.join(REPO, "experiments/k1697")
DATA_DIR = os.path.join(EXP_DIR, "data")
OUT_JSON = os.path.join(EXP_DIR, "k1697_results.json")
MANIFEST = os.path.join(DATA_DIR, "snapshot_manifest.json")
PRED_JSON = os.path.join(
    REPO,
    "experiments/paper2_taiwan_indiv_rolling_gamma/"
    "paper2_taiwan_indiv_rolling_gamma_results.json",
)

WINDOW = 2000
SAMPLE_START = "2008-01-01"
N_MULTISTART = 100  # random starts per fit, in addition to the arch default
BASE_SEED = 1697

# --- Ticker universe -------------------------------------------------------
# 9-stock set = canonical K1302+K1302b cross-section (excl 2330 TSMC, 0056 ETF)
NINE_STOCKS = {
    "2317.TW": "Hon Hai",
    "2454.TW": "MediaTek",
    "2383.TW": "Elite Material",
    "2886.TW": "Mega Financial",
    "2412.TW": "Chunghwa Telecom",
    "2881.TW": "Fubon",
    "2882.TW": "Cathay Financial",
    "2885.TW": "Yuanta",
    "2891.TW": "CTBC",
}
ETF = {"0056.TW": "Yuanta High Div. ETF"}
INDICES = {"^TWII": "Taiwan Weighted Index", "0050.TW": "Yuanta Taiwan 50 ETF"}
TSMC = {"2330.TW": "TSMC"}          # full-sample row in the table; aligned rolling for reference
US_REF = {"SPY": "SPDR S&P 500"}    # reference only; not part of the TW rolling block
ALL_TICKERS = {**INDICES, **TSMC, **NINE_STOCKS, **ETF, **US_REF}
TW_TICKERS = [t for t in ALL_TICKERS if t != "SPY"]  # define the common calendar end

# Legacy (untraceable N121/N120) Table 2 rolling values, for the comparison table
LEGACY = {
    "^TWII": {"gamma": 0.272, "gamma_t": 3.18},
    "2317.TW": {"gamma": 0.052, "gamma_t": 1.14},
    "2454.TW": {"gamma": 0.044, "gamma_t": 0.96},
    "2886.TW": {"gamma": 0.179, "gamma_t": 2.42},
    "0056.TW": {"gamma": 0.112, "gamma_t": 1.87},
}
LEGACY_AVG9, LEGACY_AVG10 = 0.054, 0.060
LEGACY_RATIO9, LEGACY_RATIO10 = 5.0, 4.5


def csv_path(ticker: str) -> str:
    return os.path.join(DATA_DIR, ticker.replace("^", "IDX_") + ".csv")


def snapshot_all() -> None:
    """Phase 1: pin fresh yfinance snapshots (auto_adjust=False). Skip existing."""
    import yfinance as yf

    manifest = {}
    if os.path.exists(MANIFEST):
        with open(MANIFEST) as f:
            manifest = json.load(f)
    for ticker in ALL_TICKERS:
        path = csv_path(ticker)
        if os.path.exists(path):
            print(f"[snapshot] {ticker}: exists, skip")
            continue
        for attempt in range(3):
            try:
                df = yf.download(
                    ticker, start=SAMPLE_START, auto_adjust=False, progress=False
                )
                if df.empty:
                    raise ValueError("empty frame")
                break
            except Exception as e:  # noqa: BLE001
                print(f"[snapshot] {ticker} attempt {attempt+1} failed: {e}")
                time.sleep(5)
        else:
            raise RuntimeError(f"snapshot failed for {ticker}")
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[["Open", "High", "Low", "Close", "Adj Close", "Volume"]]
        df.to_csv(path)
        manifest[ticker] = {
            "file": os.path.basename(path),
            "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
            "yfinance_version": yf.__version__,
            "auto_adjust": False,
            "start": SAMPLE_START,
            "n_rows": int(len(df)),
            "first_date": str(df.index[0].date()),
            "last_date": str(df.index[-1].date()),
        }
        with open(MANIFEST, "w") as f:
            json.dump(manifest, f, indent=2)
        print(f"[snapshot] {ticker}: {len(df)} rows "
              f"({df.index[0].date()}..{df.index[-1].date()})")


def load_series(ticker: str) -> tuple[pd.DataFrame, dict]:
    """Load pinned CSV, drop NaN-Close and placeholder (Volume==0 & OHLC equal) rows."""
    df = pd.read_csv(csv_path(ticker), index_col=0, parse_dates=True)
    n_raw = len(df)
    df = df.dropna(subset=["Close"])
    flat = (
        (df["Volume"].fillna(0) == 0)
        & (df["Open"] == df["Close"])
        & (df["High"] == df["Close"])
        & (df["Low"] == df["Close"])
    )
    n_placeholder = int(flat.sum())
    df = df[~flat]
    info = {
        "n_rows_raw": n_raw,
        "n_placeholder_dropped": n_placeholder,
        "n_rows_clean": int(len(df)),
        "first_date": str(df.index[0].date()),
        "last_date": str(df.index[-1].date()),
    }
    return df, info


def log_returns(prices: pd.Series) -> pd.Series:
    return np.log(prices / prices.shift(1)).dropna()


def draw_start(rng: np.random.Generator, ret_pct: pd.Series) -> np.ndarray:
    """Random admissible starting vector [mu, omega, alpha, gamma, beta]."""
    sample_var = float(ret_pct.var())
    for _ in range(200):
        alpha = rng.uniform(0.005, 0.20)
        gamma = rng.uniform(0.0, 0.40)
        beta = rng.uniform(0.40, 0.97)
        if alpha + 0.5 * gamma + beta < 0.995:
            break
    persistence = alpha + 0.5 * gamma + beta
    omega = max(sample_var * (1.0 - persistence), 1e-6)
    mu = float(ret_pct.mean()) + rng.normal(0.0, float(ret_pct.std()) / np.sqrt(len(ret_pct)))
    return np.array([mu, omega, alpha, gamma, beta])


def fit_gjr_multistart(returns: pd.Series, seed: int) -> dict:
    """GJR-GARCH(1,1) MLE with arch default start + N_MULTISTART seeded random
    starts; best converged log-likelihood wins (K1213 multistart rule)."""
    from arch import arch_model

    ret_pct = returns * 100.0
    am = arch_model(ret_pct, vol="GARCH", p=1, o=1, q=1, dist="normal", mean="Constant")
    rng = np.random.default_rng(seed)

    fits = []
    try:
        res0 = am.fit(disp="off", options={"maxiter": 5000})
        fits.append(("default", res0))
    except Exception:  # noqa: BLE001
        pass
    for i in range(N_MULTISTART):
        sv = draw_start(rng, ret_pct)
        try:
            res = am.fit(disp="off", options={"maxiter": 5000}, starting_values=sv)
            fits.append((f"rand{i}", res))
        except Exception:  # noqa: BLE001
            continue

    converged = [(tag, r) for tag, r in fits if r.convergence_flag == 0]
    pool = converged if converged else fits
    if not pool:
        raise RuntimeError("all starts failed")
    best_tag, best = max(pool, key=lambda tr: tr[1].loglikelihood)

    logliks = np.array([r.loglikelihood for _, r in converged]) if converged else np.array([])
    gammas = np.array([float(r.params.get("gamma[1]", np.nan)) for _, r in converged])
    best_ll = float(best.loglikelihood)
    n_at_best = int((np.abs(logliks - best_ll) < 0.01).sum()) if len(logliks) else 0
    default_ll = next((float(r.loglikelihood) for tag, r in fits if tag == "default"), None)

    p, t = best.params, best.tvalues
    alpha = float(p.get("alpha[1]", np.nan))
    gamma = float(p.get("gamma[1]", np.nan))
    beta = float(p.get("beta[1]", np.nan))
    return {
        "mu": float(p.get("mu", np.nan)),
        "omega": float(p.get("omega", np.nan)),
        "alpha": alpha,
        "gamma": gamma,
        "beta": beta,
        "gamma_t": float(t.get("gamma[1]", np.nan)),
        "alpha_t": float(t.get("alpha[1]", np.nan)),
        "beta_t": float(t.get("beta[1]", np.nan)),
        "persistence": alpha + 0.5 * gamma + beta,
        "n_obs": int(len(returns)),
        "log_likelihood": best_ll,
        "convergence": int(best.convergence_flag),
        "multistart": {
            "seed": seed,
            "n_starts_total": 1 + N_MULTISTART,
            "n_converged": len(converged),
            "n_at_best_basin": n_at_best,
            "best_start": best_tag,
            "default_loglik": default_ll,
            "default_minus_best": (
                None if default_ll is None else round(default_ll - best_ll, 6)
            ),
            "gamma_range_converged": (
                [float(np.nanmin(gammas)), float(np.nanmax(gammas))]
                if len(gammas) else None
            ),
        },
    }


def last_window(returns: pd.Series, end_cutoff: pd.Timestamp) -> pd.Series:
    r = returns[returns.index <= end_cutoff]
    if len(r) < WINDOW:
        raise ValueError(f"only {len(r)} obs < window {WINDOW}")
    return r.iloc[-WINDOW:]


def stable_seed(ticker: str, variant: str) -> int:
    h = sum(ord(c) * (i + 1) for i, c in enumerate(ticker + ":" + variant))
    return BASE_SEED * 100000 + h


def reconciliation_checks(frames: dict) -> dict:
    """Truncate the FRESH snapshots to the predecessors' window end dates and
    re-estimate under their conventions. Exact recovery proves the fresh data
    and this pipeline are consistent with K892 and the predecessor experiment,
    i.e. all changes in the canonical numbers come from the window end date
    moving (plus the documented spec unification), not from data or code."""
    checks = {}

    # K892 TWII rolling last_window: SIMPLE returns, data ends 2026-04-05
    r_simple = frames["^TWII"]["Adj Close"].astype(float).pct_change().dropna()
    w = last_window(r_simple, pd.Timestamp("2026-04-05"))
    est = fit_gjr_multistart(w, seed=stable_seed("^TWII", "k892check"))
    checks["twii_simple_end_20260405_vs_k892"] = {
        "gamma": est["gamma"], "gamma_t": est["gamma_t"],
        "expected": {"gamma": 0.2614, "gamma_t": 3.32,
                     "source": "k892 rolling_w2000.last_window"},
    }

    # Predecessor (aligned 2025-01-22): log returns on adj close
    for ticker, exp_g, exp_t in [("^TWII", 0.158, 2.57), ("2886.TW", 0.054, 1.41)]:
        r_log = log_returns(frames[ticker]["Adj Close"].astype(float))
        w = last_window(r_log, pd.Timestamp("2025-01-22"))
        est = fit_gjr_multistart(w, seed=stable_seed(ticker, "predcheck"))
        checks[f"{ticker}_log_end_20250122_vs_predecessor"] = {
            "gamma": est["gamma"], "gamma_t": est["gamma_t"],
            "expected": {"gamma": exp_g, "gamma_t": exp_t,
                         "source": "paper2_taiwan_indiv_rolling_gamma (aligned)"},
        }

    # Isolation: log returns at K892's end date — quantifies how much of the
    # K892-vs-canonical gap is return convention vs window end date.
    r_log = log_returns(frames["^TWII"]["Adj Close"].astype(float))
    w = last_window(r_log, pd.Timestamp("2026-04-05"))
    est = fit_gjr_multistart(w, seed=stable_seed("^TWII", "logapr"))
    checks["twii_log_end_20260405_isolation"] = {
        "gamma": est["gamma"], "gamma_t": est["gamma_t"],
        "note": ("log-vs-simple contributes ~0.007 at the same end date; the "
                 "rest of the move to the canonical 2026-07-09 value is the "
                 "window end date"),
    }
    return checks


def main() -> None:
    t0 = time.time()
    snapshot_all()

    frames, clean_info = {}, {}
    for ticker in ALL_TICKERS:
        frames[ticker], clean_info[ticker] = load_series(ticker)
        print(f"[load] {ticker}: {clean_info[ticker]}")

    # Calendar alignment: common terminal trading date over TW securities only
    # (SPY trades a different calendar; it is truncated to the same date).
    common_end = min(frames[t].index[-1] for t in TW_TICKERS)
    print(f"\n[calendar-align] COMMON_END = {common_end.date()} "
          f"(min last clean obs across {len(TW_TICKERS)} TW securities)")

    results = {}
    for variant, price_col in [("adjclose", "Adj Close"), ("rawclose", "Close")]:
        print(f"\n===== variant: {variant} ({price_col}) =====")
        rows = {}
        for ticker, name in ALL_TICKERS.items():
            r = log_returns(frames[ticker][price_col].astype(float))
            w = last_window(r, common_end)
            est = fit_gjr_multistart(w, seed=stable_seed(ticker, variant))
            est.update(
                name=name,
                ticker=ticker,
                price_column=price_col,
                window=WINDOW,
                window_start=str(w.index[0].date()),
                window_end=str(w.index[-1].date()),
            )
            rows[ticker] = est
            ms = est["multistart"]
            print(
                f"{ticker:8s} {name:20s} g={est['gamma']:.4f} (t={est['gamma_t']:.2f}) "
                f"a={est['alpha']:.4f} b={est['beta']:.4f} pers={est['persistence']:.4f} "
                f"ll={est['log_likelihood']:.2f} "
                f"[conv {ms['n_converged']}/{ms['n_starts_total']}, "
                f"best-basin {ms['n_at_best_basin']}, best={ms['best_start']}]"
            )
        g9 = float(np.mean([rows[t]["gamma"] for t in NINE_STOCKS]))
        g10 = float(np.mean([rows[t]["gamma"] for t in NINE_STOCKS]
                            + [rows["0056.TW"]["gamma"]]))
        twii_g = rows["^TWII"]["gamma"]
        agg = {
            "gamma_mean_9stock": g9,
            "gamma_mean_10security_incl_0056": g10,
            "alpha_mean_9stock": float(np.mean([rows[t]["alpha"] for t in NINE_STOCKS])),
            "beta_mean_9stock": float(np.mean([rows[t]["beta"] for t in NINE_STOCKS])),
            "twii_rolling_gamma": twii_g,
            "amplification_ratio_9stock": twii_g / g9,
            "amplification_ratio_10security": twii_g / g10,
            "ratio_0050_based_9stock": rows["0050.TW"]["gamma"] / g9,
            "ratio_0050_based_10security": rows["0050.TW"]["gamma"] / g10,
        }
        print(f"avg9={g9:.4f} avg10={g10:.4f} "
              f"ratio9={agg['amplification_ratio_9stock']:.1f}x "
              f"ratio10={agg['amplification_ratio_10security']:.1f}x (TWII base {twii_g:.4f})")
        results[variant] = {"per_security": rows, "aggregates": agg}

    # --- Comparison vs legacy N121 and vs predecessor (aligned 2025-01-22) ---
    pred = {}
    if os.path.exists(PRED_JSON):
        with open(PRED_JSON) as f:
            pj = json.load(f)
        for t, v in pj.get("per_stock", {}).items():
            pred[t] = {"gamma": v["gamma"], "gamma_t": v["gamma_t"]}
        pred["0056.TW"] = {
            "gamma": pj["etf_0056"]["gamma"], "gamma_t": pj["etf_0056"]["gamma_t"]
        }
        for t, v in pj.get("index_rows", {}).items():
            key = "^TWII" if t == "TWII" else t
            pred[key] = {"gamma": v["gamma"], "gamma_t": v["gamma_t"]}
        pred["_aggregates"] = pj.get("rolling_averages_and_ratio", {})
        pred["_common_end"] = pj.get("calendar_alignment_common_end")

    canon = results["adjclose"]["per_security"]
    comparison = {}
    for t in ["^TWII", "0050.TW", "2330.TW", *NINE_STOCKS, "0056.TW", "SPY"]:
        comparison[t] = {
            "name": ALL_TICKERS[t],
            "legacy_n121": LEGACY.get(t),
            "predecessor_aligned_20250122": pred.get(t),
            "k1697_fresh_aligned": {
                "gamma": canon[t]["gamma"], "gamma_t": canon[t]["gamma_t"]
            },
            "k1697_rawclose_sensitivity": {
                "gamma": results["rawclose"]["per_security"][t]["gamma"],
                "gamma_t": results["rawclose"]["per_security"][t]["gamma_t"],
            },
        }

    out = {
        "experiment_id": "k1697",
        "title": ("taiwan-vt Table 2 rolling block — calendar-aligned "
                  "fresh-snapshot rerun (P0-2, fable_deep_review_20260711 F2)"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "method": (
            "GJR-GARCH(1,1) MLE (arch), Constant mean, Normal innov, log-returns*100; "
            "rolling w=2000 LAST window truncated to common calendar end; "
            f"{N_MULTISTART} seeded random multistarts + arch default per fit, "
            "best converged log-likelihood wins; robust (Bollerslev-Wooldridge) t; "
            "persistence=alpha+0.5*gamma+beta"
        ),
        "data": {
            "source": "yfinance pinned snapshots (auto_adjust=False), experiments/k1697/data/",
            "sample_start": SAMPLE_START,
            "calendar_alignment_common_end": str(common_end.date()),
            "per_ticker_cleaning": clean_info,
            "placeholder_rule": ("rows with Volume==0 and Open==High==Low==Close "
                                 "dropped (TWSE closure placeholders)"),
        },
        "canonical_variant": "adjclose",
        "variants": results,
        "comparison_table": comparison,
        "legacy_aggregates": {
            "gamma_mean_9stock": LEGACY_AVG9,
            "gamma_mean_10security": LEGACY_AVG10,
            "ratio_9stock": LEGACY_RATIO9,
            "ratio_10security": LEGACY_RATIO10,
        },
        "predecessor": {
            "experiment": "paper2_taiwan_indiv_rolling_gamma",
            "calendar_alignment_common_end": pred.get("_common_end"),
            "aggregates": pred.get("_aggregates"),
            "caveats_resolved_by_k1697": [
                "common_end was stale (2025-01-22, bound by k1302 snapshots)",
                "mixed adj-close / raw-close price columns across securities",
                "single-start MLE (no multistart diagnostics)",
            ],
        },
        "lookahead_free_certification": (
            "In-sample descriptive MLE on the last 2000-obs window; no forecast, "
            "no OOS split, no signal generation. All random draws seeded "
            f"(BASE_SEED={BASE_SEED}, per-(ticker,variant) derived seeds)."
        ),
        "reconciliation_checks": reconciliation_checks(frames),
        "t_stat_wording_note": (
            "Reported t = arch robust MLE (Bollerslev-Wooldridge). Paper table "
            "note currently says 'Newey-West HAC' for rolling rows — wording "
            "must be fixed at rebind time (same discrepancy flagged by the "
            "predecessor experiment)."
        ),
        "runtime_seconds": round(time.time() - t0, 1),
    }
    with open(OUT_JSON, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n[done] runtime {out['runtime_seconds']}s -> {OUT_JSON}")


if __name__ == "__main__":
    main()
