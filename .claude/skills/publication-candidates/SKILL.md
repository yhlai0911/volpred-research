---
name: publication-candidates
description: >
  Use to rank research-driven or event-driven article candidates before any
  prose is drafted. It returns an evidence-backed brief and duplicate verdict;
  it does not write, publish, schedule, or deliver an article.
context: fork
agent: fresh-context-worker
user-invocable: true
---

# Publication Candidates

這是**選題 leaf skill**。輸出是一份可交給內容 producer 的 brief，不是文章，也不是排程指令。

## 1. 先讀 live control state

```bash
uv run python scripts/task_pool_control.py status
uv run volpred ops publication-candidates-summary --limit 10
uv run volpred ops event-preview
```

- 任務池是 queued execution、direct execution 或 restore 中，以
  `storage/ops/task_pool_mode.json` 為 canonical owner，並以
  `task_pool_control.py status` 的 receipt 為準。
- 不把任何固定 task mode、觸發頻率或 pending 數抄進 skill。
- `storage/next_tasks.json` 的 admission 與 ownership 依 live mode 解讀；
  不得繞過 formal writer 新增工作。

## 2. 建立兩條候選軌

### 研究驅動

1. 讀 `publication-candidates-summary` 的 uncovered 與 audience gap。
2. 用 `experiments/INDEX.md`、`storage/reports/INDEX.md` 做窄查詢。
3. 只以 `jq`／搜尋命令查 `storage/memory/knowledge.json` 與 `experiment_experiences.json`；禁止整檔載入。
4. 對候選主題確認 results、資料期間、樣本數、verdict 與 Codex review 狀態。

候選索引過舊或 unavailable 時，才執行：

```bash
uv run python scripts/build_publication_candidates.py
uv run volpred ops publication-candidates-summary --limit 10
```

### 事件驅動

1. 先讀 `config/runtime_schedules.json` 的 formal event spec，再用
   `event-preview` 確認 event identity、slot 與是否已 materialize。
2. 以官方公告、監管機關、交易所、公司 filing 等 primary source 驗證事件日期與已公布數字。
3. 即時資訊必上網查證，不憑記憶或歷史文章推斷。
4. 內容角度可參考 [event-article-templates.md](../feed-publisher/references/event-article-templates.md)；該 reference 不擁有排程。

熱門專欄候選另讀 [blog-sources.md](../trending-repost/references/blog-sources.md)，但 source catalogue 只是 discovery input，不是固定巡檢時鐘。

## 3. 寫作前查重

```bash
uv run python scripts/check_arc_dedup.py \
  --title "<planned title>" \
  --k-id <K-id-if-any> \
  --audience <audience>
```

- exit 1：停止派稿，除非 brief 明確寫出新證據、新結論及 formal waiver 理由。
- 同一研究的 general／research 版本要各自帶正確 audience，不能用未分流查重誤擋。
- 選題分數不會覆蓋 publisher 的最終 dedup gate。

## 4. 排序與輸出

每個候選至少包含：

- `topic`、`audience`、`task_type`
- 一句清楚 thesis 與差異化
- primary／experiment evidence 路徑
- 時效窗口與來源核驗時間
- dedup 命令、exit code、相似文章
- 建議內容 producer：一般文章、研究文章、事件文或 trending commentary

只推薦證據足以支撐的主題。候選若缺 primary source、重複或已被正式 queue 擁有，就回報 skip 理由。

## Completion readback

完成條件是交付一份排名後 brief，且每個入選項都有 live mode snapshot、evidence
與 dedup verdict。後續寫作交給內容 skill；發布交給 `feed-publisher`，由其呼叫
canonical `scripts/publish_draft.py`。本 skill 不建立時鐘、不直接 materialize
schedule，也不修改 feed。
