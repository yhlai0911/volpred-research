---
name: research-topic-discovery
description: >
  從頂尖學術期刊系統性挖掘研究主題，持續擴展 VolPred 研究方向（取代手寫 = treadmill）。
  涵蓋四大期刊群（財金 / 實務 / 經濟頂刊 / 計量經濟）的「為什麼看 + 要找哪類主題」+
  挖掘流程 + 排程。觸發時機：研究 backlog 變薄（refill fallback < 3）、週一/四 cadence、
  「該研究什麼」「持續擴展研究主題」「技術精進」「找新方向」的決策。
  Trigger phrases: '研究主題', '找方向', '期刊', 'journal', '經濟期刊', '研究方向',
  '擴展研究', '技術精進', 'topic discovery', '挖題', 'backlog 薄'.
  Do NOT use for: 單一實驗執行（autonomous-research）、寫文章（feed-publisher）。
---

# 研究主題挖掘（持續擴展 VolPred 研究方向）

2026-06-30 用戶教訓：**沒做成 skill → 不會主動發現可用；沒排程 → 不會去執行**。loose
memory + agent_prompt 一定被遺忘（曾「忘記」經濟頂刊那條）。常態研究擴展必須 skill
（discoverable）+ schedule（auto-exec）+ 結論落檔（research_program.md，不留對話串）。

**為什麼挖期刊**：研究方向 backlog 被高速消化（1400+ K）。手寫方向 = treadmill 自我重複；
從真實期刊熱門主題挖 = 真實趨勢紮根 + 高品質 + 持續精進建模技術。

## 四大期刊群：看什麼 + 為什麼 + 找哪類主題

| 群 | 期刊 | 為什麼看 | 要找哪類主題 |
|---|---|---|---|
| **財金學術** | JBF / JFE / RFS / JoE / Review of Finance / JFQA / JEmpFin / JFM | 主流波動率/資產定價/風險前沿 | 直接的 vol/VaR/因子/microstructure/ETF flow 題 |
| **實務** | JPM / FAJ / CFA / J.Fixed Income / J.Futures Markets | 可落地、機構在用的策略 | VT/再平衡/避險/配置/策略 + 實務 regime |
| **經濟頂刊** | QJE / AER / JPE / Econometrica / ReStud / AEJ:Applied&Macro / JEP | 愛收「**乾淨識別(RD/DiD/natural experiment) + 新奇角度 + 跨領域資料**」 | **外生衝擊 / 新奇變數**：氣候·天災·政策不連續·地緣·注意力·人口·媒體·博弈/樂透文化 → **轉成波動率/風險溢酬/regime 切換**，當 VolPred 的**事件窗 / 解釋變數 / regime 訊號**。⚠️ VolPred **不做純經濟學因果**，是把外生衝擊當市場訊號（例：biodiversity transition-risk → 商品波動 K1536） |
| **計量經濟** | JFEC / JBES / REStat / JAE / Econometric Theory / Quantitative Economics | 波動率/預測的**前沿方法** | 新 realized measures、HARQ/含測量誤差 HAR、rough vol、forecast combination + 評估(DM/MCS/Giacomini-White)、jump/co-jump/regime 檢測、高頻計量、ML×計量有正式 inference → **升級 VolPred vol-forecast/risk 建模**（技術精進） |

## 挖掘流程

**輕量（backlog < 3 或週度）**：派 1 個 general-purpose agent（WebSearch, background）跑
`scripts/agent_prompts/journal_topic_scan.md` → review 輸出 → 貼進 `research_program.md`
「期刊主題挖掘 batch」section → 跑 `scripts/refill_task_pool.py --apply` 補池。

**深度（ultracode / 要全面擴展）**：用 workflow `econ-journal-topic-mining`（4 個並行 mining
agent 分別掃財金/經濟/計量/跨領域 + baseline dedup + synthesis），產 8-12 個帶 VolPred 角度 +
資料可行性的方向。script 已存：`workflows/scripts/econ-journal-topic-mining-*.js`。

**每次都要**：(1) econ_finding（學界在紅什麼）(2) volpred_angle（轉 vol/風險/策略 + 具體 proxy）
(3) data_feasibility（免費資料 yfinance/FRED/TAIFEX/TWSE/NOAA/官網/arXiv 能不能跑）。
dedup against 既有 arcs（同邏輯換外殼算重複）。不捏造論文。

**市場多樣性軸（2026-07-15 用戶指示）**：每 batch 至少 2 條非美股市場方向 — 台股產業 /
日股與其產業 / 印度（^NSEI + ^INDIAVIX 可用）/ 東南亞（^STI/^JKSE/^KLSE/^SET.BK）。
掃期刊時同步留意 JIMF / EMR / Pacific-Basin Finance Journal 等亞太/新興市場線。
可用 ticker 清單與 proxy 對照見 `research_program.md` 面向 ASIA。

## 排程（auto-exec — 沒排程就不會執行）

- `config/runtime_schedules.json::journal_topic_scan`（週一/四 cadence）→ piggy-back/session
  自動派工。**驗證它真的有 fire**：查 `research_program.md` 最近 batch 日期；若 > 2 週沒新
  batch = 排程沒執行，查 cron。
- 大體檢 `mission_progress` 維度監控 backlog 薄 → 觸發挖掘。

## 結論落檔（不留對話串）

挖到的方向 → **一律寫進 `research_program.md`「期刊主題挖掘 batch（日期 + 群）」section**；
重大方法升級 → 寫 memory/knowledge。對話串裡的結論不算數。

## 關聯
- `scripts/agent_prompts/journal_topic_scan.md`（agent prompt，本 skill 的執行載體）
- memory `feedback_journal_topic_discovery`
- `.claude/skills/pdca-operations/SKILL.md`（M2 research scan）、`autonomous-research`（接著執行實驗）
- `research_program.md`（落檔目標）
