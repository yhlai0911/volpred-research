---
paths:
  - ".claude/skills/**"
  - "scripts/agent_prompts/**"
  - "AGENTS.md"
  - "CLAUDE.md"
---

# Agent Delegation 規則（主線程派工節奏）

## 核心原則

**主線程的 context 有限且昂貴；sub agent 的 context 用完即丟。** 把會燒 context 的工作外包給 agent team，主線程只保留最重要的事：**規劃、synthesis、驗證、決策、記錄**。

這是 session-level token 節約的主要槓桿，比禁止讀大檔更重要。

## 系統任務類型 × Skill 對應（10 類）

主 agent 派工前先識別任務類型，再選對應 skill。每類任務的 brief 格式差異見對應 skill 的 `references/`。

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

**交易策略研究的兩階段**：
- **設計階段** → 類型 #1（新策略 = 新 K 實驗：設計 signal → backtest → DM/Harvey 檢定 → cross-OOS）
- **上架階段** → 類型 #8（通過 5 gate 後入 STRATEGY_REGISTRY → 上線 → 績效追蹤）

**類型 #6 包含**：research audience 研究文（含策略解讀、方法論複習、負面結果分享）、general audience 教育文、回顧綜述、市場觀察（非當日事件）。**不限「補池」**——不管池滿不滿都用這類，只要不是事件驅動即屬 #6。

## 派工前 Checklist（硬性，每次都做）

**每次派 Agent tool 或 `codex:rescue` subagent 前，主線程必過三關**：

### 關 1: Mission sanity（CLAUDE.md L5-24）
這輪行動服務哪條 Mission？若全在 ops 類（補池、排程、governance），立刻警訊 — Mission L19 明寫「研究與論文永遠不輸給 ops」。token 分配要傾向研究/論文。

### 關 2: 多樣化檢查
檢 `storage/work_log.json` 最近 5 筆 task_type；若 **≥3 筆同 type，必須換 type**。10 類任務輪替避免 chamber echo。

```bash
jq '[.[-5:] | .[] | .task_type]' storage/work_log.json
```

### 關 3: 不問選擇題（CLAUDE.md L7）
「要不要 X？」一律違規。要做就做，不做就不做，不要一句話自己問自己答還同時派出去。疑問「要不要 X」時：不問，直接決定。決定錯了事後修，好過浪費 token 等確認。

**允許問用戶的例外**（CLAUDE.md L9-12）：真有破壞性風險、policy 決策（投稿/研究 pivot）、模糊到用邏輯推不出來。

**違反代價**：2026-04-18/19 session token 用量 $1897，50.3% 是純文字回覆無工具 — 主因就是違反此三關（問選擇題 + 連派同 type + 選題偏向 comfort zone）。

## Delegation Threshold（何時派 vs 自己做）

### ✅ **派 agent**（優先選項）
- 多步流程（3 步以上：讀檔 → 分析 → 寫碼 → 跑 → 驗證）
- 需要 WebSearch / 外部資料抓取
- 需要寫實驗腳本 + 跑實驗
- 需要寫文章（市場分析、事件解讀、策略報告）
- 需要批次檢視 / 修改多個檔案（> 5 個）
- 需要反覆試錯的 debug
- 可以明確列成 brief 交付的獨立任務（success criteria 能寫清楚）

### 🟡 **主線程自己做**（保留 context 用）
- 單一 grep / jq / ls 查詢
- 簡單 Edit（單檔、明確 old_string）
- 驗證 agent 回報（跑幾個 Bash 確認數字對不對）
- Agent 結果的 synthesis（解讀、決策、下一步規劃）
- 最終記錄（寫 knowledge / experience / log_entry）
- 判斷要不要派下一個 agent

### ⚖️ **判斷法則**
> 「這件事如果我做，會燒 3000+ tokens 嗎？」若會 → 派 agent。
> 「這件事需要我的對話記憶才能做嗎？」若會 → 自己做（agent 不知道上下文）。
> 「這件事的成功標準能一句話寫清楚嗎？」若能 → 派 agent 最快。

## Sub Agent 必須拿到足夠資訊（self-contained brief）

Agent 是 **空白 Claude**，只知道 prompt 裡寫的東西。不要假設 agent 知道任何事。每個 agent brief 必備 6 要素（對齊 `autonomous-research/references/agent-brief-template.md`）：

1. **任務（WHAT）**：具體產出物、資料、模型、評估指標
2. **動機（WHY）**：為什麼做、相關 K 編號、結果正負面各代表什麼
3. **Context 指引**：明確告訴 agent **要讀哪些檔** 才能 self-contained（例如 `experiments/k1100f/README.md`、`docs/error_log.md`、相關 skill）
4. **規範引用（含 skill 路徑）**：明列必讀 skill / rules。**注意 agent 類型對應不同路徑**：
   - **Claude-based agent**（`general-purpose`、`feature-dev:*` 等）→ 引用 `.claude/skills/<name>/SKILL.md` + `.claude/skills/<name>/references/*.md`
   - **Codex agent**（`codex:codex-rescue`、`codex:review`、`codex:adversarial-review` 等）→ 引用 `.agents/skills/<name>/SKILL.md`（Codex 讀不到 `.claude/` 路徑）
   - 兩套 skill 內容是 `agent-specs/skills/` render 出來的同源副本，只是放不同目錄供不同 provider 讀
   - 典型場景：LaTeX 論文審查派 `codex:review` → prompt 必寫「先讀 `.agents/skills/latex-academic-reviewer/SKILL.md`」；發文派 `general-purpose` → prompt 寫「先讀 `.claude/skills/feed-publisher/SKILL.md`」
   - 忘了指路徑 = agent 瞎猜 = 產出不符規範，主線程要花 token 重派
5. **成功標準**：可驗證的 checklist（檔案產出、數值範圍、test 通過、CLI 返回特定結果）
6. **Scope 限制**：不可擴散做什麼、不可改什麼、遇錯如何回報

## 為什麼 `experiments/kXXX/README.md` 是必備的

CLAUDE.md 的「研究誠實原則 §3」規定 `README.md` 必備。**底層動機是 delegation**：

- 未來任何 sub agent（包括未來的你自己）需要接手 / 擴充 / 驗證 / 重跑 kXXX 時，**打開資料夾就能懂**
- Agent prompt 只要一句「先讀 `experiments/kXXX/README.md`」就把動機 / 方法 / 結論全帶進它的 context
- 沒有 README = agent 要靠主線程長篇解釋，主線程 context 被燒
- README 是 **「可複製使用的 self-contained context」** — 寫一次，每次派 agent 都省 context

同理：
- `paper/<name>/README.md` + `experiments.md` + `data_sources.md` 是讓 paper review / audit agent self-contained
- `.claude/skills/<name>/references/*.md` 是讓 skill 觸發的 agent self-contained
- `research_program.md` 是讓「繼續研究」agent 找方向的 self-contained

## 依 `storage/work_log.json` 做多樣化派工

`work_log.json` 是**跨類型**工作日誌（區別於 `research_log.json` 只記 research）。10 類 task type 對照見 `CLAUDE.md`「系統任務類型 × Skill 對應」段。

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

**每完成一個任何類型的 task 後立即 append**：
- 主 agent 自己做完 → main 寫
- Agent 回報完成 → 主 agent 在驗證後補寫
- Cron 觸發的 routine 完成（例如 token 日報、知識索引）→ 由觸發的 prompt 寫

### 主 agent 每輪 cron 決策樹

```
讀 work_log.json 最近 5 筆
├─ task_type 同類 ≥3 → 換 type（多樣化）
├─ 連續 2 筆 outcome=null/cleanup → 暫停該 type 該方向
└─ 最近類型分布均勻 → 依 next_tasks.json priority 選
          ↓
讀 next_tasks.json priority 1-3 pending
          ↓
結合 Monitor alert（視不同 type）：
├─ 草稿池 <12 → 偏 type 5 event / type 6 daily article
├─ knowledge.json 膨脹 → 偏 type 10 governance memory-health
├─ 文章發佈間隔 >3h → 偏 type 5/6
└─ 無 alert → 依 next_tasks priority
          ↓
依 task_type 查「系統任務類型 × Skill 對應」表 → 派對應 skill agent
          ↓
若派 agent：agent brief 必含 6 要素（含 skill 路徑 `.claude/` vs `.agents/`）
若主線程做：按該類 skill 的 references 執行
          ↓
完成後 append work_log.json
```

### Today session（2026-04-18）反面教材

30+ 次操作 95% 是 type 10（governance）— merge_worktree bug fix、legacy cleanup、rules 重構、research_program.md 歸檔、frontend 寫入移除、token report 統一、research_log 審計……

未派 agent 多樣化，也未 append 到 work_log（還沒建立）。未來不再重犯：
- 一次 governance 任務完成後，下一輪必切到 type 1/3/5 等
- 即使 Monitor 一直 alert 草稿池，也要穿插其他 type，不可全 session governance

## Anti-patterns（禁止）

- ✗ **自己扛該派的大任務**：例如自己跑 audit 全 feed.json、自己批次 cleanup 多個 draft、自己查文獻寫實驗設計 — 主線程 token 很快耗盡
- ✗ **派 agent 但 prompt 太短**：讓 agent 自己猜 context、自己判斷成功標準、自己選工具 → 結果不可預期，主線程要再花 token debug
- ✗ **派 agent 做主線程才能做的事**：例如「決定下一個研究方向」、「判斷這篇文章該不該發」、「整合多個 agent 的結論」— 這些需要跨對話記憶，agent 沒有
- ✗ **派完不驗證**：CLAUDE.md 「agent-result-verification」skill 規範必做，不能照抄 agent 回報的數字

## 場景例子

| 場景 | 處理 | 理由 |
|---|---|---|
| 跑一個 GARCH(1,1) baseline 實驗 + 寫 README + results | 派 agent | 多步流程、可 brief 化 |
| `grep "TSMC" feed.json` 查重 | 自己做 | 單一 grep、1 秒完成 |
| 寫 4000 字事件解讀文章 + WebSearch | 派 agent | 要 WebSearch 多頁、寫作 燒 context |
| 決定是否重做 TSMC 文章 | 自己做 | 需要對話記憶 + 策略判斷 |
| 批次標 27 個 K 編號 pending → done | **派 agent**（我今天自己做了、違規） | 批次檔案操作、可寫成 one-shot script |
| 驗證 agent 回報的數字 | 自己做 | 需要跟對話中的 context 對照 |
| 從 stash 救 4 個治理檔 | 自己做 | 簡單 git checkout、< 5 指令 |
| 5 個腳本的 frontend 寫入移除 | 邊界案例 — 可派 | 5 個 Edit 加 grep 驗證，prompt 寫得清楚可派 |
