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
- [x] ~~**Model Confidence Set (MCS) / SPA / Reality Check**~~ → **K1259 完成 2026-04-20**：Phase 1 ledger 2741 DM rows from 236 K / 16 assets；Phase 1.5 main-thread asset backfill 38%→78%；Phase 2 HLN-2011 Variant A (parametric bootstrap seed=42, B=1000) 18/20 runs (0050.TW MSE 空 — 全 K400-K1258 無 TW MSE DM rows = new gap)。**關鍵發現**：(a) **SPY QLIKE α=0.10 88/100 models survive** — A4f family 全入 superior set (A4f-VIX9D-N/t, A4f_Local, A4f_N, A4f_VIX, A4f_t_2step, A4f_t_joint)，HAR/EWMA/GJR-t/MEM decisively eliminated；(b) **GLD MSE 窄 set {M2_GJR_t, M3_GAS_t, M4_HAR_RV_X}** — MSE 比 QLIKE discriminative 因 ledger 薄；(c) **α=0.10 vs 0.20 sets identical** everywhere（stopping-p ≥ 0.23）— marginal relaxation 無效；(d) **CF-Rolling 不在 ledger** — K500+ 敘事王者模型命名不一致錯過抽取（follow-up: 命名 canonicalization）；(e) Variant B (reconstructed per-day loss + stationary bootstrap) skipped — <20% per-day loss coverage。Commits: def4695b (Phase 1), efd370f4 (Phase 1.5), 5314dbd3 (Phase 2). Parent task_6055e98ca841 子任務 A+B 完成；Phase 3 (feed general-audience article) 獨立 queue。**等候 Codex 04-24 code review 才 finalize knowledge.json 寫入**（K1257 同規則）。
- [ ] **Realized semivariance / signed jumps** — Barndorff-Nielsen-Kinnebrock-Shephard 分解 RV 為 upside/downside 部分，測 asymmetric vol 更純粹。需 5-min 數據（2026 Q2 HAR-RV 解鎖後可開）。

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
- **Factor tilts NULL**（K89: MTUM/VLUE/QUAL/USMV 全不改善 50/50）
- 台灣市場：**K55/K82/K88 台灣 VT 指南 + TSMC 集中度測試**

### 面向 D: 理論貢獻
- Gamma-mechanism proposition（VT alpha 機制）— **K53: r=0.564 (N=22) 確認但衰減**
- Diversification amplification（index vs stock gamma）
- MDD vs Sharpe 區分（mechanical vs skill）— **K49: 雙通道分離**
- Anti-tautology 驗證
- **VIX sufficient statistic**（25+ 次確認：K43/K48/K57/K61/K65/K80/K84 + K730 cross-asset + K731 term structure + K732 behavioral sentiment + 歷史 15 次）
- **VT 保險費定價**（K41: ~4%/yr 恆定，K62: 利率依賴，K74: 80% 時間落後是正常的）

### 面向 E: 即時市場分析
- Hormuz 危機追蹤
- 危機類型分類（financial/pandemic/monetary/oil）
- 即時 VaR/ES 預報
- Paper trading 績效追蹤

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

**新 Paper 3 可發表主張**（narrative state machine: decision_ready_user_input_needed）：
> 「Joe copula with upper-tail structure significantly beats DCC for flight-to-safety pairs (equity-bond, equity-gold), but not equity-equity pairs, due to portfolio-mixing mechanism.」

**用戶決策選項**：
- (A) **Reframe Paper 3 為 asset-class-specific copula study** — 需 K1100e 擴驗 N=10-15 pairs 的 λ_L threshold (已加 task)，最有力實證+可發表 J. Financial Econometrics 等
- (B) 保留原 **periodic return / spot-futures** 方向（PRS 延伸），K1100 系列當 appendix null
- (C) 結合 A+B 雙 subsection，copula + periodic 都寫

等用戶 confirm 後才進 body rewrite（state machine 規則：decision_made_awaiting_body_rewrite）。

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
- [ ] K515 發現 overnight gap alpha 真實（SPY-conditioned 10.73bp/day, t=4.06）但 ETF TX 18.55bp 致命（K625 更正）
- [ ] **台指期貨（TX futures）TX cost 只有 ~2-3bp** → 可能可行！
- [ ] 需要：台指期貨歷史日頻數據（TAIFEX 或 yfinance TWF=F?）
- [ ] 測試：buy TX futures at close, sell at open, SPY-conditioned
- [ ] 如果 Net Sharpe > 0.5 + cross-OOS 4/5 → 第一個可能上架的新策略

## Codex 論文審查記錄
→ 完整審查詳見 `docs/research_archive/codex_paper_reviews.md`

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
| **P5** | **vt-crowding-abm** | 🟡 **撤回 READY (2026-04-27 cross-paper meta-eval)** — v1 reproduce GREEN 33/33 + v2 latex 4.4★ + citation 0/2/5 仍 valid，但 NotebookLM portfolio-lens 揭露 ABM 設計性問題（70% threshold = λ/γ 數學結果非 emergent）→ verdict 撤回到 3.5-3.8★ + FRL 40-50%。v3 必修 ABM framing rewrite + 非VT對照 + portfolio 區隔 (1-2 週 fundamental refactor) | 不投稿；v3 round Tier B 推進，per memory `project_paper_portfolio_decisions_2026_04_27` |
| **P6** | **prg-periodic-garch** | ✅ **READY_FOR_SUBMISSION 全 gate PASS (2026-04-27, 9 paper 首篇)** — v1-v4 完整 4 輪 paper-review-cycle + v4.1 batch fix 收斂; supabase status `ready_for_submission`; 6/6 gate PASS (latex 4.2★ + citation GREEN + cross-paper meta + FRL desk-accept 35-45% + K1260 fair-info + no tautology). **Reproduce gate 全 PASS**: reproduce.py 22 checks (15→22 加 K1260 §4.5 GJR-X 7 checks) / reproduce_report.json `match_rate=100%` / `alert_level=green` / audit_date 2026-04-27. PDF=15p / bibitems=22 / abstract=184 words / 5 tables / 7 equations. SUBMISSION_READY.md + send-alert df592119 已發 user. **主線程準備就緒** — 等用戶 confirm 投稿 FRL → status `submitted` | 等用戶 confirm 投稿 FRL；或維持 ready + 每月 continuous review loop |
| **P7** | **vix-sufficiency** | ✅ **READY — GREEN 98% (98/100)** + Sub1-6 closed (bundle + dividend + 5 divergence decisions + Table 6 K752 rewrite + source binding + reproduce.py synced) | 等用戶 confirm 投稿 |
| **P4ins** | **vt-insurance-cost** | ✅ **READY — GREEN 100% (9/9)** (2026-04-19 88.9%→100% via L184 footnote + reproduce tolerance 5→10 bps 反映 documented dual-convention) | 等用戶 confirm 投稿 |
| P1 | leverage-direction | 🟡 **0 MISMATCH** + 28 MATCH + 9 NOTE + 19 UNTRACE (structural data-limit) | C1 ✅ K1256 3-spec / C2 ✅ Kupiec rounding / ✅ 7 figure scripts bundled MATCH / C3-C5 Tables 1/6/7/8/11/14 需 new experiments |
| P3 | vt-trend-following | 🟡 **0 MISMATCH** (83%, 34 UNTRACE structural) | Table 4 M5 ✅ hybrid BAB / Table 3 period ✅ errata; 剩 Table 5 13-market + Table 6 MDD bootstrap 需 new experiments |
| P2 | taiwan-vt | 🟡 **0 MISMATCH** (6→0 本 session, 69% verified + 24 UNTRACE structural) | ✅ TSMC/0050.TW/TWII γ 3-spec footnotes + reproduce.py NOTE reclass / ✅ SSVS PIP UNTRACEABLE / ✅ GJR+Normal viol NOTE; 剩 24 UNTRACE 需 Table 4/5 VT + Sec 6 macro experiments |
| P8 | volatility-absorption | 🔴 61.3% amber + **CRITICAL errata 識別** (2026-04-20 re-verified: 46 MATCH / 12 MISMATCH / 17 UNTRACE / 75 total — 無 drift since 2026-04-19) | `errata_pending.md`: CRITICAL (controlled t Harvey cross -3.14→-1.17) + HIGH (T10 2020-26 sign flip) + MEDIUM (10+ drifts). Path B 推薦 research-honest body revision。**Still awaiting user Path A/B/C decision**. |
| P9 | garch-x-vix | 🟡 submitted under review, snapshot 53.8% / live 84.6%, **shelf errata ready** | `errata_pending.md`: 0-11% DM t drift SPY/QQQ/GLD/USO, Harvey qualitative invariant — 無 body edit 直到 R1 reviewer response |
| **P10** | **crypto-fear-channel** | ✅ **NEW GREEN — reproduce gate 100% (7/7)** + Claude pre-body review 5H/8M/5L/6-Codex-gaps 歸檔 review_history/pre_body_v0/ + body_v0_intro.tex H1+H3 fixes applied (lag 1-5 asym distinct from symmetric 1-10 + QR sign-reversal 4-quantile enumerate 8.5× reframe) | body drafting（Sec 2-6 主體）待 Codex 04-24 wake handles Gap A-F (claim-to-JSON / k1025.py read / lit review 15-20 DOIs / outline reconcile / reproduce scaffold ✓ done / data snapshot) |

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
