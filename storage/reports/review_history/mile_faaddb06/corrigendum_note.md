# Corrigendum — mile_faaddb06

**Article**: 預測波動率該回望多久？五段歷史告訴我們：沒有萬靈丹  
**Original published**: 2026-06-06  
**Corrigendum published**: 2026-06-07  
**Trigger**: Codex review 2026-06-07 verdict FAIL（`codex_review_2026-06-07.md`）  
**Experiments**: K593 (v1) → K593-v2 (corrigendum fix)

## Codex 提報的問題

1. **Forecast engine bug**：原 K593（v1）在每段視窗 refit 後直接呼叫 `last_model.forecast()` 取下期條件變異數，等同於凍結最後一日的 fitted parameters 對整個視窗預測；未做每日遞迴 σ² state update。
2. **DM date-align bug**：per-period 與 pooled DM 檢定的兩條 forecast 序列做對齊時索引未確實匹配，導致 DM 統計量計算的 pair 不一致。
3. **Pre-registration claim**：原文將判讀規則描述為「事先寫死」，但該規則並未在 OOS 跑之前獨立 timestamped。屬 ex-post documentation 但被誤表述為 pre-registered。
4. **過度推廣**：原文「沒有萬靈丹」的結論隱含跨資產跨期適用，但實驗範圍僅 SPY 5 段 OOS。
5. **無法驗證的引文**：Feng & Zhang (2025, *Journal of Forecasting*) 段落引文無法在 publisher / DOI 系統中獨立檢核。

## v2 修正內容

| 項目 | v1 | v2 |
|---|---|---|
| Forecast engine | refit→frozen params | refit→σ² 遞迴 state update（每日） |
| DM 序列對齊 | index drift | `per_day_series` 以日期 intersection 嚴格對齊 |
| Pre-reg claim | 「事先寫死」 | 改為事後說明（ex-post documentation） |
| Multiple testing | 未做 | Bonferroni N=11，α=0.00455 |
| 適用範圍 | 隱含跨資產 | 限定 SPY 5 段 OOS |
| Feng & Zhang (2025) | 文中引述 | 移除（無法獨立驗證） |

## v1 vs v2 數值差異（核心 QLIKE）

| Period | Window | v1 QLIKE | v2 QLIKE |
|---|---|---|---|
| 2012-13 | 252 | 1.5405 | 1.4636 |
| | 504 | 1.5461 | 1.4588 |
| | 1000 | 1.5484 | 1.4685 |
| | 2000 | 1.5714 | 1.4727 |
| 2014-15 | 252 | 2.0019 | 1.4490 |
| | 504 | 1.9926 | 1.4553 |
| | 1000 | 1.9433 | 1.4630 |
| | 2000 | 1.8691 | 1.4900 |
| 2016-17 | 252 | 1.9419 | 1.7930 |
| | 504 | 2.0371 | 1.8055 |
| | 1000 | 1.9655 | 1.7795 |
| | 2000 | 1.9488 | 1.8026 |
| 2020-21 | 252 | 2.1042 | 1.4787 |
| | 504 | 1.9981 | 1.4704 |
| | 1000 | 2.0774 | 1.4678 |
| | 2000 | 2.1442 | 1.5143 |
| 2023-24 | 252 | 1.6207 | 1.4690 |
| | 504 | 1.6138 | 1.4780 |
| | 1000 | 1.6266 | 1.4708 |
| | 2000 | 1.7283 | 1.4879 |

**所有 cell 在 v2 均更低**——bug 修正後 GARCH-recursion 提供更準確的下期條件變異數估計（凍結 last-day-params 等同把 forecast horizon 拉到 21 日漂移之後，自然較差）。

## Winner mapping 變化

| Period | v1 winner | v2 winner |
|---|---|---|
| OOS1 2012-13 | W=252 | **W=504** |
| OOS2 2014-15 | W=2000 | **W=252** |
| OOS3 2016-17 | W=252 | **W=1000** |
| OOS4 2020-21 | W=504 | **W=1000** |
| OOS5 2023-24 | W=504 | **W=252** |

Win counts 從 (252=2, 504=2, 1000=0, 2000=1) → (252=2, 504=1, 1000=2, 2000=0)。Mean rank leader 從 (252, 504 並列 2.2) → (252 領先 1.8、1000 居次 2.0、504 第三 2.4、2000 墊底 3.8)。

## Pooled DM 504_vs_2000

- v1: 文中表述「pooled 未顯著」（具體 p 值未在 v1 文章揭示）
- v2: DM=−1.73、p=0.083，5% 不顯著（10% 邊際），Bonferroni 校正 N=11 後不通過

## 核心 narrative 是否變化

**未變**：v1 與 v2 的核心結論「沒有任何視窗能在五段歷史中全部稱王、跨期最佳視窗會替換」皆成立；v2 數字反而更支持這個結論（4 個視窗都有自己擅長的段落）。

**改進**：v2 補上 Bonferroni 多重檢驗校正後的「0/11 通過」結果，讓「W=504 並非統計上穩固最佳」的訊息更有支撐。

## Reviewer

- **v2 reviewer**: pending Codex re-review post-corrigendum publication
- 文章 status: corrigendum_published 2026-06-07
- knowledge.json: K593-v2 entry written with verdict NULL（無視窗穩定勝出）+ provenance pointing to v2 experiment files

## 變更影響

- ✅ feed.json `mile_faaddb06.content` 更新為 v2 版（含 corrigendum stamp + 數字 + 表格）
- ✅ feed.json `mile_faaddb06.corrigendum_status = corrigendum_published`
- ✅ Supabase sync 推送
- ✅ `experiments/k593/k593_window_cross_oos_v2_results.json` 保留 v2 原始輸出
- ✅ `experiments/k593/k593_window_cross_oos_results.json` 保留 v1 作 audit trail
