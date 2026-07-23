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

| 估計起點 | ratio | p (Welch, headline) | p (Student) |
|---|---|---|---|
| 2009-12-01（原版行為） | 1.16495 | 0.0374 | **0.0479** |
| **2010-01-01（修正）** | **1.16307** | **0.0394** | **0.0506** |

樣本數影響很小（ratio 只動 0.002），但**在 Student 變體下這個洩漏剛好就是「5% 顯著」與
「不顯著」的全部差距**（0.0479 → 0.0506）。改用 Welch headline 後兩者都在 5% 內
（0.0374 → 0.0394），所以這個「決定性」是 variant-dependent 的 —— 本節第一版寫成無條件
決定性，已更正。無論哪個變體，切對窗口都是對的，理由是標籤誠實而不是它換來的顯著性。
k904 原本就切對，不受影響。

### 結論：方向不變，但**不可**上調顯著性措辭

headline 檢定變體 = **Welch**（見下節「檢定變體」）。下表 canonical 欄為 Welch 值。

| 統計量 | 論文原值 | canonical (Welch) | 變化 |
|---|---|---|---|
| Overall ratio vs all | 1.14 (p=0.081) | **1.16 (p=0.039)** | 名目跨 5%，但 Student 下 p=0.051 → **borderline，不可宣稱穩健** |
| Overall ratio vs Friday | 1.16 (p=0.061) | **1.19 (p=0.036)** | 5% 顯著 |
| Low (V<15) | 1.24 (p=0.069, n=62) | **1.31 (p=0.026, n=63)** | 未校正 5% 顯著；**Holm 後 0.104，不顯著** |
| Medium (15–20) | 1.30 (p=0.009, n=78) | **1.23 (p=0.029, n=76)** | 未校正 5% 顯著；**Holm 後 0.104，不顯著** |
| Elevated (20–25) | 1.18 (p=0.279) | **1.19 (p=0.266)** | 兩者皆不顯著（Holm 0.533） |
| High (V≥25) | 0.95 (p=0.777) | **0.94 (p=0.707)** | 兩者皆不顯著（Holm 0.707） |

**沒有任何符號翻轉**，且 regime 梯度變成**有序遞減**（1.31 → 1.23 → 1.19 → 0.94），
比原本 Medium 高於 Low 的凸起更符合 absorption 假說。但**四個 regime 檢定經 Holm 校正後
無一存活**（最小 adjusted p = 0.104），所以 regime-level 顯著性不能拿來承載敘事；
`main_v3.tex` 已據此降級（見下節）。

k904 獨立佐證（不同視窗、Welch）：overall 1.160 (p=0.042)、Low 1.305、High 0.935。
k741 改用 Welch 後兩者變體一致，5% 兩側分歧的問題消失（歷史紀錄見下節）。

### 檢定變體：選 Welch，但**不是** a priori（2026-07-20 Codex FAIL 後更正）

原版呼叫 `stats.ttest_ind` 未傳 `equal_var`，等於**因為省略而拿到 Student's**，
而論文一直標成 Welch、姊妹實驗 k904 也真的用 Welch。兩個變體在 overall 檢定上
**跨在 5% 兩側**（Student 0.0506 / Welch 0.0394），所以不能繼續放著不決定。

現在所有 call site 都顯式傳 `equal_var=False`。方法論理由是站得住的：

- Welch 無條件使用是標準建議（Zimmerman 2004；Ruxton 2006；Delacre, Lakens & Leys 2017）：
  變異數真的相等時 power 損失極小，而「先做變異數檢定再選變體」的兩階段程序會**膨脹 Type I error**。
- 與 k904 及論文既有標籤一致。
- **不是因為看到異質變異才選它** —— Brown-Forsythe p = 0.48、sd ratio 0.94，本樣本沒有異質變異證據。
  主張是「Welch 本來就該是預設」，與這份診斷結果無關。

**但本檔第一版寫成「a priori 選定」，那是不實陳述，已撤回。** 這個決定是在改稿階段做的，
當時兩個 p 值都已經看到了。知道哪個變體落在 5% 哪一側之後才選，就不能用「事前指定」來辯護。
能誠實提供的替代說法只有兩點：(a) 兩個變體到處都併陳，沒有藏；(b) 這個選擇在敘事真正倚賴之處
**對自己不利**：

| | overall p | regime family Holm 後存活 |
|---|---|---|
| Student | 0.0506 | Low (adj p = 0.036) |
| **Welch（採用）** | **0.0394** | **無** |

這比事前指定弱，而且就照這個強度寫，不裝飾。真正的結論是：**這個結果對一個合理的輔助設定
選擇很脆弱，而脆弱本身就是發現。**

### 多重比較：family 不只是那張表（2026-07-20 Codex FAIL 後更正）

本檔第一版只對四個 regime 檢定做 Holm，理由寫「該表就是 family」，並把 overall 的 vs-all 與
vs-Friday 排除在外，說它們是「同一假設的兩種框法」。**Codex 判這個界線不具原則性**：family 跟隨
的是推論主張的集合，不是 LaTeX 表格邊界；而且那兩個 overall 檢定用的是**不同的對照樣本**
（全部 non-NFP vs 只有週五），回答不同的比較問題。排除它們**剛好**是唯一能保住 sub-5% headline
的切法 —— 那叫方便，不叫原則。

現在改成把每一種合理的 family 都算出來報告，直接消掉這個 degree of freedom：

| family | 最小 Holm adjusted p |
|---|---|
| 兩個 overall 檢定 | **0.0722** |
| 四個 regime 檢定 | 0.1039 |
| 主 overall + 四 regime（5 檢定） | 0.1298 |
| 全部六個檢定 | 0.1558 |

→ **在任何一種 family 下都沒有東西過 5%**，包括 overall 效應本身（它連對上自己的
companion 檢定都撐不住）。論文的 NFP 節因此全節降級為 descriptive，推論改靠 SAR 證據
—— 這點論文本來就這樣寫，現在數字也對上了。

### ⚠️ 最重要的發現：論文的「regime 對比」本身沒被檢定過

Codex round-2 指出：論文用「calm 顯著、crisis 不顯著」承載 absorption 解讀，
那是 **difference-in-significance，不是 significance-of-difference**。
兩個 regime 的 p 值不同，不等於兩者的 ratio 有可偵測的差異。

新增 `regime_difference_test`（20 日 circular moving-block bootstrap，B=10,000，
seed=20260719，保留波動叢聚，每個 replicate 重算所有 regime ratio）**直接檢定該對比**：

| 量 | 值 |
|---|---|
| calm − crisis ratio 差 | **+0.369** |
| 95% CI | **[−0.097, 0.786]** ← **包含 0** |
| p (two-sided) | **0.115** |
| 有序趨勢 Spearman ρ | 樣本內 **−1.000**（完全單調），但 bootstrap 平均 −0.635、CI [−1.00, 0.40] ← 包含 0，代表這個排序不穩定 |

→ **論文原本「regime decline 是 absorption 最強證據」的說法不成立**，已在 tex 降級為
descriptive pattern，並明說推論改靠 SAR 證據。crisis cell 只有 28 天，檢定力極低，
所以**不能反過來說「兩 regime 相等」**——tex 也照這樣寫了。

這不是 proxy 造成的，是論文既有的推論缺口，被這次重跑翻出來。

### 另外發現的兩個獨立缺陷（非 proxy 造成）

1. **論文表格的 ratio / t / p 三欄無法追溯到任何實驗**。重現能逐位對上 `n` 與 `mean|r|`，
   但對不上 ratio/t/p（Medium 論文 1.30/2.69/0.009，實際 1.175/1.72/0.090）。
   掃過 8 種 spec 變體皆不符。根因：`reproduce.py` 只綁 regime 的 `n` 與 `mean_abs`，
   **從未綁 ratio/t/p**。已修：canonical JSON 存下這些值，`reproduce.py` 改綁 canonical
   並補齊每個 regime 六欄。gate 當時 112/112；加入 Welch 揭露與 Holm 綁定後為
   **135/135, 100%, green**（數字以 `paper/volatility-absorption/reproduce_report.json` 為準）。
2. **論文把這些檢定標成 "Welch's t-tests"，但 k741 用的是 Student's**
   （`stats.ttest_ind` 預設 `equal_var=True`）。第一輪先在 tex 改成中性的
   "two-sample $t$-tests"；**現已徹底解決**：headline 固定為 Welch、所有 call site
   顯式傳 `equal_var=`、tex 改回 "Welch's" 並在 table note 揭露 Student 變體的 p 值。
   見上節「檢定變體」。

### Codex review 歷程

| 輪次 | verdict | 結果 |
|---|---|---|
| Round 1 | **FAIL** | 混淆的兩臂設計、樣本窗洩漏、k904 endpoint 靜默丟事件、reproduce.py 仍綁舊 JSON —— 全部已修 |
| Round 2 | **FAIL** | round-1 修正全部驗證通過；新開 5 項（gate 稀釋、regime 對比未檢定、footnote 未綁定、mapping 未 fail-closed、claim surface 殘留 0.254）—— 全部已修 |
| Round 3 | **未跑** | ⚠️ merge 前必須重審 |

依 `.claude/rules/experiments.md`，merge 需要一份 pin 住現行 sha 的 `review_verdict.json`；
本 worktree **尚未產生**（`experiment_gates.py certify` 目前會以
`uncertified: no review_verdict.json` 擋下）→ **主線程合併前務必重跑 Codex review 並產生裁決檔**。

細節、2×2 全表與 feed 回溯建議見 `nfp_canonical_vs_proxy_comparison.md`。
