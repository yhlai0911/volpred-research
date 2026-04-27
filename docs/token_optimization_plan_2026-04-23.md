# Token 優化計劃（2026-04-23 修正版）

## 先更正

前一版把 `subagent` 和 `agent team` 講得太混，這版以 Claude Code 官方文件為準重新整理。

### `subagent` 是什麼

官方定義：

- `subagent` 在 **單一 session 內** 工作
- 每個 subagent 有自己的 context window
- 它做完後 **回報給主 agent**
- 適合會淹沒主對話的 side task，例如搜尋、log、docs、局部探索

來源：

- https://code.claude.com/docs/en/sub-agents

關鍵句：

- subagents work within a single session
- results return to the caller
- costs can be controlled with cheaper models like Haiku

### `agent team` 是什麼

官方定義：

- `agent team` 是 **多個獨立 Claude Code sessions**
- 有 `team lead`、`teammates`、`shared task list`、`mailbox`
- teammates 能彼此直接溝通，不必全部經過 lead
- token 成本高於 subagents，例行工作通常單 session 更省

來源：

- https://code.claude.com/docs/en/agent-teams

官方比較重點：

- `subagents`: focused tasks where only the result matters
- `agent teams`: complex work requiring discussion and collaboration
- `agent teams` token cost higher; routine tasks prefer single session or subagents

## 已確認的事實

### 1. 你本來就有 status line

已確認：

- [~/.claude/settings.json](</Users/yhlai0911/.claude/settings.json:94>) 有 `statusLine`
- [~/.claude/statusline-command.sh](</Users/yhlai0911/.claude/statusline-command.sh:1>) 有在顯示 `context_window.used_percentage`

所以這不是缺項，前一版這裡判斷錯了。

另外官方也明寫：

- status line 在本機執行
- **不消耗 API token**

來源：

- https://code.claude.com/docs/en/statusline

### 2. `auto-compact` 可以提早，不必固定等 95%

官方支援：

- `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`
- 預設約 `95%`
- 可以設更低，例如 `62`

來源：

- https://code.claude.com/docs/en/env-vars

### 3. 不能乾淨地「每完成一個任務就自動 /clear 或 /compact」

這件事要分開講：

- Claude Code有 `/clear` 與 `/compact` 兩個 built-in commands
- 但官方 skill 文件也明寫：built-in commands 並不是都能透過 Skill tool 呼叫，像 `/compact` 就**不行**
- hooks 能在 `TaskCompleted`、`Stop`、`SubagentStop` 等事件執行外部腳本，但它們不是「內建 slash command 自動器」

來源：

- https://code.claude.com/docs/en/commands
- https://code.claude.com/docs/en/skills
- https://code.claude.com/docs/en/hooks

所以結論是：

- **可以自動提早 compact**
- **可以自動提醒或外部編排**
- **但沒有一個乾淨、官方原生的「任務完成後自動在同一 session 內執行 /clear 或 /compact」機制**

### 4. 可以依 workflow 自動套 `model` / `effort`

這點官方是支援的，而且比我前一版說得更強。

#### Skill 層

skill frontmatter 支援：

- `model`
- `effort`
- `context: fork`
- `agent`
- `paths`

來源：

- https://code.claude.com/docs/en/skills

用途：

- 同一個 workflow 被 skill 命中時，主 agent **本回合**可自動切到指定 model / effort
- 若加 `context: fork`，這個 workflow 會在 forked subagent 裡跑

#### Subagent 層

subagent frontmatter 支援：

- `model`
- `effort`
- `tools`
- `permissionMode`
- `skills`
- `isolation`

來源：

- https://code.claude.com/docs/en/sub-agents

用途：

- 同一類型 subagent 可以固定用比較便宜或比較適合的 model
- 例如 Explore 類搜尋任務走 Haiku / Sonnet，嚴謹寫碼審查才升 Opus

## 這個專案目前真正的問題

根據本地 JSONL token drilldown：

- `text_only`: `35.3%`
- `bash_other`: `27.4%`
- `cache_create`: `125.0M`
- `cache_read`: `6.81B`

來源：

- [weekly_2026-04-17.md](/Users/yhlai0911/Desktop/volpred-research/storage/reports/token_usage/weekly_2026-04-17.md:1)
- [scripts/token_usage_report.py](/Users/yhlai0911/Desktop/volpred-research/scripts/token_usage_report.py:1)

結論不是「subagent 太多」這麼簡單，而是：

1. 目前 repo 文件把 `subagent` 和 `agent team` 混用，導致工作法容易選錯。
2. 你已經有 status line，但缺少把它變成實際行為邊界的規則。
3. 很多 routine 工作還沒被 skill / workflow index 吃掉，所以主對話仍有大量 shell glue。
4. `.claude/settings.json` 的多個 hooks 會主動把提示文字再塞回 context。

## 修正版策略總結

一句話：

**不是停用 subagent，而是把 `agent team` 從預設工作法降為特例；把 `subagent` 變成 skill/flow 驅動的精準工具。**

## 能力與限制矩陣

### 單一主 session

適合：

- 同一條 reasoning chain
- 短小 grep / jq / git status / 單檔修改
- 需要保留決策上下文的工作

優點：

- 最省 setup
- 不重建額外 session

缺點：

- 容易被 log / 搜尋 / SOP 汙染

### Forked subagent

適合：

- 大量搜尋
- log 過濾
- docs lookup
- 可 self-contained 的 side task
- 讀多寫少或局部寫入

優點：

- 有獨立 context
- 結果只摘要回主線
- 可指定較便宜 model / effort

缺點：

- 還是會有一份額外 context 成本
- 若 brief 不清楚，重派會浪費

### Agent team

適合：

- 真正需要多人平行討論
- 競爭假說 debug
- 跨層協作 review
- 彼此要直接互相挑戰與溝通的工作

不適合：

- routine ops
- queue / cron / token report
- 短篇 code review
- 同一檔反覆小改
- 線性、依賴重、必須一步接一步的工作

## 修正版優化計劃

### Phase 0：立即有效，先修「工具選錯」與「上下文邊界」

#### 0.1 保留現有 status line，但把它變成行為規則

你已經有顯示 context 百分比，不需要重做。  
需要補的是 **操作規則**：

- `<55%`：正常工作
- `55-62%`：避免大搜尋與新 side task
- `62%+`：優先 `/compact`
- `70%+`：除非收尾，不再開新主題

可選優化：

- 把 status line 顏色門檻從 `70/90` 改成 `62/75/90`

#### 0.2 在 user/local settings 設 `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=62`

這是目前最接近「自動整理 context」的官方原生做法。

建議：

- 先設 `62`
- 若研究 session 仍偏長，再測 `55`

#### 0.3 把 `agent team` 從預設降級為特例

目前這個 repo 有三個問題：

- [`.claude/settings.json`](</Users/yhlai0911/Desktop/volpred-research/.claude/settings.json:1>) 開了 `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`
- [`.claude/settings.local.json`](</Users/yhlai0911/Desktop/volpred-research/.claude/settings.local.json:1>) 也開了
- [`docs/hardware.md`](</Users/yhlai0911/Desktop/volpred-research/docs/hardware.md:21>) 還寫「優先使用 agent team」

修正方向：

- agent team 不再是預設
- 只有「明確需要互相溝通的平行合作」才開

#### 0.4 保留 subagent，但改成 workflow-driven

不是「看到 >3000 tokens 就派」，而是：

- 無關 side task：派 forked subagent
- 同一主題線性推進：留主 session
- 多人互相辯論：才用 agent team

#### 0.5 瘦身 chatty hooks

目前 `.claude/settings.json` 裡至少這些事件會把文字塞回 context：

- `SessionStart`
- `SessionStart matcher=compact`
- `SubagentStop`
- `Notification idle_prompt`
- `TaskCompleted`
- `PostCompact`

官方 hooks 最適合做的是：

- 本地前處理
- 過濾 log
- 寫外部 state

不適合做的是：

- 每次事件都塞一大段 meta 指令給 Claude

### Phase 1：建立 workflow index，讓 SOP 按需載入

這是你這次提出來、而且我認為最值得做的方向。

官方 skill 機制正好支援：

- description 常駐
- full skill content 用到才載
- supporting files 需要時才讀
- `paths` / `model` / `effort` / `context: fork` / `agent`

來源：

- https://code.claude.com/docs/en/skills
- https://code.claude.com/docs/en/costs

#### 建議做法

做一個 **workflow index skill / doc**，只放：

- workflow id
- 觸發條件
- 任務分類
- 執行模式：`inline` / `forked subagent` / `agent team`
- 預設 `model`
- 預設 `effort`
- 是否可自動 compact 建議
- 詳細流程位置

然後詳細流程分散到 supporting files：

- `reference/*.md`
- `checklists/*.md`
- `scripts/*.sh|py`

#### 好處

- 主對話只背「索引」，不背全部 SOP
- agent 先判斷走哪條 workflow，再按需讀詳細內容
- 這正是你想要的「先查索引，再查細節」

### Phase 2：把 model / effort 路由正式化

#### 2.1 主 agent：用 skill frontmatter 自動切

skill 支援：

- `model`
- `effort`

所以可以把 workflow skill 寫成：

- `ops-triage`: `model: sonnet`, `effort: low`
- `code-review`: `model: sonnet`, `effort: medium`
- `research-design`: `model: opus`, `effort: high`
- `paper-method-review`: `model: opus`, `effort: xhigh`

重點：

- 這種切換是 **workflow-based**
- 比「整個 session 永遠 Opus / xhigh」更省

#### 2.2 Forked 工作：用 `context: fork` + `agent`

skill frontmatter 可寫：

- `context: fork`
- `agent: Explore | Plan | general-purpose | custom subagent`

這樣同一個 workflow 被命中時，可以直接決定：

- 這次要不要 fork
- fork 給誰做

#### 2.3 Custom subagent：固定 `model` / `effort`

對高頻 task 類型，直接在 `.claude/agents/*.md` 定義：

- `docs-researcher`: `model: haiku`
- `fresh-context-worker`: `model: sonnet`
- `code-reviewer`: `model: sonnet`, `effort: medium`
- `deep-researcher`: `model: opus`, `effort: high`

### Phase 2.5：把現有 skills 的預設 `model / effort` 一次定清楚

這一步是你目前最值得先補的治理層。  
現在多數 `.claude/skills/*` 只有 `name/description`，還沒有正式 frontmatter 指定：

- `model`
- `effort`
- `context: fork`
- `agent`

這代表即使 skill 已經存在，Claude 仍常常會用「目前 session 的預設模型與 effort」直接跑，省不到真正該省的部分。

**這些建議值是預設，不是死規則。**  
若任務明顯更難或更高風險，仍可在該次工作中手動升級。

#### 現有 skills 建議矩陣

| Skill | 建議執行模式 | 建議 Model | 建議 Effort | 說明 |
|---|---|---|---|---|
| `admin-ops` | inline | `sonnet` | `medium` | 平台/後台/ops 多半是流程型與結構化工作，不必預設 Opus；遇到跨多模組高風險變更再升級 |
| `agent-result-verification` | inline | `sonnet` | `low` | 核心是對 results JSON 做精準比對，應短、硬、結構化，不需要高成本發散推理 |
| `autonomous-research` | inline | `opus` | `high` | 研究設計、方法論、統計判讀、實驗方向決策是高 intelligence task；side task 再 fork |
| `citation-verifier` | `context: fork` | `sonnet` | `medium` | 讀文獻、核對 DOI/引用內容會拉長 context，適合 fork；若只是單篇快速核對可留 inline |
| `external-data-sources` | inline | `haiku` | `low` | 主要是查來源與操作手冊，偏 lookup/reference；若延伸成大規模找資料再 fork |
| `feed-publisher` | inline | `sonnet` | `medium` | 讀者向文章以 Sonnet 當預設較省；若是方法論密度高、論文級摘要再手動升 Opus |
| `finance-paper-quality` | inline | `opus` | `high` | claim-evidence、學術定位、貢獻界定屬高風險高判斷任務 |
| `latex-academic-reviewer` | `context: fork` | `opus` | `high` | 全面審查長論文容易吃 context，review report 適合在 forked worker 中完成後回主線整合 |
| `member-questions` | `context: fork` | `sonnet` | `low` | 例行問題排序/挑題是 routine cron 型流程，與主線研究常無關，應隔離 |
| `memory-health` | `context: fork` | `sonnet` | `medium` | 記憶健康檢查常會碰大檔與 dedup，適合用乾淨 context 做完再回報 |
| `paper-review-cycle` | inline | `sonnet` | `medium` | 這是 review orchestration，不是方法論判斷本身；真正 reviewer skills 再用各自 model |
| `paper-stage-classifier` | inline | `haiku` | `low` | 分類與 cadence 判定規則化程度高，應做成便宜快速判斷 |
| `paper-update` | inline | `sonnet` | `medium` | 修訂/編譯/同步偏程序型，但若改動牽涉核心方法論，應回主線用更高模型處理 |
| `publication-candidates` | `context: fork` | `sonnet` | `low` | 選題掃描常會讀 knowledge / event context，適合 fork；最後決策回主線 |
| `taiwan-macro-data` | inline | `haiku` | `low` | 資料來源與欄位/下載規則查詢屬 reference work |
| `worktree-merge-verification` | inline | `sonnet` | `low` | 目標是 merge 後驗證與補救，流程明確、推理深度需求低 |

#### 建議補充規則

1. `autonomous-research`、`finance-paper-quality`、`latex-academic-reviewer` 三個仍應視為高風險技能，不要為了省 token 預設降到 Sonnet 以下。
2. `citation-verifier`、`publication-candidates`、`memory-health`、`member-questions` 這類會讀較多背景的技能，預設應偏向 `context: fork`。
3. `paper-stage-classifier`、`external-data-sources`、`taiwan-macro-data` 這類 lookup / classification 型技能，應優先吃便宜模型，避免無謂 thinking。
4. `feed-publisher` 的預設可用 `sonnet/medium`，但發佈前若內容涉及方法學細節或重要數字詮釋，主線程仍應做一次 higher-intelligence pass。

#### 兩個實作注意點

1. `.claude/skills/member-questions/SKILL.md` 與 `.claude/skills/taiwan-macro-data/SKILL.md` 已標準化；後續新增 provider-visible skill 時也維持統一使用 `SKILL.md`。
2. 自訂 subagent 目前已存在：
   - [docs-researcher](</Users/yhlai0911/Desktop/volpred-research/.claude/agents/docs-researcher.md:1>)：`model: haiku`
   - [fresh-context-worker](</Users/yhlai0911/Desktop/volpred-research/.claude/agents/fresh-context-worker.md:1>)：`model: sonnet`
   後續可直接把部分 `context: fork` 的 skills 綁到這兩類 worker，而不必每次臨時決定。

### Phase 3：建立「任務完成邊界」，但不要硬自動 clear

#### 為什麼不建議硬自動 `/clear`

因為：

- Claude Code 沒有官方原生「task 完成即自動 /clear」機制
- `/clear` 太強，會直接切斷當前脈絡
- 很容易在你其實還要追問、驗證、修小 bug 時太早清掉

#### 比較合理的做法

做一個 `/task-done` skill 或 workflow：

1. 寫本輪摘要
2. 寫下一輪 anchor
3. 看目前 context %
4. 給出固定決策：
   - `<55%`：留在原 session
   - `55-70%`：建議 `/compact`
   - `>70%` 或 task family 切換：建議 `/clear`

重點：

- 這是 **半自動**
- 比硬自動 clear 安全
- 也更符合官方能力邊界

若你真的要「完全自動」，比較像是：

- 外部 wrapper / orchestration 在每個 task 後關閉 session，再開新 session

這不是 Claude Code 內建 task hook 直接能優雅完成的事。

### Phase 4：再處理 shell glue 與 prompt 瘦身

這仍然重要，但應排在上面幾件之後。

#### 4.1 收斂 shell glue

把高頻巡檢收斂成固定 CLI：

- `uv run volpred ops queue-summary`
- `uv run volpred ops scheduler-summary`
- `uv run volpred ops token-summary`
- `uv run volpred ops log-summary`

#### 4.2 prompt 改 ID-based

從長自然語言 SOP 改成：

- workflow id
- 必讀檔案
- 成功標準

#### 4.3 長 session 仍要提早切斷

就算 subagent 用得再對，若主 session 一直不切，`cache_create` 還是會持續長。

## 對你使用情境的最終建議

### 不要做的事

- 不要把 `agent team` 當日常預設
- 不要把所有大於某 token 門檻的事情都丟 subagent
- 不要期待「任務完成後自動 /clear」是現成內建能力

### 應該做的事

- 保留 subagent，精準用在 noisy side task
- 用 workflow index + skills 做任務路由
- 用 skill/subagent frontmatter 管 `model` / `effort`
- 用 `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=62` 提早 compact
- 用現有 status line 當決策邊界，而不是只當顯示器

## 建議的實作順序

1. 修正文檔語義：明確區分 `subagent` 與 `agent team`
2. 保留現有 status line，改門檻規則
3. 設 `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=62`
4. 關掉 `agent team` 預設開啟
5. 建 workflow index
6. 把高頻 workflow 改成 skill
7. 為 skill / subagent 加 `model` / `effort`
8. 建 `/task-done` 半自動收尾流程
9. 再做 shell glue 收斂與 prompt 瘦身

## 最值得先做的三件事

1. 關掉 `agent team` 預設，保留 `subagent`
2. 做 workflow index + supporting files
3. 用既有 skills 的 `model` / `effort` / `context: fork` 正式路由任務

## 參考

- Claude Code subagents: https://code.claude.com/docs/en/sub-agents
- Claude Code agent teams: https://code.claude.com/docs/en/agent-teams
- Claude Code skills: https://code.claude.com/docs/en/skills
- Claude Code costs: https://code.claude.com/docs/en/costs
- Claude Code env vars: https://code.claude.com/docs/en/env-vars
- Claude Code model config: https://code.claude.com/docs/en/model-config
- Claude Code commands: https://code.claude.com/docs/en/commands
- Claude Code hooks: https://code.claude.com/docs/en/hooks
- Claude Code status line: https://code.claude.com/docs/en/statusline
