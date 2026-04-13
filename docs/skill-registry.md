# `.claude/` Skill Registry

`\.claude/` 是本專案的 canonical skill 母本。`\.agents/` 只是複製品，本次整理不修改。

本表的目的不是重述每個 skill 全文，而是回答四件事：

1. 什麼任務應該觸發哪個 skill
2. 哪些事情不該交給它
3. 需要轉交給哪個 skill
4. 它承接 `CLAUDE.md` 的哪一段治理或操作規則

## Top-Level Skills

| Skill | Trigger Phrases | 使用範圍 | 不該處理的內容 | Handoff | 對應 `CLAUDE.md` 段落 |
|------|------|------|------|------|------|
| `autonomous-research` | `開始研究`, `繼續研究`, `run experiment`, `跑實驗`, `研究波動率`, VT / vol forecast 相關請求 | 研究主流程、文獻搜尋、實驗設計、實驗執行、knowledge / experience 記錄、研究多元化 | 平台 ops、文章池節奏、feed 發文排程、paper review orchestration、citation-only 任務 | `feed-publisher`, `admin-ops`, `agent-result-verification`, `worktree-merge-verification` | `自主研究模式`, `實驗前必做`, `實驗完整流程`, `研究多元化`, `AI 協作模式`, `Agent Prompt 必備內容`, `排程核心原則` |
| `feed-publisher` | `發文`, `發佈`, `publish`, `post to feed`, `發佈到網站` | 文章內容規格、圖表要求、資料來源標注、主題查重、事件文章內容時效規則 | 文章池釋出、通知寄送、平台 cadence、研究設計本身、paper 寫作 | `admin-ops`, `autonomous-research` | `每日文章產出要求`, `署名與歸屬` |
| `admin-ops` | `admin`, `後台`, `平台操作`, `文章池`, `排程發布`, `ops`, `analytics`, `策略管理`, `問答管理` | 平台 surfaces、ops CLI、文章池、排程、通知、策略 metadata、問答營運、session cron / monitor 操作 | 核心研究判斷、論文寫作、citation 驗證 | `autonomous-research`, `member-questions`, `paper-update` | `思維模式：永遠修流程，不修資料`, `自動化：cron + Monitor`, `排程核心原則`, `Agent-first Ops Layer` |
| `member-questions` | `會員問題研究`, `member questions`, `提問排名`, `評估會員問題` | 會員問題評分、stable insertion rerank、atomic claim、candidate lifecycle、`question-answer` 綁定 | 核心研究分析本身、文章實際撰寫、平台 cadence | `autonomous-research`, `feed-publisher`, `admin-ops` | `研究主題來源`, `每日文章產出要求`（member QA 文章邏輯）, `快速指令` 的 question CLI |
| `finance-paper-quality` | `寫論文`, `revise paper`, `check paper quality`, `submission checklist` | 論文內容品質、claim-evidence matching、contribution hygiene、Harvey (2016) rigor | citation-only、LaTeX 結構審查、平台同步 | `citation-verifier`, `latex-academic-reviewer`, `paper-update` | `論文`, `研究誠實原則` 中的局限/不過度宣稱/統計嚴謹 |
| `latex-academic-reviewer` | `審查論文`, `LaTeX review`, `review paper`, `學術審查` | LaTeX 結構、論述邏輯、符號一致性、review report workflow | 純 citation 驗證、內容貢獻強度判斷、平台同步 | `citation-verifier`, `finance-paper-quality`, `paper-review-cycle` | `論文`, `Agent Prompt 必備內容` |
| `citation-verifier` | `verify citations`, `驗證引用`, `check references`, `檢查參考文獻` | citation bibliographic accuracy、DOI、內容是否忠於原文 | 一般 paper quality、LaTeX 結構審查、研究實驗 | `finance-paper-quality`, `latex-academic-reviewer`, `paper-review-cycle` | `論文`, `研究誠實原則` 的引用與可追溯要求 |
| `paper-stage-classifier` | `paper stage`, `論文 stage`, `ready_for_submission`, `submitted` | paper stage 判定、continuous review loop 入口條件 | 實際跑 review、實際修稿與同步 | `paper-review-cycle`, `paper-update` | `論文` |
| `paper-review-cycle` | `review cycle`, `跑論文審查`, `review_history` | review orchestration、雙 reviewer 併行、review_history 歸檔 | stage 判定、修稿、平台同步 | `paper-stage-classifier`, `paper-update` | `論文` |
| `paper-update` | `paper-update`, `更新論文`, `同步論文平台` | 修稿後的 compile、平台同步、版本化 | stage 判定、review orchestration、citation 審查 | `paper-review-cycle`, `paper-stage-classifier` | `論文` |
| `agent-result-verification` | agent 實驗結果返回、worktree/background 統計摘要 | 以 results JSON 驗證 agent 回報數字、檢查方向與號誌是否合理 | 研究設計、文章撰寫、平台發布 | `autonomous-research`, `worktree-merge-verification` | `實驗完整流程`, `Agent Prompt 必備內容` |
| `worktree-merge-verification` | worktree agent 返回、merge 後驗證 | merge、reflog 恢復、確認實驗檔案落地、主線程記錄前檢查 | 研究設計本身、平台操作 | `autonomous-research`, `agent-result-verification` | `研究誠實原則` 的 worktree 規範, `Agent Prompt 必備內容`, `排程核心原則` |
| `memory-health` | `memory health`, `記憶健康`, `knowledge 膨脹`, `thinking_journal` | knowledge / thinking / experiment memory 的健康檢查與維護 | 研究本身、一般發文、paper workflow | `admin-ops`, `autonomous-research` | `活文件原則`, `Error Log`, token 節約與記憶治理 |
| `external-data-sources` | `數據來源`, `data source`, `FRED`, `yfinance`, `TAIFEX`, `外部資料` | 外部資料來源用法、資料陷阱、選源導航 | 研究結論、平台 ops、文章內容規劃 | `taiwan-macro-data`, `autonomous-research` | `注意事項` 的外部數據來源段 |
| `taiwan-macro-data` | `台灣經濟數據`, `DGBAS`, `主計總處`, `Taiwan macro data` | DGBAS / NDC 台灣總體數據抓取與欄位說明 | 一般外部資料總覽、研究判斷、平台 ops | `external-data-sources`, `autonomous-research` | `注意事項` 的 DGBAS / 景氣指標段 |

## Support Bundle

| Bundle | 性質 | 用途 | 備註 |
|------|------|------|------|
| `academic-finance-reviewer/` | reference bundle | 提供 `finance-paper-quality` 使用的資產、模板與寫作品質參考 | 不是獨立 top-level skill，不單獨觸發 |

## Maintenance Rules

- 新增 skill 前，先確認不能用現有 skill + reference bundle 解決。
- 新增/刪除/改名/合併 top-level skill 時，必須同步更新本表；若影響 CLAUDE 導覽或流程入口，也要同步更新 `CLAUDE.md`。
- 若 skill 變更會影響固定路徑、hooks、session 啟動 prompt 或 cron 工作流，必須連帶檢查 `.claude/settings.json`、`scripts/session_startup.md`、`.claude/commands/` 與相關 references。
- 若內容是高頻重複流程但不值得獨立觸發，優先放到現有 skill 的 `references/`。
- 若內容是全域治理原則，優先留在 `CLAUDE.md`，不要硬拆成 skill。
- 若 skill 名稱改動會影響既有觸發，優先保留舊名並在內文修邊界。
