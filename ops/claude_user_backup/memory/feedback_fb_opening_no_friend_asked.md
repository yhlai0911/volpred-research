---
name: feedback-fb-anti-ai-style-aggressive
description: FB / Ivan Lai 貼文 anti-AI-style 完整規則 — 禁套路 hook（朋友問我）、禁列表 bullet、禁解釋語氣（其實也合理）、禁抽象 jargon、禁 summary recap、禁結尾 aphorism；要短句留白、口語、不裝專業
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 18e6b0cc-574e-47cf-a5e3-4f141a446583
---

寫 Ivan Lai FB 貼文時，**不要再用「最近朋友問我」/「有人問我」/「朋友問起」這類開頭**。

**Why**：用戶 2026-05-25 明確指出這是 recurring pattern — 之前 trending_repost 與 event_article FB 貼文反覆用同個 hook，讀者一看就知是模板。違背 Ivan Lai tone 第一原則「先個人觀察或判斷」(自然 / 不重複)。

**How to apply**：寫 FB 文案前先檢查開頭句，若以下出現 → 換掉重寫
- 「最近朋友問我」「有人問」「朋友問起」「常被問」
- 任何「X 問我，我就回答 Y」的對話框式 hook

合格的替代開頭模式（per fb-ivanlai-tone.md「先個人觀察或判斷」）：
1. **直接反詰結論**：「GDP 第二估會推 VIX？我去查了 25 年。沒有。」
2. **action-anchored**：「我去翻了一下 2001 到 2025 這 25 年的數據。」
3. **observation-anchored**：「這幾天看 5/29 GDP 第二估的市場預期，發現一件事。」
4. **time-anchored**：「5/29 又要到了。每年這時候市場都會問同個問題。」
5. **personal-anchored**：「看到 XXX 時，我會想…」「這幾天有件事卡在我腦袋裡…」

**Anti-pattern 不只 FB**：寫任何 reader-facing 文章（feed / trending / 留言）開頭都套用此規則 — 不要寫成 chatbot Q&A 模板。

---

## 2026-05-25 第二次告警 — 完整 anti-AI-style checklist

用戶第二句 feedback：「能不能不要那麼 ai style」。FB 貼文除了開頭，內文也有 AI 味。

**Why**：第一版 GDP K1401 FB post 用了多個 AI-typical patterns，整體像 AI 寫的「解釋型短文」非真實 status：
- ❌ 「結論有點反直覺：…」(explainer 鋪陳)
- ❌ 「理由其實也合理。…」(AI 教學語氣)
- ❌ 「我覺得是這三件事：」+ 一、二、三、列表 (硬塞 bullet 結構到 FB)
- ❌ 「高頻變動 / 模糊度 / 尾部風險」(抽象英文式 jargon)
- ❌ 「GDP 第二估和這三個沒關係」(summary recap)
- ❌ 「base case」(直譯英文)
- ❌ 「注意力放別處」(收尾 aphorism)

**How to apply — 寫 FB 前 7 條 self-check**：
1. 開頭是真實第一人稱觀察？（非「朋友問我」/「根據資料」/「研究顯示」）
2. 句子長 ≤ 25 字？段落 ≤ 3 行？
3. **完全沒有** 一、二、三 / 1. 2. 3. 的列表？（FB 不是 newsletter）
4. **完全沒有** 「其實也…」「不奇怪…」「值得思考的是…」這類 AI 教學鋪陳？
5. 抽象 jargon（「高頻變動」「模糊度」「尾部風險」）改成口語？（「一個週末改一輪」「我聽不太懂他下一步」「最近又有人提了」）
6. 結尾不要 summary recap、不要 aphorism — 收得短、收得粗糙也 OK
7. 完整對照 `.claude/skills/anti-ai-style/references/editor-sop.md` 9-checklist

**合格範例**（2026-05-25 K1401 第二版）：
```
5/29 又是 GDP 第二估的日子。

每年到這時候總有人在猜 VIX 會怎麼動。我自己也好奇過。
去翻了 2001 到 2025，25 年的資料。

VIX 沒動過。

其實也不奇怪。第二估是修訂不是新聞。
4 月初估那天該動的早動了。

倒是這幾週讓我比較放在心上的，是另外幾件事。
關稅一個週末改一輪。
Fed 講話我也聽不太懂他下一步是什麼。
然後 stagflation 這個詞，最近又開始有人提了。

VIX 在看的是這些。不是 GDP。

5/29 那天眼睛擺別的地方就好。
```

對應 skills：[[skill-trending-repost]] [[skill-anti-ai-style]] [[reference-fb-ivanlai-tone]]
