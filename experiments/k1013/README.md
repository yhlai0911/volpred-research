# K1013: Bayesian SSVS for GARCH-X Variable Selection

## 動機
K988 發現 VIX² 是最佳 tau 函數（A4f DM t=4.48），但只測了 VIX 系列。K1013 使用 Bayesian Stochastic Search Variable Selection (SSVS) 方法，從 6 個候選外生變數中系統性地選出最優子集，驗證是否有其他變數能改善 GJR-GARCH 的方差預測。

## 背景知識
- **K433**: SSVS mean equation — VIX PIP=0.999，唯一選入均值方程式
- **K461**: SSVS Taiwan — SPY_ret PIP=1.000 in mean eq
- **K484**: ★★★ SSVS Variance Eq — 4/5 components PIP=1.000, QLIKE -7.43%
- **K924**: Bayesian SSVS Mean Equation — NULL（所有 10 個變數 PIP<0.5）
- **K988**: VIX² 最佳 tau 函數（A4f DM t=4.48）

## 方法
**Two-stage approach** (So, Chen, Liu 2006, JRSS-C)：

1. **Stage 1**：用 MLE 估計 GJR-GARCH(1,1,1)，取得條件方差 h_t
2. **Stage 2**：在殘差方差 (r²_t - h_t) 上執行 Bayesian SSVS，選擇哪些外生變數能解釋 GJR 未捕捉的部分

**候選變數**（全部 lag 1 天，無 lookahead）：
- VIX² / 252（日方差尺度）
- VIX9D² / 252
- VIX3M² / 252
- TermSpread（10Y-3M 期限利差）
- UnempRate（失業率，月頻 ffill 至日頻）
- RV_20d（20 日實現方差，年化）

**SSVS 設定**：
- Prior inclusion probability: 0.5（無資訊先驗）
- tau0 = 0.001 (spike), tau1 = 1.0 (slab)
- MCMC: 10,000 iterations, burn-in 5,000
- Seed: 42

## 數據
- **資產**: SPY
- **來源**: yfinance + FRED
- **估計期間**: 2011-01-04 to 2019-01-07（2,000 obs）
- **OOS 期間**: 2019-01-08 to 2026-04-07（1,786 days）

## 結果

### GJR-GARCH Stage 1
- Convergence: 0（成功）
- Persistence: 0.9557
- alpha=0.000, gamma=0.298, beta=0.807（強槓桿效應）

### SSVS Posterior Inclusion Probabilities (PIP)

| 變數 | PIP | 判定 |
|------|-----|------|
| VIX_sq | 0.0012 | 排除 |
| TermSpread | 0.0010 | 排除 |
| RV_20d | 0.0008 | 排除 |
| VIX9D_sq | 0.0006 | 排除 |
| VIX3M_sq | 0.0006 | 排除 |
| UnempRate | 0.0002 | 排除 |

**空模型被選中頻率: 99.56%**（5,000 次後驗抽樣中 4,978 次）。

### OOS 預測比較
| 模型 | QLIKE | MSE |
|------|-------|-----|
| GJR baseline | 1.5013 | 2.73e-07 |
| SSVS-augmented (VIX_sq) | 1.5158 (+0.97%) | 2.73e-07 |
| VIX-only | 1.5158 (+0.97%) | 2.73e-07 |

DM test (base vs SSVS): t=-2.374（Harvey FAIL），baseline 略勝。

### MCMC 診斷
- ESS 範圍: 4793-5189（良好混合）
- ACF1 範圍: -0.019 to 0.021（接近獨立）
- PIP trace range < 0.004（穩定收斂）

## 結論

**NULL result — 但含重要方法論洞見**：

1. **Two-stage SSVS 的「殘差方差」approach 得到空模型**：GJR-GARCH 的條件方差已充分捕捉 r² 的動態，殘差 (r² - h_t) 中沒有可被外生變數系統性解釋的結構。

2. **與 K484 的差異**：K484 在方差方程式**內部**（variance equation components）做 SSVS，發現 4/5 components PIP=1.000。K1013 在方差方程式**外部殘差**做 SSVS，發現無變數被選入。兩者不矛盾——K484 測的是 GARCH 內部結構是否需要（是），K1013 測的是 GARCH 外部是否需要補充（否）。

3. **與 K988 的差異**：K988 使用 tau 函數直接將 VIX² 嵌入 GARCH-X 的方差方程式（h_t = omega + alpha*e² + gamma*e²*I + beta*h + delta*VIX²），是聯合估計。K1013 用兩階段分離法，先固定 GARCH 參數再看殘差，可能低估了 VIX 在聯合估計中的貢獻。

4. **方法論啟示**：Two-stage SSVS 在高持續性 GARCH（persistence=0.956）下效力有限——GARCH 內部的 beta*h_{t-1} 項已吸收大部分可預測的方差，留給外生變數的信號極微弱。

## 局限性
- Two-stage 方法可能低估聯合效應（VIX 在 GARCH-X 中的貢獻被 Stage 1 的 GARCH 吸收）
- 10,000 次 MCMC 迭代偏少（但 ESS>4000，混合良好）
- 僅測 SPY，未跨市場驗證
- 候選變數限 6 個，可擴展至更多 macro indicators

## 檔案
- `k1013.py` — 實驗腳本
- `k1013_results.json` — 完整結果
- `k1013_ssvs_results.png` — 圖表（PIP bar chart, convergence trace, theta posteriors, OOS QLIKE）

## 參考文獻
- George & McCulloch (1993, JASA 88(423):881-889) — SSVS 原始方法
- So, Chen, Liu (2006, JRSS-C 55(2):201-224) — SSVS for GARCH
- Patton (2011) — QLIKE loss function
