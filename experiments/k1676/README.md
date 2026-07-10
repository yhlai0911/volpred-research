# K1676 — 美元／實質利率狀態會改變黃金的避風港效果嗎？

Task：`research_safe_haven_regime`

Verdict：`NULL_NO_ROBUST_LAGGED_MACRO_STATE_MODIFIER`

## 研究問題與差異化

K1628 已證明：GLD 平均上和 SPY 低相關，但在股市大跌日不是穩定的強避風港。K1676 不重做那張危機日統計表，而是問一個更窄的增量問題：

> 在第 t−1 日已知的強美元／高實質利率狀態下，第 t 日 SPY 下跌時，GLD 的平均保護力或 SPY–GLD tail beta 是否系統性改變？

本實驗只估計同日避險共動，沒有交易策略、因果識別或報酬預測。

## 文獻先行

- Baur and Lucey (2010), *Financial Review*：以平均共動區分 hedge、以股市尾部共動定義 safe haven。
- Reboredo (2013), *Journal of Banking & Finance*：金價與美元的平均／尾部依賴不能只用單一平均相關概括。
- Baur and McDermott (2016), *Journal of Behavioral and Experimental Finance*：美元本身的避風港需求可能遮蔽黃金效果，且危機間並不固定。
- Batten et al. (2026), SSRN working paper：以美元與實質利率狀態研究黃金和美債的競爭性安全資產角色；本實驗只把它當設計動機，不把 working-paper 結論視為定論。

完整 URL 與各文獻如何進入設計，存於 `k1676_results.json` 的 `methodology.literature`。

## Data & Methodology

### 資料

| 變數 | 來源 | 原始範圍 | 代理限制 |
|---|---|---|---|
| SPY / GLD | `data/cache/price_cache.db`，本地 yfinance adjusted-price cache | 2016-01-04 至 2026-07-09，各 2,643 筆 | GLD 是 ETF，不是現貨金或 COMEX |
| UUP | `experiments/k1359/data/UUP.csv`，yfinance adjusted close | 2007-03-01 至 2026-06-18，4,857 筆 | 美元期貨 ETF，不是 DXY／即期美元 |
| DFII10 | `experiments/K1609/data/fred_dfii10.csv`，FRED 10Y TIPS real yield | 2003-01-02 至 2026-07-01，5,878 筆 | current-vintage，不是 ALFRED vintage |

共同分析樣本為 **2016-07-06 至 2026-06-18、2,503 個交易日**。各資產先在自己的 native date index 計算報酬，再 inner join；merge 後還要求三個報酬的起始日期完全相同，因此額外剔除 1 個 horizon 不一致日期。

### Information set

- UUP 狀態：log UUP level 的 252 日 rolling z-score（min 126），再明確 `shift(1)`。
- DFII10：先以 backward `merge_asof` 只取 observation date 不晚於市場日的數值，再額外 lag 一個市場日；實際 observation gap 為 1–4 日。
- 高／強狀態：z ≥ +0.5；低／弱狀態：z ≤ −0.5。bucket 只用於表格／稀疏 gate，正式檢定使用 continuous lagged z-score。
- Primary risk-off：SPY log return ≤ log(0.99)，共 **272 日**；固定 −2% robustness 共 **88 日**。
- SPY tail 與 GLD 同日報酬是 safe-haven estimand，不是 signal；程式不產生策略績效。

### 正式檢定

1. 平均保護力 joint model：`r_GLD ~ tail × {z_USD, z_real_yield}`。
2. Tail-beta joint model：`r_GLD ~ r_SPY × tail × {z_USD, z_real_yield}`，含全部 lower-order terms。
3. 四個 partial interactions 同屬一個 Holm family；另須同時通過 expected direction、Harvey `|t| ≥ 3`、5,000 次 circular block bootstrap（block=21、seed=42）與 leave-one-year-out 不翻號。
4. Extreme-state tail cell 必須 n≥50 且跨至少 5 年；−2% 係數若反號或 cell 稀疏，禁止升為 PASS。
5. HAC/Newey-West lag=21；rolling correlation、bucket、subperiod 都只能當 diagnostic。

## 結果

### 四個預註冊 interaction 全部明確未過

| Primary partial interaction | coef | HAC t | Holm p | block-bootstrap 95% CI | Gate |
|---|---:|---:|---:|---:|---|
| USD × tail mean | +0.0241% | +0.34 | 0.750 | [−0.1323%, +0.1532%] | FAIL |
| USD × tail beta | −0.0787 | −1.49 | 0.541 | [−0.2046, +0.0735] | FAIL |
| Real yield × tail mean | −0.0581% | −1.15 | 0.750 | [−0.1603%, +0.0481%] | FAIL |
| Real yield × tail beta | −0.0378 | −0.97 | 0.750 | [−0.1384, +0.0710] | FAIL |

所有 CI 都跨 0，沒有任何 `|t|` 接近 3。美元與實質利率 z-score 的相關只有 **0.217**、VIF 都約 **1.05**，所以 NULL 不是兩個 regime 高度共線造成。

### Bucket 點估計有方向，但不能升格

| SPY ≤ −1% 日的 lagged state | n | GLD 平均報酬 | GLD 收紅率 | SPY–GLD corr |
|---|---:|---:|---:|---:|
| USD strong | 175 | −0.043% | 46.9% | +0.028 |
| USD weak | 47 | −0.072% | 42.6% | +0.108 |
| Real yield high | 148 | −0.098% | 42.6% | +0.055 |
| Real yield low | 83 | −0.013% | 54.2% | +0.288 |

高實質利率 bucket 看起來較差：平均報酬差 −0.085 個百分點、收紅率差 −11.6 個百分點。但 21-day block bootstrap 的 95% CI 分別為 **[−0.465%, +0.301%]** 與 **[−27.5pp, +4.9pp]**，都跨 0。這只能說方向值得日後擴樣本，不能說已發現高實質利率會破壞黃金避險。

USD weak primary cell 只有 47 日，未達預設 n≥50；−2% 下更有三個 cell 未達 50。即使正式係數顯著，樣本 gate 也會阻止 PASS。實際上四個 primary 本來就全部不顯著。

### 相關結構仍有穩定背景，但不是 tail moderator 證據

- Lagged 63 日 GLD–UUP correlation 全樣本均值 **−0.487**，96.2% 的日子為負。
- Lagged 63 日 GLD–real-yield-change correlation 均值 **−0.414**，95.3% 的日子為負。
- GLD–SPY correlation 均值只有 **+0.035**；但在之後成為 SPY ≤−1% tail day 的日期，前一期 rolling correlation 均值反而是 **+0.102**。

這些是背景共動描述。它們沒有讓 lagged USD／real-yield interaction 通過正式 gate，也不能改寫成「脫鉤」或可交易訊號。

## 結論

在 2016–2026 的美國 ETF 樣本中，**沒有足夠證據顯示前一期美元或實質利率狀態，能穩健改變黃金在股市尾部的平均保護力或 tail beta**。

這個 NULL 延伸但不推翻 K1628：黃金仍是低相關分散資產，其危機保護力依 episode 變動；只是把這種變動簡化成「強美元／高實質利率 regime」後，沒有得到可重複的正式 moderator 證據。

## Review 與可重現性

- `codex_review_pre_run.md` 記錄初次自審被獨立 reviewer 推翻、三個 major 修正，以及 binding rerun 前的 PASS gate。
- Binding run 後再完整重跑一次；排除 `generated_at_utc` 的 canonical JSON SHA-256 兩次皆為：`85d69f125ca6844a83eb15da0e968eb75ba4ff98eaabdd1110520b372cb99165`。
- 兩張 PNG 已以 Pillow decode/尺寸驗證。

復現：

```bash
uv run python experiments/k1676/k1676.py
```

## 檔案

- `k1676.py`：完整可重現腳本。
- `k1676_results.json`：正式結果與 metadata。
- `data/analysis_panel.csv`：lag / alignment 後分析 panel。
- `figures/fig1_lagged_correlations.png`：三條前一期 rolling correlation。
- `figures/fig2_tail_hedge_by_regime.png`：tail-day bucket 點估計。
- `codex_review_pre_run.md`、`codex_review.md`：執行前與結果後審查紀錄。

## 限制

1. 共同樣本不含 2008；subperiod／危機樣本仍少。
2. DFII10 是 current-vintage 檔；保守 lag 不能取代 ALFRED vintage audit。
3. GLD／UUP 有 ETF 費用、roll/carry 與 tracking error。
4. Regime threshold 是預設模型選擇，沒有掃參數，但仍不是唯一合理定義。
5. 同日共動不等於預測、因果或投資建議。
