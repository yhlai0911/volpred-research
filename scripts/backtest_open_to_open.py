"""Backtest all 9 strategies using open-to-open returns.

Timeline:
  close(T) -> weight(T) calculated (VIX close, SPY close for momentum, GARCH on close returns)
  open(T+1) -> execute (entry price)
  open(T+2) -> rebalance (exit price)
  return = open(T+2) / open(T+1) - 1

Signals unchanged (still use close data).
Returns changed to open-to-open.

Output: storage/paper_trading_open.json
"""
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from arch import arch_model

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from volpred.data.manager import DataManager


def rolling_garch_sigma(close_returns_pct, window=2000, vol_type="GARCH", p=1, o=0, q=1):
    """Compute rolling GARCH sigma for each day (annualized %).

    Returns a Series indexed same as close_returns_pct, with NaN for the first `window` days.
    """
    n = len(close_returns_pct)
    sigmas = pd.Series(np.nan, index=close_returns_pct.index)

    for i in range(window, n):
        train = close_returns_pct.iloc[i - window:i].values
        try:
            result = arch_model(
                train, vol="GARCH", p=p, o=o, q=q,
                dist="normal", mean="Zero", rescale=False
            ).fit(disp="off", show_warning=False)
            sigma_daily = float(np.sqrt(result.forecast(horizon=1).variance.iloc[-1, 0]) / 100)
            sigma_ann = sigma_daily * np.sqrt(252) * 100
            sigmas.iloc[i] = sigma_ann
        except Exception:
            if i > window:
                sigmas.iloc[i] = sigmas.iloc[i-1]

    return sigmas


def main():
    dm = DataManager()

    # Need data from 2014 to have 2000+ trading days before 2023-01-01
    START = "2014-01-01"
    END = "2026-12-31"
    BACKTEST_START = "2023-01-01"

    print("=== Loading data ===")
    spy = dm.get_model_data("SPY", START, END)
    gld = dm.get_model_data("GLD", START, END)
    vix = dm.get_model_data("^VIX", START, END)
    tw50 = dm.get_model_data("0050.TW", START, END)
    nk225 = dm.get_model_data("^N225", START, END)

    print(f"  SPY: {len(spy)} rows, {spy.index[0].date()} to {spy.index[-1].date()}")
    print(f"  GLD: {len(gld)} rows, {gld.index[0].date()} to {gld.index[-1].date()}")
    print(f"  VIX: {len(vix)} rows, {vix.index[0].date()} to {vix.index[-1].date()}")
    print(f"  0050.TW: {len(tw50)} rows, {tw50.index[0].date()} to {tw50.index[-1].date()}")
    print(f"  ^N225: {len(nk225)} rows, {nk225.index[0].date()} to {nk225.index[-1].date()}")

    # --- Compute open-to-open returns ---
    # open_ret(T) = open(T+1) / open(T) - 1
    spy['open_ret'] = spy['open'].shift(-1) / spy['open'] - 1
    gld['open_ret'] = gld['open'].shift(-1) / gld['open'] - 1
    tw50['open_ret'] = tw50['open'].shift(-1) / tw50['open'] - 1
    nk225['open_ret'] = nk225['open'].shift(-1) / nk225['open'] - 1

    # --- Rolling GARCH on close returns (signals use close data) ---
    print("\n=== Computing rolling GJR-GARCH (w=2000) for SPY... ===")
    spy_ret_pct = spy['returns'] * 100  # log returns in percent
    gld_ret_pct = gld['returns'] * 100

    sigma_spy_gjr = rolling_garch_sigma(spy_ret_pct, window=2000, p=1, o=1, q=1)
    print("  SPY GJR done.")

    sigma_spy_garch = rolling_garch_sigma(spy_ret_pct, window=2000, p=1, o=0, q=1)
    print("  SPY GARCH done.")

    sigma_gld_garch = rolling_garch_sigma(gld_ret_pct, window=2000, p=1, o=0, q=1)
    print("  GLD GARCH done.")

    # --- Load macro data for VIX+leading strategy ---
    # CSV format: item,unit,freq,period,value
    # item = "景氣領先指標綜合指數(點)", period = "1982M01", value = 12.26
    bci_path = Path("storage/macro/tw_dgbas_bci_m.csv")
    bci_monthly_mom = {}  # (year, month) -> MoM value
    if bci_path.exists():
        bci_df = pd.read_csv(bci_path)
        # Filter to leading indicator rows
        lead_mask = bci_df['item'].str.contains('領先', na=False) & bci_df['item'].str.contains('綜合', na=False)
        lead_df = bci_df[lead_mask].copy()
        if len(lead_df) > 0:
            lead_df['val'] = pd.to_numeric(lead_df['value'], errors='coerce')
            lead_df = lead_df.dropna(subset=['val']).sort_values('period')
            lead_df['mom'] = lead_df['val'].diff()
            for _, row in lead_df.iterrows():
                period = str(row['period'])  # e.g. "2023M01"
                if pd.notna(row['mom']) and 'M' in period:
                    parts = period.split('M')
                    try:
                        bci_monthly_mom[(int(parts[0]), int(parts[1]))] = float(row['mom'])
                    except Exception:
                        pass
    print(f"  BCI MoM data: {len(bci_monthly_mom)} months loaded")

    def get_leading_mom(date):
        """Get the latest available leading indicator MoM for a given date."""
        # BCI data is monthly, published with ~2 month lag
        check_date = date - pd.DateOffset(months=2)
        key = (check_date.year, check_date.month)
        if key in bci_monthly_mom:
            return bci_monthly_mom[key]
        # Fallback: try 3 months ago
        check_date2 = date - pd.DateOffset(months=3)
        key2 = (check_date2.year, check_date2.month)
        if key2 in bci_monthly_mom:
            return bci_monthly_mom[key2]
        return 0  # default neutral

    # --- Build backtest dates ---
    backtest_mask = spy.index >= BACKTEST_START
    spy_bt = spy[backtest_mask].copy()

    target_daily = 0.12 / np.sqrt(252)

    # Initialize result dict
    result = {}
    strategies = [
        'slow_vt', 'risk_parity', 'simple_12vix', 'recommended_5050',
        'taiwan_8.63vix', 'taiwan_spy_momentum', 'vix_leading_guard',
        'tz_tw_jp_5050', 'global_vt_tz'
    ]
    for s in strategies:
        result[s] = {"entries": [], "initial_capital": 1000000}

    print("\n=== Running backtest ===")

    dates_done = 0
    for i, (date, row) in enumerate(spy_bt.iterrows()):
        date_str = str(date.date())

        # Need GARCH sigma available
        if date not in sigma_spy_gjr.index or pd.isna(sigma_spy_gjr.loc[date]):
            continue

        sigma_gjr_ann = float(sigma_spy_gjr.loc[date])
        sigma_garch_ann = float(sigma_spy_garch.loc[date]) if date in sigma_spy_garch.index and pd.notna(sigma_spy_garch.loc[date]) else sigma_gjr_ann
        sigma_gld_ann_val = float(sigma_gld_garch.loc[date]) if date in sigma_gld_garch.index and pd.notna(sigma_gld_garch.loc[date]) else np.nan
        if pd.isna(sigma_gld_ann_val):
            continue

        # Daily sigma in decimal
        sigma_gjr_daily = sigma_gjr_ann / 100 / np.sqrt(252)
        sigma_garch_daily = sigma_garch_ann / 100 / np.sqrt(252)
        sigma_gld_daily = sigma_gld_ann_val / 100 / np.sqrt(252)
        sigma_floor = max(sigma_gjr_daily, 0.9 * sigma_garch_daily)

        # VIX close
        vix_close = None
        if date in vix.index:
            vix_close = float(vix.loc[date, 'close'])

        # VIX/GARCH ratio for hybrid switch
        vix_garch_ratio = vix_close / sigma_gjr_ann if vix_close and sigma_gjr_ann > 0 else 0

        # Weight decided at close(T), executed at open(T+1), return = open(T+2)/open(T+1) - 1
        # open_ret at T+1 = open(T+2)/open(T+1) - 1
        # We need the next trading day's open_ret
        idx_pos = spy.index.get_loc(date)
        if idx_pos + 1 >= len(spy):
            continue
        next_date = spy.index[idx_pos + 1]

        spy_open_ret_next = spy.loc[next_date, 'open_ret'] if pd.notna(spy.loc[next_date, 'open_ret']) else None
        gld_open_ret_next = gld.loc[next_date, 'open_ret'] if next_date in gld.index and pd.notna(gld.loc[next_date, 'open_ret']) else None

        if spy_open_ret_next is None:
            continue

        # Taiwan and Japan: find next trading day
        tw_dates_after = tw50.index[tw50.index >= next_date]
        tw50_open_ret_next = None
        tw50_open_next = None
        tw_next = None
        if len(tw_dates_after) > 0:
            tw_next = tw_dates_after[0]
            if pd.notna(tw50.loc[tw_next, 'open_ret']):
                tw50_open_ret_next = float(tw50.loc[tw_next, 'open_ret'])
                tw50_open_next = float(tw50.loc[tw_next, 'open'])

        nk_dates_after = nk225.index[nk225.index >= next_date]
        nk225_open_ret_next = None
        nk225_open_next = None
        nk_next = None
        if len(nk_dates_after) > 0:
            nk_next = nk_dates_after[0]
            if pd.notna(nk225.loc[nk_next, 'open_ret']):
                nk225_open_ret_next = float(nk225.loc[nk_next, 'open_ret'])
                nk225_open_next = float(nk225.loc[nk_next, 'open'])

        spy_open_ret_next = float(spy_open_ret_next)
        spy_open_next = float(spy.loc[next_date, 'open'])
        gld_open_next = float(gld.loc[next_date, 'open']) if next_date in gld.index else None
        if gld_open_ret_next is not None:
            gld_open_ret_next = float(gld_open_ret_next)

        # ========== STRATEGY 1: Slow VT ==========
        if vix_close and vix_garch_ratio > 1.3:
            vix_sigma_daily = vix_close / 100 / np.sqrt(252)
            w_spy_only = round(min(max(target_daily / vix_sigma_daily, 0), 2.0), 4)
        else:
            w_spy_only = round(min(max(target_daily / sigma_floor, 0), 2.0), 4)

        port_ret_slow = w_spy_only * spy_open_ret_next
        entry_slow = {
            "date": date_str,
            "data_date": date_str,
            "weights": {"SPY": round(w_spy_only, 4)},
            "spy_open": round(spy_open_next, 2),
            "sigma_spy_ann": round(sigma_gjr_ann, 1),
            "actual_returns": {"SPY": round(spy_open_ret_next, 6)},
            "portfolio_return": round(port_ret_slow, 6)
        }
        result['slow_vt']['entries'].append(entry_slow)

        # ========== STRATEGY 2: Risk Parity ==========
        if gld_open_ret_next is not None and sigma_gld_daily > 0:
            inv_s = 1 / sigma_gjr_daily + 1 / sigma_gld_daily
            rp_spy = (1 / sigma_gjr_daily) / inv_s
            rp_gld = (1 / sigma_gld_daily) / inv_s
            port_sigma = np.sqrt((rp_spy * sigma_gjr_daily) ** 2 + (rp_gld * sigma_gld_daily) ** 2)
            scale = target_daily / port_sigma
            w_rp_spy = round(min(rp_spy * scale, 2.0), 4)
            w_rp_gld = round(min(rp_gld * scale, 2.0), 4)

            port_ret_rp = w_rp_spy * spy_open_ret_next + w_rp_gld * gld_open_ret_next
            entry_rp = {
                "date": date_str,
                "data_date": date_str,
                "weights": {"SPY": round(w_rp_spy, 4), "GLD": round(w_rp_gld, 4)},
                "spy_open": round(spy_open_next, 2),
                "gld_open": round(gld_open_next, 2) if gld_open_next else None,
                "sigma_spy_ann": round(sigma_gjr_ann, 1),
                "actual_returns": {
                    "SPY": round(spy_open_ret_next, 6),
                    "GLD": round(gld_open_ret_next, 6)
                },
                "portfolio_return": round(port_ret_rp, 6)
            }
            result['risk_parity']['entries'].append(entry_rp)

        # ========== STRATEGY 3: 12/VIX Simple ==========
        if vix_close:
            w_12vix = round(min(12.0 / vix_close, 1.0), 4)
        else:
            w_12vix = w_spy_only

        port_ret_12vix = w_12vix * spy_open_ret_next
        entry_12vix = {
            "date": date_str,
            "data_date": date_str,
            "weights": {"SPY": round(w_12vix, 4)},
            "spy_open": round(spy_open_next, 2),
            "sigma_spy_ann": round(sigma_gjr_ann, 1),
            "vix_close": round(vix_close, 2) if vix_close else None,
            "actual_returns": {"SPY": round(spy_open_ret_next, 6)},
            "portfolio_return": round(port_ret_12vix, 6)
        }
        result['simple_12vix']['entries'].append(entry_12vix)

        # ========== STRATEGY 4: 50/50 SPY/GLD 12/VIX ==========
        if vix_close and gld_open_ret_next is not None:
            w_5050 = round(min(12.0 / vix_close, 1.0), 4)
            w_5050_spy = round(0.5 * w_5050, 4)
            w_5050_gld = round(0.5 * w_5050, 4)

            port_ret_5050 = w_5050_spy * spy_open_ret_next + w_5050_gld * gld_open_ret_next
            entry_5050 = {
                "date": date_str,
                "data_date": date_str,
                "weights": {"SPY": round(w_5050_spy, 4), "GLD": round(w_5050_gld, 4)},
                "spy_open": round(spy_open_next, 2),
                "gld_open": round(gld_open_next, 2) if gld_open_next else None,
                "sigma_spy_ann": round(sigma_gjr_ann, 1),
                "vix_close": round(vix_close, 2) if vix_close else None,
                "actual_returns": {
                    "SPY": round(spy_open_ret_next, 6),
                    "GLD": round(gld_open_ret_next, 6)
                },
                "portfolio_return": round(port_ret_5050, 6)
            }
            result['recommended_5050']['entries'].append(entry_5050)

        # ========== STRATEGY 5: Taiwan 8.63/VIX ==========
        if vix_close and tw50_open_ret_next is not None:
            w_tw50 = round(min(8.63 / vix_close, 1.0), 4)

            port_ret_tw = w_tw50 * tw50_open_ret_next
            entry_tw = {
                "date": date_str,
                "data_date": date_str,
                "weights": {"0050.TW": round(w_tw50, 4)},
                "tw50_open": round(tw50_open_next, 2) if tw50_open_next else None,
                "sigma_spy_ann": round(sigma_gjr_ann, 1),
                "vix_close": round(vix_close, 2) if vix_close else None,
                "actual_returns": {"0050.TW": round(tw50_open_ret_next, 6)},
                "portfolio_return": round(port_ret_tw, 6)
            }
            result['taiwan_8.63vix']['entries'].append(entry_tw)

        # ========== STRATEGY 6: Taiwan SPY Momentum (10d) ==========
        if tw50_open_ret_next is not None:
            spy_idx = spy.index.get_loc(date)
            if spy_idx >= 10:
                spy_10d_mean = float(spy['simple_return'].iloc[spy_idx-9:spy_idx+1].mean())
                spy_10d_signal = 1.0 if spy_10d_mean > 0 else 0.0
                w_tw_mom = spy_10d_signal

                port_ret_mom = w_tw_mom * tw50_open_ret_next
                entry_mom = {
                    "date": date_str,
                    "data_date": date_str,
                    "weights": {"0050.TW": round(w_tw_mom, 4)},
                    "tw50_open": round(tw50_open_next, 2) if tw50_open_next else None,
                    "spy_10d_mean": round(spy_10d_mean, 6),
                    "signal": int(spy_10d_signal),
                    "actual_returns": {"0050.TW": round(tw50_open_ret_next, 6)},
                    "portfolio_return": round(port_ret_mom, 6)
                }
                result['taiwan_spy_momentum']['entries'].append(entry_mom)

        # ========== STRATEGY 7: VIX + Leading Guard ==========
        if vix_close and tw50_open_ret_next is not None:
            leading_mom = get_leading_mom(date)
            k_leading = 10.0 if leading_mom > 0 else 6.0
            w_vix_lead = round(min(k_leading / vix_close, 1.0), 4)

            port_ret_lead = w_vix_lead * tw50_open_ret_next
            entry_lead = {
                "date": date_str,
                "data_date": date_str,
                "weights": {"0050.TW": round(w_vix_lead, 4)},
                "tw50_open": round(tw50_open_next, 2) if tw50_open_next else None,
                "vix_close": round(vix_close, 2) if vix_close else None,
                "k_leading": k_leading,
                "leading_mom": round(leading_mom, 2) if leading_mom else 0,
                "actual_returns": {"0050.TW": round(tw50_open_ret_next, 6)},
                "portfolio_return": round(port_ret_lead, 6)
            }
            result['vix_leading_guard']['entries'].append(entry_lead)

        # ========== STRATEGY 8: TW+JP 50/50 TZ ==========
        if tw50_open_ret_next is not None and nk225_open_ret_next is not None:
            spy_idx = spy.index.get_loc(date)
            if spy_idx >= 10:
                spy_10d_mean_s8 = float(spy['simple_return'].iloc[spy_idx-9:spy_idx+1].mean())
                tw_signal = 1.0 if spy_10d_mean_s8 > 0 else 0.0
                jp_signal = tw_signal  # same signal for both
                w_tw_half = round(0.5 * tw_signal, 4)
                w_jp_half = round(0.5 * jp_signal, 4)

                port_ret_tz = w_tw_half * tw50_open_ret_next + w_jp_half * nk225_open_ret_next
                entry_tz = {
                    "date": date_str,
                    "data_date": date_str,
                    "weights": {"0050.TW": round(w_tw_half, 4), "^N225": round(w_jp_half, 4)},
                    "tw50_open": round(tw50_open_next, 2) if tw50_open_next else None,
                    "nk225_open": round(nk225_open_next, 2) if nk225_open_next else None,
                    "spy_10d_mean": round(spy_10d_mean_s8, 6),
                    "signal": int(tw_signal),
                    "actual_returns": {
                        "0050.TW": round(tw50_open_ret_next, 6),
                        "^N225": round(nk225_open_ret_next, 6)
                    },
                    "portfolio_return": round(port_ret_tz, 6)
                }
                result['tz_tw_jp_5050']['entries'].append(entry_tz)

        # ========== STRATEGY 9: Global VT + TZ ==========
        if vix_close and gld_open_ret_next is not None and tw50_open_ret_next is not None:
            spy_idx = spy.index.get_loc(date)
            if spy_idx >= 10:
                spy_10d_mean_s9 = float(spy['simple_return'].iloc[spy_idx-9:spy_idx+1].mean())
                tw_signal_s9 = 1.0 if spy_10d_mean_s9 > 0 else 0.0

                w_5050_s9 = round(min(12.0 / vix_close, 1.0), 4)
                w_global_spy = round(0.5 * 0.5 * w_5050_s9, 4)
                w_global_gld = round(0.5 * 0.5 * w_5050_s9, 4)
                w_global_tw = round(0.5 * tw_signal_s9, 4)

                port_ret_global = (w_global_spy * spy_open_ret_next +
                                   w_global_gld * gld_open_ret_next +
                                   w_global_tw * tw50_open_ret_next)
                entry_global = {
                    "date": date_str,
                    "data_date": date_str,
                    "weights": {
                        "SPY": round(w_global_spy, 4),
                        "GLD": round(w_global_gld, 4),
                        "0050.TW": round(w_global_tw, 4)
                    },
                    "spy_open": round(spy_open_next, 2),
                    "gld_open": round(gld_open_next, 2) if gld_open_next else None,
                    "tw50_open": round(tw50_open_next, 2) if tw50_open_next else None,
                    "sigma_spy_ann": round(sigma_gjr_ann, 1),
                    "vix_close": round(vix_close, 2) if vix_close else None,
                    "spy_10d_mean": round(spy_10d_mean_s9, 6),
                    "actual_returns": {
                        "SPY": round(spy_open_ret_next, 6),
                        "GLD": round(gld_open_ret_next, 6),
                        "0050.TW": round(tw50_open_ret_next, 6)
                    },
                    "portfolio_return": round(port_ret_global, 6)
                }
                result['global_vt_tz']['entries'].append(entry_global)

        dates_done += 1
        if dates_done % 100 == 0:
            print(f"  Processed {dates_done} dates (current: {date_str})")

    print(f"\n  Total dates processed: {dates_done}")

    # --- Save ---
    out_path = Path("storage/paper_trading_open.json")
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\n  Saved to {out_path}")

    # --- Summary Statistics ---
    print("\n" + "=" * 70)
    print(f"{'Strategy':<25} {'Entries':>8} {'Sharpe':>8} {'Ann Ret':>10} {'Ann Vol':>10} {'MDD':>8}")
    print("=" * 70)

    for strat_name in strategies:
        entries = result[strat_name]['entries']
        n = len(entries)
        if n == 0:
            print(f"{strat_name:<25} {0:>8}")
            continue

        rets = np.array([e['portfolio_return'] for e in entries if e['portfolio_return'] is not None])
        if len(rets) == 0:
            print(f"{strat_name:<25} {n:>8} {'N/A':>8}")
            continue

        ann_ret = float(np.mean(rets) * 252 * 100)
        ann_vol = float(np.std(rets, ddof=1) * np.sqrt(252) * 100)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

        # MDD
        cum = np.cumprod(1 + rets)
        peak = np.maximum.accumulate(cum)
        dd = (cum - peak) / peak
        mdd = float(np.min(dd) * 100)

        print(f"{strat_name:<25} {n:>8} {sharpe:>8.2f} {ann_ret:>9.1f}% {ann_vol:>9.1f}% {mdd:>7.1f}%")

    print("=" * 70)

    # Also compute buy-and-hold benchmarks with open-to-open returns
    print("\n--- Benchmarks (Buy & Hold, open-to-open) ---")
    for name, df in [("SPY", spy), ("GLD", gld), ("0050.TW", tw50), ("^N225", nk225)]:
        bt_mask = (df.index >= BACKTEST_START) & pd.notna(df['open_ret'])
        rets = df.loc[bt_mask, 'open_ret'].values
        if len(rets) > 0:
            ann_ret = float(np.mean(rets) * 252 * 100)
            ann_vol = float(np.std(rets, ddof=1) * np.sqrt(252) * 100)
            sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
            cum = np.cumprod(1 + rets)
            peak = np.maximum.accumulate(cum)
            dd = (cum - peak) / peak
            mdd = float(np.min(dd) * 100)
            print(f"  {name:<12} Sharpe={sharpe:.2f}, Ann Ret={ann_ret:.1f}%, Ann Vol={ann_vol:.1f}%, MDD={mdd:.1f}%, N={len(rets)}")


if __name__ == "__main__":
    main()
