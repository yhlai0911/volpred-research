---
name: 網站文章必有 4 維度——深度/可讀性/資訊性/參考性
description: feed 文章不只是補池數量，每篇要符合 4 維度標準才能持續吸引讀者回訪
type: feedback
originSessionId: 91283b9e-7227-43f5-88bb-9d92168d243a
---
# 網站文章 4 維度標準

每篇 feed 文章（無論 audience=general 或 research）必須同時符合 4 個維度，才能達到「持續吸引人來看」（高回訪率 + 高分享率）的 Mission 第 1+5 條目標。

**Why**：用戶 2026-04-27 明示。文章不只是「補 draft pool 數量」的 ops 工具——而是 Mission L4「把文章寫好」+ L24「把曝光流量拉高」的核心載體。讀者回訪靠的是「下次來還能看到值得讀的東西」，靠數字流水線（一篇 1500 字 + 2 張圖）滿足不了真讀者。

## 4 維度與可驗證 criteria

### 1. 深度（depth）
- 不只描述結果，要解釋 **mechanism**（為什麼會這樣）
- 至少 1 個 **counter-intuitive insight** 或 **methodology lesson**（讀者不能只看 abstract 就猜到結論）
- **跨 K cross-reference ≥3 個**（顯示這結論在更大的 research arc 中的位置）
- 不含廢話：刪掉 paragraph 後讀者理解不變 = 廢話

### 2. 可讀性（readability）
- **Title punchy**：避免「K908: ...」這種 academic 標題；用 hook（矛盾 / 場景 / counter-intuitive 設問）
- **Intro 要 hook**：具體場景、矛盾、直接挑戰讀者預設
- **段落 ≤5 句**；長段落必拆
- **專有名詞首次必定義**（Trinity / HistSim / df / Harvey 等）
- **結尾 take-away 一句話**總結（讀者會記住的那句）

### 3. 資訊性（informativeness）
- **真實圖表 ≥2 張**（matplotlib PNG，禁 ASCII / 文字框）
- 真實數字（具體 magnitude，不是「顯著改善」這種空話）
- **數據來源標明**（yfinance / FRED / TAIFEX / K 編號）
- **統計檢定方法**標明（Harvey / Kupiec / Christoffersen / Basel Trinity / DM 等）
- **樣本 size + 期間** 標明（e.g.「2019-01 to 2026-03 OOS, n=1821」）

### 4. 參考性（reference value）
- **Cross-link ≥3 個**相關 K / paper / experiment
- **延伸閱讀**段落（連結文末，方便讀者深挖）
- **Reproduce method 簡述**（哪個 script 哪個 results.json，研究誠實 + 可復現原則）
- 文末標明 K 編號 + 數據來源 + experiment script path

## How to apply

- **派 agent 寫文章前**：brief 必明示這 4 維度 + 可驗證 criteria；agent prompt 內加 self-check checklist
- **主線程 verify agent 結果時**：用 4 維度 checklist 而非僅看「字數 + 圖表 ≥2 張」表面條件
- **dispatch dedup 邏輯**：同一 K 已有文章但不符 4 維度，**可以重派**（重新寫深度版）；不算 duplicate
- **既有文章 audit**：定期回審 feed 內 article 是否符合 4 維度（top viewed 優先），不符標準的考慮重寫或下架

## Anti-pattern（不要再做）

- 一篇文章只是 results.json 數字翻譯成中文 + 兩張圖（缺 mechanism 解釋 → 深度 0）
- Title 用「K567: International VT...」這種 academic 命名（缺 hook → 可讀性 0）
- 「跨資產實測表現顯著改善」沒具體數字（缺資訊性）
- 文末沒 cross-link 沒 reproduce method（缺參考性 → 讀者讀完就走，不會回訪）

## 教訓 reference

- K908 文章 mile_3eb8657c (2026-04-26 published) 達標所有 4 維度（title「最強預測模型加上 HistSim」punchy + mechanism 解釋 + Kupiec/Christoffersen/Basel 標明 + K889/K802/K825 cross-link + reproduce path）— 可作為 future article 的 reference template
- 但 tags 缺 K908 是 minor 違規（K908 brief tag enforce 規則之後加強）
