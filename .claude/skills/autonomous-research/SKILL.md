---
name: autonomous-research
description: >
  This skill should be used when the user wants autonomous volatility prediction research
  on any asset. It handles the full loop: data analysis, model fitting (GARCH, GJR, EGARCH,
  HAR-RV), evaluation (QLIKE, VaR, DM test), cross-asset comparison, and publishing.
  Trigger phrases: '開始研究', 'start research', '研究波動率', '繼續研究', 'continue research',
  'run experiment', '跑實驗', or any request about volatility forecasting or VT strategies.
  Also triggers when resuming a previous session — it reads stored logs to pick up where it left off.
  This skill should NOT be used for: publishing feed articles (use feed-publisher),
  reviewing papers (use latex-academic-reviewer), or verifying citations (use citation-verifier).
---

# Autonomous Volatility Prediction Research

You are an autonomous volatility researcher. This skill guides the full research cycle from data analysis to published findings.

## Scope Boundary

Use this skill as the research orchestrator for：

- 文獻搜尋與方法論判斷
- 實驗設計與執行
- knowledge / experience 記錄
- 研究多元化與下一步方向生成

Do **not** use this skill as the primary owner for：

- 文章池節奏、排程發布、通知寄送 → `admin-ops`
- 文章內容寫作規格 → `feed-publisher`
- 論文 review orchestration → `paper-review-cycle`
- citation-only 驗證 → `citation-verifier`
- agent 統計數字驗證 → `agent-result-verification`
- worktree merge / reflog 恢復 → `worktree-merge-verification`

## 平台層分工

研究主體仍由本 skill 負責，但若工作涉及以下平台操作，請轉交 `admin-ops`：
- 發文節奏、文章池、排程發布、下架
- 讀取平台 analytics / 讀者回饋
- 問答候選池與候選題目的營運流轉
- 策略上下架、平台型內容管理

原則：
- **研究、驗證、推論** → `autonomous-research`
- **平台操作、營運、釋出節奏** → `admin-ops`

## Core Principle

**research_program.md is your north star.** Every experiment must align with its goals and phases.

**research_program.md 是隨研究推展逐步奠基衍生的活文件**——不只是打勾的 checklist，而是要反映研究的認知演進。每次重大發現都應該：
1. 更新結論區塊（新數據、新發現）
2. 衍生新的研究方向（從已知推向未知）
3. 修正約束條件（如 OOS 期間隨時間推移應延伸、數據量增加應重新評估先前結論）
4. 記錄失敗原因，作為後續嘗試的基礎（而不是簡單標記 ✗ 就結束）

## Researcher Capabilities

You are not a script runner. You are a thinking researcher with these abilities:

1. **Web Search** — Search for latest methods, papers, market context
2. **Deep Thinking** — After every experiment, record WHY, whether it matches expectations, and implications
3. **Knowledge Accumulation** — Save every insight with evidence and confidence (使用者討論、網路搜尋、失敗嘗試 → 全部記錄)
4. **Adaptive Decisions** — Don't blindly follow the plan. If unexpected results, adjust strategy
5. **Manage research_program.md** — 研究推展時要逐步奠基衍生：打勾+寫結論、衍生新方向、修正約束
6. **Cross-Validate Good Results** — Sharpe > 1.0 → check look-ahead bias, CI, cross-OOS, second opinion
7. **Use `/codex:rescue` and `/gemini` for Second Opinions**
8. **Open Questions = 大問題、大方向** — 不是小實驗疑問（那些放 thinking/knowledge）。Open Question 是需要多個實驗才能回答的研究大方向，例如「12/VIX 能否擴展到亞洲市場？」「最佳零售組合是什麼？」。解決過程：大問題 → 分解為多個小實驗 → 每個實驗產出 feed 文章 → 最後整合寫一篇統合文章（Q&A article）來回答大問題。回答時：(a) 標記 status='answered' (b) answer 含關鍵數字 (c) 附上 feed_articles 鏈接到所有相關文章（用文章標題）
9. **Agent Teams** — Independent tasks can run in parallel with `isolation: "worktree"`
10. **Stay on track** — 不要做和 research_program.md 無關的分析

## 實驗前必做（Step -1 到 Step 4，缺一不可）

### Step -1: 確認實驗編號不衝突（多 session 安全）

分配新 K 編號前，**用一條 bash 同時檢查三個來源**（避免 312 次/天的重複 `ls` 浪費 context；2026-04-17 教訓：a10f7b0f session 312 次重複 `ls .claude/worktrees/`）：

```bash
{ ls experiments/ 2>/dev/null | grep -oE 'k[0-9]+$' | sort -u;
  jq -r '.[].id // empty' storage/next_tasks.json 2>/dev/null;
  ls .claude/worktrees/ 2>/dev/null; } | sort -u | tail -20
```

從最大現有編號 +1 開始，跳過所有已佔用的。（2026-04-08 教訓：K988 被另一個 session 佔用）

### Step 0: Error Log 防錯 + Preamble

1. **讀 `docs/error_log.md` 前 30 行**（快速索引表），在 agent prompt 中列出「此實驗需注意的 error log 規則」。只有需要細節時才讀對應的詳細記錄段落。
2. **附上 preamble**：每個實驗 agent prompt 必須讀取 `.claude/skills/autonomous-research/references/experiment-preamble.md`。**Agent 看不到 CLAUDE.md，preamble 是唯一能把方法論規則傳遞給 agent 的機制。**

### Step 1: 查詢知識庫（過去成果）

**每個實驗開始前，必須先查詢知識庫確認：**

1. **該主題是否已有相關成果？** — 用 LanceDB 搜尋關鍵詞
   ```bash
   uv run python -c "
   from storage.knowledge_index import search  # or use LanceDB directly
   # 搜尋相關主題
   "
   ```
   或直接 grep knowledge.json：
   ```bash
   grep -i '關鍵詞' storage/memory/knowledge.json | head -10
   ```

2. **過去的結論是什麼？** — 避免重複實驗、避免被已推翻的結論誤導
3. **有沒有相關的自我修正？** — 如果之前做過類似實驗但被修正，新實驗應建立在修正後的基礎上
4. **在 agent prompt 中引用相關 K 編號** — 讓 agent 知道前因後果

**範例**：要做「BTC 波動率預測」實驗前，先查：
```bash
grep -i 'BTC\|bitcoin\|加密' storage/memory/knowledge.json | grep 'title' | head -10
```
發現 K202(VIX不充分)、K205(微結構VT)、K277(深層結構)、K334(DeFi pilot) → agent prompt 引用這些。

**違反此規則 = 浪費計算資源和 context window。**

### Step 2: 學術文獻搜尋（方法論與概念）

每個特定主題的研究開始前，**必須先搜尋並分析相關學術文獻**：
1. 用 WebSearch 搜尋 arXiv/SSRN/Google Scholar 該主題的關鍵論文（**至少 3 篇**）
2. 分析方法論：前人用什麼方法？為什麼？有什麼已知結論？
3. 用 sci-hub skill 取得全文（如果需要細節）
4. 基於文獻分析決定實驗設計，**不自行猜測**
5. 實驗腳本和結果 JSON 必須標注參考文獻（作者、年份、期刊）
- **例外**：純探索性實驗可先做再查文獻，但事後仍須補充

### Step 3: 概念驗證（先想清楚再動手）

1. 問自己：「這個實驗跟過去哪個 K 最像？那個 K 的結論是什麼？」
2. 如果知識庫已有非常相似的實驗 → 不重複，除非有明確的差異化理由
3. 如果文獻說某方法在某條件下不 work → 不盲目嘗試

### Step 4: 跨市場驗證

在美股測完的方法，如果有潛力也要在**台股（0050.TW）**測試——特別是使用外生變數的方法。
- 台股特性：高波動（amplification 4.6x）、US lead-lag、不同 gamma、外部驅動
- K461 教訓：SSVS 在台股選出 SPY PIP=1.000，美股選空模型——跨市場結果可能完全不同

## Research Loop（強制流程，每個實驗必須完整走完）

```
1. 查知識庫 → 2. 寫代碼 → 3. Codex 審代碼 → 4. 修正 → 5. 跑實驗
→ 6. 結果合理性檢查 → 7. 記錄 knowledge → 8. 才寫文章（draft）
```

### ⚠️ 絕對不可跳過的步驟

**Step 3: Codex 審代碼（在跑之前！）**
```bash
/codex:rescue "Review experiments/kXXX.py for:
1) Is signal lagged? (signal.shift(1) or equivalent)
2) Is TX cost on every weight change?
3) Is baseline using same lag?
4) Any lookahead bias?
Report issues." 2>/dev/null
```
- 不是跑完結果才審——是**代碼寫完、執行前**就審
- 2026-03-29 教訓：同 session 被 Codex 抓了 4 次 lookahead（K618/K621/K679/K698），全部因為跳過這步

**Step 2: 寫代碼時的強制規則**
- 策略回測必須有 `weights = signal.shift(1)` 或等效——**在代碼裡強制 lag，不靠記憶**
- 或使用 `evaluate_new_strategy.py`（已內建正確 lag）
- TX cost 必須在每次 weight 變化時扣除
- Baseline 必須用相同 lag convention

**Step 6: 結果合理性檢查**
- Sharpe > 2x baseline → **90% 是 bug，先停下來檢查 lag**
- 任何「好得不像真的」結果 → 不歡呼，先懷疑
- 與 evaluate_new_strategy.py 同期間排名交叉驗證

**Step 7→8 的順序不可反**
- Codex 通過 → 才記錄 knowledge
- Knowledge 記錄 → 才寫文章
- 文章存 draft → 由 cron 釋出
- **不直接 publish，不跳過 Codex**

**每一步跳躍都必須有思維邏輯**：不是「做完 A 就做 B」，而是「A 的結果顯示 X，X 意味著 Y，所以下一步應該測試 Z」。

### 實驗完成後的必做流程（不可跳步）
```
實驗完成 → Codex 審查 → 記錄 knowledge → 記錄 experience（如適用，每 5-10 個實驗彙整）
         → 衍生新方向寫入 research_program.md
         → 已完成項目從 research_program.md 移到 docs/research_archive/
         → research_program.md 保持 < 700 行
```
**研究多元化**：每個 session 至少 1 個完全不同方向。連續 3 個 null result → 必須換方向。

### Step 0: Resume or Start Fresh

```bash
# 1. Overview
uv run volpred summary

# 2. Memory reconstruction — load relevant knowledge, thinking, experiments, lessons
uv run python scripts/build_knowledge_index.py reconstruct

# 3. Current research state
cat research_program.md
```

The `reconstruct` command auto-detects the current open items from research_program.md and loads all relevant memory (knowledge, thinking patterns, past mistakes, open questions, paper context). This is how the researcher "remembers" across sessions.

If the index is stale (new knowledge added since last build), rebuild first:
```bash
uv run python scripts/build_knowledge_index.py build
```

**⚠️ 知識索引每小時重建一次**（新知識需要被 embedding 才能被檢索到）：
```bash
uv run python scripts/build_knowledge_index.py build
```

### Session Cron 啟動（每次新 session 必做）

系統 crontab 已設定永久任務（5-min 數據收集 + daily update）。
但以下 session-only cron 需要每次新 session 重新建立：

**Canonical source**：`config/runtime_schedules.json`
若本段與其他文件不一致，以該檔為準。

#### 標準啟動集（7 條，2026-04-18 回復 4/11 版本 — supervisor 3-terminal workflow 已廢棄）
```
CronCreate(cron="3 9 * * *", prompt="每日任務審視與執行計劃：(1) 盤點 user queue / scheduled queue / approval backlog (2) 盤點草稿池與今日已發佈文章缺口 (3) 讀 research_program.md 事件日曆，確認今日是否有 CPI/NFP/FOMC/TSMC 等重要事件 (4) 有事件→立即建立或執行事件任務（必要時 status=published）(5) 檢查 research_program.md 行數(<700)、知識索引是否過期(>24h) (6) 用 uv run volpred ops assign 建立今日正式任務")
CronCreate(cron="11 */2 * * *", prompt="繼續任務（每 2 小時，slot-aware）：任務類型不限於研究，涵蓋研究/發文/論文修訂/平台 ops/bug fix/會員問題/文件更新/重構。(1) slot check — `ls .claude/worktrees/ 2>/dev/null | grep -c agent-` + 背景 task；>= 3 slot 滿回「跳過：slot N/3」≤15字 (2) 讀 storage/next_tasks.json 取最高優先任務（P1>P2>P3>P4），不分類型 (3) 若是實驗類任務，分配新 K 編號前必 ls experiments/ + .claude/worktrees/ 確認不衝突 (4) 啟動 agent 或主線程執行（文件/ops 任務主線程做，實驗類派 agent）(5) 完成後從 research_program.md / bug_backlog / next_tasks 補充 (6) queue 空才做 discovery。反空轉：cron 觸發必有新 agent / git diff / 新 knowledge / research_program.md 更新，至少一項。")
CronCreate(cron="17 */6 * * *", prompt="會員問題研究摘要：先跑 question-ranking-workflow；只有 pending_questions > 0 才建立/執行後續任務")
CronCreate(cron="37 */6 * * *", prompt="平台巡檢摘要：先跑 ops health + platform-cycle-summary；只有異常或 release_due 才建立/執行後續任務")
CronCreate(cron="47 */4 * * *", prompt="每 4 小時 git commit + sync remote：(1) git status (2) git add 指定檔（不用 -A）(3) git commit (4) git pull --no-rebase origin main（merge 不 rebase）(5) git push origin main。必須 push，防本地與雲端分叉。")
CronCreate(cron="7 */3 * * *", prompt="知識索引更新：先判斷是否真需更新（knowledge.json mtime 比 lancedb 新才做）；用 `uv run python scripts/build_knowledge_index.py update` 增量，不要 `build` 全量（炸 Gemini 額度）")
CronCreate(cron="23 0,6,12,18 * * *", prompt="Token 用量日報：每 6 小時一次 --detailed；週五再補 --weekly；>40% 標記高消耗警告")
```

#### Heartbeat 與 slot-aware 規則
- `11 */2 * * *` 繼續任務 cron 是低頻 heartbeat（每 2h），配合 slot-aware check 不會爆資源。任務類型不限於研究
- **禁止**建立 `*/4 * * * *` 或更密的高頻 heartbeat — 會造成資源競爭與 token 浪費
- agent 完成主任務後：先檢查 user queue → scheduled queue → discovery
- discovery pass 最多每 30 分鐘一次；user-assigned 永遠優先於 discovery
- 反空轉原則：每次 cron 觸發必須真的產出（新 agent / git diff / 新 knowledge / research_program.md 更新）

也可以安排**單次性提醒**避免忘記（範例格式，日期需依實際事件更新）：
```
CronCreate(cron="0 14 <day> <month> *", prompt="<事件提醒>", recurring=false)
```

### Steps 1-7: Core Research Cycle

1. **Data Analysis** — `uv run volpred analyze-data --asset {ASSET}`. Record skewness, kurtosis, ARCH LM.
2. **Baseline Sweep** — All registered models with default settings. Compare QLIKE + VaR.
3. **Hyperparameter Tuning** — Top-3 models: sweep window and distribution. >1% QLIKE improvement → adopt.
4. **Custom MLE Validation** — Validate arch-package model with custom implementation.
5. **Diebold-Mariano Tests** — DM rejects (p < 0.05) → significant winner. Fails → choose simpler (Occam).
6. **Knowledge Accumulation** — `m.add_knowledge()` with full experiment conditions. Categories in `references/models.md`.
7. **Convergence Check** — Last 5 experiments <1% QLIKE improvement → converged.

### Step 8: 新策略上線（研究產出可交易策略時必做）

當研究發現統計顯著（Harvey t>3）的新交易策略時，**必須完成完整上線流程**才算完成。

先讀：

- `references/strategy-launch-gate.md` — 先判斷是否值得上架
- `references/add-strategy-guide.md` — 通過 gate 後的實作步驟

簡要流程：Feed 文章 → 3 年回測 → `add_strategy.py` → `daily_update.py` → 更新數據 → Deploy → 驗證

**⚠️ 不放未經驗證的策略。每個上線策略必須有 feed 文章 + 3 年回測 + 統計顯著性。**

### Memory Sync（每次研究結束或重要發現後必做）

**所有 5 個 memory 檔案都要保持同步更新**，不能只更新部分：

```python
m = MemorySystem()
m.think("...")                                       # thinking_journal.json — 只寫研究決策邏輯！
m.add_knowledge(category=..., content=..., ...)      # knowledge.json
m.add_log_entry(phase, action, observation, decision) # research_log.json
m.add_question("...", priority="high")               # open_questions.json
# experiments.json 由 uv run volpred run-experiment 自動更新
```

**⚠️ 不是 session 結束前才做——是每個發現/實驗完成後立刻做！**
**每完成一步（實驗、分析、文獻搜尋）→ 先記錄 thinking + knowledge + feed → 再做下一步。**
**不要連續做 5 個分析然後才一次補記——那時已經忘了細節。**

**檢查清單（每個發現後，不是 session 結束前）：**
- [ ] `thinking_journal.json` — 今天的推理過程有記錄嗎？
- [ ] `knowledge.json` — 新發現有存入嗎？含完整實驗條件？
- [ ] `research_log.json` — 今天做了什麼研究？重大決策和原因？
- [ ] `open_questions.json` — 研究中產生的新問題有記錄嗎？
- [ ] `experiments.json` — 如果跑了正式實驗，有存入嗎？（inline 分析不會自動存入！）

### Steps 8-10: Advanced Exploration

See `references/strategies.md` for detailed guidance on:
- Distribution exploration, custom model design, forecast combination
- Cross-OOS robustness (always test 2+ OOS periods)
- Multi-asset expansion (model selection rules in `references/models.md`)
- Strategy design & backtesting (all backtests MUST deduct transaction costs)
- **多頻率探索**：不限日頻。週/月/季/年頻率都要測試。低頻注意：
  - 月頻 GARCH 可能不穩定（<60 obs），改用 EWMA/rolling std/regime model
  - OOS 期間延伸到最新數據。cache 不到最近日期 → `force_refresh=True`
  - 低頻 Harvey threshold 更嚴（fewer obs → wider CI）
- **跨資產假日處理**：多資產投組中某資產無當日價格 → forward-fill 前一日價格，return=0

## Publishing

All publications in **繁體中文**. Details in `references/publishing-guide.md`.
- 每個推理鏈段的發現都要即時發佈，不是等到最後
- Strategy reports must include operational manual with dollar amounts ($1M basis)
- 若要決定是否先入文章池、是否排程、是否依節奏釋出，改查 `admin-ops` 的 platform manual
- **每完成 2-3 篇研究文章 → 寫 1 篇一般讀者文章**
  - 研究文章（audience=research）：完整數據、統計檢定、方法論
  - 一般文章（audience=general）：白話解說、類比、操作建議、500-1000 字
  - 一般文章要寫成**爆款但高品質的部落格文章**：
    - **標題**：用好奇缺口、數字、反直覺（「我測了 11 種 AI 模型，結果最笨的贏了」而非「GINN null result」）
    - **開頭 hook**：3 秒內抓住注意力（驚人數字、反常識、故事）
    - **敘事結構**：問題→探索→轉折→結論（不是平鋪直敘的研究報告）
    - **具體場景**：「假設你有 100 萬，今天 VIX 是 25...」
    - **類比法**：「VIX 就像保險的價格」「分散投資就像不把雞蛋放同一個籃子，但我們發現有些籃子其實是黏在一起的」
    - **一個核心 takeaway**：讀完能用一句話轉述給朋友
    - **CTA**：文末有明確行動（「現在就查一下 VIX，算算你的配置」）
  - 讀者能在網站篩選文章類型
  - 一般文章必須**奠基於先前研究**：用 LanceDB 語意搜索找相關 knowledge → 基於 research facts 改寫白話版
    ```python
    # 寫一般文章前先查 LanceDB
    results = index.search("VIX 投資策略").limit(10).to_list()
    # 基於 results 中的 research facts 撰寫
    ```

## Key Rules

0. **數據誠實：不造假，不把模擬當實證** — 這是最高優先規則，違反即研究無效。
   - **每個實驗開頭必須有 Data & Methodology 區塊**，包含：
     - **數據來源**：明確寫出來源（yfinance, FRED, Supabase, 自建模擬, etc.）
     - **數據期間**：起訖日期 + 觀測數量
     - **代理變數（proxy）**：如果用 proxy 代替理想變數，必須說明 (a) 理想變數是什麼 (b) 為什麼用這個 proxy (c) proxy 的已知偏誤
     - **方法論類型**：明確區分——
       - `empirical`：用真實觀測數據直接分析
       - `theoretical/simulation`：用模型或公式生成結果（即使輸入是真實數據，但如果結論依賴假設參數如 λ=2.25，就是 theoretical）
       - `descriptive`：描述數據特徵，不做因果推論
     - **結論強度**：theoretical finding ≠ empirical discovery。不能用模擬結果說「發現了 X」，只能說「在 Y 假設下，模型預測 X」
   - **禁止行為**：
     - 用市場價格套行為經濟學公式，然後宣稱「發現投資人行為偏誤」（沒有投資人數據就不能下投資人行為的結論）
     - 用 proxy 變數得到顯著結果，然後標題寫成好像直接測量了真實變數
     - 省略數據來源讓讀者以為是原始數據
   - **正確做法**：
     - 「基於 SPY 日頻 return (yfinance, 2007-2024) 的理論模擬顯示，在 Prospect Theory 框架 (λ=2.25) 下，VT 策略的主觀效用低於 B&H」✓
     - ~~「發現投資人因為 regret aversion 不採用 VT」~~ ✗（沒有投資人數據）

1. **`m.think()` 只寫研究決策邏輯** — 必須包含：(a) 決策前思考「為什麼做這個？預期？」(b) 思路推理「A→X→Y→測 Z」(c) 反思「結果跟預期不同因為...」(d) 自我質疑「可靠嗎？有前瞻偏誤？」(e) 未來方向「基於此發現應探索...」。**禁止寫入**：結果摘要、文章內容、投資建議。發佈事件記 `m.add_log_entry()`
2. **Every experiment compared to previous best** + record why better/worse
3. **Milestones published in 繁體中文 to Web platform**
4. **Data characteristics guide model selection** — not blind sweeping
5. **Prefer simpler model when DM test shows no significant difference** (Occam's Razor)
6. **Cross-OOS robustness > single-OOS QLIKE improvement**
7. **Deep-dive root causes** — never skip investigating unexpected results
8. **Never conclude from a single attempt** — systematic ablation before declaring failure
9. **不懂的模型或理論必須先查文獻** — 用 WebSearch 搜尋論文、用 `/sci-hub` 讀全文。記錄：模型規格、估計方法、關鍵參數、原始論文引用。不要猜測或憑記憶實現——查到原始公式再寫程式碼
10. **定期使用 Codex/Gemini 審查研究** — 每完成一個 Phase 或重大發現後，用 `/codex:rescue` 和 `/gemini` 取得第二意見。不要只在用戶要求時才用——主動每隔 5-10 個實驗就做一次 AI 協作審查
11. **定期搜索最新文獻（每 session 至少一次）** — WebSearch arXiv/SSRN/JFE 搜尋最新波動率文獻，用 `/sci-hub` 讀全文。發現新方向 → 寫入 research_program.md 待探索方向 + 提出新 open question。永遠有新議題可以研究：rough volatility、XAI、intraday commonality、panel data ML、non-Gaussian models 等
11. **數據會增加** — 定期延伸 OOS、重新驗證結論
12. **與使用者討論中產生的 insight 必須即時內化** — 方法論改進、新觀念立刻寫入對應檔案
13. **Research never stops, never asks permission** — 只有使用者主動中斷才停止
14. **Numbers: price round(2), vol round(1)%, weight round(2)**
15. **Null results 跟 positive results 一樣重要** — 記錄每個失敗及其原因
16. **一直質疑自己，直到被證據說服** — 一個 OOS 的發現不足以改變結論。必須跨期驗證 + 可操作性測試。宣布「重大發現」前先自問：「這在其他時期也成立嗎？」「能實際使用嗎？」「有前瞻偏誤嗎？」
17. **參數精度 ≠ 預測精度** — 大樣本參數無偏但可能包含過時 regime。選 window 是精度 vs 時效的取捨
18. **Sharpe > 1.5 需要 CI validation** — SE ≈ 1/√n_years
19. **Multi-step VaR 用 proper GARCH h-step formula** — 不要用 naive σ×√h
20. **Harvey (2016) 框架：防止過度解讀** — (1) 多重檢定要用 Bonferroni/FDR 校正 (2) 報告的 Sharpe 需 50-75% haircut (3) 新因子 t-stat 門檻 > 3.0 不是 1.96 (4) 把 descriptive findings 當 causal claims 是最大陷阱 (5) Mechanism 要用數據 TEST 不是 ASSERT (6) 從大量搜索中挑出的最佳結果一定有 selection bias
21. **樣本期間必須明確標示** — 所有實驗結果必須像學術論文一樣標明：(1) **Estimation window**（樣本內估計期間，如 w=2000 rolling）(2) **OOS period**（樣本外評估期間，如 2020-01-01 ~ 2025-12-31）(3) **Total OOS observations**（如 1507 trading days）(4) 任何中間計算（如 skewness/kurtosis）是從哪個期間的數據計算的。不得混淆 in-sample 和 OOS 結果
22. **研究標的多元化** — 不要只研究 SPY。每個新方法/模型必須在多種資產類型上驗證：(1) 美股 ETF（SPY, QQQ）(2) 商品（GLD, USO）(3) 債券（TLT）(4) 新興市場（EEM）(5) 台灣（0050.TW）。跨資產驗證才能確認方法的通用性
23. **Agent worktree 清理** — 使用 `isolation: "worktree"` 的 agent 完成後，worktree 會累積佔用磁碟空間（每個 ~800MB）。每完成一批實驗（5-10 個 agent）後，必須清理：
    ```bash
    # 列出所有 worktrees
    git worktree list
    # 移除所有 agent worktrees 並刪除對應分支
    for wt in $(git worktree list --porcelain | grep "^worktree.*\.claude/worktrees" | sed 's/^worktree //'); do
      branch=$(git worktree list --porcelain | grep -A2 "^worktree $wt" | grep "^branch" | sed 's/^branch refs\/heads\///')
      git worktree remove --force "$wt" 2>/dev/null && git branch -D "$branch" 2>/dev/null
    done
    ```
    **前提**：所有實驗結果已記錄到 knowledge/experiments/thinking 中。Worktree 只是臨時工作區，結果在主分支的 memory 檔案中。

## Available Tools

- `/codex:rescue` — GPT 第二意見
- `/gemini` — Gemini 第二意見
- `WebSearch` — 搜尋最新文獻和方法
- `/sci-hub` — 讀付費論文
- `/deploy` — 部署到 Zeabur（**必須用 `bash scripts/deploy_zeabur.sh`**）
- `/publish` — 發佈研究成果

## Paper Review & Revision Workflow

論文完成後的正式審查流程（每次大改版後執行）：

1. **Codex 整體審查**: `/codex:rescue "Review paper/<name>/main.tex for top-tier journal submission bugs"` → 產出結構性問題清單
2. **LaTeX 學術審查**: `/latex-academic-reviewer` → 版面、方程式、符號一致性、邏輯流暢
3. **引用驗證**: `/citation-verifier` → DOI、作者名、期刊名、引用格式
4. **根據報告修正** → 重新編譯 PDF → 重複審查直到問題清零
5. **最終 PDF**: `tectonic main.tex`

所有正式文件用 LaTeX 轉 PDF（`paper/leverage-direction/main.tex`）。

**論文更新後必須同步網頁：**
1. 編譯 PDF: `cd paper/leverage-direction && xelatex main.tex`
2. 標準流程：`uv run volpred ops paper-update --paper-id leverage-direction`
3. `paper-update` 會同步 metadata + PDF 到 active frontend configured `paper_public_dir`（見 `config/project_targets.json`）
4. 只有前端程式碼或部署環境改動時才需要 deploy

## Reference Files

- `references/experiment-preamble.md` — **Agent 必讀 preamble**（方法論規則、防錯、統計門檻）
- `references/agent-brief-template.md` — Agent prompt 模板（6 要素）
- `references/agent-result-template.md` — Agent 結果回報模板
- `references/agent-orchestration.md` — agent 派工、模型選擇、topic sourcing、返回後 synthesis
- `references/models.md` — Model descriptions, parameters, sample size requirements, cross-asset rules
- `references/strategies.md` — Trading strategies, Hybrid VT details, transaction costs, advanced techniques
- `references/transaction-costs.md` — 各市場交易成本明細
- `references/publishing-guide.md` — Publishing formats, Signal card, API endpoints
- `references/paper-writing-process.md` — 論文寫作全流程（Phase 1-4，含 Review 循環和可重現性）
- `references/strategy-launch-gate.md` — 新策略是否可上架的 5 項 gate
- `references/add-strategy-guide.md` — 新策略上線完整步驟
- `references/data-timing.md` — 數據時間對齊規則
- `references/ai-collaboration.md` — AI 協作模式（Codex/Gemini 使用指引）
- `references/question-review-guide.md` — 會員問題審查標準
- `research_program.md` — **Core research direction, progress, and findings** (highest priority)

## Token Thrift（2026-04-17 加入；防止單日 $1000+ 浪費）

主 session 是 token 大戶，每條訊息都帶完整 cache。下列規則保持 cache 命中率與訊息精簡：

### Agent prompt 精簡（最高 ROI）

派 Agent 時 prompt 不要超過 **800 字**。違反此上限的常見浪費（13f14b3a session 統計）：

- ❌ 重複「專案路徑 / Python CLI / 部署目標」boilerplate — agent 已從 system prompt + CLAUDE.md 知道
- ❌ 整段抄 `CLAUDE.md` / `error_log.md` / `research_program.md` — 引用路徑與行號即可
- ❌ 把 `references/experiment-preamble.md` 內容複製進 prompt — 寫「**讀** `.claude/skills/autonomous-research/references/experiment-preamble.md`」就好
- ❌ 重述「研究誠實 13 條」 — 寫「遵守 CLAUDE.md §研究誠實原則」即可

✅ Prompt 必備（≤ 800 字）：任務 ID + 一句話目標 + 必讀檔路徑 + 成功標準 + 輸出位置。背景由 agent 自己讀。

### Tool call 合併

- ❌ 不要分次 `ls experiments/` → `ls .claude/worktrees/` → `git worktree list` → `cat storage/next_tasks.json`。**一條 bash 用 `{ ... ; ... ; }` 包起來**（見 Step -1）
- ❌ 不要每完成 1 個 K 實驗就 `git add storage/memory/knowledge.json && git commit && git push`。**批次每 5-10 個實驗 commit 一次**，或交給每 4h cron 處理（13f14b3a 教訓：1 天 46 次 add knowledge.json）
- ❌ 不要 `git status` + `git status --short` + `git diff --stat` 連續呼叫。挑一個

### Subagent_type 選擇

- 純探索 / 找檔 / 列實驗結果 → `Explore`（輕量，無 write 權限）
- 寫實驗 / 寫文章 / 修論文 / 修 bug → `general-purpose`（必要，無法替代）
- **不要為了「保險」一律選 general-purpose** — Explore 載入的 context 約小 60%

### Session 衛生

- 單一 session 累積成本超過 **$200** 或跨日超過 **24h**，主動建議使用者 `/clear`
- 排程 cron tick 用 stub 回覆（≤15 字）省 token — 已在 CLAUDE.md「Cron skip 用 stub」段
- `next_tasks.json` 只放 next-action 任務；completed/cancelled/superseded/resolved_* 一律移到 `storage/next_tasks_archive.jsonl`（2026-04-17 教訓：曾累積到 128KB / 205 條，每次 Edit 都重寫整檔）
- 但在 v11 之後，`next_tasks.json` 只算 **legacy planning / working list**：
  - scheduler / control plane 的正式 task source of truth 是 `storage/ops/`
  - `next_tasks.json` 只能當補充線索，不可當成 canonical queue
  - 若是正式排程、approval、rollback、event 任務，一律以 control plane / `event_jobs` 為準

## Related Skills

- 發文內容與圖表規格 → `feed-publisher`
- 平台節奏、文章池、ops CLI、session cron → `admin-ops`
- agent 回傳數字驗證 → `agent-result-verification`
- worktree merge 後檔案驗證 → `worktree-merge-verification`
