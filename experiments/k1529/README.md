# K1529 — 稅務 friction 對 VT / Risk-Parity 風控的機械破壞檢定

- Experiment ID: `k1529`
- Status: completed
- Created At: 2026-06-17 (Asia/Taipei)
- Audience: research (paper-grade)

## 問題描述

資產配置實證文獻（Volatility Targeting / Risk-Parity / Inverse-Vol weighting）
普遍預設「再平衡可免費執行」。但在實務 taxable 帳戶（個人 / 大部分機構非 401k
退休金），每次賣出獲利資產要付 realized-gain tax：
- 短期 capital gains（持有 < 1 年）→ 22-37% federal（中位數 32% 模型用值）
- 長期 capital gains（持有 ≥ 1 年）→ 15-23.8% federal（20% 模型用值）

每次強制再平衡 → 賣出贏家 + 買入輸家 → trigger taxable event → 本金縮水。本實驗
量化此 friction 是否會 mechanically 破壞 VT / RP 風控規則（target vol tracking、
risk-budget 平衡）並衡量 after-tax Sharpe drag。

## 動機 / 差異化

VolPred 之前的 VT / RP 系列實驗（K1217 rebalance_freq_hybrid_vt、SPY+GLD RP base、
4-asset RP fail、tail_risk_parity）全在 tax-free 假設下評估。本實驗第一次：

1. 把 tax friction 加進 VT/RP 評估口徑
2. 量化 mechanical vol tracking 破壞（target 10% annualized 還守得住嗎？）
3. 比較三種 tax management 規格的 trade-off：
   - NO_TAX：tax-free benchmark（學術論文 default）
   - PERIODIC：月底 rebal + 全額 realize tax（naive taxable 投資者）
   - TAX_AWARE：5% drift tolerance band，僅超過才賣（minimize taxable events）

## 相關 K（已知結論）

- **SPY+GLD 2-asset RP**：Sharpe ~1.18（best baseline; GLD-SPY corr 0.130 最佳分散）
- **SPY+TLT vol corr 0.777**：vol spike 期分散化弱
- **K1217 rebalance_freq_hybrid_vt**：rebalance 頻率對 VT 的影響（tax-free）
- **4-asset RP failure**：rebalance friction 已被識別為 risk-parity 退化來源（cost-free assumption）

本實驗在這條 thread 上補上稅務這層 friction 的量化證據。

## 方法

### 資產與期間
- 資產：SPY (US equity), TLT (long Treasury), GLD (gold), HYG (high-yield credit),
  SHY (short Treasury)
- 期間：2010-01-01 ~ 2025-12-31（16 calendar years，含 2020 COVID + 2022 雙空頭）
- 資料源：yfinance Adjusted Close
- 報酬：log return（避免 compounding error）

### 風控規格
- **VT**: target 10% annualized vol (~0.63% daily)；60d rolling vol estimate (lag 1 day)
- **Risk Parity (inverse-vol)**: weight ∝ 1/σ_i，60d rolling vol
- 兩 rule 對「同一組 raw return series」計算，所以差異來自 tax + rebalancing trigger，不來自 raw 回報差

### Tax 模型
- 短期 capital gains rate: 32%（federal 中位數 single filer, 200k+）
- 長期 capital gains rate: 20%（含 ACA NIIT，single filer 200k+ 中位數）
- Lot tracking: FIFO（IRS default）
- Tax 從 realized gain 直接扣 capital（不另外提繳）→ 模擬完全 reinvested taxable 帳戶

### 三規格
| Spec      | Rebalance trigger        | Tax applied?    |
|-----------|--------------------------|-----------------|
| NO_TAX    | 月底                     | No              |
| PERIODIC  | 月底                     | Yes (FIFO)      |
| TAX_AWARE | 月底 AND max abs drift > 5% band | Yes (FIFO) |

### Lookahead 防線
- All signals (vol estimate, drift check) computed at t-1 close
- Trading at t open (next session); positions weighted by t-1 lag
- 明確 `signal.shift(1)` 或 equivalent indexing
- np.random.seed(42) for any bootstrap

### 公平比較
- 三規格用同一份 raw daily return time series
- 同一份 vol estimate（60d rolling）
- 同一份 target weights
- 差異 strictly 來自 rebalancing trigger 與 tax friction

## 核心 metrics

每個（規則 × 規格）組合報：
1. **Target vol tracking error** = std(realized 60d rolling vol - 10%)；annualized
2. **After-tax Sharpe**（annualized; excess over SHY proxy）
3. **CAGR**（after-tax cumulative wealth）
4. **Max Drawdown**（after-tax wealth curve）
5. **Tax drag** = cumulative realized tax / initial capital
6. **Weight drift RMS** = sqrt(mean((w_realized - w_target)²))
7. **Tax events count**（月底有實際賣出的次數）
8. **DM test** on daily after-tax PnL: NO_TAX vs PERIODIC, NO_TAX vs TAX_AWARE, PERIODIC vs TAX_AWARE
9. **Sub-period breakdown**: 2010-2019 牛市 vs 2020-2025 動盪期

## 統計檢定

- Diebold-Mariano test on daily after-tax PnL（Harvey 2016 small-sample correction）
- Stationary bootstrap (Politis-Romano 1994) on annualized Sharpe difference, B=1000, mean block length=20

## 防錯規則

- 一律 `signal.shift(1)`，target weights at t = f(σ at t-1)
- np.random.seed(42) for all bootstrap
- 不用 same-day vol → same-day trade（lookahead 主風險）
- Tax 不從 NO_TAX 的 cumulative 反推；每 spec 獨立帳本
- 不混 r² vs RV vs daily return scaling（log return throughout）
- 月底再平衡用實際交易日（不用 calendar 月底）

## 成功標準

1. 三規格 metrics 完整出（VT × 3 + RP × 3 = 6 cells）
2. DM test 給 NO_TAX vs PERIODIC vs TAX_AWARE 的顯著差異 |t|
3. Tax drag 分 2010-2019 vs 2020-2025 報告
4. Vol tracking error: 比較 NO_TAX vs PERIODIC（PERIODIC 因 tax-drained 本金少，
   如果 vol 估計 lag 60d → vol tracking 變差是預期 mechanical 效應）
5. Conclusion 一句話：稅務 friction 是否 mechanically 削弱 VT/RP

## 禁止

- 不寫 `storage/memory/knowledge.json`（主線程 Codex review 後寫）
- 不發 feed 文章
- 不假數字

---

## Codex Review (2026-06-17 22:21 台灣時間, hourly-22, codex-cli 0.139.0)

**Verdict: FAIL** — 2 CRITICAL + 3 MAJOR + 1 MINOR。原始實驗結果保留作為 direction-of-effect 觀察與後續 k1529_v2 baseline，但 CRITICAL 兩項可能 materially 改變 TAX_AWARE 結論，**不可以此結果作為 tax-law-correct conclusion 寫文章**。

### CRITICAL
1. `k1529.py:296-326` — tax 是逐 asset / 逐 rebalance event 即時扣款，未做年度 ST/LT 彙總、跨資產互抵、跨腿年度 netting、loss carry-forward。稅務 friction 結果不符實際稅法。
2. `k1529.py:262-285` — TAX_AWARE drift trigger 用今日 close 後的 `current_w` 判斷並在同一 close 執行；vol target 雖然用 `[t-60, t-1]`，但 trigger 本身沒有 lag → 偷看 t close drift。

### MAJOR
3. `k1529.py:133-137` — long-term 判定 `holding_days >= 365`，正確切點是 `> 365`。
4. `k1529.py:420-447, 590-600` — DM test 數值正確（Harvey small-sample correction 有做），但輸出 interpretation string 把 sign 寫反（`dm_test(rb, ra)` 測 mean(rb-ra)=0，positive t → b>a，輸出寫成 a>b）。
5. `k1529.py:609-611` — bootstrap seed 用 Python `hash(...)`，跨 process 因 hash randomization 改變，不符合 fixed-seed reproducibility。

### MINOR
6. `k1529.py:307-318` — `tax_short` / `tax_long` 計算後完全未使用；註解與實際 blended tax 邏輯不一致。

### Codex 認證通過部分
- `k1529.py:177-178` vol estimate 確實用 `[t-60, t-1]`
- 三規格 raw price/return 與 rule-level target vol estimate 共享，差異純粹來自 rebalance trigger + tax friction

### 跟進
- `storage/memory/knowledge.json` entry verdict=FAIL，包含 reviewer=Codex（K1259 gate compliant）
- `storage/next_tasks.json` 已排 `k1529_v2_codex_remediation` (P3) follow-up
- v2 修正後重跑 + 重 review → 若 PASS/CONDITIONAL_PASS 才能寫文章
