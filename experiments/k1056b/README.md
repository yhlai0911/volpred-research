# K1056b: A4f Tau-Alignment Fix Refit

**[提出: Codex 24h review follow-up, 執行: Codex]**

## 動機

K1056 的原始 A4f 遞推把 `u_{t-1}` 寫成 `r_{t-1} / sqrt(tau_t)`。  
Codex 審查指出，若模型定義為：

- `tau_t = theta0 + theta1 * VIX_{t-1}^2`
- `sigma_t^2 = tau_t * g_t`

則狀態更新應改為：

1. 用 `tau_{t-1}` 標準化 `r_{t-1}` 得到 `u_{t-1}`
2. 更新 `g_t`
3. 再用 `tau_t` 組合 `sigma_t^2 = tau_t * g_t`

本 follow-up 重新跑完整 K1056 協定，檢驗修正後是否只造成小幅漂移，或足以改變文章 claim。

## 方法

- **資料**：`paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv`
- **樣本期間**：2005-01-04 至 2026-04-10，`n=5350`
- **OOS**：2015-01-01 起，raw `n_oos=2834`，有效 `n_valid=2828`
- **模型**：A4f-VIX² vs GJR-GARCH(1,1)
- **Rolling window**：`w=2000`
- **Refit**：每 `63` 個交易日一次，共 `45` 次
- **評估**：QLIKE on `r²`、DM test、5 子期間、4 個 VIX bucket、252-day rolling DM
- **隨機 seed**：42

## 核心結果

### Full OOS

| 指標 | K1056 原版 | K1056b 修正後 | 差異 |
|---|---:|---:|---:|
| QLIKE improvement | 6.274% | 5.767% | -0.508 pct-pt |
| DM t-stat | -6.594 | -5.437 | +1.157 |
| 有效 OOS 樣本 | 2828 | 2828 | 0 |

結論：**A4f 仍然顯著優於 GJR，但優勢幅度比原版縮小。**

### 五個子期間

| 子期間 | K1056 原版改善 | K1056b 改善 | 勝負是否改變 |
|---|---:|---:|---|
| P1 Pre-COVID | 6.469% | 6.516% | 不變，A4f 勝 |
| P2 COVID | 8.431% | 6.357% | 不變，A4f 勝 |
| P3 Post-COVID | 5.737% | 5.098% | 不變，A4f 勝 |
| P4 Rate Hike | 3.403% | 3.417% | 不變，A4f 勝 |
| P5 Recent | 6.479% | 5.345% | 不變，A4f 勝 |

- **方向性結論保留**：A4f 仍為 `5/5` 子期間全勝
- **binomial p**：仍為 `0.03125`
- **顯著性縮弱**：個別達 `|t|>3` 的子期間由 `3/5` 降為 `1/5`

### VIX bucket

| VIX bucket | K1056 原版改善 | K1056b 改善 | 方向是否改變 |
|---|---:|---:|---|
| Low `<15` | 8.972% | 8.772% | 不變，A4f 勝 |
| Normal `15-25` | 0.966% | -0.068% | **翻轉，GJR 微幅勝** |
| High `25-35` | 13.653% | 13.656% | 不變，A4f 勝 |
| Crisis `>35` | 25.925% | 27.677% | 不變，A4f 勝 |

結論：**原文章「Normal bucket +1.0%」不再成立。** 修正後中等 VIX 區間基本打平，且數值略偏向 GJR。

### 252-day rolling DM

| 指標 | K1056 原版 | K1056b 修正後 |
|---|---:|---:|
| `% windows A4f better` | 100.0% | 97.55% |
| `max rolling DM t` | -0.117 | 0.834 |

結論：**原文章「100% A4f better, no GJR-leading window」不再成立。**  
修正後仍是強優勢，但存在少數 rolling window 由 GJR 領先。

### theta1 穩定性

- refit 次數：`45`
- **45/45 theta1 > 0**
- `theta1` CV：`1.058`

結論：`theta1` 全正這條 claim 仍成立，而且比 K1056 原版 `CV=4.75` 更穩定。

## 對原文章的影響

K1056b 顯示 tau-alignment bug **不是純技術性小修**。以下 claim 仍可保留：

1. `5/5` sub-period A4f 全勝
2. full OOS A4f 仍優於 GJR，且 DM 顯著
3. `theta1` 45 次 refit 全正

以下 claim 需要修正：

1. full OOS 數字應由 `6.27%, t=-6.59` 改為 `5.77%, t=-5.44`
2. VIX Normal bucket 不應再寫成 `+1.0%`，修正後為 `-0.07%`
3. rolling 252-day 不應再寫成 `100% A4f better / no GJR-leading window`
4. 個別子期間顯著性敘事需降溫，因為 `|t|>3` 只剩 `1/5`

## 結論

K1056 的**方向性 robustness** 沒有被推翻，但 **數值 claim 明顯需要更正**。  
最準確的表述應是：

- A4f 跨 5 個子期間仍然全面勝出
- 全 OOS 優勢仍顯著，但幅度較原版小
- 中等 VIX bucket 並沒有穩定優勢
- rolling window 優勢很強，但不是 100%

## 檔案

| 檔案 | 說明 |
|---|---|
| `k1056b.py` | 修正 tau-alignment 的完整 refit 腳本 |
| `k1056b_results.json` | 新結果與對 K1056 的比較 |
| `k1056b_subperiod_dm.png` | 子期間 DM 圖 |
| `k1056b_theta1_evolution.png` | theta1 演化圖 |
| `k1056b_qlike_improvement.png` | 子期間與 VIX bucket 改善圖 |
| `k1056b_rolling_dm.png` | rolling DM 圖 |
