# K1116f — Cross-asset PIT alignment (GLD / TLT / BTC) for Paper 4

**狀態**: COMPLETED — Verdict **ASSET_SPECIFIC (PIT-robust)**, with key qualifier
**日期**: 2026-04-17
**Worktree**: `agent-a458447b`

## 1. 動機 (WHY)

- **K1116c** 已確認 SPY weekly 下 alt-data (EPU / NFCI / ANFCI / STLFSI) 對 VIX
  baseline 在 **PIT release-calendar alignment** 下仍 robust NULL，所有 6 個 lag
  變體都沒有 `DM t > 3` 的 cell。
- **K1118** 把框架延伸到 GLD / TLT / BTC，但用的是 **`shift(1)` 在 weekly
  panel** 上 — 對 NFCI/ANFCI (release Wed W+1) 與 STLFSI (release Thu W+1) 而言，
  `shift(1)` 其實還 leak 了觀察週的 release-day 資料。這可能 **高估** alt-data
  相對 native IV 的解釋力（尤其 K1118 中 TLT M4 finstress DM = +3.74 的 marginal
  "win"）。
- **研究問題**: 把 K1116c 的 PIT alignment 套用到 K1118 cross-asset cells，看
  alt-data NULL 是否 universal 跨 asset，或 asset-specific（特別是 TLT 的 M4 signal
  會不會在 PIT 下消失）。

### 差異化
- K1116c: SPY only, PIT
- K1118: GLD/TLT/BTC, shift(1)
- **K1116f** = K1118 cells × K1116c PIT framework（唯一交集）

### 相關 K
- K1116 / K1116b / K1116c: SPY publication-delay + PIT 系列
- K1118: 原 cross-asset shift(1)
- K1121: daily alt-data allocation NULL
- K1098: 0050.TW / VIXTWN sufficiency

## 2. 資料與方法

### 2.1 市場資料 (per K1118 convention)

| Asset | Ticker | Native IV | IV type | Weekly agg |
|-------|--------|-----------|---------|------------|
| GLD | GLD | ^GVZ | close | W-FRI |
| TLT | TLT | ^MOVE | close | W-FRI |
| BTC-USD | BTC-USD | 30-day rolling RV (proxy) | rv30 | W-FRI |

- Weekly RV = `sqrt(sum(daily log-return²))`
- 期間 2018-01-12 → 2026-04-10
- IS: 2018-01-01 → 2022-12-31
- OOS: 2023-01-01 → 2026-04-10 (**170 weeks common per asset**)

> **Note on HAR-RV(1/5/22)**: brief 提到 HAR-RV 是 daily-native，但 K1116c 與 K1118
> 的 baseline 都是 **weekly AR(1) + native IV**。為了保持與 K1116c / K1118
> 直接可比（本實驗定位是「把 PIT 套用到 K1118 cells」），我們延續 weekly AR(1)+IV
> 框架。HAR-RV daily 版本是另一條獨立 follow-up，不屬 K1116f scope。

### 2.2 Alt-data 與 PIT 規格（來自 K1116c）

| Indicator | Cadence | Publication lag | Source |
|-----------|---------|-----------------|--------|
| USEPU | daily | T+1 business day | K1116c `USEPU_with_release_date.csv` + `USEPU_weekly_pit.csv` |
| WLEMU | daily | T+1 business day | 同上 |
| NFCI | weekly (Fri obs) | Wed of W+1 (~BDay+3 after obs) | 同上 |
| ANFCI | weekly (Fri obs) | Wed of W+1 | 同上 |
| STLFSI | weekly (Fri obs) | Thu of W+1 (~BDay+4) | 同上 |

- **PIT 組法** (K1116c 原版): 對每個 Friday F，取 `release_date <= F` 的最新觀察
- Weekly-mean panel 則只做觀察週均值（K1118 convention），無 explicit release 濾波
- 本實驗 **直接 reuse** `experiments/k1116c/data/<alias>_weekly_pit.csv`，不重抓
  也不自創 publication lag

### 2.3 三個變體

| Variant | Alt-data 面板 | Signal lag | 對應歷史實驗 |
|---------|---------------|-----------|----------------|
| `k1118_shift1` | weekly_mean | `shift(1)` | **K1118 reproduction** |
| `pit_shift0` | PIT | `shift(0)` | **K1116c PIT 主變體** |
| `pit_shift1` | PIT | `shift(1)` | K1116c 額外安全 margin |

### 2.4 五個 model specs（與 K1118 一致）

| Spec | Regressors (per variant's lag rule) |
|------|-------------------------------------|
| `base` | AR(1) only |
| `iv` | AR(1) + native IV (**baseline for DM**) |
| `epu` | AR(1) + USEPU + WLEMU (no IV — pure alt) |
| `finstress` | AR(1) + NFCI + ANFCI + STLFSI (no IV — pure alt) |
| `all` | AR(1) + IV + 5 alt-data (kitchen sink) |

OLS with `statsmodels.OLS`; QLIKE = `log(pred) + actual/pred` (Patton 2011 proxy-robust);
DM-HLN with Harvey (1997) correction; threshold = **Harvey (2016) |t|>3** (project
policy) 與 `|t|>2` 參考報告。

### 2.5 Lookahead 防錯

- 所有 regressor 在 code 明標 `shift(lag)` 或等效；PIT panel 本身即 `<=F`，故
  PIT spec 用 `shift(0)` 不 leak
- `signal from t-1, return at t` 慣例透過 `df_sub["rv"].shift(1)` + 明確 `signal`
  欄位的 lag 統一處理
- Seed = 42（np.random.seed）

## 3. 結果

### 3.1 DM t vs IV baseline（positive = alt 擊敗 IV；Harvey threshold |t|>3）

#### GLD (IV = GVZ)

| Variant | base | epu | finstress | all |
|---------|------:|-----:|----------:|-----:|
| k1118_shift1 | −2.103 | −1.773 | **−3.341** | −0.129 |
| pit_shift0   | −2.103 | −2.069 | **−3.341** | −2.246 |
| pit_shift1   | −2.103 | −2.942 | **−3.029** | −0.613 |

- **GLD: PIT 完全 confirms K1118 NULL** — GVZ baseline 擊敗 finstress 在三個變體
  都 `t<-3`，沒有任一 alt-spec 翻身
- `all` spec 在 PIT 下從 −0.13 惡化到 −2.25，顯示 PIT 讓 kitchen-sink 的 overfit
  negative effect 更明顯

#### TLT (IV = MOVE)

| Variant | base | epu | finstress | all |
|---------|------:|-----:|----------:|-----:|
| k1118_shift1 | +1.433 | −0.831 | **+3.743** | **−5.179** |
| pit_shift0   | +1.433 | −2.477 | **+3.743** | **−5.666** |
| pit_shift1   | +1.433 | −1.385 |   +2.000   | **−5.600** |

- **TLT finstress 在 `pit_shift0` 下 DM t 與 shift(1) 幾乎相同 (+3.74)**，
  因為 NFCI/ANFCI 的 PIT 值與 weekly_mean 相關係數 >0.985 (K1116c §4.3)，
  這裡的 "finstress win" 不是 shift(1) 的 publication-leak 人工效果
- **但 `pit_shift1` 下降到 +2.00 (p=0.047，Harvey 不顯著)**，顯示 TLT finstress
  signal 對 lag 敏感
- QLIKE improvement = +0.50%（遠低於 5% 門檻）— 與 K1118 結論一致：**TLT M4
  triple-gate FAIL**，不是真正的 niche
- `all` spec 在所有變體 `t<-5`，kitchen sink overfit 依舊 actively harmful

#### BTC-USD (IV = RV30 proxy)

| Variant | base | epu | finstress | all |
|---------|------:|-----:|----------:|-----:|
| k1118_shift1 | **−5.494** | **−5.039** | +1.370 | −1.282 |
| pit_shift0   | **−5.494** | **−3.550** | +1.370 | +0.203 |
| pit_shift1   | **−5.494** | **−3.387** | +1.035 | +0.142 |

- **BTC finstress 全部變體 `t<+2`** — PIT 沒救回來
- BTC `base` vs `iv` (RV30) → AR(1) 擊敗 RV30 proxy (t=−5.49)，與 K1118 一致
  (RV30 是 backward-looking proxy，不是 forward-looking DVOL)
- EPU 在 PIT 下仍 `t<-3`，與 K1118 "EPU actively harms BTC" 結論一致

### 3.2 QLIKE improvement (best alt vs IV baseline)

| Asset | k1118_shift1 | pit_shift0 | pit_shift1 | 5% gate? |
|-------|-------------:|-----------:|-----------:|----------|
| GLD   | −0.02% | −0.63% | −0.09% | FAIL (negative) |
| TLT   | +0.50% | +0.50% | +0.18% | FAIL (<5%) |
| BTC   | +0.23% | +0.23% | +0.13% | FAIL (<5%) |

沒有任何 asset × variant 通過 5% QLIKE gate。

### 3.3 Cross-asset 合成

| Variant | Harvey \|t\|>3 pass | \|t\|>2 pass | baseline \|t\|>3 wins |
|---------|---------------------|---------------|-----------------------|
| k1118_shift1 | [TLT] | [TLT] | 4 |
| pit_shift0   | [TLT] | [TLT] | 4 |
| pit_shift1   | []    | []    | 4 |

**PIT vs shift(1) 在 asset-level finstress t 的 Spearman rho** = 詳見
`k1116f_results.json` `spearman_pit_vs_shift1_finstress_t`（3 assets 樣本，rank 皆
同序，rho 為 +1 邊界案例）— NULL 方向一致。

### 3.4 與 K1116c SPY PIT 的對照

| Cell | K1116c SPY pit_shift0 | K1116f cross-asset pit_shift0 |
|------|-----------------------:|-------------------------------:|
| finstress DM t | −3.001 | GLD −3.34, TLT +3.74, BTC +1.37 |
| epu DM t | −2.603 | GLD −2.07, TLT −2.48, BTC −3.55 |
| all DM t | −2.537 | GLD −2.25, TLT −5.67, BTC +0.20 |

- **SPY / GLD**: PIT 下 finstress 一致被 baseline 擊敗（同方向 NULL）
- **TLT**: 唯一 finstress positive t，但 magnitude 不通過 triple gate
- **BTC**: finstress 方向正但不顯著

## 4. Verdict

**ASSET_SPECIFIC under PIT**，但具強烈 qualifier：

1. **K1116c SPY NULL 在 GLD、BTC 下被 PIT 確認**，兩者皆跨三個變體維持 alt-data
   無法擊敗 native IV。
2. **TLT finstress 在 `pit_shift0` 下 DM t = +3.74** 與 K1118 shift(1) 幾乎相同，
   看似 "alt-data 對 TLT 有邊際訊號" — **但**:
   - QLIKE improvement 僅 +0.50%（遠低於 5% triple-gate 門檻）
   - `pit_shift1`（額外安全 margin）下降到 +2.00（Harvey |t|>3 fail）
   - K1118 subperiod stability 已 fail (2023 t=1.71, 2024 t=1.69, 2025 t=2.90)
   - `all` spec 加入 IV + 5 alt 後 overfit (`t<-5.6`)
3. **結論**：**PIT 不會創造新的 alt-data niche；TLT 的 finstress 「DM positive」
   是 shift(1) 與 PIT 都保留的 marginal 現象（NFCI/ANFCI PIT vs weekly-mean 相關
   >0.98），但在 magnitude、stability、kitchen-sink 三面都無法通過 Paper 4
   triple-gate。**

對 Paper 4 narrative 的影響：

- **STRENGTHENS "universal native IV sufficiency"** — 新增 GLD/TLT/BTC PIT robust
  對 K1116c SPY PIT 結論的 cross-asset validation
- **不推翻** K1118 "TLT M4 是 timing / regime artifact" 的原結論（K1116b 已預告）
- 可在 Paper 4 加一段：「Publication-delay 修正的 PIT alignment 不解救 alt-data；
  TLT finstress 的 marginal DM t 在 shift(0) 與 shift(1) 兩個 PIT 變體之間不穩定
  (+3.74 → +2.00)，確認是 regime artifact 而非結構性 signal。」

## 5. Limitations

1. **Weekly AR(1)+IV baseline**（非 HAR-RV daily） — brief 原描述 HAR-RV(1/5/22)，
   但這是 daily-native spec；為保持與 K1116c/K1118 cells 可比，本實驗採 weekly
   AR(1)+IV（K1118 baseline）。daily HAR-RV cross-asset PIT 是獨立 follow-up。
2. **PIT 資料來自 revision-corrected fredgraph**（K1116c 已討論）— ALFRED vintage
   需 FRED API key，目前不可得。但 revision-corrected 是 vintage 的 smoother
   upper bound（K1116c §2 論證）— 若 revision-corrected PIT NULL，vintage PIT 也 NULL
3. **BTC IV 是 RV30 proxy**（yfinance 無 DVOL/BVOL） — 與 K1118 同樣限制
4. **170 weeks common OOS** — 對 regime-conditional 檢定 underpowered
5. **Kupiec / VaR 檢定未加入** — brief 提及但 HAR-RV weekly spec 下無 VaR
   application；保留給 follow-up

## 6. 檔案

- `k1116f.py` — 實驗主腳本
- `k1116f_results.json` — 完整結果（per asset × 3 variants × 5 specs）
- `k1116f_dm_heatmap.png` — 3-asset × 4-spec × 3-variant DM t heatmap
- `k1116f_qlike_ratio.png` — alt-spec QLIKE / IV baseline ratio bar chart
- `run.log` — 執行 log
- `README.md` — 本檔

## 7. References

- Baker, Bloom, Davis (2016) QJE — EPU index
- Brave, Butters (2011) Chicago Fed Letter 286 — NFCI Wed 10:30 CT release
- Kliesen, Smith (2010) — STLFSI
- Croushore, Stark (2001) J Econometrics — vintage data importance
- Patton (2011) JoE — QLIKE proxy-robust loss
- Harvey, Leybourne, Newbold (1997) IJF — HLN DM correction
- Harvey (2016) RFS — |t|>3 multiple-testing threshold
- Liu (2021) — BTC retail sentiment (K1118 H3 motivator)
- K1116 / K1116b / K1116c — SPY publication-delay + PIT series
- K1118 — cross-asset shift(1) baseline being extended here
- K1121 — daily alt-data allocation NULL

## 8. Worktree 紀律

- 所有產出僅在 `experiments/k1116f/` 內
- 未修改 `storage/**`、`paper/**`、`research_program.md` 或任何共享 state
- 主線程負責 knowledge / experience / 文章寫入
