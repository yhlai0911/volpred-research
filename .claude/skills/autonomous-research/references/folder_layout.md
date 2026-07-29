# Experiment Artifact Layout

本文件只定義新建或 touched experiment 的目錄契約。歷史命名與 paper layout 由各自
canonical workflow 管理，不在此保存日期快照。

## 建立 identity 與骨架

先由 registry 保留 K-id：

```bash
uv run python scripts/kid_reserve.py reserve \
  --owner "<owner>" --topic "<topic>"
```

再建立標準骨架：

```bash
uv run volpred ops experiments scaffold \
  --experiment-id <experiment_id> --title "<title>"
```

不要掃目錄後以最大值加一，也不要把 experiment 檔案散放在 `experiments/` 根層。

## 必備結構

```text
experiments/<experiment_id>/
├── README.md
├── <experiment_id>.py
├── <experiment_id>_results.json
├── reproduce_spec.json
└── review_verdict.json
```

可選 artifact：

- 圖表與 tables
- experiment-local input snapshot
- references / data-source manifest
- loss sidecar、diagnostic 或 convergence trace
- knowledge proposal（供主線程 writer 使用）

Experiment-local input 可以放在該 experiment tree；跨實驗 canonical data 必須由正式
storage/collector owner 管理，不得藏在某一 K 目錄作全域來源。

## README 最小內容

- Motivation 與 related K
- Data source、期間、樣本數、vintage/availability
- Empirical / theoretical / simulation / descriptive 類型
- Method、baseline、lag、cost、seed、OOS
- Formal tests 與 acceptance criteria
- Runtime command
- 結果、null、限制
- Artifact 與 review identity

所有數字由 canonical result 程式化產生或核對，不從 agent summary 轉抄。

## Runtime identity

`<experiment_id>.py` 收尾呼叫 `finalize_experiment(...)`，讓 results 與
`reproduce_spec.json` 同時 pin：

- entrypoint bytes
- canonical result bytes
- inputs
- seeds
- runtime timestamps

若 entrypoint 在結果產生後改動，先保存舊 bytes；找不到就 blocked。

## Worktree boundary

Worktree agent 只修改這個 experiment 目錄。Task pool、shared memory、feed、paper、
frontend 及 remote sync 均由主線程/正式 owner 處理。

整合前執行：

```bash
uv run python scripts/experiment_gates.py run \
  --path experiments/<experiment_id>
uv run python scripts/check_experiment_artifacts.py check \
  --path experiments/<experiment_id>
```

整合只走 `bash scripts/merge_worktree.sh <worktree-name>`，之後在 main 回讀 artifact hash。

## 完成判準

- [ ] K-id registry 有 reservation
- [ ] 五個必備 artifact 存在且可解析
- [ ] code trace、result identity 與 spec 一致
- [ ] review verdict pin 現有 claim surface
- [ ] knowledge 已由 main thread canonical writer/K1259 寫入並回讀
- [ ] artifact checker 與 methodology gates 通過
