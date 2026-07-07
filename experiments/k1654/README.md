# K1654: Skew-t GAS tail rescue — does the K1135 commodity phenomenon extend to equity indices?

`experiment_id: k1654` · [提出: Claude, 執行: Claude] · 2026-07-07
資料來源: yfinance (日資料) · IS 2010-01 ~ 2019-12 · OOS 2020-01 ~ 2026-07 · seed=42

---

## 研究問題（唯一）

K1135 在**負偏商品**（USO/UNG/GLD/SLV）上發現 Hansen (1994) skew-t GAS 的一個
現象，命名為 **"Scenario B" 尾端救援**：

> skew-t GAS **改善尾端風險（VaR/ES）** — 即使它**不改善點波動率預測（QLIKE NULL）**。
> K1135 商品：H1 QLIKE **0/4**、H2 VaR Trinity **2/4 @1% · 3/4 @5%**、H3 ES **4/4 @1% · 4/4 @5%**（M0 baseline 僅 1/4）。

**本實驗唯一問題**：這個「QLIKE 沒救、但 VaR/ES 有救」的現象，**是否從商品延伸到
平台實際交易的股票指數**？

股指有強**槓桿效應** → 負偏度通常比商品更穩定，理論上 skew channel 更該生效。
這是 K1135 留下的自然 open question，直接對接 **equity VaR/ES 風險產品**（平台
monetization angle）。**成功 = 誠實回答「延伸 or 不延伸」**，null 也如實報告。

## 與既有實驗的差異化（非重複）

| 前身 | 做了什麼 | 本實驗補上什麼 |
|------|----------|----------------|
| **K1135**（直系前身） | 商品 skew-t GAS → Scenario B（tail rescue） | 換成 **equity 指數**，同一套協定，做**跨市場對照** |
| **K1143** | equity skew-t GAS，但**只評估 QLIKE**（發現 symmetric GAS-t HARMFUL，SPY DM t=−3.27；skew-t 未救 vol，判「architectural incompat」） | **K1143 從未跑 VaR Trinity + ES Acerbi-Szekely 尾端 backtest** — K1654 是 skew-t GAS 在 equity 上**第一次正式的尾端風險評估** |

→ K1654 **不是** K1143 的重複：K1143 只看 vol（QLIKE），K1654 把 K1135 的完整
**尾端風險協定**（VaR Trinity + ES Z1/Z2）搬到 equity，才能直接比較「Scenario B
尾端救援」在 commodity vs equity 的異同。

## 方法（盡量 mirror K1135 以利跨市場可比性）

### 資料（yfinance 日資料）

| Ticker | 名稱 | full-inception skew | **post-2010 skew（建模樣本）** | OOS realized skew | n_OOS |
|--------|------|--------------------:|------------------------------:|------------------:|------:|
| SPY   | S&P 500 ETF     | −0.002 | **−0.331** | −0.265 | 1634 |
| QQQ   | Nasdaq-100 ETF  | −0.059 | **−0.211** | −0.153 | 1634 |
| ^TWII | Taiwan Weighted | −0.378 | **−0.463** | −0.434 | 1578 |
| ^N225 | Nikkei 225      | −0.227 | **−0.244** | −0.037 | 1588 |

- **資料註記**：`TW0050.TW` 在 yfinance 回 404（delisted symbol），依任務 brief 改用
  `^TWII`（台灣加權指數）。
- **`group` 標籤說明（誠實揭露）**：results JSON 的 `group` 欄用 **full-inception**
  skew 分類（含 2005-2009，SPY 因 2008 大漲大跌把全樣本 skew 拉到 ~0 → 被標
  `mild_neg`）。但**實際建模的 2010+ 樣本 4 檔全為負偏**（SPY −0.33 已達 treatment
  級）。`group` 純屬描述性欄位，**不進任何檢定或 gate** — 每檔資產都跑完整 H1/H2/H3。
  以 **post-2010 skew** 為相關框架。

### 模型

| Key | Spec | 用途 |
|-----|------|------|
| **M0** | GARCH(1,1) + Gaussian | baseline / tail 比對標準 |
| **M1** | Symmetric Student-t GAS（K1129/K1135 spec, Fisher-scaled score） | 分離「厚尾」與「偏態」兩成分的貢獻 |
| **M2** | **Hansen (1994) skew-t GAS**，static λ 聯合估計 | 主要假設：λ<0 應在負偏 equity 改善 VaR/ES |

### 設計

- **IS**: 2010-01-01 ~ 2019-12-31（乾淨 pre-COVID，與 K1135/K1143 對齊）
- **OOS**: 2020-01-02 ~ 2026-07-06（~6.5y，含 COVID crash / 2022 bear / 2024-25
  AI rally — tail-rich，VaR/ES stress 理想環境）
- **Rolling window** = 1500，**refit every** 63 days
- **QLIKE target** = r²（Patton 2011 proxy-robust）

### 估計（K1213 硬規則）

- **初次 IS fit** 每個 (asset, model)：**≥100 random multistart**，兩階段
  （100 隨機起點 screen @ maxiter=50 → top-5 basin polish @ maxiter=500，選
  global-best log-likelihood）— 避免 single-start artifact。
- **後續 refit**：從前一次 window 參數 **warm-start** + 1 個小擾動（參數隨時間緩變）。
- 所有隨機程序 seed（per (asset,model,refit) 的 deterministic `RandomState`），
  全程可復現。
- **效能**：GAS 遞迴 NLL 用 **numba `@njit`** JIT（36× 加速；`math.lgamma` ==
  `scipy.gammaln` 至 bit level）。腳本啟動時做 **numba-vs-純Python NLL parity 斷言**
  （fail-closed，實測 `max|diff| = 4.77e-12` << 1e-6），確保 JIT 不會 silently
  改變結果。**無 scope reduction** — 100 multistart × 4 資產全數跑完。

### Lag / lookahead 聲明（研究誠實）

- GARCH/GAS 濾波遞迴**本身即 lagged**：`σ²_t` 只依賴 `r_{t-1}` 及更早；等效 `signal.shift(1)`。
- OOS 迴圈：train 到 `t_abs-1` → forecast 用 `r_{t_abs-1}` 預測 `σ²` at `t_abs`
  → 比對 realized `r²_{t_abs}`。**訓練列嚴格早於預測日**，無 lookahead。
- **M0/M1/M2 三模型走完全相同的 refit/forecast 時序**（baseline 同 lag）。
- **反 lookahead 佐證**：M2 在 QLIKE 上**反而略差**於 M0（見下），若有未來資訊洩漏，
  花俏模型會顯得不真實地好 — 此處恰相反，與 K1143 一致。

### 檢定（沿用 K1135 口徑）

- **H1（點預測）**：QLIKE `actual/predicted − log(actual/predicted) − 1`（K783c 方向，
  呼叫 canonical `volpred.stats.model_evaluation.qlike_pointwise`）。M2 vs M0 DM-HLN
  （Harvey 小樣本修正）+ BH-FDR 跨資產。Gate: t>+2 & BH_p<0.05。
- **H2（VaR）**：Trinity = Kupiec POF + Christoffersen joint CC + Engle-Manganelli
  DQ（4 lags），@1% & @5%。
- **H3（ES）**：Acerbi-Szekely (2014) Z1 + Z2，@1% & @5%。
- Student-t / skew-t VaR quantile 做 **unit-variance scaling**（K802；Student-t
  用 `sqrt((ν−2)/ν)`）。
- **不把 asset-day 當 iid**（K1355）：per-asset 檢定 + BH-FDR 跨資產，不做 pooling。

---

## 結果（OOS 2020 ~ 2026）

### 1) IS diagnostic（100-multistart）與偏態

| Asset | post-2010 skew | ν̂_M1 | ν̂_M2 | **λ̂_M2** | OOS realized skew | sign match? |
|-------|---------------:|------:|------:|----------:|------------------:|:-----------:|
| SPY   | −0.331 | 5.74 | 5.61 | **−0.069** | −0.265 | ✅ |
| QQQ   | −0.211 | 5.86 | 5.56 | **−0.094** | −0.153 | ✅ |
| ^TWII | −0.463 | 6.35 | 6.35 | **−0.096** | −0.434 | ✅ |
| ^N225 | −0.244 | 6.19 | 6.14 | **−0.045** | −0.037 | ✅ |

λ̂_M2 **全為負且方向正確**（負偏 equity），但 magnitude 偏小（|λ̂|≈0.05-0.10），與
K1135 商品（|λ̂|≈0.05）同量級 — 說明 static λ 只捕捉到 IS 平靜期的溫和偏態，OOS
極端 tail（COVID/2022）的真實不對稱更大。equity ν̂≈5.6-6.4，比商品（4-8）略集中。

### 2) H1: QLIKE DM-HLN（M2 skew-t vs M0 Gaussian）

| Asset | M0 QL | M1 QL | M2 QL | M2 vs M0 DM t | BH_p | H1 PASS? |
|-------|------:|------:|------:|--------------:|-----:|:--------:|
| SPY   | **1.4949** | 1.5098 | 1.5190 | −2.346 | 0.076 | FAIL（方向反） |
| QQQ   | **1.4995** | 1.4966 | 1.5083 | −1.019 | 0.411 | FAIL（NS） |
| ^TWII | **1.5574** | 1.5673 | 1.5795 | −0.781 | 0.435 | FAIL（NS） |
| ^N225 | **1.5482** | 1.5695 | 1.5754 | −1.721 | 0.171 | FAIL（方向反） |

**H1: 0/4 PASS**。M0 Gaussian 在**全部 4 檔**的 QLIKE 上勝或平手 — skew-t / GAS-t
在 equity 上**完全未改善波動率點預測**，重現 K1143（equity GAS-t harm/null）。
SPY M2 vs M0 t=−2.35（M0 顯著較優）是最強訊號 → **skew-t 不是 equity 的 vol 工具**。

### 3) H2: VaR Trinity（Kupiec + joint CC + DQ）

#### @ 1% VaR

| Asset | Model | viol rate | Kupiec p | CC p | DQ p | Trinity |
|-------|-------|----------:|---------:|-----:|-----:|:-------:|
| SPY | M0 | 2.08% | 0.000 | 0.001 | 0.000 | **FAIL** |
| SPY | **M2** | 1.35% | 0.181 | 0.240 | 0.091 | **PASS** |
| QQQ | M0 | 2.14% | 0.000 | 0.000 | 0.000 | **FAIL** |
| QQQ | **M2** | 1.10% | 0.685 | 0.393 | 0.000 | FAIL（DQ clustered） |
| ^TWII | M0 | 2.41% | 0.000 | 0.000 | 0.000 | **FAIL** |
| ^TWII | **M2** | 1.27% | 0.305 | 0.046 | 0.000 | FAIL（CC/DQ clustered） |
| ^N225 | M0 | 2.20% | 0.000 | 0.000 | 0.000 | **FAIL** |
| ^N225 | **M2** | 0.88% | 0.628 | 0.249 | 0.398 | **PASS** |

#### @ 5% VaR（M2）

| Asset | viol | Kupiec p | CC p | DQ p | Trinity |
|-------|-----:|---------:|-----:|-----:|:-------:|
| SPY | 5.39% | 0.480 | 0.655 | 0.021 | FAIL（DQ） |
| QQQ | 5.20% | 0.710 | 0.896 | 0.114 | **PASS** |
| ^TWII | 5.58% | 0.302 | 0.000 | 0.000 | FAIL（CC/DQ） |
| ^N225 | 5.23% | 0.681 | 0.013 | 0.001 | FAIL（CC/DQ） |

**H2: M2 Trinity PASS 2/4 @1%（SPY, N225）· 1/4 @5%（QQQ）**。M0 GARCH-N @1% VaR
**全 4 檔 coverage 嚴重超標**（viol 2.08-2.41%，2x+ target；Kupiec/CC/DQ 全 p=0.000）
→ M2 把 coverage 拉回 0.88-1.35%。但 **DQ/CC clustering** 常擋下 Trinity：equity
2020-2025 的波動率 clustering（COVID crash、2022 bear）比商品更劇烈，static-λ GAS
score-update 未完全捕捉 → 這是 equity VaR Trinity **弱於** K1135 商品（3/4 @5%）之處。

### 4) H3: ES Acerbi-Szekely Z1 + Z2

#### @ 1% ES

| Asset | Model | Z1 (p) | Z2 (p) | Both PASS? |
|-------|-------|-------:|-------:|:----------:|
| SPY | M0 | +3.72 (0.000) | +3.42 (0.001) | **FAIL** |
| SPY | M1 | +2.10 (0.036) | +2.03 (0.043) | FAIL |
| SPY | **M2** | +1.63 (0.103) | +1.46 (0.145) | **PASS** |
| QQQ | M0 | +3.08 (0.002) | +3.43 (0.001) | **FAIL** |
| QQQ | **M2** | −0.45 (0.655) | +0.32 (0.746) | **PASS** |
| ^TWII | M0 | +2.71 (0.007) | +3.82 (0.000) | **FAIL** |
| ^TWII | **M2** | +1.00 (0.317) | +1.15 (0.249) | **PASS** |
| ^N225 | M0 | +2.40 (0.017) | +3.43 (0.001) | **FAIL** |
| ^N225 | **M2** | +0.78 (0.433) | −0.20 (0.839) | **PASS** |

#### @ 5% ES（M0 vs M2）

| Asset | M0 both | M2 Z1 (p) | M2 Z2 (p) | M2 both |
|-------|:-------:|----------:|----------:|:-------:|
| SPY | FAIL | +1.27 (0.203) | +1.05 (0.292) | **PASS** |
| QQQ | FAIL | −0.08 (0.939) | +0.33 (0.739) | **PASS** |
| ^TWII | FAIL | +1.51 (0.131) | +1.43 (0.153) | **PASS** |
| ^N225 | FAIL | +0.63 (0.531) | +0.58 (0.563) | **PASS** |

**H3: M2 ES PASS 4/4 @1% · 4/4 @5%，vs M0 baseline 0/4 @both**。M0 Gaussian 在
**全部 4 檔** equity ES **顯著低估**（Z1 p 全 < 0.02）→ M2 skew-t **完全 rescue**。
這是 equity 版的 K1135 尾端救援。

**⚠️ 誠實 nuance（救援主體是厚尾，skew 是邊際加值）**：ES 救援**主要來自
Gaussian→Student-t** 的厚尾切換，**非 skew 獨有**：M1 對稱 GAS-t 已在 QQQ/N225 的
1% ES PASS（Z1p=0.62/0.60），M2 skew-t 只在**最強負偏的 SPY/^TWII** 上把 M1 未過的
補到 4/4（SPY M1 Z1p=0.036 FAIL → M2 0.103 PASS；^TWII M1 Z2p=0.023 FAIL → M2
0.249 PASS）。這與 K1135 limitation #4「Student-t innovation 本身貢獻大」完全一致。
**正確 framing = 「GAS + 厚尾（Student-t / skew-t）innovation 救 equity ES；skew-t 在
最負偏指數上加碼」**，不可過度宣稱是 skew 單獨的功勞。

---

## Verdict: **Scenario B — 延伸（EXTENDS）**

| Hypothesis | M2 PASS | M0 baseline | 判定 |
|------------|:-------:|:-----------:|------|
| **H1 QLIKE DM**（t>+2 & BH_p<0.05） | **0/4** | — | **FAIL**（vol 不救，同 K1143） |
| **H2 VaR Trinity @1%** | 2/4 | 0/4 | 部分改善 |
| **H2 VaR Trinity @5%** | 1/4 | 1/4 (QQQ) | clustering 擋下 |
| **H3 ES Z1+Z2 @1%** | **4/4** | **0/4** | **PASS**（完全 rescue） |
| **H3 ES Z1+Z2 @5%** | **4/4** | **0/4** | **PASS**（完全 rescue） |

→ **Scenario B（QLIKE NULL、VaR/ES 改善）在 equity 上重現**。
**K1135 商品的 skew-t GAS 尾端救援現象「延伸到股票指數」。**

## 與 K1135 商品結果並列比較

| 指標 | **K1135 商品**（USO/UNG/GLD/SLV） | **K1654 equity**（SPY/QQQ/TWII/N225） | 異同 |
|------|:-------------------------------:|:-----------------------------------:|------|
| H1 QLIKE PASS | 0/4 | 0/4 | **相同**（skew-t 不救 vol） |
| H2 VaR Trinity @1% | 2/4 | 2/4 | **相同** |
| H2 VaR Trinity @5% | 3/4 | **1/4** | **equity 較弱**（DQ/CC clustering 更強） |
| H3 ES @1%（M2 vs M0） | 4/4 vs 1/4 | **4/4 vs 0/4** | equity **M0 更差**、M2 救援相同 |
| H3 ES @5%（M2 vs M0） | 4/4 | 4/4 | **相同** |
| IS λ̂ magnitude | ≈0.05 | ≈0.05-0.10 | 相近（皆偏小） |
| 救援主體 | Student-t 厚尾 + skew 邊際 | 同（Student-t 厚尾 + skew 邊際） | **相同機制** |
| Verdict | Scenario B | **Scenario B（EXTENDS）** | ✅ 延伸 |

**結論**：equity 與 commodity 的 skew-t GAS 呈現**同一個 asset-class-robust 的
Scenario B pattern** — GAS + 厚尾 innovation 是**跨資產類別的 ES 尾端風險工具，而非
vol forecasting 工具**。唯一差異：equity 的 VaR **coverage-independence（DQ/CC
clustering）** 在 2020-2025 更難通過，因為 equity 危機期的波動率 clustering 比商品
更集中 → 需要 leverage-augmented（GJR-skewt）GAS 才能修 clustering（follow-up）。

## 局限（誠實揭露）

1. **ES 救援主體是厚尾非 skew**（見上）：M1 對稱 GAS-t 已救 2/4，M2 skew-t 邊際加值到
   4/4。不可宣稱 skew-t 單獨救 equity ES。
2. **VaR DQ/CC clustering 未解**：equity @5% Trinity 僅 1/4（vs 商品 3/4）— static-λ
   GAS 未捕捉 equity 危機期的極端 vol clustering。**GJR-skewt GAS**（加 leverage γ）為
   follow-up candidate。
3. **static λ**：Gonzalez-Rivera et al (2014) time-varying skew GAS 未實作；IS λ̂≈0.07
   遠小於 OOS extreme tail 反映的不對稱。
4. **M0 baseline 是 GARCH-N**：若用 GARCH-t 作 baseline，ES 救援幅度會縮小（M1 已顯示
   Student-t innovation 貢獻大）— 本實驗刻意用 Gaussian baseline 以對齊 K1135，供
   跨市場可比性。
5. **OOS 期間**：2020-2026 tail-rich（COVID/2022/AI rally）；ES rescue 是否依賴
   extreme events，可用 2012-2019 quiet-regime OOS 做 robustness（follow-up）。
6. **λ̂ 幅度小**：equity IS 2010-2019 較平靜，static skew-t 未完全發揮；OOS realized
   skew（N225 −0.04 最弱）與 IS λ̂ 對齊但 magnitude 偏小。

## 對 Paper 4 Channel 3 的貢獻

K1135 已定「GAS-skewt 是 commodity tail-risk 工具，非 vol forecasting 工具」。
K1654 把此結論**升級為跨資產類別**：

> "The Scenario-B tail rescue is **asset-class-robust**: on both commodities (K1135)
> and equity indices (K1654), GARCH-N materially under-estimates 1% ES (all 4 equity
> indices Z1 p < 0.02), while GAS with fat-tailed innovations passes Acerbi-Szekely
> Z1+Z2 at 4/4 for both 1% and 5% ES. The improvement is driven primarily by the
> Student-t innovation (M1 symmetric GAS-t already rescues 2/4 equity indices), with
> the Hansen skew-t (M2) adding marginal value on the most negatively-skewed indices
> (SPY, ^TWII). QLIKE is null everywhere (0/4 equity, 0/4 commodity), and VaR
> coverage-independence (DQ) is the binding constraint on equity where 2020-2025
> volatility clustering is sharper. GAS-skewt is a cross-asset-class ES tool, not a
> volatility forecasting tool."

平台 monetization：equity VaR/ES 風險產品應以 **GAS-t / GAS-skewt 報 ES**（1% & 5%
皆 4/4 通過 Acerbi-Szekely），但 **VaR coverage 需搭配 clustering-aware 調整**。

## 衍生新方向

1. **GJR-skewt GAS**（leverage γ + skew-t）— 修 equity VaR DQ/CC clustering（@5% 僅 1/4）
2. **Time-varying λ GAS**（Gonzalez-Rivera 2014）— IS λ̂≈0.07 太小，λ_t 應 better capture
   COVID/2022 extreme tail
3. **GARCH-t baseline 對照** — 量化「厚尾 vs skew」各自對 ES 救援的貢獻份額
4. **Quiet-regime OOS（2012-2019）robustness** — ES rescue 是否依賴 extreme events

## 檔案

- `k1654.py` — 完整可復現腳本（seed=42，numba-JIT NLL + parity 斷言，明確 lag）
- `k1654_results.json` — per-asset QLIKE + DM/BH + VaR×3 檢定×2 levels + ES Z1/Z2×2
  levels + IS diagnostic + verdict
- `equity_skew_vs_gauss.png` — 4 指數經驗 PDF vs Gaussian reference（log scale）
- `var_es_backtest.png` — VaR Trinity + ES Z1/Z2 p-value heatmap（2 levels × 4 assets × 3 models）
- `run.log` — 完整執行日誌（含 parity 斷言、per-asset 進度、cross-asset summary）

## 參考

- Creal, Koopman, Lucas (2013). *J. Applied Econometrics* 28(5):777-795 — GAS framework
- Hansen, B. E. (1994). *International Economic Review* 35(3):705-730 — skew-t density
- Gonzalez-Rivera, Maldonado, Perez (2014). *IJF* 30(3):529-550 — time-varying skew/kurt
- Patton, A. J. (2011). *J. Econometrics* 160:246-256 — QLIKE proxy-robust
- Harvey, Leybourne, Newbold (1997). *IJF* 13:281-291 — DM small-sample correction
- Kupiec (1995); Christoffersen (1998) *IER* 39(4):841-862; Engle-Manganelli (2004) *JBES* 22(4):367-381
- Acerbi, Szekely (2014). *Risk* 27(11):76-81 — ES backtest Z1/Z2
- Benjamini, Hochberg (1995). *JRSS B* 57(1):289-300 — FDR control

## 關聯實驗

- **K1135**（直系前身）：commodity skew-t GAS → Scenario B tail rescue
- **K1143**（equity diagnostic）：equity skew-t QLIKE-only，判 architectural incompat（未評估 tail）
- **K1129**：commodity symmetric GAS-t QLIKE NULL
- **K1138**：equity GAS-t HARMFUL on QLIKE（SPY DM t=−3.27）
- **K802 / K783c / K1213 / K1355 / K1416**：methodology 硬規則（unit-variance VaR / QLIKE 方向 / 100-multistart / no asset-day pooling / uniqueness re-check）
