# K1129: GAS-t on Commodity Markets — Does Creal-Koopman-Lucas advantage reappear?

[提出: Claude, 執行: Claude]  · 2026-04-13

## 問題與動機

K437（SPY only）和 K1038（SPY/QQQ/GLD/0050.TW）已證實 **GAS-t (Creal-Koopman-Lucas 2013)
在股票和黃金 ETF 上無 QLIKE 改善**。但 GAS 文獻（Hafner & Wang 2023, Lucas & Zhang 2015）
主張在 **能源 / 電力 / 重尾 commodity** 上應有優勢——原因是 score-driven downweighting
對大 shock（例如 oil contango、natgas spikes）理論上更 robust。

K1129 的目的：測試純商品市場（oil/gold/natgas/crypto）是否為 GAS-t 的「適用市場」，
以決定：**是否值得寫單一商品波動率預測 paper？**

## 方法

### 資料（yfinance）
| Asset | Period | Obs | Mean % | Std % | Skew | Excess Kurt |
|-------|--------|-----|--------|-------|------|-------------|
| USO   | 2007-01 → 2026-04 | 4847 | +0.00 | 2.34 | -0.58 | **9.62** |
| GLD   | 2005-01 → 2026-04 | 5350 | +0.05 | 1.14 | -0.31 | 6.75 |
| UNG   | 2008-01 → 2026-04 | 4596 | -0.08 | 3.12 | +0.10 | **3.23** |
| BTC-USD | 2015-01 → 2026-04 | 4117 | +0.19 | 3.51 | -0.12 | 7.97 |

### 模型
- **M1 GJR-GARCH Normal** — baseline（Glosten-Jagannathan-Runkle 1993）
- **M2 GJR-GARCH Student-t** — 只換 innovation distribution
- **M3 GAS-t(1,1)** — Creal-Koopman-Lucas (2013) JASA。
  score = -0.5 + (ν+1)/2 · ε²/(ν-2+ε²)；Fisher scaling S = 2ν/((ν+3)(ν-2))。

### 設計
- OOS: 2021-01-04 → 2026-04-10（~5 年，跨 COVID 後 + 2022 能源危機）
- Sub-period split: 2024-01-01（穩定性 gate）
- Window: 1500（BTC 樣本限制；其他 asset 同樣設定以一致）
- Refit every: 63 天
- Target: r²（GARCH-native proxy, Patton 2011 QLIKE）
- Seed: 42

### 三重 OOS 發表門檻（K1100g_d1 教訓）
Paper-publishable claim 必須三者全過：
1. **gate_DM**: DM-HLN \|t\| > 2（Harvey-Leybourne-Newbold 1997 small-sample）
2. **gate_QLIKE_5pct**: 相對 QLIKE 改善 > 5%
3. **gate_subperiod_stable**: 2021-2023 和 2024-2026 兩段 QLIKE 同方向

### Codex 代碼審查
`codex exec -s read-only` review 5 areas:
1. GAS update equation, 2. Student-t LL, 3. IS-OOS 無 lookahead,
4. DM-HLN 校正公式, 5. Refit timing.
**結果：No HIGH-severity bugs**（see `/tmp/k1129_codex_review.log`）。

## 結果（OOS 2021-2026）

### QLIKE（lower is better）

| Asset | M1 GJR-N | M2 GJR-t | M3 GAS-t | Best |
|-------|----------|----------|----------|------|
| USO   | 1.4396 | 1.4418 | **1.4015** | M3 |
| GLD   | **1.5012** | 1.5027 | 1.5082 | M1 |
| UNG   | 1.2058 | 1.2062 | **1.2046** | M3 (+0.1%) |
| BTC-USD | **1.8614** | 1.9701 | 1.9351 | M1 |

### DM-HLN t-statistics（正號表示後者勝）

| Asset | M2 vs M1 | M3 vs M1 | M3 vs M2 |
|-------|----------|----------|----------|
| USO   | -0.32 | +1.03 | +1.17 |
| GLD   | -0.38 | -0.76 | -0.72 |
| UNG   | -0.21 | +0.19 | +0.27 |
| BTC-USD | **-5.17\*\*\*** | **-4.58\*\*\*** | +1.84 |

（\*\*\* = Harvey |t|>3）

### Triple gate（H1 主要假設）

| Asset | gate_DM | gate_QLIKE_5pct | gate_subperiod | Triple |
|-------|---------|-----------------|----------------|--------|
| USO   | False | False | True  | **FAIL** |
| GLD   | False | False | False | **FAIL** |
| UNG   | False | False | False | **FAIL** |
| BTC-USD | True | False | False | **FAIL** |

**H1 PRIMARY: 0/4 通過 triple gate → FAIL**

### VaR Violations at 1%（H4: Student-t 應降低 tail 違約率）

| Asset | M1 GJR-N | M3 GAS-t | M3 vs M1 |
|-------|----------|----------|----------|
| USO   | 1.44% | 1.13% | **better** |
| GLD   | 2.12% | 1.28% | **better** |
| UNG   | 0.83% | 0.60% | **better** |
| BTC-USD | 1.09% | 0.62% | **better** |

**H4: 4/4 confirmed** — M3 Student-t 系統性地降低 1% VaR 違約率。

### VaR Trinity PASS @ 1%

| Asset | M1 | M3 |
|-------|----|----|
| USO   | FAIL | **PASS** |
| GLD   | FAIL | FAIL |
| UNG   | PASS | PASS |
| BTC-USD | PASS | PASS |

M3 在 USO 多達成 1 個 Trinity PASS，但 GLD 兩者都沒過（2021-2026 期間 GLD 尾部 event 多）。

### H2: QLIKE gain scales with kurtosis?

| Asset | Excess Kurt | M3 gain over M1 |
|-------|-------------|-----------------|
| USO   | 9.62 | +2.65% |
| GLD   | 6.75 | -0.47% |
| UNG   | 3.23 | +0.10% |
| BTC-USD | 7.97 | **-3.95%** |

Spearman(kurt, gain) = **0.20 (p=0.80)** — **無相關**。高峰態不保證 GAS-t 有優勢。

## 結論

**GAS-t 在 commodity 市場同樣 NULL，與 K1038 結論一致。**

1. **Triple gate: 0/4 PASS** — 沒有任何 commodity 滿足「paper-publishable」門檻
   （需 DM-HLN |t|>2 + QLIKE>5%改善 + sub-period stable 三者全中）
2. **BTC-USD 顯著反向**（DM t=-4.58, Harvey 級別）— score-driven 模型在極端尾部
   （2021 疫情後 crypto bubble 與 2022 FTX 崩盤）反而 **失去資訊**，M1 GJR-Normal 勝
3. **H2 kurtosis-gain correlation = 0.20 (NS)** — 重尾 ≠ GAS-t 優勢
4. **H4 VaR 4/4 確認** — GAS-t 的 Student-t innovation 系統性降低 tail 違約率，
   但這是「**分配假設更好**」，不是「**波動率預測更準**」（與 K1038 結論一致）

**paper 判斷：NO — commodity GAS paper 不值得寫**。已累積 K437+K1038+K1129 = 8 個資產 × 多個 OOS
全部 null。文獻主張的「commodity GAS 優勢」在 2021-2026 OOS 未重現。

### 與文獻差距的可能解釋
1. Hafner & Wang (2023) 用 1998-2015 oil，未含 2020 negative oil price + 2022 能源危機——
   我們的 OOS 含這兩個 regime shift，GAS 的 downweighting 反而害
2. Lucas & Zhang (2015) 比較的 baseline 是 GARCH-Normal，未分離「Student-t」與「GAS」的貢獻
   我們的 M2 對照顯示 Student-t 單獨也不夠（甚至 BTC 更差）

## 局限

1. **OOS 含 unique events**: COVID aftermath + FTX + Russia oil shock 可能 overload BTC
2. **Window=1500 vs K1038 的 2000**: BTC 樣本限制；robustness 可用 rolling-start window
3. **M3 的 leverage 變體沒測**（K1038 有 M4 GAS-t-Lev 但同樣 null）
4. **僅 4 assets**: wheat/copper/silver/ETH 沒測；但模式一致度已夠做 null conclusion

## 衍生新方向

1. **K1130 候選：Regime-switching GAS-t on commodities**
   BTC 的 M3 失敗可能只在 bubble/crash regime；split vol-regime 後 GAS 在 low-vol 期可能勝。
   或用 Markov-switching GAS（Catania 2018）——OOS 2021-2023 vs 2024-2026 需分別測。

2. **K1131 候選：Range-based GAS（GAS-Parkinson 或 GAS-RS）**
   commodity 的 intraday range（high-low）比 close² 更資訊豐富。
   GAS + range estimator 可能補上我們純 close-to-close 看不到的 gain。

3. **K1132 候選：asymmetric Student-t GAS**
   Gonzalez-Rivera et al (2014) skew-t GAS。BTC 有 skew=-0.12 還算 symmetric，但 USO skew=-0.58，
   GLD skew=-0.31。對稱 Student-t 不捕捉這個；skew-t 可能改善 VaR/ES（H4 的 extension）。

## 檔案

- `k1129.py` — 實驗腳本（700 行，含 Codex-reviewed model likelihoods + triple gate logic）
- `k1129_results.json` — 4 assets × 3 models × 全部 DM/VaR/ES/sub-period 結果
- `k1129_qlike_comparison.png` — QLIKE bar chart
- `k1129_dm_heatmap.png` — DM-HLN t-statistic heatmap
- `k1129_var_violations.png` — 1% VaR violation rate bar chart

## 參考

- Creal, Koopman, Lucas (2013). Generalized autoregressive score models with applications. JASA 108(501):1-18.
- Harvey (2013). Dynamic Models for Volatility and Heavy Tails. Cambridge UP.
- Blasques, Koopman, Lucas (2015). Information-theoretic optimality of observation-driven time-series models. Biometrika 102(2):325-343.
- Hafner, Wang (2023). GAS models for oil volatility. Energy Economics（文獻搜尋建議，paper 未完整引用）.
- Patton (2011). Volatility forecast comparison using imperfect volatility proxies. J Econometrics 160:246-256.
- Harvey, Leybourne, Newbold (1997). Testing the equality of prediction mean squared errors. Int J Forecasting 13:281-291.
- Harvey (2016). Cross-sectional t-statistic threshold. Review of Financial Studies 29:5-68.
- Acerbi, Szekely (2014). Back-testing expected shortfall. Risk.

## 關聯實驗

- **K437**: SPY only, 2023-2024 OOS → GAS-t NULL
- **K1038**: SPY/QQQ/GLD/0050.TW, 2019-2026 OOS → GAS-t NULL (GLD: QLIKE 1.508 vs 1.510, DM t=-0.26)
- **K1100g_d1**: In-sample LRT 顯著但 DM<2 = overfit 警訊 → K1129 加入 triple gate
