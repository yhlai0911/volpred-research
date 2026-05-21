# Paper 2 EAV Universal-Magnitude — Early-Stage Scaffold Review v1

**Reviewer**: 主線程（Claude Opus 4.7 1M）
**Date**: 2026-05-16
**Scope**: README.md + abstract_working.md + lit_review.md (3 檔，僅 scaffold；body.tex 尚未存在)
**Mode**: byte-traceable claim audit, lit gap check, scope check, honesty gate
**Verdict**: **NEEDS_REWRITE**（5 大 weakness，2 個達 SCOPE-level）

---

## TL;DR — 主要 weakness

Scaffold 把一份**已在 `research_program.md` 升級為「三市場（TW+US+JP）universal regularity」的決策**，**錯位降級**寫成「TW IS + US OOS 雙市場 universal-magnitude」（README §0 status / Abstract / §5 Cross-Market 都缺 JP/K1150）— 落後 `research_program.md` 2026-05-17 K1146 DECISION_MADE 結論。同時 abstract 第一句即犯「2 markets = universal」over-claim 紅燈、混淆 IS θ̂ 與 OOS DM t 的不同 inference 語意、placebo「13.6σ」數字實際只 13.27σ（rounding 失真且未說明 σ 定義）、納入未顯著但呈現正向的數字而完全略過 narrative 中**已是 paper 核心轉折的 null heterogeneity 證據鏈**（K1109/K1113/K1114/K1140 一條未提）。整體呈現「selective positive framing」傾向，與 CLAUDE.md 研究誠實第 6 條（結論強度不超過證據；null 如實報告）距離尚遠。Body.tex 在此 scaffold 基礎上展開會直接複製這些 framing 偏誤，需先在 scaffold 層 rewrite。

---

## 1. Claim–Evidence Matching Audit

### 1.1 Abstract 數字 byte-trace 結果

| Abstract 引用 | Scaffold 標示來源 | JSON 實際值 | Status |
|---|---|---|---|
| θ̂_EAV = +6.36 × 10⁻⁵（TW pooled） | K1145 | `k1145_results.json.main_fit_eav_window_1.theta_eav = 6.362165e-05` | ✅ MATCH |
| cluster-bootstrap t = +5.24 | K1145 | `k1145_results.json.cluster_bootstrap.t_stat = 5.24205` | ✅ MATCH |
| placebo distance = **13.6σ** | K1145 | `(observed - placebo_mean) / placebo_se = (6.3622e-5 − 1.356e-6) / 4.691e-6 = 13.27σ` | ⚠️ **數字失真 + σ 定義缺失** |
| panel DM t = −5.58（US OOS binary） | K1148_d2 | `four_row_table[0].panel_DM_t_OOS = -5.5802` | ✅ MATCH |
| Harvey \|t\| > 3.0 | (implicit threshold) | 5.58 > 3.0 ✓ | ✅ MATCH |
| 5 robustness layers | (claim) | K1145 README 列出 5 (panel diag + window 1/3/5 + dropout + k1109 single-stock compare + BH-FDR + placebo) — 數得出來 | ✅ 對得上 |

**Weakness A1 — placebo 13.6σ → 13.27σ**：scaffold 寫 13.6σ；自己重算 (observed − placebo_mean) / placebo_se = 13.27。差異 0.33σ 不大但**寫進 abstract 的數字必須對得上 JSON 與 reproduce.py**（paper-workflow.md 硬規則 3：每個 Table row → JSON traceable binding）。更嚴重的是 abstract 對「σ」的定義從未說明 — 是 placebo theta 的 cross-permutation SE？還是 bootstrap SE？讀者無法 reproduce。**這是審稿人首問必中的點**。

**Weakness A2 — IS Hessian t-stat vs OOS DM t-stat 語意混用**：Abstract 把「θ̂_EAV = +6.36×10⁻⁵ (t=+5.24)」+「panel DM t = −5.58」並排寫，讀者誤以為兩 t 同質。實際：前者是 IS pooled θ 顯著（H₀: θ=0），後者是 OOS forecast loss 差異（H₀: model A loss = model B loss；負 t 代表 EAV-augmented model 比 baseline 在 OOS QLIKE 上**更低 loss**）。兩個 t 不同 null、不同 sample（IS vs OOS）、不同 inference target，需要在 abstract 明確分開語句結構，不能用「panel DM t = −5.58 confirms the magnitude」這類銜接 — DM test **不驗證 magnitude，只驗證 predictive ability**。

**Weakness A3 — Convergence flag 未揭露**：`k1145_results.json.main_fit_eav_window_1.converged = false`、`robustness_eav_window.window_3.converged = false`、`window_5.converged = false`、K1148_d2 `is_fit.converged = false` — 主要與 robustness fits **全部 converged=false**。Outer loop 看似收斂（連續 iter Δ < 1e-7）但 scipy 回傳 False 必須在 paper / replication package 明確說明 convergence criterion 為何 disagree（很可能是 BFGS gradient tol 太嚴；K1213 教訓也提到「套件限制 ≠ 模型無效」）。**Reproduce gate 一定會被擋下**。

### 1.2 「Universal firm-event constant」over-claim 紅燈（最嚴重）

Abstract 結語：

> *"We conclude that earnings-day volatility amplification is a **universal firm-event constant**, best captured by a binary indicator..."*

**問題**：

1. **「universal」要 ≥3 markets 是學術慣例**。TW + US = 2 markets，只能說 "cross-market evidence" / "robust to two-market cross-validation"，不能說 universal。
2. **「constant」與資料矛盾**：TW pooled θ̂_EAV = 6.36×10⁻⁵，US pooled θ̂_EAV = 1.77×10⁻⁴（four_row_table US binary IS θ）— **US 是 TW 的 2.78 倍**。這距離 "constant" 很遠，距離 "same sign, similar order of magnitude" 才合理。
3. **`research_program.md` K1146 DECISION_MADE (2026-05-17) 已升級為 3 市場 (TW K1145 + US K1147 + JP K1150)** — magnitude ordering US 1.91e-4 > JP 1.41e-4 > TW 6.36e-5。Scaffold 完全沒提 JP / K1150 / K1147，反而用 K1148_d2（US OOS panel DM）當 cross-market 證據 — 把「OOS forecast 改進」當成「magnitude estimate」用，是兩件事。
4. **scenario A 的真正內容（K1149）**：是 EAV survives PCA factor absorption，**不是** EAV magnitude 相等。Scaffold §6 「Factor Robustness — Scenario A」呈現 OK，但 Abstract 「universal-magnitude」結論超越 K1149 證據。

**修正方向**：abstract 結語改為 "earnings-day volatility amplification is a **robust, cross-market positive effect with market-specific magnitude ordering**, best..."，並把第 3 個 market (JP) 補上。

---

## 2. Literature Review Gap Check

### 2.1 缺漏（high priority）

| 缺漏 | 理由 |
|---|---|
| **Patell (1976) JAR** | "Corporate forecasts of earnings per share and stock price behavior" — **真正首篇** earnings announcement return/variance event study。lit_review 寫的「Patell & Wolfson (1979)」是 follow-up；單篇 Patell 1976 是 canonical anchor，**必引**。 |
| **Beaver (1968) JAR Supplement** | "The information content of annual earnings announcements" — earnings 公告日 trading volume + variance 兩倍 baseline。Lit_review 雖列 #3 但寫 "volume/variance changes"，要明確引 Beaver 1968 的 variance ratio finding 與本研究 amplification ratio 對話。 |
| **Bollerslev (1986) JoE** | GARCH 原典。Multiplicative GARCH 系列 (Engle-Rangel 2008 / Engle-Ghysels-Sohn 2013) 須在 Bollerslev 1986 baseline 之後引入。 |
| **Bollerslev–Patton–Quaedvlieg (2016) JBES** | "Exploiting the errors: A simple approach for improved volatility forecasting" — QLIKE loss 在 noisy proxy 下的最優 loss function 性質，與本研究 DM test loss 選擇直接相關。 |
| **Harvey, Liu, Zhu (2016) RFS** | "...and the Cross-Section of Expected Returns" — multiple testing in finance。本研究 5 robustness layers + 跨 spec 比較理應跑 multiplicity correction，引 Harvey-Liu-Zhu 並做 Bonferroni / BH adjustment。 |
| **Diebold (2015) JBES** | "Comparing Predictive Accuracy, Twenty Years Later" — DM test pitfalls + Harvey-Leybourne-Newbold 校正使用準則。OOS DM 是本 paper 主要 inference 工具，**必引**。 |

### 2.2 lit_review.md 既列引文驗證

| Citation | 風險 |
|---|---|
| **Engle & Rangel (2008) RFS** "Spline-GARCH" | ✅ exact title 對；但本研究的 multiplicative decomposition `σ² = g·τ` 比較接近 **GARCH-MIDAS (Engle-Ghysels-Sohn 2013)** 框架不是 spline；引用要對齊 specification — 別誤導讀者以為用 spline component。 |
| **Engle, Ghysels, Sohn (2013) JBES** | ✅ exact 對；但需確認 J of B&ES 還是 Review of Economics and Statistics（GES 2013 確為 ReStat 不是 JBES — **可能 citation error，待 citation-verifier 確認**）。 |
| **Trapani (2013) / De Luca-Zuccolotto (2017)** | 模糊：lit_review 列「or」表示尚未決定。Panel GARCH 真正 canonical 是 **Pesaran-Schuermann-Weiner (2004) JBES** 或 **Bauwens-Laurent-Rombouts (2006) JoE survey**，需具體化。 |

**Weakness B1 — 缺 Patell 1976 / Beaver 1968 canonical EAV 文獻**：lit_review 寫 Patell-Wolfson 1979 + Ball-Kothari 1991 + Beaver 1968 但深度不夠，未引出 amplification ratio / variance ratio 具體數字對照（本 paper 找到的 θ_EAV 對應市場 baseline σ² 的 amplification factor 沒算出來與 Beaver 1968 的 2× variance ratio 對話 — 這是 contribution 的最直接 anchor）。

**Weakness B2 — 缺 multiplicity correction 文獻**：5 robustness layers + 4 specs（TW binary, TW continuous, US binary, US continuous）+ window 1/3/5 等 = 至少 12-15 個 hypothesis tests。BH-FDR 在 K1145 跑了 3 列，但 paper 級 multiplicity 須跨所有 spec 全表 — 引 Harvey-Liu-Zhu 2016 / Romano-Wolf 2005 才有方法論底氣。

**Weakness B3 — DM test methodology citation 缺**：cross-market OOS panel DM (K1148_d2) 是論文主結果之一但 lit_review 沒列 Diebold-Mariano (1995) / Harvey-Leybourne-Newbold (1997) / Diebold (2015) 任何一篇 — **這是審稿人 5 分鐘內必抓的紅燈**。

---

## 3. README Narrative Scope

### 3.1 vs `paper/taiwan-vt/`（重疊風險）

grep `paper/taiwan-vt/body_v3.tex` 內 earnings/EAV/announcement：**0 hits**。Taiwan-VT paper 寫的是 VT strategy + leverage (γ) + dividend ex-date + diversification amplification，與 EAV 完全分開 scope。**無重疊風險** ✅。

但 README §0 沒明寫這個切割，建議 add：

> *"This paper is independent of `paper/taiwan-vt/` (VT-strategy + concentration-amplification) and `paper/leverage-direction/` (γ asymmetry direction). It focuses exclusively on earnings-event variance amplification."*

### 3.2 README vs `research_program.md` 同步（嚴重落後）

`research_program.md` 2026-05-17 K1146 DECISION_MADE：**3 markets (TW + US + JP)** magnitude ordering universal regularity，narrative state = `decision_made_awaiting_body_rewrite`，body rewrite plan 是新增 §6（不是現 README §4-§6）。

Scaffold README：

- 標題："Universal-Magnitude Evidence from **Taiwan and U.S.** Equity Markets" — **缺 Japan**
- §0 Decision Record：寫「Option 4+ (K1149 Scenario A)」— 對應 K1149 但**沒提 K1146**
- §5 章節：寫「US Out-of-Sample Validation (K1148_d2) — cross-market OOS DM test」— 但 `research_program.md` §6.3 正確寫法是「Cross-market validation (K1147 US + K1150 JP)」用 IS pooled θ_EAV 配置（K1147、K1150 都是 pooled IS，類似 K1145 對 TW），**不是用 K1148_d2 (US OOS panel DM with TW-fitted spec)**
- Supporting Experiments 表：缺 K1146 / K1147 / K1150

**Weakness C1 — Scaffold 與 research_program.md 不同步 / 用錯實驗作為 cross-market 證據**：scaffold 把 K1148_d2 當 universal-magnitude 證據誤用 — K1148_d2 是「TW 訓練、US OOS test」spec consistency cross-market，**不是 magnitude estimation per market**。K1146 三市場 universal regularity 的正確證據鏈是 K1145 (TW IS) + K1147 (US IS) + K1150 (JP IS) 三組 independent pooled estimate，**每個市場各自 5-layer robustness**。Scaffold 走的證據路徑 (TW IS + US OOS panel DM + PCA factor absorption) 比 research_program.md 走的路徑更弱，且 inference 語意混亂。

### 3.3 Differentiation vs taiwan-vt EAV section

`grep taiwan-vt EAV: 0 hits` — 不存在差異化問題（taiwan-vt 完全沒寫 EAV）。但 K1141 README 提到 Paper 4 用 K1141 「dual NULL body rewrite」— **Paper 4 ≠ Paper 2**（Paper 4 是 `vix-sufficiency`），scaffold README §0 寫 K1141 「supersedes by K1146_body」需確認 K1141 確實是 Paper 2 的 super seded plan 而非 Paper 4 — 從 `research_program.md` 看是 Paper 2，但 K1141 README 自己寫 "Paper 4 §4 Channel-Specific" — **K-ID 之間 paper 歸屬混淆，需澄清**。

---

## 4. Honesty Gates

### 4.1 Null result 揭露 — **重大缺失**

K1109 / K1113 / K1114 / K1140 在 `research_program.md` 是 Paper 2 narrative 的 **★ 主轉折點**：

> *"After N=31 sector ANOVA + 5 firm covariates + rolling HAC + block-bootstrap, no systematic source of θ_EAV heterogeneity survives multiple-testing correction."*

K1146 DECISION_MADE 段明確說：

> *"與 K1109/K1113/K1114/K1140 null heterogeneity 的關係：互補而非矛盾 — within-market 找不到 firm-attribute predictor → θ_EAV 在每個市場內近乎常數 → cross-market 差異是市場層級結構差異（不是個股層級噪音）。"*

**Scaffold 完全沒提這條 null evidence chain**：

- README Supporting Experiments 表只列 K1145/K1148/K1148_d1/d2/d3/K1149/K1302 — **K1109/K1113/K1114/K1140 缺**
- Abstract 完全不提 null heterogeneity 結論
- §7 Robustness Battery 只列 "drop-5-stocks stability, 3-EAV-def monotonicity, binary-vs-continuous"，沒列 cross-sectional null
- README §0 Decision Record 只引 "K1149 Scenario A"，沒引 K1146

這直接違反 **CLAUDE.md 研究誠實原則第 6 條**「Null result 如實報告、不過度宣稱」。Null heterogeneity 是 paper 的 **contribution** 不是負擔 — 它是 "universal magnitude" claim 之所以站得住的支撐邏輯（沒法找 firm-attribute predictor → θ 是市場常數）。略掉 = paper 邏輯斷一條腿。

**Weakness D1 — Null heterogeneity 證據鏈完全消失於 scaffold**：必須在 README narrative + Supporting Experiments 表 + Abstract（至少一句）+ paper §6.6 / new "Reconciliation" subsection 補齊。

### 4.2 K1148_d3 firm-characteristic heterogeneity REJECTED 的 framing

K1148_d3 結果：n_pass=9, n_fail=20, **significant_numeric_features=[], significant_sectors=[]** — 16 feature tests + 6 sector tests **全 null**。

Scaffold §0 Core Claim 第 4 條寫「Not firm-size driven — firm-characteristic heterogeneity rejected (K1148_d3)」— 措辭 OK，但**未說明** PASS/FAIL 切分本身依賴 K1148_d1 的 stock-level OOS DM verdict，而 K1148_d1 主結果是 TW OOS noise（DM t = −1.46，p = 0.076 NS） — pass/fail 切分基礎本身 marginal。**這是 sample-splitting on noisy outcome 的 selection bias 風險**。Scaffold 不能用 K1148_d3 「拒絕 heterogeneity」當乾淨 negative result。

**Weakness D2 — K1148_d3 selection bias 未揭露**：pass/fail split 來自 TW OOS DM (本身 NS marginal)，selected sub-samples 上跑 ANOVA / t-test 有 inflated Type I 風險。應該寫 "we exploratorily split TW stocks by..."，並引 K1109/K1113 較乾淨的 ex-ante firm-attribute null 為主要 evidence。

### 4.3 K1149 Scenario A over-state 風險

K1149 結果重看：

- `h1_absorption`：US IS t=23.81 ✅、US OOS DM=−3.31 ✅、TW IS t=10.62 ✅、TW OOS DM=−2.48 ⚠️（threshold = −2.0，僅勉強過）
- `h3_interaction`：US t_stress=+5.04 PASS、**TW t_stress=−0.39 FAIL，但 LRT p=0.010 → "pass": false**
- `scenario: "A+D"`（不是純 "A"），`paper2_implication` 明寫「conditional firm-event effect amplified by systematic stress」

Scaffold §6 寫「Factor Robustness — PCA absorption test, Scenario A narrative (K1149)」— **過度簡化**。K1149 真正 verdict 是 A+D（absorption pass + interaction asymmetric across markets），需要 paper 寫成「symmetric absorption finding + asymmetric stress-interaction finding」，不是平板的 "Scenario A"。

**Weakness D3 — K1149 verdict 簡化為「Scenario A」遺漏 D 維度 + TW interaction asymmetry**：paper §6 須完整呈現 A+D，否則被審稿人對照原 JSON 一眼抓出 cherry-pick。

### 4.4 「Best captured by a binary indicator」claim 的 scope

Scaffold Core Claim 第 3 條 + Abstract 結語都寫「best captured by binary, continuous adds no value」。

實際 K1148_d2 `four_row_table`：

- US binary OOS DM t = −5.58
- US continuous OOS DM t = −5.25
- 差 0.33，**both highly significant**

Scaffold 寫成 "binary marginally stronger" 是準確的（差距小），但 abstract「continuous |surprise| adds **no** predictive value OOS」是錯的 — continuous DM t = −5.25 也是 highly significant，binary 只是**邊際略強**。「no predictive value」是對 K1148 TW OOS NS 的描述但被誤推廣到 US OOS。

**Weakness D4 — Binary vs continuous「no value」用詞過強**：改為「binary specification slightly preferred on both markets (US: ΔDM t = 0.33; TW: both NS)」更誠實。

---

## 5. 建議改寫項目（specific actionable）

| Priority | Item | Target file / section | Rewrite |
|---|---|---|---|
| **P0** | 補 JP 市場（K1147 US IS + K1150 JP IS） | README title / §0 / §3 Data / §5 / Supporting Experiments 表 | Title 改 "Taiwan, U.S., and Japan Equity Markets"；Data 加 JP N=30 source；§5 改為「Three-market pooled IS validation (K1145+K1147+K1150)」；Supporting 表加 K1146/K1147/K1150 |
| **P0** | 移除 / 重定位「universal firm-event constant」措辭 | Abstract 結語 + README Core Claim §0 | 改為 "robust cross-market positive amplification with market-specific magnitude ordering (US > JP > TW)" |
| **P0** | 補 null heterogeneity 證據鏈到 narrative | README Supporting Experiments + Abstract + 加 §6.6 Reconciliation 計畫 | List K1109/K1113/K1114/K1140 + 加一句 abstract："Within-market firm-attribute heterogeneity is null (K1109/K1113/K1140), supporting the universal-magnitude interpretation." |
| **P0** | 拆 IS Hessian t 與 OOS DM t 不同語意 | Abstract 句構 | 重寫成兩個獨立句子，不用 "confirms the magnitude" 銜接（DM 不驗 magnitude） |
| **P1** | 修正 placebo 13.6σ → 13.27σ + 定義 σ | Abstract + 後續 paper Table | 用實算 13.27 並標明 σ = placebo permutation SE (n=60 within-stock shuffles); 改用 placebo_one_sided_p = 0/60 一起呈現 |
| **P1** | K1148_d2 從 cross-market magnitude 證據改為「spec consistency / OOS forecast superiority」證據 | §5 標題 + 內文 | §5 拆兩段：(a) K1147 US IS pooled magnitude；(b) K1148_d2 TW-fitted → US OOS DM 作 spec robustness |
| **P1** | 補 Patell 1976 / Diebold 2015 / Harvey-Liu-Zhu 2016 三大缺漏 | lit_review.md | Patell 1976 = canonical EAV anchor；Diebold 2015 = DM test methodology；HLZ 2016 = multiple testing |
| **P1** | K1149 Scenario 改 A+D 完整呈現 + TW interaction asymmetry 揭露 | §6 narrative + Core Claim §2 | "Scenario A+D: factor absorption symmetric, stress interaction asymmetric (US amplified, TW null)" |
| **P2** | K1148_d3 selection-bias 風險揭露 | Core Claim §4 | 改用 "Ex-ante firm-attribute heterogeneity null (K1109/K1113); exploratory ex-post split (K1148_d3) corroborates with caveats" |
| **P2** | Binary vs continuous「no value」改為「binary slightly preferred」 | Abstract + Core Claim §3 | "Binary specification yields marginally better OOS forecasts in both markets (ΔDM t ≈ 0.3)" |
| **P2** | 揭露 converged=false flags | README §2 Model + 之後 reproduce.py | 加一段 "Convergence: outer-loop tolerance 1e-7 achieved; scipy.minimize converged flag = False in pooled fits (BFGS gradient tol too strict for low-magnitude θ_EAV scale); manual verification via loglik plateau and outer-iter monotonicity." |
| **P2** | citation-verifier 跑 Engle-Ghysels-Sohn 2013 期刊名 | lit_review.md | 確認 JBES vs ReStat（懷疑 ReStat） |
| **P3** | README §0 加 paper scope 分隔聲明 | README §0 | "Independent of paper/taiwan-vt/ (VT strategy) and paper/leverage-direction/ (γ direction)" |
| **P3** | K1141 paper 歸屬澄清 | README pending / Supporting 表 | K1141 README 寫 Paper 4，但 scaffold 引用為 Paper 2 — 確認真正歸屬 |
| **P3** | reproduce.py / data snapshot pinning 計畫 | README §Replication | 列 yfinance snapshot date + CSV cache 路徑（paper-workflow.md 硬規則 1） |

---

## 6. Verdict & Next Step

**Verdict**: **NEEDS_REWRITE**

**理由**：
- 5 個 P0 weakness（缺 JP / over-claim universal / 缺 null evidence chain / DM-IS 語意混用 / placebo 數字失真）每一個都會被 JBF/JEF reviewer 5 分鐘內抓出
- Scaffold 與 `research_program.md` K1146 DECISION_MADE 結論不同步，body.tex 若按現 scaffold 展開會與 narrative state machine 衝突（CLAUDE.md 論文 state machine 規則：≥3 互補實驗 OOS-verified 才進 narrative decision，目前已是 3 市場但 scaffold 仍寫 2 市場）
- **NOT SCOPE_REJECT**：核心研究問題（EAV variance amplification 在多市場是否 robust）是 valid contribution，K1145/K1147/K1150/K1149 證據基礎扎實，只是 framing / scope / 證據選用需要 rewrite 而不是 paper 砍掉

**Next step（建議主線程依此 review 決策）**：

1. 主線程 sync scaffold 與 `research_program.md` K1146 結論（補 JP / 補 K1146/K1147/K1150 / 重寫 Core Claim 與 Abstract）
2. 跑 `citation-verifier` 對 lit_review.md 全 8 條既列 + 6 條建議補充 reference 做 APA + DOI 驗證
3. 完成 P0 + P1 rewrite 後**才**啟動 body.tex（避免 body 鎖死錯誤 framing）
4. body.tex 啟動前 reproduce.py 必須先寫（paper-workflow.md 硬規則 2：reproduce gate 是 review 先決條件）
5. K1141 paper 歸屬澄清 + K1302 γ provenance pending 排程

**禁止**：在現 scaffold 上直接開 body.tex agent（會繼承 5 個 P0 framing 錯誤）。

---

**Reviewer note**：本 review 嚴格遵守 `finance-paper-quality` SKILL 的 claim-evidence matching 原則 + `academic-finance-reviewer` SKILL 的 threshold justification / contribution count 原則 + CLAUDE.md 研究誠實 6 條。所有 K-experiment 數字皆從原 `*_results.json` byte-traceable 重算驗證，未引用任何記憶 / 二手描述。
