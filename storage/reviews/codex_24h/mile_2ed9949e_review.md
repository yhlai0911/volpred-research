# Codex 24h Review — mile_2ed9949e (K1107)

- **Article**: 財報日前，分析師說「IC 設計股波動較小」— 背後只有 4 家公司，其中 2 家數字截然相反
- **Draft source**: `storage/reports/feed.json` (`mile_2ed9949e`)
- **Task**: `paper_review_mile_2ed9949e`
- **Reviewed**: 2026-06-08 台灣時間
- **Reviewer**: Codex CLI
- **Verdict**: **FAIL**

## 結論摘要

這篇的核心表格與標題把兩種不同口徑的 source 混在一起。`K1107` 的 event-panel `log_r2_surprise` 數字確實是 `-2.40 / -2.75 / -2.03 / -1.45`，但四家都是負值；文章卻把聯詠、群聯寫成「明顯偏高」，再進一步推出「4 家裡，2 家往下，2 家往上」。

這個「兩上兩下」其實來自 `K1104` 的 firm-level `theta2` 符號，不是 `K1107` 的 event-panel 主結果。由於錯誤發生在標題、主表與核心解釋段，屬於結論級 source mismatch，不是措辭或摘要層面的瑕疵，因此本篇應判 `FAIL`。

## Numeric verification

下列數字已對上 `experiments/k1107` source：

| Claim area | Source | Verified value |
|---|---|---|
| Panel sample size | `k1107_results.json.panel_summary.n_events` | `1377` |
| Fabless event count | `k1107_panel.csv` | `239` |
| Foundry coef with time FE | `regression_r2_surprise_time_fe` | `0.8012`, `t=2.158`, `p=0.042` |
| Fabless coef with time FE | `regression_r2_surprise_time_fe` | `0.2573`, `t=0.967`, `p=0.344` |
| MediaTek mean log_r2_surprise | `k1107_panel.csv` | `-2.3993` |
| Realtek mean log_r2_surprise | `k1107_panel.csv` | `-2.7509` |
| Novatek mean log_r2_surprise | `k1107_panel.csv` | `-2.0272` |
| Phison mean log_r2_surprise | `k1107_panel.csv` | `-1.4525` |

四家的 `log_r2_surprise` 都是負值，沒有任何一家在 `K1107` source 裡呈現文章所寫的「偏高」方向。

## Findings

1. **Core table mixes K1107 event-panel means with K1104 firm-level signs** — `storage/reports/feed.json`, `experiments/k1107/k1107_panel.csv`, `experiments/k1104/k1104_results.json`

   文章表格列出四家公司 `-2.40 / -2.75 / -2.03 / -1.45`，這些數字對應的是 `K1107` 的公司別 event-panel 平均 `log_r2_surprise`。但文章又把聯詠、群聯標成「明顯偏高」，並寫成「2 家往下，2 家往上」。這個方向不是 `K1107` 的結果，而是 `K1104` firm-level `theta2` 的符號：
   - MediaTek `theta2=-0.001609`
   - Realtek `theta2=-0.002385`
   - Novatek `theta2=+0.000702`
   - Phison `theta2=+0.001199`

   換句話說，文章把 `K1104` 的解釋框架直接套到 `K1107` 的主表數字上，造成讀者看到的主結論與 source 不一致。

2. **Title and lead paragraph overstate a source-incompatible mechanism** — `storage/reports/feed.json`, `experiments/k1107/README.md`

   `K1107` README 的正式結論是：
   - Fabless 類股在 model-free event vol surprise 下 **不顯著**
   - Foundry 類股係數為正且顯著

   它支持的是「Fabless 內部異質性 + equal-firm vs equal-event weighting 差異」，不是「同一張 event-panel 表裡兩家高、兩家低」。目前標題與前兩段把錯誤機制包裝成 reader-facing main hook，屬於高嚴重度。

3. **Foundry paragraph is directionally plausible but phrasing exceeds the exact source claim** — `storage/reports/feed.json`, `experiments/k1107/k1107_results.json`

   `K1107` 能支持的是 foundry dummy 在 panel regression 中相對基準組為正且顯著；它不等於「台積電和聯電在財報日的波動放大現象」這種絕對層級敘述。這不是本篇最致命的錯，但若後續修稿，這段也應改成相對效果口徑。

## Lookahead audit

- PASS — 這是事件研究與 panel 描述，沒有交易規則回測，不涉及 signal-at-t 乘 return-at-t 的 lookahead。
- PASS — `K1107` README 與輸出都明確使用事件日前 baseline 視窗與 event-day 實現值做 ex-post 比較，不是前視性策略評估。

## Action taken

1. 已新增本次 24h review 記錄。
2. 已在 `feed.json` 的 `details.errata_24h_review` 掛上本次 review 與 `FAIL` verdict，方便後續 publish / sync 流程追蹤。

## Recommended follow-up

1. 這篇應先改稿再維持 published，至少要把主表、標題 hook、與「2 上 2 下」段落重寫成與 `K1107` 一致。
2. 若要保留「聯詠/群聯正向、聯發科/瑞昱負向」這條故事線，必須明確改寫成 `K1104` firm-level `theta2` 的結果，不能再沿用 `K1107` event-panel 表格與 sample size。
