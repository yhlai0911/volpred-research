# K1660 — Conditional（regime-gated）波動率目標 vs 永遠 VT：淨成本績效檢定

**Verdict: NULL** — Regime-gated VT 相對 Always-VT 大幅省下換手（SPY −41%、0050.TW −47% 年換手），
但**淨成本後的 Sharpe / Calmar 無統計顯著改善**；差異符號在跨資產、跨參數之間翻轉，全部落在 noise 範圍內
（所有 bootstrap 95% CI 皆跨 0）。省下的換手成本被「低波動期放棄槓桿的報酬損失」抵消。

---

## 1. 動機

Volatility Targeting（VT）永遠按預測波動率縮放曝險（exposure = target_vol / forecast_vol）。
批評者常主張：VT 在**平靜期**（低波動 regime）仍持續小幅換手 → 累積交易成本卻沒實質風險改善。
本題檢定一個 practitioner 常見的「省成本」宣稱：

> 只在偵測到**高波動 regime** 時才啟動 VT（regime-gated），平靜期維持 buy-and-hold（曝險 = 1，不換手），
> 能否透過省下平靜期無謂換手，改善**淨成本後**的 Sharpe / Calmar？

## 2. 與庫內既有研究的差異化

| 既有 K | 機制 | 結論 | 與本題差異 |
|---|---|---|---|
| `regime_adaptive_overlay` | 連續 cap 60% / floor 120% overlay | Sharpe 0.61→0.53 harmful | 連續調整、**不計交易成本** |
| `adaptive_vt_regime_target` | 高/低波動改 target vol（12%/10%） | Sharpe 0.697→0.705（微幅） | 調 target 非 **on/off 開關** |
| CED（research_program.md line 623） | backward-looking 連續 tail scaler | NULL | 連續 scaler、非二元 regime gate |
| Rebalancing 頻率 K | Monthly 減 whipsaw | Monthly 最佳 | 頻率非 regime gate |

**本題新機制 = 二元 regime on/off 開關 + 以交易成本為核心的淨績效比較**。既有 regime overlay 的 K 全部
未把交易成本納入比較維度；本題正面檢定「省換手成本」這個賣點是否成立。

## 3. 文獻

1. **Moreira & Muir (2017)**, "Volatility-Managed Portfolios", *Journal of Finance* 72(4):1611-1644 —
   VT 提高 Sharpe，因 vol 變化不被 expected return 成比例抵消。本題延伸：加入交易成本 + regime on/off。
2. **Harvey, Hoyle, Korgaonkar, Rattray, Sargaison & van Hemert (2018)**, "The Impact of Volatility Targeting",
   *Journal of Portfolio Management* 45(1) — VT 對 Sharpe 的貢獻主要來自「vol clustering 讓 realized vol 可預測」，
   並詳細討論 turnover / 交易成本。本題採其 realized-vol forecast 精神。
3. **FAJ — "Conditional Volatility Targeting"**（Financial Analysts Journal）— conditional / regime-dependent VT
   的實務論述，本題的直接對照題材。
4. **Bongaerts, Kang & van Dijk（cost-aware volatility management）** 與 **Barroso & Detzel（factor VT net of cost）** —
   淨成本後 vol management 是否存活的相關辯論；本題在單一資產層面做 on/off 版本的檢定。

## 4. 方法

### 資料
- **SPY**（主，S&P 500 ETF）與 **0050.TW**（robustness，元大台灣 50 ETF），yfinance auto-adjusted close。
- 期間 **2010-01-05 .. 2026-06-30**：SPY n=4,146 交易日；0050.TW n=4,028。含 2018/2020/2022 三次空頭。
- **資料清洗**：0050.TW 依台股 ±7%/±10% 漲跌幅限制，將 |日報酬| > 11% 判定為 yfinance adjustment glitch 移除
  （實際移除 **1 筆**：2014-01-02 −75.06%，明顯壞值）。SPY 無漲跌幅限制市場，不清洗（removed=0）。
  未清洗前該壞值 × 1.5x 槓桿使 cumulative wealth 變負、MDD 爆到 −196%，是資料錯誤非策略行為。

### 訊號與 lag 慣例（防 lookahead — 最高優先）
- **Vol forecast**：`rv20 = rolling(20).std() × √252`（主）或 EWMA(λ=0.94)（robustness），僅用 up-to-t 報酬。
- **Always-VT 曝險**：`exposure = clip(target_vol / forecast_vol, 0, cap)`，target_vol=15%，cap=1.5。
- **Regime detector**：`rv20_t > rolling(252).quantile(q)`（q=0.6 主），threshold 用 up-to-t 的 252 日滾動分位數。
- **Regime-gated 曝險**：高波動 regime → 用與 baseline 相同的 VT 曝險；低波動 regime → 強制 exposure = 1（buy-and-hold）。
- **持倉 lag**：所有訊號在日 t 收盤用 up-to-t 資訊算，`pos_t = exposure.shift(1)` 才進入 t+1 持倉賺 `ret_t`；
  turnover = `|pos.diff()|` 與 position 對齊。**無 lookahead**（代碼 `backtest()`：`pos = exposure.shift(1)`）。

### 成本模型（公平比較）
- Per-turnover 單邊成本：`net_ret = pos·ret − (bps/1e4)·|pos.diff()|`。
- **Baseline 與 gated 共用**同一 vol forecast、同一 cap/floor、同一成本率、同一 lag；gated 唯一差別 = 低波動 regime 時 exposure=1。
- 成本 sensitivity：**1 / 5 / 10 / 20 bp**（單邊）。

### 檢定（不看數字下結論）
- 淨 Sharpe / Calmar / MDD / 年化換手率。
- **淨 Sharpe 差（gated − always-VT）**：circular block bootstrap（block=20，B=10,000，**seed=42**），
  joint resample 兩策略同日 net return 對（保留 cross-correlation），回報 95% CI + 雙尾 bootstrap p。
- **日均淨報酬差**：Newey-West HAC t-test（lag=regime window）。
- Robustness：regime 分位數 q ∈ {0.5,0.6,0.7,0.8}、cap ∈ {1.0,1.5,2.0}、vol method ∈ {rolling20, ewma94}。

## 5. 結果

### 5.1 主 spec（target 15%、cap 1.5、q=0.6、rolling20、成本 5bp）

| 資產 | 策略 | 淨 Sharpe | Calmar | MDD | 年化換手 |
|---|---|---|---|---|---|
| **SPY** | Buy&Hold | 0.874 | 0.429 | −33.7% | 0.00 |
| | Always-VT | 0.953 | **0.755** | −19.0% | 6.60 |
| | **Regime-gated VT** | **0.971** | 0.690 | −18.9% | **3.88** |
| **0050.TW** | Buy&Hold | 0.975 | 0.524 | −33.8% | 0.00 |
| | Always-VT | 0.911 | 0.497 | −29.5% | 8.55 |
| | **Regime-gated VT** | 0.899 | 0.459 | −29.4% | **4.56** |

- **SPY**：gated 淨 Sharpe +0.018（bootstrap CI95 **[−0.087, +0.125]**，p=0.72）；NW t=−1.74（p=0.081，日均淨報酬 gated 反而**略低**）。高波動 regime 佔 35.7%。
- **0050.TW**：gated 淨 Sharpe −0.012（CI95 **[−0.108, +0.087]**，p=0.82）；NW t=−1.51（p=0.132）。高波動 regime 佔 41.4%。
- 兩資產 gated 都**大減換手**（SPY −41%、0050.TW −47%），但**淨 Sharpe 差異統計上與零無異**；Calmar 甚至略降。

### 5.2 成本 sensitivity（淨 Sharpe 差 = gated − always-VT）

| 成本 | SPY diff | SPY CI95 | 0050 diff | 0050 CI95 |
|---|---|---|---|---|
| 1 bp | +0.012 | [−0.093,+0.119] | −0.021 | [−0.117,+0.078] |
| 5 bp | +0.018 | [−0.087,+0.125] | −0.012 | [−0.108,+0.087] |
| 10 bp | +0.025 | [−0.080,+0.133] | −0.001 | [−0.098,+0.098] |
| 20 bp | +0.040 | [−0.065,+0.148] | +0.021 | [−0.077,+0.121] |

- **機制方向正確但幅度不足**：成本越高，gated 相對優勢單調上升（SPY +0.012→+0.040；0050 −0.021→+0.021），
  符合「省換手在高成本時更有價值」的理論預期。但**即使 20bp 極端成本，所有 CI 仍跨 0**，無統計顯著性。

### 5.3 Robustness（淨 Sharpe 差符號不穩定）

- **regime 分位數**：SPY q0.5-0.7 微正（+0.010~+0.023）、q0.8 轉負；0050 q0.5 微正、q0.6-0.8 皆負。跨資產符號相反。
- **cap / vol method**：**cap=1.0（無槓桿）時 gated 優勢消失甚至變負**（SPY −0.005、0050 −0.016）；cap=1.5/2.0 或 EWMA 時 gated 微正。
  → 證實主 spec 的微弱正差**部分來自 always-VT 在低波動期加槓桿到 1.5 的報酬/風險 profile 差異，而非純粹省成本**。

## 6. 結論與機制

**NULL — regime on/off gating 省下大量換手（40-47%），但不轉化為淨成本後的 Sharpe/Calmar 改善。**

機制解釋（為何省成本不生效）：
1. **平靜期 VT 的換手本來就小**：低波動 regime 中 forecast_vol 穩定 → always-VT 的 exposure 也穩定 → 省下的成本絕對值有限。
2. **低波動期強制 exposure=1 = 放棄槓桿**：always-VT 在平靜期 vol < target 時 exposure 升到 cap（≤1.5）並賺取多頭報酬；
   gated 把它壓回 1.0，放棄的報酬部分抵消了成本節省（cap=1.0 robustness 下 gated 優勢即消失，正是此證據）。
3. 兩效應大致相抵 → 淨 Sharpe 統計上與零無異，符號隨資產/參數翻轉。

本結論延續庫內 `regime_adaptive_overlay`（harmful）、`adaptive_vt_regime_target`（微幅）、CED（NULL）的
regime-overlay NULL family，並**新增交易成本維度的正面量化**：即使把「省成本」設為核心賣點、即使測到 20bp 極端成本，
二元 regime gating 也無法在淨成本後顯著贏過永遠 VT。turnover 是真的省了，但 risk-adjusted 淨績效沒有免費午餐。

**策略上架含義**：不建議把 regime-gated VT 排入上架評估 —— 相對永遠 VT 無淨績效優勢，且引入 regime 門檻參數
（q、window）增加 overfitting 面且符號不穩。永遠 VT（既有 active 策略）仍是較穩健的簡單配置。

## 7. Lag / embargo 聲明

- 本實驗為**策略回測**（非 forward-label 回歸），主要 lookahead 風險在 weight timing：已用 `pos = exposure.shift(1)` 明確 lag，
  turnover 與 position 對齊，regime threshold 用 up-to-t 滾動分位數後隨 exposure 一併 shift。無 forward-label target，故無 train-tail embargo 議題。
- 所有隨機程序（block bootstrap）固定 **seed=42**。
- Codex code review：見 §8。

## 8. Codex review

見 `reviews/codex_review.md`（VERDICT + 逐項）。Bar：CONDITIONAL_PASS 以上方可寫入 knowledge.json（由主線程負責，本 worktree 不寫共享狀態）。

## 9. 檔案清單

- `README.md`（本檔）
- `k1660_regime_gated_vt.py`：可復現腳本，seed=42，`exposure.shift(1)` 明確
- `k1660_results.json`：全部數字（Sharpe/Calmar/MDD/turnover/成本+regime+cap sensitivity/bootstrap CI/NW t）+ 期間 + 樣本數 + 資料來源 + 清洗紀錄
- `data/`：yfinance 快取（SPY、0050.TW）
- `figures/equity_curve.png`：三策略淨成本 equity（log scale）
- `figures/exposure_regime.png`：曝險路徑 + 高波動 regime 標記
- `reviews/codex_review.md`：Codex 代碼審查紀錄

## 10. 復現

```bash
uv run python experiments/k1660/k1660_regime_gated_vt.py
```
（首次會 yfinance 下載並快取到 `data/`；之後讀快取確保 byte-level 復現。）
