# leverage-direction 期刊投稿評估 memo (2026-07-01)

**Paper**: Leverage Direction Matters — Cross-Asset Evidence on GARCH Model Selection and Volatility Targeting
**Author**: Yi-Hao Lai (single author, 大葉大學財金系)
**Length**: 43 pages (main) + supplementary
**Contribution 目前定位**: "economic classification device" — GJR-γ 作為 volatility model selection heuristic，**非** forecasting winner
**Stage 2.2 (K1592) verdict**: NULL_OR_WEAK — 0 strict Harvey+Holm wins，GammaRule 只 3/8 assets best
**Replication package**: self-contained, reproduce.py GREEN (171 MATCH / 23 NOTE / 0 MISMATCH)
**Compliance**: 唯一剩 body.tex:231 一個 VolPred footnote 待清

## 觸發背景

原目標 JBF；但 Stage 2.2 完成後，論文 forecasting pitch 弱化。老闆 2026-07-01 明確指示：搜尋資料分析適合的期刊 + acceptance 勝率，建 review skill 中的 reference 檔（目標 SSCI/SCI Tier 1-2）。此 memo 對 10 個既有 profile + 8 個新建 profile 共 **18 個期刊**逐一評估 fit + acceptance probability，並給 Top-3 建議。

## Fit 評分定義

- **Strong** — 論文核心貢獻與期刊 scope 對齊，framing 略調整即可送
- **Moderate** — Scope 邊界內，需重寫 intro/contribution positioning 才可送
- **Weak** — Scope 邊界或近 boundary，desk-reject 風險高

## Acceptance probability 定義（**含當前論文 fit 因子**，非期刊 baseline）

- **High** (>20%) — 論文與期刊高度契合，只要嚴謹修訂即有勝算
- **Medium** (10-20%) — 適合但 Stage 2.2 null 顯著削弱勝率，需 reframing
- **Low** (5-10%) — 適合但當前狀態難過同儕審查
- **VeryLow** (<5%) — scope 或 rigour 門檻過高，或 stage 2.2 null 直接不符期刊 bar

---

## 18 期刊逐一評估

### Top-3 field (Trinity/類 top) — 均不適合當前 state

| 期刊 | Fit | Accept prob | Rationale |
|---|---|---|---|
| **JFE** (IF ~5.9) | Weak | VeryLow (<3%) | Top-3 economic mechanism gate；Stage 2.2 NULL 直接 desk-reject。$850 fee 損失風險高。 |
| **RFS** (IF ~7.9) | Weak | VeryLow (<3%) | 同 JFE：Trinity level "significant new financial economics" 過高；desk-reject median 33d。 |
| **JoE** (IF ~9.9) | Weak | VeryLow (<3%) | Pure methodology 導向；GJR-γ classification 非新估計量/檢定，"applied-only" 直接拒。 |

### Top-field 一般/實證（可行 pool）

| 期刊 | Fit | Accept prob | Rationale |
|---|---|---|---|
| **JBF** (IF ~3.7, $350 fee) | Moderate | Medium (12-15%) | 原目標；policy/institutional angle 需強化。Reframing 為「跨資產 asymmetric vol → risk mgmt implication」可過。Stage 2.2 null 需在 intro 就誠實揭露為「classification device」framing。 |
| **JEmpFin** (IF 2.52) | Strong | Medium (12-18%) | 極 fit — 專為 rigorous empirical finance；Stage 2.2 null 誠實揭露 + classification framing 剛好符合「no data-snooping」宣示。No fee；85% desk-reject 主要打 scope 混淆者。 |
| **JFinEc** (IF 2.42, $65 fee) | Strong | Medium (15-20%) | 高 fit — 專為 financial econometrics；GJR-γ 作為 model selection heuristic 完全符合「method + finance」pairing。**Replicability review 是 acceptance 條件 → 我方 reproduce green 是強優勢**。 |
| **JAE** (IF 3.45) | Moderate | Medium (10-15%) | Fit 好但需強化「應用型 econometric 觀察」framing；JAE Data Archive mandatory → 我方 self-contained package 是強優勢。Free-format submission 降低前期成本。 |
| **JBES** (IF 3.20) | Weak | Low (5-8%) | Methodology contribution 是硬 gate；本文無新估計量/檢定，屬 "application-first"，會被 desk-reject 或轉 JAE。 |
| **QF** (IF 1.71) | Moderate | Medium (12-18%) | Quant-methods lens；GJR-γ classification 可 frame 為 model selection algorithm。Single-blind + LaTeX 友善。No fee。 |
| **IJF** (IF ~5.4) | Weak | Low (5-8%) | Forecasting + OOS 為核心；Stage 2.2 NULL 直接違反 IJF 期待的「forecast improvement」。除非重寫為「when do complex models fail」meta-analysis。 |
| **JoF** (IF ~2.9) | Moderate | Low (8-12%) | Forecasting 範圍寬；Stage 2.2 null 仍是弱點但 JoF 對 methodology↔decision 交界較寬容。Free-format + fast (~20d) 是加分。 |

### Top-field regional / 特殊

| 期刊 | Fit | Accept prob | Rationale |
|---|---|---|---|
| **PBFJ** (IF ~4.2) | Weak | VeryLow (<5%) | Asia-Pacific ONLY (no US-only data)；本文核心 asset SPY/QQQ/GLD/TLT/BTC 全非 Asia-Pacific，desk-reject 必然。 |
| **FRL** (IF ~11) | Weak | VeryLow (<5%) | 2500-word cap，本文 43 pp 無法縮；且 FRL 排斥 single-country replications。$200 fee 損失。 |

### Practitioner

| 期刊 | Fit | Accept prob | Rationale |
|---|---|---|---|
| **JPM** (IF ~1.5) | Weak | Low (5-10%) | 需 practitioner framing HARD gate + 4000 word 目標；本文 43 pp 高度學術化，desk-reject 高。 |
| **FAJ** (IF ~4.5) | Weak | VeryLow (<5%) | Practitioner payoff net of costs 是硬 gate；本文 GJR-γ classification 缺乏直接 investment decision payoff。 |

### 第二 tier（可行 pool，勝率較高）

| 期刊 | Fit | Accept prob | Rationale |
|---|---|---|---|
| **EmpEcon** (IF 2.25) | Strong | High (20-25%) | 專為 applied empirical result；本文 asymmetric vol cross-asset classification 是清楚 empirical finding。Cross-country/panel welcome。No fee。**接受度最高的可行選項之一**。 |
| **EFM** (IF 4.42, $600 fee) | Moderate | Medium (12-18%) | 需 European/international angle 才收；本文有 EEM/BTC 但主要 SPY/QQQ，need reframe。Fast 4-week decision 是強優勢。$600 fee 需權衡。 |
| **SNDE** (IF 0.9) | Weak | Low (8-12%) | Nonlinear-dynamics thesis HARD gate；GJR-γ 沒有 regime-switching/threshold 結構，除非重寫為 "asymmetric leverage regime" framing 否則 scope 邊界。但 free S2O OA、niche audience。 |

---

## Top-3 建議投稿順序

### 1st choice: **JFinEc (Journal of Financial Econometrics)** — Strong fit + Medium accept

**Rationale (2 sentences)**: GJR-γ 作為 model selection heuristic 完全符合 JFinEc 「econometric methods for finance」的 pairing 標準，且 Stage 2.2 null 誠實揭露反而符合期刊 "no data-snooping" 期待；replicability review 是 acceptance 條件 → 我方 reproduce.py GREEN (171 MATCH) + self-contained package 是**罕見優勢**，多數投稿者敗在這關。IF 2.42 略低於 JBF 但為 SSCI Q1 Oxford 出版，學術聲譽足；submission fee **USD 65**（SoFiE 會員免費）；3-6 mo decision。**主要重寫工作**：intro reframe 為「financial econometric classification device」，收在 40-page soft cap 內；simulation section 加強（本文較弱）。

### 2nd choice: **JEmpFin (Journal of Empirical Finance)** — Strong fit + Medium accept

**Rationale**: 專為 rigorous empirical finance，本文核心「跨資產 asymmetric volatility + VT alpha」正中 scope；Stage 2.2 null + classification framing 適合 JEmpFin 對 empirical honesty 的重視。85% desk-reject 主要打 scope 混淆者，本文清楚屬 empirical finance；no fee。IF 2.52。**主要重寫工作**：strip 掉 JBF-flavor policy/institutional framing，加深 empirical robustness 章節；editable source (Elsevier)；AI declaration。

### 3rd choice: **EmpEcon (Empirical Economics)** — Strong fit + Highest accept prob (20-25%)

**Rationale**: 接受度最高的 realistic fallback — 專為 applied empirical result，本文 cross-asset asymmetric vol classification 完全是這類 finding；cross-country/panel welcome 且對 Stage 2.2 null 最寬容（不強求 "significant improvement" claim）；no fee；SSCI Q1（IF 2.25）。**Downside**: tier 稍低於 JBF/JFinEc/JEmpFin；但若 1st/2nd choice 被拒，這是 hit rate 最高的 safety net。**主要重寫工作**：reframe 為 economic finding（"我們 document 什麼 about 什麼 using 什麼"）而非 methodology contribution；single-anonymized (不 strip 名字)。

## 建議 pipeline strategy

**Serial submission**：JFinEc（12 週）→ 若拒 → JEmpFin（8 週）→ 若拒 → EmpEcon（12 週）→ 若拒 → JBF（原目標，回退）。**避免同時多投**（Elsevier + Wiley + Oxford + Springer 4 家 no fee 但學術道德不允許 parallel）。**避開**：JFE/RFS/JoE/PBFJ/FRL/FAJ（scope 或 tier mismatch）；JBES（methodology gate 過高）。

## 未 verify 的關鍵數據（老闆需知）

- **JAE acceptance rate**: 官方未公佈；estimate based on comparable Wiley Q1 econ journals (~10-15%)
- **JBES acceptance rate**: 官方未公佈；estimate ~8-12% based on ASA methodology-heavy bar
- **JFinEc acceptance rate**: 官方未公佈；estimate ~15-20% based on Oxford Q1 specialty
- **JFinEc first-decision time**: 3-6 mo 為社群經驗值，非官方公佈
- **QF acceptance rate**: 官方未公佈；estimate ~15-20%
- **EmpEcon acceptance rate**: 官方未公佈；estimate ~20-25% based on second-tier applied econ norm
- **EFM 4-week target**: 為 EFMA 官方 stated policy，實際 median 可能更長
- **SNDE acceptance rate**: 官方未公佈；estimate ~20-25% based on niche Q2 norm
- **JEmpFin 15%**: 為 Elsevier editor 公開 communications 的 "85% rejection" 反推
- 所有 5-yr IF 為 estimate（Clarivate JCR 5-year 數字需付費訂閱），未逐一 verify
- OA APC 數字為 2025 publisher 官網 snapshot，OA APCs 每年可能調整

## 附錄：本 memo 產出的 8 個新 profile

- `.claude/skills/journal-review/references/jae.md` (Journal of Applied Econometrics)
- `.claude/skills/journal-review/references/jbes.md` (Journal of Business & Economic Statistics)
- `.claude/skills/journal-review/references/jempfin.md` (Journal of Empirical Finance)
- `.claude/skills/journal-review/references/jfinec.md` (Journal of Financial Econometrics)
- `.claude/skills/journal-review/references/qf.md` (Quantitative Finance)
- `.claude/skills/journal-review/references/empecon.md` (Empirical Economics)
- `.claude/skills/journal-review/references/efm.md` (European Financial Management)
- `.claude/skills/journal-review/references/snde.md` (Studies in Nonlinear Dynamics & Econometrics)

`journal-index.md` 已同步從 10 rows 擴充到 18 rows + routing heuristics 加 8 條。
