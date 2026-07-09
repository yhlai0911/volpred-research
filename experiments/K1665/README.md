# K1665 — 原油波動率 → 股市波動率 spillover（vol-of-vol 傳導）

**Verdict:** **NULL**（一階 realized-vol level）＋ vov 二階殘留訊號無 VIX 增量
**Run:** 2026-07-09（台灣時間），worktree `agent-K1665`
**核心一句話：** 用 plain F-test（K1444/常見做法）看 oil→equity vol Granger 是 4/4 極顯著（p~1e-19）；改用**正確的 Newey-West HAC-Wald** 後，一階 realized-vol 全部崩解（0/4 過 Bonferroni、0/4 過 Harvey），控制 VIX 後徹底歸零。所謂「油波動傳染股市波動」在**可預測、增量**意義上不成立——它主要是**同期共同風險因子（VIX）**的反映。

---

## 1. 研究問題與差異化

### 問題
原油**已實現波動率（realized vol）的衝擊**，是否**領先／傳導**到股市（SPY）與能源股（XLE）的**波動率**（不是報酬），且此 lead 在 (a) 正確處理重疊窗自相關、(b) 控制 VIX、(c) 樣本外 之後還存活？

這是**波動→波動**的問題（相對於報酬的二階矩），不是價格漲跌問題。

### 為何這不是全新發現（誠實 / 查重）
本主題在本 lab 已被多個 K 深度覆蓋，本實驗**明白定位為方法論升級的複製，不宣稱新發現**：

| 先驗 K | 內容 | 與 K1665 關係 |
|---|---|---|
| **K422** | commodity vol→equity vol network；Oil→SPX Granger p≈0，但**控制 VIX 後 NS** | K1665 一階 VIX-control 結果與之一致 |
| **K861** | 一階 oil-vol→equity-vol **level** spillover（asymmetric, t=5.82） | K861 是 level/asymmetric 角度 |
| **K1088** | USO+OVX cross-section forecast PASS（asset-matched） | 不同 target（OVX 隱含波動） |
| **K1329** | CL/USO→SPY/XLE/XOP，14 Granger pairs 顯著，但**無 OOS forecast edge**（best QLIKE +0.30%，DM t=−0.52） | K1665 一階 OOS 結果複製之 |
| **K1351** | CL=F/USO→SPY/XLE/XOP，**NULL_NO_HARVEY_PASS** | 同結論 |
| **K1444** | CL=F/USO/SPY/XLE **vol-of-vol**（std-of-RV）；DY spillover 48.8%；期貨為 net receiver。**Codex 標註：Granger 標了「HAC」但實際用 plain ssr F-test，proper HAC-Wald 從未做** | **K1665 直接補這個 gap** |

### K1665 的增量（方法論，非新奇性）
1. **Proper Newey-West HAC-Wald Granger**——K1444 的 review 明確要求的 follow-up。重疊 21 天 rolling realized-vol 天然帶 MA(21) 結構，plain F-test 在自相關殘差上會**系統性過度拒絕** H0。
2. **明確反向控制**（equity→oil）與雙向讀法。
3. **VIX-control 增量檢定**——油波動在**控制 VIX 之後**是否還帶增量預測力（K422/K148「VIX sufficient statistic」主題）。
4. **XLE vs SPY 差異**作為經濟直覺 sanity check（能源股應更受油影響）。
5. **樣本外 forecast 檢定**——區分「統計 spillover」與「增量 forecast 價值」（K1329/K1351 反覆的教訓）。

### 文獻
1. Diebold & Yilmaz (2012), *Better to give than to receive*, IJF 28(1), 57–66.
2. Maghyereh, Awartani & Bouri (2016), *Directional volatility connectedness between crude oil and equity markets*, Energy Economics 57, 78–93.
3. Du & Tepper (2014), *Cross-market dynamics in spillovers between crude oil and equity market volatilities*, Energy Economics 55, 1–14.
4. Newey & West (1987), *A simple, positive semi-definite, heteroskedasticity and autocorrelation consistent covariance matrix*, Econometrica 55(3), 703–708.
5. Harvey, Leybourne & Newbold (1997) 小樣本 DM 修正；Harvey (2016) |t|>3 多重檢定門檻。

---

## 2. 資料

| | |
|---|---|
| 來源 | yfinance `download(auto_adjust=True)` daily Close |
| Tickers | `CL=F`（WTI 近月期貨）、`USO`（原油 ETF）、`SPY`（大盤）、`XLE`（能源股 ETF）、`^VIX`（控制變數） |
| 期間 | 2012-02-02 → 2026-07-08 |
| 樣本數 | **N = 3,498**（共同交易日；≥500 硬規 ✅），OOS 含 2015-16、2018Q4、2020 COVID、2022 能源衝擊等多次空頭 |
| 波動率 proxy | 21 日 rolling std of daily log-return × √252（annualized realized vol） |
| vov（二階，K1444 物件） | 21 日 rolling std of 上述 RV |

**CL=F 負油價處理**：2020-04-20 WTI 近月結算 −$37.63。log-return 在 P≤0 未定義 → 對非正價格日 mask（代碼 `log_returns()` 中 `close.where(close>0)`，並清除 ±inf）。

---

## 3. 方法（防錯硬規）

- **Lookahead**：所有 predictor 明確 lagged。回歸為 `target_t ~ target_{t-i} + source_{t-i}`（i=1..5）＋ VIX-control 用 `VIX_{t-1}`。OOS 用 expanding window，在 `[:t]` 擬合、預測 index `h≥t`，baseline 與 augmented **同 lag/同窗**。
- **HAC-Wald Granger**（本實驗核心）：OLS `E_t = c + Σaᵢ E_{t-i} + Σbᵢ O_{t-i} + ε`，Newey-West HAC 共變異數（`maxlags = max(21, NW rule)`），Wald test H₀: 所有 bᵢ=0。反向同法。
- **多重檢定**：4 個 oil→equity pair，Bonferroni α=0.0125；效應顯著門檻用 Harvey **|t|>3**。
- **跨資產不 pool**：SPY、XLE **各自獨立回歸**，不把 asset-day 當 iid（`.claude/rules/experiments.md`）。
- **DM-HLN**：一階 OOS 用 horizon=1 的 DM ＋ Harvey-Leybourne-Newbold 小樣本修正。
- **seed=42** 全程固定。
- **診斷對照**：同 pipeline 亦跑 statsmodels `grangercausalitytests`（ssr F），作為「非 HAC」對照，證明 K1444 式強顯著可複製、差異純來自 HAC 處理。

---

## 4. 結果

### 4.1 核心對照：plain F-test vs proper HAC-Wald（oil → equity，一階 RV）

| Pair | Naive ssr F（非 HAC）best-p | **HAC-Wald p** | **max\|t\|** | 過 Bonferroni? | 過 Harvey? |
|---|---|---|---|---|---|
| CL=F→SPY | **4.5e-19** | 0.045 | 2.11 | ✗ | ✗ |
| CL=F→XLE | 8.4e-06 | 0.228 | 2.28 | ✗ | ✗ |
| USO→SPY | **2.8e-19** | 0.093 | 2.93 | ✗ | ✗ |
| USO→XLE | 1.2e-03 | 0.342 | 1.97 | ✗ | ✗ |

**→ plain F-test 的「4/4 極顯著」完全是重疊窗（MA-21）自相關造成的假象；正確 HAC 下 0/4 過 Bonferroni、0/4 過 Harvey。**

### 4.2 VIX 控制（一階）：油波動有無增量？

控制 **VIX 指數水準** `VIX_{t-1}`（注意：控制的是 VIX **指數值**，非 VIX 報酬的波動——見 §8 review 修正）後，油波動 lag 係數 t 值全部不顯著、符號轉負；**VIX 本身高度顯著**：

| Pair \| VIX | oil-lag **t** | VIX t | 油過 Harvey? |
|---|---|---|---|
| CL=F→SPY | −1.77 | **+6.10** | ✗ |
| CL=F→XLE | −0.82 | **+4.13** | ✗ |
| USO→SPY | −1.89 | **+6.04** | ✗ |
| USO→XLE | −0.86 | **+4.03** | ✗ |

**→ 一階油波動對股市波動零增量（max |t|=1.89）；VIX 指數水準是充分統計量（複製 K422/K148）。**

### 4.3 樣本外 forecast（reconcile 統計 vs 可用性）

expanding window，own-lag baseline vs own+oil-lag augmented，一階 RV。DM 用 **HAC 校正（Bartlett lags=21，配合 overlapping RV target 的 MA 結構**——見 §8 review 修正）：

| Pair | MSE 改善 | DM-HLN t (hac=21) | augmented 顯著較優 (t>3)? |
|---|---|---|---|
| CL=F→SPY | +1.08% | +1.17 | ✗ |
| CL=F→XLE | **−1.29%（惡化）** | −2.06 | ✗ |
| USO→SPY | +1.09% | +0.86 | ✗ |
| USO→XLE | −0.92%（惡化） | −1.25 | ✗ |

**→ 無穩健 OOS edge，能源股甚至變差（複製 K1329/K1351）。** 註：edge 計數用**方向性 gate**（t>3，即 augmented 顯著較優），非 |t|>3——顯著較差不可誤計為 edge。

### 4.4 二階 vov（K1444 的確切物件）在 proper HAC 下的部分修正

naive ssr F 由**本 pipeline 自算**（非引用 K1444）；VIX 對照同時報 VIX 指數水準與 order-matched 的 vol-of-VIX：

| Pair（vov）| naive ssr-F p | HAC nw=21 \|t\| | HAC nw=42 \|t\| | 過 Harvey? | \|VIX-level t_src | \|vol-of-VIX t_src |
|---|---|---|---|---|---|---|
| CL=F→SPY | 1.9e-67 | 3.54 | 3.44 | ✅ | −1.34（死）| +0.08（死）|
| CL=F→XLE | 1.0e-63 | 4.60 | 4.60 | ✅ | −1.55（死）| −0.48（死）|
| USO→SPY | 1.5e-20 | 0.77 | 0.78 | ✗ | −1.05 | +0.62 |
| USO→XLE | 7.9e-03 | 1.60 | 1.55 | ✗ | −0.60 | +0.66 |

**→ vov 的 naive「4/4 顯著」在 proper HAC 下降為 2/4 存活（僅 CL=F 期貨，對 nw=42 記憶匹配穩健，非欠校正 artifact）；這 2 個存活訊號在 VIX 指數水準與 vol-of-VIX 兩種控制下**皆歸零（0/4）**。**
**淨結論：naive-F 4/4 → HAC 2/4 → 任一 VIX 控制後 0/4——部分修正 K1444 的 plain-F 計數，非完全崩解，但無任何可交易/增量價值。**

### 4.5 XLE vs SPY 差異（經濟直覺 sanity check）
HAC 下 oil→XLE 未穩健強於 oil→SPY（CL=F 略 XLE>SPY，USO 反之，兩者皆 |t|<3）。能源股對油的更高敏感度是**同期的**（concurrent beta），**不構成領先**（lead）。

---

## 5. 圖表
- `K1665_fig1_rv_overlay.png`：CL=F/USO/SPY/XLE 21 日 realized vol 時序疊圖（log 軸，標 2020 COVID / 2022 能源衝擊）——四者在危機期**同步**飆升，肉眼即見「同期共動」而非「油領先」。
- `K1665_fig2_hac_coefficients.png`：HAC-Wald Σβ（source lags）長條圖 ＋ |t| 標註（SPY / XLE，含反向）——所有 bar |t|<3。

---

## 6. 誠實聲明與結論強度
- **Verdict = NULL**（一階 realized-vol level，即 brief 主要框架「realized vol shock → equity vol」）。二階 vov 有 CL=F 特定的殘留統計 lead，但**無 VIX 增量、K1444 已測得其 DY 方向與假設矛盾**，故不升級為 positive。
- 結論強度**不超過證據**：本實驗說的是「在此 spec 集（一階 RV proxy、日頻、HAC、VIX 控制、一步 OOS）下，油波動對股市波動無穩健、可增量、可預測的傳導」。**不等於**「油與股市波動無任何關係」——同期相關與危機共動確實存在（見 fig1），只是被 VIX 充分吸收。
- **主要貢獻**：把本 lab 反覆出現的「統計 spillover ≠ 可用 forecast 訊號」用**正確的自相關穩健檢定**釘死，並具體修正 K1444 因 plain-F 誇大的顯著性。**「VIX sufficient statistic」再次確認。**
- 所有數字由 `K1665.py` 實算，結果在 `K1665_results.json`。yfinance live data 會隨時間微漂（reproducibility floor）；seed 已固定。

## 7. 是否值得寫成 reader-facing 文章
**值得**，迷思實驗室角度：**「油價一波動，股市就跟著抖？——數據說：那只是它們同時在怕同一件事」**。賣點：(1) 一張 fig1 同步飆升圖直觀；(2) 「用錯的檢定會看到 p=0.000000000000000000045 的假顯著，用對的就消失」是很好的統計素養教育點（HAC / 重疊窗陷阱）；(3) 「VIX 已經把油的資訊吃光了」的 sufficient-statistic 敘事。**注意**：發佈前主線程需做 3-layer 查重（與 K422/K1329/K1351 既有文章是否重複），且務必寫成「無穩健**領先/增量**傳導」而非「無關係」（避免過度宣稱）。

---

## 8. Code review 記錄

- **Reviewer**：`feature-dev:code-reviewer` subagent（independent fresh-context fallback）。**Codex CLI 當時額度用盡（至 2026-07-11）**，依 `.claude/rules/experiments.md` fallback 條款改派。
- **初版 verdict：CONDITIONAL_PASS**，抓到 3 個問題，本版**全部已修並重跑**：
  1. **[Critical] VIX 控制物件錯誤**：原用 `rv["^VIX"]`＝VIX 報酬的 realized vol，非 VIX 指數水準 → 「VIX sufficient statistic」sub-claim 未對正確物件檢定。**已修**為 `close["^VIX"]`（VIX 指數水準）；修正後 VIX 更顯著（t=4.0–6.1），結論不變且更強。並額外加 order-matched 的 vol-of-VIX 對照。
  2. **[Important] `dm_hln` 的 `harvey_pass` sign-agnostic**（`abs(t)>3`）被用來數「augmented 較優」的 edge → 顯著較差會被誤計。**已修**為方向性 gate `dm_hln_t>3`（`augmented_better_sig`）。
  3. **[Important] OOS DM 未 HAC 校正 overlapping RV target**（horizon=1 無自相關校正）。**已修**為 Bartlett/Newey-West lags=21；如 reviewer 預期，|t| 幅度縮小（CL=F→XLE −2.75→−2.06），更強化 NULL。
- **Reviewer 確認乾淨**：lookahead（全 `shift(i≥1)`、OOS 訓練 `[:t]` 預測 `h≥t`、baseline/augmented 同窗同 lag）、CL=F 負油價 mask、Wald restriction matrix 只選 source lags、DM-HLN 公式與符號、scoreboard 與逐 pair 值完全一致。
- **核心 NULL verdict 全程 reviewer 判定 trustworthy**（獨立於上述 3 問題）。
