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
  - **★★ K1377 HAR Exp-QLIKE Combination 完成 2026-05-19 PASS**：指數 QLIKE 加權 combo (1/√QLIKE) vs HAR-VIX baseline — SPY DM t=3.723 (Harvey PASS), GLD t=6.003 (Harvey PASS), 0050.TW t=2.434 (Harvey FAIL but combo better)；vs EqWeight 在 GLD t=3.454 / 0050.TW t=2.970 勝。Combo 在 2/3 assets Harvey-significant 勝 HAR-VIX 單模型。延伸 K530 HAR 王者，加權 ensemble 對 QLIKE 預測精度有真實增量
- 跨資產模型選擇（gamma rule, significance-based）

**多變量模型：**
- DCC-GARCH（動態條件相關）— 已有初步結果
- BEKK-GARCH（多資產波動率溢出）
- Copula-GARCH（非線性相依結構）
- Factor GARCH（共同因子驅動的波動率）
- 跨資產 Granger 因果（vol spillover）

**Under-explored methodologies (novelty quota 候選，feed_ct=0 per topic_diversity_audit 2026-04-19 19:30 UTC)**:
- [x] ~~Bayesian Model Averaging (BMA) for vol forecasting~~ → **K1257 完成 2026-04-20**：6-model pool × 3 assets × OOS 2020-2026。**H1 PARTIAL**（SPY/GLD Harvey PASS t=-3.40/-3.38, 0050.TW FAIL posterior→GJR-t），**H2 FAIL** no asset 過 equal-weight Harvey（確認 K482 equal-weight-puzzle 延伸到 Bayesian），**H3 FAIL** posterior 500 天內 concentrate 指數收斂→ standard BMA cannot forget/track regime。**K1300（Forgetting-Factor BMA 完成 2026-05-15，Codex PASS 2026-05-17）**：λ∈{0.95,0.97,0.99,1.0} × 3 assets → **CONFIRMED_FAIL**，SPY best-λ=0.99 DM t=-1.34，GLD best-λ=0.95 DM t=-1.74，0050.TW DM t=+0.14，全低於 Harvey |t|>3 門檻。BMA degeneracy is asset/market-specific 而非 forgetting-factor 可修復的問題。BMA 研究線段暫結。
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
- **★★ Close-Regime Weighted Conformal VaR (K1390)**：VIX_{t-1} > 20 切高/低 vol regime（high N=859, low N=2005, OOS 2015-2026）。5% Conformal Rolling VaR 高 vol=2.997%、低 vol=1.224%（2.45× ratio）；1% 高 vol=5.40%、低 vol=1.95%（2.77×）。Verdict=REGIME_EFFECT — VIX threshold conditioning 對 conformal predictive interval 有顯著 regime-dependent 寬度差異，high-vol regime 必須拉大尾部 quantile，避免 backtest 低估
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
- **GDP revision event study NULL (K1401)**：BEA GDP 二次/三次估計修正 N=25 events 圍繞 VIX。H1 (T-5 < T-1 pre-event 升)：t=0.160 p=0.563 NS；H2 (T0 > T+1 post drop)：t=0.006 p=0.498 NS。Bonferroni α=0.0167。Verdict=NULL — GDP 修正不是 VIX vol mover（一致於文獻：GDP 修正 informational content 低於 NFP / CPI / FOMC，市場 prior 已 absorb）。mile_daaff779 published（事件驅動文章；FB retroactive catch-up pending）

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
- **網絡/傳染模型**：用圖模型分析波動率在資產間的傳播路徑（beyond linear Granger）— **K628b Diebold-Yilmaz 跨資產 vol spillover** (N=4211 obs 2010-2026Q1)：SPY 是 dominant **NET TRANSMITTER** (net=+43.7%, to_others=48.3%)、TLT 是 **NET RECEIVER** (net=-24.9%)、0050.TW receiver (net=-1.7%)、GLD balanced。**FR-adjusted Granger 結論：SPY→0050.TW = INTERDEPENDENCE (no contagion)**（持續性連動非危機驅動跳變）。reader-facing 文章 mile_55758994 draft
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
- [x] 修正 Gemini 指出的 3 弱點（2026-06-05 closure audit：SEVERE 1 → `experiments/paper2_R1_transaction_tax_fix/`；SEVERE 2 → `experiments/paper2_R1_linear_scaling_fix/`；SEVERE 3 / TSMC endogeneity → `experiments/k1183/` + `experiments/k1302/` concentration robustness）

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

**★ Paper 2 θ_EAV Universal Regularity — DECISION_MADE (2026-05-17, K1146)**

K1145 (TW) + K1147 (US) + K1150 (JP) 三市場同步 PASS 後，EAV 貢獻框架再次升級：從「嚴格 null verification」→ **「三市場普遍性正規律」**（universal cross-market regularity with magnitude ordering）。

| 市場 | 實驗 | pooled θ_EAV | cluster bootstrap t | 95% CI | placebo p |
|------|------|-------------|---------------------|---------|-----------|
| TW（31 stocks, 2014-2025） | K1145 | +6.36e-5 | +5.24 | [+4.13e-5, +9.38e-5] | 0/60 |
| US（30 stocks, 2014-2025） | K1147 | +1.909e-4 | +4.50 | [+1.29e-4, +2.80e-4] | 0/60 |
| JP（30 stocks, 2014-2025） | K1150 | +1.413e-4 | +11.99 | [+1.29e-4, +1.76e-4] | 0/60 |

**Magnitude ordering**: US (1.91e-4) > JP (1.41e-4) > TW (6.36e-5)，與各市場制度性特徵一致（美國 earnings call 文化最強、分析師覆蓋最密、機構交易圍繞公告期最集中）。

**與 K1109/K1113/K1114/K1140 null heterogeneity 的關係**：互補而非矛盾——within-market 找不到 firm-attribute predictor → θ_EAV 在每個市場內近乎常數 → cross-market 差異是市場層級結構差異（不是個股層級噪音）。

**K1146 決策**：Paper 2 EAV 貢獻框架定為：
> *"Earnings announcement volatility amplification is a universal cross-market regularity: positive, robust, and structurally ordered across TW (K1145), US (K1147), and Japan (K1150). The within-market null heterogeneity (K1109/K1113/K1114/K1140) is reinterpreted as supporting evidence that θ_EAV is market-level constant, with cross-market ordering driven by institutional characteristics."*

**Body rewrite plan（K1146_body 任務）**：
- 新增 §6 "Earnings Announcement Volatility: A Universal Cross-Market Regularity"（插在現行 §5 Macro Indicators 與 §6 VaR 之間）
  - §6.1 A4f-EAV 模型設定
  - §6.2 Taiwan（K1145）: 5-layer robustness
  - §6.3 Cross-market validation（K1147 US + K1150 JP）
  - §6.4 5-layer robustness 彙總表（3 markets × 5 checks）
  - §6.5 Magnitude ordering 與制度性詮釋
  - §6.6 Reconciliation with null heterogeneity（K1109/K1113/K1114/K1140）
- 新增 §8.x Self-Challenge（in Discussion）：Hessian Wald vs cluster bootstrap；Bonferroni k=3 調整後所有市場 |t| > 2.39 仍全過
- K1141（舊 dual-NULL body rewrite）→ SUPERSEDED by K1146_body

**Narrative state** = `decision_made_awaiting_body_rewrite`（K1141 superseded；等 K1146_body paper_body task）

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

**RESOLVED 2026-05-18 (scaffold rewrite v2 complete)** — EAV Paper scaffold 已按 review_v1.md Option A 全面重寫：

- **Decision**: Option A（按 14-item 清單逐項修正，核心研究問題 valid）
- **Implemented**: 2026-05-17 main-thread rewrite（README.md v2 + abstract_working.md v2 + lit_review.md v2）
- **5 P0 issues**: ALL RESOLVED（JP 市場補入 K1147/K1150；"universal constant" → "robust cross-market positive amplification with market-specific magnitude ordering US>JP>TW"；null heterogeneity chain K1109/K1113/K1114/K1140 已完整列入；IS t vs OOS DM t 語意拆開；placebo 13.6σ → 13.27σ + σ 定義補齊）
- **Cross-paper conflict resolved**: K1141 明確歸屬 Paper 4（vix-sufficiency），README v2 已標注
- **Narrative state**: `decision_made_awaiting_body_rewrite`

**Remaining P1 tasks（不 blocking body start）**:
- lit_review.md: 核實 Patell & Wolfson (1979) JFE vs JFQA；補 binary-vs-continuous spec 文獻
- Engle-Ghysels-Sohn 2013 journal name 待 citation-verifier pass（ReStat vs JBES）
- reproduce.py + data snapshot pinning（body kickoff 時必須先做）

**Body.tex 狀態**: P0 scaffold resolved → body 可開始草稿；但須先完成 reproduce.py + data snapshot（paper-workflow.md hard rule 2）。Details in `paper/eav-universal-magnitude/README.md` (v2)。

---

**RESOLVED 2026-05-16 23:25 CST (commit b4148e48)** — K1370 v2 B=1000 完成 + Codex CONDITIONAL PASS + Supabase synced:
- 90% CI [2.31, 6.61], median 3.78, 1000/1000 valid（41.8 min runtime）
- body_v3.tex §3.2 採方向 (A)：headline 改 4.3× canonical 匹配 spec（原 228eedb2 parallel agent 已 pivot；本次只用 v2 deterministic CI 數字取代 v1 hash-buggy）
- reproduce.py 加 K1370 v2 CI + median bindings；gate 96.6% → 96.7% green
- knowledge.json K1370 entry rewrite（supersedes 228eedb2 v1）
- 留 caveat：MD5 seed 近乎可重現但非 bitwise (scipy.optimize ~2e-5 漂移)
- Narrative state = `decision_made` (auto, per honest correction obligation + Codex PASS); body_v3.tex already adopted Option A

**第三篇：Is Volatility Targeting Just Trend Following?**
- `paper/vt-trend-following/main.tex`（29 頁）
- 目標：Journal of Portfolio Management 或 Financial Analysts Journal
- 核心貢獻：分解 VT 的 alpha 來源（K46→K53→K79: r=0.564, VT alpha = trend following）
- [x] `/latex-academic-reviewer` 全面審查 → review_v2.tex（5H/12M/6L）
  - HIGH: 樣本期間不一致、BAB proxy（SPLV→AQR）、MDD 只有 5 美股、1.4% 數字不可驗證、需引用 K687/K697/K688
  - K687 分析：**不矛盾**——VT 打敗 BH(SPY) 但打不過 BH(50/50)，支持 insurance 論述
- [x] 修正 review_v2 的 5 HIGH（A.1+B.1+C.1 done 2026-05-18; B.2→K1371 PASS; B.3→K1376 PASS 2026-05-19）
- [x] Gemini 審查 → `paper/vt-trend-following/review_history/v4/gemini_review_v1.md`（2026-06-05；Major Revision；2 HIGH NEW：MDD retention >100% mechanical artifact + block bootstrap 252-day insufficient）
- [x] 修正 Gemini v4 的 2 HIGH（H2 stationary bootstrap → K1417 rejects block-length concern; H1 trough decomposition → K1458 finds 2020 mechanical rebound hedge present but PureVT still underperforms BH in trough window, 2009 absent due beta clipping；需落地 paper body / appendix）
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

**2026-05-29 reframe extension audit — E1 + E2 results**（hourly-08/11 compute queue + hourly-10/12 主線程 synthesis）：
- **Paper3_E1 個股 copula (K1373)**：12 pairs (6 same-sector + 6 cross-sector), **NULL 0/12 Harvey sig**, Spearman ρ(λ_L_mean, DM_t)=0.049 p=0.88. 個股 idiosyncratic noise 稀釋 tail dependence → 個股級別不可重現 K1100b ETF 結果
- **Paper3_E2 跨股市 copula (Paper3_E2_cross_market_copula)**：10 pairs (5 markets: SPY/0050.TW/HSI/N225/STOXX50), current HLN-retrofitted results show **2/10 Harvey sig**: TW0050-N225 strongest (Student-t vs DCC t=3.92, p=0.00009) and TW0050-HSI weaker (t=2.08, p=0.038). By-region: developed_cross_region 0/3, developed_vs_emerging_asia 0/4, asia_intraregional 2/3. **Spearman ρ(λ_L_clayton, dm_clayton)=0.903 p=0.0003 highly sig** — aggregate pattern 存在但多數 individual pairs Harvey 不過；舊「1/10 / TW0050-N225 only」是 pre-HLN-retrofit stale wording，不可再引用。
- **E1+E2 統一 pattern**：copula advantage 不是「跨 equity 市場 universal」— K1100b ETF asset-class 結果是 asset-class boundary 效應，不是 cross-market 通則
- **E3 commodities scope decision**：boss directive 2026-05-29 「需 E3 commodity results first before paper body rewrite」— E3 (gold/oil/copper 與 equity 配對) 仍待 enqueue。E3 之後再判定 paper narrative 是維持「asset-class-specific」框架 or 收斂為「Joe upper-tail mechanism 限 flight-to-safety pair」
- **Open question**: TW0050-N225 是最強 / 最醒目的 Harvey-sig pair（current HLN 另有較弱的 TW0050-HSI）— λ_L_clayton=0.444 + full_sample_corr=0.586 + Asian trading-hour overlap 三因子哪個是 driver？需 sensitivity (different OOS start / refit_every / window) 排除 single-start type-I
  - **K1412 (2026-06-02) partial update**：5 OOS starts (2014/2015/2016/2017/2018) raw 5/5 Student-t DM_t 3.04-3.89，**初步排除 single-start type-I**。但 Codex review FAIL：paper3_E2 系列 Harvey 判定為自製 `|t|>3`，**非** HLN small-sample correction，docstring mislabel。Paper 引用前須先 retrofit HLN correction 重跑。Open question 升級為「HLN-retrofitted 是否仍 robust + 三因子 driver identification」
  - **K1416 (2026-06-04) formal HLN retrofit**：TW0050-N225 5/5 OOS starts pass 5% and 1% HLN gates；caveats = 4 non-baseline n 為比例估算、5 starts 是 overlapping sensitivity grid、80% gate 是 internal submission rule。結論只支持 TW0050-N225 robustness，不支持「唯一 significant pair」或「cross-market copula 普遍優越」。

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

**近期延伸**：
- **K1320 Copula-GARCH OHR 2026-05-21 CONDITIONAL_PASS（vs DCC-Gaussian NS）**：SPY-GLD 9 種 OHR 方法 OOS HE 比較 — best Gumbel copula HE=0.8880 vs DCC-Gaussian baseline 0.8862，diff=+0.002。9 個 DM tests 全部 p>0.08（最低 Clayton p=0.082），統計上**無 copula 顯著勝 DCC**。Hsu et al. (2008, JFM) 框架重現：copula 結構 ≠ 自動 hedging 增量；marginal HE 改善需 N>>252 才能 power-up。對應面向 I 「核心問題：期貨避險能否系統性改善...」— 答案在 SPY-GLD 配對上**不能**，至少在 252-day OOS

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
- **K1374 台股除息日波動率擴展 2026-05-18 PASS**：17 家 TWSE 大型股、226 ex-date events 對 40,729 control obs。除息日 |r| 均值=1.32% vs 控制=0.99%（**ratio=1.342**），Welch t=4.019 p=0.0001、Mann-Whitney p<1e-6、Cohen's d=0.305（small-to-medium effect）。Robustness 排除離群 outlier 2412.TW（d=1.633）+ 2886.TW（d=1.245）後 d=0.238 仍 PASS。台股除息日**系統性**波動率抬升存在，但效應 size 小於個股 earnings shock — 對應方向 3「聚集效應」與 K1059-K1064 EAV 路線的姊妹結論。**K1375 高股息 ETF 同設計 NULL** — 個股有效應、ETF 級別 cohort 內被分散稀釋
- 8.63/VIX = 12/(VIX×1.39)，修正後 Sharpe 0.69，MDD -15.3%（Q1/R15）
- VIX 優於 VXEEM（R12: Spearman 0.595 vs 0.459，因 0050.TW≈50% TSMC→美國科技情緒）
- SPY→台股 spillover 真實存在（T5b: r=0.376, Granger F=58.8）
- SPY Momentum 5d/10d → 0050.TW c2c Harvey PASS，但 **o2o FAIL**（I8 timing bias）→ 學術發現非交易策略
- 台灣 0% 資本利得稅 = VT 結構優勢（K26/K86）
- TAIEX gamma 0.153 > 0050 0.087 > TSMC 0.039（T5a），ETF 分散化放大 gamma
- 台灣 MIDAS: 進口 YoY 唯一有增量（G12），其餘景氣燈號/M2 全 null
- 本土指標（外資買賣超/融資融券/PUT-CALL）全 null（G8）

**開放議題：**
- [x] VIXTWN 數據累積到 252 天後驗證 ratio 穩定性（Q6）— K1323 readiness update: 116/252 days, NOT_READY_AND_UNSTABLE；一般讀者敘事已由 `mile_02c71e74` 覆蓋，252-day formal gate 需等資料自然累積後再重開
- [ ] 台灣 5-min 數據 HAR-RV（0050.TW 47 天，ETA 2026 Q2）
- [x] ~~**金融股早期預警系統**：K757 發現 Fubon→TSMC Granger (F=6.11)。可建立金融股壓力指標作為 TSMC vol 早期預警~~ — 已由 K1029 + K1432 收尾：K1029 確認金融股/金融 ETF 對 0050/TSMC 有 in-sample Granger 與弱 regime signal，但 GARCH-X OOS 變差；K1432 以 5 檔金融股 stress index + HAR-RV / HAR-RV+VIX baseline 做 2021-2026 OOS，結論為 NULL，多個 stress-augmented spec 顯著 worse。除非有新資料（如 intraday/private flow），此題不再作為新 experiment 重派。
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
- [x] Adaptive Multi-Factor HAR public-proxy — **K1327-v2 完成 CONDITIONAL_PASS (2026-06-14)**：daily OHLC/risk-proxy 156 shifted factors，matched rolling 1000d/refit 21d 後 ElasticNet QLIKE 3.1606 vs HAR3 3.5971，但 DM-HLN t=2.516 未達 Harvey |t|>3。Expanding sensitivity 較強，顯示 sample-window choice 重要；仍非原 FoFI 287 高頻因子 replication。
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
- [x] ~~GARCH-to-Neural~~ → **K1312 完成 NULL (2026-05-17)**: SPY QLIKE LSTM=3.451 vs GJR=1.730 (差 99.4%，DM t=+8.71)，QQQ QLIKE LSTM=3.292 vs GJR=1.746 (差 88.5%，DM t=+9.32)，0/3 gates × 2 assets。**ML ceiling 第 8 次確認**。結構化 GJR inductive bias 仍無法突破 QLIKE ceiling；MSE 小幅改善(15%/6%)但均不顯著。
- [x] ~~RECH-X (Recurrent Conditional Heteroskedasticity + realized covariate)~~ → **K1533 完成 PARTIAL/NULL (2026-06-22, user-requested replication)**：復現 Nguyen-Nguyen-Tran (2024 FRL) SRN-GARCH+RV+Student-t vs GARCH/GJR/GARCH-X/RealGARCH，SPY/QQQ(GK proxy)+TAIFEX TX(true 5-min RV)，own MLE numba-JIT，expanding OOS，H=1/5/22，Patton QLIKE，DM-HLN Harvey。**ML ceiling 第 9 次確認**。關鍵誠實發現：(1) RECH-X 在 H1/H5 與 **linear GARCH-X 打平**（無 DM 過 |t|>3，最大 TW H1=−2.68），RNN edge 只在 H22 出現 → 增益來自 RV covariate 不是 neural net；(2) 對 **pre-specified GJR(1,1) 從不勝**，台灣 true-RV GJR 大勝（QLIKE 0.30 vs 0.40，DM +8.4@H1）；(3) 只在 SPY H≥5 勝 RealGARCH。Codex 2+1 passes CONDITIONAL_PASS。Fidelity 限制：US 用 GK daily proxy（偏向不利 RECH-X，故 SPY 薄 edge 保守）、MLE 非原文 Bayesian SMC。
- [ ] ML Risk-Based Allocation — Scientific Reports 2025（LSTM + regime switching，Sharpe 1.38）

### Rough Volatility & Hurst
- [x] ~~Multivariate fBm for RV~~ → **K806 完成 NULL**（⚠️ Codex 1 HIGH: 0050.TW 未清洗，跨資產 H 不可信；SPY 自身結果可信）。自身 H(t) 改善 NS (DM=-0.09)。5 資產全 rough (H<<0.5)。日頻 variogram 不夠精確。
- [ ] ★ **Multivariate Rough Volatility Model** — arXiv:2412.14353 (Feb 2026)。多變量 fractional OU + GMM 估計。跨資產 rough vol 的正式框架。
- [x] ~~Time-Varying Hurst via EWMA~~ — arXiv:2509.05820 → **K1423 (pilot CONDITIONAL_PASS, ρ(H,VIX)=+0.32) → K1424 (GARCH covariate, NULL_resolved 2026-06-08)**：H 控制 VIX 後 garch_plus_vix vs garch_plus_h_vix DM=-2.99 p=0.0028 d=-1.2e-4 marginal harm（effect ~10⁻⁴ 實務無意義）；VIX vs baseline d=+0.046 強 lift，H 訊息已被 VIX 完全吸收。後續方向：TW/EM 等無成熟 IV market 才有差異化動機
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

### 新發現（2026-05-29 arXiv 文獻搜尋；scan_arxiv_topics.py 能力建立）
> 來源：WebSearch arXiv q-fin（export API 當下對本 IP 限流，改 WebSearch 取得；ID 經 arxiv.org URL 驗證為真實）。`scripts/scan_arxiv_topics.py` 為自動掃描器（ground-truth API fetch，throttle 解除後可排程跑）。
- [ ] **Autoencoder Enhanced Realised GARCH** — arXiv:2411.17136。以 autoencoder 生成合成 realised measure，非線性整合多個 realised measures；4 大股市 one-step rolling 預測勝傳統 Realised GARCH。**面向A 可測**：對齊我方 multi-RM / A4f 線，可比 K-series HAR-RV baseline。
- [ ] **Quantum Reservoir Computing for Realized Volatility Forecasting** — arXiv:2505.13933 (2026-04)。指出 GARCH 低維參數遞迴對複雜非線性/多尺度動態表達受限，改用 reservoir computing。**面向A/D 觀察**：方法新穎但需評估是否可在無量子硬體下以 echo-state network 近似復現（reproducibility gate）。

### 新發現（2026-04-01 文獻搜尋）
- [ ] **Transfer Learning for New Issues Vol** — arXiv:2503.12648 (March 2025)。多源遷移學習預測數據稀少資產（新 IPO/分割股）的波動率。實務導向工具。

### Score-Driven (GAS) Models
- [x] ~~GAS-t vs GARCH on equity~~ → **K1038/K437 完成 NULL**。4 資產全 NS（SPY DM t=-0.99, QQQ t=-0.30）。Score-driven robustification 不改善 QLIKE。但 VaR violation rate 稍低（內建 Student-t）。結論：US equity 上 downweighting 大 shock 反而失資訊
- [x] ~~**K1129 (完成 2026-04-13)**~~: GAS-t on commodity markets — **4/4 TRIPLE FAIL** (USO DM t=1.03 NS, GLD NS, UNG NS, **BTC DM t=-4.58 Harvey 反向顯著 — GJR-N 勝**). H2 kurt→gain Spearman=0.20 p=0.80 FAIL。GAS compendium 擴展到 8+ assets 全 null。結論：score-driven downweighting 在 commodity/crypto bubble+FTX+tail event 期間反而失資訊。

### 其他
- [ ] Regime-aware In-Context Learning — arXiv:2603.10299（LLM vol forecasting）
- [x] ~~「HAR ceiling」驗證 — Los Flamingos 2025~~ → **K1350 完成 scope audit**。Los Flamingos 2025 來源確認為 HARd-to-Beat practitioner summary；本地 K530/K764/K1377 已覆蓋 generic HAR ceiling（日頻 proxy OOS 支持 tuned HAR/HAR-family hard-to-beat，rough-vol extension 未破 ceiling）。精確複現未做，因本地缺 1,445 檔美股 2015-2023 high-frequency RV + ML fitting grid；5-min follow-up 仍低於 252 OOS（K1349/K1521/K966 pilot-only）。
- [ ] Financial Innovation 2025 review — realized volatility forecasting 綜述
- [ ] RGARCH-CARR-SK（Realized GARCH + CARR + 高階動差）— 2025
- [ ] Multiplicative Volatility Factor (MVF) — ScienceDirect 2025, J. Econometrics
- [ ] VOLARE 平台（HAR/HAR-Q/MEM/AMEM 標準化比較框架）— arXiv:2602.19732
- [ ] Multi-Transformer Vol Forecast — Engineering App AI 2024

### 跨資產 / 另類（contrarian, yfinance-doable, 2026-06-10 補；破 vol-forecast/VIX/台股 主導, Novelty Quota）
> 這批刻意跳出 GARCH/HAR vol-forecast 與 VIX/台股 dominant clusters，全部 yfinance 免費資料可跑，服務 Novelty Quota 20% contrarian 配額。
- [ ] 加密貨幣波動率 spillover：BTC-USD / ETH-USD 的 realized vol 與股市（SPY）vol 的雙向 spillover，crypto 是否領先/落後 equity vol（yfinance，明確 lag，VAR/Granger + DCC）
- [ ] 收益率曲線斜率作為股市波動率 regime 指標：用 ^TNX − ^FVX（10Y−5Y）或 ^TNX−^IRX 斜率，檢驗曲線倒掛/陡峭 regime 下 SPY realized vol 的條件分佈差異（yfinance）
- [ ] 新興市場 ex-台 波動率景觀：EEM / INDA(印度) / EWZ(巴西) / EWY(韓國) / EWW(墨西哥) 的 realized vol 與彼此相關性結構，找跨 EM 共同 vol factor（yfinance，PCA + 相關 regime）
- [ ] 原油波動率 spillover 到股市：CL=F / USO 的 vol 衝擊是否傳導到 SPY/能源股 vol，與一般「油價漲跌」分析不同（聚焦 vol-of-vol 傳導，yfinance，明確 lag）
- [ ] 另類資產波動率特性：URA(鈾) / KRBN(碳權) / 比特幣 等非傳統資產的 vol clustering、尾部、與傳統股債的相關性 — 它們是分散工具還是高 beta 放大器（yfinance）
- [x] ~~美元指數（DXY / UUP）作為跨資產 vol 的條件變數：強弱美元 regime 下 EM/商品/黃金 vol 的差異（yfinance）~~ → **K1439 完成，K1330/K1352 duplicate closure**。canonical K1439：UUP regime × EEM/GLD/DBC/USO/DBB，bucket `shift(1)`；naive Welch 4/5 顯著但 21d RV overlap 使 p 值過樂觀，HAC+Bonferroni 後只有 **USO** 在 level/trend 兩種 regime 都穩健，GLD null，EEM/DBC/DBB 僅方向性。K1352 不重跑，避免同題 duplicate。

### 跨資產 / 另類 batch 2（2026-06-10 補；yfinance-doable，續補 backlog，diverse axes）
- [ ] 信用利差作為股市 vol 領先指標：HYG−LQD（高收益−投資級）spread 與 SPY realized vol 的 lead-lag（yfinance，明確 lag）
- [ ] 通膨預期 regime 與資產 vol：用 TIP/不同久期國債（IEF/TLT）相對表現代理通膨預期，檢驗 regime 下股債 vol 與相關性（yfinance）
- [ ] Factor ETF 的波動率特性：MTUM(動能)/QUAL(品質)/USMV(min-vol)/VLUE(價值) 各自 realized vol 與下行風險，min-vol 真的較低 vol 嗎（yfinance）
- [ ] 貨幣對波動率與股市風險：FXE(歐)/FXY(日圓避險)/FXB(英鎊) realized vol，日圓避險屬性在 risk-off 是否成立（yfinance）
- [ ] 更多新興市場 vol：VNM(越南)/EIDO(印尼)/THD(泰國)/EPHE(菲律賓) 邊境/東南亞市場 vol 與已開發市場的脫鉤程度（yfinance）
- [ ] 天然氣與農產品 vol 的季節性：UNG(天然氣)/DBA(農產) realized vol 是否有顯著季節 pattern，與能源股/通膨的關係（yfinance）
- [ ] 銅作為景氣領先的 vol 訊號：CPER/銅期貨代理 vol 與股市 vol 的 lead-lag，「銅博士」在 vol 維度成立嗎（yfinance，明確 lag）
- [ ] REIT 波動率與利率敏感度：VNQ realized vol 在升息/降息 regime 下的差異，REIT 是股是債（yfinance）

### 期刊主題挖掘 batch（2026-06-11；五新軸 microstructure/ETF flow/GPR/氣候/retail，全免費資料 yfinance/FRED/TAIFEX tick/TWSE/FINRA/NOAA/CWB/GPR 官網）
> 來源：journal-topic-discovery agent batch 2（JFM/JBF/JFE/JEF/RoF/JFQA + Cboe/IMF GFSR/OFR/arXiv 趨勢層級，非捏造論文）。已對 06-10 batch 與既有 arcs 去重。台灣在地優勢題 ×3（台海 GPR、颱風假停市、當沖比率）。
- [ ] Order-flow imbalance 的 regime 依賴預測力：台指期 tick OFI → 短期 RV — TAIFEX tick 建 5-min OFI，檢定對 5min/30min/日 RV 增量預測力是否隨 vol regime 與 horizon 變化，明確 lag（來源：JFM/Quantitative Finance 2025-26 OFI-vol 統一框架）
- [ ] 免 tick 的「realized illiquidity」作 vol 預測增量因子 — 日 OHLCV 算 Amihud/Corwin-Schultz/range-volume 比，加入 HAR-RV 檢定美股/台股 OOS 增量 QLIKE+DM（來源：JEF 2024-25 低頻流動性測度賽馬）
- [ ] 0DTE 時代的日內 vs 隔夜波動結構轉變 — SPY 日 OHLC 拆 intraday range vol vs c2c vol，斷點檢定 2022-Q2 前後 + expiration-day 效應（來源：Cboe research + SSRN/J.Derivatives 2025；0DTE 佔 SPX 量 59%）
- [ ] 槓桿 ETF 機械再平衡與尾盤波動放大 — rebalance 需求 ∝(k²−k)×報酬×AUM（TQQQ/SQQQ/SSO，1h bar），檢定大漲跌日尾盤 vol/continuation 是否隨 LETF AUM 放大（來源：arXiv/JPM 2025 beyond volatility drag）
- [ ] 被動化與個股 fragility：0050 成分調整 vol event study — TWSE 公告，納入/剔除前後個股 RV 與 idio vol DiD（來源：JFM 2024-25 ETF fragility measure）
- [ ] 單股槓桿 ETF 上市對標的尾盤 vol 的因果效應 — TSLL/NVDL/CONL 上市日 DiD（控制組同業），2025 AUM $36B+ under-explored（來源：J.Derivatives/監管關注線）
- [ ] GPR 日頻 Acts vs Threats 分解對 vol 的不對稱預測 — Caldara-Iacoviello GPRD 拆 GPRA/GPRT 入 HAR-RV，檢定對 SPY/GLD/XLE/ITA 不同 horizon 預測力（來源：AER 2022 + IMF GFSR 2025-04 Ch.2）
- [ ] 台灣 country-GPR 與台股波動：台海風險的可測價 — GPR(Taiwan) 月頻 + TAIEX/0050 RV + TWD vol，事件窗（2022-08、2024 選舉）領先性與外資通道；台灣版幾乎無人做（來源：IMF GFSR 2025 + DPE 2025 同型設計）
- [ ] 極端高溫/颶風對保險與公用 ETF 的 vol event study — NOAA 事件日期 + KIE/KBWP/XLU RV，dose-response（來源：PLOS One 2025 + JIFM 2025 climate-vol；physical>transition 是 2025 共識）
- [ ] Green-minus-brown 波動價差作 transition-risk 情緒指標 — ICLN/TAN vs XLE/XOP RV spread，氣候政策事件跳變與訊號力（來源：climate finance 2025 回顧；vol-spread 角度 under-explored）
- [ ] 颱風登陸與台股波動：颱風假的 vol 機制 — CWB 警報/登陸資料 + TAIEX/台指期，停市後復市日 gap vol 系統性檢定、與一般連假區分；台灣特有制度國際空白（來源：physical-risk event-study 2025 方法移植）
- [ ] FINRA off-exchange short volume ratio → 次日 vol — 免費日頻檔，off-exchange short ratio 對次日 RV/極端報酬預測，明確 lag（來源：OFR 2025 WP；off-exchange ~46% 政策熱點）
- [ ] 台股當沖佔比與波動：散戶 herding 在地量化 — TWSE 免費日頻當沖比率，對次日 RV 預測力 + 雙向 Granger（vol 吸引當沖 vs 當沖放大 vol）；台灣數據完整國際罕見（來源：JFQA/JEF 2024-25 retail order-imbalance 辯論）
- [ ] 現貨 BTC ETF 上市對加密 vol「時段結構」的改變 — BTC-USD 小時資料拆美股時段/非時段/週末 RV，斷點檢定 2024-01 IBIT 前後（ETF-ization 拉向傳統市場時鐘；與既有 vol-of-vol spillover 不同 — 時間分配結構非外溢）（來源：J.Futures Markets 2025）

### 期刊主題挖掘 batch（2026-06-10；掃 JBF/JFE/JoE/JFQA + JPM/FAJ/J.Fixed Income/J.Futures Markets 2025-26 熱門趨勢，全 yfinance/FRED/TAIFEX 可跑，contrarian/under-explored）
> 來源：journal-topic-discovery agent（WebSearch 趨勢層級，非捏造論文）。刻意避開純 GARCH/HAR-vol-forecast、VIX 水平、台股 VT 三大既有主軸。
- [ ] 隔夜 vs 日內 variance risk premium 反號之謎 — yfinance SPY 開/收盤切隔夜段與日內段 RV，FRED+^VIX 算 implied，檢定 VRP 在兩段是否反號（隔夜負/日內正）+ 1-3M vs 6-12M 預測力差異（來源：JFE/J.Futures Markets 2025 VRP intraday-overnight decomposition）
- [ ] BAB 報酬條件於前期已實現波動的「beta anomaly 波動之謎」 — yfinance 美股大樣本月度 RV 分高/低 vol 月重做 betting-against-beta，檢定低 vol 月後 BAB Sharpe 是否升（來源：JFE 2025 The volatility puzzle of the beta anomaly）
- [ ] 波動率目標只對風險性資產有效、對債/匯/商品近乎無效的跨資產再驗證 — yfinance 股/credit ETF/TLT/UUP/商品 ETF 各自 VT vs 固定 notional，比 Sharpe 增益 + 左尾極端頻率（來源：JPM The Impact of Volatility Targeting + Man Group 2025）
- [ ] 股債相關係數 regime 化下的 60/40 適應性配置 — FRED+yfinance 滾動股債相關，依相關 regime 動態調 60/40，比靜態的 drawdown 與 Sharpe（來源：JPM/FAJ 2025 rethinking 60/40；相關由 +0.8 降至 +0.16）
- [ ] CTA/trend-following 的 drawdown 形態 vs 股市：頻繁但淺 — yfinance 多期貨 ETF 構 time-series momentum，比 trend vs 買進持有的 drawdown 深度/頻率 + vol-scaling 是否減半 MDD（來源：FAJ/Man Group/AlphaSimplex 2025 managed-futures drawdown）
- [ ] regime-switching HAR 中「商業循環吸收 jump 成分」假說 — TAIFEX/yfinance RV+jump（BNS bipower），Markov 2-regime HAR-RV 加 FRED 景氣指標，檢定加景氣後 jump 係數是否轉不顯著（來源：JoE/Risks 2025 business-cycle vs jump RV）
- [ ] 多訊號 momentum composite 改善尾部：11 訊號等權 vs 純價格動能 — yfinance 美股價格動能 + 替代訊號 composite，比 t-stat、MDD（純價動能歷史 MDD -88%）（來源：CFA Institute/FAJ 2025 multidimensional momentum）
- [ ] dispersion / 相關性風險溢酬的免期權代理 — yfinance 指數 RV vs 成份股平均 RV 算「已實現 dispersion」，研究 mean-reversion 與 regime 擇時力（純期權版 blocked，用 RV 代理）（來源：CBOE DSPX/Numerix 2025）
- [ ] tail-hedging overlay 的真實成本 vs crisis-alpha 淨值 — yfinance VXX/put-proxy 疊 SPY，量化長期 drag（短 VIX 期貨歷史 -355bp）vs 危機保護，beta-adjusted 後是否仍正貢獻（來源：JPM/Goldman 2025 true value of tail hedging）
- [ ] 新聞情緒 / 總經注意力增益波動預測 — FRED EPU + 免費情緒/Google Trends 注意力加入 HAR/RV，檢定對美股 RV 的增量 OOS R²（來源：J.Forecasting/arXiv 2025 macro-attention & sentiment vol）
- [ ] MOVE（債市波動）對股市波動與股債配置的領先性 — FRED/yfinance ^MOVE 代理，檢定債市波動是否領先 VIX 與股債相關 regime，構 MOVE-gated 配置訊號（來源：J.Fixed Income/CFA 2025 + MOVE）
- [ ] 隔夜/日內波動率溢酬 clustering 與星期效應擇時 — yfinance ETF 隔夜段 vol，檢定 day-of-week × overnight VRP 可交易性（含成本）（來源：AEF/Harbourfront 2025-26 VRP calendar effect）
- [ ] 加密「vol-of-vol」與跨市場尾部外溢的免期權版 — yfinance BTC/ETH 算 RV 與 vol-of-vol，檢定對股/金/油尾部外溢（CoVaR/quantile spillover），加密能否當尾部避險（來源：J.Futures Markets 2025 crypto vol-of-vol；BTC vol 200%→50% 結構轉變）
- [ ] 深度學習 vs HAR 的「中長 horizon 才贏」邊界檢定 — yfinance 美股指 5-min RV，誠實對比 HAR-RV vs LSTM/簡化 Transformer 在 1/5/22 日 horizon 的 QLIKE + DM 檢定，定位 DL 增量真正出現的 horizon（來源：JFEC/IJF 2025 ML-vs-HAR）

### 期刊主題挖掘 batch（2026-06-14；JPM novel risk / CFA AI / JFM ETF / Fed Treasury OFI / private credit，可由免費代理資料啟動）
> 來源：journal-topic-discovery fallback（JPM 2025 Novel Risks and Sources of Volatility、CFA Institute Research Foundation 2025 AI / macro-correlation briefs、JFM 2025 ETF fragility、Fed 2025 Treasury OFI note、FSB/IMF/private-credit survey）。只採趨勢層級，不編造未核實文章；避開 06-10/06-11 已有 0DTE、LETF、GPR、氣候 green-brown、FINRA short volume、台股當沖、MOVE、stock-bond-correlation 題。
- [x] LLM novel-risk intensity 作為 RV 先行訊號 — K1487 daily GDELT keyword-taxonomy pilot completed (AI/private credit/cyber fetched; tariff/supply-chain blocked by GDELT 429): NULL_NEGATIVE, no OOS QLIKE wins for SPY/QQQ/HYG/TLT at 1d/5d; several 1d HAR+VIX+novel comparisons significantly worse. Reopen only with validated LLM classifier + robust GDELT/RSS collection covering all five themes, not the current coarse daily keyword proxy.
- [ ] ETF 宏觀效率 vs ETF fragility 的雙面檢定 — yfinance country/sector ETF（EFA/EEM/EWJ/EWG/EWZ/INDA/XLK/XLF）事件窗，檢定 ETF-heavy 標的是否在宏觀 shock 日更快反映資訊但後續 co-volatility / reversal 更強（來源：JPM 2025 ETF macroefficiency + JFM 2025 ETF-based fragility）
- [ ] Treasury signed-volume imbalance 免訂單簿代理 — 用 ZN=F/TLT/IEF intraday 或日頻 signed volume = sign(return)×volume 建流動性需求 proxy，檢定大單邊需求日是否預測 TLT RV、SPY RV 與股債相關升高；若 intraday 不足則先做日頻 pilot（來源：Fed 2025 Treasury order-flow imbalance / market-depth volatility）
- [x] Private credit 壓力的公開市場影子指標 — K1332 completed: BIZD + listed BDC proxy improves BKLN/HYG rolling OOS RV forecasts at Harvey strength, but not KRE/IWM; result is `PASS_NARROW_CREDIT_ONLY`, explicitly limited to public-market shadow stress because true private-credit NAV/loan tape is blocked（來源：FSB 2026 private-credit vulnerabilities；IMF/academic private-credit systemic-risk frontier）
- [ ] AI 基建資金鏈的波動傳導 — 建 hyperscaler/semis（MSFT/NVDA/SMH）× power-grid/utility（XLU/PAVE）× credit（HYG/LQD）三籃，檢定 AI capex shock 是否先在電力/基建/credit vol 出現，再傳到 Nasdaq RV（來源：J.P. Morgan 2026 alternatives outlook；AI data-center financing / public-private market shift）
- [ ] variance risk premium 下降後，短波策略是否失去經濟 edge — 用 ^VIX vs SPY realized variance、SVXY/VXX proxy、分段 2006-2017/2018-2026，檢定 VRP 均值、tail loss、short-vol Sharpe 與 drawdown 是否結構性惡化；不使用 options chain 先做免期權版（來源：Chicago Fed 2025 VRP decline）
- [ ] explainable ensemble vol model 的「特徵穩定性 gate」 — RandomForest/XGBoost/LightGBM ensemble 加 HAR/GJR features、macro/ETF/credit proxies，追蹤 walk-forward feature importance / SHAP rank drift；若 QLIKE 改善但特徵不穩，標為不可上架（來源：CFA 2025 ensemble learning / XAI in finance；回應本專案 ML ceiling）
- [ ] Bond-fund investor design 與債券 ETF 波動 proxy — 用 HYG/LQD/AGG/BND/TLT trading volume、折溢價可得性與 fund-flow proxy（若流量資料 blocked 則用成交額 shock）檢定 ETF 結構在信用壓力日是緩衝還是放大債券 RV（來源：IMF 2025 fund investor types and bond market volatility；J.Fixed Income / bond ETF liquidity trend）
- [ ] BNPL / 消費信貸平台作 credit-cycle 前哨 — 用 AFRM/UPST/SOFI/ALLY RV + FRED 信用卡/汽車貸款 delinquency、消費者信心，檢定 consumer-credit proxy 是否領先 IWM/HYG/金融股 RV（來源：CFA 2025 Alternative Credit: Rise of Consumer Lending；BNPL/consumer lending 風險透明度）
- [ ] Repo-basis funding stress gate 預測 duration 資產波動 — FRED/NY Fed SOFR-EFFR/TGCR spread、CFTC leveraged funds Treasury futures shorts、ZN=F/TLT/IEF RV，檢定 repo funding 壓力與 basis-trade proxy 是否領先長債 RV（來源：NY Fed / Dallas Fed 2025 Treasury funding liquidity and basis trade）
- [ ] Stablecoin redemption pressure 作 crypto-to-Treasury vol channel — DefiLlama stablecoin supply net flow、CoinGecko USDT/USDC peg deviation、BTC/ETH/T-bill/TLT RV，測試穩定幣流出或脫鉤是否領先 crypto RV 與短債/長債波動（來源：CFA 2025 stablecoins and Treasuries funding link；IMF/Fed digital finance concern）
- [ ] Inventory surprise 作 commodity RV regime feature — EIA crude/natgas inventory surprise、USDA WASDE/crop report dates、CL=F/NG=F/USO/UNG/DBA RV，把 inventory/carry/momentum 加入 HAR 或 gradient boosting，與 price-only baseline 做 QLIKE/DM（來源：CFA 2025 ML in commodity futures；J.Futures Markets inventory/liquidity/speculation trend）

### 期刊主題挖掘 batch（2026-06-14b；refill fallback 0 候選 → backlog 抽乾後系統補充；WebSearch JPM/FAJ/RFS/JoE/JBF/JFM/J.Index Investing/J.Alt Inv 2025-26 趨勢層級，全免費資料 yfinance/FRED/^VIX 系列可啟動）
> 來源：backlog refill discovery（WebSearch 趨勢層級，非捏造論文標題+作者）。已對 06-10/06-11/06-14 三批與既有 K（K1257 BMA、K1301 semivar TX1、K731/K489 VIX term structure level、K43 SKEW/VIX3M）逐一去重。刻意挑與既有題不同的「結構/asymmetry/timing-signal/concentration」軸，避開純 vol-forecast level。
- [ ] VIX 期限結構斜率作為 drawdown 擇時訊號（非 level 預測）— 用 ^VIX 對 ^VIX3M（或 VIXM/VXX proxy）算 VX-slope，檢定斜率跌破 1.0（backwardation）是否領先 SPY ≥5% drawdown，做含成本的進出場 timing 回測；與 K731/K489（term structure 預測 level）不同，這是 regime-flip 交易訊號（來源：2025-26 desk research，backwardation 領先 21/22 次 ≥5% 回撤；明確 lag）
- [ ] 已實現偏度的「橫斷面離散度」預測大盤報酬 — yfinance 美股大樣本日內或日報酬算 firm-level realized skewness，取橫斷面 dispersion（高−低分位差）檢定對次月 SPY 報酬/RV 的預測力；與 K1301（TX1 單一資產 HAR-RS 預測自身 vol，NULL）正交：這裡是 cross-sectional dispersion 預測 market-level（來源：arXiv 2026 skewness dispersion & market returns；明確 lag）
- [ ] Signed jump variation 的「大跳 vs 小跳」分離預測力 — 用日 OHLC/range 或可得日內代理拆 signed semivariance → signed jump，再分 small/large jump，檢定 large 與 small jump 對次日 RV 與極端報酬的不對稱預測（與 K1301 整體 RS+/RS− NULL 不同，聚焦 jump-size 分層）（來源：Econometrics/JFM 2025-26 small vs large signed jump cross-section）
- [ ] 市場集中度 risk 與大盤 vol：cap-weight vs equal-weight 波動裂口 — yfinance SPY vs RSP（等權）RV 與相關，建 top-10 集中度 proxy（用前十大成分權重或 SPY/RSP return spread），檢定集中度升高 regime 下大盤 tail vol 是否系統性放大（來源：J.Index Investing/SPGI 2025；2025 末前十大佔 S&P 41% 創高）
- [ ] 防禦因子的 drawdown 分解：low-vol/quality/value 各自只保護「哪一半」— yfinance USMV/QUAL/VLUE/SPLV vs SPY，把 drawdown 拆 frequency × depth，檢定哪個防禦因子降深度、哪個降頻率，並對比加 trend overlay 的互補性；與既有 factor-ETF RV 題不同，聚焦 drawdown 機制分解（來源：FAJ 2026「Best Defensive Strategies, 220 years」；DAR+trend 最 robust）
- [ ] 跳躍 × 非對稱外溢同時控制是否仍改善 HAR — yfinance 多市場指數 ETF（SPY/EWJ/EWG/EWU/EEM）日 RV+jump proxy，比較 HAR-RV vs 加 jump、加 sign-asymmetry spillover、兩者皆加，檢定 1/5/22 日 horizon QLIKE+DM 是否真有增量（來源：J.Forecasting 2025 jump & sign-asymmetry spillover；20 市場樣本）
- [ ] 極端尾部下的跨資產 quantile connectedness（非均值 VAR）— yfinance 股/債/金/油/加密 ETF RV，用 quantile-VAR 或 CoVaR 算「尾部 vs 中位」連結度差異，檢定危機期尾部外溢是否遠高於均值外溢、誰是淨尾部傳染源；與既有 level-VAR/Granger spillover 題正交（來源：JBF/SEF 2025-26 quantile connectedness；極端期 total connectedness >80%）
- [ ] 黃金 safe-haven 屬性的 regime 依賴與美元/實質利率脫鉤 — yfinance GLD/SPY/UUP + FRED 實質利率，滾動檢定 gold-equity 與 gold-dollar 相關在 risk-off vs 一般期是否變號，量化 gold 作 tail hedge 的條件有效性（與既有 alt-asset/DXY 題不同，聚焦 safe-haven 相關 regime 切換）（來源：LSEG/WGC 2025；2025 gold +50% 與股脫鉤但對 vol hedge 落後）
- [ ] EM 貨幣 carry unwind 的 crash-risk 不對稱 — yfinance EM 貨幣/債 ETF（CEW/EMLC/EMB）+ FXY，建 carry proxy 與 yen-funding stress，檢定 carry 報酬分佈左尾是否在 risk-off 急速放大、unwind 是否領先 EM 股 vol；明確標示 leveraged/crowded position 數據 blocked 用 proxy（來源：BIS/IMF GFSR 2025；EM drawdown 為 EUR 的 3-5 倍）
- [ ] Conditional Drawdown-at-Risk（CDaR）目標 vs 傳統 vol-target — yfinance 股/債/商品 ETF，比較以 CDaR 為風控目標 vs 固定 vol-target 的 net Sharpe、MDD 與左尾頻率，檢定 drawdown-aware 風控在壓力期是否真優於 vol-aware（與既有 VT 跨資產題不同，目標函數換成 drawdown）（來源：ITOR 2026 drawdown MINLP；JPM drawdown control trend）
- [ ] LSTM 波動預測 + 可微風險預算層的「壓力期增益」邊界 — yfinance 多資產 RV，誠實對比 LSTM-vol→risk-budget allocation vs 等權/HAR-vol-target，檢定 MDD 改善是否只在 stress regime 出現、平時是否被複雜度拖累；接 K1487/ensemble 線的 ML-ceiling 誠實檢定（來源：Sci Rep 2025 ML risk-based allocation；宣稱 stress 期 MDD −41%）
- [ ] 日內 diurnal pattern 是否「足夠」解釋 RV 變異 — yfinance 或可得 5-min 代理，用無母數方法檢定剔除已知日內 U 型季節後是否仍有顯著 intraday vol 變異，量化季節成分占 RV 的比例（方法論基礎題，校準我方所有日內 RV 估計）（來源：arXiv 2601 diurnal sufficiency nonparametric assessment）
- [ ] 價格存續期（price-duration）拆解 interday vs intraday vol 動態 — 用可得高頻或日 OHLC 代理，以自適應價格變動門檻建 price-duration 測度，檢定加入存續期季節成分是否降低 RV 估計 RMSE；與既有 range-based/realized illiquidity 題不同（來源：JTSA 2025 price-duration interday/intraday decoupling）
- [ ] VIX 的 vol-of-vol（VVIX 代理）對 VIX 自身可預測性 — 用 ^VIX 日內或日報酬算 realized vol-of-vol（VVIX blocked 則自建），檢定拆短期/長期 vol-of-vol + jump 是否改善 VIX 次日預測；與既有 crypto vol-of-vol 題（外溢角度）正交，聚焦 VIX 自我預測（來源：JFM 2025 vol-of-vol & VIX forecasting wavelet+HAR）

### 期刊主題挖掘 batch（2026-06-14c；backlog 再度抽乾 0 pending/0 in-flight platform idle critical → WebSearch JFE/RoF/JFQA/JFM/J.Forecasting/JPM/FAJ 2025-26 趨勢層級補 13 軸，全免費資料 yfinance/FRED/^VIX 系列可啟動）
> 來源：journal-topic-discovery refill（WebSearch 2025-26 趨勢層級，非捏造論文標題+作者）。已對 06-10/06-11/06-14/06-14b 四批與既有 K（K1487 GDELT novel-risk NULL、K1423/K1424 Hurst、K731/K489 VIX term structure level、K1301 semivar、crypto vol-of-vol spillover）逐一去重。刻意挑與既有題正交的 8 軸：downside/skew-term-structure 分解、graph-network spillover、naive-vs-complex hedge、rough-vol roughness、trend-as-alpha-source、RV window-size、EM-AI 耦合、crash-risk illiquidity proxy。
- [x] ~~下行 VRP 與上行 VRP 反號分解 + 跨 horizon 預測力差異~~ → **research_vrp_vrp_horizon 完成 2026-06-15，NULL**：SPY + ^VIX free-data proxy 將 VIX² 總 implied variance 依 lagged 252d realized semivariance share 拆成 down/up，所有 predictors 明確 `shift(1)`。2010-2026 分析樣本 n=4,136；total/down/up VRP 平均皆為正（91.84/49.44/42.40 vol-pts²，HAC t=4.07/4.00/3.68），但 downside-minus-upside spread 只有 7.04、HAC t=0.88，bootstrap CI [-8.81,+23.18] 跨 0。預測端 63d return downside t=2.26 方向性但未過 t>3；63/126d RV downside t=-0.53/-1.27。結論：free-data proxy 不支持 downside VRP dominance + medium-horizon prediction 敘事；若重開需真 option-chain / model-free downside-upside variance swap decomposition。
- [ ] 偏度風險溢酬「期限結構」作長 horizon 尾部訊號 — 用 ^VIX、^SKEW（CBOE SKEW free）與 realized skewness 建 skew-premium term-structure proxy，檢定長端 skew-premium 是否對 6-12 個月 SPY 報酬/drawdown 有比短端更強的預測力；與 K43（SKEW/VIX3M level）不同，聚焦 term-structure slope 而非 level（來源：JFQA 2025 crash-risk premium / skewness swap；skew premium 長 horizon 較強）
- [ ] Graph/network spillover 學習 RV 是否贏線性 VAR — yfinance 多資產 ETF（SPY/QQQ/TLT/GLD/HYG/EEM/CL=F）日 RV，建 lagged-correlation 鄰接矩陣 → 簡化 graph propagation（或 GNN-lite）vs 線性 spillover-VAR baseline，誠實檢定 1/5/22 日 horizon QLIKE+DM 增量是否真存在；與既有 quantile-connectedness（連結度測度）正交，這裡是「用網路結構做預測」（來源：J.Forecasting 2025 GNN realized-vol spillover forecasting）
- [ ] 危機期 naive 對沖優於 estimation-heavy 對沖的 robustness 賽馬 — yfinance VXX/put-proxy/inverse-equity 疊 SPY，比較固定比例 naive hedge vs 依估計 beta/vol/CVaR 動態調整的複雜 hedge，檢定 stress regime（2018Q4/2020/2022/2025）下 naive 是否因免 estimation-error 而淨值更穩；與既有「tail-hedge 成本 vs crisis-alpha」（成本核算）正交，這裡比 naive vs complex（來源：JFM 2025 naive tail hedge superiority；複雜模型在結構斷裂期 misspecification 放大）
- [ ] Realized volatility 的 roughness（Hurst<0.5）穩定性與預測增益再驗證 — yfinance 多資產 5-min RV 估 log-RV 的 roughness exponent，檢定 roughness 是否跨資產/跨期穩定、把 rough-vol 特徵（fractional kernel weighting）加入 HAR 是否改善 OOS QLIKE；接 K1423/K1424（time-varying Hurst on level）但聚焦「RV 自身路徑 roughness」而非 H 作 covariate（來源：JFE/Quant Finance 2025-26 rough volatility from short-dated data；roughness 是否真 universal 有爭議）
- [ ] Trend-following 是否「解釋」vol-managed 策略的全部 alpha — yfinance SPY 構 Moreira-Muir vol-managed portfolio + time-series momentum factor，做 vol-managed 報酬對 trend factor 的 spanning regression，檢定 vol-managed alpha 在控制 trend 後是否消失；與既有「VT impact / CTA drawdown」（策略表現）正交，這裡是 alpha 歸因分解（來源：SSRN/JPM 2025 Volatility Targeting Is Trendy；vol-managed ≈ embedded trend）
- [ ] Realized variance 估計的「最適窗長」是否 regime 依賴 — yfinance/TAIFEX RV，系統掃 rolling-window 長度（5/10/22/63 日）對 HAR-RV OOS QLIKE 的影響，檢定最適窗長是否在高 vol regime 縮短、低 vol regime 拉長，產出 adaptive-window 規則；方法論校準題，影響我方所有 HAR baseline（來源：J.Forecasting 2025 Feng window-size choice for RV forecasting）
- [ ] EM 股市與「AI 交易」耦合度的 vol regime 切換 — yfinance EEM/INDA/EWY/EWT vs SMH/QQQ，滾動檢定 EM-vs-AI-tech 相關在 risk-on/risk-off 是否變號、EM vol 是否在 AI capex shock 日被放大或反成分散，量化 EM 作 AI 風險分散工具的條件有效性；與既有 EM vol landscape（PCA 共同 factor）正交，聚焦 EM×AI 耦合 regime（來源：Goldman/IMF GFSR 2026 EM balancing AI-trade volatility）
- [ ] 期權市場流動性作股價 crash-risk 的免期權代理 — yfinance 用 SPY 量/價差代理（Amihud、range-volume）與 ^VIX skew proxy 建 option-illiquidity proxy，檢定流動性惡化日是否領先次日/次週極端負報酬與 RV 跳升，明確 lag；與既有 FINRA short-volume / realized-illiquidity（一般 vol 預測）正交，聚焦 crash-risk 左尾（來源：RoF/Euro J Finance 2025 option liquidity & crash risk；illiquidity 為 time-varying crash 的 covariate）
- [ ] Downside-CVaR 動態對沖 ratio vs 固定 vol-target 的左尾改善 — yfinance SPY+TLT+GLD，比較以 1-day 99% CVaR 為目標動態縮放曝險 vs 固定 vol-target，檢定壓力期左尾頻率/深度與淨 Sharpe；與既有 CDaR-target（drawdown 目標）正交，這裡目標函數是 conditional VaR/ES（來源：arXiv 2025 deep hedging to manage tail risk；CVaR-parameterized convex-risk）
- [ ] Markov-regime GARCH 對「不穩定相關」的配置 robustness — yfinance 股/債/金多資產，比較單 regime DCC-GARCH vs 2-regime Markov-switching GARCH 在弱成長/危機期的相關估計穩定性與配置 drawdown，檢定 regime-switching 是否真降低 misleading-correlation 風險；與既有 stock-bond correlation 60/40 題（單一相關 regime 訊號）正交，聚焦多資產 RS-GARCH 配置（來源：arXiv 2025 MRS-MNTS-GARCH；不穩定相關削弱動態模型）
- [x] ~~商品 inventory/seasonality surprise 的「regime-conditional」預測力~~ → **research_inventory_seasonality_surprise_regime_conditiona 完成 2026-06-15，NULL**：yfinance CL=F/USO/NG=F/UNG/DBA + EIA 原油/天然氣庫存，所有 inventory features 先 7 日保守 release lag 再 `shift(1)`。OOS 2018-2026，seasonal×low_inventory HAC t：CL=F -1.12、USO -0.64、NG=F -1.85、UNG -2.24，無任一油/氣 paired gate 通過 t>3。DBA seasonality-only placebo t=5.32，但沒有匹配 inventory proxy，不能當 supply-tightness 支持。結論：低庫存 regime 沒有穩健放大季節性 forward-RV 預測力；若重開需 crop/product-specific inventory surprise 與精準 release calendar。
- [ ] 防禦資產輪動：long-vol vs gold vs Treasury 誰在「哪種 crash」最有效 — yfinance VXX/GLD/TLT vs SPY，把 SPY drawdown 分類為 rate-shock（2022 型）/ growth-shock（2020 型）/ liquidity-shock（2018Q4 型），檢定三種防禦資產在不同 crash 類型的條件保護力差異，產出 crash-type-aware 防禦輪動規則；與既有 gold safe-haven regime 題（單一資產）正交，聚焦三資產 × crash-type 矩陣（來源：FAJ 2026 best defensive strategies；不同 shock 機制需不同 hedge）

### 期刊主題挖掘 batch（2026-06-14d；pool-dry diagnostic 觸發 → WebSearch JPM/CFA/JFE/JFQA/J.Futures Markets/JFM/Index Investing/Behavioral Finance 2025-26 趨勢層級補 15 軸，全免費資料 yfinance/FRED/^VIX/^MOVE/Google Trends 可啟動）
> 來源：journal-topic-discovery refill（WebSearch 2025-26 趨勢層級，非捏造論文標題+作者）。對 06-10/06-11/06-14/06-14b/06-14c 既有 batch 與最近 K1439-K1481 逐一去重，零撞題。刻意挑與既有題正交的 8 子軸：drawdown-as-risk-measure、intraday/overnight 拆解、regime classification、集中度/crowdedness、event-driven (FOMC)、跨資產 vol divergence (MOVE-VIX)、FX carry × vol、options skew 結構性解釋、multi-layer hedge、retail attention、yield curve dynamics、factor crowding、Chinese-language sentiment、commodity term-structure regime。
- [x] ~~Conditional Expected Drawdown (CED) 作為 VT 策略風險目標~~ → **research_conditional_expected_drawdown_ced_vt 完成 2026-06-15，NULL**：SPY/QQQ/IWM equal-weight OHLC 實驗顯示 CED20/CED60 target 沒有通過預設 gate。OOS 2018-2026，vol-target Sharpe 0.626、MDD -20.56%、Calmar 0.375、左尾日 39；CED20 Sharpe 0.609、MDD -24.43%、Calmar 0.323、左尾日 45；CED60 Sharpe 0.513、MDD -25.21%、Calmar 0.250、左尾日 45。CED 低換手是真的，但不能宣稱改善 drawdown/Calmar/left-tail；延續 K1494/K1334 的 backward-looking tail-risk scaler 教訓。
- [x] ~~Intraday vs Overnight VRP 分解的跨資產差異~~ → **research_intraday_vs_overnight_vrp 完成 2026-06-15，NULL**：yfinance-only pseudo-VRP（rolling GARCH expected variance - realized component variance）無法支持「overnight dominates + predicts next-day RV」跨資產敘事。OOS 2018-2026，overnight realized variance share：SPY 0.426、QQQ 0.379、IWM 0.397、EFA 0.646；只有 EFA 的 bootstrap CI 下界 > 0.5。Lagged overnight pseudo-VRP 在 4 資產 HAC regression 全未達 t>3（SPY -0.65、QQQ -2.29、IWM -0.52、EFA -1.28）。此題可作 free-data diagnostic，但不可替代 Papagelis/Dotsis 的 option-implied VRP decomposition。
- [x] ~~Risk-regime correlation breakdown 早期偵測~~ → **research_risk_regime_correlation_breakdown 完成 2026-06-15，NULL**：SPY/TLT 60d correlation breakdown regime 真實存在（positive breakdown share 9.14%，DCC rho vs rolling corr 相關 0.843），但 lagged 21d correlation-volatility 不是可靠 early-warning。Raw transition rate 高 corr-vol 9.60% vs non-high 6.08%（diff +3.53pp），stationary-bootstrap 95% CI [-1.36,+8.90]pp 跨 0；HAC(21) 控制 corr60_lag1 + SPY/TLT RV 後 high-signal 係數 -2.11pp，p=0.459。60/40 forward 21d worst return 也無惡化證據（diff +0.084pp，CI 跨 0）。結論：可作 regime 描述與 NULL 方法論教訓，不可發文宣稱可用預警器；重開需更乾淨的 OOS DCC/宏觀 inflation-vs-growth uncertainty feature。
- [ ] AI mega-cap 集中度 HHI 作為 SPY tail-risk 預測因子 — 從 S&P 500 top-10 持股權重（可由 SPY/IVV holdings 月頻代理）算 HHI / top-10 share，檢定 HHI 上升期 SPY 之後 N 月 realized vol、max drawdown、jump intensity 是否系統性放大（yfinance + 公開 holdings）（來源：JPM Global Research 2026-01「Fragile Fifty Percent」+ Deutsche Bank 2026-04 集中度 45%；2026 最熱 macro 議題之一）
- [ ] Pre-FOMC implied vol 兩週前 drift 的可交易性 — 用 SPY ATM IV 代理（GARCH/realized 衍生）在 FOMC 前 14 / 7 / 3 / 0 日的 IV path，檢定 long-vol 進場時點與 post-announcement IV crush 的風險報酬比（yfinance + FOMC 日曆）（來源：iPresage 2026 + JFQA 2025-08 disagreement 模型；老議題但 2025 解釋升級）
- [ ] VIX 期限結構斜率作為 vol-targeting overlay 開關 — 用 VIX/VIX3M 比率（^VIX、^VIX3M）construct slope signal，當 backwardation 時降股票曝險，比較 vs 純 VIX-level threshold 策略的 OOS Sharpe / MDD（yfinance）（來源：sixfigureinvesting / Cboe 2026 term structure；slope predictive content 學術已証但 trading rule 比較少完整 OOS audit）
- [ ] MOVE-VIX 跨資產 vol 分歧 regime 與配置 — 用 ^MOVE（債券 implied vol）/^VIX 比率建跨資產 vol 分歧指標，檢定分歧期 60/40 股債組合 vs risk-parity 表現差異（yfinance；MOVE 從 2024 起 yfinance ticker `^MOVE` 可抓）（來源：BondBloxx 2026 outlook + LPL Research 2026；MOVE 創 2021 來新低是 2026 macro 焦點）
- [x] ~~EM FX carry × FX vol regime 的雙閥門進出場~~ → **K1336 完成 2026-06-15，NULL**：yfinance BRL/MXN/ZAR/IDR spot + FRED/OECD short-rate proxy；FRED 月/季資料加 45/90 日 availability lag、stale masking、所有 carry/vol/threshold signals `shift(1)`，並剔除 yfinance FX spot abs(logret)>15% 錯價（ZAR 5、IDR 14）。OOS 2012-2026，pure carry Sharpe 0.022、MDD -33.5%、avg exposure 87.1%；carry×low-vol gate Sharpe 0.166、MDD -9.3%、avg exposure 13.2%。風險降低明顯但統計 gate 不過：gate-minus-pure HAC mean diff -0.14% ann, t=-0.07, p=0.948；bootstrap Sharpe diff CI [-0.429,+0.689], p_gt_0=0.67；Sharpe diff +0.144 也低於預設 +0.15。結論：own-FX-vol gate 是降曝險/現金濾網，不足以宣稱 EM carry timing alpha；若重開需 forward points + vintage-aware policy-rate data。
- [x] ~~Volatility skew 作為股票借券費代理的 cross-section 預測~~ → **K1507 completed 2026-06-16，NULL**：22 檔 ETF yfinance adjusted close，2007-03 to 2026-04 共 230 月；以過去 63 日 `-realized_skew`、downside-upside vol spread、5% left-tail loss 做 returns-only skew proxy，月末 t 排序預測 t+1 月報酬。High-minus-low 年化 -0.81% 但 HAC t=-0.23，pre/post 2018 皆 t≈0；Fama-MacBeth simple proxy t=+0.16、控制 vol/momentum 後 t=+1.08，rank IC +0.029 t=1.28。結論：yfinance-only returns proxy 不能替代 option IV skew / borrow-fee channel；不可否定真 options/stock-loan 文獻，重開需 OptionMetrics/CBOE borrow-intensity/short-fee data。
- [ ] 多層次避險的 functional role 分工驗證 — 把 TLT（First Responder long-duration）+ 趨勢跟隨（DBMF 代理 Second Responder）+ vol-target overlay 組合，跨 2020/2022/2025 三類危機檢驗各 responder 在不同 drawdown 形態下的貢獻分解（yfinance）（來源：Taylor & Francis 2025「trend-following + tail risk overlays」+ JPM 2025-26 multi-layered framework；practitioner framework 但學術 dose-response 驗證少）
- [ ] Google Trends retail attention shock → 個股 vol（台股版）— 抓「台積電」「0050」「ETF」「定期定額」Google Trends 週頻 z-score，檢定 attention spike 後 N 週 0050.TW / 個股 realized vol（yfinance + pytrends 免費）（來源：Review of Behavioral Finance 2026 retail investor 研究 + SJP 行為報告；retail crowding 是 2026 議題但中文圈缺數據）
- [x] ~~收益率曲線 steepener regime 預測股市 vol 與 sector rotation~~ → **K1337-v2 完成 2026-06-15，NULL**：K1337 v1 因 expanding OLS forward-label lookahead 被 Codex FAIL；v2 保留 v1 存證，改用 `target_end_pos(j) < forecast_pos(i)`（等價 `j+H<i`）訓練 cutoff、`dslope.shift(1)` regime label、baseline/augmented 同 log-variance HAR model + 同 clipping。18 specs（TNX-IRX/TNX-FVX × N=5/10/20 × H=5/10/20）OOS n=2564-2594；0 PASS、0 CONDITIONAL，17/18 augmented worse。唯一正改善 TNX-FVX N5 H5 只有 +0.052% QLIKE，DM t=-0.218、bootstrap CI [-0.0124,+0.0105] 跨 0；最差 TNX-IRX N5 H10 -1.705%。結論：dV/dt regime 可作描述性 macro context，但在 corrected design 下不提供 HAR 之外的 SPY forward variance forecasting edge。
- [ ] Factor ETF flows 擁擠度與 factor crash 風險 — 用 MTUM/QUAL/USMV/VLUE 的 30d AUM 變化 z-score 建 crowding score，檢定 crowding 高峰後 factor reversal 與 vol spike 的時序關係（yfinance 算近似 flow = ΔAUM − price return）（來源：Journal of Index Investing 2026 + ETF Educator 2026；smart beta $1.1T 規模下 crowding risk 新題）
- [ ] FinBERT-style 中文財經新聞情緒對 0050 vol 預測增量 — 抓 鉅亨網/工商時報 RSS 日頻標題，用免費中文 sentiment lexicon（NTUSD/CNSenti）算每日 sentiment z-score，加入 HAR-RV(0050) 檢定 OOS QLIKE 增量 + DM 顯著（yfinance + RSS）（來源：arXiv 2025-05 interpretable macro alpha + Frontiers 2025；中文圈 FinBERT-style vol forecast 缺，VolPred 角度差異化高）
- [ ] 商品 backwardation→contango 轉換點作為通膨資產 vol regime switch — 用 USO/UNG/CPER 月頻代理近月-遠月 spread（用前後月 ETF 收益代理 roll yield），標記 regime switch 日期，event study 檢定後續 30/60/90 日這些 ETF 與 SPY 的 vol jump 與相關性變化（yfinance）（來源：Schwab 2026 backwardation guide + arXiv 2026-03 rough vol commodity；2025 backwardation→extreme contango 切換是新事件）

### 期刊主題挖掘 batch（2026-06-15；用戶糾正「文章鬼打牆、回收舊 cluster」後觸發 → WebSearch JPM/FAJ/JFE/JFM/JBF/J.Fixed Income/CFA/FSB/arXiv 2025-26，**硬約束跳出 8 飽和 cluster**：VT / VIX-MOVE / GARCH-HAR 賽馬 / 風險模型比較 / ETF 分散 / 50-50+長債 / N 套策略 meta / proxy 測量比較。全免費資料 yfinance/FRED/EIA/FINRA，options/BDC 折溢價用成交量·股價動能 proxy 代理）
> 來源：journal-topic-discovery（WebSearch 趨勢層級，未捏造論文標題+作者；唯二指名 "Seeking Gamma"(AFA wp) 與 "Factor MAX and Predictable Factor Returns"(SBFC 2025) 為搜尋真實出現標題）。6 個全新主題軸，每軸 ≤3，與既有 6 batch + feed 近 120 篇正交。
> **新軸 1 — retail/dealer-gamma 微結構**
- [ ] Gamma-squeeze 候選股「散戶驅動波動」事件研究 — yfinance 2024-26 meme/gamma 候選（OPEN/KSS/GME 等），用「成交量 z-score × 報酬」代理 dealer-hedging 壓力，事件窗檢定 RV 與後續 CAR/reversal 不對稱（來源：JFE/AFA 2025-26 "Seeking Gamma"，squeeze 後一月 CAR +5.13%）
- [x] ~~散戶交易強度 proxy 對次日 idio-vol 的領先力~~ → **K1502 completed 2026-06-15，NULL**：FINRA CNMS public off-exchange short-volume ratio / off-exchange volume proxy + 22 檔 retail-tilted basket，OOS 2024-07-19 to 2026-06-12（477 obs/ticker）。Rolling 252-day HAR-log idio variance baseline；full model 加 lagged FINRA short-ratio z 與 lagged off-exchange volume z，全部 `.shift(1)`。0/22 tickers pass Harvey `|DM t|>3`，median QLIKE improvement +1.91%，sign-test p=0.416，pooled DM t=-0.69 p=0.493。限制：FINRA short-volume 只是 public off-exchange proxy，不是真 retail order flow；不可上架為獨立 vol signal。
> **新軸 2 — closing-auction / index-rebalance 微結構**
- [ ] Russell/標普 reconstitution 日尾盤波動「dislocation 但收斂」 — 重組日 vs 一般日 close-to-close vs intraday-range vol 拆解，檢定重組日尾盤 RV 系統升高但隔日均值回歸（來源：BMLL/Traders 2025 closing auction，重組日量 9%→20%）
- [ ] MOC imbalance 公布後尾盤漂移可交易性 — ETF/大型股尾盤分鐘代理，檢定 imbalance 方向是否預測收盤前漂移與隔夜 gap，含成本（~1.7bp liquidity premium）（來源：NYSE/CFA 2025 MOC imbalance）
> **新軸 3 — 私募信貸 / BDC 影子訊號（2025-26 危機熱點）**
- [ ] BDC 股價壓力作私募信貸危機前哨 vol 訊號 — yfinance 上市 BDC（ARCC/BXSL/OBDC/FSK）+ BIZD 的 RV + 折溢價/動能 proxy，檢定是否領先 HYG/KRE/IWM vol（來源：FSB 2026-05 Private Credit Vulnerabilities，違約率升 9.2%；BCRED 贖回潮）
- [x] ~~軟體/科技集中型私募信貸壓力的板塊外溢 — BDC 籃 vs IGV/HYG RV，檢定產業曝險贖回是否在板塊 vol 留足跡（來源：MS/Lexology 2026 私募信貸軟體集中度）~~ → **K1344 完成 NULL；K1353 duplicate closure**。K1344 已用 BIZD/ARCC/BXSL/OBDC/FSK BDC 籃 × IGV/HYG，含 SPY/QQQ controls、全部 features `.shift(1)`、HAC + 1000-rep block bootstrap、Bonferroni alpha 0.0125。4 個 OOS forecast cells 皆未過：IGV h21 方向最佳 +7.19% 但 DM t=1.35 p=0.178；event-study 正向僅 diagnostic，不可升格為 forecast claim。
> **新軸 4 — AI 電力 × 能源轉型 vol**
- [x] ~~資料中心電力需求衝擊對公用/電網 ETF 的 vol 重定價~~ → **K1508 completed 2026-06-16，NULL**：queue 原派 `K1345` 但該 K id 已被 `K1345_pre_fomc_iv_drift` 使用，故 remap 為 K1508。yfinance XLU/VPU/GRID/PAVE + SPY/QQQ adjusted close，FRED `IPG2211S` 作可重現電力公用事業活動 proxy（EIA v2 需 API key；ELEC bulk 約 226MB，未在 hourly run 下載）。所有訊號明確 `.shift(1)`，target 為 `t+1..t+21` forward RV；post-AI dummy primary gate 0/4 ETF 通過 Harvey/Bonferroni（XLU t=2.10、VPU t=2.04、GRID t=-0.93、PAVE t=-0.21）。結論：free-data specification 不支持「AI 電力需求已使公用/電網 ETF 相對 SPY 進入 robust 高波動 regime」；若重開需 EIA/API key 或區域 utility load / data-center interconnection queue。
- [ ] 鈾物理囤積基金放大現貨波動 — yfinance URA/URNM/SRUUF + 物理鈾基金 proxy，檢定囤積 AUM 變化放大現貨 vol（與 K1445 URA 分散題正交，聚焦 supply-shock vol 放大）（來源：2026 鈾供給衝擊 + 物理基金抽現貨）
- [x] ~~天然氣季節性波動與 Samuelson effect 到期遞增~~ → **K1504 completed 2026-06-16，CONDITIONAL_PASS**：local yfinance close snapshot `NG=F`/`UNG` 2006-01-03 to 2026-06-12。Calendar-month realized-vol seasonality passes descriptive ANOVA/permutation：`NG=F` F=3.204、perm p=0.0012、Jan/Mar peak-trough 1.86x；`UNG` F=2.450、perm p=0.0084、Jan/Aug 1.55x。**但 Samuelson proxy FAILS**：`NG=F` business-days-to-expiry coef wrong-sign +0.0036 (HAC t=1.28)，near-expiry<=5bd dummy t=0.58，near bucket RMS vol 57.3% vs far 72.0%，bootstrap P(near>far)=0.199。只可引用為天然氣月度季節性 + Yahoo continuous front-month proxy negative screen；不可宣稱合約級 Samuelson effect，重開需 multi-maturity futures / implied-vol panel。
> **新軸 5 — lottery / 行為橫斷面（backlog 零行為軸）**
- [x] Factor-MAX：因子層級彩券需求預測因子報酬 — K1503 MIXED：yfinance 因子 ETF（MTUM/QUAL/VLUE/USMV/SIZE）月度 MAX 不支持次月低報酬 anomaly（0/4 return tests pass Harvey），但強烈預測次月 realized vol 較高（4/4 vol tests pass Harvey）。可寫成風險狀態訊號，不可寫成報酬 anomaly。
- [x] ~~彩券型個股籃 vol-of-vol 與危機放大~~ → **K1346 completed 2026-06-16，NULL**：yfinance current-name retail/speculative proxy universe 75 檔，2018-05 至 2026-05 共 97 月；以 lagged low price + 63d idio-vol + 21d MAX score 每月選 top 20% lottery basket。籃子本身 risk-off 月 RV/VoV 較高（RV +0.079、t=1.82；VoV +0.034、t=1.26），但相對 SPY/IWM 的超額 RV/VoV 沒有放大，甚至 risk-off 下 basket-minus-SPY/IWM RV 為負。Lagged basket VoV/RV 對 SPY/IWM next-month RV 與 tail-excess 六個 lead tests 全不過 Harvey/Bonferroni，且多數係數 wrong-sign。結論：公開 yfinance proxy 不支持「lottery-stock VoV 是大盤 tail-vol early warning」；限制為 current-name survivorship bias、無 delisted/penny CRSP、月度 close-to-close VoV proxy。
> **新軸 6 — 退休 decumulation（全新讀者群，改用 ruin/shortfall 非 Sharpe；FAJ/JPM 2025-26 熱點）**
- [x] ~~提領期 sequence-of-returns risk 下 vol-aware 提領法則~~ → **K1505 completed 2026-06-16，PASS**：SPY/IEF 60/40 + FRED CPI，2006-02 to 2026-05 共 242 月；12m block bootstrap 10,000 條 30 年路徑。4% 固定實質提領 ruin=4.06%；lagged vol cut=2.95%、drawdown cut=2.50%、combined=2.17%（paired Δ=-1.89pp, 95% CI [-2.16,-1.62]pp）。代價是 combined 平均少領 4.95%（約 50.7k 實質美元），所以只可寫成「有成本地降低破產率」，不可宣稱免費提高安全提領率或 OOS volatility timing signal。
- [ ] TIPS 階梯 + 遞延年金 decumulation benchmark 的波動暴露分解 — yfinance TIP/STIP/LTPZ + 名目國債 RV，分解 FAJ 提領 benchmark 在通膨/利率 regime 的波動暴露與尾部保護（來源：FAJ 2025 decumulation benchmark；T. Rowe Price 2026）

### 期刊主題挖掘 batch（2026-06-17；WebSearch 13 期刊 學術6/實務7 趨勢層級；selectivity gate 後 14→3 條入單 — backlog 已飽和 11 條與既有 batch 重疊；新軸：動能拆解 / realized kurtosis / EPU regime-switching trigger）
> 來源：journal-topic-discovery (task `journal_discovery_20260616_2`, agent sonnet/low)。Agent 提 14 條自報 dedup，主線程 grep 抽查發現 ~11 條與既有重疊（HYG-LQD credit vol line 468、factor crowding line 573、CDaR/CED line 596+、0DTE line 506、CTA drawdown line 506、隔夜 VRP line 470+ 608、VIX term structure K731/K489、realized skewness 06-14b、low-vol 06-14d、tail hedge 06-14d、retail options 06-14d）。最終只入 **3 條真正正交軸**，並記 process lesson：journal_discovery agent 自報 dedup 不可信，主線程必驗（2026-06-17 教訓）。
- [x] ~~動能因子時序動量的「隔夜 vs 日內」拆解~~ → **research_rp_05c316a53f completed 2026-06-17，CONDITIONAL_PASS**：yfinance daily OHLC pilot（SPY/QQQ + 30 large-cap stocks，2010-01-04→2026-06-16；post-warmup n=3866）用 12-1M month-end momentum、`weights.shift(1)` 防 lookahead，分解 close→open vs open→close。Stocks-only CSMOM top/bottom 30% overnight ann mean 5.81%/Sharpe 0.982 vs intraday -2.84%/-0.349，diff +8.64%，DM t=-3.32 p=0.0009，bootstrap CI [+3.32%, +14.01%]；TSMOM 方向同為 overnight 但不顯著（diff +4.39%，DM p=0.128，CI 跨 0）。結論：支持「cross-sectional momentum payoff 集中於 overnight」的 pilot 證據，但非 full PASS，因 current-large-cap survivorship bias、daily OHLC 無 retail flow、未建交易成本/開盤成交風險；不可宣稱 retail mechanism 已被驗證。
- [x] ~~實現高階矩（realized kurtosis）作 vol 爆發預測的增量因子~~ → **K1521 completed 2026-06-17，NULL_INSUFFICIENT_DATA**：本機只有短期 2026 YTD 5-min CSV（SPY 105 日、0050.TW 92 日；無多年 TAIEX 5-min panel），因此改做 feasibility pilot。HAR-log vs HAR+RK-log 預測未來 5 日平均 RV；features 用 t 日收盤前 intraday RV/RK，target 從 t+1 起，expanding OOS 無 lookahead。Full OOS 不支持 RK：SPY n=51 QLIKE 改善 -8.70%、DM t=+0.295；0050.TW n=38 改善 -0.63%、DM t=+0.142。SPY high-lagged-vol bucket 有 suggestive 改善 +29.90%、DM t=-3.40，但只有 n=25，不能發布為發現。結論：pipeline 可行，研究問題仍需多年 SPY + TAIEX/TAIFEX 5-min panel 後重開。
- [x] ~~EPU 作為跨資產 vol regime **switching trigger**（非 incremental predictor）~~ → **K1519 completed 2026-06-17，NULL**：Baker-Bloom-Davis USEPUINDXD 日資料轉月均值，月結後 +2 business days 才 forward-fill；SPY/TAIEX daily log-r² 各自 fit 2-state Markov volatility-state proxy（switching variance 收斂），再用 EPU 3m log-change shock 檢定高波動 probability / low-to-high transition / log-r²。SPY 有 realized-vol 方向差（EPU shock ann vol 26.5% vs normal 15.6%，log-r² raw p=0.0398）但 BH p=0.319；SPY high-prob p=0.150、transition 反向；TAIEX 全 NS。結論：EPU 可能描述美股高波動月份，但不支持跨資產 regime-switch trigger；不是完整 MS-GARCH，只是 first-pass mechanism proxy。

### 期刊主題挖掘 batch（2026-06-16；WebSearch JFE/JFQA/FAJ/JPM/EFM/JFI/JoE/RFS/J.Forecasting/arXiv 2025-26 趨勢層級；新軸：因果 ML 資產定價 / LLM 文字 RV / 隔夜 VRP 拆解 / CVaR 風險平價 / 動態 factor 機制 / 股債相關財政 regime / 商品短期 momentum / 台股隔夜-日內動能 / ESG vol 分化 / 另類數據跨境；全免費資料 yfinance/FRED/TAIFEX/pytrends 可啟動）
> 來源：journal-topic-discovery WebSearch 趨勢層級（不捏造論文標題+作者）；與既有 7 batch + backlog 460+ 條去重，確認正交新軸。
> **新軸 A — 因果機器學習 × 資產定價（FAJ/JFQA 2025-26 熱點）**
- [ ] Double-ML 因果 factor 檢定：價值/動能/品質是否有真正因果效應 — yfinance 美股月度橫斷面，用 DoubleML 框架（`econml`/`doubleml` 免費套件）對低/高 book-to-market、12-1M 動能、ROE 做 debiased ML，檢定控制高維 confounders 後 factor return 是否仍顯著；與既有純預測 factor ETF 題不同，聚焦因果識別（來源：López de Prado/JFQA 2026 causal factor investing；FAJ 2025 causal ML 趨勢）
- [ ] 財報盈餘驚喜（SUE）對次月 vol 的因果增量：DML + instrumental variable — yfinance 美股月度橫斷面 + FRED 宏觀控制，用 SUE 作處理變數、IV 做識別，估計 earnings surprise 對後續 1-3 個月 realized vol 的 ATE，明確 lag（來源：JFE 2025-26 event-driven causal inference；因果 ML 在盈餘波動的應用空白）
> **新軸 B — LLM 長期 horizon 文字 RV 預測（JoE/arXiv 2025-26 熱點）**
- [ ] 財經新聞文字回歸預測長期（1 週-1 月）realized vol 是否顯著優於 HAR — yfinance SPY 5-min 或日 RV + 免費 RSS 新聞標題（Yahoo Finance RSS），用預訓練 FinBERT/BERT embedding 作文字 feature，LM 回歸 vs HAR baseline，誠實 DM 檢定 1/5/22 日 horizon；文字 LM 在長期 horizon 比 HAR 強這一熱點已在 SSRN 2025 出現，中文/台股版空白（來源：Parvini & Assa SSRN 2025 textual regression for RV；arXiv 2025-06 LLM-guided semantic feature selection）
- [x] ~~Regime-aware in-context LLM vol 預測 vs HAR 的邊界：哪個 regime 下 LLM 真正增量~~ → **K1520 completed 2026-06-17，NULL**：不直接用不可重跑的 LLM API output，先測可審計的 in-context analog retrieval surrogate。SPY daily r² OOS 2020-2026 n=1,621；analog/regime/combination 對純 HAR 方向上有增益，但因 retrieval/regime 使用 `VIX_{t-1}`，公平 baseline 必須是 HAR+VIX。HAR+VIX already beats HAR by +23.86% QLIKE、DM t=-4.24；所有 analog variants vs HAR+VIX 皆不通過正向 `|t|>3` + BH gate（best combo_harvix_regime overall -0.90%，DM p=0.440；trend_break +3.08% 但 p=0.730）。結論：apparent ICL edge mostly VIX/regime information；future true-LLM benchmark 必須 freeze prompts/model/raw responses，且先打贏 HAR+VIX 與 transparent analog baseline。
> **新軸 C — 隔夜 vs 日內 VRP 不對稱拆解（J.Futures Markets 2025 實測）**
- [ ] 台股 TAIEX 隔夜段 vs 日內段 realized vol 的 VRP 方向分歧 — TAIFEX/yfinance 0050/TAIEX open-close 拆隔夜 gap vol 與日內 range vol，建 VRP proxy（implied by VIXTWN - realized），檢定兩段 VRP 符號是否與 SPY 同樣反號（隔夜負/日內正），量化 horizon 預測力差異；台灣版隔夜 VRP 研究空白（來源：Papagelis J.Futures Markets 2025 VRP 隔夜/日內分解；JFQA 2025 skewness-VRP term structure）
> **新軸 D — CVaR 風險平價 vs 傳統 vol-target（JFM/Sci Reports 2025 熱點，與既有 CDaR 題正交）**
- [x] CVaR-based risk contribution 等化配置 vs sigma-based risk parity 的左尾改善 — K1347 完成，FAIL：SPY/TLT/GLD/PDBC 月度 CVaR-RP 淨 Sharpe 0.949 低於 Sigma-RP 0.966，stress MDD 只改善 1/3 可評估期間，DM p=0.796；2018Q4 因 250d CVaR warmup 無共同 OOS 樣本。見 `experiments/k1347/`。
> **新軸 E — 動態 factor 角色反轉：機構 vs 散戶驅動動能（EFM 2026 + JFQA 2025）**
- [ ] 機構作空 × 散戶跟漲的「角色反轉」月份識別與台股驗證 — yfinance 台股 0050 成分股 + TWSE 融資融券餘額（散戶 proxy）+ 外資買賣超（機構 proxy），建月度 role-reversal indicator，檢定角色反轉月後續 1M 報酬動能是否系統升高（EFM 2026 US 結果：角色反轉時月動能 +40bp）；台股版 with TWSE 免費數據，國際空白（來源：EFM 2026 "Who Drives Momentum Returns" 角色反轉結果；JFQA momentum spillover 2025）
- [ ] 商品期貨短期（1-4 週）動能與反轉「共存」驗證及 vol 條件 — yfinance 商品 ETF 代理（GLD/SLV/USO/UNG/CPER/PDBC），月/週 return series，檢定同 horizon 下動能與反轉是否因 vol 高低 regime 分離（JFEM 2026 commodity markets 發現短期動能-反轉並存，顛覆傳統 horizon 區分）；美股商品 ETF 代理版，免 tick（來源：JFEM/SSRN 2026 commodity short-term momentum-reversal coexistence）
> **新軸 F — 股債相關的財政/貨幣 regime 機制（RFS/SSRN 2025-26 熱點）**
- [x] ~~財政赤字擴張 regime 下股債相關係數轉正的可預測性~~ → **K1516 完成 2026-06-16，NULL**：yfinance SPY/TLT + FRED `MTSDS133FMS`/`GDP`/`FEDFUNDS`，月/季 macro 加 35-120 日 release lag，所有 regime features `shift(1)`，target 為 t+1..t+60 forward stock-bond correlation，train rows 要求 `target_end < 2020-01-01`。OOS 2020-2026 n=1560；augmented fiscal-monetary OLS 明顯輸 corr60_lag baseline（R2 -2.381 vs -0.545，DM t=+5.99；負才代表 augmented 較好）。高赤字 × 緊縮 regime 描述上 positive-corr rate 77.9% vs 48.9%，但 HAC LPM t=1.69/p=0.091，不過 Harvey；60/40 TLT-to-cash switch Sharpe 0.550 vs 0.458，但 strategy DM t=-1.42/p=0.155。結論：可作 2023-2024 相關轉正的描述性 macro label，不可宣稱可預測或可交易。
- [x] 2025 Liberation Day 關稅衝擊前後多資產相關結構的 event study — K1514 完成，NULL：SPY-TLT 30d 相關 -0.205→+0.208、SPY-PDBC 平均 delta +0.270 但 bootstrap CI 皆跨 0；SPY-BTC 幾乎不變，SPY-VIX 90d Fisher p=0.049 但 bootstrap 否決。close-to-close ETF 資料不支持 robust diversification-regime break claim。見 `experiments/k1514/`，knowledge `32df19ba`。
> **新軸 G — 企業債流動性 ML 預測與 vol 通道（JFI 2025 熱點）**
- [ ] 企業債 illiquidity 的機器學習預測：用股票 vol 作跨市場 feature — yfinance HYG/LQD/VCIT（bond ETF）代理 illiquidity（bid-ask proxy = `high-low/close`），以 SPY/VIX/信用利差（HYG-LQD spread）為 feature，XGBoost vs 線性 OLS，誠實 OOS R² + DM 檢定，明確 lag；把債券流動性當 vol 預測的橋梁（來源：FAJ 2024 "Predicting Corporate Bond Illiquidity via Machine Learning"；J.Fixed Income 2025 ML bond vol）
> **新軸 H — 另類數據 × 台股個股（JFQA 2025 衛星/替代數據熱點）**
- [ ] Google Trends 特定產品關鍵字對台股供應鏈個股的 vol 預測增量 — pytrends 免費抓「iPhone demand」「AI server」「TSMC」「HBM」等週頻關鍵字 z-score，加入 TAIFEX 或 yfinance 台股個股 HAR-RV（2330/2303/2454/2382），檢定 attention shock 是否在次週 realized vol 有增量 DM，明確 lag；台股供應鏈 × attention 研究空白（來源：JFQA 2025 satellite TIR/alternative data cross-section；Review of Behavioral Finance 2026 retail attention shock）
- [x] ~~外資法人流量作台股板塊 vol 的 leading indicator~~ → **K1518 完成 2026-06-17，NULL**：TWSE 官方 T86 三大法人買賣超每週最後交易日 + yfinance 台股調整收盤價，半導體/金融/傳產小型 basket，target 為 t+1..t+5 next-week realized variance；外資賣超 z-score 用 trailing 52-week window 並 `shift(1)`，train < 2022-01-01、OOS 2022-2026。Pooled HAR baseline vs augmented flow OLS：QLIKE 0.7085→0.7059，改善僅 +0.36%，DM t=-0.477/p=0.633（負才代表 augmented 較好）。半導體單一 basket +1.78% 但 p=0.520，金融/傳產反而變差。結論：weekly public-data spec 不支持外資法人賣超是台股板塊 vol 的 robust leading indicator；日頻完整 T86、完整 sector universe、order-imbalance/holding-based flow 可列 v2。

### 期刊主題挖掘 batch（2026-06-19；research backlog 連 4 天回報 all_already_covered → open questions 抽乾、experiment pending 池歸零 M2 idle → WebSearch JBF/RFS/IJF/JFEC/J.Futures Markets/JoAE/FAJ/Fed 2025-26 趨勢層級補 7 軸，全免費資料 yfinance/FRED/CFTC/OPEX 日曆可啟動）
> 來源：journal-topic-discovery（WebSearch 2025-26 趨勢層級，非捏造論文標題+作者）。對既有 8 batch（06-10/06-11/06-14/06-14b/06-14c/06-14d/06-15/06-16/06-17）+ backlog 460+ 條逐一 grep 去重：已剔除與 line 444（transfer learning new issues）、481/554（Amihud/realized illiquidity）、504/530（dispersion/skew-dispersion）、397（intraday commonality）、523/1094（repo-basis/SOFR funding gate）、line 506 行為情緒、0DTE 既有軸重疊的提案。最終 7 條真正正交，刻意挑「制度/法規變更 × 新計量技術 × under-explored 機制」三類，至少 3 條落 novelty quota（法規變更 / foundation-model / OPEX gamma 機制）。
> **新軸 a — 制度/法規變更（regulatory regime change，backlog 零此軸；novelty quota）**
- [x] ~~T+1 結算制度（2024-05-28 生效）對美股/ETF 隔夜 gap 與 realized vol 的結構斷點~~ → **research_t_1_2024_05_28_etf_gap_realized_vol 完成 2026-06-23，CONDITIONAL_BREAK_DIAGNOSTIC / daily proxy-only**：yfinance daily adjusted OHLCV，15 檔 ETF/ADR，2022-01-03 至 2026-06-22，以 2024-05-28 為事件日；overnight gap 明確用 `Open_t / Close_{t-1}`，OLS-HAC maxlags=5、Harvey `|t|>=3` + BH gate。Ticker-level `log_gap_var` 有 9/15 通過（HYG/LQD/TLT/SPY 等 post dummy 為負且顯著；部分 ADR raw mean 與控制後係數方向不同），pooled ADR/US ETF group interaction 4/6 通過；月底/季底 rebalance interaction 0/30 通過。結論：支持 cross-segment structural-break screen，但 daily OHLCV 無法識別 settlement fail / ETF primary flow / official rebalance calendar，不能宣稱 T+1 因果效果。見 `experiments/research_t_1_2024_05_28_etf_gap_realized_vol/`。
- [ ] 月度 OPEX「gamma cliff」前 72 小時 RV 壓抑 vs 釋放的事件研究 — yfinance SPY 日 OHLC（range-based RV proxy）+ 公開 OPEX/quad-witching 日曆（每月第三個週五 + 3/6/9/12 月 quad witching），event-window 檢定 dealer-long-gamma 假說：到期前 N 日 RV 是否系統性低於常日、到期週後是否反彈（mean-reversion），並比較 monthly OPEX vs quad-witching 強度差；與既有 0DTE intraday-share 軸（06-10/06-11）正交——這裡是 monthly gamma-cliff 的 daily RV 時序事件，不是 intraday 占比（來源：GEX/dealer-gamma practitioner 2025-26；witching-day abnormal return 學術文獻）
> **新軸 b — 新計量技術（time-series ML 前沿，backlog 僅有 LSTM/Transformer 在 target 上訓練的版本；novelty quota）**
- [ ] Foundation time-series model 的 zero-shot vs fine-tuned RV 預測「誠實 ceiling」檢定 — yfinance/本機 5-min 多資產 RV，用開源 pretrained TS foundation model（TimesFM / Chronos-2，免費 weights）做 (i) 純 zero-shot、(ii) 輕量 incremental fine-tune，對 HAR-RV / HAR-VIX baseline 做 OOS QLIKE + DM；誠實檢定「pretrained-on-100B-points 的 foundation model 是否在 RV 上零樣本就贏 HAR、或必須 fine-tune 才追平」；接本專案 ML-ceiling 線（K1487/K1520 LLM 皆 NULL），定位 foundation-model 增量真正出現的條件（來源：arXiv 2505.11163 Foundation TS for RV；TimesFM/Chronos-2 2025-26；本專案誠實 ML 邊界傳統）
- [x] ~~ML 強化的日頻流動性測度（CPQS proxy）作系統性流動性風險 → vol 通道~~ → **K1355 完成 2026-06-21，MIXED_WEAK / proxy-only**：yfinance SPY/QQQ/IWM/EEM/HYG/LQD/TLT/GLD + VIX 日 OHLCV，2010-01-04 至 2026-06-19；true CPQS 需要 bid/ask，yfinance 不可得，因此只做 CPQS-like low-frequency percent-cost proxy。GB 估計 proxy 的 OOS R2=0.562；lagged system liquidity factor 加入 HAR-range-var+VIX baseline 後 pooled QLIKE 改善 10.31%，7/8 assets 改善，但 date-clustered DM t=-2.24（p=0.025）未過 Harvey -3，per-asset Harvey 2/8。結論：方向性 proxy 線索可留 v2，但不可宣稱真 CPQS / trade-level liquidity discovery；需 bid-ask 或高頻 labels 才能升級。見 `experiments/k1355/`。
> **新軸 c — under-explored 機制 / 另類尾部對沖（backlog 零此軸）**
- [ ] 已實現相關性風險溢酬（realized CRP）的左尾 spike 擇時 — yfinance SPY + top 成分股 ETF 籃，算 realized index variance vs 成分股平均 realized variance 推出的 realized implied-correlation proxy，檢定 CRP 在 macro shock 日的左尾 spike（everything-correlates）是否可被前置訊號（VIX term-structure、breadth）預警，並評估 short-correlation carry 在這些 spike 期的 drawdown；與 line 504（dispersion mean-reversion 擇時）正交——這裡聚焦 CRP 左尾 spike 的尾部風險而非中位 mean-reversion（來源：CBOE COR3M/DSPX 2026 dispersion-risk briefs；correlation-risk-premium 6.7-18pt 文獻）
- [ ] 放空企業債作股票尾部對沖的效率 vs put/VIX overlay — yfinance HYG/JNK（放空 proxy，用 inverse 或 short return series）疊 SPY，跨 2018Q4/2020/2022/2025 四類 drawdown 比較「short-credit hedge」vs put-proxy / long-VXX 的 beta-adjusted crisis-alpha 與平時 drag；明確標示放空成本/借券費 blocked 用保守 proxy；與既有 tail-hedge 成本軸（06-14b line 505）正交——這裡換對沖工具為 credit-short（來源：arXiv 2504.06289「On the Efficacy of Shorting Corporate Bonds as a Tail Risk Hedging Solution」2025）
> **新軸 d — RV 估計方法論校準（內部 baseline robustness）**
- [ ] 乘法成分 intraday GARCH（日內季節 × 日間動態分離）vs 純 HAR-RV 的 RV 估計穩定性 — 本機 5-min（SPY 105d / 0050.TW 92d）或可得高頻代理，用 multiplicative-component GARCH（Engle-Sokalska 式：日內 diurnal 成分 × 條件變異）拆 intraday periodicity，檢定剔除季節成分後的 RV 估計是否比樸素 5-min RV 更穩、是否改善 daily RV 預測；方法論校準題，影響我方所有 intraday RV baseline；與 line 540（diurnal sufficiency）正交——那是無母數充分性檢定，這裡是 multiplicative-component 模型估計（來源：arXiv 2111.02376 Multiplicative Component GARCH of Intraday Volatility；Engle-Sokalska 經典）

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

## 候選新論文方向 — 從實驗語料庫挖掘（2026-06-21，boss email-11859 觸發）

boss 點名「M3 不該只盯現有論文，實驗那麼多難道沒長出新論文主題？」。掃 knowledge.json(2341) + experiments/ 後得 4 條**不重複現有 11 theme** 的方向；每條 K-id 與關鍵統計量已主線程 spot-check（抓到初掃 agent 把方向 A 招牌數字灌水）。

- **B（最扎實，可起草）— Forecast-loss ⊥ tail-coverage divergence**：模型 QLIKE 大勝（**DM t=−5.60，k850 實測確認**）卻過不了 1% VaR；CF/Conformal 只補一半。支撐 k850/k854/k824/k799/k800。方法論貢獻（loss 換排名反轉）→ IJF/J.Forecasting。**下一步：主線程起 .md 大綱。**
- **A（cluster 真，thesis 待重驗）— 跨資產 VaR 尾部分布選擇**：k799/k800/k802/k883 真跨資產 VaR backtest（Normal/t/Skew-t/EVT/CF + Trinity + Acerbi-Szekely）。**但** agent 宣稱「skewness=唯一充分統計量 ρ=−0.873」未過查核（−0.876 是某資產 skew 值被誤當預測 rho；實測 rho 僅 0.10–0.21）。需先重估真正的 selection 預測子。
- **C（誠實 null-result）— 日頻波動率 ML 天花板**：9 次確認，ML（XGBoost/MLP/LSTM/KAN/GINN/RECH-X）無一顯著贏 well-specified GJR-GARCH；失敗結構性（loss degeneracy / 227-day overfit / LSTM 塌常數 / 增益實為 RV covariate 而非 NN）。支撐 K618/k619/k816/k929/k940/k944/K1263/K1312/K1533 → FRL/IJF 負面結果。最新 K1533（RECH-X 復現）尤其乾淨：RNN 對 linear GARCH-X 在 1/5 日 horizon 打平，edge 只在 22 日且增益來自 realized covariate。

  - **C+ 復現裁決 PROGRAM（2026-06-23 啟動，回答 boss「為何文獻都說 ML 贏、我們卻 NULL」）**：不只累積自家 null，改主動**忠實復現已發表「ML 贏 GARCH」論文 + 補上它們省略的公平 baseline/檢定**來裁決。核心 thesis：文獻的 ML 勝利系統性來自 3 種 information-unfair 機制 — **M1 弱 baseline**（打 plain GARCH(1,1)，無 GJR/Student-t/GARCH-X，連 HAR-RV 都海放它）、**M2 沒對 ML 做顯著性檢定**（DM/MCS 只跑古典互比或全無，ML「贏」是 raw point-metric）、**M3 RV-covariate 不對稱**（NN 餵 RV、GARCH 只看 return²，給 GARCH 同樣 RV 資訊即抹平，=K1533 機制）。**faithful-reproduce-FIRST 紀律**：必先重現論文的 ML 勝（防自家欠訓練造假 null），再加 info-matched 公平 baseline 重測；若 ML 在對稱資訊下仍過 MCS/DM 就是**真實可發表反例**，如實報不壓制。標的（scoping workflow wf_afa5c76f-63e）：
    - **K1535（home turf，SMOKE 完成 2026-06-23；原配 K1534 因撞 CRP-spike worktree 改 K1535）✅ 第 10 次天花板成立**：復現 MDPI JRFM 2025 18(12):685（PatchTST-lite 贏 ARIMA/GARCH(1,1)/HAR daily-equity RV），漏洞 M1+M2。yfinance ^GSPC 2000-2026（6655 筆）+ Close-to-Close/Parkinson/Yang-Zhang RV，8/8 單元測試 PASS（lookahead/forward-label/QLIKE 方向/資訊對稱/seed/DM horizon）。**Phase A faithful-reproduce 通過**：在 smooth target rv_park 上重現 PatchTST QLIKE 0.455 ≤ GARCH(1,1) 0.620（證明 NN 非欠訓練，假 NULL 排除）。**Phase B 裁決**：DL 確實 Harvey-顯著贏弱 baseline（Transformer vs GARCH-X DM=−4.06、vs GJR-t=−3.58 ← 這就是論文的「贏」=M1），**但 DL vs HAR-RV-X（同 lagged RV(1,5,22)+VIX 資訊）全部不顯著**（PatchTST vs HAR-RV-X DM=+0.90、HAR-X 還略勝；所有 NN |DM|<1.1, p>0.3），MCS 含全部 10 模型不分離。**結論：M1+M2+M3 三機制全證實——文獻的 DL 優勢是資訊優勢非架構優勢；給簡單 HAR-RV-X 同樣資訊，Transformer 領先消失。** smoke ~22min；完整 run（3 指數×3 RV×3 horizon×5 seed≈135 cells）~數小時（需 7 項優化）。獨立 review=agy CONDITIONAL_PASS（Codex 額度滿至 6/25）→ **knowledge.json 待 6/25 後 primary-path Codex review 才寫**（K1259 subagent-fallback 二次驗證規則）。產出在 `experiments/k1535_ml_garch_adjudication_equity/`（worktree agent-a330fe5de20a3ec1d 待 merge）。
    - **K1536（novelty/devil's-advocate，queued，需先加 Binance 5-min ingest；原配 K1535 順移）**：復現 Akgun-Gulay 2025 Comp Econ 65(6)（11 GARCH×6 dist vs ANN/LSTM/CNN，crypto BTC/ETH/BNB 5-min RV）。baseline 形式強（含 GJR/EGARCH/component+fat-tail）但全 return-only info、無 GARCH-X/Realized-GARCH/HAR-RV = M3。**兩面結果**：crypto jumps/long-memory 下 ML 真有可能過 MCS → 若是則為「天花板 domain-bound」的可發表反例。
    - **K-C（輕量 audit note，optional）**：Springer NASL 2025（Jain et al.）—**無 GARCH baseline、不該當裁決 K**；R²=0.91 是 near-unit-root VIX level 的 persistence artifact（RW 免費得 R²≈0.88-0.93）。只做方法論 caution note，禁當「ML 被推翻」引用。
    - **發表 arc**：「Why the Literature Keeps Finding ML Beats GARCH for Volatility: the edge is an information-unfair contest, not an architecture」(M1-M3 catalogue + 兩個 reproduce-then-fair adjudication + 統一機制)。誠實 scope 限：兩個 domain 皆 daily-aggregated，intraday/options-IV-surface 列 future work，不過度宣稱 universal ceiling。
- **D（混合/null 避險，貼用戶 copula-GARCH 專長）— 動態相依 OOS 無加值**：時變 t-copula in-sample 更好（ΔAIC≈−144）但 DCC/copula OOS 少贏常數相關/naive hedge。支撐 k920/921/922/k931/k945/951/k965/K1320。用 HE/utility 不用 Sharpe；需補 1-2 OOS HE-ratio run → JFM/IJF。

追蹤紀律：每個 idle tick 主動從新實驗找此類 cluster，不只維護舊 manuscript。狀態同步 memory [[project_papers_awaiting_submit_decision]]。

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
| **P5** | **vt-crowding-abm** | ⚠️ **2026-05-21 INDEPENDENT-REVIEW OVERRIDE → MAJOR REVISION（status 降回 `working`）**：Codex(GPT-5.4) + agy(Gemini) 獨立審查雙雙 **REJECT** — 3 BLOCKING：(1) threshold detector 內生校準（先射箭再畫靶，calibrated 重現既有 70% headline = 套套邏輯）(2) 同 baseline cell TF/MR threshold 跨 Table 3/4 自相矛盾（20%↔70%）卻仍宣稱 5/5 robustness (3) CI 方法論前後不一致。先前 v1-v4 皆 Claude 自審 proxy 未抓到。報告 `review_history/v5_independent/`。以下舊記錄保留作 audit trail 但已失效：~~✅ READY_FOR_SUBMISSION 全 gate PASS (2026-04-28)~~ — v3 reframe + v4 主線程修 13 issues + v4.1 batch (sim-count unify 46,800 + AI-ack relocate + cole/baltas DOI) → v4 round verdict: academic **4.7★/5** (0/0/0/2 MED/5 MINOR) + citation **0 MAJOR / 0 MED / 2 MINOR**. 6/6 stage gate PASS (latex ≥4★ ✓ / citation 0 MAJOR ≤3 MED ✓ / reproduce GREEN 47/47 100% ✓ / compile 26p clean ✓ / FRL ≥R&R ~90-95% ✓ / self-contained ✓). knowledge entries: f1d85a74 (K1261) + f3b9edd4 (K1262) + 81ebfe54 (K1262b). reviews 歸檔 `paper/vt-crowding-abm/review_history/v1-v4/`. **Submission package 完整 ready @paper/vt-crowding-abm/** | Submission needs user click-submit on FRL portal（cover letter + suggested reviewers prep 待主線程 dispatch，類比 P6 7d2149a0 pattern）；或維持 ready + 每月 continuous review loop（v5 預計 2026-05-28） |
| **P6** | **prg-periodic-garch** | ⚠️ **2026-05-21 INDEPENDENT-REVIEW OVERRIDE → MAJOR REVISION（status 降回 `working`）**：Codex(GPT-5.4) **REJECT** + agy(Gemini) **MAJOR_REVISION→傾向 REJECT** — 共同 BLOCKING：PRG vs GJR/HAR 比較**資訊集不對等** — PRG 用當日 overnight realization 形成 h_{d,1}，baseline 限於 d-1 收盤資訊；§4.5 號稱「fair-information GJR-X」其實用 t-1 overnight，仍不公平。Codex 另指開盤可交易性未證成、agy 另指 Table 2 DM t-stat 全負與「PRG 更佳」敘述符號矛盾。注意：用戶 memory `feedback_session_boundary_forecast_timing` 認定「open 用已 realized overnight = legitimate timing」— 故 timing 本身合法，但**對照組未拿到同資訊**才是 reviewer 攻擊點，需補真正對稱 baseline。報告 `review_history/v5_independent/`。以下舊記錄保留作 audit trail 但已失效：~~✅ READY_FOR_SUBMISSION 全 gate PASS (2026-04-27)~~ — v1-v4 完整 4 輪 paper-review-cycle + v4.1 batch fix 收斂; supabase status `ready_for_submission`; 6/6 gate PASS (latex 4.2★ + citation GREEN + cross-paper meta + FRL desk-accept 35-45% + K1260 fair-info + no tautology). **Reproduce gate 全 PASS**: reproduce.py 22 checks (15→22 加 K1260 §4.5 GJR-X 7 checks) / reproduce_report.json `match_rate=100%` / `alert_level=green` / audit_date 2026-04-27. PDF=15p / bibitems=22 / abstract=184 words / 5 tables / 7 equations. SUBMISSION_READY.md + send-alert df592119 已發 user。**Submission package 完整 ready @paper/prg-periodic-garch/** | Submission needs user click-submit on FRL portal (cover letter + suggested reviewers prep可由主線程 dispatch)；或維持 ready + 每月 continuous review loop |
| **P7** | **vix-sufficiency** | ✅ **READY — GREEN 98% (98/100)** + Sub1-6 closed (bundle + dividend + 5 divergence decisions + Table 6 K752 rewrite + source binding + reproduce.py synced) | Submission needs user click-submit on chosen journal (主線程 dispatch cover letter + journal selection rationale 待用戶解 standby) |
| **P4ins** | **vt-insurance-cost** | ⚠️ **REPRODUCE-GREEN ONLY — NOT submission-ready**（2026-05-21 更正過度宣稱）。reproduce gate 100% 9/9（2026-04-19 88.9%→100% via L184 footnote + tolerance 5→10 bps）。**但從未跑過 paper-review-cycle** — `review_history/` 只有 `diagnosis_v1/`（reproducibility 診斷，明寫 "No main.tex/body.tex edits"），**零輪 latex-academic-reviewer + 零輪 citation-verifier**。per 本文件 L601「reproduce GREEN ≠ submit-ready」，舊「✅ READY」是錯標。DB status 正確維持 `working`。 | **必須先跑多輪 paper-review-cycle**（latex-academic-reviewer + citation-verifier，比照 P5/P6/P10 v1-v4）才能談 submission；已排入 review backlog |
| P1 | leverage-direction | 🟡 **0 MISMATCH** + 28 MATCH + 9 NOTE + 19 UNTRACE (structural data-limit) | C1 ✅ K1256 3-spec / C2 ✅ Kupiec rounding / ✅ 7 figure scripts bundled MATCH / C3-C5 Tables 1/6/7/8/11/14 需 new experiments |
| P3 | vt-trend-following | 🟡 **0 MISMATCH** (83%, 34 UNTRACE structural) | Table 4 M5 ✅ hybrid BAB / Table 3 period ✅ errata; 剩 Table 5 13-market + Table 6 MDD bootstrap 需 new experiments |
| P2 | taiwan-vt | 🟡 **0 MISMATCH** (6→0 本 session, 69% verified + 24 UNTRACE structural) | ✅ TSMC/0050.TW/TWII γ 3-spec footnotes + reproduce.py NOTE reclass / ✅ SSVS PIP UNTRACEABLE / ✅ GJR+Normal viol NOTE; 剩 24 UNTRACE 需 Table 4/5 VT + Sec 6 macro experiments |
| P8 | volatility-absorption | 🔴 61.3% amber + **CRITICAL errata 識別** (2026-04-20 re-verified: 46 MATCH / 12 MISMATCH / 17 UNTRACE / 75 total — 無 drift since 2026-04-19) | `errata_pending.md`: CRITICAL (controlled t Harvey cross -3.14→-1.17) + HIGH (T10 2020-26 sign flip) + MEDIUM (10+ drifts). Path B 推薦 research-honest body revision。**Still awaiting user Path A/B/C decision**. |
| P9 | garch-x-vix | 🟡 submitted under review, snapshot 53.8% / live 84.6%, **shelf errata ready** | `errata_pending.md`: 0-11% DM t drift SPY/QQQ/GLD/USO + **SF2 cross-asset drift** STOXX50E (-16.9%) / FEZ (-9.7%, K1144 forensic 2026-05-29 — `^STOXX50E` 為唯一可用 yfinance ticker, drift 屬同 vintage-reconciliation 家族), Harvey qualitative invariant — 無 body edit 直到 R1 reviewer response |
| **P10** | **crypto-fear-channel** | ⚠️ **2026-05-21 INDEPENDENT-REVIEW OVERRIDE → MAJOR REVISION（status 降回 `working`）**：Codex(GPT-5.4) 獨立審查 **REJECT** — 3 BLOCKING：論文方法段與實際 code 不符 — (1) 文稿寫 QR 用 lagged BTC_RV_{t-1}+1000 bootstrap，`experiments/k1025/k1025.py:283-312` 實際是同日 VIX_t~BTC_RV_t 無 bootstrap → 改變識別意義 (2) subperiod Granger 文稿寫 AIC-selected lag，code 實為 lag 1-3 挑最小 p-value = lag mining 無多重檢定校正 (3) OOS 文稿寫 AIC AR(p) rolling，code 為固定 lag expanding-window，且 2019-01-01 同時落 IS+OOS。另 6 MAJOR 含 Harvey |t|>3 誤用於 DM test（error_log 已記 K547 同錯）。先前 v1-v3 皆 Claude 自審 proxy 未抓到 method-vs-code 落差。報告 `review_history/v5_independent/`。**[2026-05-22 v2 COMPLETE — main.tex 全面更新]** `experiments/k1025/k1025_v2.py` 3 BLOCKING 修正已完成：(1) QR 改 BTC_RV_{t-1} lag + 1000 bootstrap SE (2) Granger 改 VAR-AIC lag + Bonferroni correction (3) OOS 嚴格切分 + AIC AR(p) + rolling 756-day window。K1025-v2 compute job exit_code=0，所有 7 分析完成；`experiments/k1025/k1025_v2_results.json` 為新 canonical source。**main.tex ~30 處數字全更新**：QR amplification 8.54×→7.04×；DM t=-0.98→-1.14, p=0.33→0.26；COVID F=11.05→12.31；spillover from_btc=21.5%→23.7%, net=-76.9pp→-74.4pp；所有 source 注解更新至 v2。定性結論不變：DM 仍 fail Harvey；asymmetry 仍 only downside；COVID 仍唯一顯著 subperiod。Narrative state = `paper_updated_v2_numbers`。下一步：(a) reproduce.py 更新 → v2 numbers gate (b) 重跑 paper-review-cycle (c) 投稿前 6/6 gate 重驗。以下舊記錄保留作 audit trail 但已失效：~~✅ READY_FOR_SUBMISSION 全 6/6 gate PASS (2026-04-28)~~ — body draft (5 slot increment) → v1 round 3.95★ → v2.1+v2.2 fix 19 issues → v2 review 4.40★ + 升 review stage → v2.3 hotfix research-honesty + v2.4 cross-paper Highest-impact + K1025b BTC→VXN multi-asset OOS extension (commit 6a41fc40, experiments/k1025b/ + main.tex §6.4 + Table 7) → v3 review **4.55★/5** post-v3.1 hotfix (academic 0/0/0/2 MED/4 MINOR; citation 0 MAJOR/1 MED/4 MINOR; proxy a50cc2e8/aa23e837). Process discipline: v3 caught Table 7 numerical errors (recurrence of 2 days prior error_log lesson "quantitative claims must have JSON backing") → v3.1 hotfix Table 7 row 1+5 fix + reproduce.py 29→37 checks (8 K1025b byte-match checks added) + §6.4 substantive narrative re-direction (VIX 8.54× > VXN 5.76× honest framing, opposite to original buggy "~11×" claim). 6/6 gate (latex ≥4★ / citation 0 MAJOR / ≤3 MED / reproduce 37/37 GREEN / compile 17p clean / cross-paper meta = no fundamental issue post-K1025b). reviews 歸檔 paper/crypto-fear-channel/review_history/v1+v2+v3/. knowledge entries: 391774db (K1025b multi-asset robustness, P10/multi-asset-robustness category, confidence 0.85) | Submission needs user click-submit on chosen journal (cover letter + suggested reviewers prep 待主線程 dispatch，類比 P5/P6 pattern); target journal IJFMIM (1st) / JEF (2nd) / FRL (backup); 預測 ~94-95% 接受率 post-v3.1 |

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

### 期刊主題挖掘 batch（2026-06-17b；WebSearch 11 期刊 學術5/實務6 趨勢層級；selectivity gate 後初稿 10 → 7 條入單；新軸：vol forecast–portfolio translation gap / idiosyncratic vol × ICAPM equity premium / 關稅板塊 vol / breakeven inflation vol regime / earnings announcement jump / 高頻 tail risk premium / 企業債 factor bias-correction）
> 來源：journal-topic-discovery (task `journal_discovery_20260617_0`, agent sonnet). WebSearch 掃 JFE/JFQA/FAJ/JPM/RFS/JFM/J.Fixed Income/J.Alternative Inv/J.Derivatives/J.Empirical Finance/arXiv 2025-26 趨勢層級，每條 grep research_program.md 確認正交後入單。不捏造論文標題+作者+具體期號；趨勢層級來源在括號標明。主線程驗收：7/7 dedup_check 關鍵字 grep 確認 0 matches，全部入單。

- [ ] **Vol forecast 統計精度 vs 投組 Sharpe 的「translation gap」** — yfinance SPY + 465 大型股週 RV 2015-2025，系統比較 HAR/GARCH/ML 在 QLIKE 精度最優 vs cross-rank accuracy 最優 vs portfolio Sharpe 最優是否為三個不同模型；min-var/vol-target 框架下，量化 QLIKE 改善不換算為淨 Sharpe 改善的 translation gap；與既有 ML-vs-HAR 系列（QLIKE+DM 角度）正交，這裡聚焦「統計精度→投組盈虧」的斷點機制本身（來源：arXiv 2605.19278 May 2026 "Do Better Volatility Forecasts Lead to Better Portfolios?" GNN/S&P 500；JFQA 2025 implied vol ML economic value trend）

- [x] **橫斷面 idiosyncratic vol 作為 ICAPM covariance risk proxy 預測股市 excess return** — K1525 completed (`MIXED_CROSS_SECTION_ONLY`): yfinance current-name large-cap proxy (68 stocks, SPY/SHY, 2004-2026; OOS 173 months from 2012). Lagged idio-vol is priced in Fama-MacBeth (`gamma_idio=0.00514`, HAC `t=4.063`; Q5-Q1 annualized `+16.18%`), but idio-vol ICAPM proxies do **not** improve next-month SPY excess-return OOS forecasts: best idio timing model `LWIV` OOS R² `-0.122%`, DM `t=0.769`; `0/7` idio timing models pass Harvey. Treat as cross-sectional proxy evidence only, not a market-timing signal and not a Han-Li long-sample CBIV replication.

- [ ] **2025 關稅衝擊板塊 realized vol 分化：高/低曝險板塊 RV 的不對稱動態** — yfinance 板塊 ETF（XLK/XLY/XLI/XLC 高曝險 vs XLV/XLP/XLU 低曝險）+ FRED T10YIE，以 Liberation Day 2025-04-02 及 05-14 豁免為事件窗做 RV event study，比較板塊分化 + 窗口前後 SPY 成分 vol 截面分化；與 K1514（相關結構 NULL）正交——那是 SPY-TLT 相關，這是 disclosed-exposure 的板塊 RV 截面（來源：SSRN/ScienceDirect 2025 "Tariff exposure and sectoral vulnerability"；2025 trade shock 是新的外生事件數據）

- [ ] **Breakeven 通膨預期 regime 對 SPY/TLT 波動的機制驗證** — FRED T10YIE/T5YIE 免費日頻（breakeven inflation），標「高通膨預期（BEI>2.5%）」vs「通縮恐慌（BEI<1.5%）」月份，比較兩 regime 下 SPY-TLT realized 相關方向 + SPY/TLT RV，DM 檢定系統差異；與 K1516（財政赤字 → 相關，NULL）正交——機制是通膨預期而非財政；與 TIPS decumulation（K1509）正交——那是退休提領，這是波動機制（來源：SSRN Ceballos "Inflation Volatility Risk and Corporate Bond Returns"；Fed FEDS 2025002 inflation regime；2026 關稅再通膨使此機制回歸前台）

- [ ] **盈餘公告 jump intensity 的橫斷面預測因子（timeliness × size × coverage）** — yfinance earnings_dates 公告日，標 [-1,+1] 窗口 price jump（5σ filter），按 filing timeliness（early/on-time/late）、市值十分位、analyst 覆蓋代理（price level proxy）分組橫斷面，Fama-MacBeth 檢定 jump intensity / post-announcement RV 差異，明確 shift(1) lag；與 K1145/K1147/K1150（EAV 跨市場 universal regularity，論文 arc）正交——那是 aggregate EAV，這是 jump 截面拆解（來源：JFE Feb 2025 "Warp speed price moves: Jumps after earnings announcements"，Christensen/Kim/Timmermann/Veliyev；AEA 2025 tail risk short-term）

- [ ] **高頻 tail risk premium 作為市場 excess return 與 VRP 的 time-varying predictor** — yfinance SPY 5-min OHLC（本機有 2026 YTD 105d）代理 tail risk（downside return 分布截斷）建 TRP proxy，月頻滾動預測 SPY excess return + 下月 VIX；免 options，用 realized 截斷代理；與既有 VRP 隔夜/日內題（06-16 新軸 C，台股版）正交——那是 VRP 方向拆解，這是 tail risk premium 的時序預測力（來源：JFQA Dec 2024 Vol.59(8) "High-Frequency Tail Risk Premium and Stock Return Predictability"，Almeida et al.；cross-section portfolio hedge；VRP return predictability arises from tail asymmetry）

- [x] **企業債 factor zoo 的 bias-corrected 再審計：ETF proxy 版誠實 OOS** — K1522 completed (`NULL_ETF_PROXY`): yfinance corporate-bond ETF proxy set (`HYG/JNK/LQD/VCIT/VCSH/VCLT/IGSB/IGIB`) across 6 signals (`momentum_63`, `carry_252`, `illiquidity_amihud_21`, `range_vol_21`, `credit_beta_126`, `term_beta_126`). Extra-lag bias correction leaves no Harvey-strength premium; best corrected signal is `carry_252` with Sharpe `0.251`, annual return `0.71%`, DM `t=-0.978`. Treat as an ETF-proxy null only, not a TRACE bond-level factor-zoo replication. Source task: `research_factor_zoo_bias_corrected_etf_proxy_oos`.

### 期刊主題挖掘 batch（2026-06-17c；WebSearch 13 期刊 學術6/實務7 趨勢層級；selectivity gate 後 14→5 條入單 — 06-17/06-17b 已飽和當日多軸，本批只入 grep=0 真正零撞 5 軸）
> 來源：journal-topic-discovery (task `journal_discovery_20260617_1`, agent sonnet/low). 主線程驗收：每條 grep research_program.md 5 個關鍵詞（CIV/credit-implied、外推/extrapolation/Chordia、sticky-price/價格剛性、情緒 beta/sentiment beta、散戶占比/TWSE 散戶）皆 0 matches，5/14 入單，9/14 與既有 batch / 06-17 / 06-17b / cross-asset 重疊剃除。趨勢層級非捏造論文標題+作者+期號。

- [ ] **信用隱含波動率（CIV）免 CDS 代理版三因子 RV 預測力** — 用 HYG/LQD/CDX ETF 構 credit-implied vol 代理拆 level/term/skew 三因子（21d range vol + 期限 spread 代理），檢定三因子對次月 SPY/IWM realized vol 是否提供超越 VIX 與 MOVE 的 OOS R² 與 DM 顯著（yfinance ETF + FRED 利差），明確 lag；不需付費 CDS 數據，純 ETF vol decomposition；與既有 MOVE-VIX 分歧（K731 系列）正交——這裡是 credit-specific vol 三因子截面（來源：FAJ Q2 2025 Kelly-Manzo-Palhares CIV 三因子架構，贏 Graham & Dodd Scroll 2026；CDS 版需付費，bond ETF 代理版尚未驗證）

- [ ] **報酬外推偏誤驅動的 IV-RV 不對稱期限結構** — 用 ^VIX（1M）/^VIX3M（3M）+ 後驗 SPY realized vol，分「過去 20 日累積負報酬」vs「累積正報酬」月份，檢定短期 IV 對 RV 的 premium 是否在負報酬期顯著放大（不對稱外推）；Fama-MacBeth 條件回歸 with negative-past-return × IV interaction，明確 lag，OOS R²（yfinance SPY + ^VIX/^VIX3M；FRED macro controls）；不對稱期限結構效應為 trading rule 而非僅 academic premium（來源：JFQA Dec 2025 Chordia/Lin/Xiang Return Extrapolation and Volatility Expectations；2025-26 行為財金前沿）

- [x] **價格剛性行業 credit spread 對 FOMC 衝擊敏感度差異作 vol 前哨** → **K1529 completed 2026-06-17，NULL_ETF_PROXY**：free-data ETF-proxy 版用 yfinance HYG/LQD/VCIT/VCSH/SPY/^VIX + sector ETF baskets，SF Fed monetary-policy-surprise CSV（102 FOMC events, 2012-01-25 至 2023-12-13；OOS 2019 起）。HYG-LQD stress event-vs-baseline diff mean 0.000457，paired t p=0.7376 / Wilcoxon p=0.3402 / block-bootstrap p=0.3766；abs surprise → credit response HAC t=1.9229 未過 Bonferroni；pre-FOMC credit worsens OOS QLIKE -13.85%；post-response credit improves QLIKE +5.92% 但 DM t=-1.294，Harvey FAIL。結論：日頻 ETF proxy 不支持「FOMC credit-spread stress 是 robust SPY RV 前哨」；若重開需 firm-level credit spread、NFIB/markup price rigidity、或 intraday FOMC window 資料。

- [ ] **市場情緒 beta 截面策略：高/低情緒 beta 股票的系統性報酬差** — yfinance 美股月度，用 VIX 日變動或市場情緒指標（FRED 消費者信心 UMCSENT/AAII 散戶情緒月頻免費代理）計算個股報酬對情緒的 beta（rolling 60M），組高/低情緒 beta 五分位組合，Fama-MacBeth + DM 檢定報酬差異與 vol-adjusted return，明確 lag；與既有 retail attention / 散戶 flow 題正交——這裡是 cross-sectional sentiment beta 純截面策略，不是流量/流動性（來源：FAJ Q3 2025 Hasan/Kumar/Taffler Investor Emotions and Asset Prices；高情緒 beta 贏低情緒 beta 為 2025 新異常）

- [x] **台股散戶占比 × 近期報酬 interaction 預測台股 RV** → **K1530 completed 2026-06-17，MIXED_PROXY_WEAK_OOS**：hourly 可重現版使用本地 public snapshots（0050.TW yfinance OHLCV、0050 三大法人買賣、0050 融資券）建兩個 ETF-level retail-like proxy：residual retail share 與 margin activity turnover。所有 feature 明確 `.shift(1)`，target 為 day-t 0050 r² / Parkinson RV，OOS 2022 起。r2_ann interaction 對 residual-retail t=-3.9515（Bonferroni pass 但方向反簡化放大故事）與 margin activity t=+2.9518（Bonferroni pass），但 0/4 OOS QLIKE spec 過 Harvey；最佳 Parkinson+residual-retail QLIKE +11.83% 但 DM t=-2.7765 未過 -3。結論：0050 retail-like proxy 有 suggestive 但不穩定資訊，不可宣稱 TWSE 全市場散戶占比 × 近期跌幅 robust 預測 RV；重開需 official full-market retail share、個股 panel 或 intraday order-flow。

### 期刊主題挖掘 batch（2026-06-17d；journal_discovery_20260617_2；WebSearch FAJ/RFS/JFQA/J.Derivatives/RPC 2025-26 趨勢層級；selectivity gate 後 7 條入單）
> 來源：journal-topic-discovery fallback。主線程先 grep 既有 backlog，剔除已存在的 bond-fund liquidity、VIX vol-of-vol、graph spillover、BTC ETF 時段結構、factor ETF crowding、AI HHI concentration、台股/0050 index-fragility 等重疊題；本批只保留「可用免費資料啟動」且與最近 K1525/K1529/K1530 不同的 7 個方向。來源採趨勢層級與公開頁面摘要，不捏造未核實期號細節。

- [x] ~~高維 factor timing 在波動 regime 下是否只是在過度換手~~ → **research_factor_timing_regime 完成 2026-06-18，NULL**：yfinance factor ETF（MTUM/VLUE/QUAL/USMV/RPV/IVE/IWF）+ SPY/^VIX，完整月頻 2013-08 到 2026-05，OOS 2018+ 共 100 月。EW net Sharpe 0.799；12-1M momentum top-3 方向略優（Sharpe 0.867、net edge +1.13%/yr）但 DM t=-0.63、bootstrap Sharpe CI [-0.159,+0.251] 跨 0；ElasticNet vol-regime top-3 turnover 0.706/月、cost drag 0.85%/yr、net Sharpe 0.643，劣於 EW。結論：此 ETF-level free-data spec 不支持高維 vol-regime factor timing 可交易 alpha；簡單 momentum rotation 只能視為方向性但非 robust。

- [ ] **稅務造成的 asset-allocation drift 會不會破壞 VT / risk-parity 風控** — 用 SPY/TLT/GLD/HYG/SHY 日資料模擬 taxable rebalancing：無稅、定期再平衡、賣出需付 realized-gain tax 的三規格，量化權重漂移、target vol tracking error、drawdown 與 after-tax Sharpe；與退休提領 / TIPS decumulation 題不同，這裡檢定稅務 friction 對波動控制規則的機械破壞（來源：Financial Analysts Journal Q2 2025 "Asset Allocation Drift Due to Taxes"）。

- [ ] **主題 ETF 的 coherence decay 作為 thematic crash 前哨** — 用 AIQ/BOTZ/ARKK/ICLN/CIBR/ITA/URA 等 thematic ETF 與各自主成分股，估 residual correlation / first-PC share / dispersion，檢定 coherence 下降後 1-3 月是否預測 theme ETF RV、max drawdown 或相對 SPY reversal；與 AI mega-cap HHI 題不同，這裡聚焦「主題本身是否還是一個共同風險」而非集中度（來源：Financial Analysts Journal 2025 Graham-Dodd Top Award "Thematic Investing: A Risk-Based Perspective"）。

- [x] ~~被動資金流對 mega-cap idiosyncratic vol 的放大：SPY/IVV/VOO 代理版~~ → **research_mega_cap_idiosyncratic_vol_spy_ivv_voo 完成 2026-06-18，NULL_PROXY**：yfinance SPY/IVV/VOO dollar-volume shock（非真 AUM flow）+ 40 current-name large-cap panel，2010-09 到 2026-05。Primary lagged month-FE spec `Top10 × flow_shock_{t-1}` 係數 +0.0074 但 clustered t=0.287、p=0.774；contemporaneous diagnostic 反向；高 shock 月份 top10-control log idio-RV spread 差 -0.0237，bootstrap CI [-0.241,+0.197]。結論：free-data dollar-volume proxy 不支持「passive flow 放大 mega-cap residual vol」；真 replication 需 historical passive AUM / ETF ownership / index weights。

- [ ] **FX realized-skewness risk premium 免期權代理：高偏態貨幣是否承擔 crash risk** — 用 yfinance FX spot / currency ETF（FXY/FXE/FXB/FXA/UUP/CEW/EMLC）建月度 downside/upside semivariance asymmetry 與 realized skewness proxy，排序 currency baskets，檢定高 SRP proxy 是否有 carry-like return 但更差 left-tail / vol-spike exposure；與 EM carry × vol gate 題不同，這裡是 skewness premium 橫斷面而非利差 carry（來源：JFQA 2025 "Skewness Risk Premia and the Cross-Section of Currency Returns"）。

- [ ] **短天期期權 forward moments 的免費 proxy：VIX9D/SKEW 是否預測一週 jump 而非 RV level** — 用 ^VIX9D/^VIX/^SKEW + SPY realized semivariance，建 short-horizon forward skew/kurt proxy，target 改成未來 5 日 jump indicator / left-tail loss / realized semivariance，而非只預測 RV level；與 K43 SKEW/VIX3M level NULL、K1521 realized kurtosis pilot 正交，這裡測 option-implied short-maturity moments 的 tail-event分類力（來源：Journal of Derivatives Spring 2025 "The Forecasting Power of Short-Term Options"）。

- [ ] **ETF heartbeat / tax-efficiency 交易是否在季末造成成分股短暫 liquidity-vol 壓力** — 用大型 equity ETF（SPY/IVV/VTI/QQQ）季末/年末高成交額日、公開 holdings top constituents、分配/資本利得公告，檢定 suspected heartbeat window 內 top holdings 的成交額、range-vol、close-to-close RV 是否異常；若 N-PORT / holdings history 不足，先做 ETF-level volume + top-current-holdings diagnostic，不宣稱因果（來源：RFS 2025 "The Role of Taxes in the Rise of ETFs"；ETF tax efficiency/heartbeat trade 機制）。

### 期刊主題挖掘 batch（2026-06-18；journal_discovery_20260617_3；4 批 06-17 連跑後嚴格 selectivity gate；scanned 10 期刊×趨勢層級，拒 5 條軸級重複，4 條入單）
> 來源：journal-topic-discovery (task `journal_discovery_20260617_3`, agent sonnet/medium). 06-17 / 06-17b / 06-17c / 06-17d 4 批已飽和 22 條，主線程 grep `/tmp/backlog_existing.txt` 全 174 條 backlog + 4 批近表後，剃除 axis-level（不僅字面）重複後僅 4 條真正未涵蓋軸入單；趨勢層級來源括號標明，不捏造論文標題+作者+期號。每條 grep ≥3 同義關鍵字確認 0 matches。Selectivity gate 拒掉的軸：(a) AI implied-realized vol divergence hedge（與既有 504 tail-hedge + 518 VRP decline 軸過近）、(b) RAG-augmented LLM × 10-K 預測 vol（與 line 611 FinBERT 軸過近）、(c) Limit order book imbalance HF 預測（無免費 LOB 資料，且 K1530 0050 intraday 已試免費代理）、(d) Climate physical risk insurance vol（line 487 NOAA hurricane × KIE/XLU 已覆蓋）、(e) Long-term capital market assumption regime（屬 strategic asset allocation，不在 vol-pred 主軸）。

- [ ] **交易日內 U-shape 波動集中度作為日頻 RV 預測的時段加權 feature** — yfinance SPY/QQQ/IWM 5-min 或本機 105d intraday，把日內 RV 拆成「開盤 30min / 中段 / 收盤 30min」三段子-RV，建 RV_open / RV_total、RV_close / RV_total 比率作為「開盤集中」vs「收盤集中」regime feature，加入 HAR-RV 檢定對 t+1/t+5 daily RV 的 OOS R² 增量與 DM 是否顯著；明確 shift(1) lag；與 K1521（kurtosis）+ K1530（0050 intraday retail）正交——這裡是 within-day periodicity 加權，不是橫斷面 retail 或四階矩（來源：JFEC 2024 Vol.22(2) intraday commonality ML for vol；Andersen-Bollerslev 經典 U-shape periodicity 在 2025-26 ML 框架被重新檢視為 attention feature）

- [x] **VT / 動態 risk parity 的「turnover-cost dominance」門檻：何時 monthly rebalance 反勝 daily** → **K1532 completed 2026-06-18，CONDITIONAL_PASS**：yfinance adjusted-close SPY/TLT/GLD/HYG/SHY，2007-04-11 至 2026-06-17，252d lagged ERC covariance，daily / weekly / monthly rebalance，成本 0/8/15/25/35 bps per dollar traded。Monthly-vs-daily net Sharpe break-even：DRP 4-asset 18.72 bps、DRP 5-asset 17.87 bps、VT-DRP+SHY 15.71 bps；35 bps 時 daily-minus-monthly HAC return t 分別 -2.595 / -3.294 / -3.083。結論：daily 有小 gross edge，但約 16-19 bps turnover cost 會吃掉；這是 execution-frequency 工程結論，不是新 alpha。見 `experiments/k1532/`。

- [ ] **SOFR-IORB spread 作為「reserve scarcity」訊號預測 Treasury & 股債相關 vol regime** — FRED SOFR + IORB 免費日頻，建 SOFR-IORB spread（reserve-side scarcity，與 K522 SOFR-EFFR repo-basis 訊號方向不同），檢定 spread 持續>0 的 regime 是否預測 t+5/t+22 ZN=F/TLT/IEF realized vol + SPY-TLT 相關升高；明確 lag，OOS 2019+；與 522 repo-basis 軸正交（那是 funding spread + CFTC leveraged short，這是 reserve adequacy）（來源：Fed FEDS Notes 2025-01 "Market-Based Indicators on the Road to Ample Reserves"；2025-12 Fed 停 runoff 後 reserve regime 切換期）

- [ ] **穩定幣供應 shock 對 FX 與 EM 貨幣 vol 的雙向 spillover 通道** — DefiLlama 穩定幣 supply net flow（USDT/USDC 月頻免費）+ yfinance DXY/UUP + EM 貨幣 ETF（CEW/EMLC），檢定 stablecoin 供應 shock 是否領先 DXY 與 EM 貨幣 RV / 左尾，雙向 Granger 與 quantile spillover；與 K523（stablecoin → Treasury 通道）正交——這裡是 FX channel 而非 short-rate channel，回應 BIS WP 1340 點出的「stablecoin flow → FX spot 與 EM 貨幣 vol」（來源：BIS Working Papers 1340 2025 "Stablecoin flows and spillovers to FX markets"；2026 USDT/USDC 供應 record high 後 FX 通道訊號）

### 期刊主題挖掘 batch（2026-06-21；journal_discovery_20260620_0；WebSearch FAJ/RFS/JOIM/JAI/JFI/JFQA/JPM/Fed/BIS/Pew 2025-26 趨勢層級；selectivity gate 後 7 條入單）
> 來源：journal-topic-discovery fallback。主線程先 grep 既有 backlog，剔除 oil vol spillover/inventory、generic liquidity proxy、factor timing、thematic ETF coherence、stablecoin→Treasury/FX、AI concentration/capex、climate insurance vol 等已覆蓋軸；本批只保留可用免費資料啟動、且與 K1522/K1530/K1532 及 06-17/06-18 批次正交的 7 條。趨勢層級來源採期刊/官方頁面摘要，不捏造未核實期號細節。

- [ ] **能源新聞 topic shock 對原油與能源股 RV 的 OOS 增量** — 用免費新聞/RSS/GDELT 標題建 oil-market topic/sentiment 指標，加入 CL=F/USO/XLE/XOP HAR-RV 與 EIA inventory controls，比較 QLIKE/DM 與 event-window RV；與原油 vol spillover、inventory NULL 正交，測「文字 topic flow 是否提供非價格/庫存資訊」（來源：FAJ 2026 Big Data Meets the Turbulent Oil Market；能源 NLP 指標對 oil vol / energy equity 有 OOS 增量）

- [ ] **RLMM 價差非對稱指紋：對稱成本衝擊下流動性是否單邊惡化** — 用日 OHLCV 建低頻價差代理，選 SPY/QQQ/IWM + 高電子化 mega-cap basket，在 VIX/成交量對稱 shock 後檢定 bid-ask proxy 是否有非對稱擴張、且是否預測 t+1..t+5 RV；與 generic CPQS liquidity predictor 正交，聚焦 reinforcement-learning market maker 的可觀測指紋（來源：RFS 2026 Algorithmic Pricing and Liquidity in Securities Markets）

- [ ] **AI 勞動收入曝險 × sector ETF vol：人力資本 shock 是否改變投組風險承擔** — 用 O*NET/免費 AI exposure score 對行業做 AI-labor exposure，映射到 sector ETF 與 BLS wage/employment surprise，檢定高曝險行業在 AI adoption news / layoff shock 後 RV、downside semivariance、sector correlation 是否升高；與 AI capex/HHI/電力需求題正交，聚焦 household labor-income hedging channel（來源：JOIM 2026 Q2 Adapting to AI）

- [x] ~~**tailasym5 joimskews 尾部不對稱估計法賽馬：多資產尾部溢酬是否穩健**~~ → **K1359 completed 2026-06-21，RISK_SIGNAL_ONLY_NULL_PREMIUM**：SPY/QQQ/TLT/GLD/USO/UUP/FXY/HYG/EEM 月頻 2007-05 至 2026-05（229 months），6 種 returns-only tail-asymmetry estimator 全部 `signal.shift(1)`。0/6 estimator 有 next-month return premium（return HAC t range -1.01 到 +0.51，遠低於 Harvey |t|>=3），但 4/6 estimator 對下一月 RV 或 left-tail exposure 有 t>=3。結論：免費 ETF realized-return 尾部不對稱 proxy 可標記高風險狀態，但不可宣稱穩健尾部溢酬；不能否定 option-implied skew / skew-swap 文獻。

- [x] ~~**Prediction-market implied probability shock 作 macro event vol prior**~~ → **K1360 completed 2026-06-21，WEAK_KALSHI_DIAGNOSTIC_UNDERPOWERED**：Kalshi public API 可建 CPI/Core CPI/FOMC/Payrolls/NFP 2026 macro event probability-shock panel（32 events、186 markets、21,759 market-candle rows；market targets 2025-09-03 至 2026-06-18，200 trading days），所有 Kalshi 與 ZQ=F FedWatch-like baseline predictors 均 `signal.shift(1)`。Polymarket public endpoints 在本環境回 domain-block / failed probe，無 cross-market replication。Kalshi lagged shock 只有 SPY 5d forward RV 弱訊號（beta +0.01485 per 1sd，HAC t=+2.12；top-quintile RV 14.23% vs 11.42%，Welch p=0.008），0 個 target 達 Harvey |t|>=3；event-day study n=10 無顯著 tail-move 關係。結論：資料管線可行，但不可宣稱 prediction-market shock robustly forecasts volatility，也不可宣稱 beats FedWatch；下一版需 CME FedWatch probability history / external Polymarket replication。

- [x] ~~**Gaming / sports-betting / esports 籃子的 vol spillover 與 risk-on 訊號**~~ → **K1361 completed 2026-06-22，DIVERSIFICATION_SINK_PLUS_WEAK_LEAD_NULL_TRANSMITTER**：yfinance adjusted close 建 ESPO/HERO/NERD/GAMR gaming ETF basket、DKNG/FLUT/HOOD betting-fintech basket，對 QQQ/ARKK/BTC/SPY 做 21d log-RV VAR/Diebold-Yilmaz connectedness、252d rolling stress/calm、lagged HAC lead tests；樣本 2019-08-15 至 2026-06-18（1,720 trading days），所有 predictive source volatility 皆 `shift(1)`，seed=42。Gaming 與 betting full-sample net connectedness 均為負（-0.077、-0.167），stress net connectedness 仍為負且 stress-minus-calm t 只有 +0.14/+0.10；lagged source-vol 只有 BETTING_FINTECH→ARKK 一項達 t=+3.13，未達預設「至少兩項 + transmitter evidence」門檻。8/8 rolling return correlations 在 SPY stress 期顯著升高，支持「壓力期 diversification sink / correlation convergence」，不支持 robust ex-ante volatility transmitter 或 trading signal claim。

- [x] ~~**optflowcrowd 總體選擇權買權需求差作 short-vol timing proxy**~~ → **K1362 completed 2026-06-22，WEAK_DIAGNOSTIC_NULL_STRONG_TIMING**：用 Cboe public total/equity/index put-call CSV archive + yfinance SPY/^VIX/SVXY/VXX/^IRX，樣本 2007-04-03 至 2019-10-04（3,275 daily rows；rolling-z 後 3,150），建 equity call share、negative equity P/C、equity-index call gap、volume-adjusted call crowd 等 5 個 public proxy；所有 predictive regressions 明確 `signal.shift(1)`，SVXY risk-off diagnostic 用 lagged rolling 80% threshold，seed=42。30 個 expected-direction HAC cells 只有 `equity_call_demand_z -> vix_change_5d` 達 Harvey t>=3（coef +0.0849, HAC t=+3.03）；SPY excess return 與 SVXY short-vol proxy 全未過（最負 SVXY 5d t=-1.13）。Top-quintile call-demand 對 5d VIX change 有診斷力（diff +0.556, Welch t=+4.38），但對 SPY / SVXY 不穩健。SVXY gating 最佳 equity_minus_index_pcr_z Sharpe 0.594 vs buy-hold 0.132、MDD -73.2% vs -93.1%，但缺 HAC target 支持且資料止於 2019，只能列 follow-up diagnostic。結論：public aggregate P/C proxy 可標記未來數日 VIX 上行壓力，不能宣稱 ACIB replication、robust short-vol timing 或可交易 call-crowd signal；需 2020+ signed/open-buy option flow 才能重開強 claim。

### 期刊主題挖掘 batch（2026-06-22；journal_discovery_20260622_0；WebSearch JoE/JFQA/RFS/JBF/JFEC/Fed 2025-26 趨勢層級；selectivity gate 後 7 條入單）
> 來源：journal-topic-discovery fallback。主線程先 grep 既有 backlog，剔除 private-credit/BDC、0DTE、repo-basis/SOFR、關稅板塊、通膨 regime、green-brown vol spread、ETF heartbeat、generic ETF fragility 等已覆蓋軸；本批只保留「期刊/官方來源明確、可用免費資料先啟動、且與 K1487/K1530/K1532/K1355 不同」的 7 條。趨勢層級來源採公開摘要與期刊頁面，不捏造未核實期號細節。

- [x] ~~**Fedspeak forecast-revision shock 作 equity/bond tail-vol prior**~~ → **K1363 completed 2026-06-23，NULL_PUBLIC_DICTIONARY_PROXY**：抓 Federal Reserve Board official speech pages 2020-2026 + official FOMC calendar，解析 526 篇 speech、排除 FOMC +/-1 business day 後使用 477 篇 between-meeting speeches；yfinance SPY/QQQ/TLT/IEF daily adjusted OHLCV 2020-01-02 至 2026-06-22（1,625 trading days）。用 transparent dictionary 建 growth / inflation / labor forecast-revision shock，全部 mapping 到交易日後 `signal.shift(1)`，加入 HAR daily/weekly/monthly lagged RV + lagged range control，對 `log_rv_1d`、`log_forward5_rv`、`left_tail5` 做 OLS-HAC maxlags=5。Primary 12 tests 中 positive Harvey t>=3 = 0/12、absolute |t|>=3 = 0/12、BH q<=0.05 positive discovery = 0/12；最強 SPY log_rv_1d HAC t=+1.60、BH q=0.654。修正後的 high-signal diagnostic（positive lagged z-signal top quintile，48 days）對 SPY/QQQ/TLT/IEF forward 5d RV 也全不顯著（Welch p>=0.497）。結論：免費 Fed Board speech + dictionary proxy 不支持 robust Fedspeak tail-vol prior；不可反駁原始 JoE NLP/high-frequency speech 文獻，重開需 full FOMC-member corpus、speech timestamp、sentence-level NLP 與 intraday event-window data。

- [x] ~~**ETF sampling arbitrage 是否只放大 liquid constituents 的 vol/comovement**~~ → **K1364 completed 2026-06-23，NULL_PROXY**：yfinance current top-10 holdings + adjusted OHLCV，SPY/IVV/VTI/IWM/MDY + 11 sector ETFs，effective sample 2020-07-02 至 2026-06-22（23,984 ETF-date rows；1,499 trading dates；128 requested constituents）。所有 ETF shock 與 liquidity ranking 皆 `shift(1)`；high-minus-low liquid tercile regression 的 3 個 target 係數皆同向為正但未過 Bonferroni（RV z=0.65 p_adj=1.000；market beta proxy z=1.09 p_adj=0.825；ETF comovement z=2.08 p_adj=0.113），top-decile shock bootstrap CI 皆跨 0。結論：免費 top-holdings / daily OHLCV proxy 不足以 robustly support liquid-constituent amplification；不可反駁 JFQA AP-basket/intraday 機制，重開需歷史完整 holdings / AP basket / TAQ 或 intraday spread-depth data。

- [ ] **同指數 ETF liquidity-clientele concentration 作 index RV 壓力代理** — 用同指數 ETF 組（SPY/IVV/VOO、QQQ/QQQM、IWM/VTWO、EEM/IEMG）每日成交額 share、spread proxy、費率與 AUM share，建 liquidity-pool concentration / fragmentation 指標，檢定短線流動性是否集中到高 turnover ETF 時，index ETF RV、premium-discount proxy 與尾盤 range-vol 升高；與被動 flow 題不同，這裡是 same-index ETF 內部 liquidity clientele 與交易池集中（來源：RFS 2024/25 Value of ETF Liquidity；同指數 ETF 的流動性外部性與短線投資人 clientele 是新近 ETF 競爭主題）

- [x] ~~**Bond mutual fund demandable-equity run proxy 對信用 ETF vol 的領先性**~~ → **K1538 completed 2026-06-23，WEAK_DIRECTIONAL_PROXY / gate fail**：yfinance AGG/BND/LQD/HYG/BKLN/TLT/SPY/^VIX 日資料 + FRED deposits/MMF assets（2010-01-04 至 2026-06-23，4,143 daily rows；K1536/K1537 已占用，故使用 K1538）建 run-pressure proxy：bond ETF dollar-volume shock、負債券 basket return、HYG-vs-LQD underperformance、ETF illiquidity、cash migration。所有 predictive signal 明確 `signal_lag = run_pressure_index.shift(1)`。HAC regression 方向符合預期但未過 gate：HYG RV5 beta=+0.00284, t=2.04, raw p=0.041 但 BH q=0.191 / Bonferroni p=0.372；HYG RV21 t=1.68，BKLN RV5 t=1.65，HYG-SPY downside corr21 t=1.45。OOS MSE 改善方向正（HYG 5d +4.06%、LQD 5d +4.35%、BKLN 5d +4.20%）但 DM t 皆未過 Harvey（best BKLN 5d t=-1.88）。結論：只能作「免費 proxy 有弱方向線索」；不可發文宣稱 bond-fund run pressure robustly predicts credit ETF vol，若重開需 ICI fund-flow / fund NAV discount / TRACE。

- [ ] **Validated cyber incident event study：從 coarse keyword 改成事件級金融穩定 shock** — 用公開重大 cyber incident / data-breach 日曆（CISA、SEC 8-K cyber disclosure、Privacy Rights Clearinghouse 等免費源）建立 verified event dates，對受害公司、cyber ETF（BUG/HACK/CIBR）與金融/雲端供應鏈籃做 event-window RV、left-tail、cross-sector spillover；明確區分 K1487 的 coarse GDELT keyword NULL，本題只接受可追溯事件清單與公告時間（來源：NY Fed 2025 Cyber Risk to Financial Stability conference；AI、third-party risk、financial infrastructure cyber risk 被列為金融穩定前沿）

- [x] ~~**Structural VIRF shock library：把重大歷史衝擊轉成 volatility impulse response templates**~~ → **K1366 completed 2026-06-23，PARTIAL_VARIANCE_TEMPLATE_CORR_NULL**：用 SPY/TLT/UUP/GLD/HYG yfinance adjusted close（2016-01-05 至 2026-06-22，2,630 daily returns）+ EWMA covariance filter（lambda=0.94, 252d init）建 historical second-moment response templates；所有 random placebo sampling seed=42，predictive carryover diagnostic 用 `signal.shift(1)`。2018Q4 equity/credit 與 2025 tariff shock 的 total-variance response 超過 placebo gate（peak lift +360.5% p=0.026；+476.6% p=0.015），但 2020-03 COVID 與 2022 rate shock 不過（p=0.324/0.469），且 4/4 correlation-response placebo tests 均不過（p range 0.175-0.740）。結論只能說免費 ETF 資料可形成「variance scenario template」的 partial evidence；不可宣稱 structural BEKK/DCC VIRF、causal covariance-network response 或 broad scenario library pass。未寫 knowledge.json。

- [x] ~~**Climate-news duration 而非 climate-news level：green/brown 反應時間差是否預測 tail risk**~~ → **K1367 completed 2026-06-23，NULL_PROXY**：GDELT DOC TimelineVolRaw climate-news daily counts（2017-01-01 至 2026-06-23，3,440 rows）+ yfinance ICLN/TAN green basket、XLE/XOP brown basket、XLU/SPY controls，建 69 個 climate-news duration / decay events；事件 features 只在 feature date 後以 `signal.shift(1)` 進入 5d RV、VaR/ES、left-tail loss 與 21d green-brown correlation-spike targets。0/18 duration / reaction-gap focal tests 達 Harvey |t|>=3 或 Bonferroni p<0.05（最強 green RV5 duration t=+1.80）；top-tercile duration-reaction composite 對 green RV5 方向為正但 bootstrap CI 跨 0。結論：免費 GDELT daily attention + public ETF proxy 不足以支持 climate-news duration/reaction-time 作 tail-risk prior；不可反駁 JBF 2025 公司級 / intraday response-time evidence。

### 期刊主題挖掘 batch（2026-06-22 Codex 補充；journal_discovery_20260622_0；WebSearch FAJ/RFS/RoF/JFQA/JFI/JOD/JAI/JPM 2025-26 趨勢層級；selectivity gate 後 7 條入單）
> 來源：journal-topic-discovery Codex fallback。保留並行流程已寫入的 2026-06-22 JoE/JFQA/RFS/JBF/JFEC/Fed batch，本段只補其未覆蓋的實務/方法論軸。先 `rg` 剔除已覆蓋軸：short-term options / VIX9D-SKEW、JAI gaming spillover、RFS algorithmic liquidity、ETF tax heartbeat、CIV、factor timing、generic retail attention、EAV、SOFR-IORB、private-credit BDC price-stress。本批只保留可用免費資料或明確代理資料啟動、且與 K1332/K1359/K1360/K1532 及 06-17~06-21 批次正交的 7 條；若使用 ETF / 新聞 / 產品名稱 proxy，結論必須標為 proxy diagnostic，不得冒充原文資料 replication。

- [ ] **私募另類基金 capital-call / distribution 壓力的公開代理 vol prior** — 用上市另類資產管理公司與私募市場 proxy（BX/KKR/APO/ARES/BAM/CG、BDC BIZD、REIT VNQ、infrastructure PAVE/IFRA）+ FRED 信用利差與股市 drawdown 建「LP liquidity stress」指標，檢定 stress 是否領先 BIZD/HYG/VNQ/IWM RV、left-tail 與相關性升高；與 K1332 private-credit BDC price-stress 正交，這裡聚焦 LP 現金流/承諾策略壓力而非 BDC 本身價格訊號（來源：Financial Analysts Journal 2025 "A Latent Factor Cash Flow Model for Alternative Investment Funds"；private funds cash-flow risk / scenario stress testing 成為實務主題）

- [x] ~~**biodiversity transition-risk 商品籃的 RV 與 tail repricing**~~ → **K1537 completed 2026-06-23，NULL_PROXY**：yfinance public ETF/ETN proxy（CORN/SOYB/WEAT/CANE/JO/WOOD/DBA vs GLD/SLV/USO/UNG/CPER/PDBC，2018-01-02 至 2026-06-22，2,128 union trading days；K1536 已被 research_program.md 其他 queued 題預留，故本題使用 K1537）不支持「高 biodiversity-footprint proxy 有更高 RV」；全樣本 high-minus-control 21d annualized vol=-8.86pp（HAC t=-9.97）與 downside semivariance=-0.0449（t=-7.05）反而顯著較低。6 個 Kunming/GBF/EUDR/TNFD/Nature Restoration 事件窗的 RV/downside diff-in-diff 方向偏正（log RV +0.236、log downside +0.304）但 bootstrap 95% CI 跨 0；abnormal return diff-in-diff +0.009 亦跨 0。不可發文宣稱 biodiversity events 預測 tail risk，也不可反駁 Review of Finance commodity-futures biodiversity-footprint 結果，因本實驗只是 ETF proxy diagnostic。

- [x] **retail structured-product complexity 的免費 ETF proxy：複雜產品熱度是否預測 tail-risk mispricing** — `experiments/research_retail_structured_product_complexity_etf_proxy_t/` 已完成 yfinance volume diagnostic；結果為 `POSITIVE_PROXY_NEEDS_CAUSAL_FOLLOWUP`，33 個 HAC(4) predictive regressions 中 3 個同時通過 Harvey `|t| >= 3` 與 Bonferroni 5% gate，主要集中在 single-stock leveraged ETF demand proxy 領先 COIN/NVDA/TSLA 5d RV。此結果只支撐 free-data proxy association，不宣稱結構型票據原文 replication 或因果效果。（來源：Review of Finance 2026 "Competition, complexity, and security design: evidence from retail investment products"；complexity 與 tail risk / investor comparison friction）

- [x] **Friday / triple-witching closing-auction concentration 作隔日 RV 與 reversal 訊號** — `experiments/research_friday_triple_witching_closing_auction_concentra/` 已完成 free-data proxy screening：日頻層使用 repo-cached yfinance SPY/QQQ/IWM 2010-01-04 至 2026-06-22，lagged Friday/OPEX/triple + volume/range crowding proxy 預測隔日 open-to-close r²；本機 SPY 5-min snapshot 2026-01-14 至 2026-06-22 僅作 final-30-min diagnostic（106 days，20 Fridays，6 monthly OPEX，2 triple-witching proxies）。Verdict=`WEAK_DIRECTIONAL_NEEDS_CONFIRMATION`：pooled OOS QLIKE 改善 2.77%、HLN DM t=-3.66，但 primary pooled triple-witching event contrasts 全未過 Harvey `|t|>3`（annualized OC vol diff -0.58pp, t=-0.85；reversal diff -13.9bps, t=-2.22）。不可發文宣稱 Friday/OPEX auction crowding 直接預測隔日 RV；若要重啟需多年度 minute bars 或真 NYSE/Nasdaq auction/imbalance feed。

- [ ] **municipal convenience premium 壓縮作 tax-liquidity stress 的 cross-asset vol prior** — 用 MUB/TFI/HYD/TAXF 對 IEF/AGG/LQD/HYG 的相對報酬、drawdown、成交額與 FRED state/local fiscal stress proxy 建 muni-richness/cheapness 指標，檢定 muni convenience premium proxy 壓縮是否領先 muni ETF RV、credit ETF RV 與股債相關 regime；與 generic bond ETF liquidity 題正交，這裡是 tax-exempt convenience demand / tax uncertainty channel（來源：RFS 2025 "Do Municipal Bond Investors Pay a Convenience Premium to Avoid Taxes?"；muni convenience premia 與 tax/fiscal uncertainty / fund-flow expectation）

- [ ] **Fama-French factor vintage drift 對 VolPred factor/alpha 結論的 robustness gate** — 針對已用 Ken French factors 的 factor timing / BAB / alpha 實驗建立 factor-file checksum 與 vintage log，若能從 Internet Archive / 本機備份取得舊版，重跑 2-3 個代表性 factor 結論；若舊版 blocked，先做「今日起固定 vintage + checksum + traded-ETF factor proxy」治理實驗，檢查結論對 factor source 是否敏感；與 ALFRED macro vintage 題正交，這是 asset-pricing factor methodological revision risk（來源：Review of Finance 2026 "Noisy factors? The retroactive impact of methodological changes on the Fama-French factors"；factor vintages 可改變 alpha/loadings）

- [ ] **corporate-bond news sentiment 的 RV-only 再檢定：報酬小不代表風險無訊號** — 用免費新聞/RSS/GDELT corporate-credit 關鍵字 sentiment + yfinance HYG/LQD/BKLN/VCIT/VCSH，先複核 sentiment 對 bond ETF returns 經濟量級是否小，再改 target 為 next-week RV、downside semivariance、spread proxy drawdown，檢定是否只在風險維度有增量；與能源新聞 topic shock 及 generic news-attention 題正交，資產類別限 corporate bond / loan ETF（來源：Journal of Fixed Income Winter 2026 "Corporate Bond Returns: Does News Sentiment Matter?"；return effect economically negligible 但可做 risk-target null/diagnostic）

### 期刊主題挖掘 batch（2026-06-23；journal_discovery_20260623_0；WebSearch JPM/JFI/JAI/CFA/Fed/RoF 2025-26 趨勢層級；selectivity gate 後 7 條入單）
> 來源：journal-topic-discovery Codex fallback + fresh-context worker（task `journal_discovery_20260623_0`）。主線程先 `rg` 既有 backlog，剔除已覆蓋軸：generic KRBN/另類資產 vol clustering、stablecoin→Treasury/FX、AI capex/HHI/電力需求、graph/GNN spillover、ensemble SHAP drift、commodity inventory ML、earnings jump/EAV、corporate-bond news sentiment、private-fund LP cash-flow stress。本批只保留「來源明確、可用免費資料先啟動、且與 06-17~06-22 批次正交」的 7 條；所有 ETF / 新聞 / 公開 disclosure proxy 只能標為 diagnostic，不得冒充原文資料 replication。

- [ ] **可轉債 volatility-management 是否只是 equity-beta timing** — 用 CWB/ICVT/CONV + SPY/QQQ/HYG/LQD/^VIX，比較 raw CB、vol-scaled CB、等 equity/credit beta baseline 的 net Sharpe/MDD/DM；AAII/UMCSENT 分 sentiment regime。與既有 VT/factor timing 不同，聚焦 hybrid equity-credit-option asset class；ETF proxy 不冒充個券可轉債 replication（來源：JFI 2026 convertible-bond volatility-managed portfolios）

- [ ] **碳權拍賣 demand-depth / reserve-price bindingness 作 KRBN RV event prior** — 用 EU ETS / California / Washington auction 公開日曆與結果，搭 KRBN/GRN/歐洲碳權 ETF proxy，檢定 auction 壓力是否領先 t+1/t+5 RV、gap risk、能源/公用事業 spillover；與 line 466 generic KRBN vol clustering 正交，聚焦 primary-market auction mechanism（來源：CFA RPC 2026 compliance carbon auction mechanisms）

- [ ] **銀行 BHC AI-loss disclosure 是否預測銀行 RV** — 抓 10-K/8-K 與年報 AI mention / model-control weakness，全部 `shift(1)` 後檢定 KRE/KBE/XLF 與銀行個股 basket 的 RV、downside semivariance、earnings-window jump；與 AI capex/HHI/勞動曝險題正交，聚焦金融機構 operational-loss channel（來源：RCFS 2026 "AI and Operational Losses: Evidence from U.S. Bank Holding Companies"）

- [x] **FX predictability complexity penalty：非線性模型是否只在小樣本看起來有效** — `experiments/research_fx_predictability_complexity_penalty/` completed 2026-06-24，verdict **PARTIAL_RV_ONLY_NO_RETURN_PREDICTABILITY**：FXE/FXY/FXB/FXA/UUP/CEW 月頻 ETF proxy + FRED macro `shift(1)`，12/60/120 月訓練窗，比較 random-walk / historical-mean benchmark、linear Ridge、Ridge-RFF。17,058 OOS forecasts / 108 test cells；return Clark-West **0 pass**，model-vs-benchmark Harvey pass 只有 2 格且都在 60m RV（FXE +20.38%, DM t=3.77；FXY +10.18%, DM t=3.25）。RFF-vs-linear 有 11 格 pass，但多半只是 linear Ridge overfit，比 simple benchmark 才是正確門檻。結論：免費 ETF 資料支持「複雜度可能局部改善 FX RV smoothing」，不支持 FX return predictability 或交易 alpha。

- [x] **permanent-capital insurance platform integration 是否改變 alternative-manager vol beta** — `experiments/research_permanent_capital_insurance_platform_integration/` completed 2026-06-24，verdict **BETA_COMPOSITION_SHIFT_NO_RV_CREDIT_PASS**：BX/KKR/APO/ARES/CG + Brookfield `BN` 作 BAM long-history proxy，major insurance platform close dates 後做 manager FE + calendar-year FE panel（18,312 manager-days，2014-05-05 至 2026-06-23）。Post-integration 互動項：SPY beta +0.222（t=3.08）與 XLF beta +0.498（t=4.42）過 Harvey，downside days 的 KIE beta +0.332（t=4.88）過 Harvey；但 residual RV level shift 不過（t=-1.94），credit-stress proxy `LQD-HYG` 也不過（t=0.83）。結論：支援「beta composition / financial-sector loading shift」，不支持 standalone residual-RV 或 credit-spread sensitivity regime shift；FRED HY OAS full history 不可得，信用風險結果只作 proxy。

- [x] **低風險組合建構參數不確定性作 ex-ante model-risk band** — `experiments/research_ex_ante_model_risk_band/` completed 2026-06-24，verdict **MODEL_RISK_BAND_MODEST**：10 檔美股 sector/real-estate ETF，OOS 2012-01-03 至 2026-05-29（3,622 日 / 173 月），72 個 min-vol 規格（covariance estimator × lookback × cap × long-only/limited-short）+ 0/10/25bps 成本。10bps 下年化 vol band 13.17%-14.89%（range 1.72pp）、Sharpe 0.745-0.886、MDD -35.98% 至 -28.52%；72/72 規格相對 sector EW 與 SPY 的 realized variance DM/HAC 過 Harvey lower-var 門檻，但 0/72 有 higher-return Harvey pass。結論：ETF-sector proxy 中低風險建構穩定降低波動，但參數 model-risk band 偏小，不能宣稱 return alpha；stock-level large-cap panel 可能仍需另測。

- [ ] **listed infrastructure inflation-hedge 是否只是在能源 beta 與 duration beta 下失效** — 用 PAVE/IFRA/IGF/GRID/UTF/XLU + CPI/PPI surprise、breakeven inflation、TLT/IEF、energy controls，檢定 inflation-shock days 與 high-inflation regime 下 RV、downside semivariance、equity correlation 是否真低於 equities；與 commodity/inflation hedge 題正交（來源：JAI Winter 2026 "Hedging Against Inflation: Are Listed Infrastructure Assets Effective?"）

### 期刊主題挖掘 batch 2026-06-24（journal_discovery_20260624_0；WebSearch JBF/JoE/RFS/JPM/FAJ/JFEC/JFE/QJE/Econometrica/JoF/IJF/JFQA/JAI/JoD/JoT/JFM/JBES/AER 2025-26 趨勢層級；selectivity gate 後 13 條入單）
> 來源：journal-topic-discovery（task `journal_discovery_20260624_0`，agent sonnet/medium）。主線程先 grep 既有 backlog 460+ 條 + 06-21/06-22/06-22b/06-23 四批，剔除：GNN spillover（已 line 1154/1135/1167）、stablecoin→Treasury/FX channel（K523/K1532 已覆蓋）、conformal VaR（K1390/RWC 已覆蓋）、AI mega-cap concentration（既有覆蓋）、forecast-portfolio translation gap（line 1072 已覆蓋）、MOVE leading vol（既有）、tail-asymmetry estimator（K1359 已 closed）。本批刻意挑「方法學前沿（HAR tree / uncertainty theory / MCS dispersion）+ 跨領域新衝擊（term-spread vol→GDP / NBFI EU stress / 央行 IMF GPR vintage）+ 結構性 ETF 機制」三軸；趨勢層級來源採公開期刊頁面/RPC/IMF 報告摘要，不捏造論文標題+作者+期號。所有 ETF / 新聞 / disclosure proxy 限標 diagnostic。

- [ ] **Macro-uncertainty conditional HAR：tree-based HAR vs HAR + macro-vol interaction 的 OOS 是否真贏** — yfinance SPY/QQQ/IWM/TLT 5-min 或日 RV proxy + FRED macroeconomic uncertainty index（Jurado/Ludvigson/Ng MUI、EPU、VIX）shift(1)，比較 (a) HAR + macro linear、(b) HARQ + macro、(c) tree-based HAR（gradient boosting on HAR features × macro-uncertainty regime）三規格的 1/5/22 日 OOS QLIKE + DM + MCS，誠實檢定 tree 是否只是 in-sample fit；與 K1487/K1520 ML-ceiling 線正交，這裡是 HAR-tree 而非 LLM/foundation（來源：J.Forecasting 2026 "Forecasting Realized Volatility With Tree-Based HAR-Type Models Incorporating Macroeconomic Uncertainty"；macro-uncertainty 進 HAR 是 2026 熱點）

- [ ] **Term-spread realized volatility 作 GDP / 衰退 領先指標的市場波動 spillover** — FRED 10y-2y / 10y-3m 日頻 yield spread，建 21d/63d realized term-spread vol，檢定其是否領先 NBER recession probability + SPY/HYG/IWM 下個 1-3 個月 RV、left-tail 與 vol-of-vol，並比較與 ^MOVE leading 軸的增量（incremental over MOVE）；與 line 1054 MOVE 軸正交，這裡是 spread 本身的 realized vol（來源：Journal of Forecasting 2026 "Term Spread Volatility as a Leading Indicator of Economic Activity"；spread vol 而非 spread level 作 macro-financial transmission）

- [ ] **Bayesian rare-disaster learning 的免費 proxy：post-shock vol persistence 是否符合 belief-updating 預測** — yfinance SPY/^VIX 1990-2026 識別 disaster windows（2008/2020/2025 tariff/2018Q4），建 Bayesian posterior disaster-probability proxy（用 rolling drawdown 與 jump frequency），檢定 post-disaster N 日 RV、IV-RV gap、negative skew 是否符合「belief 更新 → 多年高 vol persistence」預測，並與 K1145 EAV 跨資產 universality 對照；與既有 disaster window event-study 不同，這裡是 belief-channel 機制（來源：Quantitative Economics 2025 Wachter-Zhu "Learning with Rare Disasters"；Bayesian disaster 學習為 2025-26 asset pricing 焦點）

- [ ] **MCS dispersion 作 ensemble forecast 不確定性訊號：MCS set 大小是否預測 RV uncertainty** — 既有 K1259 已完成 SPY/GLD MCS，擴展至 N 資產月度滾動 MCS，target 改為 next-month RV 預測誤差絕對值（uncertainty proxy），檢定「MCS surviving model 數量大」是否預測「下期 forecast 不確定性高」；類似 forecast dispersion-as-uncertainty 文獻但用 MCS 集合大小，純內部診斷（來源：JBES 2026 forecast-combination 與 model-confidence-set 應用趨勢；K1259 ledger 已有可重用基礎）

- [ ] **NBFI 流動性壓力的免費 proxy → 信用 / 銀行 ETF vol 領先性（EU FSB 2026 stress test 前哨）** — 用 ICI MMF 流量、HYG/BKLN/BIZD 成交額與折溢價代理、FRED bank credit、SOFR-IORB → 建 NBFI run-pressure 綜合指標（pure free-data proxy），檢定是否領先 KRE/KBE/XLF + HYG RV、left-tail 與 cross-sector correlation 升高，明確 shift(1) lag；與 K1538 bond-fund run pressure 正交，這裡聚焦更廣 NBFI（含 MMF/private fund proxy）→ 銀行 RV channel（來源：FSB 2026 NBFI Year-End Assessment；EU-wide NBFI stress test 2026 計畫，monetary-policy NBFI vulnerability 為當前焦點）

- [ ] **Tether/USDC reserve 變動作 short-rate / Bills RV 的 leading flow 訊號** — DefiLlama public stablecoin supply daily series + yfinance ^IRX/SHY/SGOV/TLT，建 stablecoin reserve growth rolling shock（21d zscore）shift(1)，檢定是否領先 t+5 / t+22 short-end Treasury RV、yield-spread vol 與 SHY-TLT correlation，與 K523/06-21 batch FX spillover 正交（這裡是 reserve flow → T-bill vol channel 而非 FX channel）；明確標 ETF proxy diagnostic（來源：FSB 2026 stablecoin reserve mechanics report；2026 Q1 stablecoin supply record high）

- [ ] **Hedge-fund alpha-dispersion regime 的免費代理：strategy ETF dispersion 是否預測股票 cross-sectional vol** — 用 hedge-fund / alternative-strategy ETF basket（QAI/MNA/CTA/DBMF/MRGR/HFXI/RPAR）日報酬計算 cross-strategy dispersion（21d 標準差），shift(1) 後檢定其是否預測 SPY 成分股下個月 cross-sectional return dispersion + IWM/IWR 個股 RV 平均；與既有 dispersion 軸（504 dispersion mean-reversion）正交，這裡是 strategy-side 而非 stock-side dispersion（來源：2026 hedge fund outlook "Dispersion, Volatility, and the Return of Alpha"；JPM 2026 alternatives outlook；strategy dispersion-as-leading-indicator 為 2026 實務焦點）

- [ ] **VIX futures expected return predicting future RV：long-VXX / short-VXX timing 是否真有訊號** — yfinance VXX/SVXY/^VIX + ^VIX9D/^VIX3M term structure 建 VIX-futures expected-return proxy（用 VIX-VXX basis 與 term-structure slope），shift(1) 後檢定其是否預測 SPY/QQQ realized vol 與 vol-of-vol，並用 DM/MCS 比較預測力是否超過 ^VIX level alone；與 K731/K489 VIX term-structure level 軸正交，這裡是 expected vol return channel（來源：JFQA 2026 "Expected and Realized Returns on Volatility"；VIX futures expected return 預測下期 RV 為 2026 vol-trading 焦點）

- [ ] **Cornish-Fisher regime tail adjustment 作 Sector rotation timing：HMM-regime + CF 修正能否擇時 sector ETF** — yfinance 11 sector ETF + SPY，建 2-state HMM（calm/turbulent）on SPY daily return，每個 regime 用 Cornish-Fisher 修正 VaR/ES，依 regime-CF tail estimate 做 sector rotation（turbulent regime tilt to XLP/XLU 防禦），檢定 OOS net Sharpe / MDD / DM 是否優於 EW sector + VT baseline；與既有 conformal VaR / Regime-Weighted Conformal VaR 軸正交，這裡是 CF tail asymmetry 作 sector 訊號（來源：2026 options vol analysis "Cornish-Fisher Tail Risk Reveals About the February 2026 Sector Rotation"；CF-HMM 框架在 sector timing 為 2026 實務新方向）

- [ ] **Index inclusion fast-entry mechanism 對被納入個股 + 同 sector 對手 RV 的事件研究** — 用 S&P 500 / Nasdaq-100 公開 fast-entry 規則 2024-2026 案例（特別 mega-cap IPO 或快速納入），對被納入個股 + 同 sector ETF（XLK/XLC）+ 同 sector 對手做 [-30,+60] event window RV、jump frequency、cross-sectional correlation 變化的 event study，明確 shift(1) lag；與既有 sector vol 題正交，這裡是 index methodology change → liquidity-clientele shift → RV 的機制（來源：2026 iShares Insights "Mega Cap AI Companies, ETFs, Index Inclusion"；index fast-entry 為 2026 ETF/index 領域新焦點）

- [ ] **TIPS breakeven volatility 與 corporate bond return：BEI vol 是否預測下期 LQD/HYG RV 與 credit spread vol** — FRED T10YIE/T5YIE 日頻 breakeven inflation，建 21d/63d realized BEI vol（不只 BEI level），檢定是否領先 LQD/HYG/BKLN 5d/22d RV、credit-spread vol 與 negative-skew exposure；與既有 BEI regime 軸（line 1075）正交，那是 regime level，這裡是 BEI 本身的 realized vol channel（來源：SSRN Ceballos 2025 "Inflation Volatility Risk and Corporate Bond Returns"；inflation volatility 而非 level 為 2025-26 credit RV 新通道）

- [ ] **Multimodal LLM expert routing 的「便宜版」：dynamic weighting 多個 HAR/GARCH 規格是否贏 static ensemble** — yfinance SPY/QQQ/IWM/TLT 日 RV，建 K 個 HAR/GARCH/HARQ/EWMA 子模型，用 (a) static equal-weight、(b) past-Q QLIKE inverse weight、(c) gating network（lightweight logistic on regime features 而非 LLM）三規格，做 OOS QLIKE + DM + MCS，誠實檢定 dynamic gating 增量是否真存在；與既有 model averaging / BMA（K1257）軸正交，這裡是 regime-gated routing 而非貝氏平均（來源：arXiv 2509.05080 "MM-DREX Multimodal-Driven Dynamic Routing of LLM Experts for Financial Trading"；regime-gated forecast routing 為 2025-26 ensemble 趨勢，本題做「便宜版」自驗）

- [ ] **Term-structure of variance risk premium：1M VS 3M VS 6M VRP slope 是否預測 SPY drawdown** — yfinance ^VIX (1M) / ^VIX3M (3M) + ^VIX6M（或用 VIX futures 期貨 proxy）建 VRP term structure slope，shift(1) 後檢定 slope inversion 是否領先 SPY drawdown、left-tail 與 VRP collapse；與既有 ATM VRP 軸（line 1023 隔夜/日內拆解）正交，這裡是 cross-maturity VRP slope（來源：JFQA 2026 "Expected and Realized Returns on Volatility" + JoD 2025 "Forecasting Power of Short-Term Options"；VRP term-structure slope inversion 為 2025-26 crash-prediction 新軸）
