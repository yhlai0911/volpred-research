# K1077: A4f Extended History on 0050.TW — Taiwan Cross-Market Mirror of K1075

**提出者**：用戶（Yi-Hao Lai）
**執行者**：Claude
**日期**：2026-04-12
**狀態**：完成（NULL at Harvey threshold; directional signal in Middle/Late windows）

---

## 1. Motivation & 問題描述

K1075 驗證了 A4f 模型（multiplicative GARCH-X with VIX², free ω）在 **SPY 2007-2026** 的跨時期穩健性：

- Full OOS DM t = **+7.92**（Harvey PASS）
- GFC 2008-09 sub-period DM t = +3.14（PASS）
- VIX buckets 呈 monotonic improvement
- θ₁ 落在 1e-7 ~ 9e-7 的穩定帶狀區間

然而 **K1058 在 0050.TW 上報告 A4f DM t=-1.26 NS**（OOS 2019-2025，~6 年）。

**核心問題**：K1058 的 null result 是因為 (a) OOS 太短（只有 6 年、COVID 主導），還是 (b) A4f 本身對台灣市場不適用？

K1077 以 K1075 的擴展歷史設計（3 個非重疊 OOS windows、總長 16 年）檢驗此問題。

## 2. 動機與假說

### H1: Full OOS 2010-2025 A4f vs GJR DM Harvey-PASS（|t|>3）
延長樣本至 16 年能否讓 A4f 在台灣市場也跨過 Harvey 門檻？

### H2: 2011 Euro Crisis 子期間 A4f 改善 GJR
台股是否也像 SPY 在高波動期間特別需要 VIX² 資訊？

### H3: COVID 2020 子期間 A4f 改善 GJR
COVID VIX 達 82.7 是樣本中最極端波動，A4f 是否能捕捉？

### H4: θ₁(0050.TW) vs θ₁(SPY) 的穩定性差異
台灣市場對 VIX² 的敏感度（loading）是否與美國不同？

## 3. 方法

### 數據
- **0050.TW**：yfinance 2005-07-01 ~ 2025-12-30
  - ⚠️ 必須 `from volpred.utils import clean_tw50_data` 處理 2014-01-02 的 1:4 split artifact
  - **實際上 Yahoo 只回傳 2009-01-02 起的資料**（IPO 2003-06-30 但 Yahoo 早期數據缺失）
  - Safety net: 丟棄 |log_ret| > 0.3 的殘留極端值
  - 最終 n = 4,161（2009-01-05 ~ 2025-12-30）
- **^VIX**：yfinance 同期間，forward-fill 到 0050.TW 交易日（處理 TW/US 假日不對齊）

### 模型（與 K1075 完全對齊）
- **GJR-GARCH(1,1)**：`σ²_t = ω + α r²_{t-1} + γ r²_{t-1} I(r_{t-1}<0) + β σ²_{t-1}`
- **A4f**（Engle et al. 2013 logic）：
  - τ_t = max(θ₀ + θ₁ · VIX²_{t-1}, 1e-16)
  - u_{t-1} = r_{t-1} / √τ_t
  - g_t = ω_g + α u²_{t-1} + γ u²_{t-1} I(u<0) + β g_{t-1}
  - σ²_t = τ_t · g_t

### OOS 設計（3 個非重疊 windows）

| Window | Period | n | VIX max | ret std (ann) |
|--------|--------|---|---------|---------------|
| Early_2010_2014 | 2010-01-01 to 2014-12-31 | 1,237 | 48.0 | 0.161 |
| Middle_2015_2019 | 2015-01-01 to 2019-12-31 | 1,219 | 40.7 | 0.146 |
| Late_2020_2025 | 2020-01-01 to 2025-12-31 | 1,457 | 82.7 | 0.218 |

**訓練**：rolling window w=2000, refit every 63 天（quarterly）
**評估**：QLIKE on r² (Patton 2011), DM test (HAC Newey-West, Harvey |t|>3.0)
**Bootstrap CI**：1,000 reps, block length = n^(1/3)
**Seed**: 42

### 資料可用性警告（Limitation）

由於 Yahoo 0050.TW 只回傳 2009 年起的資料，雖然 `max(0, abs_idx - WINDOW)` 允許縮短訓練窗口，但：
- Early_2010_2014 開始時僅 ~248 天 training data（vs. 目標 2000 天）
- Middle_2015_2019 開始時約 1,485 天（仍短於 2000）
- Late_2020_2025 是唯一有完整 2000-day window 的期間

這會讓 Early window 的估計特別不穩，影響 H1 的總體顯著性。

### Crisis sub-periods（台灣相關）

| Crisis | Period | 預期 |
|--------|--------|------|
| Euro_Crisis_2011 | 2011-06 to 2012-06 | 歐債危機，VIX~48 |
| TradeWar_2018_2019 | 2018 to 2019 | 中美貿易戰 |
| COVID_2020 | 2020-02 to 2020-06 | VIX=82.7 極值 |
| Bear_2022 | 2022 | 升息 + 通膨 + 烏俄戰爭 |

### VIX buckets

Low(<15) / Normal(15-25) / High(25-40) / Extreme(40-60) / Crisis(60+)
注意：TW 樣本中 VIX>60 僅 11 天 → Crisis bucket insufficient。

---

## 4. 結果

### 4.1 Full OOS（2010-2025, n=3,913）

| 指標 | GJR | A4f | Diff |
|------|-----|-----|------|
| QLIKE | -8.1154 | -8.0885 | +0.33% |
| DM t | — | — | **-0.488** (NS) |
| DM p | — | — | 0.626 |
| Spearman | — | — | (non-significant) |
| Harvey PASS (|t|>3) | — | — | **FAIL** |

**結論**：Full OOS 下 A4f **未改善** GJR。DM t = -0.488，QLIKE 甚至略差 0.33%。

### 4.2 Per-window（非重疊 5-6 年期間）

| Window | n | QL_GJR | QL_A4f | Diff% | DM t | Harvey |
|--------|---|--------|--------|-------|------|--------|
| Early_2010_2014 | 1,237 | -8.291 | -8.092 | **+2.39%** | **-1.270** | FAIL |
| Middle_2015_2019 | 1,219 | -8.448 | -8.500 | -0.61% | **+2.789** | FAIL |
| Late_2020_2025 | 1,457 | -7.689 | -7.741 | -0.69% | +1.956 | FAIL |

**關鍵觀察**：
- Early window A4f **明顯較差**（QLIKE +2.39%、DM t=-1.27），但受 short-training 效應影響
- Middle window A4f **接近顯著**（DM t=+2.789，超過 95% CI 但未達 Harvey |t|>3）
- Late window A4f **directionally 改善**（DM t=+1.956）
- Middle + Late 合計 = 2,676 天 DM 改善，Early 1,237 天 DM 惡化 → 長期趨勢 dominating 但 Early 拖累 full OOS

### 4.3 Crisis sub-periods

| Crisis | n | QL diff% | DM t | VIX mean/max |
|--------|---|----------|------|--------------|
| Euro_Crisis_2011 | 269 | -0.39% | +0.590 | 31.6 / 48.0 |
| TradeWar_2018_2019 | 486 | -1.01% | **+2.290** | 16.5 / 36.1 |
| COVID_2020 | 101 | -0.41% | +0.251 | 34.9 / 82.7 |
| Bear_2022 | 246 | -1.25% | **+2.052** | 25.8 / 36.5 |

**所有 crisis sub-periods 的 A4f QLIKE 方向性改善，但無一達 Harvey 門檻**。Trade War 與 Bear 2022 接近 95% CI。

值得注意的是 **COVID 2020 的 DM 幾乎中性**（t=+0.25），與 SPY 上 COVID 期間 A4f 的強勢顯著改善（K1075 顯示）形成對比。

### 4.4 VIX buckets

| Bucket | Range | n | QL diff% | DM t |
|--------|-------|---|----------|------|
| Low | [0,15) | 1,419 | -0.22% | +1.246 |
| Normal | [15,25) | 1,960 | **+1.12%** | -0.861 |
| High | [25,40) | 483 | -0.91% | +1.221 |
| Extreme | [40,60) | 40 | -2.80% | +0.847 |
| Crisis | [60,200) | 11 | insufficient | — |

**非單調**：Normal bucket A4f 反而 **更差**（+1.12%），這與 K1075 的 SPY 結果（Normal 顯著改善）相反。Low、High、Extreme 均 directionally 改善但 n 太小 / DM 不顯著。

### 4.5 θ₁ 分布與穩定性

| 統計量 | 0050.TW (K1077) | SPY (K1075) |
|--------|-----------------|-------------|
| Mean | 1.27e-05 | ~4e-7 |
| Median | 1.81e-07 | ~3e-7 |
| Min | 5.21e-08 | ~1e-7 |
| Max | 3.23e-04 | ~9e-7 |
| Range（數量級）| 4 orders | <1 order |

**核心發現**：
- **Median θ₁ 與 SPY 相近**（1.81e-07，落在 SPY 1e-7~9e-7 帶內）
- **但 mean 受少數極大 outlier 拉高到 1.27e-05**（76x median）
- θ₁ 在 0050.TW 上跨越 **4 個數量級**（5e-8 ~ 3e-4），而 SPY 僅 1 個數量級
- **結論**：TW 上 θ₁ 估計**極度不穩定**，部分 refit 抓到 extreme loading，部分落在 SPY 水準

此 instability 可能是 Early window 惡化的主因：refit 期間若 θ₁ 被高估，τ_t 被極大化，導致 σ²_t 預測系統性過大、QLIKE 惡化。

---

## 5. Hypothesis Verdicts

| H | 描述 | 結果 |
|---|------|------|
| H1 | Full OOS DM Harvey-PASS | **FAIL**（t=-0.488） |
| H2 | Euro 2011 A4f 改善 | PASS directionally（diff -0.39%），但 DM NS |
| H3 | COVID 2020 A4f 改善 | PASS directionally（diff -0.41%），但 DM 幾乎 0 |
| H4 | θ₁ TW vs SPY | **DIFFERENT**（TW 不穩定，跨 4 個數量級） |

**Overall**：Null result at Harvey threshold. A4f **在台灣市場的效力弱於美國**，主要原因是 θ₁ 估計不穩定，並非樣本過短（Middle + Late 合計 10 年仍未 PASS）。

---

## 6. 結論與 Paper 2 意涵

### 6.1 核心結論

1. **A4f 不能直接從 SPY transfer 到 0050.TW**：即使延長 OOS 至 16 年，DM t 仍未達 Harvey 門檻。K1058 的 null result **不是樣本長度問題**。

2. **VIX² 對 TW 的 long-run 成分解釋力較弱**：
   - Middle/Late windows DM +2.8/+2.0 顯示仍有 directional 訊號
   - 但 Normal bucket 實際上變差（+1.12% QLIKE）— TW 在「正常 VIX」期間不需要外生資訊
   - A4f 的價值集中在 Crisis/Extreme VIX 期間，但這些期間 n 太小無法 Harvey-PASS

3. **θ₁ 不穩定是主因**：TW 上 θ₁ 跨 4 個數量級，說明 rolling window 對 VIX² 的最優 loading 敏感度極高，estimation 不如 SPY 穩定。

4. **Early window 受數據限制**：Yahoo 只有 2009+ 資料，Early_2010_2014 訓練窗口短於 2000 天，估計品質差；這解釋部分 Full OOS 的 drag。

### 6.2 對 Paper 2（Taiwan VT）的建議

- ❌ **不建議**在 Paper 2 Taiwan VT 中引用 A4f 作為 cross-market robustness feature。Null result 必須如實報告。
- ✅ **建議**改用的方向：
  - **在 Paper 2 中將 A4f 作為「cross-market 不 naive transfer」的反面案例**：證明 VIX-based multiplicative 成分在美國有效（Paper 9 / K1075），但台灣需要 local indicator 或不同結構
  - **探索 VIXTWN** 作為 local regressor（K997 測過但單獨 NS；可能需要 VIX + VIXTWN 混合）
  - **探索週頻或月頻 τ**：K1075 強調 τ 是 long-run component；TW 上 θ₁ 不穩或許是 daily VIX² 雜訊過高造成，改用 weekly/monthly MIDAS 聚合可能更穩
  - **探索 PRS-like session split**：Engle 2013 的 long-run 成分在 TW 上可能不是 overnight VIX 驅動，而是 TW 日盤/夜盤結構
- ✅ **Paper 2 可引用 K1077 的 θ₁ instability 發現**，作為說明「為什麼 Paper 2 用 8.63/VIX 簡單規則而非 MIDAS/GARCH-X」的理論依據之一

### 6.3 衍生研究方向（寫回 research_program.md）

1. **K1078（建議）**：A4f with VIXTWN² for 0050.TW — 是否 local VIX 能解決 θ₁ instability？
2. **K1079（建議）**：A4f monthly τ aggregation on 0050.TW — daily VIX² 雜訊假設
3. **K1080（建議）**：Early window 重做，用更長 TWII 或 TAIEX 代理數據填補 pre-2009 gap

---

## 7. Limitations（研究誠實原則第 10 條）

1. **資料可用性**：Yahoo 0050.TW 只有 2009+ 資料，Early window 訓練窗口短於 2000，Late window 才滿足完整 window
2. **VIX lag**：本實驗用 `VIX_{t-1}`（forward-fill）代表「前一美國交易日」VIX。TW 在台北時間 9:00 開盤，而 US VIX 在 UTC 21:15 收盤（台北時間早上 5:15），因此 TW 開盤時已知前一日 VIX。此 lag convention 正確。
3. **樣本 n=3,913** 雖超過 K1058 的 ~1,500，但 Crisis bucket (VIX>60) 只有 11 obs
4. **未測 VaR/ES Trinity**：本實驗聚焦 QLIKE/DM，風險管理層面交由後續實驗
5. **未測 VIXTWN**：K997 已測過單獨使用，Null；K1077 未組合測試
6. **未 detrend θ₁**：refit 間 θ₁ 跳動可能混合了 true time-variation 與 estimation noise

---

## 8. 檔案清單

- `k1077.py` — 完整實驗腳本
- `k1077_results.json` — 全部結果（full_oos, per_window, crisis_subperiods, vix_buckets, refit_log, spy_vs_tw_comparison）
- `k1077_extended_dm.png` — 3 OOS windows QLIKE + DM 對比
- `k1077_crisis_periods.png` — 4 crisis sub-periods DM t-stat
- `k1077_vix_bucket.png` — VIX buckets QLIKE diff%
- `k1077_theta1_evolution.png` — θ₁ 2010-2025 log-scale + SPY 參考帶
- `k1077_sp_vs_tw.png` — SPY vs TW 對照（DM per-window + θ₁ distribution）
- `README.md` — 本檔

---

## 9. References

- Engle, R.F., Ghysels, E., & Sohn, B. (2013). Stock Market Volatility and Macroeconomic Fundamentals. *Review of Economics and Statistics* 95(3):776-797.
- Conrad, C., & Loch, K. (2015). Anticipating Long-Term Stock Market Volatility. *JBES*.
- Patton, A.J. (2011). Volatility forecast comparison using imperfect volatility proxies. *J Econometrics* 160:246-256.
- Harvey, D.I., Leybourne, S.J., & Newbold, P. (2016). Testing the equality of prediction mean squared errors.
- Hansen, P.R., & Lunde, A. (2005). A forecast comparison of volatility models. *J Applied Econometrics* 20:873-889.

**Upstream K experiments**:
- **K1075 (SPY 2007-2026)**: A4f Full DM t=+7.92, GFC PASS. This is the SPY counterpart being mirrored
- **K1058 (0050.TW 2019-2025)**: A4f DM t=-1.26 NS. K1077 extends the OOS to answer whether short-sample caused the null
- **K988 (SPY A4f)**: DM t=4.48 vs GJR baseline
- **K1056 (SPY 5 sub-periods)**: All 5 periods A4f > GJR
- **K1064 (0050.TW A4f+EAV)**: NULL (VIX 吸收)
- **K997 (0050.TW VIXTWN)**: Local fear index not superior to US VIX alone

**Random seed**: 42
**Total runtime**: 141 seconds
