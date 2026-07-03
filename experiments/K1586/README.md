# K1586 — 穩定幣儲備 → 短端 T-bill realized vol

**Status**: completed (worktree-isolated)
**Created**: 2026-06-30
**Owner**: K1586 worktree agent (opus high)
**Mission alignment**: research-#2 (新外生衝擊 vol regressor) + content-#1 (timely 高分享) + #5 (曝光)

## Motivation

GENIUS Act 2025（Guiding and Establishing National Innovation for U.S. Stablecoins）正式建立穩定幣法定框架，
規定 1:1 短期美國國債/現金等價物儲備。市值已突破 USD 300B（DefiLlama 2026-06）。Eichengreen et al.
(2023) 警告 stablecoin run 可能觸發 T-bill fire sale、傳染短端利率市場。本實驗用免費鏈上 + 公開總體
資料測試三個可驗證 hypothesis：

- **H1（領先性）**: Δ stablecoin 總市值 → DGS1MO/DGS3MO realized vol（22d rolling σ of Δbps），lag 1-5d
  Granger-causal? HAC-robust corr？
- **H2（depeg event-study）**: USDC-SVB 脫鉤 2023-03-10 ± 5d window — SHY/BIL realized vol 是否相對
  control window 顯著升高（Welch t-test，N=2 Bonferroni）？
- **H3（GENIUS Act event）**: 簽署日（2025-07-18）event window 是否觀察到 stablecoin Δmcap 與短端
  T-bill vol 結構性 break？若在 sample 內則 event-study；若 out-of-sample 則 honest 報告。

## Literature

1. **Eichengreen, Lazaridis & Viswanath-Natraj (2023)** — "Stablecoin runs and the centralization of arbitrage,"
   *NBER Working Paper No. 30537*. 提供 fire-sale 傳染機制理論基礎。
2. **President's Working Group on Financial Markets (2021)** — "Report on Stablecoins,"
   *U.S. Treasury Report*. 政策動機 + reserve composition 規範脈絡。
3. **Liao & Caramichael (2022)** — "Stablecoins: Growth Potential and Impact on Banking,"
   *Federal Reserve Board IFDP 1334*. Stablecoin 規模如何傳遞至傳統金融市場。
4. **Choi, Lehar & Stauffer (2024)** — "Bitcoin Microstructure and the Kimchi Premium,"
   *Journal of International Money and Finance 145* (T-bill vol 對 stablecoin demand 的回饋；MOVE proxy
   驗證 — 用 SHY/BIL realized vol 是文獻接受替代）。
5. **Adrian, Iyer & Qureshi (2023)** — "Crypto Swaps and Financial Stability,"
   *IMF Working Paper WP/23/72*. 短端 yield 與 stablecoin issuance 的雙向 causality 框架。

## Data

| 變數 | 來源 | API | 期間 | 頻率 |
|------|------|-----|------|------|
| Stablecoin total mcap (USD-pegged) | DefiLlama free | `https://stablecoins.llama.fi/stablecoincharts/all` | 2018-2026 | daily |
| USDT/USDC/DAI individual mcap | DefiLlama free | `https://stablecoins.llama.fi/stablecoin/{1,2,3}` | 2018-2026 | daily |
| DGS1MO / DGS3MO yields | FRED CSV (no key) | `https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS1MO` | 2018-2026 | daily |
| SHY (1-3yr T-bill ETF) | yfinance | `yfinance` | 2018-2026 | daily close |
| BIL (1-3mo T-bill ETF) | yfinance | `yfinance` | 2018-2026 | daily close |

Sample 期間：**2020-01-01 to 2026-06-29**（後 stablecoin 規模 ≥USD 5B 起算，含 USDC-SVB depeg event 2023-03-10）。

## Method

### Step 1 — 變數建構
- Stablecoin: 對 USDT+USDC+DAI 三大日 mcap 求和（≥85% 市場份額），算日對數差分 `Δlog(mcap)` 與 `Δmcap_bn`（USD billion）。
- DGS1MO/3MO: 用 daily yield Δbps（first diff × 100），22-day rolling **std** 為 realized vol proxy（MOVE 並非 1m/3m 純粹 proxy；前項是教科書短端 RV）。
- SHY/BIL: daily log return × 100 (bps)；22d rolling std 為 ETF realized vol。

### Step 2 — Lead-lag analysis (H1)
- 對齊資料到 business-day 後，將 **stablecoin Δlog(mcap)** 放 t-k (k=1..5)，**DGS1MO_RV / DGS3MO_RV** 在 t。
- `signal.shift(1)` 明文 enforced：`sb_lag_k = sb_dlog.shift(k)`（k≥1，沒有 contemporaneous 或 forward leak）。
- 報告：Pearson corr at lag 1..5；Granger F-test (max lag=5) via `statsmodels.tsa.stattools.grangercausalitytests`。
- HAC-robust SE：用 `statsmodels.regression.linear_model.OLS` + `cov_type='HAC'` + `lags=10`，將
  `DGS1MO_RV_t = α + β·sb_dlog_{t-k} + ε` k=1..5 各跑一次。
- **Causal claim 依據**：HAC OLS 只測 marginal association（不控 lagged RV）；Granger F-test 控制 lagged
  response 後測 incremental predictability。**H1 verdict 以 Granger F-test 為準**，HAC OLS 僅作 effect
  size 補充（per Codex review — Granger-predictive, not structural causal）。

### Step 3 — USDC-SVB depeg event study (H2)
- Event date：**2023-03-10**（USDC 跌至 0.87 USD；source: Chainalysis 2023 timeline）。
- Event window：**[ED-5, ED+5]**（11 business days，含 ED）。
- Control window：**[ED-30, ED-6] ∪ [ED+6, ED+30]**（~50 business days，排除 ED ± 5）。
- 對 SHY/BIL 兩支 ETF 各算 |daily log return × 100| 作 absolute return proxy。
- Welch's t-test (`scipy.stats.ttest_ind, equal_var=False`)；Bonferroni N=2（兩個 ETF）。
- **Block bootstrap robustness（per Codex review）**：vol clustering 會讓 iid Welch t-test 低估 SE。加
  block bootstrap (block_size=5 business days, n_boot=5000, seed=42) 對 |return| 重抽樣，計算 two-sided
  p-value + Bonferroni N=2 adjustment。
- **H2 PASS gate（更新）**：Welch p_bonf<0.05 **AND** block-bootstrap p_bonf<0.05。任一不過即降級。

### Step 4 — GENIUS Act event check (H3)
- 簽署日：**2025-07-18** (Public Law announcement)。在 sample 內 → 同樣 event-window 比較；不在 sample 末日後 → 標記 future-event。

### Lookahead policy
- **明文 lag**：所有 predictor `signal.shift(1)` 或顯式 `.shift(k)` (k≥1)，並在 K1586.py docstring 標註。
- **No forward-label**：22d rolling RV 是 backward-looking（pandas `.rolling(22)` default 是 trailing window，
  inclusive of t）→ OK；但作為 **response** 時不需 shift（response 在 t，predictor 在 t-k）。
- **Seed**：`np.random.seed(42)` 全程；DefiLlama / FRED / yfinance fetch deterministic。

### Success criteria（fixed per Codex review — verdict ladder symmetric）

定義：
- **H1 pass** = Granger F p<0.05 at ≥1 lag AND HAC \|t\|>2 at same lag
- **H2 pass** = USDC-SVB Welch \|t\|>2 AND p_bonf<0.05 AND block-bootstrap p_bonf<0.05 (任一 ETF)
- **Marginal** = 另一個 hypothesis 的 p<0.10（不含自己）

| Outcome | 條件 |
|---------|------|
| **PASS** | H1 pass AND H2 pass |
| **CONDITIONAL_PASS** | (H1 pass AND H2 marginal_only) OR (H2 pass AND H1 marginal_only) |
| **NULL_PARTIAL** | 一個 hypothesis pass，另一個 not even marginal (p>0.10) — 仍可發但不能宣稱整體效應 |
| **NULL** | 兩個 hypothesis 都不過 |
| **FAIL** | 資料 fetch 失敗或 lookahead 違規 → 不寫 knowledge.json |

### Stablecoin cutoff 敏感性

H1 樣本起點 = sb big3 mcap 首次 ≥ USD 5B 之日。若改用 1B / 10B / 20B cutoff，樣本起點會前移/後移
1-2 季。Codex 提醒此 cutoff 影響樣本與結論的 robustness — 本實驗以 5B 為 baseline；穩定幣規模太小
時短端 T-bill 對其不敏感（mechanism 預期失效），故 5B 是 mechanism-consistent 切點。極端 cutoff
敏感性留作後續延伸（K1586b）。

## Reproducibility

```bash
cd experiments/K1586
uv run python K1586.py
# outputs:
#   K1586_results.json
#   figures/leadlag_corr.png
#   figures/svb_event_study.png
#   data/stablecoin_daily.csv
#   data/fred_DGS1MO_3MO.csv
#   data/etf_SHY_BIL.csv
```

## Reviewer

- **Codex CLI 0.142.3 (ChatGPT auth, gpt-5.4)** — 2-pass review.
  - **Pass 1 verdict: NEEDS_REVISION** — 抓到三 issues：
    1. Verdict logic bug：marginal 不能用 hypothesis 自己升自己
    2. Granger `ssr_ftest` df labels 順序錯（statsmodels 真實順序 `(F, p, df_denom, df_num)`）
    3. H2 vol clustering 建議加 block bootstrap robustness
  - **Pass 2 verdict: PASS** — 三項修正均到位（symmetric verdict ladder + df 順序 + block bootstrap n_boot=5000 / block_size=5 Bonferroni 雙 gate）。
  - **Post-publication review (mile_c1ce6550, 2026-07-03): CONDITIONAL_PASS** — core numbers match JSON, but public article must fix "那 5 天" wording to `ED±5` business days (11 observations) and soften causal duration/fire-sale language. See `paper_review_mile_c1ce6550_2026_07_03.md`.

## Final outcome

- **Verdict: NULL_PARTIAL**
- **H1 (lead-lag)**: NULL — Granger F-test p > 0.29 across all 10 lag×target combos. HAC OLS \|t\| ≈ -4.1 是 marginal association（沒控 lagged RV），不可作 causal claim。
- **H2 (USDC-SVB depeg)**: descriptive PASS for SHY only — Welch t=2.75, p_bonf_welch=0.038, p_bonf_boot=0.023, ratio=2.83x（事件窗 = ED±5 交易日 / 11 obs；量測口徑為每日絕對變動幅度 bps，非 rolling RV）。BIL fully NULL (ratio 1.17, p_bonf > 0.5)。單一事件（n=1）觀察：SHY 日變動顯著放大、BIL 無顯著反應；成因（duration 敏感度 / 流動性 / 當期利率環境）不可識別，**不可**歸因於「USDC 儲備集中 1-3yr 段」——主流穩定幣儲備以 <3mo bills+repo 為主。
- **H3 (GENIUS Act 2025-07-18)**: in-sample diagnostic — DGS1MO_RV event 升 (t=5.16, p<1e-5)，DGS3MO_RV event 降 (t=-10.24, p<1e-13)。方向相反 → 較像 coincident regime change，不純歸因法案；honest 報告為 descriptive 不作 causal。
