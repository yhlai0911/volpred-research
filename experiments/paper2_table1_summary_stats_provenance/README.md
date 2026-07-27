# paper2_table1_summary_stats_provenance

**類型**: governance / provenance reproduction（非新研究發現）
**起因**: `paper/PROVENANCE_SWEEP_20260710.md` Finding 2 — taiwan-vt 論文 Table 1（Summary Statistics for Key Assets）的 mean/std/skew/kurt 四欄無活 JSON 來源（23 untraceable 之一）。task `provenance-sweep-taiwan-vt-untraceable-batch2`。
**日期**: 2026-07-10
**修正 (2026-07-27, snapdupfix_paper2_table1_summary_stats_provenance)**: `load_col()`（SPY row 使用）先前無去重，而 `load_twii_full()` 有——稽核 audit_snapshot_dup_20260721 指出 SPY row n_obs 曾受污染（4668 vs clean 4658、kurt 14.1197 vs 14.0832）。已補 `index.duplicated` 去重（治本）。canonical CSV 現已上游去重（SPY 0 重複、延伸至 2026-07-24），故本次 clean 重跑 n_obs=4668 為當前正確值；`verdict=NOT_REPRODUCIBLE_FROM_PINNED_SNAPSHOT` 不變——paper Table 1 與 computed 的 drift 跨全部四資產，屬 yfinance vintage / skew-kurt variant 差異，非重複列污染，另案追蹤（不在本 snapdupfix 範圍）。無 paper `.tex` 引用本 provenance 產物。

## 目標

從論文自帶 pinned 資料快照離線重現 Table 1 描述統計（TWII / 0050.TW / SPY / TSMC 的 mean/std/skew/kurt），給這些數字一個可驗證來源。**禁湊值**；重現不了就如實標記等 sign-off。

## 方法

- Log returns: `r_t = ln(P_t/P_{t-1}) * 100`（body_v3.tex L41）。
- 資料: `paper/taiwan-vt/data/0050_..._2008-2026.csv`（pinned）+ `_twii_1997_2007_snapshot.csv`（TWII 1997-07-02 起）。**未 live-fetch → 無 yfinance vintage drift。**
- std = sample ddof=1；skew/kurt 慣例以「跑出來哪個 variant 對得上 paper」實證判定（不預設 Fisher/Pearson、biased/unbiased）。
- 資料品質守門: 剔除 `|log return| > 40%` 的物理不可能單日報酬（split-adjustment 斷點），並記錄。

## 結果（誠實揭露 — NOT_REPRODUCIBLE）

`verdict = NOT_REPRODUCIBLE_FROM_PINNED_SNAPSHOT`（matched 3 / 16 checks）

| 資產 | mean | std | skew | kurt |
|---|---|---|---|---|
| TWII | ✅ 0.023 vs 0.019 | drift 1.36 vs 1.45 | drift −0.28 vs −0.31 | drift 7.24 vs 5.82 |
| 0050.TW | drift 0.066 vs 0.034 | ✅ 1.35 vs 1.38 | **翻號 +0.08 vs −0.47** | **不符 17.8 vs 4.73** |
| SPY | ✅ 0.042 vs 0.042 | drift 1.25 vs 1.18 | **不符 −0.29 vs −0.52** | drift 14.1 vs 12.3 |
| TSMC | drift 0.092 vs 0.051 | drift 1.74 vs 1.92 | **翻號 +0.07 vs −0.18** | ~ 3.11 vs 3.41 |

### 三個核心 finding

1. **只有 mean 部分重現**；skew/kurt 系統性不符，0050 與 TSMC 的 skew 正負號翻轉（paper 負、重現正）。
2. **`0050_tw_adj_close` 欄損毀**: 2013-12-31=37.41 → 2014-01-02=9.33 的 split-adjustment 斷點（單日 −138.9% log return）。剔該 row 後 kurtosis 仍達 ~17.8（paper 4.73），此欄尚有殘留 adjustment artifacts，不可靠。
3. **TSMC mean 0.051 無法重現**（所有子期間 mean 0.079–0.119；paper 值更低）→ 暗示 paper TSMC 列用了此 CSV 未涵蓋的 pre-2008 較長期間資料。

**推論**: Table 1 原始估計用了與此 pinned CSV 不同的 vintage/期間（較長 TSMC 史 + 未損毀的 0050 序列），現有快照不足以重現高階矩。

## 研究誠實聲明

- 未修改論文任何數字或 JSON。
- 本輪確認這些數字仍屬 untraceable，並額外揭露 pinned CSV 的 0050 資料品質 bug。
- 後續需 owner sign-off:（a）取回原始估計 vintage 重現，或（b）用乾淨資料重估 + 發 errata 更新 Table 1（manuscript change，需 sign-off）。
- **禁於 sign-off 前 silently 改寫 Table 1 任何數字。**

## 檔案

- `reproduce_table1_summary.py` — 重現腳本
- `results.json` — 逐 check 分類 + findings + honest_conclusion + next_actions
