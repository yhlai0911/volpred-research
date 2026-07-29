# K1694 — FCM 清算集中度與商品小型交易人的高波動排擠

## 狀態：round 6 **PASS**（Codex，2026-07-30；reviewed_commit `2724b3587`）

- **round 1 → FAIL**（`storage/ops/codex_reviews/k1694_verdict.md`）：8 項缺陷
- **round 2 → FAIL**（`k1694_verdict_round2.md`）：4 項要求
- **round 3 → FAIL**（`k1694_verdict_round3.md`）：3 項缺陷，其中一項是**具體反例**
- **round 4 → FAIL**（`k1694_verdict_round4.md`）：2 項 RV 完整性反例
- **round 5 → FAIL**（`review_verdict.json`）：2 項缺陷 —— 通用休市白名單無出處、
  端點測試自己當自己的 oracle
- **round 6 → PASS**（`review_verdict.json`）：兩項缺陷皆 RESOLVED，無新增 blocking defect

`review_verdict.json` 已 PASS，`knowledge_promotion_allowed: true`。knowledge 條目仍**只能由
主線程**寫（K1259），且每個數字必須從 `K1694_results.json` 程式化取得，不得從本 README 轉抄。

## 結論：NULL —— 意思是「未獲支持」，不是「不存在」

**這份實驗沒有任何 predictive / causal 的宣稱，也沒有「沒有可預測性」的宣稱。**
所有零結果一律寫「**未獲支持**」。本文的估計式無法證明效果不存在，只能說沒有支持它的證據。

**NULL 涵蓋的假說只有一個：負向、二元 high-vol 的排擠交互項未獲支持。**
它**不是**「FCM 集中度與小型交易人部位完全沒有關聯」。

| spec | 交互項 | n | coef | t_DK | t_cluster |
|---|---|---|---|---|---|
| spec1（主）FCM HHI × high-vol（二元） | `fcm_x_highvol` | 3275 | **+3.034e-04** | +1.48 | +1.52 |
| spec2 FCM HHI × rv_z（連續） | `fcm_x_rvz` | 3275 | **+2.885e-04** | **+2.54** | **+2.56** |
| spec3 trader conc4 × high-vol | `conc4_x_highvol` | 3275 | −1.847e-04 | −0.72 | −0.71 |
| spec4 時序收緊的落後規格 | `fcm_pre_x_highvol_lag` | 2748 | +7.266e-05 | +0.30 | +0.37 |

- 主 spec 的點估計**是正的**（排擠假說預測為負），且不顯著（p_DK = 0.138）。
- 連續型 spec2 **正向且顯著**（p_DK = 0.011）——方向與排擠假說**相反**。所以正確的敘述是
  「沒有證據支持排擠；若有訊號，方向是小型交易人在高集中度高波動月份**佔比上升**」。
- 描述統計同一方向：high-HHI × high-vol 格的 Δ 非報告部位佔比平均 **+2.83 bp**，
  其餘三格皆為負（−1.84 / −4.96 / −3.06 bp）。
- spec4 幾乎是零（t = 0.30）。這句話只能讀成「**此時序安排下未獲得關聯的支持**」，
  **不能**讀成「這個時序安排下沒有關聯」，更不能讀成「沒有可預測性」——
  理由見下方「spec4 能講什麼、不能講什麼」。

| 檢定 | 值 |
|---|---|
| stationary block bootstrap（by month, 平均 block 6 個月, 2000 reps） | 95% CI [−9.02e-05, 7.78e-04], p = 0.130 |
| IID month-cluster bootstrap（對照, 2000 reps） | 95% CI [−8.05e-05, 7.13e-04], p = 0.128 |
| DK bandwidth 1..24 敏感度 | \|t\| ∈ [1.47, 1.60]，**無一點達 1.96** |
| 時間序列 aggregate `hhi_x_volfrac` | t 0.36, p 0.719（HAC lag 6, resid acf1 −0.042, 149 個月） |
| FCM 發布 lag 30/45/60/75/90 天 | t_DK ∈ [1.16, 1.48]，**無一點達 1.96**（`K1694_lag_sensitivity.json`） |

樣本：**3275 列 / 22 商品 / 2014-02..2026-06**（149 個日曆月）。每一列的 DCOT 月份都經過
**連續性認證**（漏任何一週都擋得下來）；RV 月份則只是**通過篩檢**——日數與**該商品所屬
交易所**的交易日曆相符到 1 天以內，不是逐月端點認證（round 4 起、round 6 改為 product-scoped，
見下方專節）。spec4 另有自己的樣本 2748 列。

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
| II | **RV 規則證明不了下載跑到月頭月尾**：全體商品共同短少 1–5 天時，business-day 缺口 ≤5、cross-sectional 缺口 = 0，照樣判 complete | 當時做了三件事：(a) `build_vol()` 開始記錄每月**實際首末交易日**；(b) 對只存計數的既有快取，加上**月層級的日曆 anchor**；(c) 抓不到的部分照實揭露。**這個修復在 round 4 被推翻了**——當時的 anchor 用「美國聯邦假日 + Good Friday」，把期貨照常交易的 Columbus / Veterans Day 也扣掉，anchor 因此低估；(a) 的 endpoint 路徑也還留著首尾各 3 天的容差。實際的修復見下方 round 4 專節 | `test_completeness_rule_catches_a_truncation_common_to_every_commodity`（先斷言 cross-sectional 檢查在此情境確實失明，再斷言月層級 anchor 擋下）、`test_rv_endpoint_test_is_declared_unavailable_when_the_cache_lacks_dates`；round 4 另加兩個反例 gate |
| III | **仍有直接的 absence wording**：「這個時序安排下沒有關聯」/ "no association survives this timing"，與同一份 artifact 說的「estimators cannot establish absence」矛盾；另外 `fcm_avail_inside_outcome_month_rows` 算的是 `panel` 不是 `frame`，與 README 的 N/N 對不上 | 全部改成「此時序安排下**未獲得**關聯的支持」/ "an association is NOT SUPPORTED under this timing arrangement"；欄位改名 `..._in_estimation_sample` 並從 `frame` 計算，另附 `estimation_sample_rows` | `test_nothing_claims_absence_of_association`（掃 results 與 README 的宣稱段，且要求每個「沒有關聯」都在否定句裡）、`test_within_month_overlap_count_is_scoped_to_the_estimation_sample`（含 README 的 N/N 一致性） |

第 II 項的殘留盲區在 round 4 被證明比當時寫的更寬，處理方式見下一節。

## Codex round 4 的 2 項缺陷，逐項修復對照

| # | round 4 缺陷 | 修復 | 可驗證證據 |
|---|---|---|---|
| D1 | **count-only 盲點比宣稱的寬**：`_expected_trading_days()` 用「weekdays − 美國聯邦假日 − Good Friday」，把**期貨照常交易**的 Columbus Day / Veterans Day 也扣掉，expected 因此低估。反例 2020-10：日曆給 21，快取裡 22 個商品實際都是 22 天；共同截短 2 天後 `expected − max(ndays)` 只有 1，**22/22 仍判 complete**。舊 docstring 說「方向偏 permissive 所以安全」——那推翻的正是規則自己寫的偵測宣稱 | 改用**交易所休市日曆**：不扣 Columbus / Veterans Day；1 月 1 日落在週六時**不**回捲到 12/31；Juneteenth 自 2022 起算。**當時另加的計畫外休市白名單 `CME_UNSCHEDULED_CLOSURES` 在 round 5 被推翻並於 round 6 整個刪除**，理由見下一節 | `test_common_two_day_truncation_2020_10`（修復前 22/22 complete → 修復後 0/22）；`rule.rv_expected_trading_days_definition` |
| D2 | **帶日期的路徑不是它自稱的 “true endpoint test”**：首尾各容許 3 個 weekday gap。反例 2020-06：注入日期後讓所有商品共同少掉 6/30，`rv_tail_gap_days = 1`，**22/22 仍判 complete**——那個宣稱只存在於 count-only 快取的一日端點盲點，日期路徑照樣有 | gap 改成對**日曆的首末排定交易日**量，且必須是 **0**：`first_day <= 該月第一個交易日` 且 `last_day >= 最後一個交易日`。比日曆多觀察到（縮短交易時段的日線）讀成 0，所以多的資料不會被誤擋 | `test_endpoint_truncation_2020_06`（修復前 22/22 → 修復後 0/22）、~~`test_endpoint_gate_accepts_an_untruncated_dated_cache`~~（**round 5 判定為套套邏輯並於 round 6 刪除**，改由 `test_endpoint_gate_accepts_a_primary_source_untruncated_cache` 取代，見下一節 P2） |

**同時撤回一個撐不起來的宣稱**（round 4 明講：要嘛讓認證為真，要嘛收回宣稱）。
`sample.panel_span_is_complete_months_only` 從 `true` 改成 **`false`**，另附
`panel_span_completeness_basis` 說明分界：

- **DCOT 月份是「認證」**——週報序列全域連續，漏任何一週都擋得下來。
- **RV 月份只是「篩檢」**——日數與該交易所的日曆相符到 **1 天**以內。共同短少剛好 1 天，在只有
  計數的快取裡看不出來。所以本實驗**不宣稱**每筆下載都跑到該月頭尾。
- 少數月份盲區是 **2 天**：部分合約在休市日仍印出縮短交易時段的日線，`max(ndays)` 因此
  超過日曆。這些月份由 `coverage_report()` 在**執行時逐月列出**（不是手寫）於
  `rule.rv_months_observed_beyond_the_exchange_calendar`，本次共 8 個 schedule-month。

要真的「認證」完整月份，count-only 的 `rv_monthly.csv` 需要獨立的端點證據；本輪選擇**保住
frozen cache 的 provenance 穩定性**、把宣稱降到程式證得到的強度，而不是重抓資料。

## Codex round 5 的 2 項缺陷，逐項修復對照

| # | round 5 缺陷 | 修復 | 可驗證證據 |
|---|---|---|---|
| P1 | **通用休市白名單沒有出處，而且被交易所公告直接反駁**：round 4 的 `CME_UNSCHEDULED_CLOSURES` 對**所有 22 個商品**一律扣掉 2012-10-29 / 2012-10-30 / 2018-12-05。那張表是從「快取少了幾天」反推的。CFTC 12-363 明寫 Sandy 期間 "Electronic trading remains available for **all** NYMEX and COMEX products on CME Globex"，關的只有股指與利率複合體；ICE 說 "All other ICE markets ... will remain open"；CME 2018-12-02 說 "All other markets on CME Globex ... will remain open for regular trading hours on Dec. 5"。K1694 一個股指、一個利率商品都沒有 | **走 (a)：product / exchange-scoped 行事曆**。`PRODUCT_SCHEDULE` 把 22 個商品分成 `CME_GLOBEX_COMMODITY`（18）與 `ICEUS_SOFTS`（4），日數、月端點、cross-sectional peer group 全部 per-schedule 算。查證後**兩邊的計畫外休市集合都是空的**——不是「還沒填」，是三個爭議日期交易所都開著。`_validate_unscheduled_closures()` 在 import 時就擋掉沒有 `source_id` + `quote` 的條目 | `calendar_sources.md`（22 列 ticker → 交易所 → 官方 URL）；`calendar_fixtures.json`；`test_the_disputed_dates_are_trading_days_for_every_schedule`、`test_unscheduled_closures_must_carry_a_primary_source`、`test_the_two_schedules_are_declared_separately_not_aliased` |
| P2 | **端點測試是套套邏輯**：`test_endpoint_gate_accepts_an_untruncated_dated_cache` 把 `expected_month_endpoints()` 的輸出灌回去問同一份實作接不接受，只驗內部一致性，無法證偽一張錯的日曆 | 該測試**刪除**，改成從 `calendar_fixtures.json`（手抄自交易所公告）讀端點：注入公告端點必須通過，往回縮一個交易日必須失敗。所有日曆測試的期望值一律來自 fixture，**不來自 `K1694.py`** | `test_endpoint_gate_accepts_a_primary_source_untruncated_cache`、`test_calendar_matches_primary_source_date_fixtures`、`test_calendar_matches_primary_source_month_fixtures` |

**這個 oracle 真的證偽得了東西**：拿 `gate_history/a5896554__K1694.py`（round 5 的原始 bytes，
`preserve_gate_blob.py` 在改動前存的）去跑同一份 fixture，**9 項矛盾**——4 個 Sandy 日期狀態、
1 個國殤日狀態、4 個月份日數（2012-10 給 21 而公告推得 23；2018-12 給 19 而公告推得 20）。
同一份 fixture 對 round 6 的日曆全數通過。

### 移除白名單之後，多了一件必須講的事

白名單原本把 2018-12-05 說成「休市」。現在有 CME 自己的公告說**當天有開**，而快取裡
**22 個商品一個都沒有那天的日線**。也就是說：

> **一個月份可以通過這道篩檢，同時被證明少了一個交易日。**

這比 round 5 寫的「理論上有 1 天盲區」強得多，因為它是**在樣本內實際發生**的。
`coverage_report()` 因此新增 `rule.rv_months_short_of_the_exchange_calendar`，在執行時逐月列出
「該 schedule 的每一個商品都短於自家交易所日曆」的月份與 `caught_by_the_rule` 旗標。
本次 13 個 schedule-month，其中 2012-10（短 2 天）與 2026-07（短 12 天）被規則擋下，
2018-12 等 11 個短剛好 1 天、在容忍度內 —— 這就是盲區本身，現在有名有姓。

**而且不只揭露，還量化了。** `robustness_strict_month_gate` 在執行時把
`MAX_RV_MONTH_SHORTFALL` 暫時設成 **0**（該 schedule 至少要有一個合約與交易所日曆完全相符），
把上述**全部** 13 個月一併剔除後重估 spec1：

| | 主規格（門檻 1） | strict gate（門檻 0） |
|---|---|---|
| n | 3275 | **3210**（−65） |
| coef | +3.034e-04 | **+3.348e-04** |
| t_DK | 1.48 | **1.69** |

方向不變、仍**未達顯著**（|t| < 1.96）。這是 **sensitivity 不是主規格**：報告的門檻從 round 4
至今一個字都沒動，`is_the_reported_specification: false` 與
`test_the_tolerated_blind_spot_is_quantified_not_only_disclosed` 都釘住這件事。

### 一個查不到出處的日期，照實留白

**ICE Futures U.S. 在 2018-12-05 是否交易，查不到官方出處。** 處理方式是**不主張休市**
（「查不到就當它休市」正是這輪在修的毛病）。影響已量化：`unverified_status_insensitivity`
在執行時把該日強制設成休市重算一次，`rv_complete` 5229 → 5229、**0 列會翻**，
估計樣本一列都不變。這個 probe 跑完會回讀確認全域狀態已還原，沒還原就 raise。

## Codex round 2 的 4 項要求，逐項修復對照

| # | round 2 要求 | 修復 | 可驗證證據 |
|---|---|---|---|
| A | spec4 的 predictive 宣稱過度：t−1 DCOT 控制變數在 t 月開始前未必已發布；樣本被 spec4 沒用到的 `rv_z` 篩選；發布日仍是合成的，撐不起「沒有可預測性」 | 控制變數全改 **t−2**（`nonrep_lag2` / `d_nonrep_lag2` / `dlog_oi_lag2`）；新增 `build_lagged_frame()` 用 spec4 自己的 regressors 決定樣本；spec 更名 `spec4_lagged_timing_hardened`；**全檔移除** predictive / no-predictability 宣稱 | `test_promised_lagged_spec_exists_and_is_timed_correctly`（t−1 控制變數被禁）、`test_lagged_frame_is_not_conditioned_on_a_regressor_it_does_not_use`、`test_no_spec_claims_prediction`、`test_nothing_claims_absence_of_predictability` |
| B | 「不成立」要改「未獲支持」；「149 個月的獨立 FCM 變異」是錯的 | 全檔零結果改「未獲支持 / NOT SUPPORTED」；新增 `sample.effective_temporal_dof`，報 ACF(1/3/6/12) 並明寫有效自由度**低於**日曆月數 | `test_null_is_worded_as_not_supported_not_as_disproved`（含 README 掃「不成立」）、`test_effective_temporal_dof_is_disclosed_not_asserted_independent` |
| C | `np.log(oi).diff()` 沒有 `oi > 0` / 有限值防護 | 先 mask 非正、非有限的 OI 再取 log，並把結果中殘留的非有限值清成 NaN；`oi_invalid` 計數寫進 results | `test_log_oi_has_a_positivity_guard`（含注入 0 與負值的負向案例）；`sample.oi_invalid_rows_guarded = 0` |
| D | 完整性規則證明不了全月覆蓋：5 份週報的月份可能中間漏一週；RV 也可能被獨立截斷 | **（此欄描述的是當時的規則，現已被 round 3 / round 4 取代，保留只為對照）** 當時 DCOT 改成頭/中/尾三段連續性檢查（首份距**月初** ≤8 天、相鄰週報間隔 ≤9 天、末份距月底 ≤6 天）；RV 改成三條件（絕對 ≥15 天、相對該月**營業日**缺口 ≤5 天、相對同月其他商品缺口 ≤3 天）。**現行規則**：DCOT 的 head gap 改從上一份週報量（round 3），RV 三個門檻現為 `MAX_RV_SHORTFALL_VS_CALENDAR=2` / `MAX_RV_CROSS_SHORTFALL=2` / `MAX_RV_MONTH_SHORTFALL=1`，且比對的是 CME 期貨交易日曆而非營業日（round 4） | `test_completeness_rule_catches_a_skipped_week`、`test_completeness_rule_catches_an_independently_truncated_rv_month`、`test_completeness_rule_holds_on_every_retained_row` |

門檻是照本快取的實測分布訂的，留了假日位移的餘裕但擋得住整週缺漏：相鄰週報間隔實測只有
6/7/8 天三種值，漏一週會撐到約 14 天（現行 `MAX_DCOT_GAP_DAYS=9`）。RV 側對交易所日曆的
月層級缺口，全部 schedule-month 中只有 13 個為正（逐月列在
`rule.rv_months_short_of_the_exchange_calendar`），被截斷的 2026-07 是 12 天。

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

`uv run --active python -m pytest experiments/K1694/test_K1694.py -q` → **50 passed**。

## timing：為什麼 spec1–3 只能講 association

`merge_asof(direction="backward")` 的方向是對的（0 列用到 outcome 月底之後才可得的報表），
但**方向正確 ≠ 訊號早於結果**：

- `FCM_LAG_DAYS = 45` 是合成常數，不是查證過的 CFTC 發布日；離線快取沒有發布日欄位。
- outcome `d_nonrep` 是整月 DCOT 平均相對前月的變化，而 FCM 的假設可得日通常落在 outcome
  **月中** —— 估計樣本 **3275/3275 列**都是這種情形
  （`data_provenance.fcm_avail_inside_outcome_month_rows_in_estimation_sample`）。
- 30–90 天的 lag 網格只證明結果對不同**合成** vintage 位移不敏感，不等於核對過真實發布日。

## 這次重跑相對前幾輪的數字變化

| | round 1（FAIL） | round 2（FAIL） | round 3（FAIL） | round 4（FAIL） | round 5（FAIL） | 本次（round 6） |
|---|---|---|---|---|---|---|
| spec1 樣本 | 3293 | 3278 | 3276 | 3275 | 3276 | **3275** |
| spec1 coef | 3.146e-04 | 3.158e-04 | 3.055e-04 | 3.103e-04 | 3.097e-04 | **3.034e-04** |
| spec1 t_DK | 1.55 | 1.56 | 1.51 | 1.53 | 1.53 | **1.48** |
| headline CI 出處 | 另一個規格 | spec1 本身 | spec1 本身 | spec1 本身 | spec1 本身 | spec1 本身 |

### 本輪逐項量化：刪掉白名單改變了什麼

| 項目 | round 5 | round 6 | 差 |
|---|---|---|---|
| 估計樣本列數 | 3276 | **3275** | −1（2018-12 的 CORN） |
| spec4 樣本列數 | 2749 | **2748** | −1 |
| coverage 中 `rv_complete` 的列數 | 5252 | **5229** | −23（用 `gate_history/` 的 round-5 原始 bytes 對同一份 frozen cache 重算） |
| 被 mask 的 (商品,月) 列 | 22 | **45** | +23 |
| **2012-10** 通過列數 | 22/22 | **0/22** | 該月共同短 2 天，規則現在抓得到（早於樣本起點 2014-02，不影響估計樣本） |
| **2018-12** 通過列數 | 22/22 | **21/22** | CORN 只有 17 天，對 20 天的日曆短 3 > 門檻 2 |
| spec1 coef / t_DK | 3.097e-04 / 1.53 | 3.034e-04 / 1.48 | 方向、顯著性皆未變 |
| spec2 coef / t_DK | 2.875e-04 / 2.54 | 2.885e-04 / 2.54 | 仍正向顯著（p = 0.011） |
| spec4 coef / t_DK | 6.674e-05 / 0.27 | 7.266e-05 / 0.30 | 仍近乎零 |
| stationary block boot 95% CI | [−7.41e-05, 7.75e-04] | [−9.02e-05, 7.78e-04] | 仍跨越 0（p 0.119 → 0.130） |
| **VERDICT** | NULL | **NULL** | 未變 |

兩項改動的歸因分開講：

1. **刪掉沒有出處的白名單** —— 上表所有樣本變化都出自這一項。
2. **把行事曆改成 per-schedule** —— 因為兩個交易所的常規休市集合經核對後**相同**、
   而且移除白名單後兩邊都沒有計畫外休市，這一項在本次執行**沒有改變任何一列**。
   它是結構性的：將來 ICE 或 CME 任一邊出現有出處的休市，才不會誤傷另一邊。
   `test_the_two_schedules_are_declared_separately_not_aliased` 用注入式 probe 釘住這個隔離。

**沒有動任何門檻**：`MIN_RV_DAYS=15`、`MAX_RV_SHORTFALL_VS_CALENDAR=2`、
`MAX_RV_CROSS_SHORTFALL=2`、`MAX_RV_MONTH_SHORTFALL=1` 六輪一路沒變。

**結論六輪都沒動**（NULL / NOT SUPPORTED，spec2 連續型仍是正向顯著）—— 這正是重點：五次 FAIL
沒有一次是因為結論錯，全都是因為**宣稱的東西超過程式證得的東西**。

## 檔案

| 檔案 | 說明 |
|---|---|
| `K1694.py` | 分析腳本（唯一 compute path） |
| `test_K1694.py` | round 1–5 全部缺陷的機械 gate（50 tests） |
| `calendar_sources.md` | **22 列 ticker → 交易所 → 官方行事曆 URL**；三個爭議日期的逐字引文；查不到的洞 |
| `calendar_fixtures.json` | 機器可讀的 primary-source oracle；測試只讀它，**不讀 `K1694.py`** |
| `gate_history/a5896554__K1694.py` | round 5 的原始 bytes（改動前用 `preserve_gate_blob.py` 存），供 reviewer 直接 diff 與重跑反例 |
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
2. ~~Codex round 1–5~~ ✅ → 五次皆 FAIL；~~逐輪依裁決修復並全面重跑~~ ✅
3. ~~Codex round 6 裁決~~ ✅ → **PASS**
4. 由**主線程**寫 knowledge entry（agent 不得寫 `knowledge.json`），再 `scripts/merge_worktree.sh` 合併
5. 真正核對 CFTC FCM 月報的實際上線日期（離線做不到；沒有它，spec4 的 ex-ante 身分永遠是條件式的）
6. 量化有效時間自由度（目前只揭露 ACF，沒有給出等效樣本數）
7. **ICE Futures U.S. 在 2018-12-05 的交易狀態**：查不到官方出處，目前當作有開；
   已證明對估計樣本零影響（`unverified_status_insensitivity`），但洞還在
8. **重抓帶端點日期的 RV 快取**：現行 `rv_monthly.csv` 只有計數，端點測試因此沒被實際執行。
   本輪選擇保住 frozen cache 的 provenance 穩定性；要真的把「篩檢」升級成「認證」，
   得重抓 —— 那是一個 provenance vs. 檢查強度的取捨，屬於這份修復以外的決定

## 歷史：搶救經過（2026-07-19）

- 2026-07-15 09:22 台北：`K1692_K1694_starvation_dispatch` 走 compute_queue 派出 K1692/K1694。
- **K1694 的 agent 沒有跑完**，只留下腳本與已抓好的資料，在 worktree 裡閒置 99 小時。
- task pool 中 `K1694` 的 status 是 `succeeded`，但 `result` 是 `null` —— 那個 succeeded 指
  「**派工**成功」而非實驗成功。這是狀態語意陷阱，不是實驗已完成的證據。
- 2026-07-29 修好三個讓腳本跑不動的缺陷（`.dt.normalize()`、Period 時間索引、bootstrap 的
  字串月份標籤讓每個 replicate 都靜默 NaN）後首次產出結果 → 送 Codex → FAIL → 修 → FAIL → 修。
  **改動越是讓結果從無到有，越需要外部審**：那次讓 bootstrap「活起來」的修正，活起來估的
  卻不是 spec1。
