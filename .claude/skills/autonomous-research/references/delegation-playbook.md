# Delegation Playbook（主線程派工詳細 playbook）

這檔是 `.claude/rules/agent-delegation.md` 的詳細補充，只在 `autonomous-research` skill 觸發或主動 Read 時才載，避免每次 touch `.claude/skills/**` 都把 playbook 全塞進 context。

派工決策只需看 rule 本身（threshold、三關 checklist、模型選擇）；要寫 agent brief 或決定任務分解時再查本檔。

---

## 系統任務類型 × Skill 對應（10 類）

派工前先識別任務類型，再選對應 skill。每類 brief 格式差異見對應 skill 的 `references/`。

| # | 任務類型 | 範例 | 對應 skill |
|---|---|---|---|
| 1 | 研究實驗（含**交易策略設計階段**） | K1132 bootstrap、K1100h tick-level、新 K 編號、新策略 backtest/檢定/cross-OOS | `autonomous-research` + `agent-result-verification` |
| 2 | 論文方向決策 | Paper3_reframe、Paper3_strategic_decision（blocked_user） | `paper-stage-classifier` + 主線程 |
| 3 | 論文修稿（body） | K1146 pivot、K1169 rewrite、Paper6_start | `paper-update` + `finance-paper-quality` |
| 4 | 論文審查 + citation | 每輪 review round、Paper9_bib_fix | `paper-review-cycle` + `citation-verifier` + `latex-academic-reviewer` |
| 5 | 事件驅動文章 | TSMC_0416_post、FOMC_0428、CPI/NFP/財報/地緣政治 | `feed-publisher` + `publication-candidates` |
| 6 | 一般/日常文章（非時效） | research 研究發現、general 教育、methodology、market-analysis、回顧、策略解讀 | `feed-publisher` + `publication-candidates` |
| 7 | 會員問題研究 | 6h cron 觸發 | `member-questions` |
| 8 | 策略生命週期（**上架/下架/管理階段**） | STRATEGY_REGISTRY 新增/下架、metrics 重算、sparkline、ranking | `admin-ops` + `admin-ops/references/strategy-lifecycle.md` |
| 9 | 平台 ops / 巡檢 | release-pool、cleanup、health、article-backups | `admin-ops` |
| 10 | 系統 governance / 修復 | script bug fix、legacy cleanup、rules 重構、歸檔 | 無 skill（主線程做，參考 `.claude/rules/`）|

**交易策略研究兩階段**：設計階段（新策略 = 新 K：signal → backtest → DM/Harvey → cross-OOS）= 類型 #1；上架階段（通過 5 gate → STRATEGY_REGISTRY → 績效追蹤）= 類型 #8。

**類型 #6 包含**：research audience 研究文（策略解讀/方法論複習/負面結果分享）、general 教育文、回顧綜述、市場觀察（非當日事件）。**不限「補池」**—— 只要不是事件驅動即屬 #6。

---

## Task Decomposition + Agent Team 並行分工

**硬規則**（用戶 2026-04-19 指示）：

### 1. 主任務必先規劃子任務
大 task（paper audit / feature build / 多篇文章補池）前，**主線程先規劃子任務結構**，不直接派一個 agent 扛全部：

```
Main task: "Paper 4 vix-sufficiency 投稿準備"
├─ Sub 1: Table 2 K732/K736 root cause 分析 (experiment, main thread)
├─ Sub 2: 5 hard requirements 補齊 (paper_review, general-purpose agent)
├─ Sub 3: reproduce.py full run + divergence report (code, Codex)
├─ Sub 4: Body .tex 更新 + paper-update (paper_body, main thread only)
└─ Sub 5: Citation 驗證 (paper_review, citation-verifier skill)
```

**Schema**：`storage/ops/tasks/*.json` 有 `parent_task_id` 欄位連 parent-child。

### 2. Agent team 並行分工
子任務排程到時 → 派 agent team 平行執行（不同 type / skill）：
- 每子任務對應 1 agent
- 3-4 agent 同時跑是標準（Codex × 1 + Claude Agent tool × 2-3）
- 各 subagent brief 6 要素 self-contained

### 3. 不耗 token 的工作優先排滿（主線程閒置時）

**Low-cost tasks**（主線程直接做）：
- 單檔 Edit（rule / doc 短更新）
- `jq` / `grep` queue / log 查詢
- `finish-task` 收尾 stale claim
- `work_log` append
- Cron 裝/拆
- `ops assign` 把提案入 queue
- INDEX grep / 查重快查

**中-high cost tasks**（派 agent）：
- 多步驟 script / multi-file edit
- 寫文章（需 chart + content）
- Paper audit（多 .tex + script 讀）
- 實驗跑 + 驗

**規則**：slot running < 4 可繼續派（CLAUDE.md L205）；session 閒置時主線程主動做 low-cost 直到事件觸發（avoid stub skip + wait loop）；stub skip 只用在真無事可做（queue 全 stale codex + 無 low-cost 小活）。

---

## Codex subagent Shared runtime 細節

**驗證 runtime 狀態**：
```bash
node "/Users/yhlai0911/.claude/plugins/cache/openai-codex/codex/1.0.1/scripts/codex-companion.mjs" setup --json 2>&1 | jq '.sessionRuntime'
```

**派 Codex subagent 前必做**：
1. 檢 `storage/ops/tasks/*.json` 有無 `claimed_by=codex` 且 `started_at=null` 的 stale claim（>5 分鐘警訊）
2. 無 stale 且 Codex runtime idle → 才派
3. 有 stale → 先 `finish-task --status failed` 清 + re-assign `preferred_agent=auto` 或 bypass 改派 `general-purpose` Agent tool

**Bypass 策略**（Codex 卡住時）：
- 簡單任務（Python script / CLI extension / Email send）→ 直接派 `general-purpose` Agent tool
- 複雜多檔 refactor / 大規模 audit → 必用 Codex，嚴格 serialize

**教訓**（2026-04-19）：連派 `bavof8pa3` (v12 cleanup) + `task-mo5br0ye` (email alert) 違反 shared runtime，後者 stale 5+ 分鐘；主線程 override 改派 Claude `a77622` 才真跑。

---

## Sub Agent Brief 6 要素（詳細版）

Agent 是**空白 Claude**，只知 prompt 裡寫的東西。

1. **任務（WHAT）**：具體產出物、資料、模型、評估指標
2. **動機（WHY）**：為什麼做、相關 K、結果正負面意義
3. **Context 指引**：明指 `experiments/kXXX/README.md`、`docs/error_log.md`、相關 skill
4. **規範引用 + skill 路徑**（關鍵）：
   - 一律指 `.claude/skills/<name>/SKILL.md` + `.claude/skills/<name>/references/*.md`
   - Claude agent（`general-purpose`、`feature-dev:*`）與 Codex subagent（`codex:codex-rescue`、`codex:review`、`codex:adversarial-review`）都透過 codex-companion / Claude Code runtime 讀專案檔，能 access `.claude/skills/` 下任何路徑
   - 舊設計曾把 Codex skill 放 `.agents/skills/`（dual-path），**3-terminal 路線棄用後此路徑已廢**，現在單一 canonical 路徑 `.claude/skills/`
   - 典型場景：LaTeX 論文審查派 `codex:review` → prompt 寫「先讀 `.claude/skills/latex-academic-reviewer/SKILL.md`」；發文派 `general-purpose` → prompt 寫「先讀 `.claude/skills/feed-publisher/SKILL.md`」
   - 忘了指路徑 = agent 瞎猜 = 產出不符規範
5. **成功標準**：可驗證 checklist（檔案產出、數值範圍、test 通過、CLI return）
6. **Scope 限制**：不可擴散、不可改、遇錯如何回報

範本：`.claude/skills/autonomous-research/references/agent-brief-template.md`。

---

## 為什麼 `experiments/kXXX/README.md` 是必備的

CLAUDE.md「研究誠實原則 §3」規定 README 必備。**底層動機是 delegation**：

- 未來 sub agent（或未來的你）接手/擴充/驗證/重跑 kXXX 時，**打開資料夾就能懂**
- Agent prompt 一句「先讀 `experiments/kXXX/README.md`」就把動機/方法/結論帶進 context
- 沒 README = agent 要靠主線程長篇解釋，主線程 context 被燒
- README 是「可複製使用的 self-contained context」— 寫一次，每次派 agent 都省

同理：
- `paper/<name>/README.md` + `experiments.md` + `data_sources.md` → paper review / audit agent self-contained
- `.claude/skills/<name>/references/*.md` → skill-triggered agent self-contained
- `research_program.md` → 「繼續研究」agent self-contained

---

## `storage/work_log.json` 多樣化派工

`work_log.json` 是**跨類型**工作日誌（區別於 `research_log.json` 只記 research）。

### Schema

```json
{
  "entry_id": "uuid-8char",
  "timestamp": "ISO + tz",
  "task_type": "experiment|paper_decision|paper_body|paper_review|event_article|daily_article|member_qa|strategy_lifecycle|platform_ops|governance",
  "task_id": "K1132 / mile_xxxxxxxx / STRAT_xxx / null",
  "agent": "main | agent-xxxxxxxx | cron-<id>",
  "skill_used": "autonomous-research / feed-publisher / ... / null",
  "outcome": "done | null | half-done | cleanup | deferred",
  "summary": "一句話",
  "duration_min": 15,
  "derived_tasks": ["K1133", "K1134"]
}
```

### 寫入時機

**每完成一個 task 後立即 append**：主 agent 自己做 → main 寫；agent 回報完成 → main 驗證後補寫；cron routine → 觸發的 prompt 寫。

### 主 agent 每輪 cron 決策樹

```
讀 work_log.json 最近 5 筆
├─ task_type 同類 ≥3 → 換 type（多樣化）
├─ 連續 2 筆 outcome=null/cleanup → 暫停該 type 該方向
└─ 最近類型分布均勻 → 依 next_tasks.json priority 選
          ↓
讀 next_tasks.json priority 1-3 pending
          ↓
結合 Monitor alert：
├─ 草稿池 <12 → 偏 type 5 event / type 6 daily article
├─ knowledge.json 膨脹 → 偏 type 10 governance memory-health
├─ 文章發佈間隔 >3h → 偏 type 5/6
└─ 無 alert → 依 next_tasks priority
          ↓
依 task_type 查「10 類任務 × Skill 對應」→ 派對應 skill agent
          ↓
若派 agent：brief 必含 6 要素（含 skill 路徑 .claude/ vs .agents/）
若主線程做：按該類 skill references 執行
          ↓
完成後 append work_log.json
```

### 2026-04-18 反面教材

30+ 次操作 95% 是 type 10（governance）— merge_worktree bug fix、legacy cleanup、rules 重構、research_program.md 歸檔、frontend 寫入移除、token report 統一。未派 agent 多樣化，也未 append work_log（還沒建立）。未來：一次 governance 完成後下輪必切 type 1/3/5；即使 Monitor alert 草稿池，也要穿插其他 type。

---

## 場景例子

| 場景 | 處理 | 理由 |
|---|---|---|
| 跑 GARCH(1,1) baseline + 寫 README + results | 派 agent | 多步流程、可 brief 化 |
| `grep "TSMC" feed.json` 查重 | 自己做 | 單一 grep、1 秒完成 |
| 寫 4000 字事件解讀文章 + WebSearch | 派 agent | 要 WebSearch 多頁、寫作燒 context |
| 決定是否重做 TSMC 文章 | 自己做 | 需要對話記憶 + 策略判斷 |
| 批次標 27 個 K 編號 pending → done | 派 agent | 批次操作、可 one-shot script |
| 驗證 agent 回報的數字 | 自己做 | 需跟對話 context 對照 |
| 從 stash 救 4 個治理檔 | 自己做 | 簡單 git checkout、< 5 指令 |
| 5 個腳本的 frontend 寫入移除 | 邊界案例 — 可派 | 5 個 Edit + grep 驗證，prompt 清楚可派 |
