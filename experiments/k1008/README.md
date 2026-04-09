# K1008: Regime-Weighted Conformal VaR (RWC) vs Standard Conformal

## 動機
K1005 發現 Standard Conformal VaR 對 GJR 是巨大改善（0/3 → 3/3 Trinity PASS），但對 A4f 無增量（已 3/3）。本實驗測試 **Regime-Weighted Conformal (RWC)** — 使用 VIX 作為 regime variable，以 Gaussian kernel 加權校準集殘差 — 是否能進一步改善。

## 方法
- **數據**: SPY 2004-2026 (yfinance), OOS 2019-2026, N=5600, window=2000, refit/63d
- **基礎模型**: GJR_t, A4f_t (joint MLE)
- **VaR/ES 方法**:
  1. Parametric (Student-t quantile)
  2. Standard Conformal (equal-weight calibration residuals, W=500)
  3. RWC (Gaussian kernel on VIX, h=3,5,8, W=500)
- **評估**: VaR UC/CC/DQ at 1%, 2.5%, 5%; ES Acerbi-Szekely at 2.5%
- **Regime 分析**: High VIX (>=25) vs Low VIX (<25)

### RWC 核心公式
```
w_i = exp(-0.5 * ((VIX_t - VIX_i) / h)^2)  # Gaussian kernel
weighted quantile of z_cal at alpha level
```

## 結果

### Trinity PASS 統計 (3 alpha levels)

| Model | PASS/Total |
|-------|-----------|
| GJR_t Parametric | **0/3** |
| GJR_t StdConformal | **3/3** |
| GJR_t RWC(h=3) | **3/3** |
| GJR_t RWC(h=5) | **3/3** |
| GJR_t RWC(h=8) | **3/3** |
| A4f_t Parametric | **3/3** |
| A4f_t StdConformal | **3/3** |
| A4f_t RWC(h=3) | **2/3** (1% fail) |
| A4f_t RWC(h=5) | **3/3** |
| A4f_t RWC(h=8) | **3/3** |

### QLIKE (volatility forecasting quality)
- GJR_t: -8.2556
- A4f_t: -8.3594 (better)

### Regime Analysis (2.5% VaR, High VIX >= 25)

| Model | High VIX Viol% | Low VIX Viol% | Target |
|-------|---------------|---------------|--------|
| GJR_t Parametric | **9.17%** (3.7x) | 2.37% | 2.5% |
| GJR_t StdConformal | **6.03%** (2.4x) | 1.73% | 2.5% |
| GJR_t RWC(h=5) | **4.02%** (1.6x) | 2.14% | 2.5% |
| A4f_t Parametric | **5.44%** (2.2x) | 2.03% | 2.5% |
| A4f_t StdConformal | **5.46%** (2.2x) | 2.07% | 2.5% |
| A4f_t RWC(h=5) | **4.02%** (1.6x) | 2.49% | 2.5% |

## 核心發現

1. **GJR_t: Conformal 方法是巨大改善** — Parametric 在所有 alpha 都 FAIL（過多違約），Standard Conformal 和 RWC 都修正為 3/3 PASS。確認 K1005 結論。

2. **RWC 在 High VIX regime 有顯著優勢** — 這是本實驗最重要的發現：
   - GJR_t: Parametric 9.17% → StdConformal 6.03% → **RWC 4.02%**（接近 2.5x → 1.6x target）
   - A4f_t: Parametric 5.44% → StdConformal 5.46%（無改善！）→ **RWC 4.02%**
   - RWC 對 A4f_t 在 high-VIX regime 的改善比 standard conformal 更大

3. **A4f_t + RWC(h=3) 有過度校正問題** — bandwidth 太窄導致 1% VaR 違約率偏高（1.56%, UC_p=0.028），因為極端 VIX 時 kernel 過窄，有效校準樣本太少。h=5 或 h=8 是更穩健的選擇。

4. **最佳組合: A4f_t + RWC(h=5)** — 3/3 Trinity PASS + High VIX 違約率降到 4.02% + Low VIX 精確 2.49%。

5. **ES 表現**: 所有方法 ES p-value 在 0.49-0.52 區間，都能通過 Acerbi-Szekely 測試。RWC 沒有犧牲 ES coverage。

## 局限性
- 單一資產（SPY）、單一 regime variable（VIX level）
- Bandwidth 選擇是固定的（3, 5, 8），未做 cross-validation
- RWC 依賴 VIX 數據可用性，不適用於沒有隱含波動率指標的市場
- Calibration window 固定 500 天，未測試 sensitivity

## 參考文獻
- arXiv:2602.03903 (2026): Regime-Weighted Conformal Prediction
- Vovk et al. (2005): Conformal prediction framework
- Gibbs & Candes (2021): Adaptive conformal inference
- Patton (2011): QLIKE
- Kupiec (1995), Christoffersen (1998), Acerbi & Szekely (2014)

## 檔案
- `k1008.py` — 實驗腳本
- `k1008_results.json` — 完整結果
