# Article 24h-rule Audit — mile_9839822d

**Audit timestamp**: 2026-07-01 00:18 台灣時間
**Article published**: 2026-06-29 21:00 UTC (~27h 前)
**Auditor**: Codex CLI (gpt-5.4 medium, source-code level)
**Trigger**: 24h Codex review per `.claude/rules/agent-delegation.md` K1018 lesson
**Verdict**: FAIL → fixed → re-verified online

## Findings (Codex)

| # | Severity | Issue | Fix |
|---|---|---|---|
| 1 | **CRITICAL** | Lead 句把 REMX/LIT 倍數對調，且寫成「最大日跌幅」— 實際是 absolute jump，2025-04-09 是反彈不是崩跌 | 改寫 lead：LIT=10.5x、REMX=9.2x、明示「絕對值，4/9 是反彈」 |
| 2 | **HIGH** | 「勝率不會高」「你看到的某次大跳是運氣，不是規律」超出 event-study scope（code 自述非 trading backtest） | 改「本樣本未支持穩定交易訊號」+ 加事件研究 ≠ 交易回測 caveat |
| 3 | **MEDIUM** | 「七種中重稀土」+「川普關稅政策正在發酵」K1575 raw outputs 無記載 | 改「中重稀土相關項目」+「美中關稅與其他總體新聞」 |
| 4 | **LOW** | 「兩三個極端值」CSV ratio>10 觀測 17 個（非 3 個） | 改「少數高值（兩個事件週的若干 ETF）」 |

## Number-check summary (all from k1575_results.json / event_ticker_metric_results.csv)

- 8 events, 13 ETFs ✓
- 312 RV tests + 104 jump tests, Bonferroni α=0.000120 (=0.05/416) ✓
- mean=2.45, median=0.87, ratio>1=46.2% ✓
- benchmark contrasts -0.74 / -0.45 / -1.78 / -0.39 ✓
- spillover (direct − benchmark) -2.20 (RV5), -1.17 (jump5) ✓
- SPY rv5=15.83, QQQ rv5=10.56 ✓

## Methodology check

- Multiple testing: PASS (Bonferroni family-wise on 416 p-values)
- Lookahead: PASS (PRE T-30..T-6, POST starts T+1, T=0 = first trading day ≥ announcement; DRC anchor 2025-02-24 correctly shifted)
- Seed: PASS (42, bootstrap 1000 anchors)
- Metric wording caveat: rv5/rv22/t1_r2 are r² ratios, not std-dev ratios — 文章用「波動率幾倍」可讀但不精確

## Resolution

Fixes applied to `storage/reports/feed.json` content; `uv run volpred ops sync-all` pushed to Supabase 2026-06-30 16:18 UTC (verified via REST: 4/4 new phrases present, 3/3 old phrases absent). Front-end ISR cache will refresh on next revalidation cycle.
