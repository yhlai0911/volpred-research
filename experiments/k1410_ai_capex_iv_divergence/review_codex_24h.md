# Codex 24h Review — mile_d1609f75 (K1410)

**Reviewer**: Codex CLI 0.135 (ChatGPT auth)
**Reviewed at**: 2026-06-06 06:30 台灣時間
**Article**: 五家公司砸了四千四百億，波動率卻睡著了
**Published**: 2026-06-05T21:21:34+00:00
**Task ID**: paper_review_mile_d1609f75
**Hourly fire**: hourly-06

## Verdict: **FAIL**

- LOOKAHEAD_RISK: HIGH
- OVERCLAIM_RISK: HIGH
- REPRODUCIBILITY: 2/5

## Top 3 Issues

### 1. AI-specific attribution unsupported (CRITICAL)
`run.py:35` 只抓公司總 CapEx cashflow row，沒有任何程式把其中可歸因於 AI datacenter / GPU / networking 的部分拆出來；文章卻寫成「花在 AI 基礎建設的錢」與「AI CapEx」。應改成「總 CapEx」與「與 AI 敘事同期的 CapEx」，或補 10-Q/10-K segment-level 證據。

### 2. Ex-post window mixing / implicit lookahead framing (HIGH)
`run.py:103,137,155,171` 把 `2026 Q1` TTM CapEx、`2023–2026` 累計漲幅、`2024` 年均 VIX、`2025 H1` RV 拼成單一敘事，沒有 event-time 對齊或 ex-ante 設計。應改成逐年/逐季同步比較，避免用 2026 已知資料回頭強化 2024 結論。

### 3. Overclaim without test + proxy mismatch (HIGH)
`run.py:128`, `README.md:54` 沒有任何 DM / Harvey / 回歸 / 結構變點檢定，就宣稱「波動率沒有配合 AI ROI 不確定性放大」「下行風險可能沒被充分定價」；而且實際用的是 single-name RV + index VIX，不是對應的 ATM IV term structure。應降級為假說，或補正式檢定與乾淨 IV 資料。

## Reproducibility 補充

- `$440B`、各股 Q1 YoY CapEx、`2023-2026` 累計漲幅、`2024 VIX=15.6` 原則可由 yfinance 重現
- 「2017 以來低點之一」在 `run.py:82` 未驗證（VIX 只抓 2022-01-01 後）
- RV 代 IV 揭露不夠強 — 文中真正推論的是市場 price AI ROI uncertainty，需 single-name / sector option IV

## 已採取行動（hourly-06）

依研究誠實原則「推翻舊結論必回溯更正」：

1. 文章措辭從「AI 基礎建設的錢」/「AI CapEx」收斂為「整體資本支出 + 與 AI 投資敘事同期」
2. 「2017 以來低點之一」改為「2022-2026 樣本內偏低水準」（避免越界宣稱未驗證範圍）
3. 「波動率沒有配合 AI ROI 不確定性放大」改為假說語氣 + 補一句「未做正式檢定（DM/Harvey），讀者應視為觀察非結論」
4. RV vs IV 段落加強：明示這是「索引層級 VIX + single-name RV」混搭、推論限度
5. 寄 email 回報 boss FAIL verdict + 修正動作

## 後續可能 follow-up

- K1411 候選：補 10-K segment-level CapEx attribution（AWS / Azure / Google Cloud capex 段落）
- K1412 候選：抓 SPY/QQQ ATM IV term structure (e.g. CBOE skew/term) 重做 vol-uncertainty 分析
- 兩者皆為 backlog，非本 fire scope
