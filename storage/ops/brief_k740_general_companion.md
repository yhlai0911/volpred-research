# Task: K740 general-audience companion article

**Model**: claude-opus-4-8 / xhigh (per model_router)
**Task pool id**: `K740_article_general_audience_rewrite_2fb1dfb3`（完成後請 complete 此 task）
**Parent**: content_audience_mislabel_backlog_45 / source_article = `mile_2fb1dfb3`

## 背景：為什麼有這張單（先看懂，不要照字面做）

`mile_2fb1dfb3`（2026-06-12）原本是 general，被 audience audit flip 成 research。
**flip 的機制原因**：`publisher._infer_audience` rule 6 — 文中出現 Sharpe、p-value / Spearman rho
等 ≥2 個學術關鍵詞就判 research。**不是因為它寫得艱澀** —— 它的行文其實已經很白話。

所以本任務的真正目標是：**確認 general 讀者是否真的因此失去覆蓋，若是，補一篇不含學術關鍵詞的
general 版**。「被 flip 走」≠「有覆蓋缺口」，這一點務必自己驗。

## 已完成的查重（不要重做，但要延伸）

hourly-slot-2 於 2026-07-20 已做：

- `check_arc_dedup.py --k-id K740 --audience general` → exit 0，verdict `warn_arc_near_miss`
  （非 duplicate，但**不是綠燈**）。近似清單無一命中本題結論。
- Layer-2 手動 grep feed（405 篇 general published）→ SPY+GLD 分散主題**覆蓋極密集**。

**你必須先判定差異化是否成立的關鍵對照篇**：

| 文章 | 日期 | 為何要比對 |
|---|---|---|
| `mile_343b9daf`「我測了 10 種投資策略，結果最笨的那個贏了」 | 2026-03-18 | **最高風險** — 疑似同一份 meta-analysis 的早期版本（10 套 vs 本次 14 套），結論同構 |
| `mile_651c242d`「好策略被成本吃掉 27%：11 個 VT 策略的實施費用拆解」 | 2026-06-12 | 同日、同策略池家族 |
| `mile_29dad897`「為什麼 50/50 SPY/GLD 幾乎不可能被打敗？」 | 2026-03-24 | 分散結論已被覆蓋 |
| `mile_9b72bea3`「200 個實驗後的結論：投資最該做的一件事」 | 2026-03-24 | 同一「樸素勝複雜」母題 |

**硬性要求**：讀完 `mile_343b9daf` 全文後，若你判定本題相對它**沒有實質新資訊**，
→ **不要寫**，直接把 task complete 成 succeeded 並在 result 寫明 arc-covered + 對照證據。
寧可回報覆蓋已足，也不要產出第二篇同義文章（2026-07-11 教訓：gate 回 exit 0 但線上早有同題，
兩個 writer agent 白做工）。

可主張的差異化（若成立才用）：本次是 **14 套**、forward-tracked 紙上交易至 **2026-03-27**，且首次
把「複雜度 vs 風險調整後報酬」做成**明確的統計檢定**（結果是**沒有關係**）—— 這個 null 是
`mile_343b9daf` 沒有的。

## 若決定寫：必須逐字保留的數字（不得改寫、不得四捨五入、不得杜撰新數字）

來源 `experiments/k740/k740_strategy_meta_analysis_results.json`
（腳本 `experiments/k740/k740_strategy_meta_analysis.py`；資料 `storage/paper_trading.json` +
`storage/strategy_metrics.json`；期間 2023-01-04 ~ 2026-03-27，共 14 套策略）。
**開工前先開這個 JSON 核對每個數字**，不要只信下表（下表轉錄自已發表文章）：

- 第一名：保守型 VT（Piecewise）— 綜合分數 **0.790**、Sharpe **3.158**、最大回撤 **-2.48%**、月勝率 **87.2%**
- 只做 SPY 的策略平均 Sharpe **1.173**；SPY + GLD 平均 **2.544**；差 **1.371**
- 複雜度與 Sharpe 的 Spearman rho **0.294**、p-value **0.308** → **統計上談不上關係（null result，必須誠實寫出這是 null）**
- 月頻策略平均 Sharpe **2.339**；日頻 **2.213**

**限制與 caveat 一律保留並用白話講出來**：這是**紙上交易（paper trading）forward-tracked 紀錄**，
不是真實成交；14 套策略樣本很小，rho 的 p=0.308 本來就代表「測不出關係」而非「證明沒關係」。

## 寫作規範（開工前必讀，不可跳）

1. `.claude/skills/trending-repost/SKILL.md`
2. `.claude/skills/anti-ai-style/SKILL.md`
3. `.claude/rules/publishing.md`

- **關鍵**：general 版**不得出現 Sharpe / p-value / Spearman / QLIKE / GARCH 等學術關鍵詞**，
  否則 `_infer_audience` 會再次把它判成 research，整個任務目的落空。
  用白話替代（例：Sharpe → 「每承擔一分風險換到的報酬」；rho/p-value → 「兩者高低沒有跟著一起走，
  而且這個結果弱到不能排除只是巧合」）。**替代說法必須數字照舊**。
- 寫後跑 `anti-ai-style/references/editor-sop.md` 3 階段 9-checklist。
- **publish 前必跑** `uv run python scripts/anti_ai_gate.py --file <draft>`，exit 0 才能發；
  MUST 命中任一條 = 整篇改寫到 PASS，**禁止 --force**。

## 發佈

`uv run python scripts/publish_draft.py`，`status=draft`、`audience=general`、
`experiment_refs=['K740']`、要求 `sanitize_applied=0`。
**不要**去 relabel 或弱化已修正的 research 來源 `mile_2fb1dfb3`。

## 收尾

- `uv run python scripts/task_pool_claim.py complete --id K740_article_general_audience_rewrite_2fb1dfb3 --status succeeded --result "<寫了哪篇 / 或 arc-covered 未寫的理由>"`
- work_log 一筆（`scripts/append_work_log.py`）。
- **禁止**自己寫 knowledge.json。

## 已存在的資產（先看，不要重造）

`experiments/k740/` 已有 `k740_general_figs.py` 與 `k740_complexity_vs_sharpe.png`
—— 顯示先前已為 general 版準備過圖表。先確認這些圖可直接沿用或需重跑，不要重造輪子；
若這代表 general 版其實已經寫過，那更要優先確認是否 arc-covered。
