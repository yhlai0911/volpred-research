# Agent Orchestration

這份文件是 `autonomous-research` 的派工與 brief 規格。

在以下情況讀它：

- 要決定用什麼模型 / agent 類型
- 要寫 experiment / paper / feed agent prompt
- 要分派 2-4 個 worktree agent
- 要決定研究主題從哪裡來

## Owner 與邊界

- **owner**：`autonomous-research`
- **paper-specific workflow**：交給 `paper-*` skills
- **feed 文章內容**：交給 `feed-publisher`
- **平台節奏 / cron / deploy**：交給 `admin-ops`

本檔負責的是**研究主線如何派工與收斂**，不是平台操作手冊。

## 研究主題來源優先序

不要只靠自己憑感覺選題。優先序如下：

1. 使用者指定
2. 正在推進的 open question / member question
3. 已完成實驗衍生出的 follow-up
4. Codex / Gemini 的具體建議
5. 文獻缺口或 cross-market 驗證需求

若連續 3 個 null result，先換方向，再派 agent。

## 模型 / agent 選擇

高精確度工作一律優先最強模型：

- 研究實驗
- 統計檢定
- 回測與風險評估
- 論文寫作 / 論文審查
- 程式修正

可放寬的情況：

- 單純 grep / 搜檔 / 探路 → read-only explorer 類型
- 單純 feed 文章草稿 → 可用較輕模型，但仍需 `feed-publisher` 規範

## 什麼時候要派 agent

適合派 agent：

- 多個獨立實驗可平行
- 單一任務可明確切成 worktree
- 需要第二意見或 adversarial review
- 主線程可以同時做 synthesis / literature / verification

不適合派 agent：

- 下一步完全依賴那個 agent 的即時結果
- 任務邊界不清楚
- 會碰共享 JSON / Supabase / Mirror 寫入

## Brief 最小欄位

每個 agent prompt 至少要有：

- `WHAT`：要做什麼
- `WHY`：為什麼現在做
- `FILES / DATA`：要讀哪些檔
- `CONSTRAINTS`：不可犯的錯
- `SUCCESS CRITERIA`：什麼算完成
- `OUTPUT FORMAT`：回報格式

不要只寫「幫我研究看看」。

## 各類 agent 必備約束

### Experiment agent

- 必讀 `experiment-preamble.md`
- 先查 `docs/error_log.md`
- 引用相關 K 編號 / knowledge
- 若是策略回測，必須顯式 lag

### Feed agent

- 必讀 `feed-publisher`
- 自己讀實驗 JSON / 圖表需求
- 不負責文章池 / 通知 / cadence

### Paper review agent

- 明確指定 `paper-stage-classifier` / `paper-review-cycle` / `paper-update`
- 內容品質與 citation / LaTeX 分工不可混淆

### Worktree agent

- 必須 commit
- 不得改共享狀態 JSON / Supabase / Mirror
- 返回後主線程仍需：
  - `agent-result-verification`
  - `worktree-merge-verification`

## 主線程責任

派工後，主線程不能只等結果。

主線程要做：

- 文獻補查
- 結果 synthesis
- 數字驗證
- merge 與落地檢查
- knowledge / experience / research_program 回寫

## 返回後的固定流程

1. 看 agent 回報是否完整
2. 用 `agent-result-verification` 驗數字
3. 用 `worktree-merge-verification` 驗檔案與 merge
4. 主線程做 synthesis
5. 再決定是否發文、是否續做下一個實驗

## 反模式

- 派 agent 前沒有明確成功標準
- agent 跑完就直接相信數字
- worktree agent 直接碰共享 state
- 把平台部署、排程、通知塞進研究 agent
- 用 agent 補救其實應該由 hook / script 防呆的問題

## 搭配文件

- `agent-brief-template.md`
- `agent-result-template.md`
- `experiment-preamble.md`
- `ai-collaboration.md`
- `question-review-guide.md`
