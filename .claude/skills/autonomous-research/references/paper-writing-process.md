# 論文寫作標準流程（從實證結果到投稿）

**此流程不可跳步。違反等同論文失敗。**

## Phase 1: 定位（寫作前，必須完成）

### Step 1: 定主題和貢獻
- 從實驗結果出發，但不是列數字——要回答「so what?」
- 2-3 個 core contributions（FRL 2 個，JBF 3 個）
- 每個貢獻必須通過「busy portfolio manager 會不會改變行為？」測試

### Step 2: 文獻搜尋（至少 20 篇）
- WebSearch: Google Scholar、SSRN、arXiv 搜尋相關關鍵詞
- 必搜：方法論原創論文 + 同主題近 5 年論文 + 同市場論文
- 對每篇記錄：作者、年份、期刊、方法、核心發現、與我們的關係
- **不可跳過**——沒有文獻基礎的論文必被退件

### Step 3: 文獻定位
- 我們填什麼 gap？（必須從 Step 2 的文獻中導出）
- 我們跟最接近的論文有什麼不同？
- 寫成 1-2 段「文獻缺口」敘述

### Step 4: 理論推導
- 模型的數學性質（stationarity、identification、consistency）
- Information set 正式定義
- 跟已有模型的理論關係

### Step 5: 蒐集參考文獻和實驗檔案
- 參考文獻 PDF 下載到 paper/<name>/references/
- 實驗腳本和結果 symlink 到 paper/<name>/experiments/
- 建立 paper/<name>/README.md 列出所有來源檔案

## Phase 2: 寫作

### Step 6: 從源檔案提取數據
- **每個數字必須從 experiments/*_results.json 直接讀取**
- 不可從記憶或 prompt 摘要中抄數字
- agent prompt 應寫：「讀 experiments/kXXX_results.json 的 field_name」
- 建立 number → source 的追溯表

### Step 7: 學術寫作
- 遵循 finance-paper-quality skill 的所有規則
- 學術散文體，不用 bold headers
- 每個 claim 必須有引用支撐
- 自引必須讀原論文確認標題、作者、出版狀態
- 用 sci-hub skill 取得不確定的引用全文

## Phase 3: 品質保證

### Step 8: 自我審查
- /latex-academic-reviewer（完整 13 步）
- /citation-verifier（每筆引用驗證）
- 兩個都必須產出 PDF 報告

### Step 9: Codex Adversarial Review
- 必須在 prompt 中說明模型的 information set 和時間結構
- 不可盲目接受 Codex 結果——要用自己的理解判斷

### Step 10: 修正循環
- 修正所有嚴重和中度問題
- 重跑 Step 8-9 直到嚴重問題 = 0
- 每次修正產生版本號（v1.1, v1.2...）和差異報告

## Phase 4: 可重現性（Reproducibility）

### Step 11: 重現腳本
- 每篇論文必須有一個 `paper/<name>/reproduce.py`（或 `reproduce.sh`）
- 執行此腳本必須能**從原始數據重新產出論文中的所有數字和圖表**
- 腳本讀取原始數據 → 跑模型 → 輸出 JSON 結果 + 圖表 PNG → 可與論文表格逐一比對
- **如果重跑結果跟論文數字不一致，論文不可提交**

### Step 12: README 文檔
- paper/<name>/README.md 必須包含：
  - 數據來源和下載方式
  - 軟體需求（Python 版本、套件）
  - 重現步驟（1, 2, 3...）
  - 論文每張表格的數字 → 對應的 JSON 欄位 → 產出該數字的腳本行號
  - 已知限制（如 TAIFEX tick 需要 Dropbox 存取）

## 資料夾結構

```
paper/<name>/
├── main.tex (or main_v2.tex)
├── main.pdf
├── README.md           ← 數據來源 + 重現步驟 + 數字追溯表
├── reproduce.py        ← 一鍵重現所有結果
├── references/         ← 參考文獻 PDF
├── experiments/        ← 實驗腳本和結果（symlink 或副本）
├── reviews/            ← 審查報告 + citation check + Codex review
└── figures/            ← 圖表源檔案
```

**重現性檢查**：提交前必須在乾淨環境（fresh clone）執行 reproduce.py 確認所有數字一致。
