# event_article_fomc_2026_06_17_t7

**類型**: event_article (T-7)  
**事件**: FOMC 2026-06-17  
**日期**: 2026-06-10（台灣時間）  
**Task ID**: event_article_fomc_2026-06-17_tminus7

## 動機

FOMC 6/17 T-7 定位文。與 4/20 同為 T-7 slot，但必須換軸線：
- 4/20 文用「20 年 173 場 FOMC 歷史，會前 5 天 vol 不放大」
- 本文聚焦 **SOFR 期貨隱含利率路徑 + 4 月會議後的利率 regime + VIX9D/VIX 倒掛**

## 核心差異化

本場 FOMC 特殊之處：
1. VIX9D（22.14）高於 VIX（19.87），比值 1.114 — 今年 4 場 T-7 中最高
2. SOFR 期貨顯示市場定價「無降息 + 微升態」，與 Fed 點陣圖（估計仍有 1-2 次降息）存在分歧
3. 2025 年 3 次降息後，Fed 已暫停 6 個月；6/17 幾乎確定 hold，問題是「之後呢」

## 方法

- **數據**: yfinance (^VIX, ^VIX9D, SPY, ^IRX, SR3*.CME SOFR futures, ZQ=F)
- **利率路徑**: 3-month T-bill 作 Fed Funds 代理 + SOFR 3-month 季度期貨推算前瞻路徑
- **說明**: CME FedWatch 無法透過 yfinance 直接取得，以 SOFR 期貨作為學術替代（研究誠實原則明示）
- **VIX 比較**: 2026 年所有 4 場 FOMC T-7 的 VIX/VIX9D cross-section

## 產出

- `fomc_t7_data.py` — 資料抓取 + 圖表生成腳本
- `fomc_t7_results.json` — 完整數據包
- `fig_fomc_t7_evidence.png` — 四格圖（T-bill 軌跡 / SOFR 路徑 / VIX T-7 比較 / VIX9D/VIX 比值）
- `draft.md` — 文章草稿（待 publish）
- `fb_draft.md` — FB Ivan Lai 口吻版本

## 限制

- SOFR 3-month futures 是季度 compound，不直接等於 Fed Funds overnight rate，但高度相關
- April 2026 dot plot 確切數字未能直接抓取，使用推算值
- CME FedWatch 機率未直接使用（說明在文內）
