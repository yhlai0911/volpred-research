# 台股代表股相對估值篩選（自身歷史分位 + 同業中位數）

`experiments/k_taiex_60k_scenario_20260619/valuation/`

## 動機

回答一個讀者最常問的問題：「台股漲這麼多，現在還有哪些『還沒到應有價值』、哪些
產業相對便宜？」——但以**方法論誠實**的方式回答：不喊買賣、不給目標價，只做
**相對估值位置的客觀描述 + value-trap 風險警示**。

「便宜 / 貴」是相對概念。本研究用兩個座標衡量「相對」：
1. **自身歷史分位**：個股目前 PBR / PER 落在自己近 5 年分佈的哪個百分位。
2. **同業截面比較**：個股相對其產業中位數是高是低。

## 方法

- **個股自身歷史分位**：取近 5 年每日 PER / PBR 序列，計算「最新值」的
  percentile rank（0–100）與 z-score。**PBR≤p25 = 相對自身歷史便宜帶、
  ≥p75 = 偏貴帶**。
- **PBR 為主、PER 為輔**：PER 受一次性損益、景氣循環高低點扭曲（cyclical 股
  在獲利高點時 PER 反而很低 → 反向訊號）；PBR 較穩定。
- **同業中位數**：以 yfinance `sector` 分群，算各 sector PER / PBR 中位數，
  並算各股相對其 sector 中位數的比值。
- **產業層級**：對每個 sector 取「成分股 PBR 自身歷史分位」的中位數，描述哪個
  產業整體目前靠近自身歷史低檔。
- **虧損公司處理**：FinMind 對 EPS≤0 公司回傳 PER=0.0 → 視為 PER undefined
  （`PER_undefined_loss=true`），不納入 PER 分位/統計；其 PBR 仍有效。

## 資料來源（皆真實數據）

| 用途 | 來源 | 說明 |
|---|---|---|
| 歷史 PER / PBR / 殖利率 | **FinMind `TaiwanStockPER`** (anonymous endpoint) | 每日真實歷史序列，回溯至 2018，本研究用近 5 年窗 |
| sector / industry / forwardPE / priceToBook | **yfinance `.info`** | 產業分群 + 截面比較 + cross-check |

**Cross-check 結果**：FinMind 最新 PBR 與 yfinance `priceToBook` 30 檔對照，
28 檔 ratio ≈ 1.00，僅 2 檔金融股 ratio ≈ 0.91（淨值更新時點差異），**0 檔
有 >70% 落差** → 兩源高度一致，資料可信。

## 期間與樣本

- **As-of**：2026-06-19（最新可得交易日資料 **2026-06-18**，無 lookahead）
- **歷史窗**：2021-06-15 ~ 2026-06-19（近 5 年，每檔約 1,200+ 個交易日觀測）
- **樣本**：市值前 ~30 大代表股，跨 7 個 sector（Technology 11、Financial
  Services 9、Basic Materials 3、Consumer Defensive/Cyclical/Industrials 各
  2、Communication Services 1）。FinMind 覆蓋率 30/30。
- **Seed**：42（本研究為 deterministic 統計分位，無隨機程序；seed 僅為合規記錄）

## 主要發現（相對估值位置，非買賣建議）

- **相對自身歷史較低分位（候選「便宜」帶，PBR ≤ p25）**：消費（統一超 p0.7、
  統一 p2.2）、汽車（和泰車 p4.8）、部分金融（合庫金 p14.7）、循環股（台塑、
  中鋼、萬海 — **均帶 cyclical value-trap 警示**）、電信兼營通路（台灣大 p23.6）。
- **相對自身歷史高分位（偏貴帶，PBR ≥ p75）**：**幾乎整片金融股**（永豐金、
  元大金、中信金、富邦金、國泰金、華南金 全在 p99+）+ **大半科技權值**（台積電、
  聯發科、台達電、智邦、瑞昱、日月光、廣達、鴻海 多在 p95+）+ 中華電。
- **產業層級**：Financial Services（p99.9）、Technology（p98.0）、
  Communication Services（p96.3）整體位於自身近 5 年**高檔**；Consumer
  Defensive（p1.5）、Consumer Cyclical（p14.2）、Basic Materials（p15.6）、
  Industrials（p24.9）整體靠近自身歷史**低檔**。

## Value-trap / 誠實警示（必讀）

1. **低分位 ≠ 保證上漲；便宜可以更便宜。** 歷史分佈不保證未來重演。
2. **Cyclical 股是最大陷阱**：台塑、中鋼目前 PBR<1 且**已虧損（PER undefined）**
   —— 低 PBR 來自獲利谷底，不是「撿便宜」，可能是基本面持續惡化的反映。航運
   （萬海 PBR p22 但 PER p70）低 PBR + 高 PER 分位，是典型「資產便宜但盈利尚未
   崩」的循環中段訊號。
3. **消費股低 PBR 分位**的成因之一是股價區間整理 + 淨值持續累積（分母變大），
   不必然代表低估；需個別檢視 ROE 與成長性。
4. **金融股高 PBR 分位**反映 2023–25 升息 + 資本市場熱絡推升獲利與淨值評價，
   屬 regime 驅動；分位高不等於「該跌」。
5. **本研究只描述位置，不做方向預測。** 任何進出場決策需結合基本面、籌碼、
   風險承受度，本檔不構成投資建議。

## 重跑

```bash
cd experiments/k_taiex_60k_scenario_20260619/valuation
uv run python valuation.py
```

輸出：`valuation_results.json`、`valuation_percentile.png`、`sector_heatmap.png`。
腳本獨立可重跑（FinMind anonymous + yfinance，無需 token）。
