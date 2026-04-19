# K1255 — Intraday Seasonality / MC-GARCH Pilot (Scoping Only)

[提出: Claude 自主研究 / 執行: Claude 主線程 scoping / 2026-04-18]

**Status**: Phase 0 **Scoping only**.
**不**跑 estimation、**不** commit、**不**動 `knowledge.json` / `research_program.md` / `feed.json`。
完成標準：問題定位 + literature 3 篇齊備 + differentiation 對照 PRG / K1100h 講清楚 + Phase 1 entrypoint 明確 + go/no-go 結論。

**Topic-diversity 動機**：`docs/topic_diversity_audit.md` 列 "intraday seasonality / session-boundary" 為 novelty quota top 3（feed_ct=0, kb_ct=0）。同時對齊用戶 PRS (Lai & Sheu 2024 APFM) + Paper 6 PRG 研究主軸的延伸。

---

## 1. Problem — Daily-aggregate volatility 模型遺漏的 intraday periodic structure

K1100g 系列（d1–d8）daily-scale TAIFEX gap²→intraday r² 預測 DM 卡在 Harvey |t|>3 之下；K1100h 已開 Phase 0 scoping 試圖用 tick → 5/15-min grid + intraday periodic dummies 突破。**K1100h 的本質還是 PRG 框架的 grid-level 延伸**：單一 GARCH recursion + periodic dummies + h_{n-1} cross-session bridge。

文獻有另一條主流路徑被本專案幾乎沒覆蓋：**Engle & Sokalska (2012) Multiplicative Component GARCH (MC-GARCH)**，把 intraday return variance 顯式分解為三個 multiplicative component：

```
σ²_{t,k}  =  q_t  ·  s_k  ·  g_{t,k}
              ↑       ↑        ↑
            daily   diurnal   stochastic
            (HAR-   (Flexible (GARCH(1,1)
             RV/    Fourier    on residual
             RGARCH) Form)     after q·s
                              de-seasonalization)
```

- **q_t**：daily latent vol（外部喂 HAR-RV / Realized GARCH forecast）
- **s_k**：deterministic intraday seasonal pattern（Andersen-Bollerslev 1997 Flexible Fourier Form, FFF）— bin-of-day index k = 1..K
- **g_{t,k}**：standard GARCH(1,1) on de-seasonalized standardized returns

**研究問題**：在 SPY 1-min（or 5-min）和 0050.TW 5-min 上，MC-GARCH (q·s·g) 是否在 OOS QLIKE 顯著勝過：
1. naive intraday GARCH（不分 q·s·g）
2. K1100h-style PRG with periodic dummies（dummies 是 additive in h，不是 multiplicative）
3. HAR-RV daily forecast 撒平到 intraday bin 的 baseline

---

## 2. Differentiation vs PRG (Paper 6 / K880-886) and K1100h

**核心：MC-GARCH 跟 PRG 的 component structure 根本不同。**

| 維度 | PRG (Paper 6) | K1100h (TAIFEX tick PRG) | **K1255 MC-GARCH (proposed)** |
|------|---------------|--------------------------|-------------------------------|
| Session 數 | 2 (overnight + intraday) | 76 (15-min) / 228 (5-min) bars | 同 K1100h grid，但**結構分解不同** |
| Vol decomposition | 單一 σ² with session-periodic α/β/γ | 單一 h with periodic additive dummies | **三因子 multiplicative**: q (daily) × s (FFF diurnal) × g (stochastic GARCH) |
| Diurnal pattern 表達 | 無顯式 diurnal — session 平均 | Periodic dummies (additive in h) | **FFF (Flexible Fourier Form)**: 連續 sin/cos basis 平滑近似 U-shape |
| Daily-intraday linkage | h_{n-1} 跨 session bridge | 同 PRG，加 intraday 細顆粒 | **Externally-fed q_t**（來自 HAR-RV 或 RGARCH），non-recursive |
| Fit philosophy | One-step joint MLE | One-step joint MLE | **Two-step**: 先 estimate q & s（separable）, 再 fit g on de-seasonalized residual |
| Resolution | Daily | tick → 5/15-min grid | **1-min (SPY) / 5-min (0050.TW)** |
| Markets | TAIFEX, SPY, QQQ, GLD, EEM, 0050.TW | TAIFEX TX tick only | **SPY + 0050.TW**（避免直接撞 K1100h TAIFEX scope） |
| Estimation cost | 中（6-8 參數）| 高（K periodic dummies × refit）| **低**（FFF 只 5-10 sin/cos pair；g GARCH(1,1) 只 3 參數）|

**為什麼這是真差異化，不是 PRG 換皮**：
1. **Multiplicative vs additive**：MC-GARCH 假設 vol 三因子可分離（separable scales），PRG/K1100h 是單一 recursion 加 periodic shifters。前者更接近 Engle-Sokalska / Andersen-Bollerslev 主流 high-freq vol 文獻；後者是 PRS/APFM 系延伸。
2. **Two-step vs joint**：MC-GARCH 的 daily q_t 是外部 plug-in（HAR-RV / Realized GARCH），可以重用 Paper 6 已驗證的 daily backbone — **K1255 並非取代 PRG，而是測試「PRG-as-q + MC-GARCH wrapping」是否優於純 PRG**。
3. **FFF vs dummies**：dummies 是 step function（K-1 個離散 jump），FFF 是平滑 trigonometric basis（5-10 個 sin/cos pair 通常夠；參數少且導數連續）。**比較 dummies vs FFF 本身就是獨立 methodological contribution**。
4. **資料不撞**：K1100h 鎖 TAIFEX TX tick；K1255 用 SPY 1-min（yfinance 60 天 cap → 用 polygon-style cached 5-min 替代）+ 0050.TW 5-min。**TAIFEX 留給 K1100h，不重複算力**。

**Go/no-go criterion (vs K1100h)**：若 K1100h Phase 1 結果顯示 "PRG with periodic dummies on TAIFEX tick" 已 Harvey PASS 且差異 plot 顯示 dummy φ_s 已捕捉 U-shape → K1255 仍有獨立價值（multiplicative ≠ additive；SPY + 0050.TW vs TAIFEX；FFF vs dummies — 任何一條都是 publishable comparison）。**故 go**。

---

## 3. Literature — 3 篇核心方法論論文

完整 references / DOI / arXiv ID 見 `references.md`。三條方法線：

### 3.1 Andersen & Bollerslev (1997, J. Empirical Finance) — Flexible Fourier Form
- **Intraday periodicity, long memory volatility, and macroeconomic announcement effects in the US Treasury bond market** (joint work with Cai & Zhang, but FFF 概念來自 1997 JEF paper)
- 提出 **Flexible Fourier Form (FFF)** 作為 deterministic intraday seasonal filter
- FFF：`s(k/K) = c_0 + Σ_{j=1}^{P} (c_j cos(2πjk/K) + d_j sin(2πjk/K))`，P=4-6 通常足夠
- K1255 採用：對 SPY 1-min 和 0050.TW 5-min 的 |r_{t,k}| 取 log，跑 OLS regression on FFF basis → 得 ŝ_k → 用於 de-seasonalization

### 3.2 Engle & Sokalska (2012, J. Financial Econometrics) — MC-GARCH
- **Forecasting intraday volatility in the US equity market: Multiplicative component GARCH**
- 經典三因子分解：σ²_{t,k} = q_t · s_k · g_{t,k}
- 在 NYSE 1-min 數據上顯示 MC-GARCH OOS forecast 顯著勝過 naive intraday GARCH (Bollerslev 1986) 和 fixed-day GARCH
- K1255 直接 replicate 此 spec on SPY 5-min（1-min 太多噪音 + yfinance limit），加上 0050.TW 5-min cross-market test

### 3.3 Hansen, Huang & Shek (2012, J. Applied Econometrics) — Realized GARCH
- **Realized GARCH: a joint model for returns and realized measures of volatility**
- Daily-frequency RGARCH 提供 q_t 的 high-quality estimate（替代簡單 HAR-RV）
- 與 Paper 6 PRG 共用同一 realized measure 框架，K1255 q_t 可直接從 K880 / K886 cache 取
- 重要 robustness：q_t 改用 (a) HAR-RV (b) RGARCH (c) PRG daily backbone — 三種比，看哪個 q feeder 給 MC-GARCH 最大 OOS lift

**補充候選文獻**（不必 3 篇外但 references.md 收錄）：
- Bollerslev & Ghysels (1996, JBES) — Periodic GARCH (calendar)
- Bauwens, Giot, Grammig & Veredas (2004, IJF) — UHF-GARCH
- Vatter, Wu, Chavez-Demoulin & Yu (SSRN 2330159) — Non-parametric intraday spot vol
- Engle (2000, Econometrica) — ACD/GARCH
- DeepVol (Tandfonline 2024) — dilated causal convolution baseline as ML comparator

---

## 4. Pilot Design — Phase 1 spec（不在 K1255 scoping 跑）

### 4.1 Data

| Market | Resolution | Source | OOS sample |
|--------|-----------|--------|------------|
| SPY | 5-min | yfinance `interval='5m'` 60-day rolling cap → 用 polygon / Alpha Vantage cached（2021-01 起）| 2024-01 ~ 2026-04（~580 trading days × 78 bars ≈ 45,240 obs）|
| 0050.TW | 5-min | `storage/5min_data/0050.TW_5min.parquet`（已有 60+ 天，需擴充）| 2024-07 ~ 2026-04（cap by 收集起點；~440 days × 54 bars ≈ 23,760 obs）|
| Optional | TAIFEX TX | **不用**（避免撞 K1100h scope）| — |

**bar count**：
- SPY 9:30-16:00 (390 min) / 5-min = 78 bars/day（含開收盤）
- 0050.TW 9:00-13:30 (270 min) / 5-min = 54 bars/day

### 4.2 Models（對齊 Engle & Sokalska 2012）

| Model | Spec | Free params |
|-------|------|------------|
| **M0 baseline** | Intraday GARCH(1,1) on raw r_{t,k}（無 q·s 分解）| 3 (ω, α, β) |
| **M1 PRG-like** | M0 + periodic dummies (K-1 dummies for hour-of-session) | 3 + (K-1) |
| **M2 MC-GARCH (FFF)** | σ²_{t,k} = q_t · s_k(FFF, P=5) · g_{t,k}; q_t = HAR-RV one-day-ahead; g = GARCH(1,1) on r̃_{t,k} = r_{t,k} / √(q_t · s_k) | 3 (g) + 11 (FFF: c_0 + 5 sin + 5 cos) + HAR-RV (3) |
| **M3 MC-GARCH (RGARCH q)** | M2 但 q_t = Realized GARCH forecast（Hansen-Huang-Shek 2012）| 3 + 11 + RGARCH (~5) |
| **M4 MC-GARCH (PRG q)** | M2 但 q_t = Paper 6 PRG daily forecast | 3 + 11 + PRG (6-8) |

### 4.3 Evaluation（嚴格遵守 `experiment-preamble.md` §3）

- **Target**: r²_{t,k}（Patton 2011 QLIKE 是 proxy-robust）；secondary: 1-day-ahead aggregated daily r²
- **DM test**: Harvey-HLN adjusted, lag = ⌈N^{1/3}⌉
- **Harvey threshold**: |t| > 3.0 為 main；|t|>1.96 only secondary direction
- **Lookahead**: q_t 必 lag 1 day（HAR-RV / RGARCH / PRG 都用 t-1 information）；s_k 用 IS train-only fit；g 走 expanding-window refit
- **Sample seeds**: numpy seed=42, scipy.optimize seed 透過 `n_restarts=10`

### 4.4 Pairwise comparisons & expected lifts

主比較：
- **M2 vs M0** (MC-GARCH vs naive intraday GARCH): Engle-Sokalska 2012 NYSE 結果 ~10-15% QLIKE 改善 → SPY/0050.TW 預期 5-15%（diurnal pattern 顯著程度 market-dependent）
- **M2 vs M1** (FFF vs dummies): 兩種 diurnal 表達，預期接近 (DM |t|<3 or NS)；若 FFF 顯著贏 → 連續 basis 優於 step function（methodological contribution）
- **M4 vs M2** (PRG-as-q vs HAR-RV-as-q): Paper 6 PRG 已驗證 daily-level edge → M4 應略勝 M2；若顯著 → **這是 PRG paper 6 的延伸貢獻**，可寫成 Paper 6 robustness section 或獨立 follow-up
- **Cross-market**：SPY 和 0050.TW 都應顯示 MC-GARCH lift；台股若 lift 小 → 提示 0050.TW 的 diurnal pattern 較弱（已知 0050.TW 量集中在開盤）

### 4.5 Sample-size sanity (Harvey scaling)

K1100g_d6 daily TAIFEX DM=+1.49, N=1385。SPY 5-min M2 vs M0 N≈45,240。理論上界：
```
t(5-min) ≈ +1.49 · √(45240/1385) ≈ +1.49 · √32.7 ≈ +8.5  (理論上界)
```
HAC 打 3-5 折後：realistic +1.7 ~ +2.8（marginal）；optimistic +5+。**故 M2 vs M0 過 Harvey 是合理 expectation**。

---

## 5. Risks & Mitigation

### R1. yfinance 5-min historical cap (60 天)
- **影響**: SPY 5-min 樣本不足以 OOS 跨多年
- **Mitigation**: (a) 用 `storage/5min_data/SPY_5min.parquet` 累積（已有 ~60 天，需從 2024-01 補回填 — 建議 polygon API 或 Alpha Vantage 替代 source；K1255 Phase 0 不負責補資料，列為 Phase 1 dependency）; (b) fallback 改用 1-day-ahead aggregated r² as secondary target，至少 daily-frequency DM 仍可算

### R2. FFF parameter count（過 fit 風險）
- **影響**: P=5（11 個 FFF 參數）對 78 bars/day × 580 days 看似 OK，但 single-day 樣本只有 78 obs → 若 IS 太短會過 fit
- **Mitigation**: (a) IS train > 1 year (~250 days × 78 bars ≈ 19,500 obs) 以充分覆蓋 FFF basis; (b) 用 BIC select P ∈ {3, 5, 7}; (c) cross-validation on holdout segment

### R3. q_t lookahead bias
- **影響**: HAR-RV t-1 forecast 必須在 t 開盤前可得；RGARCH 同理；PRG daily backbone 需特別注意 session boundary（PRG 預測 day t 前需用 t-1 night close 後的 information set）
- **Mitigation**: 嚴格 `q.shift(1)` + Codex review；對齊 `experiment-preamble.md` §1 模型-target 匹配規則

### R4. 0050.TW 5-min 量不足
- **影響**: 0050.TW 開盤 5-min bar 偏 thin；後段 bars 流動性 OK
- **Mitigation**: (a) 開盤集合競價 bar 單獨標記/剔除（同 K1100h R1）; (b) winsorize top 0.5% |return| outliers; (c) 比較 5-min vs 10-min vs 15-min grid robustness

### R5. K1100h overlap risk
- **影響**: K1100h scope 包含 TAIFEX tick + intraday periodic dummies，與 K1255 部分重疊
- **Mitigation**: K1255 **不碰 TAIFEX**（鎖 SPY + 0050.TW）；differentiation 額外靠 multiplicative component + FFF + external q_t plug-in。**Phase 1 啟動前再次 check K1100h 進度**：若 K1100h 已 Harvey PASS, K1255 重點放在 cross-market replication & FFF vs dummies methodological comparison；若 K1100h NULL，K1255 接力測試 multiplicative spec 是否突破 (alternative mechanism hypothesis)

### R6. Codex review gating
- **影響**: 前述任何 lookahead bias 或 sample-handling bug 會 invalidate 整個結果
- **Mitigation**: Phase 1 跑 estimation 前必走 `/codex:rescue` review on (a) q.shift(1) 是否到位 (b) FFF basis 是否在 IS-only fit (c) DM HAC lag 是否正確

---

## 6. Phase 1 Entrypoint（如 go/no-go = go）

1. **新 K**: K1256 = "MC-GARCH SPY 5-min M0/M1/M2 horse-race"
2. **依賴**:
   - `storage/5min_data/SPY_5min.parquet` 補回填到 2023-01 起（**Phase 1 第 0 步，可能需新 K1257 dedicated to data infra**）
   - 重用 Paper 6 PRG daily backbone for q_t (M4 spec) — 從 `experiments/k880v2/results.json` 取 PRG daily forecasts
3. **腳本骨架**:
   - `experiments/k1256/k1256_mcgarch_spy.py`：load 5-min → FFF estimation (IS) → MC-GARCH MLE → OOS rolling forecast → DM vs M0/M1
   - 用 `from volpred.stats.model_evaluation import strategy_dm_test`
   - 用 `clean_tw50_data` for 0050.TW (K1257 cross-market)
4. **Codex review request 模板**:
   ```
   /codex:rescue "Review experiments/k1256/k1256_mcgarch_spy.py for:
   (1) q_t lag - is q.shift(1) in place before multiplying with s_k?
   (2) FFF basis fit on IS only?
   (3) DM HAC lag = ceil(N^(1/3))?
   (4) De-seasonalization residual r̃ used for g, not raw r?
   Report issues."
   ```

---

## 7. Go / No-Go Recommendation

**Decision**: ✅ **GO**（pending Phase 1 排程）

**Rationale**:
1. **Topic-diversity quota 滿足**：feed_ct=0, kb_ct=0，是 audit 列 top 3 novelty 之一
2. **Differentiation 對 PRG / K1100h 清楚**：multiplicative ≠ additive；FFF ≠ dummies；SPY+0050.TW ≠ TAIFEX；external-q plug-in ≠ joint MLE
3. **與 PRG 互補非競爭**：M4 spec 把 PRG daily forecast 當 q feeder，可作為 Paper 6 robustness extension（不威脅 Paper 6 narrative）
4. **文獻基礎厚**：Engle-Sokalska 2012 已是 MC-GARCH canonical reference；Andersen-Bollerslev 1997 FFF 是 28 年 standard tool
5. **資料可達**：SPY 5-min 補資料是 known 工程任務（雖需獨立 K dedicated to data infra）；0050.TW 5-min 已 partial available

**Defer / Watch points**:
- K1100h Phase 1 結果 review 後再啟 K1256，避免重複算力
- K1257 (SPY 5-min historical backfill) 作為 K1256 的 dependency；若無法達標 2023-01，scope 可降至 daily target only

**Alternative if no-go**: 換到 audit 列第 4-5 候選 — **dynamic Nelson-Siegel / term-structure ML**（feed_ct=0, kb_ct=0；同樣是 deep methodology 缺口；但 data infra 較重 — 需 FRED daily yield curve + cross-sectional Bayesian 框架）。

---

## 8. Scope Boundary（K1255 Phase 0 closing）

K1255 **不**：
- ❌ 跑任何 estimation
- ❌ commit 程式
- ❌ 動 `storage/memory/knowledge.json` / `research_program.md` / `feed.json`
- ❌ 派 worktree agent

K1255 **只**產：
- ✅ 本 README.md
- ✅ `references.md`（3+ 篇文獻 metadata）
- ✅ Append `storage/work_log.json`（task_type=experiment, outcome=done, summary ≤160 chars）

下一動作：等用戶或 cron 觸發 K1256 Phase 1 estimation；K1100h Phase 1 完成後重 check overlap。
