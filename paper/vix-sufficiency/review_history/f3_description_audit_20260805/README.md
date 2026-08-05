# vix-sufficiency — Family 3 描述 vs 實作查證

**日期**: 2026-08-05（台灣時間 19:0x–19:11）
**執行**: 論文部（publications）
**觸發**: 運營經理裁決 D38 —「問題不是缺資料，是論文把它描述成了另一種東西」，升為誠實線問題，
優先於一般 review round。
**性質**: 唯讀查證 ＋ 轄區內（非 `.tex`）修正。**未動任何 `.tex`。**

---

## 一句話結論

K732 從未使用任何 put-call 序列。論文的**方法段是誠實的**，但正文一句、以及 replication package
的兩份索引，把它描述成了一個以 CBOE put-call ratio 為輸入的 family——**而那份資料從未被下載過**。

---

## 機械證據（全部可重跑）

| # | 來源 | 內容 |
|---|---|---|
| E1 | `experiments/k732/k732_pcr_behavioral_sentiment.py:53-58` | `tickers` 只有 `SPY / GLD / ^VIX / ^SKEW / ^VIX3M`。無任何 put-call 代碼。 |
| E2 | 同檔 `:11`, `:13` | 檔頭自述「K191: PCR data unavailable, used VIX proxies」「K523: VIX percentile as PCR proxy」。 |
| E3 | 同檔 `:21` | 「Data Sources: yfinance (^SKEW, ^VIX, ^VIX3M, SPY, GLD)」。 |
| E4 | `k732_pcr_behavioral_sentiment_results.json` `.data_limitation` | 「CBOE Put/Call ratio (^CPCE) not available via yfinance; used SKEW + VIX term structure + VIX momentum as behavioral proxies」。 |
| E5 | 同 JSON `.data_period` / `.sample_size` | `2011-01-07 to 2026-03-20`、n=3,760。 |
| E6 | `main_v5.tex:210-212`（§3.2.3） | BSI ＝ SKEW、VIX/VIX3M、VIX 22 日動能、VIX level 四者的 252 日百分位等權平均。**與實作一致。** |

repo 內 `experiments/k732/` 與 package 內 `paper/vix-sufficiency/experiments/` 兩份 JSON 的
`data_limitation` 逐字相同——代換不是某一份副本的筆誤。

## 四個描述點，一個正確

| 位置 | 原本說什麼 | 正確？ |
|---|---|---|
| `main_v5.tex:210-212` §3.2.3 | BSI 由四個 VIX/SKEW 分量構成 | ✅ |
| `main_v5.tex:519` | 「Family~3 (behavioral put-call ratio)」，且其 Clark-West 因「CBOE put-call volume … not yet pinned」而 deferred | ❌ 標籤與延後理由**皆不成立** |
| `data_sources.md:30`（修正前） | 「Put-Call Ratio ｜ CBOE ｜ PCR ｜ 1995-01-01 – 2026-04-17 ｜ Behavioral sentiment Family 3」 | ❌ 序列從未取得；且樣本期間比實際多報 16 年（實際 2011-01-07 起） |
| `experiments.md:18`（修正前） | 「Family 3: behavioral sentiment (PCR, put-call ratio)」 | ❌ |

## 附帶發現：整套舊 family 編號留在 package 裡

不是零星錯字，是正文重編號後 package 沒跟上，三個 family 形成一個 3-cycle：

| 舊（package） | 新（`main_v5.tex` §3.2.x，canonical） |
|---|---|
| 8 = calendar anomalies | **11** = Calendar Anomaly |
| 10 = yield curve slope | **8** = Yield Curve Slope |
| 11 = overnight VIX changes | **10** = Overnight VIX Changes |

Family 1/2/3/4/6/7/9 未變。審稿人若照 `experiments.md` 去對正文的 Family 8，會落在
calendar anomalies 而不是 yield curve——這是 self-contained replication package 的實質缺陷。

`data_sources.md:3` 另外還停在舊標題「Eleven Signal Families」（正文 `:35` 已是 Thirteen；
`README.md:14` 宣稱「family count is now consistent at thirteen」——那次掃描漏掉了 data_sources.md）。

## 已修（本部門轄區，非 `.tex`）

- `data_sources.md:3` — Eleven → Thirteen
- `data_sources.md:30` — 虛構的 PCR 列 → 實際使用的 `^SKEW` 列（含正確樣本期間、指向 E1/E4 的溯源、
  明寫 **No put-call series is used**）
- `data_sources.md:31` — Yield curve Family 10 → Family 8
- `experiments.md:18` — K732 描述改為 BSI 實際構成 ＋ 未使用 put-call 的明示
- `experiments.md:20 / :28 / :30` — 11 / 8 / 10 三個標籤歸位
- `EXECUTION.md:73` — 把 F3 從「F3/F9/F10 資料供給 followup」拆出來。原本那張卡的前提是錯的：
  pin CBOE put-call **不會**補上 F3 的 CW cell，那會製造一個新的 family，不是完成這一個。
  F9/F10 的外部資料依賴是真的，保留。

回讀驗證：`experiments.md` 十個 family 標籤現與 `main_v5.tex` §3.2.x 逐一相符；
兩份檔案殘留的 put-call 字樣只剩「明示未使用」的揭露句。

## 未修，需主線程處理（`.tex` 為保留區，本部門無寫入權）

**`main_v5.tex:519`** —— 單一句子，兩處要改：
1. 「Family~3 (behavioral put-call ratio)」→ 應為 behavioral sentiment index（BSI）
2. 該句把 F3 與 F9/F10 併為「depend on external series (CBOE put-call volume, Google Trends
   queries, and the intraday VIX opening print) that are not yet pinned」——對 F9/F10 成立，
   對 F3 不成立。F3 的 CW 沒做，不是因為缺資料。

§3.2.3 本身正確，**不要改它**。缺陷只在 L519。

## 未修，需方法論裁決（超出描述層，屬論證強度）

BSI 四個分量有三個由 VIX 導出（VIX level、VIX/VIX3M、VIX 22 日動能），只有 SKEW 在 VIX 複合體之外
（SKEW 是 CBOE 獨立指數，量的是風險中性分布的三階動差，不是 VIX 的函數）。

在一篇主張 **VIX sufficiency** 的論文裡，這意味 F3 的 null（|t|=0.52）有四分之三的權重落在
「VIX 的重組贏不了 VIX」——那接近恆真，證據力低於「thirteen pre-specified signal families」
橫向比較所暗示的獨立性。**這不是造假**：§3.2.3 誠實列出了成分，任何讀者都看得到。但把它當成
一個獨立 family 計入十三分之一，審稿人會指出來。

三個處理選項，留給後續裁決：(a) 維持現狀並在 §3.2.3 加一句自我限定；(b) 把 F3 降級為 robustness
診斷、不計入主家族數；(c) 真的取得 put-call 資料重做 F3。(c) 最強但成本最高，且會改變 Table 2 的
一格與家族數。

## 本輪未處理（已知，另案）

- `scripts/README.md` 只索引 5 個腳本（共 13 個 family）——replication package 完整度缺口。
- `EXECUTION.md:35` 記載的 K732/K736「抄錯格」決議（`decisions/k732_k736_table2_rewrite.md`）
  仍未落地，v5 Table 2 的 F3 仍印 1.64（實為 `dm_stat_oos=1.637`）。這是既有欠帳，需動 `.tex`。
- `integration_plan_v2.md:234` 指向不存在的 `main_v2.tex`。屬歷史計劃文件，不修改（改寫歷史更糟）。
- `reproduce.py` 未重跑：本部門無 `uv run` 該腳本的權限；且本輪只動 `.md`，而該 gate 驗的是
  tex↔JSON 綁定，不受影響。
