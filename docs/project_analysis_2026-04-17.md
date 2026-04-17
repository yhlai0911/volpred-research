---
title: VolPred 專案全面重新分析（2026-04-17）
date: 2026-04-17
author: Claude（Subagent 代勞，由賴奕豪教授委託執行）
version: 1.0
scope: /Users/yhlai0911/Desktop/volpred-research
method: 只讀分析，未修改任何檔案
---

# VolPred 專案全面重新分析（2026-04-17）

> 本報告為專案的年中體檢。統計數據採自當下倉庫狀態（branch: `main`，HEAD `28fc3772`），所有關鍵數字都附來源。目的是為主理人（賴奕豪副教授）提供一份**可執行**的改善藍圖，不只是診斷。

## 摘要（TL;DR）

- 專案 **成熟度高**：1,316 個 experiments 資料夾、1,232 筆 knowledge、74 筆 experience、910 篇已發佈文章、9 篇論文 MS、14 筆策略 registry、27 個前端頁面、102 個 scripts、74 個 skill 檔——研究與平台能力接近一個小型研究機構的產出。
- 但治理層**出現可觀的漂移**：`.agents/skills/`、`.claude/skills/`、`agent-specs/skills/` 三份「同名 skill」的 MD5 已經不一致（`autonomous-research`、`feed-publisher`、`paper-update` 三者各異），`git status` 顯示 **2,290** 筆未整理變更（`?? 808` / `M 159` / `D 1323`）。
- **最嚴重的資料完整性風險**：`experiments/` 有 **100** 個 K 資料夾未登記進 `knowledge.json`（孤兒實驗）、**190** 個 knowledge 中提及的 K 編號在 `experiments/` 下沒有對應資料夾（反向孤兒）、**191** 個實驗資料夾沒有任何 `*results.json`。
- 文件過載：`research_program.md` 已達 **625 行**（規則要求 < 700，逼近紅線；用戶規則實際要求 < 500）、`CLAUDE.md` 已達 **623 行 / 47KB**，兩者已經到了需要主動瘦身的臨界點。
- **磁碟異常**：`storage/ops/rollback_points/` 佔用 **14GB**（23 個 rollback 目錄），是唯一的體積巨獸，應列入短期清理對象。
- **治理產物漂移**：`.agents/` 和 `.claude/` 其實是 `agent-specs/` 的 render 產物（skill 頭部已註解 `AUTO-GENERATED FROM agent-specs/`），但三者內容已不同步——代表最近有人**直接改了 render 產物而不是 canonical**。

---

## Section 1：功能設定（Functional Inventory）

### 1.1 子系統鳥瞰

| 子系統 | 位置 | 規模 | 功能 |
| --- | --- | --- | --- |
| Python CLI（research engine） | `src/volpred/` | 74 個 `.py`、12 個子模組 | 實驗、評估、記憶、發佈、ops、stats、charts |
| 前端（active） | `frontend-v2-fix/` | 27 個 `page.tsx` | Next.js 15 + React 19 + Supabase |
| 資料同步 | `scripts/supabase_sync.py` | 668 行、29 個函式 | incremental + force-full + paper trades + drafts |
| 每日更新 | `scripts/daily_update.py` | 1,066 行 | Strategy registry、VIX regime、每日建議文章 |
| Operational scripts | `scripts/` | 102 個 `.py` | 數據抓取、回測、策略列管、知識索引 |
| Supabase schema | `supabase/migrations/` | 2 個 SQL（`interval_minutes`、`papers_table`） | 補充性 migration |
| Skill 系統（三層） | `agent-specs/skills/` canonical + `.agents/skills/` + `.claude/skills/` render | 每層 17 個目錄 | 學術審查、Ops、研究治理 |
| 論文目錄 | `paper/` | 9 個子目錄，PDF 41 個、TEX 44 個、MD 21 個 | 論文寫作 |
| Memory 系統 | `storage/memory/` | 6 個 JSON | 研究記憶 |
| Ops 層 | `storage/ops/` | 14GB（rollback 占絕大部分） | Job queue、rollback、審計 |
| 文件區 | `docs/` | 23 個 MD + `research_archive/`（7 個檔） | 規格、error log、存檔 |
| Notifications / Sentiment | `storage/notifications/` 5.4MB、`storage/sentiment/` 5.4MB | - | - |
| Reports（feed 唯一源頭） | `storage/reports/feed.json` | 6.3MB、915 entries | 910 published + 5 unpublished |

> 來源：`ls`, `wc -l`, `du -sh`, `jq 'length'`, `git status --short`。

### 1.2 STRATEGY_REGISTRY（14 筆；10 active）

讀取自 `scripts/daily_update.py` 第 29-48 行。

| key | display_name | is_active | order |
| --- | --- | --- | --- |
| `slow_vt` | GARCH VT (SPY) | True | 0 |
| `risk_parity` | Risk Parity (SPY+GLD) | True | 1 |
| `simple_12vix` | 12/VIX (SPY) | True | 2 |
| `recommended_5050` | 50/50 SPY/GLD | True | 3 |
| `taiwan_8.63vix` | 台灣 VT (0050.TW) | True | 4 |
| `taiwan_spy_momentum` | 台股動量 (0050.TW) | False | 5 |
| `tz_tw_jp_5050` | TW+JP 50/50 TZ | False | 6 |
| `global_vt_tz` | Global US VT + TW TZ | False | 7 |
| `vix_leading_guard` | VIX+景氣領先 (0050.TW) | True | 8 |
| `vix_cond_leverage` | VIX 條件槓桿（月頻） | True | 9 |
| `taiwan_hybrid_leverage` | 台股混合槓桿 | True | 10 |
| `piecewise_conservative` | 保守型 VT（Piecewise） | True | 11 |
| `fear_dca` | 恐慌加碼定期定額 | True | 12 |
| `adaptive_tier` | 自適應三階 VT | True | 13 |

**核心機制分類**（4 群）：

1. **Smooth VT（12/VIX 家族）**：`simple_12vix`、`slow_vt`、`risk_parity`、`piecewise_conservative`、`taiwan_hybrid_leverage`——這群對 lookahead 最robust（CLAUDE.md 明載）。
2. **Benchmark**：`recommended_5050`——不可動搖的三重護城河對照組。
3. **Regime 條件型**：`vix_cond_leverage`、`adaptive_tier`、`vix_leading_guard`、`fear_dca`——有離散切換，需要 VIX 分位點。
4. **已下架但仍記錄**：`taiwan_spy_momentum`、`tz_tw_jp_5050`、`global_vt_tz`——I8 TZ 系列（FAIL Harvey）。

### 1.3 論文目錄盤點

來源：`docs/paper-guide.md`（第 3-13 行）+ `ls paper/` + 各目錄的 PDF / TEX / MD 統計。

| # | slug | 目標期刊 | 頁數 | 狀態（依檔案組） |
| --- | --- | --- | --- | --- |
| 1 | `leverage-direction/` | JBF | 60 | 14 PDF / 12 TEX / 3 MD——修訂迭代最深 |
| 2 | `taiwan-vt/` | PBFJ | 34 | 5 PDF / 7 TEX / 4 MD——多版次 |
| 3 | `vt-trend-following/` | 待定 | 24 | 5 PDF / 6 TEX / 3 MD |
| 4 | `vix-sufficiency/` | J. Forecasting | 39 | 4 PDF / 4 TEX / 3 MD（`main_v2.tex`） |
| 5 | `volatility-absorption/` | - | - | 4 PDF / 4 TEX / 2 MD（`main_v2.tex`） |
| 6 | `vt-crowding-abm/` | - | - | 2 PDF / 2 TEX / 1 MD |
| 7 | `vt-insurance-cost/` | - | - | 2 PDF / 3 TEX / 1 MD |
| 8 | `prg-periodic-garch/` | - | - | 3 PDF / 3 TEX / 3 MD（含 `positioning.md`、`review_v1.1.pdf`） |
| 9 | `garch-x-vix/` | J. Empirical Finance / J. Forecasting | 31 | 2 PDF / 3 TEX / 1 MD（citation check 剛完成，見近期 commit `d6dc65a6`） |

> 觀察：論文 1（`leverage-direction`）已累積 14 個 PDF / 12 個 TEX，可能存在版本爆炸；論文 8（`prg-periodic-garch`）已到 `review_v1.1`；論文 9（`garch-x-vix`）在 2026-04-13/14 做完 citation check，是目前最活躍的工作區。

### 1.4 Skill 三層結構

來源：`ls .agents/skills/ | wc -l` = 17、`ls .claude/skills/ | wc -l` = 17、`ls agent-specs/skills/ | wc -l` = 17（三者目錄名全部相同）。

| 層 | 角色 | 檔案數 | 驗證 |
| --- | --- | --- | --- |
| `agent-specs/skills/` | **Canonical**（治理母本，CLAUDE.md 明載） | 17 個目錄 | `agent-specs/guide.md` 與 CLI `agent_spec` 模組 |
| `.agents/skills/` | Render 產物（為其他 agent 工具讀取） | 17 個目錄 | 檔頭註解 `<!-- AUTO-GENERATED FROM agent-specs/. -->` |
| `.claude/skills/` | Render 產物（Claude Code 直接讀取） | 17 個目錄 | 同上 |

**17 個 skill**：`academic-finance-reviewer`、`admin-ops`、`agent-result-verification`、`autonomous-research`、`citation-verifier`、`external-data-sources`、`feed-publisher`、`finance-paper-quality`、`latex-academic-reviewer`、`member-questions`、`memory-health`、`paper-review-cycle`、`paper-stage-classifier`、`paper-update`、`publication-candidates`、`taiwan-macro-data`、`worktree-merge-verification`。

**關鍵發現（drift 已發生）**：對 4 個 skill 跑 `md5` 比對結果：

| skill | `.agents` MD5 | `.claude` MD5 | `agent-specs` MD5 | 一致？ |
| --- | --- | --- | --- | --- |
| `admin-ops` | `24fb03ab…` | `24fb03ab…` | `0207a206…` | `.agents`=`.claude`，但與 canonical 不同 |
| `autonomous-research` | `9cb05c1b…` | `2dfd0ee8…` | `ac777eb4…` | **三者全部不同** |
| `feed-publisher` | `59c2bcb4…` | `dadee7df…` | `67611dd3…` | **三者全部不同** |
| `paper-update` | `66d8636a…` | `20d5fba3…` | `2e64a7fa…` | **三者全部不同** |

### 1.5 Memory 系統（6 個檔）

來源：`ls -lh storage/memory/` + 直接 grep 計數。

| 檔案 | 大小 | 條目數 | 最近更新 |
| --- | --- | --- | --- |
| `knowledge.json` | 1.6 MB | 1,232 `item_id` | 2026-04-16 16:36 |
| `thinking_journal.json` | 960 KB | 813 `id` | 2026-03-26 00:01 |
| `experiments.json` | 295 KB | - | 2026-03-22 00:08（**3 週未動**） |
| `research_log.json` | 176 KB | - | 2026-03-25 23:39 |
| `experiment_experiences.json` | 96 KB | 74 `"id": "E` | 2026-04-14 07:32 |
| `open_questions.json` | 17 KB | 19 | 2026-04-11 06:47 |

> `knowledge.json` 檔尾在 char 1495989 有 JSON 解析錯誤（`]}\n]}\n]`）——parser 讀到 1,435 行時報 Extra data。這是 append 時沒做 atomic replace 造成的資料結構損傷，`json.load` 失敗、只能用 grep。**這是隱性資料完整性風險**，需處理。

### 1.6 Experiments 統計

來源：`ls experiments/`、`comm` 交集分析。

| 指標 | 數字 | 備註 |
| --- | --- | --- |
| Experiments 子目錄總數 | **1,316** | `ls -d experiments/*/` |
| 含 K/k 前綴的目錄 | 937（distinct 864） | 其中 23 個大寫 K、914 個小寫 k |
| 非 K 命名的 feature-name 目錄 | 56 | 例：`behavioral_vt_barriers`、`btc_var_methods`、`hurst_fingerprint` |
| 有 `README.md` 的 K 目錄 | 896 / 914（98%） | **18 個 K 目錄未附 README**——違反 CLAUDE.md 第 3 條 |
| 無 `*results.json` 的 K 目錄 | **191** | 超過 20%（191/914） |
| Knowledge 中提及的 K 編號 | 954 distinct（`K[0-9]+` tag） | `grep -oE 'K[0-9]+' storage/memory/knowledge.json` |
| K 目錄有但 knowledge 無 | **100** | 孤兒實驗（未登記） |
| K 編號 knowledge 有但目錄無 | **190** | 可能命名不一致、或目錄被刪 |

**Root-level 未整理**：`git status` 顯示 1,323 個 `D`（deleted）檔中，**1,305** 個是 `experiments/...` 下的舊式 flat 檔（如 `experiments/I1_garch_ohr.py`）——這些是過去的 root-level 腳本被遷移到子目錄後留在 git 歷史的痕跡。需要一次 commit 才能結清。

### 1.7 Cron / 排程

來源：CLAUDE.md 第 430-480 行 + `config/runtime_schedules.json`（存在）。

**系統 crontab（永久、無需 session）**：
- `0 15 * * 1-5` — `collect_tw_data.py`
- `30 5 * * 2-6` — `collect_us_data.py`
- `3 0 * * 2-6` — `daily_update.py`
- `3 */2 * * *` — `release-pool-by-settings`（每 2 小時釋 1 篇）

**Session cron（每 session 重建；CLAUDE.md 列 5 條）**：標準啟動集含任務審視（`3 9 * * *`）、會員問題（`17 */6`）、平台巡檢（`37 */6`）、知識索引（`7 */6`）、token 日報（`23 22`）。

**雲端 trigger**：`platform-ops-patrol` 已遷移至 `trig_01HzWX2ZUmsGHnzwciGpHeNz`（6 小時一次）。

### 1.8 Feed 統計

來源：`jq` on `storage/reports/feed.json`（未 Read 整檔）。

| 指標 | 數字 |
| --- | --- |
| 總文章 | 915 |
| `status=published` | 910 |
| `status=unpublished` | 5 |
| audience `research` | 542 |
| audience `general`（一般讀者） | 256 |
| audience `unknown` | 77 |
| audience `daily` | 32 |
| audience `member_qa` | 8 |
| 最新 published_at | `2026-04-17T03:24:01+00:00` |
| Top tags | 研究(583) / SPY(335) / 一般讀者(296) / 波動率預測(248) / VIX(181) |

---

## Section 2：使用者故事（User Stories）

### 2.1 一般投資人（USER-1，訪客，非登入）

- **As a** 台灣個人投資人  
- **I want** 看到今天的策略建議（買/賣/持有、權重、VIX regime 解讀）  
- **So that** 我能在盤前知道今天該做什麼，不用自己跑模型

| 面向 | 內容 |
| --- | --- |
| 關鍵頁面 | `/`（Feed）、`/risk-forecast`、`/vix-calculator`、`/portfolio`、`/strategy-selector` |
| 支撐機制 | `daily_update.py` 的 `generate_daily_article` + VIX regime 解讀（5 級） + `paper_trading.json` |
| 滿足程度 | **強**：910 篇已發佈文章、每日建議自動發、圖表嵌入共用模組 `volpred.charts` |
| 風險 | audience=`unknown` 77 篇（8.4%）未明確分級——可能混淆讀者期待 |

### 2.2 進階 / Premium 會員（USER-2）

- **As a** 付費會員  
- **I want** 提交我的問題，72 小時內拿到基於本專案研究資料的回答  
- **So that** 我能把這裡當「私人研究助理」

| 面向 | 內容 |
| --- | --- |
| 關鍵頁面 | `/questions`、`/me`、`/me/questions`、`/me/bookmarks` |
| 支撐機制 | `member-questions` skill、`questions` + `question_articles` table、`question-ranking-workflow` cron |
| 滿足程度 | **中**：audience=`member_qa` 僅 8 篇（0.9%）——會員問答累積量偏低 |
| 風險 | 付費階梯薄弱：`quota_usage` table 存在但免費與付費差異化內容未明顯；`storage/ops/question-ranking-workflow-latest.json` 有記錄但低頻 |

### 2.3 研究者 / 學術同行（USER-3）

- **As a** 財金系同行或期刊審稿人  
- **I want** 看到 9 篇論文的最新版 PDF、完整實驗重製腳本、數據來源  
- **So that** 我能引用、審閱、或驗證結果

| 面向 | 內容 |
| --- | --- |
| 關鍵頁面 | `/paper`、`/about`、`paper/*/main*.pdf` 直連 |
| 支撐機制 | `papers` Supabase table + `paper_public_dir` 靜態 PDF + `reproduce.py`（各論文目錄） |
| 滿足程度 | **強**：9 篇 MS，部分已 `review_v1.1`；`citation-verifier` skill 剛跑過 |
| 風險 | `leverage-direction` 14 個 PDF 版本沒做清理；`AUDIT_PLAN.md` / `REWRITE_PLAN.md` 在 `paper/` 根目錄——不是論文 MS 而是流程文件，放錯位置 |

### 2.4 賴奕豪教授（USER-4，專案主理人）

- **As a** 專案所有人  
- **I want** 一個穩定的本機雙 agent 系統，自主跑實驗、寫文章、改論文，不用我逐步下指令  
- **So that** 我能把時間用在教學與決策，不用當 RA

| 面向 | 內容 |
| --- | --- |
| 關鍵 CLI | `uv run volpred ops *`（已統一 14+ 子指令）、`uv run python scripts/daily_update.py`、Skill 1. 的 slash commands |
| 支撐機制 | CLAUDE.md（623 行）+ `research_program.md`（625 行）+ `agent-specs/guide.md`、Ops job queue、3 層 skill |
| 滿足程度 | **中強**：自動化能力已經高；但文件爆量、skill drift 開始消耗教授的認知負擔 |
| 風險 | CLAUDE.md 623 行讓每次 session 啟動負擔沉重；規則 12 條研究誠實原則執行成本需要持續監控 |

### 2.5 Claude（USER-5，主研究 agent）

- **As an** 自主研究 agent  
- **I want** 明確的研究方向 queue、完整的 preamble、可查的 knowledge + error log  
- **So that** 我做實驗不會重複踩 4 次 lookahead bias 的坑

| 面向 | 內容 |
| --- | --- |
| 關鍵資源 | `research_program.md`（625 行）、`.claude/skills/autonomous-research/references/experiment-preamble.md`、`storage/memory/knowledge.json`、`docs/error_log.md`（343 行、37 entries） |
| 支撐機制 | Idle-driven continuation、反空轉規則、實驗流程 SOP（寫→Codex 審→跑→記→寫文章） |
| 滿足程度 | **中**：規則完善；但 preamble 依賴 agent 主動讀取（`render` 產物漂移可能讓 agent 讀到過時版本） |
| 風險 | worktree 殘留（`frontend-v2-fix/.claude/worktrees/agent-a85ff4df/`）顯示 agent merge 流程曾遺漏 |

### 2.6 Codex / Gemini（USER-6，審查 agent）

- **As a** 第二意見 agent（GPT-Codex 或 Gemini）  
- **I want** 被呼叫時拿到明確任務邊界（scope 不要整 repo）、檔案清單、往返 context  
- **So that** 我能給出針對性建議而不是空泛 review

| 面向 | 內容 |
| --- | --- |
| 關鍵入口 | `/codex:rescue`、`/codex:review`、`/codex:adversarial-review`、`/gemini-cli` |
| 支撐機制 | CLAUDE.md「AI 協作」章節、`docs/ai-collaboration.md`、`agent-result-verification` skill |
| 滿足程度 | **中強**：歷史紀錄顯示 Codex 已 4 次抓到 lookahead bug（K618/621/679/698） |
| 風險 | 若 Claude 不呼叫，Codex 不會主動——流程依賴 Claude 的判斷；Gemini 配額耗盡時策略缺乏自動降級 |

### 2.7 系統維運者（USER-7，賴教授兼任）

- **As the** 唯一系統維運者  
- **I want** 知道每天系統有沒有壞、Supabase 沒爆、Zeabur 部署是綠燈  
- **So that** 我不用每小時檢查

| 面向 | 內容 |
| --- | --- |
| 關鍵 CLI | `uv run volpred ops health`、`platform-cycle-summary-latest.json`、`article-backups.json` |
| 支撐機制 | ops_jobs + ops_job_logs + ops_audit_logs + cloud trigger `platform-ops-patrol` |
| 滿足程度 | **中**：有 health check 但 `storage/ops/rollback_points/` 14GB 沒有自動回收；`storage/ops/executions/` 是空的（機制存在但沒實際累積任務） |
| 風險 | 磁碟增長：rollback 23 個目錄，每個平均 608MB；未監控趨勢 |

---

## Section 3：問題點（Issues & Risks）

### 3.1 Critical（已造成或將造成資料風險）

#### C-1. `.agents/skills/` 159 個 M 檔未 commit，且內容與 canonical 漂移

- **觀察**：`git status --short | grep '.agents/skills' | wc -l` = **52** 條 `M`；加上 `.claude/skills/` 約 107 條、`agent-specs/` 本身 untracked。三層 MD5 比對 `autonomous-research`、`feed-publisher`、`paper-update` 三個 skill 已**三者全部不同**。
- **後果**：Agent 讀到過時 skill → 方法論規則傳遞失敗 → 實驗邏輯回頭踩 lookahead 等已記錄的坑。CLAUDE.md 第 436 行明寫「`CLAUDE.md` 與 `.claude/skills/` 為 render 產物；若原生工具再次改寫…視為 drift event」。
- **已有記錄**：docs/error_log.md 暫無此條目，屬於**新發生**。
- **根因假設**：最近有人（可能是 agent）直接改了 `.agents/skills/` 的檔案但沒回寫到 `agent-specs/`，導致 canonical 落後。

#### C-2. 孤兒實驗／反向孤兒（3 個指標齊發）

- **觀察**：
  - 100 個 K 資料夾不在 knowledge.json（dir-only）
  - 190 個 knowledge K 編號不在 experiments/ 下（knowledge-only）
  - 191 個 K 目錄沒有 `*results.json`
- **後果**：違反 CLAUDE.md 研究誠實第 3 條（「實驗必須同時產出：檔案 + 知識庫 + 經驗庫」）。2026-03 已踩過一次（「85/124 只有 results 但不在知識庫」）。這次規模更大。
- **已有記錄**：CLAUDE.md 第 68 行「2026-03 曾發現 85/124 實驗只有 results 但不在知識庫中」——**相同類型的 drift 又發生了**。
- **說明**：反向孤兒（knowledge-only）可能是命名慣例差異（例如 `K474` 在 knowledge 但目錄是 `k474_foo_bar/`——而非缺失）。但 dir-only 100 個 + 無 results 191 個不能用命名解釋。

#### C-3. `frontend-v2-fix/.claude/worktrees/agent-a85ff4df/` 殘留

- **觀察**：該 worktree 於 Apr 4 建立，至今未清理；內含完整的 Next.js 專案鏡像（data/Dockerfile/src/storage/supabase/... 全部複製）。`git worktree list` 只顯示 main 一條，代表這是**孤兒** worktree（git 本身已遺忘）。
- **後果**：磁碟浪費（可能數百 MB）、未來 agent 誤把它當 active workspace、混淆 merge。
- **已有記錄**：docs/error_log.md 有 K1032「merge_worktree.sh 判斷 no commits 但 reflog 有 commit 導致遺失」——這條是**相同機制的另一個失敗模式**。
- **相關規則**：CLAUDE.md 明禁 `git worktree remove --force`，要用 `bash scripts/merge_worktree.sh`。

#### C-4. `knowledge.json` JSON 結構損壞

- **觀察**：`json.load` 失敗 in `Extra data: line 26548 column 2`；檔尾 `]}\n]}\n]\n` 有雙重 close-bracket，明顯是 append 時 atomic replace 失敗。
- **後果**：任何直接 `json.load` 的腳本會崩潰；knowledge 索引只能靠 grep / 手動修復。
- **已有記錄**：無具體條目，但 CLAUDE.md 禁 Read 整檔——推測用戶已知問題，但未記錄修復方案。
- **補救**：手動修復尾端、加 schema 驗證後才寫入。

#### C-5. `storage/ops/rollback_points/` 14GB

- **觀察**：`du -sh storage/ops/*` 顯示 14G 幾乎全在 rollback_points，23 個目錄名都是 `kXXX_safe_migration_YYYYMMDDTHHMMSSZ`。
- **後果**：Time Machine / iCloud / 備份容量爆、git repo size 膨脹（雖然多數在 .gitignore 但確認一下）。
- **已有記錄**：無。屬於新發現。

### 3.2 High（影響運作效率）

#### H-1. `research_program.md` 625 行（規則要求 < 500）

- **觀察**：`wc -l research_program.md` = **625**。CLAUDE.md 原文「research_program.md 每月初存檔瘦身」+「目標 < 500 行」。
- **後果**：Context window 壓力、agent 啟動成本增加。
- **已有記錄**：CLAUDE.md 第 258 行。

#### H-2. `CLAUDE.md` 623 行 / 47KB

- **觀察**：本分析是在已讀入 623 行 CLAUDE.md 的前提下進行。許多段落（研究誠實原則 13 條、Token 節約規則、每日文章產出要求）已臨界「規則爆量」——人類很難記住 13 條原則。
- **後果**：維護成本高；新 session 每次都要重新「載入」所有規則。
- **已有記錄**：無具體記錄，但用戶偏好「CLAUDE.md 不拆分」（見 `feedback_claudemd_keep_inline.md`）——所以必須找其他瘦身策略。

#### H-3. 三層 skill canonical 漂移風險

- **觀察**：見 C-1。但更深層的問題是：沒有 CI 或 pre-commit hook 偵測「三層 MD5 不一致」。
- **後果**：隨時間拉長漂移幅度會更大。
- **已有記錄**：CLAUDE.md 第 436 行提過「drift event」但沒有 enforcement。

#### H-4. Session cron 空轉歷史

- **觀察**：`docs/error_log.md` 第 258-289 行「2026-03-31 Session Cron 空轉 6-8 小時」已有詳細記錄；CLAUDE.md 第 512-522 行新增反空轉規則。
- **後果**：過去已發生；規則建立後沒有自動化檢測機制——靠 agent 自律。
- **補救方向**：寫一個 `storage/ops/session_state.json` 的異常偵測腳本，發現連續 N 次 idle 就 alert。

#### H-5. Experiment README 覆蓋率 98%，但 18 個 K 目錄缺 README

- **觀察**：CLAUDE.md 第 29-33 行「README.md 是必備的」。18 / 914 = 2% 違規率看似小，但**規則說絕對必備**。
- **後果**：違反研究誠實原則第 3 條。

### 3.3 Medium（可接受但需改善）

#### M-1. Error Log 37 entries，lookahead bias 重複 4 次

- **觀察**：`docs/error_log.md` 343 行、37 個帶日期的 table row；CLAUDE.md 明寫「Codex 審查已 4 次抓到 lookahead（K618, K621, K679, K698）」+ 2026-04-13 K1121/K1124 再度抓到兩個。
- **後果**：lookahead 是**最常見的結構性 bug**，規則靠「agent 主動檢查」無法 100% 防範。
- **已有記錄**：CLAUDE.md 第 243-261 行詳述；已經寫入 `signal.shift(1)` 硬性要求。但再犯代表：規則寫了但沒有 CI / lint。

#### M-2. 研究誠實原則 13 條執行成本高

- **觀察**：原則 1–13，外加 3/5/6/6b/12 的細則。每個實驗要過所有檢查，負擔沉重。
- **後果**：agent 可能「檢查疲勞」、忽略邊緣條件。
- **補救方向**：把 13 條轉成 checklist（agent 填對勾），不是 prose。

#### M-3. 一般讀者 → premium 付費階梯薄弱

- **觀察**：audience 分布 research(542) / general(256) / member_qa(8)。member_qa 只有 8 篇意味著付費使用者黏著度沒建立。
- **後果**：變現能力弱。

#### M-4. `storage/memory/experiments.json` 3 週未更新（Apr 16 vs Mar 22）

- **觀察**：`ls -lh storage/memory/experiments.json` = 295K / Mar 22 00:08。其他 memory 檔已到 Apr 11-16。
- **後果**：這個檔可能已被 `knowledge.json` + `experiment_experiences.json` 取代但沒正式 deprecate，造成讀者困惑。

#### M-5. 論文版本爆炸（`paper/leverage-direction/` 14 個 PDF）

- **觀察**：ls `paper/leverage-direction/` 有 14 個 `.pdf`——超過 `docs/paper-guide.md` 的 v1/v2/review_v1 命名規則容量。
- **後果**：論文目錄難以追蹤最新版；`main.pdf` vs 各版 `review_vX.pdf` 容易混淆審稿者。

#### M-6. Git status 1,323 個 D 檔未結清

- **觀察**：99% 是 `experiments/` 下 flat 舊檔（已遷移到子目錄）。該做一次 `git rm` + commit 結清。
- **後果**：每次 `git status` 噪音太大，難以看清實際工作變更。

---

## Section 4：改進建議（Recommendations）

### 4.1 立即（本週內，< 3 天）

#### I-1. 清 skill canonical drift

- **做什麼**：(a) 先 `md5` 掃 17 個 skill 的三層是否一致；(b) 不一致的用 `agent-specs/` 為準，重新 render 到 `.agents/` 和 `.claude/`；(c) 加 pre-commit hook 阻止直接改 render 產物。
- **工作量**：中（6-8 小時）
- **預期效益**：防止 Claude agent 讀到過時 skill 而邏輯錯誤（影響所有實驗）
- **相依**：需要確認 `src/volpred/ops/agent_spec.py` 的 render 指令還能跑
- **對應問題**：C-1、H-3

#### I-2. Worktree 殘留清理

- **做什麼**：(a) 檢查 `frontend-v2-fix/.claude/worktrees/agent-a85ff4df/` 有無未 commit 變更；(b) 若無，`rm -rf` 或正式 `git worktree prune`（不是 force！）；(c) 加 `uv run volpred ops health` 檢查項：「是否有 > 7 天的 worktree」。
- **工作量**：小（1-2 小時）
- **預期效益**：磁碟回收 + 防止未來 agent 混淆
- **相依**：`scripts/merge_worktree.sh` 需驗證 reflog
- **對應問題**：C-3

#### I-3. Rollback points 清理策略

- **做什麼**：(a) 評估哪些 rollback point 是真的保險（最近 30 天）、哪些可歸檔到外部存儲；(b) 對 23 個目錄實施「保留最近 5 個 + 每月 1 個」的 rotation 策略；(c) 寫腳本每週跑。
- **工作量**：中（4-6 小時）
- **預期效益**：回收 ~10GB 磁碟空間
- **相依**：確認沒有外部腳本引用舊的 rollback point
- **對應問題**：C-5

#### I-4. 孤兒實驗快速普查（先不修，先標記）

- **做什麼**：跑一個 `scripts/audit_orphan_experiments.py`（新寫），輸出：(a) 100 個 dir-only K 的清單 + 最近修改時間；(b) 191 個無 results K 的清單；(c) 按實驗日期分 batch（老的 / 新的）。**不做合併只產清單**。
- **工作量**：小（2-3 小時）
- **預期效益**：把 C-2 從「模糊焦慮」變成「具體清單」，才能後續批量處理
- **相依**：無
- **對應問題**：C-2

#### I-5. `knowledge.json` 結構修復

- **做什麼**：(a) 手動編輯檔尾、移除重複的 `]}` 序列；(b) 跑 `python -c "import json; json.load(open('...'))"` 驗證；(c) 在寫入路徑加 temp file + atomic rename。
- **工作量**：小（1-2 小時）
- **預期效益**：讓 knowledge index 重建可以再跑、防止未來 silent corruption
- **相依**：無
- **對應問題**：C-4

### 4.2 短期（本月內，< 4 週）

#### S-1. CLAUDE.md 拆分但不拆出檔案

- **做什麼**：用戶規則是「不拆分檔案」。替代方案：把 CLAUDE.md 改成 **三段層級化**結構——
  - §A「每 session 必讀」（50 行：最高優先規則、token 節約、路徑唯一源頭）
  - §B「情境載入」（100 行：只在特定任務才看，如論文流程、策略上架）
  - §C「參考資料」（剩餘：STRATEGY_REGISTRY 細節、外部數據、Agent Prompt 模板）
- **工作量**：中（1-2 天）
- **預期效益**：新 session 啟動時只真正載入 §A
- **相依**：需用戶同意（遵守「修改既有治理內容前必須取得使用者同意」）
- **對應問題**：H-2

#### S-2. Skill canonical 單一化 + CI

- **做什麼**：(a) 寫 `src/volpred/ops/agent_spec.py verify`：檢查三層 MD5 一致；(b) 加入 pre-commit hook；(c) `uv run volpred ops health` 增加 `skill-drift-check`。
- **工作量**：中（2 天）
- **預期效益**：永久阻止 C-1 / H-3
- **相依**：I-1 需先完成
- **對應問題**：C-1、H-3

#### S-3. Cron 反空轉自動檢測器

- **做什麼**：寫 `scripts/detect_cron_spin.py`：讀 `storage/ops/session_state.json` + feed 發佈時間，若發現（a）> 3 小時無新文章、或（b）連續 5 次 idle 無實際 diff，寫入 `storage/ops_alerts/`。
- **工作量**：中（1-2 天）
- **預期效益**：把 CLAUDE.md 反空轉規則從「靠 agent 自律」變成「系統自動 alert」
- **相依**：無
- **對應問題**：H-4

#### S-4. 前端 lookahead 防火牆（CI 級別）

- **做什麼**：寫 `scripts/ci_lookahead_lint.py`：掃 `scripts/`、`experiments/k1[0-9]*/*.py`，找沒有 `.shift(1)` 或等效 lag 的策略 return 計算，輸出 WARN。加進 `.pre-commit-config.yaml`（如果有）或 `ops health`。
- **工作量**：中（2-3 天；需要 AST 分析不是 grep）
- **預期效益**：從 4 次再犯變成 0 次
- **相依**：無
- **對應問題**：M-1

#### S-5. Orphan experiments 批量補齊

- **做什麼**：基於 I-4 清單，分 3 批處理——(a) 有 `*_results.json` 但不在 knowledge：用 agent 批次從 results 生成 knowledge entry；(b) 有 README 但無 results：標記為 `status=incomplete`；(c) 無 README：刪除或請 agent 補 README。
- **工作量**：大（1 週 × agent 並行）
- **預期效益**：把 C-2 徹底清零、恢復研究誠實原則第 3 條合規
- **相依**：I-4 + I-5
- **對應問題**：C-2

#### S-6. Research program archive 自動化

- **做什麼**：寫 `scripts/archive_research_program.py`：識別 research_program.md 中 `已完成 Phase/Session` 段落，移到 `docs/research_archive/completed_phases_YYYY-MM.md`，留下追蹤表。
- **工作量**：小（半天）
- **預期效益**：`research_program.md` 保持 < 500 行
- **相依**：無
- **對應問題**：H-1

### 4.3 中期（下一季，1-3 個月）

#### L-1. USER-1 → USER-2 付費階梯

- **做什麼**：(a) 會員專屬內容標籤（如「策略 alpha 細節」、「即時 VIX alert」）；(b) `quota_usage` 實作流量限制；(c) `member_qa` 從 8 篇提升到 100+；(d) 免費 vs premium 差異化頁面。
- **工作量**：大（1-2 個月）
- **預期效益**：實現商業可持續
- **相依**：前端已有 `/me` / `/me/questions` / `/me/bookmarks` 基礎
- **對應問題**：M-3

#### L-2. 論文產出 SOP 強化

- **做什麼**：(a) `paper/leverage-direction/` 14 個 PDF 瘦身（只留 main.pdf + 最新 review）；(b) 寫 `uv run volpred ops paper-archive --paper-id xxx --keep-latest`；(c) `paper/AUDIT_PLAN.md` / `REWRITE_PLAN.md` 改放 `docs/paper-workflow/`；(d) 加 `docs/paper-guide.md` 的「版本過多怎麼辦」段。
- **工作量**：中（2 週）
- **預期效益**：論文審稿者容易找到最新版；降低主理人心智負擔
- **相依**：無
- **對應問題**：M-5

#### L-3. Error log 防再犯機制

- **做什麼**：(a) 把 error_log 37 條 parse 成結構化 JSON（`docs/error_log.json`）；(b) 每個實驗 agent 啟動時從 JSON 自動載入「類似場景警告」；(c) 做 `error_log_similarity_check` skill，新 bug 寫入時自動提示「這類似 2026-XX 的 X bug」。
- **工作量**：中大（3 週）
- **預期效益**：把「翻 error log」的認知負擔自動化
- **相依**：需要 embedding 索引（LanceDB 已有）
- **對應問題**：M-1、M-2

#### L-4. Premium 付費後研究供應鏈

- **做什麼**：讓 premium 會員問題直接 enqueue 為高優先 `user-assigned` task，保證 72 小時回覆。建立 SLA dashboard。
- **工作量**：中（1 個月）
- **預期效益**：產品化
- **相依**：L-1
- **對應問題**：M-3

#### L-5. Memory system schema 正規化

- **做什麼**：把 `experiments.json`、`knowledge.json`、`thinking_journal.json`、`experiment_experiences.json`、`open_questions.json`、`research_log.json` 統一：(a) 每個檔案有 schema.json；(b) 寫入走 `src/volpred/memory/*` 的 typed API（已有骨架？待確認）；(c) deprecate `experiments.json`（3 週未動）。
- **工作量**：大（1 個月）
- **預期效益**：防止 C-4 類的結構損壞；知識可程式化查詢
- **相依**：無
- **對應問題**：C-4、M-4

---

## 附錄 A：關鍵統計數字索引

| 指標 | 數字 | 取得指令 |
| --- | --- | --- |
| `git status` 總變更 | 2,290 | `git status --short \| wc -l` |
| 其中 untracked (`??`) | 808 | `awk '{print $1}' \| sort \| uniq -c` |
| 其中 deleted (`D`) | 1,323 | 同上 |
| 其中 modified (`M`) | 159 | 同上 |
| `.agents/skills/` M 檔 | 52 | `git status --short \| grep '.agents/skills' \| wc -l` |
| experiments 子目錄數 | 1,316 | `ls experiments/ \| wc -l` |
| K-prefix 目錄 | 914（distinct 864） | `ls ... \| grep -iE '^k[0-9]'` |
| K 目錄無 README | 18 | bash loop |
| K 目錄無 results | 191 | bash loop |
| knowledge.json entries | 1,232 | `grep -c '"item_id"'` |
| knowledge K tags (distinct) | 954 | `grep -oE 'K[0-9]+' \| sort -u \| wc -l` |
| experience entries | 74 | `grep -c '"id": "E'` |
| thinking journal entries | 813 | `grep -c '"id":'` |
| open_questions | 19 | `grep -c` + head inspection |
| feed entries | 915 | `jq 'length'` |
| published articles | 910 | `jq '[...] \| length'` |
| research_program.md 行數 | 625 | `wc -l` |
| CLAUDE.md 行數 | 623 | `wc -l` |
| error_log.md 行數 | 343 | `wc -l` |
| error_log entries | 37 | `awk` table count |
| storage/ops 大小 | 14GB | `du -sh` |
| rollback points | 23 個目錄 | `ls \| wc -l` |
| 論文數 | 9 | `ls paper/` |
| skill (三層各) | 17 | `ls <layer>/skills/ \| wc -l` |
| 前端頁面 | 27 | `find ... -name 'page.tsx'` |
| scripts 數 | 102 | `ls scripts/` |
| src/volpred 子模組 | 12 | `ls -d src/volpred/*/` |

## 附錄 B：需用戶決策的事項

以下項目**建議不由 agent 自主執行**，需賴教授決定：

1. **CLAUDE.md 分段重構（S-1）**：涉及治理文件既有結構變更，按 CLAUDE.md 第 554 行「刪除或改寫既有治理內容前必須取得使用者同意」。
2. **Rollback points 批量刪除（I-3）**：刪掉後就回不來；建議讓教授親自確認哪些可以丟。
3. **`paper/leverage-direction/` 14 PDF 瘦身（L-2）**：涉及論文歷史版本，可能教授對某幾版有特別偏好。
4. **`experiments.json` deprecate（L-5）**：需要確認沒有程式依賴。
5. **Premium 付費階梯策略（L-1、L-4）**：商業決策，屬用戶專屬判斷。

以下項目**可由 agent 自主執行**（有明確規則支撐）：
- I-1（skill drift 修復：用 canonical 覆蓋 render）
- I-2（worktree 殘留清理：有 `merge_worktree.sh` SOP）
- I-4（孤兒實驗普查：只產清單不動資料）
- I-5（knowledge.json 結構修復：屬 C-4 資料完整性）
- S-2、S-3、S-4、S-6（CI / 工具類）
- M-6（git status 結清：該做 `git add -u && git commit`）

---

*本報告由 Claude 作為 subagent 於 2026-04-17 執行，只讀分析，未修改專案任何檔案。所有統計資料來自當時的倉庫快照。後續若要執行任何「改進建議」，請先在 `research_program.md` 對應面向中登記、或建立 task 到本機控制面。*
