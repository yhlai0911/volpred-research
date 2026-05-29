---
title: VolPred 使用者故事對照 + 運作流程檢視 + 優化建議
date: 2026-04-17
author: Claude（Subagent 代勞，UX / Flow audit）
version: 1.0
scope: /Users/yhlai0911/Desktop/volpred-research
method: 只讀分析，未修改任何檔案
previous_report: docs/project_analysis_2026-04-17.md（technical inventory）
---

# VolPred UX 與流程審計（2026-04-17）

> 本報告不是技術盤點（`docs/project_analysis_2026-04-17.md` 已做）。這是 **UX / 流程 / 治理**視角——用 user story 對照 + flow bug 診斷 + 優化建議。目標讀者是主理人賴奕豪教授，讓他能決定「下週、下月、下季」動什麼。
>
> 統計基準時間：2026-04-17 午後。關鍵指標：feed 916 entries（911 published / 5 unpublished，**無 draft**——池子目前是空的）、knowledge 1,239 item_id、next_tasks 40 pending（8 筆 P1-P2 無 created_at）、14GB rollback points、`frontend-v2-fix/.claude/worktrees/agent-a85ff4df/` 仍殘留。

## 摘要（TL;DR）

- **最意外發現**：feed.json 目前 **draft = 0**。article pool 真的空了。CLAUDE.md 明訂「池子不可空超過 3 小時」——但目前除了 5 篇 `unpublished`（2/5 無 published_at 屬於幽靈或過期撤回），沒有 `draft` 可釋出。這個狀態比「5 幽靈草稿」更危急。
- **USER-2（Premium 會員）體驗是最大的商業缺口**：全站 916 篇文章中只有 8 篇 `member_qa`（0.9%）、`/me` 頁面底層 Supabase 表齊全但內容面薄弱、付費「差異化價值」沒有顯化的場景。
- **USER-4（賴教授）決策負擔偏重**：Paper 2 §5 narrative 翻了 4 次（K1144 → K1146 → K1169 → Paper2_section5_decision），顯示決策點散在 next_tasks 卻沒有單一「決策工作流」。3 筆 P1 + 5 筆 P2 無 `created_at`，看不出哪個先來——只能靠教授記憶。
- **USER-5（Claude）最常踩的流程坑**：worktree 殘留（`agent-a85ff4df` 4/4 建立，至今 13 天）、next_tasks 無 priority decay、experiment derivation 無預算上限（K1100g_d1..d7、K1148_d1..d3、K1133/K1134/K1135 重號）。
- **治理母本 vs 產物再次 drift**：三層 skill MD5 不一致、23 筆 rollback points 共 14GB 無人回收、`experiments.json` 3 週未更新但沒正式 deprecate——這些都是「流程有，但沒有 enforcement」。

---

## Section 1：使用者故事與場景（User Stories & Scenarios）

本節列 **18 個 scenarios**，分佈於 7 類 user。每個場景採 BDD 風格：User / Goal / 前置 / 步驟 / 成功定義 / 當前支援。

### USER-1 一般投資人（訪客，非登入）

#### Scenario 1.1：盤前確認「今天該怎麼配置」
- **User**: USER-1 台灣個人投資人
- **Goal**: 早上 8:30 盤前花 90 秒看今天的配置建議
- **前置條件**: `daily_update.py` 已於 08:03 跑完（台灣時間）、`paper_trading.json` 已更新當日權重
- **步驟**:
  1. 用戶打開 `https://volpred.zeabur.app/`
  2. 看 HeroSection → 當日 VIX regime 徽章（5 級）+ 簡短結論
  3. 滑到 FeedBrowser → 找標題含「每日建議」的最新一篇
  4. 讀「市場快照 + 持倉表 + VIX 分析」
  5.（可選）到 `/portfolio` 看 PaperTradingStrategyChart 即時權重
- **成功定義**: 用戶在 90 秒內拿到「今天某某策略應該是 X% SPY + Y% GLD」這種具體指令
- **當前支援狀況**: ✅ 完整——daily_update.py 自動產出「每日策略建議」單篇且包含三段。但 HeroSection 目前**不直接顯示**今日 VIX regime（是 feed 第一篇裡才講），用戶需要多滑一下。

#### Scenario 1.2：用 `/strategy-selector` 決定「我應該選哪個策略」
- **User**: USER-1 風險偏好未知的新訪客
- **Goal**: 「10 個 active 策略到底我該選哪個？」
- **前置條件**: `strategy_metrics_cache` 已同步；前端讀到各策略 Sharpe/MDD/sparkline
- **步驟**:
  1. 用戶點 nav 進 `/strategy-selector`
  2. 看到 10 個策略卡片（Sharpe、MDD、description、90 點 sparkline）
  3. 用戶套條件：「我 MDD 不能超過 -15%」→ 理想上應該有 filter
  4. 用戶比較 `recommended_5050`（-6.6% MDD）與 `simple_12vix`
  5. 點進某一個策略，到 `/portfolio` 看歷史軌跡
- **成功定義**: 用戶在 3 分鐘內挑出 1 個策略並理解其取捨
- **當前支援狀況**: ⚠️ 部分——頁面有了但**缺「決策幫助工具」**。10 個策略用戶根本看不懂區別（smooth VT vs regime-based vs fear DCA）。沒有 quiz、沒有 filter by risk appetite、沒有「推薦組合」。變成一個 menu 而不是 selector。

#### Scenario 1.3：讀完 general 文章想深入研究層
- **User**: USER-1 看完「50/50 為什麼不可動搖」爆款標題文章
- **Goal**: 想知道背後實驗做了什麼
- **前置條件**: 文章末尾有「實驗腳本 experiments/kXXX.py」標注
- **步驟**:
  1. 用戶讀完文章，看到 footer 「*本文基於實驗 K672 的實證結果*」
  2. 用戶點連結 → 應該跳到研究版文章 or GitHub 實驗頁
  3. 若跳到 GitHub → 看 README.md 了解「為什麼、怎麼做、結論」
- **成功定義**: 用戶可以 1 click 從 general 跳到 research 版本
- **當前支援狀況**: ❌ 缺口——目前 footer 是純文字標注，沒超連結；前端沒建立 general → research 的「同主題內鏈」。研究文章 542 篇與 general 256 篇配對關係沒有後設資料。

### USER-2 Premium 會員

#### Scenario 2.1：提交會員問題並追蹤
- **User**: USER-2 付費會員，想問「台股跟美股隔夜 correlation 是多少？」
- **Goal**: 72 小時內拿到基於 VolPred 資料的答案
- **前置條件**: 登入、`profiles.role = premium`、quota 尚未用完
- **步驟**:
  1. 用戶到 `/questions` 填問題 → Supabase `questions` table 寫入 pending
  2. 每 6 小時 `question-ranking-workflow` cron 排名
  3. 高分問題被主理人選中進 `question_articles` 產出回覆
  4. 用戶在 `/me/questions` 看進度（pending / ranked / answered）
  5. 收到 answered 通知 → 閱讀回覆文章
- **成功定義**: 72 小時內 answered，且回覆 1000-2000 字含實驗引用
- **當前支援狀況**: ⚠️ 部分——底層流程齊全，但 member_qa 總計只 8 篇（`audience='member_qa'` count from feed）。代表過去幾個月會員問題其實不多，或是 ranking cron 太保守只挑前 1。

#### Scenario 2.2：看 `/me` 查自己書籤、活動摘要
- **User**: USER-2 回訪會員
- **Goal**: 快速查自己關心的文章、互動紀錄、最近追的策略
- **前置條件**: Supabase `article_impressions` / `article_reactions` 有紀錄
- **步驟**:
  1. 登入後進 `/me` → 看到摘要卡
  2. 點 `/me/bookmarks` → 列出收藏文章（期望：按 tag / 時間 filter）
  3. 點 `/me/questions` → 看自己提問
  4. 回主頁
- **成功定義**: 用戶能在 30 秒內找到「我上次看到哪」
- **當前支援狀況**: ⚠️ 部分——頁面存在，但「個人化 feed」、「續讀位置」、「推薦閱讀」這類黏著機制沒有。

#### Scenario 2.3：評估「為什麼要從免費升級」
- **User**: USER-1 高頻訪客，看了 2 週免費內容
- **Goal**: 理解付費版能得到什麼免費版拿不到的
- **前置條件**: 用戶已登入但仍 free tier
- **步驟**:
  1. 用戶到首頁 → 看到哪些是 premium-only 標籤？
  2. 用戶到 `/about` → 找「訂閱方案」說明
  3. 比較免費 vs premium 的內容差異
- **成功定義**: 用戶理解升級後具體多了什麼
- **當前支援狀況**: ❌ 缺口——沒有明確的 paywall、沒有 premium-only 標籤、沒有 pricing page。即使 `quota_usage` table 存在，前端沒 surfacing。**變現鏈路斷在這一步**。

### USER-3 研究者 / 學術同行

#### Scenario 3.1：下載論文 PDF 並 cite
- **User**: USER-3 同行，看 arXiv 連結來到 VolPred
- **Goal**: 5 分鐘內下載最新版 PDF、拿到正確引用
- **前置條件**: Supabase `papers` table 有該論文；`paper_public_dir` 有 PDF 靜態檔
- **步驟**:
  1. 到 `/paper` 看 9 篇論文列表
  2. 點某篇 → 顯示 metadata（pages、citations、last_updated）
  3. Download PDF → 拿到 `main_v2.pdf`
  4. Copy BibTeX（最好前端提供）
  5. 看 reproduction 連結（`experiments/kXXX.py`）
- **成功定義**: 拿到正確 PDF + 可追溯實驗
- **當前支援狀況**: ⚠️ 部分——PDF 能下載，但 `paper/leverage-direction/` 有 14 個 PDF、`paper/taiwan-vt/` 5 個——對訪客來說哪個是「最新」不夠清楚。前端好一點（只給一個主 URL）但目錄層若 leak 會混淆。沒有 BibTeX 一鍵複製功能。

#### Scenario 3.2：追溯某個文章結論背後的實驗
- **User**: USER-3 想驗證「VIX 充分統計量 31 次驗證」是哪 31 次
- **Goal**: 看到 31 個 K 編號 + 各自的方法論
- **前置條件**: knowledge.json 搜索可用；feed 文章含超連結
- **步驟**:
  1. 文章 footer 寫「*基於實驗 K567 + 30 次獨立驗證*」
  2. 用戶想看所有 31 次 → 目前只能自己 grep
  3. 理想流程：前端提供「相關 K 清單」filter
- **成功定義**: 一次看到 31 個 K 編號、簡短結論、原始 results
- **當前支援狀況**: ❌ 缺口——knowledge 有 1,239 entries 但對外沒 API；前端沒 `/research/k/KXXX` 路由。學術追溯只能透過 GitHub 手翻。

#### Scenario 3.3：審稿者想驗證論文 reproducibility
- **User**: USER-3 JBF 審稿人拿到 Paper 1（leverage-direction）
- **Goal**: 跑 `reproduce.py` 確認表 3 數字
- **前置條件**: 實驗腳本、資料連結、環境可重建
- **步驟**:
  1. `git clone volpred-research`
  2. `cd paper/leverage-direction/ && ls` → 14 個 PDF 混亂
  3. 找 `reproduce.py` → 可能找不到或名字不一
  4. `uv run python reproduce.py` → 希望跑出表 3
- **成功定義**: 一個命令跑出所有論文圖表
- **當前支援狀況**: ⚠️ 部分——各論文目錄有 reproduce 腳本但命名不一致；14 PDF 版本沒有 README 標示「哪個是 accepted」。

### USER-4 賴奕豪教授（主理人）

#### Scenario 4.1：早上 9am 看今日任務
- **User**: USER-4 開電腦
- **Goal**: 5 分鐘決定「今天 Claude 做什麼」
- **前置條件**: `daily_planning` session cron（`3 9 * * *`）已執行、ops CLI 可用
- **步驟**:
  1. 讀 `storage/ops/platform-cycle-summary-latest.json`（最新是 2026-04-09，**已 8 天未刷新**）
  2. 跑 `uv run volpred ops jobs --status queued` 看 backlog
  3. 檢查 next_tasks.json P1 未完成
  4. 決定今日優先方向
  5. 必要時 `uv run volpred ops assign` 派工
- **成功定義**: 5 分鐘內拿到 1-3 個今日焦點
- **當前支援狀況**: ⚠️ 部分——每個資訊源分散：platform-cycle-summary 8 天沒更新、next_tasks.json 有但無 created_at 排序、article-backups 是另一個來源。**沒有統一 dashboard**——教授每天要自己拼。

#### Scenario 4.2：Paper 2 §5 narrative 決策
- **User**: USER-4 本週關鍵決策
- **Goal**: 確認 Paper 2 §5 該用 K1146 universal-magnitude 還是 K1169 correction 還是繼續衍生
- **前置條件**: K1144 (2026-04) → K1146 → K1169 → Paper2_section5_decision（當前 P1 待辦）
- **步驟**:
  1. 教授讀 4 個相關 K 編號 results
  2. 讀 K1148_d1/d2/d3 trilogy 結果
  3. 評估「narrative 該怎麼寫」
  4. 與 Claude 討論
  5. 執行論文修訂
- **成功定義**: 做出決策並 paper-update
- **當前支援狀況**: ❌ 缺口——目前有 **8 個 P1-P2 關於 Paper 2/9 的任務**（K1144/K1146/K1169/Paper2_section5_decision/Paper6_start/Paper9_dual_target/Paper9_bib_fix），但**沒有決策樹或 state machine**。narrative 翻 4 次代表決策支援工具不足。

#### Scenario 4.3：審查 agent 產出的論文修訂
- **User**: USER-4 睡前 10pm 檢查當天 agent 跑的實驗
- **Goal**: 30 分鐘審完今天 5-8 個 agent worktree 的產出
- **前置條件**: Worktree agents 完成 commit、merge_worktree.sh 已 merge
- **步驟**:
  1. `git log --since='today' --oneline` 看 commits
  2. 對每個新 K 編號 → 讀 experiments/kXXX/README.md
  3. 確認 knowledge.json 有對應 entry
  4. 有異常 → `/codex:rescue` 委派審查
- **成功定義**: 確認無 lookahead / 無 worktree 遺失 / knowledge 覆蓋完整
- **當前支援狀況**: ⚠️ 部分——規則在（CLAUDE.md 寫了 merge_worktree.sh），但 `agent-a85ff4df` 從 4/4 殘留 13 天到現在，代表某次流程沒跑完。**沒有自動化「worktree 清潔度」報表**。

### USER-5 Claude（主研究 Agent）

#### Scenario 5.1：Idle-driven slot-aware continuation（新政策）
- **User**: USER-5 主 agent 完成一個任務
- **Goal**: 決定是否啟動下一個（user / scheduled / discovery）
- **前置條件**: `config/runtime_schedules.json` idle_policy 已更新為 2026-04-17 slot-aware（max 3 agents）
- **步驟**:
  1. Agent 完成手上任務
  2. Count `.claude/worktrees/` + background tasks → 若 >=3 跳過
  3. 檢查 user queue（pending P1）→ 有就挑最高優先
  4. 否則 scheduled → 否則 discovery
  5. 啟動時確認「同一 K 編號不重複執行」
- **成功定義**: 產生實際工作（git diff / knowledge entry / 新 agent running）
- **當前支援狀況**: ⚠️ 部分——規則寫了但**沒有 enforcement 腳本**。`agent-a85ff4df` 本身就是「啟動了但沒清理完」的例子。`config/runtime_schedules.json` 有規則但沒檢查器。

#### Scenario 5.2：Agent 完成後善後
- **User**: USER-5 worktree agent 剛 commit
- **Goal**: 主線程把 knowledge / next_tasks / research_program 三件事一起做
- **前置條件**: worktree 有 commit、results JSON 齊全
- **步驟**:
  1. `bash scripts/merge_worktree.sh agent-xxx`
  2. 讀 `experiments/kXXX/*_results.json`
  3. 寫 `storage/memory/knowledge.json`（atomic write）
  4. 更新 `research_program.md` 衍生方向
  5. 決定 derivative 子任務（d1/d2/d3...）
  6. 決定是否發文（research / general）
- **成功定義**: 實驗三件套 + knowledge + experience + 衍生方向都落地
- **當前支援狀況**: ⚠️ 部分——流程在 CLAUDE.md 但**每次 agent 都重複執行 SOP**。沒包成 `volpred ops post-agent-cleanup` 一鍵命令。最近 `knowledge.json` 已被「外部寫入」破壞過一次（corrupted bak file 1.7MB 就是證據）。

#### Scenario 5.3：卡住時 `/codex:rescue`
- **User**: USER-5 同一個 bug 改 3 次還是錯
- **Goal**: 委派給 Codex 接手
- **前置條件**: Codex plugin 就緒、token 尚充足
- **步驟**:
  1. Agent 判斷「改 3 次仍錯」→ 應觸發 rescue
  2. 執行 `/codex:rescue` 給 scope
  3. 等 Codex 回報
  4. 採納修正並驗證
- **成功定義**: Codex 找到根因並給 patch
- **當前支援狀況**: ✅ 完整——K618/621/679/698 + K1121/K1124 共 6 次抓到 lookahead 是證明。但**觸發條件靠 agent 自律**——沒有「改 N 次還錯自動 rescue」。

### USER-6 Codex / Gemini（審查 Agent）

#### Scenario 6.1：Codex 被呼叫審 K1148_d3 代碼
- **User**: USER-6 Codex
- **Goal**: 接到 scope 明確的審查任務
- **前置條件**: Claude 已寫完 K1148_d3 代碼、尚未跑實驗
- **步驟**:
  1. Claude call `codex exec -s read-only "Review experiments/k1148_d3/*.py for lag/TX/baseline bugs"`
  2. Codex 讀明確檔案清單
  3. 回報 HIGH / MEDIUM / LOW 問題
  4. Claude 修正 → 才跑實驗
- **成功定義**: 無 HIGH severity、LOW/MED 可接受
- **當前支援狀況**: ⚠️ 部分——機制完整；但 **Codex quota 多 agents 同時審時爆炸**（K1148_d3 / K1131 / K1148_d2 都遇到）。沒有 quota 管理或 queue 機制。

#### Scenario 6.2：Gemini 提方法論建議
- **User**: USER-6 Gemini 被 `/gemini-cli` 呼叫
- **Goal**: 給方法論第二意見（不一定做代碼）
- **前置條件**: Gemini API 額度尚未用完
- **步驟**:
  1. Claude 問「Paper 2 universal-magnitude 寫法對嗎？」
  2. Gemini 回學術視角評論
  3. Claude 綜合採納
- **當前支援狀況**: ⚠️ 部分——Gemini 額度用完時策略缺自動降級（只在 CLAUDE.md 寫「轉 Codex」靠人記）。

### USER-7 系統維運者（賴教授兼任）

#### Scenario 7.1：發現幽靈草稿
- **User**: USER-7 Premium 會員或維運者看 admin 發現 5 篇奇怪草稿
- **Goal**: 診斷「這 5 篇從哪來、該不該 sync back」
- **前置條件**: `admin/content` 頁面顯示 Supabase drafts
- **步驟**:
  1. 發現 admin 顯示 5 筆 unpublished，但本機 feed.json 只有 5（且 3 筆已有 published_at，是撤回而非草稿）
  2. 診斷 Supabase 是否有本機沒有的 orphan
  3. 決定是 sync-back 還是 DELETE
- **成功定義**: 本機與 Supabase 一致
- **當前支援狀況**: ❌ 缺口——**沒有雙向 audit 命令**。目前 sync 只做「本機→Supabase」incremental。幽靈不會被發現除非有人手動比。

#### Scenario 7.2：文章池空超過 3 小時警報
- **User**: USER-7 晚上 9pm 接到通知（理想）
- **Goal**: 3 小時內補足池子
- **前置條件**: ops_alerts 有 alert 寫入
- **步驟**:
  1. `storage/ops_alerts/` 出現新檔 `pool_empty_YYYYMMDD.json`
  2. 觸發通知到 USER-4
  3. 由 USER-4 啟動 agent 產草稿
- **成功定義**: 池子不空超過 3 小時
- **當前支援狀況**: ⚠️ 部分——`storage/ops_alerts/20260410_061412.json` 有這類 alert（「only 2 drafts, threshold 3」），但 **2026-04-10 之後沒有新 alert**，而今天 **draft = 0**。代表偵測腳本壞了或 cron 沒跑。

#### Scenario 7.3：Supabase egress 爆量
- **User**: USER-7 收到 Supabase 額度 90% 警告 email
- **Goal**: 找 top offender 並止血
- **前置條件**: Mirror API 應該幫忙分流
- **步驟**:
  1. 查 Supabase dashboard egress by table
  2. 檢查 Mirror API 命中率
  3. 找出 top queries
- **成功定義**: 24 小時內降至 50% 以下
- **當前支援狀況**: ❌ 缺口——沒有本地 egress 監控 dashboard。用戶已升級到付費（2026-03-24）買時間但沒根本解。

---

## Section 2：運作流程邏輯問題（Process / Flow Bugs）

本節列 **13 個流程 bug**（非 code bug），按嚴重度分層。重點是「流程設計不對」。

### Critical（正在傷害資料或可信度）

#### FB-C1 Supabase ↔ feed.json 缺雙向一致性驗證（幽靈草稿根因）
- **觀察**：Supabase admin 顯示 5 篇 unpublished；feed.json `status="unpublished"` 也是 5 筆（`mile_5eebba39`、`mile_fccf06c9`、`mile_796eeecc`、`mile_530a28bc`、`mile_b2f3aaed`），其中 2 筆有 `published_at=null`（真草稿）、3 筆有 `published_at`（撤回）。同樣 5 但意義不同。真正的「5 幽靈」指的是：某些只存在 Supabase 不在本機的 orphan。
- **流程根因**：`scripts/supabase_sync.py` 只做「本機 → Supabase」incremental push，沒做「Supabase → 本機」reverse check。任何 2026-04-11~13 期間手動 INSERT 的草稿都成為 orphan。
- **已嘗試補救**：用戶已手動 INSERT / DELETE 但沒有工具化。
- **預估影響**：可信度——admin 顯示與本機源頭不一致，未來若產生 published 差異會出現「網站顯示 A 但本機是 B」。

#### FB-C2 knowledge.json 仍有外部寫入路徑（sanity guard 治標）
- **觀察**：`storage/memory/knowledge.json.bak_2026-04-17_corrupted` 1.7MB 存在，證明最近剛發生過 corruption。commit `f5edd6d2` 加了 post-write sanity guard。
- **流程根因**：沒有 type-safe API 強制所有寫入都走 `src/volpred/memory/*`。worktree agent 雖然禁止寫 knowledge（CLAUDE.md 有明訂）但沒有 **filesystem-level** 強制（比如 read-only 檔案 + CLI 專屬路徑）。
- **已嘗試補救**：sanity guard 是寫入後驗證，不是寫入前攔截。
- **預估影響**：只要有任何腳本不走 typed API，就可能再 corrupt。2026-03 發生過、2026-04-17 又發生。

#### FB-C3 Article pool 空池無自動補齊觸發器
- **觀察**：feed.json 當下 draft = 0、unpublished = 5（但無法釋出因多數有 published_at）。`storage/ops_alerts/20260410_061412.json` 是**最後一次** pool alert（threshold=3）。之後 7 天沒新 alert。
- **流程根因**：CLAUDE.md 有「池子不可空超過 3 小時」規則，但沒有 session cron 執行「池子空 → 自動派 2 個 agent 寫草稿」。alert 只寫檔案不觸發動作。
- **已嘗試補救**：`autonomous-research` skill 有「每 5 個實驗補 2 篇」但沒綁 cron。
- **預估影響**：網站今天可能長時間不更新（池子空 + 事件驅動沒 fire）。

#### FB-C4 `.agents/skills/` / `.claude/skills/` / `agent-specs/skills/` 三層 drift 無 CI 檢查
- **觀察**：上份報告 §1.4 比對三層 MD5，4 個 skill 已不一致。`agent-specs/` 是 canonical 但沒有 hook 阻止直接改 render。
- **流程根因**：render 流程只是「約定」，沒有 pre-commit hook 或 CI。
- **已嘗試補救**：CLAUDE.md 文字上禁止，但靠人遵守。
- **預估影響**：Agent 讀錯版本 skill → 方法論規則失效 → 實驗踩已記錄的坑。

### High（影響效率但可忍）

#### FB-H1 `next_tasks.json` 無 `created_at` / 無 priority decay
- **觀察**：用 python 列 40 個 pending，所有 P1-P2 的 `created_at` 為空。K1146 / K1169 / Paper2_section5_decision 都 P1 但不知哪個先來。
- **流程根因**：next_tasks 是手寫 JSON，enqueue 時沒 enforce timestamp。沒有「P1 > 7 天自動降 P2」機制，backlog 只增不減。
- **已嘗試補救**：無。
- **預估影響**：USER-4 無法快速排序；USER-5 idle-driven continuation 挑 user task 時缺時間線索。

#### FB-H2 Experiment derivative 無預算上限
- **觀察**：`K1100g` 已衍生 d1~d7（g_d5 / g_d6 / g_d7 全在 pending）、`K1148_d1/d2/d3`、`K1133` 重號（兩條都在 pending）。
- **流程根因**：每做完一個 K 就衍生 2-3 個新 K，沒有 stop rule。
- **已嘗試補救**：CLAUDE.md 寫「衍生方向回寫 research_program.md」但沒寫上限。
- **預估影響**：research_program.md 膨脹到 958 行（規則要求 <500 / <700）、next_tasks 永遠清不完。

#### FB-H3 Paper 2 §5 narrative 翻 4 次（決策過度敏感）
- **觀察**：git log 顯示 K1144（pivot to dual-NULL）→ K1146（universal-magnitude）→ K1166（analyst mechanism CONFIRMED）→ K1169（correction）。每次單一實驗出來就翻 narrative。
- **流程根因**：沒有「等 trilogy 完整結果才更新 narrative」的 state machine。單次結果就進入主線程寫作。
- **已嘗試補救**：CLAUDE.md 有「禁止用 agent 寫論文」但 narrative decision 不等於 tex 寫作。
- **預估影響**：USER-4 決策疲勞；論文進度浪費在翻寫而不是前進。

#### FB-H4 Cron「skip」回覆仍付全 token overhead
- **觀察**：`question_research` / `platform_patrol` / `knowledge_index_check` cron 都寫「先判斷是否需要執行，不需要就 skip」。但即使 skip，session cron 每次仍 full context load。
- **流程根因**：skip 檢查邏輯在 agent 對話內，不在 runtime 層。
- **已嘗試補救**：改 prompt 說「只有需要才建立任務」。
- **預估影響**：估 ~20% token overhead 花在「沒事也要寫一回狀態」。

#### FB-H5 Codex quota 無全局 queue
- **觀察**：近期 3 個實驗 agent（K1148_d3, K1131, K1148_d2）同時呼叫 codex review 時 quota 爆。
- **流程根因**：Codex plugin 是「誰呼叫誰跑」，沒有 quota budget / backoff。
- **已嘗試補救**：手動降頻。
- **預估影響**：ML / lag-sensitive 代碼審查被跳過 → 直接跑實驗風險。

### Medium（應改但不急）

#### FB-M1 主題重疊檢查在「決定主題後」而非「prompt 階段」
- **觀察**：CLAUDE.md 文字上要求「agent 啟動前檢查」，但實務是文章寫完才發現重複（2026-04-01 K791 與 K772 重複）。
- **流程根因**：檢查 step 靠 agent 自律執行。若主對話忙其他事就跳過。
- **已嘗試補救**：有 LanceDB skill。
- **預估影響**：偶發重複浪費 token。

#### FB-M2 Platform cycle summary 8 天未刷新
- **觀察**：`storage/ops/platform-cycle-summary-latest.json` generated_at = 2026-04-09，到今天 4-17 已 8 天。
- **流程根因**：`platform_patrol` cron 的 skip-if-no-issue 機制太保守，長期沒異常就整段沒跑。
- **已嘗試補救**：無。
- **預估影響**：USER-4 早晨看不到最新狀態。

#### FB-M3 `experiments.json` deprecation 未正式
- **觀察**：Apr 17，`experiments.json` 最後修改 Mar 22，已 3 週未動。knowledge.json + experiment_experiences.json 已取代。
- **流程根因**：沒有 migration / deprecation 流程。
- **預估影響**：若 agent 誤讀 experiments.json 會拿到過時資料。

#### FB-M4 Rollback points 無 rotation
- **觀察**：`storage/ops/rollback_points/` 14GB、23 個目錄、最大單個 6.6GB。
- **流程根因**：safe_migration 流程會 dump rollback 但沒 TTL / keep-latest policy。
- **已嘗試補救**：無。
- **預估影響**：磁碟增長、備份成本。

### Low（知道就好）

#### FB-L1 前端無 draft/published 同步 audit UI
- **觀察**：admin content 頁面列文章但沒顯示「本機 vs Supabase 一致性」。
- **預估影響**：幽靈草稿類問題只能 CLI 診斷。

#### FB-L2 BibTeX / paper citation 一鍵複製缺失
- **觀察**：`/paper` 列 metadata 但沒 copy-BibTeX button。
- **預估影響**：USER-3 引用時需自己手打。

---

## Section 3：使用者故事缺口分析

交叉比對 Section 1 scenarios × Section 2 flow bugs。表示「哪個 flow bug 造成哪個 user 的痛」。

| Scenario（⚠️/❌） | 主要 flow bug | 若修復效益 |
|---|---|---|
| 1.2 Strategy selector | 無 decision tree UI（非 flow bug，是 UX gap）+ L-L1 | 讓 USER-1 從 menu 變 selector、留存率 ↑ |
| 1.3 General → research 追溯 | L-L1（無 general-research 內鏈元資料）| 留存率、USER-3 流量 ↑ |
| 2.1 會員問答 | FB-C3（池空 + QA 頻率低）| USER-2 黏著、member_qa 從 8 →100+ |
| 2.2 `/me` 個人化 | L-L1（缺推薦引擎元資料）| USER-2 續訪率 |
| 2.3 升級動機 | 無 paywall/pricing（product gap）| **商業化關鍵**——目前 0 |
| 3.1 論文 PDF 下載 | FB-M4（版本爆炸）+ L-L2 | USER-3 引用容易度 |
| 3.2 結論追溯 | L-L1（knowledge 對外無 API）| USER-3 深度研究、學術可見度 |
| 3.3 Reproducibility | FB-M4 + 無 reproduce.py 統一命名 | 論文審稿順利 |
| 4.1 每日 9am 看任務 | FB-H1（無 created_at）+ FB-M2（summary 8 天沒更）| USER-4 日常效率 |
| 4.2 Paper 2 §5 決策 | FB-H3（narrative 翻 4 次 + 無 state machine）| USER-4 決策負擔 ↓ |
| 4.3 審 agent 產出 | 無 worktree 清潔度報表 + FB-C4 | USER-4 夜間確認時間 ↓ |
| 5.1 Slot-aware continuation | FB-C4（無 enforcement）| USER-5 不踩重複 agent |
| 5.2 Agent 善後 | FB-C2（無 typed API）+ 無 `post-agent-cleanup` 一鍵 | USER-5 knowledge 穩定性 ↑ |
| 6.1 Codex 審查 | FB-H5（quota 無 queue）| USER-6 審查順暢 |
| 7.1 幽靈草稿診斷 | FB-C1（無雙向 audit）| USER-7 / USER-4 信任感 |
| 7.2 池空警報 | FB-C3（alert 不觸發動作）| 網站不停更 |
| 7.3 Supabase egress | 無本地 egress dashboard | 付費 → 仍可能再爆 |

**關鍵觀察**：
- **USER-2 滿意度弱的根因有兩層**——商業層（無 paywall）+ 內容層（member_qa 只 8 篇）。不是 bug 是 product gap，需要商業決策驅動。
- **USER-4 Paper 2 narrative 翻 4 次**是 **決策支援不夠** + **誘惑「每次實驗完就翻 narrative」的 process**。解法是 batch（等 trilogy 完成）而不是 stream。
- **USER-5 idle-policy 放寬後新問題**：`agent-a85ff4df` 4/4 建立以來 13 天未清——放寬同時沒更新「清理檢查」。
- **USER-7 幽靈草稿為什麼沒被發現**：因為 sync 是單向 push；admin 雖從 Supabase 讀但教授不會每天看 admin drafts。需要「每日 reverse audit」。

---

## Section 4：優化建議（按 ROI 排序）

以下 **15 個建議**，分立即 / 短期 / 中期。每個標 S/M/L 工作量、預期效益、相依、受益 user。

### 立即（本週，< 3 天）

#### O-I1 Supabase ↔ feed.json 雙向 audit CLI
- **做什麼**：新寫 `uv run volpred ops sync-audit`：讀 Supabase articles + 讀本機 feed.json（用 jq，不整檔讀），diff 輸出「Supabase-only orphans / local-only / content-diff」。
- **工作量**：S（4-6h）
- **預期效益**：幽靈草稿 30 秒診斷
- **相依**：Supabase service_role key
- **受益 user**：USER-7、USER-4
- **對應 flow bug**：FB-C1

#### O-I2 清 5 篇 feed.json unpublished + 執行 sync-audit
- **做什麼**：(a) `mile_5eebba39/fccf06c9/b2f3aaed` 三篇 published_at=null 的真草稿，評估發佈或刪除；(b) 跑 O-I1 找出 Supabase-only orphan 決定 DELETE 或 sync-back。
- **工作量**：S（2-3h）
- **預期效益**：資料一致性恢復
- **相依**：O-I1
- **受益 user**：USER-7
- **對應 flow bug**：FB-C1

#### O-I3 修 `publish-milestone --tags '[...]'` JSON 解析
- **做什麼**：CLI 收到 `--tags '["a","b"]'` 要解析成 list，不要 split 成字串列表（FOMC agent 發現問題）。新增解析邏輯 + 單元測試。
- **工作量**：S（2h）
- **預期效益**：agent 自動發文不再爆 tag
- **相依**：無
- **受益 user**：USER-5
- **對應 flow bug**：（code bug 但同時是 CLI 流程設計）

#### O-I4 緊急補齊 article pool（draft=0 當務之急）
- **做什麼**：啟動 2 agent 並行（1 general + 1 research）寫草稿補池，並臨時把 `threshold` 從 3 調高到 5。
- **工作量**：S（啟動 agent）
- **預期效益**：3 小時內池子回到 5+
- **相依**：無
- **受益 user**：USER-1、USER-7
- **對應 flow bug**：FB-C3（症狀治療）

#### O-I5 清 worktree 殘留 `agent-a85ff4df`
- **做什麼**：確認該 worktree 無未 commit → 用 `scripts/merge_worktree.sh`（不要 --force）→ 若已無內容 `git worktree prune`。同時把「worktree > 7 天」加進 `ops health`。
- **工作量**：S（1-2h）
- **預期效益**：磁碟回收 + 未來 agent 不混淆
- **相依**：無
- **受益 user**：USER-4、USER-5
- **對應 flow bug**：FB-C4（周邊）

### 短期（本月，< 4 週）

#### O-S1 主題重疊檢查前置到 prompt 階段
- **做什麼**：寫 `volpred ops plan-article --topic "..."` wrapper，先跑 LanceDB 語義搜尋 → 找前 5 近似 → 若 >0.85 相似顯示 warning 並要求 `--force` 才能繼續。改 `autonomous-research` skill，把此命令作為 pre-agent step。
- **工作量**：M（2-3 天）
- **預期效益**：重複文章從「事後發現」變「事前攔截」
- **相依**：LanceDB index 已存在
- **受益 user**：USER-1、USER-5
- **對應 flow bug**：FB-M1

#### O-S2 Cron skip 改用 stub response
- **做什麼**：`question_research`/`platform_patrol`/`knowledge_index_check` cron 加 `--stub-if-no-work` flag。runtime 在 cron 觸發時先跑 1 行 python 判斷；若無事直接輸出 `{"skip": true}` 不進入 agent context。
- **工作量**：M（2 天）
- **預期效益**：cron token 用量降 20%
- **相依**：runtime 支援
- **受益 user**：USER-4（成本）、USER-5
- **對應 flow bug**：FB-H4

#### O-S3 Paper 2 §5 narrative state machine
- **做什麼**：在 `next_tasks.json` schema 加入 `state` field（`awaiting_trilogy` / `ready_to_decide` / `decided` / `written`）。建立 `docs/paper_decision_log.md` 記錄每次 narrative 翻轉的觸發實驗、決策理由、下一個 gate。規定「單一實驗不觸發 narrative 翻轉，需要 ≥3 互補實驗」。
- **工作量**：M（3-5 天）
- **預期效益**：Paper 2 決策從 4 次翻轉變 ≤2 次
- **相依**：用戶同意（涉及流程治理變更）
- **受益 user**：USER-4
- **對應 flow bug**：FB-H3

#### O-S4 `next_tasks.json` priority decay 機制
- **做什麼**：(a) enforce `created_at` 寫入；(b) 寫 `scripts/decay_tasks.py`：P1 > 7 天自動降 P2、P2 > 14 天 archive 到 `docs/research_archive/stale_tasks_YYYY-MM.md`；(c) 加進每日 session cron。
- **工作量**：M（2-3 天）
- **預期效益**：backlog 變短、USER-4 看到的清單是活的
- **相依**：無
- **受益 user**：USER-4、USER-5
- **對應 flow bug**：FB-H1

#### O-S5 Experiment derivative 預算上限
- **做什麼**：規則化——每個「主 K」最多 3 個 d- 衍生（d1/d2/d3），超過須 `/codex:rescue` 確認是否值得再衍生。寫 `scripts/check_derivative_budget.py`，實驗建立時驗證。
- **工作量**：S（1-2 天）
- **預期效益**：K1100g_d1-d7 類不再發生
- **相依**：無
- **受益 user**：USER-5、USER-4
- **對應 flow bug**：FB-H2

#### O-S6 Knowledge.json 改走 typed API
- **做什麼**：把所有 `json.dump(knowledge, ...)` 包成 `src/volpred/memory/knowledge.py` 的 `add_entry()` / `update_entry()`，強制 schema 驗證 + atomic temp + fsync。worktree 禁止 import 這個 module（只能走 CLI）。
- **工作量**：M（5-7 天）
- **預期效益**：knowledge corruption 不再發生
- **相依**：無
- **受益 user**：USER-5、USER-7
- **對應 flow bug**：FB-C2

### 中期（下季，1-3 個月）

#### O-L1 USER-2 價值階梯具體化（商業化）
- **做什麼**：定義 premium 差異化——(a) 即時 VIX alert（盤中推播）；(b) 策略客製服務（根據會員 risk profile）；(c) 月度深度研究 newsletter；(d) 專屬 dashboard（`/me/insights`）。寫 pricing page。
- **工作量**：L（1-2 個月）
- **預期效益**：從 0 開始建立變現鏈路
- **相依**：用戶同意（商業決策）
- **受益 user**：USER-2、USER-4（收入）
- **對應 flow bug**：（非 bug，是 product gap）

#### O-L2 前端加 Ops Health tab
- **做什麼**：`/admin/health` 加 5 個指標卡——(a) Supabase ↔ local 一致性；(b) 當前 running agents + slot 使用；(c) 池子 draft / published today；(d) cron 最近執行時間；(e) rollback points 磁碟。每指標有 red/yellow/green 門檻。
- **工作量**：M-L（2-4 週）
- **預期效益**：USER-4 早晨 1 分鐘看完系統狀態
- **相依**：O-I1 + 各指標的 CLI
- **受益 user**：USER-4、USER-7
- **對應 flow bug**：FB-M2、FB-C1

#### O-L3 General ↔ Research article 內鏈元資料
- **做什麼**：feed entry schema 加 `derived_from_k: [K672, K1146]` + `related_articles: [mile_xxx]`。前端 `/reports/[id]` 顯示「延伸閱讀」。knowledge 1,239 entry 對外開 `/research/k/KXXX` 路由。
- **工作量**：M（3-5 週）
- **預期效益**：USER-1 留存率、USER-3 學術可見度
- **相依**：knowledge JSON 結構整理
- **受益 user**：USER-1、USER-3
- **對應 flow bug**：（UX gap）

#### O-L4 Rollback points rotation + 本地 Supabase egress 監控
- **做什麼**：(a) `scripts/rotate_rollback_points.py`：保留最近 5 個 + 每月 1 個，其他刪；(b) `scripts/supabase_egress_check.py`：每日查 top queries + table size growth，寫入 `storage/ops_alerts/`。
- **工作量**：M（1-2 週）
- **預期效益**：磁碟回收 10GB + 預防 egress 再爆
- **相依**：Supabase service_role
- **受益 user**：USER-7
- **對應 flow bug**：FB-M4 + 7.3 gap

### 建議不由 agent 自主執行的項目

- **O-S3 Paper 2 state machine**：涉及論文治理變更，需用戶同意（CLAUDE.md 第 554 行規則）。
- **O-L1 Premium 付費階梯**：商業決策。
- **清 rollback points 批量刪除**：有潛在資料損失風險，需用戶確認保留範圍。

### 可由 agent 自主執行的項目

- O-I1 / O-I2 / O-I3 / O-I4 / O-I5（有明確規則或屬診斷清理）
- O-S1 / O-S2 / O-S4 / O-S5 / O-S6（有明確規則）
- O-L2 / O-L3 / O-L4（開發類，agent 可做 PR 等用戶審核）

---

## 附錄 A：關鍵統計（本次新測 vs 上份盤點）

| 指標 | 本次值 | 上份值（4-17 早些時候）| 取得指令 |
|---|---|---|---|
| feed 文章數 | 916 | 915 | `grep -c 'mile_' storage/reports/feed.json` |
| published | 911 | 910 | jq count |
| unpublished | 5 | 5 | jq count |
| **draft** | **0** | ？ | grep count |
| next_tasks pending | 40 | — | python parse |
| P1 pending（含 Paper-related） | 4（K1146/K1169/Paper9_bib_fix/Paper2_section5_decision）| — | python filter |
| P2 pending | 4（Paper9_dual_target/Paper6_start/K1144/K1175）| — | python filter |
| K1100g 衍生 d1..d7 | 至少 d3..d7 | — | next_tasks pending |
| research_program.md 行數 | 958 | 625（上份值）| wc -l |
| rollback points 總大小 | 14GB | 14GB | du -sh |
| worktree 殘留 | agent-a85ff4df（13 天）| 同 | ls |
| ops_alerts 檔 | 10 | — | ls count |
| platform-cycle-summary 最新 | 2026-04-09（8 天前）| — | cat generated_at |
| member_qa 文章數 | 8 | 8 | feed tag count |

## 附錄 B：待 USER-4 決策的事項清單

1. **Paper 2 §5 narrative**：決定是否等 K1148_d1/d2/d3 + K1167 + K1169 結果 triangulate 後再改，或立即按 K1169 correction 改（影響 O-S3 設計）。
2. **Premium 商業化方向**（O-L1）：三擇一——(a) 每月訂閱 + 即時 alert；(b) 一次性研究報告付費；(c) 免費+廣告。
3. **14GB rollback points 保留政策**：哪些可刪？建議保留最近 5 個 + 每月首個。
4. **5 篇 feed unpublished**：`mile_b2f3aaed` 是 OVERTURNED warning 文章（2026-03-31），該留或刪？
5. **`experiments.json` deprecate**：可刪除嗎？會不會有腳本還在讀？
6. **USER-2 問答頻率**：是要主動徵求提問（讓 member_qa 從 8 → 100+），還是保持 pull 為主？

## 附錄 C：本報告方法論

- 只讀分析，未修改任何檔案。
- 未整檔讀 `feed.json`、`knowledge.json`（遵守 token 紀律）。
- 用 jq / grep / python inline 抽樣統計。
- 18 個 scenarios 涵蓋 7 類 user，每類 2-3 個。
- 13 個 flow bugs 按 C/H/M/L 分層。
- 15 個優化建議跨立即 / 短期 / 中期。
- 所有數字附取得指令於附錄 A。

---

*本報告由 Claude 作為 subagent 於 2026-04-17 執行。重點不在技術盤點（已有 `docs/project_analysis_2026-04-17.md`），而在 UX / 流程 / 治理層的 actionable insight。後續執行建議請先在 `research_program.md` 對應面向登記，或建立 task 到 next_tasks.json。*
