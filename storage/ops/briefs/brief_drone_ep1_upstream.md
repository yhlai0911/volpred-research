# Brief — drone_series_ep1_upstream（無人載具系列 EP1：上游深度）

**Model**: opus / medium (per task_type routing)
**Task id**: `drone_series_ep1_upstream`（已 claim + start，owner=hourly-10）
**Task type**: daily_article（reader-facing，audience=general）
**Aged 89.8h — 系列 EP0 今早 10:00 才上線，EP1 斷檔會毀掉系列節奏。本班要收。**

## ⚠️ 寫入邊界（並行安全，硬規則）

本班有另一個 writer 同時在跑。**你只准寫**：
- `storage/drafts/drone_ep1_general_draft.md`（含 YAML frontmatter）
- 圖表 assets（自己的實驗目錄 / assets 路徑）
- 你自己的 evidence／分析腳本與 results JSON

**禁止碰**：`storage/reports/feed.json`、`storage/memory/*.json`、Supabase / Mirror sync、其他 task 的檔案。
**不要自己 publish** —— 主線程（hourly-10）會在你完成後串行跑 `scripts/publish_draft.py` 發佈。

## 開工前必讀（3 canonical，不可跳過）

1. `.claude/skills/trending-repost/SKILL.md`
2. `.claude/skills/anti-ai-style/SKILL.md`
3. `.claude/rules/publishing.md`

## 研究地基（已驗證，直接用，不要重做）

`storage/pending_series/taiwan_drone_series_ep0_research.md`（29 檔已驗證公司名冊 + 三層鏈地圖 + PEST/SWOT）
`storage/pending_series/taiwan_drone_industry_series_brief.md`（系列總 brief）

**EP0 已發佈**：`mile_a8d79d6a` —「🛩️ 無人載具｜EP0：29 檔台廠名冊、2,100 億預算，和一個跑輸大盤的題材」。
先讀 EP0 的實際內文（`storage/reports/mile_a8d79d6a.json`，**不要整檔讀 feed.json**），確認：
- EP0 已經講過什麼（產業總覽 / 名冊 / 一年風險報酬實算 → 結論是題材跑輸大盤）
- **EP1 不可重複 EP0 的論述**。EP0 是「這題材整體表現如何」；EP1 是「上游環節到底在做什麼、誰有真壁壘、數據長怎樣」。
- 沿用 EP0 的標題格式與系列標記（`🛩️ 無人載具｜EP1：...`），維持系列辨識度。

## EP1 範圍（task description 原文）

聚焦**上游**環節與代表上市櫃公司：全訊 5222、立積 4968、新唐 4919、義隆 2458、亞光 3019、邑錡 7402、千附精密 6829、昇達科 3491、聯發科 2454 / 聯詠 3034（題材性）。

逐環節說明（晶片 / 飛控 / 感測 / 通訊 / 射頻）的**技術壁壘**與**台廠定位**，附**真財務／股價數據**。

## Evidence package 先於 prose（硬規則）

動筆前先組好：
- **真數據**：走 `external-data-sources` skill（yfinance / TWSE 真查真算），**標來源與日期**。禁手 key 數字、禁憑印象寫財務。
- ≥3 個可驗證數字、≥1 表（建議：上游各檔的營收規模／毛利率／近一年報酬／波動率／與大盤相關性）
- ≥1 真圖表（matplotlib；**不可** ASCII／文字框冒充）
- ≥1 層量化分析：例如上游 vs 中下游 vs 大盤的風險報酬對照、或「題材含量 vs 實際營收占比」的落差檢驗（這一層最有價值 —— EP0 已證明題材跑輸大盤，EP1 可以問「上游是不是唯一有真營收的一層」）

**個股分析的方法透明線（硬規則）**：真數據 + 明說假設 + 講不確定性 + 免責聲明 + 可複現。
**禁止**：保證報酬、目標價、內線式宣稱、「買進／賣出」建議。VolPred 不做選股與點位建議 —— 只做風險／波動率／數據事實。這條踩線會被撤稿。

研究誠實 > 一切：查不到的數字就說查不到，不要編。營收占比若無法從公開財報拆出「無人機貢獻」，**必須明講「題材含量無法從財報驗證」** —— 這本身就是對讀者最有價值的一句話。

## Dedup gate（寫之前跑，不可跳過）

```bash
uv run python scripts/check_arc_dedup.py --text-file /tmp/ep1_theme.md --audience general --title "<planned title>"
```
exit 1 → 回報 arc-covered，不要硬寫。

## 寫後 gate（全部要過）

1. `.claude/skills/anti-ai-style/references/editor-sop.md` 3 階段 9-checklist
2. `uv run python scripts/anti_ai_gate.py --file storage/drafts/drone_ep1_general_draft.md` → **exit 0**。MUST hit 任一 = 整篇改寫，禁 `--force`。
3. 禁翻譯腔／套路 hook／空泛評論／假哲理收尾。

## 懶人包

general audience → 文末附懶人包圖組（`lazypack-infographic` skill）。Codex primary；不可用則自寫 matplotlib renderer（數字直讀你的 results JSON）。

## 回報內容

draft 路徑、標題、字數、用到的數據來源與日期、圖表路徑、表格摘要、arc-dedup 與 anti_ai_gate 結果、以及「EP1 與 EP0 的差異化在哪一句」。

## Mission sanity check

服務 Mission #1（文章）+ #5（曝光）。系列文是漏斗入口，EP0→EP1 斷檔 = 讀者流失。
