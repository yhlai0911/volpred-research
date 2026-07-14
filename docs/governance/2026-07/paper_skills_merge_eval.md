# Paper Skills 整併評估報告（WS5-5b）

- **建立**: 2026-07-14（WS5 治理疊層收斂子項 5b；`docs/refactor_plan_token_ops_waste.md` §WS5）
- **性質**: 分析-only 評估報告，**不動任何 skill 檔**。skill 編輯屬主線程 + 寄信通知 owner（CLAUDE.md skill-autonomy 契約），本報告只提整併方案供裁決。
- **範圍**: 8 個 paper 相關 skill × 5 個面向（review-round / stage / 投稿 / citation / compliance）的重疊實測。

## 0. 受評 skill 清單（實測行數）

| Skill | 行數 | 主責 | frontmatter model |
|---|---|---|---|
| paper-review-cycle | 169 | 跑審查迴圈 + 歸檔 | sonnet/medium |
| paper-stage-classifier | 181 | 5-stage 分類 + continuous loop | haiku/low |
| paper-update | 136 | v(n+1) tex 修訂 + 平台同步 | sonnet/medium |
| paper-submission-pipeline | 157 | 11-stage 投稿 state machine + gate | (無 model line) |
| journal-review | 125 | 期刊選擇 + format/substance/compliance gate + 打包 | (無 model line) |
| latex-academic-reviewer | 526 | LaTeX 全面學術審查（10 維度）| (未列) |
| finance-paper-quality | 193 | 內容品質標準（claim-evidence 等 10 條）| (未列) |
| citation-verifier | 329 | 引用驗證方法論 | (未列) |
| **合計** | **1,816** | | |

**先驗事實**：8 個 skill **全部已有 explicit `Scope Boundary` + `與其他 skill 關係`/`Related Skills` 段**，SCOPE 早已互相 deconflict。因此本評估的問題**不是「該用哪個 skill」的分工混亂**，而是 **(a) 同一規則 CONTENT 被寫在 2-3 處**（漂移風險）與 **(b) 兩套並存的 paper 生命週期 state machine**（dual source-of-truth）。→ 結論先講：**不建議大爆炸合併成單一 mega-skill**（會與 progressive-disclosure 設計 + `feedback_skill_structure` 衝突，且 8 個檔的 scope 已清）。建議做**定向去重**：把重複 CONTENT 收斂到單一 owner + 其餘留 pointer，並解一個結構性 dual-machine。

## 1. 重疊矩陣（5 面向）

| 面向 | 單一 owner（建議） | 重述層（應降 pointer） | 重疊性質 |
|---|---|---|---|
| review-round 編排 | paper-review-cycle Step 1 + 歸檔 | pipeline §86-90、journal-review Step 3 | 已半 deconflict（journal-review 已寫「do not duplicate」）；pipeline 仍重述 |
| **review-report 歸檔** | paper-review-cycle §126-162 | **paper-stage-classifier §71-116** | **近逐字重複 ~40 行** |
| **stage / 生命週期** | （需裁決）pipeline 11-stage tracker | paper-stage-classifier 5-stage | **兩套 state machine 並存 = dual SoT** |
| 投稿（submission） | paper-submission-pipeline | journal-review Step 7（打包）、paper-update（同步）| 分工清楚，低重疊 |
| citation | citation-verifier | finance-paper-quality §9、latex-academic-reviewer §J | 短維度檢查，合法多維審查，低優先 |
| **compliance** | `scripts/check_paper_compliance.py`（機械）+ journal-review Step 6（prose）| pipeline §79-84、finance-paper-quality §10 | 3 處重述 + **1 處語義衝突** |

## 2. 逐面向 findings（附行號證據）

### 2.1 review-report 歸檔 — 近逐字重複（最明確、最該修）
- `paper-review-cycle` §「Review Report Archive 規則（MUST）」（L126-162）與 `paper-stage-classifier` §「Review report 歸檔規則（必須）」（L71-116）**內容近乎逐字相同**：同一 `review_history/v<n>/` 目錄結構、「舊 reports 不可覆蓋」、Markdown-not-LaTeX、`$...$` inline、`"§4.3, eq.(7)"` 文字引用、agent prompt 寫死 output path、git-track 不進 .gitignore、以及**同一份 4 點「為什麼」rationale**（6 個月後 reviewer 問、附 prior review log、catch deferred fixes、學術誠實）。
- **判定**：paper-review-cycle 是 review 迴圈的機械 owner，歸檔規則應由它獨佔。stage-classifier 的 ~40 行應收成 1-2 行 pointer。**省 ~38 行、0 規則損失**。

### 2.2 stage / 生命週期 — 兩套 state machine（結構性 dual SoT）
- `paper-stage-classifier`：5 階段 `early / draft / review / ready_for_submission / submitted`，寫 Supabase `papers.stage` + `next_tasks.json`。
- `paper-submission-pipeline`：11 階段 `draft→revision→compliance_scrub→multi_round_review→review_converged→arxiv_ready→arxiv_posted→journal_submitted→under_journal_review→accepted/rejected`，寫 `storage/paper_pipeline_status.json`，且 §ACT（L112-113）自帶 `stage → website status` 對照表。
- 兩者是**同一 paper 生命週期的兩套字彙 + 兩個 tracker 檔**，靠 pipeline 內一段對照表手動橋接 → 正是 error_log §M（source-of-truth drift / dual SoT）的模式。目前 pipeline 有 `paper_website_drift` alert 在防「website status 高於 stage」，但**兩套 stage 字彙本身**沒有機械對齊。
- **判定（需 owner 裁決，非機械降級）**：建議定 `paper-submission-pipeline` 的 11-stage tracker（`storage/paper_pipeline_status.json`）為 canonical DECISION SoT（較新、PDCA、有 stall + drift 偵測、有 website 映射），把 `paper-stage-classifier` 的 5-stage 重構成**由 11-stage 投影而來的粗粒度公開字彙**（單一來源），而非獨立判定。此項觸及 Supabase schema + 前端 `Paper.status` union，屬結構調整，**列為 owner 決策項**，不在本次機械去重內完成。

### 2.3 compliance — 3 處重述 + 1 處語義衝突
- 機械 owner 已存在：`scripts/check_paper_compliance.py`（"Submission-compliance gate for paper LaTeX sources"）。pipeline L73/L84 也已 cross-ref「paper-submission-compliance audit」。
- prose 規則卻在 3 處各寫一份：`journal-review` Step 6（L91-107，**最完整** — grep .tex+bib+package、AI-use declaration 為獨立章節、reproduce gate、各期刊 data policy）、`paper-submission-pipeline` §Compliance gate（L79-84）、`finance-paper-quality` §10 Author Presentation（L168-172）。
- **語義衝突（研究誠實風險）**：`finance-paper-quality` §10 寫「Acknowledge AI assistance **in footnote if used**」，但 `paper-submission-pipeline` §Compliance 與 `journal-review` Step 6 要求「**ZERO** mentions of AI/LLM/Claude…」。兩條並存會讓 agent 依載到哪個 skill 而做出相反動作。journal-review 有正確處理（AI-use declaration 是**期刊要求時**的獨立章節，非 footnote，非默默省略）——即 finance-paper-quality §10 的措辭是過期/不精確版本。
- **判定**：prose 單一 owner = `journal-review` Step 6（+ 機械 `check_paper_compliance.py`）。pipeline §79-84 與 finance-paper-quality §10 降為 pointer；**同時修正 finance-paper-quality §10 的 AI-footnote 措辭**（消衝突）。**省 ~10 行 + 消一個誠實風險**。

### 2.4 review-round 編排 — 部分已 deconflict
- `journal-review` Step 3（L50-59）**已正確寫**「see those skills; do not duplicate them here」+ 只留 codex 委派 token-economy 一句 → 已是 pointer 形態，**不需再動**。
- `paper-submission-pipeline` §「Run reviews via codex」（L86-90）+ gate `-> review_converged`（L74）仍重述「透過 codex exec 跑 latex-academic-reviewer + citation-verifier，迭代到收斂」。→ 收成 pointer 指 paper-review-cycle Step 1。**省 ~5 行**。

### 2.5 citation — 低優先，建議不動
- owner = `citation-verifier`（329 行完整方法論）。`finance-paper-quality` §9（L161-167）與 `latex-academic-reviewer` §J（L307-324）都只是**全篇審查裡的一個短維度檢查**（method→cite original、DOI 一致、無孤兒文獻），屬合法的多維度 review 一環，且兩者都已在 Related Skills 指向 citation-verifier。**建議保留原狀**（去掉會傷害各自 self-contained 的審查清單），僅可選擇性各加一行「深度見 citation-verifier」。

## 3. 整併方案（哪些合併 / 哪些保留 / 省多少行）

**檔案層：8 個 skill 全部保留為獨立 skill**（scope 已清、paper-* 命名穩定、progressive disclosure）。**不合併檔案**。

**內容層去重（3 項機械降級，0 規則損失，全部保留在 owner）**：

| # | 動作 | 改哪個檔 | owner | 估省行數 |
|---|---|---|---|---|
| M1 | review-report 歸檔 ~40 行 → 1-2 行 pointer | paper-stage-classifier §71-116 | paper-review-cycle §126-162 | ~38 |
| M2 | compliance prose → pointer + 修 AI-footnote 衝突 | paper-submission-pipeline §79-84、finance-paper-quality §10 | journal-review Step 6 + `check_paper_compliance.py` | ~10 |
| M3 | review-via-codex 編排 → pointer | paper-submission-pipeline §86-90 | paper-review-cycle Step 1 | ~5 |
| | **機械去重合計** | | | **~53 行** |

**結構層（1 項 owner 裁決，非機械）**：
- S1：統一 paper 生命週期 state machine（§2.2）。canonical = pipeline 11-stage tracker；stage-classifier 5-stage 改為投影。觸及 Supabase schema + 前端 `Paper.status` union → 需 owner 決策 + 前端 deploy 驗證，行數節省次要，**主要收益是消 dual-SoT**。

**不動**：paper-update（分工清楚）、citation 面向（§2.5）、journal-review Step 3（已 pointer 化）、latex-academic-reviewer 主體（526 行是 review 方法論本體，無跨 skill 重複）。

## 4. 執行路徑（本報告不執行）

1. M1/M2/M3 是 skill 檔編輯 → **主線程執行 + 寄信通知 owner**（每個 skill 改動一封 `send-alert --title "Skill 修改通知: <name>"` 含 diff 摘要，per CLAUDE.md skill-autonomy）。
2. M2 附帶修 finance-paper-quality §10 的 AI-footnote 措辭，與 journal-review/pipeline 對齊（消語義衝突）。
3. S1 走 owner decision email（Supabase schema + 前端影響），不在 skill 去重批次內。
4. 附帶側發現（非本子項範圍，建議一併處理）：paper-review-cycle / paper-stage-classifier / paper-update 的 frontmatter `model: sonnet|haiku` 與 owner 2026-07-05「全 subagent 用 opus」指令不一致（`agent-delegation.md`）——屬 stale frontmatter，建議校正。

## 5. 一句話結論

8 個 skill scope 已清、**不需合併檔案**；真正的疊層是 **~53 行重複 prose（review 歸檔 + compliance + codex 編排）** 與 **一個 dual state machine**。前者做 3 項機械降級（主線程 + 寄信）即可 0 損失收斂；後者需 owner 裁決統一生命週期 tracker。附帶一個 compliance 語義衝突（finance-paper-quality §10 vs 投稿 compliance 的「零 AI 提及」）務必在 M2 一併修掉。
