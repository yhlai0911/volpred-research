> **🔒 CONSUMED 2026-04-26T15:45Z — published as mile_3eb8657c**. Pool went 5→6. Do not re-dispatch.

# Next Draft Candidate: K908 MF-GJR + HistSim — Universal VaR/ES Solution

**Prepared 2026-04-26 by main thread** as preemptive brief for next `draft_pool_low` remediation. Replaces depleted brief pool (K957 / K1091 / K1092 / K1174 / cross_market_binary 全 consumed/downgraded as of 2026-04-19).

## K908 Overview

**Score**: 6 (★★★ from `publication_candidates.json` `missing_general` 第 5 位; 已 covered for research, missing general audience)
**Title**: K908: MF-GJR + Student-t/HistSim — Complete VaR/ES Solution
**Coverage**: research-only (research mile_* article published earlier); general-audience uncovered

## Why this topic works

- **Self-contained 故事**：「最佳預測模型 ≠ 最佳風控」→ K889 的 MF-GJR 預測冠軍但 VaR 全 FAIL（用 Normal）；K908 加 HistSim 後 VaR/ES 變 universal solution
- **跨 3 資產 punch**：SPY / QQQ / 0050.TW 都 6/6 Trinity PASS（Kupiec + Christoffersen + Basel Trinity）— 1% 和 5% VaR 都過
- **台股 angle**：0050.TW Student-t df ≈ 4.7-6.6（最厚尾 vs SPY 6-9 / QQQ 6-11）— 賴老師台灣讀者會 relate「為什麼台股風控要更謹慎」
- **不涉及 Paper 敘事**：K908 是 risk-management 完整解，獨立於 paper 1-9，可單篇放出無 framing 風險
- **Mission L8「把文章寫好」**：reader-friendly + 真實圖表 + 跨市場故事 + 方法論教訓四要素齊全

## 具體數字（3 組必引）

- **MF-GJR + HistSim**：SPY / QQQ / 0050.TW 全部 1% 和 5% VaR **6/6 Trinity PASS**（Kupiec + Christoffersen + Basel）
- **MF-GJR + Student-t**：SPY 和 0050.TW PASS，**QQQ FAIL**（QQQ 尾部較輕，Student-t fixed parametric form 對 QQQ 不夠 flexible）
- **Student-t df 估計**：SPY ~6-9 / QQQ ~6-11 / 0050.TW ~**4.7-6.6**（台股最厚尾）；df refit 每 63 天 + `sqrt((df-2)/df)` scale correction

## Article Skeleton（general audience 1500-2000 chars）

1. **Intro**: K889 的「最佳預測模型 vs 1% VaR 全 FAIL」矛盾 — 預測準 ≠ 風控好
2. **Why Normal fails for VaR**: 預測模型輸出條件變異數，但實際報酬尾部比 Normal 厚
3. **兩個解法 candidate**: Student-t（parametric, 1 parameter df）vs HistSim（non-parametric, 用標準化殘差歷史分佈）
4. **跨 3 資產實測結果表**: 3×2 表格（資產 × Student-t/HistSim）標 PASS/FAIL
5. **Why HistSim 全勝**: parametric Student-t 假設 symmetric 厚尾，HistSim 順勢吃下 skewness（讀者直觀解釋）
6. **台股最厚尾**: df 4.7-6.6 vs SPY 6-9 — 為什麼台股風控要更謹慎（讀者本地 angle）
7. **結論**: MF-GJR(VIX) + HistSim = 預測 + 風控雙維度 universal solution；兩個維度獨立優化

## Charts needed（2 real matplotlib PNG）

1. **跨資產 VaR Trinity Heatmap**: 行 = SPY/QQQ/0050.TW，列 = (MF-GJR+Student-t, MF-GJR+HistSim) × (1% VaR, 5% VaR) → 4 列；綠色 PASS / 紅色 FAIL；視覺化 HistSim 全綠 vs Student-t QQQ 紅
2. **Student-t df 隨時間變化**: 三條線（SPY / QQQ / 0050.TW），x=日期 2019-2026，y=df 估計值；highlight 0050.TW 線最低（最厚尾）

## Data sources

- `experiments/k908/k908_mfgjr_student_t_var_es_results.json` — 5 模型 × 3 資產 OOS 結果
- `experiments/k908/README.md` — 方法 + 評估指標完整說明
- `experiments/k889/` — MF-GJR 預測 baseline 對照（VaR FAIL 的源頭）
- yfinance: SPY / QQQ / 0050.TW / ^VIX, 2005-2026
- OOS 期：2019-01 ~ 2026-03（~1821 天）

## Dispatch when

- Pool drops below 4 OR 主線程主動補 general-audience pool（目前 missing_general=22 偏多）
- 用 Claude general-purpose agent + feed-publisher skill；agent prompt 必包含：
  - 引用本 brief 路徑
  - 必須 read `experiments/k908/k908_mfgjr_student_t_var_es_results.json` 並 byte-for-byte match 文章中數字
  - status=draft 進池（非時效性）
  - audience=general
  - 至少 2 張真實 matplotlib PNG（不接受 ASCII / 文字框）
  - 1500-2000 CJK chars

## Cross-link refs

- K889: MF-GJR baseline（預測冠軍但 VaR FAIL）
- K802 / K825: Student-t / HistSim 修復 GJR 的早期實驗
- K1041 / K1092: DCC-A4f portfolio VaR（research audience covered）

## Status

**Ready** — 主線程已驗證 experiments/k908/ 檔案存在 + README 數字齊全。等下次 dispatch trigger。

**Do NOT consume this memo manually**；agent dispatch 後改本 memo header 為 `🔒 CONSUMED <date> — published as mile_<id>` 留 audit trail。
