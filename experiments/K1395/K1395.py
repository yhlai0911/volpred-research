"""
K1395 — 兒少 TISA 的複利幻覺（台股版）：0050.TW 真實窗口 + TWII 波動拖累與報酬順序風險

動機：兒少 TISA（個人投資儲蓄帳戶）是台灣的政策題，讀者是台灣家長。
坊間試算幾乎都用平滑固定報酬率（6%、8%）畫 18 年複利曲線。真實市場是
波動的。本實驗用台灣家長最熟悉的標的 0050.TW（元大台灣 50 ETF）與
台股加權指數 TWII 的真實歷史回測「每月定額、持有 18 年」的 DCA 策略，
量化三件平滑試算沒講的事：
  1. 真實 18 年路徑顛簸，不是平滑曲線。
  2. 波動拖累：幾何（複利）年報酬 < 算術平均年報酬。
  3. 報酬順序風險：不同歷史起點 → 18 年結果是一個分布。

與 K1394（美股 SPY 版）互補：K1394 用美股看同一現象，K1395 換成台灣
家長更熟的 0050 / TWII，提供「台股觀點」。

資料現實（誠實處理）：
  - 0050.TW 自 2003 上市，但可靠日資料約 2009-01 起（yfinance 與專案
    既有 CSV 一致），到 2026-05 約 17.3 年 — 只夠「一個」近乎完整的
    18 年 DCA 窗口（取 0050 全可用區間當頭條真實案例）。
  - TWII（台股加權指數）自 1997-07 起，史料長很多。0050 是台股前 50 大、
    約 7 成市值，與 TWII 高度連動 → rolling 18 年窗口的分布分析改用 TWII
    當市場 proxy。文章與 README 明說此 proxy 安排，不假裝 0050 有長史料。

資料來源：
  - experiments/K1395/data/0050_tw_yfinance_snapshot.csv（yfinance 0050.TW，
    Adj Close 含息，2009-01-02 至 2026-05-21）
  - experiments/K1395/data/twii_yfinance_snapshot.csv（yfinance ^TWII，
    Adj Close，1997-07-02 至 2026-05-21）

資料修補（重要，誠實揭露）：
  yfinance 對 0050.TW 的 Adj Close 在 2014-01-02 出現一個假的 -75%
  斷點（2013-12-31=37.41 → 2014-01-02=9.33，比值約 0.2494）。0050 真實
  價格在 2013→2014 之間連續、無此跳水 — 這是 yfinance 對 0050.TW 套用
  幻影 4:1 分割造成的 back-adjustment bug（專案既有 CSV 同欄位亦同病）。
  TWII 無此問題。修補方式：把斷點之前所有 0050 價格乘以該斷點比值
  （0.249361），讓兩段序列在斷點處連續銜接 — 此 splice 不改變任一段
  內部的日報酬，只移除人為的不連續。修補後最大單日變動 16.5%（合理），
  2014 年報酬由 -68.5%（假）修正為 +26.2%（合理）。
  全程僅此一處斷點。修補邏輯在 load_0050_fixed()。

防錯：採月末投入時序 — 第 i 個月的投入以該月「月末」調整收盤價買進份額，
      估值時點為最後一筆投入的同一月末。每筆投入只承受其後月份的價格
      變化，不引用任何未來資訊 — 無 lookahead（signal at t-1 不適用於
      純 DCA，因投入用當期收盤、估值在未來；此處明確：投入價 = 當月末，
      估值價 = 視窗最後月末，無任何 forward leak）。
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
CSV_0050 = HERE / "data" / "0050_tw_yfinance_snapshot.csv"
CSV_TWII = HERE / "data" / "twii_yfinance_snapshot.csv"

MONTHLY_CONTRIB = 5000.0  # 新台幣 / 月
HOLD_YEARS = 18
HOLD_MONTHS = HOLD_YEARS * 12
INFLATION_ANNUAL = 0.02  # 台灣長期通膨約 2%/年；實質終值用此折現
TEXTBOOK_RATE = 0.06  # 坊間「平滑 6%」對照


SPLICE_DETECT_THRESHOLD = 0.35  # 單日 |報酬| 超過此值視為可疑斷點


def _to_monthly(df, diag):
    """日序列（欄位 price）轉月末序列。"""
    df["ym"] = df["date"].dt.to_period("M")
    monthly = df.groupby("ym").last().reset_index()
    monthly["month_start"] = monthly["ym"].dt.to_timestamp()
    monthly = monthly[["ym", "month_start", "price"]].reset_index(drop=True)
    diag["monthly_rows"] = int(len(monthly))
    return monthly, diag


def load_monthly(csv_path, col):
    """讀調整收盤價，轉成月末序列；回傳 (monthly_df, diagnostics)。"""
    df = pd.read_csv(csv_path, parse_dates=["date"])
    df = df[["date", col]].dropna()
    df = df.sort_values("date").reset_index(drop=True)
    diag = {
        "raw_daily_rows": int(len(df)),
        "date_min": df["date"].min().strftime("%Y-%m-%d"),
        "date_max": df["date"].max().strftime("%Y-%m-%d"),
        "missing_values": int(df[col].isna().sum()),
    }
    df = df.rename(columns={col: "price"})
    return _to_monthly(df, diag)


def load_0050_fixed():
    """
    讀 0050.TW，修補 yfinance 在 2014-01-02 的幻影 4:1 分割斷點。

    偵測：掃日報酬，|ret| > SPLICE_DETECT_THRESHOLD 視為人為斷點。
    修補：把斷點之前的所有價格乘以斷點當日的「跌幅比值」(cur/prev)，
          使兩段序列在斷點處連續。此 splice 保留每一段內部的日報酬，
          只移除人為不連續，不引入任何 lookahead（純歷史資料清洗）。
    回傳 (monthly_df, diagnostics)；diagnostics 記錄修補細節供審查。
    """
    df = pd.read_csv(CSV_0050, parse_dates=["date"])
    df = df[["date", "t0050_adj_close"]].dropna()
    df = df.sort_values("date").reset_index(drop=True)
    raw_rows = int(len(df))
    df = df.rename(columns={"t0050_adj_close": "price"})

    ret = df["price"].pct_change()
    bad_idx = list(ret.index[ret.abs() > SPLICE_DETECT_THRESHOLD])
    splices = []
    for idx in bad_idx:
        prev = float(df.loc[idx - 1, "price"])
        cur = float(df.loc[idx, "price"])
        factor = cur / prev
        df.loc[: idx - 1, "price"] = df.loc[: idx - 1, "price"] * factor
        splices.append(
            {
                "date": df.loc[idx, "date"].strftime("%Y-%m-%d"),
                "raw_prev": prev,
                "raw_next": cur,
                "splice_factor": factor,
            }
        )

    diag = {
        "raw_daily_rows": raw_rows,
        "date_min": df["date"].min().strftime("%Y-%m-%d"),
        "date_max": df["date"].max().strftime("%Y-%m-%d"),
        "missing_values": 0,
        "splice_corrections": splices,
        "max_daily_return_after_fix": float(df["price"].pct_change().abs().max()),
    }
    return _to_monthly(df, diag)


def simulate_dca(prices):
    """
    對一段月末價格序列跑月頻 DCA。

    時序定義（明確、內部一致、無 lookahead）：
      - prices[i] = 第 i 個月「月末」的調整收盤價（i = 0 .. len-1）。
      - 第 i 個月的投入發生在該月月末，以 prices[i] 買進份額。
      - 估值時點為 prices[-1]（最後一筆投入的同一月末）。
      - 第 i 筆投入被持有 (len-1 - i) 個月，最後一筆持有 0 個月。
        最後一筆當月零報酬 — 月末定投的標準保守設定，無 forward leak。
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
    終值贖回在 t=months-1。第 i 筆折現期數 = (months-1 - i)。
    """

    def npv(r):
        v = sum(-monthly_contrib / (1 + r) ** t for t in range(months))
        v += final_value / (1 + r) ** (months - 1)
        return v

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
    return (1 + monthly_irr) ** 12 - 1


def market_level_stats(monthly):
    """以日曆年聚合的完整年份報酬序列，算算術/幾何年報酬與波動。"""
    m = monthly.copy()
    m["ret"] = m["price"].pct_change()
    m["year"] = m["ym"].dt.year
    yearly = (
        m.dropna(subset=["ret"])
        .groupby("year")
        .agg(n=("ret", "size"), gross=("ret", lambda s: float(np.prod(1 + s))))
    )
    full_years = yearly[yearly["n"] == 12].copy()
    annual_rets = full_years["gross"].to_numpy() - 1.0
    arith = float(np.mean(annual_rets))
    geo = float(np.exp(np.mean(np.log(1 + annual_rets))) - 1)
    annual_vol = float(np.std(annual_rets, ddof=1))
    monthly_ret = m["ret"].dropna().to_numpy()
    monthly_vol_ann = float(np.std(monthly_ret, ddof=1) * np.sqrt(12))
    return {
        "definition": "算術/幾何年報酬以日曆年聚合的完整年份報酬序列計算",
        "n_full_calendar_years": int(len(annual_rets)),
        "full_year_range": f"{int(full_years.index.min())}-{int(full_years.index.max())}",
        "sample_monthly_returns": int(len(monthly_ret)),
        "arithmetic_annual_return": arith,
        "geometric_annual_return": geo,
        "volatility_drag_annual": arith - geo,
        "volatility_drag_bp": (arith - geo) * 1e4,
        "annual_return_volatility": annual_vol,
        "monthly_return_volatility_annualized": monthly_vol_ann,
    }


def main():
    # ===== 讀資料 =====
    m0050, diag0050 = load_0050_fixed()
    mtwii, diagtwii = load_monthly(CSV_TWII, "twii_adj_close")

    # ===== 頭條真實案例：0050 全可用區間的單一 DCA 窗口 =====
    # 0050 史料 2009-01 起，到 2026-05 約 17.3 年 — 取全區間當「最接近一個
    # 完整 18 年」的真實頭條案例。誠實標明實際年數 < 18。
    p0050 = m0050["price"].to_numpy()
    n0050 = len(p0050)
    real_years = round((n0050 - 1) / 12, 2)
    fn0050, inv0050, path0050 = simulate_dca(p0050)
    real0050 = fn0050 / (1 + INFLATION_ANNUAL) ** real_years
    irr0050 = money_weighted_irr(fn0050, MONTHLY_CONTRIB, n0050)
    headline = {
        "asset": "0050.TW（元大台灣 50 ETF，Adj Close 含息）",
        "start_ym": str(m0050["ym"].iloc[0]),
        "end_ym": str(m0050["ym"].iloc[-1]),
        "months": int(n0050),
        "years": real_years,
        "monthly_contribution": MONTHLY_CONTRIB,
        "total_invested": float(inv0050),
        "final_nominal": float(fn0050),
        "final_real_2pct_inflation": float(real0050),
        "money_weighted_annual_return": float(irr0050),
        "multiple_nominal": float(fn0050 / inv0050),
        "note": (
            "0050 可靠日資料自 2009-01 起，全區間約 17.3 年，略短於完整 18 年；"
            "此為 0050 史料能支撐的最長單一真實 DCA 窗口"
        ),
    }

    # ===== 波動拖累：0050 與 TWII 兩邊都算 =====
    market_0050 = market_level_stats(m0050)
    market_twii = market_level_stats(mtwii)

    # ===== 報酬順序風險：用 TWII 跑所有可行 18 年 rolling 起點 =====
    ptwii = mtwii["price"].to_numpy()
    months_avail = len(ptwii)
    n_windows = months_avail - HOLD_MONTHS + 1
    results = []
    for start in range(n_windows):
        seg = ptwii[start : start + HOLD_MONTHS]
        final_nom, invested, _ = simulate_dca(seg)
        final_real = final_nom / (1 + INFLATION_ANNUAL) ** HOLD_YEARS
        irr = money_weighted_irr(final_nom, MONTHLY_CONTRIB, HOLD_MONTHS)
        results.append(
            {
                "start_ym": str(mtwii["ym"].iloc[start]),
                "end_ym": str(mtwii["ym"].iloc[start + HOLD_MONTHS - 1]),
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

    r_m = TEXTBOOK_RATE / 12
    textbook_final = MONTHLY_CONTRIB * (((1 + r_m) ** HOLD_MONTHS - 1) / r_m)

    def pct(a, q):
        return float(np.percentile(a, q))

    worst = min(results, key=lambda r: r["final_nominal"])
    best = max(results, key=lambda r: r["final_nominal"])
    median_w = sorted(results, key=lambda r: r["final_nominal"])[len(results) // 2]

    dist = {
        "proxy_note": (
            "rolling 18 年分布用 TWII（台股加權指數）— 0050 史料僅 17.3 年不足"
            "支撐多個 18 年窗口；0050 為台股前 50 大、約 7 成市值，與 TWII 高度連動"
        ),
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
        "best_worst_ratio": float(finals_nom.max() / finals_nom.min()),
        "worst_window": worst,
        "best_window": best,
        "median_window": median_w,
    }

    out = {
        "experiment_id": "K1395",
        "title": "兒少 TISA 的複利幻覺（台股版）：0050.TW 真實窗口 + TWII 波動拖累與報酬順序風險",
        "seed": SEED,
        "data_sources": {
            "0050_tw": "experiments/K1395/data/0050_tw_yfinance_snapshot.csv",
            "twii": "experiments/K1395/data/twii_yfinance_snapshot.csv",
        },
        "data_diagnostics": {"0050_tw": diag0050, "twii": diagtwii},
        "headline_0050_real_window": headline,
        "market_level_0050": market_0050,
        "market_level_twii": market_twii,
        "rolling_dca_twii": dist,
        "caveats": [
            "0050.TW 的 yfinance Adj Close 在 2014-01-02 有一個假的 -75% 斷點"
            "（幻影 4:1 分割 back-adjustment bug）；本實驗以 splice 修補（斷點前"
            "價格乘 0.249361），詳見 data_diagnostics.0050_tw.splice_corrections。"
            "修補僅移除人為不連續，不改各段內部日報酬。",
            "0050.TW 可靠日資料自 2009-01 起，全區間約 17.3 年，僅夠 1 個近乎完整"
            "的 18 年窗口；rolling 18 年分布因此改用史料較長（1997 起）的 TWII。",
            "TWII 為台股加權指數，0050 約佔台股 7 成市值、與 TWII 高度連動，"
            "但 TWII 不含息（指數），0050 含息 — 兩者報酬口徑略有差異。",
            "0050 Adj Close 含股息再投資，未扣交易成本、台股交易稅（賣出 0.3%）"
            "與經理費。",
            "歷史回測，過去報酬不保證未來。",
            "實質終值以期末通膨一次折現，為保守購買力視角；若以投入時點分別"
            "折現，實質值會略高。",
            "rolling 視窗高度重疊（相鄰起點僅差一個月），分布極端值由少數獨立"
            "18 年段落驅動，非獨立樣本 — 視為情境涵蓋而非統計推論。",
        ],
    }

    res_path = HERE / "K1395_results.json"
    with open(res_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"wrote {res_path}")

    # ============ 圖表 1：TWII 18 年終值分布直方圖 ============
    fig, ax = plt.subplots(figsize=(9, 5.2))
    ax.hist(finals_nom / 1e6, bins=20, color="#3b6ea5", edgecolor="white", alpha=0.9)
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
        f"每月定額 5,000 元投入台股加權指數、持有 18 年\n"
        f"{n_windows} 個歷史起點的終值分布（總投入 {invested_total/1e6:.2f} 百萬）"
    )
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    p1 = HERE / "K1395_final_value_distribution.png"
    fig.savefig(p1, dpi=130)
    plt.close(fig)
    print(f"wrote {p1}")

    # ============ 圖表 2：真實路徑 vs 平滑曲線 ============
    fig, ax = plt.subplots(figsize=(9, 5.2))
    months_axis = np.arange(1, HOLD_MONTHS + 1)
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
    labelmap = {
        "worst_window": ("最差起點", "#7f8c8d"),
        "median_window": ("中位起點", "#2980b9"),
        "best_window": ("最佳起點", "#16a085"),
    }
    for key, (lab, color) in labelmap.items():
        w = dist[key]
        s = mtwii[mtwii["ym"].astype(str) == w["start_ym"]].index[0]
        seg = ptwii[s : s + HOLD_MONTHS]
        _, _, path = simulate_dca(seg)
        ax.plot(
            months_axis / 12,
            path / 1e6,
            color=color,
            linewidth=1.8,
            label=f"{lab}（{w['start_ym']} 起，台股加權指數）",
        )
    # 0050 真實頭條窗口（17.3 年，畫到實際年數為止）
    axis_0050 = np.arange(1, n0050 + 1) / 12
    ax.plot(
        axis_0050,
        path0050 / 1e6,
        color="#e67e22",
        linewidth=2.0,
        linestyle="-.",
        label=f"0050.TW 真實窗口（{headline['start_ym']} 起，{real_years} 年）",
    )
    ax.set_xlabel("投入年數")
    ax.set_ylabel("組合市值（新台幣百萬元）")
    ax.set_title("教科書畫的是直線，台股走的是顛簸路徑")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    p2 = HERE / "K1395_path_vs_smooth.png"
    fig.savefig(p2, dpi=130)
    plt.close(fig)
    print(f"wrote {p2}")

    # ---- console 摘要 ----
    print("\n=== 頭條：0050.TW 真實窗口 ===")
    print(
        f"{headline['start_ym']}→{headline['end_ym']} ({real_years} 年), "
        f"投入 {inv0050:,.0f} → 名目 {fn0050:,.0f} / 實質 {real0050:,.0f}"
    )
    print(f"金額加權年報酬 {irr0050:.4%}, 倍數 {fn0050/inv0050:.2f}x")
    print("\n=== 波動拖累 ===")
    print(
        f"0050: 算術 {market_0050['arithmetic_annual_return']:.4%} / "
        f"幾何 {market_0050['geometric_annual_return']:.4%} / "
        f"拖累 {market_0050['volatility_drag_bp']:.0f} bp"
    )
    print(
        f"TWII: 算術 {market_twii['arithmetic_annual_return']:.4%} / "
        f"幾何 {market_twii['geometric_annual_return']:.4%} / "
        f"拖累 {market_twii['volatility_drag_bp']:.0f} bp"
    )
    print("\n=== TWII 18 年 rolling DCA（名目終值）===")
    print(f"視窗數 {n_windows}, 總投入 {invested_total:,.0f}")
    fn = dist["final_nominal"]
    print(f"min {fn['min']:,.0f} / median {fn['median']:,.0f} / max {fn['max']:,.0f}")
    print(f"最佳/最差倍數差 {dist['best_worst_ratio']:.2f}x")
    print(f"worst: {worst['start_ym']}→{worst['end_ym']}")
    print(f"best : {best['start_ym']}→{best['end_ym']}")
    print(f"坊間平滑 6% 終值 {textbook_final:,.0f}")


if __name__ == "__main__":
    main()
