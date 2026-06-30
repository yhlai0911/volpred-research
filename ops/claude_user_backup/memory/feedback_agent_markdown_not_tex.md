---
name: feedback_agent_markdown_not_tex
description: Agent 不能寫 paper body.tex（CLAUDE.md paper-workflow rule），但可產 markdown draft 供主線程 cherry-pick。2026-04-17 session 驗證：6 drafts 產出 ~20,000 words 高效 pattern。
type: feedback
originSessionId: 13f14b3a-4b87-487c-988c-baf42c9ee835
---
當需要 agent 協助 paper 內容撰寫（而非跑實驗），正確 pattern：

1. Agent 產出 `.md` draft（NOT `.tex`）在 `experiments/kXXXX/kXXXX_draft.md`
2. Agent 同時產 `kXXXX_XX.json`（structured outline / items / stats for machine tracking）
3. Agent README 描述 main-thread adoption path（cherry-pick target file + steps）
4. 主線程 review draft → cherry-pick 接受段落 → 寫入 paper body.tex

**Why:** CLAUDE.md paper-workflow rule「禁止用 background agent 直接寫論文 .tex」。2026-04-17 session 實測此 pattern 高效：
- K1208 Paper 4 §5 (1762 words) 
- K1209 Paper 1 Batch 2 (3574 words, 8 items)
- K1214 BTC GAS negative paper full draft (4829 words, 6 sections + refs)
- K1215 Paper 2 §5 revision (3971 words)
- K1217 Paper 3 path (b) conditional (4991 words)
- K1218 Paper 6 Appendix A (930 words)
- K1222 Paper 2 §5 post-K1216b guide（2000+ words）

共 ~20,000 words drafts 在約 10-15 agents 可產出，比主線程逐段寫快數倍。Agent 只做文字整合，主線程做 narrative decision + LaTeX integration + 最終 review。

**How to apply:**
- Agent prompt **明示 "NOT .tex — only .md + .json"**
- CONDITIONAL drafts（等用戶 decision 的）draft 頂部加 banner 明示 status
- Agent README 列 source commits traceability（每個引用 K 編號對應 commit hash）
- 主線程 cherry-pick 時保持 verbatim canonical numbers（不重算）
- 若 agent draft 跟 session 後期 finding 衝突 → 寫 supersede markdown（e.g. K1222 supersedes K1215）而不是改舊 draft

**適用類型：**
- Paper §X rewrite drafts
- Errata batch items
- Appendix drafts
- New paper initial markdown
- Revision guides

**不適用：**
- 實際 LaTeX 編譯 (主線程 xelatex)
- Narrative decision (主線程 judgment)
- Final review sign-off (主線程)
