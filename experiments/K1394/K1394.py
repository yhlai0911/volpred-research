"""
K1394 — 兒少投資帳戶的複利幻覺：波動拖累與報酬順序風險

動機：坊間討論兒少 TISA（個人投資儲蓄帳戶）幾乎都用平滑固定報酬率
（6%、8%）算 18 年複利。真實市場是波動的。本實驗用 SPY 真實歷史
回測「每月定額、持有 18 年」的 DCA 策略，量化三件事：
  1. 真實 18 年路徑顛簸，不是平滑曲線。
  2. 波動拖累：幾何（複利）年報酬 < 算術平均年報酬。
  3. 報酬順序風險：不同歷史起點 → 結果分布天差地別。

資料：paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv
      SPY adjusted close（含股息再投資），2000-01 起。
方法：月頻 DCA，每月投入固定金額，rolling 所有可行 18 年起點。
防錯：採月末投入時序 — 第 i 個月的投入以該月「月末」調整收盤價
      買進份額，估值時點為最後一筆投入的同一月末。每筆投入只承受
      其後月份的價格變化，不引用任何未來資訊 — 無 lookahead。
隨機程序固定 seed=42（本實驗為純歷史回測，seed 僅作規範保留）。
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

# 註冊 CJK 字型，避免圖表中文變方框
for _fp in (
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
):
    if Path(_fp).exists():
        try:
            font_manager.fontManager.addfont(_fp)
        except Exception:
            pass
plt.rcParams["font.sans-serif"] = [
    "Hiragino Sans GB",
    "Heiti TC",
    "STHeiti",
    "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False

SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
CSV = (
    HERE.parent.parent
    / "paper"
    / "garch-x-vix"
    / "data"
    / "spy_vix_qqq_eem_fez_2000-2026.csv"
)

MONTHLY_CONTRIB = 5000.0  # 元 / 月
HOLD_YEARS = 18
HOLD_MONTHS = HOLD_YEARS * 12
INFLATION_ANNUAL = 0.02  # 實質終值用 2%/年通膨折現
TEXTBOOK_RATE = 0.06  # 坊間「平滑 6%」對照


def load_monthly_spy():
    """讀 SPY adjusted close，轉成月末序列。"""
    df = pd.read_csv(CSV, parse_dates=["date"])
    df = df[["date", "spy_adj_close"]].dropna()
    df = df.sort_values("date").reset_index(drop=True)
    diag = {
        "raw_daily_rows": int(len(df)),
        "date_min": df["date"].min().strftime("%Y-%m-%d"),
        "date_max": df["date"].max().strftime("%Y-%m-%d"),
        "missing_spy_adj_close": int(df["spy_adj_close"].isna().sum()),
    }
    # 月末值（每月最後一個交易日的調整收盤）
    df["ym"] = df["date"].dt.to_period("M")
    monthly = df.groupby("ym").last().reset_index()
    monthly["month_start"] = monthly["ym"].dt.to_timestamp()
    monthly = monthly[["ym", "month_start", "spy_adj_close"]].reset_index(drop=True)
    diag["monthly_rows"] = int(len(monthly))
    return monthly, diag


def simulate_dca(prices):
    """
    對一段月末價格序列（長度 = HOLD_MONTHS）跑月頻 DCA。

    時序定義（明確、內部一致、無 lookahead）：
      - prices[i] = 第 i 個月「月末」的調整收盤價（i = 0 .. HOLD_MONTHS-1）。
      - 第 i 個月的投入發生在該月月末，以 prices[i] 買進份額。
      - 估值時點為第 HOLD_MONTHS-1 個月月末，價格 prices[-1]。
      - 因此第 i 筆投入被持有 (HOLD_MONTHS-1 - i) 個月：第 0 筆持滿
        215 個月、最後一筆持有 0 個月。最後一筆當月零報酬，這是月末
        定投的標準保守設定，不引用任何未來資訊。
    path[i] = 第 i 個月月末、用當月價格估的組合市值。
    """
    shares = 0.0
    invested = 0.0
    path = []
    for px in prices:
        shares += MONTHLY_CONTRIB / px
        invested += MONTHLY_CONTRIB
        path.append(shares * px)
    final_nominal = shares * prices[-1]
    return final_nominal, invested, np.array(path)


def money_weighted_irr(final_value, monthly_contrib, months):
    """
    解每月定額投入的金額加權內部報酬率（月 IRR），再年化。

    現金流時點與 simulate_dca 一致：第 i 筆投入在 t=i（月末），
    終值贖回在 t=months-1（最後一筆投入的同一時點）。
    第 i 筆投入折現期數 = (months-1 - i)。
    """
    def npv(r):
        # 折現到 t=0：投入在 t = 0 .. months-1，終值贖回在 t = months-1
        v = sum(-monthly_contrib / (1 + r) ** t for t in range(months))
        v += final_value / (1 + r) ** (months - 1)
        return v

    # npv 對 r 單調遞減；二分前先驗證 lo/hi 真的夾住根
    lo, hi = -0.5, 0.5
    if not (npv(lo) > 0 > npv(hi)):
        raise ValueError(
            f"IRR bracket invalid: npv({lo})={npv(lo):.1f}, npv({hi})={npv(hi):.1f}"
        )
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(mid) > 0:
            lo = mid
        else:
            hi = mid
    monthly_irr = (lo + hi) / 2
    annual_irr = (1 + monthly_irr) ** 12 - 1
    return annual_irr


def main():
    monthly, diag = load_monthly_spy()
    prices = monthly["spy_adj_close"].to_numpy()
    months_avail = len(prices)

    # ---- 市場層級的算術 vs 幾何年報酬（波動拖累的根源）----
    # 為讓兩者口徑可比，先算「年報酬序列」：以日曆年聚合月報酬。
    monthly = monthly.copy()
    monthly["ret"] = monthly["spy_adj_close"].pct_change()
    monthly["year"] = monthly["ym"].dt.year
    # 只保留有完整 12 個月的年份，避免頭尾不完整年扭曲算術/幾何比較
    yearly = (
        monthly.dropna(subset=["ret"])
        .groupby("year")
        .agg(n=("ret", "size"), gross=("ret", lambda s: float(np.prod(1 + s))))
    )
    full_years = yearly[yearly["n"] == 12].copy()
    annual_rets = full_years["gross"].to_numpy() - 1.0  # 各完整年的年報酬
    arith_annual = float(np.mean(annual_rets))  # 算術平均年報酬
    geo_annual = float(np.exp(np.mean(np.log(1 + annual_rets))) - 1)  # 幾何年報酬
    annual_vol = float(np.std(annual_rets, ddof=1))  # 年報酬標準差
    vol_drag_annual = arith_annual - geo_annual  # 波動拖累（年化）
    # 月頻波動另存作參考
    monthly_ret = monthly["ret"].dropna().to_numpy()
    monthly_vol_annualized = float(np.std(monthly_ret, ddof=1) * np.sqrt(12))

    # ---- rolling 18 年 DCA ----
    n_windows = months_avail - HOLD_MONTHS + 1
    results = []
    for start in range(n_windows):
        seg = prices[start : start + HOLD_MONTHS]
        final_nom, invested, path = simulate_dca(seg)
        # 實質終值：以投入期中點折現過於粗略，這裡用「期末以 18 年通膨折現」
        # 給讀者一個保守的購買力下限視角。
        final_real = final_nom / (1 + INFLATION_ANNUAL) ** HOLD_YEARS
        irr = money_weighted_irr(final_nom, MONTHLY_CONTRIB, HOLD_MONTHS)
        results.append(
            {
                "start_ym": str(monthly["ym"].iloc[start]),
                "end_ym": str(monthly["ym"].iloc[start + HOLD_MONTHS - 1]),
                "final_nominal": float(final_nom),
                "final_real": float(final_real),
                "invested": float(invested),
                "money_weighted_annual_return": float(irr),
                "multiple_nominal": float(final_nom / invested),
            }
        )

    finals_nom = np.array([r["final_nominal"] for r in results])
    finals_real = np.array([r["final_real"] for r in results])
    irrs = np.array([r["money_weighted_annual_return"] for r in results])
    invested_total = results[0]["invested"]

    # 坊間「平滑 6%」對照：每月投入 5000、月利率 6%/12、18 年終值
    r_m = TEXTBOOK_RATE / 12
    textbook_final = MONTHLY_CONTRIB * (((1 + r_m) ** HOLD_MONTHS - 1) / r_m)

    def pct(a, q):
        return float(np.percentile(a, q))

    dist = {
        "n_windows": int(n_windows),
        "monthly_contribution": MONTHLY_CONTRIB,
        "total_invested": float(invested_total),
        "hold_years": HOLD_YEARS,
        "textbook_smooth_6pct_final_nominal": float(textbook_final),
        "final_nominal": {
            "min": float(finals_nom.min()),
            "p10": pct(finals_nom, 10),
            "median": float(np.median(finals_nom)),
            "p90": pct(finals_nom, 90),
            "max": float(finals_nom.max()),
        },
        "final_real_2pct_inflation": {
            "min": float(finals_real.min()),
            "p10": pct(finals_real, 10),
            "median": float(np.median(finals_real)),
            "p90": pct(finals_real, 90),
            "max": float(finals_real.max()),
        },
        "money_weighted_annual_return": {
            "min": float(irrs.min()),
            "p10": pct(irrs, 10),
            "median": float(np.median(irrs)),
            "p90": pct(irrs, 90),
            "max": float(irrs.max()),
        },
        "worst_window": min(results, key=lambda r: r["final_nominal"]),
        "best_window": max(results, key=lambda r: r["final_nominal"]),
        "median_window": sorted(results, key=lambda r: r["final_nominal"])[
            len(results) // 2
        ],
    }

    market = {
        "definition": "算術/幾何年報酬以日曆年聚合的完整年份報酬序列計算",
        "n_full_calendar_years": int(len(annual_rets)),
        "full_year_range": f"{int(full_years.index.min())}-{int(full_years.index.max())}",
        "sample_monthly_returns": int(len(monthly_ret)),
        "arithmetic_annual_return": float(arith_annual),
        "geometric_annual_return": float(geo_annual),
        "volatility_drag_annual": float(vol_drag_annual),
        "volatility_drag_bp": float(vol_drag_annual * 1e4),
        "annual_return_volatility": float(annual_vol),
        "monthly_return_volatility_annualized": float(monthly_vol_annualized),
    }

    out = {
        "experiment_id": "K1394",
        "title": "兒少投資帳戶的複利幻覺：波動拖累與報酬順序風險",
        "seed": SEED,
        "data_source": str(CSV.relative_to(HERE.parent.parent)),
        "data_diagnostics": diag,
        "market_level": market,
        "rolling_dca": dist,
        "caveats": [
            "SPY adjusted close 含股息再投資，未扣交易成本與管理費。",
            "歷史回測，過去報酬不保證未來；US 大盤是 survivorship-favourable 市場。",
            "實質終值以期末 18 年通膨一次折現，為保守購買力視角；"
            "若以投入時點分別折現，實質值會略高。",
            "rolling 視窗高度重疊（相鄰起點僅差一個月），分布的"
            "極端值由少數獨立 18 年段落驅動，非獨立樣本。",
        ],
    }

    res_path = HERE / "K1394_results.json"
    with open(res_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"wrote {res_path}")

    # ============ 圖表 1：18 年終值分布直方圖 ============
    fig, ax = plt.subplots(figsize=(9, 5.2))
    ax.hist(finals_nom / 1e6, bins=24, color="#3b6ea5", edgecolor="white", alpha=0.9)
    ax.axvline(
        textbook_final / 1e6,
        color="#c0392b",
        linestyle="--",
        linewidth=2,
        label=f"坊間平滑 6% 假設：{textbook_final/1e6:.2f} 百萬",
    )
    ax.axvline(
        np.median(finals_nom) / 1e6,
        color="#27ae60",
        linewidth=2,
        label=f"真實回測中位數：{np.median(finals_nom)/1e6:.2f} 百萬",
    )
    ax.set_xlabel("18 年後名目終值（新台幣百萬元）")
    ax.set_ylabel("歷史起點數量")
    ax.set_title(
        f"每月定額 5,000 元投入 SPY、持有 18 年\n"
        f"{n_windows} 個歷史起點的終值分布（總投入 {invested_total/1e6:.2f} 百萬）"
    )
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    p1 = HERE / "K1394_final_value_distribution.png"
    fig.savefig(p1, dpi=130)
    plt.close(fig)
    print(f"wrote {p1}")

    # ============ 圖表 2：真實路徑 vs 平滑曲線 ============
    fig, ax = plt.subplots(figsize=(9, 5.2))
    months_axis = np.arange(1, HOLD_MONTHS + 1)
    # 平滑 6% 路徑
    smooth = np.array(
        [MONTHLY_CONTRIB * (((1 + r_m) ** m - 1) / r_m) for m in months_axis]
    )
    ax.plot(
        months_axis / 12,
        smooth / 1e6,
        color="#c0392b",
        linewidth=2.5,
        linestyle="--",
        label="坊間平滑 6% 曲線",
    )
    # 三條真實路徑：最差 / 中位 / 最佳
    labelmap = {
        "worst_window": ("最差起點", "#7f8c8d"),
        "median_window": ("中位起點", "#2980b9"),
        "best_window": ("最佳起點", "#16a085"),
    }
    for key, (lab, color) in labelmap.items():
        w = dist[key]
        s = monthly[monthly["ym"].astype(str) == w["start_ym"]].index[0]
        seg = prices[s : s + HOLD_MONTHS]
        _, _, path = simulate_dca(seg)
        ax.plot(
            months_axis / 12,
            path / 1e6,
            color=color,
            linewidth=1.8,
            label=f"{lab}（{w['start_ym']} 起）",
        )
    ax.set_xlabel("投入年數")
    ax.set_ylabel("組合市值（新台幣百萬元）")
    ax.set_title("教科書畫的是直線，市場走的是顛簸路徑")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    p2 = HERE / "K1394_path_vs_smooth.png"
    fig.savefig(p2, dpi=130)
    plt.close(fig)
    print(f"wrote {p2}")

    # ---- console 摘要 ----
    print("\n=== 市場層級 ===")
    print(f"算術年報酬 {arith_annual:.4%} / 幾何年報酬 {geo_annual:.4%}")
    print(f"波動拖累 {vol_drag_annual:.4%} = {vol_drag_annual*1e4:.0f} bp")
    print(f"年化波動 {annual_vol:.2%}")
    print("\n=== 18 年 rolling DCA（名目終值）===")
    print(f"視窗數 {n_windows}, 總投入 {invested_total:,.0f}")
    fn = dist["final_nominal"]
    print(f"min {fn['min']:,.0f} / median {fn['median']:,.0f} / max {fn['max']:,.0f}")
    fr = dist["final_real_2pct_inflation"]
    print(
        f"實質 min {fr['min']:,.0f} / median {fr['median']:,.0f} / max {fr['max']:,.0f}"
    )
    print(f"坊間平滑 6% 終值 {textbook_final:,.0f}")
    print(f"worst window: {dist['worst_window']['start_ym']} → "
          f"{dist['worst_window']['end_ym']}")
    print(f"best  window: {dist['best_window']['start_ym']} → "
          f"{dist['best_window']['end_ym']}")


if __name__ == "__main__":
    main()
