---
date: 2026-05-30
paper: vix-sufficiency (Paper 4)
section: Table 3 (Strategy Comparison) + §5 narrative around line 495
trigger: Paper4_DIV3_Table3_Sharpe_ranking (next_tasks pending_main_thread)
severity: MEDIUM (narrative-affecting, no Harvey-threshold change)
type: errata + source rebinding
---

# Errata — Table 3 BH 50/50 Sharpe ranking flip

## 發現

Paper Table 3 row "Buy-and-hold 50/50 SPY/GLD" 標示 Sharpe = **0.947** 與 12/VIX = 0.870
→ 結論 "static 50/50 outperforms every dynamic strategy" + "VT sacrifices return for drawdown protection"。

實際來源追蹤：

| 來源 | BH 50/50 Sharpe | 期間 | N |
|------|----------------|------|---|
| paper Table 3（原） | 0.947 | — | — |
| `experiments/k507/k507_dynamic_allocation_results.json -> full_sample_results.static_5050.sharpe` | 0.947 | 不同短 sample | 5339 days |
| **`experiments/k731/k731_vix_term_structure_results.json -> full_sample_strategies."BH 50/50".sharpe`（registered canonical for 2008–2026）** | **0.827** | 2008-01-01 to 2026-03-30 | 4564 days |

Paper Table 3 的其餘 row（12/VIX 0.870、Contango Boost 0.880）已與 K731 一致；Table 3 caption 寫「longest common sample for each pair」隱含 per-row 不同 sample，但實際 BH row 與 12/VIX row 期間不同 → **未對齊**。

## 影響

採 K731 canonical（two benchmarks 同期同 sample）：

| 策略 | Sharpe (K731 2008-2026) | MDD (%) | $\Delta$Sharpe vs 12/VIX |
|------|--------------|---------|--------------------------|
| Buy-and-hold 50/50 SPY/GLD | **0.827** | $-32.5$ | $-0.043$ |
| 12/VIX (SPY/GLD) | **0.870** | $-32.2$ | — (reference) |

**Ranking 翻轉**：12/VIX (0.870) 略勝 BH (0.827) +0.043；MDD 幾乎一致（-32.18 vs -32.49）。

→ 原 narrative「BH 打敗所有動態策略 + VT 用報酬換 drawdown 保護」不成立 — 兩個 benchmark 期間對齊後 12/VIX 報酬與 drawdown 雙線勝出。

**訊號類 strategies 不受影響**：Signal rows 與 12/VIX 對比的 $\Delta$Sharpe 與 DM $|t|$ 不變；Harvey threshold 0/11 通過的核心 vix-sufficiency 結論不變。

## 修正

1. `main_v4.tex` Table 3 line 472 (BH row): Sharpe `0.947 → 0.827`、$\Delta$Sharpe `--- → -0.043`、加 `% source: experiments/k731/.../full_sample_strategies."BH 50/50".sharpe`
2. `main_v4.tex` Table 3 line 473 (12/VIX row): $\Delta$Sharpe `-0.077 → ---`（reference column）、MDD `-32.3 → -32.2`、加 `% source: ...12/VIX"`
3. `main_v4.tex` line 495 narrative 重寫（BH 不再 outperform，改為 12/VIX 略勝 + MDD 幾乎一致）
4. `reproduce.py` Check T3 expected 已是 0.827（與 K731 一致）— **本質問題是 reproduce gate 比對 JSON↔JSON 而非 LaTeX↔JSON**。本 errata 後 paper LaTeX 0.827 與 expected 一致，gate 自然通過。長期 fix（不在本 errata 範圍）：加 LaTeX 數字 extractor 雙向驗證。

## 不在本次修正的相關 follow-up

- §1 intro line 98 "VT sacrifices average returns 3.49%/year for 12/VIX" — 來源 K738 cross-asset insurance framework，與 K731 不同數據集；不受本 errata 直接影響但敘事張力（"VT 用報酬換 drawdown"）需要重新校準到 K731 期間 BH-12/VIX 報酬幾乎一致的新事實。建議下一輪 paper review 處理。
- main.tex / main_v2.tex 舊版本同樣含 0.947 — 不動舊版，僅修 active main_v4.tex。

## 參考

- `reproducibility_audit/diff_report.md` DIV-3（2026-04 已標記未 fix）
- `reproducibility_audit/main_tex_numbers.csv` Table3 T3-row-BH MISMATCH_PERIOD
- K731 results: `experiments/k731/k731_vix_term_structure_results.json`
- K507 results: `experiments/k507/k507_dynamic_allocation_results.json`（不再為 Table 3 來源）
