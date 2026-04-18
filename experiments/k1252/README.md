# K1252 — Milestone 文章發佈：為什麼 GARCH-MIDAS 跨市場估計要跑 100 次？

[提出: Claude, 執行: Claude]

## Purpose

將 K1213 → K1216 → K1216b → K1216c 共四個實驗所揭露的**跨市場 pooled MLE optimizer fragility**（9/9 markets 全 FRAGILE）寫成一篇 research-audience feed 文章，傳達：

1. 單次 L-BFGS-B 估計在 GARCH-MIDAS shared-MIDAS + stock-FE-GJR 聯合似然面上**會系統性卡在次要 local minimum**
2. 100-multistart 是必要的 methodological baseline，不是 nice-to-have
3. Asymmetric refinement（EM refined but DEV still canonical）會產生 artefact sign flip（K1216b ρ=-0.071 是假結果）
4. 對稱 refined 後 Paper 2 §5 結論趨向弱正相關、非顯著（ρ=+0.379, p=0.20, N=13）

## Deliverables

- `k1252_article.md` — 文章原稿（繁體中文 1000-1500 字）
- 經 `volpred ops publish-milestone` CLI 發佈到 feed，status=`draft`

## Source experiments

| K | 發現 |
|---|------|
| K1171 | 原始 AU pooled θ_rel=0.150 (below ladder) |
| K1213 | AU 100-multistart basin-B θ_rel=1.476, LR=198.94 |
| K1216 | BR/IN/MX 100-multistart WIDESPREAD_FRAGILITY |
| K1216b | CH/ID 100-multistart → 5-EM 全 fragile; asymmetric refinement artefact ρ=-0.071 |
| K1216c | US/EU/JP/TW 100-multistart → 4 DEV markets 全 fragile; 9/9 根本原因=methodology; 對稱 refined ρ=+0.379 |

## Data sources

- `experiments/k1216c/k1216c_results.json` — 最終 9-market Spearman table、per-market LR、basin stats
- `experiments/k1213/README.md` — AU basin-B 發現敘事
- `experiments/k1216b/README.md` — asymmetric refinement 警示
- `storage/memory/knowledge.json` K1207/K1213/K1216b/K1216c 條目

## Files

- `README.md` — 本文件
- `k1252_article.md` — 發佈的文章正文（Markdown 原稿）

## Notes

- Worktree scope：只新增 `experiments/k1252/` 檔案與透過 CLI upsert feed；不手改 `storage/reports/feed.json`
- 文章中所有數字 verbatim 抄錄自 `k1216c_results.json` 與 K1213/K1216b README
- 圖表 embed 既有 PNG：`k1216c_9market_trajectory.png` (9-market Spearman trajectory)、`k1216c_US_basin_hist.png`（US basin histogram 代表）
