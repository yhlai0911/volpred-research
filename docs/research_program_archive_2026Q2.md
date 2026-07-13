---
title: Research Program Archive — 2026 Q2
source: research_program.md sections extracted 2026-04-17
purpose: 已完成研究階段 + 歷史重大研究結論 + 舊 Next Session Priorities。主檔 research_program.md 僅保留 active 狀態。
---

# Research Program Archive — 2026 Q2

本檔是 `research_program.md` 瘦身後的歷史封存，保留：

- 已完成研究階段索引
- 重大研究結論（歷史版本，含後續翻轉 / 已被推翻的條目）
- 舊 Next Session Priorities（2026-03-31 + 2026-04-13 版）

_當前 active 研究方向、priorities、行為準則見主檔 `research_program.md`_。

## 研究發現與成果
詳見 `research_findings.md`（已加入知識索引 embedding）

### 已完成研究階段（存檔，查詢見下方路徑）
| 類型 | 位置 | 說明 |
|------|------|------|
| 完成 Phase 詳細記錄 | docs/research_archive/completed_phases_2026-03.md | 含所有 Phase O~K + K426-K753 逐實驗結果 |
| 知識庫（發現） | storage/memory/knowledge.json | 3,189+ 筆，記錄**發現了什麼**。grep 搜尋：grep -i '關鍵詞' storage/memory/knowledge.json |
| 經驗庫（教訓） | storage/memory/experiment_experiences.json | Exxx 編號，記錄**學到了什麼**（成功/失敗原因、方法論教訓、避坑指南） |
| 知識索引（向量搜尋） | storage/knowledge_index/ | LanceDB，用 build_knowledge_index.py 重建 |
| 實驗腳本 | experiments/k*.py | 119+ 個 Python 腳本，每個可獨立執行 |
| 實驗結果 | experiments/k*_results.json | 每個實驗的完整 JSON 結果 |
| Feed 文章 | storage/reports/feed.json + storage/reports/mile_*.json | 562+ 篇文章（含 content） |
| 研究記憶 | storage/memory/thinking_journal.json | 研究決策推理過程 |
| 論文 | paper/leverage-direction/ / paper/taiwan-vt/ / paper/vt-trend-following/ | 三篇論文 LaTeX 源碼 |
| 數據 | yfinance 線上（每次實驗即時下載）+ data/vixtwn/ + storage/5min_data/ | 日頻 OHLC + VIXTWN + 5-min |
| 策略 Paper Trading | storage/paper_trading.json | 9 策略 × 7,950+ entries |
| 同步狀態 | storage/.supabase_sync_state.json | Supabase 增量同步狀態 |

**Phase O~K(K507) 共 ~340 個實驗，詳見 `docs/research_archive/completed_phases_2026-03.md`。**
核心成果：GJR-X(VIX9D) best forecaster, MCS 5-model set, VIX sufficiency 32x, 50/50 irreducible, Prediction≠Application 4x。

### 最終工具指南（K426-K495, cross-OOS validated）
| 任務 | SPY | Other equity | Non-equity | Taiwan |
|------|-----|-------------|------------|--------|
| **Forecasting** | **GJR-X(VIX9D) ★★★** | GJR+HAR ensemble | GARCH(1,1) | GJR alone |
| **VaR** | **GJR + Student-t ★★★** | GJR + Student-t | GJR + Student-t | GJR + Student-t |
| **VT Strategy** | 12/VIX（#9 irreducible） | 12/VIX adapted | Asset-specific | 8.63/VIX |

**★★★ K799-K804 最終結論（2026-04-01）：**
- **預測選模型**：GJR-GARCH（QLIKE #1，DM vs GARCH t=-3.25 Harvey PASS）
- **風險管理選分配**：Student-t/Skewed-t（VaR Trinity PASS，df=5-8 for equity）
- **兩個維度獨立選擇** — 預測精度和風險管理是正交問題
- K804 跨資產驗證：equity/commodity 3/4 PASS，BTC 例外（右偏需不同分配）
- K800 conformal 是 artifact（Codex 抓到），K802 分配修正才是正解
- K799：六層評估發現 GJR QLIKE #1 但 VaR Normal FAIL（1.79%）。MCS 含全部 5 模型。
- K800：Conformal heuristic 看似修復（0.80%）→ K800v2 推翻（artifact，Codex 抓到）
- **K802：正確解法 = GJR + Skewed-t/Student-t 分配**。QLIKE 不變 + VaR 1.20% Trinity PASS。
- **結論**：預測選模型（GJR），風險管理選分配（Skewed-t）。兩個維度獨立。
- 待驗證：跨資產 + 整合進 Paper 1/5

**K801**：Event-Surprise VIX Shock Guard — NULL（12/VIX 本身即 shock-guard）

## 重大研究結論（持續更新）

### 1. VT 策略本質 — drawdown insurance 不是 alpha generator（2026-03-29 K687/K697/K700/K701）
- K687：正確 lag 後，沒有 VT 策略在 Sharpe 上打敗 BH 50/50（0.545）
- K697：VIX 預測 vol（corr 0.57）但不預測 direction（corr 0.04）——daily alpha 理論不可能
- K701：weekly/monthly 也一樣（direction corr 全部<0.04）
- K688：VT 在 CRRA utility γ≥5 時勝出——drawdown protection 對風險厭惡投資人有價值
- K693：歷史 paper_trading 9935 筆修正 same-day→next-day return
- K700：Codex 審查防止 3 個 false breakthrough（37.5% false positive rate without review）

### 2. 50/50 SPY/GLD 不可動搖
K2/K16/K19/K24/K54/K63/K64/K89 共 **8 次獨立驗證**（見 line 191）+ K534 理論解釋（correlation dynamics 不可預測）。任何新策略的 Sharpe 門檻 = 50/50 Sharpe 0.545，打不過就不上架。

### 3. Smooth-weight 設計原則（最可靠）
**連續權重策略（12/VIX、Risk Parity、Piecewise VT）幾乎不受 signal lag 的影響。** 機制：每天權重變化 <5%，即使 lag 方向錯也無害；反觀 binary regime-switch 策略 lag 錯一天 Sharpe 可差 0.5+。教訓來自 K679（VIX Percentile Sharpe 1.68→lag 修正後 0.355，100% artifact）和 K618/K621/K698 共 4 次 lag bug。**設計新策略優先 smooth-weight，避免 binary switch**。

### 4. Proxy-robust 模型比較（Patton 2011 標準）
- GARCH/GJR：原生 target σ²（r² 是無偏估計）
- MEM：原生 target |r| 或 r²（r² 直接可比 GARCH）
- HAR-RV：原生 target 5-min RV
- **跨模型必做 QLIKE on r²**（詳見行為準則「模型比較公平性標準」段）
- K782 教訓：Proxy 比模型更重要——HAR 在 |r| target DM=-15.45（K530）但在 r² target 全輸 GJR

### 5. 風險管理必做 VaR + ES 雙指標
不能只做 VaR——VaR 無法反映尾部形狀。必須用 Fissler-Ziegel (2016) joint score 同時評估兩者。詳見「經濟顯著性評估」段和 K1041/K1092 DCC-A4f 實驗。

### 6. Paper 2 firm-selection 路線完整 dead-end（2026-04-13 K1067 系列 7 實驗）
**A4f-EAV 在 Taiwan equity 有 pooled-level signal，但 cross-sectional heterogeneity 不可用 observable firm characteristics 預測。**
- K1067 (TSMC null) → K1067b (UMC +39%) → K1067c (MediaTek 反方向 monotonicity FAIL)
- K1103 (τ-lag bug-fix STABLE) → K1104 (N=24 fabless p=0.039)
- K1106b (cherry-pick p=0.004) → **K1109 (pre-reg N=31 BH-adj p=0.278 REJECTED)**
- **K1113 (firm-level 6 covariates 全 5/5 FAIL, CV R²=-0.66)**
- → 任何 observable firm characteristic（market cap, beta, sector dummy, earnings CV, momentum）都不能預測 EAV 增益
- → 需要 **private data**（retail flow, governance opacity, analyst dispersion 細節）才能 firm-select
- **Paper 2 final**: pooled A4f-EAV + cluster SE by firm 當 default，不寫 Tier 規則
- **教訓 E052/E053**: pre-registration 2-commit audit trail 救一個 cherry-pick artefact

### 7. Paper 3 copula-GARCH 不可推廣（2026-04-13 K1100 系列 6 實驗 + K1115）
**Lai 2024 PRS copula edge 是 TAIFEX 市場 microstructure 特有現象，不是通用 methodology。** E055 三條件全 REJECTED：
- (a) Near-collinear ρ>0.95: K1100f SPY-ES (corr=0.97) 也 NULL（portfolio variance degenerates as ρ→1）
- (b) Tail-dependent: K1100b 5 pairs 含 SPY-QQQ λ_L=0.589 全 NULL（aggregation 把 tail dep 平均化）
- (c) Single-asset path-dependent: K1115 SPY VaR breach clustering NULL（GARCH-t 已 absorb clustering）
- **K1100g_d1/d2 chain**: 「找到 anchor → OOS 推翻」3 級 correction（E059 LRT-vs-DM divergence trap）
- **Paper 3 status**: 待用戶決策（A reframe negative paper / B TAIFEX microstructure / C abandon）
- **教訓 E055/E056/E060**: pivot depth L1-L4，當前需 L4 framing change

### 8. Paper 4 Universal IV Sufficiency Compendium（2026-04-13 NEW，10 實驗 × 5 asset class × 2 application）
**no public alt-data source improves over native implied volatility for vol prediction or portfolio allocation.**
- **Forecasting NULL**: K473 (Trends VAR) + K750 (Trends weekly) + K789 (Trends overlay) + K504 (STLFSI4) + K1116 (EPU+NFCI+STLFSI on SPY) + K1098 (VIXTWN on 0050.TW) + K1118 (GLD/TLT/BTC native IV sufficient) = 7 evidence
- **Allocation NULL**: K1121 (4 alt-data strategies vs 50/50 baseline, bootstrap p>0.16) = 1 evidence
- **K1116b verified**: TLT M4 NFCI 唯一 positive (+3.74) 是 publication-delay artifact，corrected → +1.96 NS。Universal NULL 統一無例外
- **Active harm pattern**: SPY M4 NFCI 修正後從 -3.00 → -3.61，alt-data 不只 silent 是 actively harmful
- **Paper 4 status**: 主線程寫作 priority 1，建議標題 "Universal Sufficiency of Native Implied Volatility for Weekly Realized Volatility Prediction: A 10-Experiment Compendium"
- **教訓 E061/E062**: knowledge-base precheck 救重複實驗 + FRED publication delay (NFCI shift(5), EPU shift(2)) 必查

### 10. Taiwan microstructure findings（2026-04-13 K1124+K1125+K1128）
**TAIFEX OFI 對 diffusive vol 和 jump 方向相反（Cont-Tankov decomposition 實證）**
- K1124：|OFI| ↑ → 下一 5-min RV ↓ (反 US 市場直覺，Taiwan mean-revert after unwind)
- K1125：|OFI| ↑ → jump 機率 ↑ (DM t=+2.82, sell-side asymmetric)
- K1128：High-VIX tertile DM t=+3.59 超 Harvey，但 COVID OOS 超出 IS 範圍 (E064 教訓)
- 合：Cont-Tankov (2004) decomposition 在 TAIFEX 實證成立，diffusive 主導解釋 K1124 total RV 降
- **Paper Taiwan microstructure** candidate（US vs Taiwan 對比、sell-side asymmetry）
- Triple-gate 擋住 K1124/K1125/K1128 各自 null，但 meta-finding (decomposition + regime) 可寫

### 11. GAS compendium: 8+ assets 全 null（2026-04-13 K437/K1038/K1129）
**Generalized Autoregressive Score (Creal-Koopman-Lucas 2008) 不是通用替代品**
- K437/K1038：equity 4 assets NS
- K1129：USO/GLD/UNG/BTC 4 assets triple-gate FAIL；**BTC DM t=-4.58 Harvey 反向**（score-driven 在 crypto extreme regime 反 hurt）
- Hafner-Wang (2023) commodity GAS claim 在 2021-2026 OOS 未重現
- **不單獨 paper**，併入 Paper 4 vix-sufficiency 作「alt-model NULL」第三類（alt-data forecasting + alt-data allocation + alt-model）
- 通則：score-driven downweight 大 shock 在含極端 events 的期間反向傷害（K1038 equity + K1129 BTC 共同 pattern）
- H4 VaR violation rate 低是「分配假設好」不是「vol predict 好」——兩個不同 task

### 26. K1174 WEAKENS K1170 press-concentration claim：3.28σ → 0.03σ in empirical partial replication（2026-04-14 K1174）
**真實 GDELT 數據未支持 K1170 hardcoded PCR**
- K1174 GCP BigQuery 無 auth → fallback GKG raw CSV 每日 12:00 UTC 1/96 slice (1.04%)，131/413 events 覆蓋
- Real Cross-market Spearman ρ(hardcoded, real) = -0.257 (N=6, p=0.62) — 完全不對齊甚至微負相關
- **EU-JP pair test**: hardcoded +0.45 (3.28σ) → empirical +0.005 (0.03σ, Welch t=+0.03 p=0.98) — **崩潰**
- US 最大落差 (hardcoded 0.85 vs real 0.24) 推測因 AMC 盤後財報新聞在 T+1 UTC, 12:00 UTC slice under-sample
- **Verdict: INSUFFICIENT_COVERAGE with direction-of-evidence WEAKENING K1170**
- Sample 太小 (EU n=3, JP n=2) 無法決定性 overturn，但 direction 明確不 support K1170 claim
- **K1170 PARTIAL_CONFIRMED 應降級為 OPEN question**，3-level mechanism 第三層 (press) 從 claim 降為 hypothesis
- 前兩層仍穩固：institutional ownership (between-market) + analyst coverage (within-market)
- **既有 press article mile_45060685 已加 caveat**
- 衍生 K1175 (full 96-files-per-day scan 或 GCP-authed BigQuery decisive)

### 25. Paper 2 三層 mechanism 浮現：press concentration 解 EU-JP residual（2026-04-14 K1170）→ K1174 WEAKENS
**EU-JP pair gap (institutions_pct 幾乎相同但 θ_rel 半數差距) 由媒體集中度解釋**
- K1170 GDELT API 429 → fallback hardcoded PCR (Reuters Institute 2024 + Pew + K1153 prior)
- Per-market PCR: EU 0.317 / TW 0.65 / JP 0.767 / US 0.85 / BR 0.567 / CH 0.567 / CA 0.65 / HK 0.667 / KR 0.65 / IN 0.517
- **EU-JP pair**: ΔPCR=+0.45 (3.28σ) 跟 Δθ_rel=+0.25 sign consistent — **first regressor to discriminate EU from JP**
- Joint between-market R²: inst_pct 0.196 → +PCR 0.239 (incremental +0.04)
- Cross-market N=10 Spearman ρ(PCR, θ_rel)=+0.062 NS — 新興市場 break ladder
- Developed N=6 ρ=+0.899 p=0.015 (drop CA outlier)
- **Verdict PARTIAL_CONFIRMED**: pair gap supported, universal driver rejected
- **3-level mechanism revised**:
  1. Between-market institutional ownership (developed ladder, K1167/K1168)
  2. Within-market analyst coverage (per-stock, K1166/K1168 t=+3.63)
  3. Press concentration (EU-JP residual, K1170)
- E072: GDELT rate-limit fallback + hardcoded prior circularity risk
- 衍生 K1174 (GDELT BigQuery export 取真實 PCR)

### 24. Paper 2 two-level mechanism STRENGTHENED：N=7 markets 確認 between/within R² super-clean 切換（2026-04-14 K1165）
**N=4 → N=7 把 Spearman p 從 0.20 推進到 0.052 緊貼門檻**
- K1165 +AU/KR/CA/HK 擴展，AU 因 yfinance earnings 0/10 droppped → N=7 final
- Spearman ρ(institutions_pct, θ_rel)=+0.750 p=0.052 (Drop-EU LOO ρ=+0.943 p=0.005)
- Per-market table: TW 6.36e-5 / HK 5.21e-5 / KR 1.27e-4 / EU 4.07e-5 / JP 1.41e-4 / CA 3.13e-4 / US 1.91e-4
- Per-stock panel (N=133, +24 new) log_analyst β=+1.07e-3 t=+3.24 PASS Harvey (replicates K1166 t=+3.56)
- **Two-level R² 分解 super-clean**:
  - Between-market: institutions_pct 63.1% vs log_analyst 15.8% (institutions 強 4×)
  - Within-market: log_analyst 7.2% vs institutions_pct 0.4% (analyst 強 20×)
  - 兩個 channel 在 between/within 邊界乾淨切換 — 強 evidence for K1167 hypothesis
- **Verdict**: STRENGTHENED (CONFIRMED 留 N≥10 K1168)
- Paper 2 §5 narrative **READY commit**
- 衍生 K1168 (+BR/CH/IN N≥10), K1171 (AU via Alpha Vantage)

### 23. Paper 2 two-level mechanism 浮現：between-market 用 institutional + within-market 用 analyst（2026-04-14 K1167）
**K1166 within-market analyst 確認後，K1167 用 institutional ownership 解 cross-market puzzle**
- 4-market institutions_pct ranking: TW 0.247 < EU 0.416 < JP 0.425 < US 0.750 **完全匹配** 2-cluster split
- Spearman ρ(institutions_pct, θ_rel)=+0.80 p=0.20 (N=4 限制 power) — 優於 analyst ρ=+0.40
- Per-stock joint panel: log_analyst β=+1.14e-3 t=+2.71 (PASS); institutions_pct β=-2.73e-3 t=-0.93 (NS)
- **Two-level mechanism**:
  - **Between-market** retail-vs-institutional → cluster split
  - **Within-market** analyst coverage → per-stock θ_EAV_i
  - Institutions_pct **不 subsume** analyst — 兩通道互補
- EU-vs-JP gap (0.14 vs 0.39) institutions_pct 也未完全解釋 (EU 0.416 ≈ JP 0.425) — 殘差留 K1170 press-concentration
- N=4 preliminary, K1165 升 P1 補 N≥8 markets
- **E071**: yfinance major_holders 0.2+ 結構踩坑教訓

### 22. Paper 2 mechanism 翻轉再翻轉：per-stock refit CONFIRMED within-market（2026-04-14 K1166）
**K1164 REJECTED 純粹是 σ² tautology artifact，移除後 analyst hypothesis 在 within-market 層級成立**
- K1166: 110 stocks per-stock θ_EAV_i refit (no shared pooling) + Engle-Ghysels-Sohn (2013) E[g]=1 normalization
- Pooled Spearman ρ(log_analyst, θ_EAV_i) = +0.241, p=0.012 (vs K1164 ρ=+0.40 p=0.60)
- US 獨市場 ρ=+0.575 p=0.001 PASS Harvey
- Panel OLS coef log_analyst β=+9.68e-4 t=+3.56 p=0.0006 **PASS Harvey 3.0**
- 全 4 markets ρ>0 無反向；JP 100% |t|>2 80% Harvey
- Per-stock vs pooled-shared θ_EAV ratio 6-16x（EGS normalization 差異），ordering 保留
- **Mechanism verdict**:
  - K1153 within-market analyst hypothesis **CONFIRMED**
  - cross-market 4-market rank inversion (EU 21 analysts > JP 14.5 但 EU LOW JP HIGH cluster) **仍 open puzzle**
- **E070 教訓**: shared-coef pooled spec 評估個股 mechanism 必踩 σ² tautology；per-stock refit + EGS E[g]=1 才是 ground truth
- K1167 升級 P2 (retail-vs-institutional 解 cross-market puzzle)
- K1169 NEW P1：Paper 2 §5 主線程改寫（K1164 降為 tautology demonstration, K1166 升為 main mechanism test）

### 21. Paper 2 mechanism 仍 OPEN：analyst hypothesis 也被推翻（2026-04-14 K1164）→ 已被 K1166 翻轉
**K1153 後第二次推翻——cluster mechanism 尚未找到**
- K1164 檢驗 analyst coverage × media density 假說 (K1153 §5.4 提出)
- 4-market analyst median: TW 7.5 / EU 21.0 / JP 14.5 / US 32.5
- 假設預測順序 TW<EU<JP<US，但實際 EU(21) > JP(14.5) 且 cluster 反轉 (EU LOW vs JP HIGH) — **rank-ordering inversion**
- Cross-market Spearman ρ=+0.40 p=0.60 無 power
- Panel coef β=-0.149 但是 σ² tautology artifact (θ_rel=θ_EAV/σ² 機械 rank-inverse)，**不可採信**
- **Mechanism question remains OPEN**：K1153 §5.4 必須改寫為「analyst hypothesis tested in K1164 also rejected」
- 衍生 K1165 (N≥8 markets), K1166 (per-stock θ_EAV refit 移除 tautology), K1167 (retail-vs-institutional ownership proxy via 13F/MOF/ECB/FISC)

### 20. Paper 2 四市場 + 雙 cluster taxonomy（2026-04-14 K1153 EU）
**EU 加入四市場全 PASS，但 K1152 quarterly hypothesis 被推翻**
- EU (DAX+CAC+FTSE, N=18 due yfinance earnings 稀疏) pooled θ_EAV = +4.07e-5, bootstrap t=+4.19 PASS
- Placebo +14.77σ p=0/60；3 EAV-def monotonic, drop-5×5 stable
- **Four-market direction universal confirmed** (TW+US+JP+EU all PASS + placebo p=0)
- **θ_rel cluster**: TW 0.167 / EU 0.137 / JP 0.388 / US 0.586
- EU 是純季報但 θ_rel 落 TW cluster → **K1152 quarterly-cadence hypothesis REJECTED**
- 新假說：media concentration × analyst coverage 密度（US 季報媒體報導 + I/B/E/S coverage 最密）
- Paper 2 narrative: "four independent markets + refined two-cluster θ_rel taxonomy; quarterly cadence 不是 cluster 主因"
- 衍生 K1163 (EU local filings 改 N=30), K1164 (analyst coverage + media mechanism test)

### 18. Paper 2 relative-magnitude verdict: 方向 universal + 量級 market-specific（2026-04-13 K1152）
**Scale-adjusted θ_rel 仍顯著差異：quarterly vs mixed reporting cluster**
- K1145/K1147/K1150 三市場 absolute θ_EAV 差 3× — 只是 scale artifact 還是真 magnitude 差異？
- θ_rel = θ_EAV / avg_σ²: TW 0.1673 [0.109, 0.247] / US 0.5862 [0.395, 0.859] / JP 0.3875 [0.354, 0.482]
- avg_σ² 三市場近乎相同 (3.26e-4 ~ 3.80e-4) — scaling 沒校正差異
- Wald H0 (equal θ_rel): χ²(2)=29.19, p≈4.6e-7 bootstrap p=0.000 — 決定性 reject
- CI overlap: TW∩US=F, TW∩JP=F, US∩JP=T → quarterly cluster (US+JP) vs mixed (TW)
- **Paper 2 narrative 雙層修正**: "方向 universal（三市場均顯著正向）+ 量級 market-specific（quarterly reporting institutional density 主導）"
- 衍生 K1153 EU 4th market, K1156 TW 季報 sub-sample converge test

### 19. Paper 2 binary-sufficient universality 跨市場確認（2026-04-13 K1157）
**JP 完美複製 US K1151 — 三市場 binary EAV 全 PASS，US+JP continuous 全 NS**
- JP TOPIX N=30 同 panel 同 design：binary θ=+1.25e-4 boot t=+13.03 PASS vs continuous θ=+4.76e-6 boot t=+1.32 NS, ΔAIC=-2551 strongly favors binary
- Placebo z=+1.53 p=0.067 跟 US K1151 (+1.60) 量級一致
- Drop-5 sign-flip when removing SoftBank (outlier-driven main-spec signal)
- **Universality verdict**: 三市場 binary PASS + 兩市場 continuous NS replication
- Paper 2 narrative 升級：「Announcement-day long-run variance channel reflects information-processing friction (attention/IV crush/scheduled hedging), not scaling with market-aggregated EPS surprise magnitude — universal across US and JP」
- 衍生 K1162 (analyst-coverage-high sub-sample mechanism test)

### 17. Paper 2 mechanism narrowing: binary sufficient, surprise size 無關（2026-04-13 K1151）
**Continuous EAV surprise spec 全面失效 — 機制非 surprise-size driven**
- US S&P 500 N=30 (K1147 cache) 同 panel: continuous |Surprise%| z-score winsor p99 取代 binary EAV
- Binary θ=+1.72e-4 boot t=+4.49 p=0.000 (K1147 confirmed) vs Continuous θ=+5.26e-6 boot t=+1.11 p=0.413
- Placebo continuous z=+1.60 p=0.10 (跟 null 無法區別)
- **ΔAIC binary - continuous = -5479** (binary 嚴格更佳)
- **Mechanism evidence**: announcement-day vol clustering 跟 surprise size 無關 → 解釋為 attention-based vol spike 或 IV crush 一致性 resolve，非 information-shock-magnitude 驅動
- Paper 2 narrative 微調：「effect characterised by announcement-day information-processing friction rather than surprise-magnitude-scaled information shock」
- 衍生 K1157 (JP universality verification), K1161 (options IV crush as alt continuous regressor)

### 16. Paper 2 三市場全 PASS：true global volatility regularity（2026-04-13 K1150）
**TW + US + JP 三市場全 universal-magnitude PASS — 真 cross-market regularity 確認**
- JP TOPIX top-30 pooled θ_EAV = +1.413e-4，bootstrap (n=150) t=+11.99，95% CI [+1.29e-4, +1.76e-4]
- Placebo 60 reps: 觀測值 = +38.6σ from null mean，p=0/60 decisive
- 3 EAV-def monotonic shrinkage 同 K1145 TW pattern
- Drop-5 × 5 seeds θ ∈ [+1.34e-4, +1.47e-4]，全部 t > 18
- **Three-market table**: TW (+6.36e-5, t=+5.24, +13.6σ) / US (+1.91e-4, t=+4.50, +70.7σ) / JP (+1.41e-4, t=+11.99, +38.6σ)
- Magnitude ratio US/TW=3.0, JP/TW=2.2, JP/US=0.74 — 同 1e-4 量級
- JP 高 t (+11.99) 觸發 Rule #5 self-challenge: TOPIX top-30 同質性 > S&P 500 (NVDA/TSLA outlier 不存在)，所有 150 bootstrap draws 嚴格 >0，三層一致可接受
- **Paper 2 final narrative**: "Three independent equity markets, 5 robustness layers each, magnitudes differ ~3× but direction uniformly positive — global volatility regularity where GARCH-MIDAS τ component absorbs market-wide announcement-day variance premium invisible at firm level but robust at panel level"
- K1146 主線程改稿升 P1; 衍生 K1153 EU + K1156 cover-fig

### 15. Paper 2 cross-market 升級：global volatility regularity（2026-04-13 K1147）
**TW K1145 + US K1147 雙市場全 PASS — universal regularity 確認**
- US S&P 500 top-30 pooled θ_EAV = +1.91e-4，bootstrap t=+4.50，95% CI [+1.29e-4, +2.80e-4]
- Placebo 60 reps: 觀測值 = +70.7σ from null mean，p=0/60 (比 K1145 +13.6σ 強 5×)
- 3 EAV-def: 1d 峰 +1.91e-4 / 3d +7.7e-5 / 5d +8.3e-5 — US conference call 同日集中釋出
- TW (+6.36e-5) vs US (+1.91e-4) 方向 match，量級比 3.0 (US 大型股 σ² 規模較大 + 季報密度)
- **Paper 2 升級 narrative**: "Two independent equity markets (TW N=31 + US N=30), 5 robustness layers each, consistent with global volatility regularity where GARCH-MIDAS τ component absorbs market-wide announcement-day variance premium invisible at firm level but robust at panel level"
- 衍生 K1150 (TOPIX 第三市場), K1151 (continuous surprise), K1152 (relative-magnitude), K1153 (EU)

### 14. Paper 2 SAVED：universal-magnitude pooled effect（2026-04-13 K1145）
**Pooled MLE 揭露 firm-level idiosyncratic SE 掩蓋的 universal signal**
- N=31 K1109 pre-reg stocks pooled A4f-EAV，shared θ_EAV，stock-FE on (m_i, GJR_i)
- **Pooled θ_EAV = +6.36e-5**
- Cluster bootstrap (n=150) **t=+5.24** primary inference (Hessian Wald t=14.14 may inflate)
- Bootstrap 95% CI [+4.13e-5, +9.38e-5] excludes 0
- Placebo permutation 60 reps mean=+1.36e-6 ≈0; observed = +13.6σ from null mean; one-sided p=0/60
- 三 EAV-def (1d/3d/5d) θ 線性遞減 +6.4e-5 / +3.8e-5 / +1.7e-5 符合 smear-over-days 物理直覺
- Drop-5 stocks × 5 seeds θ ∈ [+6.21e-5, +7.96e-5], t ∈ [+12.17, +14.12]
- vs single-stock K1109: mean θ=+4.64e-5 SE=1.15e-4 (t=0.40 NS); pooled SE=1.21e-5 (9.5x reduction)
- Codex review passed
- **Paper 2 narrative pivot**: 從 dual-NULL 改為 "EAV is universal-magnitude population-level constant, invisible at firm level due to large idiosyncratic SE"
- **E069**: pooled panel reveals signal hidden by firm-level noise floor — 對 dual-NULL 假設前必跑 pooled spec
- 衍生 K1146 (paper rewrite, main thread), K1147 (US S&P validation), K1148 (continuous surprise EAV), K1149 (PCA factor competition)

### 13. Paper 2 dual-NULL 確認（2026-04-13 K1114→K1140）→ 被 K1145 推翻
**Cross-sectional + temporal θ_EAV heterogeneity 雙 NULL**（已過時 — 見 §14 K1145）
- K1114 rolling 2-yr A4f-EAV on TSMC/UMC/MediaTek 報 3/9 BH-PASS (UMC trend t=3.06, MediaTek t=4.51, TSMC regime KS p=0.009)
- K1140 三層 robustness 重檢：(1) Newey-West HAC L=5/24/48; (2) Spearman block-permutation; (3) Block-bootstrap block=24 gold standard
- 結果：HAC L=24 後 1/9 倖存 (MediaTek t=4.33)，block-boot 後 0/9 PASS — K1114 全為 96% overlap artifact
- K1067 三檔 mean pattern 真實但 within-sample artifact，無 systematic 來源
- Paper 2 contribution 定位轉為 rigorous null：「after N=31 sector ANOVA + 5 covariates + rolling HAC + block-boot, no systematic θ_EAV heterogeneity survives MTCorrection」
- **E068**：HAC alone 對 high-overlap rolling 不夠，必加 block-bootstrap 第二門

### 12. Universal robust-method NULL：非 score-driven 也失敗（2026-04-13 K1136）
**「alt-model NULL」擴張到 score-driven + non-score-driven 兩家族**
- K1136 fair-test 設計：M3 GARCH-MIDAS-X vs M1 GJR-N on r²（close²-native 公平）；M4 HAR-RV-X vs M5 HAR-RV on Parkinson（within HAR-family control, 孤立 VIX marginal）
- **Fair Test #1 (MIDAS)**: 0/4 PASS, DM t=1.23/0.94/0.62/-0.32
- **Fair Test #2 (HAR-within)**: 0/4 PASS, DM t=1.65/-0.88/0.74/0.52, GLD 反向
- **命名升級**：Paper 4 從 "GAS-specific fail" 升為 "Universal robust-method NULL across score-driven AND non-score-driven"
- 證據合計：8 unique assets × 4 proxies × {GAS/MIDAS/HAR-X} = 一致 NULL
- **Meta-lesson (E066)**：首次跑 M4 看到 Parkinson t=2.5~13 誤判為 breakthrough，實為 model-target mismatch 造成的 mechanical win；加入 M5 within-family control 才揭穿
- 亦修 VIX monthly-lag double-shift bug（`monthly.shift(1)` + "latest ≤ d" 重複 shift）

### 9. 防 in-sample data mining 的雙重門檻（2026-04-13 K1100g_d1/K1115/K1116 教訓）
**LRT 顯著 + DM-HLN<2 = overfit 警訊**（E059）：
- LRT 用全樣本 likelihood 易 overfit residual variance → χ² 易顯著
- DM-HLN test forecast accuracy improvement，prospective fit assessment
- 兩者 divergence > 1.5 → 必做 OOS 才能 publish
- K1100g_d1 in-sample LRT χ²=12.48 p=0.0004 → K1100g_d2 OOS LRT 0.00 p=1.00（推翻）
- K1115 IS Kupiec p~0.92 grid fit → OOS p<0.01 同 pattern
- K1116 M5 IS QLIKE -2.84 → OOS +59.9（24× degradation）
- **規則**：Paper-publishable finding 在啟動文章 agent 前必做 OOS PASS

## Next Session Priorities（2026-04-13 update）

### P0: 用戶決策待回（不可繼續挖同 direction）
- **Paper 3 strategic decision** (A negative paper / B TAIFEX microstructure / C abandon)
- **Paper 4 main thread 啟動寫作** (compendium 10 實驗 ready)
- **TSMC 法說 04/16** 事件文章準備（04/17 截止）

### P1: 高價值新方向（避免 Paper 2/3/alt-data 死局重蹈）
- 面向 G NLP sentiment（用真新聞 headlines + FinBERT，非 Google Trends）
- 面向 G market microstructure（OFI from existing TAIFEX tick）
- 面向 I7 Taiwan cross-border hedging
- Paper 6 crypto fear 完稿 (K639/K746b/K1025 素材齊備)

## Next Session Priorities（2026-03-31 起）

### P0: 時間敏感

| 項目 | 說明 | 截止日 |
|------|------|--------|
| **HAR-RV 正式實驗** | 5-min 數據 ETA 04/11 達 60 天門檻 | 04/11 |
| **TSMC 營收 04/10 解讀** | 營收公告後解讀文 | 04/11 |
| **TSMC 法說 04/16** | 預告+解讀文 | 04/14, 04/17 |
| **FOMC 04/28-29** | 預告文 04/26，事後解讀 04/30 | 04/26, 04/30 |

### P1: 高價值

**論文修正：**
- [ ] **Leverage-Direction**（K628 已瘦身 64→52p）：加入「VT is insurance」框架
- [ ] **Taiwan VT**：K636 修正 amplification（gamma vs vol level）、TX cost 已修正

**平台經營方向（基於 analytics：192 views, 3 users, 10 reactions）：**
- [x] **SEO 完成**：Google Search Console 驗證 + sitemap + 6 頁 metadata + FAQ/Article/Breadcrumb schema + admin noindex + /portfolio 公開路由 ✅ 2026-03-31
- [x] **分享按鈕**：LINE/Facebook/X/Twitter + 複製連結 ✅ 2026-03-31
- [x] **首頁預設「一般讀者」tab** ✅ 2026-03-31
- [ ] **加強入門內容**：「從零開始」是最熱門文章之一，應建立 /guide 頁面
- [ ] **減少學術文章比例，增加實務操作指南**：收藏(7)>按讚(3) = 讀者當工具書用
- [x] K705 GAP-03：StrategySelector CAGR 降級，突出 Sharpe/MDD ✅ 2026-03-31
- [x] **Umami Analytics** 上線（cloud.umami.is，免費方案） ✅ 2026-03-31
- [ ] **Umami API 自動化**：寫 scripts/analytics.py 包裝 Umami REST API，方便終端查看訪客數據（**2026-04-04 週五檢視數據後決定**）

### P2: 研究新方向

**高優先（有明確下一步）：**
- [x] **★ Paper: Multiplicative GARCH-X(VIX) — 規格比較與 VRP 解釋**（K988 發現，初稿 31p 完成 2026-04-10）：
  - **核心發現**：K988/K988b 比較 17 個規格。A4f（VIX² + free ω）冠軍 DM t=+4.48 vs GJR。τ=VIX² 最佳（維度一致）。GARCH-MIDAS 不優於單 lag。
  - **已完成**：跨資產（K994 QQQ/K997 GLD PASS）、VaR/ES（K995 scorecard 3/4）、Codex 審查（K999）、VRP 驗證（K998 NULL）。初稿 31 頁完成。
  - **論文待做**：E(g)=1 理論推導、Conrad & Loch 比較、Student-t df 聯合估計
- [ ] **HAR-RV 正式實驗**：K744 驗證數據 94% clean，K745 pipeline 通過。SPY 51 天（ETA 60 天 ~04/07），需 100+ OOS days ~05 月。到時重跑 HAR-RV vs HAR-ABS vs GJR 的完整比較
- [ ] **Paper 6: Crypto Fear Channel**：K746b 確認 BTC vol asymmetrically Granger-causes VIX。結合 coupling 增加 + tail dependence，可寫成「加密貨幣市場對傳統金融的波動率溢出」論文
- [ ] **Paper 5 正式撰寫**：草稿 31p 已完成。Codex 建議 J. Forecasting。需要：統一 pipeline（不只 VIX，含 HAR-RV/GARCH benchmark）、多重檢定控制、replication package

**新完成（2026-04-10）：**
- [x] **K1013: Bayesian SSVS GARCH-X Variable Selection** — NULL，所有 PIP<0.01。GJR persistence=0.956 已捕捉殘差方差。不矛盾 K988（joint MLE vs 殘差修正不同機制）
- [x] **K1014: HAR-PD Path-Dependent Features** — Path features 惡化 HAR（multicollinearity trap）。vix_gap 唯一顯著（t=7.27）。HAR 仍是 QLIKE(r²) 最強。衍生：HAR+vix_gap 簡約模型
- [x] **K1015: VIX9D+VIX3M Dual-Factor A4f — NULL**。θ₂=0，退化為單因子。DM t=-0.298 (Dual) / t=-1.333 (Slope) 全 NS。VIX9D 完全吸收 VIX3M。VIX sufficiency #30
- [x] **K1016: HAR+vix_gap — In-Sample Overfit**。vix_gap IS t=18.43 但 OOS QLIKE(r²) 惡化（1.831 vs HAR 1.616）。|r| MSE 改善（DM=-2.869 未達 Harvey）。86.5% 時間 VIX>realized 導致系統性高估。教科書級過擬合
- [x] **K1019: MS(2)-GJR ★ — Regime Dynamics Real**。MS-GJR 顯著勝 GJR（DM t=-3.20 PASS）但輸 A4f-VIX9D（DM t=+2.75 NS）。Calm: γ=0.60; Crisis: pure β=0.83。Regime prob 與 VIX 弱相關 r=0.225。衍生：MS-A4f 結合兩者

- [x] **K1016b: HAR+vix_gap corrected**。|vix_gap| DM t=-4.20***、vix_gap² DM t=-5.57*** 顯著勝 HAR，但 A4f 仍稱霸（DM t=+7.11***）。線性 vix_gap ≡ VIX level
- [x] **K1020: MS(2)-A4f NULL**。結合 regime+VIX 反而惡化。VIX 已包含 regime info
- [x] **K1021: A4f df joint ★**。df≈8.5，QLIKE 不變但 VaR 從失敗→通過。Paper 9 建議 df=8
- [x] **K1022: A4f 跨資產 6/6 QLIKE 改善**。Student-t 下 DM 個別未達 Harvey 但 VaR 6/6 PASS
- [x] **K1023: E(g)=1 理論框架 ★★**。VRP auto-correction 證明非 relabeling
- [x] **K1024: Refit insensitive ★**。QLIKE spread 0.021%，63d 最佳
- [x] **K1025: Crypto Fear Channel ★★★**。BTC down-vol→VIX asymmetric
- [x] **K1026: Conformal VaR ★★**。92% pass rate vs parametric 58-83%。不是 K800 artifact
- [x] **K1027: Drawdown Recovery K735 修正** — K735 rho=-0.49 確認為 artifact（IS=0.00, OOS=-0.14）。VIX reactive not predictive。Protection overlay 不如 12/VIX
- [x] **K1028: DCC-A4f Multivariate** — DCC-A4f 勝 DCC-GJR（DM t=2.58）但 DCC≈CCC（SPY-QQQ 相關太穩定）。A4f 共用 VIX 因子=隱式 common factor

- [x] **K1029: 金融股早期預警 MIXED**。Granger F=18.98 存活 VIX 控制，但 GARCH-X 反而惡化。VT overlay +1.5%。Regime indicator 非 predictor
- [x] **K1030: ★★ Sub-Period 7/7 全勝**。QLIKE +4.8~8.1%，平均 6.52%。非 COVID 驅動。Paper 9 robustness 完備

**中優先（新研究主題）：**
- [ ] **K1016b: HAR+vix_gap 修正版**：修正 M4/M5 bug，重新評估 vix_gap 在正確 QLIKE 下的效果
- [x] **K1018: Robust VT**：Sharpe 0.594 vs baseline 0.575（DM t=-1.47 ns）≈ BH 50/50。不上架。Sensitivity PASS 但 alpha 不顯著。VT=insurance confirmed
- [x] **K1019: VIX Regime 轉換預測** — NULL。Naive persistence F1=0.91 unbeatable。12/VIX smooth weight 已內建 regime 資訊。Regime-switching 反而更差（Sharpe 0.882 vs 0.918）
- [ ] **Drawdown Recovery 修正版**：K735 被 Codex 推翻（fake OOS + timing misalign）。修正方法論後重做
- [ ] **跨國 VIX sufficiency**：K752 證明 US 33 年成立。在其他市場（VSTOXX、VNKY、VIXTWN proxy）驗證？
- [ ] **Alternative data**：K750 Google Trends 是反應式。嘗試 Reddit/Twitter 情緒或 options flow
- [ ] **Intraday alpha**：5-min 數據就緒後，測試日內 VIX-equity lead-lag（K751 overnight 有 +0.45% R²）

**低優先（長期探索）：**
- [ ] **VT 與 ESG 整合**：ESG 評分高的公司是否有不同的 gamma？
- [ ] **Agent-Based Model 正式版**：K742 用簡化 Kyle's lambda。正式 ABM 可模擬異質投資人
- [ ] **因果推論**：用 DiD/RDD 分析 Fed 升息決議對 VIX regime 的因果影響
- [ ] **Climate vol**：極端天氣事件頻率增加是否改變 vol 動態？

### P3: 長期待辦

**研究：**
- [ ] Rough Volatility multivariate（需理論準備）
- [ ] Decision-focused policy learning（contextual bandit）
- [ ] 除權息季節研究（06 月）

**平台：**
- [ ] Feature gating（V0.7）
- [ ] API rate limiting（V0.9）
- [ ] Email/LINE 訂閱（W3.1）

---

## [Archive] Codex/Gemini/用戶 歷史建議（2026-03-26 → 2026-04-14）


### Codex 第 7 次建議：從預測轉向策略（2026-03-27）[提出: Codex GPT-5.4]
**核心洞見**：瓶頸不是預測 RV，而是判斷何時 forecast 值得交易。
- [ ] **Conditional Dispersion Trade**：預測 correlation risk premium mispricing → index vs sector options。需 sector ETF options data。
（已完成項目見 archive：K730 Cross-Asset Vol Momentum, K763 Regime-Switched Carry Filter, K760 Alt Risk Premia Rotation, K762 Action-First ML）

### Codex 第 8 次建議（2026-03-31）[提出: Codex GPT-5.4]
**5/5 全 NULL**。詳見 `docs/research_archive/completed_session_2026-04-01.md`。
核心結論：VIX-based 風險管理工具無法改善 50/50 baseline。連續調整 >> binary 切換。

### Codex 第 5 次建議（2026-03-26）[提出: Codex]
- [x] ~~Decision-focused policy learning~~ → **K798 NULL**。DM 全 NS。12/VIX irreducible #7。
- [x] ~~Two-clock decomposition~~ → **K791 NULL**。隔夜/盤中分解不改善預測。
- [ ] **Options surface state variables**：⚠️ BLOCKED: 需 options 歷史數據
- [ ] **Dispersion / correlation-regime trading**：sector dispersion, correlation breakdown trades
- [x] ~~Event-surprise strategies~~ → **K801 NULL**。|ΔVIX|>2σ 多餘，12/VIX 自帶 shock guard。#8 irreducible。

Codex 優先排序：(1) Decision-focused policy (2) Overnight/intraday decomposition (3) Dispersion trading

### Gemini 第 2 次建議（2026-03-31，行為金融 + 方法論 + 實務工具）[提出: Gemini]
- [ ] **Retail Reflexivity & Gamma-Driven Skew**：0DTE 散戶 flow 導致 delta-hedging 連鎖反應，可能打破 VIX sufficiency。量化 "Volatility Gap"（VIX-implied vs flow-induced realized move）。⚠️ BLOCKED: 需 order flow 數據
- [ ] **Path Signatures for Rough Volatility**：用 rough path theory 的 signature transform 編碼日內價格路徑的幾何特性，捕捉 HAR 遺漏的路徑依賴性。需 5-min 數據（ETA 04/11）
- [x] ~~Convexity-Adjusted Insurance Premium Tool~~ → **K811 完成 混合結果**（⚠️ Codex 2 HIGH: VVIX pre-2012 + cost calc mislabel）。VoV-cond 方向可信（減少保險費、smooth 優於 binary），但 40% 數字需 K811v2 修正。

### Gemini 第 1 次建議（2026-03-26，台灣特色 + 免費數據）[提出: Gemini]
- [x] ~~Taiwan Price Limit Latent Volatility~~ → **K790v2 完成 NULL**：>5% 天數僅 0.9%，GJR asymmetry 已捕捉。DM 全 NS。
- [x] ~~FRED STLFSI4 Macro Stress Regime~~ → **K795 完成 NULL**（⚠️ Codex 2 HIGH：pre-2004 GLD + DM 實作錯誤，數字不可靠但方向正確）。Binary Sharpe 0.466 vs 0.313 但 DM 未通過。VIX sufficiency #24（方向確認，精確統計待 K795v2）。
- [x] ~~VIX→Taiwan Vol Spillover Strategy~~ → **K817 完成 NULL**。Spillover 存在（r=0.376）但 OTC return 不可交易（77-93% alpha 在隔夜 gap）。DM 全 NS。8.63/VIX 仍最佳。
- [ ] **TXO Put-Call Ratio Mean-Reversion**：台指選擇權 P/C ratio 作為散戶恐慌指標，極端值做反向操作。Data: TAIFEX 網站
- [x] ~~EWT vs 0050.TW Vol Arbitrage Spread~~ → **K792 完成**：Granger YES (F=28.4) 但方向反（高 ratio → vol 下降）。Trading 虧損。Mean reversion 陷阱。

### 用戶提出方向
- [x] ~~什麼是好的交易策略？~~ → **K793 完成**：8 維度評估 6 策略。BH 50/50 #1 (75.4), Risk Parity #2 (73.7), Piecewise #3 (54.0，唯一正 stress)。單一 Sharpe 遺漏大量 tradeoffs。
- [x] **HAR-RV with 5-day RV** [提出: 用戶, 2026-03-31] → **K782 完成**：GJR-GARCH multi-step 在 5d/22d/66d 全勝 HAR。日頻 squared returns 做的 RV 不足以讓 HAR 發揮優勢——需等 5-min 數據。
- [x] ~~MEM（Multiplicative Error Model）~~ [提出: 用戶] → **K805 完成**：AMEM-r² 數值最佳（QLIKE 1.4689 vs GJR 1.4824）但 DM=-2.19 未通過 Harvey t>3.0。非對稱性（leverage）比模型類別更重要。MEM 不提供超過 GJR 的統計顯著改善。
- [x] ~~K501/K818: SSVS for Return Prediction~~ [提出: 用戶] → **K818 完成 NULL for SPY**。OOS R²=-1.47%（EMH barrier）。SSVS 選出 HYG(0.93)+VIX_change(0.78)。台灣 hit 62.1% 但 c2c gap artifact。SSVS 更適合 vol 非 return。
- [ ] Return prediction → trading strategy pipeline：如果方向準確度 > 55% → 可做 long/short 策略
- [ ] 跨資產 return prediction：SPY、0050.TW、QQQ
- [x] ~~K502/K812v2: US→Taiwan Lead-Lag Strategy~~ [提出: 用戶] → **K812v2 完成 乾淨 NULL**。OtC direction accuracy 50.2%（硬幣），lead-lag beta t=-0.25 (NS)。C2C Sharpe 3.51 → OtC -0.17（100% 信號在隔夜 gap）。方向正式關閉。
- [x] ~~K503/K810: VIX Mean-Reversion Strategy~~ [提出: 用戶] → **K810 完成 NULL**。12/VIX 本身就是 MR 交易。顯式 MR 策略增加 vol 和 MDD，得不償失。VIX spike 93.5% 回復但短期 NS。50/50 不可動搖 #10。
- 策略上架前必須：Cross-OOS ≥ 5 periods、3 年回測、Net Sharpe (after TX) > 0
- **不要輕易上架**——交易策略必須多次確認（cross-OOS + out-of-sample + sensitivity），避免上架後發現是錯誤

### Bayesian Subset Selection 方法論（用戶指定，2026-03-26）
- [ ] K433: **Bayesian SSVS for ARX-GARCH** — So, Chen, Liu (2006) JRSS-C, 55(2), 201-224. Latent binary indicator δ_i + MCMC 從 2^(p+q) 子集空間搜索最優外生變數組合。比 K113 逐一測試更有力。**進行中**
- [x] ~~K431/K813: Smooth Transition GARCH~~ → **K813 完成 NS**。In-sample LR=252 強烈顯著但 OOS DM=-0.11 NS。11 參數不優於 5 參數 GJR。結構發現：低 VIX 高 leverage(0.50)/低 persistence(0.39)，高 VIX 相反。QLIKE ceiling 持續。
- [x] ~~K432/K814: Bayesian MCMC GARCH~~ → **K814 完成**（⚠️ Codex 3 HIGH：P(γ>0) 是先驗 tautology、OOS h[0] leak、ESS/Geweke 錯誤）。框架有價值但數字不可靠。需 K814v2 修正 prior + 初始化 + 診斷。
- [ ] Bayesian Subset Selection for TARMA — Chen, Liu, Gerlach (2011) Computational Statistics, 26, 1-30. 擴展 SSVS 到 threshold + MA terms，16M+ 可能子集
- [ ] Threshold Variable Selection for Asymmetric SV — Chen, Liu, So (2013) Computational Statistics, 28, 2415-2447. Combined threshold variable Z_t = Σω_i Z_i，同時選 threshold 變數和模型結構。五個亞洲市場實證
- [x] ~~SSVS for Variance Equation~~ → **K821 完成 NULL**。0/8 外生變數 PIP>0.5。GJR variance equation 自足。VIX_level PIP=0.039。與 K484 internal（4/5 PIP=1.0）形成鮮明對比。
- [ ] Threshold GARCH with Bayesian Model Selection — 結合 2006+2013 方法：threshold GARCH + SSVS 同時選 regime 結構和變數子集

