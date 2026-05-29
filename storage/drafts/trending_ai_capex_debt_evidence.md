# Evidence Package: AI 基建支出與科技股波動率

## Task ID: trending_repost_2026_05_29_ai基建債務
## Prepared: 2026-05-29

---

## Primary Source Numbers

### AI Capex (Q1 2026, from public 10-Q filings)

| 公司 | Q1 2026 資本支出 | Q1 2025 資本支出 | YoY 增幅 |
|------|----------------|----------------|---------|
| Microsoft (MSFT) | $21.4B | $14.0B | +53% |
| Meta Platforms | $13.7B | $6.7B | +104% |
| Alphabet (GOOGL) | $17.2B | $12.0B | +43% |
| Amazon (AWS) | $24.3B | $14.9B | +63% |
| **四大合計** | **$76.6B** | **$47.6B** | **+61%** |

- 年化折算：~$306B/年（以 Q1 pace 計）
- Meta 全年 2026 指引：$64–72B
- Sources: 各公司 Q1 2026 10-Q/earnings releases

### Mag5 科技股 實現波動率（Realized Volatility）
Data source: yfinance, 2026-05-28

| 股票 | RV30 (%) | RV60 (%) | RV90 (%) |
|------|----------|----------|----------|
| MSFT | 27.5 | 26.8 | 33.3 |
| META | 34.0 | 40.8 | 41.2 |
| GOOGL | 35.4 | 33.8 | 31.2 |
| AMZN | 21.1 | 28.7 | 30.4 |
| NVDA | 38.1 | 35.6 | 37.9 |
| **Mag5 avg** | **31.2** | **33.1** | **34.8** |

比較：
- Mag5 RV60 現在：33.1%
- ~1年前 (2025-05-28)：48.5%（當時 tariff shock 後遺症）
- ~6個月前 (2025-12-01)：30.9%

### 高收益債 ETF (HYG) 作為信用市場代理
Data source: yfinance

- HYG 現值：$80.23（2026-05-28）
- HYG 2026 年低點：$77.93（2026-03-27，tariff 恐慌高峰）
- HYG April 2025 低點：$71.10（關稅衝擊低谷）
- 從 April 2025 低點反彈：+13%

### VIX 走勢
- VIX 現值：15.7（2026-05-28）
- VIX 2026 高點：31.0（2026-03-27）
- VIX 2024-now 範圍：11.9 – 52.3

---

## Quantitative Analysis: Rolling Correlation

**Mag5 平均 RV60 vs HYG ETF 收盤價，60日滾動相關係數**

- 最新相關係數：+0.671（歷史性高位）
- 過去 3 年均值：-0.046（接近零）
- 相關係數為負的天數：339/633（54%）
- 相關係數 ≥ 0.5 的天數：120/633（19%）

**解讀**：
- 典型市場：Mag5 RV 高 → 恐慌情緒 → HYG 跌（負相關）
- 當前：Mag5 RV 依然偏高(33.1%) + HYG 強勢回彈(80.23) → 正相關
- 這種正相關在過去 3 年佔比不到 20%
- 意味：股市波動與信用市場同步緩和，而非典型的「股跌債跌」分歧

---

## Figures Generated
- Fig 1: `assets/ai_capex_debt_fig1_rv_vs_hyg.png` — Mag5 RV60 vs HYG 雙軸時序圖
- Fig 2: `assets/ai_capex_debt_fig2_rolling_corr.png` — 60日滾動相關係數

---

## VolPred Angle

**主論點**：四大超級運算巨頭單季燒掉 766 億美元 AI 基建支出（年化 3,000 億），
資本密集度前所未有。但股市波動率（Mag5 RV60 = 33.1%）與信用市場（HYG = $80.23）
目前呈現**同步緩和**而非分歧——這在歷史上屬於少見的正相關機制（+0.671，
過去 3 年僅 19% 的時候出現）。

**問題**：這是市場對 AI ROI 的真實信心，還是低利率預期驅動的流動性泡沫？
若信用市場開始重新定價這筆槓桿，Mag5 波動率將如何反應？

**Lookahead check**: 全部使用 realized (historical) vol，沒有 forward-looking。
