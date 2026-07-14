# K1655 DM/HAC 掃描 — `unknown` bucket 全量分流（78/78）

- **任務**：`k1655_dm_sweep_triage_unknown_bucket`（來源：`docs/governance/2026-07/dm_hac_lag_class_sweep.md` §盲區分析）
- **母體**：`scripts/audit_dm_hac_lag.py` 判為 `verdict="unknown"` 的 78 個站點（靜態解析不出 Newey-West bandwidth）
- **方法**：78 個**全部逐一打開讀程式碼**，不抽樣。每個站點解析：(1) bandwidth 實際怎麼算（含 helper function 與模組常數展開）、(2) 呼叫端實際餵進去的 h、(3) `README.md` / `*_results.json` 對外報出去的是哪個變體。
- **不修代碼**：本輪只做分類與判定。

## 分類定義

| bucket | 定義 | 數量 |
|---|---|---|
| **a** | 正確實作 —— bandwidth 有明確下界（floor 至 1 或 canonical NW rule），h=1 不退化；主檢定餵給對外結論的是 HAC 變體 | 11 |
| **b** | 純名字撞到 —— 不是推論站點，本身不估變異數、沒有 bandwidth | 1 |
| **c** | 真的要打開讀才判得出來的推論站點 | 66 |
| | **其中 `needs_fix=YES`（h=1 真的退化成無 HAC）** | **5** |

## 全量表（78 列）

| # | file:lineno | function | 類別 | bandwidth 實際規則 | h=1 退化？ | 對外引用的變體 | 需修？ |
|---|---|---|---|---|---|---|---|
| 1 | `experiments/K1655/K1655.py:717` | `hln_dm` | a | lag = max(h-1, max(1, min(ceil(h^(1/3)*n^(1/3)), n//4))) | no | t_hln (HAC-corrected) | no |
| 2 | `experiments/K1663_rcov_har_gmv/K1663_rcov_har_gmv.py:164` | `dm_hln` | a | L = max(floor(4*(T/100)^(2/9)), h-1) | no | t_hln | no |
| 3 | `experiments/K1679-rev/K1679-rev.py:334` | `dm_hln` | a | nw_variance(d, lag=h) -> range(1, h+1) | no | t_hln + p(t_hln) | no |
| 4 | `experiments/K1679-rev2/K1679-rev2.py:591` | `dm_hln` | a | nw_variance(d, lag=h) -> range(1, h+1) | no | t_hln + p(t_hln) | no |
| 5 | `experiments/K1679/K1679.py:261` | `dm_hln` | a | nw_variance(d, lag=h) -> range(1, h+1) | no | t_hln + p(t_hln) | no |
| 6 | `experiments/k1019/k1019.py:722` | `dm_test` | c | max_lag = int(n^(1/3)) | no | t/p | no |
| 7 | `experiments/k1031/k1031/k1031.py:698` | `dm_test` | c | bw = int(n^(1/3)) | no | t/p | no |
| 8 | `experiments/k1054/k1054.py:577` | `dm_test` | c | hardcoded HAC(1): gamma0 + 2*gamma1（矩形核，無 Bartlett 權重） | no | t/p | no |
| 9 | `experiments/k1072/k1072.py:502` | `dm_test` | c | hardcoded HAC(1): gamma0 + 2*gamma1 | no | t/p | no |
| 10 | `experiments/k1097/k1097.py:645` | `dm_test` | c | max_lag = int(n^(1/3)) | no | t/p | no |
| 11 | `experiments/k1144/k1144.py:432` | `harvey_dm_test` | c | max_lag = floor(T^(1/3)) | no | dm_stat/dm_p | no |
| 12 | `experiments/k1265/k1265.py:212` | `dm_hln` | a | max_lag = max(floor(4*(n/100)^(2/9)), h-1) | no | t (HLN-corrected) | no |
| 13 | `experiments/k1314/k1314.py:228` | `dm_hln_test` | a | newey_west_se: L = max(1, floor(n^(1/3))) | no | t_stat (HLN) | no |
| 14 | `experiments/k1337/K1337.py:219` | `dm_test_hac` | a | lag 為參數；呼叫端 line 389: lag = max(H-1, 1) | no | t/p | no |
| 15 | `experiments/k1337_v2/K1337_v2.py:295` | `dm_test_hac` | a | lag 為參數；呼叫端 line 483: lag = max(H-1, 1) | no | t/p | no |
| 16 | `experiments/k1371/k1371.py:146` | `dm_test` | c | statsmodels OLS cov_type='HAC', maxlags=NW_LAGS=22 | no | dm_stat/p_value | no |
| 17 | `experiments/k1379/k1379.py:359` | `dm_test` | c | 無 —— gamma0 = mean(d^2)-dbar^2，完全沒有 autocovariance 迴圈 | YES（任何 h 都沒有 HAC） | dm_t/dm_p 寫進 k1379_results.json -> Paper 9 (garch-x-vix) horse race + feed×4 + knowledge×2 | **YES** |
| 18 | `experiments/k1386/k1386.py:367` | `dm_test_harvey` | c | for k in range(1, max(1, h))；呼叫端 h=1 -> range(1,1) 空迴圈 | YES | README \|t\|=3.26 -> 「HAR 顯著優於 fGN（>3.0 Harvey 門檻）」；feed×6 + knowledge×1 | **YES** |
| 19 | `experiments/k1399/k1399_vix_decomp.py:269` | `dm_hln_test` | c | bw = int(T^(1/3)) | no | dm_stat (HLN) / p | no |
| 20 | `experiments/k144/k144_mf2_cross_bond.py:512` | `dm_test_onesided` | c | bw = max(1, int(n^(1/3))) | no | dm/p | no |
| 21 | `experiments/k151/k151_sectoral_vol_dispersion.py:528` | `dm_test` | c | max_lag = min(5, n//5) | no（除非 n<5） | dm_stat/p_val | no |
| 22 | `experiments/k1513/k1513.py:224` | `dm_test` | a | newey_west_se: lag = max(1, round(T^(1/3))) | no | t/p | no |
| 23 | `experiments/k152/k152_liquidity_ms_garch.py:103` | `diebold_mariano` | c | for k in range(1, max(h, 2))；h=1 -> k=1（無權重，2*gamma_k） | no | statistic/p_value | no |
| 24 | `experiments/k1520/k1520.py:108` | `dm_hac` | c | lag = min(HAC_LAGS=5, n-2) | no | dm_t/p | no |
| 25 | `experiments/k1525_hf_tail_risk_premium_vrp/k1525_hf_tail_risk_premium_vrp.py:265` | `dm_test` | c | for k in range(1, max(1, h))；呼叫端 h=1 -> 空迴圈（且權重 1-k/h 在 h=1 時亦為 0，雙重退化） | YES | README §4.3「DM (HLN-corrected): t=-0.85, p=0.397, n=137」-> 焦點 spec 未過 OOS gate 的核心論據 | **YES** |
| 26 | `experiments/k1526_hf_tail_risk_premium_vrp/k1526_hf_tail_risk_premium_vrp.py:265` | `dm_test` | c | 同 k1525（逐字複製） | YES | 同 k1525（README t=-0.85, p=0.397）；knowledge×1 | **YES** |
| 27 | `experiments/k157/k157_correlation_forecasting.py:421` | `dm_test_correlation` | c | for k in range(1, min(5, T))（無權重） | no | statistic/p_value | no |
| 28 | `experiments/k160/k160_copula_tail_dependence.py:897` | `dm_test` | c | for k in range(1, min(h+1, T//2))；h=1 -> k=1 | no | statistic/p_value | no |
| 29 | `experiments/k1616_cointegration_ect_har_rv/k1616_cointegration_ect_har_rv.py:260` | `hln_correct` | b | 無 bandwidth —— 只是 HLN 小樣本因子 sqrt((n+1-2h+h(h-1)/n)/n) | n/a | hln_t/hln_p；輸入 dm_t 來自 canonical volpred.stats.model_evaluation.dm_test（line 57 import） | no |
| 30 | `experiments/k1637/k1637.py:102` | `dm_hac` | c | lag = min(max_lag=5, n-1) | no | t_stat/p_value/harvey_pass | no |
| 31 | `experiments/k180/k180_directional_change.py:114` | `dm_test` | c | for k in range(1, max(h, 2))，權重 1-k/max(h,2)=0.5 | no | t/p | no |
| 32 | `experiments/k188/k188_har_ceiling.py:342` | `dm_test_hac` | c | max_lag = floor(n^(1/3))（n>=30 guard） | no | t/p | no |
| 33 | `experiments/k190/k190_realized_semivariance.py:337` | `dm_test` | c | bw = max(1, floor(4*(n/100)^(2/9))) | no | t_stat/p_value | no |
| 34 | `experiments/k192/k192_google_trends_vol.py:242` | `diebold_mariano_test` | c | for k in range(1, max(h,2))，權重 1-k/(h+1)=0.5 | no | dm_stat/p_val | no |
| 35 | `experiments/k197/k197_persistence_break.py:296` | `dm_test` | c | bw = max(1, int(n^(1/3))) | no | t/p | no |
| 36 | `experiments/k198/k198_realized_garch.py:130` | `dm_test` | c | for k in range(1, max(h,2))，權重 0.5 | no | t/p | no |
| 37 | `experiments/k206/k206_asset_specific_vt.py:478` | `dm_test` | c | bw = int(n^(1/3)) | no | t_stat/p_value | no |
| 38 | `experiments/k230/k230_optimal_vt_param.py:245` | `dm_test` | c | max_lag = min(h, n-1)；h=1 -> 1 -> range(1,2) 納 k=1 | no | t/p | no |
| 39 | `experiments/k233/k233_three_asset.py:288` | `dm_test_returns` | c | max_lag = int(sqrt(n)) | no | t/p | no |
| 40 | `experiments/k409/k409_options_mispricing.py:207` | `dm_test` | c | newey_west_se: max_lag = floor(4*(n/100)^(2/9)) | no | t/p | no |
| 41 | `experiments/k437/k437_gas_model.py:603` | `dm_test` | c | for k in range(1, max(h,2))（無權重） | no | dm_stat/p_value | no |
| 42 | `experiments/k450/k450_vrp_semivar_combined.py:359` | `dm_test` | a | lag = max(ceil(4*(n/100)^(2/9)), h) | no | t/p | no |
| 43 | `experiments/k460/k460_semivar_cross_oos.py:94` | `dm_test_losses` | c | for k in range(1, max(h,2))，權重 0.5 | no | t/p | no |
| 44 | `experiments/k465/k465_har_range_cross_oos.py:383` | `dm_test` | c | for k in range(1, max(h,2))，權重 0.5 | no | t/p | no |
| 45 | `experiments/k469/k469_har_r2_proxy.py:330` | `dm_test` | c | for k in range(1, max(h,2))，權重 0.5 | no | t/p | no |
| 46 | `experiments/k470/k470_har_vt_strategy.py:443` | `dm_test_returns` | c | for k in range(1, max(h+1,2))；h=1 -> k=1，權重 0.5 | no | t/p | no |
| 47 | `experiments/k472/k472_taiwan_comprehensive.py:257` | `dm_test` | c | hardcoded lag-1: gamma0 + 2*gamma1 | no | t/p | no |
| 48 | `experiments/k478/k478_entropy_vol.py:262` | `dm_test` | c | max_lag = min(DM_HAC_LAG, n-1)，DM_HAC_LAG = HORIZON = 21 | no | dm_stat/p_value | no |
| 49 | `experiments/k488/k488_gjrx_vt_strategy.py:605` | `dm_test_returns` | c | for k in range(1, max(h+1,2))，權重 0.5 | no | t/p | no |
| 50 | `experiments/k489/k489_vix_term_structure.py:200` | `dm_test` | c | for k in range(1, max(h,2))，權重 (1 - k/h) | 結構上 YES，但未被觸發 | t/p（README 的 matched-tenor DM 表） | no（潛在） |
| 51 | `experiments/k494/k494_forex_vol.py:289` | `dm_test` | c | hardcoded lag-1: gamma0 + 2*gamma1 | no | dm_stat/p_val | no |
| 52 | `experiments/k526/k526_garch_midas.py:557` | `dm_test` | c | bw = max(floor(4*(n/100)^(2/9)), h) | no | dm/p | no |
| 53 | `experiments/k534/k534_copula_dcc.py:355` | `dm_test` | c | nw_l = ceil(n^(1/3)) | no | dm_stat/p_val | no |
| 54 | `experiments/k569/k569_piecewise_vt_validation.py:223` | `dm_test_nw` | c | opt_lag = max(1, int(4*(n/100)^(2/9))) | no | t/p | no |
| 55 | `experiments/k570/k570_earnings_season.py:253` | `dm_test_sharpe` | c | lag = int(n^(1/3)) | no | t/p | no |
| 56 | `experiments/k593/k593_window_cross_oos.py:132` | `dm_test` | c | for k in range(1, max(h,2))，權重 0.5 | no | dm_stat/p_value | no |
| 57 | `experiments/k593/k593_window_cross_oos_v2.py:109` | `dm_test` | c | for k in range(1, max(h,2))，權重 0.5 | no | dm_stat/p_value | no |
| 58 | `experiments/k595/k595_hybrid_multi_strategy.py:329` | `dm_test` | c | bw = int(n^(1/3)) | no | t/p | no |
| 59 | `experiments/k598/k598_adaptive_debounce.py:587` | `dm_test` | c | bw = int(n^(1/3)) | no | t/p | no |
| 60 | `experiments/k625/k625_hurst_volatility.py:583` | `dm_test` | c | max_lag = int(n^(1/3))（n>=30 guard） | no | dm_stat/p_val | no |
| 61 | `experiments/k684/k684_percentile_implementation.py:186` | `dm_test` | c | bw = ceil(n^(1/3)) | no | t/p | no |
| 62 | `experiments/k765/k765_xai_volatility.py:84` | `dm_test` | c | hardcoded 5 lags: range(1,6)，Bartlett w=1-k/6 | no | t/p | no |
| 63 | `experiments/k781/k781_mvf.py:565` | `dm_test` | c | bw = max(1, h) | no | **變體不一致**：回傳 (dm, p_value, harvey_t)，p_value 由『未修正』的 dm 算，但 PASS gate（line 807/828）用 harvey_t | no（次要） |
| 64 | `experiments/k783b/k783b_cross_asset_window.py:115` | `dm_test` | c | for k in range(1, max(h,2))，權重 0.5 | no | dm_stat/p_value | no |
| 65 | `experiments/k783c/k783c_cross_period_window.py:64` | `dm_test` | c | hardcoded lag-1: gamma0 + 2*gamma1 | no | t/p | no |
| 66 | `experiments/k785/k785_mf2_garch.py:285` | `dm_test` | c | for k in range(1, max(h,2))（無權重） | no | dm_stat/p_value | no |
| 67 | `experiments/k796v2/k796v2_vix_spike_taiwan.py:299` | `dm_test` | c | hardcoded lag-1 | no | t/p | no |
| 68 | `experiments/k821/k821_ssvs_variance_equation.py:795` | `dm_test` | c | max_lag = min(10, n//5) | no（除非 n<5） | dm_stat/p_val | no |
| 69 | `experiments/k841/k841_futures_realtime_vt.py:436` | `dm_test` | c | for k in range(h) —— h=1 -> 只取 gamma[0]（= 樣本變異數），var_d = gamma[0]/n | YES | k841_results.json: dm_tests.*.t_stat 與 harvey_significant=True（s2_vs_s1 t=10.82、s2_vs_s0 t=-7.13、s3_vs_s0 t=-1.97）；feed×5 + knowledge×2 | **YES** |
| 70 | `experiments/k895/k895_ssvs_arx_garch.py:876` | `dm_test_qlike` | c | bw = int(n^(1/3)) | no | t/p | no |
| 71 | `experiments/k910/k910_tci_vt_overlay.py:525` | `dm_test` | c | max_lag = int(n^(1/3)) | no | dm_stat/p_value | no |
| 72 | `experiments/k923/k923_copula_hedge_ratio.py:561` | `dm_test_hedge` | c | h_bw = floor(T^(1/3))（T>=30 guard） | no | t_stat/p_value/harvey_significant | no |
| 73 | `experiments/k960/k960_har_rv.py:511` | `dm_test` | c | hardcoded lag-1（巢狀 def） | no | dm_stat/dm_pval | no |
| 74 | `experiments/k980v2/k980v2.py:532` | `dm_test_hac` | c | max_lag = int(12*(T/100)^0.25) | no | dm_stat/p_value | no |
| 75 | `experiments/k987/k987_vix_nonlinear.py:131` | `dm_test` | c | for k in range(1, max(h,2))，權重 1-k/(h+1)=0.5 | no | t/p | no |
| 76 | `experiments/k989/k989_mf2_vix2.py:455` | `dm_test` | c | for k in range(1, max(h,2))（無權重） | no | t_stat/p_value | no |
| 77 | `experiments/research_google_trends_vol/research_google_trends_vol.py:286` | `dm_hac` | c | statsmodels OLS cov_type='HAC', maxlags=HAC_MAXLAGS=4 | no | tvalues[0]/pvalues[0] | no |
| 78 | `paper/vix-sufficiency/experiments/k821_ssvs_variance_equation.py:795` | `dm_test` | c | max_lag = min(10, n//5) | no（除非 n<5） | dm_stat/p_val | no |

## 結論

**78 個裡真正需要修的有 5 個。** 全部是 K1655 bug class 的實例：h=1 時 HAC 迴圈空轉或權重歸零，長期變異數退化成 iid 樣本變異數。

### 必修清單（依實質影響排序）

| 優先 | 站點 | 失效機制 | 對外結論 | 為什麼會改變已發表結論 |
|---|---|---|---|---|
| **P1** | `experiments/k1386/k1386.py:367` `dm_test_harvey` | `for k in range(1, max(1, h))`，呼叫端 `h=1` → `range(1,1)` 空迴圈 | README：`DM \|t\|=3.26 > 3.0`，宣告「HAR 顯著優於 fGN」（Harvey 門檻）；**feed×6** | `\|t\|=3.26` 只超過門檻 8%。QLIKE loss differential 若 acf(1)>0，補 HAC 後 `\|t\|` 下修即跌破 3.0 → 「顯著」變「不顯著」，已發表文章的核心宣稱直接翻掉。 |
| **P1** | `experiments/k841/k841_futures_realtime_vt.py:436` `dm_test` | `for k in range(h)`（不是 `range(1,h+1)`）→ h=1 只取 `gamma[0]`，即樣本變異數 | `k841_results.json`：`t_stat=10.82 / -7.13 / -1.97`，`harvey_significant=True`；**feed×5 + knowledge×2** | 這是**策略報酬差**的 DM（VT overlay），報酬差序列自相關是常態。整組 t 與 `harvey_significant` 旗標都建立在無 HAC 的變異數上；`t=-1.97` 這格離 2.0 只差 1.5%，補 HAC 後兩個方向都可能翻。 |
| **P2** | `experiments/k1379/k1379.py:359` `dm_test` | **完全沒有 autocovariance 迴圈** —— `gamma0 = mean(d²)-d̄²` 直接當長期變異數 | `k1379_results.json`：`dm_t=-1.19, p=0.234`（A4f vs HAR-RV，null）；**餵 Paper 9 (garch-x-vix) horse race** + feed×4 + knowledge×2 | 「本來就 null 所以安全」是錯的：負自協方差會讓 `\|t\|` 變**大**（k621 前例：acf(1)=-0.18 → `\|t\|` 2.26→3.64）。這支餵的是投稿中的論文 horse race，null 若翻成顯著，Paper 9 的 contribution 敘事要改。**另有第二個 bug**：HLN 因子寫成 `(T+1-2+1/T)/T`，h=1 的正確式是 `(T-1)/T`。 |
| **P2** | `experiments/k1525_hf_tail_risk_premium_vrp/...py:265` `dm_test` | `for k in range(1, max(1, h))` 空迴圈；且權重 `1-k/h` 在 h=1、k=1 時 =0（雙重退化） | README §4.3：`DM (HLN-corrected): t=-0.85, p=0.397, n=137` —— 「焦點 spec ES+VIX 未過 OOS gate」的核心論據 | 同上，null≠安全。月頻 RV、n=137，補 HAC 後 `\|t\|` 若上升到顯著，整篇的 headline 結論（RDSV 訊號無法轉成 OOS 預測力）就站不住。 |
| **P2** | `experiments/k1526_hf_tail_risk_premium_vrp/...py:265` `dm_test` | 與 k1525 逐字相同 | 同 k1525（README t=-0.85, p=0.397）；knowledge×1 | k1525 的重跑版。**修 k1525 必須同一輪修這支**，否則兩份 README 會分岔成不同數字。 |

### 會改變已發表結論的：3 個（k1386、k841、k1379）

k1386 與 k841 已進 feed（合計 11 次引用）；k1379 除 feed 外還餵 Paper 9 的 horse race 表。k1525/k1526 目前只在 knowledge，尚未進 feed，但 k1525 是那條研究線的 headline null —— 修完若翻轉，整個 K 的 verdict 要回溯更正。

### 一個 latent（不必現在修，但要記）

`experiments/k489/k489_vix_term_structure.py:200` 是**結構上的雙重退化**（`range(1, max(h,2))` 空迴圈 + 權重 `1-k/h` 在 k=1,h=1 時剛好 =0），但本檔的 horizon 只取 `{5, 21, 63}`（line 247-251），`h=1` 從未被呼叫，實際 bandwidth = h-1 ≥ 4 → **現況安全**。這支若被複製貼到 h=1 的情境就是下一個 K1655。

### 順手發現（非 K1655 class，不列必修）

- **`k781_mvf.py:565` 變體不一致**：`dm_test` 回傳 `(dm, p_value, harvey_t)`，其中 `p_value` 由**未修正**的 `dm` 算出，但 PASS gate（line 807/828）用的是 `harvey_t`。對外的 t 與對外的 p 來自不同變體。h=1 時 HLN 因子 = `sqrt((n-1)/n) ≈ 1`，實質差異可忽略，故不列必修；但這正是 brief 講的「哪個變體餵給對外結論」失效模式的輕症版。
- **註解與程式碼不符**：`k593`（兩支）、`k783b`、`k1525/k1526` 的註解都寫「bandwidth = h-1」，但 `k593`/`k783b` 實際用 `max(h,2)` 保底納了 lag-1（安全），只有 `k1525/k1526` 真的照註解退化。**註解不可信，必須讀程式碼** —— 這也是這輪不能靠 grep 收斂的原因。
- **矩形核（無 Bartlett 權重）**：`k1054`、`k1072`、`k152`、`k157`、`k437`、`k472`、`k494`、`k783c`、`k796v2`、`k960`、`k989` 用 `gamma0 + 2*gamma_k` 不加權。這不是 K1655 class（lag-1 有納入），但矩形核不保證半正定，長期變異數可能為負（多數站點被 clamp 到 `1e-20` 或 fallback 到 `gamma0`）。屬另一個 bug class，**本輪不處理**。

## 盲區分析（本輪**沒**覆蓋到什麼）

誠實列出這輪的邊界 —— 以下都**不在**本輪保證範圍內：

1. **沒有實測任何 loss differential 的自相關。** 本輪是純靜態 + 人工判讀。「h=1 是否退化」是**程式碼層**的確定判定（可信）；但「退化後 t 值實際會偏多少、結論會不會翻」是**經驗問題**，必須重跑實驗量 `acf(1)` 才知道。上面 5 個必修站點的「實質影響」欄位是**風險評估，不是已證實的錯誤**。K1655 的 acf(1)=0.68 與 k621 的 acf(1)=-0.18 只是說明「兩個方向都可能」，不能外推到這 5 個。
2. **只掃 `verdict=="unknown"` 這 78 個。** 稽核器判為 `canonical_like` / `hardcoded` / `h_lags_inclusive` / `delegates_to_canonical` / `not_a_dm_test` 的站點**完全沒看**。特別是 `not_a_dm_test`：稽核器用 `TEST_MACHINERY_RE` + `STAT_TARGET_NAMES` 啟發式排除，若某個真檢定的統計量存進了非典型變數名（例如 `score`、`z`），會被誤排除 → 這輪看不到。
3. **稽核器的 scan pattern 只涵蓋 `experiments/**/*.py` 與 `paper/*/experiments/**/*.py`。** DM 若寫在 `src/volpred/`、`scripts/`、`prototypes/`、`archive/` 或 notebook 裡，母體裡根本沒有。
4. **稽核器對「手算變異數」有 false negative —— 這輪實測到了。** `k1379` 用 `mean(d**2) - d_bar**2` 手算 gamma0，`PLAIN_VARIANCE_RE`（只認 `np.var` / `np.std`）認不出來，所以它被丟進 `unknown` 而不是 `no_hac`。**同樣的 pattern 若出現在稽核器判為其他 verdict 的檔案裡，這輪一樣抓不到。** 建議把 `mean(x**2) - mean(x)**2` 這個 idiom 加進 `PLAIN_VARIANCE_RE`。
5. **「對外引用的變體」只查到 `README.md` 與 `*_results.json`。** feed 文章正文、`knowledge.json` 的 K 條目內文、論文 `body.tex` 的表格數字，**沒有逐字比對**。我只確認了「這些 K 有沒有被 feed / knowledge / paper 引用」（用 grep 數命中次數），沒有確認「文章裡印的那個 t 值是不是就是這支 helper 算的那個」。中間可能還隔了一層手抄或重算。
6. **呼叫端 h 只查了必修候選 + 可疑站點。** 對於 bandwidth 已經 floor 到 ≥1 的站點（bucket a、以及 `n^(1/3)` 這類），h 是多少都不影響「不退化」的判定，所以沒有逐一去追呼叫端。若某站點存在我沒看到的第二個呼叫端、傳了異常的 h，判定不受影響（bandwidth 不依賴 h）—— 但這是推論，不是逐一驗證。
7. **`n` 太小的邊界沒有實測。** `k151`（`min(5, n//5)`）與 `k821`（`min(10, n//5)`）在 `n<5` 時 bandwidth=0 → 空迴圈，且兩者都**沒有 n guard**。我判定「實務 OOS 不會 n<5」，但沒有去讀資料確認每個呼叫端的樣本數。標為潛在風險而非必修。
8. **矩形核（無 Bartlett 權重）那 11 個站點沒有評估嚴重性。** 只記錄存在，沒判斷哪幾個實際產生了負的長期變異數。那是另一個 class。
