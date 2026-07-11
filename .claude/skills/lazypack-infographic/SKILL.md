---
name: lazypack-infographic
description: |
  Use this skill when producing a 懶人包 (cheat-sheet) infographic SET for a
  reader-facing article (audience='general', and reader-facing event/daily/
  trending pieces). Generates multiple poster-session-style PNGs — concept /
  method / results, each its own image. PRIMARY generator = codex exec (writes a
  render script fed by the evidence package → data-accurate, reproducible, free on
  the ChatGPT subscription); NotebookLM is the FALLBACK. Activates during article
  writing and at the publish step (append to article end). Triggered by intent like
  "幫這篇生懶人包圖" or the publishing rule that every general-reader article carries one.
---

# lazypack-infographic — 懶人包資訊圖（多圖 poster 模式）

每篇**一般讀者**文章（`audience='general'`，以及 reader-facing 的 event / daily / trending）發佈時，**文末必附一組懶人包圖**（用戶 2026-06-04 硬性要求）。

## 生圖時機：draft 走 async、立即發佈走同步（2026-07-02，error_log 15:15 #4）

codex render 一組圖要 ~5-15 min，**不可佔用寫作 agent 的 50 分鐘 cap**（曾擠壓正文深度 -49%）。兩條路：

- **draft 文章（daily_article 等非時效）＝ PREDEFINED async 路徑**：寫作 agent 只寫正文 + 寫好 plan.json → publish draft → 一行 enqueue：
  ```bash
  uv run python scripts/lazypack_async_render.py enqueue \
    --article-id <mile_id> --experiment K1413 --plan /tmp/plan.json
  ```
  `*/15` compute worker 自動跑 codex render → upload → append `## 懶人包圖組` → 單篇 re-sync（0 Claude token）。**draft 建檔不需懶人包**；release_pool 在 flip published 前 enforce（缺 section 不釋出，計數 3 次後 materialize fix task）。檢查 job：`uv run python scripts/compute_queue.py show lazypack-<mile_id>`。
- **立即發佈（event_article / trending_repost，status=published）＝ 同步路徑**：時效文不能等 async，publish gate 仍要求發佈當下就有 section — 照本 skill 下方「一鍵指令」同步生完再 publish。

Gate 邊界單一來源：`volpred.publisher.publisher.lazypack_required_at()`（draft/scheduled 放行、published enforce）。

## 生成方法：codex exec 為主，NotebookLM 為 fallback（用戶 2026-06-30 硬性糾正）

**PRIMARY = `codex exec`**：用 Codex CLI（ChatGPT 訂閱 auth，**flat-rate 非按張計費**）讓 codex **寫一支 render 程式**（PIL / SVG→PNG / matplotlib 自訂版面）餵 evidence package 出圖。為什麼優於 NotebookLM：
- **數字精確**：圖上每個數字直接從 `<k>_results.json` 取，不經 AI 生圖的 hallucination 風險（研究誠實）。
- **可復現**：render 程式存檔，同 input 同 output；審稿/回溯可重跑。
- **零增量成本**：codex 走 ChatGPT 訂閱（flat），本機 render 不打任何按張計費影像 API。
- **可控品質**：poster 版面（bento-grid / 分區 / 圖示 / 字級）由程式精準控制，不靠 AI 抽卡。

**FALLBACK = NotebookLM**（`notebooklm` CLI / notebooklm-py，免費網頁產品）：只在 codex exec 不可用、或某張圖確實更適合 AI-poster 美術風時用。`scripts/gen_lazypack_infographic.py` 走此路。

**仍然絕對禁止**：按張計費影像 API —— `gpt-image-2`（OpenAI 按張收費）、付費 Gemini key（`gemini_ask.py` 那支）。「零費用」的本意是禁 metered billing，**codex 訂閱與 NotebookLM 都不違反**。

## 三條鐵則（兩種生成法都適用）

1. **零（增量）費用**：codex exec（訂閱 flat）或 NotebookLM（免費）；禁按張計費影像 API（見上）。
2. **餵 source 數據，不是餵成品文字**（用戶 2026-06-04 糾正）：用「寫這篇文章的全部素材」生圖 —— `experiments/<k>/<k>_results.json` + `README.md` + `draft.md` + 任何 refs/數據檔。codex 路徑：把這些路徑當 context 餵給 codex exec，要求數字逐一對齊 results.json。文章 prose 是 lossy 壓縮；餵 source 數據才能把**方法圖**畫準、數字對得上 results.json。不要等文章寫完才用文字去生。
3. **多圖、不要一張塞爆**（poster-session 感）：一篇通常 **2–4 張**，每張只講**一種資訊型態**：
   - **概念/框架**（必）：這篇在講什麼、核心框架/名詞
   - **方法**（文章有研究方法時）：怎麼量/怎麼算的，**非技術白話**（像研討會壁報的方法說明）
   - **結果**（必）：主要發現 + 真實數字
   - **結論/takeaway**（可選）：一句話的意涵
   不同型態分不同張，**禁止**把框架+方法+結果全擠一張。

## 一鍵指令

### PRIMARY — codex exec（codex 寫 render 程式出圖）

```bash
# 推薦：scripts/gen_lazypack_codex.py（codex exec 驅動；2–4 panel；數字對齊 results.json）
uv run python scripts/gen_lazypack_codex.py \
  --experiment K1413 \                 # 自動帶 results.json + README + draft 當 context
  --source experiments/k1413/refs.md \ # 額外 refs/數據（可重複）
  --title "K1413 懶人包" \
  --plan /tmp/plan.json \              # 每個 panel 一張圖（同下 plan.json 格式）
  --out-dir /tmp/k1413_poster
```
codex exec 內部流程：餵 evidence package + panel plan → codex 寫 PIL/SVG/matplotlib render
程式 → 本機跑出 PNG → 自我核對每個數字 vs results.json。零按張計費（ChatGPT 訂閱）。
`--dry-run` 先看組出來的 codex prompt；`--model` 可覆寫 codex model。

> 既有 data-bound Pillow 範例（codex 可參考的寫法）：`scripts/lazypack_render_example_spacex.py`
> （SpaceX 文章專用 templates，僅供結構參考，每篇要重寫對應自己數據）。

### FALLBACK — NotebookLM（AI poster；codex 不可用時）

```bash
# 多圖（poster）— 餵 evidence package + plan
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
  {"name": "1_framework", "style": "professional", "prompt": "只講框架是什麼…"},
  {"name": "2_method",    "style": "editorial",    "prompt": "只講方法怎麼量（白話）…"},
  {"name": "3_results",   "style": "bento-grid",   "prompt": "只講主要結果與結論…"}
]
```

## 好提示詞（用戶強調「要有好的提示詞」）

每個 panel 的 prompt 必含：
1. **「只講 X 這一個主題」** + 明確排除別的（「不要放波動率數字」「不要重複方法」）→ 強制單一型態。
2. **真實數字**，與 `<k>_results.json` 對齊（研究誠實；數字必對得上）。
3. **非技術白話**（一般投資人看懂）；方法圖用比喻/步驟，不用統計術語。
4. **版面要求**：分區、用圖示與數字、一眼看懂。
5. **資料來源標註**：`資料來源：experiment K<id>`。

### 🚫 風格鐵則：專業、不卡通（用戶 2026-06-04 硬性）
財務內容要**專業、資料導向**。**只用**：`professional`、`bento-grid`、`editorial`、`scientific`。
**禁用卡通/可愛/手繪風**：`kawaii`、`anime`、`clay`、`bricks`、`sketch-note`、`instructional`（後兩者會放卡通小人/塗鴉,顯得不專業 — mile_71dd116b 踩過坑）。
**prompt 內也要寫死**：「風格專業、簡潔、資料導向;**禁止卡通人物、可愛插畫、手繪塗鴉風**;用乾淨圖表、圖示與數字」。讓 style + prompt 雙重保險。

## 發佈後處理

1. 每張 png → 上傳 Supabase `article-images` bucket（同既有圖流程 `publish_draft.py` 的 image upload helper）。
2. append 到文章最後，做成「## 懶人包」圖區（多張依序）。
3. `scripts/supabase_sync.py full` 推上線。

## 限制 / 防錯

- **Rate limit**：NotebookLM infographic 生成有 Google rate limit，連生多張可能 429 → `--retry 3`（指數退避）已內建；仍失敗就分批/隔幾分鐘。
- **headless**：notebooklm-py 用 stored auth（`~/.notebooklm/`），cron 可跑（不需互動瀏覽器）—— 但 auth 過期要 `notebooklm login`（互動）。若 cron 報 auth 失敗，降級成「互動 session 補圖」。
- **品質不過關**：數字錯/版面亂/塞太多 → 改 prompt 重生，不將就發佈（同 anti-ai-style 是 publish gate）。
- **「codex 不能生圖」= PATH，不是 codex**（2026-07-11，error_log 21:55）：`codex` 裝在 nvm bin，只有互動 shell 會加進 PATH；Bash tool / subagent / 缺 PATH 的 launchd job 拿到 rc 3「codex CLI not found」，被誤讀成生圖功能壞掉。所有入口已自行解析絕對路徑（`gen_lazypack_codex.py::_resolve_codex_bin`、`codex_exec_bounded.sh`）。**看到生圖失敗先確認錯誤是「找不到 binary」還是「真的生不出來」，不要直接降級 NotebookLM。**
- 驗證：生完用 Read 看圖、核對數字 vs results.json 再 append。

## 交叉參考
- `.claude/rules/publishing.md`（每篇必備：一般讀者文章文末附懶人包圖）
- `~/.claude/skills/notebooklm/SKILL.md`（NotebookLM CLI 全指令）
- `scripts/gen_lazypack_infographic.py`（一鍵實作）
