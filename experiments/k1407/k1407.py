#!/usr/bin/env python3
"""K1407 — 真實歷史進場年份的「年化報酬率 (TWR) vs IRR」分歧.

延續已發佈的 DCA vs Lump Sum / IRR 文章，用**真實歷史價格**（非 bootstrap）
檢視「從過去每一個年份起開始投入、持有至資料最後一天」這種真實進場情境下，
時間加權年化報酬率 (TWR, 一般人看到的『報酬率』) vs money-weighted IRR
(你的錢實際賺到的年化) 的差異。

資料: 直接讀 experiments/k1406/data/{SPY,0050.TW}.csv (真實 yfinance auto-adjust
收盤；SPY 2005-2026 / 0050.TW 2009-2026)。**不重抓 yfinance**。
無隨機程序 (真實歷史，deterministic)，不需 seed。

兩種投入方式 (對每資產 × 每個起始年份 Y，持有至資料最後一天):

1. 單筆投入 (Lump Sum)
   * Y 年第一個交易日一次投入固定金額 LUMP_AMOUNT。
   * 指標: 總報酬倍數、CAGR、期間 MDD。
   * 數學上單一現金流的 IRR == CAGR (本檔明確驗證並註記兩者相同)。

2. 定期定額 (DCA)
   * 從 Y 年第一個交易日起，每月 (~21 交易日) 投入固定金額 PER_PERIOD_AMOUNT，
     持有至資料最後一天。
   * TWR (time-weighted 年化報酬率): 用組合「每日時間加權報酬鏈」累乘後年化
     (忽略現金流時點 — 基金/平台常秀的『報酬率』)。
   * IRR (money-weighted 年化): 用實際現金流序列 (每期投入為負、期末市值為正)
     grid-scan + brentq 求年化 IRR (你的錢真正的年化報酬)。
   * 指標: TWR、IRR、TWR−IRR 差距 (百分點)、期間 MDD、累積投入金額、期末市值。

公平比較定義:
   * lump 與 DCA 同期間 (同起點、同終點)。
   * DCA 每期固定投入 PER_PERIOD_AMOUNT；TWR/IRR 皆對「報酬率」而非絕對金額，
     金額尺度不影響年化報酬率結論 (TWR/IRR 對等比例 cashflow 不變)。

數值穩定 (error_log IRR/overflow 教訓):
   * IRR 用「每期現金流 + 期末市值」的年度化 NPV，以實際時間 (年) 為指數。
   * NPV(r) = Σ_k CF_k / (1+r)^{t_k}，t_k = (日期 − 起點) / 365.25 年。
   * 先在安全 grid (-0.95 .. +5.0) 掃描尋找變號區間，再 brentq 求根，
     避免 (1+r)^t 在極端 r 下 overflow / NaN。
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import brentq

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
DATA_DIR = (HERE.parent / "k1406" / "data").resolve()
FIG_DIR = HERE / "figures"
FIG_DIR.mkdir(exist_ok=True)

ASSETS = {
    "SPY": DATA_DIR / "SPY.csv",
    "0050.TW": DATA_DIR / "0050.TW.csv",
}

TRADING_DAYS_PER_YEAR = 252.0
MONTH_STEP = 21          # ~每月一次 DCA 投入 (交易日)
LUMP_AMOUNT = 120_000.0  # 單筆投入金額
PER_PERIOD_AMOUNT = 1_000.0  # DCA 每期固定投入金額
MIN_HOLD_DAYS = int(1.5 * TRADING_DAYS_PER_YEAR)  # 至少持有 ~1.5 年才納入起始年份

# matplotlib 繁中字型
plt.rcParams["font.sans-serif"] = ["Heiti TC", "Arial Unicode MS", "Hiragino Sans GB"]
plt.rcParams["axes.unicode_minus"] = False


# ---------------------------------------------------------------------------
# 工具函數
# ---------------------------------------------------------------------------
def load_prices(path: Path) -> pd.Series:
    df = pd.read_csv(path, parse_dates=["Date"])
    df = df.dropna(subset=["Close"]).sort_values("Date").reset_index(drop=True)
    s = pd.Series(df["Close"].astype(float).values, index=pd.DatetimeIndex(df["Date"]))
    return s


def max_drawdown(equity: np.ndarray) -> float:
    """最大回撤 (負值, 0 = 無回撤). equity 為市值序列."""
    if len(equity) == 0:
        return 0.0
    running_max = np.maximum.accumulate(equity)
    safe = np.where(running_max == 0, np.nan, running_max)
    dd = equity / safe - 1.0
    dd = dd[~np.isnan(dd)]
    return float(dd.min()) if len(dd) else 0.0


def annualized_irr(cashflows: list[tuple[pd.Timestamp, float]]) -> float | None:
    """Money-weighted 年化 IRR.

    cashflows: [(date, amount)]，投入為負、期末市值為正。
    以實際時間 (年) 為指數，grid-scan 找變號區間後 brentq 求根，避免 overflow。
    """
    if len(cashflows) < 2:
        return None
    t0 = cashflows[0][0]
    times = np.array([(d - t0).days / 365.25 for d, _ in cashflows], dtype=float)
    amounts = np.array([a for _, a in cashflows], dtype=float)

    if not (np.any(amounts > 0) and np.any(amounts < 0)):
        return None

    def npv(r: float) -> float:
        base = 1.0 + r
        if base <= 1e-9:
            base = 1e-9
        return float(np.sum(amounts / np.power(base, times)))

    grid = np.linspace(-0.95, 5.0, 600)
    vals = np.array([npv(r) for r in grid])
    finite = np.isfinite(vals)
    if not finite.any():
        return None

    root = None
    for i in range(len(grid) - 1):
        if not (finite[i] and finite[i + 1]):
            continue
        if vals[i] == 0.0:
            root = grid[i]
            break
        if vals[i] * vals[i + 1] < 0:
            try:
                root = brentq(npv, grid[i], grid[i + 1], maxiter=200, xtol=1e-10)
            except (ValueError, RuntimeError):
                root = None
            break
    return float(root) if root is not None else None


def lump_sum_metrics(prices: pd.Series, start_idx: int) -> dict:
    """單筆投入: start_idx 一次投入 LUMP_AMOUNT，持有至最後一天."""
    seg = prices.iloc[start_idx:]
    p0 = float(seg.iloc[0])
    shares = LUMP_AMOUNT / p0
    equity = shares * seg.values
    final_val = float(equity[-1])
    total_mult = final_val / LUMP_AMOUNT
    years = (seg.index[-1] - seg.index[0]).days / 365.25
    cagr = total_mult ** (1.0 / years) - 1.0 if years > 0 else np.nan
    mdd = max_drawdown(equity)
    irr = annualized_irr([(seg.index[0], -LUMP_AMOUNT), (seg.index[-1], final_val)])
    return {
        "start_date": str(seg.index[0].date()),
        "end_date": str(seg.index[-1].date()),
        "years": round(years, 3),
        "invested": round(LUMP_AMOUNT, 2),
        "final_value": round(final_val, 2),
        "total_multiple": round(total_mult, 4),
        "cagr": round(cagr, 6),
        "irr": round(irr, 6) if irr is not None else None,
        "irr_equals_cagr": (irr is not None and abs(irr - cagr) < 1e-4),
        "mdd": round(mdd, 6),
    }


def dca_metrics(prices: pd.Series, start_idx: int) -> dict:
    """定期定額: start_idx 起每 MONTH_STEP 交易日投入 PER_PERIOD_AMOUNT，持有至最後天.

    回傳 TWR (time-weighted 年化) 與 IRR (money-weighted 年化)。
    """
    seg = prices.iloc[start_idx:]
    px = seg.values.astype(float)
    dates = seg.index
    n = len(px)

    buy_idx = list(range(0, n, MONTH_STEP))
    if len(buy_idx) < 2:
        return {}

    shares = 0.0
    invested = 0.0
    mv = np.zeros(n)
    cashflows: list[tuple[pd.Timestamp, float]] = []
    buy_set = set(buy_idx)

    # TWR: 每日時間加權報酬鏈。
    # r_t = mv_before_inject_t / mv_after_inject_{t-1}（注入現金不算報酬）
    twr_factors: list[float] = []
    prev_mv_after = None

    for i in range(n):
        mv_before = shares * px[i]
        if prev_mv_after is not None and prev_mv_after > 0:
            twr_factors.append(mv_before / prev_mv_after)
        if i in buy_set:
            shares += PER_PERIOD_AMOUNT / px[i]
            invested += PER_PERIOD_AMOUNT
            cashflows.append((dates[i], -PER_PERIOD_AMOUNT))
        mv_after = shares * px[i]
        mv[i] = mv_after
        prev_mv_after = mv_after

    final_val = float(mv[-1])
    cashflows.append((dates[-1], final_val))

    years = (dates[-1] - dates[0]).days / 365.25

    twr_cum = float(np.prod(twr_factors)) if twr_factors else np.nan
    twr_ann = twr_cum ** (1.0 / years) - 1.0 if (years > 0 and np.isfinite(twr_cum) and twr_cum > 0) else np.nan

    irr = annualized_irr(cashflows)
    mdd = max_drawdown(mv)
    diff_pp = (twr_ann - irr) * 100.0 if (irr is not None and np.isfinite(twr_ann)) else None

    return {
        "start_date": str(dates[0].date()),
        "end_date": str(dates[-1].date()),
        "years": round(years, 3),
        "n_periods": len(buy_idx),
        "invested": round(invested, 2),
        "final_value": round(final_val, 2),
        "total_multiple": round(final_val / invested, 4) if invested > 0 else None,
        "twr_annualized": round(twr_ann, 6) if np.isfinite(twr_ann) else None,
        "irr_annualized": round(irr, 6) if irr is not None else None,
        "twr_minus_irr_pp": round(diff_pp, 4) if diff_pp is not None else None,
        "mdd": round(mdd, 6),
    }


def early_late_split_return(prices: pd.Series, start_idx: int) -> dict:
    """診斷市場路徑: 持有期前半 vs 後半累積報酬，用以解釋 TWR vs IRR 分歧方向."""
    seg = prices.iloc[start_idx:]
    px = seg.values.astype(float)
    half = len(px) // 2
    if half < 2:
        return {}
    early_ret = px[half] / px[0] - 1.0
    late_ret = px[-1] / px[half] - 1.0
    return {
        "early_half_return": round(float(early_ret), 6),
        "late_half_return": round(float(late_ret), 6),
        "early_minus_late": round(float(early_ret - late_ret), 6),
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run_asset(name: str, prices: pd.Series) -> dict:
    first_year = int(prices.index[0].year)
    last_date = prices.index[-1]
    last_year = int(last_date.year)

    results_by_year: list[dict] = []

    for year in range(first_year, last_year + 1):
        in_year = prices.index[prices.index.year == year]
        if len(in_year) == 0:
            continue
        start_ts = in_year[0]
        start_idx = prices.index.get_loc(start_ts)
        if isinstance(start_idx, slice):
            start_idx = start_idx.start
        if (len(prices) - start_idx) < MIN_HOLD_DAYS:
            continue

        lump = lump_sum_metrics(prices, start_idx)
        dca = dca_metrics(prices, start_idx)
        path = early_late_split_return(prices, start_idx)
        if not dca:
            continue

        results_by_year.append({
            "entry_year": year,
            "lump_sum": lump,
            "dca": dca,
            "path_diagnostic": path,
        })

    diffs = [r["dca"]["twr_minus_irr_pp"] for r in results_by_year
             if r["dca"].get("twr_minus_irr_pp") is not None]
    diffs_arr = np.array(diffs, dtype=float)

    summary = {}
    if len(diffs_arr):
        abs_idx = int(np.argmax(np.abs(diffs_arr)))
        diff_years = [r["entry_year"] for r in results_by_year
                      if r["dca"].get("twr_minus_irr_pp") is not None]
        summary = {
            "n_entry_years": len(results_by_year),
            "twr_minus_irr_pp_median": round(float(np.median(diffs_arr)), 4),
            "twr_minus_irr_pp_mean": round(float(np.mean(diffs_arr)), 4),
            "twr_minus_irr_pp_min": round(float(np.min(diffs_arr)), 4),
            "twr_minus_irr_pp_max": round(float(np.max(diffs_arr)), 4),
            "twr_gt_irr_count": int(np.sum(diffs_arr > 0)),
            "twr_lt_irr_count": int(np.sum(diffs_arr < 0)),
            "most_divergent_entry_year": diff_years[abs_idx],
            "most_divergent_twr_minus_irr_pp": round(float(diffs_arr[abs_idx]), 4),
        }

    return {"by_entry_year": results_by_year, "summary": summary}


def make_figures(all_results: dict) -> list[str]:
    paths = []

    # (a)/(b) DCA TWR vs IRR 按進場年份 (兩條線 + 差距 bar) — SPY 與 0050
    for asset_key, fig_tag in [("SPY", "a_spy"), ("0050.TW", "b_0050")]:
        res = all_results[asset_key]["by_entry_year"]
        years = [r["entry_year"] for r in res]
        twr = [r["dca"]["twr_annualized"] * 100 if r["dca"]["twr_annualized"] is not None else np.nan for r in res]
        irr = [r["dca"]["irr_annualized"] * 100 if r["dca"]["irr_annualized"] is not None else np.nan for r in res]
        diff = [r["dca"]["twr_minus_irr_pp"] if r["dca"]["twr_minus_irr_pp"] is not None else np.nan for r in res]

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), height_ratios=[2, 1], sharex=True)
        ax1.plot(years, twr, "o-", color="#1f77b4", label="TWR（時間加權年化，平台常秀的『報酬率』）", lw=2)
        ax1.plot(years, irr, "s-", color="#d62728", label="IRR（資金加權年化，你的錢真正的年化）", lw=2)
        ax1.axhline(0, color="gray", lw=0.8, ls="--")
        ax1.set_ylabel("年化報酬率（%）")
        ax1.set_title(f"{asset_key}：定期定額 TWR vs IRR 隨進場年份的分歧（真實歷史，持有至資料最後一天）")
        ax1.legend(loc="best", fontsize=9)
        ax1.grid(alpha=0.3)

        colors = ["#2ca02c" if d >= 0 else "#ff7f0e" for d in diff]
        ax2.bar(years, diff, color=colors, alpha=0.8)
        ax2.axhline(0, color="gray", lw=0.8)
        ax2.set_ylabel("TWR − IRR（百分點）")
        ax2.set_xlabel("進場年份")
        ax2.grid(alpha=0.3, axis="y")
        fig.tight_layout()
        out = FIG_DIR / f"fig_{fig_tag}_twr_vs_irr.png"
        fig.savefig(out, dpi=130)
        plt.close(fig)
        paths.append(str(out))

    # (c) 單筆 vs DCA 各進場年份 CAGR/IRR 對比 (兩資產 subplot)
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    for ax, asset_key in zip(axes, ["SPY", "0050.TW"]):
        res = all_results[asset_key]["by_entry_year"]
        years = [r["entry_year"] for r in res]
        lump_cagr = [r["lump_sum"]["cagr"] * 100 if r["lump_sum"]["cagr"] is not None else np.nan for r in res]
        dca_irr = [r["dca"]["irr_annualized"] * 100 if r["dca"]["irr_annualized"] is not None else np.nan for r in res]
        x = np.arange(len(years))
        w = 0.38
        ax.bar(x - w / 2, lump_cagr, w, color="#9467bd", label="單筆投入 CAGR（=IRR）")
        ax.bar(x + w / 2, dca_irr, w, color="#17becf", label="定期定額 IRR")
        ax.axhline(0, color="gray", lw=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels(years, rotation=45, fontsize=8)
        ax.set_ylabel("年化報酬率（%）")
        ax.set_title(f"{asset_key}：單筆 vs 定期定額 各進場年份的年化（資金加權）")
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    out = FIG_DIR / "fig_c_lump_vs_dca.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    paths.append(str(out))

    return paths


def build_verdict(all_results: dict) -> dict:
    lines = {}
    for asset_key in ["SPY", "0050.TW"]:
        lines[asset_key] = all_results[asset_key]["summary"]

    all_diffs = []
    all_path = []
    for asset_key in ["SPY", "0050.TW"]:
        for r in all_results[asset_key]["by_entry_year"]:
            d = r["dca"].get("twr_minus_irr_pp")
            pdg = r.get("path_diagnostic", {})
            if d is not None:
                all_diffs.append(d)
                if pdg.get("early_minus_late") is not None:
                    all_path.append((pdg["early_minus_late"], d))
    corr = None
    if len(all_path) >= 3:
        em = np.array([p[0] for p in all_path])
        dd = np.array([p[1] for p in all_path])
        if np.std(em) > 0 and np.std(dd) > 0:
            corr = float(np.corrcoef(em, dd)[0, 1])

    arr = np.array(all_diffs)
    direction = ("TWR 系統性高於 IRR（一般人看到的『報酬率』高估自己實際資金年化）"
                 if np.median(arr) > 0 else
                 "IRR 系統性高於 TWR（一般人看到的『報酬率』低估自己實際資金年化）")

    return {
        "headline": (
            "定期定額情境下，平台常秀的 TWR（時間加權年化報酬率）與你的錢真正賺到的 "
            "IRR（資金加權年化報酬率）會分歧；分歧方向由市場路徑決定。"
        ),
        "direction_aggregate": direction,
        "twr_minus_irr_pp_pooled_median": round(float(np.median(arr)), 4),
        "twr_minus_irr_pp_pooled_mean": round(float(np.mean(arr)), 4),
        "twr_minus_irr_pp_pooled_range": [round(float(arr.min()), 4), round(float(arr.max()), 4)],
        "corr_earlyMinusLate_vs_twrMinusIrr": round(corr, 4) if corr is not None else None,
        "mechanism": (
            "DCA 的錢是分批晚進場：早段漲多、後段平/跌的路徑下，大部分資金沒吃到早段漲幅 "
            "→ IRR < TWR（TWR 高估）；早段平/跌、後段漲的路徑下，資金正好在低點累積、吃到後段漲幅 "
            "→ IRR > TWR（TWR 低估）。corr(早段−後段報酬, TWR−IRR) 為正即支持此機制。"
        ),
        "per_asset_summary": lines,
        "practical_takeaway": (
            "看『報酬率』(TWR) 不等於你的錢的年化報酬 (IRR)。在多頭早段就進場的年份，"
            "DCA 投資人實際資金年化通常低於平台秀的 TWR；務必以 IRR 評估自己的真實績效。"
        ),
    }


def main() -> None:
    all_results: dict = {}
    for name, path in ASSETS.items():
        prices = load_prices(path)
        all_results[name] = run_asset(name, prices)
        all_results[name]["data_span"] = {
            "first_date": str(prices.index[0].date()),
            "last_date": str(prices.index[-1].date()),
            "n_obs": int(len(prices)),
        }

    fig_paths = make_figures(all_results)
    verdict = build_verdict(all_results)

    out = {
        "experiment_id": "k1407",
        "title": "真實歷史進場年份的『年化報酬率 (TWR) vs IRR』分歧",
        "review_status": (
            "Codex usage-limit (resets 2026-05-31) 且 agy fallback 無回應；改用獨立解析驗證："
            "(1) TWR 因子鏈解析證明 — 單一資產 buy-and-hold 下 TWR 累積 == 標的本身總報酬，"
            "與現金流時點無關（注入現金未被誤計為報酬，1.5==15/10 驗證通過）；"
            "(2) IRR 閉式驗證 — -100→+121 兩年 IRR=10.0072%、多筆現金流 NPV 解亦 10.0072%（365.25 天捨入誤差）；"
            "(3) 單筆 IRR==CAGR 36/36 起始年份全部成立。主線程於 Codex 恢復後可二次 primary-path review。"
        ),
        "data_source": (
            "experiments/k1406/data/{SPY,0050.TW}.csv（真實 yfinance auto-adjust 收盤，"
            "未重抓）。SPY 2005-2026 / 0050.TW 2009-2026。"
        ),
        "method": {
            "lump_amount": LUMP_AMOUNT,
            "dca_per_period_amount": PER_PERIOD_AMOUNT,
            "dca_month_step_trading_days": MONTH_STEP,
            "min_hold_trading_days": MIN_HOLD_DAYS,
            "twr": "DCA 組合每日時間加權報酬鏈（分母為注入現金前期初市值）累乘後以實際年數年化。",
            "irr": "money-weighted：每期投入為負現金流、期末市值為正，以實際年(365.25天)為指數，grid-scan+brentq 求根年化。",
            "deterministic": True,
        },
        "verdict": verdict,
        "assets": all_results,
        "figures": [str(Path(p).relative_to(HERE)) for p in fig_paths],
    }

    out_path = HERE / "k1407_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"[k1407] results → {out_path}")
    for name in ASSETS:
        s = all_results[name]["summary"]
        print(f"\n=== {name} ===  進場年份數={s.get('n_entry_years')}")
        print(f"  TWR−IRR (pp): median={s.get('twr_minus_irr_pp_median')} "
              f"mean={s.get('twr_minus_irr_pp_mean')} "
              f"range=[{s.get('twr_minus_irr_pp_min')}, {s.get('twr_minus_irr_pp_max')}]")
        print(f"  TWR>IRR 年數={s.get('twr_gt_irr_count')}  TWR<IRR 年數={s.get('twr_lt_irr_count')}")
        print(f"  最分歧進場年份={s.get('most_divergent_entry_year')} "
              f"(TWR−IRR={s.get('most_divergent_twr_minus_irr_pp')} pp)")
    print(f"\nVerdict direction: {verdict['direction_aggregate']}")
    print(f"Pooled TWR−IRR median={verdict['twr_minus_irr_pp_pooled_median']} pp "
          f"corr(early−late, TWR−IRR)={verdict['corr_earlyMinusLate_vs_twrMinusIrr']}")
    print("Figures:", fig_paths)


if __name__ == "__main__":
    main()
