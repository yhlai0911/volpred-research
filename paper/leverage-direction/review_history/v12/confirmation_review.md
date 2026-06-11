# latex-academic-reviewer — v12 Confirmation Round

- **Paper**: `paper/leverage-direction/` (main.tex → body.tex + tables_main.tex), target JBF
- **Review date**: 2026-06-11
- **Round type**: confirmation review（驗證 v11 round 的 5 HIGH 修復狀態 + v12 sweep 新句子的數字正確性）
- **Verification basis**: 全部數字重新對 `experiments/k903/tables/k903_table2.csv` / `k903_table3.csv` 逐 cell 核對；stale-literal 全文 grep；`reproduce_report.json`（2026-06-11T05:43, green, 161 MATCH / 0 MISMATCH / 23 NOTE）；main.log（2026-06-11 05:42 fresh compile）

## Verdict: **RESIDUALS_FOUND** — 1 HIGH 殘留（v11 H5 未修），不建議解凍

v11 的 5 HIGH 中 **4 個修乾淨（H1/H2/H3/H4）**，v12 sweep 新引入的句子數字全部與 K903 CSV 一致、無新矛盾。但 **H5（body.tex:187 TLT/BTC QLIKE 舊 vintage 段）完全未動**，v11 指出的「BTC QLIKE 同文兩個相反方向（L187 vs L199）」自我矛盾仍然存在。這是一個 bounded、單段落的修復，修完 + reproduce 重跑即可解凍。

---

## 1. v11 五個 HIGH 逐項驗證

| # | v11 finding | 現行狀態 | 證據 (file:line) |
|---|---|---|---|
| H1 | GLD QLIKE prose（舊 L184）與 L144/Table 3 矛盾（Δ=−0.07%/p=0.871 舊 vintage） | ✅ **FIXED** | `body.tex:185`：「For GLD, the comparison reverses: symmetric GARCH significantly outperforms GJR in 2023--2024 (Δ = +0.39%, DM p = 0.001) and directionally in 2025 (Δ = +1.54%, p = 0.070)」— 4 個數字全 match `k903_table3.csv`（0.39/0.0013、1.54/0.0696）；「actively hurts forecasts」framing 與 L145 一致 |
| H2 | Table 2 mixed-vintage（僅 GLD row 換到 K903） | ✅ **FIXED** | `tables_main.tex:31-37`：7 rows 全部逐 cell match `k903_table2.csv`（SPY +0.132/11.08、QQQ +0.116/10.76、EEM +0.087/11.88、GLD +0.002/0.15、TLT −0.005/−0.46、BTC +0.072/2.88、SLV −0.009/−0.68）；`% source:` comment at line 30 註明 full-table swap |
| H3 | SPY 2025 QLIKE prose 舊數字（−8.818/−8.719/Δ=−1.13%/p=0.029） | ✅ **FIXED** | `body.tex:185`：「−8.412 vs −8.268 (2025, Δ = −1.74%, DM p = 0.048)」— match CSV（−8.412/−8.268/−1.74/0.0478）；grep `8.818\|8.719\|-1.13` = 0 hits |
| H4 | GLD γ 三個互斥值（+0.002 / −0.088 / regime pair）無 vintage 區分 | ✅ **FIXED**（v11 建議的 option b：window disambiguation） | `body.tex:406`：「The γ values in this mapping exercise are estimated on the 2010--2017 in-sample window … differ from the full-sample canonical values of Table tab:gamma; the GLD in-sample value in particular (−0.088) predates the K903 full-sample sign reversal and should be read as window-specific」；SPY 0.211 同句明標 "in-sample"。符合 3-spec disambiguation pattern |
| H5 | TLT/BTC QLIKE prose（舊 L186）pre-K903 vintage；BTC 方向反 | ❌ **NOT FIXED — 殘留 HIGH** | `body.tex:187` 原文未動，見下 |

### H5 殘留細節（blocking）

`body.tex:187` 現行原文：

> "TLT shows a similar pattern: GJR achieves marginally lower QLIKE ($\Delta = -0.01\%$ to $-0.54\%$), but DM tests fail to reject equal accuracy ($p > 0.10$), consistent with near-zero $\gamma$. BTC-USD is instructive: despite mild standard leverage ($\gamma \approx +0.12$), GARCH slightly outperforms GJR ($\Delta = +0.14\%$, $p = 0.293$), suggesting the asymmetric parameter introduces estimation noise when underlying asymmetry is weak and unstable (std $= 0.14$)."

對 K903 canonical 的逐項矛盾：

| 項目 | L187 現值 | K903 canonical | 矛盾位置 |
|---|---|---|---|
| TLT Δ 範圍 | "−0.01% to −0.54%"（GJR 雙期較低） | 2023--24 Δ = **+0.20%**（GARCH 較低）、2025 Δ = **−0.33%**（混合符號） | vs `k903_table3.csv` + Table 3 TLT row（+0.20） |
| BTC γ | "≈ +0.12" | **0.072** | vs `body.tex:136`（+0.072）、`body.tex:11`、Table 2 |
| BTC std | "0.14" | **0.105** | vs `body.tex:136`、`body.tex:199`、Table 2 |
| BTC Δ / 方向 | "+0.14%，GARCH slightly outperforms" | **−0.06%（GJR marginally 較低 — 方向相反）** | vs `body.tex:199`（Δ=−0.06%）、Table 3 BTC row |
| BTC DM p | "0.293" | **0.848** | vs `body.tex:199`（p = 0.848） |

**同文自我矛盾**：L199 已正確引 K903 BTC cell（Δ=−0.06%, p=0.848, γ=0.072, std=0.105）— 與 L187 相隔 12 行出現兩組互斥數字 + 相反方向，正是 v11 H5 點名的 referee-visible contradiction，原樣保留。

**Reproduce gate 為何沒攔到**：`reproduce_report.json` 的 "Prose (body.tex)" checks 是 **canonical literal 存在性**正向檢查（"+2.88 present"、"−0.06% present"），不掃 stale literal 的**負面黑名單** — L187 的 0.293/+0.14%/0.12/0.14 因此穿透 green gate。建議 v13 修復時順手在 reproduce.py prose 段加 stale-literal blacklist（0.293、+0.14\%、\approx +0.12、std = 0.14、-0.54\% 等），杜絕同型回歸。

---

## 2. v12 sweep 新句子數字驗證（全部 PASS）

| 句子 | 位置 | 對 CSV 驗證 |
|---|---|---|
| BTC significant-but-DM-tie 敘事 | `body.tex:199` | t=+2.88 ✓、std=0.105 ✓、25% negative ✓、Δ=−0.06% ✓、p=0.848 ✓、「γ=0.072 smallest among significant assets」✓（significant 組 SPY .132 / QQQ .116 / EEM .087 / BTC .072，BTC 最小）|
| Band (0.009, 0.072) | `body.tex:11`, `body.tex:199`, `body.tex:201` | SLV \|γ\|=0.009 = largest insignificant（vs TLT 0.005、GLD 0.002）✓；BTC 0.072 = smallest significant ✓ |
| L405/406 in-sample window 揭露 | `body.tex:406` | 0.211 / −0.088 / 0.006 明標 2010--2017 in-sample window-specific，與 Table 2 full-sample canonical 明確區分 ✓（窗口值本身屬 K-mechanism 實驗 spec，非 K903 對象 — 揭露方式正確）|
| GLD reversal 句 | `body.tex:185` | Δ=+0.39%/p=0.001、Δ=+1.54%/p=0.070 全 match ✓ |
| BTC 段（rolling gamma 節） | `body.tex:136` | mean +0.072 / HAC t +2.88 / std 0.105 / 25% negative 全 match ✓ |
| 「nine DM comparisons」count | `body.tex:11`, `body.tex:199`, abstract | Table 3 = 9 rows ✓；rule-prescribed model 在 9 cells 中 never significantly beaten 逐 cell 驗證 ✓（SPY×2 GJR 顯著贏、GLD 2023-24 GARCH 顯著贏、餘 6 cells NS）|

## 3. Stale vintage literal 全文掃描

grep `0.211|8.30|+1.83|0.136|-2.91|[0.12,0.17]|0.117|8.818|8.719|-1.13|0.871|0.350|-5.79|-0.067|3.21|4.12|0.180` 對 main.tex / body.tex / tables_main.tex：

- **0 個未標註殘留**，除了：
  - `body.tex:134` footnote 與 `tables_main.tex:24` caption 的 −0.067/−5.79/−2.91 — **均為明示的 earlier-draft disclosure**（合法，v11 已認可此 pattern）
  - `body.tex:406` 的 0.211/−0.088 — 已明標 in-sample window-specific（H4 fix 本體）
  - **`body.tex:187` 的 +0.12 / +0.14% / 0.293 / 0.14 — 即上述 H5 殘留**（唯一 unflagged stale 群）
- abstract（main.tex:37-40）乾淨：nine comparisons、ρ=0.886/0.83、6/6 OOS 全部與正文及 CSV 一致

## 4. v11 MEDIUM 現況（4 條）

| # | v11 finding | 現況 |
|---|---|---|
| M1 | `sec:model_selection` undefined ref | ✅ FIXED — `body.tex:141` 有 `\label{sec:model_selection}`；main.log（05:42）`LaTeX Warning` count = 0、無 undefined reference |
| M2 | Table 3 只列 9/12 K903 cells、無 row-selection rule | ❌ **未修** — `tables_main.tex:51-59` 仍 9 rows（缺 TLT 2025、EEM 2025、BTC 2025，三者均 NS）；caption 仍無 selection rule。文字端已改說 "nine comparisons" 所以無數字矛盾，但 cherry-picking appearance 殘留。建議與 H5 同批補 3 rows（文字 nine→twelve 同步）或 caption 註明規則 |
| M3 | EEM "GJR" prescription 無 DM 支持、與 band 邏輯衝突 | ✅ RESOLVED — `tables_main.tex:24` caption 明文「Model Choice applies the t > 1.65 rule to the HAC column」；EEM HAC t=+11.88 顯著 → GJR 與規則一致；band 已降格為 in-sample 等價性陳述（L199/201），無衝突 |
| M4 | Table 2 caption 只揭露 GLD swap | ✅ FIXED — caption 改為 full-table K903 provenance（"All rows reflect the K903 canonical replication"）+ line 30 `% source:` 全表註記 |

## 5. 編譯驗證

- `main.log`（2026-06-11 05:42）：**"Output written on main.pdf (49 pages)"**、`LaTeX Warning` = 0、無 undefined references。mtime 序：body.tex 01:49 < tables_main.tex 05:42 ≤ main.log/main.pdf 05:42 → log 反映現行 sources。
- 本輪嘗試重新執行 `xelatex main.tex` 多次被 sandbox classifier unavailable 阻擋（read-only 命令不受影響）；以上述 fresh log 為編譯證據。05:42 編譯與 reproduce gate rerun（05:43）為同批 v12 收尾動作。
- Overfull \hbox 262pt × 2（main.log:659/664，conclusions 摘要表區）仍在 — v11 LOW L1 殘留，JBF production 會擋，投稿前修。
- 其他 LOW 殘留：`main.tex:29` `\date{May 2026 (v3.3)}` 未 bump（v11 L2）；`experiments.md:19-25` 仍映射舊 14-table layout，例如 "Table 2 Subperiod descriptive stats" ≠ 現行 Table 2 gamma 表（v11 L3，破壞 self-contained replication folder 一致性）。

## 6. 結論與建議

**Verdict: RESIDUALS_FOUND（1 HIGH + 1 MEDIUM + 3 LOW）— 不建議現在解凍。**

殘留清單（priority order）：
1. **HIGH** `body.tex:187` — 整段以 `k903_table3.csv` 重寫（TLT：2023-24 Δ=+0.20% p=0.238 / 2025 Δ=−0.33% p=0.133，雙期 NS；BTC：γ=+0.072、std=0.105、Δ=−0.06% p=0.848 — 或直接刪去與 L199 重複的 BTC 數字、改 cross-ref）。質性結論（TLT/BTC 兩模型 indistinguishable）存活，方向句必須翻轉或中性化。
2. **MEDIUM** Table 3 補 TLT 2025 / EEM 2025 / BTC 2025 三 rows（全 NS，無敘事風險；nine→twelve 同步改 L11/L199/abstract），或 caption 註明 row-selection rule。
3. **LOW** overfull 262pt × 2、`\date` 版本字串、experiments.md table mapping。

**修復後動作**：因 1、2 觸及 tracked literals → 必須重跑 `reproduce.py` 回 green，再做一次輕量 spot-check（僅 L187 段 + Table 3 + nine/twelve 一致性），即可解凍進投稿準備。建議 reproduce.py prose 段加 stale-literal 負面黑名單（見 §1 H5 細節），把這類「正向檢查穿透」結構性堵掉。

v12 sweep 本身品質良好：4/5 HIGH 修復精確、新句子 0 數字錯誤、無新矛盾 — 殘留是 sweep 漏掃一段，不是 systematic 問題。
