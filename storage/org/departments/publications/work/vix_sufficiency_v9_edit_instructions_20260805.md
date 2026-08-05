# vix-sufficiency v9 — .tex edit instructions（main_v5.tex，主線程執行）

**目標檔**：`paper/vix-sufficiency/main_v5.tex`（本部門子樹產出，因 `paper/` 本輪被另一 session
持有寫鎖，內容先落在這裡，待鎖釋放或主線程直接取用本檔內容套用）。

**來源**：經理裁決 `item_20260805T200528019400Z`（2026-08-05），F3/BSI 採選項 (b)：降級為
robustness 診斷，家族數由 thirteen 改 twelve；`main_v5.tex:519` 誠實線修正同批；F9/F10 承既有
裁決 `paper/vix-sufficiency` 外部的 `adjudications/vix_sufficiency_f3_f9_f10_20260805.md`。
三件併一輪 .tex 編輯，理由：全部落在 `§2.3 / Table 1 / Table 2 / L519` 段落同一鄰域，分兩輪會
互相踩對方修過的行號。

**改動原則（經理明示）**：只動標題／Table/計數，不重取數據。**不重新編號 Family 4–13**——
維持既有編號（避免全文引用 `Family 4`/`Family 8`… 連鎖改號），只把 F3 從「headline 十三家族」
移出、改列 robustness 診斷小節，並把總數敘述由 thirteen 改 twelve。

## 1. Family count：thirteen → twelve（僅指「家族總數」的語境，逐一核對，禁止全文批次取代）

以下每一處 `thirteen` 都是「總家族數」語境，全部改 `twelve`（行號基準：main_v5.tex 2026-08-05
版本，套用前先 `grep -n thirteen` 重新核對行號未漂移）：

| 行號 | 現況片段 | 動作 |
|---|---|---|
| L35 | 標題 `...Thirteen Signal Families for Equity...` | → `Twelve Signal Families` |
| L48 | abstract「thirteen pre-specified signal families---cross-asset ... behavioral sentiment, the variance risk premium...」 | → `twelve`；並把列舉清單中的 `behavioral sentiment,` 整段拿掉（F3 不再是列舉中的一員），前後逗號接好 |
| L74 | 「pre-specified horse race among thirteen signal families」 | → `twelve` |
| L77 | 「All thirteen signal families and their construction rules are defined...」 | → `twelve` |
| L94 | 「The thirteen signal families we test are precisely the inputs...」 | → `twelve` |
| L100 | 「describes the data and the thirteen signal families」 | → `twelve` |
| L134 | 「Each of the thirteen signal families we test represents...」 | → `twelve` |
| L144 | 「we test thirteen signal families simultaneously」 | → `twelve` |
| L148 | section 標題 `Data and the Thirteen Signal Families` | → `Twelve` |
| L163 | subsection 標題 `The Thirteen Signal Families` | → `Twelve` |
| L165 | 「We pre-specify thirteen signal families spanning seven broad categories...」 | → `twelve`；本句後面新增一句交代 F3 地位（見下方建議句 A） |
| L171 | Table 1 caption `The Thirteen Signal Families` | → `Twelve Signal Families` |
| L467 | 「Table~\ref{tab:main_results} presents the main results for all thirteen signal families.」 | → `twelve`；並在句末新增子句交代 F3 另表報告（見建議句 B） |
| L473 | Table 2 caption `Thirteen Signal Families vs. VIX` | → `Twelve Signal Families vs. VIX` |
| L671 | 「among the thirteen families evaluated in the main horse race」 | → `twelve` |
| L805 | 「aggregate null across thirteen signal families」 | → `twelve` |
| L1030 | 「Our thirteen signal families are all elements of $\Omega_t$」 | → `twelve` |
| L1141 | 「systematic evaluation of thirteen pre-specified signal families」 | → `twelve` |
| L1143 | 「Each of the thirteen signal families we tested represents...」 | → `twelve` |

**禁止觸碰**：L870「thirteen of sixteen DM statistics change by less than 0.5」——這裡的
`thirteen` 是「16 個 cell 裡有 13 個」的計數，與家族總數無關，若做全文 `thirteen→twelve`
批次取代會誤傷這一行。**逐行手動改，不要用 sed 全域取代。**

## 2. Table 1（`tab:signals`，L169-186）：F3 列保留，加註腳標示降級

不刪 F3 那一列（L181 `3 & Behavioral sentiment & ...`），改法：

- 在該列 `Behavioral sentiment` 後加 `$^{\ddagger}$` 之類的標記
- Table note（`tablenotes` 區，約 L187）新增一條：
  `$^{\ddagger}$Family 3 is reported as a robustness diagnostic rather than one of the twelve
  headline pre-specified families: three of its four components (VIX level, VIX/VIX3M ratio, VIX
  momentum) are transforms of the VIX benchmark itself, and the fourth (SKEW) is also an
  SPX-option-implied index inside the information set under test. See \S\ref{sec:family3} for
  detail.`
- Table caption 本身仍是「Twelve Signal Families」——這是刻意的張力（表列 13 列但標題講
  twelve），note 要交代清楚，避免讀者誤以為算錯

## 3. §2.3 Family 3 小節（L210-212）：開場句改寫，交代降級理由

現況：
> Investor sentiment affects asset prices through both rational and behavioral channels
> \citep{baker2006}. We construct a composite Behavioral Sentiment Index (BSI) using four
> components: the CBOE SKEW index, the VIX/VIX3M ratio, VIX 22-day momentum, and VIX level...

改為（新增一段在原段落之後，原段落內容不動）：

> \emph{A note on Family 3's status.} Three of BSI's four components (VIX level, the VIX/VIX3M
> ratio, VIX momentum) are transforms of the VIX benchmark itself, and the fourth (the CBOE SKEW
> index) is also an SPX-option-implied index inside the information set under test. We therefore
> report Family 3 throughout as a \emph{robustness diagnostic} rather than as one of the twelve
> headline pre-specified families: its null (Table~\ref{tab:main_results}, DM $|t|=0.52$) is
> close to tautological---a non-linear recombination of VIX failing to beat linear VIX is what
> the paper's own thesis predicts, not independent evidence for it. We retain it in the tables for
> transparency but exclude it from the headline family count and from the Holm-Bonferroni
> family-wise correction (which properly applies to independent tests).

**§ label**：若要讓 Table note 的 `\S\ref{sec:family3}` 生效，確認本 subsubsection 有
`\label{sec:family3}`（目前沒有，需新增在 `\subsubsection{Family 3: ...}` 之後）。

## 4. Table 2（`tab:main_results`，L473 起）：F3 列處理 + Holm-Bonferroni 說明句

- L483 該列 `3 & Behavioral sentiment & 0.091 & 0.004 & 1.64 & ...` 保留數字（不重算），
  在 family 名稱後加同一個 `$^{\ddagger}$` 標記，指回 Table 1 的 footnote（或另立一條
  table note，二擇一，取決於 LaTeX 排版習慣，主線程判斷）
- L513-514（Holm-Bonferroni 段）現況「Among the ten testable DM tests, families 1--4 and 8--11
  produce raw $p$-values...」——確認這段的 correction family 數是否含 F3；若含，需要加一句
  說明 F3 因非獨立測試被排除在 family-wise correction 之外（呼應 §2.3 新增段）；若本來就
  不含（「ten testable」是否已經排除 F3？需查證再動筆，不要臆測）

## 5. L519 段落：F3 描述謬誤 + F9/F10 分流（三家族併一次改）

現況（同一句錯誤描述 + 錯誤 deferred 框架，`adjudications/vix_sufficiency_f3_f9_f10_20260805.md`
已查證並給出建議句）：

> The three remaining daily families---Family~3 (behavioral put-call ratio), Family~9 (Google
> Trends fear), and Family~10 (overnight VIX change)---depend on external series (CBOE put-call
> volume, Google Trends queries, and the intraday VIX opening print) that are not yet pinned in
> the replication snapshot; their nested Clark-West increments are deferred to a
> data-provisioning follow-up and are expected... to be equally immaterial.

**問題**：(a) Family 3 從未使用 put-call 資料（見 adjudication §「F3 — SUPERSEDED」）；
(b) F9 應排除（方法論理由，非資料問題）；(c) F10 根本沒 blocked（`^VIX` daily OHLC Open 欄
已存在於 pin，只是需要跑 nested CW，非本部門轄區，已請研究部評估承接，**本輪不動 F10 的執行
狀態，只修文字**）。

**替換為**（整合 adjudication 建議句 + 本裁決的降級框架，這版取代 adjudication 原建議，因為
原建議仍把 F3 當「thirteen 之一」處理，現在要反映 twelve + 診斷的新框架）：

> The remaining daily families are treated differently. Family 3 (behavioral sentiment index) is,
> as noted above, a robustness diagnostic rather than a headline family, and its DM statistic
> ($|t| = 0.52$) is reported for completeness rather than as an independent test; a nested
> Clark-West increment adds no information beyond what \S\ref{sec:family3} already establishes and
> is therefore not computed. Family 10 (overnight VIX change) depends on the unlagged Open column
> of the daily VIX series, already present in the replication snapshot; its nested Clark-West
> increment is a pending robustness computation, not a data limitation. Family 9 (Google Trends
> fear) is excluded from the nested Clark-West exercise on methodological rather than logistical
> grounds: Google Trends returns values rescaled to the queried window with no vintage archive, so
> no series available at each forecast origin can be reconstructed. Its main-table Diebold-Mariano
> statistic ($|t| = 0.67$) is reported as a final-vintage figure and is not upgraded to a real-time
> predictive claim.

## 6. 收斂後動作（五步 Gate 4-5）

1. 上述全部套用後，`git diff paper/vix-sufficiency/main_v5.tex` 逐處核對本清單勾完
2. 重新編譯，檢查 Table 1/2 排版沒有因為加 footnote marker 而跑版
3. `uv run volpred ops paper-update --paper-id vix-sufficiency`
4. 開 v9 review round（`paper-review-cycle` skill，含 latex + citation + Codex 三軌——prg 那輪
   Codex 軌被 deny，這裡若同樣被擋，記錄但不要當作可省略）
5. 回讀：round 完成後由本部門（publications）依 v8-recheck 同款流程獨立複驗 sha256 + 逐條核對
   本清單，而非套用者自行宣告收斂

## 未在本清單範圍內

- F10 的實際 nested CW 執行（`experiments/` 寫入權，研究部承接中，另案追蹤）
- Table 2 之外的策略表（L550「3 & Behavioral sentiment (fear hedge)」屬 volatility-timing
  strategy 表，非 family-count 語境，未列入本輪改動——若主線程判斷該表也需要一致性標記，
  屬於延伸判斷，非本清單遺漏）
