# Experiment Agent Preamble

每個正式 experiment brief 都要要求 agent 先讀本文件與
`operations-core-contract.md`。Agent 只產出被授權的 experiment tree；主線程負責
shared state、review、knowledge 與 integration。

## 1. 研究誠實

- 數字、表格與圖只來自實際執行 artifact。
- README 與 results 標明資料來源、期間、樣本數、更新/vintage 時點。
- 明確區分 empirical、simulation、theoretical 與 descriptive。
- Proxy 必須說明理想變數、採用原因與已知偏誤。
- Null、模型不收斂及資料不足都如實保存。
- 結論強度不得超過 formal tests 與 OOS evidence。

## 2. 模型與 target 對齊

| 模型 | 原生預測標的 | 主要評估 target |
|---|---|---|
| GARCH / GJR / EGARCH | close-to-close conditional variance | daily squared return 或明確的 full-day proxy |
| HAR-RV | intraday realized variance | 相同 sampling rule 的 realized variance |
| MEM | absolute return / duration-like nonnegative process | 與 fitted observation 一致 |
| Range estimator | intraday high-low variation | 相同 range-based measure |

跨模型比較若 target 不同，先建立共同 estimand 或 proxy-robust loss。模型在自己的
原生 target 勝出可能是 mechanical result，不能自動宣稱 empirical contribution。

## 3. 時序與 lookahead

- `signal from t-1, return at t`；代碼中要有明確 lag 或等價 information-set join。
- Forward-label row 只有在完整 label window 早於 forecast origin 時才可進 train。
- 跨市場以實際可用時間及交易日 join，不以相同 date label 猜測同步。
- 修訂型總經資料使用 real-time vintage；做不到時標為 final-vintage pseudo-OOS。
- Baseline、candidate、成本與 rebalance 使用相同 lag convention。

跨市場細節見 `data-timing.md`。

## 4. 統計與風險 gate

- 固定 bootstrap、Monte Carlo、sampling、split 與 optimizer seed。
- Forecast loss 使用 repository canonical QLIKE/DM implementation。
- DM/HAC bandwidth 不自行退化成只用 `h-1`；依 repo canonical implementation 並做
  sensitivity。
- 多重比較依 `research_program.md` 的 Harvey 標準。
- VaR 與 ES 同時評估，清楚區分 IS/OOS、coverage、independence 與 joint loss。
- 不同實現波動的策略不可只比較 raw MDD；依 repo rule 做 exposure matching 與
  phase-randomization null。
- Sharpe 遠高於 baseline 時先查 lag、成本、return alignment 與 sample selection。

完整方法論以 `.claude/rules/experiments.md` 和 `methodology.md` 為準。

## 5. 資料診斷先行

估計前保存：

- 缺值、重複、極端值、交易日與 timezone
- 描述統計與 ARCH/autocorrelation diagnostics
- train/OOS 日期與樣本數
- release/vintage availability
- 每個輸入檔或 API snapshot 的 identity

資料品質不符合 brief 成功標準時停止，不以補值掩蓋來源錯誤。

## 6. Runtime artifact contract

必備：

- `README.md`
- `<experiment_id>.py`
- `<experiment_id>_results.json`
- `reproduce_spec.json`

實驗腳本必須以 `finalize_experiment(...)` 同時封存 canonical result 與 spec。不要另寫
一套 results writer，也不要事後手補 code hash。

若已封存結果後要改 entrypoint，先執行 `preserve_gate_blob.py preserve` 保存原始 bytes。
找不到原始 bytes 時回報 blocked；不能用重建檔證明重建流程。

## 7. Review contract

- 執行前：review information set、target、cost、seed、formal test。
- 執行後：review 完整 claim surface，而非只抽查可疑 rows。
- Review agent 不執行受審實驗；需要新 run 時交回正式 compute/experiment workflow。
- `review_verdict.json` 由 gate template 產生，pin 當下 bytes。
- Review 後任何 claim-surface 改動都使 verdict 失效，必須重審。
- Prompt 與 raw transcript 放在受審 worktree 外。

## 8. Worktree ownership 與保存

Worktree agent 只修改 `experiments/<experiment_id>/`。禁止修改 task pool、shared memory、
feed、paper、frontend、Supabase、Mirror 或其他實驗。

完成前，用受鎖的 exact-path transaction 保存本實驗：

```bash
uv run python scripts/git_writer_lock.py commit \
  --actor "<owner>" \
  --task-id "<task-id>" \
  --message "K<id> experiment artifacts" \
  -- experiments/<experiment_id>
```

若此 worktree task 沒有 task id，依 dispatcher 提供的正式 commit contract 執行；不要
自行發明 shared-checkout mutation。整合由主線程執行 `merge_worktree.sh`。

## 9. Agent 回報

依 `agent-result-template.md` 回報：

- artifact 路徑與 hash/identity
- 實際執行命令與 seed
- 核心數字所在 JSON path
- gate 結果
- 異常、null 與限制
- 建議後續

Agent summary 只協助定位；主線程仍會從 canonical results 重新計算所有 claim。
