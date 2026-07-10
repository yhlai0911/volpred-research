# K1675 — 台股颱風臨時停市事件研究（T+0：2026-07-10 颱風巴威停市）

## 研究問題

颱風臨時停市（非預定休市）之後的首個交易日，台股是否出現系統性的
(a) 開盤跳空放大、(b) 當日絕對報酬放大、(c) 停市後 5 日 realized vol 放大？
直覺說「停市累積未消化資訊，復市會補跳」，數據驗證這個直覺是否成立。

觸發事件：2026-07-10 颱風巴威，臺北市全日停止上班，台股休市
（`config/market_closures_adhoc.json`，由 `scripts/detect_market_closure.py` 自動偵測寫入）。

## 停市日推導（雙來源 + 交叉驗證）

原設計假設 exchange_calendars 對颱風停市盲目（sessions 對比行情，缺資料 = 停市）。
probe 發現 4.13.2 已把歷史颱風停市 backfill 進 `adhoc_holidays`（source 內有結構化
`typhoons` 清單），故改雙來源 union：

- **來源 A**：exchange_calendars XTAI source `typhoons` 清單 ∩ 2012-2025（15 天），
  逐日驗證 ^TWII 與 0050.TW 皆無真實行情。
- **來源 B**：殘差掃描 — ^TWII（市場指數）缺行情的 session 即候選（Codex review
  2026-07-10 補強：原「兩序列皆缺」改為「指數缺即候選」，寬進嚴出，堵單源 phantom
  漏抓盲點），再以三重 reject 交叉驗證（0050 真實行情 / TWSE 融資融券
  `storage/sentiment/tw_margin_0050.csv`（獨立於 yfinance 的第二來源）/ 假期鄰接）：
  - 2012-01-02：0050 有真實行情 → 市場有開，^TWII 缺漏 → 剔除
  - 2019-09-09 / 2021-04-06：融資券有資料 → 市場有開，yfinance 缺漏 → 剔除
  - 2022-02-04 / 2023-01-18：緊鄰春節連假（calendar 邊界誤標）→ 剔除
  - **2024-10-31（康芮）**：無融資券資料、非假期邊界 → 真停市，納入（library 漏列）
  - 正向總驗證：最終 16 個停市日全數無 TWSE 融資券資料（`final_margin_cross_check`）
  - 已知盲點（記入 `derivation_audit.known_blind_spots`）：真停市日緊鄰預定連假時
    來源 B 會誤剔（杜鵑型，靠來源 A 覆蓋）；新型 phantom 填充 pattern 可能漏抓

**資料清理**：yfinance 在部分休市日塞 phantom 填充列（^TWII 2014-07-23 / 2016-07-08
整列複製前日；0050.TW 多個颱風日 OHLC 全平 + 量 0）。`load_prices()` 以「整列 byte-同前日
OR（收盤同前日 + 量 0 + 高低相等）」規則剔除，剔除清單印在 run log 且可重跑驗證。

**結果**：2012-2025 共 **16 個停市日、13 個事件**（連續停市日合併：梅姬 2 日、
凱米 2 日、山陀兒 2 日）。全數為颱風停市，名稱逐一對照 DGPA/TWSE 公開紀錄。

## 統計設計

- 事件統計（n=13）：復市首日 \|開盤跳空\|（vs 停市前收盤）、\|close-to-close 報酬\|、
  RV ratio = RV(復市起 5 交易日) / RV(停市前 5 交易日)，RV = sqrt(mean(r²))。
- 主對照（n=1042）：同月份（7-10 月）2012-2025 普通交易日，排除停市 ±5 交易日。
- 次對照（n=205）：主對照中的週一（跨 2+ 日曆日 gap，與停市跨日結構較可比）。
- Bootstrap 95% CI（seed=42，10,000 次）。描述性事件研究，無交易訊號，無 lookahead 面。

## 主要結果（詳 `k1675_results.json`）

| 指標 | 停市後首日 (n=13) | 同月普通日 (n=1042) | 週一對照 (n=205) |
|---|---|---|---|
| mean \|報酬\| | 0.871% | 0.706% | 0.778% |
| median \|報酬\| | 0.601% | 0.515% | 0.581% |
| mean \|跳空\| | 0.706% | 0.324% | 0.355% |
| mean RV ratio | 0.948（median 0.838）| — | — |

- \|報酬\| 差（停市 − 主對照）= +0.165pp，boot95 [−0.235, +0.662] → **不顯著**
- \|報酬\| 差（停市 − 週一）= +0.094pp，boot95 [−0.318, +0.604] → **不顯著**
- \|跳空\| 差（停市 − 主對照）= +0.382pp，boot95 [+0.028, +0.840] → 名目上顯著，
  但對週一對照 +0.350pp，boot95 [−0.004, +0.815] → **邊界、不顯著**。跳空放大
  主要反映「跨的日曆時間比較多」（類週末效應），非停市特有。
- RV ratio mean 0.948，boot95 [0.727, 1.280]；13 事件中 **11 個 < 1** →
  **停市後波動未系統性放大（null result）**。
- 事件路徑（tau=0 = 停市前**最後**交易日、tau=1 = 復市首日，見
  `rv_path.tau_definition`）：全視窗高點在 tau=−1（停市前倒數第二個交易日）
  mean \|報酬\| = 1.1710%；tau=0 為 0.8693%、復市首日 0.8711%，幾乎持平。
  復市後第 3、4 日降到 0.3875% / 0.3787%。市場在停市前就把颱風訊息定價了大半。

## 結論

**「颱風假是波動炸彈」的直覺不成立**：復市首日絕對報酬與普通日差異不顯著、
停市後 5 日 RV 中位數比停市前低 16%。跳空略大但與跨週末同量級。
Null result 如實報告；n=13 樣本小，所有結論皆為描述性、不宣稱因果。

## Caveats

樣本僅 13 事件；跳空橫跨 2+ 日曆日與單日對照結構不同（已用週一對照緩解）；
yfinance ^TWII 開盤價部分時期疑似回填（zero-gap fraction 0.3%，見 data_quality）；
颱風災損對基本面的實質衝擊無法與「停市機制」本身分離。
2024-07-26（凱米後復市，\|報酬\| 3.29%）與全球科技股回檔同日，不可全歸因颱風。

## 檔案

- `k1675_typhoon_closure_event.py` — 推導 + 統計 + 圖（seed=42）
- `k1675_results.json` — 全部數字（含 derivation_audit 可驗證）
- `k1675_reopen_ret_dist.png` — 復市首日 vs 對照 \|報酬\| 分佈（箱型圖）
- `k1675_rv_path.png` — 事件前後 ±5 交易日平均 \|報酬\| 路徑
- `k1675_data_quality_article_charts.py` — 從 K1675/K758v2/K739bv2 results JSON
  重現一般讀者文章的資料鑑識圖
- `k1675_residual_candidate_audit.png` — 6 個殘差候選的交叉驗證分類
- `k1675_bad_row_consequences.png` — 0050 幻影拆股斷點清理前後三項結果比較

資料來源：yfinance ^TWII / 0050.TW、exchange_calendars XTAI 4.13.2、TWSE 融資融券。

## Review status

Codex code review（gpt-5.4, 2026-07-10）：**CONDITIONAL PASS** → 兩項 findings 已同日修正：
(1) MEDIUM — 來源 B「兩序列皆缺才候選」的 false-negative 盲點 → 改「指數缺即候選 +
三重 reject」寬進嚴出，加 final margin 正向總驗證，殘餘盲點記入 `known_blind_spots`；
(2) LOW — README tau 定義誤植（原把 tau=−1 寫成停市前最後交易日）→ 已更正
（tau=0 = 停市前最後交易日）。修正後重跑，主結果不變（16 停市日 / 13 事件 /
mean \|reopen ret\| 0.871% / mean \|gap\| 0.706% / mean RV ratio 0.948，Codex 已獨立重算驗證）。
