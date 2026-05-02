---
name: publication-candidates
description: >
  系統化選文章主題。雙軌來源：(1) 研究驅動 — 從 knowledge.json 掃 PASS / methodology 教訓但無 feed 覆蓋的 K；
  (2) 事件驅動 — 近期時事、數據公佈、重大財報日、地緣政治。
  Trigger phrases: '選題', '寫什麼文章', 'publication candidates', '文章候選',
  '補草稿池', '時事文章', '事件文章'. Do not use for 實際寫作（use feed-publisher）。
model: sonnet
effort: low
context: fork
agent: fresh-context-worker
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

**日常讀取**：`uv run volpred ops publication-candidates-summary`

**重建**：`uv run python scripts/build_publication_candidates.py`

**使用時機**：
- 每週一次自動（正式時鐘以 shared scheduler / canonical runtime schedule 為準；若本機仍保留 session cron，只視為過渡期便利）
- 補草稿池前必跑
- 用戶說「寫什麼文章」時查

### 軌道 B — 事件驅動（時事 / 公佈 / 財報）

**沒有獨立腳本，因為需要 WebSearch 或即時資料。主線程執行。**

**來源清單**（主線程檢查）：
1. **macroeconomic 數據公佈**：
   - CPI: 每月 10-15 日美國公佈
   - NFP 非農: 每月第一週五
   - FOMC: 3/6/9/12 月固定 + 中間會議
   - PPI / Retail Sales / PMI / Housing / GDP
   - TW: DGBAS 月景氣對策信號（每月底）、失業率、CPI
2. **企業事件**：
   - `財報公告日.txt` 台股財報日（TSMC/Hon Hai/MediaTek 等大型股）
   - US earnings season（1/4/7/10 月中）: 主要 mega-caps 如 NVDA/AAPL/MSFT/GOOGL/AMZN/META/TSLA
   - JP earnings season
3. **地緣政治 / 市場事件**：
   - 戰爭 / 制裁（Hormuz / Israel-Iran / Russia-Ukraine）
   - 能源危機（OPEC+ 決議）
   - 股災 / 閃崩（>3% daily drop）
   - 加密貨幣重大事件（halving / regulation）
4. **其他**：
   - 央行決議（ECB / BOJ / PBoC）
   - 選舉事件
   - 會員提問（高排名且無文章）

**候選擷取 SOP**：
- WebSearch 當日 + 未來 7 天重要事件
- `cat 財報公告日.txt` 過濾近期財報
- 讀 `storage/next_tasks.json` 找 `*_post` / `*_immediate` 事件任務

補充：
- `storage/next_tasks.json` 在 v11 orchestration 下只屬 **legacy planning / working list**，這裡只能把它當事件靈感或人工待辦線索。
- 正式事件 queue 與去重狀態仍以 `config/runtime_schedules.json` 的 `event_jobs`、`storage/ops/` task records、`storage/ops/event_ledger/` 為準。
- 若兩者不一致，永遠以 control plane / `event_jobs` 為準。

**時效性分級**（與 `feed-publisher` skill 同步）：

| 分級 | 寫作時點 | 策略 |
|------|---------|------|
| **T-7** heads-up | 事件前 7 天 | 背景 + 歷史反應 |
| **T-2** preview | 事件前 2 天 | 具體數字預期 + 情境分析 |
| **T+0** immediate | 事件當天/次日 | **status=published**，不等節奏釋出 |
| **T+1** followup（可選） | 事件後 1-2 天 | 市場反應解讀 |

**配額**：一個事件最多 3-4 篇（T-7 + T-2 + T+0 + 可選 T+1），避免過度集中。

**查重必做**：
```bash
grep -i "事件關鍵詞" storage/reports/feed.json | grep title | head -10
```
一個事件不可發 5 篇以上（2026-04-13 TSMC 04/16 踩過坑）。

> 以上頻率/配額規則以 `feed-publisher` skill + `CLAUDE.md` 為母本；本段為主線程操作時的自我檢查 reference，若不一致以 母本為準。

## 完整選題 SOP — 5 Step 決策流程（主線程必走）

以下是 v12 具體選題流程，遍歷**六個庫**再下決策。**禁整檔讀大 JSON**（`.claude/rules/context-hygiene.md`），全部 jq/grep/index 方式存取。

### Step 1 — 掃「候選庫」（3 個機器產）

**1-A 候選庫 `storage/publication_candidates.json`**（主要軌道 A 來源）：
```bash
uv run volpred ops publication-candidates-summary
```
若 `available=false` 或 `source_age_hours` 過高 → `uv run python scripts/build_publication_candidates.py` re-build，再重跑一次 summary。

**1-B 實驗庫索引 `experiments/INDEX.md`**（1010 K 單頁索引）：
```bash
# 所有 uncovered (feed=- + paper=-) 的 K
grep '| - | - |' experiments/INDEX.md | head -20
# 看特定 verdict
grep '| PASS |' experiments/INDEX.md | grep '| - |' | head  # PASS 但無 feed
```

**1-C 主題庫 `docs/topic_diversity_audit.md`** + `storage/reports/INDEX.md`（文章庫索引）：
```bash
# 看 novelty 候選（feed 覆蓋少的主題軸）
head -60 docs/topic_diversity_audit.md
# 文章庫最近 30 天主題分佈
head -80 storage/reports/INDEX.md
```

### Step 2 — 掃「教訓庫」（2 個歷史教訓）

**2-A 知識庫 `storage/memory/knowledge.json`**（2043 entries，禁整檔 Read）：
```bash
# 找相近主題 K 的 verdict
jq '.[] | select(.content | test("K1098|VIXTWN|台股"; "i")) | {id: .item_id, verdict: (.verdict // "-"), content: .content[0:120]}' storage/memory/knowledge.json | head -20
# 找 FAIL / NULL 避免重踩
jq '.[] | select(.content | test("FAIL|NULL|paradigm")) | .content[0:100]' storage/memory/knowledge.json | head -10
```

**2-B 經驗庫 `storage/memory/experiment_experiences.json`**（方法論教訓，每 5-10 K 彙整 1 條）：
```bash
jq '.[] | {lesson_id, domain, summary: .summary[0:200]}' storage/memory/experiment_experiences.json | head -15
```

### Step 3 — 文獻確認（學術庫）

**禁憑記憶或舊文獻判斷 novelty**。必做：
```bash
# WebSearch 主題最近 2 年 top 3 papers（主線程 call）
# 或用 sci-hub skill 取 DOI
```
若文獻已有大量 recent coverage → 降級為 replication 而非 novel contribution。

### Step 4 — 跨庫 Synthesis + Quota 檢查

候選 K / 主題必須通過以下篩選（依序）：
1. **Uncovered 必要條件**：`experiments/INDEX.md` feed=- 或 paper=- 至少一個
2. **無近期 FAIL 教訓**：knowledge.json / experiences.json 沒標該方向已 paradigm 推翻
3. **主題多樣化**：對比 work_log 最近 10 個新 K + feed 最近 10 篇文章，檢查是否落在 dominant cluster（避重踩）
4. **Novelty 20% quota**（`.claude/rules/publish-checklist.md`）：每 10 個新研究至少 2 個在 under-explored 主題（RL vol / HF microstructure / intraday seasonality / term-structure ML / climate vol / REIT / crypto-stablecoin / Bayesian averaging / MCS-SPA / retail flow）
5. **文獻支持**：WebSearch 回傳 ≥3 篇學術支持或 flag 為 negative result 誠實研究

### Step 5 — 派工

通過 Step 1-4 才派：
- 事件驅動（軌道 B T+0 / T-2）→ **主線程自己寫**（時效高，不派 agent）或 Agent tool
- 非時效研究文（軌道 A）→ Agent tool `general-purpose`
- 論文研究（新 K 實驗）→ Codex `codex-rescue` 或 Agent tool
- Brief 6 要素必備（`.claude/rules/agent-delegation.md`）

**不通過就 skip，不寫推測性文章**。

## 雙軌合併排序（簡化版，急用時）

```
1. 先跑 `uv run volpred ops publication-candidates-summary`（軌道 A 候選）
2. 檢查今日日期 + 未來 7 天（軌道 B 事件）
3. 合併排序：
   - T+0 / T-2 事件必寫（時效高）
   - T-7 事件可排
   - 軌道 A 高分 uncovered (score ≥ 5) 填空
   - 軌道 A 缺 audience (general/research) 次之
4. 批次下單給 writing agent（3-4 篇 parallel，主題軸**各不相同**）
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

> 寫文章前先跑 `uv run volpred ops publication-candidates-summary` 看候選；若 unavailable 或太舊再 rebuild。

## 自動化

正式時鐘應由 shared scheduler / canonical runtime schedule 觸發；以下若仍存在，只視為 legacy session convenience：
```
7 */6 * * *  知識索引維護（執行 knowledge-index-maintain --stub-if-no-work；有動作再看 after summary）
```

加掛：每週一 9:00 自動掃 publication candidates：
```python
CronCreate(cron="0 9 * * 1", prompt="publication 候選巡檢：先跑 publication-candidates-summary；必要時 rebuild；回報候選缺口")
```

（若本機尚有 session 版 convenience，可保留作提醒；但 v11 canonical orchestration 以 shared scheduler 為準）

## 規則

- ⚠️ 候選清單不直接等於寫作清單——主線程仍需判斷品質、時效、用戶方向
- ⚠️ 軌道 B（事件）**必須 WebSearch 確認**事件是否發生、數字是否已公佈，禁止憑記憶寫
- ⚠️ 主線程 MUST cross-reference 兩軌，不只看一邊
- ⚠️ 1900+ 舊實驗也會被候選清單涵蓋（不止本 session）
- ⚠️ `next_tasks.json` 只屬 legacy planning view；不要把它當成 scheduler 的正式事件來源
