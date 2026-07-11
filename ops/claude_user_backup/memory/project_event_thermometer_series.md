---
name: project_event_thermometer_series
description: 文章系列「事件溫度計｜」🌡️（boss 2026-07-06 於 Telegram 定名）— 即期事件前後分析；與迷思實驗室並列
metadata: 
  node_type: memory
  type: project
  originSessionId: 257d8984-a4d3-475c-aa28-1eebcd51e6f1
---

**文章系列「事件溫度計」🌡️**（boss 2026-07-06 於 Telegram 定名；2026-07-10 從 telegram_memory.md 併入統一大腦）。

- **定位**：即期事件（FOMC / CPI / 非農 NFP / 重大財報 / 重大宣告）前後的溫度分析 —— 事件驅動、時效性文章。
- **標題格式**：前綴 `事件溫度計｜<標題>`（全形 `｜`）。
- **權威 marker**：`details.event_series_slot`；going-forward 的 `event_article` 一律掛此系列。
- **系列 SoT（single source of truth）**：`config/article_series.json`（與迷思實驗室並列於此 config）。
- **與迷思實驗室的分工**：事件溫度計 = 即期事件驅動（有時效）；迷思實驗室 = 投資人傳言用真數據驗證（非時效）。兩者並列，見 [[project_myth_lab_series]]。

**How to apply**：派事件驅動寫作 agent 時，brief 明寫標題前綴 `事件溫度計｜` + 設 `details.event_series_slot`。系列定義以 `config/article_series.json` 為準，不從標題文字反推。
