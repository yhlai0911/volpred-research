---
paths:
  # 原 publish-checklist.md 觸發路徑
  - "storage/reports/feed.json"
  - "storage/reports/mile_*.json"
  - "scripts/publish_*.py"
  - "scripts/supabase_sync.py"
  - "src/volpred/publisher/**"
  - ".claude/skills/feed-publisher/**"
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

觸及 feed / publisher / mile_ / feed-publisher skill / publication-candidates / experiment results / next_draft_candidate / paper_trading / daily_update / supabase_sync / recalc_metrics 路徑時 auto-load。對應 Mission 第 1 條「把文章寫好」+ 第 5 條「把曝光流量拉高」。

## 觸發時機對應 workflow 階段

- **選題階段** → `publication_candidates.json` / `next_draft_candidate_*.md` / `publication-candidates skill` → 規則在主線程挑主題時 auto-load，提醒 3-layer dedup
- **查數字階段** → `experiments/*/results.json` → 規則在 agent brief 引用 K 數字前 auto-load
- **寫文階段** → `feed-publisher skill` / `feed.json` / `mile_*.json` → 規則照舊觸發
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
4. **每篇必備**：
   - 至少 2 張**真實圖表**（matplotlib PNG + Supabase upload；禁 ASCII / 文字框冒充）
   - 標明**數據來源**（yfinance / FRED / TAIFEX / K 編號）
   - 2000+ 字繁中正文（research）或 1500+ 字（general）
5. **寫前必做主題查重**：
   - `grep -i "關鍵詞" storage/reports/feed.json | head` 或
   - LanceDB semantic search（dist < 0.45 視為 hard duplicate，需換角度或放棄）
6. **數字必對齊實驗檔**：文章中每個統計量要能 byte-for-byte 對應到 `experiments/kXXX/kXXX_results.json` 或公開數據源。

## 選題三層查重（主線程親為，不外包給 agent）

派寫作 agent 前，主線程**必做三層查重**，不只靠 agent 的 LanceDB：

### 層 1: publication-candidates skill
```bash
uv run python scripts/build_publication_candidates.py
jq '.top_10_uncovered, .missing_general_top5, .missing_research_top5' storage/publication_candidates.json
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

## 交叉參考

- `.claude/skills/feed-publisher/SKILL.md`（發佈 SOP 完整版）
- `.claude/skills/feed-publisher/references/event-article-templates.md`（事件驅動文章 populate playbook）
- `.claude/skills/publication-candidates/SKILL.md`（選題雙軌機制）
- `docs/architecture.md` 發佈流程區塊
