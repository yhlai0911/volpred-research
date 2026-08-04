# CLAUDE.md × AGENTS.md 整合提案（逐章判斷）

**狀態**：提案，尚未寫入任何治理檔。老闆 2026-08-04 指定設計＝「共用章節機械同步」＋「逐章由我判斷後提報」。

## 1. 為什麼要做

- 11 個同名章節**全部漂移**（逐章 md5 比對，無一相同）。
- 各自獨有的規則**正是對方需要的**。實證：本 session 主線程漏掉 graphify（只在 AGENTS.md），
  整場改用 grep 與手寫 AST walker 定位；`query_usage.jsonl` 顯示同一個問題別人花 ~923 token。
- 漂移已經碰到**最高優先規則**：研究誠實原則 CLAUDE 13 行（6 條壓縮）vs AGENTS 27 行（13 條原版）。
  語意目前不牴觸（6 條是 13 條的合併），但這是兩份會持續分岔的副本。

## 2. 誰比較新（客觀證據，非口味）

| | commits / 近半年 | 最後修改 |
|---|---|---|
| CLAUDE.md | **141** | 2026-07-29 |
| AGENTS.md | 29 | **2026-08-02**（graphify 整合） |

CLAUDE.md 維護頻率約 5 倍，但 AGENTS.md 持有最新那筆。分工實況是：
**CLAUDE.md 在治理／後設規則上較新**（互動 session 編輯），
**AGENTS.md 在執行機制上較新**（Codex 編輯）。因此不能單向擇一，必須逐章判。

## 3. 逐章判斷

「獨有」＝該章內出現、對方章內未出現的檔名／路徑／反引號術語（去重後計數）。

| # | 章節 | CLAUDE 獨有 | AGENTS 獨有 | 建議 | 理由 |
|---|---|---|---|---|---|
| 1 | Bootstrap 原則 | 9 | 1 | **CLAUDE 為準** | AGENTS 唯一獨有項是自我指涉 `AGENTS.md`；CLAUDE 多出 path-trigger 時序原則、`feedback_path_narrowing_audit` |
| 2 | 研究誠實原則 | — | — | **CLAUDE 為準**（老闆已定壓縮方向） | 6 條壓縮版語意涵蓋 13 條；完整版仍在 `.claude/rules/experiments.md` 與 git history |
| 3 | 專案地圖 | 6 | 0 | **CLAUDE 為準** | CLAUDE 有 agy／codex CLI 可用性與對應 memory 指標，AGENTS 無獨有項 |
| 4 | 關鍵操作規則 | 9 | 5 | **合併** | CLAUDE：3-Strike、anti-stacking、`enforcement_layer_map.md`；AGENTS：`event_jobs`、`handoff_latest/archive` |
| 5 | Token / Context 紀律 | 18 | 3 | **合併（CLAUDE 為主）** | CLAUDE 有 `%` 行為邊界、`/compact`、notebooklm；AGENTS 有 `context-hygiene.md`、`read_context_budget.py` hook |
| 6 | 實驗與研究流程 | 3 | 多 | **合併（AGENTS 為主）** | AGENTS 獨有一整套 CI artifact gate：`check_experiment_artifacts.py`、`.github/workflows/experiment-artifacts.yml`、`config/experiment_artifact_exclusions.json`、`code_trace`、K1708/K1750 教訓。CLAUDE 完全沒提 |
| 7 | 發佈、論文、策略 | 3 | 0 | **CLAUDE 為準** | AGENTS 無獨有項 |
| 8 | 自動化與控制面 | 10 | 8 | **合併** | CLAUDE：`clamp_machine_priority_inflation`、incident lifecycle；AGENTS：slot-aware idle continuation、`.codex/worktrees/` |
| 9 | Agent skills | 10 | 多 | **合併** | AGENTS：**graphify**（本 session 漏掉的那條）、全域 `$HOME/.agents/skills/`；CLAUDE：path ownership 協調、issue disposition |
| 10 | 活文件原則 | 1 | 0 | **CLAUDE 為準** | 僅差 `.claude/rules/` 指標 |
| 11 | 一句話版本 | 0 | 0 | **等價，任一** | 無獨有項，僅字面差異 |

小計：**CLAUDE 直接為準 5 章、等價 1 章、需真正合併 5 章。**

### 查證後撤回的一項指控

初判懷疑 AGENTS.md 還在教已退役的 `.agents/skills/`。**查證後不成立**：AGENTS.md L319 明確區分
「全域 `$HOME/.agents/skills/`（存在，已驗證）」與「repo 內已退役副本（禁止復活）」，比我原先假設精確。
此項不列為合併理由。

## 4. 機械同步設計

```
config/governance_shared.md          ← 共用區唯一來源
  ├─ 上表判定為「CLAUDE 為準／等價」的 6 章，取 CLAUDE 版
  ├─ 判定為「合併」的 5 章，取聯集（逐條標註來源）
  └─ 補進雙邊都該知道但目前單邊獨有者：graphify、Mission/Vision

CLAUDE.md = <生成的共用區> + Compact Instructions + 回報時間戳 + 系統定位/PDCA
AGENTS.md = <生成的共用區> + Codex 每小時任務池工作流

scripts/sync_governance.py           ← 生成器（唯一 writer）
tests/test_governance_sync.py        ← gate：兩檔共用區與來源不符即 FAIL
```

**為什麼不用「指標」而用「複製＋gate」**：兩個 agent 只 auto-load 自己那份，指標依賴對方主動跟隨。
本 session 就是反例 —— handoff 明確要求讀 AGENTS.md，主線程只跑了 `wc -l` 就跳過，於是漏掉 graphify。
複製讓兩邊都自足（不需跟隨），gate 讓複製不會漂移。這也符合專案「prose 提醒升級為機械 gate」的既有路線。

## 5. 落地順序（每步可獨立驗證）

1. 建 `config/governance_shared.md`，內容＝上表判定結果（**此步會產生實質內容決策，需老闆逐章確認**）
2. 寫 `scripts/sync_governance.py`，以標記區塊（`<!-- shared:begin -->` / `<!-- shared:end -->`）注入兩檔
3. 跑一次同步，**逐檔 diff 給老闆過目**後才 commit
4. 加 `tests/test_governance_sync.py`，並做 break-then-verify（故意改壞一邊必須轉紅）
5. 依 `docs/agents/ownership.md`：改 AGENTS.md ＝對 Codex 下指令，commit 後在回覆說明

## 6. 風險

- **AGENTS.md 由 Codex 頻繁編輯**：同步後 Codex 直接改共用區會被 gate 擋。需在共用區頂端標明
  「此區由 `scripts/sync_governance.py` 生成，請改 `config/governance_shared.md`」。
- **兩檔都會變長**（各自吸收對方獨有規則）。與「CLAUDE.md 保持精簡」的既有指示有張力；
  緩解方式是合併時同步套用 CLAUDE.md 既有的壓縮風格，而非原樣貼上 AGENTS 長版。
- 第 1 步的逐章取捨是**內容決策**，不是機械操作，需老闆確認後才寫。
