VERDICT: CONDITIONAL PASS

核心 remediation 與樣本 realignment 通過；沒有實證翻案。尚不能正式放行的原因是 reader-facing claim、語意欄位與 certification artifacts 未收乾淨。

## 1. 樣本對齊

裁決：已修好。

K1257 以 BMA ∩ Equal ∩ GJR-t 建立 `common_mask`，headline 三個均值共用該 mask；regime QLIKE 亦使用 `mask & common_mask`：[k1257_bma_volatility.py](/Users/yhlai0911/volpred-research/experiments/k1257/k1257_bma_volatility.py:675)、[同檔](/Users/yhlai0911/volpred-research/experiments/k1257/k1257_bma_volatility.py:706)。

我由 [forecasts_SPY.parquet](/Users/yhlai0911/volpred-research/experiments/k1258/forecasts_SPY.parquet) 的六模型逐日 variance 與 log-likelihood，獨立重建 absorbing standard-BMA：

- `n_oos = 1581`
- `n_common_sample = 1518`
- BMA = `-8.186392692633385`
- Equal = `-8.166751026857440`
- GJR-t = `-8.135790746830748`
- BMA own-sample = `-8.227435956662777 @ 1581`

逐位吻合 [k1257_results.json](/Users/yhlai0911/volpred-research/experiments/k1257/k1257_results.json:25)。

Regime 亦逐值吻合：

| Regime | n_common | BMA | GJR-t | Equal |
|---|---:|---:|---:|---:|
| VIX<15 | 236 | -9.14957509 | -9.08549796 | -9.10248640 |
| 15–20 | 579 | -8.86338187 | -8.85428711 | -8.84774877 |
| 20–25 | 355 | -7.98861447 | -7.94740096 | -7.97340901 |
| >25 | 348 | -6.60858663 | -6.48848638 | -6.59636360 |

Artifact 證據見 [k1257_results.json](/Users/yhlai0911/volpred-research/experiments/k1257/k1257_results.json:99)。

## 2. DM 是否曾受樣本錯配污染

裁決：樣本錯配只污染舊 headline，不污染 DM verdict。

`dm_harvey` 先形成逐日 `d = loss1-loss2`，再用 `np.isfinite(d)` 取共同有效日：[k1257_bma_volatility.py](/Users/yhlai0911/volpred-research/experiments/k1257/k1257_bma_volatility.py:641)。K1258 相同：[k1258_forgetting_factor_bma.py](/Users/yhlai0911/volpred-research/experiments/k1258/k1258_forgetting_factor_bma.py:656)。

須精確區分：

- 報告層 sample mismatch 從未改變 DM 的樣本。
- 原本 MAJOR-1/2 確實改變過 DM 的底層 forecast/loss：SPY t 從 `-3.39750` 變成 `-3.17394`，但仍越過 `|t|>3`。
- 所以 H1 PARTIAL / H2 FAIL / H3 FAIL 未翻案，[結果檔](/Users/yhlai0911/volpred-research/experiments/k1257/k1257_results.json:497)正確。

## 3. `-inf` absorbing state

裁決：本次 archived 結果不強制改成可復活 posterior；K1257 的揭露足以支持當前結論，但兩實驗的機器可讀語意仍需補齊。

K1257 以 `next_log_weights=-inf` 且只更新 valid support，故模型恢復後仍有 `-inf + lp = -inf`：[k1257_bma_volatility.py](/Users/yhlai0911/volpred-research/experiments/k1257/k1257_bma_volatility.py:592)。JSON 已明載 absorbing 語意：[k1257_results.json](/Users/yhlai0911/volpred-research/experiments/k1257/k1257_results.json:47)。

我獨立算得 2024-04-05 drop 前 GJR-t 權重為 `3.0421e-06`。另以「任一模型缺失時暫停 posterior update，恢復後沿用最後共同 posterior」做敏感度重算：

- common BMA：`-8.18639269` → `-8.18639198`
- DM t：`-3.17393865` → `-3.17394360`

差異約 `7.1e-7` 與 `5e-6`，完全不影響 verdict。因此沒有必要只為改復活語意重跑主結論。

但 K1258 的 `log_floor=-700` 會讓 `-inf` 在後續更新重新成為極小有限權重：[k1258_forgetting_factor_bma.py](/Users/yhlai0911/volpred-research/experiments/k1258/k1258_forgetting_factor_bma.py:613)。SPY λ=1 GJR-t 為 `8.467e-305`：[k1258_results.json](/Users/yhlai0911/volpred-research/experiments/k1258/k1258_results.json:58)。K1258 尚缺對應 `posterior_semantics`／drop-cause 欄位。

## 4. README ↔ JSON

裁決：主要結果表正確，但既有 debt 只部分修完。

- K1257 的 6 models、`HAR_ABS`、`A4f_IV2`、GLD `^GVZ`：已修，見 [README](/Users/yhlai0911/volpred-research/experiments/k1257/README.md:25)。
- Realized GARCH 未實作：已揭露。
- 但底部仍殘留「7 model × 2520」與等待執行的舊 spec 文字：[README](/Users/yhlai0911/volpred-research/experiments/k1257/README.md:178)。
- 「約 500 天集中」：未修，仍無 effective-number／hitting-time 指標：[README](/Users/yhlai0911/volpred-research/experiments/k1257/README.md:122)。
- K1257 headline 表與 own-sample 數字均吻合 JSON；但 README runtime `343.8s` 與目前 artifact `369.6s` 不符：[README](/Users/yhlai0911/volpred-research/experiments/k1257/README.md:4)、[JSON](/Users/yhlai0911/volpred-research/experiments/k1257/k1257_results.json:503)。
- K1258 family-level 過度外推：主要段落已修成 scoped claim，[README](/Users/yhlai0911/volpred-research/experiments/k1258/README.md:112)；但末段仍稱 FAIL 可告訴社群「別花更多時間在 BMA family」，所以是部分修復，不是已完全修復：[README](/Users/yhlai0911/volpred-research/experiments/k1258/README.md:152)。
- K1258 README 的 Harvey 範圍「+1.3 至 +2.66」不符 JSON；實際 SPY/GLD 範圍為 `+0.207` 至 `+2.659`。
- SPY λ=.90 switch frequency 現為 `19.81%`，README `19.9%` 是 remediation 前數字：[JSON](/Users/yhlai0911/volpred-research/experiments/k1258/k1258_results.json:204)。
- 「λ=1 QLIKE 與 K1257 byte-identical」僅對 K1257 `qlike_own_sample` 成立；SPY 現行 K1257 headline 是 common-sample `-8.18639`，不能再無限定地寫 byte-identical：[README](/Users/yhlai0911/volpred-research/experiments/k1258/README.md:107)。
- H4 已正確改成 `RECOMMENDATION`，不是偽 PASS/FAIL：[k1258_results.json](/Users/yhlai0911/volpred-research/experiments/k1258/k1258_results.json:773)。

## 5. 「結論沒變」是否可信

裁決：可信，且足以排除「新分支根本沒跑到」。

獨立比較 remediation 前後：

- SPY GJR-t QLIKE：`-8.17485278 → -8.13579075`，Δ=`+0.03906203`
- SPY DM t：`-3.39749670 → -3.17393865`，Δ=`+0.22355804`
- SPY GJR-t final weight：`1.80335e-09 → 0.0`
- SPY BMA own-sample 僅變 `-2.26e-08`
- GLD 全部實質 Δ=0
- 0050.TW 僅浮點 `1.1e-16`

此外 SPY artifact 明確記錄 26 次 fit、1 次 non-convergence、63 個 invalid days：[k1257_results.json](/Users/yhlai0911/volpred-research/experiments/k1257/k1257_results.json:152)。K1258 cache loader 只接受 `posterior_semantics_version==2` 且含 diagnostics：[k1258_forgetting_factor_bma.py](/Users/yhlai0911/volpred-research/experiments/k1258/k1258_forgetting_factor_bma.py:423)。

這些是新 branch 被實際觸發後才會產生的數值簽章，不是只改註解或 JSON schema。

## 額外裁決

- 多重比較：`|t|>3` 對約 1,500 日樣本相當於 two-sided `p≈0.0027`。K1257 三檢定與 K1258 十二 cells 均比 5% Bonferroni 門檻 `0.0167`／`0.00417` 更嚴；本輪 verdict 不受 multiplicity 影響。但 README 應明講這是 de-facto FWER 保護，或直接保存 `m` 與 adjusted threshold。
- `invalid_forecast_days` 與 `dropped_model_days` 在同一分支同步加一，確實完全重複：[k1257_bma_volatility.py](/Users/yhlai0911/volpred-research/experiments/k1257/k1257_bma_volatility.py:576)。應合併，或把後者改成 `drop_events`／`posterior_excluded_days`。
- 不應從 `final_weights==0` 推斷 drop cause。新增 `absorbing_dropped_models`、`ever_invalid_models` 或逐模型 `final_weight_status`；K1258 也應記錄 floor-revival 語意。
- K1258 H2 的程式實際檢驗 switch frequency ≥2×，不是「切換與 VIX regime 對齊」：[k1258_forgetting_factor_bma.py](/Users/yhlai0911/volpred-research/experiments/k1258/k1258_forgetting_factor_bma.py:885)。H2 PASS 可保留，但 README 應改稱「switching/deconcentration restored」，不能稱已證明 regime tracking。

## Blocking issues

- SEVERE：無。
- MAJOR：K1258 README 末段仍有 family-level 過度外推，且 H2 把 switching 說成 regime tracking。最小修復：限縮為本設計下的 descriptive switching result。
- MAJOR：兩目錄都缺 `review_verdict.json`；certification gate 明確判 uncertified：[experiment_gates.py](/Users/yhlai0911/volpred-research/scripts/experiment_gates.py:352)。兩者亦缺 `reproduce_spec.json`，artifact check 現在均為 BLOCKED。
- MINOR：上述 README stale 數字、執行日期/runtime、λ=1 byte-identical 限定與 K1257 殘留 7-model 文字。
- MINOR：重複 diagnostics、final-weight cause 無機器欄位、多重比較未明載。

## 放行最小條件

1. 修正 K1258 family-level／regime-tracking 過度宣稱，以及 README 的 stale 數字與 λ=1 own-sample 限定。
2. K1257 移除殘留 7-model／等待執行文字；將「約 500 天」標為圖示描述，或補正式 concentration hitting-time 指標。
3. 兩支結果加入明確 posterior/drop 狀態欄位；合併或重新定義重複 diagnostics。
4. README 明載 `|t|>3` 對 3／12 comparisons 的 multiplicity 含義。
5. 補兩個 `reproduce_spec.json`；固定最終 claim-surface bytes 後，重新產生 hash-bound `review_verdict.json` 並讓 certification/artifact gates 通過。

附註：本環境唯讀，targeted pytest 因 Matplotlib 無可寫 cache/temp directory 而未能啟動；parquet replay、JSON 重算與 gate 的唯讀檢查均已完成。
