---
name: publication-candidates
description: >
  系統化選文章主題。雙軌來源：(1) 研究驅動 — 從 knowledge.json 掃 PASS / methodology 教訓但無 feed 覆蓋的 K；
  (2) 事件驅動 — 近期時事、數據公佈、重大財報日、地緣政治。
  Trigger phrases: '選題', '寫什麼文章', 'publication candidates', '文章候選',
  '補草稿池', '時事文章', '事件文章'. Do not use for 實際寫作（use feed-publisher）。
user-invocable: true
---

# Publication Candidates — 雙軌選題機制

## Scope

Use this skill for：

- 每週掃一次「哪些 K 實驗值得發文」
- 寫文章前快速查候選
- 建立時事 / 事件 article 優先清單

Do **not** use for：

- 實際寫作 → `feed-publisher`
- 平台層 publish / sync → `admin-ops`

## 雙軌來源

### 軌道 A — 研究驅動（K-experiment 候選）

**腳本**：`scripts/build_publication_candidates.py`

**邏輯**：
1. 掃 `storage/memory/knowledge.json` 所有 `experiment_id` (normalize K1145/K1145b → K1145)
2. 交叉比對 `storage/reports/feed.json`：tags array 含 K-id / title 含 K-id / content 含 K-id
3. 評分（0-10）：
   - PASS / Harvey: +3
   - cross-market / universal: +3
   - methodology / mechanism 教訓: +2
   - 決定性 NULL / paradigm 推翻: +2
   - 5-layer robustness: +2
   - inconclusive / data 不足: -2
4. 輸出 `storage/publication_candidates.json`：
   - `top_10_uncovered`（score 排序，完全沒文章覆蓋的 K）
   - `missing_general_top5`（有研究版但缺一般讀者版）
   - `missing_research_top5`（有一般版但缺研究版）

**執行**：`uv run python scripts/build_publication_candidates.py`

**使用時機**：
- 每週一次自動（session cron 已整合）
- 補草稿池前必跑
- 用戶說「寫什麼文章」時查

### 軌道 B — 事件驅動（時事 / 公佈 / 財報）

**發文頻率、時效性分級、配額規則已在 `CLAUDE.md` 事件文章段 + `feed-publisher` skill 定義。不在此重寫。**

本 skill 只負責「**哪些事件正在發生**」的候選擷取：

1. **macro 數據公佈**（CPI / NFP / FOMC / PPI / TW DGBAS 等）
2. **企業財報**（`財報公告日.txt`、US/JP earnings season）
3. **地緣政治 / 市場事件**（戰爭、能源、股災、加密）
4. **央行決議**（ECB / BOJ / PBoC）
5. **會員提問**（高排名無文章覆蓋）

**候選擷取 SOP**：
- WebSearch 當日 + 未來 7 天重要事件
- `cat 財報公告日.txt` 過濾近期財報
- 讀 `storage/next_tasks.json` 找 `*_post` / `*_immediate` 事件任務

**發文規則（頻率 / 時效 / 配額 / 查重）** → 見 `feed-publisher` skill「事件文章段」與 `CLAUDE.md`。

## 雙軌整合決策

**寫文章前** `publication-candidates` 主線程 SOP：

```
1. 先看 storage/publication_candidates.json (軌道 A 候選)
2. 檢查今日日期 + 未來 7 天（軌道 B 事件）
3. 合併排序：
   - T+0 / T-2 事件必寫（時效高）
   - T-7 事件可排
   - 軌道 A 高分 uncovered (score ≥ 5) 填空
   - 軌道 A 缺 audience (general/research) 次之
4. 批次下單給 writing agent（3-4 篇 parallel）
```

## 輸出 publication_candidates.json 結構

```json
{
  "generated_at": "ISO",
  "summary": {
    "total_k": 567,
    "uncovered": 258,
    "high_priority_uncovered": 15,
    "missing_general_audience": 20,
    "missing_research_audience": 8
  },
  "top_10_uncovered": [...],
  "missing_general_top5": [...],
  "missing_research_top5": [...],
  "candidates": [...]  // 完整清單
}
```

## 整合到 feed-publisher

`.claude/skills/feed-publisher/SKILL.md` 於「主題查重」段之前新增：

> 寫文章前先 `cat storage/publication_candidates.json | jq '.top_10_uncovered, .missing_general_top5, .missing_research_top5'` 看候選。

## 自動化

session cron 已在：
```
7 */3 * * *  知識索引更新
```

加掛：每週一 9:00 自動掃 publication candidates：
```python
CronCreate(cron="0 9 * * 1", prompt="執行 uv run python scripts/build_publication_candidates.py 並回報 summary；告訴用戶 uncovered high-priority / missing audience 的 K 清單")
```

（目前 session 已建，每週自動重建候選清單）

## 規則

- ⚠️ 候選清單不直接等於寫作清單——主線程仍需判斷品質、時效、用戶方向
- ⚠️ 軌道 B（事件）**必須 WebSearch 確認**事件是否發生、數字是否已公佈，禁止憑記憶寫
- ⚠️ 主線程 MUST cross-reference 兩軌，不只看一邊
- ⚠️ 1900+ 舊實驗也會被候選清單涵蓋（不止本 session）
