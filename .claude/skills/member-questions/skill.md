---
name: member-questions
description: >
  會員問題研究。每 6 小時由 cron 自動觸發。評估排名會員提問，
  選最高分做研究，回答發佈為 feed 文章（proposer=會員名稱），
  問答頁自動連結文章。每次只處理一個問題。
  Trigger phrases: '會員問題研究', 'member questions', '提問排名', '評估會員問題'
user-invocable: true
---

# 會員問題研究

## 核心原則
- **每個回答 = 一篇完整資訊性文章**（1000-2000 字，委託研究報告等級）
- **每次只處理一個**（排名最高且尚未被承接的問題）
- **先研究再回答**（不能只複製現有 knowledge，要有新分析或數據驗證）
- **proposer = 會員名稱**（不是 Claude）
- **會員是付費的**——品質等同一般讀者文章（場景、表格、操作建議、風險說明）
- **排名更新採 stable insertion**：待評分題目插入既有榜單，但原 ranked 榜單彼此相對順序不可變
- **固定表格欄位**：排名 / 前次排名 / 主題 / 提出者 / 狀態

## 流程
1. 先讀目前榜單與待評分題目：
   - `uv run python -m volpred.cli ops question-ranking-summary --limit 20`
   - 或 `/api/admin/questions/summary`
2. 對 `pending_questions` 逐題做 LLM 評分，產生：
   - `score`
   - `score_breakdown`
3. 呼叫 `question-rerank`，把待評分題目插入既有榜單適當位置：
   - 只插入新題目
   - 舊榜相對順序不可變
   - 更新 `current_rank` / `prev_rank` / `status`
4. 從 ranked 榜單挑最高分且未承接題目
5. **Atomic claim（跨 session 防撞必做）**：
   - `uv run volpred ops question-claim <question_id>`
   - 成功（exit 0）→ 繼續做研究
   - 失敗（exit 2，claimed=False）→ 代表另一個 session 已經接走，挑下一題重試
   - 機制：Supabase 條件式 PATCH `status=ranked → researching`，原子操作
6. 若進研究候選池，遵循 lifecycle：
   - `queued` → `claimed` → `completed` / `cancelled`
7. 做研究（LanceDB 搜尋 + Agent 實驗 if needed）
8. 發 feed 文章：`uv run volpred ops publish-milestone --title "..." --description "..." --phase member_qa --category member_qa --audience member_qa --proposer 會員名稱 --status draft --tags "會員提問,..."`
   - **必須傳 `--category member_qa`、`--audience member_qa` 和 `--proposer 會員名稱`**（否則 badge 和署名不顯示）
9. 連結文章到問題：`uv run volpred ops question-answer <question_id> --answer "摘要" --article-id <article_slug>`
   - **文章是 draft → 問題保持 `researching`**（不是 answered），文章發佈時 release-pool 自動改為 `answered`
   - **文章是 published → 問題直接標為 `answered`**
   - ⚠️ **不要在文章發佈前手動改問題狀態為 answered**——這是之前的 bug
10. 回報：處理了哪個問題、發了什麼文章、問題狀態（researching=等待發佈 / answered=已完成）

## 詳細實作
見 `references/evaluation-guide.md`（評分標準、Supabase 程式碼、文章格式模板、DB 欄位）
