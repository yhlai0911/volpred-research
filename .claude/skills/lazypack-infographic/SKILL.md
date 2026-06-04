---
name: lazypack-infographic
description: |
  Use this skill when producing a 懶人包 (cheat-sheet) infographic SET for a
  reader-facing article (audience='general', and reader-facing event/daily/
  trending pieces). Generates multiple poster-session-style PNGs — concept /
  method / results, each its own image — via NotebookLM for FREE (no paid image
  API). Activates during article writing (fed by the evidence package) and at
  the publish step (append to article end). Triggered by intent like "幫這篇生懶人包圖"
  or the publishing rule that every general-reader article carries one.
---

# lazypack-infographic — 懶人包資訊圖（多圖 poster 模式）

每篇**一般讀者**文章（`audience='general'`，以及 reader-facing 的 event / daily / trending）發佈時，**文末必附一組懶人包圖**（用戶 2026-06-04 硬性要求）。

## 三條鐵則

1. **零費用**：只用 **NotebookLM**（`notebooklm` CLI / notebooklm-py，驅動用戶免費的 NotebookLM 網頁產品）。**絕對禁止**付費影像 API：`gpt-image-2`（OpenAI 按張收費）、付費 Gemini key（`gemini_ask.py` 那支）。NotebookLM `generate infographic` 直接出 .png。
2. **餵 source 數據，不是餵成品文字**（用戶 2026-06-04 糾正）：在**寫文過程中**就用「寫這篇文章的全部素材」生圖 —— `experiments/<k>/<k>_results.json` + `README.md` + `draft.md` + 任何 refs/數據檔，**一起加進同一個 notebook**。文章 prose 是 lossy 壓縮；餵 source 數據才能把**方法圖**畫準、數字對得上 results.json。不要等文章寫完才用文字去生。
3. **多圖、不要一張塞爆**（poster-session 感）：一篇通常 **2–4 張**，每張只講**一種資訊型態**：
   - **概念/框架**（必）：這篇在講什麼、核心框架/名詞
   - **方法**（文章有研究方法時）：怎麼量/怎麼算的，**非技術白話**（像研討會壁報的方法說明）
   - **結果**（必）：主要發現 + 真實數字
   - **結論/takeaway**（可選）：一句話的意涵
   不同型態分不同張，**禁止**把框架+方法+結果全擠一張。

## 一鍵指令

```bash
# 多圖（poster，推薦）— 餵 evidence package + plan
uv run python scripts/gen_lazypack_infographic.py \
  --experiment K1413 \                 # 自動加 results.json + README + draft
  --source experiments/k1413/refs.md \ # 額外 refs/數據（可重複）
  --article-id mile_31b2b0bb \         # （可選）也把文章內容加進來
  --title "K1413 懶人包" \
  --plan /tmp/plan.json \              # 每個 panel 一張圖
  --out-dir /tmp/k1413_poster

# 單圖
uv run python scripts/gen_lazypack_infographic.py \
  --experiment K1413 --prompt "<好提示詞>" --out /tmp/x.png --style bento-grid
```

語言鎖 `zh_Hant`；`--wait --retry` 已內建；跑完自動刪 notebook（`--keep-notebook` 保留）。

### plan.json 格式
```json
[
  {"name": "1_framework", "style": "instructional", "prompt": "只講框架是什麼…"},
  {"name": "2_method",    "style": "sketch-note",   "prompt": "只講方法怎麼量（白話）…"},
  {"name": "3_results",   "style": "bento-grid",    "prompt": "只講主要結果與結論…"}
]
```

## 好提示詞（用戶強調「要有好的提示詞」）

每個 panel 的 prompt 必含：
1. **「只講 X 這一個主題」** + 明確排除別的（「不要放波動率數字」「不要重複方法」）→ 強制單一型態。
2. **真實數字**，與 `<k>_results.json` 對齊（研究誠實；數字必對得上）。
3. **非技術白話**（一般投資人看懂）；方法圖用比喻/步驟，不用統計術語。
4. **版面要求**：分區、用圖示與數字、一眼看懂。
5. **資料來源標註**：`資料來源：experiment K<id>`。

`--style` 可選：`professional`（資料型）、`bento-grid`（結論卡）、`instructional`/`sketch-note`（框架/方法）、`editorial`、`scientific` 等。

## 發佈後處理

1. 每張 png → 上傳 Supabase `article-images` bucket（同既有圖流程 `publish_draft.py` 的 image upload helper）。
2. append 到文章最後，做成「## 懶人包」圖區（多張依序）。
3. `scripts/supabase_sync.py full` 推上線。

## 限制 / 防錯

- **Rate limit**：NotebookLM infographic 生成有 Google rate limit，連生多張可能 429 → `--retry 3`（指數退避）已內建；仍失敗就分批/隔幾分鐘。
- **headless**：notebooklm-py 用 stored auth（`~/.notebooklm/`），cron 可跑（不需互動瀏覽器）—— 但 auth 過期要 `notebooklm login`（互動）。若 cron 報 auth 失敗，降級成「互動 session 補圖」。
- **品質不過關**：數字錯/版面亂/塞太多 → 改 prompt 重生，不將就發佈（同 anti-ai-style 是 publish gate）。
- 驗證：生完用 Read 看圖、核對數字 vs results.json 再 append。

## 交叉參考
- `.claude/rules/publishing.md`（每篇必備：一般讀者文章文末附懶人包圖）
- `~/.claude/skills/notebooklm/SKILL.md`（NotebookLM CLI 全指令）
- `scripts/gen_lazypack_infographic.py`（一鍵實作）
