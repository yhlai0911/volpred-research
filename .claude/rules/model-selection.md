---
paths:
  - ".claude/skills/**"
  - "scripts/agent_prompts/**"
  - "AGENTS.md"
  - "CLAUDE.md"
---

# 模型選擇與 Agent 派工原則

## 任務類型 vs 模型（必須遵守）

| 任務類型 | 模型 | 原因 |
|---|---|---|
| **研究實驗**（GARCH、統計檢定、策略回測） | `model: "opus"` | 精確性與專業性要求高 |
| **程式開發**（前端、後端、bug 修復） | `model: "opus"` | 程式碼正確性關鍵 |
| **統計分析**（DM test、bootstrap、cross-OOS） | `model: "opus"` | 數學嚴謹性不可妥協 |
| **論文寫作/審查** | `model: "opus"` | 學術品質要求 |
| **知識合成**（meta-analysis、投資指南） | `model: "opus"` | 需要深度推理 |
| 簡單搜尋（grep、檔案查找） | `subagent_type: "Explore"` | 快速唯讀 |
| 簡單文章撰寫（feed 文章） | `model: "sonnet"` 可接受 | 創意寫作彈性較大 |
| 規劃與架構 | `subagent_type: "Plan"` | 結構化思考 |

## 核心規則

1. **研究、分析、程式等精確性與專業性工作，務必使用 opus 模型**
2. **不確定時預設 opus**，不要省 token 換 sonnet
3. **優先使用 agent team 並行分派任務**，同時推進 3-4 個方向以最大化效率
4. 簡單唯讀探索（grep、檔案查找）才降級到 Explore / Plan subagent

## 與 CLAUDE.md 的關係

CLAUDE.md 的高層原則：「研究、統計、程式、論文相關工作預設用最強模型；簡單唯讀探索才降級」。此文件是該原則的具體對照表 — 對照用，不是替代 CLAUDE.md。
