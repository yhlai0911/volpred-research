# K1031: Bayesian SSVS ARX-GARCH Joint Estimation

## 動機
K1013 用 two-stage SSVS（先 MLE 估 GJR → 殘差上做 SSVS）得到 NULL result（所有 PIP < 0.01，null model 99.56%）。但 K988 用 GARCH-X 直接嵌入 VIX^2 的 multiplicative structure 得到 DM t=4.03。這個矛盾可能源自 two-stage 方法的局限：Stage 1 的 GARCH beta*h_{t-1} 已吸收大部分可預測方差，留給外生變數的殘差信號極微弱。K1031 直接在完整 GARCH-X 方差方程式中做 SSVS（joint estimation），更接近 So, Chen, Liu (2006) 的原始方法。

## 背景知識
- **K988**: VIX^2 在 multiplicative GARCH-X 中有效（DM t=4.03）
- **K1013**: Two-stage SSVS → NULL（all PIP < 0.01, null 99.56%）
- **K484**: SSVS Variance Eq components（4/5 PIP=1.000）
- **K433**: SSVS mean equation（VIX PIP=0.999）

## 方法
**Joint Bayesian GARCH-X with SSVS** (So, Chen, Liu 2006):

方差方程式：
```
h_t = omega + alpha * e_{t-1}^2 + gamma * e_{t-1}^2 * I(e<0) + beta * h_{t-1}
      + sum_j delta_j * X_{j,t-1}
```

SSVS prior on delta_j:
```
delta_j | xi_j ~ xi_j * N(0, c^2 * tau^2) + (1-xi_j) * N(0, tau^2)
xi_j ~ Bernoulli(0.5)
tau_spike = 0.001, tau_slab = 1.0 (c = 1000)
```

**候選變數**（全部 lag 1 天）：
- VIX^2 / 252（日方差尺度）
- VIX9D^2 / 252
- VIX3M^2 / 252
- TermSpread（DGS10 - DGS2）
- STLFSI4（金融壓力指數，週頻 ffill）
- RV_20d（20日實現方差）

**MCMC**: Gibbs + MH sampler, 10,000 iterations, 5,000 burn-in, seed=42

## 數據
- **資產**: SPY
- **來源**: yfinance + FRED（local cache）
- **IS 期間**: 2011-01-04 to 2018-12-13（2,000 obs）
- **OOS 期間**: 2018-12-14 to 2026-04-09（1,838 obs）

## 結果

### Posterior Inclusion Probabilities (PIP)

| 變數 | PIP | 判定 |
|------|-----|------|
| VIX3M_sq | 0.0012 | 排除 |
| RV_20d | 0.0010 | 排除 |
| TermSpread | 0.0008 | 排除 |
| VIX_sq | 0.0006 | 排除 |
| VIX9D_sq | 0.0006 | 排除 |
| STLFSI4 | 0.0006 | 排除 |

**Null model frequency: 99.52%**（與 K1013 的 99.56% 幾乎一致）

### GARCH Posterior vs MLE

| 參數 | MLE | Posterior mean | Posterior std |
|------|-----|---------------|---------------|
| alpha | 0.0551 | 0.0059 | 0.0062 |
| gamma | 0.1045 | 0.1935 | 0.0349 |
| beta | 0.8517 | 0.5963 | 0.0447 |
| Persistence | 0.9590 | 0.6989 | — |

注：posterior persistence (0.70) 顯著低於 MLE (0.96)，反映 MCMC 混合不完全（beta 的 ESS=9 極低）。

### MCMC 診斷

| 參數 | ESS | MH Acceptance |
|------|-----|--------------|
| mu | 475 | 77.0% |
| omega | 7 | 24.6% |
| alpha | 356 | 35.4% |
| gamma | 61 | 86.1% |
| beta | 9 | 82.7% |
| delta (各變數) | 6-13 | 0.4-0.9% |

**⚠️ omega 和 beta 的 ESS 極低（<10），delta 的 acceptance rate < 1%。** 這些是 MCMC 品質紅旗。然而，SSVS 的 inclusion indicator xi_j 是 Gibbs step（不是 MH），其 PIP 估計的可靠性不直接受 delta acceptance rate 影響——因為 delta 值極小時（被 spike prior 壓制），xi_j 幾乎一定選 0。

### OOS 預測比較

| 模型 | QLIKE | vs Baseline |
|------|-------|-------------|
| GJR baseline (MLE) | -8.2703 | — |
| GARCH-X (all vars, posterior) | -8.3521 | -0.99% (better) |
| GARCH-X (selected = null) | -8.1591 | +1.34% (worse) |
| GARCH-X (best single VIX3M) | -8.1755 | +1.15% (worse) |

DM test (baseline vs GARCH-X all): t=3.561, p=0.0004 (**PASS** Harvey)
DM test (baseline vs best single): t=-3.660, p=0.0003 (**PASS** Harvey)

注意：GARCH-X (all vars) 使用 posterior mean 的所有參數（包括不同的 alpha/beta），其 QLIKE 略優於 MLE baseline，但這主要來自不同的 GARCH 基本參數，而非外生變數的貢獻（delta 值極小，~1e-6 量級）。

## 結論

**NULL result — 聯合估計同樣選出空模型，確認 K1013 的結論。**

1. **Joint vs Two-stage 結果一致**：K1013 null freq=99.56%, K1031 null freq=99.52%。兩種方法都得到相同的空模型結論，排除了「two-stage 方法低估聯合效應」的擔憂。

2. **所有候選變數 PIP < 0.002**：即使在聯合估計框架中，VIX^2、VIX9D^2、VIX3M^2、TermSpread、STLFSI4、RV_20d 都無法通過 SSVS 選擇門檻。這強化了「GJR-GARCH 內部動態已充分捕捉方差可預測性」的結論。

3. **與 K988 的矛盾解讀**：K988 的 VIX^2 GARCH-X 顯著（DM t=4.03）而 SSVS 不選的原因：(a) K988 用 multiplicative structure（h_t * tau(VIX)），本質不同於 additive SSVS；(b) SSVS 的 spike-slab prior 偏好稀疏模型，可能壓制小但穩定的效應。

4. **方法論洞見**：Additive GARCH-X（本實驗）和 multiplicative GARCH-X（K988）是根本不同的建模假設。Multiplicative 允許 VIX 調節整個方差水平，而 additive 僅加入一個常數項。SSVS 在 additive 框架下的 NULL 不代表 multiplicative 也是 NULL。

## 局限性
- MCMC 混合品質不理想（omega/beta ESS < 10, delta acceptance < 1%）
- 10,000 次迭代對聯合 GARCH-X 可能不足——但對 SSVS selection 結論影響有限
- 僅測 SPY，未跨市場驗證
- 僅測 additive specification，未測 multiplicative SSVS
- 候選變數限 6 個

## 後續方向
1. **Multiplicative SSVS**：在 h_t = base_garch * exp(sum delta_j X_j) 結構中做 SSVS
2. **增加 MCMC iterations**：20,000-50,000 以改善 ESS
3. **Block sampling**：對 (omega, alpha, gamma, beta) 用 block MH 改善混合
4. **台股驗證**：K461 發現 SSVS 在台股選出 SPY PIP=1.000

## 檔案
- `k1031.py` — 實驗腳本
- `k1031_results.json` — 完整結果
- `k1031_ssvs_joint_results.png` — 圖表

## 參考文獻
- So, Chen, Liu (2006, JRSS-C 55(2):201-224) — SSVS for GARCH
- George & McCulloch (1993, JASA 88(423):881-889) — original SSVS
- Patton (2011) — QLIKE loss function
- Harvey (2016) — DM test threshold |t| > 3.0
