"""3-year backtest for 6 strategies + Buy & Hold benchmark.

Period: 2023-01-02 to 2026-03-16
GARCH uses weekly refit (every 5 trading days) for speed.

Run: uv run python scripts/backtest_3yr_final.py
"""
import json
import sys
import warnings
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
from arch import arch_model

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from volpred.data.manager import DataManager

# ── Config ──────────────────────────────────────────────────
BACKTEST_START = "2023-01-02"
BACKTEST_END = "2026-03-16"
GARCH_WINDOW = 2000
TARGET_ANNUAL = 0.12
TARGET_DAILY = TARGET_ANNUAL / np.sqrt(252)
REFIT_EVERY = 5  # weekly refit for GARCH strategies

STORAGE = Path(__file__).parent.parent / "storage"


# ── GARCH fitting ───────────────────────────────────────────
def fit_garch_sigma(returns_pct, vol_type="GARCH", p=1, o=0, q=1):
    """Fit GARCH and return daily sigma (as decimal, not %)."""
    try:
        res = arch_model(
            returns_pct, vol=vol_type, p=p, o=o, q=q,
            dist="normal", mean="Zero", rescale=False
        ).fit(disp="off", show_warning=False)
        sigma = float(np.sqrt(res.forecast(horizon=1).variance.iloc[-1, 0]) / 100)
        return sigma
    except Exception:
        return None


# ── Metrics ─────────────────────────────────────────────────
def compute_metrics(daily_returns: np.ndarray, strategy_name: str) -> dict:
    """Compute comprehensive performance metrics."""
    n = len(daily_returns)
    trading_days_per_year = 252

    # Cumulative
    cumulative = np.prod(1 + daily_returns) - 1
    years = n / trading_days_per_year
    ann_return = (1 + cumulative) ** (1 / years) - 1 if years > 0 else 0

    # Volatility
    ann_vol = np.std(daily_returns, ddof=1) * np.sqrt(trading_days_per_year)

    # Sharpe (excess return over 0 since cash weight handles risk-free)
    sharpe = ann_return / ann_vol if ann_vol > 0 else 0

    # Sortino
    downside = daily_returns[daily_returns < 0]
    downside_vol = np.std(downside, ddof=1) * np.sqrt(trading_days_per_year) if len(downside) > 0 else 1e-9
    sortino = ann_return / downside_vol

    # Win rate
    win_rate = np.mean(daily_returns > 0) * 100

    # Max drawdown
    cum_series = np.cumprod(1 + daily_returns)
    running_max = np.maximum.accumulate(cum_series)
    drawdowns = cum_series / running_max - 1
    max_dd = np.min(drawdowns)

    # Calmar
    calmar = ann_return / abs(max_dd) if abs(max_dd) > 1e-9 else 0

    # Max drawdown duration (in trading days)
    in_dd = cum_series < running_max
    dd_groups = []
    current_len = 0
    for x in in_dd:
        if x:
            current_len += 1
        else:
            if current_len > 0:
                dd_groups.append(current_len)
            current_len = 0
    if current_len > 0:
        dd_groups.append(current_len)
    max_dd_days = max(dd_groups) if dd_groups else 0

    # VaR / CVaR (95%)
    sorted_rets = np.sort(daily_returns)
    var_idx = int(np.floor(0.05 * n))
    var_95 = sorted_rets[var_idx] if var_idx < n else sorted_rets[0]
    cvar_95 = np.mean(sorted_rets[:max(var_idx, 1)])

    best_day = np.max(daily_returns)
    worst_day = np.min(daily_returns)

    return {
        "display_name": strategy_name,
        "cumulative_return": round(cumulative * 100, 2),
        "annualized_return": round(ann_return * 100, 2),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "max_drawdown": round(max_dd * 100, 2),
        "annualized_vol": round(ann_vol * 100, 2),
        "calmar": round(calmar, 2),
        "win_rate": round(win_rate, 1),
        "var_95": round(var_95 * 100, 2),
        "cvar_95": round(cvar_95 * 100, 2),
        "max_drawdown_days": max_dd_days,
        "best_day": round(best_day * 100, 2),
        "worst_day": round(worst_day * 100, 2),
        "trading_days": n,
    }


def main():
    print("=" * 70)
    print("3-Year Backtest: 2023-01-02 → 2026-03-16")
    print("GARCH refit: every 5 trading days (weekly approximation)")
    print("=" * 70)

    dm = DataManager()

    # ── Fetch data ──────────────────────────────────────────
    print("\nLoading data...")
    spy_full = dm.get_model_data("SPY", "2015-01-01", "2026-12-31")
    gld_full = dm.get_model_data("GLD", "2015-01-01", "2026-12-31")
    vix_full = dm.get_model_data("^VIX", "2022-01-01", "2026-12-31")
    tw50_full = dm.get_model_data("0050.TW", "2022-01-01", "2026-12-31")

    # Build date arrays for backtest period
    bt_start = pd.Timestamp(BACKTEST_START)
    bt_end = pd.Timestamp(BACKTEST_END)

    # US trading dates in backtest period (based on SPY)
    us_dates = spy_full.loc[bt_start:bt_end].index
    # TW trading dates
    tw_dates = tw50_full.loc[bt_start:bt_end].index
    tw_dates_set = set(tw_dates)

    print(f"  US trading days: {len(us_dates)} ({us_dates[0].date()} to {us_dates[-1].date()})")
    print(f"  TW trading days: {len(tw_dates)} ({tw_dates[0].date()} to {tw_dates[-1].date()})")

    # ── Pre-compute GARCH sigmas (weekly refit) ─────────────
    print("\nFitting GARCH models (weekly refit)...")
    sigma_gjr_cache = {}
    sigma_garch_cache = {}
    sigma_gld_cache = {}
    last_gjr = None
    last_garch = None
    last_gld = None

    for i, date in enumerate(us_dates):
        if i % REFIT_EVERY == 0:
            # Get training window
            date_loc = spy_full.index.get_loc(date)
            if date_loc < GARCH_WINDOW:
                start_loc = 0
            else:
                start_loc = date_loc - GARCH_WINDOW

            spy_train = spy_full.iloc[start_loc:date_loc + 1]["returns"].values * 100
            gld_loc = gld_full.index.get_loc(date)
            gld_start = max(0, gld_loc - GARCH_WINDOW)
            gld_train = gld_full.iloc[gld_start:gld_loc + 1]["returns"].values * 100

            gjr = fit_garch_sigma(spy_train, "GARCH", p=1, o=1, q=1)
            garch = fit_garch_sigma(spy_train, "GARCH", p=1, o=0, q=1)
            gld_s = fit_garch_sigma(gld_train, "GARCH", p=1, o=0, q=1)

            if gjr is not None:
                last_gjr = gjr
            if garch is not None:
                last_garch = garch
            if gld_s is not None:
                last_gld = gld_s

            if (i // REFIT_EVERY) % 20 == 0:
                print(f"  Refit {i // REFIT_EVERY + 1}: date={date.date()}, σ_gjr={last_gjr*np.sqrt(252)*100:.1f}%")

        sigma_gjr_cache[date] = last_gjr
        sigma_garch_cache[date] = last_garch
        sigma_gld_cache[date] = last_gld

    print(f"  Total refits: {len(us_dates) // REFIT_EVERY + 1}")

    # ── Helper: find next TW trading day strictly after a US date ──
    tw_dates_sorted = sorted(tw_dates_set)

    def next_tw_day_after(us_date):
        """Find next TW trading day with date > us_date."""
        for td in tw_dates_sorted:
            if td > us_date:
                return td
        return None

    # ── Strategy computations ───────────────────────────────
    # We iterate over US dates. For each date[t], we compute weights.
    # Then the return is from date[t+1] (US) or next TW day after date[t] (TW).

    results = {
        "slow_vt": [],
        "risk_parity": [],
        "simple_12vix": [],
        "recommended_5050": [],
        "taiwan_8.63vix": [],
        "taiwan_spy_momentum": [],
        "benchmark_spy_bh": [],
    }

    # Paper trading entries
    paper_trading = {}
    for key in results:
        paper_trading[key] = {"entries": [], "initial_capital": 1000000}

    print("\nRunning backtest...")

    for i in range(len(us_dates) - 1):
        date_t = us_dates[i]
        date_t1 = us_dates[i + 1]  # next US trading day

        # Get data values
        vix_level = float(vix_full.loc[date_t, "close"]) if date_t in vix_full.index else None
        spy_ret_t1 = float(spy_full.loc[date_t1, "simple_return"])
        gld_ret_t1 = float(gld_full.loc[date_t1, "simple_return"])

        sigma_gjr = sigma_gjr_cache.get(date_t)
        sigma_garch = sigma_garch_cache.get(date_t)
        sigma_gld = sigma_gld_cache.get(date_t)

        if sigma_gjr is None or sigma_garch is None or sigma_gld is None:
            continue

        sigma_gjr_ann = sigma_gjr * np.sqrt(252) * 100

        # ── Strategy 1: GARCH VT (SPY) ──
        sigma_floor = max(sigma_gjr, 0.9 * sigma_garch)
        if vix_level is not None:
            vix_garch_ratio = vix_level / sigma_gjr_ann
            if vix_garch_ratio > 1.3:
                # Hybrid: use VIX-implied vol
                vix_sigma_daily = vix_level / 100 / np.sqrt(252)
                w_spy_vt = min(max(TARGET_DAILY / vix_sigma_daily, 0), 2.0)
            else:
                w_spy_vt = min(max(TARGET_DAILY / sigma_floor, 0), 2.0)
        else:
            w_spy_vt = min(max(TARGET_DAILY / sigma_floor, 0), 2.0)

        port_ret_vt = w_spy_vt * spy_ret_t1
        results["slow_vt"].append({"date": date_t1, "return": port_ret_vt, "weight_spy": w_spy_vt})

        # ── Strategy 2: Risk Parity (SPY + GLD) ──
        inv_s = 1 / sigma_gjr + 1 / sigma_gld
        rp_spy = (1 / sigma_gjr) / inv_s
        rp_gld = (1 / sigma_gld) / inv_s
        port_sigma = np.sqrt((rp_spy * sigma_gjr) ** 2 + (rp_gld * sigma_gld) ** 2)
        scale = TARGET_DAILY / port_sigma
        w_rp_spy = min(rp_spy * scale, 2.0)
        w_rp_gld = min(rp_gld * scale, 2.0)
        port_ret_rp = w_rp_spy * spy_ret_t1 + w_rp_gld * gld_ret_t1
        results["risk_parity"].append({
            "date": date_t1, "return": port_ret_rp,
            "weight_spy": w_rp_spy, "weight_gld": w_rp_gld
        })

        # ── Strategy 3: 12/VIX (SPY) ──
        if vix_level is not None:
            w_12vix = min(12.0 / vix_level, 1.0)
        else:
            w_12vix = min(max(TARGET_DAILY / sigma_floor, 0), 1.0)
        port_ret_12vix = w_12vix * spy_ret_t1
        results["simple_12vix"].append({"date": date_t1, "return": port_ret_12vix, "weight_spy": w_12vix})

        # ── Strategy 4: 50/50 SPY/GLD 12/VIX ──
        if vix_level is not None:
            w_5050 = min(12.0 / vix_level, 1.0)
        else:
            w_5050 = w_12vix
        w_5050_spy = 0.5 * w_5050
        w_5050_gld = 0.5 * w_5050
        port_ret_5050 = w_5050_spy * spy_ret_t1 + w_5050_gld * gld_ret_t1
        results["recommended_5050"].append({
            "date": date_t1, "return": port_ret_5050,
            "weight_spy": w_5050_spy, "weight_gld": w_5050_gld
        })

        # ── Strategy 5: Taiwan 8.63/VIX (0050.TW) ──
        # VIX[date_t] → next TW trading day AFTER date_t
        if vix_level is not None:
            w_tw = min(8.63 / vix_level, 1.0)
            next_tw = next_tw_day_after(date_t)
            if next_tw is not None and next_tw in tw50_full.index:
                tw_ret = float(tw50_full.loc[next_tw, "simple_return"])
                port_ret_tw = w_tw * tw_ret
                results["taiwan_8.63vix"].append({
                    "date": next_tw, "return": port_ret_tw,
                    "weight_tw": w_tw, "data_date": date_t
                })

        # ── Strategy 6: Taiwan SPY Momentum (0050.TW) ──
        # SPY past 10d average return > 0 → 100% 0050, else 0%
        spy_loc = spy_full.index.get_loc(date_t)
        if spy_loc >= 10:
            spy_10d_avg = float(spy_full.iloc[spy_loc - 9:spy_loc + 1]["simple_return"].mean())
            w_tw_mom = 1.0 if spy_10d_avg > 0 else 0.0
            next_tw = next_tw_day_after(date_t)
            if next_tw is not None and next_tw in tw50_full.index:
                tw_ret = float(tw50_full.loc[next_tw, "simple_return"])
                port_ret_tw_mom = w_tw_mom * tw_ret
                results["taiwan_spy_momentum"].append({
                    "date": next_tw, "return": port_ret_tw_mom,
                    "weight_tw": w_tw_mom, "data_date": date_t
                })

        # ── Benchmark: Buy & Hold SPY ──
        results["benchmark_spy_bh"].append({"date": date_t1, "return": spy_ret_t1})

        if (i + 1) % 100 == 0:
            print(f"  Processed {i + 1}/{len(us_dates) - 1} days")

    print(f"  Done. {len(us_dates) - 1} signal days processed.")

    # ── De-duplicate Taiwan strategies (same TW date may appear multiple times) ──
    for tw_key in ["taiwan_8.63vix", "taiwan_spy_momentum"]:
        seen = {}
        deduped = []
        for entry in results[tw_key]:
            d = entry["date"]
            if d not in seen:
                seen[d] = True
                deduped.append(entry)
        results[tw_key] = deduped

    # ── Compute metrics ─────────────────────────────────────
    display_names = {
        "slow_vt": "GARCH VT (SPY)",
        "risk_parity": "Risk Parity (SPY+GLD)",
        "simple_12vix": "12/VIX (SPY)",
        "recommended_5050": "50/50 SPY/GLD",
        "taiwan_8.63vix": "台灣 VT (0050.TW)",
        "taiwan_spy_momentum": "台股動量 (0050.TW)",
        "benchmark_spy_bh": "Buy & Hold SPY",
    }

    metrics = {}
    for key, entries in results.items():
        if not entries:
            continue
        rets = np.array([e["return"] for e in entries])
        m = compute_metrics(rets, display_names[key])
        metrics[key] = m

    # ── Build paper_trading entries ─────────────────────────
    for key, entries in results.items():
        if key == "benchmark_spy_bh":
            continue
        pt_entries = []
        for e in entries:
            pt_entry = {
                "data_date": str(e.get("data_date", e["date"]).date()) if hasattr(e.get("data_date", e["date"]), "date") else str(e.get("data_date", e["date"])),
                "trade_date": str(e["date"].date()) if hasattr(e["date"], "date") else str(e["date"]),
                "weights": {},
                "portfolio_return": round(e["return"], 6),
            }
            if "weight_spy" in e:
                pt_entry["weights"]["SPY"] = round(e["weight_spy"], 4)
            if "weight_gld" in e:
                pt_entry["weights"]["GLD"] = round(e["weight_gld"], 4)
            if "weight_tw" in e:
                pt_entry["weights"]["0050.TW"] = round(e["weight_tw"], 4)
            pt_entry["cash_weight"] = round(max(0, 1 - sum(pt_entry["weights"].values())), 4)
            pt_entries.append(pt_entry)
        paper_trading[key] = {
            "entries": pt_entries,
            "initial_capital": 1000000,
            "stats": metrics.get(key, {}),
        }

    # Add benchmark
    bh_entries = results["benchmark_spy_bh"]
    paper_trading["benchmark_spy_bh"] = {
        "description": "Buy & Hold SPY (100% invested)",
        "stats": metrics.get("benchmark_spy_bh", {}),
        "entries": [
            {
                "trade_date": str(e["date"].date()) if hasattr(e["date"], "date") else str(e["date"]),
                "portfolio_return": round(e["return"], 6),
            }
            for e in bh_entries
        ],
    }

    # ── Save paper_trading_3yr_final.json ───────────────────
    pt_path = STORAGE / "paper_trading_3yr_final.json"
    pt_path.write_text(json.dumps(paper_trading, indent=2, ensure_ascii=False, default=str))
    print(f"\nSaved: {pt_path}")

    # ── Save strategy_metrics.json ──────────────────────────
    sm_path = STORAGE / "strategy_metrics.json"
    sm_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(f"Saved: {sm_path}")

    # ── Print results table ─────────────────────────────────
    print("\n" + "=" * 110)
    print("PERFORMANCE SUMMARY: 2023-01-02 → 2026-03-16")
    print("=" * 110)

    # Return metrics table
    header_ret = f"{'Strategy':<25} {'CumRet%':>8} {'AnnRet%':>8} {'Sharpe':>7} {'Sortino':>8} {'WinRate%':>9} {'BestDay%':>9} {'WorstDay%':>10}"
    print("\n── 報酬類指標 ──")
    print(header_ret)
    print("-" * 110)
    order = ["slow_vt", "risk_parity", "simple_12vix", "recommended_5050",
             "taiwan_8.63vix", "taiwan_spy_momentum", "benchmark_spy_bh"]
    for key in order:
        if key not in metrics:
            continue
        m = metrics[key]
        print(f"{m['display_name']:<25} {m['cumulative_return']:>8.2f} {m['annualized_return']:>8.2f} "
              f"{m['sharpe']:>7.2f} {m['sortino']:>8.2f} {m['win_rate']:>9.1f} "
              f"{m['best_day']:>9.2f} {m['worst_day']:>10.2f}")

    # Risk metrics table
    header_risk = f"{'Strategy':<25} {'MDD%':>8} {'AnnVol%':>8} {'Calmar':>7} {'MDDdays':>8} {'VaR95%':>8} {'CVaR95%':>9}"
    print("\n── 風險類指標 ──")
    print(header_risk)
    print("-" * 110)
    for key in order:
        if key not in metrics:
            continue
        m = metrics[key]
        print(f"{m['display_name']:<25} {m['max_drawdown']:>8.2f} {m['annualized_vol']:>8.2f} "
              f"{m['calmar']:>7.2f} {m['max_drawdown_days']:>8d} "
              f"{m['var_95']:>8.2f} {m['cvar_95']:>9.2f}")

    print("\n" + "=" * 110)
    print("Notes:")
    print("  - GARCH VT uses weekly refit (every 5 days), GJR-GARCH(1,1,1) w=2000")
    print("  - VIX/GARCH > 1.3 → hybrid VIX-based weight for GARCH VT")
    print("  - Taiwan strategies: VIX[t] → next TW trading day after date[t]")
    print("  - All returns use simple returns; weights applied to next-day returns")
    print("  - Sharpe assumes 0% risk-free (cash allocation handles it)")
    print(f"  - Backtest period: {BACKTEST_START} to {BACKTEST_END}")
    print("=" * 110)


if __name__ == "__main__":
    main()
