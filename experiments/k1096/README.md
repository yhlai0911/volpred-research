# K1096: BTC Regime-Switching A4f — Can State-Dependent VIX Loading Rescue Crypto?

[提出: 用戶 (via K1096 brief), 執行: Claude]

## 1. 計劃與動機

K1089 在 BTC 上測試 A4f-VIX 得到令人困惑的結果：
- Full OOS：DM t = +1.13（NS，但方向對）
- **High-VIX bucket [25,40)：DM t = -2.91（wrong direction）**

亦即當股市最恐慌時，把 VIX 寫進 BTC 的 long-run component 反而**傷害**預測。
這與 K1025 / Paper 6 的發現一致：BTC-equity 的 fear contagion 是**非對稱**的—
crypto 在股市高壓期**脫鉤（decouple）**。

**研究問題**：如果 VIX loading 的傷害集中在 high-VIX state，用 regime-switching
「在該關掉的時候關掉」能否救回 BTC 上 A4f 的優勢？

## 2. 問題描述

設計 3 種 regime-switching 變體對比 K1089 的 A4f-VIX baseline：

| Model | Specification |
|-------|---------------|
| M1 | GJR-GARCH(1,1) baseline |
| M2 | A4f-VIX：τ = θ₀ + θ₁·VIX² (K1089) |
| M3 | Reg-VIX-OFF-HighVIX：τ = θ₀ + θ₁·VIX²·**1(VIX<25)** |
| M4 | Reg-VIX-ON-HighCorr：τ = θ₀ + θ₁·VIX²·**1(|corr60d|>0.3)** |
| M5 | Adaptive：τ = θ₀ + θ₁·VIX²·**|corr60d|** |

## 3. 方法

- 資料：BTC-USD、SPY、^VIX 日頻收盤價（yfinance，2014-11-17 ~ 2026-04-11，n=4164）
- 24/7 BTC 日曆；SPY 與 VIX 對 BTC 日曆 forward-fill
- 60-day rolling 相關係數 corr(BTC ret, SPY ret)
- Rolling GARCH：1000-day train，63-day refit，49 次 refit
- 3 個 OOS 窗口（non-overlapping）：
  - Early_2018Bear（2018-01-01 ~ 2020-02-14，n=775）
  - Middle_COVID_Luna（2020-02-15 ~ 2022-10-31，n=990）
  - Late_FTX_Rally（2022-11-01 ~ 2026-04-11，n=1258）
- 評估：QLIKE on r²（Patton 2011）+ Newey-West HAC DM test（Harvey 2016 |t|>3.0）+ Spearman + 1000-rep block bootstrap CI
- 所有 regime 指標使用 **lagged 資訊（t-1）**，無 lookahead
- 隨機種子：42

### 非 Lookahead 檢查（代碼結構）
- `vix_lag_series[1:] = vix[:-1]`（VIX 提前 1 天）
- `corr_lag_series[1:] = corr60[:-1]`（相關係數提前 1 天）
- 預測 day t 使用 `r_prev = ret[abs_idx - 1]`、`v_lag = vix[abs_idx - 1]`、
  `w_*_t = w_*[abs_idx]`（其中 w_* 已由 lagged series 建構）

## 4. 結果（Full OOS n=3023, 2018-2026）

### 4.1 所有 regime 模型都 FAIL vs GJR

| Model | QLIKE diff% | DM t | Harvey |
|-------|-------------|------|--------|
| A4f-VIX (baseline K1089) | -0.23% | **+1.13** | FAIL |
| Reg-VIX-OFF-HighVIX | -0.15% | +0.82 | FAIL |
| Reg-VIX-ON-HighCorr | -0.20% | +1.19 | FAIL |
| Adaptive |corr| | +0.12% | **-0.92** | FAIL (worse than GJR) |

**H1 / H2 / H3**：FAIL——沒有一個 regime 變體達到 Harvey |t|>3。
**H4**：FAIL——所有 regime 模型相對 pure A4f-VIX 的 DM t 都是負數（變差）。

### 4.2 High-VIX 傷害確實被消除（H5 部分 PASS）

VIX bucket [25, 40) 分析（n=463）：

| Model | QLIKE diff% | DM t | 說明 |
|-------|-------------|------|------|
| A4f-VIX（K1089） | +1.10% | **-2.91** | 傷害基線（loss 增加） |
| Reg-VIX-OFF | +0.12% | -0.54 | **傷害消失** |
| Reg-VIX-ON-HighCorr | +0.02% | -0.10 | **傷害消失** |
| Adaptive |corr| | +1.52% | **-3.50** | **傷害更嚴重** |

關掉 high-VIX state 的 VIX loading（M3）或只在 high-correlation 下打開（M4），
確實把 K1089 在 High-VIX 的 -2.91 damage 消除到接近 0。但 adaptive smooth
weighting（M5）反而讓 high-VIX 傷害惡化到 -3.50。

### 4.3 Per-window 發現

**Middle_COVID_Luna（高 corr 時期，corr mean=0.324）**：
- Adaptive：DM t = **-3.26**（Harvey PASS **wrong direction**）
- A4f-VIX：DM t = -0.63（NS）

**Late_FTX_Rally**：
- A4f-VIX：DM t = **+2.29**（接近但未過 Harvey 門檻）
- 所有 regime 變體都比 pure VIX 差

## 5. 結論

### 主要結論：**BTC A4f 的 crypto boundary 是結構性的，regime switching 無法救回**

1. **沒有任何 regime 變體 PASS Harvey |t|>3 vs GJR**（全部 FAIL）
2. **沒有任何 regime 變體改善 pure A4f-VIX**（relative DM t 全部 ≤ 0）
3. **Reg-VIX-OFF 和 Reg-VIX-ON-HighCorr 局部消除了 High-VIX damage**
   （從 t=-2.91 降到 -0.54 / -0.10），但**整體樣本優勢沒有浮現**
4. **Adaptive |corr| weighting 反而惡化**（-3.50 in High-VIX）—
   smooth weighting 把傷害保留而非消除

### 對 Paper 6 + Paper 9 的影響

**Null result（如預期）**：
- K1089 已顯示 crypto 是 A4f asset-matched principle 的 boundary case
- K1096 進一步證實：即使用「把 VIX 在傷害期關掉」這類狀態切換，也無法把 BTC
  拉進 PASS asset class
- Paper 9 的 asset-matched IV 結論維持：Equity、Gold、Oil PASS；Bonds、Crypto
  都是 boundary cases（結構性限制）
- Paper 6 的 crypto fear asymmetry 結論得到**間接證實**：high-VIX + high-corr
  state 正是 BTC decoupling 最明顯的時候，VIX loading 在該處最無用

### 局限

- 只測試了 60-day 相關係數與 0.3/25 兩個 threshold；可擴充為 Markov-switching
  hidden state
- 只用了 BTC-USD；ETH/SOL/其他 crypto 未驗證
- Regime 指標都是 backward-looking（過去 60 天 corr），未嘗試 forward-looking
  indicator（如 implied corr）
- `adaptive` 的惡化可能是參數化問題（multiplying VIX² by small weight 讓 long-run
  component 退化，但 MIDAS 結構未同時調整）

## 6. 衍生研究方向

1. **K1097** 候選：Markov-switching GARCH（HMM state-dependent GJR parameters）
   for BTC，看是否比 deterministic regime switching 好
2. **K1098** 候選：Crypto-native implied vol（DVOL / BVIV via Deribit API 或
   Coinglass）取代 VIX 作為 cross-asset fear proxy
3. **K1099** 候選：Aggregating decision — 看 BTC vol 最佳預測器是否應該切換到
   HAR-RV + crypto-native 因子，完全放棄 VIX

## 7. 檔案清單

- `k1096.py` — 主腳本（800 行）
- `k1096_results.json` — 完整結果 + forecasts + refit_log（873 KB）
- `k1096_regime_dm.png` — 5 models full-OOS DM t 比較
- `k1096_correlation_ts.png` — BTC-SPY rolling 60d corr + VIX 時間序列
- `k1096_theta1_by_regime.png` — θ₁ 在 49 次 refit 的演化
- `k1096_vix_bucket_rescue.png` — VIX bucket DM t（展示 high-VIX 傷害是否消失）
- `make_charts.py` — 繪圖腳本

## 8. 統計門檻與參考文獻

- Harvey, Leybourne & Newbold (2016). MSE equality testing. |t|>3.0 threshold
- Patton (2011). Volatility forecast comparison. JoE 160:246-256. QLIKE on r²
- Engle, Ghysels & Sohn (2013). RES 95(3):776-797. GARCH-MIDAS origin
- Baur & Dimpfl (2018). Asymmetric volatility in cryptocurrencies. EL
- Hamilton (1989). Econometrica 57(2):357-384. Regime-switching
- K1089 BTC A4f-VIX baseline（NS, high-VIX wrong direction）
- K1025 Paper 6 crypto fear channel asymmetry

## 9. 執行資訊

- 執行時間：228 秒（49 次 refit × 5 models × 1000-day training）
- 隨機種子：42
- Python 3.12 + numpy + scipy + numba + yfinance + matplotlib
