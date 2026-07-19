# k741

> ✅ **已於 2026-07-19 用 canonical BLS 日曆重跑（task `assign_1238781f`）— 見下方「Canonical 重跑」段**
>
> 下面這則 proxy 污染警告仍然成立，描述的是**封存版** `k741_nfp_event_study.py` /
> `k741_nfp_event_study_results.json`。那兩個檔**維持原狀不修改**（保留可復現性）。
> 論文改引用 canonical 版。

> ⚠️ **NFP 日期用 first-Friday proxy — 結論須重驗；且此為論文引用源**
>
> 本實驗（NFP event study）用 `first_friday` 把 NFP 發布日推算成「每月第一個週五」。此 proxy 已知不可靠：對 13 個近期官方 BLS 日期驗證錯 7 個（含 2025-10 停擺幻影日）。`part_a_historical`（n_nfp=195、ratio_vs_all=1.145、ratio_vs_friday=1.165、p_vs_all=0.081、p_vs_friday=0.061 及所有 VIX-regime 細分）皆建立在污染的日期集合上。
> **重要**：`paper/volatility-absorption/main_v3.tex` 的 Table~\ref{tab:nfp} 明確以本檔 `k741_nfp_event_study_results.json .part_a_historical` 為 source，論文摘要/結果段所有 NFP 數字都來自此處 → 論文 NFP 事件證據直接受此 proxy 影響。
> 修正方向：改用 canonical `volpred.data.event_dates.nfp_release_dates` 重跑；根因見 `docs/error_log.md` 2026-07-12、knowledge `390d9784`、K528 修正案。
> （2026-07-19 first-Friday proxy 全庫 sweep 標記，assign_23b2a961）

- Experiment ID: `k741`
- Status: planning
- Created At: 2026-04-16T09:40:48.867526+00:00

## 問題描述

- 待補充

## 動機

- 待補充

## 方法

- 待補充

## 預期

- 待補充

## 結論

- 待補充

---

## Canonical 重跑（2026-07-19, task `assign_1238781f`）

### 新舊檔案關係

| 檔案 | 角色 |
|---|---|
| `k741_nfp_event_study.py` / `..._results.json` | **封存原版**，first-Friday proxy。不修改，保留原始可復現性 |
| `k741_nfp_event_study_canonical.py` / `..._canonical_results.json` | **新增**，官方 BLS 發布日曆。論文現行引用源 |
| `nfp_canonical_vs_proxy_comparison.md` | 新舊逐項對照 + 三個獨立缺陷的說明 |

Canonical 版只重跑論文引用的 Part A / Part B。原版 Part C（sector dispersion）、Part D（strategy）
未重跑 —— 已 grep 確認 `main_v3.tex` 兩者皆未引用，且需要 pinned snapshot 沒有的 sector ETF。
**若日後要發表 C/D，它們帶著同樣的污染。**

### 日期污染程度

官方來源 = FRED/ALFRED release id 50（Employment Situation），
經 `volpred.data.event_dates.nfp_release_dates`。

**195 個 proxy 事件日中 34 個（17.4%）是錯的** —— 比 sweep 原估「13 個」嚴重得多：
33 個月份日期錯（26 個是「當月 1 號剛好是週五 → BLS 其實在第二個週五發布」），
外加 1 個幻影月（2025-10 因政府停擺根本沒發布，proxy 卻把一個普通交易日當事件日）。

另外修掉一個原版的 **lookahead**：原本 date→trading-day 對應會往回找（`[nd-1d, nd+3d]` 取第一個），
遇到 release 落在休市日時會取到**發布前一個交易日**。影響 5 個 Good Friday
（2010-04-02、2012-04-06、2015-04-03、2021-04-02、2023-04-07）。canonical 版只往前對應。

### 結論：方向不變，且比污染版更乾淨

兩個 arm（proxy / canonical）跑在**同一份 pinned 價格快照**上，所以差異是純日期效應。
proxy arm 幾乎逐位重現封存 JSON（ratio 1.14497 vs 1.14481），證明重寫忠實、快照漂移可忽略。

| 統計量 | 論文原值 | canonical | 變化 |
|---|---|---|---|
| Overall ratio vs all | 1.14 (p=0.081) | **1.16 (p=0.048)** | ⚑ 10% marginal → 5% 顯著 |
| Overall ratio vs Friday | 1.16 (p=0.061) | **1.19 (p=0.033)** | ⚑ 10% marginal → 5% 顯著 |
| Low (V<15) | 1.24 (p=0.069, n=62) | **1.31 (p=0.009, n=63)** | ⚑⚑ 升到 1% 顯著 |
| Medium (15–20) | 1.30 (p=0.009, n=78) | **1.23 (p=0.026, n=76)** | ⚑ 1% → 5%（仍顯著） |
| Elevated (20–25) | 1.18 (p=0.279) | **1.20 (p=0.226)** | 兩者皆不顯著 |
| High (V≥25) | 0.95 (p=0.777) | **0.94 (p=0.731)** | 兩者皆不顯著 |

**沒有任何符號翻轉。** 修正後 regime 梯度變成**單調遞減**（1.31 → 1.23 → 1.20 → 0.94），
比原本 Medium 高於 Low 的凸起更符合 absorption 假說。整體顯著性淨改善。
→ 論文 NFP 小節**不需降級或移除**，`main_v3.tex` 已直接更新數字。

k904 `task_s4_nfp` 同步重跑（`experiments/k904/k904_task_s4_nfp_canonical.py`），
不同視窗、不同檢定（Welch）獨立得到一致答案（overall 1.162、Low 1.305、High 0.935），
是真佐證而非共用程式碼的假一致。

### 另外發現的兩個獨立缺陷（非本次 proxy 造成）

1. **論文表格的 ratio / t / p 三欄無法追溯到任何實驗**。proxy arm 能逐位重現 `n` 與 `mean|r|`，
   但重現不出論文的 ratio/t/p（Medium 論文 1.30/2.69/0.009，實際 1.181/1.77/0.078）。
   掃過 8 種 spec 變體皆不符。根因：`reproduce.py` 只綁定 regime 的 `n` 與 `mean_abs`，
   **從未綁定 ratio/t/p**，所以這三欄從來沒被復現檢查覆蓋過。canonical JSON 已把它們寫進檔案，
   建議主線程補上 binding。
2. **論文把這些檢定標成 "Welch's t-tests"，但 k741 用的是 Student's**
   （`stats.ttest_ind` 預設 `equal_var=True`）。已在 tex 改為 "two-sample $t$-tests"。

細節與 feed 回溯建議見 `nfp_canonical_vs_proxy_comparison.md`。
