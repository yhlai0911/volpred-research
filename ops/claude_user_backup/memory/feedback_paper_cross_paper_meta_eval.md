---
name: 論文 review 必含 cross-paper meta-evaluation 不只 single-paper review
description: Single-paper latex/citation review 抓不到 cross-paper 結構性問題（同數據集、同主題、自我引用）— 必須額外做 portfolio-level meta-evaluation
type: feedback
originSessionId: 91283b9e-7227-43f5-88bb-9d92168d243a
---
# 論文 review 必含 cross-paper meta-evaluation

學術論文 review cycle 不只是 single-paper latex/citation 兩個維度。**必須額外做 cross-paper meta-evaluation**，否則會漏 reviewer 一定打的結構性問題。

**Why**：用戶 2026-04-27 提供 NotebookLM + 獨立評估，揭露我之前 P5 v2 review 4.4★ 預測過度樂觀的根因 — single-paper agent 範圍只在 main.tex，看不見以下「跨論文視角」issues：

1. **同數據集 / 同主題 / 同工具切片 risk**：9 篇都用 SPY/GLD/TLT/VIX，樣本高度重疊，結論都收斂「12/VIX 法則夠用」— reviewer 會懷疑「一篇切九份」
2. **方法論套套邏輯 / 設計性結果**：P8 NSI `|r|/VIX` 對 `VIX` 迴歸（分母與自變數同 = 數學必然），P5 ABM 70% 崩盤閾值是 λ/γ 參數結果（不是 emergent）— 這些 single-paper review 範圍內看不到，要從「設計這個方法 vs 發現 emergent property」的 step-back perspective 才看得見
3. **新穎性過度宣稱**：P5 ABM Brunnermeier-Pedersen 已有框架、P4ins True Cost 已被 Moreira-Muir 隱含、P7 共識已存在 — single-paper citation review 只 verify「引用是否正確」，不評「貢獻是否真新穎」
4. **互相引用未發表 working paper**：P1-P10 互引在 peer review 高度敏感，single-paper review 不會 flag

**How to apply**：

### v2/v3+ review round 必含 4 維度（不只 latex + citation）

每輪 review 要 launch **3 個 reviewer agent + 1 主線程 synthesis**：

1. **latex-academic-reviewer**（單篇 latex 完整審）— skill 已有
2. **citation-verifier**（單篇引用驗）— skill 已有
3. **🆕 cross-paper-meta-evaluator** 主線程或 dedicated agent — 評估：
   - 這篇 paper 與 portfolio 其他篇的 dataset / methodology / conclusion 重疊度
   - 「設計性結果 vs emergent finding」誠實 framing
   - 真實新穎性（先行文獻 within ±3 years vs claimed contribution）
   - Self-citation 比例（互引 working paper > 30% 是 red flag）
   - 統計力 + sample size adequacy（N=22 截面 / N=9 個股 太小）
4. **主線程 synthesis** — 整合三個 review 的 verdict，給 portfolio-aware 升 stage 判斷

### Stage 升 ready_for_submission 條件強化

舊規則（paper-stage-classifier / paper-review-cycle SOP）：「latex ≥ 4★ + citation 0 MAJOR + ≤3 MED → 升 ready」**不夠嚴格**。

**新規則**：升 ready_for_submission 需 **4 條件齊備**：
- latex ≥ 4★ ✓
- citation 0 MAJOR + ≤3 MED ✓
- **cross-paper meta-eval verdict = "no fundamental issue"** （新增）
- **target journal 現實機率 ≥ 40%**（按獨立 reviewer-style 評估而非 self-prediction）

### 不要再相信「single agent 4.4★ + 4 ready papers 全可投稿」這種 framing

agent 的 single-paper review 視角窄，主線程綜合判斷時必須加 portfolio view。Mission L7「把學術論文寫好」+ top-tier journal 目標 = 方法論誠實 + cross-paper 獨立性 + 新穎性嚴格自評，三者缺一不可。

## 教訓 reference

- 2026-04-27 P5 v2 round：latex-academic-reviewer agent 給 4.4★ + FRL 85-90% accept 預測，我採信寫進 v2 README。NotebookLM + 獨立 Opus 評估後揭露 ABM 臨界點是「設計出來的」非 emergent finding，預測應降至 3.5-3.8★ + FRL 40-50%。差距 +0.6-0.9★ 完全因為 single-paper agent 看不到 step-back 設計性問題。
- 9 篇 paper 同數據集 / 同主題 / 同工具的 portfolio risk 在任何 single-paper round 都不會 surface — 必須 portfolio-level review。

## Anti-pattern

- 用 single-paper latex 4★ + citation 0 MAJOR 直接判定可投稿（沒 cross-paper view）
- agent 預測 journal acceptance probability 直接寫進 README（agent 沒讀過該 journal 近期 reject pattern，預測偏樂觀）
- ping 用戶「4 papers READY 等 confirm 投稿」（這次教訓的根源）
- v(n+1) round 只 fix v(n) raise 的 issues，不重新跑 portfolio-level meta（漏新發現的結構問題）
