# K1100g_d2 — OOS Validation of night→day Predictive Power in TAIFEX PRG

[提出: Claude 自主研究 / 執行: Claude worktree agent-k1100g-d2]

## 1. 動機

K1100g_d1 以 TAIFEX TX 2017-2021 全樣本建立 4+1 個 PRG 模型，發現：

- **In-sample LRT M4 vs M2** (day + night exog vs day only)：χ²=12.48, p=0.0004
- In-sample HLN-DM：t=1.07（僅 directional）
- 被提為 Paper 3「PRG 成功來自 Taiwan session 微結構」的 reframe anchor。

但 in-sample fit 不等於 predictive。reviewer 會問：
**這個 night→day 預測效應能 out-of-sample 保持嗎？還是 in-sample 多擬合？**

K1100g_d2 用嚴格的 expanding-window OOS 直接回答。

## 2. 設計

### Train / Test 分割

| 期間 | 範圍 | N 樣本 |
|------|------|-------|
| Train (initial) | 2017-05-16 ~ 2019-12-31 | 613 |
| Test (OOS) | 2020-01-02 ~ 2021-12-30 | 464 |

注：K1100g_d1 aligned sample 從 2017-05-16 開始（而非 2017-01-01）因為早期 2017 許多 file 缺夜盤 tick。這也是 K1100g_d1 report 的實際 aligned 樣本起點。

### 模型（限縮至 2 個關鍵）

| 模型 | Target | 自由參數 | Exog | 資訊集 |
|-----|--------|---------|------|-------|
| **M_null** (baseline) | r²_day | 9 | — | K1100g_d1 的 M2 spec |
| **M_full** | r²_day | 10 | r_night[t]² (contemp) | K1100g_d1 的 M4 spec |

PRG kernel 與 K1100g_d1 一致：τ×g multiplicative，E[g]=1 識別化。
Information set：night_t 結束 05:00 早於 day_t 開盤 08:45 → contemporaneous exog 合法。

### Refit 策略（expanding window）

- `REFIT_EVERY=5` 個交易日 refit 一次（週頻 refit）
- 每次 refit 用 **strictly pre-t** 資料 `r[0:t]`（無 lookahead）
- Refit 之間參數固定，但 exog r_night[t]² 每日更新
- 共 93 次 refit × 2 模型 = 186 次 L-BFGS-B estimate
- Warm-start：每次 refit 把上次參數當第一個 restart

### 假設

| # | 假設 | 門檻 | 依據 |
|---|------|-----|------|
| **H1** (Primary) | OOS LRT χ² > 7.88 | p<0.005 | 嚴於 in-sample 0.05 |
| **H2** (Robustness) | OOS DM-HLN \|t\| > 2 | directional | Harvey 小樣本 |
| **H3** (Magnitude) | OOS QLIKE 改善 > 1% | meaningful | effect size |
| **H4** (Stability) | 2020 + 2021 各自 PASS H3 | 分段穩定 | 排除 COVID 單點驅動 |

## 3. 結果

### 3.1 全樣本 OOS

| 指標 | M_null | M_full | 差異 |
|------|--------|--------|------|
| OOS log-lik 總和 | 1533.08 | 1531.19 | **-1.89**（full 更差） |
| OOS QLIKE 均值 | 1.6167 | 1.6245 | **+0.48%**（full 更差） |

### 3.2 假設檢定

| # | 假設 | 結果 | PASS? |
|---|------|------|------|
| **H1** | OOS LRT χ² > 7.88 | χ²=**0.000**, p=1.00（ll_diff<0 被 clamp） | ✗ FAIL |
| **H2** | OOS DM-HLN \|t\| > 2 | t=**-0.212**, p=0.832（方向反轉） | ✗ FAIL |
| **H3** | QLIKE 改善 > 1% | **-0.48%** | ✗ FAIL |
| **H4** | 2020+2021 各 PASS | 2020:-0.98%, 2021:+0.10% | ✗ FAIL |

### 3.3 對比 in-sample

| 指標 | In-sample (K1100g_d1) | OOS (K1100g_d2) | Δ |
|------|------------------|-------------|---|
| LRT χ² | 12.48（p=0.0004） | **0.00**（p=1.00） | **-12.5** |
| DM-HLN t | +1.07（p=0.28） | **-0.21**（p=0.83） | 方向反轉 |
| QLIKE improv | — | **-0.48%**（惡化） | — |

**4/4 假設全部 FAIL。** OOS 效果完全消失，甚至方向反轉。

## 4. Paper 3 Reframe Verdict

```
FAIL — OOS worse than baseline; in-sample was data mining
```

**K1100g_d1 的 χ²=12.48, p=0.0004 是 spurious finding。**
- In-sample：night_t² 的係數 (`xn=0.039`) 看似顯著捕捉 day 波動，但這是 overfit 的自由參數
- OOS：在 2020-2021 的真實 forecast 中，加入 night exog 反而讓 forecast 變差
- 沒有一個 2 年子期間（2020 或 2021）顯示效應成立

### 對 Paper 3 的影響

1. **原 anchor 推翻**：不能用「night→day asymmetric prediction」作為 reframe narrative——這不是 OOS-robust。
2. **K1100g 的 1.586 ratio 更加可疑**：K1100g 本身是 cache mask-bug 的產物（error_log 已記錄）。現在連「清理後的 night→day 預測」都 fail，整個「夜盤資訊優勢」敘事需要重新考慮。
3. **Paper 3 的 reframe 需要另找 anchor**，例如：
   - 跨市場複製（SPY、N225 做類似 decomposition，看台灣是否真的特殊）
   - 換 exog（不是 night r² 而是 overnight gap、5-min RV、VIX）
   - 結構性差異（TX 的合約轉倉、流動性時段分布）

## 5. 限制

1. **N=464 OOS** 對 asymptotic chi-square 精度偏小；OOS 的 `2*(LL_diff)` 是近似 chi² 而非嚴格分配
2. **單一市場（TAIFEX）**——但既然本市場都 fail，跨市場複製不具迫切性
3. **COVID 2020** 是非典型波動 regime；H4 sub-period 檢驗已直接處理這個擔憂
4. **Refit 頻率=5 天**（週頻）。每日 refit 會更嚴格但 ~5× compute；穩健性未在此測（d3 候選）
5. **Active-contract 篩選**（每日用 volume argmax 選合約月）在轉倉日前後有微細差異（K1100g_d1 Codex MED，未改）
6. **早期 2017**（2017-01 ~ 2017-05）aligned sample 為空——因為 TAIFEX raw 檔在那段時期缺夜盤 tick。這對 test 期沒有影響，但 train 期比原預期少了 ~5 個月

## 6. 衍生的 3 個新方向

1. **K1100g_d3（PRG 結構性重檢）**：既然 night→day 不 robust，檢查 M2 (day-only) 本身相對於 baseline GJR 的優勢是否 OOS-robust。Paper 3 如果要保 PRG 敘事，需要證明**某個 PRG component** 是 OOS 有效的。

2. **K1100g_d4（跨市場 decomposition）**：把同樣的 day/night PRG decomposition apply 到 SPY（pre-market + regular session）、N225（morning + afternoon + overnight）。看哪個市場的 cross-session prediction 真的 OOS-robust——可能都不 robust，這本身是重要發現。

3. **K1100g_d5（Overnight gap vs night session return）**：K1100g 用的是 overnight gap σ（13:45 → next 08:45），K1100g_d1 用的是 night session open→close σ（15:00 → 05:00）。兩者資訊集不同。用 **overnight gap²** 當 exog（而非 night session r²）再做一次 OOS，看是否 gap 才是真正的 leading indicator。

## 7. 檔案

- `k1100g_d2.py` — 實驗腳本（expanding-window OOS + LRT + DM）
- `k1100g_d2_results.json` — 完整結果 JSON
- `firm_oos_decomposition.csv` — OOS 期間每日 forecast + loss
- `data/_cache_taifex_sessions_2017-2021.parquet` — 從 K1100g_d1 複製的 clean session cache（raw-tick rebuild，不是 K1100g buggy cache）
- `k1100g_d2_oos_lrt_cumulative.png` — 累積 OOS LRT χ² 時序
- `k1100g_d2_qlike_improvement.png` — OOS QLIKE 差異時序（日 + 30 天滾動）
- `k1100g_d2_covid_recovery_split.png` — 2020 vs 2021 子期間對照

## 8. 對 error_log 的新教訓

- **in-sample LRT p<0.001 仍可能是 data mining**（不只 Sharpe 2x baseline）——特別是 nested models 加自由參數時
- **in-sample DM HLN t=1.07 + LRT p=0.0004** 的組合是典型警訊：LRT 大但 DM 小 = 自由度提升比 predictive gain 大
- OOS 驗證不可省略，尤其當用 in-sample result 當 paper anchor 時
- **即使 exog 的資訊集合法（night_t<day_t）也不保證 predictive**——合法性是必要但非充分

## 9. Seed 與可重現性

- `np.random.seed(42)` + `np.random.default_rng(42)`
- `fit_prg()` 內部 `np.random.default_rng(42)` 建 restart 初值
- L-BFGS-B 為 deterministic optimizer
- Warm-start 在 trial=0 固定使用上次 params
- 重跑應得到完全相同結果

## 10. 關鍵數字一覽

```
OOS period: 2020-01-02 .. 2021-12-30 (n=464)
Refits:     93 (weekly expanding window)

          M_null    M_full    Δ
LL sum    1533.08   1531.19   -1.89
QLIKE     1.6167    1.6245    +0.48% (worse)

H1 LRT chi2 = 0.000 (p=1.00)   [need >7.88]   FAIL
H2 DM-HLN t = -0.21 (p=0.83)   [need |t|>2]   FAIL
H3 QLIKE    = -0.48%           [need >1%]     FAIL
H4 2020     = -0.98%           [need >1%]     FAIL
H4 2021     = +0.10%           [need >1%]     FAIL

Paper 3 anchor: REJECTED as OOS-robust
```
