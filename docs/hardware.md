# 硬體資源與執行模式

## 硬體規格

| 項目 | 規格 |
|------|------|
| CPU | Apple M1 Max · 10 核心 |
| RAM | 64 GB |
| 平行 agent 建議 | 3-4 個 worktree agent 同時跑（每個 ~1GB RAM） |
| GARCH 估計速度 | ~6ms/model（單核） |
| Bootstrap 10,000 reps | ~2-5 秒 |
| 大規模 sweep（100 configs） | ~1 分鐘（單核串行） |

設計分析程式時參考：
- 可用 `multiprocessing` 平行化 cross-asset sweep（10 核 → 10 資產同時跑）
- 64GB RAM 足以載入全部資產的完整歷史（~500MB total）
- Agent worktree 每個 ~800MB，同時 4 個 = 3.2GB（無壓力）

## 執行模式選擇

Claude Code 的 Agent 工具可啟動獨立子程序（subagent），有自己的 context window 和工具權限。這個 repo 的預設不是「把所有工作丟給 agent team」，而是依 task shape 選最便宜、最乾淨的模式。

### 1. 單一主 session

適合：
- 單一 `grep` / `jq` / 小 edit / 一次驗證
- 需要保留完整決策鏈的主線任務
- agent 回報後的 synthesis / 驗證 / canonical 寫入

### 2. Forked subagent

預設用在：
- 大量搜尋、log 過濾、docs lookup
- 與主線無關的 side task
- 可 self-contained 的局部寫入或唯讀探索

這是本專案的**主要平行化手段**，不是 agent team。

### 3. Agent team

只在以下情況啟用：
- 多個 session 之間需要直接討論、交叉審查或挑戰假說
- 單純多個獨立 subagent 不足以完成任務
- 跨多模組事故 / paper synthesis / 策略上架評審等真實協作場景

若子任務彼此不必互相溝通，就不要開 team。

## 模型與 workflow 路由

先看 [`docs/workflow-index.md`](/Users/yhlai0911/Desktop/volpred-research/docs/workflow-index.md)，再讀對應 skill。預設矩陣如下：

| 工作類型 | 預設模式 | 預設 model / effort | 備註 |
|---------|------|------|------|
| 研究實驗、統計檢定、核心方法論判斷 | inline 主線程，side task 再 fork | `opus / high` | 高風險任務，不為省 token 降級 |
| 平台 ops、發文、paper-update 類程序型工作 | inline | `sonnet / medium` | 流程明確，優先依 skill frontmatter 跑 |
| 驗證、merge safety、publication scan、member QA ranking | inline 或 forked subagent | `sonnet / low` 或 `medium` | 以精準比對與 checklist 為主 |
| data-source lookup、paper stage 判定、分類型任務 | inline | `haiku / low` | 便宜快速即可 |
| 大量 docs / log / 無關 side task | forked subagent | 跟隨對應 skill | 先隔離 context，再摘要回主線 |

## 平行 slot 原則

- M1 Max 10 核可支援 3-4 個獨立 agent / worktree，但**不是每次都要塞滿**。
- 平行化的前提是寫入範圍不重疊、brief self-contained、主線程仍能驗證結果。
- Codex 類 subagent 預設 serialize；只有完全獨立時才放寬到同一 session 最多 3 個。

## Context 邊界

Context / status line 門檻以 `config/token_policy.json` 為準：

- `< normal_max_pct`：正常工作
- `normal_max_pct - compact_min_pct`：避免開新 noisy side task；優先 fork 或收斂
- `compact_min_pct+`：優先 `/compact`
- `clear_min_pct+`：除非正在收尾，不開新主題；跨 workflow 時優先新 session
