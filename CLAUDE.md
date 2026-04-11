# 自主波動率預測研究系統
原則上使用繁體中文互動

## 研究誠實原則（最高優先）

**一切結果必須真實、嚴謹、可驗證。**

1. **不可造假**：所有數據必須來自實際計算，不可編造
2. **數據來源透明**：標明來源、期間、樣本數量
3. **實驗三件套**：每個實驗 → `experiments/<id>/`（README+腳本+結果）+ knowledge.json + experience（每 5-10 個彙整）
4. **文獻先於實驗**：新主題前先 WebSearch 3-5 篇文獻，基於文獻設計實驗
5. **觀察先於計算**：描述性統計 → ADF/ARCH LM → 估計 → 收斂檢查 → 異常啟動覆查
6. **統計檢定**：DM test、bootstrap，遵守 Harvey (2016) t>3.0
7. **模型比較公平**：Patton (2011) QLIKE，VaR+ES 同時做
8. **區分實證與理論**
9. **Null result 如實報告**
10. **發佈內容可追溯**：每篇文章標注實驗 K 編號和數據來源
11. **承認局限**
12. **Lookahead Bias**：代碼必須有 `signal.shift(1)`，Sharpe > 2x baseline = 幾乎一定有 bug
13. **自我修正後回溯更新**已發佈文章
14. **固定 seed**：所有隨機操作 `np.random.seed(42)`

## 核心約束（每 turn 必知）

- **⚠️ 禁止整檔讀取**：`feed.json`（5.4MB）、`knowledge.json`（1.4MB）用 `grep`/`jq` 查詢
- **時間用 UTC**：`datetime.now(timezone.utc)` 不是 `datetime.now()`
- **修流程不修資料**：任何問題追溯到底層流程自動化，禁止手動改 JSON/DB
- **Worktree agent 禁止修改共享 JSON**：knowledge.json、feed.json、thinking_journal.json 由主線程負責
- **Agent 完成後**：`bash scripts/merge_worktree.sh` 合併（禁止 `git worktree remove --force`）
- **Codex 審查閘門**：實驗代碼寫完後、執行前先審。卡住或快沒 token → `/codex:rescue`
- **Error Log 優先**：出錯第一步查 `docs/error_log.md`（含研究錯誤和系統錯誤）
- **做事前先查重**：實驗前 `grep knowledge.json`、發文前 LanceDB 語義搜尋，避免重複
- **研究永不停止**：完成任務後立刻下一個，不需等待或徵求同意

## Skill 路由（按需載入，不要全讀）

| 觸發情境 | 載入 Skill |
|---------|-----------|
| 研究實驗、模型、agent team、排程 | `autonomous-research`（含 experiment-preamble、agent 規則、硬體規格） |
| 平台運維、前端、策略管理、發文排程 | `admin-ops`（含 architecture、scheduling、surfaces） |
| 撰寫 feed 文章 | `feed-publisher` |
| 論文寫作/審查 | `latex-academic-reviewer` + `citation-verifier` |
| 外部數據（yfinance/FRED/TAIFEX） | `external-data-sources` |
| 會員問題 | `member-questions` |
| 記憶系統健檢 | `memory-health` |
| Agent 結果驗證 | `agent-result-verification` |
| Worktree 合併驗證 | `worktree-merge-verification` |

**原則：先判斷任務類型 → 載入對應 skill → 按 skill 指引操作。不要把所有 skill 都讀一遍。**

## 活文件原則

以下文件隨研究推展持續演化，應主動修改：
- **`CLAUDE.md`**：架構變更、新發現 → 立即更新
- **`research_program.md`**：目標調整、新研究面向 → 及時更新（北極星文件，保持 < 700 行）
- **`.claude/skills/`**：發現反覆出錯的流程 → 建立或修正 skill

修改原則：新增補充可先做；**刪除或改寫既有治理內容**前須取得使用者同意。

## 署名與歸屬
所有研究成果標注 `[提出: Gemini/Codex/Claude/用戶, 執行: Claude]`。

## Error Log
**遇到 error 第一步查 `docs/error_log.md`。** 每次根本修正後更新該檔案。

## 參考文件指引（不要在 CLAUDE.md 中展開，需要時再讀）
- 網站架構/DB/策略 → `.claude/skills/admin-ops/references/architecture.md`
- 自動化排程/cron → `.claude/skills/admin-ops/references/scheduling.md`
- 快速指令 → `docs/quick-commands.md`
- 論文更新程序 → `docs/paper-guide.md`
- AI 協作模式 → `docs/ai-collaboration.md`
- 研究結論/方法論 → `research_program.md`
- 知識細節 → `storage/memory/knowledge.json`（用 grep 查詢）
