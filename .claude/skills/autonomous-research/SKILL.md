---
name: autonomous-research
description: >
  Design, execute, and verify a VolPred research experiment from a concrete
  volatility-forecasting question. Use for requests to run or continue an
  experiment, test a model or strategy, or turn a verified research gap into
  experiment artifacts.
---

# Autonomous Research

這個 skill 是「研究問題 → 可驗證實驗」的 orchestrator。它不擁有排程、文章發布、
paper state、deployment 或 shared-memory 寫入。

## 開工 gate

先完整讀：

1. `references/operations-core-contract.md`
2. `references/experiment-preamble.md`
3. `.claude/rules/experiments.md`
4. `docs/error_log.md` 的索引及與本題相關條目

每次 invocation 都先執行：

```bash
uv run python scripts/task_pool_control.py status
```

即使工作由使用者直接交付，也要回讀 mode；只有需要 queue mutation 時才依 mode 分支。

## 研究流程

### 1. 把問題寫成可推翻的假說

Brief 必須列出：

- 動機與決策用途
- empirical / theoretical / simulation / descriptive 類型
- 與既有 K 的差異
- 資料來源、期間、預期樣本數及 proxy 偏誤
- baseline、lag convention、主要 loss 與正式檢定
- 正面、null、失敗各自代表什麼
- 可機械檢查的完成標準

使用 `references/agent-brief-template.md`，不要讓 agent 自己補研究動機。

### 2. 先查既有證據，再查文獻

- 以 `rg`、bounded `jq` 或 knowledge index 搜尋相關 K；不要整檔載入大型 memory。
- 非純探索題至少核對三篇 primary academic sources。
- 記錄作者、年份、正式 URL/DOI、方法與本實驗採用或偏離之處。
- 已有等價實驗時，只有資料、期間、識別或方法存在明確增量才繼續。

文獻事實未核實前，不建立虛構 paper title、DOI 或結論。

### 3. 保留 experiment identity

不從資料夾最大值推算 K 編號。使用：

```bash
uv run python scripts/kid_reserve.py reserve \
  --owner "<owner>" --topic "<topic>"
```

建立標準目錄優先用：

```bash
uv run volpred ops experiments scaffold \
  --experiment-id <experiment_id> --title "<title>"
```

正式 artifact 至少包含：

- `experiments/<experiment_id>/README.md`
- `experiments/<experiment_id>/<experiment_id>.py`
- `experiments/<experiment_id>/<experiment_id>_results.json`
- `experiments/<experiment_id>/reproduce_spec.json`

結構細節見 `references/folder_layout.md`。

### 4. 派工與寫入邊界

- 可獨立執行的正式實驗使用 worktree；只授權
  `experiments/<experiment_id>/`。
- Agent brief 必含 K-id、error-log 防錯條目、相關 K、資料與成功標準。
- Worktree/background agent 不寫 task pool、memory、feed、paper、Supabase 或 Mirror。
- Review prompt 與 raw transcript 放在受審 worktree 外，避免污染 clean-tree read-back。
- 派工與 timeout 切割見 `references/delegation-playbook.md`。

### 5. 觀察先於估計

先保存：

- 缺值、重複、極端值與交易日覆蓋
- 描述統計、分布、ARCH/自相關診斷
- timestamp、timezone、release/vintage 可用時間
- train/OOS 切點與每一段樣本數

再估計模型，固定所有 seed。策略訊號必須由 `t-1` 形成並作用於 `t` 報酬；baseline
使用相同 lag 與成本口徑。更完整方法論分支見 `references/methodology.md`、
`references/data-timing.md` 與 `references/transaction-costs.md`。

### 6. Runtime 同時封存 results 與 spec

實驗腳本收尾必須呼叫
`volpred.research.reproduce_spec.finalize_experiment`。不能先寫 results、幾天後再補
spec。輸入 identity、seed、entrypoint code trace 與 canonical result 必須來自同一次 run。

若已 pin 的 entrypoint 要改，先按
`references/operations-core-contract.md` 執行 `preserve_gate_blob.py preserve`；
原始 bytes 不可重建或用新檔冒充。

### 7. 審查與 artifact certification

順序：

1. 執行前 review lag、target alignment、成本、seed 與 inference。
2. 執行後從 artifact 重建所有對外 numeric/verdict claims。
3. 用 `scripts/reproduce_check.py inventory` 檢查 reproduce contract，再跑
   `scripts/experiment_gates.py run`。
4. 由獨立 reviewer 產生 pin 住 claim surface 的 `review_verdict.json`。
5. 跑 `scripts/check_experiment_artifacts.py check`。

Agent 回報不是證據。返回後一律交給 `agent-result-verification`；worktree integration
也由該 skill 的 worktree 分支處理。

### 8. Main-thread integration

只有 reviewer verdict 與 artifact identity 都有效時，主線程才：

- 從 canonical result 程式化產生 knowledge record
- 經 canonical memory writer 與 K1259 gate 寫入並回讀
- 更新 `research_program.md` 的 verified finding／null／限制
- 視需要提出 article 或 paper 的 handoff，由對應 owner 決定

不在本 skill 直接發文或改 paper body。若要新增後續 task，重新讀 task-pool mode，
再依 `references/operations-core-contract.md` 選合法入口。

## 完成條件

- [ ] K-id 由 registry 保留，沒有 identity 衝突
- [ ] 文獻、既有 K、資料來源、期間與樣本數可核實
- [ ] README、entrypoint、canonical result、runtime spec 齊全
- [ ] seed、lag、成本、OOS、收斂與正式檢定有證據
- [ ] result/spec/code trace identity 一致
- [ ] independent review 與 experiment gates 通過
- [ ] knowledge 由 main thread 經 canonical writer/K1259 寫入並回讀
- [ ] worktree 經 `merge_worktree.sh` 整合，main artifact hash 已回讀
- [ ] null result 與局限如實保留

任一 artifact identity 或 provenance 不明時，狀態只能是 blocked；只補跑或補檔則是
`contained`，不得宣稱完整解決。

## 需要時才讀的 references

| 情境 | Reference |
|---|---|
| 所有研究／task／memory／git 操作 | `references/operations-core-contract.md` |
| Experiment agent 通用方法論 | `references/experiment-preamble.md` |
| Brief / return 格式 | `references/agent-brief-template.md`, `references/agent-result-template.md` |
| 派工、timeout、ownership | `references/agent-orchestration.md`, `references/delegation-playbook.md` |
| Artifact layout | `references/folder_layout.md` |
| 模型、策略與交易成本 | `references/models.md`, `references/strategies.md`, `references/transaction-costs.md` |
| 跨市場時間對齊 | `references/data-timing.md` |
| 策略上架前研究 gate | `references/strategy-launch-gate.md`, `references/add-strategy-guide.md` |
