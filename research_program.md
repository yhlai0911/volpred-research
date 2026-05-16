# Research Program: Autonomous Volatility Prediction

## 目標（持續推進，永不完成）
1. 持續找出選定資產的最佳 1-step ahead 波動率、VaR/ES、報酬率預測模型
2. 持續建立一般非專業投資人可運用的各種交易策略
3. 持續找出利用研究成果獲利的模式
4. 持續找出並優化本網站的風格、經營模式、發展方向，持續修正朝之前進

## 行為準則 → 已搬到 `.claude/skills/autonomous-research/references/methodology.md`

**2026-04-18 搬移**：統計有效性、模型比較公平性（Patton 2011）、經濟顯著性 VaR/ES 轉換、多頻率研究約束、跨資產假日、資料期間 COMMON_START、評估指標、研究多元化、研究主題來源（原 9 節技術細節）現在 skill reference，Claude 觸發 `experiments/` / `paper/` / `storage/` 對應 paths 時自動載入。

此處保留 stub 避免舊引用 404。`research_program.md` 回歸**方向／方法／標的／軌跡**文件（短期 active 詳細、中期概念、長期索引）。

## 研究面向（螺旋式推進，非線性完成）

研究不是線性階段，而是持續探索的多個面向。每個面向可以隨時回訪：
新數據、新方法、新 insight 都可能讓之前「收斂」的面向重新打開。

### 面向 A: 波動率預測模型（多頻率探索）
**不限日頻**——週、月、季、年頻率都要探索。低頻率的注意事項：
- 樣本數隨頻率下降（月頻 20 年 ≈ 240 obs，季頻 ≈ 80，年頻 ≈ 20）
- 年頻 GARCH 不可行（<30 obs），改用 EWMA、rolling std、或 regime model
- 低頻模型需更長資料期間（月頻建議 30+ 年，季頻 50+ 年 if possible）
- OOS 期間要延伸到最新數據——如果 cache/存檔不到最近日期，用 `force_refresh=True` 重抓
- 月頻策略的 Harvey threshold 更嚴（fewer observations → wider CI）

**單變量模型：**
- GARCH 家族（GARCH, GJR, EGARCH, TARCH, FIGARCH）
- 高頻模型（HAR-RV, Realized GARCH, Realized GJR）— 需 5-min 數據（SPY 46天/0050.TW 34天，~2026 Q2 解鎖）
- **★★★★ HAR Multi-Scale (K530)**：HAR-ABS 以 DM=-15.45 壓倒性勝過 GJR-GARCH，DM=-16.26 勝 EWMA——**1306 實驗中最強統計顯著性**。|r_t| proxy 比 r²_t 好 3x。HAR-VIX 最佳 (QLIKE=0.46)。β5(5日) 主導。0050.TW 同模式。等 5-min RV 後應更強。
  - **⚠️ K782 修正**：HAR 在 r² target 上**全輸** GJR（5d/22d/66d DM 全正）。HAR 優勢限於 |r| target。日頻 squared returns 做的 RV 不足以讓 HAR 發揮。**Proxy 比模型更重要**。
- **★★★ Rough Volatility (K529)**：H=0.1 確認 roughness。HAR-Rough 顯著勝 GJR (DM=-7.04) 但未勝 EWMA。Time-varying H 反而更差。
- **K526 GARCH-MIDAS**: OOS 未勝 GJR，但 regime 轉換期（COVID/升息）有局部優勢。long-run τ 僅解釋 11% variance。
- **MF2-GARCH**（Conrad & Engle 2025: 短期 GJR + 長期乘法誤差模型）— 測試中
- 分解式模型（EMD-GARCH: 經驗模態分解 + GARCH）
- ML/DL — Branco 2024 確認非線性 ML 整體不優於線性模型，降低優先級
- 組合預測（GJR+HAR, stacking, 反 QLIKE 加權）
- 跨資產模型選擇（gamma rule, significance-based）

**多變量模型：**
- DCC-GARCH（動態條件相關）— 已有初步結果
- BEKK-GARCH（多資產波動率溢出）
- Copula-GARCH（非線性相依結構）
- Factor GARCH（共同因子驅動的波動率）
- 跨資產 Granger 因果（vol spillover）

**Under-explored methodologies (novelty quota 候選，feed_ct=0 per topic_diversity_audit 2026-04-19 19:30 UTC)**:
- [x] ~~Bayesian Model Averaging (BMA) for vol forecasting~~ → **K1257 完成 2026-04-20**：6-model pool × 3 assets × OOS 2020-2026。**H1 PARTIAL**（SPY/GLD Harvey PASS t=-3.40/-3.38, 0050.TW FAIL posterior→GJR-t），**H2 FAIL** no asset 過 equal-weight Harvey（確認 K482 equal-weight-puzzle 延伸到 Bayesian），**H3 FAIL** posterior 500 天內 concentrate 指數收斂→ standard BMA cannot forget/track regime。下步：forgetting-factor BMA 或 sliding-window posterior。**等候 Codex 04-24 code review 才 finalize knowledge.json 寫入**（CLAUDE.md §實驗後必做 L1）。
- [x] ~~**Model Confidence Set (MCS) / SPA / Reality Check**~~ → **K1259 完成 2026-04-20，review-cycle 真正全結 2026-04-29**（Codex primary-path review v2 closure，1 day after 2026-04-28 subagent-fallback premature closure RETRACTED）：Phase 1 ledger **2718 DM rows** from 236 K / 16 assets（v1 −11 ttest/mcnemar + v2 −12 statistical_tests/stat_test/welch/vs_zero = 23 false-positives 全濾除；原 2741 → 2718 final）。NON_DM_PATH_TOKENS 9 tokens 包覆所有已知 non-DM patterns（Option A 擴展 blacklist；Option B positive DM gate `dm`/`harvey`/`hln` 拒絕 — 會誤刪 K1085/K1088 等 191 legit DM rows）。see `experiments/k1259/codex_review_v2.md` for full FAIL verdict +Phase 1.5 main-thread asset backfill 38%→78%（**已 scripted** as `apply_phase15_backfill.py` + `phase15_asset_map.json` 105 K_ids，two-step pipeline 完整可重現）；Phase 2 HLN-2011 Variant A (parametric bootstrap seed=42, B=1000) 18/20 runs (0050.TW MSE 空 — 全 K400-K1258 無 TW MSE DM rows = new gap)。**關鍵發現**：(a) **SPY QLIKE α=0.10 87/100 models survive**（post-audit；原 88，cosmetic "middle" 移除）— A4f family 全入 superior set (A4f-VIX9D-N/t, A4f_Local, A4f_N, A4f_VIX, A4f_t_2step, A4f_t_joint)，HAR/EWMA/GJR-t/MEM decisively eliminated；(b) **GLD MSE 窄 set {M2_GJR_t, M3_GAS_t, M4_HAR_RV_X}** — MSE 比 QLIKE discriminative 因 ledger 薄；(c) **α=0.10 vs 0.20 sets identical** everywhere（stopping-p ≥ 0.23）— marginal relaxation 無效；(d) **CF-Rolling 不在 ledger** — K500+ 敘事王者模型命名不一致錯過抽取（follow-up: 命名 canonicalization）；(e) Variant B (reconstructed per-day loss + stationary bootstrap) skipped — <20% per-day loss coverage。Commits: def4695b (Phase 1), efd370f4 (Phase 1.5), 5314dbd3 (Phase 2), 7c0013b6 (review entry), d4c2faf1 (MAJOR-3 docstring), 53c1d559 (MAJOR-1 backfill scripted), aff7b4a5 (MAJOR-2 generic-key filter), b1f85845 (knowledge refresh)。**Codex review fallback** (Codex CLI blocked → `feature-dev:code-reviewer` subagent per `.claude/rules/experiments.md`)：PASS-with-caveats (0 CRIT/0 SEV/3 MAJOR/2 MED/3 MINOR)；**v1 + v2 audit 全 5 finding closed**：MAJOR-1 v1 (Phase 1.5 backfill scripted + map) / MAJOR-1 v2 (NON_DM_PATH_TOKENS 9 tokens) / MAJOR-2 v1 + v2 (full-population audit) / MAJOR-3 (docstring) / MINOR (inline comment row count)。MED (phase15_asset_map K1128/K1130/K1131 TAIFEX TX with VIX as conditioning variable target-asset semantic ambiguity) 留 separate slot 處理 — orthogonal to extraction correctness。Knowledge entry `c4db347a` confidence **0.88 → 0.75 (retracted v1) → 0.90 (v2 closure verified)** finalized — Codex primary-path 二次驗證 + 18/20 MCS cells superior_sets 100% identical pre-v2 vs post-v2 (12 removed rows had 0 MCS signal due to MIN_PAIRS_PER_MODEL=2 filter)。Phase 3 (feed research-tier article) 仍獨立 queue（uncovered；未在 publication_candidates）。
- [x] ~~**Realized semivariance / signed jumps**~~ → **K1301 完成 2026-05-11 NULL on TAIFEX TX1 day session**：BNKS RS+/RS- 分解，HAR-RS vs HAR-RV n_test=649 DM-HLN t=1.29 (p=0.197) fail Harvey 3σ；MSE 方向 favors HAR-RS (1.4503 vs 1.4709) 但量級不足。Joins NULL quartet K868/K1301/K1303/K1309 (sign/jump/session/path 四類 HAR decomp all NULL on TX1)。Closure: provisional_pending_codex_reverify; synthesis article `mile_42e7131c` published (research-tier) 2026-05-12。

### 面向 B: VaR/ES 風險管理
- 分配選擇（Normal, Student-t, GED, Skewed-t, FHS）
- Adaptive sigma floor
- Multi-step VaR（proper GARCH h-step formula）
- VIX/GARCH ratio 作為 VaR reliability indicator
- **★★★ Cornish-Fisher Rolling VaR (K1034)**：CF-Rolling 6/6 Trinity PASS（Normal 0/6, Student-t 1/6）。用 rolling 偏態/峰態修正 quantile，無需假設特定分配。**目前最佳 VaR 方法**
- **★★ EVT-GPD VaR (K1035)**：GJR-EVT rescues GJR（0/4→4/4 Trinity PASS），但 A4f 本身已 4/4 不需 EVT。EVT 是 weak model 的補救工具，非 strong model 的加分項
- **VaR 方法排名（K1034+K1035 綜合）**：CF-Rolling ≥ EVT > Student-t >> Normal
- **★★ Multi-Horizon VaR (K1039)**：A4f+CF-Rolling h=1,5 均 100% Trinity PASS。h=10 降為 75%（小樣本）。**√h scaling = proper h-step**（pass rate 相同）→ 實務不需 h-step 公式。Normal 隨 horizon 增加改善（CLT）
- **Copula-based VaR**（多資產聯合尾部風險）
- Monte Carlo VaR（GARCH 路徑模擬）
- [x] **★★ A4f + CF-Rolling 結合 (K1036)**：2×3 factorial 完成。CF-Rolling 是 VaR 王者——GJR+CF = A4f+CF = 6/6 Trinity PASS。A4f 對 Student-t 有巨大改善（1/6→5/6），但 CF-Rolling 使模型選擇對 VaR 無關。A4f 的真正價值在 QLIKE 預測精度

### 面向 C: 投資策略
- Volatility Targeting（12/VIX, EWMA VT, Hybrid VT）
- Multi-asset portfolio（40/30/30, Conditional TLT）
- 報酬預測（Excess Fear Signal [Gemini], VRP timing）
- DCA + VT：**K59 DCA 用 24/VIX**，**K70 DCA 50/50 幾乎不需 VT（防禦階層）**
- Covered Call：**K72 XYLD + VT 不改善 50/50**
- **VaR-targeting**（K44: rescaled σ-targeting，非新 alpha 但提供直觀風險選擇框架）
- **VT alpha = trend following**（K46→K53→K79: r=0.564, N=22, threshold-robust）⚠️ **K1044 修正**：13 資產 panel ρ=-0.209 (NS)，gamma-VT alpha 相關不可重現。Gamma 決定 VT 機制但不決定效果
- **VT 雙重機制**（K49: Sharpe 來自 TSMOM, MDD 來自 VIX position sizing, 90-97% 跨 5 資產）
- **VVIX/SKEW/VIX3M overlay**（K43: 全部 NULL，方向關閉）
- **利率 regime**（K62: 高利率保險費僅 1.8%/yr vs 低利率 6.10%）
- **退休情境**（K85→K87: VT 不翻倍提領率，只提供更穩定的 4% 存活）
- **稅務**（K86: 保險費佔 71-80% 成本，稅佔 20-29%。台灣 0% 資本利得稅 = 結構優勢）
- **50/50 SPY/GLD 不可動搖**（K2/K16/K19/K24/K54/K63/K64/K89 — 8 次驗證 + K534 理論解釋：correlation dynamics 不可預測）
- **5% BTC 唯一統計顯著改善但尾部風險代價**（K66: p=0.014, 但 coskewness -0.50）
- **Sector VT uniform**（K58: gamma 不預測行業 VT 效果）
- **International VT universal**（K68: 13/13 市場 MDD 改善，US VIX 通用）
- **Rebalancing: 月度最佳**（K48/K65/K75: 週/季/年全 NS）
- **VT 季節性 NULL**（K80）、**槓桿 NULL**（K81）、**Stop-loss NULL**（K83）
- **TF / MA 5 strategies all fail Harvey**（K518: SMA200 / Faber10M / Golden Cross / Dual Momentum / MA+VT, 1999-2025 SPY 27yr; 5/5 fail Harvey t>3 multi-test bar; 4/5 sub-B&H absolute Sharpe; best Golden Cross Sharpe 0.51 vs B&H 0.41 NS; MA+VT collapse Sharpe -83% / MDD +74% ↑; refs Moskowitz 2012 JFE / Faber 2007. mile_67169c30）— "課本級別" trend-following folk rules 全通不過嚴格統計 bar
- **K1018 4-layer engineering ≈ baseline NS**（robust_vt vs 12/VIX baseline; metric helper 修 cumsum→cumprod 後：Sharpe 0.5937 vs 0.5364 vs 0.5966 (bh_5050) all DM-NS; MDD -31.26% vs -30.17% vs -32.49%; 4 layers 工程加值 ≈ 0. mile_a4311ba7）— **methodology lesson**: 簡化版 metric helper (cumsum + cum-peak) 對 arithmetic returns 系統性 understate MDD + understate CAGR；須改 (1+r).cumprod() NAV path + (cum-peak)/peak relative drawdown，否則 Calmar 報導 ~half 失真
- **K549 multi-asset 5-asset VT all weather**（A_50/50, B_TLT, D_4-asset, F_5-asset; bootstrap 95% CI 4 portfolios 完全重疊；Harvey-style |t|>3.0 跨 5 個年份視窗 (2010/2013/2016/2019/2022) 0/7 portfolios 通過；EFA 跨期間最一致，TLT 2022 災難性。mile_50030b56）— **lesson**: 多資產分散沒有「免費 Sharpe」；TLT 升息週期變毒藥；VIX_t 同期決權重 lookahead disclaimer 必加
- **Factor tilts NULL**（K89: MTUM/VLUE/QUAL/USMV 全不改善 50/50）
- 台灣市場：**K55/K82/K88 台灣 VT 指南 + TSMC 集中度測試**

### 面向 D: 理論貢獻
- Gamma-mechanism proposition（VT alpha 機制）— **K53: r=0.564 (N=22) 確認但衰減**
- Diversification amplification（index vs stock gamma）
- MDD vs Sharpe 區分（mechanical vs skill）— **K49: 雙通道分離**
- Anti-tautology 驗證
- **VIX sufficient statistic**（25+ 次確認：K43/K48/K57/K61/K65/K80/K84 + K730 cross-asset + K731 term structure + K732 behavioral sentiment + 歷史 15 次）— **K1315+K1316+K1098 boundary characterization**：此效應為 **market-specific**，不可跨市場推論。K1315（SPY, within-market）：HAR-VIX QLIKE 改善 +28.7%，DM=4.58 Harvey-significant PASS；K1316（TX1 台指期，cross-market VIX）：QLIKE 差異 DM=1.041 p=0.298 NULL；K1098（0050.TW + VIXTWN）：cross-market channel NULL。結論：VIX 做 SPY 波動率的 sufficient statistic 有強力支持，但 cross-market IV channel（用美股 VIX 預測台灣市場）在 DM-HLN 標準下不成立。
- **VT 保險費定價**（K41: ~4%/yr 恆定，K62: 利率依賴，K74: 80% 時間落後是正常的）
- **Copula tail dependence asymmetry — multi-pair Bonferroni-robust evidence**（K195: 66 配對股票/行業 ETF, OOS Bonferroni 26/66 通過, full-sample 28/66；Top-5 EEM-XLK t=-10.29 / QQQ-XLK / SPY-XLE / XLE-XLF / SPY-EEM；leverage effect 確認下尾依賴強於上尾。**Methodology caveat**: GARCH-X 用 TDA 當 exog regressor 預測 RV → DM t=-0.601 NS — "cross-section structural evidence ≠ forecast utility"；refs Patton 2006 / Joe 1997 / Embrechts copula textbook. mile_7de1c5a2）

### 面向 E: 即時市場分析
- Hormuz 危機追蹤
- 危機類型分類（financial/pandemic/monetary/oil）
- 即時 VaR/ES 預報
- Paper trading 績效追蹤
- **FOMC / 重大事件 ex-ante prior + ex-post 對帳**（2026-04-29 FOMC: HOLD 3.50-3.75% 兌現 12 天前 94.8% prior 中央 scenario; 但 8-4 dissent (1992-10 以來首次 4-dissent) 是 prior 沒涵蓋的 narrative shock，把 June implied prob 從 78% → 95.5% (+17.5pp); SPY 04/29 收盤 -0.04% 落在 hold-conditional 中位附近. mile_fef2e0b2 published）— **methodology lesson**: T+0 ex-post 對帳框架 (actual vs prior conditional distribution) 行得通；dissent structure / vote-split 是 ex-ante prior 應 cover 但常忽略的維度，未來事件 prior 模板需加 vote-split scenario branch
- **Event date 必驗證外部官方 calendar**（2026-05-02 NFP 假日期 incident: scheduler 把 first-Friday-of-month heuristic 算成 NFP 日期，實際 BLS 是 first Friday _after_ 12th of month. event_expander 必須抓 BLS / FOMC 官方 schedule URL 對齊，否則 silent date drift 會堆積到 publish 階段才被研究誠實 net 抓到. docs/error_log.md 2026-05-02 entry）

### 面向 F: 網站與系統
- 前端功能（12/VIX 計算器, Feed 品質, Paper 下載）
- 部署架構（v2 Supabase + Zeabur）
- 知識索引（LanceDB embedding）
- AI 協作模式（Claude + Codex + Gemini）
- 平台操作層（`/admin/*`、`/api/admin/*`、`uv run volpred ops ...`）
- 讀者分析回饋（analytics summary → 研究與發文方向）
- 會員問題排行與研究候選池

### 面向 G: 跳躍式探索（全新方向線）
**這些方向與現有 VT/GARCH 研究顯著不同，目的是打破舒適區。**

- **NLP 情緒分析**：用 FinBERT/LLM 分析財經新聞情緒，預測次日波動率或報酬
- **替代數據**：Google Trends 搜尋量（已測 null for VT overlay，但可用於報酬預測）、衛星停車場數據、航運追蹤
- **市場微結構**：order flow imbalance → 短期波動率預測、bid-ask spread dynamics
- **網絡/傳染模型**：用圖模型分析波動率在資產間的傳播路徑（beyond linear Granger）
- **因果推論**：用 DiD / RDD 分析政策事件（例如 Fed 升息）對波動率的因果影響
- **Agent-Based Simulation**：模擬不同比例投資人使用 VT 對市場穩定性的影響（如果所有人都用 12/VIX 會怎樣？）
- **加密 DeFi**：AMM 池的 impermanent loss 與波動率的關係、DeFi yield 策略的風險管理
- **氣候金融**：極端天氣事件對商品/保險公司波動率的影響
- **行為金融**：投資人對 VT 的心理接受度實驗、為什麼知道 VT 有效卻不用？
- **跨學科方法**：物理學的相變模型、生態學的 regime shift detection、複雜系統理論

### 面向 H: 論文撰寫與投稿
**第一篇：Leverage Direction Matters**
- `paper/leverage-direction/main.tex`（60 頁，3 contributions）
- 目標：Journal of Banking and Finance (JBF)
- 狀態：H3-H9 完成 Codex+Gemini 審查修正
- [ ] 最終校稿 + `/latex-academic-reviewer` 全面審查
- [ ] `/citation-verifier` 引用驗證
- [ ] 投稿準備（cover letter, highlights, graphical abstract）

**第二篇：Taiwan VT + TZ Information Transmission**
- `paper/taiwan-vt/main.tex`（34 頁）
- 目標：Pacific-Basin Finance Journal 或 Emerging Markets Review
- 初稿、Codex 審查、引用驗證已完成（見 archive）
- [x] Gemini 審查 → gemini_review_v1.md（3 weaknesses: TX tax、linear scaling、TSMC endogeneity）
- [ ] `/latex-academic-reviewer` 全面審查
- [ ] 修正 Gemini 指出的 3 弱點

**★ Paper 2 θ_EAV Heterogeneity Narrative — DECISION_MADE (2026-05-16, K1144)**

四個互補實驗（≥3 OOS-verified + Codex reviewed）確認 cross-sectional + temporal 雙 NULL：

| 實驗 | 類型 | 結果 | 說明 |
|------|------|------|------|
| K1109 (Sector ANOVA) | Cross-sectional | **FAIL** p=0.297 | N=31 pre-registered random sample；ANOVA joint test NULL；fabless β 衰減 46% |
| K1113 (Firm covariates) | Cross-sectional | **FAIL** 0/5 significant | log_mktcap / beta_rolling / ROA / leverage / turnover 全 null after BH |
| K1114 (Rolling HAC) | Temporal | FAIL | Initial 3/9 BH-pass — 但全是 96% overlap artifact（↓ block-boot） |
| K1140 (HAC + Block-boot) | Temporal | **0/9 BH-FDR PASS** | Newey-West L=24 + stationary block-bootstrap seed=42；MediaTek t 從 4.33→1.75 collapse |

**貢獻框架轉向（Decision）**：Paper 2 EAV 貢獻從「找 firm-attribute predictor」改為「嚴格 null verification」：
> *"After N=31 sector ANOVA + 5 firm covariates + rolling HAC + block-bootstrap, no systematic source of θ_EAV heterogeneity survives multiple-testing correction. Earnings-announcement variance effects appear universal in magnitude (or too noisy at stock level to detect cross-sectionally / temporally)."*

**Pending（paper_body task）**：body.tex EAV heterogeneity 段落需對應改寫（K1141）；narrative state = decision_made_awaiting_body_rewrite。K1302 γ provenance rebuild 仍 pending（FAIL_LARGE_DRIFT → needs separate investigation）。

**★ Paper 2 §3.2 Amplification Narrative — DECISION PENDING (2026-05-16, K1370)**

K1370 block-bootstrap CI 重跑揭露：論文 headline 10× 是 **spec mismatch artifact**。

| Spec / period | TAIEX γ | 9-indiv mean γ | Ratio | Source |
|---|---|---|---|---|
| Table 1 (rolling w=2000 NW-HAC, 1997-2026 +81 Asian-crisis days) | 0.272 | — | — | `paper2_table1_twii_stats` |
| Table 2 / K1302+K1302b (full-sample BW-robust, 2008-2024) | — | 0.027 | — | K1302/K1302b |
| Body.tex §3.2 headline = Table 1 ÷ Table 2 | 0.272 | 0.027 | **10×** | spec-mismatch artifact |
| K1370 matched-sample (2008-2024 both) BW-robust | 0.114 | 0.024 | **4.70×** | K1370 sanity (B=10 quick + B=1000 in progress) |
| K1370 mixed-sample (TAIEX 1997-2026 BW-robust / indiv 2008-2024) | 0.106 | 0.024 | **4.35×** | K1370 sanity |

**Same-spec same-period 比率落在 4.35-4.70×，不是 10×**。Codex v1 review FAIL → v2 (hash-stable + cache guard + per-series n) CONDITIONAL PASS → B=1000 重跑 ETA ~44 min（22:36 CST 啟動）。

**Decision needed (user)**：
1. (A) headline 改為 **4.7×** matched-sample + 完整披露 spec/period 一致性，撤回 10× 與 8.8× / 9.1× 衍生敘述
2. (B) headline 保留 10× 但補強質性免責：標明 「spec asymmetric, not same-methodology comparison」
3. (C) 雙報導：matched-spec 4.7× 為 primary，extended-TAIEX rolling 10× 為 supplementary 並標明 spec mismatch

**Recommendation**：選項 A — 研究誠實 § 第 6 條「結論強度不超過證據；推翻舊結論必回溯更正」。10× headline 不能用 same-spec 復現，等同無法 reproduce。

**Pending**：B=1000 CI 完成 → Codex re-review → user decision (A/B/C) → body.tex §3.2 重寫 → reproduce.py binding 補 K1370。Narrative state = `decision_pending` (NOT yet `decision_made_awaiting_body_rewrite`)。

**第三篇：Is Volatility Targeting Just Trend Following?**
- `paper/vt-trend-following/main.tex`（29 頁）
- 目標：Journal of Portfolio Management 或 Financial Analysts Journal
- 核心貢獻：分解 VT 的 alpha 來源（K46→K53→K79: r=0.564, VT alpha = trend following）
- [x] `/latex-academic-reviewer` 全面審查 → review_v2.tex（5H/12M/6L）
  - HIGH: 樣本期間不一致、BAB proxy（SPLV→AQR）、MDD 只有 5 美股、1.4% 數字不可驗證、需引用 K687/K697/K688
  - K687 分析：**不矛盾**——VT 打敗 BH(SPY) 但打不過 BH(50/50)，支持 insurance 論述
- [ ] 修正 review_v2 的 5 HIGH
- [ ] Gemini 審查
- [ ] `/citation-verifier` 引用驗證

**第三篇相關方向探索：Copula-GARCH for Portfolio Risk Management**（2026-04-17 narrative state machine triggered, user decision pending）

三個互補實驗（K1100b uniform / K1100d regime / K1100c asymmetric）完成：

| 實驗 | 方向 | 結果 | Mechanism implication |
|------|------|------|----------------------|
| K1100b (2026-04-13) | Student-t / Clayton uniform | 5/5 NULL | 對稱或單下尾 copula 不足 |
| K1100d (2026-04-17) | VIX regime-switching (Gaussian↔Student-t/Clayton) | 5/5 NULL | 反直覺：crisis 子期 RS 反略輸 DCC，regime conditioning 無用 |
| K1100c (2026-04-17) | Hansen SkewT + Joe upper-tail | **2/5 PASS** | SPY-TLT Joe DM=+10.36, SPY-GLD Joe DM=+7.66 (λ_L<0.05); equity-equity (λ_L>0.4) 仍 NULL |

**重大發現**：copula 非 general NULL — **asset-class-specific**。
- **Mixing-averaging mechanism**: 50/50 portfolio variance = w₁²h₁+w₂²h₂+2w₁w₂ρs₁s₂ 由 ρ_t 主導
- 高 tail-dep (equity-equity, λ_L 0.4-0.6): DCC ρ 已捕獲主 info → copula 邊際貢獻小
- 低 tail-dep (flight-to-safety, λ_L <0.05): DCC under-specifies regime → Joe upper-tail 正確 capture 殘餘結構
- **Joe copula is the star** (不是 SkewT)：上尾結構是 K1100b 遺漏的關鍵

**新 Paper 3 可發表主張**（narrative state machine: **decision_made_awaiting_body_rewrite**）：
> 「Joe copula with upper-tail structure significantly beats DCC for flight-to-safety pairs (equity-bond, equity-gold), but not equity-equity pairs, due to portfolio-mixing mechanism.」

**決策：Option A 採用**（2026-05-13 自主推進，依 2026-04-27 paper portfolio 授權）：
- K1100e (N=13 pairs, n_harvey_joe=9/13) SUPPORT：equity-equity 0/3 PASS, equity-bond 3/3, equity-commodity 3/3, equity-fx 2/2, equity-credit 1/2
- Spearman ρ(λ_L, Joe_pass) = -0.79 (p=0.0006) 確認 λ_L threshold 假說
- paper3_decision = "SUPPORT: Publish asset-class-specific copula claim"
- **(A) Reframe Paper 3 為 asset-class-specific copula study** — 三層實驗充分（K1100b null + K1100e N=13 + λ_L threshold confirmed），目標 J. Financial Econometrics / IJF
- Body rewrite 可開始（主線程執行，不走 worktree agent）

**未來可能的第四篇：VIX Sufficient Statistic**
- 23+ 個指標全被 VIX 吸收的 comprehensive study
- 適合 Journal of Financial Economics 或 Review of Financial Studies
- 需要更多跨市場驗證（目前只有 US + Taiwan）

**第九篇：Multiplicative GARCH-X with VIX**
- `paper/garch-x-vix/main.tex`（31 頁，3 contributions）
- 目標：Journal of Empirical Finance 或 Journal of Forecasting
- 狀態：✅ 初稿完成（2026-04-10）
- 核心實驗：K988/K988b（17 規格比較）、K994（跨資產）、K995（VaR/ES）、K997（本地 fear index）、K998（VRP 預測 null）
- 核心發現：A4f（VIX², free ω）DM t=4.48 vs GJR，勝所有 GARCH-MIDAS
- [x] 初稿撰寫（31 頁，24 references）
- [ ] `/latex-academic-reviewer` 全面審查
- [ ] `/citation-verifier` 引用驗證
- [ ] Codex adversarial review
- [ ] 補充 robustness（refit frequency sensitivity、sub-period analysis）
- 適合 Journal of Financial Economics 或 Review of Financial Studies
- 需要更多跨市場驗證（目前只有 US + Taiwan）

### 面向 I: 期貨避險（Futures Hedging）
**動機**：K341 建立框架（ES=F r=0.978, VIX>25 tail hedge 資本效率最高），需深化為完整研究路線。
**核心問題**：期貨避險能否系統性改善 50/50+VT？台灣投資人如何用台指期？

**⚠️ 方法論原則：避險效果用避險指標評估，不跟交易策略比 Sharpe/CAGR**
| 指標 | 定義 | 用途 |
|------|------|------|
| Hedging Effectiveness (HE) | 1 - Var(hedged)/Var(unhedged) | 主要指標，Ederington (1979) |
| Basis Risk | Var(spot - h×futures) 的穩定性 | 殘差風險 |
| VaR/ES Reduction | hedged vs unhedged 的尾部風險改善 | 極端保護 |
| Utility (mean-variance) | E[R] - λ/2 × Var(R) | 風險偏好依賴 |
| 避險成本 | margin + roll + basis cost | 實際成本（非 vs B&H 機會成本）|
| OHR 穩定性 | 不同 regime 下 h 的波動 | 實務可行性 |

**已完成實驗**：見 `docs/research_archive/completed_phases_2026-03.md`（I0, I1, I1b, I2, I3, I5, I6, I8, I9, I10, I11, I12, K199, K340, K341, K417）

**研究方向（開放）：**
- [ ] I4: VIX futures roll yield 策略 — contango 環境下的 roll yield 收割 vs 尾部風險保護 ⚠️ **BLOCKED: 需要 VIX futures 歷史數據（yfinance 無）**
- [ ] I7: 台灣投資人跨境避險實務 — 用台指期避台股、用 ES mini 避美股，匯率風險、保證金需求、稅務影響

**學術參考（待查）：**
- Baillie & Myers (1991): Bivariate GARCH OHR
- Kroner & Sultan (1993): Time-varying OHR with error correction
- Lien & Tse (2002): Some recent developments in futures hedging
- Alexander & Barbosa (2007): Minimum variance hedge ratios
- 台灣：Chen et al. 台指期最適避險比率系列研究

### 面向 TW: 台灣市場專線
**核心結論：8.63/VIX + 月度再平衡是台灣投資人的最佳 VT 策略**

**已確立的結論：**
- 8.63/VIX = 12/(VIX×1.39)，修正後 Sharpe 0.69，MDD -15.3%（Q1/R15）
- VIX 優於 VXEEM（R12: Spearman 0.595 vs 0.459，因 0050.TW≈50% TSMC→美國科技情緒）
- SPY→台股 spillover 真實存在（T5b: r=0.376, Granger F=58.8）
- SPY Momentum 5d/10d → 0050.TW c2c Harvey PASS，但 **o2o FAIL**（I8 timing bias）→ 學術發現非交易策略
- 台灣 0% 資本利得稅 = VT 結構優勢（K26/K86）
- TAIEX gamma 0.153 > 0050 0.087 > TSMC 0.039（T5a），ETF 分散化放大 gamma
- 台灣 MIDAS: 進口 YoY 唯一有增量（G12），其餘景氣燈號/M2 全 null
- 本土指標（外資買賣超/融資融券/PUT-CALL）全 null（G8）

**開放議題：**
- [ ] VIXTWN 數據累積到 252 天後驗證 ratio 穩定性（Q6）
- [ ] 台灣 5-min 數據 HAR-RV（0050.TW 47 天，ETA 2026 Q2）
- [ ] **金融股早期預警系統**：K757 發現 Fubon→TSMC Granger (F=6.11)。可建立金融股壓力指標作為 TSMC vol 早期預警
- [x] ~~K1059: TSMC → 0050.TW ETF event study~~ — NULL at T+0 but A4f advantage concentrated in event window (DM t=2.50)
- [x] ~~K1060: Individual Taiwan stock EAV~~ — **★★ 重大發現**：T+0 ratio=0.936 (NULL) but T+1 ratio=1.466 (p=0.034). Taiwan 盤後公告 → vol shock 在 T+1。解開 K1059 謎題。
- [ ] **K1061**: Extend to full TWSE 50 constituents (N≥50 for binomial power)
- [ ] **K1062**: Re-run K1059 on 0050.TW with **T+1 event window** to confirm ETF-level EAV
- [ ] **K1063**: Scrape actual announcement timestamps (盤中 vs 盤後) for cleaner T+0/T+1 classification
- [ ] **K1064**: Test whether `TW_EAV_factor` (sector-conditional, T+1) can serve as exogenous regressor in A4f family (K1058 NS may be due to un-conditioned EAV)
- [ ] ★ **台股財報公告日 × 波動率研究** [提出: 用戶, 2026-04-12]（原始研究方向，上述 K1059-K1064 為子實驗）：
  - **數據**：`財報公告日.txt`（Big5 編碼），2,411 家公司、158,674 筆、1986-2025、97% 有公告日。TSMC 96 筆。欄位：公司代碼/簡稱/財報期間(YYYYMM)/公告日(YYYY/MM/DD)
  - **方向 1（個股層級）**：Earnings Announcement Volatility (EAV) — 公告日前後 [-5,+5] 天的異常波動率，分析 early/on-time/late filer 的差異
  - **方向 2（TSMC → 0050.TW）**：TSMC 佔 0050.TW 50% 權重。TSMC 財報公告是否驅動 0050.TW 異常波動？公告日 VT 策略應否調整？
  - **方向 3（聚集效應）**：多家公司同日公告時（如財報季密集期），0050.TW/TAIEX 波動率是否顯著上升？與 K1050（SPY 盈餘季均勻改善）對照
  - **方向 4（A4f 台灣擴展）**：結合 K1058（A4f 0050.TW DM NS）——A4f 在台股財報日附近是否表現更好/更差？VIX 是否捕捉台股 earnings uncertainty？
  - **方向 5（學術貢獻）**：台股 40 年 earnings announcement 數據 + VT 策略 = 獨特切入角度，可能成為 Paper 2（Taiwan VT）的重要補充
  - **注意**：需要 TAIEX/0050.TW 個股日頻價格配合（yfinance 可取 2003 年後）

**論文**：第二篇 `paper/taiwan-vt/main.tex`（34 頁）涵蓋台灣 VT + TZ 資訊傳遞


> **Codex / Gemini / 用戶歷史建議**已移至 [`agent-specs/references/research_program_archive_2026Q2.md`](agent-specs/references/research_program_archive_2026Q2.md#archive-codexgemini-用戶-歷史建議2026-03-26--2026-04-14)。新建議請直接 append 此處或該歷史檔。

## 前沿文獻方向（2025-2026）

### 即刻可行動（不需新數據）
1. ★ ~~Window Size Sensitivity~~ → **K783 完成**：expanding window 以 QLIKE=0.529 勝 w=2000 的 0.560（DM=-3.23 Harvey PASS）。w=2000 不是最優。
   - [x] **K783b 完成**：最優 window 因資產而異。QQQ 偏好 504（DM=+3.59 PASS），GLD 偏好 3000，0050 偏好 1000，BTC 偏好 2000。**w=2000 仍是合理預設。**
   - [x] **K783c 完成**：regime-dependent。危機→w=2000，中波動→w=504，平靜→w=252。1/14 DM 通過 Harvey。w=504 是跨 regime 最佳折衷。
2. ★ ~~MF2-GARCH~~ → **K785 完成 NULL**：GJR baseline 仍勝（QLIKE 0.529），MF2-EWMA 0.533 (NS)，MF2-MEM 0.599（worse）。Expanding GJR 已隱式捕捉長期趨勢。
3. KAN-GARCH-MIDAS（結構化 NN 可能突破 ML ceiling）— J. Applied Economics 2025
4. VIX-Managed Portfolio 文獻引用整理 — Int. Rev. Financial Analysis 2024（支持 Paper 3）

### 需 5-min 數據（ETA 2026 Q2）
- [ ] HAR-PD (Path-Dependent) — arXiv:2503.00851
- [ ] Adaptive Multi-Factor HAR — FoFI 2026, Cinquetti et al.（287 個高頻因子）
- [ ] HAR + Wavelet Decomposition — ScienceDirect 2026
- [ ] HAR-GNN（Graph Neural Network）— ScienceDirect 2024
- [ ] Graph Signal Processing HAR — arXiv:2410.22706
- [ ] PatchTST-lite vs HAR-RV — MDPI 2025
- [ ] Neural Heteroscedasticity — Eng App AI 2025
- [ ] Intraday Commonality — JFE 2024

### 需 Options/Tick 數據（BLOCKED）
- [ ] Options-Driven Vol Forecasting — Quantitative Finance 2025
- [ ] Bespoke Realized Volatility — Patton & Zhang, J. Econometrics 2026（需 tick data）
- [ ] Vision Transformer for RV — arXiv:2511.03046（需 IV surface 圖像）

### ML-GARCH 混合
- [x] ~~KAN-GARCH-MIDAS~~ → **K1263 完成 NULL (2026-05-03)**: SPY KAN QLIKE 23.7% 比 GJR 差 (DM t=+4.89 p=0.000), QQQ 32.8% 差 (DM t=+6.35)，0/3 gates × 2 assets。**ML ceiling 第 7 次確認**。Counter-intuitive：2024-2025 frontier 結構化 NN + MIDAS macro fundamentals 反而比 30 年前 GJR-Normal 差 24-33%。
- [x] ~~GARCH-Informed NN (GINN)~~ → **K816v2 完成 NULL**。修正 GJR state propagation 後 DM=2.96→0.64（完全 NS）。GJR baseline 改善 8.56%，DM 是 artifact。**ML ceiling 第 6 次確認**。
- [x] ★ ~~GARCH-GRU~~ → **K784 完成 NULL**：QLIKE 排 #1 但 vs GJR DM=-0.51 不顯著。ML 額外複雜度不帶來改善。
- [x] ~~HAR Directional Prediction~~ → **K787 完成**：67.9% 方向準確率(z=8.03)但無經濟價值（timing +33% vs B&H +58%）。VIX 對方向無用(49.6%)。
- [ ] **Probabilistic RV Quantile Forecasting** — arXiv:2508.15922（從 HAR/GARCH 點預測到條件分位數）
- [ ] Sentiment-Augmented GARCH-LSTM — Computational Economics 2025
- [ ] KAN for VIX Forecasting — Expert Systems with Applications 2025
- [ ] CNN-Transformer Hybrid — European J. Finance 2025
- [ ] GARCH-to-Neural — AAAI 2024
- [ ] ML Risk-Based Allocation — Scientific Reports 2025（LSTM + regime switching，Sharpe 1.38）

### Rough Volatility & Hurst
- [x] ~~Multivariate fBm for RV~~ → **K806 完成 NULL**（⚠️ Codex 1 HIGH: 0050.TW 未清洗，跨資產 H 不可信；SPY 自身結果可信）。自身 H(t) 改善 NS (DM=-0.09)。5 資產全 rough (H<<0.5)。日頻 variogram 不夠精確。
- [ ] ★ **Multivariate Rough Volatility Model** — arXiv:2412.14353 (Feb 2026)。多變量 fractional OU + GMM 估計。跨資產 rough vol 的正式框架。
- [ ] Time-Varying Hurst via EWMA — arXiv:2509.05820
- [ ] Adaptive Fractal Dynamics — Frontiers Applied Math 2025
- [ ] Non-Gaussian Rough Vol（α-stable increments）— arXiv:2507.15437

### Tail Risk & Conformal Prediction
- [ ] Regime-Weighted Conformal VaR (RWC) — arXiv:2602.03903 (2026)。控制非定態 portfolio VaR 超限率。regime-structured vol clustering。
- [ ] Conformal Predictive Portfolio Selection (CPPS) — arXiv:2410.16333。預測區間 → 選最佳投資組合。
- [ ] ★ **Proxy-Reliance Control in Conformal VaR** — arXiv:2603.22569 (2026)。校準 one-sided VaR 時控制 proxy 依賴。直接相關我們的 Patton (2011) proxy-robust 框架。
- [ ] **Online Conformal via Universal Portfolio** — arXiv:2602.03168 (2026)。在線 conformal prediction + portfolio theory 交叉。
- [ ] **KOWCPI (Kernel-Optimally-Weighted Conformal)** — arXiv:2405.16828。自適應權重 conformal prediction interval，適合波動率聚集。
- [ ] Risk Parity + Heavy-Tailed + Regime-Switching DCC — Paolella (2025, JTSA)

### 期貨避險方法論
- [ ] Quadratic Hedging under GARCH — Ma, J. Futures Markets 2026
- [ ] Copula-based GARCH Hedge — Hsu et al.
- [ ] Wild Bootstrap OHR — JRFM 2024
- [ ] Partial Cointegration Hedging — RQFA 2023
- [ ] Regime-Switching Correlation Hedging

### 新發現（2026-04-01 文獻搜尋）
- [ ] **Transfer Learning for New Issues Vol** — arXiv:2503.12648 (March 2025)。多源遷移學習預測數據稀少資產（新 IPO/分割股）的波動率。實務導向工具。

### Score-Driven (GAS) Models
- [x] ~~GAS-t vs GARCH on equity~~ → **K1038/K437 完成 NULL**。4 資產全 NS（SPY DM t=-0.99, QQQ t=-0.30）。Score-driven robustification 不改善 QLIKE。但 VaR violation rate 稍低（內建 Student-t）。結論：US equity 上 downweighting 大 shock 反而失資訊
- [ ] **K1129 (NEW 2026-04-13, user 提)**: 測 commodity/electricity markets 上 GAS-t 是否真有優勢（Creal-Koopman-Lucas 文獻主張）。USO/GLD/UNG/BTC × GJR baseline。equity null ≠ commodity null，需獨立驗證

### 其他
- [ ] Regime-aware In-Context Learning — arXiv:2603.10299（LLM vol forecasting）
- [ ] 「HAR ceiling」驗證 — Los Flamingos 2025
- [ ] Financial Innovation 2025 review — realized volatility forecasting 綜述
- [ ] RGARCH-CARR-SK（Realized GARCH + CARR + 高階動差）— 2025
- [ ] Multiplicative Volatility Factor (MVF) — ScienceDirect 2025, J. Econometrics
- [ ] VOLARE 平台（HAR/HAR-Q/MEM/AMEM 標準化比較框架）— arXiv:2602.19732
- [ ] Multi-Transformer Vol Forecast — Engineering App AI 2024

## 決策框架

### 何時深入某面向
- 發現新線索（例：Gemini 建議 Excess Fear Signal → 立刻測試）
- 新數據可用（例：5-min 累積到 60 天 → 重測 HAR-RV）
- 舊結論需重新驗證（例：gamma decline → VT 還有效嗎？）

### 何時暫停某面向
- 連續 3 次實驗無改善 → 暫停但不關閉（標記為「等待新 input」）
- 缺乏數據或工具 → blocked（標記預計解除日期）

### 何時回訪已「完成」的面向
- 數據量增加（OOS 延伸、5-min 累積）
- 新方法出現（文獻搜尋發現）
- 用戶提出新需求
- 之前的 null result 可能因條件改變而翻轉

## 發佈規範
- 每個發現即時記錄（thinking + knowledge + feed）
- Feed 文章用 `feed-publisher` skill，確保品質
- 平台型發佈（文章池、排程、節奏釋出、下架、重釋出）轉交 `admin-ops`
- 預設可先進文章池（`draft` / `scheduled`），再依節奏釋出，不必每次都立即公開
- 所有議題標注發起者（Gemini/Codex/Claude/用戶）
- 具體發現存 `research_findings.md`（加入 embedding）
- Claude 應定期讀取平台摘要（尤其 analytics / questions summary），把讀者回饋與高分會員問題納入研究來源


---

> **研究發現與成果 / 歷史 Next Session Priorities** 已移至 [`agent-specs/references/research_program_archive_2026Q2.md`](agent-specs/references/research_program_archive_2026Q2.md)。保留此檔的體積在 bootstrap 範圍內。


## 重要事件日曆（當月+下月，每月更新覆蓋）
**最後更新：2026-04-10。下次更新：2026-05-01。**

### 美股事件
| 日期 | 事件 | 研究安排 | 文章安排 |
|------|------|---------|---------|
| **04/28-29** | **FOMC 利率決議 + Powell 記者會** | FOMC 對 VIX/vol regime 影響 | 預告 04/26，解讀 04/30 |
| **05/02 (五)** | **NFP 非農就業（4 月）** | 就業 vs vol | 預告 04/30，解讀 05/03 |
| **05/13 (二)** | **CPI 通膨數據（4 月）** | CPI surprise | 預告 05/11，解讀 05/14 |
| **05/29 (四)** | **GDP 第二估（Q1）** | GDP vs vol | 預告 05/27，解讀 05/30 |

### 台股事件
| 日期 | 事件 | 研究安排 | 文章安排 |
|------|------|---------|---------|
| **04/16 (四)** | **TSMC Q1 法說會** | TSMC earnings 對 0050.TW vol | 預告 04/14，解讀 04/17 |
| **04/17 (五)** | **中經院台灣經濟預測** | 經濟預測修正對台股 sentiment | 搭配法說會文章 |
| **05/10 前** | **TSMC 4月營收公告** | TSMC 營收 surprise | 預告 05/08，解讀 05/11 |
| **06月~** | **台股除權息旺季開始** | 除權息對 vol/return | 系列文章 |

### 事件執行原則
- 事件前 2-3 天發佈「預告」文章（一般讀者 + 研究各 1 篇）
- 事件後 1 天發佈「解讀」文章
- 研究實驗在事件前 1 週完成，結果寫入文章
- 用 CronCreate 設定 one-shot reminder 確保不遺漏
- **每月 1 日更新此日曆，覆蓋而非累積**

## 待深入研究主題

### 除權息研究方向（用戶指定）
- [ ] 除權息前後波動率是否系統性改變？（類似 K498 earnings 但用台股個股/ETF）
- [ ] 高股息 ETF（0056/00878/00919）除息日前後的價格行為
- [ ] 「填息率」與波動率的關係——填息快的股票 vol 是否較低？
- [ ] 除息日對 0050.TW 的 vol 影響（0050 成分股集中除息期間）

### SEC Filings / EPU / Google Trends 研究方向
→ 完整項目清單見 `docs/research_archive/detailed_research_topics.md`
- SEC Filings（10-K/10-Q/8-K 文字探勘、情緒、財務、管理、MOPS）：長期方向，待數據取得
- EPU/GPR：VIX sufficiency 限制下作為內容題材（每月至少 1 篇市場解讀）

### 成交量作為波動率預測因子（用戶提出）
**文獻基礎**：Lamoureux & Lastrapes (1990), Clark (1973) MDH, Tauchen & Pitts (1983)

**過去研究**：K113 null, K135 OOS null, K136 BTC 有效, K418 Taiwan null, K527 OOS 失敗（MDH = contemporaneous）

#### ⚠️ K519 上架暫停（K521 data alignment bug）
K519-K521 + K527 完成結果：見 archive。
**結論**：上架暫停——需要找到在 5AM-9AM 之間可執行的交易機制才能重啟。

#### 台指期貨 Overnight Gap Strategy（K515 延伸，高優先）
- [x] **K1264 完成 REJECT (2026-05-03)**：n=2179 days (2017-05-16~2026-04-28), 5bp round-trip cost。Gross Sharpe 1.045 (t=3.07) replicates K515 SPY finding，但 5bp 吃 81% gross → Net Sharpe 0.200 (t=0.59) << 0.5 listing 門檻。SPY-conditioning ratio 0.94 (H2 fail)。**Holiday gap 反向 finding**: long-weekend ≥4d -9.33bp vs normal 1d +7.72bp。Bear-year asymmetry: 2018/2022 systematic -19%。Revive 條件: cost ≤3bp OR normal-1day filter + regime timing。**NOT listing-eligible**.

## Codex 論文審查記錄
→ 完整審查詳見 `docs/research_archive/codex_paper_reviews.md`

## Article 三模 Review Pattern（2026-05-02 立）

**Production article 出 publication pipeline 後 24h 內必走 3-model review**（Claude write → Gemini-2.5-pro text framing → Codex GPT-5.4 source-code）。實證 6 篇 article × 20+ source-level catches gemini 純 markdown review 漏看：

| Article | Gemini caught | Codex 二審 caught (gemini missed) |
|---------|---------------|----------------------------------|
| K518 mile_67169c30 | tone framing | 21年/27年錯, 5×5獨立區間錯, Golden Cross 2/5→3/5, SPY/債券 vs SPY/GLD |
| K672 mile_cbbf35cb | overclaim flag | A7 >20pp 每次 / B1 股債 spec mismatch |
| K655 mile_40fbffbb | NEEDS_FIX (BH 60/40 spec) | rolling-window 21天細節 |
| K1018 mile_a4311ba7 | PASS | MDD cumsum bug, 控制多重檢驗 overclaim, dm_test() 非標準 DM |
| FOMC mile_fef2e0b2 | SPY/S&P typo (1) | sign error, VIX 對帳混用, T-2 id 誤指, 78%→95.5% 來源, traceability |
| K549 mile_50030b56 | (skipped → codex direct) | 所有 CI 重疊 (只算 4/7), 多重比較 framing, 5 個 2 年期 vs 5 個年份視窗, VIX 同期 lookahead |

**Operational caveats**：
- **Codex CLI quota**：高頻 review 易撞 OpenAI usage limit (e.g. 2026-05-02 21:44 CST 撞，reset ~3h 後)
- **Codex 中文 prompt 用 heredoc**（避免 printf UTF-8 % char bug：K655 first attempt 撞）
- **Stop-gap：Gemini-2.5-pro PASS_WITH_CAVEAT** 可暫代但不可省 codex（gemini 無法看 implementation backing）
- **Hook discipline**：metric helper edit 即使是 K1018 同 pattern，重跑前仍要走獨立 codex review 流程

## 其他研究方向（詳細版）
→ MEM 文獻、Gemini/用戶建議（WVD/TE-VT/K770 修正版/Overnight component）、Hansen & Lunde Gold Standard 比較 → 見 `docs/research_archive/detailed_research_topics.md`

## Paper 4 vix-sufficiency Table 2 — K732/K736 Decision (2026-04-19)

**Root cause report**（`task_7100e5d03ec2` + `task_27ea42d3e0eb` a750dc agent）：

- **K732 row**: Paper IS t-stat=1.64 實為 `dm_stat_oos=1.637` 抄錯格。真 IS t-stat = 5.58 (script) ≈ 5.29 (canonical)。
- **K736 row**: Composite salad — 跨 3 sub-experiments 混搭欄位。

**Decision**:
- K732: **(b) 改 paper**，canonical values: partial_r=0.086, is_t_stat=5.29, r²_oos_ct=0.297, dm_abs_t=0.67, raw_p=0.50
- K736: **(b) split 3 rows** by sub-experiment（VIX seasonality / SPY return seasonality / VT weight seasonality）或**(c) 單列 canonical** (is_t=-0.27, r²_oos=0.357, dm=0.21)

**Next**: `task_729e70de0f66` Sub4 body_v3.tex 更新 — 主線程 L188 限做，分段 edit。

## Paper 4 Citation Audit (2026-04-19, task_ced5ad598ae3)

- Total: 38 inline cites / 40 bibitems
- **MAJOR 1**: harvey2016 content mis-attribution in abstract L48 + intro L80（Sec 5.2 已 v2 改但前面段沒）— 投稿前必修
- MED 5: bibliography 未 alphabetize、0 DOIs、luo2019 weak support (line 206)、2 orphan bibitems (bollerslev2020 / engle2006)
- MINOR 2: Baruník / Božović diacritics
- **Action**: 納入 Sub4 body_v3.tex 更新時一併修

## Paper 5 vt-crowding-abm — 2026-04-27 UPDATE: 撤回 APPROVE FOR SUBMISSION

**舊 audit (2026-04-19 af0c6b)**: GREEN 33/33 / Seed robust / FRL 5 hard requirements met → APPROVE FOR SUBMISSION（**已撤回 2026-04-27**）

**新 verdict（2026-04-27 v2 round + cross-paper meta-eval addendum）**:
- single-paper latex agent 4.4★ → **NotebookLM cross-paper meta-eval 撤回到 3.5-3.8★**（per memory `feedback_paper_cross_paper_meta_eval`）
- FRL 預期：85-90% → **40-50%**（desk-reject 風險不可忽略）
- 根因：ABM 70% 崩盤閾值是 λ/γ 數學結果不是 emergent finding；single-paper agent 看不到「設計性 vs emergent」誠實 framing 問題；portfolio overlap risk
- Paper 自己 §1 L60-61 + §2 L97 已部分 acknowledge "quantifies---rather than discovers" 但 reviewer 仍可能challenge threshold magnitude IS λ/γ-determined

**v3 必修**（升級 action plan，per `paper/vt-crowding-abm/review_history/v2/README.md` L⚠️ addendum）:
- ABM mechanism framing 重寫（誠實「parameter sensitivity + crowding cost bounding」）
- 補「非 VT 策略也有的擁擠效應」對照組（NotebookLM 建議）
- 加 dataset/methodology portfolio 區隔段
- 既有 M1-M9 v2 fix list（broken cross-ref / abstract trim / barroso2021 reframe / harvey2018 DOI 等）仍要修
- 不升 ready stage 直到 v3 round 含 cross-paper meta-evaluation 通過

**Next**: 主線程 P5 v3 round 含 ABM framing rewrite — Tier B，effort 估 1-2 週（不是 quick fix）。短期不投稿。

## Paper Portfolio Status (2026-04-20 02:14 — post K1257 BMA + P10 reproduce scaffold)

| # | Paper | Status | Blocker |
|---|---|---|---|
| **P5** | **vt-crowding-abm** | ✅ **READY_FOR_SUBMISSION 全 gate PASS (2026-04-28, 9 paper portfolio 第二篇)** — v3 reframe + v4 主線程修 13 issues + v4.1 batch (sim-count unify 46,800 + AI-ack relocate + cole/baltas DOI) → v4 round verdict: academic **4.7★/5** (0/0/0/2 MED/5 MINOR) + citation **0 MAJOR / 0 MED / 2 MINOR**. 6/6 stage gate PASS (latex ≥4★ ✓ / citation 0 MAJOR ≤3 MED ✓ / reproduce GREEN 47/47 100% ✓ / compile 26p clean ✓ / FRL ≥R&R ~90-95% ✓ / self-contained ✓). knowledge entries: f1d85a74 (K1261) + f3b9edd4 (K1262) + 81ebfe54 (K1262b). reviews 歸檔 `paper/vt-crowding-abm/review_history/v1-v4/`. **Submission package 完整 ready @paper/vt-crowding-abm/** | Submission needs user click-submit on FRL portal（cover letter + suggested reviewers prep 待主線程 dispatch，類比 P6 7d2149a0 pattern）；或維持 ready + 每月 continuous review loop（v5 預計 2026-05-28） |
| **P6** | **prg-periodic-garch** | ✅ **READY_FOR_SUBMISSION 全 gate PASS (2026-04-27, 9 paper 首篇)** — v1-v4 完整 4 輪 paper-review-cycle + v4.1 batch fix 收斂; supabase status `ready_for_submission`; 6/6 gate PASS (latex 4.2★ + citation GREEN + cross-paper meta + FRL desk-accept 35-45% + K1260 fair-info + no tautology). **Reproduce gate 全 PASS**: reproduce.py 22 checks (15→22 加 K1260 §4.5 GJR-X 7 checks) / reproduce_report.json `match_rate=100%` / `alert_level=green` / audit_date 2026-04-27. PDF=15p / bibitems=22 / abstract=184 words / 5 tables / 7 equations. SUBMISSION_READY.md + send-alert df592119 已發 user。**Submission package 完整 ready @paper/prg-periodic-garch/** | Submission needs user click-submit on FRL portal (cover letter + suggested reviewers prep可由主線程 dispatch)；或維持 ready + 每月 continuous review loop |
| **P7** | **vix-sufficiency** | ✅ **READY — GREEN 98% (98/100)** + Sub1-6 closed (bundle + dividend + 5 divergence decisions + Table 6 K752 rewrite + source binding + reproduce.py synced) | Submission needs user click-submit on chosen journal (主線程 dispatch cover letter + journal selection rationale 待用戶解 standby) |
| **P4ins** | **vt-insurance-cost** | ✅ **READY — GREEN 100% (9/9)** (2026-04-19 88.9%→100% via L184 footnote + reproduce tolerance 5→10 bps 反映 documented dual-convention) | Submission needs user click-submit on chosen journal (主線程 dispatch cover letter ready) |
| P1 | leverage-direction | 🟡 **0 MISMATCH** + 28 MATCH + 9 NOTE + 19 UNTRACE (structural data-limit) | C1 ✅ K1256 3-spec / C2 ✅ Kupiec rounding / ✅ 7 figure scripts bundled MATCH / C3-C5 Tables 1/6/7/8/11/14 需 new experiments |
| P3 | vt-trend-following | 🟡 **0 MISMATCH** (83%, 34 UNTRACE structural) | Table 4 M5 ✅ hybrid BAB / Table 3 period ✅ errata; 剩 Table 5 13-market + Table 6 MDD bootstrap 需 new experiments |
| P2 | taiwan-vt | 🟡 **0 MISMATCH** (6→0 本 session, 69% verified + 24 UNTRACE structural) | ✅ TSMC/0050.TW/TWII γ 3-spec footnotes + reproduce.py NOTE reclass / ✅ SSVS PIP UNTRACEABLE / ✅ GJR+Normal viol NOTE; 剩 24 UNTRACE 需 Table 4/5 VT + Sec 6 macro experiments |
| P8 | volatility-absorption | 🔴 61.3% amber + **CRITICAL errata 識別** (2026-04-20 re-verified: 46 MATCH / 12 MISMATCH / 17 UNTRACE / 75 total — 無 drift since 2026-04-19) | `errata_pending.md`: CRITICAL (controlled t Harvey cross -3.14→-1.17) + HIGH (T10 2020-26 sign flip) + MEDIUM (10+ drifts). Path B 推薦 research-honest body revision。**Still awaiting user Path A/B/C decision**. |
| P9 | garch-x-vix | 🟡 submitted under review, snapshot 53.8% / live 84.6%, **shelf errata ready** | `errata_pending.md`: 0-11% DM t drift SPY/QQQ/GLD/USO, Harvey qualitative invariant — 無 body edit 直到 R1 reviewer response |
| **P10** | **crypto-fear-channel** | ✅ **READY_FOR_SUBMISSION 全 6/6 gate PASS (2026-04-28, 9-paper portfolio 第三篇)** — body draft (5 slot increment) → v1 round 3.95★ → v2.1+v2.2 fix 19 issues → v2 review 4.40★ + 升 review stage → v2.3 hotfix research-honesty + v2.4 cross-paper Highest-impact + K1025b BTC→VXN multi-asset OOS extension (commit 6a41fc40, experiments/k1025b/ + main.tex §6.4 + Table 7) → v3 review **4.55★/5** post-v3.1 hotfix (academic 0/0/0/2 MED/4 MINOR; citation 0 MAJOR/1 MED/4 MINOR; proxy a50cc2e8/aa23e837). Process discipline: v3 caught Table 7 numerical errors (recurrence of 2 days prior error_log lesson "quantitative claims must have JSON backing") → v3.1 hotfix Table 7 row 1+5 fix + reproduce.py 29→37 checks (8 K1025b byte-match checks added) + §6.4 substantive narrative re-direction (VIX 8.54× > VXN 5.76× honest framing, opposite to original buggy "~11×" claim). 6/6 gate (latex ≥4★ / citation 0 MAJOR / ≤3 MED / reproduce 37/37 GREEN / compile 17p clean / cross-paper meta = no fundamental issue post-K1025b). reviews 歸檔 paper/crypto-fear-channel/review_history/v1+v2+v3/. knowledge entries: 391774db (K1025b multi-asset robustness, P10/multi-asset-robustness category, confidence 0.85) | Submission needs user click-submit on chosen journal (cover letter + suggested reviewers prep 待主線程 dispatch，類比 P5/P6 pattern); target journal IJFMIM (1st) / JEF (2nd) / FRL (backup); 預測 ~94-95% 接受率 post-v3.1 |

### 2026-04-19 Session 重大成就
- **4 papers reproduce GREEN**（P4 vix-sufficiency 98% / P4 vt-insurance-cost 100% / P5 vt-crowding-abm 100% / P6 prg-periodic-garch 100%）— reproduce gate 達標但**reproduce GREEN ≠ submit-ready**（per memory `feedback_paper_multi_round_review`）；P5 經 NotebookLM cross-paper meta-eval 撤回 READY；P6 經 4 輪 review + 6/6 gate 升 ready_for_submission（首篇 portfolio）
- **6 papers 0 MISMATCH**（P1 / P2 / P3 / P4 / P5 / P6 — 3-spec disambiguation pattern 成功 3-paper 移植 + cross-source NOTE reclass）
- **2 errata_pending.md** shelf-ready（P8 / P9）記 CRITICAL / HIGH / MEDIUM 嚴重度分層
- **5 Codex ops victories**（P12 snapshot infra / P15 release-pool last_released_at fix / P10 P6 audit / P30 session-bootstrap v11 cleanup / P25 claim-next parent guard）
- **Data snapshot infra**（`scripts/snapshot_yfinance.py` + 5 paper data/ CSVs bundled yfinance drift 對策）
- **Release cadence unified**（settings interval_minutes 60→120 對齊 cron 每 2h canonical）
- Daily article 補池 **`mile_28f0ae1b`** 15,862 chars + 2 real charts（three-market binary-sufficient universality, Paper 2 連動）
- Daily article 補池 **`mile_a1f7bfa8`** K957 40 個實驗蒸餾 5 條 meta-lessons (research, 10,610 CJK)
- Daily article 補池 **`mile_a21a6e06`** K1091 meta-prediction OOS 股指 PASS 商品 FAIL (general, 6,828 CJK, 18:00 UTC 純 piggy-back auto-release 首例)
- Daily article 補池 **`mile_b9d5db50`** 跨市場 binary-sufficient 四國財報事件 (general-audience 版, 3,443 CJK, pre-empted 20:00 UTC breach)
- docs/error_log.md 加 2 entries (release-pool fix resolution + Codex quota blocker 2026-04-24)
- Memory: feedback_dont_ask_do + feedback_email_on_major_decisions + feedback_3spec_disambiguation（session 新 rules 入 MEMORY.md）

### 2026-04-19 18:00+ UTC post-compact saturation-round outcomes
- ✅ **Piggy-back alerts.py bug fix**: false-positive release_pool_gap 消除（補 .release_settings.json fallback）
- ✅ **experiments/INDEX.md rebuild** 1011→1012 K，uncovered 736→735
- ✅ **publication_candidates.json rebuild** uncovered 225→215
- ✅ **docs/strategy-registry.md drift fix** 14/10 active → 14/11 active verified
- ✅ **Strategy metrics refresh** 14 策略 Sharpe/MDD + Supabase strategy_metrics_cache 14/14 synced
- ✅ **docs/topic_diversity_audit.md refresh** 14h stale → fresh (feed tags 4665→4731)
- ✅ **Question-archive** test-garbage 54ba8732 清
- ✅ **K957 knowledge.json metadata fix** 37→40 Experiments (filesystem canonical)
- 📝 **5 next_draft_candidate memos** pipeline: K957✅ K1091✅ cross_market_binary✅ consumed / K1092 ready / K1174 DOWNGRADED
- 📝 **error_log.md** 5 新 sections (P1/P2/P3 reproduce stale / alerts piggy-back / K957 KB drift / applied-deferred markers)

## Platform V3 Editorial Redesign COMPLETE (2026-04-19)

**Status**: 上線 + RWD + 手機修正全部完成。`/v3/*` live 預覽、舊站 `/` byte-identical。
**Mission 對齊**：目標 4「把網頁平台運營好」— 品牌視覺升級至 NYT/Economist 雜誌風。

**交付**：
- 27 `/v3/*` routes（home + feed + reports/[id] + 7 tools + 13 admin）
- 8 Editorial primitives + 7 native 重繪（strategy-selector / risk-forecast / calculators / portfolio / me×3）
- 13 admin editorial frame + contained dark dashboard
- RWD at 768 / 480 breakpoints（useIsMobile hook + V3Shell hamburger drawer）
- LeadIllustration chart mobile fix、market checkbox wire-up、overflow-x 修正

**Deploy**: `d3ef25c` + `d202b4d` + `f4b0988` + `2f68833`。Zeabur `69e4aff350cfe9704d091e57` RUNNING。細節 `docs/frontend-v3-redesign.md`。

**待主人決定**：何時切 `active_frontend = v3`（目前獨立預覽不影響舊站 SEO）。

## 2026-05-08 自主 /loop session: 集中 systemic fixes

12-hour autonomous /loop 期間累積 **8 篇 articles published** + **5 systemic fixes**:

**Articles** (P4 daily_article published as draft, all real-data + 4-dimension quality):
- mile_4df2d060 (K479 wavelet vol mixed)
- mile_b6249667 (K485 SSVS PROMISING)
- mile_b79e0701 (K489 VIX term structure)
- mile_09c3dbf6 (K497 Patton loss sensitivity ρ=0.71)
- mile_21cf034d (K511 ETF pairs 5/5 FAIL)
- mile_0aa76d4d (K517 monthly conditioning ALL FAIL)
- mile_1ed654f4 (K544 tail hedge NEGATIVE confirms Israelov 2017)
- mile_fffc6147 (K550 adaptive VIX threshold NUANCED)
- mile_c5127413 (K571 VIX mean-reversion MARGINAL)
- mile_e8d99cf3 (K576 vol clustering NULL)
- mile_6dc01de9 (K594 adaptive window NULL)
- mile_340972b5 (K603 dynamic target MARGINAL)
- mile_257ddc69 (K635 fixed-vs-rolling GARCH)
- mile_f5714212 (K647 strategy-matcher v2)
- mile_bdf75de2 (K631 day-of-week ALL NULL)
- mile_4c1045ea (K663 rate environment GLD/TLT)

**Systemic fixes** (per "永遠修流程，不修資料"):
1. **Period-Attribution Checklist** in feed-publisher SKILL.md (3rd-occurrence trigger after d716099a/c496072f/ed9e4626 financial-quote audits all FAIL'd) — fiscal-year boundary table 7 公司 + mandatory checklist + BAD/GOOD examples
2. **publish_draft.py --update flag** (replaces 3rd one-off patch script) — 596L (+285), `errata.update_history[]` audit trail, 7 smoke tests PASS, 2x dogfood validated (major +5259c + light +694c)
3. **TW close staleness fix** in scripts/daily_update.py (rich article path) — 0050.TW 1-session lag explicit date stamp + warning when stale, 18 tests PASS
4. **TW staleness extension** to publish_milestone path — `build_milestone_description()` helper extracted, byte-for-byte text consistency enforced via test
5. **Task type backfill governance** — 29 NULL task_type pending tasks classified (paper_body 12 / experiment 9 / paper_decision 8)

**Important pattern**: Research-result articles consistently PASS audits (mile_d25f7f90 17/17, mile_0e3fb5f6 15/15, mile_146dc06e/f7584521/688f15e9/5a50ea3c daily formulaic chain). FAIL pattern was systematic to financial-quote articles only — Period-Attribution Checklist now blocks at source.

**Codex CLI**: ENOBUFS persistent through session, fallback to general-purpose subagent for all paper_review tasks (per .claude/rules/experiments.md).

---

## 2026-05-08 / 09 Session — Memory Integrity + Image-Fix + 3-Model Review Saga

**14 daily articles published**: K709 / K715 ★★★ / K717 / K722 / K852 / K719 self-correction / K726 K727-rejected / K753 / K890 / K928 / K936 / K911 / K945 / K947.

**Systemic fixes** (per "永遠修流程，不修資料"):

1. **Image-fix saga (102 articles)**: User-reported mile_53983530 K547 broken image → audit found 101 articles with relative-path images. Bulk fix 60 + 5 PNG regen for K438/K681 = **102 total**. Root cause: agent inconsistency. **P2 structural fix** in publish_draft.py: `normalize_image_paths` + `normalize_image_url_field` auto-upload local paths or fail (245 LOC + 15 tests).

2. **publish_draft.py P3 polish** (180 LOC + 20 tests, 99/99 suite PASS): tag-cap priority eviction (frontmatter > audience > K-id) + CLI UX (--draft alias, --phase default, /tmp path tolerance).

3. **Citation regex root-cause** (K928 footgun): sanitizer protection 3+ author citations from `and`-only to `(?:and|&amp;|&)`. publish_draft.py + publisher.py both patched + 2 regression tests.

4. **Knowledge.json memory integrity (51 entries)**:
   - **K936 audit (25 entries)**: K932-K956 ids carrying K109-K140 legacy content. All re-keyed batch.
   - **26-pair audit**: 23 Case B re-key K860-K882 → K43-K66 **RESTORED 23 lost early research entries** + 3 Case C preserved as `K<id>_legacy_pilot`. 0 deletion. Same root cause as 2026-04-10 bloat (merge_worktree.sh jq dedup bug).

5. **merge_worktree.sh dedup regression gate**: 446 LOC integrity gate + 171 LOC pytest (12 tests) + delta-mode integration (pre-merge baseline + post-merge check + `git reset --hard` on new corruption).

6. **memory-health SKILL.md +section 5** ID-vs-title 對齊檢查: jq one-liner + 4-step fix protocol — weekly cron will catch future regressions.

7. **mile_c4c73ed9 K1032 LIVE article**: Codex 24h-rule FAIL (2 CRIT + 1 SEVERE + 2 MAJOR + 2 MED + 1 MINOR). 7 fixes applied via publish_draft.py --update + errata 段落. **3-model review pattern saved LIVE article from prod hallucination** (per K1018 教訓 validated).

8. **feed-publisher SKILL.md +4 dogfood best practices**: proactive Supabase upload / dry-run sanitizer pre-check / image_url frontmatter scalar / tag count cap behavior.

9. **k947_results.json conclusion field** disambiguated (pair-specific DM verdicts replacing single "Yes").

**4 CRITICAL agent catches today** (Mission 2「研究誠實」直接 demonstrated):
- K719 cross-sectional vs rolling RV → self-correction story
- K726 K727-rejected timezone hypothesis → self-correction
- K936 knowledge.json id="K936" had K112 content → cross-check experiments/k112/ DNE → wrote about real K936
- K947 brief "PASS at Harvey" misled by conclusion field → DM table verified T-GJR FAIL → honest NULL

**Pattern**: Agents that cross-check `experiments/<id>/{README.md, results.json}` against knowledge.json/brief catch hallucinations. Pattern P4 queued to encode in agent-brief-template.md.

**Codex CLI**: smoke test `echo TEST` PASS but adversarial-review fails on git ENOBUFS (large diff). `codex exec --skip-git-repo-check` with stdin pipe works. Fallback path documented.


---

## 2026-05-09 / 10 Session — Daily Articles + 3-Model Review Pattern Continuation

**12 articles published** (10 K + 2 errata v2):

- **新文章**：K950 (cross-asset VT 0/5 NULL) / K953 (HAR-RV pilot PRELIMINARY) / K971 (CAViaR-VT 11yr OOS NULL) / K973 (Hurst rough vol NULL @ daily) / K979 research v1 (SKEW NULL Harvey 3.0) / K982 (sector dispersion VIX-suff) / K984 (SPY→TW50 daily lead-lag NULL net-of-cost) / K986 (Adaptive HAR LASSO/Ridge NULL) / K989 (MF2-VIX + VIX² synthesis NULL) / K990 (SPY→TW50 monthly NULL — 信號蒸發 daily 0.40 → monthly 0.03) / K981 (HAR + Wavelet NULL) / K1020 (MS(2)-A4f synthesis NULL — information substitution)
- **Errata v2 (Codex review fixes)**：K979 research mile_f46b6320 (Harvey ref + mechanical artifact 軟化 + quintile timing + DM sign + M7M8 n=1780) / K986 mile_912dd699 (CV-leakage caveat + GARCH ceiling 軟化) / K982 mile_9ed87beb (sample size 1936→1913 + high-corr t=13.7 framing + gross-of-cost + lookahead 細化)

**Systemic fixes** (per "永遠修流程，不修資料"):

1. **Dedup Layer-2 K-id title-test 補強**：feed-publisher SKILL.md + agent-brief-template.md 同步加 `jq title-test` 強制兜底 (K852 incident — grep -c 對中文夾雜上下文不可靠). 後續 K979 incident 用 audience-pivot 救援 (general → research) — dedup 不是禁令而是換角度提示。
2. **build_publication_candidates topic-family clustering**：對每個 K candidate 計算 ≥2 domain-tag overlap per audience，excludes K-id 不重複但 topic family 已 covered cases. missing_general 從 ~50 → 1 (K1018), missing_research → 1 (K1122). 跨語言 tag normalization (vix-sufficiency vs VIX 充分性) 留 P5 follow-up.
3. **gen_paper_review filter audience=daily + experiment_refs empty**：mile_d4a3b5c0/0347be08 等 formulaic cron output 不再被誤撈進 Codex 24h-rule 池.
4. **K728/K924 dead-end close + P5 build_publication_candidates results.json existence check queued**：避免 dispatcher 反覆 surface 無 source K.
5. **2× feed-sync 推 12 articles + 3 errata 上 Supabase**：214 inserted + 968 updated + 0 failed (total).

**3-Model Review Pattern 連續 4 次成功實戰**:

| Article | Codex catches |
|---|---|
| K979 research mile_f46b6320 | 2 MAJOR (Harvey framing + Q1-Q5 mechanical over-claim) + 2 MINOR (DM sign + M7/M8 n size) — 全 errata v2 修正 |
| K986 mile_912dd699 | 1 MAJOR (sklearn CV plain KFold within-window α leakage) + 1 MINOR (GARCH ceiling 過度打包) — errata v2 修 |
| K982 mile_9ed87beb | 2 MAJOR (sample size 1936→1913 + high-corr 22-day overlap autocorr) + 2 MINOR (gross-of-cost + regime same-day observable) — errata v2 修 |

**Pattern confirmed**: Codex source-code review 系統性抓出 Gemini text-framing review 漏的：(a) numerical-vs-narrative drift (b) statistical convention misuse (c) sample-size effective vs nominal (d) hyperparameter leakage (e) reference attribution. 全在 LIVE article 上線 24h 內捕獲 + 主線程 errata flow 修正。每篇 v2 errata 增加 ~400-1100 chars 的方法論誠實標記 — Mission 2 (research 嚴謹) + 研究誠實 #6 (推翻舊結論回溯更正) compliant.

**Diversity rule (CLAUDE.md 關 2) 實戰反思**：
- 「≥3 同 type 必換」rule 導致長 plateau (queue 全 P4 daily candidates)
- 用 ops/governance/paper_review 主線程任務手動 inject diversity 是必要 valve
- feedback_dispatch_over_diversity「不能 hold 空轉」與此 rule 之間需 case-by-case 判斷
- 主線程 Codex review (paper_review type) 是 daily article batch 的天然 partner — 每寫完一波 daily 接著 codex review push pr 入 last-5 解 daily 鎖

**今 session 數據**:
- 12 articles published (general audience), avg 5,300 chars
- 4 Codex primary-path reviews completed (K979 / K982 / K986 + 一筆早先 audit)
- 3 errata v2 完整修正
- 6+ systemic improvements (5 listed above + minor patches)
- 79 → 80 entries in experiment_experiences.json (dedup pattern entry)
- 363 → 366+ pending tasks in next_tasks.json (mostly auto-discovered + Codex 24h queue)

**遺留 backlog** (next session priorities):
- K1146 / K1169 / vix_sufficiency_expansion (P1 paper main-thread, awaiting policy direction)
- 11+ paper_review (Codex 24h-rule) for today's articles
- P5 multi_source_task_generator_v2 (5 task type generators)
- P5 cross-language tag normalization (topic_family_collision)

---

## 2026-05-11 Session — Dispatch / Refill / Paper2-Reproduce Gate Progress

**Session theme**: 5-layer dispatcher / refill / dedup hardening + paper2 reproduce gate 3/7 cat closure.

### Articles published

- mile_d1b23190 — K868 day/night RV decomposition (general)
- mile_b10348ee — K871 yield curve null vs SPY vol (general, null result)
- mile_410450e4 — K878 DXY null-result (general)
- mile_193a0d90 — K898 Paper 3 Table 3 reproducibility audit (general)
- mile_3b689404 — K904 Paper 8 reproducibility (honest plot twist, general)

### Paper 2 reproduce gate (3/7 cat closed)

- **Table 4 (tab:vt_results)** — K1175 byte-match bindings 10 VERIFIED checks (BH/EWMA/GARCH/GJR/8.63VIX × Sharpe+MDD). GJR VT MDD -22.3→-22.2 align K1175 -22.25 rounding.
- **Sec 2.5 (VIXTWN ratio + Steiger Z)** — K1181 4 VERIFIED checks (ratio=1.393, Spearman VIX-RV=0.595, Spearman VXEEM-RV=0.459, Steiger Z=16.2).
- **Sec 4.4 (0056.TW robustness)** — K558 test_8_robustness_0056.harvey_dm.t_stat=5.6664 byte-match paper 5.67.

### Paper 2 body_v3 review (v4, 2026-05-13) — MAJOR REVISION NEEDED

Previous HIGH issues H1/H2/H3/M2 all **RESOLVED** (HF section removed from body_v3). But 3 **new HIGH (BLOCKER)** issues found:

- **NEW-H1**: 8.63/VIX Sharpe = 1.137 (Table 3) vs 0.690 (Table 5 Reconciliation) — Table 5 cites Table 3 as source; root cause = Table 3 footnote claims daily vs monthly rebalancing simultaneously
- **NEW-H2**: GJR VT Sharpe increment stated as +0.114 (Intro+Conclusion) but arithmetic = 1.074−0.950 = +0.124; Table 3 shows 1.074 but Table 4 (same period) shows 1.084
- **NEW-H3**: 8.63/VIX MDD = −13.7% (Table 3) vs −15.3% (Section 4.3 narrative), same 2016–2026 period
- **Broken `\ref{sec:hf}`** in Introduction road map → compiles as "??" (HF section removed but ref not cleaned)
- **M1 still OPEN**: Section 4 → next section bridging paragraph missing

Full review at `paper/taiwan-vt/review_v4.md`. Traceback to K900/K1175 needed before any submission.

### Codex post-publish reviews (4 articles, Codex quota fallback)

- K1035 EVT-VaR (mile_052ed9e4) — PASS via Gemini fallback
- K1040 VRP/g_t (mile_b4774629) — PASS via Gemini fallback
- K971 CAViaR-VT (mile_8c3829e5) — CONDITIONAL PASS main-thread audit (1 MAJOR overclaim L51)
- K980 TGJR (mile_3655a10a) — CONDITIONAL PASS main-thread (28/28 numeric, 0 Critical/Major)

Codex CLI 0.121.0 daily quota exhausted at session 019e13ef—reset 2026-05-12 19:46 PT. All 4 reviews queued primary-path re-verify post-reset per K1259 lesson (subagent/secondary PASS ≠ primary-path PASS).

### Experiments

- **K1100h v2** Phase 1 — Codex CONDITIONAL PASS (0 MAJOR/0 MINOR, 4 v1 issues fixed: bar-agg 13:45 endpoint + settlement-day filter + Big5 fallback + HAC lag). Verdict BORDERLINE (DM-t=2.21 secondary 5% but Harvey |t|>3 fail). Knowledge entry written.
- **K1116d v2** ALFRED first-release vintage — Codex PASS (fetch v2) + CONDITIONAL PASS (main battery). Master verdict H2_ROBUST_NULL_VINTAGE_CONFIRMED (0/24 cells pass both vintage + revised cycles; worst pit_shift1×all DM t=-5.21). Paper 4 alt-data NULL upper-bound argument empirically robust to first-release vintage data.
- **K1268 GDELT** — FAIL_NO_DATA. GDELT 2.0 public bulk endpoint production-ready (864 files/3min, no auth) but yfinance 1m/5m limited to last 30/60 days — historical backtest periods (2020 COVID, 2024 Nikkei flash crash, 2023 SVB) all out of window. Honest FAIL framing; K1268b queued with paid data prereq.

### Systemic fixes (12+ commits)

1. **refill_task_pool 4-layer dedup** (commits 6e57b64b + 0503155e + a2f9b434):
   - audience=null legacy articles included in dedup set
   - candidate.covered_by direct honor
   - build_publication_candidates audiences_covered backfill (None → 'general')
2. **continue_task_dispatch is_paper_task exemptions** (commits 3f0eaa6d + 05e98ee5):
   - task_type=daily_article (K898/K904 had "[Paper 3 R1]" verdict_preview triggering)
   - task_type=paper_review (id `paper_review_mile_*` triggers `paper_` regex)
   - Effect: agentable 0 → 7 paper_reviews unblocked
3. **vix-sufficiency K1116d addendum** (commit 86ae71f7): integration_plan_v2 §publication-delay-robustness extended to 7 pieces (K1116/b/c/d + K1118 + K1121 + K504 + K1098).
4. **Paper 10 README backfill** (commit b2558f75): Status updated from "kickoff" → "Body drafted v5 — pre-review" (body_v5.tex 494 LoC + main.pdf 2026-04-28 + 14 % source K-bindings).
5. **taiwan-vt abstract sync** (commits 02b0ac14 + e707c232):
   - main.tex + main_v3.tex abstract OLD 0.729/0.796/-41.3/-18.4 → K1175 canonical 0.799/0.701/-33.8/-21.2
   - Supabase synced via upsert_paper_metadata
   - paper-update CLI feature: _count_tex_metrics now extracts abstract from main_v3.tex regex (止 future drift)
6. **error_log yfinance high-freq lesson** (commit 3478f4c6): yfinance 1m/5m 30/60-day lookback documented as backtest blocker; K1268b prereq.

### Closed K-id collision incidents

- K1175 (kid_collision Paper 2 Table 3 audit) → K1176 collision again (Paper 2 Table 4) → K1268 (free, GDELT scan).
- K637/K872/K729/K708/K711/K723/K1023 article tasks bulk-closed as audience-null-fix superseded (7 stale before they hit dedup_conflict round).

### Reviewer ecosystem state

Codex CLI 0.121.0 production-path proven 2026-04-28; daily quota fully consumed 2026-05-11 by K1035/K1040/K971/K980 reviews. Gemini CLI fallback exercised twice (K1035 K1040 PASS) + main-thread audit fallback exercised twice (K971 K980 CONDITIONAL PASS). Subagent fallback path remains untested this session (tool not surfaced).

### Outstanding paper2 reproduce gate work (4 cat deferred)

- **Table 1 TWII summary stats** (4): TWII mean/std/skew/kurt — needs descriptive_stats experiment
- **Table 5 vt_common** (1 lumped): K1175 doesn't byte-match (1.108 paper vs 1.0742 K1175); needs dedicated 2020-2026 common-period strategy battery
- **Sec 6 macro** (2): K1179 verdict NO_MATCH (paper r=0.214 vs K1179 r=0.189, 11.7% rel diff); needs body revision OR re-run
- **Appendix TZ** (2): Taiwan c2c Sharpe 1.473 / TW+JP 50/50 Sharpe 1.810 — K1176 has 1.91 not 1.473 (different spec)
- **Sec 4.5 TSMC** (2): VT Sharpe 1.121 + 52.5% return variance — no clean JSON source
- **Sec 3 TWD/USD** (1): p=0.08 — K461 has FX as regressor but no Granger test extracted
- **Table 2 individual gamma** (3): Hon Hai 0.052/MediaTek 0.044/0056 0.112 — paper spec doesn't match any existing K (K1060 Hon Hai=0.105)

Each cat needs dedicated session work; not iterative one-cycle fixes.

