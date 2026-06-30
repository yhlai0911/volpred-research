---
name: NotebookLM 在 volpred-research 的 RAG 用途
description: 何時用 /notebooklm 建主題式筆記本作 RAG；commands SOP 在 ~/.claude/skills/notebooklm/SKILL.md
type: reference
originSessionId: 91283b9e-7227-43f5-88bb-9d92168d243a
---
# NotebookLM RAG（volpred-research-specific 用途）

**Skill SOP（commands / autonomy / parallel safety / workflows / 80+ 語言）**：`~/.claude/skills/notebooklm/SKILL.md` ← canonical source，**用前必讀**，不要查 GitHub repo 繞遠路（我 2026-04-27 犯過這個錯）。

---

## 用戶 2026-04-27 四條原話（觸發 intent + 授權範圍）

1. 「未來如果有文件或論文全文，可以透過 notebooklm 建立筆記本作為 RAG 資料庫進行查詢」
2. 「當你要針對特定議題進行深度研究時，可以透過 notebooklm 蒐集資料來源並建立**主題式筆記本**提供往後查詢」
3. 「**把符合主題的論文透過 /notebooklm 上傳，或直接透過 notebooklm 去搜集資料，並建立筆記本來作為 RAG 資料庫**」
4. **「往後你要增加文獻 可自行看需要上網下載全文後 上傳至 notebooklm 上建立特定主題的筆記本 也可直接透過 notebooklm 進行資料搜集 並將筆記本作為 rag 資料庫」**

## 主線程 Autonomous workflow（授權範圍，不必逐次徵詢）

按用戶 2026-04-27 第 4 條原話，**主線程被授權**：

- 自主判斷需要哪些文獻
- 自主上網 search & download paper PDF（WebFetch / sci-hub skill / Google Scholar）
- 自主 `notebooklm source add` 上傳到既有或新建主題 notebook
- 或自主 `notebooklm source add-research "<query>"` 啟動 web/Drive auto-discover
- 自主 `notebooklm ask` query 作 cross-paper meta-eval / lit review / R1 drafting
- 主題 notebook 命名 + sources curation + 維護節奏（每月 / quarter）由主線程決定

不在授權範圍（仍需確認）：
- 大量 quota 消耗（單次建 ≥ 10 個主題 notebook、單 notebook 載 ≥ 50 sources）
- generate audio / video / podcast 等 long-running rate-limit-prone artifact
- 跨 paper 重大投稿決策（這是 paper-update / 投稿 policy 範疇，不是 NotebookLM 範疇）

## volpred-research 專案的觸發時機

- Cross-paper meta-eval（派 latex / citation agent 同時，主線程 invoke 做第三維度）
- 投稿前 prior-art audit
- Reviewer R1 response drafting
- 開新研究方向 / 重大實驗失敗深挖文獻
- Paper introduction & lit review 寫作
- 法規 / 公告 / 大型文件查詢（DGBAS / Fed / SEC / TAIFEX 規則 / 服務條款）

## 兩種使用情境（用戶區分）

### 情境 1：單篇 / 一次性查詢
單篇 paper 或 reviewer report，問完即可。直接 `notebooklm source add` + `notebooklm ask`。

### 情境 2：主題式筆記本（長期累積）
針對研究議題建持久 notebook，往後反覆查詢。
- **主動 discover**：`notebooklm source add-research "<query>" --mode deep` 自動 web/Drive 搜集
- **手動補強**：`notebooklm source add <url|path>` 補 add-research 沒抓到的關鍵 paper
- **定期維護**：每月 / quarter check SSRN / arXiv 該主題新發補進去
- 主題由實際研究需求決定（不預設 prescriptive list）

**升級判斷**：同主題會反覆用 → 建主題式筆記本，比每次重建一次性 notebook 省 quota + 跨 dispatch 累積記憶。

## 與 LanceDB / Bash 的分工

| 用途 | 工具 |
|---|---|
| 外部論文 / 文件 / 文獻 RAG | **NotebookLM** |
| 我們自己 knowledge.json / experiments / feed semantic search | LanceDB（`uv run python scripts/build_knowledge_index.py update`） |
| 專案內精確查詢 | Bash + ripgrep + jq |

**不混用**：NotebookLM 不該 ingest knowledge.json（LanceDB 已涵蓋）；LanceDB 不該 ingest 外部 paper PDF。

## Audit trail（volpred-research 慣例）

NotebookLM 雲端 service 不在 git track。重要 query 結果：
- 一次性 query → `paper/<paper-id>/review_history/v(n)/notebooklm_audit.md`
- 主題式 notebook 跨 dispatch → `paper/<paper-id>/research_notes/notebooklm_<topic>.md` 累積
- 標 notebook ID（URL 內）+ source list（`notebooklm metadata --json`）+ query 全文 + answer 摘要

## 教訓

- 2026-04-27 P5 v2 round：我給 4.4★，用戶 paste NotebookLM 評估揭露 ABM 設計性問題後降到 3.5-3.8★ → **每輪 paper review 主線程應主動 invoke `/notebooklm`，不等用戶 paste**
- 2026-04-27 我**沒讀 SKILL.md 就 WebFetch GitHub repo + 寫過於 prescriptive memory（Mode A/B 框架 + 6 個 specific 主題 notebook）**。Anti-pattern：skill 已 install 時直接讀 SKILL.md 才是 canonical source

## Anti-pattern

- ❌ 用前不讀 `~/.claude/skills/notebooklm/SKILL.md`，去 WebFetch GitHub README 繞遠路
- ❌ Memory dump SKILL.md 已有內容（commands / format / workflows）— 重複 + 浪費 token
- ❌ Prescriptive 列具體主題 notebook（用戶沒授權具體主題，case-by-case 由實際需求決定）
- ❌ 把 NotebookLM 當「被動上傳 PDF」工具（漏 `add-research` 主動 discover 能力）
