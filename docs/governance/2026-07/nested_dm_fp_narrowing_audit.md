# nested-DM 偵測器收窄 —— false-positive 全量稽核

- **日期**：2026-07-13
- **稽核器**：`scripts/audit_nested_dm_misuse.py`
- **Enforcement owner**：`scripts/tests/test_nested_dm_misuse_ratchet.py`
- **Baseline**：`storage/ops/nested_dm_misuse_baseline.json`
- **關切**：巢狀模型比較必須用 Clark-West (2007)；標準 DM/HLN 在巢狀虛無下偏向不拒絕。

---

## 0. 結論（先講結果）

**提案中的收窄規則必須否決，不可上線。**

被提議的收窄（stash commit `16df847b1`，`wip/nested-dm-fp-narrowing`）會讓 141 個站點
不再被 flag。逐一裁決後：

| 裁決 | 數量 | 意義 |
|---|---|---|
| **(a) 真 false positive** | **32** | 通用統計散文誤判；該檔的 DM 確實沒有巢狀對 |
| **(b) 真實巢狀誤用，被收窄漏掉** | **109** | 收窄的代價 —— 會靜默抹掉 109 筆真研究誠實債 |

109 遠超任務書「(b) >20 就停下來說清楚」的門檻。若照原方案上線，
`storage/ops/nested_dm_misuse_baseline.json` 會從 220 縮到 79，
**其中 109 筆是把真誤用當成「已修好」刪掉** —— 這比它想解決的 FP 噪音嚴重得多。

**實際落地的方案**（見 §4）：偵測器**維持保守（廣）**，32 筆 FP 改以
**逐筆具名、附理由的 adjudicated allowlist** 退場，由 ratchet 機械把關。

---

## 1. 掃描範圍（full population，無抽樣）

| 項目 | 值 |
|---|---|
| 掃描 glob | `experiments/**/*.py` |
| 掃到的 Python 檔 | **1,826** |
| 收窄前 flagged（= 原 baseline） | **220** |
| 收窄後 flagged | 79 |
| **差集（逐一裁決對象）** | **141** |
| scan_errors | 0 |

任務書寫的是 145，實測 **141**。差異來源已查明：stash 版偵測器除了收窄 nesting 證據，
還**同時放寬了 safe class**（`DM_DIAGNOSTIC_RE` 加 `secondary`、新增 `RAW_PERFORMANCE_ROLE_RE`），
且其 base 早於 main 的 `8b4cfd7c5`（K1698 role isolation），因此少了 `(?<!non-)` 反向守衛。
本稽核以 **main HEAD 偵測器**為 before 基準（其輸出與 baseline 220 逐檔完全一致，見 §5）。

> ⚠️ 附帶發現：stash 版會把 `experiments/k1025/k1025_v3.py` 用散文 marker 洗白成 safe。
> 本次不採納該放寬 —— 那正是 main 的 module docstring 明文禁止的
> 「用 marker 把真巢狀比較洗乾淨」。

---

## 2. 逐一裁決表

判準（採「移除=風險方向」的不對稱原則：無法確證非巢狀者一律留在 baseline）：

- **巢狀** = 一個模型是另一個的參數受限特例（係數設 0 或設相等即可還原）。
- **非巢狀** = 跨族比較、DM 作用在策略/組合報酬、或兩個特徵集只是重疊而非包含。

### 2.1 (a) 真 false positive —— 32 筆（可從 baseline 移除）

（見下表；主群是「DM 作用在策略報酬」，共 20 筆 —— 巢狀 CW 的問題域根本不含它們。）

| 站點 | 裁決 | 理由（為何是/不是巢狀） | 受檢 DM 對 |
|---|---|---|---|
| `experiments/K1049/K1049.py` | **(a) FP** | 三個模型 HAR-RV / GJR-GARCH / A4f-VIX² 互為不同族，無零約束關係 | HAR-RV vs GJR-GARCH vs A4f |
| `experiments/k1100b/k1100b.py` | **(a) FP** | 邊際分配同為 A4f-ASYM，差異只在 DCC vs 靜態 t-copula vs Clayton copula 的相依結構（非巢狀族） | DCC vs Copula-t vs Clayton |
| `experiments/k1100d/k1100d.py` | **(a) FP** | 同 k1100b：邊際相同，比的是 DCC vs 靜態/regime-switching copula 相依結構 | DCC vs RS-Copula |
| `experiments/k1254_rl_volatility_pilot/k1254_rl_volatility_pilot.py` | **(a) FP** | RL(PPO) policy 對 HAR-RV / GJR / rolling-RV，神經策略不是任何計量模型的參數約束 | RL vs HAR/GJR |
| `experiments/k1312/k1312.py` | **(a) FP** | GARCH-LSTM 是獨立神經參數化，僅「靈感取自」GJR，非其參數約束 | GARCH-LSTM vs GJR |
| `experiments/k1473_har_vs_dl_horizon_proxy/k1473.py` | **(a) FP** | LSTM / tiny-Transformer vs 線性 HAR，跨族比較 | LSTM/Transformer vs HAR |
| `experiments/k1535_ml_garch_adjudication_equity/k1535.py` | **(a) FP** | 僅有的 DM 是 HAR-RV vs GARCH(1,1) 與深度模型 vs 計量模型，皆跨族；巢狀對（GARCH-X vs GJR）未互比 | HAR vs GARCH; DL vs econ |
| `experiments/k1541_convertible_vol_management_beta_timing/k1541_convertible_vol_management_beta_timing.py` | **(a) FP** | strategy_dm_test 比的是可轉債組合實現報酬（vol-managed vs raw vs beta-replicated），非預測損失 | 策略報酬 |
| `experiments/k1595/k1595.py` | **(a) FP** | EWMA / HAR / Ridge / GJR / Transformer 各自獨立設定，無參數約束關係 | 多族 horse race |
| `experiments/k1624_rv_long_memory_vs_level_shifts/k1624_rv_long_memory_vs_level_shifts.py` | **(a) FP** | ARFIMA 分數積分 vs HAR 有限落後 OLS vs break-robust 變體，無有限樣本零約束 | ARFIMA vs HAR vs brk |
| `experiments/k230/k230_optimal_vt_param.py` | **(a) FP** | DM 作用在 VT 策略報酬序列（不同參數配置），非預測模型 | 策略報酬 |
| `experiments/k233/k233_three_asset.py` | **(a) FP** | dm_test_returns 直接比組合報酬 vs 50/50 baseline | 策略報酬 |
| `experiments/k359/k359_quantile_reg.py` | **(a) FP** | dm_test_returns 比 VT 策略報酬（QR-based vs 12/VIX） | 策略報酬 |
| `experiments/k435/k435_structural_break_garch.py` | **(a) FP** | 三個預測子同為 GJR(1,1)，只差訓練視窗子樣本，非係數約束 | 同模型不同視窗 |
| `experiments/k440/k440_vrp_strategy.py` | **(a) FP** | diebold_mariano_returns 比 VT 策略報酬 | 策略報酬 |
| `experiments/k537/k537_cross_asset_vol_momentum.py` | **(a) FP** | DM 比 CrossAsset overlay 策略報酬 vs 12/VIX | 策略報酬 |
| `experiments/k548/k548_leveraged_risk_parity.py` | **(a) FP** | DM 作用在槓桿/VT 組合的日報酬平方 | 策略報酬 |
| `experiments/k549/k549_multi_asset_expansion.py` | **(a) FP** | DM 比多資產 VT 組合報酬 vs 50/50 benchmark | 策略報酬 |
| `experiments/k558/k558_k553_taiwan_validation.py` | **(a) FP** | dm_test_harvey 比 hybrid-leverage 策略報酬 vs 8.63/VIX | 策略報酬 |
| `experiments/k559/k559_conditional_dispersion.py` | **(a) FP** | S1-S5 dispersion overlay 組合報酬 vs base_12vix | 策略報酬 |
| `experiments/k565/k565_btc_allocation.py` | **(a) FP** | BTC 配置變體組合報酬 vs 50/50 | 策略報酬 |
| `experiments/k570/k570_earnings_season.py` | **(a) FP** | 財報季權重 overlay 組合報酬 vs 12/VIX | 策略報酬 |
| `experiments/k574/k574_complete_strategy_backtest.py` | **(a) FP** | BH / VT / 槓桿變體之組合報酬兩兩比較 | 策略報酬 |
| `experiments/k680/k680_percentile_cross_oos.py` | **(a) FP** | VIX 百分位 vs 12/VIX 兩種權重策略報酬 | 策略報酬 |
| `experiments/k774/k774_all_weather_vt.py` | **(a) FP** | 全天候多資產組合報酬 vs 50/50 | 策略報酬 |
| `experiments/k786/k786_vt_insurance_premium.py` | **(a) FP** | VoV-conditional VT overlay 組合報酬 vs BH/12-VIX | 策略報酬 |
| `experiments/k796v2/k796v2_vix_spike_taiwan.py` | **(a) FP** | VIX-spike 權重 overlay 組合報酬 vs baseline | 策略報酬 |
| `experiments/k801/k801_event_surprise.py` | **(a) FP** | VIX-shock 權重 overlay 組合報酬 vs 12/VIX | 策略報酬 |
| `experiments/k807/k807_bond_stress_signal.py` | **(a) FP** | 債市壓力 overlay 組合淨報酬 vs BH/12-VIX | 策略報酬 |
| `experiments/k812/k812_us_taiwan_leadlag.py` | **(a) FP** | lead-lag 策略報酬 vs buy-and-hold 0050.TW | 策略報酬 |
| `experiments/k820/k820_event_risk_budgeter.py` | **(a) FP** | 事件日減碼 overlay 組合報酬 vs BH 50/50 | 策略報酬 |
| `experiments/k825/k825_conformal_var_proxy.py` | **(a) FP** | 同一 GJR sigma 下的不同 VaR 分位校準法（Normal/t/HistSim/conformal），互非參數約束 | VaR 校準法 |

### 2.2 (b) 真實巢狀誤用 —— 109 筆（**必須留在 baseline**）

這 109 筆是**收窄的代價**。每一筆的 raw DM/HLN 都真的落在巢狀對上，且餵進 verdict/claim。

| 站點 | 裁決 | 理由（為何是/不是巢狀） | 受檢 DM 對 |
|---|---|---|---|
| `experiments/K1038/k1038.py` | **(b) 真誤用** | GARCH 是 GJR 的 γ=0 受限版；GAS-t 是 GAS-t-Lev 的 leverage=0 受限版 | GARCH vs GJR; GAS-t vs GAS-t-Lev |
| `experiments/K1053/K1053.py` | **(b) 真誤用** | M2/M3 在 M1 的 tau 方程加一個 θ 項，M1 = θ=0 的受限版 | M2/M3 vs M1 |
| `experiments/K1655/K1655_vix_nfci_encompassing.py` | **(b) 真誤用** | VIX+NFCI 是 VIX-only 加一個 NFCI 迴歸項；raw dm_test/hln_dm 直接餵 encompass_pass | VIX+NFCI vs VIX-only |
| `experiments/k1003/k1003.py` | **(b) 真誤用** | A4f 的長期成分 tau 在 θ1=0 時退化為常數，模型收斂回 GJR | GJR vs A4f |
| `experiments/k1011/k1011.py` | **(b) 真誤用** | HAR+EQ / HAR+PCA 是 baseline HAR 加一個壓力指標迴歸項 | HAR vs HAR+EQ/PCA |
| `experiments/k1015/k1015.py` | **(b) 真誤用** | M3/M4 的 tau 是 M1 的 tau 加一個 θ·X² 項 | M1 vs M3/M4 |
| `experiments/k1019/k1019.py` | **(b) 真誤用** | M4(A4f) 是 GJR 加 VIX 驅動的 tau，VIX 係數為 0 時退化回 GJR | M4 vs M1(GJR-t) |
| `experiments/k1020/k1020.py` | **(b) 真誤用** | M5 的 tau = M2 的 tau 加 θ2·P(crisis)；M2 又巢狀於 M1(GJR-X) | M5 vs M2; M2 vs M1 |
| `experiments/k1021/k1021.py` | **(b) 真誤用** | t-fixed5/t-fixed8 是把自由度參數固定為等式約束的受限版 | t-joint vs t-fixed |
| `experiments/k1022/k1022.py` | **(b) 真誤用** | 兩個 A4f 變體都是 GJR 加 tau，θ1=0 時退化 | A4f vs GJR-t |
| `experiments/k1027/k1027.py` | **(b) 真誤用** | 同 K1003/K1022 的 A4f-nests-GJR 結構 | A4f-VIX² vs GJR-t |
| `experiments/k1065/k1065.py` | **(b) 真誤用** | 三組皆 GJR vs A4f（θ1=0 巢狀），DM t 值直接餵 H3 裁決 | GJR vs A4f (oc/on/close) |
| `experiments/k1080/k1080.py` | **(b) 真誤用** | 檔內明寫 GJR baseline vs A4f (tau=θ0+θ1·VIX²)，θ1=0 巢狀 | GJR vs A4f |
| `experiments/k1081/k1081.py` | **(b) 真誤用** | 同 K1080 的 GJR-vs-A4f 設計 | GJR vs A4f |
| `experiments/k1082/k1082.py` | **(b) 真誤用** | 同 GJR-vs-A4f 設計，跨 EWT/EWZ/FXI | GJR vs A4f |
| `experiments/k1084/k1084.py` | **(b) 真誤用** | HAR-RSk/RKt/SJ/Full 都是 HAR-RV 加額外 realized moment 迴歸項 | HAR-RV vs HAR-* |
| `experiments/k1085/k1085.py` | **(b) 真誤用** | A4f-COMBO 的 tau 含 VIX² 與 GVZ² 兩項，巢狀 A4f-VIX 與 A4f-GVZ；後者又巢狀 GJR | GJR/A4f-VIX vs A4f-COMBO |
| `experiments/k1088/k1088.py` | **(b) 真誤用** | A4f tau=θ0+θ1·X² 的 multiplicative GARCH-X，θ1=0 退化為 GJR | GJR vs A4f-* |
| `experiments/k1091/k1091.py` | **(b) 真誤用** | 同 K1088 的 A4f-VIX 結構，raw hac_dm_test 餵 Harvey verdict | GJR vs A4f-VIX |
| `experiments/k1096/k1096.py` | **(b) 真誤用** | M2-M5 全部保留 tau=θ0+θ1·VIX²·indicator，θ1=0 collapse 回 M1(GJR) | GJR vs A4f-Regime-* |
| `experiments/k1099/k1099.py` | **(b) 真誤用** | A4f_VIX/FX/COMBO 同 multiplicative GARCH-X 構造，pairwise_dm 對 GJR baseline | GJR vs A4f-* |
| `experiments/k1100f/k1100f.py` | **(b) 真誤用** | fit_prg = fit_a4f 加 4 個星期別 dummy（δ=0 即回 A4f） | DCC-A4f vs DCC-PRG |
| `experiments/k1100g_d3/k1100g_d3.py` | **(b) 真誤用** | M4 = M2 的 PRG kernel 加夜盤 exog 項 | M2 vs M4 |
| `experiments/k1100g_d4/k1100g_d4.py` | **(b) 真誤用** | 同 d3 的 M2/M4 巢狀對，逐年重跑 | M2 vs M4 |
| `experiments/k1100g_d5/k1100g_d5.py` | **(b) 真誤用** | M2_gap_* 是 M1 的 PRG kernel 加 gap² exog 項 | M1 vs M2_gap_* |
| `experiments/k1100g_d6/k1100g_d6.py` | **(b) 真誤用** | 同 d5 的 M1-vs-M1+exog 構造，延長樣本 | M1 vs M2_gap_total |
| `experiments/k1100g_d7/k1100g_d7.py` | **(b) 真誤用** | M_gap = M_base 多一個 ξ·gap² 係數（檔內自己用 LRT df=1 檢定） | M_base vs M_gap |
| `experiments/k1100g_d8/k1100g_d8.py` | **(b) 真誤用** | gap 項巢狀，另外 Hansen skew-t 在 λ=0 退化為對稱 Student-t | M_base vs M_gap; t vs skew-t |
| `experiments/k1100h/k1100h.py` | **(b) 真誤用** | M2/M3/M4 是 M1 加 1/2/5 個 intraday exog 項（檔內已用 LRT） | M1 vs M2/M3/M4 |
| `experiments/k1116/k1116.py` | **(b) 真誤用** | M1_AR1 是 M2_AR1_VIX 的 VIX 係數=0 受限版；M5_All 又是 M2 的超集 | M2 vs M1; M2 vs M5 |
| `experiments/k1116b/k1116b.py` | **(b) 真誤用** | 同 K1116 的巢狀 5-spec 設計 | IV-baseline vs M1/M5 |
| `experiments/k1116c/k1116c.py` | **(b) 真誤用** | base ⊂ vix ⊂ all 的巢狀 spec 鏈 | vix vs base/all |
| `experiments/k1116d/k1116d.py` | **(b) 真誤用** | 同 K1116c 的巢狀 spec 鏈，跨 ALFRED vintage 重跑 | vix vs base/all |
| `experiments/k1117b/k1117b.py` | **(b) 真誤用** | M6_all = M2_vix 的迴歸集加 5 個 alt-data 項 | M2_vix vs M6_all |
| `experiments/k1118/k1118.py` | **(b) 真誤用** | M5_All 是 M2_IV 的迴歸超集（加 EPU/finstress） | M2 vs M5 |
| `experiments/k1118b/k1118b.py` | **(b) 真誤用** | M1_AR1 ⊂ M2_AR1_IV ⊂ M5_AR1_All 的巢狀鏈 | M1 vs M2; M2 vs M5 |
| `experiments/k1119/k1119.py` | **(b) 真誤用** | M2-M5 皆 M1(AR1) 加項；另 A4f-DVOL 在 θ=0 退化為 GJR | M1 vs M2-M5; GJR vs A4f |
| `experiments/k1120/k1120.py` | **(b) 真誤用** | M4 = M1(AR1) 加 NFCI/ANFCI/STLFSI 三項 | M1 vs M4 |
| `experiments/k1120b/k1120b.py` | **(b) 真誤用** | M4_resid_* 明定為 M3_VIX_MOVE + NFCI_resid，是本檔 primary DM | M3 vs M4_resid_* |
| `experiments/k1125/k1125.py` | **(b) 真誤用** | M2/M3/M4 各為 M1 的特徵集加 OFI/交互項（真子集） | M1 vs M2/M3/M4 |
| `experiments/k1130/k1130.py` | **(b) 真誤用** | FEAT_M1 ⊂ FEAT_M3；另 regime vs no-regime 是門檻迴歸的巢狀約束 | M1 vs M3 |
| `experiments/k1135/k1135.py` | **(b) 真誤用** | Hansen skew-t 在 λ=0 精確退化為對稱 Student-t | M1 vs M2 (GAS) |
| `experiments/k1139/k1139.py` | **(b) 真誤用** | M1-M7 皆 M0(HAR-RV) 加 exogenous γ 項，M0 = γ=0 受限版 | M0 vs M1-M7 |
| `experiments/k1148/k1148.py` | **(b) 真誤用** | tau 含 θ_VIX 與 θ_EAV，兩者皆 0 時退化為 pure GJR | GJR vs 連續 EAV 模型 |
| `experiments/k1148_d1/k1148_d1.py` | **(b) 真誤用** | 同 K1148（binary EAV），θ=0 退化為 pure GJR | GJR vs binary EAV |
| `experiments/k1201/k1201.py` | **(b) 真誤用** | spec=all 是 spec=iv 加 5 個總經訊號的真超集 | iv vs all |
| `experiments/k1203/k1203.py` | **(b) 真誤用** | 同 K1201 的 iv ⊂ all 巢狀 spec | iv vs all |
| `experiments/k1241/k1241.py` | **(b) 真誤用** | M2 是 M1 的變異數方程加 φ·VIX²（GARCH vs GARCH-X 標準巢狀） | M1 vs M2; M2 vs M3 |
| `experiments/k1263/k1263.py` | **(b) 真誤用** | KAN 權重全 0 時 tau≡1，模型精確退化為 plain GJR baseline | GJR vs KAN-GARCH-MIDAS |
| `experiments/k1304/k1304.py` | **(b) 真誤用** | BMA 組合的 6 個成分含 GJR_t 本身，權重→1 時還原 benchmark | GJR_t vs BMA |
| `experiments/k1305/k1305.py` | **(b) 真誤用** | M3/M4/M5 是 M2 baseline 加 alt-data 迴歸項 | M2 vs M3/M4/M5 |
| `experiments/k1315/k1315_forecast_combination.py` | **(b) 真誤用** | 組合預測的兩個輸入就是 HAR-ABS 與 HAR-VIX，含 benchmark 本身 | HAR-VIX vs 組合 |
| `experiments/k1337/K1337.py` | **(b) 真誤用** | aug_yhat 用 X=[1, log_har, sig] 迴歸，是 HAR 加訊號的擴充 | HAR vs HAR+signal |
| `experiments/k1356/K1356.py` | **(b) 真誤用** | HAR_INV_NEWS = HAR_INV 特徵 + news_signal（真超集） | HAR_INV vs HAR_INV_NEWS |
| `experiments/k1357/K1357.py` | **(b) 真誤用** | HAR_VIX_VOL_SPREAD_ASYM 在 HAR_VIX_VOL 全部特徵上再加兩項 | HAR_VIX_VOL vs +SPREAD_ASYM |
| `experiments/k1358/K1358.py` | **(b) 真誤用** | HAR_VIX_AI_LABOR = HAR_VIX 特徵 + ai_news 交互項 | HAR_VIX vs HAR_VIX_AI_LABOR |
| `experiments/k1396/k1396.py` | **(b) 真誤用** | 檔內 docstring 明定 HAR-VIX = HAR + VIX²/252，單一迴歸項擴充 | HAR vs HAR-VIX |
| `experiments/k1465/k1465.py` | **(b) 真誤用** | F1 是 F2 的 gated 修正版，F2 = γ=0 的受限特例 | F1 vs F2 |
| `experiments/k1487/k1487.py` | **(b) 真誤用** | 各挑戰者皆 baseline 特徵集加 novel-risk 迴歸項 | HAR/HAR_VIX vs +Novel* |
| `experiments/k1492/k1492.py` | **(b) 真誤用** | full model = baseline(rv5_lag1) 加 redemption_pressure + peg_dev_max | baseline vs full |
| `experiments/k152/k152_liquidity_ms_garch.py` | **(b) 真誤用** | GARCH-X 把同一 GJR 預測乘上 exp(slope·exog)，slope=0 時還原 GJR | GJR vs GARCH-X |
| `experiments/k1523_realized_kurtosis_vol/k1523.py` | **(b) 真誤用** | H1-H3 各為對應 baseline 加 RKt 迴歸項 | HAR-* vs HAR-*+RKt |
| `experiments/k1525/k1525.py` | **(b) 真誤用** | OLS 預測迴歸 vs 歷史均值 baseline = 斜率全 0 的受限版 | OLS spec vs 歷史均值 |
| `experiments/k1525_hf_tail_risk_premium_vrp/k1525_hf_tail_risk_premium_vrp.py` | **(b) 真誤用** | Campbell-Thompson 設計：預測迴歸 vs 歷史均值即斜率=0 受限版 | OLS vs 歷史均值 |
| `experiments/k1526_hf_tail_risk_premium_vrp/k1526_hf_tail_risk_premium_vrp.py` | **(b) 真誤用** | 與 k1525 版位元相同的重複檔，同一巢狀對 | OLS vs 歷史均值 |
| `experiments/k154/k154_order_flow_imbalance.py` | **(b) 真誤用** | 調整後預測 = GJR 變異數乘 (a+b·OFI)，a=1,b=0 時還原 baseline | GJR vs GJR+OFI 調整 |
| `experiments/k1600/k1600.py` | **(b) 真誤用** | HARQ/HARQ-F 是 HAR 加 sqrt(RQ) 交互項（BPQ 2016），係數=0 退化為 HAR | HAR vs HARQ/HARQ-F |
| `experiments/k1616_cointegration_ect_har_rv/k1616_cointegration_ect_har_rv.py` | **(b) 真誤用** | Xect = HAR 設計矩陣再加 ect_lag 與 abs(ect_lag) 兩欄 | HAR vs HAR+ECT |
| `experiments/k1637/k1637.py` | **(b) 真誤用** | CONST（擴張均值）就是 HAR 的斜率全 0 受限版 | CONST vs HAR |
| `experiments/k1654/k1654.py` | **(b) 真誤用** | M2 的 score 在 λ=0 時代數上等於 M1，M1 是 λ=0 受限版 | M1 vs M2 (GAS) |
| `experiments/k1657/k1657.py` | **(b) 真誤用** | full 的設計矩陣 = feat_base + feat_full，baseline 是新增係數=0 的受限版 | baseline vs full |
| `experiments/k1666/K1666.py` | **(b) 真誤用** | models = {HAR, HAR+r1, HAR+r1+r2} 是嚴格巢狀的特徵擴充鏈 | HAR vs HAR_R1(_R2) |
| `experiments/k1668/K1668.py` | **(b) 真誤用** | CPU_FEATURES = BASE_FEATURES + 額外迴歸項 | HAR vs HAR_CPU |
| `experiments/k191/k191_put_call_ratio.py` | **(b) 真誤用** | GJR-GARCH-X 的 δ·exog 項在 δ=0 時還原 plain GJR | GJR vs GJR-X |
| `experiments/k195/k195_tda_deep_dive.py` | **(b) 真誤用** | garch_x 加 δ'·X（TDA 特徵），baseline 即 δ=0 | GJR vs GJR-X(TDA) |
| `experiments/k213/k213_signature_vol.py` | **(b) 真誤用** | augmented 預測由 GJR 預測加 path-feature 迴歸調整而來，係數=0 退回 baseline | GJR vs GJR+path |
| `experiments/k266/k266_amihud_validation.py` | **(b) 真誤用** | GARCH-X 的 δ·exog（Amihud）在 δ=0 時退化為 GJR baseline | GJR vs GJR-X |
| `experiments/k300/k300_vix_speed_validation.py` | **(b) 真誤用** | h_adjusted = h_baseline + δ·vix_speed，δ=0 即 baseline（兩階段修正） | baseline vs two-stage |
| `experiments/k355/k355_transfer_learning.py` | **(b) 真誤用** | Blend = w·finetune + (1-w)·target-only，w=0 時就是 DM 的 baseline 本身 | Target-only vs Blend |
| `experiments/k431/k431_stgarch.py` | **(b) 真誤用** | GARCH(1,1) 是 GJR-GARCH 的 γ=0 受限版 | GARCH vs GJR |
| `experiments/k431/k431_stgarch_v2.py` | **(b) 真誤用** | 同 v1：GARCH(1,1) 巢狀於 GJR-GARCH | GARCH vs GJR |
| `experiments/k450/k450_vrp_semivar_combined.py` | **(b) 真誤用** | M2=M1+vrp、M4=M3+vrp、M5=M4+vix+asym，皆逐項擴充 | M1 vs M2; M3 vs M4; M4 vs M5 |
| `experiments/k457/k457_weekly_vol.py` | **(b) 真誤用** | GARCH11 對 GJR_GARCH baseline，前者是 γ=0 受限版 | GARCH11 vs GJR |
| `experiments/k459/k459_weekly_vrp_cross_oos.py` | **(b) 真誤用** | vrp_model 的迴歸集 ['VRP','RV_lag'] 含 baseline 的 ['RV_lag'] | baseline vs vrp_model |
| `experiments/k471/k471_higher_moments.py` | **(b) 真誤用** | M2-M6 皆 M1(lagged_rv) 加 skew/kurt 等額外迴歸項 | M1 vs M2-M6 |
| `experiments/k473/k473_attention_vol.py` | **(b) 真誤用** | M2 ⊂ M3；M10 = M3 加 3 個 attention 迴歸項 | M3 vs M2/M10 |
| `experiments/k478/k478_entropy_vol.py` | **(b) 真誤用** | M2-M5 皆 M1 的特徵集加 entropy 迴歸項 | M1 vs M2-M5 |
| `experiments/k498/k498_earnings_vol.py` | **(b) 真誤用** | GARCH-X（season/month）在 δ=0 時退化為 baseline GJR | GJR vs GJR-X |
| `experiments/k508/k508_tw_price_limit.py` | **(b) 真誤用** | GJRX_* 在同一 GJR 遞迴上加 δ·X，baseline = δ=0 | GJR vs GJRX_* |
| `experiments/k583/k583_iv_surface.py` | **(b) 真誤用** | HAR-Slope/Curvature/Surface/Full 皆 HAR-ABS 加額外迴歸項 | HAR-ABS vs HAR-* |
| `experiments/k790v2/k790v2_taiwan_price_limit.py` | **(b) 真誤用** | GJR-GARCH-X 加 exogenous dummy 到變異數方程，δ=0 即 baseline | GJR vs GJR-X |
| `experiments/k791/k791_overnight_intraday.py` | **(b) 真誤用** | GJR-X 加 r²_overnight 為 exogenous 迴歸項 | GJR vs GJR-X |
| `experiments/k813/k813_smooth_transition_garch.py` | **(b) 真誤用** | 檔內自陳 STGARCH 在 γ_transition→0 時退化為 GJR（並用 LRT df=6） | GJR vs STGARCH |
| `experiments/k862/k862_bidask_spread_vol.py` | **(b) 真誤用** | HAR-S = HAR 加 spread 迴歸項；VIX-only ⊂ Spread+VIX | HAR vs HAR-S |
| `experiments/k868/k868_har_day_night.py` | **(b) 真誤用** | HAR-DN-Ratio = HAR-RV 加 night_ratio；HAR-RV 是 HAR-DN 的係數相等約束版 | HAR-RV vs HAR-DN(-Ratio) |
| `experiments/k878/k878_dollar_index_vol.py` | **(b) 真誤用** | B/C/E 是 A(vix_only) 加 DXY 迴歸項 | A vs B/C/E |
| `experiments/k883/k883_taifex_tick_prg.py` | **(b) 真誤用** | PRG_Extended 加 leverage 項 γ0/γ1，γ=0 時退化為 PRG_Basic | PRG_Basic vs PRG_Extended |
| `experiments/k887/k887_financial_early_warning.py` | **(b) 真誤用** | OOS 段落直接比 y~VIX（受限）與 y~VIX+FSI（非受限）的預測誤差 | VIX vs VIX+FSI |
| `experiments/k891/k891_dcc_portfolio_var.py` | **(b) 真誤用** | DCC 的 Q 遞迴在 a=b=0 時精確退化為常數相關模型 | ConstCorr vs DCC |
| `experiments/k908/k908_mfgjr_student_t_var_es.py` | **(b) 真誤用** | MF-GJR 的 tau 在 θ1=0 時為常數，模型退化為重參數化的 GJR | GJR vs MF-GJR |
| `experiments/k914/k914_overnight_intraday_mfgjr.py` | **(b) 真誤用** | Model B/D 明為 Model A 的長期成分加一個迴歸項（θ2=0 退回 A） | A vs B/D |
| `experiments/k944/k944.py` | **(b) 真誤用** | 同 K908/K914 的 MF-GJR-nests-GJR 結構（δ1=0） | GJR vs MF-GJR |
| `experiments/k945/k945.py` | **(b) 真誤用** | QH 的避險比在估計均值 μ=0 時代數上退化為 MV 的避險比 | MV vs QH |
| `experiments/k948/k948.py` | **(b) 真誤用** | OLS/Ridge/LASSO 在斜率全 0 時退化為歷史均值 —— 正是 Clark-West 的經典設定 | 歷史均值 vs OLS/Ridge/LASSO |
| `experiments/k980/k980_threshold_garch.py` | **(b) 真誤用** | Threshold-GJR 是 GJR baseline 的雙 regime 參數相等約束版；GJR+VIX dummy 是 δ=0 約束版（主線程自審） | GJR vs TGJR / GJR+dummy |
| `experiments/k_repo_basis_funding_stress_gate_duration_2026_06_14/k_repo_basis_funding_stress_gate_duration_2026_06_14.py` | **(b) 真誤用** | 檔內 design 明寫 baseline=AR(1)、full=AR(1)+stress index | baseline vs full |
| `experiments/order_flow_vol/order_flow_vol.py` | **(b) 真誤用** | GARCH-X 預測 = plain GJR 變異數乘 (截距+斜率·X)，斜率=0 時還原 | plain GJR vs GARCH-X |
| `experiments/predictive_model_selection/predictive_model_selection.py` | **(b) 真誤用** | Adaptive 每日就等於 GJR 或 GARCH 其中之一（且 GARCH 是 GJR 的 γ=0 受限版） | Adaptive vs Fixed-GJR/GARCH |
| `experiments/research_rgarch_carr_sk_realized_garch_carr_2025/research_rgarch_carr_sk_realized_garch_carr_2025.py` | **(b) 真誤用** | 各模型皆 HAR_FEATURES 加特徵區塊，rgarch_carr_sk_proxy 是 har_range/har_sk 的真超集 | HAR vs +RANGE/SK/ASYM |

---

## 3. 為什麼收窄規則本身要被否決（root cause）

任務書假設「FP 來自 nesting 證據太寬」，因此收窄 nesting 證據。**實測推翻了這個假設。**

量測（可重跑，見 §5）：把 stash 的**純精度修正**（bibliographic 過濾 +
`full_wald` / `full_results` 那類 AST subset-build 收緊）單獨套用到 main 偵測器上 ——
**一個站點都沒掉，仍然 220**。

也就是說：**141 個站點全部是被「散文詞彙收窄」那一條殺掉的**
（`BASE_WORDS`/`AUG_WORDS` 從 `base|restricted|small|parsimonious|null` ×
`aug|full|unrestricted|large|challenger` 縮成只剩 `base(line)` × `aug(mented)`）。

而這條散文 channel 正是本 repo 抓到真巢狀債的**唯一**通道 —— 因為真正的巢狀關係大多
**不寫在變數命名裡**，而藏在模型設定中：

- `A4f` 的 `tau = θ0 + θ1·VIX²` 在 θ1=0 時退化為 `GJR`（K1003/K1022/K1065/K1085/K1088/K1099…共 20+ 筆）
- `MF-GJR`、`GARCH-X`、`STGARCH`、`Threshold-GJR` 對 `GJR` 的退化
- Hansen skew-t 在 λ=0 退化為 Student-t
- 預測迴歸 vs 歷史均值（斜率全 0）—— 正是 Clark-West 的原始設定
- 兩階段修正 `h_adj = h_base + δ·signal`

這些**沒有任何 `aug_cols = base_cols + [...]` 形式的 AST 證據可抓**。
要求「AST 證明 container 構成關係」等於要求一種本 repo 幾乎不使用的寫法。

**教訓（bug class 級）**：偵測器的 recall 靠散文、precision 靠 AST 時，
**收窄散文 = 直接砍 recall**。想降 FP 必須在**別的維度**下手（見 §4），
不能動唯一的 recall 來源。

---

## 4. 實際落地的方案

### 4.1 偵測器（`scripts/audit_nested_dm_misuse.py`）

只採納**能被單元測試證明、且零 recall 代價**的一項精度修正：

- `BIBLIOGRAPHIC_NESTED_RE` —— 參考文獻標題
  `"Tests of Equal Forecast Accuracy and Encompassing for Nested Models"`（Clark-West 論文名）
  只是書目，不代表這個檔在比巢狀模型。單元測試：
  `test_bibliographic_nested_title_is_not_local_nesting`。

**未採納**（且刻意不留）：散文詞彙收窄、`paired_prefixes` 刪 restricted/unrestricted、
AST subset-build 收緊、safe class 放寬。理由分別是：前二者砍掉 109 筆 recall；
第三項在現有 population 上**零作用且其單元測試在廣散文下無法通過**（= 無法驗證的程式碼，
依 anti-stacking 不留）；第四項會用散文 marker 洗白真站點。

### 4.2 FP 退場機制 —— adjudicated allowlist

32 筆 FP 寫進 `storage/ops/nested_dm_misuse_baseline.json` 的 `reviewed_nonnested`，
**每筆帶 `site` / `reason` / `dm_pairs` / `adjudicated_at` / `audit`（指回本報告）**。
ratchet 的 `affected` = `偵測器 flagged` − `allowlist`。

這與被否決的「檔內 marker」有本質差異：
marker 是**作者自助**把自己的檔洗白；allowlist 是**治理資料**裡一筆具名、附理由、
可被 review 的裁決紀錄。

### 4.3 機械 gate（enforcement owner 唯一，不疊層）

`scripts/tests/test_nested_dm_misuse_ratchet.py` 新增：

| 測試 | 擋住什麼 |
|---|---|
| `test_baseline_only_contains_active_sites`（訊息強化） | **有人再次收窄偵測器** → 109 筆 baseline 站點變 stale → CI 紅 |
| `test_reviewed_nonnested_entries_carry_an_adjudication` | allowlist 條目沒有理由 / 沒有裁決日期 / 沒指回稽核報告 |
| `test_reviewed_nonnested_cannot_silence_a_baseline_site` | 有人拿 allowlist 去消掉已凍結的巢狀債 |
| `test_reviewed_nonnested_sites_are_still_flagged` | allowlist 留下不再被 flag 的死條目（會遮蔽未來 regression） |

最關鍵的是第一條：**任何未來重演這次收窄的 PR 都會被 CI 擋下**，
因為 109 筆真誤用會立刻變成 stale baseline。

### 4.4 Baseline 數字

| 欄位 | 收窄前 | 現在 |
|---|---|---|
| `count`（active） | 220 | **188** |
| `exposed_count` | 111 | 96 |
| `diagnostic_only_count` | 109 | 92 |
| `reviewed_nonnested_count` | — | **32** |

188 = 109 筆 (b) 真誤用 + 79 筆原本就被收窄後偵測器保留的站點。
220 = 188 + 32。**沒有任何 (b) 站點被移除。**

---

## 5. 可驗證證據（任何人可重跑核對）

```bash
# (1) main 偵測器輸出 == 原 baseline 220（逐檔一致，非只比數量）
git stash && uv run python scripts/audit_nested_dm_misuse.py --json /tmp/before.json
git stash pop
jq -r '.findings[].file' /tmp/before.json | sort > /tmp/before_aff.txt
jq -r '(.active.exposed + .active.diagnostic_only)[]' \
   storage/ops/nested_dm_misuse_baseline.json | sort > /tmp/base.txt
# 收窄前：diff 為空

# (2) 現行偵測器 flagged 220，扣掉 32 筆 allowlist == baseline 188
uv run python scripts/audit_nested_dm_misuse.py --json /tmp/now.json
jq '.affected_count' /tmp/now.json                                   # => 220
jq '.reviewed_nonnested_count, .count' storage/ops/nested_dm_misuse_baseline.json  # => 32, 188

# (3) 109 筆 (b) 一個都沒漏（row-count invariant）
jq -r '(.active.exposed + .active.diagnostic_only)[]' \
   storage/ops/nested_dm_misuse_baseline.json | sort | wc -l          # => 188

# (4) allowlist 與 active 不相交、且每筆仍被偵測器 flag
uv run --extra dev python -m pytest scripts/tests/test_nested_dm_misuse_ratchet.py -q  # => 21 passed
```

**Row-count invariant**：`count(220, 偵測器 flagged) = count(188, baseline active) + count(32, allowlist)`。
三者任一變動而其他兩者沒跟著變，ratchet 就會紅。

---

## 6. 盲區分析（本稽核**沒有**覆蓋到什麼）

誠實揭露，避免把本報告當成比它實際更強的保證：

1. **本稽核只裁決「收窄後會掉的 141 個站點」，不重新裁決留下的 79 個。**
   那 79 個仍在 baseline 中（未動），但本輪沒有逐一確認它們是否也含 FP。
   → 若要宣稱「baseline 內全是真債」，需要另一輪對 79 個的全量裁決。

2. **32 筆 (a) 的「非巢狀」是就『該檔目前的 DM 對』而言。**
   若日後有人在同一檔加入新的 DM 比較（例如在策略回測檔裡補一個預測模型 horse race），
   allowlist 會讓它靜默通過。→ `test_reviewed_nonnested_sites_are_still_flagged`
   只擋死條目，**擋不住這種「檔內新增巢狀對」**。這是已知殘留風險，
   緩解方式是 allowlist 條目記了 `dm_pairs`，review 時可比對。

3. **偵測器仍是靜態分析，不 import 實驗程式碼。**
   跨檔案、經由 helper module 或 config JSON 才組出的巢狀關係，
   散文 channel 抓不到就漏。本 repo 的 `k1698` 類（明確標 nonnested 的 gate）已由
   main 的 `(?<!non-)` 守衛處理，但一般性的跨檔巢狀仍是盲區。

4. **(b) 的裁決以「模型設定是否為參數受限特例」為準，未逐一重跑數值驗證。**
   例如 `A4f` 在 θ1=0 是否**精確**退化為 `GJR`（而非僅近似），是讀 code 的代數判斷。
   個別檔若有重參數化細節，可能讓「巢狀」程度弱於本表所述。
   → 但方向是保守的：疑似巢狀就留在 baseline，不會漏放。

5. **109 筆 (b) 目前只是「被凍結為債」，本輪沒有修任何一筆。**
   baseline 的語義是「凍結既有債務，不是宣稱每個站點的數值結論都錯」。
   真正的修復（改用 Clark-West，或把 raw DM 降級為 diagnostic）是後續 backlog。

---

## 7. 後續 backlog（建議）

1. **109 筆 (b) 的分批修復**：優先 `exposed`（96 筆，結論已對外）而非 `diagnostic_only`。
   修復手段：squared-error 用 Clark-West (2007)；QLIKE/pinball 不可直接套 MSPE-CW，
   需 general-loss encompassing 或 recursive bootstrap。
2. **對留下的 79 筆做同等級的全量裁決**（補上 §6.1 的盲區）。
3. **不要再嘗試用詞彙收窄降 FP** —— 本報告已證明那條路會砍掉 recall。
   若要降 FP，正確方向是**在 DM channel 上把「策略報酬 DM」排除**
   （20/32 的 FP 屬此類，且方法論上本就不在巢狀 CW 的問題域內）。
   本輪未做，是因為靜態上難以在不誤傷 `k945`（避險比 QH/MV 巢狀，DM 作用在避險後報酬）
   這類站點的前提下寫出安全判準 —— 需要獨立設計 + 以本報告的 (b) 集合當 regression guard。

---

## 8. 2026-07-14 補充稽核：paired-loss HAC dataflow

第三角色（fixed rolling、bounded-memory、unconditional GW/DM）實作時，對抗性審查發現
舊 detector 只認 `loss_diff` / `dloss` 等少數變數名。像
`delta = err_aug - err_base; OLS(delta, ...).fit(cov_type="HAC")` 的等價
unconditional loss-mean test 可以完全躲過。新 AST channel 追蹤「augmented/base 成對差值 →
HAC/OLS/mean test」後，多抓到 11 個既有檔；本輪逐檔追到實際 claim sink，而不是把新增
偵測結果直接塞進 baseline。

### 8.1 新增 active debt（8，皆 exposed）

| site | 巢狀關係與 raw test | claim sink |
|---|---|---|
| `experiments/k1351/k1351.py` | `base_cols` / `aug_cols = base + oil features`（448–457），QLIKE baseline−augmented loss 後跑 Newey-West mean t（496–503） | `pass_gate` 直接要求 HAC t > 3（508–515），再決定 verdict（605–625） |
| `experiments/k193/k193_copula_tail_dep.py` | GARCH+TDA 的 `(alpha, beta, gamma)=(0, 1, 0)` 可還原 GARCH baseline（489–498、620–633）；QLIKE DM/HAC（679–699） | `dm_pval` 直接決定 NULL/MARGINAL/POSITIVE（973–991） |
| `experiments/k258/k258_skew_dynamics.py` | GJR baseline 對 `[1, GJR forecast, SKEW feature]` augmented OLS（431–449、502–507），QLIKE DM/HAC（512–540） | `garchx_passes` 直接餵總結論（915–943） |
| `experiments/k367/k367_short_interest.py` | `VIX+RV` baseline 對 `VIX+RV+SH/SPY` augmented（617–626），raw iid mean-loss t（663–674） | `dm_p < .05` 參與結論（811–817） |
| `experiments/k430/k430_vrp_predictability.py` | lagged-RV baseline 對 VRP augmentation（183–199、260–266），HAC loss-mean DM（294–326） | M4 DM 顯著性直接寫入 conclusions（578–609） |
| `experiments/research_hedge_fund_alpha_dispersion_regime_strategy_etf/research_hedge_fund_alpha_dispersion_regime_strategy_etf.py` | `aug_cols = base_cols + STRATEGY_SIGNAL_COLS`（524–526），QLIKE/MSE HAC mean tests（341–360） | `positive_harvey` 決定 verdict/conclusion（566–595） |
| `experiments/research_nbfi_proxy_etf_vol_eu_fsb_2026_stress_test/research_nbfi_proxy_etf_vol_eu_fsb_2026_stress_test.py` | `aug_cols = base_cols + run_pressure_lag1`（491–493），QLIKE/MSE HAC mean tests（371–395） | variance-cell `qlike_dm_t` 決定 verdict/conclusion（535–564）；correlation cell 雖是 diagnostic-only，不能替主要 variance cells 豁免 |
| `experiments/research_tips_breakeven_volatility_corporate_bond_return/research_tips_breakeven_volatility_corporate_bond_return.py` | 兩個 target 都是 `aug_cols = base_cols + VOL_COLS`（450–458、509–518），QLIKE/MSE HAC mean tests（283–302） | `qlike_dm_t > 3` 決定 mixed-positive/null conclusion（561–591） |

這 8 筆只被凍結成既有債務；本補充稽核沒有替它們改數字或結論。

### 8.2 新增 reviewed-nonnested（3）

| site | 裁決 |
|---|---|
| `experiments/k570b/k570b.py` | volatility-targeting 策略 vs baseline 的投資組合日報酬差；不是巢狀 forecast-loss comparison。 |
| `experiments/k671/k671_vix_roll_yield.py` | VIX roll-yield 策略 vs 12/VIX baseline 的投資組合日報酬差；不是預測模型的受限/非受限 pair。 |
| `experiments/rate_hike_vt_experiment/rate_hike_vt_experiment.py` | 升息期 VT 策略 vs baseline 的投資組合日報酬差；不是 nested forecast loss。 |

補充後的 ratchet invariant：`231 flagged = 196 active + 35 reviewed_nonnested`；
active 分成 `104 exposed + 92 diagnostic_only`。三個 strategy-return FP 均保留逐檔
`dm_pairs` 裁決，不能靠一般詞彙豁免洗掉未來新增的 forecast comparison。

---

## 9. 2026-07-14 第三角色：fixed-memory unconditional GW/DM

K1709 rev3 證明原本的 two-role model 不完整：巢狀模型的 raw DM 不能直接裁決，但在
**整條 forecasting method 都是 bounded-memory 的 paired fixed rolling window** 時，
GW (2006) Sec. 3.4 的 unconditional special case 正是 HAC 標準化的平均 loss
differential，公式呈 DM form。把誠實的「primary unconditional GW/DM」文字改回模糊的
「GW gate」不是修復；ratchet 現在承認第三角色
`primary_unconditional_gw_dm_fixed_memory`，但 declaration 本身沒有豁免力。

接受第三角色前，auditor 逐一要求：

1. literal、versioned、cell-level manifest，列出每個 claim-bearing nested pair；
2. base/aug 的 fixed window、complete-case mask、training schedule、origin schedule、label
   embargo 完全相同，上游 predictor stages 也都只有有限記憶；
3. runtime 保存 paired unadjusted loss differential、Bartlett HAC、canonical bandwidth、
   finite-positive LRV、standard-normal reference 與 unconditional average-loss estimand；
4. manifest、runtime primary inventory、registry inventory、Holm p 值、gate flag 與 verdict
   counts 精確一致，只有全證據成立的 record 可 `feeds_gate=true`；
5. reader-facing claim 就地寫明 unconditional，並明示 conditional/regime-offsetting effects
   未測且未排除；
6. trusted main checkout 的外部 PASS receipt 綁定 reviewed commit、source、manifest、runtime、
   exact primary cells 與整個 claim surface 的 SHA-256；
7. declaration 缺欄、mixed fixed/expanding、expanding preprocessing、schedule/mask 漂移、
   truthy gate、shadow gate、conditional wording、stale receipt 或 commit-byte mismatch
   一律 fail closed。

獨立 rev5 review 另抓到一個原 gate 的盲點：tracked Figure 5 還留著舊 scope label，
但 review certification 與第三角色 receipt 當時只發現 Python／README／results JSON，
PNG 完全不在 hash inventory。這不是「圖不在 brief」可以豁免的問題，因為 README 直接把
圖交給讀者。`scripts/experiment_claim_surface.py` 現為兩個 gate 的共同、stdlib-only
discovery owner；除 code/prose/results 外，也納入 PNG/JPEG/SVG/WebP/GIF/PDF。測試固定了
兩個方向：審後新增 reader-facing figure 必須使 certification 失效；manifest 漏列任何
既有 figure 必須使第三角色失效。

目前 regression suite：

```text
scripts/tests/test_nested_dm_misuse_ratchet.py
scripts/tests/test_experiment_gates.py
scripts/tests/test_experiment_certification.py
=> 129 passed
```

第三角色仍不是密碼學證明：外部 receipt 的信任根是 main checkout 的治理與獨立 reviewer。
它解決的是「candidate 自填 marker 就能自我豁免」與「reviewed bytes 漂移」；若 trusted main
本身遭未審修改，仍需正常 code review、branch protection 與 CI 保護。

### 靜態威脅模型界線

這個 auditor 是**保守的 accidental-bypass 靜態 ratchet，不是 Python sandbox**：它不 import、
不執行候選實驗，也不宣稱能解任意 alias、反射、動態字串或跨函式資料流。它會攔截 AST
可直接證明的模組綁定（含一般控制流、`global`、current-module mapping/object、built-in
mapping mutator 與 literal `exec`/`eval`）；import-only reference 則不算 declaration。

這個界線不形成第三角色的 escape hatch。任何動態或別名寫法都**不能取得** fixed-memory
角色；接受條件仍是唯一一個 top-level AST-literal manifest，接著逐項通過 source、runtime、
claim-surface 與 trusted external receipt 驗證。上文的「fail closed」精確指這條 acceptance
protocol：一旦 direct declaration 被辨識，任何證據錯誤都禁止退回較鬆的 lexical marker。
若未來要把 auditor 升級成惡意 Python 的語義分析器，必須另立 sandbox／data-flow threat
model，不能把那個尚未承諾的能力冒充成本 ratchet 已有的保證。
