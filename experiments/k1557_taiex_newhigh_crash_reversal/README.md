# K1557 — TAIEX 創一年新高後急殺：FinLab 病毒宣稱的系統性驗證

## 動機
FinLab 財經實驗室一則 FB 貼文宣稱（TAIEX 大盤 1999–今）：指數創一年新高後，3–4 天內急殺、最近 3 日跌幅排進過去一年最慘 2%；歷史 10 次；急殺後 3 個月 88% 收紅（中位 +4.7%），但抱 1 年中位 −1.7%、勝率不到三成、大輸買進持有 +8.5%；最慘 2007（金融海嘯）一年後 −47.6%。論點：短彈可搶、別當波段抱一年。

VolPred 用真實資料做**系統性驗證 + placebo bootstrap**，檢驗這個聽起來很玄的故事在統計上站不站得住。

## 資料
- `^TWII`（台灣加權指數）daily close，yfinance，1997-07 ~ 2026-06（7102 交易日；event 限 1999+，1997-98 當 252 日 rolling 暖身）。

## 方法（Codex 審查後修正版）
- **Event signal（只用 t 當下及之前資料，無 lookahead）**：過去 5 個交易日內出現 252 日新高（嚴格新高，非平高）**且** trailing 3 日報酬 ≤ 過去 252 日 3 日報酬分佈的第 2 百分位（跌最慘 2%）。
- **Entry = t+1 收盤**（事件在 close[t] 才確認，可交易進場是次日；Codex 修正 v1 用 close[t] 偏樂觀）。
- **Dedupe = first trigger**（20 日內同一波只取第一個觸發日；Codex 修正 v1 取「最慘 r3」= 事後挑谷底會高估反彈）。
- Forward 3M/6M/1Y = entry 後 63/126/252 交易日報酬。
- **Baseline**：無條件「隨便買任一日」同 forward 定義。
- **Placebo bootstrap（核心）**：隨機抽 n 個日期 10000 次，看事件後報酬中位數落在隨機分佈第幾百分位（真信號 vs 雜訊）。
- **Sensitivity**：lookback ∈ {3,5,7} × pctile ∈ {2,3,5}。seed=42。

## 結果（誠實版）
- **事件數 13**（主規格 lb5/pct2），非 FinLab 的 10（其 filter 未明確定義，數量對 filter 敏感）。
- **3M 短彈**：中位 +4.0%、勝率 75% —— 但無條件隨便買 3M 也有 +2.82%；**placebo 顯示事件落在隨機分佈第 69 百分位 → 統計上與亂買無異（雜訊）**。
- **6M**：中位 +5.4%（**反駁** FinLab 的 −0.2%），placebo 第 61 百分位（與隨機無異）。
- **1Y**：主規格中位 −5.6%、placebo 第 3 百分位（看似異常 p≈0.03）；**但 sensitivity 範圍 −5.6% ~ +3.4%（換 filter 翻正），9 種切法 multiple-testing 期望本就會中一個 p<0.05，n=11 信賴區間巨大 → 不 robust**。
- 2007 確有尾部：2007-11 事件 1 年後 −49.1%（≈ FinLab −47.6%），但屬 13 次中撞上 GFC 一次，非規律。
- 無條件 baseline 1Y +9.1%（≈ FinLab +8.5%，驗證 baseline 正確）。

## 結論
**創新高急殺後沒有可靠、能下注的 edge。** FinLab 叫人搶的「短彈」在 placebo 下與隨機無異（雜訊）；嚇人的「一年詛咒」是特定 filter + 小樣本 + multiple-testing 拼出來的故事，換個合理切法就消失。整個論述建在 ~13 個事件上。誠實答案 = 別照這個模式下單。

## 防錯 / 限制
- Codex review 2026-06-28：v1 FAIL（entry timing、retrospective dedupe、缺 README）→ 已全修為本版。
- 無 lookahead（event signal ≤ t，forward 從 t+1）；baseline 同 forward 定義；seed 固定。
- 小樣本（n=5~28 by filter）→ 所有統計皆描述性、信賴區間大，如實揭露不隱藏。
- ^TWII 為價格指數（無股利），forward 為價格報酬；不含交易成本/滑價。

## 檔案
- `k1557.py`、`k1557_results.json`、`fig_*.png`
