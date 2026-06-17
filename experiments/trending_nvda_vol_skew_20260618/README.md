# NVDA Vol Skew Snapshot — 2026-06-18

**類型**: trending_repost 支撐資料
**任務**: trending_repost_2026_06_18_ai_波動
**發佈文章**: mile_0daa4bb2

## 目的

抓取 NVDA 當前選擇權 implied volatility skew 結構，
計算 ATM IV、25Δ 近似 skew、realized vol、IV-RV gap，
並追蹤跨 expiry 的 skew term structure。

## 關鍵數字 (2026-06-17 close / 2026-06-18 盤前)

| 指標 | 數值 |
|------|------|
| NVDA Spot | $204.65 |
| Expiry (primary) | 2026-06-24 (6 days) |
| ATM IV (avg call+put) | 32.4% |
| 25Δ Put IV | 32.7% @ $200 |
| 25Δ Call IV | 31.9% @ $210 |
| 25Δ Skew (put-call) | +0.8% |
| RV30 (annualized) | 45.4% |
| IV-RV Gap | -13.0pp |

## Skew Term Structure (±10% OTM)

| 到期日 | ATM IV | 10% OTM Skew |
|--------|--------|--------------|
| 2026-07-02 (14d) | 36.7% | +3.5% |
| 2026-07-10 (22d) | 36.9% | +2.5% |
| 2026-07-17 (29d) | 37.7% | +1.8% |
| 2026-07-24 (36d) | 38.6% | +1.2% |
| 2026-07-31 (43d) | 39.7% | +0.5% |
| 2026-08-21 (64d) | 41.0% | -1.0% |
| 2026-09-18 (92d) | 44.0% | -2.3% |
| 2026-10-16 (120d) | 45.2% | -3.2% |

Skew flip point: ~64 天後（8月中旬）

## 檔案

- `run.py` — 主分析腳本
- `results.json` — 完整數據輸出
- `skew_curve.png` — 近期到期日 IV smile 曲線
- `skew_term_structure.png` — Skew term structure + IV vs RV 圖

## 結論

1. 近期 put skew 存在（+3.5% 7月初），但 25Δ skew 幾乎持平（+0.8%）
2. 長線 skew 翻轉為 call skew，暗示市場中長線看多
3. RV30 (45.4%) >> ATM IV (32.4%)，IV 低估近期真實波動 13pp
4. 解讀：市場短線防守、長線看漲，同時 IV 可能低估

## 資料來源

- yfinance NVDA option chain + price history
- 擷取時間: 2026-06-18 07:11 台灣時間
- N=30 (RV), N=64 (price history buffer)
