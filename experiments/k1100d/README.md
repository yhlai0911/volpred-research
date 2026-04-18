# K1100d: VIX Regime-Switching Copula

- **提出者**: 用戶 (賴奕豪 Lai Yi-Hao)
- **設計/執行**: Claude (autonomous-research, worktree agent)
- **日期**: 2026-04-17
- **狀態**: 完成
- **父實驗**: K1100b (5/5 NULL — Student-t / Clayton copula 無法打敗 DCC-A4f-ASYM)
- **關聯**: K1100c (asymmetric copula 方向，同期並行)、K1092 (A4f-ASYM best)、K1041 (DCC-A4f)

---

## 問題 (Research Question)

K1100b 對所有市場狀態使用統一 copula family，發現 5/5 NULL。

**K1100d 的核心假設**：K1100b NULL 是「regime-averaging artifact」——低 VIX 時市場相對獨立（Gaussian 夠用），高 VIX 時尾部聯動強（需 Student-t / Clayton）。若 regime-switching copula 在 VIX 高低 regime 各用最適 copula，能否打敗 uniform DCC？

## 方法 (Method)

### 資料

與 K1100b 完全一致：
- 5 pairs: SPY-QQQ, SPY-XLF, SPY-IWM, SPY-TLT, SPY-GLD (50/50 weight)
- 2005-01-04 ~ 2026-04-09, yfinance
- Marginals: A4f-VIX GARCH; GLD 用 GVZ
- OOS: 2013-06-01 ~ 2026-04-09 (3233 days/pair)

### Regime 定義（2 方案，均測以驗穩健性）

| 方案 | 定義 | High-VIX 佔比 |
|------|------|--------------|
| **R1** | VIX(t-1) ≥ 25（古典危機門檻） | 12.2% (393/3233 days) |
| **R2** | VIX(t-1) ≥ rolling 252-day 75th pct（自適應） | 24.7% (797/3233 days) |

**關鍵 lookahead 防範**：`regime(t) = VIX(t-1) >= threshold`（強制 lag-1）

### 模型（6 個）

| 模型 | 說明 |
|------|------|
| **M1: DCC-A4f-ASYM** | baseline（K1092 最佳） |
| **M2: Copula-t-A4f-ASYM** | K1100b 重現（uniform Student-t） |
| **M3: RS-Copula-Gaussian-t-R1** | VIX(t-1)<25 → Gaussian copula; VIX(t-1)≥25 → Student-t copula |
| **M4: RS-Copula-Gaussian-Clayton-R1** | VIX(t-1)<25 → Gaussian; VIX(t-1)≥25 → Clayton |
| **M5: RS-Copula-Gaussian-t-R2** | 同 M3 但用 R2 adaptive threshold |
| **M6: RS-Copula-Gaussian-Clayton-R2** | 同 M4 但用 R2 adaptive threshold |

Rolling MLE 重要細節：估計 high-VIX 參數時只用 training window 內 high-VIX 天的 (u₁, u₂)；low-VIX 同理（within-regime MLE）。若 regime 內 obs < 30，fall back 到全 window 估計。

### 評估

- Training window: 1250 days; refit every 63 days
- MC paths: 5000/day, seed=42
- **分 regime 子樣本 DM（critical）**：全 OOS DM + high-VIX 子期 DM + low-VIX 子期 DM
- Harvey |t|>3.0 全期；regime 子期 |t|>2.5 + Bonferroni(4 tests)
- Trinity (Kupiec + CC + Basel) + FZ + Acerbi-Szekely Z1

---

## 結論 (Findings)

### Scenario 判定：**B（NULL）**

> **B (NULL): All RS models 5/5 NULL → mixing-averaging is fundamental, not regime-specific**

即使加入 VIX regime-switching，所有 RS copula 模型在所有 5 個 pair 上仍未達到 Harvey |t|>3.0 門檻。5/5 NULL 確認。

### 主表：By-Regime DM t-stat（DCC vs RS-Copula-Gaussian-t-R1）

> 正值 = RS 模型比 DCC 好；負值 = DCC 比 RS 模型好

| Pair | Full OOS | High-VIX R1 | Low-VIX R1 | High-VIX R2 | Low-VIX R2 | Harvey Full |
|------|----------|-------------|------------|-------------|------------|-------------|
| **SPY-QQQ** | +0.374 | −0.390 | +0.534 | +1.907 | +0.712 | ❌ |
| **SPY-XLF** | +2.256* | −0.788 | **+2.496*** | +1.093 | +2.154* | ❌ |
| **SPY-IWM** | +2.288* | −0.535 | **+2.374*** | +1.858 | +1.957* | ❌ |
| **SPY-TLT** | −3.682*** | −0.862 | −3.779*** | −1.878 | −3.667*** | ✅ DCC wins |
| **SPY-GLD** | −2.155* | −0.563 | −2.182* | −0.034 | −1.647 | ❌ |

- `*` p<0.05 normal, `***` Harvey |t|>3.0
- RS-Copula-Gaussian-t-R1 代表性 RS 模型，其他 RS 模型（R1-Clayton, R2-t, R2-Clayton）結果類似

### 完整 6 模型 × 5 Pair 全 OOS DM 表（vs DCC-A4f-ASYM）

| Pair | Cop-t | RS-Gt-R1 | RS-GCl-R1 | RS-Gt-R2 | RS-GCl-R2 | Harvey |
|------|-------|----------|-----------|----------|-----------|--------|
| SPY-QQQ | +0.676 | +0.374 | +0.423 | +1.652 | −0.275 | 0/5 ❌ |
| SPY-XLF | +1.769 | +2.256* | +2.288* | +2.369* | +2.224* | 0/5 ❌ |
| SPY-IWM | +2.114* | +2.288* | +2.109* | +2.586* | +2.080* | 0/5 ❌ |
| SPY-TLT | −3.995*** | −3.682*** | −4.192*** | −3.599*** | −4.645*** | 5/5 DCC wins ❌ |
| SPY-GLD | −1.454 | −2.155* | −1.741 | −1.331 | −1.089 | 0/5 ❌ |

SPY-XLF 和 SPY-IWM 在 full OOS 上 RS 模型接近但未超過 Harvey t>3.0；SPY-TLT 仍然是 DCC 強勢勝出。

### 關鍵觀察

**1. Regime-switching 無法突破 Harvey 門檻**
- 最接近的是 SPY-XLF/IWM RS-Copula-Gaussian-t-R2（t≈2.37–2.59），但離 t=3.0 仍有距離
- 即使分 high/low VIX 子期，RS copula 在 high-VIX（理應 Student-t 最強）子期反而 DM 較弱（SPY-XLF high-VIX R1 t=−0.79）

**2. 高 VIX 子期 RS 模型沒有明顯優勢**
- 理論預期：在 crisis（high VIX）中 Student-t copula 最強 → RS 模型 high-VIX t-stat 應最高
- 實際：SPY-XLF high-VIX R1 = −0.788（DCC 略勝），R2 = +1.093（RS 略勝但不顯著）
- SPY-QQQ high-VIX R1 = −0.390（DCC 略勝）
- **高 VIX 時 copula 優勢並未增強**，推翻「regime-switching 救活 copula」假設

**3. Low-VIX 子期的微弱訊號**
- SPY-XLF 和 SPY-IWM 在 low-VIX 子期 DM 較強（t≈2.4–2.5）
- 這可能反映低 VIX 時 Gaussian copula 比統一 Student-t 更貼近實際分佈 → RS 的優勢不是來自高 VIX 尾部，而是低 VIX 時 Gaussian 的節省
- 但即使如此也未達到 Harvey 顯著

**4. SPY-TLT 仍然最強烈反向**
- 所有 6 個模型，包括 RS 版本，都在 SPY-TLT 上 DCC 顯著勝（t=−3.6 至 −4.6）
- Regime-switching 無法改變負相關 pair 的本質問題（Clayton 強制 θ→0，t copula MC 雜訊大）
- SPY-TLT high-VIX 子期 DM 其實較不顯著（RS-t R1 = −0.86），說明在 crisis 時 RS 模型稍微縮小差距，但全 OOS 仍被負相關 low-VIX 主導

**5. Regime 覆蓋率合理**
- R1 high-VIX：12.2%（393 天），對應 2008-2009 GFC 尾端 + 2020 COVID + 2022 inflation shock
- R2 adaptive（24.7%）提供更多 high-VIX 觀察，但結論一致

### 四種 Scenario 判定

| Scenario | 條件 | 結果 |
|----------|------|------|
| **A**: RS 有 pair Harvey |t|>3 full OOS | ≥1 pair RS 顯著勝 DCC | ❌ 未達到 |
| **B**: 5/5 NULL，含 regime 子期 | 所有 pair 所有模型 NULL | ✅ **CONFIRMED** |
| **C**: tail-dep pairs PASS，tail-indep NULL | SPY-QQQ/XLF/IWM PASS | ❌ 未達到 |
| **D**: high-VIX 子期 PASS，full OOS NULL | |t|>2.5 high-VIX | ❌ 未達到（high-VIX 反而弱） |

**最終：Scenario B** — RS 無法救活 K1100b NULL 結論。

### 與 K1100b 的比較

K1100b（uniform copula）DM t-stat 對照：
- SPY-QQQ Copula-t: +0.624 → K1100d +0.676（無改善）
- SPY-XLF Copula-t: +1.812 → K1100d RS-Gt-R1: +2.256（接近 Harvey 但未達）
- SPY-IWM Copula-t: +2.196 → K1100d RS-Gt-R2: +2.586（接近 Harvey 但未達）
- SPY-TLT Copula-t: −4.293 → K1100d RS-Gt-R1: −3.682（略緩和）
- SPY-GLD Copula-t: −1.699 → K1100d RS-Gt-R1: −2.155（略差）

Regime-switching 在正相關 equity pair（XLF, IWM）略有改善，但距 Harvey t=3.0 仍有 0.4–0.7 的差距。

### 與 K1100c 的比較

K1100c 測試 asymmetric copula（skew-t / vine），方向不同。若 K1100c 也回報 NULL，則 K1100b + K1100d + K1100c 三實驗三路徑均為 NULL，Paper 3 copula 路線可確定性地否定 → Paper 3 需要轉向「periodic return structure + copula」或聚焦 futures-hedge pairs。

### Paper 3 Implication

1. **Mixing-averaging 是根本問題**（非 regime-averaging artifact）：即使 regime-splitting 後，copula 的尾部信息在 50/50 portfolio 中仍被稀釋。
2. **Regime-switching 的微弱 low-VIX signal**：SPY-XLF/IWM 在低 VIX 期 RS copula 略優（Gaussian 比 uniform Student-t 更精簡），但這是 parameterization efficiency 效應，不是尾部聯動效應，學術意義有限。
3. **Paper 3 走向建議**（強化 K1100b 結論）：
   - ❌ Copula 對 general equity portfolios（50/50 symmetric）無決定性優勢，包括 regime-switching 變體
   - ✅ Paper 3 核心應聚焦「periodic return structure + copula」（PRG spot-futures pair），那裡尾部聯動 ~0.99 correlation，不會被 portfolio averaging 稀釋
   - ✅ K1100d + K1100b 共同提供「為什麼 general equity copula 失敗」的完整解釋：portfolio QLIKE 主要由 ρ_t 主導，copula 的額外尾部結構在 50/50 mixing 下消失

---

## 研究誠實聲明

- **實驗數據**：yfinance daily data, 2005-2026, 5349 days × 6 assets
- **NULL result 如實回報**：Scenario B 確認，未修飾
- **Lookahead 防範**：regime(t) = VIX(t-1) 嚴格 lag-1；代碼中 `vix_lag1[1:] = vix_series[:-1]`
- **seed=42 固定**：所有 MC 路徑（每日 sub_rng = np.random.default_rng(42+i)）
- **局限性**：
  - Within-regime MLE：高 VIX 觀察少（R1 12.2%），估計不穩定是已知風險
  - R3（HMM Markov switching）因 R1/R2 均 NULL 而跳過，此決定合理
  - Portfolio 固定 50/50；其他權重下可能不同，但 CLT portfolio-averaging 效應在 2-asset case 普遍存在
  - 未測 k=3 vine copula（更複雜但計算成本高）

---

## 檔案 (Files)

- `k1100d.py`: 完整實驗腳本（~800 行）
- `k1100d_results.json`: 5 pairs × 6 models 完整結果
- `k1100d_dm_by_regime.png`: 5 pairs × 2 regimes × 2 RS models DM heatmap（核心圖）
- `k1100d_fz_regime_comparison.png`: FZ score by regime 比較圖
- `run.log`: 完整執行記錄

---

## 參考文獻 (References)

- Hamilton (1989). A new approach to the economic analysis of nonstationary time series and the business cycle. *Econometrica* 57(2). [Markov regime switching]
- Patton (2006). Modelling asymmetric exchange rate dependence. *IER* 47(2). [Time-varying copula]
- Christoffersen, Errunza, Langlois & Huang (2012). Is the potential for international diversification disappearing? *RFS* 25(12). [Regime copula]
- Rodriguez (2007). Measuring financial contagion: A copula approach. *Journal of Empirical Finance* 14(3). [Regime-switching copula contagion]
- Harvey, Leybourne & Newbold (2016). Tests of equal forecast accuracy. *JBES* 15(2).
- Fissler & Ziegel (2016). Higher order elicitability and Osband's principle. *Ann Stat* 44(4).
- Kupiec (1995). *J Derivatives* 3(2). / Christoffersen (1998). *Int Econ Rev* 39(4).
- K1100b (2026-04-13): 5/5 NULL with uniform copula — parent experiment.
- K1092 (2026): DCC-A4f-ASYM best marginal specification.
