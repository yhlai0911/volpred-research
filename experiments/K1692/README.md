# K1692 — 原油波動率 → 股市 / 能源股波動率 spillover（vol-of-vol 傳導）

**Verdict: NULL**（無穩健、油報酬-增量、VIX-增量、樣本外、能過嚴格門檻的傳導）
**Run:** 2026-07-15（台灣時間），worktree `wt/dispatch-slot-1-f53bca44-k1692`
**核心一句話：** 用正確的 HAC-Wald Granger、控制「油自身報酬」的識別、以及**排序不變的 generalized-FEVD（Pesaran-Shin）** Diebold-Yilmaz 連結度，重新檢視「油波動→股波動」的 vol-of-vol 傳導。結論**再一次是 NULL**：一階 realized-vol uncontrolled 0/6、控制油報酬後 1/6 邊際、VIX 控制後 0/6、OOS 0/6；**二階 vol-of-vol 的 in-sample Granger 有 2/6 過 Bonferroni（複製 K1444 物件），但在控制油報酬與 VIX 之後全部歸零（0/6，複製 K1665）**。GFEVD 顯示連結度雖高（≈61–63%），但油的**淨**方向量級小且隨 proxy 變號（vol-level 系統油淨接收 −0.10、vov 系統油小幅淨傳出 +0.07），無 net-direction CI，故不宣稱方向已確立。

---

## 1. 研究問題與差異化（誠實 / 查重）

### 問題
原油**波動**（CL=F WTI 近月期貨、USO ETF）的衝擊，是否**傳導**到大盤（SPY）與能源股（XLE、XOP）的**波動**——即「波動→波動」的 vol-of-vol 通道，明確區別於眾所周知的「油**價**→股**報酬**」通道——且此傳導在 (a) 正確的自相關穩健（Newey-West HAC-Wald）推論、(b) **控制油自身報酬**（避免把報酬效果誤當波動效果）、(c) 排序不變的 Diebold-Yilmaz 連結度 之後還存活？

### 這不是新發現（本 lab 已收斂為 NULL）
本主題在本 lab 已被至少 5 條實驗深度覆蓋，且在**正確推論**後一致收斂為 NULL / directional-NULL。本實驗**明白定位為方法論 / robustness 複製**，不宣稱新奇性：

| 先驗 K | 內容 | 與 K1692 關係 |
|---|---|---|
| **K1665** | CL=F/USO→SPY/XLE realized-vol + vol-of-vol，proper HAC-Wald，VIX-controlled，OOS。**NULL**（一階全崩、二階僅 CL=F 過 HAC 但 VIX 控制後歸零） | 最接近的先驗；K1692 補其未做的三點（見下），並複製其「vov 過 HAC 但 VIX 控制後死」 |
| **K1444** | CL=F/USO/SPY/XLE vol-of-vol；DY 溢出 48.8%；期貨為 net RECEIVER。Codex 標其「HAC」實為 plain ssr F-test | K1692 用 GFEVD 重算 DY；vov 系統油方向與 K1444 相反（見 §4.4 誠實揭露） |
| **K1351** | CL=F/USO→SPY/XLE/XOP；`NULL_NO_HARVEY_PASS` | 同 target set、同結論 |
| **K1329** | CL/USO→SPY/XLE/XOP；14 in-sample Granger pair 顯著，但**無 OOS edge** | 複製「統計 spillover ≠ forecast 價值」 |
| **K1647** | oil RV→equity RV，VIX-controlled；directional NULL | K1692 VIX 控制結果與之一致 |
| **K1025** | Diebold-Yilmaz 連結度 — **statsmodels `.fevd()` 是 Cholesky（依排序），非其註解宣稱的 Pesaran-Shin GFEVD**，net/方向量級曾被撤回 | K1692 **手刻 KPPS** 避開此陷阱 |

### K1692 相對 K1665 的三個增量（皆為方法論，非新奇）
1. **brief 指定、先驗未做的核心識別**：油**波動**是否在**控制油自身報酬**（signed + squared 落後報酬）之後仍對股波動有邊際貢獻？——把「波動效果」從「報酬效果」中分離。K1665 控制的是 VIX，**未**控制油報酬本身。本實驗對一階 vol 與二階 vov **兩者**都做此控制。
2. **XOP（油氣探勘）**作為第 3 個 target，並用 proper HAC-Wald（K1665 缺 XOP；K1329/K1351 用過 XOP 但僅 in-sample）。
3. **正確的 generalized-FEVD（Pesaran & Shin 1998）** Diebold-Yilmaz 連結度，跑在完整 `{CL=F, USO, SPY, XLE, XOP}` 波動系統上，**手刻**自 `sigma_u` + `ma_rep`（排序不變），並附 moving-block bootstrap CI——明確避開 K1025 的 Cholesky 排序假象。

### 預先登記的預期
如上先驗，預期結果是**複製性的 NULL**：同期共動存在（危機期油與股波動同步飆升），但其自相關穩健、油報酬-控制、VIX-控制、樣本外的**增量傳導**微弱或不存在。

### 文獻
1. Diebold & Yilmaz (2012), *Better to give than to receive: Predictive directional measurement of volatility spillovers*, IJF 28(1), 57–66.
2. Pesaran & Shin (1998), *Generalized impulse response analysis in linear multivariate models*, Economics Letters 58(1), 17–29.（GFEVD 排序不變性的來源）
3. Clark & West (2007), *Approximately normal tests for equal predictive accuracy in nested models*, Journal of Econometrics 138(1), 291–311.
4. Maghyereh, Awartani & Bouri (2016), *The directional volatility connectedness between crude oil and equity markets*, Energy Economics 57, 78–93.
5. Newey & West (1987), *A simple, positive semi-definite, heteroskedasticity and autocorrelation consistent covariance matrix*, Econometrica 55(3), 703–708.
6. Harvey, Leybourne & Newbold (1997) 小樣本 DM 修正；Harvey (2016) `|t|>3` 多重檢定門檻。

---

## 2. 資料

| | |
|---|---|
| 來源 | yfinance `download(auto_adjust=True)` daily Close |
| Tickers | `CL=F`（WTI 近月期貨）、`USO`（原油 ETF）、`SPY`（大盤）、`XLE`（能源股）、`XOP`（油氣探勘）、`^VIX`（控制變數） |
| 期間 | **2006-09-22 → 2026-07-14**（可得最長共同樣本；XOP 2006-06 掛牌 + EWMA burn-in 為 binding constraint） |
| 樣本數 | **N = 4,985** 共同交易日（≥500 硬規 ✅）；OOS 切最後 3 年（2023-07-14 起），涵蓋 2008 GFC、2011、2015-16、2018Q4、2020 COVID+負油價、2022 能源衝擊等多次空頭 |
| 波動率 proxy | **EWMA(λ=0.94) 日條件波動（RiskMetrics），年化**：σ²ₜ = λσ²ₜ₋₁ + (1−λ)r²ₜ₋₁ |
| vol-of-vol | 上述 σ 序列的 21 日 rolling std（K1444 二階物件的對應）|
| 交叉驗證 proxy | 21 日 rolling realized vol（K1665 慣例），用於 headline pair 的一致性核對 |

**為何用 EWMA 而非 21 日 rolling window**（方法論選擇）：EWMA 條件波動是**日頻、僅用過去資訊**（σₜ 只用 rₜ₋₁ → 收盤於 t−1 即已知，無 lookahead），且**沒有硬窗重疊假象**。21 日 rolling window 的機械重疊會人為抬高 VAR 的持續性與連結度量級（DY 部分尤其敏感），對 Granger 回歸則製造 MA(20) 殘差。EWMA 對 Granger 與 VAR/DY 兩者都乾淨。

**因果初始化（防 lookahead）**：σ² 以**第一筆可得的 r²（單一過去點）**作 seed，**不用前向窗均值**——用前向窗做 seed 會把最多 VOV_WINDOW−1 筆未來報酬平方注入早期 σₜ（本實驗 Codex review 抓到並修正的 lookahead）。隨後**丟棄前 63 筆 burn-in**，讓單點 seed（雖粗但因果）充分衰減（λ=0.94 半衰期約 11 天）。

**平穩性檢查（已寫進 K1692.py，存 `stationarity_adf`）**：ADF 對 5 條 EWMA vol level 全部強烈拒絕單位根（ADF −5.21～−5.90，p ≤ 8.6e-6）→ 波動序列平穩（高持續，acf₁≈0.99，但平穩），levels 回歸合法。

**CL=F 負油價處理**：2020-04-20 WTI 近月結算 −$37.63，log-return 於 P≤0 未定義 → 對非正價格日 mask（`close.where(close>0)`，清 ±inf）。

---

## 3. 方法（防錯硬規）

- **Lookahead**：所有 predictor 明確 lagged。Granger 回歸 `E_t = c + Σaᵢ E_{t−i} + Σbᵢ O_{t−i} (+ 控制項_{t−i})`，i=1..5。EWMA σₜ 僅用 rₜ₋₁（因果 seed + burn-in，見 §2）。OOS 用 expanding window，在 `[:t]` 擬合、預測 index `t`，baseline 與 augmented **同 lag/同窗**。
- **HAC-Wald Granger**（核心）：OLS + Newey-West HAC 共變異數，Wald 檢定 H₀: 所有 source-lag 係數 = 0。**HAC 落後期先量殘差 acf 再決定**（`_hac_bandwidth`：取 |acf| 仍超過 2/√n 白噪音帶的最大落後期，下限 = repo canonical `⌈n^{1/3}⌉`=18，上限 42）——**非盲目 h−1**。實測殘差近乎白噪音（acf₁≈−0.01），data-driven nw 落在 28–41。**並報 2× 落後期的 lag sensitivity**（`wald_p_2x_lag`）。
- **主要顯著性判準 = joint Wald block test + Bonferroni**（α=0.05/6=0.0083）。**per-lag max|t| 僅為描述性**：對 5 個共線 lag 取 max|t| 是 block 內多重比較，**不是**合法的 Harvey 單一統計量檢定——這正是以 joint Wald 為主的原因（與 K1665 一致）。
- **控制油報酬 / VIX 的識別**：`E_t = c + Σaᵢ E_{t−i} + Σcᵢ r^{oil}_{t−i} + Σdᵢ (r^{oil}_{t−i})² + Σbᵢ σ^{oil}_{t−i} + ε`，Wald H₀: 所有 bᵢ=0 → 油**波動**在控制油**報酬**（水準與平方）之後是否有增量。另跑 VIX-level 控制變體。**一階 vol 與二階 vov 兩者都做此兩種控制。**
- **跨資產不 pool**：SPY、XLE、XOP **各自獨立回歸**，不把 asset-day 當 iid。
- **Diebold-Yilmaz generalized FEVD**：對波動系統擬合 VAR（AIC 選 lag ≤5），**手刻** Pesaran-Shin GFEVD：θᵢⱼ = σⱼⱼ⁻¹ Σₕ(eᵢ'Aₕ Σ eⱼ)² / Σₕ(eᵢ'Aₕ Σ Aₕ'eᵢ)，逐列正規化（每列和=1，已驗證）。total connectedness = 100·(Σᵢ≠ⱼ θ̃ᵢⱼ)/k；net = to_others − from_others。**從不呼叫 statsmodels Cholesky `.fevd()`**（K1025 教訓；`audit_fevd_ordering` → OK_GFEVD）。CI 用 **fixed-design moving-block（block=21）殘差 bootstrap，B=300，seed 固定**；此 CI **僅涵蓋 total connectedness**，未對 net direction 做 CI（誠實揭露，不宣稱方向已釘穩）。
- **OOS 增量 forecast（巢套正確檢定）**：own-lag baseline **巢套於** own+source-lag augmented → raw DM/HLN 在巢套 null 下無效（loss differential 退化，Clark & West 2007）。用 **canonical `volpred.stats.model_evaluation.clark_west_test`**（MSPE-adjusted，正值=大模型有增量預測力，one-sided），非 raw DM（nested-dm ratchet）。edge gate = `cw_t > 3`（Harvey-strict, one-sided）。
- **seed=42** 全程固定（bootstrap 可重現）。

---

## 4. 結果

### 4.1 一階 EWMA 條件波動：plain ssr F vs proper HAC-Wald（油→股）

| Pair | naive ssr-F p（非 HAC）| **HAC-Wald p** | 2× lag p（sensitivity）| max\|t\| | 過 Bonferroni(0.0083)? |
|---|---|---|---|---|---|
| CL=F→SPY | 5.3e-11 | 0.287 | 0.214 | 2.15 | ✗ |
| CL=F→XLE | 5.5e-04 | 0.498 | 0.410 | 1.46 | ✗ |
| CL=F→XOP | 2.1e-03 | 0.489 | 0.440 | 1.52 | ✗ |
| USO→SPY | 2.6e-15 | 0.058 | 0.038 | 2.62 | ✗ |
| USO→XLE | 1.6e-03 | 0.390 | 0.298 | 1.74 | ✗ |
| USO→XOP | 1.1e-02 | 0.405 | 0.411 | 1.75 | ✗ |

**→ plain F 全部 nominally 顯著（4 對達 e-3～e-15 的極顯著，USO→XOP 僅 nominal 5% p=0.011）是持續性造成的假象；正確 HAC-Wald 下 0/6 過 Bonferroni（2× lag 亦然）。** 複製 K1665。

### 4.2 一階：控制「油自身報酬」與 VIX 的識別

控制 油報酬（signed）＋ 油報酬平方 的 5 期落後（或 VIX level）之後，油波動的增量 joint Wald p：

| Pair | 控制油報酬 p | 過 Bonf? | 控制 VIX p | 過 Bonf? |
|---|---|---|---|---|
| CL=F→SPY | 0.098 | ✗ | 0.406 | ✗ |
| CL=F→XLE | 0.035 | ✗ | 0.831 | ✗ |
| CL=F→XOP | 0.013 | ✗ | 0.734 | ✗ |
| **USO→SPY** | **0.0057** | **✓（唯一）** | 0.269 | ✗ |
| USO→XLE | 0.145 | ✗ | 0.734 | ✗ |
| USO→XOP | 0.327 | ✗ | 0.617 | ✗ |

**→ 控制油報酬後僅 1/6（USO→SPY）過 Bonferroni；控制 VIX 後 0/6。**

**對這唯一 blip 的誠實解讀**：USO→SPY 控制油報酬後 Wald p=0.0057（勉強過 Bonferroni），但 (a) uncontrolled 檢定中**並不顯著**（p=0.058），僅在加入 10 個高度共線油報酬控制項後才浮現，符合 suppressor / 共線抽樣假象；(b) 期貨對應 CL=F→SPY **不過**（p=0.098）；(c) **控制 VIX 後消失**（p=0.269）；(d) **OOS 未過嚴格門檻**（§4.5，CW t=1.66/p=0.049 僅 nominal）。故**不升級為 positive**，判為 in-sample 偶發。

### 4.3 二階 vol-of-vol（K1444 物件）：Granger + 同樣控制

vol-of-vol = σ 序列的 21 日 rolling std。這是 K1444 的確切物件，且 in-sample Granger 有 Bonferroni-顯著站點——**必須施以與一階相同的控制才能宣稱 NULL**（Codex review 指出的漏報，已補）：

| Pair (vov) | naive ssr p | **HAC-Wald p** | 過 Bonf? | 控制油報酬 p | 控制 VIX p |
|---|---|---|---|---|---|
| **CL=F→SPY** | 1.8e-20 | **0.0002** | **✓** | 0.084 | 0.051 |
| CL=F→XLE | 1.2e-08 | 0.078 | ✗ | 0.519 | 0.334 |
| CL=F→XOP | 4.2e-06 | 0.320 | ✗ | 0.553 | 0.446 |
| **USO→SPY** | 1.9e-27 | **0.0013** | **✓** | 0.101 | 0.017 |
| USO→XLE | 1.2e-07 | 0.204 | ✗ | 0.139 | 0.278 |
| USO→XOP | 4.5e-02 | 0.526 | ✗ | 0.043 | 0.361 |

**→ 二階 vov 的 HAC-Wald 有 2/6 過 Bonferroni（CL=F→SPY、USO→SPY，皆到 SPY）——比一階更強。但控制油報酬後 0/6（最小 0.043，兩個原顯著站點升到 0.084/0.101）、控制 VIX 後 0/6（兩站點升到 0.051/0.017，仍不過 0.0083）。** 這**精確複製 K1665**：油的 vol-of-vol 對股波動有 in-sample lead，但被油報酬與 VIX（共同風險因子）完全吸收，非增量傳導。

### 4.4 Diebold-Yilmaz generalized-FEVD 連結度（排序不變，含 XOP）

VAR(AIC, p=5) on 5-asset 波動系統，H=10 步 GFEVD（每列和=1，已驗證）。**net = to − from（+傳導 / −接收）**：

| 系統 | CL=F | USO | SPY | XLE | XOP | total | 油→股 淨 |
|---|---|---|---|---|---|---|---|
| **一階 vol** | −0.144 | +0.045 | −0.176 | +0.160 | +0.115 | **61.5%** | **−0.100** |
| **二階 vov** | +0.040 | +0.030 | −0.236 | +0.047 | +0.119 | **62.8%** | **+0.070** |

- 一階 vol bootstrap CI95(total) = **[59.97, 62.56]%**（B=300，seed=42）。
- **方向誠實揭露（Codex review 指出的矛盾，已修正敘事）**：**油的淨方向隨 proxy 變號**——一階 vol 系統油是**淨接收方**（CL=F −0.144、油→股 −0.100，與 K1444「期貨 net receiver」一致），但二階 vov 系統油是**小幅淨傳出方**（CL=F +0.040、油→股 +0.070）。兩者**量級都小**（|net|≤0.18，系統 off-diagonal 總量 ≈(total/100)·k ≈ 3），且**未做 net-direction bootstrap CI**。故**不宣稱「油是接收方」為穩健結論**，只說：連結度高（≈61–63%）但油的**淨**角色小、且 proxy-dependent，無證據支持油是主導傳導方（若有，一階更像接收方）。

### 4.5 OOS 增量 forecast（Clark-West，巢套正確檢定）

own-lag baseline **巢套於** own+oil-lag augmented，故用 **Clark-West (2007) MSPE-adjusted 檢定**（raw DM 在巢套 null 下無效；canonical `clark_west_test`，HAC lag=10，n_oos=755）。CW 正值 = augmented 有增量預測力，one-sided：

| Pair | MSE 改善 | CW t | CW p(one-sided) | 過 Harvey-strict(t>3)? |
|---|---|---|---|---|
| CL=F→SPY | +2.19% | +1.46 | 0.073 | ✗ |
| CL=F→XLE | +0.17% | +1.80 | 0.036 | ✗ |
| CL=F→XOP | −1.00%（惡化）| −0.19 | 0.576 | ✗ |
| USO→SPY | +2.79% | +1.66 | 0.049 | ✗ |
| USO→XLE | +0.17% | +1.78 | 0.038 | ✗ |
| USO→XOP | −0.86%（惡化）| −0.26 | 0.603 | ✗ |

**誠實讀法**：Clark-West 比 raw DM 對巢套模型更有檢定力（修正 downward bias），因此在 **CL=F→XLE、USO→SPY、USO→XLE 三對浮現邊際 one-sided 增量訊號（p≈0.036–0.049）**——比先驗 DM-based null 更細緻，不予埋沒。但 (a) **無一過本 lab 對 6 pair 的嚴格門檻**（Harvey t>3，或 Bonferroni p<0.0083），(b) **XOP 兩對為負**（augmented 惡化），(c) 與 §4.2/4.3 一致，此微弱訊號屬 sub-threshold、不可交易。`oos_edge=0/6`，不升級為 positive。

---

## 5. 圖表
- `K1692_fig1_vol_overlay.png`：CL=F/USO/SPY/XLE/XOP EWMA vol 時序疊圖（log 軸，標 2020 油崩 / 2022 能源）——危機期**同步**飆升，肉眼即見「同期共動」而非「油領先」。
- `K1692_fig2_dy_net_spillover.png`：一階 vol GFEVD **net 連結度**長條（+傳導 / −接收）——能源股正、油與大盤負。
- `K1692_fig3_gfevd_heatmap.png`：一階 vol GFEVD 變異數份額矩陣（列 i FROM 欄 j，%）。

---

## 6. 誠實聲明與結論強度

- **Verdict = NULL**：在此 spec 集（EWMA-λ0.94 因果 vol proxy、日頻、data-driven HAC + lag sensitivity、油報酬-控制、VIX-控制、Clark-West 一步 OOS、GFEVD 連結度）下，**原油波動對股市/能源股波動無穩健、可增量、可預測、能過嚴格門檻的傳導**——一階與二階 vol-of-vol 皆然。
- 結論強度**不超過證據**：**不等於**「油與股市波動無任何關係」——同期相關與危機共動確實存在（見 fig1，total connectedness 61–63%），只是被油報酬與 VIX 這些共同因子吸收。**GFEVD 的淨方向 proxy-dependent 且量級小，不作方向性因果宣稱。**
- **三處誠實揭露、皆未升級為 positive**：(1) 一階 in-sample blip（USO→SPY 控制油報酬後 p=0.0057，§4.2）；(2) 二階 vov 有 2/6 in-sample Bonferroni-顯著（§4.3），但兩種控制後全歸零；(3) Clark-West 3 對邊際 one-sided 增量（p≈0.036–0.049，§4.5），無一過嚴格門檻、XOP 為負。皆微弱 sub-threshold，不足以推翻先驗 NULL。
- **相對先驗的增量（誠實範圍內）**：(1) 首次做「控制油自身報酬」的 vol-of-vol 識別（一階＋二階），證實控制報酬後傳導不成立；(2) 補上 XOP，NULL 在第 3 個 target 上仍成立；(3) 用**正確的排序不變 GFEVD**（避開 K1025 Cholesky bug）重算 DY，並誠實揭露油淨方向 proxy-dependent。
- 所有數字由 `K1692.py` 實算，結果在 `K1692_results.json`（含 `stationarity_adf`）。yfinance live data 會隨時間微漂（reproducibility floor）；seed 已固定。

## 7. 是否值得寫成 reader-facing 文章

**可，迷思實驗室角度**（但需主線程 3-layer 查重，K422/K1329/K1351/K1665 可能已有覆蓋）：**「油價一波動，股市就跟著抖？——數據說：抖的是同一份恐懼（VIX），不是油在帶動」**。賣點：(1) fig1 同步飆升圖直觀；(2)「用錯的檢定看到 p=0.00000000005 的假顯著，控制 VIX 後就消失」的統計素養點；(3)「連結度 60%+ 很高，但油的『淨』角色小到看 proxy 變號」的反直覺敘事。務必寫成「無穩健**領先/增量**傳導、共同因子（VIX）吸收」，而非「無關係」或「油是接收方」（後者不穩健）。

## 8. Code review 記錄

- **Reviewer**：Codex primary-path（`gpt-5.6-sol`, ultra；CLI 0.144.1，ChatGPT auth）。**初版判 FAIL，4 個 blocking defects 已全部修正並重跑**：
  1. **[Critical] EWMA 初始化 lookahead**：初版 seed 用前 21 筆報酬平方均值 → 早期 σₜ 含未來報酬。**已修**為單點因果 seed + 63 天 burn-in，全序列嚴格只用 rₜ₋₁。
  2. **[Critical] NULL verdict 漏報二階 vov Granger 顯著**：vov 有 2/6 過 Bonferroni 卻未納入 verdict/README。**已修**：加 `granger_vov` 的 verdict 計數 + 對 vov 施以油報酬/VIX 控制（§4.3），證實控制後全歸零，NULL 成立。
  3. **[Critical] vov GFEVD 方向與 README 相反**：vov 系統油是淨傳出方（+0.07），與 vol-level 系統（−0.10）相反。**已修**：§4.4 同時報兩系統 net，明說方向 proxy-dependent、量級小、無 net-direction CI，撤回「油是接收方」的概括宣稱。
  4. **[Critical] ADF 數字不可驗證**：README 引 ADF 但 script 未算。**已修**：ADF 計算寫進 `main()`，存 `stationarity_adf`。
- **非 blocking 亦已處理**：README 全部數字重新從 `K1692_results.json` 對齊（VIX-control p、起日 2006-09-22 等漂移已修）；`robust_positive` 改為**同一 pair** 須同時過三關；`wald_F` 更名 `wald_stat`（robust Wald χ²/F）；加 `wald_p_2x_lag` lag sensitivity；OOS「無任何價值」改為「未過嚴格門檻」。
- **開發過程自查修正**（誠實留痕）：初版 `_residual_acf` 在 `ols.resid` 為 pandas Series 時被 index 對齊抵銷 lag → acf 恆 1.0 → HAC 落後期恆退化 42。ADF + 直接 `.autocorr(1)` 診斷後改 `np.asarray` 強制 positional；verdict 判準從錯誤的 per-lag max|t|>3 改為 joint Wald + Bonferroni；`experiment_gates.py` 抓到 nested-dm-misuse（初版 OOS 用 raw DM 比較巢套模型）後改 canonical Clark-West，4 關全清。
- **審完凍結**：本裁決僅對當前 sha 的 claim surface 有效；如再動 code，`review_verdict.json` 的 sha 會漂移、gate 會再擋，須重審。
