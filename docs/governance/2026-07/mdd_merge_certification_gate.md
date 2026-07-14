# MDD scale-artifact merge gate：K1695 根因與修復邊界

- 日期：2026-07-15
- 任務：`gate_experiments_must_use_compare_max_drawdown`
- Enforcement owner：`scripts/audit_mdd_scale_artifact.py` +
  `scripts/tests/test_mdd_scale_artifact_ratchet.py`

## 結論

K1695 的時間線必須精確描述：實驗 commit `a20099d99`（2026-07-12 14:45）早於
MDD class sweep / auditor / baseline `a3858edbe`（2026-07-13 08:17），也早於
`experiment_gates.py` 與 compute-queue choke point `1f6097af4`（2026-07-14 13:20）。
因此 K1695 交件當下不是「auditor 有跑漏掉」，而是 auditor 與 runner gate 尚不存在；隔日
sweep 才把它的 5 個 production scopes 與 1 個 test scope 辨識成 `RAW_COMPARISON`，並隨
455-site population 一起凍入 legacy baseline。

修復前仍存在的現役缺口是另一件事：compute queue 已在完成前執行
`experiment_gates.py run`，但 worktree merge 只執行 stdlib-only 的 `certify`；後者只驗
reviewer PASS 與 claim-surface SHA，完全不跑 MDD methodology gate。非 compute-queue 路徑
因此仍可帶著 byte-valid PASS receipt 合併新的 naked raw-MDD claim。

## 修復

`certify` 現在從 trusted main checkout 重用唯一 MDD auditor 與 main baseline：

1. candidate worktree 的絕對路徑先正規化成 `experiments/<kid>/...::scope`；
2. `RAW_COMPARISON` / `UNKNOWN` 若不在 frozen baseline，與 review-certification violation
   一起令 `certify` exit 1；
3. candidate 自帶的假 gate 或自增 baseline 不具授權力；
4. `retired` site 不再被通用 baseline walker 誤收成 frozen debt；
5. MDD owner 本身只用 stdlib，故 bare `python3 -I -S ... certify` 的 merge contract 保留。

Regression fixture 固定 K1695 的 reader-facing raw claim 形狀：平均 raw MDD 改善
`+12.6138795804pp`、`13/13` 市場為正、VT/BH realized-vol ratio 約 `0.65`。搬到未凍結的
K path，即使 review receipt 完整且 SHA 全吻合，`certify` 仍必須以
`mdd-scale-artifact / RAW_COMPARISON` 阻擋；改用 canonical helper並輸出
`exposure_mismatch` / `exposure_matched_gap` 則可通過這一層靜態 gate。

## 不過度宣稱

這個 gate 禁止的是「新增 naked raw comparison」，不是逐字強制每個實驗 import helper。
既有 auditor 也接受能讓 scale/exposure 問題可被檢查的等價 companion。靜態 PASS 不證明
兩序列 realized vol 已低於 20% mismatch threshold，更不證明 positive matched gap 是擇時
能力；後者仍需自己的 phase/randomization null。

K1695 數據更正、primary CI / decision 重算、README/results/figure 改寫、paper Table 5 與
文章處置皆屬獨立任務。本 gate 沒有重跑 K1695，也沒有把現有同曝險約 `-0.87pp / 7-of-13`
描述成統計顯著。

## 已知靜態邊界

- Baseline 目前綁 `file::scope`，不是內容 hash；既有 baselined scope 的 on-touch
  re-adjudication 仍是後續可加強項。
- Auditor 是保守 lexical classifier；本次沒有把它升級成完整 data-flow analyzer。
- 直接繞過正式 worktree merge 的手動 git 操作不由 `certify` 本身攔截；repo-wide ratchet / CI
  仍是第二道防線。正式流程必須走 `scripts/merge_worktree.sh`。
