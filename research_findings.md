## 研究結論（持續更新）

### SPY 最佳模型（2026-03-14）
| 目標 | 最佳模型 | QLIKE | VaR 1% |
|------|---------|-------|--------|
| 最高 QLIKE（忽略 VaR）| GJR-arch/Normal | -9.034 | 2.0% ✗ |
| QLIKE + VaR（單環境）| GJR/GED | -9.032 | 1.8% ✓ |
| 跨環境穩健性 | **GJR-HAR 或 70/30 組合** | -9.027 | 1.6% ✓ |

### 跨資產規律
- **Current γ 決定模型選擇**（比 skewness 或 asset class 更精確）：
  - γ > 0.10 → 用 GJR（SPY, QQQ when γ high）
  - γ < 0.10 → 用 GARCH（GLD in bull market, TLT, QQQ when γ low）
  - γ < 0 → 必須用 GARCH（GLD in fear-driven bull）
- **GLD leverage 是 regime-dependent**：牛市(恐慌驅動) γ<0 inverted，熊市(清算) γ>0 standard
  - 2007-2012, 2017-2026（牛市）: 93% negative
  - 2013-2015（熊市）: γ=+0.17~+0.30 STANDARD
  - Pre-2017 整體: 52% negative（mixed）
- 加密貨幣 → 規則不適用，需 FHS VaR

### 日頻預測天花板（Phase H 發現, 2026-03-15）
- **SPY 日頻 GARCH 天花板 QLIKE ≈ -9.034**（GJR-arch/Normal w=252 on 2023-2024）
- GJR 殘差 Ljung-Box z² 不顯著（p=0.76/0.94/0.97）→ 日頻結構已被完全捕捉
- DL (LSTM/GRU) 和 hybrid (GARCH-LSTM) 都無法改善殘差
- Realized GARCH 用 daily range proxy 也不足（需要 5-min RV）
- **突破天花板的唯一路徑：5-min 高頻 Realized Variance 數據**
- Window=504 是最佳實踐（滿足 ≥500 統計門檻 + 避免 regime change 污染）

### Gamma-Mechanism Boundary Conditions（2026-03-17, 提出: User, 執行: Claude）
12 資產（SPY, QQQ, GLD, TLT, EEM, IWM, EFA, EWJ, FXI, USO, BTC-USD, 0050.TW），OOS 2020-2025, LAGGED 12/VIX

**核心發現：Gamma 不能跨資產類別預測 VT 效果**
- 全樣本(N=12): gamma vs Sharpe improvement rho=-0.448 (p=0.14, n.s.)
- 全樣本(N=12): gamma vs MDD improvement rho=-0.287 (p=0.37, n.s.)
- Bootstrap 95% CI 均包含 0 → 統計上不顯著

**但在純股票資產內(N=6), gamma 仍然顯著預測 VT Sharpe：rho=+0.886 (p=0.019)**
- 股票資產（VIX corr < -0.4）: SPY, QQQ, EEM, IWM, EFA, EWJ
- 非股票資產（VIX corr >= -0.4）: GLD, TLT, FXI, USO, BTC-USD, 0050.TW

**原始 rho=1.000 (N=7) 結果的三個問題：**
1. 小樣本不穩定（N=7 的 Spearman 本身不可靠）
2. VIX 敏感度是混淆變量（高 gamma 資產恰好也是高 VIX 相關的股票）
3. 資產選擇偏差（原始 7 個以美股為主）

**已識別的 5 個邊界條件：**
1. VIX 非相關資產失效：gamma 對 GLD/TLT/0050.TW/BTC 的 VT 效果無預測力
2. MDD 改善是 universal 的：所有 12 個資產 VT 都降低了 MDD（+4.6pp 到 +58.9pp），與 gamma 無關
3. GARCH VT 的 MDD 改善由 base volatility 主導（rho=+0.944, p<0.001）
4. Gamma 穩定性問題：SPY gamma 從 0.33 下降到 0.20，QQQ 從 0.25 降到 0.16
5. 0050.TW 異常：gamma≈0 但 12/VIX Sharpe improvement +0.493（台股牛市效應）

**修正後的 proposition：**
- Gamma-mechanism 僅在**同質性高的股票型資產**內成立
- 跨資產類別時，VIX correlation（rho=+0.531, p=0.075）比 gamma 更具預測力
- MDD 改善是 VT 的 mechanical 效果，不需要 gamma 機制解釋

### 關鍵發現
- Parkinson RV proxy 低估 37%（overnight gap bias）
- EGARCH 假收斂原因：regime change 邊界的似然面平坦
- Multi-start MLE 改善自建模型 0.25-0.48%
- VaR violations 30% 來自不可預測事件
- FHS 解決 BTC 分配悖論（Normal/Student-t 都不行）

### VaR/ES 研究結論
- **Student-t(df≈5) 是 VaR 改善的最大因素**（-45.5%），Jump augmentation 冗餘（+0%）
- GJR w=504 + Student-t(5): **6/6 年 Basel III Green Zone** (2020-2025)
- Normal VaR: 33 violations (2.2%) → Student-t: 18 (1.2%) → +Adaptive: 14 (0.9%)
- Kupiec 整體 p=0.78，結果在 df≤7 範圍穩健
- VaR violations 30% 來自不可預測的外部事件（日圓平倉、Fed 鷹派）
- FHS 對 SPY+GJR 無效（殘差已近 Normal），但對 BTC 有效
- Jump component = 23% of SPY vol（解釋 VaR 結構性低估的根因）
- GARCH 預測精度 98.8%（vs 5-min RV 黃金標準驗證）
- 2026 YTD: 1 violation in 49 days (Jan 20 Trump inauguration)
- **★ CF-VaR (Cornish-Fisher expansion) 大幅超越 Student-t 和 Normal（Phase O, 2026-03-16）**
  - CF-VaR 是唯一在 1% 和 5% 都通過 Kupiec 的方法（5/5 資產）
  - SPY: CF 14 viol 0.9% (p=0.78) vs Student-t 26 viol 1.7% (p=0.01) vs Normal 38 viol 2.5%
  - QQQ: CF 10 viol 0.7% (p=0.16), GLD: CF 12 viol 0.8% (p=0.41), TLT: 18 viol 1.2% (p=0.46), EEM: 13 viol 0.9% (p=0.58)
  - CF 是 asset-specific：殘差 skew/kurt 越大→quantile 越保守（SPY -3.32 vs TLT -2.60）
  - EVT-VaR (POT+GPD) 反而比 Student-t 差（28 viol, p=0.003）——GPD 在 rolling window 不穩定
  - Estimation: GJR-GARCH(1,1) rolling, OOS: 2020-01-01 ~ 2025-12-31, 1507 days/asset
  - 排名：CF-VaR > Student-t(5) > EVT > Normal（at 1% level）
- **★★★ VaR Backtest Trinity: Kupiec + Christoffersen + DQ（Phase VaR_Trinity, 2026-03-17）**
  - 回應 Codex 批評「Kupiec alone is far too weak」——新增 Christoffersen 獨立性 + Engle-Manganelli DQ 檢驗
  - 7 資產 × 5 方法 × 3 測試 = 105 項回測，OOS 2020-2025，GJR-GARCH(1,1) 5% VaR
  - **FHS 是唯一 7/7 資產全通過三重檢驗的方法（21/21 測試全過，100%）**
  - Skewed-t 6/7（GLD Christoffersen fail），CF-VaR 6/7（GLD Christoffersen fail）
  - Student-t(5) 僅 2/7——系統性高估尾部（SPY 6.8%、QQQ 6.2% > 5% 名義），Kupiec 拒絕
  - GLD violation clustering：Normal/Student-t/Skewed-t/CF-VaR 都 fail Christoffersen（p<0.02），只有 FHS 通過（p=0.055）
  - BTC Normal VaR 完全失敗（3.3% 違反率，太保守，Kupiec p<0.001）
  - DQ 比 Kupiec 更嚴格（85.7% vs 88.6% 通過率），抓到 Kupiec 漏掉的問題
  - **修正先前建議**：df=5 固定對 VaR 覆蓋率有害，FHS 或 Skewed-t 更好
  - 排名（5% VaR 三重檢驗）：**FHS (7/7) > Skewed-t = CF-VaR (6/7) > Normal (5/7) > Student-t(5) (2/7)**
- **★★ Skewed Student-t 是唯一通過所有 6 資產 Kupiec 的方法（Phase O8, 2026-03-16）**
  - 6/6 pass：SPY, QQQ, GLD, TLT, EEM, 0050.TW 全部通過
  - CF-VaR 5/6（QQQ 過度保守 0.53%），Student-t 4/6，Normal 1/6
  - Skewed-t 通過 MLE 同時估計 df(eta) 和 skewness(lambda)，自動適應
  - SPY: eta=6.5, lambda=-0.19 | TLT: eta=77, lambda≈0 (近 Normal) | 0050.TW: eta=5.2, lambda=-0.05
  - 最終排名：**Skewed-t (6/6) > CF-VaR (5/6) > Student-t(5) (4/6) > Normal (1/6)**
  - Estimation: GJR-GARCH(1,1) dist='skewt', rolling w=2000 (TLT/0050 w=504), OOS: 2020-2025
- **O11: VaR-based position sizing 假說被拒絕（Phase O, 2026-03-16）**
  - 12/VIX Sharpe 1.984 vs VaR Skewed-t 0.969 vs VaR CF 0.958（DM p<0.0001）
  - 原因：VIX 含 variance risk premium（forward-looking），GARCH 不含（backward-looking）
  - 三種 VaR 之間無顯著差異（p>0.22）——VaR 方法的改善對策略層面無增值
  - 結論：**投資決策用 VIX，風控合規用 VaR**。12/VIX 在策略層面無可取代
- **O12: 分配選擇只影響 VaR，不影響 QLIKE（Phase O, 2026-03-16）**
  - Skewed-t QLIKE 改善 +0.057%（DM p=0.56, 不顯著）
  - GARCH equation → 決定 QLIKE（預測精度），Distribution → 決定 VaR（尾部覆蓋）
  - 兩者獨立可優化——模型結構和分配選擇是正交的
- **O13: GED VaR 確認偏態是關鍵（Phase O, 2026-03-16）**
  - GED (nu=1.29) 26 violations, Kupiec p=0.01 FAIL ≈ Student-t
  - GED 只處理厚尾不處理偏態 → 跟 Student-t 一樣
  - 最終排名：Skewed-t (6/6) > CF-VaR (5/6) > GED ≈ Student-t (4/6) > Normal (1/6)
- **Realized GARCH 自建完成（Phase O, 2026-03-16）**
  - Hansen-Huang-Shek (2012) log-linear, 8 parameters, QML estimation
  - Pilot test (41 days 5-min RV): QLIKE -18% vs GJR, Corr(h,RV) 3x
  - Blocked: 需 252+ 天 5-min 數據（預計 2027 Q1）

### 高頻數據發現
- 5-min RV 確認 Parkinson bias = -33.9%
- 開盤首根 K 棒波動是正常的 46.5 倍（隔夜資訊釋放）
- 日內 U-shape 波動率模式確認
- Overnight variance = 43.1% of daily（獨立於 intraday）
- **開盤 30 分鐘 RV 佔全日 41.1%，同日相關 0.935** → 可作即時預警信號
- 文獻驗證：Bloomberg research (Young Li) + Oxford JFEC 確認日內 pattern

### 獲利策略結論（2026-03-16 更新，含 Harvey haircut）
- **Hybrid VT (SPY)**：⚠️ Sharpe 修正——公平比較 Hybrid 0.772 vs GARCH VT 0.718 (+0.054)。之前 Sharpe 1.06 來自不公平比較
- **12/VIX 簡易策略**：Sharpe 0.61（19yr），MDD -33% vs BH -80%（+47pp）。⚠️ Sharpe improvement t=0.33 不顯著。VT 的唯一可靠優勢 = MDD reduction
- **最佳組合**：Vol-adj EW (SPY+QQQ) 12/VIX + SHY：Sharpe 0.91, MDD -20%
- **12/12 年 Sharpe 全勝** Buy & Hold（包括 2018 Vol 衝擊、2020 COVID、2022 升息、2026 Iran）
- **交易成本穩健**：breakeven 37.2 bps（SPY 實際 1-2 bps 的 18-37 倍）
- **Daily rebalancing + w=2000 最佳**：Sharpe 1.064（因為大窗口 SNR 高→daily 捕捉真實 regime shift）
- **慢調整 VT (SPY)**：Sharpe 0.59, MaxDD -28%（含成本 0.12%/年）
- **Risk Parity (SPY+GLD)**：Sharpe ≈1.18（有選擇偏差，CI 含 0）
- **每週調倉**最實用（Sharpe 0.58, 年 49 次交易）
- 參數穩健：MA 3-10 天 Sharpe 皆 0.60
- ✗ VRP 方向交易、VIX TS 日頻信號、裸賣 put、Regime overlay 全失敗
- ✗ XGBoost 無法替代 GARCH（target 太 noisy，樣本太少）
- ⚠️ **Kill Test 修正**：10/10 crisis protection 是 cherry-pick（客觀 VIX>25 定義只有 36% 保護）。Hybrid VT 的真正價值是 MaxDD reduction，不是 crisis-period outperformance
- ✓ Alpha 存活 VRP 控制（t=2.05），不是 short-vol carry

### 已完成的延伸研究
- [x] GARCH-X with VIX — ✗ 失敗，隱含波動率增量太弱（已發佈）
- [x] 開盤 30 分鐘波動率即時預警信號 — ✓ 成功！3/3 觸發全部避開大跌（已發佈）
- [x] Paper trading — 已啟動 $1M 投資組合（已發佈）
- [x] Phase F 重試 (GRU 5500 天) — GRU 首次超越 GARCH(-0.06%) 但 DM 不顯著(p=0.27)（已發佈）
- [x] 選擇偏差測試 — SPY+GLD vs SPY+SLV 驗證 Risk Parity 穩健性（已發佈）
- [x] 高頻數據分析 — 5-min RV 確認 Parkinson bias=-33.9%，GARCH 精度 98.8%，跳躍=23% vol（已發佈）
- [x] 日內微觀結構 — 開盤首根 K 棒波動 46.5 倍，日內 U-shape 確認（已發佈）
- [x] 期權策略模擬 — GARCH 引導賣出 Put（僅模擬，需 IV surface 數據才能真實回測）（已發佈）

### 下一步研究方向

#### Phase H: 數據擴展與結論驗證（2026-03-15 新增）
**動機**：研究至今 OOS 固定在 2023-2024，但現在已有 2025 整年新數據。這是真正的前瞻驗證機會。
- [x] H1: 2025 OOS 驗證完成（6 模型）— GJR/GED QLIKE=-8.802 在 VaR 約束下最佳，GJR>GARCH 跨三期穩健
- [x] H2: 三期 OOS 穩健性確認 — GJR/GED 三期一致最佳。GJR-HAR 2025 排名下滑（第5）。CARR VaR 災難
- [x] H3: DL 重試 — Ljung-Box 確認 GJR 殘差 iid (p=0.76/0.94/0.97)，DL 無法改善日頻預測（信號已被用完）
- [x] H3b: GARCH-LSTM hybrid 失敗（LSTM factor 不穩定 std=1.16）— 確認非數據量問題
- [x] H3c: Expanding window 測試 — QLIKE=-8.405（最差），2000 年起的遠古事件污染估計
- [x] H3d: Realized GARCH 簡化版 — QLIKE=-8.795，Parkinson RV 信息不足以超越 GJR。需要 5-min RV
- [x] H4: 策略 2025 更新 — 慢調整 VT Sharpe=0.36（牛市跑輸 BH 0.58，但 MaxDD 改善 22%）
- [x] H5: 跨資產 2025 驗證 — GLD GARCH≈GJR（規律成立），QQQ VaR 1% FAIL 需 GED/Floor

#### Phase H 結論（2026-03-15）
- 日頻 GARCH 天花板 QLIKE≈-9.034，殘差 iid（Ljung-Box p>0.76）
- DL/LSTM/hybrid 都無法改善（信號已被用完）
- Window=504 對 SPY 最佳，但 asset-specific：TLT=252
- **Persistence stability 可量化 adaptive window**：std<0.02→504, std>0.05→252
- 2025 偏態翻正(+1.09)但 leverage effect 更強(1.54)——GJR alpha=0, gamma=0.24
- EMD 分解：~49天季度週期主導(37.9%)，per-window EMD 不穩定
- Realized GARCH 需 5-min RV 才能突破天花板
- 4 資產 adaptive window 指南完成（SPY/TLT/GLD/BTC）

#### Phase I: 波動率與報酬率的基本規律發現
**動機**：不只做預測，也要像 Robert Engle 發現 volatility clustering 那樣，找出波動率和報酬率之間的基本規律和特徵。
- [x] I1: vol→return 不可預測（r=-0.002, p=0.86）；leverage ratio 隨 regime：牛市 1.2-1.5, 熊市 1.0；VoV spike 統計顯著但策略無增量
- [x] I2: persistence stability 30x SPY(0.007) vs TLT(0.214) → adaptive window 指標；GLD/BTC 2024-25 趨穩
- [x] I3: 跨資產 spillover 無 Granger 因果（p>0.70），SPY-QQQ 同步但不因果
- [x] I4: October Effect 在高波動 regime 放大 3.4x，Q4 危險季節（ratio>2.5x），day-of-week 極弱
- [x] I5: EMD ~49天季度週期主導(37.9%)，peaks 在 5/8/12月（機構行為）；per-window EMD 不穩定
- [x] Overnight gap >1.5% 是避險信號（daily return -0.37%），已整合進 daily_update

#### 其他方向
- [x] DCC-GARCH — SPY-GLD corr 0.09-0.21，2025 分散化最佳(0.088)，理論改善有限
- [x] TLT 擴展 — GARCH≈GJR（skew 規律成立），w=252 最佳（利率轉折），模型過度保守
- [x] Realized GARCH — 用 Parkinson(-8.795) 和 hourly RV(-8.378) 都未超越 GJR(-8.818/-8.472)。yfinance 1h 僅 7 bars/day 不夠，需付費 5-min 數據源
- [x] GARCH Stacking — Ridge 歸零所有 features（QLIKE -5.3%），三重確認：GARCH 之外無增量
- [x] Adaptive window 自動化 — scripts/check_persistence_stability.py，GLD 趨穩→w 從 252 升級到 504
- [x] TLT VT 策略 — Sharpe=-0.49（升息虧損），50/50 SPY+TLT VT MaxDD -18.4%（所有策略最低）

### 模型選擇精確規則（Phase I/J 更新，2026-03-15）
- **γ > 0.10** → GJR 有顯著優勢（SPY, QQQ when γ high, BTC）
- **γ < 0.10 且 γ > 0** → GARCH 即可（GJR 增加噪音，如 QQQ 2023 γ=0.03）
- **γ < 0** → 必須用 GARCH（GJR 方向錯誤，如 GLD γ=-0.088）
- **γ ≈ 0** → 用 GARCH（TLT γ=0.006）

#### Phase J: 下一階段研究方向（2026-03-15 規劃）
**前提**：日頻模型研究已收斂（GJR w=504 是最終答案），下一步重點在策略優化和數據擴展。

- [x] J1: TLT 2025 從 -12.1% 恢復到 -0.1%（改善 12pp），降息效果開始但未翻正
- [x] J2: 動態多資產 — 2020-2025 升息環境所有含 TLT 策略跑輸 SPY VT。「TLT 負就不持有」(Sharpe 0.36) 最實用但仍不如純 SPY VT (0.61)
- [x] J3: 5-min 數據收集 — scripts/collect_5min_data.py 建立，已收集 41 天。需設 cron 每日跑
- [x] J4: Target vol 消融 — Sharpe 在 6-16% 完全相同(0.61)！投資人只需選 MaxDD 承受力
- [x] J5: 學術論文初稿完成 (paper_sections/)——12 sections, 5833 字。4 貢獻：inverted leverage (t=-8.30), γ>skewness, Student-t VaR (-48%), VT across regimes (ρ=0.983)
- [x] J6: VaR 報告自動化——Student-t VaR 實現 6/6 年 Green Zone。歸因修正：Student-t(-45.5%)是最大改善，Jump augmentation 冗餘(+0%)
- [~] J7: 2026 YTD 追蹤——進行中。VaR: 0/49 at 1%, 1/49 at 5% (Jan 20 only)。VIX/GARCH=1.66, Hybrid VT in VIX mode
- [x] J8: 風險預報頁面——隔日/隔週/隔月 VaR/ES + regime + Basel III，4 資產(SPY/QQQ/GLD/TLT)
- [x] J9: Peer review (68/100 Major Revision) + 全部 critical issues 修正：Parkinson RV ✓, df sensitivity ✓, HAC SE ✓, EGARCH alignment ✓, VT costs ✓, BTC 2025 ✓
- [x] J10: 跨資產 leverage taxonomy 完成（7 資產 + 4 FX）——GLD inverted (t=-5.79 HAC), FX 模糊

#### Phase K: 當前研究方向
- [x] K4: 多資產 VT（EW VT Sharpe 1.08, MaxDD -13.8%）+ rebalancing 頻率（monthly Sharpe 0.75 最佳）
- [x] K6: GLD regime-dependent leverage（t=-4.71, p<0.0001）——牛市 inverted，熊市 standard
- [x] K7: Commodity leverage taxonomy（8 ETFs）——supply-shock→inverted, demand→standard
- [x] K8: Coffee VT 極端測試——100% inverted gamma 上 VT 仍有效 (+48% Sharpe)
- [x] K9: VaR violation 事件歸因——83% 不可預測，17% 可預測（Fed/CPI）
- [x] K10: Significance-based model selection（γ t-stat > 1.65 → GJR，100% accuracy in 12 DM tests）
- [x] K11: VIX/GARCH ratio 作為 VaR reliability indicator（94% violations at ratio>1.5, p<0.0001）
- [x] K12: Fixed df=5 >> estimated df（17 vs 24 violations）
- [x] K13: PIT calibration 跨資產比較（SPY kurt=2.80 最難, TLT kurt=0.67 最易）
- [x] K14: GARCH crisis adaptation speed（2-5d to peak, 10-60d recovery）
- [x] K15: Cross-asset vol synchronization（SPY-TLT vol corr=0.777, P(all high)=1.9%=19x expected）
- [x] K16: Overnight variance = 44.3% of total（解釋 Parkinson bias）
- [x] K17: VT during Liberation Day（保護下跌 -7.6% vs -10.8%，但錯過反彈 +4.7% vs +10.5%）
- [x] K18: Monte Carlo 驗證 γ rule（95% overall accuracy, 300 simulations）
- [x] K19: True OOS validation（83% single-point, 100% multi-window）
- [x] K20: Forecast encompassing test（GJR encompasses GARCH, not vice versa）
- [x] K21: Mincer-Zarnowitz regression（TLT best calibrated, SPY moderate, GLD worst）
- [x] K22: Model selector 自動化 (scripts/model_selector.py)
- [x] K23: Paper 合併為 paper_complete.md (8,009 words)
- [x] K24: 20+ 資產 leverage taxonomy (equities/gold/commodities/bonds/crypto/FX)
- [x] K25: Iran crisis real-time validation — USO γ flipped (+0.10→-0.13), σ 26%→107%, Gold hedge FAILED (-6%)
- [x] K26: Multi-step VaR bias fix — proper GARCH h-step formula, QQQ monthly +10% correction
- [x] K27: **Hybrid VT** — VIX/GARCH > 1.3 時切換到 VIX weight。Sharpe ~2.0 across 11 years (2015-2026)。7/7 年勝過 GARCH VT。Transaction cost robust (+0.12 Sharpe at all costs)。Multi-asset confirmed (EW Hybrid Sharpe 1.46 vs GARCH 1.04)
- [x] K28: Iran Crisis 2026 驗證 — Operation Epic Fury (2/28)。GARCH adaptation 10 days to peak (1.27x), VIX jumped immediately → Hybrid VT value confirmed。Cross-asset: SPY-USO corr=-0.80 (oil=equity negative), GLD FAILED as short-term hedge (corr=+0.38), TLT vol unchanged (true safe haven)。USO γ=-0.133 (inverted deepened), GLD γ=-0.221 (inverted intensified)
- [ ] K1: 論文 LaTeX 排版 + 正式 Tables/Figures
- [ ] K2: Realized GARCH OOS（等 5-min 數據累積到 252+ 天，預計 2027）
- [ ] K3: GARCH-GRU integrated（文獻 2025：嵌入式比 cascade 好，但日頻殘差 iid 可能無效）
- [ ] K5: 2026 H2 OOS 驗證（新增半年 OOS 數據）

#### Phase L: 危機傳導與避險研究（2026-03-16 規劃）
**動機**：Iran crisis 揭露重要現象——GLD 在 oil supply shock 中不是有效短期避險。需系統性研究不同危機類型的避險機制。
- [x] L1: 危機類型分類——10 場歷史危機分析。Financial→GLD, Pandemic/Oil→TLT, 但 2026 Iran 兩者都負。CASH (via Hybrid VT deleveraging) 是通用最佳避險
- [x] L2/L3: 結論——Hybrid VT 是類型無關的通用危機保護，不需要辨識危機類型。10/10 crises +8.7pp avg protection
- [x] L4: Oil transmission 量化——SPY-USO 同期 corr=-0.80，但無 Granger 因果 (p>0.46)。傳導即時，不可預測
- [x] L5: 論文更新——Section 4.6.7 Iran crisis validation (+555 words)。Abstract/Conclusion 更新。Hybrid VT 10/10 crisis + 2026 VaR Green Zone + γ rule confirmed
- [x] L6: VIX/GARCH ratio 預測——ratio autocorr=0.764，simple persistence 83.1%。預測不必要，reactive switching 已近乎最優。Deeper: Hybrid VT = VRP asymmetric exploitation
- [x] L7: GLD 泡沫預警——RSI>90 → 62% crash probability (5/8 episodes)。RSI>85 + Mom>15% → 100% (2/2)。3/3 crashes preceded by RSI>80。Small sample caveat
- [x] L8: Cross-asset VaR overlay——USO vol 不改善 SPY VaR (R² +0.06pp, null result)。Vol synchronization 依危機類型而異
- [x] L9: VRP Regime Analysis——ratio>2 發生在 calm market (VIX~22, GARCH~11%)，非危機。COVID ratio=0.71 (GARCH>VIX)。VRP crisis cycle: anticipation→peak→recovery
- [x] L10: Henriksson-Merton Timing Test——Alpha=5.77% ann (t=3.99)。NOT directional timing (γ=-0.043)。Alpha from variance management. Validates Moreira & Muir (2017)
- [x] L11: Factor Decomposition——VIX Δ β=-0.017 (t=-25.0) = short VIX exposure。Residual α=4.79% (t=4.77)。Hybrid VT ≈ 31% market + short VIX + 4.8% alpha
- [x] L12: Regime-Conditional——Hybrid advantage at ratio 1.5-2.0。Low VIX: BH best。Crisis: all negative。Optimal zone for Hybrid switch = 1.3-2.0
- [x] L13: Threshold Robustness——[1.0, 1.6] all give Sharpe 0.93-0.98。Adaptive threshold worse than fixed (null result)
- [x] L14: Timing Alpha Tests——HM: α=5.77% (t=3.99)。TM: Hybrid γ=-0.15 vs GARCH γ=-0.50 (reduced concavity)
- [x] L15: Dollar Value——$867K saved per $1M across 10 crises (54% damage reduction)
- [x] L16: Peer Review #2 (74/100)——Section numbering fix, HAC SE, OOS clarification。Paper 9,006 words
- [x] L17: Window Size 深入分析（用戶質疑）——完整 6 期驗證: w=5000 wins 3/6, w=504 wins 1/6 (COVID only)。w=504 只在極端危機佔優，w=5000 在多數情況更好（包括 Iran 2025-26）。U-shape 確認。Persistence 偏誤: w=504 -3%, w=2000+ ~0%。實務折衷 w=2000-3000 可能更佳
- [x] L18: 前瞻偏誤警覺（用戶提醒）——window 選擇基於全部 OOS = data snooping。但 rolling 預測本身無偏誤

#### Phase M: Window Size Robustness（2026-03-16）
**動機**：用戶質疑 w=504 樣本數不足。Hwang 2006 文獻確認 w=504 有 -3% persistence bias。
- [x] M1: GJR vs GARCH w=2000——GJR 優勢在 w=2000 下成立且更大（-6.1% vs w=504 的 -3.8%）。核心結論 ROBUST
- [x] M2: VaR w=2000——0.8% violation rate（better than w=504 的 1.1%）。更精確的 persistence → 更好的尾部覆蓋
- [x] M3: daily_update.py 預設升級 w=504 → w=2000。σ 16.2→16.8%（微調），VaR 改善 0.8% vs 1.1%，計算時間 +4ms
- [x] M4: 論文已報告雙窗口結果（Section 4.6.1 更新）。跨資產驗證：SPY -6.1%, GLD -4.0%, TLT +1.8%
- [x] M5: 跨資產 window: equity/commodity → w=2000 better QLIKE, bonds → w=504 better
- [x] M6: FIGARCH 長記憶 d=0.683 — null result, +8.7% worse than GJR
- [x] M7: Hybrid VT w=2000: MaxDD -25.6% (好 4pp) 但 Sharpe 0.635 (差 0.11)。Trade-off: MaxDD vs Sharpe
- [x] M8: Bias-corrected GARCH 不需要 — w=2000 已解決 persistence bias

#### Phase N: 高頻數據與 Realized GARCH（2026-03-16 啟動）
**動機**：5-min RV 初步分析顯示 GARCH σ² 與 5-min RV 日度相關性幾乎為零 (corr=-0.11)。GARCH 總量正確 (ratio 1.08) 但無法追蹤每日變動。Realized GARCH 是突破 QLIKE ceiling 的唯一路徑。
- [x] N1: 5-min RV 初步分析——41 天，GARCH/RV ratio=1.08, corr=-0.11
- [x] N5: Kill Tests（Gemini+Codex 審查後）：#1 Alpha 存活 VRP 控制 (t=2.05) ✓，#2 客觀 crisis 定義只有 36% 保護（修正 10/10 cherry-pick 結論），#3 大幅超越簡單替代 (+0.15 Sharpe) ✓
- [x] N6: VIX1D vs 30-day VIX — null result。VIX ratio Sharpe 1.118 > VIX1D 0.919。30-day VIX 更適合 position sizing（穩定信號 vs noisy 短期）
- [x] N7: 0DTE 文獻搜尋：Vasquez 2025 (gamma +6.4pp), Dim 2024 (stabilizing), Albers 2025 (VIX1D as new indicator)
- [x] N8: 個股 γ 分析——SPY γ=0.211 > 全部 20 隻個股 (avg 0.079, t=-10.68, p<0.0001)。Diversification amplifies leverage effect 2.7x。機制：correlation asymmetry
- [x] N9: 50 股驗證——2.8x amplification (49/50, t=-16.92, p<10⁻⁶)。極穩健
- [x] N10: 國際驗證——US 2.8x ✓, EEM 3.3x ✓, Japan 0.7x ✗ (attenuation), Germany 0.9x ✗。非全球通用
- [x] N11: 個股 VT GARCH vs GJR——混合結果(2 GARCH, 1 GJR, 2 TIE)。GJR VT 優勢主要在 ETF
- [x] N12: 時間穩定性——amplification 20 年都存在(1.4x→2.0x→1.7x→4.3x)，個股 γ 下降 74%
- [x] N13: Structural γ shift——10/10 個股 2021-26 γ 全部下降，JNJ/UNH 翻負
- [x] N14: Sector ETF γ——defensive vs cyclical 無顯著差異(p=0.37)。Inverted leverage 是個股特性非 sector
- [x] N15: Correlation asymmetry——US(+0.042)/Japan(+0.071)/Germany(+0.092) 都有，但 US absolute corr 更高
- [x] N16: Crypto leverage taxonomy — 0/7 用 GJR（BTC/ETH/SOL 全部 γ 不顯著，no stable leverage in crypto）
- [x] N17: FX leverage taxonomy — 5/6 用 GARCH（JPY/CHF safe-haven 沒有 inverted γ，跟 gold 不同）
- [x] N18: Harvey-Liu Sharpe haircut — 0.99→0.95（N=10 strategies，haircut 小但 CI 寬 [0.42, 1.56]）
- [x] N19: Christoffersen independence test — PASS（p=0.79，violations 獨立）
- [x] N20: 正式審查報告 review_v1.0.pdf — 8 嚴重 + 9 中度 + 6 輕微問題
- [x] N21: 方法論反省 — Harvey (2016) 框架下 6 個過度解讀風險，論文需重新定位
- [x] N22: VIX-Zone Enhancement 驗證 — +0.044 Sharpe（Harvey-adjusted +0.022），3/3 跨期通過。VIX<14 boost 30%, VIX 14-18 reduce 20%。邊際改善，secondary enhancement
- [x] N23: Kurtosis collapse 深入分析 — BH 13.24 → HVT 2.85（78% reduction）。State-dependent: crisis years 59-62% reduction, calm years ~0%。Sortino +22%（0.92→1.12）。Worst day -10.94%→-3.01%
- [x] N24: Skewness puzzle — HVT skew -0.59 > BH -0.29（more negative）。Source: VIX 15-20 de-leveraging misses bounces。但 Sortino/Omega unanimously favor HVT → cosmetic, not harmful
- [x] N25: VRP deep structure — **Threshold 1.3 = long-run VRP median (1.31)**。Not ad hoc, principled justification。No return prediction (corr=-0.053)。AC=0.93 (persistent)。GARCH≈Realized (0.2% diff)
- [x] N26: Regime switching analysis — 50/50 mode split (emergent, not designed)。Mean spell 10 days, 26 transitions/year。Longest VIX spell 49 days (COVID 2020)
- [x] N27: March 2026 Strait of Hormuz crisis — HVT -1.50% vs BH -3.45%（+1.96pp, 57% protection）。Oil>$100，Hormuz near-closed。GLD -6%（gold fails again）
- [x] N28: Charalampopoulos (2025) VRP timing paper — parallel concept, cite in paper
- [ ] N2: 持續收集 5-min 數據（42/252 天，16.7%，預計 2027 Q1）
- [ ] N3: Realized GARCH 正式實驗（需 252+ 天 5-min RV）
- [ ] N4: HAR-RV 用 5-min RV（不需 GARCH，直接迴歸 realized vol）
- [x] N29: VRP spell duration prediction — null result（r=0.013），reactive switching 確認正確
- [x] N30: GARCH adaptation speed — crisis-type dependent: sudden 6.6%/d, gradual 3.7%/d, sustained 1.2%/d
- [x] N31: Amplification ratio time-variation — mean 2.0x, range 0.95-6.5x, upward trend p=0.021
- [x] N32: 第三輪 peer review 完成 — Codex 12 issues + Gemini 6 blind spots
- [x] N33: 前瞻偏誤排除 — VIX[t-1] delta=-0.008 Sharpe（穩健）
- [x] N34: 融資成本排除 — 權重從未>100%，avg 59%，零融資成本
- [x] N35: Table 2 符號修正 — 所有 HAC t-stat 符號已修正
- [x] N36: VIX Momentum 跨期驗證 — **FAIL**（delta +0.005，3/3 方向正確但幅度可忽略）。MA(5) 已吸收信號
- [x] N45: 跨資產 VRP — Realized/GARCH 所有資產 ≈1.0，VIX/GARCH=1.22。VRP 是 SPY 特有。Hybrid VT 是 equity strategy
- [x] N46: 14 資產 VT correlation — ρ=0.830 (p=0.0002)，原本 5 資產 0.983 是 inflated。但仍高度顯著
- [x] N47: 論文 3 張圖表生成 — rolling gamma, VIX/GARCH ratio, cumulative returns (PDF)
- [x] N48: Ang-Chen asymmetric correlation 驗證 — down-day corr 0.540 > up-day 0.480（t=7.20, p<0.0001）。90% 股票展現。完美解釋 diversification amplification 機制
- [x] N52: Kurtosis collapse 是 vol-of-vol dependent (r=0.709)，不是 gamma dependent (r=0.013)。SPY 75.7% vs 個股平均 26.3% (t=-5.36, p<0.0001)。6/20 個股 VT 反而增加 kurtosis
- [x] N53: Regime-conditional window — null result。w=504/1000/2000 across 6 periods 的 QLIKE 差異僅 0.43%。No regime indicator predicts best window
- [x] N54: Structural gamma decline — 個股 -65% (0.287→0.099), SPY -53% (0.299→0.141)。7/10 顯著。Amplification 1.04x→1.42x。5/20 個股 gamma 翻負
- [x] N55: MCS test — GJR superior set, GARCH excluded (p=0.044)。Added to paper Section 4.3.3
- [x] N56: VIX/GARCH ratio logistic regression — AUC 0.929 (in-sample), 0.973 (OOS)。OR=19.5x。100% violations at ratio>1.3。Added to paper Section 4.4.5
- [x] N57: Sector ETF gamma validation — 11/11 correct。Financials 0.264 (strongest, Black 1976), Energy 0.076 (weakest)。All equity sectors have standard leverage
- [x] N58: International equity VT — 8/8 MaxDD improvement (avg +27pp), 0/8 Sharpe improvement (avg -0.14)。Corr(base_risk, MDD_improvement)=0.947。VT universal but VIX switching needed for Sharpe
- [x] N59: US VIX predicts international VaR — AUC 0.80-0.86 (EEM/EWG/EWJ)。低於 SPY 0.93 但仍有用。Local implied vol preferred for Hybrid VT
- [x] N60: Gamma decline 不影響 VT effectiveness — VT 在 6 期都有效（5/6 MDD 改善），benefit 是 vol-of-vol 驅動，不是 gamma 驅動
- [x] N61: GLD VT 在 bull/bear 都有效。Bull Sharpe+0.09/MDD+5.5pp, Bear Sharpe-0.08/MDD+8.5pp。60/62% symmetric scaling 確認 VT 是 volatility scaling 非 directional
- [x] N62: Fine-grained threshold sensitivity (0.8-2.5, step 0.1)。Peak at 1.4 (Sharpe 0.914)。Plateau [1.0-1.6] within 4%。All beat GARCH VT (0.780)
- [x] N63: Paper scope analysis — 5 contributions thematically linked, recommend keeping single paper (11K < 15K limit)
- [x] N64: GLD MCS — all 5 models in superior set (none eliminated)。直接對比 SPY (GARCH excluded p=0.044)。Validates gamma rule
- [x] N65: Day-of-week VaR — null result (chi2=2.17, p=0.70)。No Monday effect。Violations uniformly distributed
- [x] N66: Bootstrap CI — GJR QLIKE improvement -0.45% [-0.78, -0.14]。P(GJR better)=99.7%。DM significant 78.5%
- [x] N67: GARCH ceiling universal — 5/5 assets clean Ljung-Box (p>0.30)。Not SPY-specific
- [x] N68: Overnight gap >1.5% → 10.5% VaR violation rate (10.5x normal)。36% violations on 5% of days
- [x] N49: 跨資產 VRP — Realized/GARCH ≈ 1.0 所有資產。VIX/GARCH=1.22（VRP）是 SPY 特有。Hybrid VT 是 equity-specific
- [x] N50: Limitations 編號修正 — Second→Third→Fourth→Fifth→Sixth
- [x] N51: 論文修改 agent — C1 section numbering, C4 HM/TM equations, M7 symbol conflict, M2 numbered equation, M3 appendix format
- [x] N37: 論文更新——VRP threshold = VIX/GARCH median (1.31) justification, kurtosis collapse (78% reduction), skewness caveat (-0.59 vs -0.29), new citations 全部加入
- [x] N45: Factor decomposition 方程式加入論文（Eq 3, R²=0.26）
- [x] N46: HM/TM 方程式加入論文（Eq 1, 2），γ 符號區分（γ_HM vs γ_TM vs GJR γ）
- [x] N47: ρ 更新 0.983→0.83 (p=0.0002, N=14)——abstract + body 兩處
- [x] N48: 前端 content 欄位 bug 修正（ReportDetail.tsx）
- [x] N38: QLIKE 指標統一——Section 4.6.1 已修正為 log-scale（-9.034 格式），與全文一致
- [ ] N39: 論文範圍重構（Codex: 5 contributions 太多，考慮拆成 2 篇）
- [x] N40: MCS 分析完成 — GJR 是 MCS-superior（3/5 models），GARCH excluded (p=0.002)。用 MCS 替代「天花板」宣稱
- [x] N43: 1987 型黑天鵝模擬 — HVT 不是 short gamma，保護線性。平靜市場（VIX=12）零保護但 conditional probability 接近零
- [x] N44: GARCH adaptation speed — 危機類型決定：突發 6.6%/d, 漸進 3.7%/d, 持續 1.2%/d
- [x] N41: 移除 2026 Basel 推論——已加入 49 天不足的 caveat，不再聲稱 Green Zone compliance
- [x] N42: 新引用已加入——Zakamulin (2014) VT timing test, Zhu-Kuan (2016) QLIKE, Charalampopoulos (2025) VRP timing
- [x] N68: 0DTE γ decline 假說——NULL RESULT。γ 下降是全面性市場現象，Non-SPX (-45.3%) > SPX-heavy (-5.7%)，p=0.47。不是 0DTE 特有
- [x] N69: Persistence Bias vs VRP 機制——VIX 切換 ≈ fast GARCH adaptation。12 年 OOS 所有 VT 策略 Sharpe 0.72-0.80（差距 <0.08）。⚠️ 之前 K27 報告的 Sharpe 1.06 來自不公平比較（GARCH 未用 MA(5) 平滑），公平比較後 Hybrid 只贏 +0.054 Sharpe。真正價值在 MDD 改善（ratio 1.3-2.0 區間 -6.3pp）
- [x] N70: Kurtosis collapse vs correlation asymmetry — NULL RESULT（R²=0.16）。Corr asymmetry 不解釋 kurtosis reduction。但 VT kurtosis level 由 vol-of-vol 決定（R²=0.77, p=0.006）。個股 VT 平均增加 kurtosis（-14.4%），只有 SPY 降低（+33.8%）
- [x] N71: 2024-2026 文獻搜尋 — 5 篇必引新論文：Hood & Raughtigan (2025 JPM, VT=implicit trend), Bozovic (2024 IRFA, VIX>realized), DeMiguel (2024 JF, +13% OOS), Xu (2024 CFR, 148/197 improved), Nelson (2025, correlation breakdown)
- [x] N74: Hood-Raughtigan 趨勢跟蹤假說驗證 — SPY 135% alpha 被趨勢吸收（表面確認 VT=隱性趨勢），GLD 49%，TLT -5%。但見 N76
- [x] N75: VT alpha 分解 — Market 88% + Trend 6% + Variance Mgmt 6%。趨勢和 vol-mgmt 成分都很小
- [x] N76: VIX regime 趨勢分析 — Within-regime separate regressions 顯示 trend 在 3/4 regime 不顯著。但 N77 修正此結論
- [x] N77: 正式 FE 檢驗修正 N76 — trend β 加入 regime FE 後不變（not Simpson's Paradox），但高度 regime-dependent（F=293, p<0.0001）。Low VIX β=0.41, Med/High β≈0, Crisis β=0.27。Hood (2025) 核心宣稱正確但 regime-conditional
- [x] N78: 非專業投資人策略比較 — 7 策略 12 年：所有 Sharpe 0.68-0.75（差 <0.06），MDD 差距 24pp。VT 真正價值是 MDD control
- [x] N79: ★ 12/VIX 懶人策略 — Sharpe 0.737（差 EWMA VT 僅 0.011），MDD -16.5%（比 EWMA 更好 2.9pp）。最簡單 VT：weight=12/VIX，不需模型/程式
- [x] N80: 12/VIX 19年擴展回測 — Sharpe 0.607 vs BH 0.502, MDD -32.5% vs -80.3% (+47.8pp)。GFC +30.5pp, COVID +25.5pp。4/20年贏（全是熊市年）
- [x] N81: 風險偏好指南 — target/VIX 對照：6(退休)→MDD-16%, 8(保守)→MDD-22%, 12(標準)→MDD-33%, BH→MDD-80%。所有 Sharpe 0.59-0.62（差距可忽略）
- [x] N82: Cash 部分配置 — SHY（短債）最佳（Sharpe 0.695, MDD -23.7%），TLT 最差（利率風險抵消 VT）
- [x] N83: 完整操作手冊 — 12/VIX+SHY，Daily Sharpe 0.682，Monthly 0.646。$1M 範例 + 風險提醒
- [x] N84: 12/VIX 跨市場 — SPY/QQQ 有效(+0.09~+0.12 Sharpe)，IWM/EFA/EEM 無效（VIX 是 SPY 特定）。MDD 改善全球通用(+40-53pp)。Vol-adjusted 版本大幅改善（QQQ Sharpe 0.938）
- [x] N85: Drawdown Recovery Paradox — VT 回撤淺（-17% vs -31%）但恢復慢（555d vs 466d, +19%）。原因：VIX 高位→持續減碼→miss 反彈
- [x] N86: Recovery 改善方案 — Percentile target 最佳（+0.047 Sharpe, same MDD）。但增加複雜度，懶人版仍推薦 base 12/VIX
- [x] N87: ★ 12/VIX 理論基礎 — w=12/VIX = σ_target/σ_implied = Moreira-Muir + implied vol。Bozovic (2024 IRFA) 已證明 VIX-managed > realized-vol-managed。VIX/GARCH=1.27 (VRP)
- [x] N88: ★★ GARCH vs 12/VIX 對決 — 12/VIX 贏 5/7 期間！整體 Sharpe 0.856 > GARCH 0.826 (+0.030)，MDD -16.5% > -18.4% (+1.9pp)。GARCH 價值在學術理解而非策略執行
- [x] N89: Target sensitivity — target=12 不是 cherry-pick。ALL targets 6-20 beat EWMA VT（Sharpe 0.85-0.87 flat），只影響 MDD（-8% to -27%）
- [x] N90: GARCH 增值測試 — GARCH overlay 降低 Sharpe (-0.031)。VRP timing 也不行。GARCH 在 VT 策略層面無增值，價值在風控和學術
- [x] N91: 12/VIX GFC 逐月表現 — 2008-10 保護 +12.4pp（持倉 22%），但 2009-03 miss +8% 反彈（持倉 27%）。Recovery paradox 實例
- [x] N92: Multi-asset trend absorption — ★★ Spearman ρ(gamma, beta_trend)=0.954 (p=0.0008)。7 資產完美驗證：γ>0→trend follower, γ<0→contrarian, γ≈0→pure variance mgmt
- [x] N72: 論文引用更新完成 — 5 篇新文獻 + narrative repositioned（VRP→implied-realized integration）
- [x] N93: 交易成本分析 — Monthly turnover 116%, 年成本 0.012% (at 1bps), breakeven 63 bps。Monthly 最佳頻率
- [x] N94: ★★★ Formal Proposition — Spearman ρ(gamma, trend_beta)=1.000，Pearson r=0.996。7 資產完美排序。Gamma taxonomy 完美預測 VT alpha 機制
- [x] N95: 統計驗證 — LOO 全部 rho=1.000（穩健），permutation p=0.0003（極顯著）
- [x] N96: 擴展到 17 資產 — 新增 10 資產中 7/10 確認（70%），Spearman 0.855 (p=0.0016)
- [x] N97: 合併 17 資產 — Spearman ρ=0.874 (p=4e-6)，STRONG
- [x] N98: Safe-haven 例外解釋 — FXY/IEF 在 VIX spike 時上漲，VIX VT 結構性衝突
- [x] N99: 2026 YTD 最新表現 — BH -2.9%, 12/VIX -1.4% (+1.5pp)。VIX=27.3, weight=46%
- [x] N101: Multi-asset 12/VIX — Vol-adj EW (SPY+QQQ+SHY) Sharpe 0.912, MDD -20%（最佳組合）
- [x] N102: 多因子 VIX — 2/3-factor 改善微小（+0.01~+0.02 Sharpe），不值得複雜化
- [x] N103: GARCH tail-risk protection — Sharpe 0.759 vs 12/VIX 0.737，但保險成本 7.78%/yr 太高
- [x] N104: 再平衡頻率 — Weekly≈Daily, Monthly 是 sweet spot, Quarterly 效果下降
- [x] N105: ⚠️ Harvey (2016) test — 12/VIX Sharpe improvement t=0.33，不顯著！需 1573 年
- [x] N106: ★ Bootstrap MDD test — P(VT MDD < BH MDD)=0.9996 (p=0.0004)。MDD improvement 95% CI [+9.2pp, +71.7pp]。Sharpe 不顯著但 MDD 極度顯著
- [x] N107: 理論解釋——MDD 是 mechanical（99% under null），Sharpe 需 skill。VT pitch = same return, much less risk
- [x] N108: Contribution 評估——6 contributions，2 HIGH novelty（Gamma-mechanism + 12/VIX）
- [x] N109: 26 資產 gamma test — Spearman ρ=0.753 (p=9e-6)。7→17→26 資產 rho 遞減但始終顯著
- [x] N110: Convergence 分析 — rho 隨 N 遞減但始終顯著（7:1.000, 17:0.874, 26:0.753）
- [x] N111: Exception 分析 — FXY(safe-haven), TLT(duration), UNG(contango) 系統性例外
- [x] N112: Monte Carlo — MDD 100% 改善（mechanical），Sharpe 50%（random）
- [x] N113: ★ 真正 OOS 預測 — gamma(2010-17) 預測 trend_beta(2018-26)：Spearman 0.821 (p=0.023)。Genuine predictive power!
- [x] N116: 利率環境穩健性 — 所有利率 regime 都有效，Low rate 最大 +0.407 Sharpe
- [x] N117: 行為金融 — VT 降低恐慌拋售機率（MDD -11% vs -30%），恐慌者少賺 $64,819
- [x] N118: 台灣 EWT — US VIX 無效，EWMA VT 最佳 (+0.076 Sharpe)，MDD -96%→-29%
- [x] N119: 台灣 0050.TW — EWMA VT 有效！Sharpe 0.73→0.80, MDD -41%→-18%。不需 VIX
- [x] O22: VIX 期限結構預測月度波動率 — VIX/VIX3M ratio in-sample t=4.49 (R²=0.50) 但 OOS 加入 ratio 反而降低 R²（0.32→0.14）。Classic overfitting。Raw VIX×ratio (=VIX²/VIX3M) 是最佳無參數預測器 R²=0.35。VIX>>GARCH at monthly freq (DM p=0.004)。Backwardation 資訊被 VIX level 吸收（controlled p=0.51）
- [ ] N120: 取得 VIXTWN 歷史數據，測試 12/VIXTWN 台灣市場策略
- [x] Q_sensitivity: ★ Taiwan K/VIX ratio sensitivity analysis — Codex calibration leakage concern RESOLVED。Sharpe 在 K=5-12 完全不變（0.612），variation=0.0%。這是數學恆等式：Sharpe(K*ret)=Sharpe(ret)。ratio=1.39 只影響 MDD level（K=8.63→MDD-15.9%, K=12→MDD-21.6%），不影響 alpha。VIXTWN ratio=1.393±0.139 (CV=10%)。K/VIX vs EWMA VT Sharpe 差異不顯著(p=0.51)。結論：ratio 是風險偏好參數，不是 alpha 參數，calibration leakage 結構上不可能影響 Sharpe
- [x] Q_sharpe_reconciliation: ★★ 0050.TW 8.63/VIX Sharpe 差異和解——Q1=1.16, Q7=0.612, R14=1.32 的差異來自計算規格不一致：
  - **Q7 (0.612)** 最接近「daily rebal + TX 0.585% + lagged + cash=1.5%, 2016-2025」→ Sh(exc)=0.590。Q7 的 0.612 是純 Sharpe(raw) 下的數學恆等式結果（K 無關），但 daily rebal TX 吃掉大量報酬
  - **Q1 (1.16)** 最接近「daily rebal + no TX + lagged + cash=0%, 2016-2025」→ Sh(ari)=1.160 精確匹配。Q1 遺漏 TX cost 且用 arithmetic Sharpe
  - **R14 (1.32)** 最接近「daily rebal + same-day VIX + no TX + cash=1.5%, 2020-2025」→ Sh(exc)=1.306。R14 有 same-day timing bias（VIX_t→r_t 而非 VIX_t→r_{t+1}）
  - **正確基準值**：月度再平衡、lagged VIX、TX 0.585%、cash 1.5% → **Sharpe(exc) = 0.688**（2016-2025）/ **0.684**（2020-2025）
  - K-invariance 確認：純 K/VIX（no cap, no tx, no cash）Sharpe = 0.8499 對所有 K 值完全相同
  - 主要教訓：(1) daily vs monthly rebal 差異巨大（TX 累積）(2) same-day bias 膨脹 ~+0.4-0.7 (3) 必須統一規格才能跨實驗比較
- [ ] N73: Hybrid VT Sharpe 修正寫入論文（公平比較 0.772 vs 0.718）
- [ ] N72: 論文引用更新（加入 5 篇新文獻 + 重新定位 Hybrid VT narrative）— agent 執行中
- [ ] N73: Hybrid VT Sharpe 修正（公平比較結果寫入論文）

### FDR Audit (2026-03-17) — Benjamini-Hochberg Multiple Testing Correction
**動機**：110+ 實驗中多個正面發現，Codex 和 Gemini 都標記多重檢定為最大風險。

**方法**：BH-FDR at q=0.05, 32 statistical tests, 2 mathematical identities excluded。

**結果摘要**：
- 30/32 統計發現通過 BH-FDR (93.75%)
- 19/32 通過更嚴格的 Bonferroni
- 53 個 null results vs 34 個正面發現 (ratio 1.6:1) — 誠實報告
- 2 個未通過 FDR 的發現（12/VIX Sharpe p=0.74, Ljung-Box p=0.76）本來就被正確標記為不顯著

**高風險發現（通過 FDR 但有質性問題）**：
1. VIX backwardation (t=4.31) — 名義通過，但 same-day timing bias + subsample instability。判定：FALSE POSITIVE
2. Momentum Overlay SPY (t=4.00) — 名義通過 Harvey，但跨資產 0/4 驗證失敗。判定：SPY-SPECIFIC
3. Excess Fear in-sample (t=4.48) — OOS t=2.61 低於 Harvey 門檻。判定：IN-SAMPLE ONLY
4. VT alpha survives VRP (t=2.05) — 邊際顯著，未達 Harvey t>3。判定：MARGINAL
5. HM timing alpha (t=3.99) — Hybrid VT Sharpe 已修正為 0.772。判定：NEEDS RECALCULATION

**最穩健的發現（通過 FDR + 交叉驗證 + 多重獨立確認）**：
1. GJR > GARCH (MCS p=0.044 + DM p<0.001 + bootstrap p=0.003) — 三重確認
2. Gamma-mechanism (N=7→17→26→OOS, 全部獨立通過 FDR) — 漸進驗證
3. FHS best VaR Trinity (21/21, p≈5e-7) — 極度穩健
4. Diversification amplification 2.8x (t=-16.92, 49/50 stocks) — 極度穩健
5. Correlation asymmetry (t=7.20, 90% stocks) — 機制驗證
6. MDD improvement (bootstrap p=0.0004) — 但為 mechanical 而非 skill
7. GLD inverted leverage (t=-5.79 HAC) — 通過 Harvey + 跨 regime 驗證

---

## VIX Proxy Transport 跨市場研究（2026-03-17）
[提出: Codex, 執行: Claude]

**研究問題**：US VIX 何時可作為非美市場的波動率代理？transfer coefficient 由什麼決定？

### 核心數學發現
K/VIX 是線性槓桿規則 → **Sharpe 對 K 完全不變**（數學恆等式）。「最佳 K」和「transfer coefficient」概念具誤導性。K 僅決定：報酬水準、波動度、MDD。真正的問題是 VIX 是否提供 **timing information**。

### VIX Timing Alpha（2016-2025, K=12）
| 資產 | VT Sharpe | B&H Sharpe | Timing α | MDD 改善 | 結果 |
|------|-----------|------------|----------|----------|------|
| SPY | 0.814 | 0.786 | +0.028 | +10.5% | MARGINAL |
| EFA | 0.242 | 0.312 | -0.070 | +10.4% | FAILS |
| EEM | -0.082 | 0.067 | -0.149 | +14.3% | FAILS |
| FXI | 0.157 | 0.118 | +0.039 | +12.1% | MARGINAL |
| EWJ | 0.320 | 0.340 | -0.021 | +11.3% | FAILS |
| 0050.TW | 0.865 | 0.803 | +0.062 | +15.6% | WORKS |
| IWM | 0.337 | 0.434 | -0.097 | +12.5% | FAILS |

### 關鍵發現
1. **MDD 改善是普遍的**：所有資產 MDD 改善 10-16%，即使 timing alpha 為負
2. **Sharpe 改善不可靠**：跨期交叉驗證顯示 timing alpha 符號不穩定（SPY: +0.068→-0.013）
3. **決定因素**：corr(asset_return, ΔVIX) 與 timing alpha 相關 r=+0.54；beta_SPY 和 corr_SPY 不是可靠預測指標
4. **IWM 悖論**：β=1.1 但 timing fails，因為 high-VIX 期間 IWM 報酬為正（mean-reversion）
5. **0050.TW 悖論**：corr_SPY=0.22 但 timing works，因為高 B&H Sharpe 使微小 timing 也有效
6. **VIX vs Local RV**：Local RV 在 EFA/EEM/EWJ 較佳；VIX 在 FXI/0050.TW/IWM 較佳

### 預測迴歸
R_{t+1} = α + β*(1/VIX_t)：**無資產顯著**（最佳 t=-1.48, p=0.14）
R_{t+1} = α + β*VIX_t：IWM β=+0.0016 (t=2.04, p=0.044) — 但為正號（高 VIX → 高報酬），解釋為何 timing 失敗

### 實務建議
- VIX timing 用於 **MDD 控制**（普遍有效）
- VIX timing 用於 **Sharpe 改善**（僅 SPY 和 0050.TW 有前景，但不穩定）
- 非美資產：優先使用 local implied vol 或 realized vol
- K 是風險預算參數，不是優化參數

---

## BTC Positive Skewness & Crypto VT Rule（2026-03-17）
[提出: User (Q17 extension), 執行: Claude]

**研究問題**：Q17 發現 BTC skew=+0.464，能否基於正偏態建立加密貨幣特有的 VT 規則？

### 關鍵修正：BTC 正偏態不穩定
- Q17 報告的 +0.464 來自 **2024 年 simple returns**
- 全樣本 (2020-2025)：**log skew = -1.35, simple skew = -0.48**（強烈負偏）
- 2023-2025 子集：log skew = +0.37, simple skew = +0.52
- 252d 滾動偏態**僅 55% 時間為正**
- 年度：2020=-4.07, 2021=-0.11, 2022=-0.60, 2023=+0.69, 2024=+0.34, 2025=-0.01
- **結論：BTC 偏態是 regime-dependent，不是結構性正偏**

### BTC Realized Vol 特徵
| 統計量 | BTC (22d ann) | SPY (22d ann) | 比率 |
|--------|--------------|--------------|------|
| Mean vol | 46.5% | 15.0% | 3.1x |
| Median vol | 42.7% | — | — |
| % days vol>30% | 79.9% | — | — |
| % days vol>50% | 33.1% | — | — |

### BTC VT 策略表現（2020-2025 OOS, LAGGED weights, max 1.5x）
| 策略 | AnnRet | AnnVol | Sharpe | t-stat | MDD | Skew |
|------|--------|--------|--------|--------|-----|------|
| Buy-and-Hold | 0.162 | 0.514 | 0.316 | 0.93 | -83.7% | -1.35 |
| VT(10%) | 0.062 | 0.119 | 0.520 | 1.52 | -30.2% | -1.00 |
| **VT(15%)** | **0.088** | **0.178** | **0.495** | **1.45** | **-42.2%** | -1.00 |
| VT(20%) | 0.112 | 0.238 | 0.470 | 1.38 | -52.3% | -1.00 |
| **Asym VT(25/10)** | **0.157** | **0.232** | **0.676** | **1.98** | **-53.3%** | +0.31 |
| VT(15%) monthly | 0.086 | 0.184 | 0.466 | 1.36 | -43.2% | -1.27 |

### 統計檢定
- MDD improvement (VT 15% vs BH): bootstrap **p=0.003 (SIGNIFICANT)**
- Sharpe improvement: all t < 2.0 → **FAILS Harvey t>3**
- Asymmetric vs symmetric VT: t=2.2 → **FAILS Harvey**
- 子期間：VT 在 4/4 期間都改善 MDD，但 Sharpe 僅 2/4 勝出

### 三資產投資組合（2020-2025 OOS）
| Portfolio | AnnRet | AnnVol | Sharpe | MDD | Skew |
|-----------|--------|--------|--------|-----|------|
| 60/40 SPY/GLD | 0.143 | 0.149 | 0.962 | -24.3% | -0.38 |
| 50/40/10 raw | 0.166 | 0.161 | 1.031 | -27.3% | -0.96 |
| 50/40/10 VT_BTC | 0.136 | 0.139 | 0.983 | -22.5% | -0.59 |
| 50/40/10 VT_both | 0.123 | 0.107 | 1.154 | -16.3% | -0.60 |

- **加 BTC 沒有顯著 Sharpe 改善**（最佳 diff=+0.19, Harvey t=0.33）
- BTC coskewness = **-0.61（負值！）** → BTC 惡化組合尾部，非改善
- BTC-SPY corr=0.39（中度正相關，非零）

### BTC VT vs Equity VT 關鍵差異
| 指標 | BTC VT(15%) | SPY VT(12%) |
|------|-------------|-------------|
| Vol / Target | 3.4x | 1.7x |
| Avg weight | 0.38 | 0.86 |
| % days weight<0.5 | 79.9% | 16.0% |
| Annual turnover | 4.05x | 7.18x |
| TC cost (10/2 bps) | 0.40% | 0.14% |
| 本質 | **減碼工具** | **槓桿工具** |

### 實務建議
1. **Crypto VT 規則**：weight = min(0.15 / RV_22d, 1.5)，月度調倉即可
2. **定位**：position sizing discipline，非 alpha 來源
3. **BTC 配置**：在 SPY+GLD 組合中 10% 足矣，更多反而惡化偏態
4. **不要用 VIX**：BTC 與 VIX 無關聯，使用自身 realized vol
5. **不要基於「正偏態」做策略**：此特性不穩定
