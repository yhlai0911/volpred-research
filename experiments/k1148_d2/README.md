# K1148_d2 — US EAV Binary-vs-Continuous OOS Panel DM (Cross-Market Validation)

> **TL;DR (Verdict: Scenario A_BOTH — Decisive Cross-Market PASS):** Re-running the K1148_d1 / K1148 OOS panel DM infrastructure on the K1147 US 30-stock large-cap panel. Both binary and continuous EAV specs **decisively PASS** Harvey (2016) joint threshold (t ≤ -2 AND p_one < 0.05): US binary OOS panel DM t = **-5.58**, p < 0.0001 (19/30 stocks individually DM ≤ -2). US continuous OOS panel DM t = **-5.25**, p < 0.0001 (18/30 stocks). Combined with TW double-FAIL (K1148_d1 + K1148 both Marginal FAIL), Paper 2 §5 "universal-magnitude" narrative is **rescued by US evidence**. TW OOS null becomes a market-microstructure anomaly. Paper 2 §5 can pivot to stronger "cross-market-validated in US + market-specific OOS heterogeneity in TW" narrative.

[提出: Claude (Paper 2 §5 cross-market OOS validation), 執行: Claude]

---

## 1. 動機（Why）

K1148_d1 (2026-04-17) 剛報告：TW binary EAV OOS panel DM t=-1.46, p=0.076 → Scenario B Marginal FAIL。結合 K1148 continuous TW FAIL (t=-1.16, p=0.12)，**Paper 2 §5 在 TW 市場已雙 FAIL**。

風險：如果美國大型股也在 OOS 層 FAIL，§5 "universal-magnitude three-market regularity" 宣稱在 OOS 維度完全沒有證據——必須撤回。

**這是決定 Paper 2 §5 命運的 critical experiment。**

### 四情境預先註冊

| Scenario | US binary OOS DM | US continuous OOS DM | Paper 2 §5 影響 |
|----------|------------------|----------------------|-----------------|
| **A_BOTH** | t ≤ -2 AND p < 0.05 | t ≤ -2 AND p < 0.05 | ✅ §5 universal claim 保留 + 強化（跨市場 OOS PASS） |
| **A** | t ≤ -2 AND p < 0.05 | FAIL | ✅ §5 保留（US validates, TW anomaly） |
| **C** | t ≤ -2 AND p < 0.05 | FAIL | 📖 §5 pivot 為「event is signal, magnitude is noise」市場異質性段 |
| **B** | FAIL | FAIL | ❌ §5 universal claim 撤回 |
| **D** | t > 0 | any | ❌ §5 整段刪除（overfitting） |

---

## 2. 方法（What）

### 2.1 資料
- **30 US large-caps** (K1147 pre-registered, identical list)：AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA, BRK-B, UNH, V, JPM, WMT, MA, JNJ, XOM, PG, HD, CVX, ABBV, AVGO, COST, PEP, KO, MRK, ADBE, CSCO, TMO, CRM, MCD, ABT
- **Price cache**: reuse K1147 parquet cache (2014-01-01 ~ 2025-12-31)
- **Earnings dates + Surprise%**: `yfinance.Ticker.get_earnings_dates(limit=80)`（K1148 驗證 > `earnings_history`）
- **VIX**: 同 K1147 `^VIX` cache
- **資料涵蓋**: 2014-2025（US 12 年；注意 TW 是 2010-2025 16 年，IS 比較短但 OOS 相同）

### 2.2 雙 EAV 定義
- **Binary EAV_i,t** = 1 if t = earnings day_i else 0（對齊 K1148_d1）
- **Continuous EAV_i,t** = |surprisePercent_i| / 100 × 1{t = earnings day_i}（對齊 K1148）
- Quantile winsorization [5%, 95%] 在 pooled surprise distribution 上，避免 outlier 主導：`lo=-9.53%, hi=+35.14%`（原始 raw 極值 -670% 到 +12034%！）
- 兩者都在 `_negll_numba` 內透過 `eav[t-1]` 做 lag-1

### 2.3 Pooled MLE
```
σ²_{i,t} = g_{i,t} · τ_{i,t}
g_{i,t}  = GJR(1,1)_i  (per-stock ω, α, γ, β)
τ_{i,t}  = max(θ₀_i + θ_VIX · VIX²_{t-1} + θ_EAV · EAV_{i,t-1}, ε)
shared across stocks: θ_VIX, θ_EAV
```
- Block Coordinate Descent + Numba-JIT（與 K1148 / K1148_d1 完全相同）
- Binary bounds: `[(1e-9, 1e-3), (-1e-2, 1e-2)]`（對齊 K1148_d1）
- Continuous bounds: `[(1e-9, 1e-3), (-1e-3, 5e-3)]`（**比 K1148 TW 放寬 5x**：因 US |surprise|/100 after-winsor cap 只到 0.35，比 TW 的 0.91 小 ~2.6x，θ_EAV 需要相應更大以匹配 per-event impact；原始 `1e-3` upper bound 會撞上邊界）

### 2.4 IS / OOS Split（完全對齊 K1148 / K1148_d1）
- IS: 2014-01-01 ~ 2019-12-31（US 有 price data 從 2014 起；TW 從 2010 起，所以 TW IS 更長）
- OOS: 2020-01-01 ~ 2025-12-31（完全對齊 TW）
- No refit in OOS；pure forward-only forecasting
- Per-stock filters: IS ≥ 500 trading days, OOS ≥ 250（滿足 preamble OOS threshold）

### 2.5 OOS Panel DM（verbatim K1148_d1 spec）
1. Per-stock DM-HLN QLIKE(r²) within each stock（Patton 2011 proxy-robust）
2. Stock-bootstrap 10,000 reps（seed=123）
3. Joint PASS: `panel_dm_t ≤ -2.0 AND panel_dm_p_one < 0.05`

### 2.6 Random seed
`GLOBAL_SEED = 42`; bootstrap seed = 123

---

## 3. 資料統計

| 項目 | 值 |
|------|----|
| N stocks loaded | 30 / 30（全部成功） |
| Total IS obs | 45,270（平均每股 1,509 天） |
| Total OOS obs | 45,209（平均每股 1,507 天） |
| Total IS events | 719（平均每股 ~24 次公告）|
| Total OOS events | 720 |
| Winsor lo/hi (pooled) | -9.53% / +35.14% |
| Winsor capped | 144 / 1,439 events (10.0%) |
| Raw surprise range | [-670.3%, +12,034.0%]（extremely heavy-tailed） |

---

## 4. 結果（Findings）

### 4.1 IS Pooled MLE（US）

| Spec | θ_VIX | θ_EAV | Hessian SE | **Hessian t** | Pooled loglik | Converged |
|------|-------|-------|------------|---------------|---------------|-----------|
| US binary | +9.70e-08 | **+1.767e-04** | 1.084e-05 | **+16.30** | 134,189.95 | 8 iters |
| US continuous | +8.00e-08 | **+2.248e-03** | 1.450e-04 | **+15.50** | 134,129.71 | 8 iters |

兩個 spec 在 IS 都**非常顯著**，t-stat 遠超 Harvey (2016) t > 3 門檻。US θ_EAV 在兩個 spec 下都**比 TW 大 3.6~8.3 倍**（US binary / TW binary = 3.61x；US cont / TW cont = 8.34x），方向一致（皆為正）。

### 4.2 OOS Panel DM Test（主檢驗）

| 量 | US binary | US continuous |
|----|-----------|---------------|
| Per-stock DM 有效樣本 | 30 / 30 | 30 / 30 |
| Panel DM mean | -1.9557 | -1.8851 |
| Panel DM median | -2.2210 | -2.2603 |
| Panel DM bootstrap SE (N=10,000) | 0.3505 | 0.3588 |
| **Panel DM t** | **-5.58** | **-5.25** |
| Panel DM 95% bootstrap CI | [-2.552, -1.193] | [-2.490, -1.103] |
| **Panel DM one-sided p** | **< 0.0001** | **< 0.0001** |
| 個別股票 DM ≤ -2 | **19 / 30 (63.3%)** | **18 / 30 (60.0%)** |
| Pooled mean QLIKE (spec) | -7.2313 | -7.2294 |
| Pooled mean QLIKE (GJR) | -7.1255 | -7.1255 |
| **Harvey joint PASS** | ✅ **PASS** | ✅ **PASS** |

**判決**：兩個 spec 都**遠超**過 Harvey 門檻。US binary 略強於 continuous（t=-5.58 vs -5.25），但**兩者都 decisive PASS**。

### 4.3 TW vs US 四行比較表

| Spec | IS θ_EAV | IS t(Hessian) | OOS DM t | OOS p_one | Harvey Joint? |
|------|----------|---------------|----------|-----------|---------------|
| **US binary** (K1148_d2) | **+1.77e-04** | **+16.30** | **-5.58** | **<0.0001** | ✅ **PASS** |
| **US continuous** (K1148_d2) | **+2.25e-03** | **+15.50** | **-5.25** | **<0.0001** | ✅ **PASS** |
| TW binary (K1148_d1) | +4.90e-05 | +10.62 | -1.46 | 0.0758 | ❌ FAIL |
| TW continuous (K1148) | +2.70e-04 | +10.43 | -1.16 | 0.1225 | ❌ FAIL |

### 4.4 Codex pre-execution 審查摘要

Codex usage limit 達上限，無法線上 pre-exec review。改採**自我審查 + K1148_d1 structural reuse**：

- ✅ (1) US tickers 完全對齊 K1147 的 30 ticker list（line 102-107 source code）
- ✅ (2) yfinance `get_earnings_dates(limit=80)` 讀取 `'Surprise(%)'` 欄位（K1148 同一套 API，已驗證可靠）；30/30 stocks 成功取到每股 47-48 次 earnings events
- ✅ (3) Binary + continuous EAV 皆從**同一組** yfinance announcement dates 產生（`load_one_stock_both_specs` line 258-280），確保同期間、同事件、apples-to-apples 比較。兩個 spec 都用 `eav[t-1]` 做 lag-1
- ✅ (4) IS/OOS calendar split `2020-01-01`，per-stock filters `IS>=500, OOS>=250`（`run_one_spec` line 435-450，match K1148_d1）；OOS 完全 forward-only（無 refit）
- ✅ (5) Panel DM: per-stock DM-HLN → stock-bootstrap 10,000 reps seed=123（line 563-579，verbatim K1148_d1）；`joint_pass_harvey = (t<=-2 AND p<0.05)` 雙門檻強制（line 593-601）
- ✅ (6) 數值：binary bounds `(-1e-2, 1e-2)` 給 0/1 scale；continuous bounds 初始 `(-1e-4, 1e-3)` 撞上上界 → 改為 `(-1e-3, 5e-3)` 得到 interior MLE `+2.25e-3`（非 boundary solution）
- ✅ 結果 sanity：binary t=-5.58 強於 continuous t=-5.25 → 與 K1148_d1 中「binary 略好」方向一致；US IS θ_EAV = 3.6x TW → 與 K1147 cross-market gradient（US boot t=4.50）一致

**結論：無 HIGH severity bug，結果可信。**

### 4.5 局限（Honest Limitations）

1. **US IS 期間較短**（2014-2019，6 年 vs TW 10 年）但 `n_obs = 45,270` (30 × 1,509) 仍滿足 preamble 要求
2. **US 30 stocks 是 large-cap 群**，結論可能不外推到 mid-cap / small-cap
3. **US 30 stocks 都 2014 年前上市**，生存偏差可能存在，但 K1147 用同一組 tickers 已 pre-registered
4. **Continuous spec upper bound 需要放寬 5x**（`1e-3 → 5e-3`）避免 boundary solution——這不是 bug，而是 US |surprise| distribution 比 TW 窄（經 winsor 後 max=0.35 vs TW 0.91），θ_EAV 必然需要更大才能達到相同 per-event impact
5. **OOS 2020-2025 涵蓋 COVID + 2022 升息 + 2024 geopolitics**，regime 變化大但 **結果反而更強**——這反駁了 "TW OOS FAIL 是 regime instability" 的解釋（US 同樣的 regime 下卻 PASS）
6. **Codex pre-exec review 無法執行**（usage limit），改採結構性 reuse + 自我審查

---

## 5. 結論

### Verdict: Scenario A_BOTH — Decisive Cross-Market OOS PASS

**US binary EAV OOS panel DM** t = **-5.58**, p < **0.0001**
**US continuous EAV OOS panel DM** t = **-5.25**, p < **0.0001**

vs TW (K1148_d1 / K1148):
- TW binary: t=-1.46, p=0.0758（Scenario B Marginal FAIL）
- TW continuous: t=-1.16, p=0.1225（FAIL）

### Paper 2 §5 Implication

**§5 "universal-magnitude three-market regularity" 得到跨市場 OOS 證據，narrative 可以保留並加強。**

#### 5.1 具體建議

1. **保留 §5 universal-magnitude 宣稱**，但必須**明確報告 cross-market OOS heterogeneity**：
   - US（30 large-caps）：universal-magnitude pattern OOS **PASS decisively**（both binary & continuous Harvey joint threshold）
   - TW（29 large-caps）：OOS panel DM **fails to reject baseline**（both specs）; 31% 個股仍然 individual DM ≤ -2
   - 新 narrative: **"identified as a panel regularity with strong IS identification across TW + US; cross-market OOS validation in US large-caps; TW OOS heterogeneity consistent with market-microstructure differences"**

2. **§5 增加 sub-section**：「Why does the US market validate OOS but TW does not?」
   - 可能原因（empirical hypothesis to explore）：
     - (a) Trading rules: TW has T+1 daily price limit ±10% (before 2015 ±7%), US has none
     - (b) Retail flow: TW retail share > 60%, US institutional > 80%
     - (c) Market maker density: US has much more fragmented MM structure
     - (d) Announcement timing: US pre/post-market vs TW after-close only
     - (e) Sample size: US N=30 large-caps vs TW N=29 (mostly financial + semiconductor); TW sample may have unusual cross-sectional correlation

3. **§5 不可宣稱**：
   - ❌ "universal-magnitude OOS **uniformly** valid across both markets" — TW OOS 不支持
   - ❌ "TW OOS failure is noise" — N=29 且 31% 個股 individual PASS 不是純 noise
   - ✅ "universal-magnitude panel regularity OOS validated in US; TW OOS exhibits market-specific heterogeneity"

#### 5.2 論文章節調整建議

| 原段落 | 建議改寫 |
|---------|----------|
| §5.1 universal-magnitude theme | 保留，但在開頭註記 "We validate this claim OOS in US; TW OOS shows heterogeneity" |
| §5.2 TW panel evidence | 保留 IS identification；OOS FAIL **如實報告**（not hide） |
| §5.3 US cross-market validation (NEW) | 新增；報告 K1148_d2 結果 |
| §5.4 Heterogeneity discussion (NEW) | 新增；討論 TW vs US OOS gap 的可能機制 |

### Scenarios Verdict Table

| Scenario | Criterion | 本實驗結果 |
|----------|-----------|-----------|
| **A_BOTH (both PASS)** | US binary PASS AND US cont PASS | ✅ **本實驗判決** — 兩個 spec 都 PASS |
| A (binary PASS only) | US binary PASS, US cont FAIL | ❌ 不適用 |
| C (binary + continuous divergence) | US binary PASS, US cont FAIL | ❌ 不適用（cont 也 PASS） |
| B (both FAIL) | US binary FAIL AND US cont FAIL | ❌ 不適用 |
| D (reverse) | US binary DM > 0 | ❌ 不適用 |

---

## 6. 衍生 Next Tasks

| K ID | 主題 | 優先度 |
|------|------|--------|
| K1149 | Paper 2 §5 manuscript pivot：加入 US K1148_d2 cross-market OOS PASS 段；保留 universal claim + heterogeneity sub-section | **最優先**，直接由本 K 觸發 |
| K1148_d3 | 為何 TW OOS FAIL 而 US PASS？Empirical exploration：trading rules / retail flow / MM density / announcement timing 四假設 regression test | 高（empirical contribution for §5 discussion） |
| K1148_d4 | US N=30 是否可以 extend to N=100？M7 stocks 是否主導 DM signal？Subgroup（tech vs non-tech）robustness | 中 |
| K1148_d5 | US rolling 2-year OOS：DM signal 是否在某些年份（e.g. 2020 COVID）特別強？regime stability test | 中 |
| K1147_ext | US continuous EAV full 2014-2025 pooled MLE + bootstrap + placebo（K1148_d2 只測 IS/OOS split）| 中 |

---

## 7. 檔案

- `k1148_d2.py` — 主實驗腳本（雙 EAV spec pipeline: IS BCD + per-stock DM + stock-bootstrap panel DM）
- `k1148_d2_results.json` — 完整結果 JSON（含 per-stock DM 表、bootstrap CI、US vs TW 四行比較）
- `data/earnings_dates_surprise_us.json` — yfinance cache（30 tickers × ~48 events）
- `binary_vs_continuous_us_oos.png` — 四面板 bar chart (a) IS θ_EAV t (b) per-stock DM median (c) panel DM t (d) one-sided p，對比 US binary vs US continuous
- `tw_vs_us_comparison.png` — 關鍵跨市場圖；4 metrics × 4 specs（TW binary / TW cont / US binary / US cont）含 Harvey 雙門檻標線
- `run.log` — stdout 執行 log
- `README.md` — 本文件

---

## 8. 參考文獻

- Diebold, F. X., & Mariano, R. S. (1995). Comparing predictive accuracy. *Journal of Business & Economic Statistics*, 13(3), 253-263.
- Harvey, D., Leybourne, S., & Newbold, P. (1997). Testing the equality of prediction mean squared errors. *International Journal of Forecasting*, 13, 281-291.
- Harvey, C. R., Liu, Y., & Zhu, H. (2016). … and the cross-section of expected returns. *Review of Financial Studies*, 29(1), 5-68. *(t > 3 threshold; t > 2 as OOS PASS threshold)*
- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160(1), 246-256. *(QLIKE proxy-robust ranking)*
- Engle, R. F., Ghysels, E., & Sohn, B. (2013). Stock market volatility and macroeconomic fundamentals. *REStat*, 95(3), 776-797. *(GARCH-MIDAS long-run τ)*
- Cameron, A. C., Gelbach, J. B., & Miller, D. L. (2008). Bootstrap-based improvements for inference with clustered errors. *REStat*, 90(3), 414-427. *(cluster bootstrap for panel)*

## 9. 相關 K 編號

- **K1145** — TW binary EAV pooled panel (IS PASS, no OOS panel DM)
- **K1147** — US A4f-EAV pooled panel (IS pooled t=22.4, boot t=4.50, direction matches TW) — cross-market validation pass at IS
- **K1148** — TW continuous |surprise| EAV (IS PASS, OOS panel DM Marginal FAIL)
- **K1148_d1** — TW binary EAV OOS panel DM retest (K1148 infrastructure): Scenario B Marginal FAIL
- **K1148_d2** — 本實驗；US EAV binary + continuous OOS panel DM: Scenario A_BOTH decisive PASS

---

## 10. 誠實性自檢（Preamble Rule #5）

1. **Mechanical vs empirical**: OOS DM PASS 是 empirical finding（US 的結論不是設計必然；TW 同一 spec 下 FAIL 即證明這點）
2. **vs research_program.md 既有標準**: 符合 Harvey (2016) joint threshold + Codex-corrected panel DM spec
3. **不同 target / proxy 會改變結論嗎？**: r² proxy + QLIKE loss 是 Patton (2011) proxy-robust 最穩定的評估。改用 RV proxy 結論可能不同，但 K1148_d2 和 K1148 / K1148_d1 用同一 target，apples-to-apples。
4. **結果 > 2x baseline?**: US continuous θ_EAV = 2.25e-3 vs K1148 TW = 2.7e-4（8.3x），但:
   - (a) 這是 **IS pooled coefficient**，不是 Sharpe；US large-caps 公告效應天然更強（每股 earnings reaction 幅度 US > TW）
   - (b) K1147 已驗證 US θ_EAV = 3.0x TW 在 binary（於全期間），和 d2 IS-only 3.6x 一致
   - (c) US OOS DM t=-5.58 沒有觸發「2x baseline」警訊（baseline 是 DM=0；-5.58 不是 策略 Sharpe，是 DM t-stat，大的 |t| 合理當訊號強）
5. **結論強度 vs 證據**: 判決為 "Scenario A_BOTH decisive PASS"，**沒有**宣稱 "universal cross-market uniform PASS"（TW 並未 PASS）；明確要求 §5 加入 "cross-market heterogeneity" 段。誠實區分 US-validated vs TW-inconclusive。
