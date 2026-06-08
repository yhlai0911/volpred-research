# K1429 — EAV Effect: Realized Volatility Around Earnings Announcements

## 動機

2026-05-28 NVDA 發布 Q1 FY27 財報，12 天前。市場對 AI 龍頭股財報週的波動率直覺多半是「財報前緊繃上升、財報後恢復平靜」。本實驗直接用日線 Realized Volatility 測試這個直覺是否成立，並與 AAPL、MSFT 做跨股對照，提供 EAV 效應（Earnings Announcement Volatility）的量化基礎。

## 方法

**資料**：yfinance 日線收盤（adj close），2024-01-01 至 2026-06-08，3 檔股票（NVDA、AAPL、MSFT）。

**Metric**：5-day rolling annualised RV = sqrt(252) × std(log return) over [t-4, t]。

**財報日**：
- NVDA：9 次（2024-02-21 至 2026-05-28）
- AAPL：9 次（2024-02-01 至 2026-01-30）
- MSFT：9 次（2024-01-30 至 2026-01-29）

**事件窗口**：
- Pre-earnings: [T-5, T-1] 平均 RV
- Post-earnings: [T+1, T+5] 平均 RV
- Event day: T=0
- Baseline: 移除所有財報 ±10 日的其餘交易日，計算平均 RV

**統計檢定**：scipy.stats.ttest_rel（paired t-test，每個 event 的 mean RV vs baseline 常數）。H0: 無差異，p<0.05 拒絕。

**Lookahead 確認**：5-day rolling std 使用 [t-4, t]，純回顧窗口，無 lookahead。

**Seed**：np.random.seed(42)（雖本實驗無 bootstrap/MC，仍設定以符合規範）。

## 結果

| Ticker | Baseline RV | Pre RV | Pre Premium | t | p | Sig. | Post RV | Post Premium | t | p | Sig. | n |
|--------|------------|--------|-------------|---|---|------|---------|-------------|---|---|------|---|
| NVDA | 0.4235 | 0.3401 | **-19.7%** | -2.560 | **0.034** | ✓ | 0.6047 | +42.8% | 1.803 | 0.109 | ✗ | 9 |
| AAPL | 0.2167 | 0.1996 | -7.9% | -0.733 | 0.484 | ✗ | 0.2744 | +26.6% | 1.565 | 0.156 | ✗ | 9 |
| MSFT | 0.1919 | 0.2084 | +8.6% | 0.488 | 0.639 | ✗ | 0.3889 | **+102.6%** | 3.851 | **0.005** | ✓ | 9 |

**關鍵發現**：

1. **NVDA pre-earnings RV 顯著低於基準**（-19.7%, p=0.034）。與「財報前緊繃」的直覺相反 — 日線 RV 在事件前 5 日反而壓縮。

2. **MSFT post-earnings RV 顯著高於基準**（+102.6%, p=0.005）。公告後 5 日的波動率倍增，且效應顯著。

3. **AAPL 無顯著 EAV 效應**。6 個檢定中 0 個顯著。

4. NVDA post-earnings premium 42.8% 為正，但 p=0.109 未達顯著 — 方向與直覺一致（公告後波動率放大），但 9 個事件的樣本不足以在 0.05 水準拒絕 H0。

## 解讀

NVDA 財報前的波動率壓縮（realized vol 降低）與選擇權市場常觀察到的 IV 預售溢價形成對比：implied vol 在財報前常飆升（市場願意付更多保護費），但 realized vol 實際上更低。這是 EAV 文獻常提到的「realized vol 在事件窗口壓縮 → 期後釋放」模式的日線版本。

MSFT 的 post-earnings 效應更明顯（翻倍），反映其財報報告後的市場反應期更長，或是 2024-2026 期間幾次財報都觸發顯著 price discovery。

## 限制

- n=9 每股，樣本偏小，統計功效有限（type-II error 風險高）
- 日線 RV 非 intraday RV，無法捕捉財報當日盤後跳空的細粒度動態
- 未控制同期宏觀事件（FOMC、CPI 等）可能汙染財報日附近 RV
- 財報日使用資料集中的宣告日，有時與實際盤後公告日差 1 天
- 2024-2026 樣本期 AI narrative 特殊，不可外推至所有財報股或其他時期

## Verdict

**CONDITIONAL_PASS**

2/6 檢定統計顯著（NVDA pre: p=0.034；MSFT post: p=0.005）。NVDA 的 pre-earnings RV 壓縮效應顯著，方向與直覺相反但與 EAV 文獻的 "IV-RV divergence" 模式一致。AAPL 與多數測試不顯著，反映樣本小且跨事件異質性高。

Codex 審查待辦（主線程任務）。

## 檔案列表

- `k1429.py` — 分析腳本（可重跑）
- `k1429_results.json` — 完整結果 JSON
- `fig_rv_event_study.png` — 事件研究圖（-10 to +10 天 RV 曲線 + 95% CI）
- `fig_premium_compare.png` — Pre/Post premium 條形圖（含顯著性標記）
- `draft.md` — 繁中 trending 草稿
