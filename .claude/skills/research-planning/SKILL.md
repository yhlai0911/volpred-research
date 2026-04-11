---
name: research-planning
description: >
  Research scheduling and program management. Reads next_tasks.json / research_program.md
  to decide what to do next, routes to domain-specific skills, manages cron setup and
  anti-idling rules. Trigger: cron '繼續研究', '每日任務審視', session startup scheduling,
  or any research planning/prioritization question.
---

# Research Planning & Scheduling

研究調度層：決定「下一步做什麼」，然後路由到對應 skill 執行。

## 任務獲取流程

### 1. 讀取 next_tasks.json（優先）
```bash
cat storage/next_tasks.json
```
有具體任務 → 直接路由到對應 skill 執行。

### 2. Fallback: 讀 research_program.md
```bash
cat research_program.md
```
找未完成（✗）或進行中項目，選最高優先級。

## research_program.md 管理

research_program.md 是北極星文件，隨研究推展逐步奠基衍生：
1. 更新結論區塊（新數據、新發現）
2. 衍生新的研究方向（從已知推向未知）
3. 修正約束條件（如 OOS 期間隨時間推移應延伸）
4. 記錄失敗原因，作為後續嘗試的基礎
5. 已完成項目移到 `docs/research_archive/`
6. **保持 < 700 行**

## 研究域 Skill 路由表

| 任務類型 | 載入 Skill | 執行方式 |
|---------|-----------|---------|
| 實驗任務 | `autonomous-research` | worktree agent |
| 論文任務 | `latex-academic-reviewer` | 主線程 |
| 文章任務 | `feed-publisher` | 可用 sonnet agent |

**注意：平台任務不經此路由。** 平台運營由 CLAUDE.md 路由表直接觸發 `admin-ops`。

## Session Cron 啟動（每次新 session 必做）

所有排程配置的**單一權威來源**是 `admin-ops/references/scheduling.md`。
新 session 啟動時，讀取該檔案並依序執行 CronCreate。不在此處重複列出。

## 經濟金融事件日曆

FOMC、CPI、非農、TSMC 法說等重大事件會影響波動率結構。
調度層職責：每月初（或新 session 啟動時）WebSearch 查詢當月重大事件日期，
用 `CronCreate(recurring=false)` 排入單次提醒，確保研究排程配合事件窗口。

## 反空轉與研究節奏

操作性反空轉規則（每次 cron 觸發必須產出）見 `admin-ops/references/scheduling.md`。
原則宣示（研究永不停止）見 `CLAUDE.md` 核心約束。

## 文章池水位

每 5 個實驗後必須檢查文章池（status=draft 或 scheduled）數量：
- **< 3 篇 → 立刻補 2 篇**（1 general + 1 research）
- 檢查指令：`python3 -c "import json; f=json.load(open('storage/reports/feed.json')); print(len([a for a in f if a.get('status') in ('draft','scheduled')]))`

## 反空轉與研究節奏

操作性反空轉規則（每次 cron 觸發必須產出）見 `admin-ops/references/scheduling.md`。
原則宣示（研究永不停止）見 `CLAUDE.md` 核心約束。

以下是**調度層獨有**的策略規則：
- 連續 3 個 null result → 必須換方向
- 每個 session 至少 1 個完全不同方向的實驗
- 定期搜索最新文獻（每 session 至少一次）— 發現新方向 → 寫入 research_program.md
- 數據會增加 — 定期延伸 OOS、重新驗證結論
- 每個推理鏈段的發現都要即時發佈，不是等到最後（發文比例見 feed-publisher）
