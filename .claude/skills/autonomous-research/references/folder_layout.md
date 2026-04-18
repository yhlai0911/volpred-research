# 資料夾架構指示文件

使用者 2026-04-18 整理後的正式 layout。此文件是 `experiments/` 與 `paper/` 的 source-of-truth convention。新增實驗或論文時請遵守此結構，避免再次退化成扁平散檔。

---

## 1. `experiments/` 資料夾架構

當前 1130 個實驗資料夾，七種命名 convention。**每一個實驗都必須有自己的資料夾**（不可把 `.py`、`_results.json` 散在 `experiments/` 根目錄）。

### 1.1 命名 convention（七類）

| 類型 | 範例 | 用途 | 數量 |
|---|---|---|---|
| `k####` 小寫編號 | `k1251/`, `k880/` | 主流編號實驗 | ~937 |
| `K####` 大寫編號 | `K1252/`, `K158/` | 早期或跨專案特殊標記 | ~23 |
| `k####[a-z]` 單字母變體 | `k880b/`, `k1067e/` | 同實驗的 b/c/d 後續變體（調參、換資料） | ~48 |
| `k####v2/v3` 版本後綴 | `k880v2/`, `k797v2/` | 方法顯著升級後的第二版 | ~22 |
| `k####_d#` 多階段 | `k1100g_d1/`~`k1100g_d8/` | 同一大實驗拆成 d1、d2、d3 順序階段 | ~11 |
| `k####_charts` 圖表輔助 | `k880v2_charts/`, `k884_charts/` | 主實驗的圖表專區，僅放 `.png` | ~18 |
| `i#` / `I#` 期貨避險系列 | `i0/`~`i12/`, `I1/` | 期貨避險專題（hedge ratio 系列） | ~13 |
| 主題名 snake_case | `behavioral_vt_barriers/`, `emd_garch_vol/`, `rough_vol_pilot/` | 純探索性實驗，無 K 編號 | ~55 |

額外頂層目錄：`experiments/charts/` — 放跨實驗共用的 `.png`（如 `k572_*.png`），不是單一實驗的資料夾。

### 1.2 資料夾內部結構（五種子類型）

**A. 標準研究型**（最多，對應 `k####/`、主題名、`i#/`、`_d#/`、`v2/`、變體）：
```
kXXX/
├── README.md              (必備：動機、方法、預期、結論)
├── kXXX.py                (主腳本，與資料夾同名小寫)
├── kXXX_results.json      (結果 JSON)
├── *.png                  (圖表，選)
├── data/                  (實驗專屬數據，選)
├── references/            (參考文獻，選)
├── run.log                (執行日誌，選)
└── __pycache__/           (Python 快取，git-ignored)
```

**B. 純分析/文章型**（如 `K1252/`）：
```
KXXX/
├── README.md
└── kXXX_article.md        (分析文章，無程式碼)
```

**C. Playbook 型**（如 `K1248/`）：
```
KXXX/
├── README.md
├── kXXX_playbook.md
└── kXXX_playbook_items.json
```

**D. 圖表輔助型**（`_charts` 後綴）：
```
kXXX_charts/
└── *.png                  (純圖表，依賴主實驗 kXXX/)
```

**E. 多階段型**（`_d#` 後綴，結構同 A，但檔名帶階段）：
```
kXXX_dN/
├── README.md
├── kXXX_dN.py
├── kXXX_dN_results.json
├── *.png
└── run.log
```

### 1.3 共通規則（新實驗必遵守）

1. **README.md 是必備**：打開資料夾就能知道**做什麼、為什麼、怎麼做、結論是什麼**
2. **檔名與資料夾名一致**：`kXXX/` 放 `kXXX.py`、`kXXX_results.json`（非 `script.py`、`output.json`）
3. **不可散檔**：絕對禁止 `experiments/kXXX.py`（散在根目錄），必須 `experiments/kXXX/kXXX.py`
4. **K 編號不衝突**：開跑前跑 `ls experiments/ | grep -oE '^[Kk][0-9]+' | grep -oE '[0-9]+' | sort -n | tail` 確認下一個可用編號
5. **`data/`、`references/` 子目錄只裝該實驗的資料與文獻**，不是全局共用
6. **Worktree agent 產出的檔案只應在 `experiments/kXXX/` 內**，共享 JSON（knowledge.json、feed.json）由主線程統一寫

### 1.4 歷史整理脈絡

- 2026-04-18 使用者整理：把 `experiments/kXXX_*.py`（散檔）→ `experiments/kXXX/kXXX_*.py`（資料夾化）
- 整理時被移除的 ~437 個無價值早期實驗，**移入 `archive/root-clutter/`**（不進 git，516MB）
- 新實驗（4/14 後的 K1240～K1252）本來就符合新結構

---

## 2. `paper/` 資料夾架構

10 篇論文，每篇在自己的資料夾下。投稿時期刊要求 **replication package**，所以論文資料夾必須 **self-contained**（reviewer 拿到整個 folder 就能復現所有數字）。

### 2.1 必備五項（投稿前 hard requirement）

每個 `paper/<name>/` 在達到投稿狀態前必須包含：

| 項目 | 檔案/目錄 | 說明 |
|---|---|---|
| 1. 資料清單 | `data_sources.md` 或 `data/` 目錄 | 標明 API endpoint、期間、授權條件、對應實驗路徑 |
| 2. 復現腳本 | `reproduce.py` 或 `scripts/reproduce_all.sh` | 一鍵重跑產出 `reproduce_report.json` |
| 3. 結果檔 | `results/`、`tables/`、`figures/` | 表格 PDF、圖 PNG（可 soft-link 指向 experiments/kXXX/） |
| 4. 實驗索引 | `experiments.md` 或 `experiments/` 目錄 | 列出支持實驗（K 編號 + 一句話貢獻） |
| 5. README | `README.md` | title、目標期刊、status、對應實驗 K 列表、資料來源摘要 |

### 2.2 LaTeX 版本化命名

- `main.tex`：當前最新主檔（投稿版）
- `main_v2.tex`、`main_v3.tex`：版本快照（revision rounds）
- `body_v2.tex`、`body_v3.tex`：僅修 body 不動 preamble 的版本
- `review_v1.tex`、`review_v1.1.tex`：給審稿人的 rebuttal 或追修版
- `cover_letter.tex`：給期刊編輯的 cover letter
- `citation_check.md`：引用檢核記錄（配合 `citation-verifier` skill）
- `reproducibility_audit/`：投稿前復現審計報告目錄

### 2.3 當前 10 篇論文自足度（2026-04-18 快照）

| Paper | 狀態 | 齊全度 |
|---|---|---|
| prg-periodic-garch | submitted / ready | 5/5 ✓ |
| vix-sufficiency | revision | 5/5 ✓ |
| volatility-absorption | revision | 5/5 ✓ |
| vt-crowding-abm | revision | 5/5 ✓ |
| vt-insurance-cost | revision | 5/5 ✓ |
| garch-x-vix | revision | 4/5（缺 `reproduce.py`） |
| leverage-direction | revision | 4/5（資料放 `experiments/` 目錄，無 `data_sources.md`） |
| taiwan-vt | revision | 4/5（同上） |
| vt-trend-following | revision | 4/5（同上） |
| crypto-fear-channel | outline 階段 | 1/5（合理，尚未進 body drafting） |

**投稿前補齊清單**（部分 paper）：
- `garch-x-vix`：需補 `reproduce.py`
- `leverage-direction` / `taiwan-vt` / `vt-trend-following`：建議新增 `data_sources.md` 明列資料來源（目前散在 `experiments/` 子目錄）

### 2.4 論文 workflow 入口（不屬於 layout，但補充索引）

- 修稿 workflow → `.claude/skills/paper-update/` 或 CLI `uv run volpred ops paper-update --paper-id <id>`
- Stage 判定 → `.claude/skills/paper-stage-classifier/`
- Review orchestration → `.claude/skills/paper-review-cycle/`
- 期刊 metadata、PDF slug → `docs/paper-guide.md`

---

## 3. 違反此架構的 Anti-patterns

**實驗側**
- ✗ `experiments/k1253.py`（散檔，應該 `experiments/k1253/k1253.py`）
- ✗ 無 README.md 的實驗資料夾
- ✗ 檔名與資料夾不一致（`experiments/k1253/script.py`）
- ✗ 跨實驗共用檔案塞在某個 `kXXX/data/`（共用資料放 `data/` 頂層）

**論文側**
- ✗ `main.tex` 裡引用 `Table 6` 但 `results/` 或 `figures/` 裡沒有對應檔
- ✗ 數字 drift：論文 body 寫 `QLIKE=0.287` 但 `reproduce.py` 跑出 `0.291`，且未記 errata
- ✗ 用硬 coded 結果或調整 seed 湊到論文數字（研究誠實原則第一條）

---

## 4. 變更此文件的原則

- 新增實驗命名 convention 時（例如出現第 8 種後綴），補入 §1.1 的表格
- 論文從 outline 進 body drafting 時，把 paper 齊全度表更新
- 若整理方式再次大改（例如把 K 編號遷移到 `experiments/kXXX/kXXX_vN/`），先更新此文件再執行遷移
- **不要直接手改 experiments/ 結構**（例如把 `kXXX/` 改回散檔）— 會破壞此文件描述的契約
