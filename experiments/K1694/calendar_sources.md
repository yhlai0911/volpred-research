# K1694 交易日曆的來源表（product / exchange scoped）

**這份檔案回答一個問題**：K1694 的 22 個商品各自在哪個交易所、跟哪一份**官方**行事曆走，
以及那份行事曆的網址是什麼。每一列都要能被第三人點開驗證。

機器可讀的對應版本是 `calendar_fixtures.json`（測試直接讀它，**不讀 `K1694.py`**）。

## 為什麼要有這份檔案

Codex round 5 判 FAIL，理由是 round 4 引進的 `CME_UNSCHEDULED_CLOSURES` 是一張
**通用（universal）白名單**：對所有 22 個商品一律扣掉 2012-10-29、2012-10-30、2018-12-05。
那張表是從「快取裡少了幾天」反推出來的，不是從交易所公告來的 —— 而交易所公告直接反駁它。

反駁的原文（逐字）：

- **CFTC 12-363（2012-10-29，CME/CBOT/NYMEX/COMEX 自己送件）**：
  > "NYMEX and COMEX closed their physical **trading floors** for trade dates October 29, 2012
  > and October 30, 2012. **Electronic trading remains available for all NYMEX and COMEX
  > products on CME Globex.**"

  同一份送件把**所有**緊急措施逐條列完，關的只有 US equity futures/options 與利率複合體
  （Treasury / Eurodollar / Fed Funds）。CBOT 穀物、KCBT 小麥、CME 畜產**完全沒有出現**。

- **ICE 新聞稿（2012-10-29）**：
  > "**All other ICE markets and clearing houses will remain open and follow regular market
  > hours**, including ICE Clear Europe for CDS clearing."

  例外只有兩個：ICE 的 Russell 股指期貨（改時段）與 ICE Clear Credit（10/30 休市）。

- **CME 新聞稿（2018-12-02）**：
  > "…closure of its U.S.-based **equity and interest rate** futures and options products on
  > Wednesday, Dec. 5, 2018… **All other markets on CME Globex, CME ClearPort and the trading
  > floor will remain open for regular trading hours on Dec. 5.**"

K1694 一個股指、一個利率商品都沒有。**所以那三天對本實驗的每一個商品都是交易日**，
通用白名單把它們扣掉是錯的。

## 22 個商品的來源表

`schedule` 欄是 `K1694.py` 裡 `PRODUCT_SCHEDULE` 的值，也是 `calendar_fixtures.json`
的 `schedules` 鍵。

| DCOT contract_market_name | ticker | 交易所（product schedule 所屬） | schedule | 官方行事曆來源 |
|---|---|---|---|---|
| WTI-PHYSICAL | `CL=F` | NYMEX（CME Group 能源） | `CME_GLOBEX_COMMODITY` | [S5](#s5) [S6](#s6) [S7](#s7) [S8](#s8) |
| NAT GAS NYME | `NG=F` | NYMEX（CME Group 能源） | `CME_GLOBEX_COMMODITY` | 同上 |
| NY HARBOR ULSD | `HO=F` | NYMEX（CME Group 能源） | `CME_GLOBEX_COMMODITY` | 同上 |
| GASOLINE RBOB | `RB=F` | NYMEX（CME Group 能源） | `CME_GLOBEX_COMMODITY` | 同上 |
| GOLD | `GC=F` | COMEX（CME Group 金屬） | `CME_GLOBEX_COMMODITY` | 同上 |
| SILVER | `SI=F` | COMEX（CME Group 金屬） | `CME_GLOBEX_COMMODITY` | 同上 |
| PLATINUM | `PL=F` | NYMEX（CME Group 金屬） | `CME_GLOBEX_COMMODITY` | 同上 |
| PALLADIUM | `PA=F` | NYMEX（CME Group 金屬） | `CME_GLOBEX_COMMODITY` | 同上 |
| COPPER- #1 | `HG=F` | COMEX（CME Group 金屬） | `CME_GLOBEX_COMMODITY` | 同上 |
| CORN | `ZC=F` | CBOT（CME Group 穀物油籽） | `CME_GLOBEX_COMMODITY` | 同上 |
| SOYBEANS | `ZS=F` | CBOT（CME Group 穀物油籽） | `CME_GLOBEX_COMMODITY` | 同上 |
| SOYBEAN OIL | `ZL=F` | CBOT（CME Group 穀物油籽） | `CME_GLOBEX_COMMODITY` | 同上 |
| SOYBEAN MEAL | `ZM=F` | CBOT（CME Group 穀物油籽） | `CME_GLOBEX_COMMODITY` | 同上 |
| WHEAT-SRW | `ZW=F` | CBOT（CME Group 穀物油籽） | `CME_GLOBEX_COMMODITY` | 同上 |
| WHEAT-HRW | `KE=F` | KCBT（2012 起併入 CME Group，走 CBOT 穀物時段） | `CME_GLOBEX_COMMODITY` | 同上（[S6](#s6) 明列 "CBOT, KCBT and MGEX Grains"） |
| LIVE CATTLE | `LE=F` | CME（CME Group 畜產） | `CME_GLOBEX_COMMODITY` | 同上（[S6](#s6) 明列 "Livestock"） |
| LEAN HOGS | `HE=F` | CME（CME Group 畜產） | `CME_GLOBEX_COMMODITY` | 同上 |
| FEEDER CATTLE | `GF=F` | CME（CME Group 畜產） | `CME_GLOBEX_COMMODITY` | 同上 |
| SUGAR NO. 11 | `SB=F` | ICE Futures U.S.（softs） | `ICEUS_SOFTS` | [S9](#s9) [S10](#s10) [S11](#s11) |
| COFFEE C | `KC=F` | ICE Futures U.S.（softs） | `ICEUS_SOFTS` | 同上 |
| COCOA | `CC=F` | ICE Futures U.S.（softs） | `ICEUS_SOFTS` | 同上 |
| COTTON NO. 2 | `CT=F` | ICE Futures U.S.（softs） | `ICEUS_SOFTS` | 同上 |

18 個 CME Group 實體商品 + 4 個 ICE Futures U.S. softs。**沒有任何一個是股指或利率商品** ——
這正是三份公告所關的那兩類。

## 兩份行事曆的休市日集合

兩個 schedule 的**常規**休市日集合，經各自的官方行事曆核對後，**相同**：

| 假日 | `CME_GLOBEX_COMMODITY` | `ICEUS_SOFTS` |
|---|---|---|
| New Year's Day | 休 | 休 |
| Martin Luther King Day | 休 | 休 |
| Presidents' Day | 休 | 休 |
| Good Friday | 休 | 休 |
| Memorial Day | 休 | 休 |
| Juneteenth（2022 起） | 休 | 休 |
| Independence Day | 休 | 休 |
| Labor Day | 休 | 休 |
| Thanksgiving | 休 | 休 |
| Christmas | 休 | 休 |
| **Columbus Day** | **交易** | **交易** |
| **Veterans Day** | **交易** | **交易** |

「相同」是**核對出來的結果，不是假設**。程式仍然把兩者宣告成兩份獨立的行事曆
（`CALENDAR_SPECS`），日數、月端點、cross-sectional peer group 全部 per-schedule 計算；
將來哪一邊出現有出處的休市，只會作用在該交易所的商品上。本輪已用
`test_the_two_schedules_are_declared_separately_not_aliased` 釘住這件事。

ICE 的 Canola 與 currency / stock index / metal / nat gas / power 欄位是**不同**的行事曆
（見 [S9](#s9)–[S11](#s11) 的雙欄表），K1694 只用 softs 欄。

### 計畫外休市（unscheduled closures）

**兩個 schedule 都是空集合。** 三個爭議日期的官方狀態如下：

| 日期 | `CME_GLOBEX_COMMODITY` | `ICEUS_SOFTS` | 出處 |
|---|---|---|---|
| 2012-10-29 | 開 | 開 | [S1](#s1) / [S2](#s2) |
| 2012-10-30 | 開 | 開 | [S1](#s1) / [S2](#s2) |
| 2018-12-05 | 開 | **查無出處** | [S3](#s3) [S4](#s4) / — |

`K1694.py` 的 `UNSCHEDULED_CLOSURES` 因此是 `{}`，而且結構上**強制**每一筆新條目附
`source_id` + `quote`（`test_unscheduled_closures_must_carry_a_primary_source` 擋沒出處的條目）。

### 一個查不到的洞，照實寫

**ICE Futures U.S. 在 2018-12-05 是否交易 —— 沒找到官方出處。** ICE 自己的 2018 年行事曆
（notice 日期 2017-07-06）早於布希過世，講不到這件事；也沒有搜到當天的 ICE exchange notice。

處理方式：**不主張休市**。「查不到 → 就當它休市」正是這輪要修掉的毛病。
影響已量化並寫進 `K1694_results.json` 的 `insensitivity_check`：即使反過來假設 ICE 當天休市，
估計樣本一列都不會變（離開樣本的是 CORN，屬 CME schedule）。

### 一條證據等級較弱的規則，也照實標

**1 月 1 日落在週六時不回捲到 12/31。** 沒找到明說這件事的交易所公告；根據是**本 panel 自己的
日線數**（2010-12 與 2021-12 每一個合約都多出那一天）。這條規則的證據等級是
**empirical-from-panel**，不是 primary-source，`calendar_fixtures.json` 沒有替它背書，
本檔在此標明。它與本輪的兩個 blocking defect 無關，是 round 4 就已在的既有狀態。

---

## 出處清單

<a id="s1"></a>**S1 — CFTC Submission 12-363（2012-10-29）**
CME/CBOT/NYMEX/COMEX 就 Hurricane Sandy 緊急措施向 CFTC 的 40.6(a) 自我認證。
<https://www.cftc.gov/sites/default/files/stellent/groups/public/%40rulesandproducts/documents/ifdocs/rul102912cmecbotnymexandcomex1.pdf>

<a id="s2"></a>**S2 — IntercontinentalExchange Announces Hurricane Sandy Market Update（2012-10-29）**
<https://ir.theice.com/press/news-details/2012/IntercontinentalExchange-Announces-Hurricane-Sandy-Market-Update/default.aspx>

<a id="s3"></a>**S3 — CME Group U.S. Equity, Interest Rate Markets to Close for National Day of Mourning（2018-12-02）**
<https://www.cmegroup.com/media-room/press-releases/2018/12/02/cme_group_u_s_equityinterestratemarketstoclosefornationaldayofmo.html>
（cmegroup.com 對非瀏覽器 UA 回 403；鏡像：
<https://web.archive.org/web/2019id_/https://www.cmegroup.com/media-room/press-releases/2018/12/02/cme_group_u_s_equityinterestratemarketstoclosefornationaldayofmo.html>）

<a id="s4"></a>**S4 — CME Clearing Advisory Chadv18-474（2018-12-03）** National Day of Mourning – December 5, 2018
<https://www.cmegroup.com/notices/clearing/2018/12/Chadv18-474.html>
（鏡像：<https://web.archive.org/web/2019id_/https://www.cmegroup.com/notices/clearing/2018/12/Chadv18-474.html>）

<a id="s5"></a>**S5 — CME Group Holiday Calendar（landing page）** "CME Group observes 11 U.S.-recognized holidays."
<https://www.cmegroup.com/tools-information/holiday-calendar.html>

<a id="s6"></a>**S6 — CME Globex Columbus Day Holiday Schedule, 2010**（last updated 2010-06-09）
NYMEX / COMEX、CBOT+KCBT+MGEX Grains、Livestock 在 Columbus Day 均為 regular open / regular close。
<http://www.cmegroup.com/tools-information/holiday-calendar/files/2010-columbus-day.pdf>
（鏡像：<https://web.archive.org/web/20100821133122id_/http://www.cmegroup.com/tools-information/holiday-calendar/files/2010-columbus-day.pdf>）

<a id="s7"></a>**S7 — CME Globex 2010 Holiday Calendar（彙編）**
逐節列出 11 個假日的 per-product-group 時段：New Year's / MLK / President's / Good Friday
（"No CME Globex Trading on Good Friday"）/ Memorial / Fourth of July / Labor Day /
**Columbus Day** / **Veterans Day** / Thanksgiving / Christmas。
<http://www.cmegroup.com/tools-information/holiday-calendar/files/2010-globex-holiday-calendar.pdf>
（鏡像：<https://web.archive.org/web/20100215061802id_/http://www.cmegroup.com/tools-information/holiday-calendar/files/2010-globex-holiday-calendar.pdf>）

<a id="s8"></a>**S8 — CME Clearing Juneteenth 2022 advisory**（Juneteenth 6/19/2022 觀察日為 6/20/2022；2022 是首次）
<https://www.cmegroup.com/tools-information/holiday-calendar/files/2022-juneteenth-advisory.pdf>

<a id="s9"></a>**S9 — ICE Futures U.S. 2018 Holiday Calendar**（Exchange Notice，2017-07-06）
Sugar/Cocoa/Coffee/Cotton 欄：Columbus Day = Open。
<https://www.ice.com/publicdocs/futures_us/exchange_notices/ExNot2018HolidayCal.pdf>

<a id="s10"></a>**S10 — ICE Futures U.S. 2019 Holiday Calendar**（Exchange Notice，2018-06-22）
Sugar/Cocoa/Coffee/Cotton 欄：Columbus Day = open、Veterans Day = open。
<https://www.ice.com/publicdocs/futures_us/exchange_notices/ICE_Futures_US_2019_Holidays_20180622.pdf>

<a id="s11"></a>**S11 — ICE Futures U.S. 2026 Trading Holiday Calendar**（2025-06-09）
Cocoa / Coffee "C" / Cotton No 2 / FCOJ / Sugar No. 11 欄：Juneteenth = closed、
Columbus Day = open、Veterans Day = open。
<https://www.ice.com/publicdocs/futures/IFUS_Trading_Hours_Holiday_Calendar.pdf>
