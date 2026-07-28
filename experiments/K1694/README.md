# K1694 — FCM 清算集中度與商品流動性風險（**Codex 審 FAIL，結果不可引用**）

## 狀態：REVIEW_FAILED（Codex round 1，2026-07-29）

`storage/ops/codex_reviews/k1694_verdict.md` 已回，**`VERDICT: FAIL`**。因此：

- 不得寫進 `storage/memory/knowledge.json`（審沒過就寫 = 污染知識庫）
- 不得據此寫 feed 文章或論文段落
- 本檔以下所有數字**一律不可引用**，包含 `K1694_results.json` 內的 headline CI

外部審的價值在此具體化：本次讓它跑起來的三個修正裡，有一個把 bootstrap 從「每次 replicate
都靜默變 NaN」改成活的估計路徑 —— 而 Codex 查出那條活起來的路徑估的**不是 spec1**（RHS 少了
時間趨勢 `t`、樣本多 7 列、`highvol` 被錯標），所以它產出的 CI 被冒名寫進
`primary_interaction.bootstrap_ci95`。改動越是讓結果從無到有，越需要外部審。

## 本次做了什麼（2026-07-29）

原 agent 跑不完的原因是三個缺陷，兩個直接 raise、一個靜默作廢：

1. `build_panel`：`.dt.to_timestamp(how="end").normalize()` — Series 沒有 `.normalize`，
   改 `.dt.normalize()`。
2. `panel_regression`：panel 的時間索引是 pandas `Period`，`linearmodels` 直接拒收
   （`The index on the time dimension must be either numeric or date-like`）。改用
   timestamp 索引 `month_ts`。
3. `bootstrap_interaction`：block bootstrap 把重抽的月份改標成字串 `f"B{k}"`，`PanelOLS`
   同樣拒收字串時間索引 → 每個 replicate 都 raise → 被 `except Exception: return np.nan`
   吞掉 → `boots` 全空 → `np.percentile` 在空陣列上 IndexError。改成整數 `k`，並讓
   point-estimate 路徑把 `Period` 轉 timestamp。修好後 `n_boot = 2000/2000`。

## 結果（**FAIL — 以下數字不可引用，僅供修復對照**）

| 項目 | 值 |
|---|---|
| spec1 `fcm_x_highvol` coef | 3.146e-04 |
| t (Driscoll-Kraay) | 1.55 |
| t (cluster by month) | 1.59 |
| block bootstrap point（2000 reps, by month） | 3.509e-04 |
| bootstrap 95% CI | [-2.72e-05, 7.47e-04] |
| bootstrap two-sided p | 0.074 |
| 時間序列 `hhi_x_volfrac` t | 0.54（HAC lag 6） |
| panel | 3293 可用列 / 22 商品 / 2014-02..2026-07 |

沒有證據支持「FCM 清算集中度在高波動期把小額商品交易人擠出去」。

⚠️ Codex 指出這句話**寫得過寬**：NULL 只能限定為「**負向、binary high-vol** 的 crowding-out
假說未獲支持」。連續型的 `fcm_x_rvz`（spec2）其實是**正向且顯著**（`t_DK=2.50`、month-cluster
`t=2.54`），寫成「完全沒有關聯」是錯的。修復重跑後的敘述必須照這個口徑。

⚠️ 表中「bootstrap 95% CI」那一列**不是** spec1 的 CI（見下方 FAIL 缺陷 1）。

## CFTC 發布日 lag：原始 brief 的核心設計，如何處理

`FCM_LAG_DAYS = 45` 是**人為常數**（`avail_date = month_end + 45d`），不是真實 CFTC 發布日；
離線資料裡沒有發布日欄位（`asof_file` 是資料 as-of 日，不是發布日），本班無法核對真值。

改用能離線回答的問法：這個常數是不是承重結構？`lag_sensitivity.py` 對假設 lag =
30/45/60/75/90 天重估 spec1：

| 假設 lag | n | coef | t_DK | t_cluster |
|---|---|---|---|---|
| 30d | 3315 | 2.384e-04 | 1.27 | 1.21 |
| 45d | 3293 | 3.146e-04 | 1.55 | 1.59 |
| 60d | 3271 | 2.644e-04 | 1.30 | 1.32 |
| 75d | 3271 | 2.570e-04 | 1.28 | 1.29 |
| 90d | 3271 | 2.962e-04 | 1.50 | 1.47 |

無一點達 |t| > 1.96 → **NULL 對 lag 假設不敏感**。方向上也是安全的：lookahead 只會在假設
lag *短於*真實 lag 時出現，而拉長到 90 天仍是 NULL。產出 `K1694_lag_sensitivity.json`。

這不等於「發布日已核對」。要宣稱對齊真實發布日，仍需抓 CFTC 各月報的實際上線日期。

## Codex round 1 裁決：**FAIL**（2026-07-29，全文見 `storage/ops/codex_reviews/k1694_verdict.md`）

Codex 確認 bootstrap 的橫截面重抽機制**已修好**（月份整批保留、整數標籤不撞 index、
`n_boot = 2000/2000` 真的有跑）。擋下 PASS 的是下列具體缺陷：

**1. headline CI 規格錯配（阻擋 PASS 的主因）**

bootstrap 估的不是 spec1：

| 設定 | coef |
|---|---|
| 現行 bootstrap spec/sample | 3.5093e-04 |
| 同 bootstrap sample、加回 `t` | 3.2834e-04 |
| 主 sample、不含 `t` | 3.3285e-04 |
| **真正的 spec1** | **3.1464e-04** |

- spec1 RHS 含時間趨勢 `t`（`K1694.py:472`），bootstrap RHS 沒有（`K1694.py:521`）
- 主模型 3,293 列 vs bootstrap 3,300 列 —— 主模型多要求 `rv_z` 非空
- `(s > s.median())` 對缺 RV 的列回 `False`，`highvol` 被**錯標成 0** 而非 NaN（`K1694.py:368`）

**2. bootstrap 命名不誠實**：現行是 IID month-cluster bootstrap（保留同月橫截面、破壞月間序列
相關）。要嘛改成 consecutive moving / stationary block，要嘛老實叫它 month-cluster bootstrap。

**3. partial month 未排除**：`panel_span` 寫到 `2026-07`，但該月 DCOT 只有一週、RV 只有 10 個
交易日、只有 15 個商品，且未揭露為 partial。

**4. 方法論描述與程式不符**

- `_acf_bandwidth()` 根本沒讀 `resid`（`K1694.py:421`）—— 永遠回
  `max(ceil(T^(1/3)), 4)`。這固定規則本身可辯護，但不能宣稱 bandwidth 由 residual ACF 決定。
- 檔頭宣稱「另附全落後 predictive spec」（`K1694.py:36`），**實際沒有這個 spec**。

**5. timing 不能宣稱 predictive**：`merge_asof(direction="backward")` 機械方向正確，但 FCM
availability 落在 outcome 月中、`d_nonrep` 是整月平均變化，2026-07 甚至用 7/31 當 merge key 去
配 7/15 才可得的 FCM factor。只能講 ex-post association，不能講 predictive / causal /
known-before-outcome。30–90 日 grid 只證明對 synthetic vintage shift 不敏感，不足以退休 timing
concern。

**6. limitations 漏列**：synthetic publication dates、月內 timing overlap、full-sample regime
labels、bootstrap 不保留序列相關。

**7. 缺 runtime-generated `reproduce_spec.json`**，artifact checker 仍擋。

**Codex 的最低修復要求**：讓 bootstrap 共用 spec1 完全相同的 design matrix / sample / `t`；
處理缺失 RV；決定 temporal-block 或誠實改名；排除 partial month；修正 timing 與 bandwidth 的
方法描述；重跑正式 artifacts 後再審。

診斷性好消息（Codex 唯讀重算，非正式結果）：DK bandwidth 1–24 的 spec1 t 值仍在 1.55–1.74；
排除不完整的 2026-07 後 `t_DK=1.60`、`t_cluster=1.64`。所以 bandwidth 與 partial month 目前
**看不出是 NULL 的製造者** —— 但這些敏感度尚未正式寫進可重現結果。

## 搶救經過（2026-07-19）

- 2026-07-15 09:22 台北：`K1692_K1694_starvation_dispatch` 走 compute_queue 派出 K1692/K1694
  兩個 starved 實驗（各建 registered worktree）。
- K1692 的 agent job timeout，但結果後來被 salvage 進 canonical（commit `86255ebdc`）。
- **K1694 的 agent 沒有跑完**，只留下腳本與已抓好的資料，在 worktree 裡閒置 99 小時。
- task pool 中 `K1694` 的 status 是 `succeeded`，但 `result` 是 `null` —— 那個 succeeded
  指的是「**派工**成功」而非實驗成功。這是狀態語意陷阱，不是實驗已完成的證據。
- 搶救時 `storage/knowledge.json` 沒有 K1694 條目（未污染知識庫），至今仍未寫入。

## 檔案

| 檔案 | 說明 |
|---|---|
| `K1694.py` | 分析腳本（可跑通） |
| `lag_sensitivity.py` | FCM 發布 lag 敏感度檢查 |
| `K1694_results.json` | 主結果（**Codex FAIL，不可引用**） |
| `K1694_lag_sensitivity.json` | lag 網格結果 |
| `figures/fig1_fcm_hhi_timeseries.png` | FCM HHI 時序 |
| `figures/fig2_regime_2x2.png` | 2×2 regime 對照 |
| `figures/fig3_interaction_coef.png` | 交互項係數 |
| `data/fcm_monthly.csv` | CFTC FCM customer-segregated assets 月頻（150 列） |
| `data/dcot_weekly.csv` | DCOT 週頻部位（23,056 列） |
| `data/rv_monthly.csv` | 已實現波動率月頻（5,643 列） |

## 還缺什麼

1. ~~跑通 `K1694.py`~~ ✅
2. ~~檢查 CFTC 發布日 lag 的影響~~ ✅（敏感度取代真值核對，見上）
3. ~~Codex primary-path review~~ ✅ 已回 → **FAIL**
4. 依上節 7 項缺陷修復 + 重跑正式 artifacts + Codex round 2 —— 見 task
   `k1694_codex_fail_repair_20260729`。**round 2 PASS 之前不得寫 knowledge entry**。
