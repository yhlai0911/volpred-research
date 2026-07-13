#!/usr/bin/env python3
"""建立無人載具 EP3 下游公司的可複現證據包與三張真實圖表。

行情與年度財務數字一律從 yfinance 讀取；政策狀態及公司揭露逐筆附官方
來源。公開資料若沒有無人載具營收占比或具約束力訂單金額，就明確記為
未揭露，不用公司整體營收、訂單或供應商資格代替。

輸出：
  storage/drafts/drone_ep3_downstream_evidence.json
  storage/drafts/assets/drone_ep3_price_paths.png
  storage/drafts/assets/drone_ep3_risk_return.png
  storage/drafts/assets/drone_ep3_disclosure_ladder.png
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


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "storage" / "drafts" / "assets"
OUT_JSON = ROOT / "storage" / "drafts" / "drone_ep3_downstream_evidence.json"

START = "2025-06-30"
END_EXCLUSIVE = "2026-07-11"
BENCHMARK = "^TWII"
TRADING_DAYS = 252

plt.rcParams["font.family"] = "Heiti TC"
plt.rcParams["axes.unicode_minus"] = False


# highest_public_stage 是截至 2026-07-13 查得的最高公開證據層級，不是
# 投資評等。三個層級互斥，避免把資格、原型與量產混成同一件事。
COMPANIES: list[dict[str, Any]] = [
    {
        "name": "雷虎",
        "ticker": "8033.TW",
        "segment": "空中載具整合",
        "highest_public_stage": "直接產品／原型／合作",
        "stage_group": "產品、原型或合作",
        "evidence": "官網列有空中、陸上與水面無人系統；漢翔揭露雙方共同開發 T-400 原型機。",
        "source_urls": [
            "https://www.thundertiger.com/tw/index.html",
            "https://www.aidc.com.tw/tw/news/618",
        ],
        "visibility": "可確認產品與原型合作；查核來源未揭露具約束力訂單金額或無人載具營收占比。",
    },
    {
        "name": "漢翔",
        "ticker": "2634.TW",
        "segment": "空中載具整合",
        "highest_public_stage": "共同開發／量產規劃",
        "stage_group": "產品、原型或合作",
        "evidence": "公司揭露 T-400、AIxVNAV、V-BAT 等合作，以及建立量產基地的規劃。",
        "source_urls": [
            "https://www.aidc.com.tw/tw/military/drone",
            "https://www.aidc.com.tw/tw/news/13638",
            "https://www.aidc.com.tw/tw/news/618",
        ],
        "visibility": "公司整體在手訂單不等於無人機訂單；查核來源未拆分無人載具營收或具約束力訂單金額。",
    },
    {
        "name": "亞航",
        "ticker": "2630.TW",
        "segment": "組裝／維修",
        "highest_public_stage": "組裝／維修能力",
        "stage_group": "資格或能力",
        "evidence": "年報揭露光纖陀螺儀契約生產、無人機組裝能力與無人機維修布局。",
        "source_urls": [
            "https://www.airasia.com.tw/userfiles/03.Investor_Relations/%E4%BA%9E%E8%88%AA114%E5%B9%B4%E5%A0%B1.pdf"
        ],
        "visibility": "能力與既有軍機維修合約不能直接視為無人機訂單；未拆分無人載具營收。",
    },
    {
        "name": "長榮航太",
        "ticker": "2645.TW",
        "segment": "供應商／維修",
        "highest_public_stage": "供應商資格",
        "stage_group": "資格或能力",
        "evidence": "股東會手冊揭露已取得國防部軍商船用監偵型無人機供應商資格。",
        "source_urls": [
            "https://www.egat.com.tw/documents/290/EGAT-2025_Annual_General_Shareholders_Meeting_HandbookCh.pdf"
        ],
        "visibility": "取得資格不代表得標、交貨或認列營收；查核來源未揭露相關金額。",
    },
    {
        "name": "中光電",
        "ticker": "5371.TWO",
        "segment": "整機／光電酬載",
        "highest_public_stage": "量產／海外出貨",
        "stage_group": "量產或已交付",
        "evidence": "永續報告揭露取得軍用無人機採購案，並量產出貨熱顯像無人機至澳洲。",
        "source_urls": [
            "https://www.coretronic-robotics.com/index",
            "https://www.coretronic.com/en/csr/report/my5Aay/download/2024-Sustainability-Report_EN.pdf",
        ],
        "visibility": "可確認海外量產出貨；查核來源未拆分無人載具營收占比或具約束力訂單金額。",
    },
    {
        "name": "神基",
        "ticker": "3005.TW",
        "segment": "地面控制站",
        "highest_public_stage": "直接產品",
        "stage_group": "產品、原型或合作",
        "evidence": "公司 2026-03 發表 CommandCore，可控制 UAV、USV 與 UGV，並有完整地面站產品頁。",
        "source_urls": [
            "https://www.getac.com/us/news/getac-announces-commandcore-remote-drone-control-solution/",
            "https://www.getac.com/tw/products/laptops/Ground-Control-Stations/",
        ],
        "visibility": "可確認商用產品；查核來源未揭露無人載具營收占比或確定訂單金額。",
    },
    {
        "name": "融程電",
        "ticker": "3416.TW",
        "segment": "地面控制站",
        "highest_public_stage": "直接產品",
        "stage_group": "產品、原型或合作",
        "evidence": "公司公開 UAV 地面控制站，2026-05 再推出整合式 drone kit solution。",
        "source_urls": [
            "https://www.winmate.com/StaticPages/newsletter/News_UAV-ground-control_20230504_Winmate-HQ_Global-EN.html",
            "https://www.winmate.com/en/StaticPages/Newsletter/drone-kit-solution-20260528-News_Winmate-HQ_Global-EN.html",
        ],
        "visibility": "可確認商用產品；查核來源未揭露無人載具營收占比或確定訂單金額。",
    },
    {
        "name": "龍德造船",
        "ticker": "6753.TW",
        "segment": "無人艇",
        "highest_public_stage": "已交付",
        "stage_group": "量產或已交付",
        "evidence": "公司沿革明載已交付兩艘無人水面載具。",
        "source_urls": ["https://www.lungteh.com/zh/about-us"],
        "visibility": "可確認交付紀錄；頁面未揭露軍用小型自殺無人艇訂單或無人艇營收占比。",
    },
    {
        "name": "台船",
        "ticker": "2208.TW",
        "segment": "無人艇",
        "highest_public_stage": "原型／規劃",
        "stage_group": "產品、原型或合作",
        "evidence": "公司刊物收錄無人船原型與非紅供應鏈規劃。",
        "source_urls": [
            "https://www.csbcnet.com.tw/monthly_pub/files/009%E5%8F%B0%E8%88%B9%EF%BC%9A%E7%84%A1%E4%BA%BA%E8%88%B9%E4%BC%B0%E4%BB%8A%E5%B9%B4%E9%A6%96%E5%AD%A3%E4%BA%AE%E7%9B%B8%20100%E8%B6%B4%E5%8E%BB%E7%B4%85%E5%8C%96%E4%BE%9B%E6%87%89%E9%8F%88%281%29.pdf"
        ],
        "visibility": "屬原型與路線圖；查核來源未揭露具約束力軍用無人艇訂單金額。",
    },
    {
        "name": "中信造船",
        "ticker": "2644.TWO",
        "segment": "無人艇",
        "highest_public_stage": "原型／研發",
        "stage_group": "產品、原型或合作",
        "evidence": "公司公開中信五號智慧無人船，股東會手冊列出無人船研發投資。",
        "source_urls": [
            "https://www.jongshyn.com/news_info.asp?id=71",
            "https://www.jongshyn.com/upload/ckeditor/files/2_%E4%B8%AD%E4%BF%A1115%E5%B9%B4%E8%82%A1%E6%9D%B1%E5%B8%B8%E6%9C%83%E8%AD%B0%E4%BA%8B%E6%89%8B%E5%86%8A%E4%B8%8A%E5%82%B3%E7%89%88.pdf",
        ],
        "visibility": "可確認原型與研發；既有海巡船訂單不可視為無人艇訂單。",
    },
]

STAGE_ORDER = ["量產或已交付", "產品、原型或合作", "資格或能力"]
STAGE_COLORS = {
    "量產或已交付": "#16847A",
    "產品、原型或合作": "#2E6F9E",
    "資格或能力": "#A0A6AD",
}
SEGMENT_COLORS = {
    "空中載具整合": "#2E6F9E",
    "組裝／維修": "#7A5FA3",
    "供應商／維修": "#A06B9A",
    "整機／光電酬載": "#16847A",
    "地面控制站": "#C8872E",
    "無人艇": "#4D8B69",
}


def require_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.number)):
        raise TypeError(f"{label} must be numeric, got {type(value).__name__}")
    result = float(value)
    if not np.isfinite(result):
        raise ValueError(f"{label} must be finite, got {result}")
    return result


def validate_metadata() -> None:
    required = {
        "name", "ticker", "segment", "highest_public_stage", "stage_group",
        "evidence", "source_urls", "visibility",
    }
    for row in COMPANIES:
        missing = required - set(row)
        if missing:
            raise KeyError(f"{row.get('name', '<unknown>')} metadata missing {sorted(missing)}")
        if row["stage_group"] not in STAGE_ORDER:
            raise ValueError(f"Unknown stage_group for {row['name']}: {row['stage_group']}")
        if not row["source_urls"] or not all(str(url).startswith("https://") for url in row["source_urls"]):
            raise ValueError(f"{row['name']} requires at least one HTTPS source URL")


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
    frame = pd.DataFrame(prices).dropna()
    if len(frame) < 80:
        raise ValueError(f"Common price window too short: {len(frame)} observations")
    return frame


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


def main() -> None:
    validate_metadata()
    ASSETS.mkdir(parents=True, exist_ok=True)
    tickers = [row["ticker"] for row in COMPANIES]
    prices = fetch_prices(tickers + [BENCHMARK])
    log_returns = np.log(prices).diff().dropna()

    rows: list[dict[str, Any]] = []
    for meta in COMPANIES:
        ticker = meta["ticker"]
        series = prices[ticker]
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
                    log_returns[ticker].std() * np.sqrt(TRADING_DAYS),
                    f"{ticker}.annualized_volatility",
                ),
                "separate_uav_usv_revenue_share_disclosed": False,
                "binding_uav_usv_order_value_disclosed": False,
                **financials,
            }
        )
        rows.append(row)

    frame = pd.DataFrame(rows)
    basket_log_return = log_returns[tickers].mean(axis=1)
    benchmark_return = float(prices[BENCHMARK].iloc[-1] / prices[BENCHMARK].iloc[0] - 1.0)
    benchmark_vol = float(log_returns[BENCHMARK].std() * np.sqrt(TRADING_DAYS))
    stage_counts = {stage: int((frame["stage_group"] == stage).sum()) for stage in STAGE_ORDER}
    summary = {
        "n_companies": int(len(frame)),
        "n_mass_production_or_delivered": stage_counts["量產或已交付"],
        "n_product_prototype_or_collaboration": stage_counts["產品、原型或合作"],
        "n_qualification_or_capability": stage_counts["資格或能力"],
        "n_with_separately_disclosed_uav_usv_revenue_share": int(
            frame["separate_uav_usv_revenue_share_disclosed"].sum()
        ),
        "n_with_public_binding_uav_usv_order_value_in_checked_sources": int(
            frame["binding_uav_usv_order_value_disclosed"].sum()
        ),
        "n_positive_revenue_growth": int((frame["revenue_yoy"] > 0).sum()),
        "n_operating_loss": int(
            sum(row["by_year"][str(row["latest_fy"])]["operating_margin"] < 0 for row in rows)
        ),
        "median_revenue_yoy": float(frame["revenue_yoy"].median()),
        "median_operating_margin": float(
            np.median(
                [row["by_year"][str(row["latest_fy"])]["operating_margin"] for row in rows]
            )
        ),
        "basket_return_common_window": float(np.expm1(basket_log_return.sum())),
        "basket_annualized_volatility": float(
            basket_log_return.std() * np.sqrt(TRADING_DAYS)
        ),
        "twii_return_common_window": benchmark_return,
        "twii_annualized_volatility": benchmark_vol,
        "return_gap_basket_minus_twii": float(np.expm1(basket_log_return.sum())) - benchmark_return,
        "stage_counts": stage_counts,
    }

    payload = {
        "generated_at_tw": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S"),
        "as_of_date": "2026-07-13",
        "policy": {
            "status": "行政院通過草案，已送立法院並付委；尚未完成立法",
            "budget_ceiling_twd": 210_000_000_000,
            "implementation_period": "2026-08 至 2031-12",
            "small_expendable_usv_planned_quantity": 1_320,
            "next_scheduled_committee_hearing": "2026-07-16",
            "source_urls": [
                "https://www.mnd.gov.tw/news/announcement/86952",
                "https://ppg.ly.gov.tw/ppg/bills/202110223090000/details",
                "https://ppg.ly.gov.tw/ppg/sittings/2026070904/details?meetingDate=115%2F07%2F16",
                "https://www.ey.gov.tw/File/39A867B74E2BA985?A=C",
            ],
            "interpretation_limit": "上限、計畫數量與法案進度都不是個別公司的已得標訂單。",
        },
        "certification_check": {
            "checked_at": "2026-07-13",
            "source_url": "https://www.auvsi.org/certification-training/green-uas/cleared-list/",
            "result": "查核當日公開 Green UAS Cleared List 未見本文十家公司或其台灣平台名稱。",
            "interpretation_limit": "未列入公開清單不等於產品不合格；只代表本文不能宣稱已取得該項認證。",
        },
        "price_window_requested": {"start": START, "end_exclusive": END_EXCLUSIVE},
        "price_window_common": {
            "start": prices.index[0].strftime("%Y-%m-%d"),
            "end": prices.index[-1].strftime("%Y-%m-%d"),
            "observations": int(len(prices)),
            "reason": "公平比較採十家公司與加權指數都有還原收盤價的日期交集。",
        },
        "data_source": (
            "yfinance adjusted close (auto_adjust=True) and annual income statement; "
            "policy and company stages use the attached official/public primary source URLs"
        ),
        "method": {
            "return": "common-window adjusted-close total return",
            "volatility": "daily log-return standard deviation * sqrt(252)",
            "basket": "ten-company equal-weight daily log return, rebalanced daily, no costs",
            "financials": "latest two or three annual income statements available from yfinance",
            "disclosure_stage": "highest public stage found by 2026-07-13; mutually exclusive, not an investment rating",
        },
        "summary": summary,
        "companies": rows,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 圖一：十家公司與加權指數的共同窗口還原價格路徑。
    normalized = prices / prices.iloc[0] * 100
    fig, ax = plt.subplots(figsize=(11, 7.2), dpi=160)
    for meta in COMPANIES:
        ax.plot(normalized.index, normalized[meta["ticker"]], lw=1.35, alpha=0.83, label=meta["name"])
    ax.plot(normalized.index, normalized[BENCHMARK], lw=2.8, color="#252A34", label="加權指數")
    ax.axhline(100, color="#8B929A", lw=0.8, ls="--")
    ax.set_ylabel("起點 = 100（還原收盤價）")
    ax.set_title(
        f"十家下游無人載具公司：共同窗口股價路徑\n"
        f"{payload['price_window_common']['start']} 至 {payload['price_window_common']['end']}｜資料源 yfinance"
    )
    ax.legend(ncol=4, fontsize=8, frameon=False, loc="upper left")
    ax.grid(alpha=0.2, lw=0.6)
    fig.tight_layout()
    fig.savefig(ASSETS / "drone_ep3_price_paths.png")
    plt.close(fig)

    # 圖二：市場報酬與年化波動率，分群著色。
    fig, ax = plt.subplots(figsize=(10, 7), dpi=160)
    for segment, group in frame.groupby("segment"):
        ax.scatter(
            group["annualized_volatility"] * 100,
            group["common_window_return"] * 100,
            s=85,
            color=SEGMENT_COLORS[segment],
            edgecolor="white",
            linewidth=0.8,
            label=segment,
        )
    for _, row in frame.iterrows():
        ax.annotate(
            row["name"],
            (row["annualized_volatility"] * 100, row["common_window_return"] * 100),
            xytext=(5, 4),
            textcoords="offset points",
            fontsize=8,
        )
    ax.scatter(
        benchmark_vol * 100,
        benchmark_return * 100,
        marker="*",
        s=390,
        color="#D74E3F",
        edgecolor="white",
        zorder=5,
        label="加權指數",
    )
    ax.axhline(benchmark_return * 100, color="#D74E3F", lw=0.8, ls="--", alpha=0.65)
    ax.axvline(benchmark_vol * 100, color="#D74E3F", lw=0.8, ls="--", alpha=0.65)
    ax.set_xlabel("年化波動率（%）")
    ax.set_ylabel("共同窗口報酬（%）")
    ax.set_title("下游名單的市場定價並不同步\n相同題材不代表相同報酬或風險")
    ax.legend(ncol=2, fontsize=8, frameon=False, loc="best")
    ax.grid(alpha=0.2, lw=0.6)
    fig.tight_layout()
    fig.savefig(ASSETS / "drone_ep3_risk_return.png")
    plt.close(fig)

    # 圖三：證據階梯，只計最高公開層級，三組互斥。
    counts = [stage_counts[stage] for stage in STAGE_ORDER]
    fig, ax = plt.subplots(figsize=(9, 5.8), dpi=160)
    bars = ax.barh(
        STAGE_ORDER,
        counts,
        color=[STAGE_COLORS[stage] for stage in STAGE_ORDER],
        height=0.58,
    )
    ax.invert_yaxis()
    for bar, count in zip(bars, counts, strict=True):
        ax.text(count + 0.12, bar.get_y() + bar.get_height() / 2, f"{count} 家", va="center", fontsize=12)
    ax.set_xlim(0, max(counts) + 1.5)
    ax.set_xlabel("公司數（最高公開證據層級；互斥分類）")
    ax.set_title("十家公司只有兩家走到量產或交付\n資格、原型、量產不可混為同一階段")
    ax.grid(axis="x", alpha=0.2, lw=0.6)
    fig.tight_layout()
    fig.savefig(ASSETS / "drone_ep3_disclosure_ladder.png")
    plt.close(fig)

    print(json.dumps({"output": str(OUT_JSON), "summary": summary}, ensure_ascii=False, indent=2))
    print(f"[ok] 3 charts -> {ASSETS}")


if __name__ == "__main__":
    main()
