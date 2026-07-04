#!/usr/bin/env python3
"""K1631 — Does Taiwan margin-balance new high signal a market top?

Research question:
    網路熱門說法「融資餘額創新高 = 股市要見頂」是否成立？

Design:
    Signal day t uses TWSE market-wide margin financing balance after close.
    Targets start at t+1, never same-day returns.  This is intentionally
    conservative for lookahead control.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
from matplotlib import font_manager
from scipy import stats

from volpred.utils import clean_tw50_data


EXPERIMENT_ID = "k1631"
TITLE = "融資餘額創新高＝股市要見頂？台股日頻實證檢定"
ROOT = Path(__file__).resolve().parents[2]
EXP_DIR = Path(__file__).resolve().parent
DATA_DIR = EXP_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

PRICE_DB = ROOT / "data/cache/price_cache.db"
MARGIN_CACHE = DATA_DIR / "twse_market_margin_daily.csv"
RESULTS_PATH = EXP_DIR / "k1631_results.json"
FIG_EVENTS = EXP_DIR / "fig_margin_balance_high_events.png"
FIG_RETURNS = EXP_DIR / "fig_forward_returns.png"

SEED = 42
START_DATE = "2014-01-01"
HORIZONS = [5, 20, 60]
WARMUP_DAYS = 252
COOLDOWN_DAYS = 20
N_BOOT = 2000
BOOT_BLOCK = 20

UA = {"User-Agent": "Mozilla/5.0 (VolPred research; k1631)"}


def setup_matplotlib_font() -> None:
    candidates = [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/Library/Fonts/NotoSansCJKtc-Regular.otf",
        "/Library/Fonts/Noto Sans CJK TC Regular.otf",
    ]
    for raw in candidates:
        path = Path(raw)
        if path.exists():
            font_manager.fontManager.addfont(str(path))
            prop = font_manager.FontProperties(fname=str(path))
            matplotlib.rcParams["font.sans-serif"] = [prop.get_name()]
            matplotlib.rcParams["axes.unicode_minus"] = False
            return
    raise RuntimeError("No CJK font found for matplotlib.")


def load_tw50_prices() -> pd.DataFrame:
    if not PRICE_DB.exists():
        raise FileNotFoundError(PRICE_DB)
    con = sqlite3.connect(PRICE_DB)
    px = pd.read_sql_query(
        """
        select date, adj_close, close, open, high, low, volume
        from price_data
        where ticker = '0050.TW' and date >= ?
        order by date
        """,
        con,
        params=(START_DATE,),
        parse_dates=["date"],
    )
    if px.empty:
        raise RuntimeError("No 0050.TW rows in local price_cache.db")
    px = px.set_index("date").sort_index()
    clean_price, _ = clean_tw50_data(px["adj_close"].astype(float))
    px["adj_close_clean"] = clean_price
    px["ret_log"] = np.log(px["adj_close_clean"] / px["adj_close_clean"].shift(1))
    return px


def parse_margin_response(date: pd.Timestamp, obj: dict[str, Any]) -> dict[str, Any] | None:
    if obj.get("stat") != "OK" or not obj.get("tables"):
        return None
    table = obj["tables"][0]
    for row in table.get("data", []):
        if row and "融資金額" in str(row[0]):
            try:
                return {
                    "date": date.strftime("%Y-%m-%d"),
                    "margin_buy_kntwd": float(str(row[1]).replace(",", "")),
                    "margin_sell_kntwd": float(str(row[2]).replace(",", "")),
                    "margin_cash_repay_kntwd": float(str(row[3]).replace(",", "")),
                    "prev_balance_kntwd": float(str(row[4]).replace(",", "")),
                    "today_balance_kntwd": float(str(row[5]).replace(",", "")),
                    "twse_report_date": obj.get("date"),
                }
            except (IndexError, ValueError):
                return None
    return None


def fetch_margin_one_day(date: pd.Timestamp, session: requests.Session | None = None) -> dict[str, Any] | None:
    ymd = date.strftime("%Y%m%d")
    url = f"https://www.twse.com.tw/exchangeReport/MI_MARGN?date={ymd}&selectType=MS&response=json"
    client = session or requests
    for attempt in range(3):
        try:
            response = client.get(url, headers=UA, timeout=10)
            if response.status_code != 200:
                time.sleep(0.20 * (attempt + 1))
                continue
            parsed = parse_margin_response(date, response.json())
            if parsed is not None:
                return parsed
        except Exception:
            time.sleep(0.25 * (attempt + 1))
    return None


def fetch_or_load_margin(price_dates: pd.DatetimeIndex) -> pd.DataFrame:
    if MARGIN_CACHE.exists():
        cached = pd.read_csv(MARGIN_CACHE, parse_dates=["date"])
    else:
        cached = pd.DataFrame()

    cached_dates = set()
    if not cached.empty:
        cached_dates = set(cached["date"].dt.strftime("%Y-%m-%d"))

    rows: list[dict[str, Any]] = []
    price_date_list = list(pd.DatetimeIndex(price_dates).sort_values())
    missing = [d for d in price_date_list if d.strftime("%Y-%m-%d") not in cached_dates]
    if missing:
        print(
            f"Fetching TWSE margin rows: {len(missing)} missing of {len(price_date_list)} trading dates",
            flush=True,
        )
    if missing:
        with requests.Session() as session:
            for i, date in enumerate(missing, start=1):
                parsed = fetch_margin_one_day(date, session=session)
                if parsed is not None:
                    rows.append(parsed)
                if i % 50 == 0:
                    print(f"  fetched {i}/{len(missing)} missing dates; new rows={len(rows)}", flush=True)
                if i % 100 == 0 and rows:
                    new_df = pd.DataFrame(rows)
                    combined = pd.concat([cached, new_df], ignore_index=True) if not cached.empty else new_df
                    combined["date"] = pd.to_datetime(combined["date"])
                    combined = combined.drop_duplicates("date").sort_values("date")
                    combined.to_csv(MARGIN_CACHE, index=False)
                time.sleep(0.10)

    if rows:
        new_df = pd.DataFrame(rows)
        cached = pd.concat([cached, new_df], ignore_index=True) if not cached.empty else new_df
        cached["date"] = pd.to_datetime(cached["date"])
        cached = cached.drop_duplicates("date").sort_values("date")
        cached.to_csv(MARGIN_CACHE, index=False)

    if cached.empty:
        raise RuntimeError("TWSE margin cache is empty after fetch")
    margin = cached.copy()
    margin["date"] = pd.to_datetime(margin["date"])
    margin = margin.set_index("date").sort_index()
    numeric_cols = [
        "margin_buy_kntwd",
        "margin_sell_kntwd",
        "margin_cash_repay_kntwd",
        "prev_balance_kntwd",
        "today_balance_kntwd",
    ]
    margin[numeric_cols] = margin[numeric_cols].apply(pd.to_numeric, errors="coerce")
    return margin.dropna(subset=["today_balance_kntwd", "prev_balance_kntwd"])


def cooldown_event(event: pd.Series, gap: int) -> pd.Series:
    out = pd.Series(False, index=event.index)
    last_i = -10**9
    for i, flag in enumerate(event.fillna(False).to_numpy(dtype=bool)):
        if flag and i - last_i >= gap:
            out.iloc[i] = True
            last_i = i
    return out


def add_targets(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel.copy()
    for h in HORIZONS:
        ret_sum = sum(out["ret_log"].shift(-i) for i in range(1, h + 1))
        rv_sum = sum(out["ret_log"].shift(-i) ** 2 for i in range(1, h + 1))
        out[f"fwd_ret_{h}d"] = ret_sum
        out[f"fwd_vol_{h}d_ann"] = np.sqrt((rv_sum / h) * 252)
        out[f"fwd_down_{h}d"] = out[f"fwd_ret_{h}d"] < 0
    return out


def add_high_signals(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel.copy()
    for source_col, prefix in [
        ("today_balance_kntwd", "today"),
        ("prev_balance_kntwd", "strict_prev"),
    ]:
        balance = out[source_col]
        prior_all_time = balance.shift(1).expanding(min_periods=WARMUP_DAYS).max()
        prior_252 = balance.shift(1).rolling(WARMUP_DAYS, min_periods=126).max()
        out[f"{prefix}_all_time_high"] = balance > prior_all_time
        out[f"{prefix}_one_year_high"] = balance > prior_252
        out[f"{prefix}_all_time_high_cool20"] = cooldown_event(out[f"{prefix}_all_time_high"], COOLDOWN_DAYS)
        out[f"{prefix}_one_year_high_cool20"] = cooldown_event(out[f"{prefix}_one_year_high"], COOLDOWN_DAYS)
    return out


def build_panel() -> pd.DataFrame:
    px = load_tw50_prices()
    margin = fetch_or_load_margin(px.index)
    panel = px.join(margin, how="inner")
    if len(panel) < 1000:
        raise RuntimeError(f"Too few joined daily rows: {len(panel)}")
    panel = add_targets(add_high_signals(panel))
    panel["margin_balance_twd_trn"] = panel["today_balance_kntwd"] / 1e9
    return panel


def hac_dummy_test(y: pd.Series, event: pd.Series, maxlags: int) -> dict[str, float]:
    sample = pd.concat([y.rename("y"), event.astype(int).rename("event")], axis=1).dropna()
    if sample["event"].sum() < 2 or (1 - sample["event"]).sum() < 2:
        return {"coef": math.nan, "t": math.nan, "p": math.nan}
    x = sm.add_constant(sample["event"])
    model = sm.OLS(sample["y"], x).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
    return {
        "coef": float(model.params["event"]),
        "t": float(model.tvalues["event"]),
        "p": float(model.pvalues["event"]),
    }


def compare_event(panel: pd.DataFrame, event_col: str, h: int) -> dict[str, Any]:
    ret_col = f"fwd_ret_{h}d"
    vol_col = f"fwd_vol_{h}d_ann"
    down_col = f"fwd_down_{h}d"
    sample = panel[[event_col, ret_col, vol_col, down_col]].dropna()
    event = sample[event_col].astype(bool)
    n_event = int(event.sum())
    n_other = int((~event).sum())
    ret_event = sample.loc[event, ret_col]
    ret_other = sample.loc[~event, ret_col]
    vol_event = sample.loc[event, vol_col]
    vol_other = sample.loc[~event, vol_col]
    if n_event < 2 or n_other < 2:
        return {
            "event_col": event_col,
            "horizon_days": h,
            "n_event": n_event,
            "n_other": n_other,
            "insufficient": True,
        }

    welch = stats.ttest_ind(ret_event, ret_other, equal_var=False, nan_policy="omit")
    event_down = int(sample.loc[event, down_col].sum())
    event_not_down = int(n_event - event_down)
    other_down = int(sample.loc[~event, down_col].sum())
    other_not_down = int(n_other - other_down)
    odds_ratio, fisher_p = stats.fisher_exact(
        [[event_down, event_not_down], [other_down, other_not_down]],
        alternative="two-sided",
    )
    ret_hac = hac_dummy_test(sample[ret_col], sample[event_col], maxlags=h)
    vol_hac = hac_dummy_test(sample[vol_col], sample[event_col], maxlags=h)

    return {
        "event_col": event_col,
        "horizon_days": h,
        "n_event": n_event,
        "n_other": n_other,
        "insufficient": False,
        "event_dates_first_last": [
            str(sample.index[event].min().date()),
            str(sample.index[event].max().date()),
        ],
        "mean_return_event": float(ret_event.mean()),
        "mean_return_other": float(ret_other.mean()),
        "median_return_event": float(ret_event.median()),
        "median_return_other": float(ret_other.median()),
        "mean_return_diff_event_minus_other": float(ret_event.mean() - ret_other.mean()),
        "welch_t_return": float(welch.statistic),
        "welch_p_return": float(welch.pvalue),
        "hac_return_coef": ret_hac["coef"],
        "hac_return_t": ret_hac["t"],
        "hac_return_p": ret_hac["p"],
        "prob_down_event": float(sample.loc[event, down_col].mean()),
        "prob_down_other": float(sample.loc[~event, down_col].mean()),
        "fisher_odds_ratio_down": float(odds_ratio),
        "fisher_p_down": float(fisher_p),
        "mean_vol_event_ann": float(vol_event.mean()),
        "mean_vol_other_ann": float(vol_other.mean()),
        "mean_vol_diff_event_minus_other_ann": float(vol_event.mean() - vol_other.mean()),
        "hac_vol_coef": vol_hac["coef"],
        "hac_vol_t": vol_hac["t"],
        "hac_vol_p": vol_hac["p"],
    }


def moving_block_bootstrap_diff(panel: pd.DataFrame, event_col: str, h: int) -> dict[str, Any]:
    rng = np.random.default_rng(SEED)
    ret_col = f"fwd_ret_{h}d"
    sample = panel[[event_col, ret_col]].dropna().reset_index(drop=True)
    n = len(sample)
    if n < BOOT_BLOCK * 4:
        return {"n_boot_effective": 0, "ci95": [math.nan, math.nan], "mean": math.nan}
    diffs: list[float] = []
    event_arr = sample[event_col].to_numpy(dtype=bool)
    ret_arr = sample[ret_col].to_numpy(dtype=float)
    starts = np.arange(0, max(1, n - BOOT_BLOCK + 1))
    for _ in range(N_BOOT):
        pieces = []
        while sum(len(p) for p in pieces) < n:
            s = int(rng.choice(starts))
            pieces.append(np.arange(s, min(s + BOOT_BLOCK, n)))
        idx = np.concatenate(pieces)[:n]
        ev = event_arr[idx]
        if ev.sum() < 2 or (~ev).sum() < 2:
            continue
        rr = ret_arr[idx]
        diffs.append(float(rr[ev].mean() - rr[~ev].mean()))
    if not diffs:
        return {"n_boot_effective": 0, "ci95": [math.nan, math.nan], "mean": math.nan}
    arr = np.array(diffs)
    return {
        "event_col": event_col,
        "horizon_days": h,
        "block": BOOT_BLOCK,
        "seed": SEED,
        "n_boot_requested": N_BOOT,
        "n_boot_effective": int(len(arr)),
        "mean": float(arr.mean()),
        "ci95": [float(np.quantile(arr, 0.025)), float(np.quantile(arr, 0.975))],
    }


def run_analysis(panel: pd.DataFrame) -> dict[str, Any]:
    event_cols = [
        "today_all_time_high_cool20",
        "today_one_year_high_cool20",
        "today_all_time_high",
        "today_one_year_high",
        "strict_prev_all_time_high_cool20",
        "strict_prev_one_year_high_cool20",
    ]
    comparisons = []
    for event_col in event_cols:
        for h in HORIZONS:
            comparisons.append(compare_event(panel, event_col, h))

    primary_event = "today_all_time_high_cool20"
    primary_h = 20
    primary = next(c for c in comparisons if c["event_col"] == primary_event and c["horizon_days"] == primary_h)
    bootstrap = moving_block_bootstrap_diff(panel, primary_event, primary_h)
    if primary.get("insufficient"):
        verdict = "DATA_FAIL"
    elif (
        primary["hac_return_t"] <= -3.0
        and bootstrap["ci95"][1] < 0
        and primary["mean_return_diff_event_minus_other"] < 0
    ):
        verdict = "SUPPORTS_TOP_SIGNAL"
    elif (
        primary["hac_return_t"] >= 3.0
        and bootstrap["ci95"][0] > 0
        and primary["mean_return_diff_event_minus_other"] > 0
    ):
        verdict = "OPPOSITE_SIGN"
    else:
        verdict = "NULL_NO_ROBUST_TOP_SIGNAL"

    latest = panel.iloc[-1]
    return {
        "experiment_id": EXPERIMENT_ID,
        "title": TITLE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data": {
            "price_source": "data/cache/price_cache.db :: price_data adj_close for 0050.TW",
            "margin_source": "TWSE exchangeReport/MI_MARGN selectType=MS market-wide margin financing amount",
            "tw_proxy": "0050.TW as Taiwan large-cap market proxy, not official TAIEX",
            "analysis_start": START_DATE,
            "price_start": str(panel.index.min().date()),
            "price_end": str(panel.index.max().date()),
            "n_joined_daily_obs": int(len(panel)),
            "latest_margin_balance_kntwd": float(latest["today_balance_kntwd"]),
            "latest_margin_balance_twd_trn": float(latest["margin_balance_twd_trn"]),
        },
        "method": {
            "signal_timing": "margin balance at day t after close; targets use returns from t+1 through t+h only",
            "lookahead_guard": "forward returns are sum(ret_log.shift(-1) ... ret_log.shift(-h)); no same-day return included",
            "primary_event": primary_event,
            "primary_horizon_days": primary_h,
            "event_definitions": {
                "today_all_time_high": f"today_balance_kntwd > prior all-time max after {WARMUP_DAYS} warmup days",
                "today_one_year_high": f"today_balance_kntwd > prior {WARMUP_DAYS}-trading-day max",
                "cool20": f"keep first event only if at least {COOLDOWN_DAYS} trading days since prior kept event",
                "strict_prev": "uses TWSE previous-balance field as stricter one-report-lag robustness",
            },
            "horizons_days": HORIZONS,
            "return_test": "event vs non-event forward log return; Welch plus OLS dummy with Newey-West HAC maxlags=horizon",
            "vol_test": "event vs non-event annualized realized volatility over next h days; HAC dummy test",
            "bootstrap": f"moving block bootstrap on primary return diff, block={BOOT_BLOCK}, n_boot={N_BOOT}, seed={SEED}",
        },
        "primary_result": primary,
        "bootstrap_primary_return_diff": bootstrap,
        "comparisons": comparisons,
        "verdict": verdict,
        "related_knowledge": [
            {
                "id": "K1511",
                "note": "TWSE margin-balance monthly proxy in role-reversal PoC; null/underpowered and conceptually adjacent but different hypothesis.",
            },
            {
                "id": "K1530",
                "note": "0050 retail-like margin activity proxy contains suggestive but unstable OOS information for volatility; no robust public retail-flow conclusion.",
            },
        ],
        "literature": [
            {
                "citation": "Zhang, Seyedian, and Li (2005), Economics Letters",
                "relevance": "Aggregate margin credit balance is closely tied to prior returns/leverage dynamics; margin may be more coincident or momentum-driven than cleanly predictive.",
                "url": "https://www.sciencedirect.com/science/article/abs/pii/S0165176505000480",
            },
            {
                "citation": "Andrade, Chang, and Seasholes (2008), Journal of Financial Economics",
                "relevance": "Taiwan margin-account imbalances proxy individual-investor non-informational demand and predict reversals at stock level.",
                "url": "https://www.sciencedirect.com/science/article/abs/pii/S0304405X08000214",
            },
            {
                "citation": "Barber, Lee, Liu, and Odean (2009), Review of Financial Studies",
                "relevance": "Complete Taiwan transaction data show individual investors lose economically large amounts, motivating margin balance as a retail heat proxy.",
                "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=529062",
            },
            {
                "citation": "Baker and Wurgler (2006), Journal of Finance",
                "relevance": "Investor sentiment can forecast cross-sectional return patterns, but high sentiment does not mechanically imply immediate market-level tops.",
                "url": "https://pages.stern.nyu.edu/~jwurgler/papers/wurgler_baker_cross_section.pdf",
            },
        ],
    }


def save_results(results: dict[str, Any]) -> None:
    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


def plot_figures(panel: pd.DataFrame, results: dict[str, Any]) -> None:
    setup_matplotlib_font()
    event = panel["today_all_time_high_cool20"].astype(bool)
    one_year = panel["today_one_year_high_cool20"].astype(bool)

    fig, ax = plt.subplots(figsize=(12, 6), dpi=150)
    ax.plot(panel.index, panel["margin_balance_twd_trn"], color="#1F5A8A", linewidth=1.8, label="市場融資餘額（兆元）")
    ax.scatter(
        panel.index[event],
        panel.loc[event, "margin_balance_twd_trn"],
        color="#C83E3A",
        s=26,
        label="全樣本新高（cooldown 20日）",
        zorder=3,
    )
    ax.set_title("TWSE 市場融資餘額與創高事件")
    ax.set_ylabel("兆元新台幣")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(FIG_EVENTS)
    plt.close(fig)

    rows = []
    for event_col, label in [
        ("today_all_time_high_cool20", "全樣本新高"),
        ("today_one_year_high_cool20", "一年新高"),
    ]:
        for h in HORIZONS:
            rec = next(c for c in results["comparisons"] if c["event_col"] == event_col and c["horizon_days"] == h)
            rows.append(
                {
                    "label": label,
                    "h": h,
                    "event": rec["mean_return_event"] * 100,
                    "other": rec["mean_return_other"] * 100,
                }
            )
    chart = pd.DataFrame(rows)
    x = np.arange(len(HORIZONS))
    width = 0.18
    fig, ax = plt.subplots(figsize=(12, 6), dpi=150)
    for i, label in enumerate(["全樣本新高", "一年新高"]):
        sub = chart[chart["label"] == label]
        offset = (i - 0.5) * width * 2.2
        ax.bar(x + offset, sub["event"], width=width, label=f"{label}後", color=["#C83E3A", "#A76616"][i])
        ax.bar(x + offset + width, sub["other"], width=width, label=f"{label}非事件日", color=["#E6A39F", "#E8C58E"][i])
    ax.axhline(0, color="#333333", linewidth=1)
    ax.set_xticks(x + width / 2)
    ax.set_xticklabels([f"{h}日" for h in HORIZONS])
    ax.set_ylabel("後續平均 log 報酬（%）")
    ax.set_title("融資餘額創高後，後續報酬是否更差？")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend(ncol=2, fontsize=9)
    fig.tight_layout()
    fig.savefig(FIG_RETURNS)
    plt.close(fig)


def main() -> None:
    np.random.seed(SEED)
    panel = build_panel()
    panel.to_csv(EXP_DIR / "k1631_panel.csv")
    results = run_analysis(panel)
    save_results(results)
    plot_figures(panel, results)
    print(json.dumps({
        "results": str(RESULTS_PATH.resolve()),
        "figures": [str(FIG_EVENTS.resolve()), str(FIG_RETURNS.resolve())],
        "verdict": results["verdict"],
        "primary": results["primary_result"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
