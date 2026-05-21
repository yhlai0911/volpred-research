# Codebase Code Review & Optimization Report — 2026-05-16

**範圍**：volpred-research 全 codebase（~1.27M LOC；1,185 experiments / 170 scripts / 90 src python / 198 frontend ts/tsx / 42 tests）
**方法**：6 個並行 code-reviewer subagent 分區深入審查（core engine / ops+CLI+API / scripts / Next.js 前端 / tests+governance / 跨層 hygiene）+ 主線程整合
**Audit baseline**：Phase 1-3 改進計劃進度（B3.7 + B4.1 outstanding）、`docs/error_log.md` 最近 7 個 incident

---

## 0. Executive Summary

### 整體風險評估

| 維度 | 等級 | 主要原因 |
|---|---|---|
| **研究誠實性** | 🔴 **HIGH** | `evaluation/metrics.py::qlike` 公式錯誤 + `statistical_tests.py::dm_test` HAC 在 h=1 失效 — 主 Evaluator pipeline 用的就是錯的版本 |
| **資料完整性** | 🔴 **HIGH** | 4 個 unauthenticated HTTP mutation endpoint（2 個 FastAPI、2 個 Next.js）+ `feed.json` 4 個 writer 缺 lock / atomic |
| **平台運維穩定** | 🟠 **MEDIUM-HIGH** | continue_task_stub 缺 lock / hang cap（dual-cron 模式重現）+ 3 個 next_tasks writer race |
| **文件治理** | 🔴 **HIGH** | AGENTS.md 與 CLAUDE.md 直接矛盾（next_tasks.json 角色） + `.agents/skills/` 空目錄但 AGENTS.md 仍引用 |
| **測試覆蓋** | 🔴 **HIGH** | `cli.py` (2961 LOC) / `evaluator.py` / `models/garch/*` / `engine/rolling_forecast.py` 全部 **零測試** |
| **依賴 / Hygiene** | 🟡 **MEDIUM** | 6 個 dead deps + 6 個應該降到 optional + 大量 `.DS_Store` 與 cache parquet 進 repo |

### Top 10 應立即修

| # | Severity | File:Line | 一句話 |
|---|---|---|---|
| 1 | 🔴 CRIT | `src/volpred/evaluation/metrics.py:25` + `evaluator.py:205` | QLIKE 公式錯（用 `a/f + log(f)` 不是 Patton 的 `r - log(r) - 1`），主 pipeline 全用錯 |
| 2 | 🔴 CRIT | `src/volpred/evaluation/statistical_tests.py:26` | DM HAC loop 是 `range(1, h)` → h=1 時迴圈空轉，等於沒做 Newey-West |
| 3 | 🔴 CRIT | `frontend-v2-fix/src/app/api/sync/[...path]/route.ts:206` | `POST /api/sync/*` **完全無 auth** — 任何人可覆蓋 feed/risk/memory 全表 |
| 4 | 🔴 CRIT | `frontend-v2-fix/src/app/api/publications/publish/route.ts:4` | `POST /api/publications/publish` 無 auth — 可任意發佈到正式 feed |
| 5 | 🔴 CRIT | `src/api/routers/publications.py:56` | FastAPI `/api/publications` `publish` endpoint 同樣無 auth gate |
| 6 | 🔴 CRIT | `frontend-v2-fix/src/lib/admin-auth.ts:24` | `OPS_ADMIN_TOKEN` 缺值時 fallback 到 `SUPABASE_SERVICE_ROLE_KEY` 當 admin bearer |
| 7 | 🔴 CRIT | `AGENTS.md:73-82` vs `CLAUDE.md` Source-of-Truth 段 | next_tasks.json 角色定義直接矛盾 → Codex subagent silent deadlock |
| 8 | 🔴 CRIT | `AGENTS.md:17,100,120,...` | 引用的 `.agents/skills/` 是空目錄 — Codex 永遠載不到 skills |
| 9 | 🔴 CRIT | `src/volpred/publisher/publisher.py:597` (`unpublish`) + `ops/content.py:374,704` | feed.json 3 個 writer site 仍缺 lock 或 atomic rename（與 Phase 3 #17 fix 同類） |
| 10 | 🔴 CRIT | `scripts/cron_continue_task_stub.sh` | 缺 `flock` + perl alarm hang cap — 2026-05-16 dual-cron incident 同 root cause |

---

## 1. CRITICAL — 必須在 7 天內修完

### 1.1 研究誠實性 — Evaluation 層公式 bug（CRIT-A1)

**影響**：每一篇用 `volpred.evaluation.Evaluator` 跑出的 K 結果，QLIKE 數字與 DM p-value 都不是 Patton/HLN 標準。包含已發佈的 feed 文章與已 closed 的 knowledge entries。

**根因**：codebase 同時存在兩套統計實作：
- `src/volpred/stats/model_evaluation.py` — **正確**版本（Patton QLIKE、HAC DM with `range(1, max_lag+1)`）
- `src/volpred/evaluation/metrics.py` + `statistical_tests.py` — **錯誤**版本（QLIKE = `a/f + log(f)`、HAC = `range(1, h)`）

而 `Evaluator.compare_models` (`evaluator.py:182, 205, 217`) 全部 import 的是錯誤版本。

**Fix（< 30 min）**：
1. `metrics.py:17-25` → 改成 `ratio = a/f; return float(np.mean(ratio - np.log(ratio) - 1))`
2. `statistical_tests.py:26` → `for k in range(1, h + 1):`
3. `evaluator.py:205` → 同 1
4. 加 unit test：`tests/test_evaluation_metrics.py` 用三個 analytical 案例（perfect forecast → 0；over-forecast/under-forecast 對稱性）

**追溯（必做，研究誠實原則第 6 條）**：
- 列出最近 3 個月所有 `evaluator.compare_models` 跑出的 K，標 `requires_revision`
- 不可刪除舊結果，只能改 `closure_status=requires_revision` + `qlike_implementation_bug=true`

### 1.2 安全性 — 4 個 unauthenticated mutation endpoint（CRIT-B/D）

| 路徑 | 方法 | 可造成 |
|---|---|---|
| `frontend-v2-fix/src/app/api/sync/[...path]/route.ts` | POST/PUT | 覆蓋 feed/risk_forecasts/paper_trades/memory/questions 任何表 |
| `frontend-v2-fix/src/app/api/publications/publish/route.ts` | POST | 發佈任意內容到正式 feed |
| `src/api/routers/publications.py::publish` | POST | 同上 + 觸 Supabase push |
| `frontend-v2-fix/src/app/api/notifications/route.ts` | GET | 讀任意 server filesystem path（小風險，但無 auth） |

**Fix（< 1 hr 全部）**：
1. 三個 mutation endpoint 加 `authorizeOpsAdmin` (Next.js) / `Depends(require_research_mirror_token)` (FastAPI)
2. `admin-auth.ts:24` 移除 `process.env.SUPABASE_SERVICE_ROLE_KEY` fallback；強制 production 設 `OPS_ADMIN_TOKEN`
3. `strategy-overview/refresh/route.ts:7` 改用獨立的 refresh secret，不重用 service-role key
4. 加 startup warning：若 fallback path 啟用則 log `[security] OPS_ADMIN_TOKEN missing — using SERVICE_ROLE_KEY fallback`

**回測**：用 `curl -X POST https://volpred.zeabur.app/api/sync/feed.json -d '{"test":1}'` 確認 401。

### 1.3 治理矛盾 — AGENTS.md 與 CLAUDE.md（CRIT-E1/E2)

**症狀**：
- AGENTS.md 說 `next_tasks.json` = legacy planning list、`storage/ops/tasks/` 是 canonical queue
- CLAUDE.md 2026-05-04 audit 後說反過來 — `next_tasks.json` = de-facto pending queue
- `.agents/skills/` 目錄是空的（只有 `.DS_Store`），但 AGENTS.md 引用它 7 次當作 Codex 載 skill 的主路徑

**影響**：Codex subagent 按 AGENTS.md 行事就會：
1. 拒絕從 `next_tasks.json` 派工（silent deadlock）
2. 完全載不到 skill preamble — anti-lookahead / multistart / DM-HAC 規則全部缺席 → 直接造成 1.1 那類 bug 持續復發

**Fix（30 min）**：
1. AGENTS.md 全文 `.agents/skills/` → `.claude/skills/`（7 處）
2. AGENTS.md L73-82 改寫成與 CLAUDE.md Source-of-Truth 段一致
3. `.claude/rules/agent-delegation.md:paths` 加入 `storage/next_tasks.json`, `storage/work_log.json`, `storage/ops/**`；移除 dead `scripts/agent_prompts/**`

### 1.4 平台運維 — Shared-state writer race（CRIT-B/C）

**Pattern**：feed.json 與 next_tasks.json 的 writer 還有殘留缺 lock / atomic 的點。Phase 3 #17 部份修了 content.py 兩處，但漏這些：

| File:Line | 問題 | Fix |
|---|---|---|
| `src/volpred/publisher/publisher.py:597` `unpublish()` | bare `open(... 'w')` 無 lock 無 read-back | 套 `shared_state_lock("publisher_feed")` + tmpfile+rename + sync_article 失敗寫 `.failed_supabase_syncs.json` |
| `src/volpred/ops/content.py:374,704` | `dump_json(feed.json)` 在 lock 外呼叫 `_sync_feed_to_remote()` | 把 `_sync_feed_to_remote()` 移進 `with shared_state_lock` block |
| `src/volpred/ops/common.py:26-28` | `dump_json` 用 `path.write_text` 非 atomic | 升級為 tmpfile + `tmp.replace(path)` 模式 |
| `src/volpred/publisher/publisher.py:799` | `_sync_feed_to_remote` `except Exception: pass` 完全靜默 | 至少 print log；理想寫 `.failed_remote_syncs.json` 供 check-alerts 監測 |
| `scripts/refill_task_pool.py:57` + `generate_diverse_tasks.py:68` + `generate_research_backlog.py` | 三個 writer 對 `next_tasks.json` 同時 read-then-write 無 lock | 統一用 `fcntl.flock` 或 `filelock.FileLock`（compute_queue 已用此 dep） |

### 1.5 Cron stub 缺 hang 防護（CRIT-C1）

`scripts/cron_continue_task_stub.sh` 21 行：無 `flock`、無 perl alarm。`cron_check_alerts.sh` 2026-05-16 已修，`cron_hourly_dispatch.sh` 也有兩層防護 — 這隻被漏掉。

**三-strike 觸發**：cron hang 已連兩次（2026-05-13、2026-05-14），且**已看到結構性 root cause（無 single-lock-per-Label、無 hang detect）**，依 CLAUDE.md「strike 3 是 LATEST 不是 ONLY 觸發點」原則應該**現在就 refactor**，不等下一次。

**最小 Fix**：把 `cron_check_alerts.sh` 的 lock + alarm pattern 複製過來。
**長期 Fix**（在 `docs/refactor_plan_cron_dispatch.md` 規劃）：worker daemon + queue + health check 取代 shell + LaunchAgent + perl alarm。

### 1.6 Deploy config 矛盾（CRIT-F1）

`Dockerfile.api:23` 指 `api.main:app` + PYTHONPATH=/app/src；同時根目錄 `zbpack.json` 指 `entry: server.py`（檔不存在）。兩者矛盾 — 其中一個 deploy 會 fail。

**Fix**：確認當前 production API 走哪條路徑，刪掉另一個。建議刪 `zbpack.json` 根目錄版本（active deploy = `frontend-v2-fix/` per `config/project_targets.json`，API 走獨立 Dockerfile.api）。

---

## 2. HIGH — 30 天內修

### 2.1 src/volpred 核心
- `src/volpred/core/custom_model.py:73-74` — `CustomVolModel.fit()` 只 4 starts；CLAUDE.md 規則要求 pooled MLE ≥100. **所有** CustomGARCH/CustomGJR/CustomEGARCH 與實驗模型都繼承這個 base → 全平台 pooled MLE 違規。Fix：base class 強制 `n_starts >= 100`，子類可上調不可下調
- `src/volpred/models/garch/realized_garch.py:47` — `n_starts=5` 太低（8-parameter model）。建議 ≥20
- `src/volpred/evaluation/statistical_tests.py:127` — `christoffersen_test` 把 `alpha = p_hat` 蓋掉傳入的 test level，joint CC LR 從未真的算
- `src/volpred/models/realized_vol/har.py:82-83` — `adj_r2` 公式 `k` 重複扣 1（X 已含 intercept column）
- `src/volpred/engine/rolling_forecast.py:109-111` — `WindowSpec.end` 命名語意模糊（exclusive 但欄位名像 inclusive）→ 易誤改成 lookahead

### 2.2 src/volpred Ops
- `src/volpred/ops/execution_brief.py:37` — `CODEX_EXEC_EXTRA_ARGS = ("--full-auto",)` 是 Codex 0.130 已 deprecated 的 flag（CLAUDE.md 2026-05-14 明寫應改 `-s workspace-write`）
- `src/volpred/publisher/publisher.py:395-401` — `publish_milestone` 24h dedup 用 `dateutil.parser` 包在 bare `except Exception: pass`；dateutil 缺或 parse 失敗就 silent skip dedup → 可能放掉重覆標題
- `src/api/routers/publications.py:30` `get_publication` — `publisher.get_feed(limit=1000)` 整檔讀 feed.json（違 CLAUDE.md token discipline）。改 `publisher.get_report(pub_id)` 即可
- `src/volpred/ops/shared_lock.py:42-63` — non-blocking 模式 yield `False`，caller 若沒檢查就跑 → silent unlocked write
- `src/api/schemas.py:16-22` — `FeedItem` 是 stub，與實際 feed item shape 不符，現在沒被用所以是 dead code，未來接 response model 會直接 schema drift

### 2.3 scripts/
- `scripts/daily_update.py:900-903` — idempotency 只看 first `daily_update` entry；feed.json 排序若被打亂會雙發
- `scripts/merge_worktree.sh:517` — pipefail + `python | sed` 組合，DEDUP-GATE FAIL 可能在到達 `gate_rc=...` 前就被 set -e 殺掉
- `scripts/supabase_sync.py:106` — `_post` 非 409 error 把 body discard 後才 print code；2026-04-12 silent failure 一週的 root cause；保留 body 印出可把 debug 時間從天降到分
- `scripts/cron_continue_task_stub.sh:20` — `echo "exit $?"` 抓的是 dispatch.py 的 exit code，不是 stub.py 的；stub fail 不會觸 `host_cron_fail` alert
- `scripts/cron_continue_task_stub.sh` 全文 — 缺 `set -euo pipefail`、`cd` 用 hardcoded absolute path

### 2.4 Frontend
- `frontend-v2-fix/src/lib/supabase-browser.ts:22` — `flowType: 'implicit'`；`@supabase/ssr` 裝了但完全沒用 → 任何 server-side session-gated content 永遠拿不到 user
- `frontend-v2-fix/src/app/v3/layout.tsx` — `/v3/admin/**` 沒設 `robots: noindex`（`/admin/layout.tsx` 有）。Google 可索引 `/v3/admin/users`、`/v3/admin/content` 等
- `frontend-v2-fix/src/app/api/notifications/route.ts:6-8` — 讀 container filesystem 的 `data/notifications/`，在 Zeabur container 不存在 → silent return `[]`

### 2.5 Tests 覆蓋 — 高優先補
| Module | LOC | 現有 coverage |
|---|---|---|
| `src/volpred/cli.py` | 2961 | **0** — 整個 CLI 入口沒測 |
| `src/volpred/evaluation/*` | ~500 | **0** — QLIKE/DM/Christoffersen 沒測 |
| `src/volpred/models/garch/*` | ~3000 | **0** — gjr/egarch/standard/realized/midas 沒測 |
| `src/volpred/engine/rolling_forecast.py` | ~200 | **0** — rolling pipeline 沒測 |
| `src/volpred/publisher/publisher.py` | 806 | 3 個 narrow methods only — `publish_draft` / `update_article` / `unpublish` / `_sync_feed_to_remote` 沒測 |
| `src/volpred/ops/summaries.py` | 1738 | 37 tests but 全 monkeypatch inner，內部分支實際無覆蓋 |

**最高 ROI**：先補 `tests/test_evaluation_metrics.py`（property-based + 對 analytical 已知值）— 直接守 1.1 那類 bug 再發生。

### 2.6 Hygiene
- `pyproject.toml`：6 個 dead deps（`emd`, `mgarch`, `pypdf2`, `xlrd`, `numdifftools`, `pandas-datareader`）— 整個 codebase 0 import → 直接刪
- `pyproject.toml`：6 個應降到 `[project.optional-dependencies] experiments`（`torch`, `ripser`, `persim`, `pywavelets`, `hurst`, `pytrends`）— 都只在 experiments/ 用，但被打進 production Dockerfile.api image（torch ~2.5GB）
- `.gitignore`：`.DS_Store` 應改 `**/.DS_Store`（root only 規則不會 recursive cover 已 tracked 的 subdir copy）
- `.gitignore`：加 `experiments/**/_cache_*.parquet`、`experiments/**/gdelt_*.parquet`、`experiments/**/data/*.parquet` — 多個 ≥10MB 的 cache 已進 repo

---

## 3. MEDIUM — 季度排程

### 3.1 重複邏輯應合併
- `Publisher._load_feed` 與 `content.py::load_feed` 兩套獨立實作 — 任何行為差異（如錯誤處理）只會 apply 到一邊
- `scripts/refill_task_pool.py` / `generate_diverse_tasks.py` / `generate_research_backlog.py` 三隻各有自己的 `_load_tasks`/`_save_tasks` — 抽到 `src/volpred/ops/next_tasks.py` 並加 lock
- `.env.local` parser 在 `supabase_sync.py:26-39` 與 `build_knowledge_index.py:49-57` 重覆 — src/volpred 該有共用 loader

### 3.2 文件 / Skill 治理
- `.claude/skills/admin-ops/SKILL.md` references index 漏列 `references/scheduling.md`（檔存在但 progressive load 載不到）
- `.claude/settings.json:45-47` 殘留 3 行 hardcoded PID permission（debug session 留下，現在 PID 已對應到其他 process — 給了任意 kill 權）
- `config/runtime_schedules.json:79-92` `shared_scheduler_tick` 已死 14 天，但 spec 還在 → 排程 audit script 會誤判 active

### 3.3 Experiments 目錄健康
- 抽樣 25 個低 K-id (k300-k700) — 18 個缺 `_results.json` (~70%)、`k924`/`k588` script 與 results 都缺
- `experiments/k818_ssvs_return_prediction_results.json` 與 `experiments/k645_results.json` 放錯在 experiments/ 根（應入 subdir）
- 9 個 non-k-id naming dirs（`tda_vol_topology/`, `behavioral_vt_barriers/` 等）— 是 paper-section level work 還是 should-be-K?

### 3.4 Auth 架構統一
目前同時存在 4 套 admin auth：`OPS_ADMIN_TOKEN` / `x-ops-key` / `x-refresh-key` / service-role-as-token。統一成單一 `authorizeOpsAdmin` + 獨立 `OPS_ADMIN_TOKEN`，不要 service-role fallback。

### 3.5 cli.py 2961-LOC 拆檔
建議拆 module：`cli_ops_content`, `cli_ops_tasks`, `cli_ops_agents`, `cli_ops_experiments`, `cli_ops_questions`, `cli_ops_rollback`, `cli_core` + `cli_helpers`（共用 `_parse_json_input` / `_parse_tags` / `_print_json`）。可降 `--help` 載入成本、單檔可測試。

---

## 4. LOW — 隨手清理

- `src/volpred/models/garch/experimental.py:660-661` — 死 `q_last` 算式（後面被覆寫，且公式還是錯的）
- `src/volpred/models/garch/experimental.py:67-70` — EMD fallback `np.convolve(mode='same')` 邊界 artifact
- `src/volpred/models/garch/experimental.py:93` — CARR.fit() 全 4 starts fail 時 `best.x` AttributeError 無 diagnostic
- `frontend-v2-fix/src/app/v3/layout.tsx:29` — Google Fonts `display=swap` → 對 LCP/CLS 不利（目標 #5 流量）
- 10+ Next.js API route 用 `catch (e: any)` + `e.message` only，丟失 stack & Supabase error code
- `texput.log`、`CLAUDE.md.backup.2026-04-11` — 已 gitignore 但 working tree 還在
- `paper_complete.md` / `paper_frl_short.md` / `paper_outline.md` / `research_findings.md` — root clutter，被 `paper/` + `research_program.md` 取代，建議搬 `archive/root-clutter/tracked/`
- `pyproject.toml:6` `readme = "idea.md"` — package metadata 指向個人筆記

---

## 5. 死代碼歸檔候選

### Scripts 可移 `archive/legacy_experiments/`

26 個無 cron / skill / config 引用的 pre-K-era 實驗 script：
```
vt_trend_decomposition.py, experiment_regime_switching_vt.py,
experiment_adaptive_window_var.py, experiment_vol_spillover.py,
experiment_interest_rate_vt.py, experiment_sector_vt_map.py,
experiment_risk_budgeting.py, rough_vol_pilot.py,
experiment_evt_var.py, experiment_fhs_var_targeting.py,
kurtosis_corr_asymmetry.py, vt_tsmom_final_n22.py,
vvix_skew_analysis.py, exp_multi_asset_portfolio.py,
vol_return_prediction.py, experiment_vix_seasonality.py,
btc_allocation_deep_dive.py, experiment_garch_midas.py,
backtest_3yr_us.py, backtest_3yr_final.py,
var_report.py, gbm_qlike_cross_validation.py,
var_backtest_trinity.py, cross_asset_multistep_gjr.py,
master_var_panel.py, phase_u1_panel_garch.py
```

### One-off publish scripts 可歸檔
20+ `publish_k*.py` / `write_articles_*.py` / `append_k*.py` — 一次性 publish 工作，已被 `feed-publisher` skill 取代：
```
publish_k826_article.py, publish_k822_article.py, publish_k812v2_methodology_article.py,
publish_k798_article.py, publish_k767_k768_article.py, publish_k774_article.py,
publish_k738_general_article.py, publish_k672_milestone_article.py,
publish_k464_k467.py, publish_k943_article.py, publish_k940_article.py,
publish_k917_article.py, append_k667_k668_articles.py,
write_articles_k733_k747.py, write_articles_k551_k552.py,
write_3_articles_20260327.py, write_articles_20260327.py,
gen_articles_20260328.py, write_k604_k597_k598_articles.py, write_nfp_articles.py
```

### Frontend
- `frontend-v3-design/` — 沒在 active deploy（per `config/project_targets.json`）。確認 design 已完成 sync 到 v2-fix 後可移歸檔
- `舊前端/` — 已 gitignore 但 working tree 還在，可實體刪除
- `frontend-v2-fix/src/lib/supabase-server.ts:13-18` `createBrowserClient` — 命名 footgun + 看似 unused → 確認後刪除

---

## 6. 跨層 Pattern 總結（三-strike 候選）

以下 pattern 跨 ≥3 domain 重覆出現，已達 CLAUDE.md「結構性 root cause 立即三層 refactor」門檻：

### Pattern 1：**Silent failure on critical I/O**
- `publisher.py:597` unpublish 吞 sync error
- `publisher.py:799` `_sync_feed_to_remote` 全吞
- `publisher.py:395` publish_milestone dedup bare except
- `supabase_sync.py:106` discard error body
- 10+ Next.js routes `catch (e: any)` 只 print message
- `content.py::release_pool_articles` 早期已修，但 pattern 滿天

**結構性 fix**：寫 `src/volpred/ops/io_safe.py` 提供 `safe_write_json(path, data, on_failure="alert+log+pending_file")` + `safe_sync(callable, name, on_failure=...)` 兩個 wrapper。所有 critical I/O 強制走這層。bare except 在 CI lint 階段擋。

### Pattern 2：**Shared state writer 無 atomic + lock 三件套**
- feed.json：unpublish / content.py 兩處 / common.dump_json
- next_tasks.json：3 個 writer
- pattern 共通：read → mutate → write 全無 lock，write 用 `write_text` 不是 tmpfile+rename

**結構性 fix**：`src/volpred/ops/shared_state.py::SharedJsonFile` class，封裝 `with shared_json("feed.json") as f: f.data['x'] = ...`，內部自動 lock + atomic + read-back verify。所有 shared JSON state 強制用這個 class，禁止 raw `dump_json` 對 canonical files。

### Pattern 3：**HTTP mutation endpoint 缺 auth gate**
- `frontend-v2-fix/src/app/api/sync/[...path]/route.ts`
- `frontend-v2-fix/src/app/api/publications/publish/route.ts`
- `src/api/routers/publications.py::publish`
- + multiple legacy admin auth fallbacks

**結構性 fix**：兩端都加 lint/test rule — Next.js API route handler 若包含 `service-role` import 但無 `authorizeOpsAdmin` 呼叫 → CI fail。FastAPI router 同理。

### Pattern 4：**HAC / 統計實作雙版本**
- QLIKE 兩套
- DM test 兩套
- 而 `Evaluator` import 的是錯的那套

**結構性 fix**：刪一套。`src/volpred/evaluation/` 整個收編成 `src/volpred/stats/` 的 thin wrapper（保留 import path 但內部 delegate）。

### Pattern 5：**Cron / dispatch script 缺統一 hang/lock pattern**
- `cron_check_alerts.sh` 有
- `cron_hourly_dispatch.sh` 有
- `cron_continue_task_stub.sh` 沒有 ← strike 累積中
- 任何未來新 cron wrapper 都會再犯

**結構性 fix**：寫 `scripts/lib/cron_wrapper.sh` 提供 `cron_run <label> <cmd> [timeout]` 函式內部含 flock + perl alarm + log redirect。所有 cron stub 套用，不准 raw script。

---

## 7. 與既有 Improvement Plan 的關係

**`docs/project_improvement_status.md` 4-phase plan 進度**：
- Phase 1-2：completed
- Phase 3：B3.1-B3.6, B3.8 done；**B3.7（piggy-back drift assertion）outstanding**
- Phase 4：**B4.1（continue-task launchd plist）outstanding**

**本 review 新發現需加入 Phase 5**（暫定）：
- B5.1 — Auth gate 補齊（CRIT-D1/D2/D3/D4）
- B5.2 — Evaluation 公式統一（CRIT-A1）+ 追溯標記受影響 K
- B5.3 — AGENTS.md 與 .agents/skills 修整（CRIT-E1/E2）
- B5.4 — cron_continue_task_stub.sh 套 lock/alarm（CRIT-C1）→ 同時規劃 `docs/refactor_plan_cron_dispatch.md` 走 worker daemon 三-strike refactor
- B5.5 — Shared state 三件套（lock + atomic + read-back）class 化（Pattern 2）
- B5.6 — io_safe wrapper + bare except CI lint（Pattern 1）
- B5.7 — pyproject deps 瘦身 + Dockerfile.api 對應變更（HIGH-F1/F2）
- B5.8 — 補關鍵測試（cli/evaluator/models/engine）— ROI 最高 = test_evaluation_metrics.py

---

## 8. 快速勝出 Checklist（半天可全做）

```
□ metrics.py:25 + evaluator.py:205 + statistical_tests.py:26 三處統計 bug 修
□ 加 tests/test_evaluation_metrics.py 3-5 個 analytical 案例
□ Next.js /api/sync + /api/publications/publish 加 authorizeOpsAdmin（4 行 × 2）
□ FastAPI publications router 加 require_research_mirror_token Depends
□ admin-auth.ts:24 移除 SUPABASE_SERVICE_ROLE_KEY fallback
□ AGENTS.md sed 全文 .agents/skills/ → .claude/skills/
□ AGENTS.md L73-82 改寫對齊 CLAUDE.md
□ .claude/rules/agent-delegation.md paths 加 next_tasks/work_log/ops
□ cron_continue_task_stub.sh 套 flock + perl alarm（複製 cron_check_alerts.sh）
□ execution_brief.py:37 --full-auto → -s workspace-write
□ publications.py:30 get_feed(limit=1000) → get_report(pub_id)
□ common.py:26-28 dump_json 升級 atomic rename
□ publisher.py:597 unpublish 套 lock + tmpfile+rename + sync 失敗寫 pending
□ supabase_sync.py:106 _post 印出 error body
□ .claude/settings.json 刪 hardcoded PID 3 行
□ .gitignore .DS_Store → **/.DS_Store + 加 experiments cache parquet pattern
□ pyproject.toml 刪 emd/mgarch/pypdf2/xlrd/numdifftools/pandas-datareader
□ zbpack.json 根目錄移除（或補回 server.py）
```

---

## 9. 度量基線（下次 review 對照）

| Metric | 2026-05-16 | 目標（30d） |
|---|---|---|
| CRITICAL findings | 10 | 0 |
| HIGH findings | 18 | ≤ 5 |
| Unauthenticated mutation endpoints | 4 | 0 |
| Modules ≥300 LOC with 0 test | 6 | ≤ 2 |
| pyproject 未用 deps | 12 (6 dead + 6 mis-tier) | 0 |
| Shared JSON writer 無 lock | 5 sites | 0 |
| Bare `except:` in src/ | 4 | 0 |
| `print()` in src/ | 94 | ≤ 30（改 logging） |
| Cron stub 無 hang cap | 1 | 0 |
| Skill SKILL.md dead refs | 1 | 0 |

---

## 10. 致謝 / Review 範圍透明度

- 6 個並行 subagent（feature-dev:code-reviewer）+ 主線程整合
- 採樣涵蓋：全 `src/`、全 `tests/`、全 `frontend-v2-fix/src/`、170 scripts 抽 30 個高 traffic 與 18 個 random、experiments 抽 25 個 random + 8 個 paper-section、全 `.claude/skills` + `.claude/rules` + `config/`
- 未深入審查：`paper/*.tex`（屬論文寫作 workflow 不在 code review 範圍）、`backups/`（gitignored）、`.venv/`（自動產出）、`experiments/` 內個別 K 實驗代碼（佔 ~80% LOC，假設由本就 enforced 的 Codex review gate 守護；只查 trio 完整性與 cache 大小）
- 所有 findings 皆 cite `file:line`，可在 git current state 直接驗證
