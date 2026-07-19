# k528 — NFP 事件研究（SPY 波動率）

- Experiment ID: `k528`
- Created At: 2026-04-16T09:39:52.904348+00:00
- Corrected At: 2026-07-19（事件日期來源修正，全樣本重跑；同日第二次修正見下）
- Status: 已重跑，**方向性結論全部不變**，僅數值微調 + 一項口徑澄清

## 問題描述

NFP（非農就業）公布日，SPY 的波動是否會系統性放大？如果會，放大的來源是「NFP 這個
事件本身」，還是「進場當下的市場狀態」？

## 兩次修正，不要混為一談

本實驗在 2026-07-19 被修正了**兩次**，第二次是修第一次修壞的地方。

### 修正 1：事件日期從 proxy 換成官方日曆

原始版本用「每月第一個週五」推算 NFP 發布日。這個 proxy 錯得有結構、不是隨機噪音：

- BLS 在參考週較晚的月份會改到**第二個週五**發布
- 遇到聯邦假期會**提前**
- **2025-10 根本沒有發布**（政府關門取消），proxy 卻憑空生出一場
- proxy 把每一場都放在**週五**；官方日曆的 253 場只有 237 場在週五

錯的事件日期不會拋錯、不會出現 NaN，圖照樣畫得出來 —— 它只是把安靜的日子算成事件日、
同時把真的事件日丟進對照組。這是修正存在的理由。

`get_first_friday()` 已**整條移除**（不是標 deprecated），日期改由
`volpred.data.event_dates.nfp_release_dates` 取自 BLS 官方發布日曆（ALFRED，FRED
release id 50），且**取不到就 raise，不回退 proxy**。

### 修正 2（本輪）：accessor 的同月多筆選擇錯誤

第一次修正的 accessor 對「同月多筆 release 條目」取 `max()`。ALFRED 的 release id 50
在**六個月份**會回兩筆：前一筆是 Employment Situation 正式報告，後一筆是年度季節調整
因子／benchmark 修訂。`max()` 選到了後者 —— 也就是**把修訂當成了就業報告**：

| 月份 | 正確（正式發布） | `max()` 誤選（off-cycle 修訂） |
|---|---|---|
| 2006-05 | 2006-05-05 | 2006-05-08 |
| 2012-12 | 2012-12-07 | 2012-12-12 |
| 2013-05 | 2013-05-03 | 2013-05-06 |
| 2020-05 | 2020-05-08 | 2020-05-11 |
| 2024-01 | 2024-01-05 | 2024-01-10 |
| 2024-08 | 2024-08-02 | 2024-08-21 |

六個日期錯，聽起來只佔 253 場的 2%，但它剛好把 NFP-vs-週五 檢定推過 5% 分界線。
**第一次修正因此得出了一個錯誤的「顯著→不顯著」翻轉，並據此準備了 18 條文章更正 ——
那 18 條會把一個本來正確的結論撤回。** Codex 二審判 FAIL 擋下，未套用。

根修在 `src/volpred/data/event_dates.py`（改 per-month `min()` + 13–110 天 cadence
fail-closed 驗證，commit `305d118a3`）。

**為什麼原本 42 個測試全綠卻沒抓到**：fixture 是手寫的，同月第二筆事先就被刪掉了 ——
測試餵進去的輸入根本表達不出這個 bug。修法不是加更好的斷言，是餵真實輸入：
`tests/test_event_dates_real_raw_response.py` 直接釘住 ALFRED 的 264 筆原始回應
（fixture `tests/fixtures/fred_release_50_nfp_raw_20260719.json`，**禁止去重**，
那六對重複就是迴歸面），並附 mutation 檢查證明舊 `max()` 規則會在這份輸入上失敗。

## 方法

- 資料：SPY / ^VIX 日頻（yfinance），2005-01 至 2026-03
- 事件日：BLS 官方發布日曆（ALFRED release id 50），fail-closed
- 事件窗：T-5 ~ T-1（前）、T（當日）、T+1 ~ T+5（後）
- 檢定：Welch t（vs 全體非 NFP 日 / vs 非 NFP 週五）、Mann-Whitney U、
  VIX 中位數分組 regime 檢定、Pearson / Spearman 相關

### 週五基準的口徑（estimand）調整

proxy 下每一場 NFP 都是週五，「NFP vs 非 NFP 週五」自動就是同星期別對同星期別。
官方日曆下有 16 場不在週五，若沿用原寫法，就變成**星期別混合的事件組**對**純週五的
對照組**，週五本身的波動特性會直接混進 p 值。

本輪把事件組**限定為在週五公布的 237 場**，兩邊星期別一致。另一個選項是保留全部 253 場
改用 weekday-matched controls，未採用的理由：非週五事件是週四 8、週二 2、週三 1，
用這種格數做加權平均，標準誤會被 1 筆的週三格主導 —— 那是對一個更難陳述的量做更吵的估計。
被排除的 16 場以描述統計另行報告（平均 |ret| 0.715%），不是靜默丟掉。

原口徑（全部事件 vs 非 NFP 週五）以 `B_diagnostic_mixed_weekday` 保留在結果檔中，
標明 **DIAGNOSTIC ONLY、不可引用**，只用於和修正前做 apples-to-apples 對照。

## 結果：逐項前後對照

每一項都同時看 **mean / median / 勝率 / 樣本數 / 顯著性** —— 平均值可能幾乎不動，
而中位數與勝率在底下已經移位。

| 指標 | 修正前（proxy） | 修正後（官方，本輪） | 判定 |
|---|---|---|---|
| 樣本數 | 254 | 253（212 個日期共通） | 數值微調 |
| NFP vs 全體非 NFP（平均） | 1.104× (p=0.128, NS) | 1.108× (p=0.112, NS) | 數值微調 |
| ↳ 中位數比 / 勝率 | 1.190× / 0.555 | 1.193× / 0.561 | 數值微調 |
| NFP vs 非 NFP 週五（平均） | 1.168× (p=0.0335, **顯著**) | 1.190× (p=0.0202, **仍顯著**) | 數值微調（口徑見上） |
| ↳ 中位數比 / 勝率 | 1.209× / 0.563 | 1.223× / 0.570 | 數值微調 |
| VIX 高低體制差（平均） | 2.167× (p=2.8e-10) | 2.027× (p=4.6e-9) | 數值微調（仍極顯著） |
| ↳ 中位數比 / 勝率 | 2.265× / 0.717 | 2.073× / 0.695 | 數值微調 |
| 事前 VIX 相關（Pearson） | 0.451 | 0.440 | 數值微調 |
| ↳ Spearman | 0.377 | 0.346 | 數值微調 |
| VIX 中位數切點 | 16.71 | 16.69 | 數值微調 |

**6 項受稽核宣稱中，0 項結論翻轉。**

參考：若沿用修正前的舊口徑（全部 253 場 vs 非 NFP 週五），數值為 1.178×、p=0.0249 ——
同樣顯著。也就是說**「顯著→不顯著」的翻轉在任何一種口徑下都不成立**，那是六個錯誤
日期造成的假象。

**方向性主結論不變**：決定 NFP 日波動的是**進場當下的 VIX 體制**（2.03 倍、p≈4.6e-9），
遠大於 NFP 這個日曆事件本身。

### 關於「不顯著」的措辭

修正前的結果檔寫過 NFP 效果 "insignificant across all tests"，但同一份檔案裡單尾
Mann-Whitney 的 p=0.0088 明確顯著 —— 那句總結**與它自己的數字矛盾**。本輪起每個顯著性
陳述都綁定它自己的檢定：

- Welch 平均差（vs 全體非 NFP 日）：1.108×，p=0.112，**未拒絕**
- Welch 平均差（週五對週五）：1.190×，p=0.0202，**拒絕**
- Mann-Whitney 單尾（隨機優勢，不是平均）：p=0.0019，**拒絕**

平均差檢定沒拒絕，**不等於**分佈相同，更不是效果為零的證據。|return| 厚尾，
排序檢定抓得到平均檢定抓不到的位移。兩個都報，不合併成單一裁決。

## 產出檔案

| 檔案 | 內容 |
|---|---|
| `k528_nfp_event_study.py` | 主腳本（官方日曆版，含前後對照 audit 段） |
| `k528_nfp_event_study_results.json` | 修正後結果（現行 canonical） |
| `k528_nfp_event_study_results_PROXY_SUPERSEDED.json` | **修正前**結果存證，勿刪 —— 它是線上文章當初宣稱數字的唯一紀錄；檔內已帶 `superseded: true` / `do_not_cite: true` / 撤回原因，離開檔名也可機器判別 |
| `k528_nfp_official_dates_results.json` | 逐項前後對照 + 換掉的日期 + 文章更正替換清單 |
| `build_article_correction.py` | 文章更正計畫（預設 dry-run **完全不寫**，`--apply` / `--record-plan` 才寫入） |
| `k528_rerun_v3_summary.json` | 本輪修正的機器可讀摘要 |
| `review_verdict_v3.json` / `codex_review_v3.md` | Codex 三審裁決與全文 |

## 線上文章更正（`mile_35eef830`）

### ⚠️ 原 18 條更正清單已全數作廢

原清單是對著**被污染的 JSON** 建的，且包含一個**錯誤的方向翻轉**（把「達到顯著水準」
改寫成「p=0.057，差一點過線但沒過」）。文章原本寫的是對的；套用那 18 條等於發佈一則
撤回正確結論的更正。作廢原因已寫入 `k528_nfp_official_dates_results.json` 的
`article_correction.supersedes`。

### 新清單：19 條，全部是數值重述，0 條方向翻轉

文章原始的三個方向性判讀 —— 對全體交易日基準未達顯著、對週五基準達到顯著、真正拉開
差距的是進場 VIX 體制 —— 在官方日期下**全部成立**。新清單只改數字
（1.10→1.11、1.17→1.19、2.17→2.03、0.45→0.44、254→253、16.71→16.69 等），
外加一段讀者可見的更正說明，內含週五基準的口徑調整揭露。

19 條已對線上 canonical 文章驗證，全部恰好命中一次。

```bash
# 主線程在 repo root 執行
uv run python experiments/k528/build_article_correction.py            # 驗證（不寫任何檔）
uv run python experiments/k528/build_article_correction.py --apply    # 寫入 + sync
```

**為什麼不在 worktree 內直接寫**：`storage/reports/feed.json` 是共享 canonical 狀態，
`.claude/rules/worktree.md` 明文禁止 worktree agent 觸碰。這不是形式規定 —— 本 worktree
自帶一份 15MB 的 feed.json 複本，在這裡寫等於寫進一份「其他文章一發佈就過期」的分支複本，
合併回去會把期間發佈的文章靜默蓋掉。因此拆成：worktree 負責解析與驗證，主線程負責寫入。

**未解決的缺口**：文中兩張圖表（`nfp_20260703_regime.png`、`nfp_20260703_baseline.png`）
與文末兩張懶人包圖仍是修正前的數據，圖片內容無法用文字替換修正。更正後正文與圖片會不一致，
因此更正說明中已明寫「圖表仍是初版數據，正在重新產製」。重新產圖 + 上傳 Supabase 屬後續工作。

## 防迴歸

事件日期正確性的 owner 是 `tests/test_nfp_official_release_dates.py`（未另開新檔）：

- `TestK528UsesOfficialCalendar` — 釘住 k528 用官方日曆、樣本 253 筆、237 筆在週五、
  212 個日期共通、結果檔宣告 fail-closed
- `test_no_off_cycle_revision_date_is_treated_as_an_event` — **直接釘住本輪 BLOCKER**：
  對 artifact 斷言六個 off-cycle 日期不在事件集合、六個正式發布日在。對 artifact 而非
  只對 accessor 斷言，因為「accessor 是對的」不能證明「出貨的結果用了它」
- `TestProxyMutationIsCaught` — mutation test：proxy 日曆餵給 guard 必須被拒；
  只塞回幻影的 2025-10-03 也必須被抓；同時驗證 guard 不會誤殺官方日曆

accessor 層的 owner 是 `tests/test_event_dates_release_selection.py` 與
`tests/test_event_dates_real_raw_response.py`（真實 raw response + mutation 檢查）。

Mutation 已實測：把 `min()` 改回 `max()` 後 `test_regular_release_wins_in_every_duplicate_month`
由綠轉紅（`2006-05-08 != 2006-05-05`），還原後 51 passed。沒被實際觸發過的 gate 不算 gate。

## 主腳本的 fail-closed 面

- **日曆完整性**（`check_calendar_is_complete`）：同月多筆 → raise；樣本窗內缺月 → raise。
  已知的真實缺口只有 2025-10（政府關門，ALFRED 在 2025-09-05 與 2025-11-20 之間 76 天無
  條目），寫在 `KNOWN_MISSING_MONTHS` 並附理由 —— 這個清單是用來記錄真實缺口的，
  不是用來讓檢查通過的
- **事件日→交易日對映**：一對一完整性斷言。樣本內發布日找不到三日內交易日 → raise；
  兩個發布日映射到同一個 session → raise（原本的 `set()` 去重會把這件事藏起來並靜默減少
  事件數）。窗口邊界排除改為明確記錄在 `sample.event_mapping_audit`，不再靜默 `continue`
- **原子寫入**：主結果與 audit 皆走 temp file + `fsync` + `os.replace`

## 參考

- K1442 事件日期稽核（發現 proxy bug）；`event_article_nfp_2026_07_03_t1` 修正報告 §7
- `docs/error_log.md` 2026-07-12 CPI 事件研究發布日條目（同一 bug class 的前例）
- Savor & Wilson (2013, JFE)；Lucca & Moench (2015, JFE)
- K513：先前的 FOMC/NFP/CPI 事件研究
