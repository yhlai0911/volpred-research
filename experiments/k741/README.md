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

### 為什麼是 2×2 factorial，不是兩臂對照

修正日曆會**同時改兩件事**：(1) 日期來源、(2) release→trading-day 對應規則。
原版對應規則遇到 release 落在休市日時會往回取到**發布前一個交易日**（lookahead），
影響 5 個 Good Friday（2010-04-02、2012-04-06、2015-04-03、2021-04-02、2023-04-07）。

本檔第一版把兩者混在一起報成「純日期效應」—— **那是錯的**，由 Codex review
（2026-07-19, verdict FAIL）抓出。現改為完整 2×2，日期效應只在**固定 mapper** 下引用。

**關鍵且反直覺的結果**：在 pooled overall 統計上，修日曆幾乎沒動（1.1487 → 1.1510），
真正推動數字的是**修 lookahead**；而且在正確 mapper 下，官方日曆反而讓 pooled ratio **變小**
（1.1779 → 1.1631）。但在 **regime 層次**日期修正就很關鍵：High-VIX cell 從
proxy 的 1.010（等於沒有 absorption）掉到 official 的 0.936 —— 那正是 absorption 主張所依賴的 cell。

### 另一個被抓到的缺陷：樣本窗洩漏

原版 frame 從 2009-12-01 建起（VIX_prev warm-up），卻把**整個 frame** 當 control，
讓 21 個 2009-12 的日子進了論文宣稱的「2010-01 起」樣本。這在決策邊界上是決定性的：

| 估計起點 | ratio | p |
|---|---|---|
| 2009-12-01（原版行為） | 1.16495 | **0.0479** |
| **2010-01-01（修正）** | **1.16307** | **0.0506** |

洩漏本身就是「5% 顯著」與「不顯著」的全部差距。k904 原本就切對，不受影響。

### 結論：方向不變，但**不可**上調顯著性措辭

| 統計量 | 論文原值 | canonical | 變化 |
|---|---|---|---|
| Overall ratio vs all | 1.14 (p=0.081) | **1.16 (p=0.051)** | 仍為 10% marginal，**未跨 5%** |
| Overall ratio vs Friday | 1.16 (p=0.061) | **1.19 (p=0.034)** | 5% 顯著 |
| Low (V<15) | 1.24 (p=0.069, n=62) | **1.31 (p=0.009, n=63)** | ⚑⚑ 升到 1% 顯著 |
| Medium (15–20) | 1.30 (p=0.009, n=78) | **1.23 (p=0.027, n=76)** | ⚑ 1% → 5%（仍顯著） |
| Elevated (20–25) | 1.18 (p=0.279) | **1.19 (p=0.254)** | 兩者皆不顯著 |
| High (V≥25) | 0.95 (p=0.777) | **0.94 (p=0.731)** | 兩者皆不顯著 |

**沒有任何符號翻轉**，且 regime 梯度變成**單調遞減**（1.31 → 1.23 → 1.19 → 0.94），
比原本 Medium 高於 Low 的凸起更符合 absorption 假說。
→ 論文 NFP 小節**不需降級或移除**；`main_v3.tex` 已更新，pooled 措辭維持
「marginal at the 10% level」（本檔第一版誤寫成 5% 顯著，已撤回）。

k904 獨立佐證（不同視窗、Welch）：overall 1.160 (p=0.042)、Low 1.305、High 0.935。
注意 k741 (Student, p=0.0506) 與 k904 (Welch, p=0.0424) **跨在 5% 兩側**——
5% 的判定是 spec-dependent，這也是 pooled 措辭要保守的理由。

### 另外發現的兩個獨立缺陷（非 proxy 造成）

1. **論文表格的 ratio / t / p 三欄無法追溯到任何實驗**。重現能逐位對上 `n` 與 `mean|r|`，
   但對不上 ratio/t/p（Medium 論文 1.30/2.69/0.009，實際 1.175/1.72/0.090）。
   掃過 8 種 spec 變體皆不符。根因：`reproduce.py` 只綁 regime 的 `n` 與 `mean_abs`，
   **從未綁 ratio/t/p**。已修：canonical JSON 存下這些值，`reproduce.py` 改綁 canonical
   並補齊每個 regime 六欄（gate 112/112, 100%, green）。
2. **論文把這些檢定標成 "Welch's t-tests"，但 k741 用的是 Student's**
   （`stats.ttest_ind` 預設 `equal_var=True`）。已在 tex 改為 "two-sample $t$-tests"。

### ⚠️ 未完成：Codex 尚未複審

第一輪 Codex review 對上述缺陷判 **FAIL**；修正後的腳本**尚未重審**。
依 `.claude/rules/experiments.md`，merge 需要一份 pin 住現行 sha 的 `review_verdict.json`
→ **合併前必須重跑 Codex review**。

細節、2×2 全表與 feed 回溯建議見 `nfp_canonical_vs_proxy_comparison.md`。
