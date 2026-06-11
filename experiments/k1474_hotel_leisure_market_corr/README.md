# K1474: 酒店娛樂業與股市相關性實證分析

**Member QA**: yaoxk1431 提問
**Question ID**: 79077d59-9647-4119-90dc-d86cfb230bdb
**Run Date**: 2026-06-11

## 研究動機

會員 yaoxk1431 提問：酒店消費娛樂業是否為民生消費市場的火車頭？要求文獻回顧娛樂產業特別是酒店與股市的相關性，並歸納出產業指標項目。

本實驗從實際市場數據出發，補充純文獻回顧的不足，以 2015-2026 長期視窗量化酒店/娛樂業與 S&P500 的相關性、beta、波動率特徵，並分析 COVID 危機時的行為。

## 資料來源

- **yfinance** (auto_adjust=True)：PEJ、XLY、HLT、MAR、H、RCL、CCL、SPY
- **期間**：2015-01-02 至 2026-06-09
- **樣本數**：2,875 交易日（遠超 500 最低要求）
- **Seed**: 42（所有隨機程序固定）

## 標的說明

| Ticker | 名稱 | 類型 |
|--------|------|------|
| SPY | SPDR S&P 500 ETF | 基準 |
| PEJ | Invesco Leisure & Entertainment ETF | 娛樂業 ETF |
| XLY | Consumer Discretionary Select Sector SPDR | 消費可選 ETF |
| HLT | Hilton Worldwide Holdings | 酒店龍頭 |
| MAR | Marriott International | 酒店龍頭 |
| H | Hyatt Hotels | 酒店 |
| RCL | Royal Caribbean Group | 郵輪 |
| CCL | Carnival Corporation | 郵輪 |

## 方法論

- **日對數報酬**：`ln(P_t / P_{t-1})`（無前瞻性偏誤，純統計描述）
- **滾動相關係數**：252 個交易日滾動窗口（≈ 1 年）
- **Beta**：`Cov(r_i, r_mkt) / Var(r_mkt)`，同樣 252 日滾動
- **年化波動率**：`std_daily * sqrt(252)`
- **Max Drawdown**：累計報酬對 rolling max 的最大回撤
- **COVID 分析**：crash 期 (2020-02-20 to 2020-03-23) vs recovery (2020-03-23 to 2020-12-31)
- **正常期對照**：2018-01-01 to 2019-12-31

## 主要發現

### 全期相關性（2015-2026）

- **PEJ-SPY 相關**: 0.781（強中度）、Beta 1.069
- **XLY-SPY 相關**: 0.898（強）、Beta 1.091
- **HLT-SPY 相關**: 0.623、Beta 1.011
- **MAR-SPY 相關**: 0.611、Beta 1.107
- **RCL-SPY 相關**: 0.564、Beta 1.645（高 beta 高波動）
- **CCL-SPY 相關**: 0.559、Beta 1.749（最高 beta）

### 波動率（年化）

- SPY: 17.7%（基準）
- PEJ: 24.2%
- XLY: 21.5%
- HLT: 28.7%
- MAR: 32.1%
- H: 34.3%
- RCL: 51.6%
- CCL: 55.3%

### COVID 危機分析（2020-02-20 至 2020-03-23）

| Ticker | 崩跌幅度 | 復甦幅度 (Mar23-Dec31) |
|--------|---------|----------------------|
| SPY | -33.7% | +65.5% |
| PEJ | -52.4% | +93.0% |
| HLT | -43.7% | +80.6% |
| MAR | -52.3% | +76.9% |
| RCL | -74.4% | +213.7% |
| CCL | -72.0% | +80.5% |

酒店/娛樂業跌幅明顯大於大盤，反映實體消費的直接衝擊。

### 相關性在危機時的變化

- PEJ 正常期(2018-19) corr=0.799，COVID 崩盤期 corr=0.813 (微升)
- XLY 正常期 corr=0.923，COVID 崩盤期 corr=0.964 (顯著升)
- 這是典型的「危機相關性收斂」(crisis correlation convergence) — 恐慌拋售時資產相關性趨近 1

## 圖表

1. `k1474_rolling_corr.png` — 滾動 252 日相關性時序（Panel A: ETF、Panel B: 個股）
2. `k1474_sector_beta.png` — 全期 Beta 與年化波動率條形圖

## 研究結論

1. 娛樂/酒店板塊與大盤有中強度正相關（0.56-0.90），beta 多 > 1，是順週期高 beta 板塊
2. 個別酒店股 (HLT/MAR) beta ≈ 1，ETF (PEJ) beta ≈ 1.07，消費可選 ETF (XLY) beta ≈ 1.09
3. 郵輪股 (RCL/CCL) beta > 1.6，極高波動，不是普通「防禦型」
4. COVID 崩盤時相關性升高（危機收斂），復甦期跑贏大盤（RCL +214%）
5. 這種高 beta + COVID 暴跌 + 復甦超額 pattern，與文獻中 consumer discretionary cyclicality 完全一致

## 防錯備註

- 純描述統計，無信號預測，無 lookahead 問題
- 所有滾動計算只用過去數據
- yfinance auto_adjust=True 處理股息調整
- Seed=42 固定
- 樣本數 2874 遠超 500 門檻

## 實驗三件套

- `README.md` (本文件)
- `k1474.py` (完整可重現代碼)
- `k1474_results.json` (機器可讀結果)
- `k1474_rolling_corr.png` (圖1)
- `k1474_sector_beta.png` (圖2)
