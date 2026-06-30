"""
K1589 — Reinsurer / cat-bond carrier individual-stock vol vs Atlantic hurricane
landfall dose-response.

Research question:
    Does the Saffir-Simpson category of an Atlantic hurricane at landfall predict
    a dose-response increase in specialty-reinsurer individual-stock realized
    volatility (RV) in the 5 trading days post-landfall, after controlling for
    market-wide vol shock (VIX, SPY RV)?

Method (high level):
    - Universe: RNR, EG, ACGL, AXS (specialty reinsurers); KIE (insurance ETF
      sanity baseline); SPY, ^VIX (market controls).
      Ticker notes:
        * EG = Everest Group (renamed from Everest Re "RE" in 2023-06).
          yfinance backfills full history under EG to 2010.
        * ACGL = Arch Capital Group (the ticker "ARCH" on yfinance is Arch
          Resources, an unrelated coal company).
    - Events: NOAA HURDAT2 Atlantic landfalls 2010-01-01 to 2024-12-31, hurricane
      strength (>= 64 kt wind = Cat 1+). Each storm contributes ONE landfall
      event = the first landfall record per storm.
    - Outcomes:
        ΔRV_i,e = RV_5d(t+1:t+5) - RV_21d(pre, ending no later than t0-6 cal days)
      where RV is annualized std of daily log returns over the respective
      trading-day windows.
    - Regression (per stock i, pooled across events e):
        ΔRV_i,e = α + β·Category_e + γ·VIX_t-1 + δ·SPY_RV21_t-1 + ε
      with events sorted chronologically before HAC (Newey-West, lag 10)
      standard errors.
    - Multiple-testing: Holm-Bonferroni across the 4 reinsurer outcome stocks
      (RNR, EG, ACGL, AXS) for the β coefficient. KIE is a benchmark, not part
      of the reinsurer family.
    - Identification check: stacked panel test of Category × Reinsurer vs KIE,
      clustered by event date.

Lookahead policy:
    The pre-event 21-return window ends no later than t-6 calendar days (no
    landfall-week or post-landfall info enters baseline RV). The event-window
    starts t+1 trading days after the first trading day ≥ landfall date. VIX
    and SPY controls are strictly pre-t0. All RV are realized backward-looking
    over closed price history; no future info.
    `random.seed(42)` is set even though no random procedure is used (defensive).

Dependencies (Python ≥ 3.9):
    pip install yfinance numpy pandas scipy statsmodels requests

Outputs:
    experiments/k1589/k1589_results.json — events_used, regression coefficients,
    raw + Holm-adjusted p-values, baseline / event RV per stock per event,
    reinsurer-mean vs KIE comparison.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
import statsmodels.api as sm

random.seed(42)
np.random.seed(42)

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
DATA_DIR.mkdir(exist_ok=True)

# ----- 1. Parse HURDAT2 ------------------------------------------------------

HURDAT2_PATH = DATA_DIR / "hurdat2.txt"


def parse_hurdat2(path: Path, start_year: int = 2010, end_year: int = 2024) -> pd.DataFrame:
    """Return one row per (storm, FIRST landfall) record at Cat 1+ intensity."""
    records = []
    current_id = None
    current_name = None
    with open(path) as fh:
        for line in fh:
            parts = [p.strip() for p in line.strip().split(",") if p != ""]
            if line.startswith("AL") and len(parts) >= 3 and parts[0].startswith("AL"):
                current_id = parts[0]
                current_name = parts[1]
                continue
            if current_id is None:
                continue
            if len(parts) < 7:
                continue
            try:
                date_str = parts[0]
                yr = int(date_str[:4])
            except ValueError:
                continue
            if yr < start_year or yr > end_year:
                continue
            record_id = parts[2]
            status = parts[3]
            if record_id != "L":
                continue
            try:
                wind_kt = int(parts[6])
            except ValueError:
                continue
            try:
                dt = datetime.strptime(date_str, "%Y%m%d")
            except ValueError:
                continue
            records.append({
                "storm_id": current_id,
                "name": current_name,
                "landfall_date": dt,
                "status": status,
                "wind_kt": wind_kt,
            })
    df = pd.DataFrame(records)
    if df.empty:
        return df
    df = df.sort_values(["storm_id", "landfall_date"]).reset_index(drop=True)
    # Per design: use FIRST landfall date and the wind at THAT landfall.
    df = df.drop_duplicates("storm_id", keep="first").reset_index(drop=True)

    def cat(w: int) -> int:
        # Saffir-Simpson thresholds in knots (1-min sustained wind):
        # 64 = Cat 1, 83 = Cat 2, 96 = Cat 3, 113 = Cat 4, 137 = Cat 5.
        if w >= 137:
            return 5
        if w >= 113:
            return 4
        if w >= 96:
            return 3
        if w >= 83:
            return 2
        if w >= 64:
            return 1
        return 0

    df["category"] = df["wind_kt"].apply(cat)
    df = df[df["category"] >= 1].reset_index(drop=True)
    return df


# ----- 2. Fetch market data ---------------------------------------------------

TICKERS = ["RNR", "EG", "ACGL", "AXS", "KIE", "SPY", "^VIX"]
STOCKS = ["RNR", "EG", "ACGL", "AXS", "KIE"]
REINSURERS = ["RNR", "EG", "ACGL", "AXS"]


def fetch_prices(start: str = "2009-09-01", end: str = "2025-01-15") -> pd.DataFrame:
    cache = DATA_DIR / "prices.csv"
    if cache.exists():
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
        return df
    df = yf.download(
        TICKERS,
        start=start,
        end=end,
        progress=False,
        auto_adjust=True,
        threads=False,
    )
    if isinstance(df.columns, pd.MultiIndex):
        close = df["Close"].copy()
    else:
        close = df[["Close"]].copy()
    close = close.dropna(how="all")
    # Ensure all expected tickers are present, even if some failed
    missing = [t for t in TICKERS if t not in close.columns]
    if missing:
        raise RuntimeError(f"missing tickers in download: {missing}")
    close.to_csv(cache)
    return close


# ----- 3. Build per-event panel -----------------------------------------------


def compute_rv_windows(close: pd.DataFrame, event_dates: list[pd.Timestamp]) -> pd.DataFrame:
    """Compute per-event pre- and post-event annualized RV for each ticker.

    Pre-event RV: 21 trading-return observations ending at the last trading
    date no later than t0-6 calendar days. This keeps landfall-week trading
    from entering the baseline while preserving a fixed 21-return RV scale.
    Event RV: 5 trading-return observations starting t+1, where t0 is the
    first trading day ≥ landfall_date. VIX and SPY controls are strictly
    pre-t0.
    """
    logret = np.log(close / close.shift(1))
    trading_idx = close.index
    rows = []
    for ed in event_dates:
        future = trading_idx[trading_idx >= ed]
        if len(future) == 0:
            continue
        t0 = future[0]
        pre_end_cd = t0 - pd.Timedelta(days=6)
        pre_candidates = logret.index[logret.index <= pre_end_cd]
        if len(pre_candidates) < 21:
            continue
        pre_idx = pre_candidates[-21:]
        pre_rows = logret.loc[pre_idx]
        idx_of_t0 = trading_idx.get_loc(t0)
        post_idx = trading_idx[idx_of_t0 + 1 : idx_of_t0 + 6]
        post_rows = logret.loc[post_idx]
        spy_lag_rows = logret["SPY"].iloc[max(0, idx_of_t0 - 21) : idx_of_t0]
        if len(pre_rows) < 21 or len(post_rows) < 5 or len(spy_lag_rows.dropna()) < 21:
            continue
        rec = {
            "event_date": ed,
            "t0_trading": t0,
            "pre_rv_start": pre_rows.index[0],
            "pre_rv_end": pre_rows.index[-1],
            "post_rv_start": post_rows.index[0],
            "post_rv_end": post_rows.index[-1],
        }
        for col in logret.columns:
            pre_std = pre_rows[col].std() * np.sqrt(252)
            post_std = post_rows[col].std() * np.sqrt(252)
            rec[f"pre_rv_{col}"] = float(pre_std) if pd.notna(pre_std) else np.nan
            rec[f"post_rv_{col}"] = float(post_std) if pd.notna(post_std) else np.nan
            rec[f"drv_{col}"] = (
                float(post_std - pre_std)
                if pd.notna(post_std) and pd.notna(pre_std)
                else np.nan
            )
        if "^VIX" in close.columns:
            vix_pre = close["^VIX"].loc[close.index < t0]
            rec["vix_lag1"] = float(vix_pre.iloc[-1]) if len(vix_pre) > 0 else np.nan
        rec["spy_rv_lag21"] = float(spy_lag_rows.std() * np.sqrt(252))
        rows.append(rec)
    return pd.DataFrame(rows).sort_values("event_date").reset_index(drop=True)


# ----- 4. Regression with HAC SE ---------------------------------------------


def run_regression(panel: pd.DataFrame, stock: str) -> dict:
    y_col = f"drv_{stock}"
    spy_control_col = "spy_rv_lag21"
    need = ["category", "vix_lag1", spy_control_col, y_col]
    if not all(c in panel.columns for c in need):
        return {"n": 0, "error": f"missing cols: {[c for c in need if c not in panel.columns]}"}
    df = panel[need + ["event_date"]].dropna().sort_values("event_date").copy()
    n = len(df)
    if n < 5:
        return {"n": n, "error": "insufficient observations"}
    y = df[y_col].values
    X = sm.add_constant(df[["category", "vix_lag1", spy_control_col]].values)
    model = sm.OLS(y, X)
    res = model.fit(cov_type="HAC", cov_kwds={"maxlags": 10})
    return {
        "n": int(n),
        "event_order": "chronological_by_event_date",
        "cov_type": "HAC",
        "cov_maxlags": 10,
        "alpha": float(res.params[0]),
        "beta_category": float(res.params[1]),
        "gamma_vix": float(res.params[2]),
        "delta_spy_rv_lag21": float(res.params[3]),
        "se_beta": float(res.bse[1]),
        "t_beta": float(res.tvalues[1]),
        "p_beta": float(res.pvalues[1]),
        "rsq": float(res.rsquared),
        "y_mean": float(np.mean(y)),
        "y_std": float(np.std(y, ddof=1)),
    }


def holm_bonferroni(pvals: list[float]) -> list[float]:
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    adj = [0.0] * m
    running = 0.0
    for rank, idx in enumerate(order):
        candidate = (m - rank) * pvals[idx]
        running = max(running, candidate)
        adj[idx] = min(1.0, running)
    return adj


def run_kie_interaction_test(panel: pd.DataFrame) -> dict:
    """Test whether reinsurer category slope exceeds KIE category slope.

    The coefficient on `category_x_reinsurer` is the formal benchmark
    identification test. It is a pooled average reinsurer-vs-KIE difference,
    clustered by event date to avoid treating same-event stock residuals as
    independent.
    """
    rows = []
    base_cols = ["event_date", "category", "vix_lag1", "spy_rv_lag21"]
    for stock in STOCKS:
        y_col = f"drv_{stock}"
        need = base_cols + [y_col]
        if not all(c in panel.columns for c in need):
            continue
        df = panel[need].dropna().copy()
        df["stock"] = stock
        df["y"] = df[y_col]
        df["reinsurer"] = 1 if stock in REINSURERS else 0
        rows.append(df[base_cols + ["stock", "y", "reinsurer"]])

    if not rows:
        return {"n": 0, "error": "missing stacked panel rows"}

    df = pd.concat(rows, ignore_index=True).sort_values(["event_date", "stock"]).reset_index(drop=True)
    if df["event_date"].nunique() < 5:
        return {"n": int(len(df)), "error": "insufficient event clusters"}

    df["category_x_reinsurer"] = df["category"] * df["reinsurer"]
    X = pd.DataFrame({
        "const": 1.0,
        "category": df["category"].astype(float),
        "reinsurer": df["reinsurer"].astype(float),
        "category_x_reinsurer": df["category_x_reinsurer"].astype(float),
        "vix_lag1": df["vix_lag1"].astype(float),
        "spy_rv_lag21": df["spy_rv_lag21"].astype(float),
    })
    groups = pd.factorize(df["event_date"])[0]
    res = sm.OLS(df["y"].values, X).fit(cov_type="cluster", cov_kwds={"groups": groups})
    diff_test = res.t_test([0, 0, 0, 1, 0, 0])
    total_reinsurer_test = res.t_test([0, 1, 0, 1, 0, 0])
    diff_se = float(np.ravel(diff_test.sd)[0])
    diff_t = float(np.ravel(diff_test.tvalue)[0])
    diff_p = float(np.ravel(diff_test.pvalue)[0])
    total_se = float(np.ravel(total_reinsurer_test.sd)[0])
    total_t = float(np.ravel(total_reinsurer_test.tvalue)[0])
    total_p = float(np.ravel(total_reinsurer_test.pvalue)[0])
    return {
        "n": int(len(df)),
        "n_events": int(df["event_date"].nunique()),
        "n_stocks": int(df["stock"].nunique()),
        "cov_type": "cluster_by_event_date",
        "beta_kie_category": float(res.params["category"]),
        "beta_reinsurer_minus_kie_category": float(res.params["category_x_reinsurer"]),
        "se_reinsurer_minus_kie_category": diff_se,
        "t_reinsurer_minus_kie_category": diff_t,
        "p_reinsurer_minus_kie_category": diff_p,
        "beta_reinsurer_category_total": float(res.params["category"] + res.params["category_x_reinsurer"]),
        "se_reinsurer_category_total": total_se,
        "t_reinsurer_category_total": total_t,
        "p_reinsurer_category_total": total_p,
    }


# ----- 5. Main ----------------------------------------------------------------


def main() -> None:
    print("[K1589] parsing HURDAT2 …")
    storms = parse_hurdat2(HURDAT2_PATH)
    print(f"        {len(storms)} storms with Cat 1+ first-landfalls in 2010-2024.")

    print("[K1589] fetching market data …")
    close = fetch_prices()
    print(f"        price panel: {close.shape[0]} trading days × {close.shape[1]} columns.")
    print(f"        columns: {list(close.columns)}")

    print("[K1589] building per-event windows …")
    event_dates = [pd.Timestamp(d) for d in storms["landfall_date"].tolist()]
    panel = compute_rv_windows(close, event_dates)
    storms_idx = storms.copy()
    storms_idx["event_date"] = pd.to_datetime(storms_idx["landfall_date"])
    panel = panel.merge(
        storms_idx[["event_date", "name", "category", "wind_kt", "storm_id"]],
        on="event_date",
        how="left",
    ).sort_values("event_date").reset_index(drop=True)
    print(f"        usable events with full panel: {len(panel)}")

    print("[K1589] running per-stock regressions …")
    reg_results = {}
    for s in STOCKS:
        out = run_regression(panel, s)
        reg_results[s] = out
        if "p_beta" in out:
            print(
                f"        {s:5s} n={out['n']:3d} β={out['beta_category']:+.4f} "
                f"(SE={out['se_beta']:.4f}, t={out['t_beta']:+.2f}, p={out['p_beta']:.4f})"
            )
        else:
            print(f"        {s:5s} ERROR {out.get('error')}")

    holm_reinsurer_order = [s for s in REINSURERS if "p_beta" in reg_results.get(s, {})]
    adj = holm_bonferroni([reg_results[s]["p_beta"] for s in holm_reinsurer_order]) if holm_reinsurer_order else []
    for s, p_adj in zip(holm_reinsurer_order, adj):
        reg_results[s]["p_beta_holm_reinsurer_scope"] = float(p_adj)
    if "KIE" in reg_results:
        reg_results["KIE"]["p_beta_holm_reinsurer_scope"] = None
        reg_results["KIE"]["benchmark_role"] = "excluded_from_reinsurer_multiple_testing_family"

    print("[K1589] running KIE benchmark interaction test …")
    kie_interaction = run_kie_interaction_test(panel)

    reinsurer_betas = [
        reg_results[s]["beta_category"]
        for s in REINSURERS
        if "beta_category" in reg_results[s]
    ]
    kie_beta = reg_results.get("KIE", {}).get("beta_category")
    id_check = {
        "reinsurer_mean_beta": float(np.mean(reinsurer_betas)) if reinsurer_betas else None,
        "kie_beta": float(kie_beta) if kie_beta is not None else None,
        "reinsurer_minus_kie": (
            float(np.mean(reinsurer_betas) - kie_beta)
            if reinsurer_betas and kie_beta is not None
            else None
        ),
    }
    id_check["formal_kie_interaction_test"] = kie_interaction

    diag = {}
    for s in STOCKS + ["SPY"]:
        pre_col = f"pre_rv_{s}"
        post_col = f"post_rv_{s}"
        if pre_col in panel.columns and post_col in panel.columns:
            diag[s] = {
                "pre_rv_mean": float(panel[pre_col].mean()),
                "post_rv_mean": float(panel[post_col].mean()),
                "drv_mean": float((panel[post_col] - panel[pre_col]).mean()),
            }

    base_cols = ["category", "vix_lag1", "spy_rv_lag21"] + [f"drv_{s}" for s in STOCKS]
    full_panel = (
        panel.dropna(subset=[c for c in base_cols if c in panel.columns])
        .sort_values("event_date")
        .copy()
    )
    events_used = []
    for _, r in full_panel.iterrows():
        events_used.append({
            "storm_id": r["storm_id"],
            "name": str(r["name"]),
            "landfall_date": pd.Timestamp(r["event_date"]).strftime("%Y-%m-%d"),
            "t0_trading": pd.Timestamp(r["t0_trading"]).strftime("%Y-%m-%d"),
            "pre_rv_start": pd.Timestamp(r["pre_rv_start"]).strftime("%Y-%m-%d"),
            "pre_rv_end": pd.Timestamp(r["pre_rv_end"]).strftime("%Y-%m-%d"),
            "post_rv_start": pd.Timestamp(r["post_rv_start"]).strftime("%Y-%m-%d"),
            "post_rv_end": pd.Timestamp(r["post_rv_end"]).strftime("%Y-%m-%d"),
            "wind_kt": int(r["wind_kt"]),
            "category": int(r["category"]),
        })

    any_sig = any(
        reg_results[s].get("p_beta_holm_reinsurer_scope", 1.0) < 0.10
        and reg_results[s].get("beta_category", 0) > 0
        for s in REINSURERS
    )
    identification_pass = (
        kie_interaction.get("beta_reinsurer_minus_kie_category", 0) > 0
        and kie_interaction.get("p_reinsurer_minus_kie_category", 1.0) < 0.10
    )
    verdict_internal = "PASS" if (any_sig and identification_pass) else "NULL"

    results = {
        "experiment_id": "k1589",
        "title": "Reinsurer / cat-bond carrier vol dose-response to Atlantic hurricane landfall",
        "run_date_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "seed": 42,
        "lookahead_policy": (
            "pre-event RV uses 21 trading returns ending no later than t0-6 calendar days; "
            "event RV uses t+1..t+5 trading returns after first trading day ≥ landfall; "
            "VIX control uses last close strictly before t0; SPY control uses 21 trading "
            "returns strictly before t0."
        ),
        "rv_window_spec": {
            "pre_rv": "21 trading-return std * sqrt(252), ending at last trading date <= t0-6 calendar days",
            "post_rv": "5 trading-return std * sqrt(252), starting one trading day after t0",
            "t0": "first trading day >= HURDAT2 first-landfall date",
        },
        "universe": {
            "outcome_stocks": STOCKS,
            "reinsurer_stocks": REINSURERS,
            "sanity_baseline": "KIE",
            "controls": ["VIX_t-1", "SPY_RV21_t-1"],
        },
        "multiple_testing": {
            "method": "Holm-Bonferroni",
            "family": REINSURERS,
            "benchmark_excluded": "KIE",
            "scope_flag": "holm_4_reinsurers_only",
        },
        "n_events_eligible": int(len(storms)),
        "n_events_used": int(len(events_used)),
        "events_used": events_used,
        "regression": reg_results,
        "kie_interaction_test": kie_interaction,
        "identification_check": id_check,
        "rv_diagnostics": diag,
        "success_criteria": {
            "any_reinsurer_beta_pos_holm_p_lt_0p10": bool(any_sig),
            "formal_reinsurer_minus_kie_interaction_pos_p_lt_0p10": bool(identification_pass),
            "n_events_ge_12": bool(len(events_used) >= 12),
            "n_events_ge_20": bool(len(events_used) >= 20),
        },
        "verdict_internal": verdict_internal,
        "reviewer": "Codex primary path — v2 methodological blockers addressed",
    }

    out_path = HERE / "k1589_results.json"
    with open(out_path, "w") as fh:
        json.dump(results, fh, indent=2, default=str)
    print(f"[K1589] wrote {out_path}")
    print(f"[K1589] verdict_internal = {verdict_internal} (subject to Codex review)")
    print(f"        any reinsurer β+ (Holm-4 p<0.10) = {any_sig}")
    print(
        "        KIE interaction βdiff = "
        f"{kie_interaction.get('beta_reinsurer_minus_kie_category')} "
        f"(p={kie_interaction.get('p_reinsurer_minus_kie_category')})"
    )


if __name__ == "__main__":
    main()
