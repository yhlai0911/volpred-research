# Macroeconomic and Official Data

## FRED / ALFRED

FRED適合利率、信用、通膨、就業及活動指標。Series id每次從FRED official page核對，
不要只信舊實驗或模型記憶。

常見研究族群：

- Policy/rates：effective policy rate、Treasury yields、curve spreads
- Credit/risk：corporate spreads、stress indices
- Inflation：CPI/PCE、breakeven inflation
- Activity/labor：GDP、industrial production、payroll、claims、unemployment

### Vintage gate

- Final-vintage history不能自動支撐real-time OOS。
- 使用ALFRED或release archive取得forecast origin當時可見值。
- 核對first public release date，排除發布前backcast。
- 只取得current vintage時，明確標為final-vintage pseudo-OOS。
- 保存series id、vintage/realtime window、retrieval timestamp與missing rule。

## Taiwan official statistics

主計總處、國發會、央行、交易所等資料優先使用官方下載/API。每次核對：

- dataset id或下載頁
- 單位、基期、季調、修訂與發布日
- CSV/Excel schema與locale encoding
- 是否有官方archive/vintage

Browser automation只是取得方式，不是source identity。下載後將原始artifact與metadata
交給正式collector/storage owner，不在skill保存瀏覽器點擊順序。

## Event / disclosure data

例如政治人物交易、政策公告或公司揭露：

- 使用official disclosure或可追溯primary archive。
- 區分transaction date、filing date、public availability date。
- Forecast feature只能在public availability之後使用。
- Entity matching、amendment與duplicate filing規則必須記錄。
- 保存license與redistribution限制。

## Completion evidence

Official URL、release/vintage time、schema、units、period、row count、revision policy與
input hash都必須進README/reproduce spec。
