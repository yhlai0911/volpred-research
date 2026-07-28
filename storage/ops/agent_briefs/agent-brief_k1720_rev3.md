# K1720 rev3 — Codex round-2 的兩項 NOT_RESOLVED 定向修正

## 裁決來源

`storage/ops/codex_reviews/k1720_r2_verdict.md` → **VERDICT: FAIL**
（job `compute-k1720-rev2-codex-round-2-review-1785248465`）。

**先講清楚範圍**：round 2 判 **R2 / R3 / R4 已 RESOLVED**，且 lookahead、rev1→rev2 數值變動、
NULL 決策樹**全部通過**。只剩兩項，都很窄。**不要重做已經過關的部分，不要動統計內容。**

Worktree：`/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-87c7269d-k1720`

## R1 — NOT_RESOLVED：11:30 whitelist 沒有對照官方半日清單

位置：`K1720.py:120-126, 193-208`。

rev2 的作法是「最後一根 bar 起於 15:30 或 11:30 才算 observed close」。Codex 指出漏洞：
**正常交易日若在 11:30 之後斷檔，一樣會被當成合法收盤**，因為程式只看 bar 起始時間、
不看那天是不是真的提早收市。

Codex 同時說明：**對目前這份固定資料，那 8 個日期是完整的** —— 也就是說
**現有數字沒有錯**，這是穩健性/設計缺陷，不是結果缺陷。修它是為了讓 panel 建構在換資料、
延長樣本時不會靜默出錯。

要求：讓 11:30 收盤只在**該日確實是官方 early-close** 時才成立。
- 用明確的 early-close 日期集合（NYSE/Nasdaq 半日：感恩節翌日、聖誕夜、7/3 或獨立日前夕等），
  以常數表或既有行事曆來源實作，**寫死在程式裡要附來源註解**。
- 若某日最後一根 bar 起於 11:30 但**不在** early-close 集合 → 那是資料斷檔，
  **不得當成收盤**，該日應排除並計入既有的 `non_7bar_sessions_excluded` 或新增明確欄位。
- 重跑後 `sample_provenance` 與那 8 個 `prev_close_changed_days` 若有變動，照實更新；
  **若數字完全沒變（Codex 預期如此），也要在 report 裡明說「驗證後 8 日期不變」**，
  不要默默通過。

## R5 — NOT_RESOLVED：`~3 years` 仍是硬編

位置：`K1720.py:687-688`，在 verdict rationale 字串裡：

```
"the day's move is detected in the last hour. At 1h resolution, on ~3 years of "
```

R5 的整個重點就是「樣本敘述必須 run-time 從 panel 產生，不能漂移」。rev2 把
`sample_provenance` 與 power limitation 字串做成 run-time 格式化，**但漏了 verdict rationale
這一條**。`sample_provenance.per_underlying.*.span_years` 實際是 **2.9**。

要求：把該字串改為從 `sample_provenance` run-time 格式化（與既有 limitation 字串同一套作法），
並**掃過整份 `K1720.py` 與 `README.md`**，確認沒有其他硬編的樣本敘述
（`~3 years` / `~2 years` / `~500 sessions` / 年數 / session 數 任何一種寫法）。

## 收尾

- 修改後 `K1720.py` bytes 會變 → **必須用 run-time `finalize_experiment()` 重出
  `reproduce_spec.json` 與 results**，讓 `code_trace` 的 sha/size 與磁碟一致
  （目前三者一致為 `bf431b7b…` / 52,614 B，不要修完留下漂移）。
- README 每個數字仍要對得上其引用的 JSON 路徑。
- commit worktree。

## 產出契約

寫 `experiments/K1720/k1720_rev3_report.json`：

- `r1_fix`：early-close 集合的來源與內容、判定邏輯 before/after、重跑後
  `prev_close_changed_days` 與 `sample_provenance` 是否變動（沒變也要明寫）
- `r5_fix`：改成 run-time 格式化的位置清單、掃描到的其他硬編樣本敘述（沒有就寫 none）
- `numbers_moved`：任何統計量的變動；**若 R1 修正導致 session 數或統計量改變，
  逐項列出並說明**
- `spec_refresh`：新的 `code_trace` sha256/size，與 `reproduce_spec.entrypoint`、磁碟三方一致
- `status`：`READY_FOR_CODEX_ROUND_3` 或 `BLOCKED`

## 禁止

動 R2/R3/R4 已過關的統計內容；為了讓數字不變而跳過 R1 的實質判定；
merge（主線程的事）；寫 `knowledge.json`（K1259）；自行 enqueue Codex；force-remove worktree。

**Model**: opus / max (per model_router, experiment attempt 2)
