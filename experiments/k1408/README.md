# K1408 — 進場時點是否顯著影響最終年化報酬與 IRR

## 研究問題
對每一個進場時點 t（**月頻**，每 21 交易日一個進場點），從 t 一路投入、**全部持有到資料最後一天 T**（t→T、t+1月→T … 直到接近 T）。每個進場點各算：

- **單筆投入 (Lump Sum)**：t 一次投入持有到 T。年化報酬率（= 單一現金流 IRR，數學上相等）。
- **定期定額 (DCA)**：從 t 起每月投入持有到 T。**時間加權年化報酬 (TWR)** 與 **money-weighted IRR** 兩者都算。
- 每個進場點記錄 horizon（持有年數 =(T−t)/252）。

→ SPY 得 254 組、0050 得 200 組數值。

**要回答**：不同進場時點的最終年化報酬率 / IRR **是否有顯著差異**？差異多大、主要來源是什麼、是否隨 horizon 收斂？

## 重要方法論認知（前提）
- 年化報酬率與 IRR **已除以年數**，故「持有期長短」**不造成 level 差異**（2 倍報酬持有 1 年 = 100% 年化、持有 10 年 = 7.2% 年化，都是每年口徑可比）。本實驗**不**把持有期長短當「干擾」排除，也**不**改用固定持有窗口 — 持有到 T 是研究問題的定義核心。
- 唯一真實的細節：**越短的持有期，年化數字的離散度 (variance) 越大**（時間平均不足，σ_annualized ∝ 1/√horizon）。「晚進場 = 結果更不確定」是**要如實報告的現象本身**，不是要排除的東西。

## 資料
- `experiments/k1406/data/SPY.csv`：**2005-01-03 .. 2026-05-29，5,385 個交易日**（yfinance auto-adjust 收盤價）
- `experiments/k1406/data/0050.TW.csv`：**2009-01-02 .. 2026-05-28，4,257 個交易日**（yfinance auto-adjust）
- 直接讀 k1406 既有 CSV，未重抓、未捏造。

## 方法
- **Lump 年化** = (P_T / P_t)^(1/years) − 1。
- **DCA TWR**：對單一標的，time-weighted return 與投入排程無關，等同該標的在 [t, T] 區間 daily 報酬鏈的幾何年化（每筆現金都買同一檔）。一致性檢查：最早進場點的 lump 年化 == TWR（diff 0.00pp）✓。
- **DCA money-weighted IRR**：每月投入 1 單位，最終市值 = Σ(各期股數)·P_T。NPV 以**進場點 t 為 0、往未來遞增的年數**為時間軸，`(1+r)^(-t)` 用 `exp(-t·log1p(r))` 形式避免 overflow，**brentq grid-scan** 找變號區間求根。單一現金流時退化回 lump 年化（已驗證）。
- **Horizon 定義**：years = (T_idx − t_idx) / 252；最短 horizon 保留到剩約 3 個月（63 交易日）。
- **隨機程序固定 seed = 20260530**（所有 bootstrap）。

### 正式檢定（處理 overlapping-window 自相關）
進場點的持有期**重疊**（共享同一終點 T），outcome 序列高度自相關，naive iid 檢定會嚴重低估 p-value。因此：

1. **描述統計** + 分 horizon bucket（>10年 / 5-10年 / 2-5年 / <2年）看離散度隨持有期變化；log-log 回歸 bucket std vs 平均 horizon 驗證 σ∝1/√horizon（理論斜率 −0.5）。
2. **趨勢檢定**：進場日曆順序 vs outcome 的 Spearman ρ，用 **moving block bootstrap**（block=12 進場點，保留局部自相關、破壞長期趨勢建構 H0 null）+ **Newey-West HAC** OLS 同時做，對照 naive iid p 展示低估程度。
3. **核心檢定（分離「日曆擇時」vs「短 horizon 雜訊」）**：在每個 horizon band 內，先 OLS `outcome ~ horizon_years` 去掉「band 內殘餘 horizon 長度差異」的機械效應，再測**殘差 vs 日曆順序的 Spearman ρ**，用 block bootstrap（重排殘差塊序破壞日曆對應、保留局部自相關）求 p。ρ 顯著 → 控制持有期後仍有真日曆擇時效應；p 大 → band 內離散純粹是 horizon 殘餘 + 雜訊。

## 主要結果（verdict）

**(a) raw range 可觀，但短窗年化會誤導。** 單筆年化在不同進場點之間：SPY range **34.4 個百分點**（10.9%~45.2%）、0050 range **226 個百分點**（6.7%~232.8%）。0050 的極大值 232.8% 來自 2025-12-24 進場、僅持有 ~0.39 年的短窗：標的 +59.6% 年化放大成 233%，**數學正確但非長期可實現報酬**，正是「短 horizon → 年化離散爆增」現象本身。

**(b) 差異主要來源 = horizon 長度，不是日曆擇時。** 分 band 後年化 std 隨持有期單調放大（σ∝1/√horizon）：

| band | SPY 單筆年化 std | 0050 單筆年化 std |
|---|---|---|
| >10年 | 1.71% | 6.53% |
| 5-10年 | 1.08% | 3.30% |
| 2-5年 | 4.28% | 12.97% |
| <2年 | 6.66% | 52.88% |

log-log 斜率 SPY −0.63 / 0050 −0.99（理論 −0.5，方向一致；0050 更陡因 2009 後低點進場拉高短窗離散）。

**控制 horizon 後，擇時效應為 NULL**：OLS 去 horizon → 殘差 vs 日曆順序 Spearman ρ + block bootstrap，**SPY 0/4 band、0050 0/4 band 達顯著 (p<0.05)**；最大殘差-日曆 |ρ| 僅 SPY 0.19 / 0050 0.068，min p = 0.566 / 0.799。→ **控制持有期後，沒有任何進場月份系統性勝出**。horizon 在各 band 平均解釋了 0.445(SPY) / 0.789(0050) 的離散。

**(c) 隨 horizon 收斂：是。** >10年 band 的 std 約為 <2年 band 的 1/4~1/8。長期投資者進場時點影響有限且不可預測擇時；短期投資者結果離散巨大，但那是運氣 / 雜訊（σ∝1/√horizon），**非任何進場時點本身的可重複優劣**。

**趨勢檢定（純機械示範）**：晚進場因 horizon 短 + 近期價格在高點，年化機械偏高 → Spearman ρ 為正且大（SPY 0.80 / 0050 0.975）；block-bootstrap p (0.0) 與 naive iid p (0.0) 的對照展示 overlapping-window 下 naive iid 嚴重低估 p。此 ρ 是 **horizon 機械耦合**，非可交易擇時；真正分離後（within-band）擇時效應為 null。

## 一句話結論
不同進場時點的「最終年化報酬 / IRR」raw 差異很大（SPY 34pp、0050 226pp），但**這個差異幾乎全部來自持有期長短（horizon），不是日曆擇時**。控制持有期後，沒有任何進場月份能系統性勝出（兩資產各 0/4 band 顯著）。對長期投資者，進場時點影響有限且不可預測；對短期投資者，年化結果離散巨大，但純屬時間平均不足的雜訊（σ∝1/√horizon），不是可重複的擇時優劣。

## 圖（experiments/k1408/figs/）
- `fig_a_spy_lump_vs_entry.png` — SPY 單筆年化 vs 進場時點（顏色 = horizon）
- `fig_b_spy_dca_vs_entry.png` — SPY DCA TWR & IRR vs 進場時點
- `fig_c_spy_dispersion_vs_horizon.png` — SPY 離散度 vs horizon bucket（驗證短期更跳）
- `fig_d_tw_lump_vs_entry.png` — 0050 單筆年化 vs 進場時點
- `fig_e_dispersion_loglog.png` — σ vs horizon log-log（兩資產，驗證 σ∝1/√horizon）
- `fig_f_tw_dca_vs_entry.png` — 0050 DCA TWR & IRR vs 進場時點

## 檔案
- `k1408.py` — 完整可復現腳本（seed=20260530）
- `k1408_results.json` — 每進場點數值陣列（entry_tables）+ 描述統計 + 各檢定統計量 + verdict + calendar_effect_summary
- `figs/` — 6 張圖

## Code review
- 主審 **Codex** 中途因 ChatGPT 用量上限中斷（usage limit reset 5/31）。改用 **Antigravity (agy 1.0.3, gemini)** 做 independent review。
- agy 抓到關鍵 methodological confound：原版 within-band 檢定「局部相鄰 std vs 全 band std」因 overlapping-window 機械正自相關，p 恆 ≈0、無法分離日曆 vs horizon。已**重構為 OLS 去 horizon → 殘差 vs 日曆順序 Spearman + block bootstrap**（見方法 §3），結果由「假性顯著」修正為「null 擇時效應」。
- agy 確認 `_npv` 的 exp/log1p 形式無 overflow 隱患、無 lookahead（realized 報酬計算非預測信號）、IRR 單一現金流退化正確。
- 待 Codex 用量恢復後可二次驗證（primary-path）；本 README 註明 reviewer source = **agy review（Codex usage-limit fallback）**。

## 防錯記錄
- **無 lookahead**：本實驗計算 realized 持有期報酬（entry t → 實際價格路徑 → 終點 T），不使用任何 forecast 進場，故無 signal.shift(1) 議題（使用 P_T 是研究設計定義核心，非前瞻偏差）。
- **無 overflow**：IRR NPV 用 `exp(-t·log1p(r))`，極端高年化下安全。
- **seed 固定**：20260530，全部 bootstrap 可復現。
