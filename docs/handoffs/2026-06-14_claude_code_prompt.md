# Claude Code Prompt: Mac Studio VolPred Research Posts Only

請在 Mac Studio 本機的 VolPred 專案中工作：

`/Users/yhlai0911/Desktop/volpred-research`

先不要發 Facebook、不要改線上資料、不要刪檔、不要改 visibility、不要送任何付費生成。你的第一步只做「讀取交接檔與相關檔案，確認你掌握狀態」，然後用繁體中文回報。

## 必讀

請依序讀取：

1. `AGENTS.md`
2. `CLAUDE.md`
3. `docs/handoffs/2026-06-14_claude_code_volpred_posts_and_spacex_video.md`
4. `docs/workflow-index.md`
5. `docs/error_log.md`
6. `docs/claude-code-skill-handoff.md`

## 任務範圍更正

本次 Mac Studio 的 Claude Code 只負責：

1. 讀取 VolPred 研究資料與既有發文 queue。
2. 進行分析研究。
3. 生成「VolPred 專題貼文包」。

本次 Mac Studio 的 Claude Code **不負責影片製作**。

SpaceX / 專題影片製作會留在 MacBook 這邊處理。Mac Studio 這邊如果看到 SpaceX S-1 快照，只能把它當成參考資料，不要建立影片 jobs、不要做 Seedance/Kie/Suno payload、不要做影片企劃包。

## VolPred 相關快照

請讀這些本機專案內檔案，不要讀 `/Users/apple/...`，也不要用 `/Volumes/Macintosh HD-2/...`：

- `docs/handoffs/2026-06-14_related_files/volpred_fb_context/README.md`
- `docs/handoffs/2026-06-14_related_files/volpred_fb_context/posting-library.json`
- `docs/handoffs/2026-06-14_related_files/volpred_fb_context/posted-links.json`
- `docs/handoffs/2026-06-14_related_files/volpred_fb_context/posting-schedule.md`
- `docs/handoffs/2026-06-14_related_files/volpred_fb_context/profile-state.md`

也請用專案本身資料刷新 live truth：

- `https://volpred.zeabur.app/api/publications/feed?limit=20&offset=0&diversify=cluster`
- 對候選文章使用 canonical full text URL：`https://volpred.zeabur.app/v3/reports/{id}`

## 已知狀態

截至快照 `posting-schedule.md` 2026-06-14 13:42 CST：

- `mile_651c242d` 已發布。
- `mile_5ef55c52` 已發布。
- queue head 是 `mile_9d646fae`：
  - 標題：`跌了就多買一點，真的比較聰明嗎？把 5 段歷史排開後，答案沒有想像中穩`
  - 狀態：`blocked`
  - 原因：全文與公開 duplicate 檢查過關，但 Facebook 被登入 / QR modal 擋住，無法安全確認 Ivan live session、無法完成 live content library duplicate check、發文與第一留言。

後續 ready 候選包含：

- `mile_1b56cf6b`：股票加黃金還不夠？多放一點長債，報酬會少一點，但跌的時候真的差很多
- `mile_2fb1dfb3`：投資策略是不是越複雜越厲害？我們把 14 套方法排在一起，答案有點反直覺
- `mile_47ff52c7`：量今天的波動，選哪種方法差很多？五種工具實測 20 年 SPY 資料
- `mile_74d12ac6`：0DTE 真的把 SPY 的波動搬進日內了嗎？2022 斷點檢定只答對一半
- `mile_483425f2`：同樣都在尾巴加保險，為什麼只有這個模型真的補對？

## 你要產出的不是單篇流水發文，而是「專題貼文包」

請先分析 VolPred 最新研究與 queue，做一個專題貼文包。建議先做 3-5 篇，每篇都要有明確主題、研究依據、受眾鉤子與 Facebook 文案。

每篇專題貼文包至少包含：

1. `candidate_id`
2. 原文標題
3. full text URL
4. 研究重點摘要
5. 可驗證的數字 / 圖表 / 實證依據
6. 為什麼適合現在發
7. 是否和近期已發文重複
8. Facebook 主文草稿
9. 第一留言
10. anti-ai-style 自檢
11. 發布建議：`ready` / `needs_review` / `blocked`

## Facebook 硬規則

- 主文不能放 URL、`http`、`volpred.zeabur.app`、raw article id。
- 全文連結只能放第一留言。
- 第一留言格式固定：`全文：https://volpred.zeabur.app/v3/reports/{id}`
- 發文前必須查重，不能只看本地 cache。
- 若 Facebook session、QR、checkpoint、policy warning、留言失敗、重複疑慮、全文讀不到，立即標 `blocked` 或 `needs_review`，不要跳下一篇。

## 文風要求

- 自然台灣繁中。
- 像 Ivan Lai 的個人觀察，不像制式財經摘要。
- 短句、短段落、有留白。
- 先講具體數字或現象，再帶出判斷。
- 不要模板句，不要 AI 腔，不要翻譯腔。
- 不要只做「這篇文章在說什麼」摘要，要把研究變成一般讀者會停下來看的觀點。

## 回報格式

讀完後先回報：

1. 你確認的 VolPred queue 狀態。
2. 你判斷最適合做專題貼文的 3-5 篇候選。
3. 每篇候選需要補查什麼資料。
4. Facebook blocker 是否仍需人工解除。
5. 下一步你會生成哪些貼文包。

再次提醒：先不要發布，只產出分析與專題貼文包。
