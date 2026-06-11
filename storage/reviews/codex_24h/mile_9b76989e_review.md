# Codex 24h Review — mile_9b76989e (K1474)

- **Article**: 酒店娛樂業是股市的晴雨表嗎？文獻回顧與十年實證
- **Task**: `paper_review_mile_9b76989e`
- **Reviewed**: 2026-06-11 台灣時間
- **Reviewer**: Codex CLI 0.137.0 (gpt-5.4)
- **Verdict**: **CONDITIONAL_PASS**（文章正文層級；附 experiment-artifact 待修項）

## Summary

文章正文誠實：所列 corr / beta / 年化波動率 / COVID 跌幅與復甦幅度，與 `k1474_results.json` 四捨五入後一致；先行指標口徑有節制（「嚴格統計意義上當先行指標需更細緻論證，做為同步確認可以」），未把相關當因果。文中「危機相關性收斂」段落只引用 PEJ（0.80→0.81）與 XLY（0.92→0.96），這兩者在 results 中確實上升，文章正文未宣稱「全部標的都上升」。

Codex 原始整體 verdict 為 **FAIL**，但其三項實質扣分主要針對 `README.md` / `results.json` 的 `key_findings`，**不是已發佈的文章正文**。經主線程逐項對照文章 content 後，文章層級判 **CONDITIONAL_PASS**，並把 artifact 待修項列為後續任務（回報主線程裁決，本次 review 不改文章 content）。

## Codex 逐項

| 維度 | Codex verdict | 說明 |
|---|---|---|
| (1) Lookahead bias | CONDITIONAL_PASS | 滾動 corr/beta 皆 backward-looking（`rolling().corr()` / `cov()/var()`），無未來資訊洩漏。純同期描述統計，不可包裝成開盤前先行訊號 — 文章未如此宣稱。 |
| (2) 數字一致 / overclaim | FAIL（against README/results） | 文章正文數字一致。但 `results.json` `key_findings` 字串「All hotel/leisure tickers show elevated corr during COVID crash」為偽 — HLT/MAR/H/RCL 的 corr 實際下降，只有 PEJ/XLY/CCL 上升。 |
| (3) 相關 vs 因果/先行 | PASS | 文章口徑克制，未把相關當因果。 |
| (4) 樣本/期間/資料源 | FAIL（against README） | yfinance auto_adjust=True 一致；但 README 期間 `2015-01-02~2026-06-09` vs script/results `2015-01-01~2026-06-10` 不一致；`n_obs_total=2875`（price rows）vs `spy_stats.n_obs=2874`（return obs）口徑混用。 |

## 待修項（experiment-artifact 層級，回報主線程）

1. **README + results `key_findings` 偽推廣**：「全部標的 COVID 期 corr 上升」與 results 矛盾（HLT/MAR/H/RCL 實際下降）。應改為「PEJ/XLY/CCL 上升，其餘個股未普遍上升」。文章正文未犯此錯，但 artifact 應更正以維持研究誠實。
2. **COVID recovery window 重疊**：`crash_end='2020-03-23'` 與 `rec_start='2020-03-23'` 同日，close-to-close 報酬使 2020-03-23 同時計入 crash 與 recovery。magnitude 影響極小，但 window 定義應改不重疊。
3. **期間 / n_obs 口徑統一**：README 與 results 的起訖日、price-rows vs return-obs 應一致標註。
4. **script docstring**：仍寫 `Leading/lagging indicator analysis via RevPAR proxy`，但實際產出無 lead-lag 檢驗 — 建議刪以免誤導。

## 結論

文章正文（reader-facing content）通過研究誠實 gate，數字真實、口徑克制 → **CONDITIONAL_PASS**。實驗 artifact（README/results `key_findings` + recovery window）有需更正的不一致，已列為後續 follow-up，不影響已發佈文章正文的正確性。
