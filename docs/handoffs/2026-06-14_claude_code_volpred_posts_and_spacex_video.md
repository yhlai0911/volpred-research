# Claude Code Handoff: Mac Studio VolPred Research Posts

更新時間：2026-06-14 19:35（台灣時間）

## 更正後分工

這份交接檔只交給 **Mac Studio 上的 Claude Code** 處理 VolPred 工作。

Mac Studio Claude Code 的任務：

1. 讀取 VolPred 研究資料、發文 queue、已發文紀錄。
2. 進行分析研究。
3. 生成 VolPred 專題貼文包。

Mac Studio Claude Code **不負責影片製作**。

SpaceX S-1 專題影片會留在 MacBook 這邊製作。若 Mac Studio 專案內有 SpaceX S-1 快照，只作為跨工作線參照，不要建立影片 job，不要送 Kie / Seedance / Suno，不要做影片企劃包。

## 專案位置

Mac Studio 本機專案根目錄：

`/Users/yhlai0911/Desktop/volpred-research`

不要在 Mac Studio Claude Code 裡使用 MacBook 的 `/Users/apple/...` 路徑，也不要使用 MacBook 掛載視角的 `/Volumes/Macintosh HD-2/...` 路徑。

## 必讀規則

Claude Code 進入專案後，先讀：

1. `AGENTS.md`
2. `CLAUDE.md`
3. `docs/workflow-index.md`
4. `docs/error_log.md`
5. `docs/claude-code-skill-handoff.md`
6. `config/project_targets.json`
7. `config/runtime_schedules.json`

專案硬規則：

- 使用繁體中文。
- 用 `uv` 管理 Python venv 與指令。
- 研究誠實優先，所有數據與圖表必須可追溯。
- 不要手修歷史 JSON 或 DB 來假裝完成，錯誤要回到流程與程式修。
- 發文、同步、研究與平台動作優先走專案既有 CLI / skill / rules。
- 讀者向文字必跑 anti-ai-style：自然台灣繁中，避免模板腔、翻譯腔、空泛總結。

## 本機快照資料

VolPred FB context 已複製到專案內：

- `docs/handoffs/2026-06-14_related_files/volpred_fb_context/README.md`
- `docs/handoffs/2026-06-14_related_files/volpred_fb_context/posting-library.json`
- `docs/handoffs/2026-06-14_related_files/volpred_fb_context/posted-links.json`
- `docs/handoffs/2026-06-14_related_files/volpred_fb_context/posting-schedule.md`
- `docs/handoffs/2026-06-14_related_files/volpred_fb_context/profile-state.md`

這些是交接快照，不是 live truth。開工時要刷新：

- VolPred 最新 feed：`https://volpred.zeabur.app/api/publications/feed?limit=20&offset=0&diversify=cluster`
- 候選全文：`https://volpred.zeabur.app/v3/reports/{id}`

## 目前確認狀態

截至快照 `posting-schedule.md` 2026-06-14 13:42 CST：

- 最近兩篇已成功發布：
  - `mile_651c242d`：好策略被成本吃掉 27%：11 個 VT 策略的實施費用拆解
  - `mile_5ef55c52`：同樣從 5 萬美元出發，20 年後差到快 5 倍：問題常常不是你不夠會算
- Queue head：
  - `mile_9d646fae`：跌了就多買一點，真的比較聰明嗎？把 5 段歷史排開後，答案沒有想像中穩
  - 狀態：`blocked`
  - 原因：全文與公開 duplicate 檢查都過關，但 Facebook 被登入 / QR modal 擋住，無法安全確認 Ivan live session，也無法發布與留言。
- 後續 ready 候選：
  - `mile_1b56cf6b`：股票加黃金還不夠？多放一點長債，報酬會少一點，但跌的時候真的差很多
  - `mile_2fb1dfb3`：投資策略是不是越複雜越厲害？我們把 14 套方法排在一起，答案有點反直覺
  - `mile_47ff52c7`：量今天的波動，選哪種方法差很多？五種工具實測 20 年 SPY 資料
  - `mile_74d12ac6`：0DTE 真的把 SPY 的波動搬進日內了嗎？2022 斷點檢定只答對一半
  - `mile_483425f2`：同樣都在尾巴加保險，為什麼只有這個模型真的補對？

## 這次要產出的東西

不是單篇流水發文，也不是只按 queue 發出去。

這次要先做分析研究，產出 **VolPred 專題貼文包**。建議先做 3-5 篇，每篇都應該像一個可發布的小專題。

每篇至少包含：

1. `candidate_id`
2. 原文標題
3. full text URL
4. 研究重點摘要
5. 可驗證的數字 / 圖表 / 實證依據
6. 為什麼適合現在發
7. 和近期已發文是否重複
8. Facebook 主文草稿
9. 第一留言
10. anti-ai-style 自檢
11. 發布建議：`ready` / `needs_review` / `blocked`

建議輸出到：

`docs/handoffs/2026-06-14_related_files/volpred_fb_context/topic_post_packages.md`

如果後續要整合回正式發文庫，再依專案既有流程同步，不要直接手修歷史資料。

## Facebook 非談判規則

VolPred Facebook 貼文必守：

- 發文前要打開 VolPred 全文，不可只看標題或本地摘要。
- Facebook 主文不得放 URL、`http`、`volpred.zeabur.app`、raw report id。
- 全文連結只放第一留言，格式固定：
  - `全文：https://volpred.zeabur.app/v3/reports/{id}`
- 不能只靠本地 cache 判斷沒有重複；至少檢查：
  - `posted-links.json`
  - `posting-library.json`
  - `posting-schedule.md`
  - `profile-state.md`
  - Ivan live Facebook profile / content library
  - 公開 web-visible / Facebook-visible exact id 或 exact title
- 如果 Facebook session、QR、checkpoint、policy warning、留言失敗、重複疑慮、全文讀不到，立即停止，標 `blocked` 或 `needs_review`，不要跳下一篇。
- 發文成功後要驗證主文 permalink 與第一留言可見，再同步狀態檔。

## 文風

- 像 Ivan Lai 個人觀察，不像制式財經摘要。
- 短句、短段落，有留白。
- 先講一個具體現象或數字，再慢慢帶出判斷。
- 不要把站內長文硬縮成摘要。
- 不要每篇都用「這件事提醒我們」這種模板句。
- 台灣繁中，不要中國用語與英文直譯句。

## 驗收標準

VolPred 專題貼文包：

- 每篇已讀全文並留下查重判斷。
- 每篇有明確研究依據，不只是心得。
- FB 主文無連結。
- 第一留言格式正確。
- 文風自然，不像 AI 摘要。
- 若不能發，原因具體到 live session / duplicate / comment / policy / article readability 等層級。

## 回報格式

Claude Code 讀完交接後先回報：

1. 確認的 queue 狀態。
2. 最值得先做成專題貼文的 3-5 篇候選。
3. 每篇還需要補查的資料。
4. Facebook blocker 是否仍需人工處理。
5. 下一步預計輸出的貼文包檔案。

再次提醒：先不要發布。先做分析研究與專題貼文包。
