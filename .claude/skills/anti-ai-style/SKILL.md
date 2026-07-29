---
name: anti-ai-style
description: >
  Use for drafting or editing reader-facing Traditional Chinese prose. It
  catches formulaic AI phrasing before a feed article, FB draft, member answer,
  or public-facing summary is handed to its delivery workflow. Do not use for
  code, logs, internal memory, or data-only tables.
paths:
  - "storage/drafts/*.md"
  - "storage/reports/*.md"
  - "paper/**/*.tex"
  - "paper/**/*.md"
  - ".claude/skills/anti-ai-style/**"
  - ".claude/skills/feed-publisher/**"
  - ".claude/skills/trending-repost/**"
---

# Anti-AI Style

這是**寫作品質 leaf skill**。它只負責把讀者可見文字修到自然、精確、有人味；不選題、不發布、不操作平台或社群。

## 執行順序

1. 寫作前按情境讀 [prompt-templates.md](references/prompt-templates.md)，把負向約束放進 brief。
2. 草稿完成後執行機械 gate：

   ```bash
   # Feed／長文
   uv run python scripts/anti_ai_gate.py --file <draft.md> --no-fb-mode

   # FB 短文（啟用短段落與社群格式檢查）
   uv run python scripts/anti_ai_gate.py --file <fb-draft.md>
   ```

3. gate 非 0 時，依 [editor-sop.md](references/editor-sop.md) 的三階段修稿；需要具體改寫方式時再讀 [bad-vs-good.md](references/bad-vs-good.md)。
4. 重跑相同命令。只有 exit 0 且人工逐段確認語意沒有被改壞，才能 handoff。

## 九個必查訊號

- 假哲理式「不是／並非 X，而是 Y」
- 只在換句話說、沒有增加資訊
- 直接替讀者命名情緒
- 從小事硬拉成宏大結論
- 生硬、預告片式轉折
- 沒有來源的「有人說」
- 翻譯腔與空泛「這」
- 吊書袋、官樣抽象詞
- 中文破折號濫用

完整症狀與修法見 [8-landmines.md](references/8-landmines.md)。該檔名是歷史名稱；第九項破折號 gate 由本 skill 與 `scripts/anti_ai_gate.py` 擁有。

## 不可妥協

- 修文不能刪除或弱化必要的統計證據、限制與 null result。
- 不得為了通過字詞 gate 改變數字、因果強度或研究結論。
- 不以「同一模型自審覺得自然」作完成證據；至少要有機械 gate，加上人類或獨立 reviewer 的語意檢查。
- 連續修三輪仍無法自然表達時，退回內容 producer 重寫論證骨架，不帶病發布。

## Completion readback

交付時附：

- 實際 gate 命令與 exit code
- 修改後草稿路徑
- 仍刻意保留的專業術語及理由

來源與方法論背景只在需要追溯時讀 [sources.md](references/sources.md)，不影響日常執行。
