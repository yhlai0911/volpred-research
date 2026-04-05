# 論文全面徹查計劃

**建立日期**：2026-04-05
**目的**：徹查所有 8 篇論文（7 篇已公開 + 1 篇 PRG 草稿）的品質問題
**原則**：不下架，但逐篇修正到可投稿水準

## 現狀總覽

| # | 論文 | 頁數 | 引用數 | 目標期刊 | 實驗檔案 | 參考文獻 | 審查報告 | 狀態 |
|---|------|------|--------|---------|---------|---------|---------|------|
| 1 | leverage-direction | 62 | 54 | JBF | ❌ 0 | ❌ 0 | ❌ 0 | 未連結實驗 |
| 2 | taiwan-vt | 60 | 34 | PBFJ | ✅ 21 | ❌ 0 | ✅ 5 | 部分完成 |
| 3 | vt-trend-following | 33 | 18 | JPM/FAJ | ❌ 0 | ❌ 0 | ❌ 0 | 未連結實驗 |
| 4 | vt-insurance-cost | 13 | 15 | FRL | ✅ 6 | ❌ 0 | ❌ 0 | 實驗已連結 |
| 5 | vt-crowding-abm | 14 | 11 | FRL | ✅ 8 | ❌ 0 | ❌ 0 | 實驗已連結 |
| 6 | vix-sufficiency | 39 | 40 | JFE/RFS | ❌ 0 | ❌ 0 | ❌ 0 | 未連結實驗 |
| 7 | volatility-absorption | 38 | 37 | ? | ❌ 0 | ❌ 0 | ❌ 0 | 未連結實驗 |
| 8 | prg-periodic-garch | 12 | 15 | FRL | ✅ 22 | ❌ 0 | ✅ 審查+引用 | 審查完成待修正 |

**共同問題**：所有論文都缺少 references/ 資料夾（參考文獻 PDF）和 reproduce.py（可重現性腳本）

## 每篇論文的徹查流程（7 步）

### Step 1: 實驗連結檢查
- 論文中每個實驗結果（表格、數字）→ 對應到哪個 experiments/kXXX_results.json？
- 建立 **數字追溯表**（Table X, Row Y, Column Z → kXXX_results.json, field_name）
- 如有無法追溯的數字 → 標記為 ⚠️ 需補實驗或移除

### Step 2: 數字驗證
- 對每個追溯到的數字，讀 JSON 確認跟論文中的值一致
- 不一致 → 標記為 ❌ 並記錄正確值
- PRG 論文已知有 Table 4 VaR 數據張冠李戴

### Step 3: 引用驗證（citation-verifier skill）
- 每筆引用 WebSearch 驗證：作者、年份、標題、期刊、DOI
- 內容引用準確性：論文對被引文獻的描述是否正確？
- APA 格式檢查
- 產出 citation_check.md

### Step 4: 學術審查（latex-academic-reviewer skill）
- 完整 13 步審查
- 特別注意：
  - 研究動機是否有文獻支撐
  - 模型假設是否明確且合理
  - 方程式是否正確（stationarity 條件等）
  - 學術散文體（無 bold headers、無 bullet points）
  - 貢獻宣稱是否匹配證據
- 產出 review LaTeX PDF

### Step 5: 可重現性
- 建立 reproduce.py：從原始數據到論文所有數字
- 執行並確認數字一致
- 產出 README.md（數據來源 + 重現步驟 + 追溯表）

### Step 6: 參考文獻蒐集
- 下載所有引用文獻的 PDF 到 references/
- 確認每個方法論引用的原始論文都被正確理解

### Step 7: 修正
- 根據 Step 1-6 的發現修正論文
- 產生新版本（v2.1 等）和差異報告
- 重新編譯 PDF
- 更新 Supabase 的 PDF

## 優先順序

基於**公開曝光度 × 問題嚴重度**排序：

### Tier 1：最高優先（已知有問題 + 公開中）
1. **prg-periodic-garch**：已知 5 嚴重 + 3 引用錯誤。但這篇是草稿未正式公開，修正成本低。
2. **vt-insurance-cost** (Paper 4, FRL)：13 頁短文，本 session 修過散文體。需驗證數字。
3. **vt-crowding-abm** (Paper 5, FRL)：14 頁短文，K864 有新結果可加入。需驗證數字。

### Tier 2：中優先（大論文，影響大）
4. **leverage-direction** (Paper 1, JBF)：62 頁，54 引用。最大最重要的論文，但未連結任何實驗。
5. **taiwan-vt** (Paper 2, PBFJ)：60 頁，已有部分審查。本 session 加了 TAIFEX 高頻結果。

### Tier 3：需評估
6. **vt-trend-following** (Paper 3)：33 頁，review_v2 已有 5 HIGH 待修。
7. **vix-sufficiency**：39 頁，40 引用。大量實驗支撐（29 次 sufficiency），但未連結。
8. **volatility-absorption**：38 頁，37 引用。需確認是否有獨立實驗支撐。

## 時間估計

| 步驟 | 每篇耗時 | 8 篇總計 |
|------|---------|---------|
| Step 1 實驗連結 | 30 min | 4 hr |
| Step 2 數字驗證 | 1 hr | 8 hr |
| Step 3 引用驗證 | 1 hr | 8 hr |
| Step 4 學術審查 | 2 hr | 16 hr |
| Step 5 可重現性 | 2 hr | 16 hr |
| Step 6 參考文獻 | 30 min | 4 hr |
| Step 7 修正 | 3 hr | 24 hr |
| **合計** | **~10 hr/篇** | **~80 hr** |

## 執行方式

- 每次 session 處理 1-2 篇（Tier 1 先）
- 可並行：Step 3（引用驗證）和 Step 4（學術審查）可同時用 agent 跑
- Step 5（可重現性）必須串行（需要手動確認）
- 每篇完成後 git commit + 更新此計劃的進度

## 進度追蹤

| 論文 | Step 1 | Step 2 | Step 3 | Step 4 | Step 5 | Step 6 | Step 7 | 完成 |
|------|--------|--------|--------|--------|--------|--------|--------|------|
| vt-insurance-cost | ✅ | ✅ | ✅ R3 | ✅ R3 S=0 | ✅ | ❌ PDF | ✅ v1.4 | ✅ |
| vt-crowding-abm | ✅ | ✅ | ✅ R2 | 🔄 R3 | ✅ | ❌ PDF | ✅ v1.5 | 🔄 |
| prg-periodic-garch | ✅ K880/881/886/874d | ✅ 復現OK | ✅ R2 | ✅ R2 S=0 | ✅ reproduce.py | ❌ PDF | ✅ v1.1 (14p/19ref/6mkt) | 🔄 |
| leverage-direction | ✅ 多數部分驗證 | ✅ 2 mismatch | ❌ | ❌ | ❌ | ❌ | ❌ 需補JSON | |
| taiwan-vt | ✅ 嚴重gamma衝突 | ✅ 多處mismatch | ✅ 舊版 | ✅ 舊版 | ❌ | ❌ | ❌ 需重估 | |
| vt-trend-following | ✅ ~50%無源 | ✅ 3H | ✅ 舊版 | ✅ 舊版 | ❌ | ❌ | ❌ 需補實驗 | |
| vix-sufficiency | ✅ 6/9驗證 | ✅ T6嚴重 | ❌ | ❌ | ❌ | ❌ | ❌ T6 era例外 | |
| volatility-absorption | ✅ 核心OK/63+無源 | ✅ T6差異 | ❌ | ❌ | ❌ 無腳本 | ❌ | ❌ 需補腳本+T9-10 | |
