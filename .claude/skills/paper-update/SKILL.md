---
name: paper-update
description: >
  論文修訂操作 SOP — body_v(n+1).tex → xelatex → paper-update CLI → NotebookLM
  source refresh → commit → 驗證 API。只負責修訂操作；review 由 paper-review-cycle
  負責，stage 由 paper-stage-classifier 負責。Trigger phrases: 'paper-update',
  '更新論文', '同步論文平台'. Do not use for review orchestration（use
  paper-review-cycle）或 stage 判定（use paper-stage-classifier）。
model: sonnet
effort: medium
user-invocable: true
---

# Paper Update SOP

**只負責「修訂 + 同步」**。不審查（→ paper-review-cycle）、不分類（→ paper-stage-classifier）。

## Scope Boundary

Use this skill for：

- review 後的 tex 修訂
- compile 驗證
- `volpred ops paper-update` 平台同步

Do **not** use this skill for：

- review orchestration → `paper-review-cycle`
- stage 判定 → `paper-stage-classifier`

## 啟動條件

review_history/v(n)/README.md action plan 已就緒，主線程要把 v(n+1) 修出來。

## 6 步 SOP（不可跳步）

```
1. 修正（主線程，不可用 agent，per CLAUDE.md「禁止用 agent 寫論文」）：
   - body_v(n+1).tex（保留原版 v(n)）
   - main_v(n+1).tex 對應更新 \input{}
   - v(n)_to_v(n+1)_diff.md（變動摘要，供 reviewer log）

1.5 Quantitative-claim audit（每次 v(n+1) 修正後、編譯前必跑；2026-04-28 P10 v3 教訓）：
   - 對 v(n+1) 加入或修改的所有 prose-level quantitative claim（table cell、
     narrative %、ratio、t-stat、F-stat、Sharpe 等）— grep 對應 K-experiment
     JSON field 確認 source 存在
   - extend `paper/<id>/reproduce.py` 加 byte-match check (source_path
     指向 specific JSON field)
   - 若 JSON 無對應 field → 兩條路（見下方 ⚠️ 規則）：軟化為 qualitative OR
     擴 K-experiment 重跑 export

2. 編譯（驗 latex 無 error）：
   - cd paper/<id> && xelatex main_v(n+1).tex && xelatex main_v(n+1).tex
   - 確認 PDF 出來
   - 確認 page count 合理

2.5 Reproduce gate verify（編譯後、sync 前必跑；2026-04-28 P10 v3 教訓）：
   - `uv run python paper/<id>/reproduce.py`
   - 驗 `match_rate=100%`、`alert_level=green`、`gate_status=pass`
   - 若新 check fail → fix prose 數字 OR fix experiment script，**不可** commit
     pre-fix v(n+1)

3. 一鍵同步平台：
   - uv run volpred ops paper-update --paper-id <id>
   - 自動：計算 pages + citations → 上傳 PDF → 更新 metadata → 複製到前端

3.5 NotebookLM source refresh（每次 main.tex 修改 必跑）：
   - 找對應 notebooks: notebooklm list（typically：「<paper> Prior Literature
     RAG」+「VolPred Research Papers — VT & GARCH」portfolio collection）
   - 對每個含此 paper 的 notebook 跑：
       notebooklm source list -n <notebook-id> --json | grep <paper-slug>
       notebooklm source refresh <source-id-prefix> -n <notebook-id>
   - Supabase URL 不變但內容已被 paper-update 覆蓋；NotebookLM cache 需 forced
     refresh 才會 re-index 新版（`source stale` 可能誤報 fresh — 直接 refresh）
   - 目前 P6 對應 2 notebooks: 5d8707e3 (P6 Prior Lit RAG) + f0210e90 (VolPred
     Research Papers Portfolio)

4. Git commit：
   - 含 review_history/v(n)/* + body_v(n+1).tex + main_v(n+1).tex + diff
   - Message: "Paper <id> v(n+1): <核心修正主題>"

5. 驗證：
   - curl API 確認 pages/citations/pdf_url 正確
   - 看前端 /paper 頁面顯示無誤

6. 觸發下一輪 review_history（呼叫 paper-review-cycle skill）
```

## ⚠️ 規則

- **agent 禁止寫 .tex**（per CLAUDE.md）—— 修訂必須主線程
- **修正完不跑 step 3 = 沒修**——paper-update CLI 取代手動 upload + metadata update
- **跑完 step 3 不跑 step 3.5 = NotebookLM RAG 仍是舊版**——supabase URL 不變但
  NotebookLM 不會自動重 index，導致下次 RAG query 拿到舊內容（2026-04-27 P6 v4.1
  教訓：`source stale` 誤報 fresh 但實際 supabase 已被覆蓋；direct refresh 才有效）
- 每次 commit 必含 review_history/v(n)/ 全部檔案
- v(n+1).tex 完成後立即觸發新一輪 review（→ paper-review-cycle）

### Quantitative claim ↔ reproduce.py 同步硬規則（2026-04-28 P10 v3 教訓）

**規則**：任何 prose-level quantitative claim 加入 main.tex（table cell、narrative
percentage、ratio、t-stat、F-stat、Sharpe 等具體數字）**必須在 commit 前**：

1. **Extend `reproduce.py`** 加對應 byte-match check，`source_path` 指向 K-experiment
   JSON 的 specific field
2. **Re-run `reproduce.py`** 驗 gate 仍 GREEN，新 check 全 match
3. **若 K-experiment JSON 沒對應 field** → 兩條路（不可第三條）：
   - (a) 軟化 prose 為 qualitative（不報具體數字，加 footnote 承認 diagnostic 留 follow-up）
   - (b) 擴 K-experiment script 重跑、export 新 field、再 extend reproduce.py
   - **不可** 憑直覺 / narrative defensibility 寫 fabricated 數字 — 違反 CLAUDE.md
     研究誠實原則 §1「不可造假/虛構」

**為何 hard rule**：review-cycle 只 catch 已 commit 的 errors（v3 academic review
caught Table 7 numerical errors 後才 hotfix）；prepare-time prevention 才 break
recurrence pattern。2026-04-28 同 24 小時內 recurrence 證明 behavioral norm
不夠，必須 procedural enforce。

**歷史 incidents** (`docs/error_log.md`)：
- 2026-04-28 P10 v2.1 SEV-3 fix 寫 §7 γ rolling-window quantitative claims
  (median t<1.5, half-positive sign) but K1025 results.json 無對應 field → v2 review
  NEW MED-1 caught → v2.3 hotfix 軟化為 qualitative footnote
- 2026-04-28 P10 v3 K1025b 加進 Table 7 寫 row 1 "$\sim$15"、row 5 "$\sim 11\times$"
  但實際 24.31 / 5.76× → v3 review NEW MAJOR-1 caught → v3.1 hotfix Table 7
  + reproduce.py 29→37 (補 8 K1025b byte-match)

**SOP 中對應 step**：
- Step 1 修正後、Step 2 編譯前 → **Step 1.5 reproduce.py extension** (新 quantitative
  claim 對應 byte-match 加進去)
- Step 2 編譯後、Step 3 sync 前 → **Step 2.5 `uv run python paper/<id>/reproduce.py`**
  驗 100% match_rate + alert_level=green

## 與其他 skill 關係

- **review 跑不跑、何時跑** → `paper-review-cycle`
- **stage 升降判定** → `paper-stage-classifier`
- **本 skill 只在 review reports ready，要動 .tex 寫 v(n+1) 時用**
