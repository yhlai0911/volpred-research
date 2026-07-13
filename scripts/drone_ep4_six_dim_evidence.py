"""EP4 evidence package — 六面向（經營/財務/市場/籌碼/技術/心理）逐檔真查真算。

六檔核心龍頭（EP0 名冊「高信心」且屬整機/系統整合層；空中 5 + 海域 1）：
  雷虎 8033.TW / 漢翔 2634.TW / 亞航 2630.TW / 長榮航太 2645.TW
  中光電 5371.TWO（上櫃）/ 龍德造船 6753.TW

資料來源（全部公開、可複現）
  價格 / 財報 / 市值：yfinance（還原除權息收盤價）
  三大法人買賣超：TWSE 開放資料 T86「三大法人買賣超日報」（上市）
                  TPEx openapi（上櫃，僅提供最近一日，故上櫃檔的籌碼面標記為口徑不同）

研究誠實
  - 只計算可從來源直接驗證的量；缺的欄位寫 None，不推估、不填補。
  - 六面向的定義與門檻寫死在本檔，文章的每個數字都能用本腳本重算。
  - 個股分析僅為描述性統計 + 公開財報事實，非投資建議。
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from volpred.ops.diagnostics import warn

TW = ZoneInfo("Asia/Taipei")
OUT = Path("storage/drafts/drone_ep4_six_dim_evidence.json")

# 名冊來源：storage/pending_series/taiwan_drone_series_ep0_research.md（信心=高、整機/系統整合層）
COMPANIES = [
    {"name": "雷虎", "ticker": "8033.TW", "code": "8033", "board": "上市", "segment": "空中·整機/系統整合"},
    {"name": "漢翔", "ticker": "2634.TW", "code": "2634", "board": "上市", "segment": "空中·整機/機體/發動機"},
    {"name": "亞航", "ticker": "2630.TW", "code": "2630", "board": "上市", "segment": "空中·整機整合"},
    {"name": "長榮航太", "ticker": "2645.TW", "code": "2645", "board": "上市", "segment": "空中·整機/MRO"},
    {"name": "中光電", "ticker": "5371.TWO", "code": "5371", "board": "上櫃", "segment": "空中·整機方案/光學"},
    {"name": "龍德造船", "ticker": "6753.TW", "code": "6753", "board": "上市", "segment": "海域·無人艇"},
]
BENCHMARK = "^TWII"

PRICE_START = "2025-06-30"
PRICE_END = "2026-07-11"
CHIP_LOOKBACK_DAYS = 60  # 三大法人累計買賣超的交易日視窗


# ---------------------------------------------------------------- 價格 / 市場面
def fetch_prices() -> pd.DataFrame:
    tickers = [c["ticker"] for c in COMPANIES] + [BENCHMARK]
    raw = yf.download(tickers, start=PRICE_START, end=PRICE_END, auto_adjust=True, progress=False)
    close = raw["Close"].dropna(how="all")
    return close


def market_metrics(px: pd.Series, bench: pd.Series) -> dict:
    """報酬 / 年化波動 / beta / 最大回撤 / 與大盤相關性。"""
    px = px.dropna()
    if len(px) < 60:
        return {}
    ret = px.pct_change().dropna()
    bret = bench.pct_change().reindex(ret.index).dropna()
    common = ret.index.intersection(bret.index)
    ret_c, bret_c = ret.loc[common], bret.loc[common]

    cum = float(px.iloc[-1] / px.iloc[0] - 1.0)
    ann_vol = float(ret.std() * np.sqrt(252))
    beta = float(np.cov(ret_c, bret_c)[0, 1] / np.var(bret_c)) if len(common) > 30 else None
    corr = float(ret_c.corr(bret_c)) if len(common) > 30 else None
    running_max = px.cummax()
    mdd = float((px / running_max - 1.0).min())

    return {
        "window_return": cum,
        "annualized_volatility": ann_vol,
        "beta_vs_twii": beta,
        "corr_vs_twii": corr,
        "max_drawdown": mdd,
        "price_start": float(px.iloc[0]),
        "price_end": float(px.iloc[-1]),
        "first_date": px.index[0].strftime("%Y-%m-%d"),
        "last_date": px.index[-1].strftime("%Y-%m-%d"),
    }


# ------------------------------------------------------------------- 技術面
def technical_metrics(px: pd.Series) -> dict:
    px = px.dropna()
    last = float(px.iloc[-1])

    def ma_gap(n: int):
        if len(px) < n:
            return None
        return float(last / px.rolling(n).mean().iloc[-1] - 1.0)

    delta = px.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = float((100 - 100 / (1 + rs)).iloc[-1]) if len(px) > 15 else None

    high_52w = float(px.tail(252).max())
    ret_60d = float(last / px.iloc[-61] - 1.0) if len(px) > 61 else None

    return {
        "vs_ma20": ma_gap(20),
        "vs_ma60": ma_gap(60),
        "vs_ma200": ma_gap(200),
        "rsi14": rsi,
        "drawdown_from_52w_high": float(last / high_52w - 1.0),
        "return_60d": ret_60d,
    }


# -------------------------------------------------------- 財務面 / 心理（估值）面
def _safe_row(df: pd.DataFrame, keys: list[str], col) -> float | None:
    for k in keys:
        if k in df.index:
            v = df.loc[k, col]
            if pd.notna(v):
                return float(v)
    return None


def fundamental_metrics(tk: yf.Ticker) -> dict:
    out: dict = {"fy_rows": {}}
    try:
        fin = tk.income_stmt
    except Exception:
        fin = None

    if fin is not None and not fin.empty:
        cols = sorted([c for c in fin.columns], reverse=True)[:2]
        for c in cols:
            fy = str(c.year)
            revenue = _safe_row(fin, ["Total Revenue", "Operating Revenue"], c)
            gross = _safe_row(fin, ["Gross Profit"], c)
            op_inc = _safe_row(fin, ["Operating Income", "EBIT"], c)
            net = _safe_row(fin, ["Net Income", "Net Income Common Stockholders"], c)
            out["fy_rows"][fy] = {
                "revenue": revenue,
                "gross_profit": gross,
                "operating_income": op_inc,
                "net_income": net,
                "gross_margin": (gross / revenue) if (gross is not None and revenue) else None,
                "operating_margin": (op_inc / revenue) if (op_inc is not None and revenue) else None,
                "net_margin": (net / revenue) if (net is not None and revenue) else None,
            }
        yrs = sorted(out["fy_rows"].keys(), reverse=True)
        if len(yrs) == 2:
            cur, prev = out["fy_rows"][yrs[0]], out["fy_rows"][yrs[1]]
            if cur["revenue"] and prev["revenue"]:
                out["revenue_yoy"] = cur["revenue"] / prev["revenue"] - 1.0
            out["latest_fy"], out["previous_fy"] = yrs[0], yrs[1]
            out["latest_is_profitable"] = (cur["net_income"] or 0) > 0

    info = {}
    try:
        info = tk.get_info()
    except Exception:
        info = {}

    out["market_cap"] = info.get("marketCap")
    out["shares_outstanding"] = info.get("sharesOutstanding")
    out["return_on_equity"] = info.get("returnOnEquity")
    out["debt_to_equity"] = info.get("debtToEquity")
    # yfinance 的 trailingPE / priceToBook 跟著「當下」股價走 —— 盤中每跑一次數字就不同，
    # 文章引用它等於引用一個不可複現的量。改存每股盈餘與每股淨值，由 main() 用
    # 價格窗口末日的收盤價自行計算，把倍數釘在查核日上。
    out["trailing_eps"] = info.get("trailingEps")
    out["book_value_per_share"] = info.get("bookValue")
    out["live_trailing_pe_unpinned"] = info.get("trailingPE")  # 僅供對照，勿引用
    return out


# ------------------------------------------------------------------- 籌碼面
def fetch_twse_chip(codes: list[str], lookback: int) -> dict:
    """TWSE T86 三大法人買賣超日報 — 逐交易日抓，累加每檔的外資/投信/自營淨買超股數。"""
    acc = {c: {"foreign": 0.0, "trust": 0.0, "dealer": 0.0, "total": 0.0, "days": 0} for c in codes}
    days_ok, dates_used = 0, []
    failed_dates: list[str] = []       # 抓取失敗而被跳過的日期（會改變累計區間）
    parse_failures: list[tuple] = []   # 欄位解析失敗（被當 0 計入）
    probe = pd.Timestamp(PRICE_END, tz=TW).normalize()
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (research; volpred)"})

    while days_ok < lookback and probe > pd.Timestamp("2026-01-01", tz=TW):
        d = probe.strftime("%Y%m%d")
        probe -= pd.Timedelta(days=1)
        if pd.Timestamp(d).dayofweek >= 5:  # 週末直接跳過，省請求
            continue
        try:
            r = session.get(
                "https://www.twse.com.tw/rwd/zh/fund/T86",
                params={"date": d, "selectType": "ALLBUT0999", "response": "json"},
                timeout=20,
            )
            js = r.json()
        except Exception as e:
            # 靜默跳過會讓「實得交易日數」悄悄少一天、改由更早的日期補位，
            # 等於偷換累計區間 → 必須留痕，讓 date_range 與 days 對得起來。
            warn("ep4_twse_t86", "request failed, date skipped", date=d, err=str(e))
            failed_dates.append(d)
            time.sleep(1.5)
            continue
        if js.get("stat") != "OK":
            continue  # silent-ok: 非交易日 / 當日尚未公布，屬預期內的正常回應

        fields = js["fields"]
        idx_code = fields.index("證券代號")
        # 欄名含全形括號，用關鍵字定位避免版本差異
        def col(kw: str) -> int | None:
            for i, f in enumerate(fields):
                if kw in f:
                    return i
            return None

        i_foreign = col("外陸資買賣超股數")
        i_trust = col("投信買賣超股數")
        i_dealer = col("自營商買賣超股數")
        i_total = col("三大法人買賣超股數")

        for row in js["data"]:
            code = row[idx_code].strip()
            if code not in acc:
                continue
            def val(i):
                if i is None:
                    return 0.0
                try:
                    return float(row[i].replace(",", ""))
                except Exception as e:
                    # 解析失敗當成 0 會把「不知道」記成「沒買賣」，直接污染累計淨買超。
                    warn("ep4_twse_t86", "cell parse failed, counted as 0",
                         date=d, code=code, col=i, raw=str(row[i])[:20], err=str(e))
                    parse_failures.append((d, code, i))
                    return 0.0
            acc[code]["foreign"] += val(i_foreign)
            acc[code]["trust"] += val(i_trust)
            acc[code]["dealer"] += val(i_dealer)
            acc[code]["total"] += val(i_total)
            acc[code]["days"] += 1

        days_ok += 1
        dates_used.append(d)
        time.sleep(1.1)  # 對 TWSE 有禮貌

    return {"per_code": acc, "trading_days_collected": days_ok,
            "date_range": [dates_used[-1], dates_used[0]] if dates_used else None,
            "fetch_failed_dates": failed_dates,
            "cell_parse_failures": len(parse_failures)}


def main() -> None:
    print(f"[ep4] 抓價格 {PRICE_START} → {PRICE_END}")
    close = fetch_prices()
    bench = close[BENCHMARK].dropna()

    twse_codes = [c["code"] for c in COMPANIES if c["board"] == "上市"]
    print(f"[ep4] 抓 TWSE 三大法人（{CHIP_LOOKBACK_DAYS} 個交易日，上市 {len(twse_codes)} 檔）…")
    chips = fetch_twse_chip(twse_codes, CHIP_LOOKBACK_DAYS)
    print(f"[ep4] 法人資料實得 {chips['trading_days_collected']} 個交易日 {chips['date_range']}")

    bench_m = market_metrics(bench, bench)
    results = []
    for c in COMPANIES:
        print(f"[ep4] {c['name']} {c['ticker']}")
        px = close[c["ticker"]]
        tk = yf.Ticker(c["ticker"])
        row = dict(c)
        row["market"] = market_metrics(px, bench)
        row["technical"] = technical_metrics(px)
        row["fundamental"] = fundamental_metrics(tk)

        # 倍數釘在價格窗口末日收盤（as-of），不用會漂的即時值
        px_end = row["market"].get("price_end")
        eps = row["fundamental"].get("trailing_eps")
        bvps = row["fundamental"].get("book_value_per_share")
        row["fundamental"]["pe_asof"] = (px_end / eps) if (px_end and eps and eps > 0) else None
        row["fundamental"]["pb_asof"] = (px_end / bvps) if (px_end and bvps and bvps > 0) else None
        row["fundamental"]["valuation_asof_date"] = row["market"].get("last_date")

        chip = chips["per_code"].get(c["code"])
        if chip and chip["days"] > 0:
            so = row["fundamental"].get("shares_outstanding")
            row["chip"] = {
                "source": "TWSE T86 三大法人買賣超日報",
                "trading_days": chip["days"],
                "foreign_net_shares": chip["foreign"],
                "trust_net_shares": chip["trust"],
                "dealer_net_shares": chip["dealer"],
                "total_net_shares": chip["total"],
                "total_net_pct_of_shares_out": (chip["total"] / so) if so else None,
            }
        else:
            row["chip"] = {
                "source": None,
                "note": "上櫃股，TWSE T86 不含；TPEx 開放資料僅提供最近一日，無法建立同口徑 60 日累計 → 本次未取得",
            }
        results.append(row)

    payload = {
        "generated_at_tw": datetime.now(TW).isoformat(),
        "as_of_date": "2026-07-13",
        "method": {
            "universe": "EP0 名冊中信心=高、且屬整機/系統整合層的 6 檔（空中 5 + 海域 1）",
            "price_source": "yfinance 還原除權息收盤價",
            "price_window": [PRICE_START, PRICE_END],
            "financial_source": "yfinance income_stmt / get_info（公司年報揭露值）",
            "chip_source": "TWSE T86 三大法人買賣超日報（僅上市；上櫃無同口徑歷史）",
            "chip_lookback_trading_days": chips["trading_days_collected"],
            "chip_date_range": chips["date_range"],
            "chip_fetch_failed_dates": chips["fetch_failed_dates"],
            "chip_cell_parse_failures": chips["cell_parse_failures"],
            "benchmark": BENCHMARK,
            "disclaimer": "全部為公開資料的描述性統計，非投資建議；不預測價格、不保證報酬。",
        },
        "benchmark": {"ticker": BENCHMARK, **bench_m},
        "companies": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ep4] 寫出 {OUT}")


if __name__ == "__main__":
    main()
