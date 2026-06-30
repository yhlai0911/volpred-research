---
name: feedback_journal_topic_discovery
description: 研究方向自行從頂尖期刊(JBF/JFE/JPM/FAJ/CFA + QJE/AER 等經濟頂刊獵奇題)挖,不手寫;backlog 薄就派 journal-discovery agent
metadata:
  node_type: memory
  type: feedback
  originSessionId: 75c327d7-96ae-4c25-b7aa-993e4b7673d4
---

用戶 2026-06-10 糾正：「研究主題你要自行開發 先前不是有定時任務要你去找頂尖財金學術期刊的熱門主題 或是 實務類期刊 JPM、FAJ、CFA 等熱門主題 與交易策略、投資策略等有關」。

## 問題
研究 backlog 被高速消化(K1420-K1448 兩天燒光 + 我手動補的批次也很快用完)→ 我一直**手寫**研究方向 = treadmill + 品質參差。

## 正解：從真實期刊挖,不手寫
- **觸發**：refill research fallback 候選 < 3（backlog 薄）OR 週度 cadence（已建 session_cron `journal_topic_scan`，週一/四 08:17）。
- **做法**：派 `general-purpose` agent（WebSearch, background）跑 `scripts/agent_prompts/journal_topic_scan.md`，從**學術**（JBF/JFE/RFS/JoE/JFQA）+ **實務**（JPM、FAJ、CFA Institute、J. Investment Strategies、J. Trading、J. Alternative Investments、J. Fixed Income、J. Derivatives）期刊挖近 1-2 年**交易/投資策略 + 波動率**熱門主題 → 12-15 個 VolPred 角度方向（yfinance/FRED/TAIFEX 可跑、contrarian、不捏造論文）。
- **落地**：agent 完成 → 主線程 review 輸出 → 貼進 `research_program.md`「期刊主題挖掘 batch」section → `refill --apply` 補池。
- **取代**：不再手寫研究方向當 backlog。手寫只在期刊挖掘也乾的極端情況臨時用。

## 2026-06-23 用戶加：經濟學頂刊（獵奇/跨領域角度）
- 也往 **QJE / AER / JPE / Econometrica / RES / AEJ / JEP** 這類頂尖經濟期刊掃 —— 它們愛收「乾淨識別（RD/DiD/natural experiment）＋新奇角度＋跨領域資料」的題目，找**能轉成波動率/投資/風險角度**的方向。
- **VolPred 接法**：不做純經濟學因果，而是把這些外生衝擊/新奇變數當成波動率與投資策略的**事件窗 / 解釋變數 / regime 訊號**（例：氣候·天災·政策不連續·博弈樂透文化·注意力·人口·媒體·地緣 → 市場波動/風險溢酬/regime 切換）。已落地例：biodiversity transition-risk → 商品波動（K1536）。
- 已把這類來源寫進 `scripts/agent_prompts/journal_topic_scan.md` 的「## 要掃的期刊」第三類。

## 2026-06-23 用戶再加：計量經濟學頂刊（方法學）
- 也掃 **JFEC / JBES / REStat / JAE / Econometric Theory / Quantitative Economics**（Journal of Econometrics + Econometrica 已列）。
- 與經濟頂刊分工：**經濟頂刊 = 新題目/新變數；計量頂刊 = 更好的方法**（新 realized measures、HARQ/測量誤差修正 HAR、rough vol、forecast combination/評估 DM·MCS·GW、高頻、jump/regime/co-jump、ML×計量含 inference）→ 升級 VolPred 既有 vol-forecast/risk 核心，接住 C+ ML-天花板 program。
- 已寫進 prompt 第四類。

## 既有掃描器分工
- `scan_arxiv_topics.py`（週一 06:00 cron）：arXiv q-fin RSS，**ground-truth 不經 LLM**（避免 hallucinate citation），seed staging `arxiv_candidates.json`。但只 arXiv、候選薄。
- **journal_topic_scan（新，2026-06-10）**：補實務期刊 JPM/FAJ/CFA + 學術期刊，agent-based（WebSearch，有防捏造 guard），覆蓋 arXiv 沒有的 practitioner 策略主題。
- `scan_trending_agy.py`：trending blog（havingchien 等），給 trending_repost 用，不同用途。

## 首批成果（2026-06-10）
agent 掃 8 主題軸產 14 方向（VRP 隔夜/日內反號、BAB 條件性低 vol 異象、VT 跨資產有效性、股債相關 regime 60/40、CTA drawdown、regime-switch HAR+jump、multi-signal momentum、dispersion 免期權代理、tail-hedge 真實成本、新聞情緒 vol、MOVE 跨資產領先、隔夜 VRP 星期效應、加密 vol-of-vol 尾部外溢、DL-vs-HAR horizon 邊界）。全 contrarian/under-explored、期刊紮根。

相關：[[feedback_refill_check_saturation_and_running_hourly]]、[[feedback_proactive_research_posture]]、[[reference_notebooklm_rag_workflow]]、[[reference_trending_blog_sources]]。
