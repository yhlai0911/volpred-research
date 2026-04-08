---
name: taiwan-macro-data
description: >
  從主計總處（DGBAS）總體統計資料庫下載台灣宏觀經濟數據。
  支援 GDP、CPI、失業率、產業結構、進出口等官方統計。
  Trigger phrases: '台灣經濟數據', 'DGBAS', '主計總處', 'Taiwan macro data'
user-invocable: true
---

# 台灣主計總處數據下載

## 資料來源
- **主計總處總體統計資料庫**: https://nstatdb.dgbas.gov.tw/dgbasall/webMain.aspx?k=dgmain
- 資料格式：CSV(UTF8)、JSON、Excel、XML
- 時間範圍：民國 40 年（1951）至今
- 頻率：年、季、月

## API 結構

### 1. 取得資料庫目錄（JSON）
```
GET https://nstatdb.dgbas.gov.tw/dgbasall/webMain.aspx?sys=100&funid=a1110m
```
回傳 JSON array，每個 item 含 `funid`（資料集 ID）和 `funname`（名稱）。

### 2. 查詢頁面
```
https://nstatdb.dgbas.gov.tw/dgbasall/webMain.aspx?sys=210&x=2098&funid={FUNID}
```
需在頁面上設定：
- 統計期（民國年）：`yyf`（起）、`yyt`（迄）
- 週期：`cycle`（4=年, 2=季, 1=月）
- 輸出模式：`outmode`（0=網頁, 1=Excel, 2=CSV, 3=CSV-UTF8, 8=JSON）
- 統計項：勾選 checkbox

### 3. 透過 Chrome 自動化下載
因為查詢需要 JavaScript 互動，用 Chrome 瀏覽器自動化操作：
1. 導航到查詢頁面
2. 設定 yyf=95, yyt=114, cycle=4, outmode=3 (CSV-UTF8)
3. 勾選所有 checkbox
4. 點擊「查詢」按鈕
5. CSV 自動下載到 ~/Downloads/

## 常用資料集 funid 對照表

| funid | 名稱 | 內容 | 頻率 |
|-------|------|------|------|
| **A018101010** | 國民所得統計常用資料 | GDP、經濟成長率、人均 GDP、GNI | 年/季 |
| **A018102050** | GDP 依支出分（70年後）| 民間消費、政府支出、投資、淨出口 | 年 |
| **A018103010** | 國內各業生產及平減指數-年 | 農/工/服務業 GDP、製造業細項 | 年 |
| **A030101015** | 消費者物價基本分類指數 | CPI 各類別 | 月 |
| **A030103015** | 消費者物價特殊分類指數 | 核心 CPI、食物、能源 | 月 |
| **A040107010** | 人力資源主要指標 | 人口、勞動力、就業、失業率 | 年/月 |
| **A040103050** | 各行業就業人口（第十次修訂）| 按行業分的就業人數 | 年/月 |
| **A040201010** | 受僱員工人數 | 各業受僱人數 | 月 |
| **A040202010** | 每人每月總薪資 | 各業平均薪資 | 月 |
| **A040206010** | 勞動生產力指數 | 生產力與單位勞動成本 | 月 |
| **A050101010** | 工業生產指數 | 製造業生產量 | 月 |
| **A060101020** | 外銷訂單按地區 | 對美/中/歐/東協訂單 | 月 |
| **A060102010** | 外銷訂單按貨品 | 電子/資訊/機械訂單 | 月 |
| **A080101010** | 進出口貿易總值 | 出口/進口/貿易餘額 | 月 |
| **A100101010** | 景氣指標統計 | 景氣對策信號、領先/同時/落後指標 | 月 |
| **A110101010** | 村里鄰戶數暨人口數 | 人口總數 | 月 |
| **A110103010** | 出生死亡統計 | 出生率/死亡率 | 年/月 |
| **A110104010** | 按五歲年齡組人口 | 年齡結構（老齡化分析） | 年 |

## 已下載資料（data/dgbas/）

| 檔案 | 內容 | 期間 |
|------|------|------|
| gdp_national_income_2006_2025.csv | GDP、經濟成長率、人均 GDP | 民國 95-114 年 |
| labor_indicators_2021_2025.csv | 人口、勞動力、失業率 | 民國 110-114 年 |

## 民國↔西元轉換
- 民國年 + 1911 = 西元年
- 例：民國 95 年 = 2006 年，民國 114 年 = 2025 年

## 使用範例

```python
import pandas as pd

# 讀取 GDP 數據
gdp = pd.read_csv('data/dgbas/gdp_national_income_2006_2025.csv', 
                   skiprows=2, encoding='utf-8')
# 民國年轉西元
gdp['year'] = gdp['統計期'].str.extract(r'(\d+)').astype(int) + 1911
```

## 注意事項
- 統計期用民國年（非西元年）
- 部分資料集只有近 5 年（視資料庫設定）
- 大量 checkbox 的資料集（>50 項）可能下載失敗，需分批
- CPI 類資料用月頻查詢更完整
- 需要 Chrome 瀏覽器自動化或手動操作（無 REST API key）
