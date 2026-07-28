# K1694 — FCM 清算集中度與商品小型交易人的高波動排擠

## 狀態：round 4 審查中（重跑於 2026-07-29）

- **round 1 → FAIL**（`storage/ops/codex_reviews/k1694_verdict.md`）：8 項缺陷
- **round 2 → FAIL**（`k1694_verdict_round2.md`）：4 項要求
- **round 3 → FAIL**（`k1694_verdict_round3.md`）：3 項缺陷，其中一項是**具體反例**
- round 3 的 3 項缺陷已全部修完並再次重跑，等 round 4 裁決

**在 `review_verdict.json` 出現 PASS 之前**：不得寫進 `storage/memory/knowledge.json`、不得據此
寫文章或論文段落。下面的數字是重跑後的真實輸出，但**認證未完成**。

## 結論：NULL —— 意思是「未獲支持」，不是「不存在」

**這份實驗沒有任何 predictive / causal 的宣稱，也沒有「沒有可預測性」的宣稱。**
所有零結果一律寫「**未獲支持**」。本文的估計式無法證明效果不存在，只能說沒有支持它的證據。

**NULL 涵蓋的假說只有一個：負向、二元 high-vol 的排擠交互項未獲支持。**
它**不是**「FCM 集中度與小型交易人部位完全沒有關聯」。

| spec | 交互項 | n | coef | t_DK | t_cluster |
|---|---|---|---|---|---|
| spec1（主）FCM HHI × high-vol（二元） | `fcm_x_highvol` | 3275 | **+3.103e-04** | +1.53 | +1.57 |
| spec2 FCM HHI × rv_z（連續） | `fcm_x_rvz` | 3275 | **+2.880e-04** | **+2.55** | **+2.56** |
| spec3 trader conc4 × high-vol | `conc4_x_highvol` | 3275 | −1.934e-04 | −0.77 | −0.76 |
| spec4 時序收緊的落後規格 | `fcm_pre_x_highvol_lag` | 2748 | +6.752e-05 | +0.28 | +0.34 |

- 主 spec 的點估計**是正的**（排擠假說預測為負），且不顯著（p_DK = 0.126）。
- 連續型 spec2 **正向且顯著**（p_DK = 0.011）——方向與排擠假說**相反**。所以正確的敘述是
  「沒有證據支持排擠；若有訊號，方向是小型交易人在高集中度高波動月份**佔比上升**」。
- 描述統計同一方向：high-HHI × high-vol 格的 Δ 非報告部位佔比平均 **+2.76 bp**，
  其餘三格皆為負（−1.89 / −4.89 / −3.06 bp）。
- spec4 幾乎是零（t = 0.28）。這句話只能讀成「**此時序安排下未獲得關聯的支持**」，
  **不能**讀成「這個時序安排下沒有關聯」，更不能讀成「沒有可預測性」——
  理由見下方「spec4 能講什麼、不能講什麼」。

| 檢定 | 值 |
|---|---|
| stationary block bootstrap（by month, 平均 block 6 個月, 2000 reps） | 95% CI [−7.49e-05, 7.75e-04], p = 0.120 |
| IID month-cluster bootstrap（對照, 2000 reps） | 95% CI [−7.21e-05, 7.09e-04], p = 0.122 |
| DK bandwidth 1..24 敏感度 | \|t\| ∈ [1.53, 1.66]，**無一點達 1.96** |
| 時間序列 aggregate `hhi_x_volfrac` | t 0.33, p 0.739（HAC lag 6, resid acf1 −0.039, 149 個月） |
| FCM 發布 lag 30/45/60/75/90 天 | t_DK ∈ [1.25, 1.53]，**無一點達 1.96**（`K1694_lag_sensitivity.json`） |

樣本：**3275 列 / 22 商品 / 2014-02..2026-06**（149 個日曆月），皆為完整月份。
spec4 另有自己的樣本 2748 列。

### 有效時間自由度：149 個月**不是** 149 個獨立觀察

FCM HHI 是**單一系統層月度序列**，持續性極高：

| ACF(1) | ACF(3) | ACF(6) | ACF(12) |
|---|---|---|---|
| 0.964 | 0.918 | 0.817 | 0.584 |

所以「3275 列」的樣本量對主效果沒有意義，能用的時間資訊遠少於 149 個月。本實驗**沒有**量化
到底少到多少 —— 這是誠實邊界，不是已解決的問題。DK / month-cluster / block bootstrap 是防護，
不是證明。

## spec4 能講什麼、不能講什麼

spec4 把時序收緊到：

- FCM 報表以**月初**（不是月底）做 as-of 合併 → 訊號的假設可得日早於整個 outcome 視窗；
- 波動 regime label 用 **point-in-time expanding 動差**（RV 來自當日就公開的期貨收盤價，
  沒有發布落差），取 **t−1** 的標籤；
- DCOT 控制變數用 **t−2** 的月聚合 —— 因為 t−1 月**最後一份**週報的 as-of 是週二、週五才發布，
  可能落到 t 月的頭幾天，所以 t−1 的月聚合在 t 月開始前**還沒完全公開**；t−2 才是；
- 樣本由 spec4 **自己的** regressors 決定（`build_lagged_frame()`），不被 spec4 根本沒用到的
  同期 `rv_z` 篩選。

它**不能**講 predictive，因為 `FCM_LAG_DAYS = 45` 是**合成常數**：真實 CFTC 發布日一天都沒查過。
若真實落後大於 45 天，spec4 當成「月初已可得」的那份報表其實還沒出。所以 spec4 的 ex-ante 身分
是**條件式**的，它的零結果只能講「**此時序安排下未獲得關聯的支持**」——
不是「沒有關聯」，那會是一個這些估計式證明不了的存在性宣稱。

## Codex round 3 的 3 項缺陷，逐項修復對照

| # | round 3 缺陷 | 修復 | 可驗證證據 |
|---|---|---|---|
| I | **head completeness 有具體反例**：GOLD 2024-10 週報落在 1/8/15/22/29，刪掉 10/1 後 head gap 只有 7 天仍判 complete。根因是 head gap 從**月初**量起，而月初到第一個週二本來就可能是 0 天 | 不從月初量，改從**上一份週報**量（跨月界連續）。週報序列本來就全域連續，用全域連續性證明覆蓋，月界就不再是盲區。同一個反例現在的 gap 是 **14 天**。序列的第一個月沒有 entry gap → 永遠不可認證，直接剔除 | `test_completeness_rule_catches_a_skipped_week` 用 **5 個參數化案例**（含 Codex 的 GOLD 2024-10 原案）逐一刪掉第一週／中間週／最後一週；全域相鄰週報間隔實測只有 6/7/8 天三種值 |
| II | **RV 規則證明不了下載跑到月頭月尾**：全體商品共同短少 1–5 天時，business-day 缺口 ≤5、cross-sectional 缺口 = 0，照樣判 complete | 兩件事一起做：(a) `build_vol()` 現在會記錄每月**實際首末交易日**，任何重新產生的快取都會自動升級成真正的 endpoint 檢查；(b) 對只存計數的現有快取，加上**月層級的假日調整日曆 anchor**（美國聯邦假日 + Good Friday），抓得到「共同短少 ≥2 天」；(c) **抓不到的部分照實揭露**，不用規則假裝它不存在 | `test_completeness_rule_catches_a_truncation_common_to_every_commodity`（先斷言 cross-sectional 檢查在此情境確實失明，再斷言月層級 anchor 擋下）、`test_rv_endpoint_test_is_declared_unavailable_when_the_cache_lacks_dates`；`rule.rv_endpoint_test = "UNAVAILABLE for this cache..."`、`rule.rv_residual_blind_spot` |
| III | **仍有直接的 absence wording**：「這個時序安排下沒有關聯」/ "no association survives this timing"，與同一份 artifact 說的「estimators cannot establish absence」矛盾；另外 `fcm_avail_inside_outcome_month_rows` 算的是 `panel` 不是 `frame`，與 README 的 N/N 對不上 | 全部改成「此時序安排下**未獲得**關聯的支持」/ "an association is NOT SUPPORTED under this timing arrangement"；欄位改名 `..._in_estimation_sample` 並從 `frame` 計算，另附 `estimation_sample_rows` | `test_nothing_claims_absence_of_association`（掃 results 與 README 的宣稱段，且要求每個「沒有關聯」都在否定句裡）、`test_within_month_overlap_count_is_scoped_to_the_estimation_sample`（含 README 的 N/N 一致性） |

第 II 項的殘留盲區要講清楚：**全體商品共同短少「剛好 1 天」在只有計數的快取裡無法與計畫外
休市區分**。樣本內就有兩次真的計畫外休市（2012-10 桑迪颶風、2018-12 老布希國殤日），規則正確地
留下了它們。所以本實驗**不宣稱**「每筆下載都跑到該月頭尾」，只宣稱「日數與假日調整後的日曆
一致到 1 天以內」。

## Codex round 2 的 4 項要求，逐項修復對照

| # | round 2 要求 | 修復 | 可驗證證據 |
|---|---|---|---|
| A | spec4 的 predictive 宣稱過度：t−1 DCOT 控制變數在 t 月開始前未必已發布；樣本被 spec4 沒用到的 `rv_z` 篩選；發布日仍是合成的，撐不起「沒有可預測性」 | 控制變數全改 **t−2**（`nonrep_lag2` / `d_nonrep_lag2` / `dlog_oi_lag2`）；新增 `build_lagged_frame()` 用 spec4 自己的 regressors 決定樣本；spec 更名 `spec4_lagged_timing_hardened`；**全檔移除** predictive / no-predictability 宣稱 | `test_promised_lagged_spec_exists_and_is_timed_correctly`（t−1 控制變數被禁）、`test_lagged_frame_is_not_conditioned_on_a_regressor_it_does_not_use`、`test_no_spec_claims_prediction`、`test_nothing_claims_absence_of_predictability` |
| B | 「不成立」要改「未獲支持」；「149 個月的獨立 FCM 變異」是錯的 | 全檔零結果改「未獲支持 / NOT SUPPORTED」；新增 `sample.effective_temporal_dof`，報 ACF(1/3/6/12) 並明寫有效自由度**低於**日曆月數 | `test_null_is_worded_as_not_supported_not_as_disproved`（含 README 掃「不成立」）、`test_effective_temporal_dof_is_disclosed_not_asserted_independent` |
| C | `np.log(oi).diff()` 沒有 `oi > 0` / 有限值防護 | 先 mask 非正、非有限的 OI 再取 log，並把結果中殘留的非有限值清成 NaN；`oi_invalid` 計數寫進 results | `test_log_oi_has_a_positivity_guard`（含注入 0 與負值的負向案例）；`sample.oi_invalid_rows_guarded = 0` |
| D | 完整性規則證明不了全月覆蓋：5 份週報的月份可能中間漏一週；RV 也可能被獨立截斷 | DCOT 改**頭/中/尾三段連續性**檢查（首份距月初 ≤8 天、相鄰週報間隔 ≤9 天、末份距月底 ≤6 天）—— 任何被跳過的一週都會把某段 gap 撐到約 14 天；RV 改**三條件**（絕對 ≥15 天、相對該月營業日缺口 ≤5 天、相對同月其他商品缺口 ≤3 天） | `test_completeness_rule_catches_an_interior_weekly_gap`（實際刪掉 GOLD 2020-06 中間一週 → 該月被擋）、`test_completeness_rule_catches_an_independently_truncated_rv_month`、`test_completeness_rule_holds_on_every_retained_row` |

門檻是照本快取的實測分布訂的，留了假日位移的餘裕但擋得住整週缺漏：
interior gap 實測最大 8 天（假日位移），漏一週會是 14 天；head gap 實測最大 7 天；
RV 正常月缺口 0–2 天（假日重的月份最多 5），被截斷的月份是 10/11/13 天。

## Codex round 1 的 8 項缺陷，逐項修復對照

| # | round 1 缺陷 | 修復 | 可驗證證據 |
|---|---|---|---|
| 1 | bootstrap 估的不是 spec1（RHS 少 `t`、樣本 3300 vs 3293、`highvol` 錯標） | `build_spec_frame()` 當**估計樣本的唯一 owner**，`SPEC1_RHS` 為模組常數，panel 迴歸與兩個 bootstrap 都吃同一份；bootstrap 內用 `_within_ols()`，抽樣前先斷言它等於 PanelOLS 的 spec1 係數 | `primary_interaction.bootstrap_matches_spec1_sample_and_rhs = true`；bootstrap `n_rows` = spec1 `n_obs` = 3275；identity check 差 7.1e-19 |
| 2 | `(s > s.median())` 讓缺 RV 的列 `highvol` 錯標成 0 | 改 `s.gt(s.median()).astype(float).where(s.notna())` | `rv` 缺值列數 = `highvol` 缺值列數，交集錯標 0 列 |
| 3 | 現行是 IID month-cluster，卻叫 block bootstrap | **兩個都做、都誠實命名**：headline = **stationary block bootstrap**（Politis–Romano）；IID 版保留為對照，label 明寫 "NOT a block bootstrap" | `bootstrap_spec1.headline`；`preserves_serial_correlation` 分別 true/false |
| 4 | partial month 2026-07 未排除也未揭露 | `monthly_coverage()` 是完整性規則的唯一 owner，**不寫死日期**（round 2 又再收緊，見上表 D）；另加相鄰性檢查，跨被剔除月份的差分一律作廢 | `sample.completeness`（規則 + 被剔除月份 + `date_hardcoded: false`）；剔除 2026-07 與 2006-06 |
| 5a | `_acf_bandwidth()` 沒讀 resid 卻宣稱由 residual ACF 決定 | 更名 `_hac_bandwidth_rule(nmonths)`，移除假的 `resid` 參數，明寫 fixed rule；補 DK bandwidth 1..24 敏感度 | `panel_regressions._hac_bandwidth_rule`；`dk_bandwidth_sensitivity_spec1` |
| 5b | 檔頭宣稱有全落後 spec 但實際沒有 | 補上 spec4（round 2 又把它的時序與樣本再收緊，見上表 A） | `spec4_lagged_timing_hardened` |
| 6 | results JSON 過度陳述 | 冒充 CI 的兩個舊 key 刪除；`claim_type` / `claim_language_rule`；limitations 補齊 | `test_no_stale_bootstrap_key_impersonating_a_spec1_ci` 等 |
| 7 | NULL 口徑過寬 | `verdict_scope` + `secondary_findings` 帶出 spec2 的正向顯著結果 | `test_null_is_scoped_and_names_the_positive_continuous_result` |
| 8 | 缺 run-time `reproduce_spec.json` | 收尾改用 `finalize_experiment()`，results 與 spec 同一次 `trace_file()` | spec `entrypoint.sha256` = results `code_trace.sha256` = 磁碟 sha |

`uv run --active python -m pytest experiments/K1694/test_K1694.py -q` → **39 passed**。

## timing：為什麼 spec1–3 只能講 association

`merge_asof(direction="backward")` 的方向是對的（0 列用到 outcome 月底之後才可得的報表），
但**方向正確 ≠ 訊號早於結果**：

- `FCM_LAG_DAYS = 45` 是合成常數，不是查證過的 CFTC 發布日；離線快取沒有發布日欄位。
- outcome `d_nonrep` 是整月 DCOT 平均相對前月的變化，而 FCM 的假設可得日通常落在 outcome
  **月中** —— 估計樣本 **3275/3275 列**都是這種情形
  （`data_provenance.fcm_avail_inside_outcome_month_rows`）。
- 30–90 天的 lag 網格只證明結果對不同**合成** vintage 位移不敏感，不等於核對過真實發布日。

## 這次重跑相對前兩輪的數字變化

| | round 1（FAIL） | round 2（FAIL） | round 3（FAIL） | 本次 |
|---|---|---|---|---|
| spec1 樣本 | 3293 | 3278 | 3276 | 3275 |
| spec1 coef | 3.146e-04 | 3.158e-04 | 3.055e-04 | 3.103e-04 |
| spec1 t_DK | 1.55 | 1.56 | 1.51 | 1.53 |
| headline CI 出處 | 另一個規格 | spec1 本身 | spec1 本身 | spec1 本身 |

樣本每輪掉一點，全都是完整性規則變嚴的結果：−15 是 partial month 2026-07，−2 是被獨立截斷的
RV 下載（2014-04 / 2016-03），−1 是假日調整後日曆抓到的又一個短少月。**結論四輪都沒動** ——
這正是重點：三次 FAIL 沒有一次是因為結論錯，全都是因為**宣稱的東西超過程式證得的東西**。

## 檔案

| 檔案 | 說明 |
|---|---|
| `K1694.py` | 分析腳本（唯一 compute path） |
| `test_K1694.py` | round 1 + 2 + 3 全部缺陷的機械 gate（39 tests） |
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
2. ~~Codex round 1~~ ✅ → FAIL；~~依裁決修 8 項 + 重跑~~ ✅
3. ~~Codex round 2~~ ✅ → FAIL；~~依裁決修 4 項 + 重跑~~ ✅（本次）
4. Codex round 3 裁決 → `review_verdict.json`
5. PASS 後才由**主線程**寫 knowledge entry（agent 不得寫 `knowledge.json`）
6. 真正核對 CFTC FCM 月報的實際上線日期（離線做不到；沒有它，spec4 的 ex-ante 身分永遠是條件式的）
7. 量化有效時間自由度（目前只揭露 ACF，沒有給出等效樣本數）

## 歷史：搶救經過（2026-07-19）

- 2026-07-15 09:22 台北：`K1692_K1694_starvation_dispatch` 走 compute_queue 派出 K1692/K1694。
- **K1694 的 agent 沒有跑完**，只留下腳本與已抓好的資料，在 worktree 裡閒置 99 小時。
- task pool 中 `K1694` 的 status 是 `succeeded`，但 `result` 是 `null` —— 那個 succeeded 指
  「**派工**成功」而非實驗成功。這是狀態語意陷阱，不是實驗已完成的證據。
- 2026-07-29 修好三個讓腳本跑不動的缺陷（`.dt.normalize()`、Period 時間索引、bootstrap 的
  字串月份標籤讓每個 replicate 都靜默 NaN）後首次產出結果 → 送 Codex → FAIL → 修 → FAIL → 修。
  **改動越是讓結果從無到有，越需要外部審**：那次讓 bootstrap「活起來」的修正，活起來估的
  卻不是 spec1。
