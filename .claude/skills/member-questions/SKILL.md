---
name: member-questions
description: >
  評分、stable-rerank、atomic claim、發佈綁定與回讀會員問題。
  用於會員提問排行或回答 lifecycle；研究交給 autonomous-research，文章交給 feed-publisher。
context: fork
user-invocable: true
---

# 會員問題流轉

本 skill 是 question lifecycle 的執行母本，不擁有觸發 cadence。每次只承接一題，所有
mutation 走 `uv run volpred ops`，以 receipt + live readback 結案。

若上游要求 materialize／dispatch member-QA work，先讀
`storage/ops/task_pool_mode.json`，再走該 mode 接受的 canonical ingress；本 skill
不直接建立 task，且 admission refusal 必保留 structured receipt。

## 流程

1. **讀取**

   ```bash
   uv run volpred ops question-ops-maintain --stub-if-no-work
   uv run volpred ops question-ranking-summary --limit 20
   ```

   沒有 pending／ranked work 就停止；不要建立空任務。

2. **評分與 stable insertion**

   pending 存在時讀 `references/evaluation-guide.md`，產 evaluation array，再執行：

   ```bash
   uv run volpred ops question-rerank \
     --evaluations-json /tmp/member-question-evaluations.json
   uv run volpred ops question-ranking-summary --limit 20
   ```

   第二次 summary 必須證明每個 evaluation 被套用、舊 ranked 題彼此相對順序未變。

3. **Atomic claim**

   ```bash
   uv run volpred ops question-claim <question_id>
   ```

   只有 exit 0 且 receipt `claimed=true` 才能開始。exit 2 代表 claim lost 或 duplicate
   gate 拒絕；依 receipt 改選下一題。重複題預設連結既有回答；真正新角度才依
   `question-claim --help` 提供可稽核理由。理由 receipt 缺失時停止。

4. **研究與文章 handoff**

   把已 claim 的原題、會員名稱、question id 與成功 claim receipt 交給
   `autonomous-research`；可發佈結果再交給 `feed-publisher`。member QA 發佈必須使用
   `audience=member_qa`、會員 proposer、exact question id，且直接 `published`。
   發佈 command 的 live syntax 以 `uv run volpred ops publish-milestone --help` 為準。

5. **先驗文章，再綁問題**

   從 publish receipt 取得 article id，先以
   `config/project_targets.json.site.default_remote_url` 的
   `/api/publications/feed/<article_id>` 確認 reader 可見，再執行：

   ```bash
   uv run volpred ops question-answer <question_id> \
     --answer "<可公開摘要>" --article-id <article_id>
   ```

6. **獨立回讀**

   再跑 `question-ranking-summary`，確認 exact question 進 `answered`、
   `linked_articles_count >= 1`，且 public article 的 question identity、audience 與
   proposer 正確。CLI exit 0 或 UI toast 都不能代替這兩段 readback。

完成條件：rerank（若需要）、claim、publish、answer receipts 全可追溯，question 與
reader-facing article exact match。任一步只有止血或缺 readback，狀態是 `contained`。

明顯 spam／測試輸入走
`uv run volpred ops question-archive <question_id> --reason "<audit reason>"`，並以 summary
確認已離開 active ranking；不要直接改狀態。
