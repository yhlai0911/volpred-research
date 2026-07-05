# `_superseded/` — 已封存的舊版本（非 canonical，勿編譯 / 勿投稿）

本目錄存放 **taiwan-vt 論文的舊單體版本**，2026-07-05 由 `paper2_taiwan_vt_body_main_version_divergence` 任務封存。

## Canonical 投稿版（唯一有效）

- **`../main_v3.tex`**（`\input{body_v3}`）→ `../main_v3.pdf`（48pp）
- 目標期刊：PBFJ；stage：revision

## 為何封存這兩個檔

| 封存檔 | 說明 |
|---|---|
| `main.tex` | 舊單體 wrapper（`\input{body}`），54pp 舊架構 |
| `body.tex` | 舊單體 body（Table 1–14 架構），已被 `body_v3.tex` 的「7-table main + supplement」架構取代 |

### 分岔根因（significance flip）

舊 `body.tex:152` 把 TSMC(2330) 全樣本 gamma 標為 **0.039 / t=0.87（不顯著）**，來源引用
`data/tsmc_canonical.json`（**該檔不存在**，斷鏈），且誤標為「full-sample BW-robust canonical」。

實際上 0.039 是 **零均值 GJR-GARCH spec**（3-spec disambiguation 之一）；canonical 應為
**常數均值 / K892 full-sample = 0.052 / t=3.98（顯著）**，body_v3 已一致採用
（`body_v3.tex` tab:gamma L54 + 次表 L151 + sec:tsmc L457-458 footnote，皆 sourced 至
`experiments/k892/k892_verify_tw_gamma_results.json .assets["2330.TW"].full_sample`）。

舊 `body.tex:683` 另留無來源的 0050 γ=0.124/2.46 + TSMC γ=0.054/1.07 —— body_v3 已於
commit `7712d6127`（sec:tsmc provenance fix）以 K892 canonical + 2020-26 refit robustness footnote 取代。

### 額外好處：消除 paper-update mtime-tie fragility

`src/volpred/ops/papers.py` 以「最新 mtime 的 `main*.tex`」決定同步版本。封存前 `main.tex` 與
`main_v3.tex` mtime 同為 Jul 1 18:46（tie，靠 list 順序偶然選中 main_v3）。封存 `main.tex` 後
只剩 `main_v3.tex` 為當期 candidate，**同步目標變 deterministic**。

## 尚未處理（已開 followup task）

- `reproduce.py` + `experiments.md` 仍綁舊 `body.tex`/`body_v2.tex` 架構（paper_audit 2026-06-10
  line 234，JBF replication package hard requirement）→ 需 rebind 到 canonical `body_v3.tex`。
- `body_v3.tex:152-154` 個股 rolling-w2000 rows（鴻海 0.052/1.14 等）缺 `% source:` provenance。

_封存者：hourly-19 dispatch，2026-07-05。恢復方式：`git mv _superseded/main.tex ../main.tex` 等。_
