"""
K1511 — Role-Reversal Months × Taiwan Market PoC
================================================

Hypothesis: Months where institutions (foreign investors) are net sellers
but retail traders (proxied by margin balance change) are net buyers
("institutional_sell_retail_buy") exhibit different next-month 0050 returns
compared with non-reversal months.

Following the EFM 2026 "Who Drives Momentum Returns" US-market spirit but
ported to TAIEX with TWSE free data.

Lag: signal at end of month t, target = 0050 log return in month t+1.
Seed: 42 (for downstream bootstrap).

Author: K1511 PoC, 2026-06-16
"""

from __future__ import annotations

import io
import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf
import matplotlib.pyplot as plt
import statsmodels.api as sm

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SEED = 42
np.random.seed(SEED)

START_YEAR = 2014  # 0050 reliable + TWSE monthly available
END_YEAR = 2026

UA = {"User-Agent": "Mozilla/5.0 (research; K1511 PoC)"}


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

def fetch_monthly_inst_flow() -> pd.DataFrame:
    """三大法人月度買賣金額 → 外資及陸資 (含自營商) 淨買賣金額（元）.

    TWSE BFI82U monthly aggregate. Returns df indexed by month (Period[M]).
    """
    cache = DATA_DIR / "twse_inst_monthly.parquet"
    if cache.exists():
        return pd.read_parquet(cache)

    rows = []
    now = datetime.now()
    for year in range(START_YEAR, END_YEAR + 1):
        for month in range(1, 13):
            # Skip future months
            if (year, month) > (now.year, now.month - 1):
                continue
            ym = f"{year}{month:02d}01"
            url = (
                "https://www.twse.com.tw/rwd/zh/fund/BFI82U"
                f"?response=json&monthDate={ym}&type=month"
            )
            # Retry up to 5 times with exponential backoff for TWSE rate limit
            success = False
            for attempt in range(5):
                try:
                    r = requests.get(url, timeout=30, headers=UA)
                    if r.status_code != 200:
                        time.sleep(2 ** attempt)
                        continue
                    d = r.json()
                except Exception as e:
                    print(f"  inst fetch retry {ym} attempt {attempt+1}: {e}")
                    time.sleep(2 ** attempt)
                    continue
                if d.get("stat") != "OK" or not d.get("data"):
                    time.sleep(2 ** attempt)
                    continue
                # Find 外資 row(s) — combine 外資及陸資 + 外資自營商 if present
                foreign_total = 0.0
                got = False
                for row in d["data"]:
                    name = row[0]
                    if "外資" in name:
                        net = row[3].replace(",", "")
                        try:
                            foreign_total += float(net)
                            got = True
                        except ValueError:
                            pass
                if got:
                    rows.append({"month": f"{year}-{month:02d}", "foreign_net_twd": foreign_total})
                    success = True
                    break
                time.sleep(2 ** attempt)
            if not success:
                print(f"  INST FAIL {ym} after 5 retries")
            time.sleep(1.0)  # be polite to TWSE
        print(f"  inst year {year} done, total rows so far: {len(rows)}")

    df = pd.DataFrame(rows)
    df["month"] = pd.PeriodIndex(df["month"], freq="M")
    df = df.set_index("month").sort_index()
    df.to_parquet(cache)
    return df


def _twse_last_trading_day_margin(year: int, month: int) -> dict | None:
    """Walk last day of month backward to first valid MI_MARGN response."""
    # Last day of month
    if month == 12:
        last = datetime(year + 1, 1, 1)
    else:
        last = datetime(year, month + 1, 1)
    # Walk back day by day until we get OK
    for delta in range(0, 10):
        d = last.toordinal() - 1 - delta
        dt = datetime.fromordinal(d)
        ymd = dt.strftime("%Y%m%d")
        url = (
            "https://www.twse.com.tw/exchangeReport/MI_MARGN"
            f"?date={ymd}&selectType=MS&response=json"
        )
        try:
            r = requests.get(url, timeout=20, headers=UA)
            obj = r.json()
        except Exception:
            time.sleep(0.5)
            continue
        if obj.get("stat") != "OK":
            time.sleep(0.4)
            continue
        if not obj.get("tables"):
            return None
        t = obj["tables"][0]
        fields = t.get("fields", [])
        data = t.get("data", [])
        # Want margin balance (融資) row: 今日餘額 column
        for row in data:
            if "融資" in row[0] and "金額" in row[0]:
                # 今日餘額 is last col typically index 5 or 6
                # fields: 項目, 買進, 賣出, 現金(券)償還, 前日餘額, 今日餘額, ...
                try:
                    bal_str = row[5].replace(",", "")
                    return {
                        "date": ymd,
                        "margin_balance_kntwd": float(bal_str),  # 千元 unit
                    }
                except (ValueError, IndexError):
                    continue
        # fallback: try '融資(交易單位)' for share count; but we want money
        time.sleep(0.4)
    return None


def fetch_monthly_margin_balance() -> pd.DataFrame:
    """Month-end margin balance (融資餘額金額, 千元 NTD)."""
    cache = DATA_DIR / "twse_margin_monthly.parquet"
    if cache.exists():
        return pd.read_parquet(cache)

    rows = []
    for year in range(START_YEAR, END_YEAR + 1):
        for month in range(1, 13):
            # Skip future months
            now = datetime.now()
            if (year, month) > (now.year, now.month - 1):
                continue
            res = _twse_last_trading_day_margin(year, month)
            if res is None:
                continue
            rows.append({
                "month": f"{year}-{month:02d}",
                "margin_balance_kntwd": res["margin_balance_kntwd"],
            })
            time.sleep(0.3)
        print(f"  margin year {year} done, total rows so far: {len(rows)}")

    df = pd.DataFrame(rows)
    df["month"] = pd.PeriodIndex(df["month"], freq="M")
    df = df.set_index("month").sort_index()
    df.to_parquet(cache)
    return df


def fetch_0050_monthly_returns() -> pd.DataFrame:
    """0050.TW monthly log return."""
    cache = DATA_DIR / "tw0050_monthly.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    start = f"{START_YEAR}-01-01"
    end = f"{END_YEAR}-12-31"
    px = yf.download("0050.TW", start=start, end=end, progress=False, auto_adjust=True)
    if px is None or len(px) == 0:
        raise RuntimeError("yfinance 0050.TW empty")
    if isinstance(px.columns, pd.MultiIndex):
        px.columns = [c[0] for c in px.columns]
    px = px[["Close"]].copy()
    px.index = pd.to_datetime(px.index)
    # month-end close
    m = px["Close"].resample("ME").last()
    ret = np.log(m / m.shift(1)).dropna()
    df = pd.DataFrame({"ret_log": ret})
    df.index = pd.PeriodIndex(df.index, freq="M")
    df.index.name = "month"
    df.to_parquet(cache)
    return df


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def build_panel() -> pd.DataFrame:
    inst = fetch_monthly_inst_flow()
    margin = fetch_monthly_margin_balance()
    ret = fetch_0050_monthly_returns()

    df = inst.join(margin, how="inner").join(ret, how="inner")
    # retail proxy: change in margin balance month-over-month
    df["retail_flow"] = df["margin_balance_kntwd"].diff()
    # inst flow already net buy in TWD
    df["inst_sign"] = np.sign(df["foreign_net_twd"])
    df["retail_sign"] = np.sign(df["retail_flow"])
    df["role_reversal"] = (df["inst_sign"] != df["retail_sign"]) & \
                          (df["inst_sign"] != 0) & (df["retail_sign"] != 0)
    df["inst_sell_retail_buy"] = (df["inst_sign"] < 0) & (df["retail_sign"] > 0)
    df["inst_buy_retail_sell"] = (df["inst_sign"] > 0) & (df["retail_sign"] < 0)
    # Forward 1-month return (target)
    df["ret_next"] = df["ret_log"].shift(-1)
    df = df.dropna(subset=["retail_flow", "ret_next"])
    return df


def run_tests(panel: pd.DataFrame) -> dict:
    out = {}
    out["N_total"] = int(len(panel))
    out["sample_start"] = str(panel.index.min())
    out["sample_end"] = str(panel.index.max())

    # Focus: inst_sell_retail_buy
    target = panel["inst_sell_retail_buy"]
    n_focus = int(target.sum())
    n_other = int((~target).sum())
    out["N_inst_sell_retail_buy"] = n_focus
    out["N_other"] = n_other

    ret_focus = panel.loc[target, "ret_next"]
    ret_other = panel.loc[~target, "ret_next"]

    mean_focus = float(ret_focus.mean())
    mean_other = float(ret_other.mean())
    mean_diff_bp = float((mean_focus - mean_other) * 1e4)

    out["mean_focus_bp"] = float(mean_focus * 1e4)
    out["mean_other_bp"] = float(mean_other * 1e4)
    out["mean_diff_bp"] = mean_diff_bp
    out["std_focus_bp"] = float(ret_focus.std() * 1e4)
    out["std_other_bp"] = float(ret_other.std() * 1e4)

    # Welch t-test
    from scipy import stats
    t_stat, p_val = stats.ttest_ind(ret_focus, ret_other, equal_var=False, nan_policy="omit")
    out["t_stat_welch"] = float(t_stat)
    out["p_value_welch"] = float(p_val)

    # Newey-West HAC OLS on dummy
    X = sm.add_constant(target.astype(float))
    y = panel["ret_next"]
    model = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 3})
    beta_bp = float(model.params.iloc[1] * 1e4)
    t_nw = float(model.tvalues.iloc[1])
    p_nw = float(model.pvalues.iloc[1])
    out["beta_NW_bp"] = beta_bp
    out["t_stat_NW"] = t_nw
    out["p_value_NW"] = p_nw

    # Also test the broader role_reversal (any sign mismatch)
    rr = panel["role_reversal"].astype(float)
    Xr = sm.add_constant(rr)
    mr = sm.OLS(y, Xr).fit(cov_type="HAC", cov_kwds={"maxlags": 3})
    out["any_reversal_N"] = int(rr.sum())
    out["any_reversal_beta_bp"] = float(mr.params.iloc[1] * 1e4)
    out["any_reversal_t_NW"] = float(mr.tvalues.iloc[1])
    out["any_reversal_p_NW"] = float(mr.pvalues.iloc[1])

    # Verdict gate
    abs_t = abs(t_nw)
    if abs_t > 1.96 and n_focus >= 24:
        verdict = "PASS_PRELIMINARY"
    elif abs_t > 1.0 or n_focus < 24:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "NULL"
    out["verdict"] = verdict
    out["verdict_rule"] = "PASS_PRELIMINARY if |t_NW|>1.96 AND N_focus>=24; else INCONCLUSIVE/NULL"

    return out


def make_figure(panel: pd.DataFrame, out_path: Path) -> None:
    target = panel["inst_sell_retail_buy"]
    ret_focus = panel.loc[target, "ret_next"] * 100
    ret_other = panel.loc[~target, "ret_next"] * 100

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))

    ax = axes[0]
    ax.hist(ret_other, bins=24, alpha=0.55, label=f"Other months (N={len(ret_other)})",
            color="#4c78a8", density=True)
    ax.hist(ret_focus, bins=18, alpha=0.7,
            label=f"Inst sell × Retail buy (N={len(ret_focus)})",
            color="#e45756", density=True)
    ax.axvline(ret_other.mean(), color="#4c78a8", lw=1.6, ls="--",
               label=f"Other mean={ret_other.mean():.2f}%")
    ax.axvline(ret_focus.mean(), color="#e45756", lw=1.6, ls="--",
               label=f"Focus mean={ret_focus.mean():.2f}%")
    ax.set_xlabel("Next-month 0050 log return (%)")
    ax.set_ylabel("Density")
    ax.set_title("K1511 | Role-Reversal vs Other months: 0050 t+1 return distribution")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.3)

    ax2 = axes[1]
    # Box plot (no need for DataFrame — boxplot takes lists)
    ax2.boxplot([ret_focus.values, ret_other.values],
                tick_labels=["Inst sell × Retail buy", "Other"],
                showmeans=True)
    ax2.set_ylabel("Next-month 0050 log return (%)")
    ax2.set_title("Boxplot")
    ax2.grid(alpha=0.3, axis="y")

    plt.tight_layout()
    plt.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def main():
    print("[K1511] building panel...")
    panel = build_panel()
    panel_out = ROOT / "k1511_panel.parquet"
    panel.to_parquet(panel_out)
    print(f"[K1511] panel: N={len(panel)}, {panel.index.min()} → {panel.index.max()}")

    print("[K1511] running tests...")
    results = run_tests(panel)
    results["generated_at_utc"] = datetime.utcnow().isoformat()
    results["seed"] = SEED
    results["data_sources"] = [
        "TWSE BFI82U monthly aggregate (三大法人月度買賣)",
        "TWSE MI_MARGN month-end last trading day (融資餘額)",
        "yfinance 0050.TW month-end Close",
    ]
    results["lag_protocol"] = "signal at end-of-month t, return = log(Close_t+1 / Close_t)"

    out_json = ROOT / "k1511_results.json"
    out_json.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"[K1511] results written: {out_json}")
    print(json.dumps(results, indent=2, ensure_ascii=False))

    fig_path = ROOT / "fig_a_role_reversal_returns.png"
    make_figure(panel, fig_path)
    print(f"[K1511] figure: {fig_path}")


if __name__ == "__main__":
    main()
