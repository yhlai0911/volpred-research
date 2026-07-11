# EXECUTION — btc-gas-negative

> **BADGE** · verdict `3.5/5` · stage `draft`（**pre-draft：僅 markdown drafts，無 .tex / reproduce.py**）· journal `IJF → JoFE → JEF` · **p0 = TODO** · dod `0/8`
> 依據：`review_history/fable_deep_review_20260711/README.md`（Fable 深審 3.5/5，conditional GO）· `docs/paper_portfolio_review_20260711.md` · `storage/paper_pipeline_status.json`
> 最後更新：2026-07-11（Fable deep review 完成，P0 尚未執行）

> **主題澄清（避免被檔名誤導）**：本篇的「GAS」是 **Generalized Autoregressive Score**（Creal-Koopman-Lucas 2013 score-driven 波動率模型），**不是** blockchain gas fee；「negative」指 negative-result methodology paper（GAS-t 在 pre-institutional BTC 反轉輸給 GJR-Normal 的負面結果）。全文不存在任何 gas fee 分析。

---

## 最終目標

把 btc-gas-negative 從「pre-draft（只有 markdown outline + body_v1.md，無 `.tex` / `reproduce.py` / snapshot CSV / `data/`）」狀態，經 P0 誠實重寫 + 可復現底盤建置，推進到 **International Journal of Forecasting（IJF）可投稿**。

**核心貢獻（保留、不稀釋 — 但要正確框架）**：Period 1（pre-institutional BTC）GAS-t 相對 GJR-Normal 有 robust 的 forecast deficit（跨 QLIKE/MSE/Patton loss、boundary、LOO jackknife 全數存活）。把 deficit **歸因於 Student-t innovation** 的 2×2 factorial 診斷則是 **loss-specific**：QLIKE 下成立，MSE/Patton 下翻 NS/反向（因 GAS-N 以偶發變異數暴衝換取 QLIKE 優勢）。GED 為厚尾卻表現如 Normal → 元兇不是「厚尾」而是 **t/skew-t 特定的 score 減權形狀**。最誠實、最耐審的賣點 = 把「診斷本身 loss-dependent」升級為方法論貢獻（Patton 2011 forecast-bias 情境的實例），而非掩蓋它。

**期刊順序（已裁定，老闆授權自主 — memory `feedback_paper_autonomy_optimize_acceptance`）**：
1. **IJF（primary）** — forecast-evaluation + negative result + loss-function sensitivity 完全在 scope（Catania et al. 2019 crypto forecasting 即 IJF）；replication package 符合 IJF replication 傳統。
2. **JoFE（Journal of Financial Econometrics，secondary）** — factorial 診斷方法論角度。
3. **JEF（Journal of Empirical Finance）/ Quantitative Finance（backup）**。

> **關鍵裁定（寫進本檔以免再被誤導）**：標題「Student-t Innovation, ... **Is the Culprit**」與摘要「isolating Student-t innovation as **the proximate cause**」在 `k1133b_robustness_results.json` 的 `alt_loss_m4_vs_m3_all_positive = false` 面前**過強、無法存活誠實審查**。K1133b README（2026-06-29）已自承：stronger claim「Normal-vs-Student-t decomposition is uniformly robust」does **not** pass。**正確動作 = attribution 全面降級為 QLIKE-conditional**（deficit robust ✅，attribution 不 robust ❌），標題改為診斷的條件性版本。**JBF 建議放棄** — 本文無 banking/asset-pricing 經濟內容，掛 JBF 是 desk-reject 風險。

---

## 當前狀態

**Verdict 3.5 / 5（現狀 conditional GO；完成 P0 後為「扎實的 IJF 投稿候選」，非 JFE/RFS 級別）。**

- **實證核心乾淨** ✅：Period 1 五模型 factorial 全部 headline 數字（**-4.67 / -3.36 / +2.67 / +5.97 / +0.28**）本次直讀 `k1133b_results.json` 逐一吻合；兩輪誠實清洗（R0 2026-06-07 + audit 2026-06-10）已移除捏造 §8 與 K1129 誤歸屬。DM/HAC lag **不在** K1655 凍結 backlog（k1133b 用 `floor(n^(1/3))` Bartlett = lag 11，非退化 `h-1` class；與 repo canonical `ceil(h^(1/3)·n^(1/3))`=12 僅 floor/ceil 差異）。全樣本 2015–2026（4,121 obs）、P1 OOS n=1,441 遠超 ≥500 門檻且含 2018 空頭；LOO jackknife（2017/18/19/20 逐年排除，t = -3.64/-3.47/-4.19/-2.84 全負）確認非單一年份 artifact。
- **手稿層尚不可投** ❌：這是 **pre-draft** — 只有 `drafts/body_v1.md`（459 行）+ section markdown，**無** `.tex` / `reproduce.py` / snapshot CSV / `data/`。三個誠實問題必先修（見 P0）：§5 L361 tight-basin 捏造句倖存且被 6-29 真實 multistart 打臉；pre-registration 2026-04-12/04-15 日期 git 驗證失敗；M3 GAS-t 重建 DM -4.03 vs archive -4.67。
- **核心 attribution 是 QLIKE-specific**（6-29 robustness 已落地 runtime 2,655s，但 paper 文件仍寫「planned/not yet run」— 狀態 stale）：M4 GAS-N vs M3 GAS-t 創新對比 QLIKE(b=-2) **t=+2.97 顯著**，但 **MSE(b=0) t=-1.01 NS**（M4 平均 MSE 83,754 vs M3 4,364，爆炸 19 倍）、**Patton(b=-1) t=-0.32 NS**。M3-vs-M1 **deficit 本身**則跨三 loss 全 |t|>3（-4.03 / -5.14 / -6.02）— deficit robust，attribution 不 robust。
- **GED 打破「厚尾=元兇」簡化**：GAS-GED vs M1 **t=-1.23 NS（有 recover to parity）**、GAS-skew-t **t=-5.02（更糟）**、GAS-N vs GAS-GED t=-0.16（無差異）→ 元兇是 t/skew-t 特定 score 減權形狀，非厚尾本身。§5 現行「skewed-t 與 GED 都 do not recover」敘述**對 GED 是錯的**，必改。另注意 alt-dist 協定用 refit 252（非 headline 的 63），該協定下 M4 vs M1 **t=-2.57 顯著輸** → dynamics-parity 對 refit cadence 敏感，須揭露。
- **未關閉最大實證風險**：單資產（ETH/BNB 因 Yahoo 歷史不夠長 fail-fast — 誠實的 fail）；Period 2 (n=345) / Period 3 (n=100) 「無 deficit」屬低 power null，JSON 自標 preliminary。BTC-USD 價格無 vintage 修訂（K1655 不適用），殘餘風險僅 yfinance 歷史 bar 偶發回溯修正（K903/K904 → snapshot pin 就是為此，尚未落地）。

---

## 完成定義（DoD）— 全部未達成

- [ ] **P0-1** 落地：§5 L361 tight-basin 捏造句刪除、§8 由「planned」改引 2026-06-29 真實 robustness battery（boundary/LOO PASS、alt-loss deficit-robust / attribution-QLIKE-only、GED/skew-t 真值、ETH/BNB fail-fast 如實）、GED 敘述修正、標題/摘要降級為 QLIKE-conditional attribution、雙份 abstract 收斂
- [ ] **P0-2** 落地：pinned 2026-04-15 snapshot CSV + per-model OOS forecast 序列 persist + `reproduce.py` 兩層 gate（archived-forecast bit-exact 快速層 + re-estimation tolerance 慢速層）+ §8 誠實揭露 M3 重建變異（DM -4.03 ~ -4.67）
- [ ] **P0-3** 落地：刪除 2026-04-12 / 04-15 pre-registration 日期宣稱（git 含 `--all` 驗證失敗），改結構性 2×2-design 論證；`experiments.md` / `data_sources.md` 同步
- [ ] markdown → **IJF（Elsevier）LaTeX** `main.tex` 建置，xelatex 編譯無誤，每 Table row `% source:` binding 到 JSON field
- [ ] `reproduce.py` exit 0 且 `reproduce_report.json` match_rate ≥ 95% / **alert green**
- [ ] `/citation-verifier` 重跑 **0 MAJOR**（新增 Ardia et al. 2019 / Caporale & Zekokh 2019 prior art + 補 6 條缺 bib + 修 Hansen-Lunde-Nason 2003 誤歸屬 + L328「Diebold-Mariano-Harvey-Lin-Newey」錯誤展開）
- [ ] IJF `journal-review` compliance gate 通過（author = Yi-Hao Lai only；無 volpred / AI / Codex / platform metadata 字樣）
- [ ] `uv run volpred ops paper-update --paper-id btc-gas-negative` 同步 + 線上驗證

---

## P0 — 誠實修正 + 可復現底盤（阻擋 .tex 的全部項；估 3–4 個工作天；全部 ⬜ TODO）

### ⬜ P0-1 — §5/§8/abstract/標題 對 robustness JSON 重寫（主線程，markdown，估 1 天）

把 6-29 已落地但文件 stale 的真數字內化，並降級過強 attribution：

- ⬜ **刪 `body_v1.md:361` tight-basin 捏造句**（「100 random initializations converge to a tight basin with maximum-to-median log-likelihood ratio below 1.5% ... reported for all five cells」），改引真實 `multistart_dispersion.aggregate`：全 5 模型 `share_windows_max_minus_best_le_0.5 = 0.0`；M4 median-start 離 best 35.5 LL 單位、單窗最大離散 3,140 萬（M1/M2/M3/M5 的 median_minus_best ≈ 1e-8）。可辯護的是「100-start 必要性」（M4 basin 難找），**不是**「tight basin」。
- ⬜ **§8 從「planned / not yet run」改為引用 6-29 真實 mixed battery**：boundary PASS、LOO PASS、alt-loss「deficit 跨三 loss robust（-4.03/-5.14/-6.02）／attribution 僅 QLIKE 成立」、GED/skew-t 真值、ETH/BNB fail-fast 如實。
- ⬜ **GED 敘述修正**：改為「GED（厚尾）recover to parity（t=-1.23 NS）而 t/skew-t 不 → 元兇是 t 特定 score 減權形狀，非厚尾本身」。
- ⬜ **揭露 alt-dist refit-252 協定差異**與該協定下 M4 vs M1 t=-2.57（dynamics-parity 對 refit cadence 敏感）。
- ⬜ **標題 / 摘要降級為 QLIKE-conditional attribution**：標題方向如「The QLIKE-Specific Anatomy of a GAS-t Failure on Pre-Institutional Bitcoin」或保留架構但副標明示診斷的條件性；刪「the proximate cause」絕對化。
- ⬜ **收斂雙份 abstract**：body 內嵌 abstract（L21「FTX-Luna (2021-2023) and spot-ETF (2024+)」）與已修正的 `v0_outline_abstract.md`（「post-FTX recovery (OOS 2023)」）drift → 單一來源。

**驗證 gate**：markdown 重寫後每一 robustness 數字回 `k1133b_robustness_results.json` 逐格覆核；標題/摘要無絕對化 causal 措辭。

### ⬜ P0-2 — snapshot CSV + forecast 序列 persist + reproduce.py（估 1.5–2 天）

- ⬜ **落地 pinned 2026-04-15 snapshot CSV**（`auto_adjust=False`）— K1133b canonical sample end；`reproduce.py` 讀 local snapshot **不** live fetch（K903/K904 sign-flip 教訓）。
- ⬜ **改 k1133b pipeline 存 per-model OOS forecast 序列**（目前未存檔）。
- ⬜ **`reproduce.py` 兩層 gate**：archived-forecast 快速層從 persist 的 forecast 序列重算 loss/DM（bit-exact 可達）；re-estimation 慢速層 full re-fit 標 tolerance。
- ⬜ **§8 誠實揭露 M3 重建變異**：M1/M2/M4/M5 重建 delta=0.0，M3 GAS-t QLIKE 2.2076 vs archive 2.1904（Δ0.017）、DM -4.03 vs -4.67（Δ0.64）— 方向與顯著性不變（-4.0~-4.7 全遠過 |3|），根因 GAS-t 非凸面 + 重建 RNG stream 差異。exact-match gate 對 M3 會 fail，故走兩層設計。

**驗證 gate**：`reproduce.py` exit 0、`reproduce_report.json` match_rate ≥ 95% / green、`table_row_mapping` 驗證每 row 綁定。

### ⬜ P0-3 — pre-registration 宣稱降級（估 0.5 天，研究誠實 § 不可協商）

- ⬜ **刪除 2026-04-12 / 2026-04-15 日期宣稱**（§5、`experiments.md` §Methodological pre-registration、`data_sources.md`）。git 事實（含 `--all`）：`experiments/k1133/` 最早 commit = 2026-04-17 23:38（b05e47458）、k1133b = 2026-04-18；k1133b results `created_at` = 2026-04-17 17:04 UTC。2026-04-12 不存在於任何可驗證歷史。
- ⬜ **改結構性論證**：「the factorial contrasts follow mechanically from the 2×2 design, limiting specification-search freedom」取代不可驗證的日期宣稱（§5 用 pre-registration 反 data-mining 是 load-bearing，必須降級不刪除論證本身）。

**驗證 gate**：`grep` 全 paper 無殘留 `2026-04-12` / `2026-04-15` pre-registration 日期宣稱；結構性論證通順。

---

## P1 — R1 前補強（與 P0 平行可做，估 2–3 個工作天 + 計算）

- **MCS（Hansen-Lunde-Nason，6 模型 × 3 期，α=0.10/0.25）** 落 JSON + §3.6 multiple-testing 說明（primary contrasts pre-specified、其餘 descriptive）；~15 個 DM 檢定目前無 joint inference，IJF referee 必問。計算量小（loss 序列已有）。
- **per-period excess kurtosis 落 JSON**（§7.1 現為定性）、§3.1 補 **UTC 收盤定義**（24/7 交易下「日收盤」= UTC 午夜切點）、Period 2 warm-up 揭露（Luna/FTX 崩盤不在 OOS）。
- **Citation cleanup 全套** + **Ardia, Bluteau & Rüede 2019（FRL）/ Caporale & Zekokh 2019（RIBAF）prior art 引用**並把「no prior paper tests MS-GAS-t rescue」gap 陳述收窄為「score-driven MS + factorial 分解」+ **NotebookLM prior-art audit**（確認 previously-unreported 站得住）。
- **Compliance scrub**：「Codex」以審查者身分出現在方法論正文（L310, 426 等）→「an independent code review」；刪 header/尾段平台 metadata（hourly-08 fire / Next Sub-Tasks / P4 paper_body）。
- **knowledge.json K1133 條目誤歸屬修正（主線程）**：現寫「K1129 DM t=-4.58 **decomposes into** P1 2017-2020」，但 K1129 無 2017-2020 OOS，為已知誤歸屬殘留。
- **（可選但高價值）ETH 原生窗 factorial**：ETH-USD 2017-11 → 2020-12-31（OOS ~2.3 年），用 ETH 自己的 pre-institutional 窗而非硬對齊 BTC P1，一舉補掉單資產致命傷。計算 ~1 小時級。
- **canonical `volpred.stats.model_evaluation.dm_test`（`ceil(h^(1/3)·n^(1/3))`）重算 DM 對照表附錄**，消除 floor/ceil 差異的任何質疑（數字預期不動，成本極低）。

---

## P2 — 轉換與投稿（P0 全部完成後才啟動；估 3–5 個工作天；全部 ⬜ TODO）

- ⬜ **Markdown → IJF（Elsevier）LaTeX `main.tex`**（非 JBF template），每 Table row 掛 `% source:` binding；xelatex 過。**主線程進行，不丟 background agent 改 .tex**（paper-workflow 硬規則）。
- ⬜ **`paper-review-cycle` R1**（latex-academic-reviewer + citation-verifier）→ 收斂 → **`journal-review`（IJF profile）** → compliance gate。
- ⬜ **`paper-update` CLI 同步** + `paper_pipeline_status.json` stage 由 `draft` 推進。

**驗證 gate**：xelatex 無誤 + reproduce green + citation 0 MAJOR + IJF compliance PASS + paper-update 線上驗證。**P0 全部完成前維持禁轉 .tex**（延續 R0/audit gate）。

---

## 禁止事項（本篇特有）

- ⛔ **標題「Student-t Innovation ... Is the Culprit」絕對化必改** — attribution 是 QLIKE-specific（`alt_loss_m4_vs_m3_all_positive = false`）；MSE t=-1.01 NS、Patton t=-0.32 NS，M4 均 MSE 爆炸 19 倍。K1133b README 6-29 已自承 stronger claim does **not** pass。
- ⛔ **`body_v1.md:361` tight-basin 句是捏造** — 6-29 真實 multistart 顯示 `share_windows_max_minus_best_le_0.5=0.0`、M4 median-start 離 best 35.5 LL；必刪，改引真實 aggregate，不可沿用「below 1.5%」。
- ⛔ **別再宣稱 pre-registration 2026-04-12 / 04-15 日期** — git（含 `--all`）證實 k1133 最早 commit 2026-04-17，日期不存在於可驗證歷史；改結構性 2×2-design 論證（研究誠實層級，不可協商）。
- ⛔ **§5「GED do not recover to parity」對 GED 是錯的** — GAS-GED vs M1 t=-1.23 NS 有 recover；必改寫為「t/skew-t 特定 score 形狀」框架。
- ⛔ **M3 重建 DM -4.03 vs archive -4.67 不合** — 誠實揭露重建變異 + 走 reproduce 兩層設計，**不 sed / Edit 改 JSON 湊 exact match**（修流程不修資料）。
- ⛔ **別把 deficit 與 attribution 混為 robust** — deficit robust（跨 loss/boundary/jackknife），attribution 僅 QLIKE 成立；任何 uniqueness / robust framing 必回 `k1133b_robustness_results.json` 重驗（K1416 教訓）。
- ⛔ **JBF 別投** — 無 banking/asset-pricing 經濟內容，desk-reject 風險；主目標 IJF。
- ⛔ **本文 GAS = Generalized Autoregressive Score，非 blockchain gas fee**；"negative" = negative-result methodology paper（勿被檔名 `btc-gas-negative` 誤導）。
- ⛔ **不整檔讀** `feed.json` / `knowledge.json`（用 grep / jq / 單檔）。

---

## 進度日誌

```
2026-07-11 | Fable deep review | 深審完成（conditional GO），待執行 P0 | f913ed68c
```

---

## 接續提示詞

讀 `paper/btc-gas-negative/EXECUTION.md` 後，從 **P0-1** 開始（本篇是 pre-draft：只有 markdown、無 .tex / reproduce.py，最終要走 markdown → LaTeX body 建置 + reproduce.py + 標題絕對化改）。**首要動作 = §5/§8/abstract/標題對 robustness JSON 重寫**：先刪 `body_v1.md:361` tight-basin 捏造句（改引真實 `multistart_dispersion.aggregate`），再把 §8 由「planned」改為引用 2026-06-29 已落地的 `k1133b_robustness_results.json` 真數字（deficit 跨三 loss robust -4.03/-5.14/-6.02、attribution 僅 QLIKE 成立、GED recover-to-parity t=-1.23、alt-dist refit-252 下 M4 vs M1 t=-2.57），並把標題/摘要降級為 QLIKE-conditional attribution，完整清單見上方 P0-1。每項改動的來源數字**先讀 `k1133b_robustness_results.json` / `k1133b_results.json` 驗證再寫，不臆造**。P0-2（snapshot + forecast persist + reproduce.py）、P0-3（pre-registration 日期降級）可與 P0-1 平行。markdown → .tex 轉換與所有方法論決策**在主線程進行**（不丟 background agent 改 .tex，paper-workflow 硬規則）；P0 全部完成前維持禁轉 .tex。
