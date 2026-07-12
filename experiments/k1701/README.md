# K1701 — Realized dispersion 對指數波動率與尾部風險的預測力

## 結論

**正式 verdict：`INCONCLUSIVE_NO_EXACT_NULL_CLAIM`。**

這次修訂推翻舊版「NULL 已證實」的推論強度。HAR 與 HAR + `rdisp` 是巢狀模型；舊版把
expanding-window raw Diebold–Mariano 檢定接到主 gate，會在虛無假設下偏向較小模型，不能用來承載
「沒有增量預測力」。本版改成：

1. 兩模型使用完全相同的完整樣本與固定 756 筆 rolling estimation window；
2. 用 Giacomini–White（2006）bounded-window test 比較 Patton QLIKE；
3. 另以預先指定的 **1% 相對 QLIKE 改善**作 material-gain exclusion，反轉「證明沒有用」的舉證責任；
4. raw DM 僅保留為 expanding-window 診斷，不進任何巢狀模型 verdict。

正式 2 資產 × 3 horizon 家族中：

- 正向 GW discovery gate：**0/6**；
- 方向上改善：3/6，但最大僅 +0.685%；
- Holm 校正後能排除至少 1% 改善：**0/6**；
- 所以既不能說有穩健增量，也不能說已證明 exact null／排除實質增益。

不過，舊版最重要的識別結果仍成立：`rdisp` 在含 index RV 的 HAR 中，與「成分股平均波動水準」是同一
regressor span 的重參數化。先控制水準後，再加入真正的離散度測度（平均相關 `rho`、橫斷面變異係數
`csvd_rel`），12 格 MSE / Clark–West + BH-FDR **0/12 通過**。因此較窄而誠實的結論是：

> 本資料沒有提供「真正離散度在波動水準之外仍有穩健增量預測力」的證據；但 primary QLIKE 家族仍是
> inconclusive，不能升格成模型完全等效或至少 1% 增益已被排除。

## Data & Methodology

| 項目 | 內容 |
|---|---|
| 方法論類型 | empirical；樣本外 forecast comparison，不作因果宣稱 |
| 價格來源 | yfinance，`auto_adjust=True` adjusted close |
| 名單來源 | Wikipedia S&P 500 / 臺灣 50 現行名單與歷史納入、剔除表 |
| 樣本期間 | 2010-01-04 至 2026-07-10 |
| SPX 樣本 | 4,153 個可計算 dispersion 的交易日；每日成分股中位數 439（346–503） |
| TW50 樣本 | 4,038 日；每日成分股中位數 48（44–51） |
| 正式 OOS 數 | SPX 3,353–3,387；TW50 3,134–3,271，依 horizon 與 zero-RV filter 不同 |
| Seed | 42；bootstrap 每格用可重現的衍生 seed |
| 主 target | t+1 至 t+h 的平均日變異數，h = 1 / 5 / 22 |
| 基準 | log-HAR：`l_rv_d`, `l_rv_w`, `l_rv_m` |
| 增廣 | HAR + `l_rdisp`；固定 756 筆 rolling window |
| 主 loss | Patton QLIKE：`actual/pred - log(actual/pred) - 1` |
| 主檢定 | Giacomini–White equal unconditional predictive ability；HAC lag 取 canonical bandwidth 且至少 h−1 |
| 多重檢定 | 正向發現用 BH-FDR；1% material-gain exclusion 用 Holm-FWER |
| 結果寫入 | temp file → `json.load` 驗證 → `os.replace` 原子替換 |

### 訊號與 proxy 邊界

- `idx_vol`：指數過去 22 日 realized volatility。
- `avg_vol`：逐時點成分股過去 22 日 realized volatility 的等權平均。
- `rdisp = avg_vol / idx_vol`：預先指定 proxy；它混合了成分股波動水準與相關結構。
- `rho`：由等權投組 realized variance 推回的平均相關 proxy。
- `csvd_rel`：成分股 realized volatility 橫斷面標準差／平均值。

S&P 500 / 0050 是市值加權指數，但 `avg_vol` 與 `rho` 使用可取得的等權成分股資料；因此本實驗是免費
資料 proxy diagnostic，不等同可交易的 options dispersion book，也不能量出 correlation risk premium。

### Point-in-time 名單與殘留 survivorship bias

名單用歷史變動表倒推，避免把今日成分股直接塞回歷史；但 yfinance 對已下市 ticker 覆蓋不完整。SPX
覆蓋率由 2010 年 68.63% 升至 2026 年 99.80%；TW50 由 92% 升至 100%。缺失公司不是隨機樣本，偏誤
方向不確定。R1 高覆蓋率子樣本保留作 secondary robustness，不能消除 vendor-grade PIT 資料缺口。

TW50 價格另走 canonical `clean_tw50_data`，修復 Yahoo 0050.TW 2014-01-02 的假 1:4 split；清理前最大
絕對 log return 1.389，清理後 0.153，共調整 1,238 個價格點。成分股異常日報酬門檻固定為 |log r|>1.0；
本輪 SPX / TW50 分別遮罩 47 / 1 筆。

## 為什麼不能再用 expanding raw DM

巢狀模型在虛無假設下，大模型多估的係數會帶入 forecast noise；raw DM 的 equal-loss 常態近似會退化，
未拒絕特別容易被誤讀成「沒有資訊」。Clark–West 修正的是 MSPE，不能貼標成 QLIKE general-loss test。

Giacomini–White 的解法是把**整個 forecasting method**納入比較，並讓 estimation uncertainty 在漸近下不
消失；這要求 estimation window 有界。因此本版正式路徑固定使用 756 筆 rolling window。舊 expanding
結果仍可描述有限樣本 loss 方向與 ACF，但 `feeds_gate=false`。

## 正式 primary QLIKE 結果

負的 GW z 代表 HAR + rdisp 較好。Discovery gate 為：QLIKE 改善 > 0、GW z < −3、BH q < 0.05。

| 資產 | h | OOS n | QLIKE 改善 | GW z | BH q | Gate |
|---|---:|---:|---:|---:|---:|---|
| SPX | 1 | 3,386 | −0.009% | +0.022 | 0.982 | fail |
| SPX | 5 | 3,387 | +0.247% | −0.140 | 0.982 | fail |
| SPX | 22 | 3,353 | −0.649% | +0.366 | 0.982 | fail |
| TW50 | 1 | 3,134 | +0.685% | −1.069 | 0.982 | fail |
| TW50 | 5 | 3,271 | +0.646% | −0.214 | 0.982 | fail |
| TW50 | 22 | 3,238 | −5.132% | +0.801 | 0.982 | fail |

QLIKE 改善符號與 GW z 六格全部一致；0/6 通過，不能宣稱 positive predictive ability。

### 1% material-gain exclusion

每格檢定的 H0 是「增廣模型的 expected QLIKE 至少改善 1%」。只有正向 exclusion z 且 Holm p<0.05，
才可排除這個實質增益。這不是 exact-equivalence test。

| 資產 | h | exclusion z | Holm p | 排除 ≥1% gain？ |
|---|---:|---:|---:|---|
| SPX | 1 | +2.380 | 0.052 | 否 |
| SPX | 5 | +0.434 | 0.934 | 否 |
| SPX | 22 | +1.014 | 0.777 | 否 |
| TW50 | 1 | +0.492 | 0.934 | 否 |
| TW50 | 5 | +0.117 | 0.934 | 否 |
| TW50 | 22 | +0.947 | 0.777 | 否 |

因此 **0/6** 能在 family-wise correction 後排除 1% gain；整體 verdict 必須是 inconclusive。

### Moving-block CI（僅 uncertainty diagnostic）

這些 CI 對已產生的 paired fixed-window QLIKE losses 做 1,999 次 circular moving-block bootstrap；模型沒有
在 bootstrap 內重估，所以它們不是 recursive nested-inference 修正，也不進 verdict。

| 資產 | h | QLIKE 改善 95% CI |
|---|---:|---:|
| SPX | 1 | [−0.877%, +0.728%] |
| SPX | 5 | [−3.533%, +3.752%] |
| SPX | 22 | [−5.685%, +2.771%] |
| TW50 | 1 | [−0.543%, +1.932%] |
| TW50 | 5 | [−5.489%, +6.417%] |
| TW50 | 22 | [−17.446%, +5.655%] |

## 識別階梯：先控制水準，再問真正離散度

`log(rdisp) = log(avg_vol) - log(idx_vol)`；HAR 已含 index RV，故 HAR + `l_rdisp` 與 HAR +
`l_avg_vol` 張成同一個線性空間。primary proxy 的任何效果都不能直接歸因於「離散度」。決定性的階梯為：

- M0：HAR；
- M1：HAR + `l_avg_vol`（成分股波動水準）；
- M3：M1 + `rho`；
- M4：M1 + `csvd_rel`。

這個家族用 MSE 點估計與 Clark–West one-sided p，BH-FDR 跨 12 格；QLIKE 與 raw DM 都不進 gate。

| 資產 | h | 訊號 | MSE 改善 | CW t | BH q | Gate |
|---|---:|---|---:|---:|---:|---|
| SPX | 1 | rho | +2.780% | +1.545 | 0.183 | fail |
| SPX | 1 | csvd_rel | −1.332% | −1.493 | 0.999 | fail |
| SPX | 5 | rho | +1.898% | +1.138 | 0.255 | fail |
| SPX | 5 | csvd_rel | −0.037% | −0.452 | 0.999 | fail |
| SPX | 22 | rho | −0.487% | −0.668 | 0.999 | fail |
| SPX | 22 | csvd_rel | −0.342% | −1.346 | 0.999 | fail |
| TW50 | 1 | rho | −0.727% | −1.405 | 0.999 | fail |
| TW50 | 1 | csvd_rel | −0.871% | −3.240 | 0.999 | fail |
| TW50 | 5 | rho | +0.730% | +1.565 | 0.183 | fail |
| TW50 | 5 | csvd_rel | +0.129% | +1.214 | 0.255 | fail |
| TW50 | 22 | rho | +3.466% | +2.033 | 0.183 | fail |
| TW50 | 22 | csvd_rel | +1.005% | +1.663 | 0.183 | fail |

CW nominal p<0.05 有 2 格，但 BH 後 0 格；完整 gate 0/12。這支持「未發現水準之外的真正離散度增量」，
不支持 exact zero。

## 尾部風險（secondary）

未來 22 日最大回撤使用 legacy expanding-window MSE / CW 診斷。控制 `avg_vol` 後：SPX 的 rho / csvd_rel
MSE 改善為 −0.807% / −0.315%，CW t=+0.336 / +0.031；TW50 為 −3.554% / −0.548%，CW
t=−2.142 / +0.069。沒有正向強證據，但這個 secondary family 未做本版 primary 的 bounded-window QLIKE
inference，故只作輔助，不承載 headline verdict。

## 防錯與可重現性

- paired GW 六格全部使用相同 augmented complete-case mask、相同 target、相同 training dates；
- 每格固定 train size = 756；audit 的 min / max 都是 756；
- embargo 實測：h=1 / 5 / 22 的 origin−last-train gap 分別至少 2 / 6 / 23，皆嚴格大於 h；
- truncation test：SPX / TW50 的 rdisp、disp、rho、csvd 在 T0 前 max diff 全為 0；
- `y_h1` 與 next-day squared return bit-identical；
- raw DM helper 與 canonical helper parity max abs diff = 0；
- primary family 少任何一格、重複或多出 unexpected cell 都 raise，禁止 `all([])` 假 bounded-null；
- bootstrap seed 固定；results JSON 原子寫入。

## 限制

1. 免費 yfinance 缺已下市股票，早期 SPX PIT coverage 偏低。
2. Wikipedia 變動表不是 vendor-grade announcement vintage；TW50 只有月份時採月底生效，避免提早納入造成 lookahead。
3. 日頻 squared-return / rolling-RV proxy 很吵；QLIKE 對 conditionally unbiased noisy proxy 排名較穩健，但不會消除資料誤差。
4. `rdisp` 混合波動水準與相關結構，不能把 primary proxy 的結果命名成純 correlation effect。
5. 固定 756 筆 window 是 GW 合法性的設計代價；它回答 forecasting method 的 bounded-memory 表現，不是原 expanding estimator 的同一個 estimand。
6. 1% exclusion 是單邊 material-gain bound，不是 ±1% TOST equivalence。

## 檔案

| 檔案 | 內容 |
|---|---|
| `k1701.py` | 主實驗；paired fixed-window GW、material-gain exclusion、legacy diagnostics |
| `k1701_data.py` | PIT 名單重建與價格快取 |
| `k1701_results.json` | canonical 數字、audit、provenance、文獻 metadata |
| `test_k1701_general_loss.py` | fixed-window、embargo、GW 方向、exclusion、seed、claim sink、family completeness 測試 |
| `data/` | 名單、價格快取與 data manifest |
| `fig1`–`fig7` | 資料結構、偏誤、正式 GW、raw-DM diagnostic、事件研究、MSE/CW 識別階梯 |

## 參考文獻

1. Giacomini, R., & White, H. (2006). Tests of Conditional Predictive Ability. *Econometrica*, 74(6), 1545–1578. https://doi.org/10.1111/j.1468-0262.2006.00718.x
2. Patton, A. J. (2011). Volatility Forecast Comparison Using Imperfect Volatility Proxies. *Journal of Econometrics*, 160(1), 246–256. https://doi.org/10.1016/j.jeconom.2010.03.034
3. Clark, T. E., & McCracken, M. W. (2001). Tests of Equal Forecast Accuracy and Encompassing for Nested Models. *Journal of Econometrics*, 105(1), 85–110. https://doi.org/10.1016/S0304-4076(01)00071-9
4. Clark, T. E., & West, K. D. (2007). Approximately Normal Tests for Equal Predictive Accuracy in Nested Models. *Journal of Econometrics*, 138(1), 291–311. https://doi.org/10.1016/j.jeconom.2005.09.003
5. Corradi, V., & Swanson, N. R. (2007). Nonparametric Bootstrap Procedures for Predictive Inference Based on Recursive Estimation Schemes. *International Economic Review*, 48(1), 67–109. https://doi.org/10.1111/j.1468-2354.2007.00418.x
6. Driessen, J., Maenhout, P. J., & Vilkov, G. (2009). The Price of Correlation Risk: Evidence from Equity Options. *Journal of Finance*, 64(3), 1377–1406.

## Review 狀態

- Pre-run adversarial review：初審 FAIL（缺六格 family completeness fail-closed），修正並補 empty / partial / duplicate / unexpected tests 後 **PASS**。
- K1701 專屬測試 9 passed；nested-DM ratchet 17 passed。
- results JSON 獨立核對：六格 QLIKE improvement 重算一致、GW z 方向一致、paired-window audit 6/6 通過。
