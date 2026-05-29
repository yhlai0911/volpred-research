# VolPred 重新擘劃 Master Plan（2026-05-29）

> 依 `VISION.md`（全自動不間斷自我運營 → 盈利）重新擘劃前後端 + 控制面 + 研究/內容/曝光/變現 pipeline + 治理文件。
> 來源：主線程 session audit + 3 份平行架構盤點（後端 / 前端 / 指引文件，2026-05-29）。
> 執行隔離：結構性重構在 `../volpred-refactor` worktree（branch `refactor/autonomy-overhaul`，錨點 tag `stable-pre-refactor-20260529`）；純清理與文件更新可在 main。
> ⚠️ 治理文件（CLAUDE.md / .claude/rules）改寫前需用戶同意（已在 §6 列清單待核）。
> ⚠️ explorer 結論需主線程驗證才採信（已知誤報：docs explorer 誤稱 memory 僅 1 檔；實際數十檔 + MEMORY.md 健在）。

---

## 0. 一句話診斷
願景清晰、底層模組品質高，但**控制面碎片化（5 層重疊）、腳本/文件膨脹（~70 廢棄腳本 + 35% 文件重疊）、商業化與可復現展示薄弱**。地基（自動化可靠性）是最高槓桿，必須先修。

---

## 1. 現況評估（三層）

### 1.1 後端
- **5 層重疊控制面**：LaunchAgent + piggy-back scheduler + session crons + hourly dispatch + task pool；雙/三 fire 位點多、狀態同步 race。
- **dispatch_supervisor 重構卡 4/8**（D1-D4 完成；D5-D8 = categorize 抽象 / session replay / RPC socket / piggy-back 遷移未做）。**這就是 5 層收斂成 1 層的正解。**
- **213 腳本 ~70 冗餘**（test_*/experiment_*/_*/rough_* ~31、publish_k*.py 35+、generate_diverse+research_backlog 重複、continue_task_stub 遺物）。
- **資料管線缺樞紐**：FRED 無定時抓取（只有 backfill guard）、collect_5min 無排程、event 來源靠手動硬編日期；磁碟 JSON 接力延遲 1-4h。
- **可復現**：三件套 100% 落實、provenance gate 已建（新條目受管），但歷史 284+ 違反待補；無「paper body vs knowledge.json 數字一致性」自動檢查（K562 漂移風險）。
- 底層 models/evaluation/publisher/memory 模組品質高，保留。

### 1.2 前端（frontend-v2-fix，Next.js 15 + React 19 + Supabase）
- **~70% 對齊願景**。文章分流（research/general/member_qa）+ badge + SEO（sitemap/og）完整；策略追蹤、risk-forecast、會員區、admin 有。
- **最大缺口 = 商業化**：付費漏斗/升級 CTA/支付集成/付費牆**全無或極弱** → 直接卡住盈利願景。
- **可復現展示弱**：paper 只有列表、無 `/paper/[id]` 詳頁、無「資料/程式下載」入口 → 損學術信譽。
- **冗餘**：v2 + v3 雙套路由 1:1 鏡像（~20-30% 重複，未完成遷移）；`舊前端/{frontend,frontend-v2}` 未部署可刪；`/portfolio`→`/admin/paper-trading` 公開/內部混淆。
- 缺 error.tsx/not-found.tsx；image unoptimized；canonical/hreflang 缺。

### 1.3 指引文件（CLAUDE.md + 10 rules + 18 skills + 50+ docs）
- **重疊 35%、single-source 遵守 55%**。
- **AGENTS.md 80% 重複 CLAUDE.md + 路徑過時（.agents/）+ Codex plugin 已廢** → 該歸檔。
- **scheduler 規則 4-way 散落**（control-plane / alert / publishing / architecture）→ 改一次要改 4 處。
- **publishing.md 60% 重疊 feed-publisher SKILL**；FB SOP 散 3 處。
- **architecture.md（4/19）+ system_handbook 嚴重 stale**（描述已廢的 3-terminal supervisor-worker，沒涵蓋 LaunchAgent+piggy-back+codex_loop+dispatch_supervisor 真實架構）。
- **15+ 一次性 audit 文件混在 docs/ 主目錄**（噪音 30%）→ 該歸檔 `docs/archived/`。
- context-hygiene.md path-trigger 失效（planning 階段不 load）。
- 數個可能廢棄 skill（anti-ai-style 內嵌、external-data-sources 應降 reference、memory-health 被 CI 取代、worktree-merge-verification 已規則化）— **需查 work_log 使用記錄再定**。

---

## 2. 目標架構（重新擘劃）

### 2.1 控制面：5 層 → 1 樞紐 + 3 消費端
單一 `dispatch_supervisor`（long-lived，LaunchAgent KeepAlive RunAtLoad）為唯一排程樞紐：讀 runtime_schedules → croniter 評估 due → timeout-wrapped 執行 → 統一 last_run/event/session replay/alert/email；開 RPC socket 供查詢/觸發/解鎖。消費端：(2a) task pool（next_tasks.json 唯一 pending queue + ops/tasks 純 audit）(2b) agent sessions（claude/codex，無內部 cron）(3) 觀測+email。**消滅雙 fire、空轉 heartbeat、競爭 daemon、ScheduleWakeup 斷鏈。**

### 2.2 後端：模組保留 + 腳本瘦身 + 資料樞紐
- 保留 models/evaluation/publisher/memory；發佈統一 `publish_draft.py --kid --type`；任務生成統一進 supervisor auto_refill；建 DataPipeline（collect 直寫、daily_update 讀）。
- FRED/5min/event 自動排程補齊（願景「不間斷抓資料/追事件」）。
- paper-publish CI gate：body cite 的 K-id 必在 knowledge.json 且 provenance complete。

### 2.3 前端：商業化 + 可復現展示 + 設計統一
- **商業核心**：`/account/upgrade` + 支付（ECPay/Stripe）+ 付費牆 + 訂閱管理。
- **可復現**：`/paper/[id]` 詳頁附資料/程式/結果下載 + reproduce 說明。
- **設計統一**：決定終態（Editorial v3 vs legacy），逐頁遷移、廢另一套；公開 `/strategies` 與內部 `/admin/paper-trading` 分離。
- 補 error/not-found/loading；SEO canonical/hreflang/內鏈強化。

### 2.4 研究/內容/曝光 pipeline（對齊 6 種產出）
- 議題發現加 **selectivity/變現 scoring gate**（學術新穎 × 策略可建構 × 變現潛力 × trending 熱度；重複方向 cool-down）。
- 多軌來源：trending（修停擺）/ economic-event / 會員提問 / knowledge gap / 策略 idea。
- 論文：強制 independent-review gate（reproduce-green ≠ submit-ready）；body-sprint 解 decision→body 卡關。
- 策略：好+穩+cross-OOS+MDD 自動上架追蹤；**標的多元化**（美/台/商品/加密/跨市場）。
- 曝光：FB **headless 化**（消滅 interactive 依賴，對齊「不間斷」）+ SEO 自動化。

### 2.5 治理文件：single-source + 漸進揭露
AGENTS.md 歸檔；scheduler 規則歸 control-plane.md 唯一源（其餘指向它）；publishing.md 縮成政策層、技術細節歸 feed-publisher SKILL；FB SOP 共用 reference；architecture.md/system_handbook 更新到真實架構；15+ audit 歸檔；context-hygiene 補 paths。

---

## 3. 分階段執行路線圖

| Phase | 主題 | 工作 | 位置 | ROI |
|-------|------|------|------|-----|
| **P0 地基** | 控制面整併 | dispatch_supervisor D5-D8 完成 → 收斂 5 層 → cutover（60 天 shadow 後棄舊） | worktree | 最高（穩定性+不間斷） |
| **P1 清理** | 刪冗餘 | 驗證後刪 ~70 廢棄腳本 + 舊前端/ + 歸檔 15+ audit docs | main(安全項)/worktree | 維護 -33% |
| **P2 文件** | 治理優化 | AGENTS 歸檔、scheduler 單源、publishing 縮減、architecture 更新、context-hygiene 補 path（**需用戶核**） | main | single-source +40% |
| **P3 商業前端** | 變現 | 付費漏斗 + paper 可復現詳頁 + 公開/內部策略分離 | worktree | 直接服務盈利 |
| **P4 資料管線** | 不間斷 | FRED/5min/event 自動排程 + DataPipeline 樞紐 | worktree | 願景達成度 |
| **P5 可復現** | 誠實護城河 | 284+ provenance 補修 + paper-publish CI gate | worktree | 學術權威 |
| **P6 內容引擎** | 選題+曝光 | selectivity gate + FB headless + 設計統一 | worktree | 曝光×轉換 |

執行序：P0 先（穩地基）→ P1/P2 並行（清理+文件，低風險快收益）→ P3-P6 依商業優先序。

---

## 4. 可立即執行的安全清理（已/待驗證）
- ✅ 已修：log rotation、handoff KEEP 保留、codex 自動更新、VISION.md。
- 待驗證後執行（reversible）：歸檔 15+ 一次性 audit docs（move 非 delete）；刪 `舊前端/`（確認無 git/build 參考）；標 AGENTS.md deprecated。
- 需逐一驗證不被 import/cron 參考再刪：~70 腳本（分批，每批查引用）。

## 5. 不做的（避免 three-strike 反例）
- 不對 5 層重疊逐個貼 config 補丁（如 double-fire host_crontab_managed）→ 由 P0 dispatch_supervisor 整併根治。
- 不在沒驗證下刪任何腳本/文件。

## 6. 需用戶核可的治理變更（§2.5）
1. AGENTS.md → `docs/archived/`（標已整合進 CLAUDE.md）
2. scheduler 規則統一到 control-plane.md（architecture/alert/publishing 改指向）
3. publishing.md 251→~100 行（技術細節歸 feed-publisher SKILL）
4. 廢棄候選 skill（anti-ai-style/external-data-sources/memory-health/worktree-merge-verification）— 查 work_log 後定
5. CLAUDE.md autonomous-loop 段 → 獨立 `.claude/rules/autonomous-loop.md`

---

## 7. 執行狀態（2026-05-29 更新）

### P1 清理 — ✅ 大致完成（安全項）
- 舊前端 515MB → Trash；16 死腳本刪除（驗證無引用，scripts 179→163）；12 文件歸檔（11 audit + 1 deprecated）。
- 剩：publish_k*.py 35+ → **需先建 `publish_draft.py` 統一才能刪**（真 refactor，未做）。

### P2 文件優化 — ✅ 安全項完成；2 項判定為 explorer over-reach 不做
- ✅ AGENTS.md 7 處 `.agents/`→`.claude/` 壞路徑（Codex 活躍指令檔）；architecture.md + system_handbook STALE 修正 header。
- ❌ **autonomous-loop 抽離獨立 rule** — 違反 user memory `feedback_claudemd_keep_inline`（CLAUDE.md 不拆，Claude 常忘讀外部檔）→ **正確做法是不做**。
- ❌ **publishing.md 砍 60%/slim 到 100 行** — 經全文檢視，publishing.md 絕大部分是正當 always-loaded 治理政策（audience gate / 4 層查重 / novelty quota / 失敗模式 / pipe 跳脫）。**治理 rule 的「重複」是刻意 enforcement 冗餘**（rule path-trigger 自動載入並強制；skill 僅 on-demand）→ 搬進 skill 會削弱 enforcement → **正確做法是不砍**。
- ⏳ scheduler 規則「4-way dedup」— 待逐檔驗證是真重複還是 contextual reference 再定（architecture.md 已加指向 control-plane 的 header）。

**方法論教訓**：explorer 的 DRY / single-source 建議**不能直接套用到治理文件** — always-loaded 規則的冗餘常是 enforcement 設計。本 session 共擋下 ~5 個 explorer over-reach（AGENTS 歸檔、memory 計數、context-hygiene path、publishing slim、autonomous-loop 抽離）。

### P0 / P3-P6 — 多 session 工程（非 chat 可完成）
supervisor D5-D8、前端商業化（付費漏斗/可復現詳頁）、資料管線樞紐、provenance 補修、內容引擎 selectivity gate。由 autonomous loop 逐步推進。

---
*Drafted 2026-05-29 by main thread. 對應 worktree branch refactor/autonomy-overhaul。實施逐項驗證後獨立 commit。Status 區 2026-05-29 補。*
