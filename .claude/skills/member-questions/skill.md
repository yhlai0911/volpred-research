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
4. 從 ranked 榜單挑最高分且未承接題目：
   - 直接進研究
   - 或先加入研究候選池
5. 若進研究候選池，遵循 lifecycle：
   - `queued` → `claimed` → `completed` / `cancelled`
6. 做研究（LanceDB 搜尋 + Agent 實驗 if needed）
7. 發 feed 文章：`uv run volpred ops publish-milestone --title "..." --description "..." --phase member_qa --audience member_qa --proposer 會員名稱 --status draft --tags "會員提問,..."`
   - **必須傳 `--audience member_qa` 和 `--proposer 會員名稱`**（否則 badge 和署名不顯示）
8. 更新 question（answer=摘要, feed_articles=[article_slug]）→ status: `answered`
9. 回報：處理了哪個問題、發了什麼文章、榜單是否更新

## 詳細實作
見 `references/evaluation-guide.md`（評分標準、Supabase 程式碼、文章格式模板、DB 欄位）
