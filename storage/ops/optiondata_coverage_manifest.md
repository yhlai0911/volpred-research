# TAIFEX OPTIONDATA Coverage Manifest

- **產出時間**：2026-07-19 14:06:21（台灣時間）
- **任務**：task pool `assign_6b29e647`（K-C 資料工程，不配 K 號、無假說）
- **來源**：`/Users/yhlai0911/Dropbox/TAIFEXDATA/OPTIONDATA`
- **性質**：唯讀清點，不下載、不動其他 storage 檔

---

## 一句話結論

`OPTIONDATA` 有 **3,787 個交易日的目錄 entry（2011-01-03 → 2026-07-17）**，但只有 **536 天實際下載到本機**（其餘 3,251 天是 Dropbox 雲端 placeholder）。**缺口 100% 可拉（cloud placeholder），沒有一天是「根本不存在」**。更關鍵的是：這 536 天的分佈**不具代表性**（2022 全年 + 2025 全年 + 2024 的 48 個散落日，2023 整年缺），所以在補齊前不該啟動任何 IV surface 實驗。走 **zip 表示法**補齊全史只要 ~5GB（走 csv 要 ~264GB）。

---

## 三個核心數字

| 口徑 | 數字 | 說明 |
|------|------|------|
| **local_real** | **1,024 檔 / 536 交易日** | 已 materialize 的真實 bytes（536 csv + 488 zip = 1,024；多數日子 csv/zip 兩份冗餘）|
| **placeholder** | **12,083 檔 / 3,251 交易日** | Dropbox online-only，size=0，**可拉** |
| **missing（連 entry 都沒有）** | **0**（本 entry 集內） | 真正不存在需對照官方交易日曆才能定論（見下）|

> file 口徑總計 13,107 個資料檔（+4 非資料檔 = 13,111 entries）。brief 引用的 **13,093/1,024** 是稍早近似值；現行實測 13,107 data files，1,024 real 精確吻合。

---

## Real 資料的年度覆蓋（為何不具代表性）

| 年份 | Real 交易日 | 狀態 |
|------|-----------|------|
| 2011–2021 | 0 | 全 placeholder |
| **2022** | **246** | ✅ 全年完整（僅農曆年假斷點，正常）|
| 2023 | 0 | 全 placeholder（**398 天洞**，切斷連續性）|
| 2024 | 48 / 242 | ⚠ 散落 48 天，多處數週斷點 → 時序不可用 |
| **2025** | **242** | ✅ 全年完整 |
| 2026 YTD | 0 / 127 | 全 placeholder（至 07-17）|

**可用 real 資料實為「2022 + 2025 兩個乾淨年 + 2024 雜訊」**。2022 是空頭年、2025 是回升年，中間 2023 整年缺 —— 在此子集上估的 IV surface 動態會被 regime 選擇偏誤污染。

---

## Strike / Maturity 覆蓋（橫斷面粒度充足）

抽 2 個 real 代表日 stream-aggregate（未整檔載入）：

| 代表日 | TXO 到期別數 | 履約價範圍 | 相異履約價 | C/P |
|--------|:---:|:---:|:---:|:---:|
| 2022-05-27 | 6（202206 / 202206W1 週選 / 202207 / 08 / 09 / 12 季選）| 12,400–21,000 | 75 | C 179,747 / P 203,648 |
| 2025-01-02 | 7 | 15,800–29,400 | 123 | 皆全 |

- 檔案格式：9 欄 big5（`成交日期,商品代號,履約價格,到期月份(週別),買賣權別,成交時間,成交價格,成交數量(B or S),開盤集合競價`），tick-level，單日約 38 萬列。
- TXO 佔單日成交約 **99.8%**；同檔另含 TFO/TEO/CDO 等其他選擇權商品。
- **判定**：每個 real 日都是完整選擇權鏈（多到期別含週/季選、75–123 履約價、C/P 皆全）→ **建 IV surface 的橫斷面粒度充足，blocker 純粹是時間覆蓋**。

---

## 缺口類型判定：100% cloud placeholder（可拉）

- **偵測法**：`st_size==0` ⟺ Dropbox online-only；double-confirm 用 xattr `com.dropbox.placeholder`。
- **相關性驗證**：41 個 zero-byte 抽樣**全帶** `com.dropbox.placeholder`（0 例外）；41 個 real 抽樣**全無**（0 例外）。
- placeholder 檔：`com.dropbox.placeholder` + `com.dropbox.attrs`；real 檔：只有 `com.dropbox.attrs`。
- **zip 表示法涵蓋全部 3,787 天**（含全部 3,251 placeholder-only 日）→ 每個缺口日都有可拉的 zip entry。
- **真正「不存在」caveat**：本清單所見 3,787 個 entry 皆可拉。連 entry 都沒有的日子只能對照官方 TAIFEX 交易日曆才能定論；per-year entry 數（233–250）與台股每年約 245 交易日一致，無明顯整段缺漏（2019=233 為單年最低，值得補查）。

---

## Fetch 建議（**本 session 不下載**，交主線程排程）

- **機制**：Dropbox online-only 檔讀取即觸發下載（`cat/dd file > /dev/null`），下載後 size 由 0 變真實 bytes。
- **最省路徑：走 zip**。real zip 平均 **1.5MB/日**（壓縮）vs real csv **81.3MB/日** → 全史 zip ~5GB vs csv ~264GB（差 54×）。

### 分階段

**Tier 1（先做）— 補 2023 + 2024 缺日 → 連續 2022-2025 四年**（IV surface 最小可信樣本，433 天，~0.65GB）
```bash
uv run python scripts/compute_queue.py enqueue \
  --title 'Materialize OPTIONDATA zip 2023+2024gap' \
  --script scripts/materialize_optiondata.py --interpreter 'uv run python' \
  --script-args --years 2023 2024 --representation zip \
  --result-artifact storage/ops/optiondata_materialize_2023_2024.json \
  --timeout 7200
```

**Tier 2（tier1 驗證可用後）— 補全史剩餘 placeholder**（2011-2021 + 2026 YTD，2,818 天，~4.2GB）
```bash
uv run python scripts/compute_queue.py enqueue \
  --title 'Materialize OPTIONDATA zip full-history' \
  --script scripts/materialize_optiondata.py --interpreter 'uv run python' \
  --script-args --all-placeholder --representation zip \
  --result-artifact storage/ops/optiondata_materialize_full.json \
  --timeout 28800
```

> **`scripts/materialize_optiondata.py` 尚未存在** — 需主線程建立。規格：讀 placeholder 檔清單 → 逐個 zip 強制讀取觸發下載 → 驗證 `st_size>0` → 記成功/失敗清單到 result-artifact。scope 限制下本 session 不建此 script、不下載。timeout：tier1 抓 2h、tier2 抓 8h（Dropbox 逐檔 on-demand 受網速/API 節流）。

---

## 驗證命令（`OD=/Users/yhlai0911/Dropbox/TAIFEXDATA/OPTIONDATA`）

```bash
# 總 entry
find "$OD" -type f | wc -l                                   # 13111
# real vs placeholder
find "$OD" -type f -print0 | xargs -0 stat -f '%z|%N' \
  | awk -F'|' '{if($1==0)z++;else r++}END{print "placeholder",z,"real",r}'   # 12084 1027
# real 資料檔 (排除 DS_Store)
... | awk -F'|' '$1>0 && $2~/OptionsDaily/' | wc -l          # 1024
# 相異 real 交易日
real 檔 basename 抽 OptionsDaily_YYYY_MM_DD | sort -u | wc -l  # 536
# 相異全 entry 交易日
全 entry basename 抽日期 | sort -u | wc -l                     # 3787
# placeholder 確認
xattr <zero-byte-file> | grep com.dropbox.placeholder
```
