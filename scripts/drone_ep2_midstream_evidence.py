#!/usr/bin/env python3
"""建立無人載具 EP2 中游公司的可複現證據包與三張真實圖表。

數字來源固定為 yfinance 的還原收盤價與年度損益表；公司與無人機的
關聯分類則逐筆附公開來源。程式不把「具備相鄰製程」推論成已取得訂單，
也不把公司整體營收當成無人機營收。

輸出：
  storage/drafts/drone_ep2_midstream_evidence.json
  storage/drafts/assets/drone_ep2_price_paths.png
  storage/drafts/assets/drone_ep2_risk_return.png
  storage/drafts/assets/drone_ep2_fundamentals.png
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from matplotlib.colors import TwoSlopeNorm


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "storage" / "drafts" / "assets"
OUT_JSON = ROOT / "storage" / "drafts" / "drone_ep2_midstream_evidence.json"

START = "2025-06-30"
END_EXCLUSIVE = "2026-07-11"
BENCHMARK = "^TWII"
TRADING_DAYS = 252

plt.rcParams["font.family"] = "Heiti TC"
plt.rcParams["axes.unicode_minus"] = False


# linkage_stage 是公開揭露強度，不是投資評等。每筆都保留來源與限制。
COMPANIES: list[dict[str, Any]] = [
    {
        "name": "碳基",
        "ticker": "7719.TWO",
        "segment": "複材／機體",
        "linkage_stage": "直接產品／製造",
        "evidence": "公司官網明列無人機配件、複材零組件與無人飛行載具機體製造。",
        "source_url": "https://www.uaver.com/?lang=tw",
        "visibility": "有直接產品證據；未見無人機營收占比或具約束力訂單金額拆分。",
    },
    {
        "name": "永虹先進",
        "ticker": "6618.TWO",
        "segment": "複材／機體",
        "linkage_stage": "共同開發／意向",
        "evidence": "公司具航太級碳纖複材能力；2026-01 公告 Cougar 無人機共同開發採購意向書。",
        "source_url": "https://www.uht.com.tw/zh-tw/news",
        "secondary_source_url": "https://goodinfo.tw/tw/StockAnnounceDetail.asp?CLAIM_TIME=2026%2F01%2F12+19%3A20%3A52&STOCK_ID=6618&SUBJECT=%E3%80%8CCougar%E7%84%A1%E4%BA%BA%E6%A9%9F%E3%80%8D%E5%85%B1%E5%90%8C%E9%96%8B%E7%99%BC%E6%8E%A1%E8%B3%BC%E5%90%88%E7%B4%84%E6%84%8F%E5%90%91%E6%9B%B8",
        "visibility": "意向書不等於具約束力主合約；未見營收占比或確定訂單金額。",
    },
    {
        "name": "加百裕",
        "ticker": "3323.TWO",
        "segment": "電池／能源",
        "linkage_stage": "相鄰能力",
        "evidence": "公司公開電動載具鋰電池組、BMS 與安全認證能力，但查核頁面未單列無人機。",
        "source_url": "https://zh-tw.celxpert.com.tw/e-mobility",
        "visibility": "只能確認電池模組能力；不可由此推論無人機訂單或營收。",
    },
    {
        "name": "系統電",
        "ticker": "5309.TWO",
        "segment": "電池／系統",
        "linkage_stage": "直接產品／合作",
        "evidence": "公司法說揭露自主 X-DRONE、Vantage Robotics 與 Quantum Systems 合作及在地化角色。",
        "source_url": "https://www.sysgration.com/uploads/investor-conference-information/TW/Sysgration_Investor_Presentation_TW_20251212.pdf",
        "visibility": "工業電腦產品線包含無人機，但未單獨拆出無人機營收與訂單金額。",
    },
    {
        "name": "力山",
        "ticker": "1515.TW",
        "segment": "馬達／動力",
        "linkage_stage": "開發／展會",
        "evidence": "公司法說把無人機列入機電新事業，並揭露參與海外無人機展。",
        "source_url": "https://www.rexon.net/data/report/1724806778FCBF1.pdf",
        "visibility": "屬新事業布局；未見無人機營收占比、客戶或確定訂單金額。",
    },
    {
        "name": "富田",
        "ticker": "4590.TW",
        "segment": "馬達／動力",
        "linkage_stage": "開始出貨",
        "evidence": "公司公開開發高扭矩密度小型馬達；公司主管表示無人機馬達已開始對台灣客戶出貨。",
        "source_url": "https://www.fukuta-motor.com.tw/images/csr/2024-FUKUTA-ESG_Report-tw.pdf",
        "secondary_source_url": "https://www.cna.com.tw/news/afe/202411040177.aspx",
        "visibility": "有出貨敘述，但未公開無人機馬達營收金額或客戶集中度。",
    },
    {
        "name": "寶一",
        "ticker": "8222.TW",
        "segment": "航太精密件",
        "linkage_stage": "航太相鄰能力",
        "evidence": "公司官網可確認航太引擎零件、超合金與鈦合金加工及長期民航客戶。",
        "source_url": "https://www.aerowin.com/Content_Layout.php?Id=p1-1",
        "visibility": "官方頁面未把既有長約拆成無人機用途；不可直接列為無人機訂單。",
    },
    {
        "name": "晟田",
        "ticker": "4541.TWO",
        "segment": "航太精密件",
        "linkage_stage": "航太相鄰能力",
        "evidence": "公司法說產品含發動機、起落架、飛控致動器與航太精密零件。",
        "source_url": "https://maicl.com/upload/sponsor/2024062010004194.pdf",
        "visibility": "公開資料未拆出無人機用途營收或訂單；本文只視為可轉用製程。",
    },
]

SEGMENT_COLORS = {
    "複材／機體": "#2E6F9E",
    "電池／能源": "#16847A",
    "電池／系統": "#36A29A",
    "馬達／動力": "#C8872E",
    "航太精密件": "#7A5FA3",
}


def require_number(value: Any, label: str) -> float:
    """拒絕缺值、布林與非有限數字，避免畫圖時靜默跳過。"""
    if isinstance(value, bool) or not isinstance(value, (int, float, np.number)):
        raise TypeError(f"{label} must be numeric, got {type(value).__name__}")
    result = float(value)
    if not np.isfinite(result):
        raise ValueError(f"{label} must be finite, got {result}")
    return result


def fetch_prices(tickers: list[str]) -> pd.DataFrame:
    raw = yf.download(
        tickers,
        start=START,
        end=END_EXCLUSIVE,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
    )
    prices: dict[str, pd.Series] = {}
    for ticker in tickers:
        try:
            series = raw[ticker]["Close"]
        except (KeyError, TypeError):
            series = raw["Close"][ticker]
        series = series.dropna()
        if series.empty:
            raise ValueError(f"No adjusted close data for {ticker}")
        prices[ticker] = series
    frame = pd.DataFrame(prices)
    common = frame.dropna()
    if len(common) < 80:
        raise ValueError(f"Common price window too short: {len(common)} observations")
    return common


def financial_value(financials: pd.DataFrame, key: str, column: Any, ticker: str) -> float:
    if key not in financials.index:
        raise KeyError(f"{ticker} annual income statement missing {key}")
    value = financials.loc[key, column]
    if pd.isna(value):
        raise ValueError(f"{ticker} {key} is missing for {column}")
    return require_number(value, f"{ticker}.{key}.{column}")


def annual_financials(ticker: str) -> dict[str, Any]:
    financials = yf.Ticker(ticker).financials
    if financials is None or financials.empty or len(financials.columns) < 2:
        raise ValueError(f"{ticker} requires at least two annual income statements")
    columns = sorted(financials.columns, reverse=True)[:3]
    by_year: dict[str, dict[str, float]] = {}
    for column in columns:
        year = str(pd.Timestamp(column).year)
        revenue = financial_value(financials, "Total Revenue", column, ticker)
        gross_profit = financial_value(financials, "Gross Profit", column, ticker)
        operating_income = financial_value(financials, "Operating Income", column, ticker)
        net_income = financial_value(financials, "Net Income", column, ticker)
        if revenue <= 0:
            raise ValueError(f"{ticker} revenue must be positive for {year}")
        by_year[year] = {
            "revenue": revenue,
            "gross_profit": gross_profit,
            "operating_income": operating_income,
            "net_income": net_income,
            "gross_margin": gross_profit / revenue,
            "operating_margin": operating_income / revenue,
        }
    years = sorted(by_year, reverse=True)
    latest, previous = years[0], years[1]
    return {
        "latest_fy": int(latest),
        "previous_fy": int(previous),
        "revenue_yoy": by_year[latest]["revenue"] / by_year[previous]["revenue"] - 1.0,
        "by_year": by_year,
    }


def pct_text(value: float) -> str:
    return f"{value * 100:+.1f}%"


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    tickers = [row["ticker"] for row in COMPANIES]
    prices = fetch_prices(tickers + [BENCHMARK])
    log_returns = np.log(prices).diff().dropna()

    rows: list[dict[str, Any]] = []
    for meta in COMPANIES:
        ticker = meta["ticker"]
        series = prices[ticker]
        returns = log_returns[ticker]
        financials = annual_financials(ticker)
        row = dict(meta)
        row.update(
            {
                "price_start": require_number(series.iloc[0], f"{ticker}.price_start"),
                "price_end": require_number(series.iloc[-1], f"{ticker}.price_end"),
                "common_window_return": require_number(
                    series.iloc[-1] / series.iloc[0] - 1.0,
                    f"{ticker}.common_window_return",
                ),
                "annualized_volatility": require_number(
                    returns.std() * np.sqrt(TRADING_DAYS),
                    f"{ticker}.annualized_volatility",
                ),
                **financials,
            }
        )
        rows.append(row)

    frame = pd.DataFrame(rows)
    basket_log_return = log_returns[tickers].mean(axis=1)
    basket_return = float(np.expm1(basket_log_return.sum()))
    basket_vol = float(basket_log_return.std() * np.sqrt(TRADING_DAYS))
    benchmark_return = float(prices[BENCHMARK].iloc[-1] / prices[BENCHMARK].iloc[0] - 1.0)
    benchmark_vol = float(log_returns[BENCHMARK].std() * np.sqrt(TRADING_DAYS))

    stage_counts = frame["linkage_stage"].value_counts().to_dict()
    direct_stages = {"直接產品／製造", "直接產品／合作", "開始出貨"}
    development_stages = {"共同開發／意向", "開發／展會"}
    n_direct = int(frame["linkage_stage"].isin(direct_stages).sum())
    n_development = int(frame["linkage_stage"].isin(development_stages).sum())
    n_adjacent = int(len(frame) - n_direct - n_development)
    n_positive_revenue_growth = int((frame["revenue_yoy"] > 0).sum())
    n_operating_loss = int(
        sum(row["by_year"][str(row["latest_fy"])]["operating_margin"] < 0 for row in rows)
    )

    summary = {
        "n_companies": int(len(frame)),
        "n_direct_product_or_shipment": n_direct,
        "n_development_or_intent": n_development,
        "n_adjacent_capability_only": n_adjacent,
        "n_with_separately_disclosed_uav_revenue_share": 0,
        "n_with_public_binding_uav_order_value_in_checked_sources": 0,
        "n_positive_revenue_growth": n_positive_revenue_growth,
        "n_operating_loss": n_operating_loss,
        "median_revenue_yoy": float(frame["revenue_yoy"].median()),
        "median_operating_margin": float(
            np.median(
                [row["by_year"][str(row["latest_fy"])]["operating_margin"] for row in rows]
            )
        ),
        "basket_return_common_window": basket_return,
        "basket_annualized_volatility": basket_vol,
        "twii_return_common_window": benchmark_return,
        "twii_annualized_volatility": benchmark_vol,
        "return_gap_basket_minus_twii": basket_return - benchmark_return,
        "stage_counts": stage_counts,
    }

    payload = {
        "generated_at_tw": datetime.now(timezone(timedelta(hours=8))).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "price_window_requested": {"start": START, "end_exclusive": END_EXCLUSIVE},
        "price_window_common": {
            "start": prices.index[0].strftime("%Y-%m-%d"),
            "end": prices.index[-1].strftime("%Y-%m-%d"),
            "observations": int(len(prices)),
            "reason": "公平比較採所有標的與加權指數都有還原收盤價的日期交集。",
        },
        "data_source": (
            "yfinance adjusted close (auto_adjust=True) and annual income statement; "
            "company linkage statements use the per-row public source URLs"
        ),
        "method": {
            "return": "common-window adjusted-close total return",
            "volatility": "daily log-return standard deviation * sqrt(252)",
            "basket": "eight-stock equal-weight daily log-return basket, rebalanced daily",
            "financials": "latest two annual income statements available from yfinance",
            "disclosure_classification": (
                "公開揭露強度的描述性分類；直接產品／合作／出貨、開發／意向、相鄰能力三層。"
            ),
            "caveat": (
                "公司整體營收與股價不可解讀為無人機業務表現；未單獨揭露的營收占比與訂單金額一律不估。"
            ),
        },
        "summary": summary,
        "companies": rows,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT_JSON}")

    # 圖一：共同窗口的還原價格路徑。只畫真實市場資料，不畫主觀分類。
    normalized = prices / prices.iloc[0] * 100.0
    fig, ax = plt.subplots(figsize=(12, 7.2))
    for row in rows:
        ax.plot(
            normalized.index,
            normalized[row["ticker"]],
            linewidth=1.5,
            alpha=0.82,
            label=row["name"],
        )
    ax.plot(
        normalized.index,
        normalized[BENCHMARK],
        color="#111111",
        linewidth=2.8,
        linestyle="--",
        label="加權指數",
    )
    ax.axhline(100, color="#999999", linewidth=0.8)
    ax.set_title("無人載具中游 8 檔：共同窗口還原價格路徑")
    ax.set_ylabel("起點 = 100")
    ax.grid(alpha=0.22)
    ax.legend(ncol=3, fontsize=9, loc="best")
    fig.text(
        0.01,
        0.01,
        f"資料：yfinance｜共同窗口 {prices.index[0]:%Y-%m-%d}～{prices.index[-1]:%Y-%m-%d}",
        fontsize=9,
        color="#555555",
    )
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    path = ASSETS / "drone_ep2_price_paths.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    print(f"wrote {path}")

    # 圖二：同期間報酬與波動，泡泡大小固定，避免用缺乏一致性的市值欄位。
    fig, ax = plt.subplots(figsize=(11.5, 7.2))
    for segment, group in frame.groupby("segment"):
        ax.scatter(
            group["annualized_volatility"] * 100,
            group["common_window_return"] * 100,
            s=150,
            color=SEGMENT_COLORS[segment],
            alpha=0.9,
            edgecolors="white",
            linewidths=1.2,
            label=segment,
        )
    for _, row in frame.iterrows():
        ax.annotate(
            row["name"],
            (row["annualized_volatility"] * 100, row["common_window_return"] * 100),
            xytext=(6, 5),
            textcoords="offset points",
            fontsize=9.5,
        )
    ax.axhline(benchmark_return * 100, color="#B84A4A", linestyle="--", linewidth=1.4)
    ax.axvline(benchmark_vol * 100, color="#B84A4A", linestyle=":", linewidth=1.4)
    ax.set_xlabel("年化波動率（%）")
    ax.set_ylabel("共同窗口報酬（%）")
    ax.set_title("報酬與風險沒有跟供應鏈標籤排隊")
    ax.grid(alpha=0.22)
    ax.legend(fontsize=9)
    fig.text(
        0.01,
        0.01,
        f"紅線：同期加權指數，報酬 {pct_text(benchmark_return)}、年化波動 {benchmark_vol*100:.1f}%",
        fontsize=9,
        color="#555555",
    )
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    path = ASSETS / "drone_ep2_risk_return.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    print(f"wrote {path}")

    # 圖三：年度財報的兩個尺度。色階限制在 ±100 個百分點，但每格標出真實值；
    # 早期公司可能因極小營收基數出現數百%的比率，不能截斷數字或讓它壓扁全圖。
    plot = frame.sort_values("revenue_yoy", ascending=False)
    latest_operating_margin = [
        row["by_year"][str(row["latest_fy"])]["operating_margin"] for row in rows
    ]
    margin_by_name = {row["name"]: margin for row, margin in zip(rows, latest_operating_margin)}
    margins = np.array([margin_by_name[name] for name in plot["name"]])
    heat = np.column_stack([plot["revenue_yoy"].to_numpy() * 100, margins * 100])
    fig, ax = plt.subplots(figsize=(10.5, 7.4))
    image = ax.imshow(
        heat,
        cmap="RdYlGn",
        norm=TwoSlopeNorm(vmin=-100, vcenter=0, vmax=100),
        aspect="auto",
    )
    ax.set_yticks(np.arange(len(plot)))
    ax.set_yticklabels(plot["name"])
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["最新年度營收年增率", "最新年度營業利益率"])
    for row_index in range(heat.shape[0]):
        for column_index in range(heat.shape[1]):
            value = heat[row_index, column_index]
            ax.text(
                column_index,
                row_index,
                f"{value:+.1f}%",
                ha="center",
                va="center",
                color="white" if abs(value) >= 45 else "#17212B",
                fontweight="bold",
                fontsize=11,
            )
    colorbar = fig.colorbar(image, ax=ax, fraction=0.05, pad=0.04)
    colorbar.set_label("色階（百分點；超過 ±100 以端點色顯示）")
    ax.set_title("中游 8 檔財報：能力相鄰，不保證成長同步")
    fig.text(
        0.01,
        0.01,
        "資料：yfinance 年度損益表；格內為完整真值，色階封頂不截斷數字。公司整體財報不等於無人機業務財報。",
        fontsize=9,
        color="#555555",
    )
    fig.tight_layout(rect=(0, 0.035, 1, 0.96))
    path = ASSETS / "drone_ep2_fundamentals.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    print(f"wrote {path}")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
