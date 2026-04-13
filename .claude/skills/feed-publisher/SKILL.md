---
name: feed-publisher
description: >
  This skill should be used when publishing research findings as reader-facing articles
  to the website feed. It ensures each article has complete Traditional Chinese Markdown
  content (title, tables, interpretation, conclusion) rather than internal reasoning notes.
  Trigger phrases: '發佈', '發文', 'publish', '/publish', 'post to feed', '發佈到網站'.
  Trigger situations: after completing an experiment with noteworthy results, reaching a
  research milestone, or when the user explicitly requests a feed publication.
  This skill should NOT be used for: internal memory recording (use m.think/m.add_knowledge),
  running experiments (use autonomous-research), or paper writing (use finance-paper-quality).
---

# Feed 研究文章發佈規範

## Scope Boundary

Use this skill for **文章內容本身**：

- audience / article type 選擇
- 標題、結構、圖表與資料來源標注
- 主題查重與事件文章內容時效

Do **not** use this skill for：

- 文章池釋出節奏、排程發布、補寄通知 → `admin-ops`
- 實驗設計與研究判斷 → `autonomous-research`
- 論文寫作或 paper metadata 更新 → `finance-paper-quality` / `admin-ops`

## 核心原則

**Feed = 給讀者看的完整文章，不是內部研究筆記。**

每篇文章必須通過「讀者測試」：一個不認識你的人看完後，能學到什麼？

## thinking ≠ content

| | thinking（內部） | content（發佈） |
|---|---|---|
| 目的 | 記錄推理過程 | 展示研究成果 |
| 讀者 | 自己 | 外部訪客 |
| 格式 | 自由筆記 | 結構化 Markdown |
| 語氣 | 「我發現...」「可能是...」 | 「研究結果顯示...」 |
| 長度 | 不限 | 500-3000 字 |

## 選題來源（寫之前先查）

**主題不是憑記憶挑——用 `publication-candidates` skill 系統化選。**

1. **研究驅動**：`cat storage/publication_candidates.json | jq '.top_10_uncovered, .missing_general_top5, .missing_research_top5'`
2. **事件驅動**：WebSearch 近期 CPI/NFP/FOMC/TSMC/earnings season；`grep '財報公告日.txt'`；讀 `next_tasks.json` 事件任務

詳見 `publication-candidates` skill。

## 發文前必做：主題重複檢查（不可跳過）

**在決定主題之後、撰寫內容之前，必須先確認主題是否已有類似文章。**

### 檢查步驟（⚠️ 2026-04-14 強化：用**概念關鍵字**不是字面字串）
1. **grep 概念關鍵字**（多組查，涵蓋同義詞）：
   ```bash
   # 例：寫「0050 夜盤」主題必須至少查：夜盤 | overnight | 跳空 | 隔夜 | gap | pre.*market
   grep -iE "夜盤|overnight|跳空|隔夜|gap" storage/reports/feed.json | grep title | head -20
   ```
   **禁止**只用狹義字串（例「0050.*夜盤」）——會漏掉同主題不同代號的文章（如 TX 期貨夜盤、K847 台股隔夜）
2. **LanceDB 語義搜尋**（必跑，比 grep 更精確）：
   ```bash
   uv run python scripts/build_knowledge_index.py search --query "主題一句話描述"
   ```
   若 top-3 結果 dist < 0.5（高相似）→ 有重複，不可寫
3. **同 audience 檢查**：只比較相同受眾類型（general vs general，research vs research）
4. **主題家族檢查**：若主題屬已知高頻家族（overnight/gap/50-50 SPY-GLD/VT 保險/VIX 充分性），**先列已有同家族文章 title 清單，逐一確認差異化角度**，再決定是否寫

### 判斷標準
- **完全重複**（>70% 標題相似）→ **禁止發佈**，除非要更正或更新
- **部分重疊**（30-70% 相似）→ **必須找出新觀點**：
  - 過去文章的結論是什麼？
  - 這次有什麼不同的數據、角度、或結論？
  - 新文章標題和內容必須明確與既有文章區隔
  - 在文章中主動引用/連結舊文章：「我們在 [之前的分析] 中發現 X，但這次新數據顯示 Y」
- **無重疊**（<30%）→ 正常發佈

## 寫作前必讀實驗檔案（⚠️ 不可跳過）

**寫每篇文章前，每個引用的 K 實驗都必須**：

1. `cat experiments/k<id>/README.md` —— 計劃、問題、方法、預期、結論（若有獨立資料夾）
2. `cat experiments/k<id>*.py` 或 `experiments/k<id>/k<id>.py` —— 實作細節、真實樣本、參數設定
3. `python3 -c "import json; print(json.dumps(json.load(open('experiments/k<id>*_results.json')), ensure_ascii=False, indent=2)[:3000])"` —— 真實統計量、DM t / p / bootstrap CI / VaR 等
4. `ls experiments/k<id>*.png` 或 `experiments/k<id>/*.png` —— **優先直接 embed 既有圖表**，不要重畫

**為什麼**：
- knowledge.json 摘要只有 200-300 字，可能漏關鍵細節（樣本數、OOS 期間、模型版本）
- 文章數字必須 byte-for-byte 對應 results JSON，不可從記憶引用
- 既有 PNG 是原始實驗設計的視覺化，重畫簡化反而丟失資訊
- 若沒有既有 PNG 才用 `volpred.charts` 生成新圖

**2026-04-14 教訓**：agent 只讀 knowledge.json 摘要就寫文章，漏掉實驗真實方法細節；重畫新 chart 失去原始 bootstrap/placebo 分布資訊。

### 高頻重複主題警告
以下主題已有多篇文章，新文章必須有**顯著不同的切入角度**：
- 50/50 SPY/GLD 配置（10+ 篇）
- VT 保險/保費（5+ 篇）
- VIX 充分性（多篇）
- **隔夜波動 / overnight gap / 跳空 / 夜盤（20+ 篇，含 K847 / K906 / K812v2 / K847 / K886 / I4 / I5 / N68 等）**
- 美股對台股的 spillover / lead-lag（10+ 篇）
- PRG / Periodic GARCH 勝出 GJR（多篇，含 K874 系列）

## 延伸閱讀（自動附加）

Publisher 會自動在文章末尾附加「延伸閱讀」區塊，列出同 audience 中相似度 >20% 的已發布文章（最多 3 篇）。這些連結也存在 `related_articles` metadata 中供前端使用。

**不需要手動操作** — 只要 `_find_similar_articles` 找到相關文章，就會自動附加。

## 三種發文類型

### 1. 即時發現（milestone）— 500-1500 字
每個實驗完成後立即發佈。一個發現、一個結論、一個實務意義。

### 2. 深度長文（article）— 2000-5000 字
整合 5-10 個相關發現，提供完整的理論框架和實務指南。例如：
- 「VaR 七方法大評比」（整合 Phase O 全部 VaR 實驗）
- 「日頻 QLIKE 天花板」（整合 4 個自建模型的 null results）
- 「12/VIX 完整操作手冊」（策略+風控+歷史驗證）
適合在一個研究主題收斂後撰寫。不只是把 milestones 拼在一起——要有新的綜合觀點。

### 3. 研究報告（research report）— 5000-10000 字
跨 Phase 的總結性文件，包含完整數據表格、方法論比較、限制和未來方向。例如：
- 「Phase O+P 完整報告：從 Skewed-t 到 QLIKE 天花板」
- 「2026 Q1 Hormuz 危機即時追蹤報告」
適合每個月或每個重大 Phase 結束後撰寫一次。

## Related Skills

- 研究產出來源 → `autonomous-research`
- 文章池、節奏與通知 → `admin-ops`

## 文章結構模板（milestone 用）

```markdown
## 摘要
一句話說明發現了什麼、為什麼重要。

## 研究背景
為什麼要做這個分析？之前的結論是什麼？

## 方法與數據
| 項目 | 設定 |
|------|------|
| 資產 | SPY, QQQ... |
| 期間 | 2014-2026 |
| 方法 | GJR-GARCH... |

## 核心發現

### 發現一：[標題]
數據 + 解讀。不只報數字，要解釋為什麼重要。

### 發現二：[標題]
...

## 實務意義
投資人可以怎麼用這個結果？

## 結論
重申核心發現，指出限制和未來方向。

## 圖表（必須，不可省略）
![核心發現的視覺化圖表](supabase_storage_url)
用 matplotlib 生成 PNG，上傳 Supabase Storage article-images bucket。
禁止用 ASCII art 或純文字表格替代真正的圖表。

## 數據來源
*本文基於實驗 KXXX（腳本：experiments/kXXX.py，結果：experiments/kXXX_results.json）。
數據來源：yfinance 實證數據，期間：YYYY-YYYY，樣本：N 個觀測值。*
```

## 發佈流程

### 方法 A：Agent 寫完整文章（推薦）

```
Agent(description="Publish article", prompt="
Write a complete research article in 繁體中文 Markdown about [topic].
Include: summary, method table, key findings with interpretation, practical implications.

MANDATORY — 每篇文章必須包含：
1. 真正的圖表（使用 volpred.charts 模組）：
   from volpred.charts import generate_bar_chart, upload_chart, embed_chart
   path = generate_bar_chart(labels=[...], values=[...], title='...', ylabel='...')
   url = upload_chart(path)
   content = embed_chart(content, url, '圖表描述')
   可用函式：generate_bar_chart, generate_grouped_bar_chart, generate_line_chart, generate_heatmap
   禁止用 ASCII art 或純文字表格替代真正的圖表。
2. 數據來源標注（文末）：
   *本文基於實驗 KXXX（腳本：experiments/kXXX.py，結果：experiments/kXXX_results.json）。
   數據來源：yfinance，期間：YYYY-YYYY。*

Then save as DRAFT (not published) via Publisher:

from src.volpred.publisher.publisher import Publisher
pub = Publisher()
pub.publish_milestone(title='...', description='[content]', phase='research',
                      tags=[...], status='draft')  # ← 永遠 draft！

Working directory: /Users/yhlai0911/Desktop/volpred-research
")
```

## 平台層發佈決策

### 核心規則：所有文章一律 `status=draft`，由文章池節奏釋出

- **永遠用 `status=draft`**：不論 research 或 general，所有文章先進文章池
- **禁止直接 `status=published`**：除非用戶明確說「立即發布這篇」
- **Agent prompt 必須指定 `status="draft"`**：不可省略
- 文章池每 **15 分鐘**自動釋出 1 篇（session cron 驅動）
- CLI 指令：`uv run python -m volpred.cli ops release-pool --include-drafts --limit 1 --storage-dir storage`

### 文章類型寫作模板（寫作前必須選定類型）

**一般讀者和研究文章的受眾完全不同，寫作方式必須有本質差異。**

#### 一般讀者 (audience=general) — **融會貫通型**
**受眾**：非專業投資人、對金融有興趣但無統計背景的人
**目的**：讓讀者「看完就知道該怎麼做」

**⚠️ 寫作模式 = 多實驗融合**：
- **不可**只用單一 K 實驗寫 general 文——內容太薄
- **必須**從讀者關心的主題切入（風險管理、成本、心態、策略選擇等）
- **必須**融合 3-5 個相關 K 實驗的發現，串成一個連貫洞見
- 結構：問題場景 → 多實驗證據 → 跨實驗歸納 → 實務建議 → 跨市場 / 跨時間對比（可選）
- 目的是**站在讀者角度講故事**，不是「發表實驗結果」

| 元素 | 規範 |
|------|------|
| 標題 | 爆款型：有懸念、驚喜、具體場景（「你以為...其實...」「為什麼...」） |
| 開頭 | 用生活場景或問題帶入（「想像你有 100 萬...」），不用學術摘要 |
| 核心概念 | 用類比解釋（VIX = 恐懼溫度計、VT = 自動煞車、MDD = 最深的坑） |
| 數據 | 只引用 1-2 個關鍵數字，用白話解釋（「20 年來最差的一個月也只虧了 4.7%」） |
| 結構 | 問題 → 一句話答案 → 為什麼 → 具體例子 → 行動建議 → CTA |
| 長度 | 800-1200 字 |
| 語氣 | 像朋友聊天，不是教授講課 |

**禁止**：
- ❌ t-stat、p-value、DM test、Harvey threshold（改用「經過嚴格統計檢驗」）
- ❌ K 編號（改用「我們的研究發現」）
- ❌ 多個表格堆砌統計結果（最多 1 個簡單對比表）
- ❌ 論文引用格式（改用「學術研究顯示」）
- ❌ 超過 2 個 takeaway（一篇一個核心重點）

#### 研究發現 (audience=research)
**受眾**：有金融/統計背景的讀者、學術研究者
**目的**：完整記錄實驗結果，可追溯、可驗證

**觸發時機**：**跟著實驗走**——當實驗（或一組系列實驗）產生顯著發現時寫。不是從候選清單挑。

**兩種合法形式**：
1. **單一 K 深度報告**：重大發現可獨立成篇（例：K1145 pooled panel PASS、K1140 block-bootstrap 方法論警示）
2. **系列實驗聚合**：同主題 / 同研究目的 / 同標的的多實驗共圖寫成研究文（例：K1145+K1147+K1150 三市場 universality；K1136+K1129+K1134 alt-model NULL 跨資產）

**寫作來源（必讀，不可從 knowledge 摘要寫）**：
- `experiments/k<id>/README.md` —— 計劃、問題描述、動機、方法、預期、結論
- `experiments/k<id>*.py` 腳本**內部註解** —— 實作細節、設計意圖、樣本處理邏輯
- `experiments/k<id>_results.json` —— 真實統計量（byte-for-byte 對應，不可引自記憶）
- `experiments/k<id>*.png` —— **直接 embed 既有圖表**，不要重畫
- 系列實驗相關 K 的對應檔案（如寫 K1145 要一併讀 K1109/K1113/K1140 等背景 K）

### general vs research 二分總結

| 維度 | General（一般讀者） | Research（研究發現） |
|------|----------|----------|
| 觸發 | **主動挑讀者感興趣主題**（`publication-candidates` 軌道 A+B） | **跟著實驗進行**，有顯著發現就寫 |
| 素材 | 融貫 3-5 個相關 K 實驗 | 單 K 深度 或 系列實驗聚合 |
| 文風 | 生活類比、禁 K 編號、800-1200 字 | K 編號 + t-stat + 完整方法、3000-8000 字 |
| 主要來源 | knowledge.json 摘要 + 概念層 | README.md + 腳本註解 + results JSON + 既有 PNG |
| 寫作節奏 | 寫手動籌劃，每天 4 篇配額 | 實驗完成即寫，無固定配額 |

| 元素 | 規範 |
|------|------|
| 標題 | K編號 + 發現描述（「K304: VIX 因果性檢定 — Toda-Yamamoto 確認」）；聚合型可列多 K |
| 署名 | `[提出: XXX, 執行: Claude]` |
| 數據來源 | 明確標示（yfinance, FRED, CBOE 等）、資料期間、樣本數量 |
| 方法 | 統計方法完整描述、OOS 設定 |
| 結果 | 表格呈現（Sharpe、MDD、t-stat、p-value、DM test） |
| 結論 | 區分「統計顯著」vs「經濟顯著」 |
| 局限 | 樣本大小、proxy 假設、look-ahead 風險 |
| 引用 | 相關實驗 K 編號 |

### General 文章產出規範

- **每日 4 篇** general 文章（audience=general）
- **主題不要重疊**：每篇必須有獨立的核心 insight，不能是同一發現的不同角度改寫
- **言之有物**：必須基於具體研究數據，不能空泛
- 用 LanceDB 搜尋確認該主題尚未被寫過 general 文章
- 每完成 3-5 篇 research 文章後寫 1 篇 general

### 例外（可立即發布）

- 用戶明確要求「立即發布」
- 即時市場危機更新（如 Hormuz 事件）

- 若涉及文章池、排程發布、節奏釋出、下架、內容工作台操作，請交由 `admin-ops` skill 與平台層 API / CLI 完成
- 若是論文 PDF/metadata 更新，這不屬於 feed 發文本身；請轉交 `admin-ops` 的 `paper-*` surface

### 方法 B：record_and_publish.py（快速但品質較低）

只適合簡短的里程碑通知或 legacy 快速同步，不適合完整文章。

```bash
uv run python scripts/record_and_publish.py \
  --title "標題" \
  --thinking "內部推理（存 thinking_journal）" \
  --knowledge "知識摘要（存 knowledge.json）" \
  --phase "Phase_N"
```

**注意**：此工具的 content 來自 --thinking 參數，品質不夠好。如果要發完整文章，用方法 A。

### 方法 C：平台層釋出（文章池 / 節奏發布）

```bash
uv run python -m volpred.cli ops publish-milestone ...
uv run python -m volpred.cli ops release-pool-by-settings --storage-dir storage
```

需要查看現況或管理釋出節奏時，優先參考：
- `.claude/skills/admin-ops/references/platform-api-manual.md`
- `.claude/skills/admin-ops/references/surfaces.md`

## 發布後通知

- 文章真正進入 `published` 後，平台層可自動建立管理通知
- 管理通知預設是短版：
  - 標題
  - 摘要
  - 文章連結
- `draft` / `scheduled` 階段不應寄送通知
- 若需要補送或重寄，交由 `admin-ops`：

```bash
uv run python -m volpred.cli ops send-article-notification <pub_id>
uv run python -m volpred.cli ops send-daily-digest --target-date YYYY-MM-DD
```

- 若 `sent=false`，代表通知已建立，但 SMTP 尚未配置或尚未真正送出

## 關鍵字 Tags

每篇文章必須包含 `tags` 欄位（JSON array），用於搜尋和分類：

```json
"tags": ["VaR", "Cornish-Fisher", "SPY", "QQQ", "GLD", "TLT", "EEM", "風險管理"]
```

Tag 規則：
- 涉及的**資產代碼**（SPY, QQQ, 0050.TW...）
- **方法/模型**（GARCH, CF-VaR, EVT, MIDAS...）
- **主題分類**（波動率預測, 風險管理, 投資策略, 避險, 危機分析...）
- **研究階段**（Phase_O, Phase_N...）
- 3-8 個 tags 為宜

## 品質檢查清單

發佈前必須確認：
- [ ] 有 Markdown 結構（標題、段落、表格）
- [ ] 繁體中文
- [ ] 有數據解讀，不只是數字
- [ ] 回答「為什麼這個結果重要？」
- [ ] 回答「投資人可以怎麼用？」
- [ ] content 欄位非空且 > 300 字
- [ ] 寫入 `storage/reports/feed.json`（`storage/feed.json` 已廢除，不要使用）
- [ ] 寫入 `storage/reports/{id}.json`，且**必須包含完整 content**（不可空白）
- [ ] **圖片 URL 必須是 Supabase Storage**（`https://...supabase.co/storage/...`），不可用 `/tmp/` 本地路徑
- [ ] 寫完後執行 `uv run python scripts/supabase_sync.py full`（確保同步到 Supabase）
- [ ] Badge：category=milestone, status=published
- [ ] **tags 欄位**：包含資產代碼 + 方法 + 主題分類

## ⚠️ Agent Worktree 寫文章注意事項

Agent 在 worktree 中寫文章時：
1. **必須寫到 `storage/reports/feed.json`**（append to items array）
2. **必須寫 `storage/reports/{id}.json`**，且包含完整 `content` 欄位
3. worktree 的檔案會在 agent 完成後複製回主分支——**如果 report 檔案沒有 content，文章會以空白狀態發佈**
4. 複製回主分支後，**必須執行 `supabase_sync.py full`** 確保 Supabase 有最新文章

**2026-03-29 教訓**：27 篇文章因寫到 `storage/feed.json`（而非 `reports/feed.json`）導致 7 小時不發文；2 篇文章因 report 個別檔案沒有 content 導致空白頁面發佈到線上。

## 不該發佈的內容

- Bug fix、格式修正、系統維護
- 純數字列表沒有解讀
- 內部推理過程（放 thinking journal）
- 重複的進度更新
- 空白或只有標題的文章

## 資料同步

發佈後必須同步：
1. `storage/reports/feed.json` + `reports/{id}.json`（**唯一源頭**，不是 `storage/feed.json`）
2. 執行 `uv run python scripts/supabase_sync.py full`（將 draft 同步到 Supabase）
3. System crontab 每小時 `:03` 自動從 Supabase 釋出 draft → published
3. `frontend-v2-fix` 與後台工作台讀取最新資料
4. 依部署流程同步到線上站

## 作者標注

每篇 Feed 文章和知識記錄必須標注發起者：

| 標注格式 | 含義 |
|---|---|
| `[提出: Gemini, 執行: Claude]` | Gemini 建議方向，Claude 實驗驗證 |
| `[提出: Codex, 執行: Claude]` | Codex 建議改進，Claude 執行 |
| `[提出: Claude]` | Claude 自主發起 |
| `[提出: 用戶, 執行: Claude]` | 用戶要求的分析 |

在文章的摘要或首段註明即可。
