
---
paths:
  - "paper/**/*"
  - "docs/paper-guide.md"
---

# Paper Workflow Rules

- 論文 `.tex` 寫作與方法論決策留在主線程；不要丟給 background agent 直接改寫。
- 標準流程：審查 → 修正 → 編譯 → `uv run volpred ops paper-update --paper-id <id>`。
- 修訂時保留 review、diff、版本化檔案，不要只覆蓋舊版。
- 期刊 metadata、PDF slug、同步細節看 `docs/paper-guide.md`。
- 若涉及實驗數據或引用檢查，主線程應明確調用 `latex-academic-reviewer`、`citation-verifier`、`paper-update` 等技能。

## 論文資料夾必備內容（Self-contained paper folder）

**動機（用戶 2026-04-17 強調）**：投稿時期刊要求附上原始資料與腳本供審稿人復現（replication package / supplementary materials）。若資料夾不 self-contained，到投稿那一刻才補會措手不及；審稿人收到不完整 package 會直接拒稿。**此為投稿 hard requirement，非 nice-to-have**。

每個 `paper/<name>/` 在論文達到可投稿狀態前，**必須**包含以下 5 項：

1. **原始資料或資料清單**：`data/` 子目錄或 `data_sources.md`（若原始資料在 `experiments/kXXX/data/` 或受授權限制，此處列指標、期間、來源 API 與對應實驗路徑）
2. **復現腳本**：`scripts/` 或 `code/` 子目錄，至少收錄主要表/圖的產出腳本；若完整程式在 `experiments/kXXX/`，此處需有 `scripts/README.md` 指出對應實驗編號與入口檔
3. **結果檔**：`results/` 或 `tables/` + `figures/`（輸出 PDF/PNG 表格與圖；可用 soft-link 指向 experiments/kXXX/ 圖）
4. **實驗索引**：`experiments.md` 或在 `README.md` 列出所有支持實驗（K 編號 + 一句話貢獻）
5. **README.md**：論文 title、目標期刊、status（draft/under_review/revision/published）、對應實驗 K 列表、資料來源摘要

### Data snapshot pinning — yfinance drift 對策（2026-04-19 P8 K903/K904 教訓）

**硬規則**：Paper investible data sources（yfinance、FRED、高頻 provider）**必 pin snapshot date**，不得依賴 live re-fetch。

**為什麼**：yfinance / FRED 歷史資料**會 retroactive revise**（dividend adjustment、corporate action reconciliation）。Paper 寫作時 pull 的 sample 與 投稿 / reviewer rerun 時**不保證相同**，造成：
- 數字漂移（P8 K903 T10 2020-26 β 從 -0.00031 → +0.00014 **sign flip**，"absorption all periods" claim broken）
- Significance 漂移（P8 K904 NFP p=0.037 → 0.074）
- Cross-paper reproduce gate 集體 fail 多因此

**How to apply**：
1. 每 paper 的 `paper/<name>/data/` 下存 **snapshot CSV**（不依賴 live yfinance）
2. `reproduce.py` **必讀 local snapshot**，**禁 live yfinance.download()** 為預設 path
3. 投稿後審稿人 rerun 同樣讀 snapshot → bit-identical match
4. 若需更新資料（如 R&R 擴 OOS）→ 新 snapshot + 明標 `snapshot_date`，舊 version 保留
5. Snapshot CSV 必 `auto_adjust=False`（raw Close canonical，避 dividend reinvest drift — P4 vt-insurance-cost 教訓）

**交叉 reference**：`.claude/rules/paper-workflow.md` 「論文資料夾必備內容」之「原始資料 data/」項需同時 satisfy snapshot pinning。

**不 pin 代價**：Reviewer 復現數字與 paper 不同 → research credibility 破洞 → 拒稿風險。Paper 8、P4、P1 都踩此坑。

### Reproduce Gate — 審查的先決條件（2026-04-19 P9 garch-x-vix 教訓）

**硬規則**：Paper **不能進 review stage** 除非先通過 reproduce gate：

1. `paper/<name>/reproduce.py` **必存在**
2. `uv run python paper/<name>/reproduce.py` **exit 0**
3. `reproduce_report.json` 的 **match_rate ≥ 95%**
4. `alert_level == "green"`

**未 pass gate 的 paper**：
- **不得跑** `paper-review-cycle` / `latex-academic-reviewer` / `citation-verifier`
- **不得標** ready / submission-ready / near-submission
- **已跑過的 review 結果視為無效**（審查建立在無法驗證的 claim 上，發現的 MAJOR/MED/MINOR 全需 reproduce 補完後**重跑 review cycle**）

**為什麼**（2026-04-19 P9 教訓）：
- P9 garch-x-vix README 標 "submitted under review"、有 `review_history/v1/` + `citation_check.md` 完整審查歷史
- 但 `reproduce.py` **不存在**，`reproduce_report.json match_rate=0.0/7`
- 審稿人要 replication package → 直接拒稿
- 前輪審查發現 1 MAJOR + 5 MED citation issue — 但這些建立在「paper 數字為真」前提上；連數字都無法驗證，citation 對不對都無意義

**How to apply**：
- `paper-stage-classifier` 升 stage 前必跑 reproduce gate
- `paper-review-cycle` 開頭必 check gate，fail 則 abort + 回報 "reproduce gate fail"
- 主線程標 paper READY 前必驗 `reproduce_report.json` 現況（不只看 review_history 存在）

### Table row → JSON source 必 traceable binding（2026-04-19 Paper 4 K732/K736 教訓）

**硬規則**：Paper main.tex 裡**每個 Table row 的每個數字** 必須有**明示 source traceability**：

1. Body.tex Table row 旁加 **inline comment**：
   ```latex
   % source: experiments/k732/k732_results.json .bsi_t_stat (IS t-stat)
   % source: experiments/k732/k732_results.json .dm_stat_oos (DM t-stat)
   ```

2. `reproduce.py` 輸出結構化 mapping 到 `reproduce_report.json`:
   ```json
   "table_row_mapping": {
     "Table2.K732": {
       "is_t_stat": {"paper_value": 5.29, "source": "experiments/k732/k732_results.json", "field": "bsi_t_stat", "source_value": 5.58, "abs_pct_diff": 5.3, "status": "match"},
       "dm_abs_t": {"paper_value": 0.67, "source": "...", "field": "dm_stat_oos", ...}
     }
   }
   ```

3. **Paper-update CLI gate**：`uv run volpred ops paper-update` 改 body.tex 前必跑 `reproduce.py` + 驗證**每個 claimed number 在 Table row 有對應 source field**（不只總 match rate）。缺 source binding 的 Table row 阻擋 update。

4. **Review cycle 要求**：`paper-review-cycle` skill 檢查 body.tex 的 Table rows 都有 `% source:` inline comment + reproduce_report.json 的 `table_row_mapping` 覆蓋全部 rows。

**為什麼**（2026-04-19 Paper 4 Table 2 K732/K736 教訓）：
- K732 `IS t-stat=1.64` 實為 `dm_stat_oos=1.637` 抄錯格 — 作者複製 JSON 數字時找錯欄位
- K736 row 是 3 個 sub-experiments 混搭 composite — 沒有 source binding 檢不出
- Review cycle 和 reproduce.py 都沒抓到因為**只檢總 match rate 沒檢 per-row source mapping**

**投稿前檢查清單**（投稿 commit 前必跑）：
- 所有 Table X / Figure X 在 main.tex 都能對應到 `results/` 或 `figures/` 的具體檔
- `scripts/README.md` 能從乾淨 clone 走到每張主表/主圖
- `data_sources.md` 列全 API endpoint、期間、授權條件（含付費資料的取得管道）
- 孤兒 K ref（experiments.md 標 TODO 的）必須在投稿前補齊或明註「unused in final draft」

### 腳本 / 資料 / 論文數字必須三方一致（用戶 2026-04-17 強調）

**「所有論文中的腳本和資料都要能直接跑出最新的論文內結果。」**

每次論文數字更新（新實驗、revision、OOS 延長）後，對應腳本必須能產出**與論文 body 內寫的數字一致**的結果。具體操作：

1. **reproduce 檢查常駐**：`paper/<name>/reproduce.py` 或 `scripts/reproduce_all.sh`，一鍵重跑產出 `reproduce_report.json`；若該 paper 有 `reproduce_report.json`，則 CI / 投稿前必須重跑對齊。
2. **數字不符處理三選一**：
   - (a) **修腳本到符合論文**（合理路徑：腳本有 bug、資料切片錯誤、參數 drift）
   - (b) **修論文到符合腳本**（合理路徑：研究誠實原則 — 發現舊數字有錯 → 主線程改論文 + 記 error_log + paper-update workflow）
   - (c) **明記 errata**（暫時接受 divergence，但 commit message / README 必須明標 "pending errata, magnitude <X>%"；**不得靜默保留不一致**）
3. **絕對禁止**：為了 match 論文數字而偽造腳本輸出、硬 coded 結果、調整隨機 seed 直到湊到。研究誠實原則優先於任何「看起來齊全」的表象。
4. **重建的腳本**（如 K716-K722 case）：若 reconstruction 未能 allclose 還原舊 JSON → 必須走 (a)(b)(c) 其一決策，不可靜默 commit divergent 狀態。

參考範例：`paper/leverage-direction/`、`paper/taiwan-vt/`、`paper/vt-trend-following/`（均為齊全樣板）。

Kickoff 階段（僅 outline/abstract）可暫缺，但 body drafting 開始時必須補齊；第一次投稿前跑投稿前檢查清單。
