---
name: external-data-sources
description: >
  所有可用外部數據來源的完整操作手冊。涵蓋 yfinance、FRED、TAIFEX tick、CBOE、
  DGBAS 主計總處、Congressional trades 等。每個來源包含：取用方式、常用代碼、
  注意事項、已知陷阱。新增或移除數據來源時更新此 skill。
  Trigger phrases: '數據來源', 'data source', '怎麼抓資料', 'FRED', 'yfinance',
  'TAIFEX', '台指期資料', '外部資料'
---

# 外部數據來源操作手冊

## 總覽

| 來源 | 類型 | 費用 | API Key | 頻率 | 主要用途 |
|------|------|------|---------|------|---------|
| **yfinance** | Python 套件 | 免費 | 不需要 | 日/分鐘 | 股價、ETF、VIX、期貨 |
| **FRED** | pandas_datareader | 免費 | 不需要 | 日/月/季/年 | 總經指標（利率、通膨、就業等）|
| **TAIFEX tick** | 本地 Dropbox 檔案 | N/A | N/A | tick level | 台指期/選擇權日內高頻 |
| **CBOE** | yfinance / 直接下載 | 免費 | 不需要 | 日 | VIX、VVIX、VIX3M、SKEW |
| **DGBAS 主計總處** | Chrome 自動化 | 免費 | 不需要 | 月/季/年 | 台灣 GDP、CPI、就業 |
| **Congressional trades** | 本地 CSV | N/A | N/A | 不定期 | 美國國會議員交易 |

---

## 1. yfinance（股價與金融市場數據）

### 安裝
```python
# 已在 pyproject.toml，無需額外安裝
import yfinance as yf
```

### 基本用法
```python
import yfinance as yf
import pandas as pd

# 單一資產日頻 OHLCV
df = yf.download('SPY', start='2020-01-01', end='2026-04-01')
# 欄位: Open, High, Low, Close, Adj Close, Volume

# 多資產
df = yf.download(['SPY', 'GLD', 'QQQ'], start='2020-01-01')

# 5-min 數據（⚠️ 上限 60 天，免費版限制）
df_5m = yf.download('SPY', period='60d', interval='5m')

# VIX 系列
vix = yf.download('^VIX', start='2005-01-01')
vvix = yf.download('^VVIX', start='2012-01-01')
vix3m = yf.download('^VIX3M', start='2008-01-01')
skew = yf.download('^SKEW', start='2011-01-01')
```

### 常用 ticker 代碼

| Ticker | 名稱 | 說明 |
|--------|------|------|
| `SPY` | SPDR S&P 500 ETF | 美股基準 |
| `QQQ` | Invesco QQQ | 那斯達克 100 |
| `GLD` | SPDR Gold Trust | 黃金 ETF |
| `TLT` | iShares 20+ Year Treasury | 長期國債 |
| `0050.TW` | 元大台灣 50 ETF | 台股基準（⚠️ 見下方注意事項）|
| `2330.TW` | 台積電 | 台股龍頭 |
| `^VIX` | CBOE VIX | 波動率指數 |
| `^VVIX` | CBOE VVIX | VIX 的 VIX（2012 起可靠）|
| `^VIX3M` | CBOE 3-month VIX | 3 月期 VIX |
| `^SKEW` | CBOE SKEW | 尾部風險指標 |
| `BTC-USD` | Bitcoin | 加密貨幣 |
| `ES=F` | S&P 500 Futures | 美股期貨 |
| `NQ=F` | Nasdaq 100 Futures | 那斯達克期貨 |
| `CL=F` | Crude Oil Futures | 原油期貨 |
| `GC=F` | Gold Futures | 黃金期貨 |
| `DX-Y.NYB` | US Dollar Index | 美元指數 |

### ⚠️ 已知陷阱

1. **0050.TW 數據品質**：Yahoo Finance 把 2025-06-18 的 1:4 分割回溯應用到歷史數據，但只從 2014-01-02 起——2013 年以前未調整，造成 2014-01-02 假 -75% 回報。**所有使用 0050.TW 的實驗必須呼叫 `from volpred.utils import clean_tw50_data`**
2. **5-min 數據上限 60 天**：yfinance 免費版最多回溯 60 個交易日的分鐘級數據
3. **台股收盤時間**：台股 13:30 收盤（非 16:00），yfinance 的 Close 是 13:30 價格
4. **假日 forward-fill**：跨市場使用時，假日資產需 ffill 價格，return 設 0
5. **API rate limit**：大量下載時可能被暫時封鎖，加 `time.sleep(1)` 間隔

---

## 2. FRED（Federal Reserve Economic Data）

### 安裝
```python
# pandas_datareader 已在 pyproject.toml
import pandas_datareader.data as web
```

### 基本用法
```python
import pandas_datareader.data as web
from datetime import datetime

# 單一系列
dff = web.DataReader('DFF', 'fred', '2000-01-01', '2026-04-01')

# 多系列
series = ['DFF', 'DGS10', 'T10Y2Y', 'VIXCLS']
data = web.DataReader(series, 'fred', '2000-01-01', '2026-04-01')
```

### 常用系列代碼

#### 利率與貨幣政策
| Series ID | 名稱 | 頻率 | 說明 |
|-----------|------|------|------|
| `DFF` | Federal Funds Rate | 日 | 聯邦基金利率（有效） |
| `DFEDTARU` | Fed Funds Target Upper | 不定期 | 目標區間上限 |
| `DGS2` | 2-Year Treasury | 日 | 2 年期國債殖利率 |
| `DGS10` | 10-Year Treasury | 日 | 10 年期國債殖利率 |
| `DGS30` | 30-Year Treasury | 日 | 30 年期國債殖利率 |
| `T10Y2Y` | 10Y-2Y Spread | 日 | 殖利率曲線（倒掛=衰退信號）|
| `T10Y3M` | 10Y-3M Spread | 日 | 另一個衰退指標 |
| `M2SL` | M2 Money Supply | 月 | 貨幣供給量 |

#### 信用與風險
| Series ID | 名稱 | 頻率 | 說明 |
|-----------|------|------|------|
| `BAMLH0A0HYM2` | High Yield OAS | 日 | 高收益債信用利差 |
| `BAMLC0A0CM` | Investment Grade OAS | 日 | 投資等級債利差 |
| `TEDRATE` | TED Spread | 日 | 銀行間信用風險 |
| `STLFSI4` | Financial Stress Index | 週 | 聖路易金融壓力指數 |
| `DCOILWTICO` | WTI Crude Oil | 日 | 原油價格 |

#### 通膨
| Series ID | 名稱 | 頻率 | 說明 |
|-----------|------|------|------|
| `CPIAUCSL` | CPI (All Urban) | 月 | 消費者物價指數 |
| `CPILFESL` | Core CPI | 月 | 核心 CPI（除食物能源）|
| `PCEPI` | PCE Price Index | 月 | 個人消費支出物價 |
| `T5YIE` | 5Y Breakeven Inflation | 日 | 5 年通膨預期 |
| `T10YIE` | 10Y Breakeven Inflation | 日 | 10 年通膨預期 |

#### 就業與經濟活動
| Series ID | 名稱 | 頻率 | 說明 |
|-----------|------|------|------|
| `UNRATE` | Unemployment Rate | 月 | 失業率 |
| `PAYEMS` | Nonfarm Payrolls | 月 | 非農就業（NFP）|
| `ICSA` | Initial Claims | 週 | 初次申請失業救濟 |
| `GDP` | GDP | 季 | 國內生產毛額 |
| `GDPC1` | Real GDP | 季 | 實質 GDP |
| `UMCSENT` | Consumer Sentiment | 月 | 密西根消費者信心 |
| `INDPRO` | Industrial Production | 月 | 工業生產指數 |
| `HOUST` | Housing Starts | 月 | 新屋開工 |

#### 波動率（CBOE via FRED）
| Series ID | 名稱 | 頻率 | 說明 |
|-----------|------|------|------|
| `VIXCLS` | VIX Close | 日 | 與 ^VIX 相同但 FRED 格式 |

### ⚠️ 已知陷阱

1. **無需 API key**：`pandas_datareader` 直接讀 FRED 公開 API，不需註冊
2. **NaN 處理**：部分系列在假日/週末無數據，需 `ffill()` 或 `dropna()`
3. **修訂數據**：GDP、NFP 等會事後修訂，FRED 提供最新修訂版（可能與發布日不同）
4. **頻率混合**：合併日頻和月頻數據時，月頻數據通常對應月底或月初日期
5. **STLFSI4 已確認 NULL**（K503/K828）：與 VIX 的信息重疊，VIX 吸收了壓力指標

---

## 3. TAIFEX 台指期 Tick 日內資料

### 資料位置
```
~/Dropbox/TAIFEXDATA/
├── TAIFEXDATA/
│   ├── python/          ← ✅ 唯一已同步本地（10,440 檔，~33G）
│   │   ├── Daily_2012_01_02TX.csv
│   │   ├── Daily_2012_01_02TX1.csv   ← 近月（策略用這個）
│   │   └── Daily_2012_01_02TX2.csv   ← 次月
│   └── {year}/csv/      ← ❌ Dropbox placeholder（0 bytes）
├── OPTIONDATA/          ← ❌ 僅雲端（41G），使用前需確認下載
├── vix/                 ← ✅ 已同步（63M）
└── 證交所/              ← ❌ 僅雲端
```

### 基本用法
```python
import pandas as pd

# 讀取近月合約
path = f'/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python/Daily_{year}_{month:02d}_{day:02d}TX1.csv'
df = pd.read_csv(path, encoding='big5')

# 欄位（2014 起，10 欄）：
# 成交日期, 商品代號, 到期月份(週別), 成交時間, 成交價格, 成交數量(B+S),
# 近月價格, 遠月價格, 開盤集合競價, 時間戳記
```

### 商品代碼
| 代碼 | 說明 | 流動性 | 用途 |
|------|------|--------|------|
| TX | 台指期（全合約合併） | 高 | 總量分析 |
| TX1 | 近月合約 | 最高（佔 98.7%） | **策略交易用 TX1** |
| TX2 | 次月合約 | 極低（1%） | 換月研究 |

### ⚠️ 格式隨時間變動（必須處理）

| 期間 | 欄位數 | 成交時間格式 | 說明 |
|------|--------|------------|------|
| ~2011 | 未確認 | 7-8 位 | 特殊編碼，多 2 位 |
| 2012-2013 | 9 欄 | 5-6 位（`84500`） | 無「開盤集合競價」，無前導零 |
| 2014-2017/05/15 | 10 欄 | 5-6 位 | 多「開盤集合競價」欄 |
| 2017/05/16 起 | 10 欄 | 6 位（`150000`） | 含夜盤，統一格式 |

**必須用欄位數量或 header 名稱判斷格式，不可硬編碼 column index。**

### 交易時段
- 日盤：8:45-13:45
- 夜盤：15:00-05:00（隔日），**2017/05/16 起**
- 結算日：每月第三個週三
- 集合競價：「*」標記

### 5-min RV 計算（已驗證 pipeline）
```python
# K849 使用的方法：
# 1. 讀取 TX1 tick data
# 2. 重採樣為 5-min bars（OHLCV）
# 3. 計算 5-min log returns: r = log(close_t / close_{t-1})
# 4. RV = sum(r_i^2)，日內所有 5-min 返回
# 5. 如含夜盤：RV_total = RV_day + RV_night
```

### 已驗證結論
- K849: HAR-RV 勝 GJR（DM t=-11.14），QLIKE 0.18 vs 0.53
- K847: 隔夜 gap 61% 可交易（R²=0.83）
- K844: TX VT 空頭全勝，夜盤 return 73.7%
- K848: 74.9% 天有 jump，夜盤 vol 佔比 24%→57%（2017→2026）
- **台灣 vol 模型評估必須用 5-min RV 做 target，不能用 r²**

---

## 4. CBOE（波動率指數）

### 透過 yfinance
```python
import yfinance as yf

vix = yf.download('^VIX', start='1990-01-01')      # VIX（1990 起）
vvix = yf.download('^VVIX', start='2007-01-01')     # VVIX（2012 起可靠）
vix3m = yf.download('^VIX3M', start='2008-01-01')   # 3 個月 VIX
skew = yf.download('^SKEW', start='2011-01-01')      # SKEW index
vix9d = yf.download('^VIX9D', start='2011-01-01')    # 9 天 VIX
```

### 透過 FRED
```python
import pandas_datareader.data as web
vix = web.DataReader('VIXCLS', 'fred', '1990-01-01', '2026-04-01')
```

### ⚠️ 已知陷阱
- **VVIX 2012 前不可靠**：數據存在但品質差
- **VIX sufficiency**：已 33+ 次確認 VIX 吸收其他所有指標（VVIX/SKEW/VIX3M/VIX9D/STLFSI4 等），新指標幾乎不可能超越 VIX
- **VIX9D 是唯一有增量的**：GJR-X(VIX9D) 是 SPY 最佳日頻預測模型

---

## 5. DGBAS 台灣主計總處

詳見 `taiwan-macro-data` skill（`.claude/skills/taiwan-macro-data/SKILL.md`）。

### 快速用法
需透過 Chrome 自動化下載 CSV（無 REST API key）。

### 常用資料集
| funid | 名稱 | 頻率 |
|-------|------|------|
| A018101010 | GDP / 經濟成長率 | 季 |
| A030101015 | CPI 分類指數 | 月 |
| A040107010 | 失業率/勞動力 | 月 |
| A100101010 | 景氣指標/對策信號 | 月 |

### 已下載
- `data/dgbas/gdp_national_income_2006_2025.csv`
- `data/dgbas/labor_indicators_2021_2025.csv`

---

## 6. Congressional Trades（美國國會議員交易）

### 資料位置
```
data/congressional_trades_house.csv
```

### 說明
美國眾議院議員股票交易揭露（STOCK Act 要求）。可用於分析國會交易與市場波動率的關係。

---

## 7. 本地收集的 5-min 數據（yfinance cron）

### 資料位置
```
data/intraday/
├── SPY_5min_2026-01-20.csv      # SPY（~55 天）
├── 0050_TW_5min_2026-01-20.csv  # 0050.TW（~44 天）
├── SPY_daily_rv.csv             # 預計算的日頻 RV
└── 0050_TW_daily_rv.csv
```

### 收集方式
- `scripts/collect_5min_data.py`：由 `collect_us_data.py` 自動呼叫
- cron：美股收盤後自動收集（`30 5 * * 2-6`）
- 自動偵測 gap 並回補（上限 59 天）
- macOS 休眠時 cron 不執行，醒來後自動回補

### ETA
- SPY: ~55 天（2026-04-05），60 天門檻 ~04/07-08
- 0050.TW: ~44 天，60 天門檻 ~04/15-16

---

## 新增數據來源的 checklist

新增外部數據來源時，請在此 skill 中加入：
1. **來源名稱**與 URL
2. **取用方式**（Python 套件、API、手動下載）
3. **是否需要 API key**
4. **常用系列/代碼**表
5. **頻率與歷史深度**
6. **已知陷阱**（數據品質、格式變動、rate limit）
7. **已有實驗使用紀錄**（哪些 K 編號用過）
8. **本地存放位置**（如有）
