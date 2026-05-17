---
paths:
  # 原 publish-checklist.md 觸發路徑
  - "storage/reports/feed.json"
  - "storage/reports/mile_*.json"
  - "scripts/publish_*.py"
  - "scripts/supabase_sync.py"
  - "src/volpred/publisher/**"
  - ".claude/skills/feed-publisher/**"
  - ".claude/skills/trending-repost/**"
  # 選題階段 path-trigger（避免 rule 在需要 3-layer dedup 時 silent skip）
  - "storage/publication_candidates.json"
  - "storage/next_draft_candidate_*.md"
  - ".claude/skills/publication-candidates/**"
  # 寫文前引用實驗數字
  - "experiments/*/results.json"
  - "experiments/*/*_results.json"
  # 原 storage-and-publishing.md 觸發路徑（收窄：僅 daily / supabase / recalc 腳本）
  - "scripts/daily_update.py"
  - "scripts/recalc_metrics.py"
  - "storage/paper_trading.json"
---

# 發佈 + Storage 規則（合併 publish-checklist + storage-and-publishing）

觸及 feed / publisher / mile_ / feed-publisher skill / trending-repost skill / publication-candidates / experiment results / next_draft_candidate / paper_trading / daily_update / supabase_sync / recalc_metrics 路徑時 auto-load。對應 Mission 第 1 條「把文章寫好」+ 第 5 條「把曝光流量拉高」。

## 觸發時機對應 workflow 階段

- **選題階段** → `publication_candidates.json` / `next_draft_candidate_*.md` / `publication-candidates skill` → 規則在主線程挑主題時 auto-load，提醒 3-layer dedup
- **查數字階段** → `experiments/*/results.json` → 規則在 agent brief 引用 K 數字前 auto-load
- **寫文階段** → `feed-publisher skill` / `feed.json` / `mile_*.json` → 規則照舊觸發
- **熱門改寫 / 專欄文階段** → `trending-repost skill` → 套用雙發佈與 style-reference 規則
- **Pipeline 校驗** → `supabase_sync.py` / `publisher/**` → 照舊
- **Storage 維護** → `daily_update.py` / `recalc_metrics.py` / `paper_trading.json` → 規則提醒 sync/recalc 不手改資料

## Storage 硬規則（合併自 storage-and-publishing.md）

- `storage/` 是本地唯一資料源；**不手改歷史 JSON 補洞**（補洞 = 掩蓋產生它的流程缺陷）
- `paper_trading.json` **不手改歷史值**；回補與績效重算走既有流程（`recalc_metrics.py` / forward tracking）
- Supabase / Mirror sync **是流程責任**；不手動 PATCH 當正式修復 — 任何 sync 錯誤都要追到 `supabase_sync.py` 或 mirror 端

## 發佈硬規則

1. **一律走 `feed-publisher` SKILL**。不要自己拼 Write feed.json 或繞路 supabase_sync（會漏 LanceDB embed + notification + dedup）。
2. **thinking ≠ content**。`m.think()` 內部決策邏輯不是 Markdown 文章內容。文章必須是讀者能直接讀的 Markdown（標題 + 段落 + 表格 + 圖 + 結論）。
3. **Status 分流**：
   - **非時效性**（研究發現、回顧、方法論）→ `status=draft` 進池，由 release_pool cron 節奏釋出
   - **事件驅動**（CPI/NFP/FOMC/財報當天/地緣政治）→ `status=published` 立即發，不等節奏
   - **trending_repost**（熱門改寫 / havingchien-style 專欄文）→ feed 端預設 **`status=published`**，且 **FB / Ivan Lai 同步發佈是任務定義的一部分**
4. **每篇必備**：
   - 至少 2 張**真實圖表**（matplotlib PNG + Supabase upload；禁 ASCII / 文字框冒充）
   - 標明**數據來源**（yfinance / FRED / TAIFEX / K 編號）
   - 2000+ 字繁中正文（research）或 1500+ 字（general）
5. **寫前必做主題查重**：
   - `grep -i "關鍵詞" storage/reports/feed.json | head` 或
   - LanceDB semantic search（dist < 0.45 視為 hard duplicate，需換角度或放棄）
6. **數字必對齊實驗檔**：文章中每個統計量要能 byte-for-byte 對應到 `experiments/kXXX/kXXX_results.json` 或公開數據源。
7. **所有讀者向文章都必跑 `anti-ai-style`**：
   - `feed-publisher` / `trending_repost` / `daily_article` / 社群貼文文案，全部都要 co-run `.claude/skills/anti-ai-style/SKILL.md`
   - 若仍有明顯 AI 味、翻譯腔、套路式昇華、空泛評論，**不得 publish**
   - 這是 publish gate，不是可選優化
8. **若 task_type=`trending_repost`**：
   - 風格參考可用 havingchien-style Substack column
   - 但只能借 genre / pacing / commentary tone，**不可引用或貼近改寫原文**
   - 不能只寫成市場評論；必須符合 VolPred 平台文章標準：
     - 有真實證據鏈
     - 有可追溯數字
     - 最好有統計或至少一層簡單量化分析
     - 至少 1 表 + 1 圖支撐主論點
   - 若題目無法做出證據包與量化支撐，應放棄該題或改用其他 task type
   - 除 VolPred feed 外，需同步發到 **Facebook / Ivan Lai**
   - Facebook 文案必須是 **改寫後的 Facebook-native 版本**
   - Facebook 文案還必須符合 **Ivan Lai 舊文口吻**：
     - 先有個人觀察 / 判斷，再帶出主題
     - 句子短、段落短、允許留白
     - 不把 VolPred 全文濃縮成摘要
     - 不要寫成制式財經分析貼文或 SEO 式導語
     - 可保留少量畫面感，但不可做作
   - Facebook 主貼文**不要直接放連結**
   - VolPred 原文連結改為 **發文後留言區第一則留言**
   - 每日上限 **2 篇**，不可超發
   - 若 FB 失敗，可不阻塞 feed publish，但必須留下 retry log，不可直接略過

## 選題三層查重（主線程親為，不外包給 agent）

派寫作 agent 前，主線程**必做三層查重**，不只靠 agent 的 LanceDB：

### 層 1: publication-candidates skill
```bash
uv run volpred ops publication-candidates-summary
# 若 unavailable 或過期再重建：
uv run python scripts/build_publication_candidates.py
uv run volpred ops publication-candidates-summary
```
**只選 uncovered 或 missing_audience 的 K**。session_state.json 記得的 K 可能已有覆蓋。

### 層 2: feed 主題 grep
```bash
grep -i "核心關鍵詞" storage/reports/INDEX.md | head
# 或對特定 K:
grep -i "K<id>" storage/reports/feed.json | grep title
```
檢查既有文章標題與 tags，不是只看自家剛派的幾篇。

### 層 3: 跨文章主題 matrix
多篇並行時，主線程先手畫主題軸：`VT / VIX / 台股 / 事件研究 / 方法論 / 資產類 / 策略類`。每篇分配**不同軸**。LanceDB dist 0.6-0.8 **不足以排除主題重疊**（K1098 vs 台美 VT dist=0.769 仍高度相關）。

### 層 4: Narrative-arc dup check（2026-05-17 新增，K650/K1199 retract 教訓）

**Trigger**：3-layer 全 PASS 仍可能漏掉「**邏輯結構相同、外殼換掉**」的 dup。

**主線程派寫作 agent 前必做**：

1. **抽取候選文章的 narrative arc**（一句話模板）：
   - 「N 個實驗 → M 個 established facts / cheatsheet」
   - 「失敗訊號 → 換變數重做 → 又失敗 → 結構性結論」
   - 「我們檢驗 X 是否能解釋 Y → NULL → 維持原假設」
   - 「跨 N 個市場驗證 → 同一現象出現」
   - 「Paper N 結果 byte-exact 重現 → PASS」
   - 「Strategy X 在 OOS 崩潰 → Sharpe 變雜訊」

2. **grep 過去 30 天 feed**：把候選 arc 的關鍵詞組對比：
   ```bash
   jq -r '[.[] | select(.published_at > "2026-04-17") | {id, title}] | .[] | "\(.id) \(.title)"' storage/reports/feed.json | grep -iE "<arc keywords>"
   ```
   例：候選是「N 個實驗 meta-analysis」→ 搜 `meta.analysis|meta-analysis|N 個實驗|N 筆|實驗回顧|established facts|cheatsheet`

3. **同 K-cluster 鄰近度**：候選 K 屬哪個 cluster？（K644/K200/K650/K644 都是 meta-analysis；K1168/K1172/K1173 都是 EM ladder；K1100g_d* 都是 OFI×VIX）
   - jq scan `feed.json` 同 cluster 過去 14 天文章數
   - **同 cluster ≥2 篇近 14 天 → 強制換 cluster 或寫差異化證明**

4. **「換變數變奏」test**：候選文章是否只是把過去文章的某個參數換掉？
   - 換 N 數量（24→271 個實驗）→ **同 arc**
   - 換 cut-point 切法（固定 vs 動態）→ **同 arc**
   - 換 proxy 來源（yfinance vs SEBI）但結論仍 NULL → **同 arc**
   - **同 arc 不算新文章**，要嘛放棄要嘛升級到真正新角度（e.g. 不只擴大 N，而是改 metric definition 或 introduce new dimension）

5. **派 agent 前在 brief 寫死**：「不要做以下變奏：[list]，這些已被 mile_xxx 覆蓋過」。讓 agent 不能用同 arc 交差。

**Post-publish retract trigger**：若已發佈後才發現 narrative-arc dup（用戶或 audit 抓到），**標 `status=retracted` + `retracted_reason="logical_dup_with_prior"` + `retracted_dup_of=[mile_xxx]`**，feed.json 保留 entry 做 audit trail，前端按 status 過濾不顯示。範例：mile_490999f6 (K650) + mile_b5a91c4d (K1199) 於 2026-05-17 retract（用戶 feedback 觸發）。

## Novelty Quota — 跳脫主題研究（20%）

**規則**：每 10 個新實驗 / 新文章中，至少 **2 個**（20% quota）必須完全跳脫既有主題軸的 **contrarian research**。

### 既有 dominant clusters（需刻意避開）
- VT / volatility targeting 策略
- VIX / VIX 家族 / VIX term structure
- 台股 / 0050.TW / TAIFEX
- GARCH / GJR / A4f / multiplicative GARCH
- Earnings event / FOMC / macro event study
- Paper trading / backtest / Sharpe 比較
- Leverage direction / asymmetric vol

### 跳脫主題候選（under-explored）
- 加密貨幣機制（除 BTC-VIX spillover 外）：DeFi yield、stablecoin depeg、options 流動性
- HFT / market microstructure：order book dynamics、liquidity、maker-taker
- Options surface：vol surface dynamics、gamma exposure、dealer positioning
- Macro fundamental：inflation regime、yield curve、currency crisis
- Behavioral finance novel：sentiment dispersion、social media alpha、meme dynamics
- Commodity-specific：OPEC cycle、agricultural seasonality、energy transition
- 新興市場 ex-台：VN / IDX / KOSPI 的 volatility landscape
- 規範變更：SEC/FINRA/FSA 新規 vs 市場行為
- AI/ML 新方法：transformer、conformal prediction、ICL
- 非傳統資產：art indices、carbon markets

**檢查點**：選題時**主線程必算**「最近 10 個新 K + 10 篇新文章主題軸分佈」。若 8+ 在 dominant clusters → **強制下輪選 contrarian**。

## 事件驅動文章配額

一個事件最多 3-4 篇（T-7 + T-2 + T+0 + 可選 T+1）；TSMC 2026-04-13 單事件 5+ 篇是踩過坑的反面教材。

完整 FOMC / CPI / NFP / Earnings populate playbook 見 `.claude/skills/feed-publisher/references/event-article-templates.md`（feed-publisher skill 觸發時載）。

## 失敗模式（不要再犯）

- 把 thinking/reasoning 當成文章 content publish
- 同一事件連發 5+ 篇（過度集中，讀者疲勞）
- 圖表用 ASCII 或「[fig X: ...]」placeholder 冒充
- 非時效文章直接 published（繞過池節奏，壓縮未來 release slot）
- 事件驅動文章設 draft（時效性流失）
- 不標 K 編號或數據來源（讀者無法追溯 / 審稿人無法驗證）
- 手改 `paper_trading.json` 歷史值（應走 `recalc_metrics.py` 流程）
- 手動 PATCH Supabase / Mirror 補 sync 斷點（應修 `supabase_sync.py`）

## Markdown 表格 cell 內 `|` 必跳脫（2026-04-29 K549 教訓）

統計符號常用 `|t|`, `|z|`, `|r|`, `|p|`, `|t-stat|`, `|F|` 表 |statistic|。**這些 pipe 在 markdown 表格 cell 內若未跳脫會炸渲染** — GFM/CommonMark renderer 把 cell 內 pipe 當 cell 分隔符 → row 的 pipe count 不對 header → 整張 table broken。

**架構性自動防護**（不靠 agent 自律）：
- **PRIMARY** `volpred.publisher.publisher._append_to_feed` 寫 feed.json 前呼叫 `markdown_table_sanitizer.sanitize_markdown_tables()` → 自動 escape `|<token>|` 為 `\|<token>\|`（短 alphanumeric token 才匹配，不會誤傷散文）
- **SECONDARY** `scripts/supabase_sync.py::sync_article` 寫 Supabase 前再跑同 sanitizer（belt-and-suspenders；catch 繞過 publisher 的 path）
- 兩層 print warning 列 fix-line / unfix-line

**Agent / 主線程寫文時仍建議**主動寫 `\|t\| ≥ 3.0` — 但忘了 sanitizer 會兜底。

**Test gate**：`tests/test_markdown_table_sanitizer.py`（9 cases，含 K549 verbatim regression case）。改 sanitizer 必跑。

**反面教材**：
- K549 `mile_5c662be0` line 32 / line 70 寫 `|t|>3.0` / `Pass |t|>3?` 沒跳脫
- K1018 `mile_b4cf48f9` 同 session 並行 agent 部分跳脫但 line 28 漏了 — agent 行為不一致證明 manual escape 不可靠

## 交叉參考

- `.claude/skills/feed-publisher/SKILL.md`（發佈 SOP 完整版）
- `.claude/skills/feed-publisher/references/event-article-templates.md`（事件驅動文章 populate playbook）
- `.claude/skills/publication-candidates/SKILL.md`（選題雙軌機制）
- `docs/architecture.md` 發佈流程區塊
