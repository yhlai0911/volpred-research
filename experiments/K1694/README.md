# K1694 — FCM 清算集中度與商品小型交易人的高波動排擠

## 狀態：round 2 審查中（重跑於 2026-07-29）

Codex primary-path review round 1 判 **FAIL**（全文 `storage/ops/codex_reviews/k1694_verdict.md`）。
本目錄已依裁決的「最低修復要求」逐項修好並**重跑正式 artifacts**，等 round 2 裁決。

**在 `review_verdict.json` 出現 PASS 之前**：不得寫進 `storage/memory/knowledge.json`、不得據此
寫文章或論文段落。下面的數字是重跑後的真實輸出，但**認證未完成**。

## 結論（NULL，口徑要看清楚）

**NULL 只涵蓋一個假說：負向、二元 high-vol 的排擠效果不成立。**
它**不是**「FCM 集中度與小型交易人部位完全沒有關聯」。

| spec | 交互項 | n | coef | t_DK | t_cluster |
|---|---|---|---|---|---|
| spec1（主）FCM HHI × high-vol（二元） | `fcm_x_highvol` | 3278 | **+3.158e-04** | +1.56 | +1.60 |
| spec2 FCM HHI × rv_z（連續） | `fcm_x_rvz` | 3278 | **+2.962e-04** | **+2.59** | **+2.61** |
| spec3 trader conc4 × high-vol | `conc4_x_highvol` | 3278 | −1.702e-04 | −0.67 | −0.67 |
| spec4 全落後 predictive | `fcm_pre_x_highvol_lag` | 2750 | +4.415e-05 | +0.18 | +0.22 |

- 主 spec 的點估計**是正的**（排擠假說預測為負），且不顯著。
- 連續型 spec2 **正向且顯著**（p_DK = 0.010）——方向與排擠假說**相反**。所以正確的敘述是
  「沒有證據支持排擠；若有訊號，方向是小型交易人在高集中度高波動月份**佔比上升**」，
  不能寫成「完全沒有關聯」。
- 描述統計同一方向：high-HHI × high-vol 格的 Δ 非報告部位佔比平均 **+2.76 bp**，
  其餘三格皆為負（−1.74 / −4.83 / −3.06 bp）。
- spec4（唯一能講 predictive 的規格）幾乎是零（t = 0.18）：**沒有可預測性**。

| 檢定 | 值 |
|---|---|
| stationary block bootstrap（by month, 平均 block 6 個月, 2000 reps） | point 3.158e-04, 95% CI [−7.08e-05, 7.79e-04], p = 0.117 |
| IID month-cluster bootstrap（對照, 2000 reps） | point 3.158e-04, 95% CI [−6.77e-05, 7.11e-04], p = 0.119 |
| DK bandwidth 1..24 敏感度 | \|t\| ∈ [1.56, 1.71]，**無一點達 1.96** |
| 時間序列 aggregate `hhi_x_volfrac` | coef 4.34e-04, t 0.41（HAC lag 6, resid acf1 −0.045, 149 個月） |
| FCM 發布 lag 30/45/60/75/90 天 | t_DK ∈ [1.28, 1.56]，**無一點達 1.96**（`K1694_lag_sensitivity.json`） |

樣本：**3278 列 / 22 商品 / 2014-02..2026-06**（149 個月），皆為完整月份。

**claim 型別：ex-post association。** spec1–3 **不可**被描述為 predictive / causal /
known-before-outcome —— 理由見下方「timing」。只有 spec4 的時序安排允許 predictive 字眼。

## round 1 的 8 項缺陷，逐項修復對照

| # | Codex 裁決指出的缺陷 | 修復 | 可驗證證據 |
|---|---|---|---|
| 1 | bootstrap 估的不是 spec1（RHS 少 `t`、樣本 3300 vs 3293、`highvol` 錯標） | 抽出 `build_spec_frame()` 當**估計樣本的唯一 owner**；`SPEC1_RHS` 為模組常數；panel 迴歸與兩個 bootstrap 都吃同一份 frame 與同一份 RHS | `results.primary_interaction.bootstrap_matches_spec1_sample_and_rhs = true`；bootstrap `n_rows` 3278 = spec1 `n_obs` 3278；`test_bootstrap_shares_spec1_design_matrix` |
| 2 | `(s > s.median())` 讓缺 RV 的列 `highvol` 錯標成 0 | 改 `s.gt(s.median()).astype(float).where(s.notna())` | 全 panel `rv` 缺值 45 列、`highvol` 缺值 45 列，交集錯標 0 列；`test_highvol_is_nan_when_rv_is_missing` |
| 3 | 現行是 IID month-cluster，卻叫 block bootstrap | **兩個都做、都誠實命名**：headline 改為 **stationary block bootstrap**（Politis–Romano，幾何長度、循環接續，保留月間序列相關）；原 IID 版保留為對照，標成 `month_cluster_iid` 並在 label 明寫 "NOT a block bootstrap" | `results.bootstrap_spec1.headline = "stationary_block_by_month"`；`preserves_serial_correlation` 兩者分別 true/false；`test_bootstrap_names_are_honest` |
| 4 | partial month 2026-07 未排除也未揭露 | `monthly_coverage()` 是完整性規則的**唯一 owner**，**不寫死日期**：DCOT 月需 ≥4 份週報且最後一份 as-of 距月底 ≤6 天；RV 月需 ≥15 個交易日。另加**相鄰性檢查**，跨被剔除月份的差分一律作廢 | `results.sample.completeness`（規則 + 被剔除月份清單 + `date_hardcoded: false`）；剔除 2026-07（1 週 DCOT、tail gap 24 天）與 2006-06（3 週）；`panel_span` 收到 2026-06 |
| 5a | `_acf_bandwidth()` 沒讀 resid，卻宣稱由 residual ACF 決定 | 更名 `_hac_bandwidth_rule(nmonths)`，移除假的 `resid` 參數，文件與 results 明寫「fixed rule, not ACF-derived」；另補 **DK bandwidth 1..24 敏感度**讓選擇可查 | `results.panel_regressions._hac_bandwidth_rule`；`results.dk_bandwidth_sensitivity_spec1`；`test_bandwidth_rule_is_named_for_what_it_computes` |
| 5b | 檔頭宣稱「另附全落後 predictive spec」但實際沒有 | **補上 spec4**：FCM 報表改以**月初**做 as-of 合併（訊號在 outcome 月開始前就可得）、regime label 改用 point-in-time expanding 動差、所有控制變數落後一期 | `spec4_predictive_fully_lagged`；`test_predictive_spec_signal_precedes_the_outcome_window`（0 列違反） |
| 6 | results JSON 過度陳述（冒充 CI、`panel_span` 含 partial、limitations 漏列、timing 用語） | `bootstrap_interaction_spec1` / `primary_interaction.bootstrap_ci95` 兩個舊 key **刪除**，改成具名的 `stationary_block_bootstrap_ci95` / `month_cluster_iid_bootstrap_ci95`；新增 `claim_type: ex_post_association` 與 `claim_language_rule`；limitations 補上 synthetic publication dates、月內 timing overlap、full-sample regime labels、IID bootstrap 不保留序列相關 | `test_no_stale_bootstrap_key_impersonating_a_spec1_ci`、`test_limitations_cover_every_disclosure_codex_named`、`test_results_do_not_claim_prediction_for_the_association_specs` |
| 7 | NULL 口徑過寬 | `verdict_scope` 明寫「限於負向二元假說；連續型 spec2 正向且顯著」；`secondary_findings` 帶出 spec2 的係數與 t 值 | `test_null_is_scoped_and_names_the_positive_continuous_result` |
| 8 | 缺 run-time `reproduce_spec.json` | 收尾改用 `volpred.research.reproduce_spec.finalize_experiment()`，results 與 spec 由**同一次 `trace_file()`** 寫出 | spec `entrypoint.sha256` = results `code_trace.sha256` = 磁碟上 `K1694.py` 的 sha；`test_reproduce_spec_pins_the_bytes_that_ran` |

`uv run --active python -m pytest experiments/K1694/test_K1694.py -q` → **23 passed**。

### 與 task 摘要的差異（以裁決原文為準）

task 描述把缺陷列成 8 點，裁決原文分成 4 節。兩者實質一致，唯一要點名的差別是：裁決原文
把「`_acf_bandwidth` 誤述」與「檔頭 predictive spec 不存在」放在不同節（§3 與 §4），
task 摘要合成一條第 5 點。本 README 拆回 5a / 5b 逐項對照。

## timing：為什麼只能講 association

`merge_asof(direction="backward")` 的方向是對的（0 列用到 outcome 月底之後才可得的報表），
但**方向正確 ≠ 訊號早於結果**：

- `FCM_LAG_DAYS = 45` 是**合成常數**，不是查證過的 CFTC 發布日；離線快取沒有發布日欄位。
- outcome `d_nonrep` 是整月 DCOT 平均相對前月的變化，而 FCM 的假設可得日通常落在 outcome
  **月中** —— 估計樣本 **3278 / 3278 列**都是這種情形（`data_provenance.fcm_avail_inside_outcome_month_rows`）。
  所以部分 outcome 視窗發生在訊號可得之前。
- 30–90 天的 lag 網格只證明結果對不同**合成** vintage 位移不敏感，不等於核對過真實發布日。

想講「訊號在 outcome 開始前就已可得」只有 spec4 做得到（月初 as-of + PIT label + 全落後控制），
而 spec4 的結果是 **t = 0.18**。

## 這次重跑相對 round 1 的數字變化

| | round 1（FAIL） | 本次 |
|---|---|---|
| spec1 樣本 | 3293 | 3278（−15 = 被剔除的 partial month 2026-07 的可用列） |
| spec1 coef / t_DK | 3.146e-04 / 1.55 | 3.158e-04 / 1.56 |
| headline CI 出處 | 另一個規格（少 `t`、多 7 列） | spec1 本身 |
| CI | [−2.72e-05, 7.47e-04]（不可比） | [−7.08e-05, 7.79e-04]（stationary block） |

係數幾乎沒動 —— 這正是重點：**round 1 的 FAIL 不是因為結論錯，是因為那個 CI 不屬於被報告的
係數**。修好之後 NULL 仍然是 NULL，而且 bootstrap 現在保留了月間序列相關（CI 因此略寬）。

## 檔案

| 檔案 | 說明 |
|---|---|
| `K1694.py` | 分析腳本（唯一 compute path） |
| `test_K1694.py` | 8 項缺陷的機械 gate（23 tests） |
| `lag_sensitivity.py` | FCM 發布 lag 敏感度 |
| `K1694_results.json` | 主結果 |
| `reproduce_spec.json` | **run-time 產出**，與 results 同一次 `trace_file()` |
| `K1694_lag_sensitivity.json` | lag 網格 |
| `figures/fig1_fcm_hhi_timeseries.png` | FCM HHI / CR4 時序 |
| `figures/fig2_regime_2x2.png` | 2×2 regime 對照 |
| `figures/fig3_interaction_coef.png` | 四個 spec 的交互項係數 + bootstrap CI |
| `data/fcm_monthly.csv` | CFTC FCM customer-segregated assets 月頻（150 列） |
| `data/dcot_weekly.csv` | DCOT 週頻部位（23,056 列） |
| `data/rv_monthly.csv` | 已實現波動率月頻（5,643 列） |
| `data/panel.csv` | 組完的 panel（中間產物） |

重跑：`cd experiments/K1694 && uv run --active python K1694.py`（走 `data/` 快取，不連網），
再 `uv run --active python lag_sensitivity.py`。

## 還缺什麼

1. ~~跑通 `K1694.py`~~ ✅
2. ~~Codex primary-path review round 1~~ ✅ → FAIL
3. ~~依裁決修復 8 項缺陷 + 重跑正式 artifacts~~ ✅（本次）
4. Codex round 2 裁決 → `review_verdict.json`
5. round 2 PASS 後才由**主線程**寫 knowledge entry（agent 不得寫 `knowledge.json`）
6. 真正核對 CFTC FCM 月報的實際上線日期（本班無法離線完成；目前只有合成 lag + 敏感度）

## 歷史：搶救經過（2026-07-19）

- 2026-07-15 09:22 台北：`K1692_K1694_starvation_dispatch` 走 compute_queue 派出 K1692/K1694。
- **K1694 的 agent 沒有跑完**，只留下腳本與已抓好的資料，在 worktree 裡閒置 99 小時。
- task pool 中 `K1694` 的 status 是 `succeeded`，但 `result` 是 `null` —— 那個 succeeded 指
  「**派工**成功」而非實驗成功。這是狀態語意陷阱，不是實驗已完成的證據。
- 2026-07-29 修好三個讓腳本跑不動的缺陷（`.dt.normalize()`、Period 時間索引、bootstrap 的
  字串月份標籤讓每個 replicate 都靜默 NaN）後首次產出結果 → 送 Codex → FAIL → 本次修復。
  **改動越是讓結果從無到有，越需要外部審**：那次讓 bootstrap「活起來」的修正，活起來估的
  卻不是 spec1。
