# K1708 agent brief — time-varying state-space HAR

**Model**: claude-opus-4-8 / xhigh (per `scripts/model_router.py --task-type experiment`)

## 任務（WHAT）

在已註冊 worktree `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-8dda242d-k1708` 完成 K1708。你只能新增或修改 `experiments/k1708/` 內的檔案，最後必須在該 worktree commit。

回答：在完全相同的 target、forecast-origin ledger、訓練窗與超參數選擇規則下，時變狀態空間 HAR 是否穩定勝過固定 HAR 與 rolling HAR？至少比較：

1. 固定係數 HAR；
2. rolling-window HAR；
3. 文獻定義可追溯的 state-space HAR / SHAR；
4. 若原始 SHARP-SV 規格能在本機可靠重現，加入 SHARP-SV；若不能，明確列為未實作並說明不可把近似品冒充原模型。

先盤點本機可用資料。優先完成 SPY、QQQ 與本機 TAIFEX TX 三市場；每個市場只能用可 byte-trace、至少 252 個共同 OOS origins 的 realized-variance target。若 SPY/QQQ 沒有足夠歷史的本機 intraday bytes，不得用日報酬平方偷偷替代 RV；應在 results JSON 中誠實標為 `FAIL_NO_DATA`，並以有合格資料的市場完成可驗證實驗。TAIFEX 必須使用 TX 全合約逐日依成交量選最活躍月份，不能直接使用 TX1。

每個 origin 的估計、filtering 與 hyperparameter selection 只能看到當時可得資料。超參數（rolling window、state innovation variance / discount factor 等）必須由內層 rolling validation 選，不得用外層 OOS 或 full-sample smoothed state。所有模型在同一市場使用完全相同的共同 ledger；任何模型失敗的 origin 要在 ledger 與結果中留下可稽核原因。

主評估：QLIKE、MSE、相對 fixed-HAR 的 DM-HLN、Giacomini-White conditional predictive ability、10% MCS（stationary/block bootstrap，seed=42）及事前定義的 high/low-vol regime breakdown。DM 必須呼叫 `volpred.stats.model_evaluation.dm_test`，不可自寫另一份。重疊 horizon 的 block/HAC 長度要與 horizon 一致。先做 one-day horizon；只有時間與資料允許時才加 5-day，且不得犧牲 one-day 的完整驗證。

交付三件套與可稽核附件：

- `experiments/k1708/README.md`：動機、至少三篇 primary scholarly sources、資料 bytes/hash/期間/N、模型方程、lookahead policy、nested tuning、success criteria、限制與誠實結論；
- `experiments/k1708/K1708.py`：可由 repo root 重跑，seed=42；predictor construction 必須有明確的 `.shift(1)`（或名為 `signal = ...shift(1)` 的等價程式碼）讓 target t 只吃到 t-1 可得資訊；
- `experiments/k1708/K1708_results.json`：原子 temp-write + `json.load` 驗證 + `os.replace`，含 schema/status/data traces/common-ledger counts/tuning choices/point losses/test outputs/regime results；
- 至少一張 model-ranking 或 cumulative-loss 圖；必要時另存 compact forecast ledger（不得把大型原始資料複製進 git）。

## 動機（WHY）

固定 HAR 假設 heterogeneous volatility components 的係數跨 regime 不變；rolling HAR 允許變動，但 window 是粗糙且可能高方差的適應方式。K1708 要檢查 state-space filtering 的連續係數更新是否帶來可重現的 OOS 增益，而不是再做一次「較複雜模型點估計較低」的賽馬。

正面結果只有在多個市場、QLIKE/MSE、DM-HLN/GW/MCS 與 regime breakdown 大致一致時才支持 state-space HAR。若只在單一市場或單一 loss 改善，結論只能是 heterogenous/conditional。若 rolling 或 fixed HAR 留在 MCS superior set，應誠實判為沒有穩定優勢。Null result 仍是完整成果。

## 此實驗特有的約束

- 開工先完整讀 `.claude/skills/autonomous-research/references/experiment-preamble.md`、`docs/error_log.md`、`research_program.md` 的 K1708 原始題目，並用 `rg` 搜 `storage/memory/knowledge.json` 與既有 HAR 實驗，避免重做或沿用已知錯誤。
- 文獻先行：至少查三篇原始論文或官方 working paper，先鎖定 SHAR/SHARP-SV 的真正方程、filtering 與 tuning；不可只靠二手摘要或模型名稱猜規格。
- 可重用已驗證的 local data loader、DM/MCS helper 與 K1704 common-ledger/data-trace pattern，但必須在 README 列出 reused code 與任何必要差異。
- 所有 variance forecast 必須為有限正數；clip/floor 規則只能由 inner training data 決定並揭露，不得在看完 OOS 後調參。
- 不可把 filtered in-sample fit 當 forecast；不得使用 Kalman smoother 的 future information。
- 不得修改 `storage/next_tasks.json`、knowledge/work log、feed、research program、任何 Supabase/Mirror state，也不得發布文章。
- 若資料或 dependency 阻擋，仍需產出有效 `K1708_results.json`，以可驗證的 failure status、已完成的診斷與 exact blocker 收尾；不可造數或留下截斷 JSON。

## 成功標準

完成標準是三件套、至少一圖、可重跑 command、所有輸出 JSON 可 parse、common-ledger 與 nested-OOS 無 lookahead、正式檢定齊全，且 worktree commit 只包含 `experiments/k1708/`。

結果判準：

- `SUPPORTED`：state-space model 在至少兩個合格市場 QLIKE 改善，DM-HLN 過 Harvey |t|>=3，GW 支持、且進入 MCS superior set，regime 結論不靠單一短期；
- `CONDITIONAL_PASS`：有可重現增益但跨市場／loss／regime 不一致；
- `NULL`：未穩定優於 fixed/rolling HAR；
- `FAIL_NO_DATA` / `FAIL_METHOD`：資料或可追溯規格不足，明列 blocker。

任何異常（forecast 非正、state variance 在邊界、單一模型 origins 大量消失、極端 loss 由一兩天主導）都必須在 README 與 results 中顯示，不能 silent drop。

## 相關知識

- K1704：TAIFEX 上 common OOS ledger 與 proxy-robust QLIKE ranking 已完成並有 byte-level trace；可借鑑資料追溯與共同 origins，不可直接把其結論當 K1708 結論。
- K986：rolling adaptive HAR 未勝 static 版本，提醒「適應」本身可能只增加估計噪音；其日報酬平方 target 不可直接拿來冒充本題 RV 設計。
- K849/K850、K868/K874/K884 及其他 HAR-RV 實驗可能含可重用 TAIFEX loader；使用前先驗證 target、contract roll 與 lookahead convention。

## 必讀文件

- `.claude/skills/autonomous-research/references/experiment-preamble.md`
- `.claude/skills/autonomous-research/references/data-timing.md`
- `.claude/skills/autonomous-research/references/methodology.md`
- `.claude/skills/autonomous-research/references/agent-result-template.md`
- `AGENTS.md`
- `docs/error_log.md`
- `.claude/rules/experiments.md`
- `research_program.md`
- `experiments/k1704/README.md`
- `experiments/k986/README.md`

## 收尾與回報

從 worktree repo root 跑必要測試與至少一次 clean rerun，驗證 JSON parse 與 git diff scope。然後在 worktree commit，訊息使用 ASCII，例如 `K1708: evaluate state-space HAR forecasts`。回報時依 `agent-result-template.md`，列出 commit hash、exact files、commands/exit codes、資料期間/N、主要數字、誠實 verdict、blockers。不要 merge worktree；後續 collector 會在 Codex review/certification 後用正式 `scripts/merge_worktree.sh` 整合。
