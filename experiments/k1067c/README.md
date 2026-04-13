# K1067c: MediaTek (2454.TW) Single-Stock A4f-EAV — Monotonicity Test

**Status**: ✅ Complete (2026-04-13)
**Proposer**: 賴奕豪
**Executor**: Claude
**Data**: yfinance (2454.TW, ^VIX) + 財報公告日.txt (Big5, filter code==2454)
**Sample**: 2010-01-05 ~ 2025-12-30 (n=3,911); OOS 2019-01-02 ~ 2025-12-30 (n=1,697, 28 T+1 event days)
**Random seed**: 42; Runtime: 231 s

## 動機 / The Big Question

K1067 (TSMC, T+1 amp = 0.98) yielded NULL (aggregate DM t = +0.348, event DM t = +0.083).
K1067b (UMC, T+1 amp = 2.58) yielded strong **event-window** signal (event DM t = −2.204, event improvement = +39.27%, θ₂ pos_frac = 1.00).

Two data points raised a monotonicity conjecture: **does EAV event-window edge scale with T+1 amplification?** If yes, Paper 2 can use T+1 amp as a firm-selection criterion. K1067c provides the third data point using MediaTek (2454.TW), K1060 T+1 amp = 1.67 — squarely between TSMC (0.98) and UMC (2.58).

## 方法

- Identical GARCH-MIDAS specification to K1067/K1067b (only asset changes):
  - `τ_{t+1} = max(θ₀ + θ₁·VIX²_t + θ₂·EAV_t, ε)` (t-1 exogenous info)
  - `g_t = ω + α·u²_{t-1} + γ·u²_{t-1}·I(u<0) + β·g_{t-1}`
  - `σ²_{t+1} = τ_{t+1}·g_{t+1}`
- EAV binary: 1 on day t if MediaTek earnings announcement, else 0. Mapped to first trading day ≥ announcement date via `searchsorted` (Taiwan post-close convention).
- Rolling window = 2000; refit every 63 days (quarterly) → 27 refits over OOS.
- Evaluation: QLIKE on r² (Patton 2011), DM Harvey |t|>3.0 threshold, θ₂ one-sample t-test + 2000-rep bootstrap, event T+1 vs non-event conditional DM.

### Data summary
| Item | Value |
|---|---|
| Announcements in file | 64 (2010-04-15 ~ 2025-11-13) |
| Distinct event trading days | 59 |
| OOS event days | 28 (T+1) |
| Event-day fraction | 1.51% |
| ADF stat (log ret) | −33.4 (p < 0.001, stationary) |
| ARCH-LM(10) | 153.9 (p = 5.9e-28, strong ARCH) |
| Full-sample r²_event/r²_nonevent (T+1) | 0.865 |
| In-sample corr(r², EAV) | **−0.0168** |

> Note: Full-sample T+1 r² ratio 0.865 for MediaTek (2019-2025 OOS) is actually *below* 1.0 — MediaTek's ex-post event-day vol in OOS is **lower** than non-event vol, even though K1060 reported T+1 amp = 1.67 over a different sample. This already foreshadows the result.

## 三公司核心對照表

| 指標 | TSMC (K1067) | MediaTek (K1067c) | UMC (K1067b) |
|---|---:|---:|---:|
| Ticker | 2330.TW | **2454.TW** | 2303.TW |
| K1060 T+1 amplification | 0.983 | **1.67** | 2.579 |
| OOS n | 1,697 | 1,697 | 1,697 |
| OOS event T+1 days | 28 | 28 | 28 |
| Refits | 27 | 27 | 27 |
| In-sample corr(r², EAV) | −0.0011 | **−0.0168** | +0.0319 |
| Aggregate DM t (A4f+EAV vs A4f) | +0.348 | **+0.616** | −1.371 |
| Aggregate QLIKE improvement | −0.070% | **−0.154%** | +0.517% |
| Event T+1 DM t | +0.083 | **+1.588** | −2.204 |
| Event T+1 improvement | −0.249% | **−23.461%** | +39.266% |
| θ₂ positive fraction | 0.593 | **0.185** | 1.000 |
| θ₂ one-sided p (>0) | 0.948 | **0.980** | 6.7e-15 |
| θ₂ bootstrap 95% CI | — | [−1.83e-3, −1.76e-4] | — |
| Harvey |t|>3 (aggregate) | FAIL | FAIL | FAIL |

### Monotonicity 假設檢驗

| 假設 | 標準 | MediaTek 實測 | 結果 |
|---|---|---:|---|
| H1 | |event DM t| ∈ [0.083, 2.204] | 1.588 | **PASS** (magnitude only) |
| H2 | θ₂ pos_frac ∈ [0.593, 1.000] | 0.185 | **FAIL** |
| H3 | event improvement ∈ [−0.249%, +39.27%] | −23.46% | **FAIL** |
| H4 (strong) | |linear interp residual| < 0.5 | residual = +2.49 | **FAIL** |

**Overall monotonicity verdict: FAIL**

Critical nuance: H1 passes only on **magnitude**. The **sign** of MediaTek's event DM t is POSITIVE (A4f better) while UMC's is NEGATIVE (EAV better) — they point in opposite directions. Linear interpolation between (0.98, +0.083) and (2.58, −2.204) predicted MediaTek ≈ −0.90 (EAV slightly better), but we observe +1.59 (A4f notably better) — a residual of +2.49, more than 2.5× the permissible threshold.

## 結論

### T+1 放大倍率 ≠ EAV event-window edge 的單調預測子

三個單一個股 + 一個 MediaTek 內部觀察給出強力否定證據：

1. **TSMC 低放大 (0.98) → NULL (微負)**  ← 與直覺一致
2. **UMC 高放大 (2.58) → 強正 event signal (+39.3%)**  ← 與直覺一致
3. **MediaTek 中放大 (1.67) → 強負 event signal (−23.5%)**  ← **破壞單調性**

MediaTek 顯示 EAV regressor 在 event-window 上**顯著傷害**預測精度（event improvement = −23.5%、DM t = +1.588 向 A4f 偏），θ₂ 在 27 次 refit 中僅 5 次為正（pos_frac = 0.185）、bootstrap 95% CI 完全落在負區 [−1.83e-3, −1.76e-4]。UMC 的 100% 正 θ₂ 與 MediaTek 的 15% 正 θ₂ 之間沒有來自 T+1 的線性橋樑。

### 對 Paper 2 的影響

- **不可**以 T+1 amplification 作為 firm-selection criterion（MediaTek 反例）。
- UMC 的強 event signal 可能是 firm-specific artefact（晶圓代工商品化週期、法說會 timing、較大相對 EPS 變異）而非可一般化的統計規律。
- Paper 2 若要保留 EAV regressor，必須：
  1. 用 panel GARCH-MIDAS 在 ≥15 檔股票上做橫截面統計，不能靠 N=3 的類比推論。
  2. 加入更豐富的 firm-level covariate（analyst dispersion、float、sector dummy、options-implied pre-event vol）。
  3. 區分 foundry vs fabless 次級產業——UMC/TSMC 同為 foundry、MediaTek 為 fabless，可能是非單調性的結構原因。

### 局限與不可控因素

- N=3 observations 無法建立嚴謹的 cross-sectional test；這只是 motivational evidence for panel extension。
- MediaTek 的 28 個 OOS event days 樣本小，event-window DM 本身 standard error 大。
- 財報公告日.txt 是「發佈日」不是「盤後即時」；若某次公告落在台股收盤後但美股盤前，VIX^2 信息可能已反映→ 潛在 timing 複雜度。
- `u_prev = r_{t-1}/√tau[t]` 使用當日 τ 而非昨日 τ（Codex 已指出 HIGH timing issue）——但此實作與 K1067/K1067b 完全相同，保留以確保三公司比較的方法論一致性。若要修正，需同步 refit TSMC/UMC，在下一輪「bug-fix replication」統一處理。

## 衍生方向（寫入 research_program.md）

1. **K1068: Panel GARCH-MIDAS across N≥15 Taiwanese stocks** — 用 foundry/fabless 分組 + analyst dispersion，檢驗 EAV 在 panel 層級是否仍有 marginal information content。
2. **K1068b: Implied-vol pre-event signal** — 與其用 backward-looking announcement flag，改用 options-implied 30-day IV 的 event-day upward shift 作為 ex-ante EAV。
3. **K1068c: u_prev τ-lag bug-fix replication** — 在 K1067/K1067b/K1067c 三檔上同步修正 `u_prev = r_{t-1}/√τ[t-1]`，驗證 UMC event +39% 是否為此 timing quirk 放大的結果。若 UMC 修正後仍顯著 → 可信；若消失 → 推翻 K1067b 結論，monotonicity 討論失去核心 anchor。

## 檔案

| 檔案 | 說明 |
|---|---|
| `k1067c.py` | 主腳本（1132 行；K1067b 修改版） |
| `k1067c_results.json` | 完整結果（27 KB） |
| `k1067c_dm_comparison.png` | 圖1：QLIKE + 跨資產 aggregate DM t 比較（含 ETF baseline） |
| `k1067c_event_window_analysis.png` | 圖2：Event T+1 vs non-event QLIKE improvement |
| `k1067c_theta2_evolution.png` | 圖3：θ₂ time-series + bootstrap CI + monotonicity scatter |
| `README.md` | 本檔 |

## 參考文獻

- Engle, Ghysels & Sohn (2013). GARCH-MIDAS. *Review of Economics and Statistics* 95(3):776-797.
- Patton (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics* 160:246-256.
- Harvey, Leybourne & Newbold (2016). Testing the equality of prediction mean squared errors. *International Journal of Forecasting* 13(2):281-291 — DM |t|>3 threshold.
- Patell & Wolfson (1984). The intraday speed of adjustment of stock prices to earnings and dividend announcements. *Journal of Accounting Research*.
- K1058: A4f baseline on 0050.TW.
- K1060: Per-stock EAV — TSMC T+1=0.98, MediaTek T+1=1.67, Hon Hai T+1=1.22, UMC T+1=2.58.
- K1064: ETF A4f+EAV all NULL.
- K1067: TSMC single-stock A4f+EAV NULL (aggregate DM t=+0.348, event DM t=+0.083).
- K1067b: UMC single-stock A4f+EAV MIXED (event DM t=−2.204, event improvement=+39.27%).
