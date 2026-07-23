# K1731 F1：pinball loss 的 nested-forecast bootstrap，重建 macro 效果的正式界

**Model**: opus / xhigh (per model_router, task_type=experiment)
**Task id**: `k1731_F1_nested_forecast_bootstrap` (P2, starved 53.9h)
**Worktree / cwd**: `.claude/worktrees/dispatch-slot-1-bd00f90a-k1731`（已存在，branch `wt/dispatch-slot-1-bd00f90a-k1731`）

## 為什麼

K1731 arm B rev6 把「bounded macro null」宣稱**撤回**了（route b）。理由：

- SSVS vs GEV-HAR 是**嵌套比較** —— `k1731_gevreg_midas_ssvs_returns.py:163` 用 coefficient
  mask `active[n_beta-n_macro:]=0.0` 建 GEV-HAR
- 且用 **expanding window**（`:129`），關掉 Giacomini-White (2006) 的例外門
- → West (1996) / Clark-McCracken (2001) 適用，**DM 統計量非漸近常態**，HAC 區間撐不起
  母體效果的界

目前 `[-0.74%, +4.41%]` **只是實現損失差的敘述性摘要**，不是母體界。

## 目標

實作對 **pinball loss** 有效的 recursive-bootstrap / nested-forecast 校正，重建區間，
讓 macro null 有正式界。

⚠️ **Clark-West 是為二次損失推的，不可直接套到 pinball。** 這是本任務的技術核心 ——
要找到（或推導出）適用於 general loss 的 nested-forecast 推論方法，並寫清文獻出處。

## 必走 compute_queue

需在 **19 次年度 refit 的 Bayesian MCMC** 上做 bootstrap 重抽 = heavy compute。
**禁止塞進 hourly fire。** 你要做的是：實作 + 小規模驗證通過後，把全量 bootstrap
`compute_queue.py enqueue` 出去（單一 artifact、明確 success criterion、timeout 合理）。

## 注意 bias 方向（做完要能回答這件事）

虛無下大模型仍估 macro 係數（純噪音）→ 抬高其 OOS 損失，把統計量推向「macro 較差」
（Clark-West 2007）。**觀察到的 t=+1.39 正是真虛無會機械產生的方向**，所以生統計量無法
區分「macro 無用」與「macro 微幅有用但被估計噪音蓋掉」。

但 rev6 也誠實記下**反向弱點**：大模型是 SSVS 後驗混合而非無限制 MLE，spike-and-slab
收縮讓機械懲罰衰減，故失真可能**小於**無限制 MLE 情形。

→ 你的校正必須把這兩個方向都納入討論，不能只做單向修正就宣稱解決。

## 阻擋

任何論文層級「macro null 有界」的宣稱，在本任務落地前都不得寫入。

## 成功判準

1. 產出**可回溯的區間**（method + 隨機種子 + artifact 路徑）
2. **方法出處**（文獻引用 —— general-loss nested forecast 推論的正式依據）
3. 與**現有診斷區間的並列對照**表（舊 `[-0.74%, +4.41%]` vs 新正式界，並說明差異來源）
4. `uv run python scripts/experiment_gates.py run --path experiments/k1731` 綠燈

## 禁令

- **knowledge.json 由主線程寫，agent 禁寫**（K1259）
- 禁 force push、禁 `--no-verify`、禁假數字
- 若最後發現 pinball 的正式界在現有樣本下**撐不起任何結論**，照實寫「撤回並說明為何撤回」
  —— 這是可接受且有價值的產出，**不要為了交差硬湊一個區間**
