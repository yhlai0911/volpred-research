# Leverage-direction — canonical manuscript state & paper-update risk (verified 2026-07-02 23:xx 台灣時間)

由 hourly-23 fire 查證，為 P2 任務 `paper_body_leverage_direction_method_null_reframe_20260702`
的 **item 4（manuscript 收斂 / stale-publish 風險）** 提供已驗證 grounding。
**t1–t6 敘事重寫屬 delicate main-thread 工作，留給 clean interactive session；本 note 只記查證結果，不動 body。**

## 1. paper-update 實際 canonical 選擇（修正任務 item-4 的誤診）

任務 item-4 寫「paper-update 抓 most-recently-modified 為 canonical」。**部分正確、機制不同**：

`src/volpred/ops/papers.py:250-263` 的實際邏輯：
- 固定候選清單 `main_candidates = ["main_v4.tex", "main_v3.tex", "main_v2.tex", "main.tex"]`
  + `body_candidates = ["body.tex", "body_v5.tex", "body_v4.tex", "body_v3.tex"]`
- 先 filter 出**存在**的候選，再在其中取 `max(..., key=mtime)`。
- **`main_v_ijf.tex` / `body_v_ijf.tex` 不在清單 → paper-update 完全看不到 IJF 版。**

leverage-direction 根目錄現況：`main_v2.tex`/`main_v3.tex` 已在 `_archived/`、`main_v4.tex` 不存在
→ 清單內只剩 **`main.tex`（JBF-era，Jul 1）** 存在 → paper-update 會 sync **舊 JBF-era `main.tex`+`body.tex`**
（帶正向 inverted-leverage 宣稱，正是 Option A 要推翻的敘事）。
mtime 排序只在「hardcoded 清單內」生效，`v_ijf` 隱形 —— 這是 item-4 該記的正確機制。

**風險性質 = LATENT**：只有實際執行 `volpred ops paper-update --paper-id leverage-direction` 才觸發；
paper-update 非排程自動跑。但 paper 目前 gated，任何 tick 誤跑就會發佈 stale 正向版。

## 2. 「systemic gate」不可行 —— blocker 不是乾淨 signal（已驗證 blast radius）

考慮過給 paper-update 加「gated paper 拒絕 sync」的流程修復，但驗證後**放棄**：
- paper-update **無** do_not_advance / gated guard（`grep do_not_advance src/volpred/ops/papers.py` = 0）。
- `storage/paper_pipeline_status.json` 內 **14 篇論文全部 `has_blocker: true`**，含 `garch-x-vix`（`under_journal_review` = 已投稿/live）。
  → 用 `blocker` 非空當 gate signal 會**誤擋所有論文含 live 的**。
- leverage 的 gating 訊號是 prose（`blocker` 內文「do NOT advance to arxiv_ready」）+ `stage=multi_round_review`，非 boolean。
- **正解 = 新增 per-paper `do_not_publish` / `sync_blocked` boolean schema 欄位**（+ backfill 判定），
  屬 interactive session 的 design 工作，非 headless 快修。

## 3. Manuscript inventory（供 t1 選 base file）

| 檔案 | 定位 | 狀態 |
|---|---|---|
| `main.tex` + `body.tex` | JBF-era | STALE（正向 inverted-leverage 宣稱，Option A 要推翻） |
| `main_v_ijf.tex` + `body_v_ijf.tex` | complexity-ceiling IJF reframe | **IJF multi-round review FAIL_DO_NOT_ADVANCE**；prose 仍隱含正向 wedge，與誠實 same-windows 矛盾 |
| Option A **method-null** 版 | 目標 | **尚未寫**（t1–t6 產出） |

`_archived/` 已含 `main_v2.tex` / `main_v3.tex`（item-4 擔心的 main_v3 680-line 並存已解）。

## 4. 給下個 interactive session 的建議（t1–t6 前）

1. **base file 決策**：t1 method-null reframe 應以 `body_v_ijf.tex` 為 base（最近、已合規 scrub、elsarticle review class），
   把「complexity ceiling / positive wedge」headline 改成「method diagnosis + honest null」。
2. **收斂順序**：先寫出 method-null 版，**再**做 manuscript 收斂（item-4）—— 收斂前 method-null 版不存在，無法收斂。
3. **stale-publish 即時防護（interim，零風險）**：method-null 版未定稿前，**不要**對 leverage 跑 paper-update；
   若要根治，加 `do_not_publish` schema 欄位（見 §2）。
4. **title-page AI-disclosure**（`title_page_v_ijf.tex`）現有 Claude/Codex/AI 揭露段標為 DRAFT，
   與 boss 硬規則「禁 AI/LLM 提及」衝突 → 屬 **policy，需 boss sign-off**，勿自動改。

---
_查證者：hourly-23 autonomous fire。未改動任何 body/tex；僅新增本 note。_
