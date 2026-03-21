"""3-year backtest (2023-01-02 to 2026-03-16) for SPY-based strategies.

Replicates backfill_paper_trading.py logic with start date = 2023-01-02.
Only US strategies (4):
  1. slow_vt: GJR-GARCH VT, Hybrid VIX switch when VIX/GARCH > 1.3
  2. risk_parity: SPY+GLD risk parity with GJR+GARCH
  3. simple_12vix: min(12/VIX, 1.0) SPY
  4. recommended_5050: 50/50 SPY/GLD × min(12/VIX, 1.0)

Run: uv run python scripts/backtest_3yr_us.py
"""
import json
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from arch import arch_model

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from volpred.data.manager import DataManager


def fit_garch(returns_pct, p=1, o=0, q=1):
    """Fit GARCH and return 1-step-ahead daily sigma (decimal)."""
    result = arch_model(
        returns_pct, vol="GARCH", p=p, o=o, q=q,
        dist="normal", mean="Zero", rescale=False
    ).fit(disp="off", show_warning=False)
    sigma = float(np.sqrt(result.forecast(horizon=1).variance.iloc[-1, 0]) / 100)
    return sigma


def main():
    print("=== 3-Year US Backtest (2023-01-02 to 2026-03-16) ===")
    print(f"Running at {datetime.now()}")

    dm = DataManager()

    # --- Fetch all data (need 2000 window before 2023-01-02) ---
    print("Fetching data...")
    spy = dm.get_model_data("SPY", "2015-01-01", "2026-12-31")
    gld = dm.get_model_data("GLD", "2015-01-01", "2026-12-31")
    vix = dm.get_model_data("^VIX", "2015-01-01", "2026-12-31")

    print(f"  SPY: {spy.index[0].date()} to {spy.index[-1].date()} ({len(spy)} rows)")
    print(f"  GLD: {gld.index[0].date()} to {gld.index[-1].date()} ({len(gld)} rows)")
    print(f"  VIX: {vix.index[0].date()} to {vix.index[-1].date()} ({len(vix)} rows)")

    # Build VIX lookup (date -> close)
    vix_lookup = {}
    for dt, row in vix.iterrows():
        vix_lookup[dt.date()] = float(row["close"])

    # Determine backtest date range
    backtest_start = pd.Timestamp("2023-01-02")
    backtest_end = pd.Timestamp("2026-03-16")
    spy_dates = spy.index[(spy.index >= backtest_start) & (spy.index <= backtest_end)]

    if len(spy_dates) == 0:
        print("No SPY data in range. Exiting.")
        return

    print(f"  Backtest range: {spy_dates[0].date()} to {spy_dates[-1].date()} ({len(spy_dates)} trading days)")

    spy_full_idx = list(spy.index)
    target_daily = 0.12 / np.sqrt(252)
    WINDOW = 2000

    # Initialize strategy results
    strategies = {
        "slow_vt": {"initial_capital": 1000000, "entries": []},
        "risk_parity": {"initial_capital": 1000000, "entries": []},
        "simple_12vix": {"initial_capital": 1000000, "entries": []},
        "recommended_5050": {"initial_capital": 1000000, "entries": []},
    }

    total_days = len(spy_dates)
    for i, data_date_ts in enumerate(spy_dates):
        data_date = data_date_ts.date()

        # Find position in full SPY index
        spy_pos = spy_full_idx.index(data_date_ts)
        if spy_pos < WINDOW:
            print(f"  Skipping {data_date}: insufficient window ({spy_pos} < {WINDOW})")
            continue

        # Extract training windows
        spy_train = spy.iloc[spy_pos - WINDOW + 1: spy_pos + 1]["returns"].values * 100

        # For GLD, find available data up to data_date
        gld_mask = gld.index <= data_date_ts
        gld_available = gld[gld_mask]
        if len(gld_available) < WINDOW:
            print(f"  Skipping {data_date}: insufficient GLD window ({len(gld_available)} < {WINDOW})")
            continue
        gld_train = gld_available.iloc[-WINDOW:]["returns"].values * 100

        # Fit GARCH models
        try:
            sigma_gjr = fit_garch(spy_train, p=1, o=1, q=1)  # GJR-GARCH
            sigma_garch = fit_garch(spy_train, p=1, o=0, q=1)  # Standard GARCH
            sigma_gld = fit_garch(gld_train, p=1, o=0, q=1)   # GLD GARCH
        except Exception as e:
            print(f"  Error fitting GARCH on {data_date}: {e}")
            continue

        sigma_gjr_ann = round(sigma_gjr * np.sqrt(252) * 100, 1)
        sigma_gld_ann = round(sigma_gld * np.sqrt(252) * 100, 1)
        sigma_floor = max(sigma_gjr, 0.9 * sigma_garch)

        spy_close = round(float(spy.iloc[spy_pos]["close"]), 2)
        gld_close_val = round(float(gld_available.iloc[-1]["close"]), 2)

        # VIX for this date
        vix_level = vix_lookup.get(data_date, None)

        # Compute VIX/GARCH ratio
        vix_garch_ratio = None
        if vix_level is not None and sigma_gjr_ann > 0:
            vix_garch_ratio = round(vix_level / sigma_gjr_ann, 2)

        # --- Strategy 1: Slow VT ---
        if vix_level is not None and vix_garch_ratio is not None and vix_garch_ratio > 1.3:
            vix_sigma_daily = vix_level / 100 / np.sqrt(252)
            w_spy_only = round(min(max(target_daily / vix_sigma_daily, 0), 2.0), 2)
        else:
            w_spy_only = round(min(max(target_daily / sigma_floor, 0), 2.0), 2)
        cash_spy_only = round(max(0, 1 - w_spy_only), 2)

        # --- Strategy 2: Risk Parity ---
        inv_s = 1 / sigma_gjr + 1 / sigma_gld
        rp_spy = (1 / sigma_gjr) / inv_s
        rp_gld = (1 / sigma_gld) / inv_s
        port_sigma = np.sqrt((rp_spy * sigma_gjr) ** 2 + (rp_gld * sigma_gld) ** 2)
        scale = target_daily / port_sigma
        w_rp_spy = round(min(rp_spy * scale, 2.0), 2)
        w_rp_gld = round(min(rp_gld * scale, 2.0), 2)
        w_rp_cash = round(max(0, 1 - w_rp_spy - w_rp_gld), 2)

        # --- Strategy 3: 12/VIX Simple ---
        if vix_level is not None:
            w_12vix = round(min(12.0 / vix_level, 1.0), 2)
        else:
            w_12vix = w_spy_only  # fallback
        cash_12vix = round(1 - w_12vix, 2)

        # --- Strategy 4: 50/50 SPY/GLD 12/VIX ---
        if vix_level is not None:
            w_5050 = round(min(12.0 / vix_level, 1.0), 2)
            w_5050_spy = round(0.5 * w_5050, 2)
            w_5050_gld = round(0.5 * w_5050, 2)
            w_5050_cash = round(max(0, 1 - w_5050_spy - w_5050_gld), 2)
        else:
            w_5050_spy = round(0.5 * w_spy_only, 2)
            w_5050_gld = round(0.5 * w_spy_only, 2)
            w_5050_cash = round(max(0, 1 - w_5050_spy - w_5050_gld), 2)

        # --- Compute next-day actual returns ---
        next_spy_ret = None
        next_gld_ret = None

        if spy_pos + 1 < len(spy):
            next_spy_ret = round(float(spy.iloc[spy_pos + 1]["simple_return"]), 6)

        gld_after = gld[gld.index > data_date_ts]
        if len(gld_after) > 0:
            next_gld_ret = round(float(gld_after.iloc[0]["simple_return"]), 6)

        # Date strings
        date_str = str(data_date)
        if spy_pos + 1 < len(spy):
            next_date_str = str(spy.iloc[spy_pos + 1].name.date())
        else:
            next_date_str = date_str

        common = {
            "spy_close": spy_close,
            "gld_close": gld_close_val,
            "sigma_spy_ann": sigma_gjr_ann,
            "sigma_gld_ann": sigma_gld_ann,
        }

        # Strategy 1: slow_vt
        if next_spy_ret is not None:
            port_ret_slow = round(w_spy_only * next_spy_ret, 6)
            actual_rets_slow = {"SPY": next_spy_ret}
        else:
            port_ret_slow = None
            actual_rets_slow = None
        strategies["slow_vt"]["entries"].append({
            "date": next_date_str,
            "data_date": date_str,
            "weights": {"SPY": w_spy_only},
            "cash_weight": cash_spy_only,
            **common,
            "actual_returns": actual_rets_slow,
            "portfolio_return": port_ret_slow,
        })

        # Strategy 2: risk_parity
        if next_spy_ret is not None and next_gld_ret is not None:
            port_ret_rp = round(w_rp_spy * next_spy_ret + w_rp_gld * next_gld_ret, 6)
            actual_rets_rp = {"SPY": next_spy_ret, "GLD": next_gld_ret}
        else:
            port_ret_rp = None
            actual_rets_rp = None
        strategies["risk_parity"]["entries"].append({
            "date": next_date_str,
            "data_date": date_str,
            "weights": {"SPY": w_rp_spy, "GLD": w_rp_gld},
            "cash_weight": w_rp_cash,
            **common,
            "actual_returns": actual_rets_rp,
            "portfolio_return": port_ret_rp,
        })

        # Strategy 3: simple_12vix
        if next_spy_ret is not None:
            port_ret_12vix = round(w_12vix * next_spy_ret, 6)
            actual_rets_12vix = {"SPY": next_spy_ret}
        else:
            port_ret_12vix = None
            actual_rets_12vix = None
        strategies["simple_12vix"]["entries"].append({
            "date": next_date_str,
            "data_date": date_str,
            "weights": {"SPY": w_12vix},
            "cash_weight": cash_12vix,
            **common,
            "actual_returns": actual_rets_12vix,
            "portfolio_return": port_ret_12vix,
        })

        # Strategy 4: recommended_5050
        if next_spy_ret is not None and next_gld_ret is not None:
            port_ret_5050 = round(w_5050_spy * next_spy_ret + w_5050_gld * next_gld_ret, 6)
            actual_rets_5050 = {"SPY": next_spy_ret, "GLD": next_gld_ret}
        else:
            port_ret_5050 = None
            actual_rets_5050 = None
        strategies["recommended_5050"]["entries"].append({
            "date": next_date_str,
            "data_date": date_str,
            "weights": {"SPY": w_5050_spy, "GLD": w_5050_gld},
            "cash_weight": w_5050_cash,
            **common,
            "actual_returns": actual_rets_5050,
            "portfolio_return": port_ret_5050,
        })

        # Progress
        if (i + 1) % 50 == 0 or i == total_days - 1:
            print(f"  [{i+1}/{total_days}] {date_str} | VIX={vix_level} | σ_SPY={sigma_gjr_ann}% | σ_GLD={sigma_gld_ann}%")

    # --- Output ---
    output_path = Path("storage/paper_trading_3yr_us.json")
    output_path.write_text(json.dumps(strategies, indent=2, ensure_ascii=False))

    # --- Performance Summary ---
    print(f"\n{'='*70}")
    print(f"{'Strategy':<25} {'CumRet':>10} {'Ann.Sharpe':>12} {'MaxDD':>10} {'Days':>6}")
    print(f"{'='*70}")

    # Also compute buy-and-hold SPY for comparison
    spy_bh_entries = []
    for strat_id, strat in strategies.items():
        entries = strat["entries"]
        filled = [e for e in entries if e["portfolio_return"] is not None]
        if not filled:
            print(f"  {strat_id}: 0 entries with returns")
            continue

        rets = np.array([e["portfolio_return"] for e in filled])
        cum_ret = np.prod(1 + rets) - 1
        ann_ret = (1 + cum_ret) ** (252 / len(rets)) - 1
        ann_std = np.std(rets) * np.sqrt(252)
        sharpe = ann_ret / ann_std if ann_std > 0 else 0

        # Max drawdown
        cumulative = np.cumprod(1 + rets)
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = cumulative / running_max - 1
        max_dd = np.min(drawdowns)

        print(f"  {strat_id:<23} {cum_ret*100:>+9.2f}% {sharpe:>11.2f} {max_dd*100:>+9.2f}% {len(filled):>5}")

        # Collect SPY returns for buy-and-hold comparison
        if strat_id == "simple_12vix":
            spy_bh_rets = np.array([e["actual_returns"]["SPY"] for e in filled if e.get("actual_returns") and "SPY" in e["actual_returns"]])

    # Buy-and-hold SPY benchmark
    if len(spy_bh_rets) > 0:
        cum_ret_bh = np.prod(1 + spy_bh_rets) - 1
        ann_ret_bh = (1 + cum_ret_bh) ** (252 / len(spy_bh_rets)) - 1
        ann_std_bh = np.std(spy_bh_rets) * np.sqrt(252)
        sharpe_bh = ann_ret_bh / ann_std_bh if ann_std_bh > 0 else 0
        cumulative_bh = np.cumprod(1 + spy_bh_rets)
        running_max_bh = np.maximum.accumulate(cumulative_bh)
        drawdowns_bh = cumulative_bh / running_max_bh - 1
        max_dd_bh = np.min(drawdowns_bh)
        print(f"  {'SPY Buy&Hold':<23} {cum_ret_bh*100:>+9.2f}% {sharpe_bh:>11.2f} {max_dd_bh*100:>+9.2f}% {len(spy_bh_rets):>5}")

    print(f"{'='*70}")
    print(f"\nOutput: {output_path.resolve()}")
    print("Done!")


if __name__ == "__main__":
    main()
