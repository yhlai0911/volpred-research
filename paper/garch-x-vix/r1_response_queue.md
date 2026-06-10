# R1 Response Queue — garch-x-vix（under review）

> 政策（v8_plan 2026-06-08 決策）：**投稿版 main.tex pre-R1 不動**。所有已知修正集中此檔，R1 reviewer response 時一次落地 + 重編譯 + resubmit。
> 來源：v7 Codex adversarial review（2026-06-05）+ 全組合學術審查（2026-06-10，`review_history/audit_2026-06-10/audit_findings.json`）。

## BLOCKING（R1 必修 — 數字/來源正確性）

### Q1. Table 3 Harvey 顯著性欄三處質性翻轉【audit HIGH #1】
- `main.tex:413` C1 報 t=3.49「Yes」— k988b JSON 存 2.849 (False)、canonical mcs_dm 存 1.995 (false)；**3.49 無任何來源**。
- `main.tex:409` A3f 報 2.92「No」— 兩來源 3.38/3.02 皆顯著。
- `main.tex:410` B2 報 2.99「No」— 兩來源 3.11/3.07 皆顯著。
- `main.tex:817`「10 of 16 models |t|>3.0」按 canonical 應 11/16 且成員不同。
- **修法**：以 pinned-snapshot `mcs_dm_results.json` 重生 Table 3 全表 + 重算 §Multiple Testing 計數；errata 對照表擴充涵蓋 C1/A3f/B2（現行 errata 只涵蓋 SPY headline）。

### Q2. Headline t=4.03 來源宣稱為偽【audit HIGH #2】
- `main.tex:723` 明文稱 4.03 出自 `mcs_dm_results.json` — 該檔存 4.148；K988 JSON 存 4.483；K1393 重跑 3.603。reproduce_report 已標 mismatch (2.93%>1%)。
- **修法**：R1 統一採 canonical 4.148 全文同步（abstract/intro/Table 3/Table 5/conclusion, lines 52/80/723/776/905），或為 4.03 建可追溯 frozen-vintage artifact 並 errata 註記；line 723 來源宣稱改寫為真實來源。

### Q3. §5.3 macro 比較範圍與統計量錯誤【audit HIGH #3】
- `main.tex:861` 稱六個 macro 變數 — K1001 實際只有 TermSpread + Unemployment (+Combined)；「t=4.77 VIX vs best macro」實為 GJR_N_vs_A4f_VIX。
- **修法**：改寫為實際範圍（two macro variables and their combination）；t=4.77 重標為 A4f vs GJR；補 A4f vs Macro_Combined 正確 DM 值（或補跑其餘四變數）。

### Q4. acerbi2019 chimeric reference【audit HIGH #4】
- `main.tex:976-980`：標題屬 Du & Escanciano (2017 MS)，論文用的 Z1/Z2 出自 Acerbi & Székely (2014, Risk 27(11):76-81)；現印的 MS 65(12) 2019 兩者皆非。
- **修法**：bibitem 改 Acerbi & Székely (2014, Risk)；in-text (321, 642) 改 (2014)；如需 tail-risk 修正版另列 Du & Escanciano (2017)。

### Q5. K1393 leave-COVID「~2.5× larger」比值錯【audit provenance #2 殘項】
- JSON mean_diff 比值 ≈7.6×，論文寫 ~2.5×。
- **修法**：R1 時重算並更正該句。

## v7 P1-P3 wording patches（non-blocking，R1 順帶）
- v7 review（`review_history/v7/codex_adversarial_review_2026-06-05.md`）的 1 high + 2 med-high + 1 med wording 修正 — 詳該檔；與本 queue 合併落地。

## 已完成（pre-R1 repo 層，不動 main.tex）
- [x] README headline qualified + FEZ/STOXX 對調修正 + GLD 來源改 K997（2026-06-10）
- [x] K1066 dual-target robustness shelf-ready（`r1_prep/robustness_oc_proxy.tex`，2026-05-17）
- [x] errata_pending.md（SPY headline drift，2026-04-19）— **R1 時需擴充 C1/A3f/B2**
