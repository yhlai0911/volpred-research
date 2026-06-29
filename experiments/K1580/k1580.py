#!/usr/bin/env python3
"""K1580 — 年度等權再平衡 vs 買進持有 vs 大盤指數（台灣 + 美國）。

驗證老闆自創的「年度等權再平衡」策略：每年第一個交易日，計算 N 檔股票的
組合總淨值，平均分配（每檔目標 = 總額 / N），高於目標賣、低於目標買，回到等權；
持有一年後再平衡，年復一年。對照組 = 同籃子買進持有 + 大盤指數（台灣 0050、美國 SPY）。

研究誠實守則（對應 .claude/rules/experiments.md）:
- 無 lookahead：再平衡在「該年第一個交易日」用『當日』收盤價執行（理想化同日收盤 MOC
  執行假設；新權重不乘同日報酬，非 lookahead alpha，但非保證成交價）。買進持有與指數同樣期初一次建倉。
- 交易成本：台股 30bps、美股 10bps（單邊，charge 在成交名目上），另含 no_cost 對照。
- Survivorship bias：個股籃子用「今日已知的大型股」必然偏向存活者 → 明確揭露，
  並加 sector ETF / 多資產 / 跨國籃子（不下市，降低個股存活者偏差，仍有集合選擇）作為再平衡『機制本身』的較乾淨檢定。
- 固定 seed：block bootstrap n_boot=5000, seed=42。
- 公平比較：再平衡 / 買進持有 / 指數同期間、同成本慣例、同籃子。
- 顯著性：對「再平衡 - 買進持有」的每日報酬差做 block bootstrap（block=21）取年化差 CI95；
  另報年度超額序列（n≈11）。再平衡溢酬本質是低頻現象，兩種口徑都報以求誠實。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from volpred.utils import clean_tw50_data  # 修 yfinance 0050.TW 幻影拆股（skill: external-data-sources）

SEED = 42
START = "1990-01-01"   # 下載下限；各籃子實際起點由「全員都有資料」的最早日自動決定
END = "2024-12-31"
TRADING_DAYS = 252
INITIAL = 1_000_000.0

# 單邊交易成本（成交名目 × rate）。台股含稅費較高，美股較低。
COST_BPS_GRID = {"no_cost": 0.0, "tw_30bps": 0.0030, "us_10bps": 0.0010}

# 分時期（regime）：name, start, end。各籃子只計算落在其資料範圍內的時期。
SUB_PERIODS = [
    ("2000-2002 網路泡沫破裂", "2000-01-01", "2002-12-31"),
    ("2003-2007 多頭", "2003-01-01", "2007-12-31"),
    ("2008-2009 金融海嘯", "2008-01-01", "2009-12-31"),
    ("2010-2019 長多頭/低波", "2010-01-01", "2019-12-31"),
    ("2020-2021 COVID 崩跌+反彈", "2020-01-01", "2021-12-31"),
    ("2022 升息/輪動", "2022-01-01", "2022-12-31"),
    ("2023-2024 AI 大型股", "2023-01-01", "2024-12-31"),
]

# 註：yfinance 的 0050.TW 把 2025-06-18 的 1:4 拆股只回溯套到 2014-01-02 起 → 2014-01-02 假 -75%
# 報酬、CAGR 嚴重低估（external-data-sources skill 已記載）。用 clean_tw50_data 修回連續序列，
# 救回「可投資」的 0050 當對照；另保留 ^TWII（price-only，少配息，但歷史更長到 2001）作交叉。
# 個股序列（2330/2454/...）皆乾淨，rebal vs BH 主比較不受影響。
BASKETS = {
    "TW_large_caps": {
        "tickers": [
            "2330.TW", "2317.TW", "2454.TW", "2412.TW", "2882.TW",
            "1301.TW", "2308.TW", "2002.TW", "2881.TW", "1303.TW",
        ],
        "benchmark": "0050.TW",
        "default_cost": "tw_30bps",
        "survivorship": True,
        "label": "台灣大型股（10 檔，對照可投資的 0050；0050 經 clean_tw50_data 修拆股；起點受 0050 yfinance 史 2009 限制）",
    },
    "TW_large_caps_TWII": {
        "tickers": [
            "2330.TW", "2317.TW", "2454.TW", "2412.TW", "2882.TW",
            "1301.TW", "2308.TW", "2002.TW", "2881.TW", "1303.TW",
        ],
        "benchmark": "^TWII",
        "default_cost": "tw_30bps",
        "survivorship": True,
        "label": "台灣大型股（同籃子，對照 ^TWII 加權指數;price-only 低估配息;換取更長歷史到 2001）",
    },
    "US_large_caps": {
        "tickers": [
            "AAPL", "MSFT", "JNJ", "PG", "KO",
            "JPM", "XOM", "WMT", "HD", "MCD",
        ],
        "benchmark": "SPY",
        "default_cost": "us_10bps",
        "survivorship": True,
        "label": "美國大型股（10 檔，對照 SPY；起點受 SPY 上市 1993 限制 → 涵蓋網路泡沫+金融海嘯）",
    },
    "US_sector_ETFs": {
        "tickers": [
            "XLK", "XLF", "XLE", "XLV", "XLP",
            "XLY", "XLI", "XLB", "XLU",
        ],
        "benchmark": "SPY",
        "default_cost": "us_10bps",
        "survivorship": False,
        "label": "美國產業 ETF（9 檔，產業不下市 → 降低個股存活者偏差（仍有集合選擇）；起點受 SPDR 上市 1999 限制）",
    },
    "US_multi_asset": {
        "tickers": ["SPY", "TLT", "GLD", "VNQ", "DBC"],
        "benchmark": "SPY",
        "default_cost": "us_10bps",
        "survivorship": False,
        "label": "多資產類別（股/長債/黃金/REIT/商品，低相關 → 再平衡溢酬經典場景；起點受 DBC 上市 2006 限制）",
    },
    "Global_country_ETFs": {
        "tickers": ["EWJ", "EWG", "EWU", "EWH", "EWA", "EWC", "EWZ", "EWW", "EWS"],
        "benchmark": "ACWI",
        "default_cost": "us_10bps",
        "survivorship": False,
        "label": "跨國家 ETF（9 國 iShares，不下市 → 降低個股存活者偏差（仍有國家集合選擇）；對照 ACWI 全球指數，起點受 ACWI 上市 2008 限制）",
    },
}


def _download(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    """抓 auto-adjusted 收盤價（已還原配息/拆股，適合多年持有）。回傳原始（不裁切），
    僅丟全空欄。各籃子的起點裁切交給 _basket_window（用全員都有資料的最早日）。"""
    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].copy()
    else:  # 單一 ticker
        close = raw[["Close"]].copy()
        close.columns = tickers
    close = close.dropna(axis=1, how="all")
    return close


def _basket_window(prices: pd.DataFrame, bench: pd.Series) -> tuple[pd.DataFrame, pd.Series]:
    """各籃子實際起點 = 「所有成員 + 對照」都已有資料的最早日（避免存活/上市偏差地對齊）。"""
    starts = [prices[c].first_valid_index() for c in prices.columns]
    starts.append(bench.first_valid_index())
    start = max(s for s in starts if s is not None)
    p = prices.loc[start:].ffill().dropna()
    common = p.index.intersection(bench.loc[start:].index)
    p = p.loc[common]
    b = bench.loc[common].ffill()
    return p, b


def _first_trading_days(index: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """每個日曆年的第一個交易日。"""
    df = pd.DataFrame(index=index)
    df["year"] = df.index.year
    return [grp.index[0] for _, grp in df.groupby("year")]


def _simulate(prices: pd.DataFrame, rebalance: bool, cost_rate: float,
              initial: float = INITIAL) -> pd.Series:
    """模擬組合淨值序列。

    rebalance=True : 期初等權建倉；每年第一個交易日用『當日』價回到等權（無 lookahead）。
    rebalance=False: 期初等權建倉後買進持有，永不再平衡。
    成本：建倉一次 + 每次再平衡的成交名目 × cost_rate，以等比例縮減組合後重新配置。
    """
    tickers = list(prices.columns)
    n = len(tickers)
    dates = prices.index
    first_days = set(_first_trading_days(dates)) if rebalance else set()

    p0 = prices.iloc[0].values
    # 期初等權：扣建倉成本後平均配置（建倉成本之後在 _metrics 以 INITIAL 為分母計入績效）
    gross = initial
    entry_cost = gross * cost_rate  # 全額建倉的單邊成本
    investable = gross - entry_cost
    shares = (investable / n) / p0  # 每檔等金額

    values = np.empty(len(dates))
    start_date = dates[0]
    for i, dt in enumerate(dates):
        px = prices.iloc[i].values
        if rebalance and dt in first_days and dt != start_date:
            # 理想化同日收盤(MOC)再平衡執行假設：以該年首個交易日收盤價計算組合淨值
            # 並下單回到等權。成本是 traded_notional×cost_rate；因成本後目標會降低、
            # 交易量隨之變動，用 fixed-point 迭代求 self-financing 解（移除近似誤差）。
            total = float(np.dot(shares, px))
            total_after = total
            for _ in range(3):
                target = total_after / n
                new_shares = target / px
                traded_notional = float(np.sum(np.abs(new_shares - shares) * px))
                total_after = total - traded_notional * cost_rate
            shares = (total_after / n) / px              # 回到等權（成本後）
        values[i] = float(np.dot(shares, px))
    return pd.Series(values, index=dates, name="value")


def _simulate_benchmark(price: pd.Series, cost_rate: float,
                        initial: float = INITIAL) -> pd.Series:
    """大盤指數買進持有（期初全額建倉一次，扣一次成本）。"""
    investable = initial * (1.0 - cost_rate)
    shares = investable / price.iloc[0]
    return (shares * price).rename("value")


def _metrics(value: pd.Series, initial: float = INITIAL) -> dict:
    # 分母用 INITIAL（gross），讓建倉成本計入 total_return / CAGR（Codex CR #2）
    ret = value.pct_change().dropna()
    total_return = float(value.iloc[-1] / initial - 1.0)
    years = (value.index[-1] - value.index[0]).days / 365.25
    cagr = float((value.iloc[-1] / initial) ** (1.0 / years) - 1.0)
    ann_vol = float(ret.std() * np.sqrt(TRADING_DAYS))
    sharpe = float((ret.mean() * TRADING_DAYS) / ann_vol) if ann_vol > 0 else float("nan")
    roll_max = value.cummax()
    dd = value / roll_max - 1.0
    max_dd = float(dd.min())
    calmar = float(cagr / abs(max_dd)) if max_dd < 0 else float("nan")
    return {
        "total_return": total_return,
        "cagr": cagr,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "calmar": calmar,
        "final_value": float(value.iloc[-1]),
    }


def _annual_returns(value: pd.Series) -> pd.Series:
    # 把期初淨值當錨點，使首年（建倉→首個年底）報酬也納入（Codex CR #4）
    ye = value.resample("YE").last()
    anchor = pd.Series([value.iloc[0]], index=[value.index[0]])
    s = pd.concat([anchor, ye]).sort_index()
    s = s[~s.index.duplicated(keep="first")]
    return s.pct_change().dropna()


def _block_bootstrap_diff_ci(rebal_val: pd.Series, bh_val: pd.Series,
                             block: int = 21, n_boot: int = 5000,
                             seed: int = SEED) -> dict:
    """對『再平衡 - 買進持有』每日報酬差做 block bootstrap，取年化平均差 CI95。"""
    r_rebal = rebal_val.pct_change().dropna()
    r_bh = bh_val.pct_change().dropna()
    diff = (r_rebal - r_bh).dropna().values
    m = len(diff)
    if m < block * 3:
        return {"insufficient": True, "n": int(m)}
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(m / block))
    boot_means = np.empty(n_boot)
    max_start = m - block
    for b in range(n_boot):
        starts = rng.integers(0, max_start + 1, size=n_blocks)
        sample = np.concatenate([diff[s:s + block] for s in starts])[:m]
        boot_means[b] = sample.mean()
    ann = boot_means * TRADING_DAYS
    point = float(diff.mean() * TRADING_DAYS)
    lo, hi = float(np.percentile(ann, 2.5)), float(np.percentile(ann, 97.5))
    return {
        "ann_mean_diff": point,
        "ci95_low": lo,
        "ci95_high": hi,
        "prob_positive": float(np.mean(ann > 0)),
        "significant": bool(lo > 0 or hi < 0),
        "n_days": int(m),
        "block": block,
        "n_boot": n_boot,
        "seed": seed,
    }


def _cagr_between(value: pd.Series) -> float:
    if len(value) < 2:
        return float("nan")
    years = (value.index[-1] - value.index[0]).days / 365.25
    if years <= 0:
        return float("nan")
    return float((value.iloc[-1] / value.iloc[0]) ** (1.0 / years) - 1.0)


def _subperiod_breakdown(rebal_val: pd.Series, bh_val: pd.Series,
                         bench_val: pd.Series) -> list[dict]:
    """分時期（regime）逐期計算 rebal / BH / bench 的 CAGR 與 rebal−BH 溢酬。
    各期 value 重新 rebase 到期初（只看該期內表現）。短窗 bootstrap 也做但標註低 power。"""
    out = []
    for label, s, e in SUB_PERIODS:
        sl = slice(pd.Timestamp(s), pd.Timestamp(e))
        rv, bv, mv = rebal_val.loc[sl], bh_val.loc[sl], bench_val.loc[sl]
        if len(rv) < 30:  # 該期資料不足（多半因籃子起點較晚）
            continue
        rv, bv, mv = rv / rv.iloc[0], bv / bv.iloc[0], mv / mv.iloc[0]
        boot = _block_bootstrap_diff_ci(rv, bv, block=21, n_boot=2000)
        out.append({
            "period": label,
            "start": str(rv.index[0].date()), "end": str(rv.index[-1].date()),
            "trading_days": int(len(rv)),
            "rebal_cagr": _cagr_between(rv),
            "bh_cagr": _cagr_between(bv),
            "bench_cagr": _cagr_between(mv),
            "rebal_minus_bh_cagr": _cagr_between(rv) - _cagr_between(bv),
            "rebal_minus_bench_cagr": _cagr_between(rv) - _cagr_between(mv),
            "boot_ann_diff": boot.get("ann_mean_diff"),
            "boot_ci95": [boot.get("ci95_low"), boot.get("ci95_high")],
            "boot_significant": boot.get("significant"),
            "boot_low_power": True,
            "boot_note": "短窗 + 7 期多重比較 → 顯著性 power 低，分期 CI 僅作描述，不作正式 inference",
        })
    return out


def run_basket(name: str, spec: dict) -> dict:
    print(f"\n=== {name}: {spec['label']} ===")
    tickers = spec["tickers"]
    prices_raw = _download(tickers, START, END)
    bench_raw = _download([spec["benchmark"]], START, END)
    bench_full = bench_raw.iloc[:, 0]
    if spec["benchmark"] == "0050.TW":  # 修 yfinance 幻影拆股（canonical fix）
        bench_full, _ = clean_tw50_data(bench_full.dropna())
        print("   [data] 0050.TW 已用 clean_tw50_data 修拆股")
    prices, bench_series = _basket_window(prices_raw, bench_full)
    print(f"   標的 {list(prices.columns)}  期間 {prices.index[0].date()}~{prices.index[-1].date()}  交易日 {len(prices)}")

    per_cost = {}
    for cost_name, cost_rate in COST_BPS_GRID.items():
        rebal_val = _simulate(prices, rebalance=True, cost_rate=cost_rate)
        bh_val = _simulate(prices, rebalance=False, cost_rate=cost_rate)
        bench_val = _simulate_benchmark(bench_series, cost_rate=cost_rate)
        boot = _block_bootstrap_diff_ci(rebal_val, bh_val)
        rebal_ann = _annual_returns(rebal_val)
        bh_ann = _annual_returns(bh_val)
        premium_ann = (rebal_ann - bh_ann)
        per_cost[cost_name] = {
            "cost_rate": cost_rate,
            "rebalance": _metrics(rebal_val),
            "buy_hold": _metrics(bh_val),
            "benchmark": _metrics(bench_val),
            "bootstrap_diff": boot,
            "annual_premium_rebal_minus_bh": {
                str(k.year): float(v) for k, v in premium_ann.items()
            },
            "annual_premium_mean": float(premium_ann.mean()),
            "annual_premium_positive_years": int((premium_ann > 0).sum()),
            "annual_premium_total_years": int(len(premium_ann)),
        }

    # verdict 用該籃子的 default cost
    dc = spec["default_cost"]
    d = per_cost[dc]
    rebal_cagr = d["rebalance"]["cagr"]
    bh_cagr = d["buy_hold"]["cagr"]
    bench_cagr = d["benchmark"]["cagr"]
    boot = d["bootstrap_diff"]
    sig = boot.get("significant", False)
    beats_bh = rebal_cagr > bh_cagr
    beats_bench = rebal_cagr > bench_cagr
    verdict = {
        "default_cost": dc,
        "rebal_cagr": rebal_cagr,
        "bh_cagr": bh_cagr,
        "bench_cagr": bench_cagr,
        "rebal_beats_buyhold": bool(beats_bh),
        "rebal_beats_benchmark": bool(beats_bench),
        "diff_vs_buyhold_significant": bool(sig),
        "rebal_negative_return": bool(d["rebalance"]["total_return"] < 0),
        "summary": (
            f"再平衡 CAGR {rebal_cagr:.2%} vs 買進持有 {bh_cagr:.2%} vs 指數 {bench_cagr:.2%}；"
            f"差異{'顯著' if sig else '不顯著'}（CI95 "
            f"[{boot.get('ci95_low', float('nan')):.2%}, {boot.get('ci95_high', float('nan')):.2%}]）"
        ),
    }
    print(f"   {verdict['summary']}")

    # 分時期（regime）用 default cost 的三條腿 value 重跑
    rebal_dc = _simulate(prices, rebalance=True, cost_rate=COST_BPS_GRID[dc])
    bh_dc = _simulate(prices, rebalance=False, cost_rate=COST_BPS_GRID[dc])
    bench_dc = _simulate_benchmark(bench_series, cost_rate=COST_BPS_GRID[dc])
    subperiods = _subperiod_breakdown(rebal_dc, bh_dc, bench_dc)
    for sp in subperiods:
        print(f"      · {sp['period']}: rebal−BH {sp['rebal_minus_bh_cagr']*100:+.2f}%/yr "
              f"(rebal {sp['rebal_cagr']*100:.1f}% vs BH {sp['bh_cagr']*100:.1f}% vs bench {sp['bench_cagr']*100:.1f}%)")

    return {
        "label": spec["label"],
        "benchmark": spec["benchmark"],
        "survivorship_bias": spec["survivorship"],
        "survivorship_note": (
            "個股籃子用今日已知大型股回測 → 存活者偏差（偏高）" if spec["survivorship"]
            else "ETF/資產類別籃子降低個股存活者偏差，但仍有產品/集合選擇偏差，非完全無偏"
        ),
        "tickers_used": list(prices.columns),
        "period": {"start": str(prices.index[0].date()), "end": str(prices.index[-1].date()),
                   "trading_days": int(len(prices))},
        "by_cost": per_cost,
        "subperiods_default_cost": subperiods,
        "verdict": verdict,
    }


def main() -> int:
    np.random.seed(SEED)
    results = {
        "experiment_id": "K1580",
        "title": "年度等權再平衡 vs 買進持有 vs 大盤指數（台灣 + 美國，含分時期）",
        "config": {
            "start": START, "end": END, "initial_capital": INITIAL,
            "cost_bps_grid": COST_BPS_GRID, "seed": SEED,
            "trading_days_per_year": TRADING_DAYS,
        },
        "data_source": {
            "provider": "yfinance",
            "price_field": "Close (auto_adjust=True，已還原配息/拆股)",
            "download_floor": START,
            "note": "各籃子實際起點 = 全員都有資料的最早日（_basket_window），故各籃子期間不同。",
        },
        "execution_assumption": (
            "理想化同日收盤(MOC)再平衡：以該年首個交易日收盤價計算組合淨值並回到等權。"
            "非 lookahead alpha（新權重不乘同日報酬），但屬理想化執行假設，非保證可成交價。"
        ),
        "strategy_definition": (
            "每年第一個交易日：計算組合總淨值 → 每檔目標 = 總額/N → 高於目標賣、"
            "低於目標買，回到等權；持有一年再重複。"
        ),
        "baskets": {},
    }
    for name, spec in BASKETS.items():
        try:
            results["baskets"][name] = run_basket(name, spec)
        except Exception as exc:  # noqa: BLE001 — 單一籃子失敗不擋其他
            print(f"   [error] {name}: {exc}")
            results["baskets"][name] = {"error": str(exc)}

    out = Path(__file__).parent / "k1580_results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n結果寫入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
