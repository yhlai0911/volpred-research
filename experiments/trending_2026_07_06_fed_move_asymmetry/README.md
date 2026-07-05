# trending_2026_07_06_fed_move_asymmetry

## 主題
聯準會「長期高利率（higher-for-longer）」訊號下，美債隱含波動率（MOVE 指數）對利率
**上行 vs 下行的非對稱定價**。

## 差異化（與既有文章區隔）
- `trending_2026_06_12_fed_move_vix`：MOVE/VIX 跨資產比值不同步（event_window）
- `article_2026_06_22_move_vix_resonance`：MOVE-VIX 滾動相關/共振（correlation）
- **本篇（regime_signal + vol_term_structure）**：MOVE 對殖利率方向的條件反應非對稱，
  且非對稱不來自殖利率單向多動（半變異數近對稱），是純粹的波動率定價非對稱。
  已過 `check_arc_dedup.py`（exit 0，narrative_axis 不同）。

## 資料
- Yahoo Finance `^MOVE`（ICE BofA MOVE Index）、`^TNX`（CBOE 10Y Treasury yield ×10）
- 期間 2010-01-05 ~ 2026-07-02，4,065 交易日（上行 1,968 / 下行 2,032）

## 方法
1. 同日條件化：以 10Y 殖利率日變動方向分組，比較當日 MOVE 日變動 %（Welch t-test）
2. Magnitude 控制斜率：MOVE 日變動 對 |Δ殖利率(bp)| 的 OLS 斜率，分上/下行日
3. 殖利率 realized semivariance ratio（檢驗非對稱是否來自殖利率單向多動）
4. 近 90 交易日 regime 對照
5. Bootstrap 5000 次 95% CI（seed=20260706）

## 關鍵結果
| 指標 | 上行日 | 下行日 | 差異 |
|---|---:|---:|---:|
| MOVE 當日平均變動 | +0.510% | −0.280% | +0.79pp（t=5.52, p=3.6e-08） |
| 每 bp 斜率（控制幅度） | 4.01%/bp | 2.74%/bp | 比值 1.465 |
| 殖利率半變異數 | 604 bp² | 582 bp² | 比值 1.038（近對稱） |
| 近 90 日均變動 | +2.15% | −2.39% | +4.53pp（regime 放大） |

Bootstrap 95% CI（上−下）= [+0.50, +1.07] pp，不含 0。

## 結論
債市波動率對「利率往上」的反應顯著大於「利率往下」，即使控制殖利率變動幅度後仍成立
（1.465 倍）；殖利率本身上下行幅度近乎對稱 → 這是**波動率定價的非對稱**，非資料生成
過程的偏態。近 90 日此非對稱放大近 6 倍，與 higher-for-longer regime 一致。

## 誠實聲明
同期（contemporaneous）描述性統計，非 lagged 可交易預測訊號；文章不宣稱 forecast /
交易 alpha。seed 固定、bootstrap CI 報告。

## 產出
- `asymmetry.py`、`results.json`、`fig_move_asymmetry.png`
- 文章 slug：見 feed（trending_repost，VolPred 直接 published；FB 走 Ivan Lai）
