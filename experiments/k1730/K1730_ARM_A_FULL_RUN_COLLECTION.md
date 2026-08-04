> **SUPERSEDED (2026-08-05)** — this collection memo records an EARLIER run's numbers
> (cov90=0.8501, DM t=1.998/p=0.046). Canonical numbers live ONLY in
> `k1730_gevreg_midas_ssvs_results.json` (cd931fbf lineage, runtime-spec rerun);
> see `RECONCILIATION_20260804.md`. Kept as historical record — do not cite.

# K1730 arm A — 全量 production 收件驗證

**收件時間**：2026-07-18 20:2x 台北
**Compute job**：`compute-k1730-arm-a-production-quick-mode-1784358686`（exit 0，09:15→10:02 UTC，47 分鐘）
**Artifact**：`k1730_gevreg_midas_ssvs_results.json`
**收件者**：`hourly-slot-1-60b14fa66918477594ecd98ef2540e3f`（主線程收件，非 agent 代寫）

## 1. 全量確認

`quick_mode = false` ✔（config：`n_starts=30`、`n_draws=40000`、`n_burnin=10000`、`thin=10`、`n_chains=2`、`n_pred_draws=500`）。
樣本 1,640 個週區塊（1995-02-06 → 2026-07-16），7,936 個日觀測，19 次 refit，OOS 共同樣本 967 週（2008-01-07 → 2026-07-13）。

## 2. Lookahead — 0 violations（三項全過）

| 檢查 | violations | n_checked |
|---|---|---|
| macro_released_before_origin | 0 | 118,080 |
| origin_before_block_start | 0 | 1,640 |
| blocks_non_overlapping | 0 | 1,639 |

GEV 數值驗證 `passed=true`，最大 logpdf 誤差 4.5e-13。

## 3. 全量 vs quick-mode：結論沒有翻轉

| 指標 | quick | full |
|---|---|---|
| GEVReg-MIDAS-SSVS mean pinball | 0.114193 | 0.114066 |
| 90% 區間實際覆蓋 | 0.8532 | 0.8501 |
| Kupiec UC p | 4.8e-06 | 1.2e-06 |
| DM vs GEV-HAR | t=2.130, p=0.033（favours benchmark） | t=1.998, p=0.046（favours benchmark） |

全量把 pinball 改善了 0.0001（第四位小數），方向與統計結論完全一致。**quick-mode 的「區間偏窄、Kupiec 拒絕」在全量下重現**。

## 4. 跨模型校準表（967 週 OOS）

| 模型 | cov90 | Kupiec90 p | cov95 | Kupiec95 p | width90 | mean pinball |
|---|---|---|---|---|---|---|
| GEVReg-MIDAS-SSVS | 0.8501 | 1.2e-06 | 0.9069 | 3.4e-08 | 2.428 | 0.11407 |
| GEV-HAR | 0.8625 | 2.1e-04 | 0.9111 | 4.9e-07 | 2.415 | 0.11224 |
| Gaussian-MIDAS | 0.8480 | 4.4e-07 | 0.9121 | 9.2e-07 | 2.322 | 0.11510 |
| HAR-QR | 0.8542 | 7.6e-06 | 0.9173 | 1.8e-05 | 2.347 | 0.11201 |
| Empirical | 0.8366 | 1.2e-09 | 0.9018 | 9.4e-10 | 3.353 | 0.16539 |

**所有五個模型的 Kupiec UC 都被拒絕** — 區間偏窄是這個 target（週最大 Parkinson RV 的對數）的共同性質，不是本模型特有的缺陷。
Christoffersen independence 對本模型不拒絕（p=0.73），所以問題是**無條件寬度**不是**叢聚**。

## 5. 主結論：NULL（macro 無增量價值）

- DM vs GEV-HAR：**favours benchmark**（p=0.046；Harvey 校正後不顯著）。
- DM vs HAR-QR：favours benchmark（p=0.076）。
- 只贏 Empirical（p<1e-8）與 Gaussian-MIDAS（不顯著）。
- **[RETRACTED — v1 宣稱的「permutation test 決定性」已撤回]** v1 用全樣本 shuffle 破壞了 macro 張量的時序結構，且把較晚的 release 放到較早的 origin 前面，本身就漏未來資訊，不能當成 leakage falsifier。v2 改用 non-circular lag-shift placebo（lags [52, 104, 156, 208, 260] 週，每個 arm 共同丟掉開頭 260 個 block，1380 blocks matched）：real=0.11415、placebo 區間 [0.11245, 0.11471]、4/5 個 placebo arm 不輸給 real → one-sided p=0.833。這是**粗解析度的 placebo 佐證，不是 permutation test**（5 shifts 的 p 值下限 0.167），只能佐證 NULL，不足以支撐任何正面結論。
- SSVS 的 PIP 一律為 **diagnostic-only（inference_tier = `diagnostic_only`）**：鏈未充分混合（worst R-hat 1.107、min ESS 41.93350252336614、worst |Geweke z| 28.05），因此樣本內「選了哪些 macro」只能當診斷訊號，不可讀成後驗機率，也不再作為 NULL 的支撐證據。

即：point-in-time 月頻總經資料對 SPY 週最大 RV 的區間預測沒有可偵測的增量資訊；模型複雜度只帶來一點點損失。

## 6. 必須如實記錄的限制

- **SSVS MCMC 沒有收斂**：worst R-hat = 1.61、min ESS = 6.25、worst |Geweke z| = 49.3。PIP 數字要當作粗略指標，不可當成穩健的後驗機率。
- **[RETRACTED — v1 宣稱的「似然面多峰」已撤回]** v1 把低收斂率讀成似然面形狀，實際上那是「常數 1e10 外部懲罰 + 過寬隨機起點」造成的起點可行性假象。v2 改用平滑外部懲罰後：mean feasible-start rate 0.60（起點盒子的性質）、mean feasible-optimum rate 0.986、mean basin concentration 0.918（min 0.867）。Hessian 全部正定、條件數 ≤ 1.8e+04、Nelder-Mead 追加改善 1.6e-09。最佳解是穩的，且**本實驗不對似然面形狀作任何主張**。
- xi 估計範圍 [-0.140, -0.095]（Weibull 域，有界上尾）。

以上限制使「NULL」的強度打折的方向是**保守的**：估計品質再好，最多只是讓本模型更接近而非超越 benchmark。佐證來自 lag-shift placebo，且該 placebo 只有粗解析度——NULL 的依據是 OOS 損失與 DM 檢定，placebo 只是佐證。

## 7. 尚未完成（另立 followup）

- Codex 代碼審 `k1730_models.py` 的 GEV MLE 與 SSVS 實作（本班 fire 內禁止 spawn codex exec；已另立 task）。
