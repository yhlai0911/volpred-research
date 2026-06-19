# PUBLISH STATUS — 台股 6 萬點 member_qa 文章

**狀態**：成品完成、已驗證、四審 PASS、圖已上傳 Supabase。**未發佈**，卡在 publish gate，等老闆裁示。

## 成品
- 文章：`experiments/k_taiex_60k_scenario_20260619/article_FINAL_draft.md`（3997 字，含免責+假設專節，γ over-precision 已修）
- 分析 artifact（全驗證真實、可複現）：`path_sim/`（GARCH-t MC，觸及 6 萬機率 3.36%零drift/4.89%歷史drift）、`valuation/`（FinMind 真實 PER/PBR 分位 30 檔）、`rotation/`（大漲段風險實證+產業輪動）
- 圖：5 張已 upload 到 Supabase article-images bucket
- 審查：honesty/methodology/anti-ai-style/reader-value 四維全 PASS；sim Codex 7 項方法論全 PASS

## 卡點（兩道 gate，皆老闆本 session 建/在意的機制）
1. **anti-recycle gate**（防 K1054 鬼打牆）：因內文引用 K1404 誤判 recycle。需 `dup_waiver`（主實驗全新、arc 不同 → 正當，但要繞老闆剛建的 gate）。
2. **content-vs-source honesty gate**：只認 `K\d+` 格式、讀不到新實驗 `k_taiex_60k_scenario_20260619`。14 個數字被旗標（10 個來自新實驗、3 個來自舊 K K176/177/178、1 個 derived ratio 4.6）。數字全已人工驗證為真，gate 只是看不到來源。

## 待裁示的選項
- **A（推薦）**：教 honesty gate 讀宣告的 experiment_refs 的 results.json（強化非弱化）+ 建 consolidated results.json + 修 derived 4.6 改引用 component + 用具名 dup_waiver → 正式發佈。~10 min。
- **B**：老闆先看 article_FINAL_draft.md 再決定。
- **C**：audit_strict=False bypass（不推薦——對點名個股的文章不該關誠實 gate）。

## 接續
老闆說 go → 走選項 A：改 `src/volpred/publisher/publisher.py` L786-789 experiment_refs filter 接受非 K-id ref + 建 consolidated results.json + 修文章 derived 4.6 + 重跑 publish（dup_waiver）→ question-answer --article-id link → commit → email。
