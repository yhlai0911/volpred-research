---
name: external-data-sources
description: >
  Select and validate an external dataset for a VolPred experiment. Use when a
  research question needs a market, macroeconomic, official, TAIFEX, intraday,
  or event-data source and its availability or data contract must be verified.
---

# External Data Source Selection

這個 skill 決定 source contract；不擁有 collection schedule，也不保存外部資料的機器路徑。

## Preflight

先讀
`.claude/skills/autonomous-research/references/operations-core-contract.md`，並執行：

```bash
uv run python scripts/task_pool_control.py status
```

只有需要建立 collector/follow-up task 時才依 mode mutation；source investigation 本身可
維持 read-only。

## Source index

| Need | Read |
|---|---|
| Equity、ETF、futures quote、volatility index、intraday API | `references/market-data.md` |
| FRED、官方總經、revision/vintage、event disclosure | `references/macro-and-official-data.md` |
| TAIFEX tick、session、contract roll、RV | `references/taifex-data.md` |
| 新增 provider/collector | `references/source-onboarding.md` |

## Selection workflow

### 1. 定義 estimand

先寫清楚：

- 需要 price、return、conditional variance、realized measure、flow 或 event？
- 頻率與 target horizon？
- 原始觀測、proxy 或 model-derived value？
- Decision time 何時必須可用？

沒有 estimand 就不要先抓資料。

### 2. 核對 primary source

每次使用都核對 provider/官方文件：

- series/ticker/field semantics
- timezone、release time、revision policy
- history depth與 intraday retention
- authentication、rate limit、license
- delisting、split、continuous-contract 或 schema change

時間敏感限制不能沿用本 skill 的舊數字。

### 3. 做 bounded sample

先抓小樣本，觀察：

- schema與 dtype
- missing/duplicate/extreme rows
- timezone和交易日
- adjusted/unadjusted price
- source timestamp與 retrieval timestamp

Source 不符合 estimand 時先換 source 或改稱 proxy，不用清洗掩蓋語義錯誤。

### 4. Resolve path and provenance

- Project input 從正式 collector/manifest/config 解析。
- 外部 archive root 由 collector option、manifest 或明確環境設定取得。
- 不在實驗或 skill 內寫使用者 home、雲端同步目錄、worktree或服務 ID。
- `reproduce_spec.json` 保存 resolved input identity、hash、period、retrieval/vintage與
  license/source URL。

### 5. Handoff

- 一次性 experiment input：交給 `autonomous-research`，runtime 用
  `finalize_experiment` pin input。
- Recurring collection/freshness：交給 `data-collection-ops`，先改 canonical schedule，
  再驗 Operations Core receipt與下游 read-back。
- 新 follow-up task：重新讀 task-pool mode後，由 main thread走 canonical producer。

## Completion

- [ ] Estimand與source field語義一致
- [ ] Provider docs/official URL已核對
- [ ] Availability、timezone、vintage與revision已記錄
- [ ] Bounded sample diagnostics通過
- [ ] Path由正式 resolver取得，沒有機器-specific hardcode
- [ ] Input identity進入 runtime reproduce spec
- [ ] 限制與proxy bias如實寫入README
