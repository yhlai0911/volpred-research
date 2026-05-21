# Sources — NotebookLM `20291e44-e14a-4dbc-9df1-ff4d252f581d`

本 skill 全部規則與範例的引用來源。Notebook 共 5 個 sources，4 個 Google Docs +
1 個 YouTube。

---

## Source 1：AI 生成文案專業品質控管與編輯審核準則

- **類型**：Google Docs（私人連結）
- **角色**：編輯審核 SOP 的主要來源
- **核心貢獻**：
  - 為「AI 生成 → 人工審核」工作流定義 3 階段 SOP
  - 強調編輯不應信任 AI 自我修正
  - 提供逐句新資訊測試方法
- **本 skill 應用**：[editor-sop.md](editor-sop.md) 階段二、階段三大部分內容
- **NotebookLM source_id**: `8b4ccf36-9ad7-4d22-a3ce-94ad7f0c5b62`

可能對應 URL（4 篇 Google Docs 之一，未確認逐一對應）：
- https://docs.google.com/document/d/1lv8umUiWabElcuiCrMAtjQAj5E6gBJ0Apqj8wKb_Z9c/edit
- https://docs.google.com/document/d/1lZHVb8UyA3rIdtvOGQiU4mk-uNt9l9qcDXOnoEvBqTI/edit
- https://docs.google.com/document/d/1Ia1xRsYs5_aItDdbLkudJCQcrWmhu8rsoY4v2fv2JEQ/edit
- https://docs.google.com/document/d/1pyhyA2ZZZ8oLT8uJRsHNs2Ji4fXmtJHvf1gzVp7RP98/edit

（4 篇 Google Docs URL 為私人，僅可在用戶 Google 帳號內訪問；NotebookLM CLI
作為服務端 fetcher 無法越權，故 sources.md 不做 1-to-1 mapping，列為候選清單。
要 verify 個別內容需透過 NotebookLM Web UI 開啟。）

---

## Source 2：專業文案生成策略建議書：從避雷到升華的 AI 協作指南

- **類型**：Google Docs（私人連結）
- **角色**：prompt-engineering 5 原則的主要來源
- **核心貢獻**：
  - 把 AI 從「代筆者」重新定位為「研究助理（福爾摩斯）」
  - 提出「主動對槓」AI 的方法論
  - 強調人類「編輯之眼」與批判性思維
- **本 skill 應用**：[prompt-templates.md](prompt-templates.md) 原則 5（蘇格拉底對槓）+ SKILL.md
  人類角色定位段
- **NotebookLM source_id**: 見 notebook（5 sources 之一）

---

## Source 3：拒絕「AI 味」：提升文字生命力的寫作邏輯大揭密

- **類型**：Google Docs（私人連結）
- **角色**：8 大地雷 catalog 的補充來源 + 「人味」概念框架
- **核心貢獻**：
  - 把 AI 文章的問題從「事實錯誤」重定向到「觀感問題」（讀者「想吐」/「噁心感」）
  - 提出「以景抒情」取代「情緒命名」的核心方法
  - 文字「人味」與「溫度」的可操作定義
- **本 skill 應用**：[8-landmines.md](8-landmines.md) 地雷 3 標籤式情緒 +
  [bad-vs-good.md](bad-vs-good.md) 畫面轉化範例

---

## Source 4：提示詞優化手冊：讓你的 AI 報告更有「人味」

- **類型**：Google Docs（私人連結）
- **角色**：prompt-engineering 5 原則的最主要來源（手冊型 reference）
- **核心貢獻**：
  - 「虛擬角色降齡」設定技巧（年齡降級）
  - 「先寫長、人為標記、後精鍊」裁切術
  - 「以景抒情」實戰示範（如「一江春水向東流」）
  - 8 個邏輯地雷的初始 catalog（與 Source 5 交叉驗證）
- **本 skill 應用**：[prompt-templates.md](prompt-templates.md) 原則 1/2/3/4 的核心 +
  [8-landmines.md](8-landmines.md) 地雷 1/2/4/7/8 引用

---

## Source 5：吳淡如 EP5 — AI 寫文的 8 個地雷

- **類型**：YouTube
- **URL**：https://www.youtube.com/watch?v=eIeqTmCM9Vo
- **講者**：吳淡如（50 年寫作經驗）
- **NotebookLM source_id**: `8d1bdf81-18f6-417c-a67f-9693fc0bba00`
- **角色**：8 大地雷 catalog 的**權威來源**（基於 50 年寫作經驗的口述總結）
- **核心貢獻**：
  - 完整列出 8 大地雷：「不是…而是」/ 換句話說 / 標籤情緒 / 爆米花 /
    生硬轉折 /「有人說」/ 翻譯腔「這」/ 吊書袋
  - 提出「下指令時下修年齡層」實戰技巧
  - 強調「字數先多後少由人裁減」
  - 推薦用 Gemini 查證 AI 編造的數據與引文
- **本 skill 應用**：[8-landmines.md](8-landmines.md) 全 8 條 catalog 的命名與分類 +
  [prompt-templates.md](prompt-templates.md) 原則 1（年齡降級）/ 原則 2（長文裁切）/
  原則 5（Gemini 查證）

---

## Notebook metadata

- **Notebook ID**：`20291e44-e14a-4dbc-9df1-ff4d252f581d`
- **Web URL**：https://notebooklm.google.com/notebook/20291e44-e14a-4dbc-9df1-ff4d252f581d?authuser=2
- **Authenticated account**：用戶在 NotebookLM CLI `notebooklm login` 時授權的 Google
  帳號（可由 `notebooklm auth check` 查）
- **建立目的**：彙整中文寫作圈關於「AI 味」的最佳實踐，做為本 skill 唯一 ground truth

## 為什麼用 NotebookLM 而非把內容 inline

- 內容會持續更新（新地雷 / 新範例 / 新 prompt 技巧）— 把資料留在 NotebookLM
  讓內容單一 source of truth，skill 透過 reference 引用，不複製
- 5 sources 都是中文原生內容，NotebookLM zh-Hant query 能力勝過直接 grep
- 未來新增 source（如新文章、新 YouTube）只要加進 notebook，本 skill 自動受益

## 如何引用 NotebookLM 內容更新

當 notebook 新增 source 或更新內容後，本 skill 規則 / 範例如需相應更新：

1. 跑查詢確認新內容：`notebooklm ask "新增了什麼新原則？" --notebook 20291e44-...`
2. 對應更新 [8-landmines.md](8-landmines.md) / [prompt-templates.md](prompt-templates.md) /
   [editor-sop.md](editor-sop.md) / [bad-vs-good.md](bad-vs-good.md)
3. Commit `skill(anti-ai-style): sync from notebook update <date>`
4. 更新本 sources.md 的「核心貢獻」段以反映新內容
