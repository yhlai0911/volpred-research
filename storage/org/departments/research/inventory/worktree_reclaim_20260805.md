# 13 個未合併 worktree 收編判定（研究部判定層）

- 判定人：research 部門
- 判定時間：2026-08-05 16:51–17:20（台灣時間）
- 來源工作項：`item_20260805T074701282542Z_13-commit-worktree-2026-08-05t0`（P1）＋
  `item_20260805T084156023702Z_p1-inbox-a-item-20260805t074205`（執行範圍修正）
- 判定方法：`git log --oneline main..<branch>`、`git diff --name-only main...<branch>`、
  `python3 scripts/check_experiment_artifacts.py check --path <worktree絕對路徑>`、
  `python3 scripts/experiment_gates.py certify --path <worktree絕對路徑>`、`ls -la`（髒檔比對）
- **未 cd 進任何 worktree，未執行任何寫入操作。**

---

## 結論先講：13 個一個都合不了，而且瓶頸不在權限

`experiment_gates.py certify` 是 `merge_worktree.sh` 的**第一道門**（`.claude/rules/worktree.md`
合併流程第 0 條）。我對 14 個實驗目錄（13 個 worktree，k1095v3 分支帶 v2/v3 兩個）逐一跑了 certify：

**14/14 全部 BLOCKED。**

所以把這批單純轉給平台工程部「跑 merge_worktree.sh」不會救回任何一個 K —— 13 次全部會在同一道
gate 被擋回來。真正的瓶頸是**這批實驗沒有一個帶著有效的審查裁決**，那是研究流程的缺口，不是
執行權限的缺口。

三道關卡的實際順序（每個 K 都要全過才進得了 main）：

1. **certify gate**（`review_verdict.json`，verdict=PASS 且 sha256 對得上現行 bytes）→ 14/14 擋
2. **artifact gate**（knowledge 條目 + `reproduce_spec.json`）→ 12/14 擋
3. **merge 執行**（`bash scripts/merge_worktree.sh`）→ 尚未輪到

---

## 逐個判定表

| # | K / worktree 分支 | ahead | 研究產物與 commit 內容 | certify | artifact gate | 髒檔 |
|---|---|---|---|---|---|---|
| 1 | k1734 `wt/dispatch-slot-1-1e5922b4-k1734` | 7 | EM carry-unwind 崩跌風險不對稱；三件套＋4 圖＋8 個 raw CSV＋rev1–rev4 審查歷程＋2 份 Codex verdict md | **FAIL**（reviewer verdict = FAIL） | BLOCKED 缺 knowledge | 無 |
| 2 | k1095v3 `wt/dispatch-slot-1-6ec34837-k1095v3` | 6 | 台股事件切換 VT（known-in-advance schedule）；帶 **v2 與 v3 兩個實驗目錄**，v3 是對 v2 Codex FAIL 的 remediation ＋ reproduce 紀錄 | v2 **FAIL** / v3 **無 verdict** | v3 顯示 PASS 但**是假通過**（見下方 gate 缺陷）／ v2 BLOCKED 缺 reproduce_spec | 無 |
| 3 | k1720 `dispatch-slot-3-87c7269d-k1720` | 4 | 槓桿型 ETF 機械式再平衡與尾盤波動放大（裁決 NULL）；rev2/rev3 對 Codex round-1/2 的定向修正＋兩份 rev snapshot | **無 verdict** | BLOCKED 缺 knowledge | 無 |
| 4 | k1737 `k1737-slot1-9783132d` | 2 | DML 因果 factor 檢定的**預先登錄**（README 凍結成功標準）＋中斷 run 的 artifact 保存；`K1737_results.json` 已被作者自行 **QUARANTINE** | **無 verdict** | BLOCKED 缺 knowledge ＋缺 reproduce_spec | **有**（見下） |
| 5 | k1748 `codex/k1748-bcc254dc` | 2 | 國債交割失敗（settlement fails）與波動；三件套＋NY Fed 原始 API 快照（含 meta.json）＋2 圖＋診斷 CSV | **FAIL**（4 項 blocking） | BLOCKED 缺 knowledge | 無 |
| 6 | k1747 `wt/dispatch-slot-1-bf6e9f48-k1747` | 2 | 估計風險對推論的影響稽核（code/tests/pinned data，結果後補）＋ reproduce_spec | **無 verdict** | BLOCKED 缺 knowledge | **有**（見下） |
| 7 | k1721 `dispatch-slot-3-87c7269d-k1721` | 1 | GPR daily Acts vs Threats 對 RV 的不對稱增量預測力；三件套（無圖） | **無 verdict** | BLOCKED 缺 reproduce_spec | **有**（見下） |
| 8 | signfc `wt/dispatch-slot-2-7087efc0-signfc` | 1 | 誠實 OOS 方向預測檢定（direction_predictability_signforecast）；三件套＋3 圖 | **FAIL**（3 項 blocking） | BLOCKED 缺 reproduce_spec | **有**（見下） |
| 9 | k1813 `wt/dispatch-slot-1-8af0700e-k1813` | 1 | 隔夜/盤中 VRP 群聚與星期效應（NULL）；三件套＋6 個 raw CSV＋4 圖＋reproduce_spec | **無 verdict 檔**，但 knowledge 條目 `ccbccb6a` 記載 **Codex primary-path 已審且 FAIL**（2026-08-02，2 項 blocking defect），remediation round 2 = `assign_bfd8dbf8`（**已在池中 pending，P2**）。certify 讀不到是因為裁決沒落成 `review_verdict.json` 檔 | **PASS**（有專屬 knowledge 條目，真通過） | 無 |
| 10 | k1742 `k1742-minwage` | 1 | 各州最低工資生效日 vs 勞力密集零售/餐飲波動（NULL）；三件套＋原始 xlsx＋test | **UNCERTIFIED**（裁決檔自陳「這些 bytes 沒被審過」） | BLOCKED 缺 knowledge | 無 |
| 11 | k1741 `wt/dispatch-slot-1-6fe0dac5-k1741` | 1 | 放空信用債作股票尾部對沖 vs put/VIX overlay；三件套＋2 圖＋pinned yfinance CSV＋data manifest＋literature.md＋reproduce_spec＋test＋gate_history | **無 verdict** | BLOCKED 缺 knowledge | 無 |
| 12 | k1745 `wt/dispatch-slot-1-c6dd8dc8-k1745` | 1 | TVP-HAR（Kalman/random-walk）vs 靜態 OLS-HAR；三件套＋forecasts CSV＋圖＋SPY/0050 raw＋reproduce_spec/commit＋source_manifest＋test | **無 verdict** | BLOCKED 缺 knowledge | 無 |
| 13 | k1749 `wt/dispatch-slot-1-b7f47803-k1749` | 1 | 盤整期長度 vs 波動狀態轉換（NULL）；三件套＋3 個 daily CSV＋preregistration.json＋reproduce_spec/commit＋test | **無 verdict** | BLOCKED 缺 knowledge | 無 |

### certify 阻擋原因分類

- **無 `review_verdict.json`（9）**：k1720、k1737、k1747、k1721、k1813、k1741、k1745、k1749、k1095_v3
  —— 其中 **k1813 其實審過**（Codex primary-path 判 FAIL，裁決只寫進 knowledge 條目沒落成檔案）。
  **「沒有裁決檔」有兩種成因，certify 分不出來**：真的沒審過，與審過但裁決沒歸檔。判定這 9 個時
  不能只看 certify 輸出，要交叉查 knowledge 條目 —— 但另外 8 個都缺 knowledge 條目，所以除了
  k1813 之外沒有第二個資訊源可查，它們「沒審過」的判定嚴格說只是**沒有相反證據**。
- **verdict = FAIL（4）**：k1734、k1748、signfc、k1095_v2
- **verdict = UNCERTIFIED（1）**：k1742

### artifact gate 阻擋原因分類

- **缺 knowledge 條目（9，只能主線程寫）**：k1734、k1720、k1737、k1748、k1747、k1742、k1741、k1745、k1749
  （k1737 同時缺 reproduce_spec）
- **缺 `reproduce_spec.json`（4）**：k1737、k1721、signfc、k1095_v2
- **PASS（2）**：k1813（真通過）、k1095_v3（**假通過**，見下）

### 順帶查出的 gate 缺陷：artifact gate 的 knowledge 檢查是 substring 匹配

`check_experiment_artifacts.py` 判斷「有沒有 knowledge 條目」是看 `knowledge.json` 裡有沒有任何條目
**提到**該 kid 字串。`k1095_v3` 因此匹配到 2026 年更早的 **K1095 原版**條目（內容是「8.63/VIX ＋
A4f-VT 事件窗合成策略，OOS 2017-2026 N=2160，三個假說全被拒」）而通過 —— 但那是**另一個實驗的
結論**，v3 本身沒有任何 knowledge 條目。

也就是說：**任何 kid 只要是既有 kid 的字串延伸（`k1095_v3` ⊃ `k1095`、`k1737b` ⊃ `k1737`），
就會自動繼承前作的 gate 通過權。** 這個 gate 的目的是「發現不會對 topic dedup 與選題隱形」，
substring 匹配會讓 v2/v3/變體系列整批隱形而 gate 仍然亮綠燈。

這不在研究部轄區（`scripts/check_experiment_artifacts.py`），已上報經理。修法方向是把匹配改成
邊界敏感（word-boundary 或顯式 `experiment_id` 欄位比對），不是把 kid 改名。

---

## 髒檔 disposition（4 個）

判定方式：`ls -la` 實際內容 vs `git diff --name-only main...<branch>` 的 tracked 清單差集。
（`git -C <worktree> status` 在本部門的權限下被 deny，見文末權限缺口。）

| worktree | 未追蹤內容 | disposition | 理由 |
|---|---|---|---|
| **k1737** | `__pycache__/`、`data/`（4 檔／約 57MB：`panel_k1737.parquet` 20MB、`prices_daily.parquet` 37MB、`fundamentals_raw.parquet` 199KB、`universe_sp500_frozen.csv` 15KB） | `__pycache__` **丟棄**；`data/` **不要 commit 大 parquet**，改保留現地並由 `checkpoint_manifest.json` 的 sha 引用 | 57MB 進 git 不合理，且這是**中斷 run 的中間態**（見下）；作者已用 checkpoint_manifest 釘住 hash，續作 `split_K1737_cached_rerun_20260802` 明文要求「從 cached panel 續跑、不重抓」——parquet 一刪就毀掉續作前提 |
| **k1747** | `__pycache__/`、`figures/`（2 圖 160KB）、`tables/`（2 CSV 68KB） | `__pycache__` **丟棄**；`figures/` 與 `tables/` **必須 commit** | 這是**研究產物**，不是垃圾。commit 訊息自陳「results pending」，圖表與表格是後補的結果本體，漏掉等於產物遺失 |
| **k1721** | `__pycache__/`、`data/`（5 檔 5.0MB：GLD/ITA/SPY/XLE CSV ＋ `gpr_daily_recent.xls` 3.2MB） | `__pycache__` **丟棄**；`data/` **應 commit** | 5MB 在可接受範圍；GPR 指數是會被覆寫的外部下載檔，不 pin 住就無法復現。這個 K 正好缺 `reproduce_spec.json`，data 一起補才有意義 |
| **signfc** | `__pycache__/`、`review_verdict.json` | `__pycache__` **丟棄**；`review_verdict.json` **必須 commit** | 這是 Codex round-2 的審查裁決（verdict=FAIL）。裁決是研究誠實紀錄的一部分，不能只留在工作目錄；且 certify gate 就是讀這個檔 |

**四個 worktree 的 `__pycache__/` 一律不 commit**（本來就該被 gitignore 忽略；未被忽略本身是
`.gitignore` 覆蓋不足的小缺口，屬平台工程部轄區）。

---

## 需要主線程處理的部分（研究部不可代寫）

**缺 knowledge 條目的 9 個 K**：k1734、k1720、k1737、k1748、k1747、k1742、k1741、k1745、k1749。

依 K1259 規則，`knowledge.json` 只能主線程寫，且數字必須從 `*_results.json` 程式化取得。研究部
不代寫、不轉抄。**但這一步排在 certify 之後**——先有 PASS 裁決才有值得寫進知識庫的結論，順序倒過
來寫就是在替未認證的結果背書。

---

## 建議處置順序（給經理裁決）

這 13 個不是同一種東西，硬要一批處理會卡死。按可救回的難度分三組：

### A 組 — 只差一次 Codex 審查（5 個，最划算）
k1741、k1745、k1749、k1720、k1095_v3

產物齊全（三件套＋資料＋spec），唯一缺口是沒人審過。處置：對凍結的 bytes 跑 Codex primary-path
審查 → `verdict-template` 產裁決檔 → 填 → 不再動 code。審完 PASS 才補 knowledge 條目。

（**k1813 原本被我列在這一組，更正為 B 組**：certify 只說「沒有 `review_verdict.json`」，我一開始
把它讀成「沒審過」；實際查 knowledge 條目後發現它已被 Codex primary-path 審過並判 FAIL，裁決只是
沒落成檔案。這正是「gate 的沉默不等於事實」的例子 —— 缺裁決檔有兩種成因，沒審過與審過沒歸檔，
certify 分不出來。）

**k1741 與 k1745 正好是本部門今天收到的 P3 canonical 任務（見下節）——這兩個不必重跑，實驗早就
做完了。**

### B 組 — 有 FAIL 裁決，要先修 blocking defect 再重審（5 個）
- **k1813**（2 項，remediation round 2 已在池中 pending = `assign_bfd8dbf8`「Fix additive
  buy-and-hold benchmark (B1) and README…」）：這一個**不需要新裁決**，只需要把已排的 remediation
  跑完，並在修完後把新裁決落成 `review_verdict.json`（現在裁決只活在 knowledge 條目的敘述裡，
  certify 讀不到）。

- **k1734**（5 項）：H2b 事後探索被標成預先登錄、H2a/H2b 多重性口徑不一致、lead logit 用 IID
  共變異數（HAC(21) 敏感度會實質削弱結論）、QLIKE 宣稱 nested-valid 但未施加 nested null、
  README 宣稱全數字可回溯但 power check 無存檔計算
- **k1748**（4 項）：發布時間戳被虛構成「觀察週三＋8 天 16:15 ET」卻仍推進 H1/H3、
  只稽核 2013 接縫未處理 2015/2022/2024 斷點、H2 主損失宣稱 level-scale QLIKE 卻對 log-scale
  跑 Clark-West、圖的誤差棒用錯誤的對稱變換
- **signfc**（3 項）：GARCH 收斂失敗可能靜默回退（全域關 warnings）、DM 單尾 p 值被誤讀成 8/8
  顯著較差（實際 6/8）、failure-to-reject 被寫成「證實 NULL」
- **k1095_v2**（4 項）：策略對已可實作的 t-1 權重重複延遲、S1 statutory 行事曆遺漏多個制度、
  HAC 檢的是均值報酬差卻宣稱 Sharpe 差異且未做多重性校正、公告捕捉率用未 shift 的 mask 計算

這組要研究人力實際動手修，不是行政流程。**修完必須重審**（改了 code 就 sha 漂移，舊裁決自動失效
——這是 gate 的設計，不是 bug）。

### C 組 — 特殊狀態（3 個）
- **k1737**：實驗**沒做完**。作者自己把 `K1737_results.json` 隔離並寫下理由（results 寫於
  02:11、`K1737.py` 改於 02:13、`panel_k1737.parquet` 改於 02:16 —— 結果早於它自己的輸入，
  是中斷 run 的證據不是結論），明文寫「不得 review、不得 merge、不得寫進 knowledge.json」，
  取代它的是續作 `split_K1737_cached_rerun_20260802`（**已在任務池 pending，P2 main_thread
  lane**）。處置：**這個 worktree 現階段不該收編，保留現場等續作**。合併它等於把一份自陳無效的
  結果送進 main。
- **k1747**：commit 訊息自陳「results pending」，但 `K1747_results.json`（894KB）與
  `figures/`、`tables/` 都已存在——結果其實已經產出，只是最後一哩沒 commit。處置：先把髒檔
  commit 補齊，再走 A 組流程送審。
- **k1721**：產物只有三件套（無圖、無 spec），且 `data/` 全在未追蹤狀態。處置：commit data ＋
  補 reproduce_spec，再走 A 組流程送審。

---

## 對本部門今天 3 張 P3 canonical 任務的直接影響

| 工作項 | canonical 任務 | 判定 |
|---|---|---|
| `item_20260805T085056310819Z` | K1737 Double-ML 因果 factor 檢定 | **不可從頭開跑**。已有預先登錄的 README（凍結成功標準）與被隔離的中斷 run；續作 `split_K1737_cached_rerun_20260802` 已在池中 pending 且指定 main_thread lane，明文要求從 cached panel 續跑。重跑會撞號、毀掉預先登錄、並重複下載 57MB 資料。 |
| `item_20260805T085056474828Z` | K1741 放空企業債作尾部對沖 | **實驗已完成**（2026-07-28 前後，1 commit）。`assessment.verdict = CONDITIONAL_PASS`（方向性效率或費率敏感度存在，但 N=4 事件與多重性 gate 不支持無條件排序），評估期 2018-01-26～2026-07-31，n=2138，三件套齊全含 reproduce_spec 與 literature.md。缺的只有 Codex 裁決與 knowledge 條目。 |
| `item_20260805T085056629604Z` | K1745 TVP-HAR | **實驗已完成**（1 commit）。`verdict.grade = NULL_NO_MULTIPLICITY_AWARE_TVP_HAR_EDGE`，`substantive_positive = false`——預先登錄的雙市場多重性感知 QLIKE 與 fluctuation 準則未同時滿足，敏感度分析無法挽救主要族群。三件套齊全含 reproduce_spec/commit 與 source_manifest。缺的只有 Codex 裁決與 knowledge 條目。 |

**三張單都不是「做實驗」，是「收編既有實驗」。** 研究部本班不重跑任何一個，避免製造第二份同號
產物（`.claude/worktrees/` 已存在對應 worktree，撞號規則明文禁止同 K 雙 agent）。

---

## 本部門遇到的權限缺口（回報經理，供平台工程部權限修補單參考）

在 dont-ask 模式下被 deny 的指令原文：

1. `git -C <worktree絕對路徑> status --porcelain` — 也試過 `--short` 與相對路徑，全部 deny。
   影響：無法直接讀 worktree 的 modified/untracked 狀態，改用 `ls -la` 對照
   `git diff --name-only` 推導未追蹤檔。**已追蹤但被修改的檔案（M 狀態）用這個方法看不到**，
   所以上表髒檔欄位對「untracked」是完整的，對「modified」是盲的。
2. `for d in ...; do ... done` 迴圈與 `python3 -c "..."` 內嵌腳本 — deny。影響：只能逐條下命令，
   不影響結論。

**可用**（本次判定全靠這些）：`git worktree list`、`git log`、`git diff --name-only`、
`ls -la`、`du -sh`、`jq`、`head`、
`python3 scripts/check_experiment_artifacts.py check`、`python3 scripts/experiment_gates.py certify`。

`bash scripts/merge_worktree.sh` 與 `git worktree` 未嘗試（依經理指示，執行層不屬本部門）。
