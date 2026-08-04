---
name: feedback_graphify_query_before_grep
description: 架構/caller/依賴/影響面問題先走 graphify query，不要一路 grep；整合是 Codex 已建好的，不要重裝
metadata: 
  node_type: memory
  type: feedback
  originSessionId: c4ef4804-4fe0-4950-af7c-8f22d3f398ce
  modified: 2026-08-04T03:12:30.248Z
---

VolPred 有完整的 code graph 整合，**canonical 入口是
`uv run python scripts/graphify_integration.py query "<question>"`**（不是裸 CLI，走它才會寫
retrieval-proxy usage record）。註冊了兩張圖：`root` 與 `active_frontend`（前端要用
`--graph active_frontend`，不可從 root 圖推論前端行為）。輔助命令：`graphify explain "<node_id>"`
列某符號的所有 caller/callee，`graphify path "A" "B"` 查關係。

**Why**：2026-08-04 老闆點出「你知道你有 graphify 可以用嗎」。我整個 session 用 grep + 手寫 AST
walker 做定位，一次都沒用它 —— 包括自己寫 AST 掃 re-pend sites（`graphify explain
scripts_task_pool_claim_repend_task` 一行就列出全部 4 個 caller），以及硬拼 lazypack strict
plan schema（連吃三次 validation error；`query_usage.jsonl` 顯示別人昨天同一個問題只花 ~923
token，全 corpus 是 ~5.9M）。同一輪我還因為 grep 開太寬把一整封歸檔郵件拉進 context。

規則本體在 **`AGENTS.md` L333-349 與 L478-495**，我在 session 開頭被明確要求讀這份檔卻只跑了
`wc -l` 就跳過。關鍵條文：
- 架構 / caller / 依賴 / legacy path / 影響面 / data-flow 問題 **先走 graphify，再讀命中的原始碼**
- **`graphify-out/` 髒檔不是跳過 graphify 的理由**（它整場掛在 dirty list，我當雜訊略過）
- **Graphify 是 map 不是 proof**：結論一定要回到 `source_location` 對應原始碼 / 測試 / runtime 驗證

**How to apply**：
- 定位類問題（誰呼叫它、owner 是誰、改這裡會影響什麼、canonical writer 在哪）**先 query，再 grep**；
  grep 降級成拿到節點後的精確確認手段。
- 用前先 `status` 看 `fresh`；stale 就 `update --graph all`（AST-only、本機、無 API 成本）。
- **查詢要窄**。問太寬會被 ~1200 token 預算截斷（我第一次就是）；先從 graph vocabulary 取詞，
  或用 `context_filter=['call']` / `get_node` 針對單一符號。
- **不要重裝**。整合是 Codex 做的（`scripts/graphify_integration.py`、
  `config/graphify_integration.json`、`.graphifyignore`、commit hook 自動 rebuild）。我曾提議跑
  `graphify install --platform claude`，那會在已完成的東西上疊第二套 —— 動手前先查既有機制
  （見 [[feedback_check_existing_mechanism_before_building]]）。
- 更廣的教訓：**session 開頭被指定要讀的檔就要真的讀完**，不是 `wc -l` 確認存在。
  相關：[[reference_knowledge_wiki_and_context_economy]]、[[feedback_verify_before_restructure]]。
