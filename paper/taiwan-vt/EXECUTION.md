# taiwan-vt — 執行追蹤（EXECUTION）

> 論文修訂執行檔。來源裁決：`review_history/fable_deep_review_20260711/README.md`（Fable 深審，2026-07-11）。
> 本檔是「深審計畫 → 可勾稽待辦」的落地層；勾選狀態代表實際完成度，不是計畫本身。

## 0. 狀態徽章（BADGE）

`paper: taiwan-vt` ｜ `target: PBFJ` ｜ `stage: revision (do_not_advance)` ｜ `verdict: 3/5 Major Revision`

| Gate | 狀態 |
|---|---|
| **P0**（submission blockers） | 🟥 **TODO**（0/6） |
| **P1**（統計加固） | ⬜ TODO（0/6） |
| **P2**（PBFJ 投稿準備） | ⬜ TODO（0/5） |
| **DoD**（可投稿定義） | ❌ 不符 |
| **Go / No-Go** | **No-Go**（現狀）→ P0 清完 + 1 輪 review cycle → Conditional Go |

canonical tex = `main_v3.tex`（`\input{body_v3}`）→ `main_v3.pdf`（49pp，2026-07-06 編譯）。

---

## 1. 一句話現況

內容有真貢獻（diversification amplification + VT 移植台灣 + VIX-proxy 校準），底層實驗數字大體驗證乾淨（reproduce gate 96.7% traceable、0 MISMATCH），PBFJ 適配度高——**但現狀不可投稿**：6 個 submission blocker 未動，其中 TWII γ=0.272 headline 已被 provenance 實驗證偽（可復現 0.105–0.109），修正會**反轉**跨國槓桿敘事，且需 owner sign-off。這是「誠實修稿 + 敘事校正」，不是「研究垮掉」。

---

## 2. Definition of Done（可投稿門檻，全部達成才 Conditional Go）

- [ ] TWII γ headline 已替換為 canonical 0.105/0.109（**owner 已 sign-off**）+ 跨國比較句全部重寫（TAIEX 絕對 γ 低於 SPY；保留 amplification ratio 4.2×>2.8× 點估計 + CI 含 2.8 的誠實揭露）
- [ ] Table 2 rolling block 以 calendar-aligned snapshot 重建 + 0056 段落敘事重寫（0.310 = 最高，「conservative bias」論證作廢）
- [ ] L343 / L387 兩處 comment-swallow 修復；`pdftotext` 確認被吞正文（「economically indistinguishable」「The key insight」）已渲染出現在 PDF
- [ ] §7 樣本窗口矛盾消除（L439 "2008–2026" → "2019–2026"）
- [ ] GARCH-ceiling 全稱宣稱 + U.S.-side SSVS 對比措辭降級
- [ ] `reproduce.py` 重跑 0 MISMATCH、`alert_level=green`；`paper-update` 已同步平台
- [ ] 一輪完整 `paper-review-cycle` 收斂（latex-academic-reviewer + citation-verifier）
- [ ] `journal-review` PBFJ compliance scrub 通過（author = Yi-Hao Lai only、無 volpred / AI / LLM 提及）

---

## 3. P0 — Submission blockers（預估 1–2 週；全部主線程論文修訂流程）

> ⚠️ P0-1 是關鍵路徑：F1 沒有繞過路徑，所有下游修訂都依賴它先落地。**必須先取得 owner sign-off。**

- ⬜ **P0-1｜TWII γ decision package → owner sign-off（F1，最重）**
  - 整理證據包（已齊）：`experiments/paper2_twii_fullsample_gamma_provenance/results.json` 重估 γ=0.1047/t=5.312；K892 corroborate full γ=0.109/t=5.62（n=7,044）、rolling w=2000 mean=0.114 / **max 僅 0.236**——0.272 在任何 documented spec 下都達不到。
  - 提請 owner 二選一：**(a) 換 canonical 0.105/0.109 + 敘事反轉重寫（推薦）**；(b) 找回 0.272 原始估計環境並補 JSON（成本高、大概率失敗）。
  - 核准後全文替換：intro（L10/L14）、Table 1（L51）、Table 2（L150）、§3.2 footnote、conclusion（L539，並修正 spec 標籤錯置——同句混用 rolling 與 full-sample 兩組數字）。
  - **跨國比較句全部重寫**：§3.1「TAIEX substantially exceeding U.S. S&P 500」方向反轉（修正後 TAIEX γ≈0.109 < SPY 0.22）；保留 amplification 故事（0.114/0.027≈4.2×，CI [2.28,6.58] 已如實含 2.8）。rolling 5.0× 句用重算值或直接刪 rolling variant。

- ⬜ **P0-2｜Table 2 rolling block 重建（F2）**
  - `experiments/paper2_taiwan_indiv_rolling_gamma` 以 **calendar-aligned snapshots 重跑**（現結果 2886 端點 2025-01 未對齊，是採納前置條件）→ Codex review → 替換 N121 遺留四列 + 平均列 + footnote ratios。
  - **0056 段落敘事重寫**：重估 0056=0.310（全場最高、高於 index），「second-highest / inclusion bias 是 conservative」整段論證翻掉。
  - 已排 follow-up 任務 `fable0711_taiwanvt_rolling_gamma`（P2 lane=agent，見進度日誌）。

- ⬜ **P0-3｜修 L343 / L387 comment-swallow（F3，本次審查新發現）**
  - 兩處 mid-line `% source:` 之後同一物理行接了正文，`%` 之後全部從未渲染（`pdftotext` 驗證：`economically indistinguishable`、`20.1 percentage point`、`The key insight` 皆 0 hits）。
  - prose 移出註解（`% source` 換行放行尾）；被吞文字引用的 `\ref{sec:results}` label 全文不存在，改指 §4.1 或刪除。
  - xelatex 後 `pdftotext` 驗證被吞段落確實渲染。

- ⬜ **P0-4｜§7 樣本窗口矛盾（F4）**
  - §7.5（L439）"2008–2026" 與 §7.2（L422）"2019–2026" 衝突；n=1,756 ≈ 7 年只能是 2019–2026（k896 n_total=1756）→ L439 改 "2019–2026"。

- ⬜ **P0-5｜措辭降級兩處（F5 / F6）**
  - §4.2「all ... enhancements」（K472 footnote）→ 明示「所測試的三種 daily-frequency GARCH-X regressors 皆失敗」（K852 Realized-GARCH、K886 PRG_Extended DM t=5.27 是自家 package 反例；可考慮把 intraday-RV 例外寫進 footnote，反而強化「cross-market channel 才是增量資訊來源」）。
  - §3.3（L258）U.S.-side SSVS 對比：表注已誠實標 untraceable/pending，正文仍以事實口吻陳述——降為 qualitative + 標 pending。

- ⬜ **P0-6｜P0 收尾**
  - xelatex → `reproduce.py` 重跑（目標維持 0 MISMATCH）→ `uv run volpred ops paper-update --paper-id taiwan-vt`。

---

## 4. P1 — 統計加固（2–4 週，可與 P0 平行派工）

- ⬜ **P1-7｜DM/HAC lag 盲區補掃**：`audit_dm_hac_lag.py` 掃描範圍擴到 `paper/*/experiments/**`（本篇 17 個本地 K 腳本逃過凍結 baseline 掃描）；重驗三個 DM claim（GJR vs GARCH p=0.86、import growth p=0.043、VIX+leading combo p=0.0005）——**先量 loss differential acf 再判方向**（k621 教訓：null 也可能翻顯著；h=1 用 lag=0 等於無 HAC）。
- ⬜ **P1-8｜§5 macro 補實驗**：27-indicator sweep 落地成 results JSON（或把 §5.1/§5.2 未溯源數字降級為 qualitative）；import growth p=0.043 用 canonical bandwidth 重跑後決定去留。
- ⬜ **P1-9｜Appendix TZ 補 K1176 binding**（c2c Sharpe 1.915、TW+JP 2.192、五市場 t 值全列在 untraceable gaps）。
- ⬜ **P1-10｜legacy 數字統一**：4.3× 統一為 K1370 matched-sample pairing 並給算式（M1）+ GJR VT 1.074/1.084 選定一處引用（M2）+ SPY γ row canonical 化（M3，K892 full 0.2197/6.94）+ TWII 天數對齊（M4，7,148 vs provenance n_prices=7,107）。
- ⬜ **P1-11｜Steiger Z=16.2 HAC 敏感度**（M5，daily overlapping rank 無 HAC，Z 幾乎必然高估；方向 0.595>0.459 大概率存活）+ §4.3「Sharpe(K·r)=Sharpe(r)」在 cap 下不成立、12/VIX common-period Sharpe 實際≈8.63/VIX，「outperforms」改寫為 risk/MDD 語言（M6）。
- ⬜ **P1-12｜未驗證 uniqueness 溯源**：skewed-t「6/6 perfect pass」+ cross-asset panel 實驗溯源；未溯源則降級。

---

## 5. P2 — PBFJ 投稿準備（P0 + P1 綠後）

- ⬜ **P2-13｜package 衛生**：`reproduce.py` rebind body_v3（pipeline 已立案 followup）+ README.md / experiments.md 去 stale（README status 段停在 2026-05-23 的 H1/H2，其實已清）。
- ⬜ **P2-14｜完整 review cycle**：`paper-review-cycle` 一輪（latex-academic-reviewer + citation-verifier，經 codex exec）→ 歸檔 `review_history/v3`。
- ⬜ **P2-15｜journal-review PBFJ profile**：format check、highlights、cover letter、compliance scrub（author = Yi-Hao Lai only、無 volpred / AI 提及）。
- ⬜ **P2-16｜時程**：P0（1–2 週）→ P1 平行收斂（+2 週）→ review cycle 1–2 輪（+1–2 週）→ PBFJ 投稿。目標 **2026-08 中下旬**。
- ⬜ **P2-17｜流程固化（PDCA）**：(a) mid-line comment-swallow 偵測併入 reproduce/paper-update gate（pdftotext 抽查 mid-line `%` 後含句號+大寫的 tail）；(b) `audit_dm_hac_lag.py` 掃描範圍擴 `paper/*/experiments`（class-level 修，其他論文同受益）。

---

## 6. 禁止事項（本篇特有 — 修稿踩雷清單）

- **別再沿用 TWII γ=0.272 / t=3.18 舊值**：已被 provenance 證偽為 0.105–0.109；K892 rolling max 僅 0.236，任何 documented spec 都達不到 0.272。凡引用 0.272 的句子（intro、Table 1/2、§3.2 footnote、conclusion）一律待 owner sign-off 後替換。
- **別再寫「TAIEX index-level 槓桿效應絕對值強於 SPY」**：修正後 TAIEX γ≈0.109 < SPY 0.22，方向已反轉；只保留 amplification ratio（4.2×>美國 2.8× 點估計 + CI 含 2.8 的誠實揭露），不可宣稱台灣槓桿絕對值更強。
- **別在 mid-line 留 `% source:` 後接正文**：`%` 之後整段會被吞、PDF 靜默缺文（L343/L387 教訓）。`% source` 註解一律換行放行尾；改完必 `pdftotext` 驗證。
- **uniqueness / all-claims 已降級的敘事勿復用**：GARCH-ceiling「all enhancements」不可再用全稱（K852/K886 自家反例）；U.S.-side SSVS 對比不可用事實口吻（未溯源）；0056「second-highest / conservative bias」整套敘事作廢（重估 0.310 = 最高）。
- **Table 2 rolling 採納前必 calendar-aligned**：現有可復現結果 2886 snapshot 端點 2025-01 未對齊，直接採納會再引入不可復現值。
- **不手改 JSON、不 widen tolerance 湊 reproduce green**（研究誠實 §1/§6）；數字不符走「修腳本 / 修論文 / 明記 errata」三選一，絕不偽造。

---

## 7. 進度日誌

```
2026-07-11 | Fable deep review | 深審完成，待執行 P0 | f913ed68c
```

---

## 8. 接續提示詞

> 讀 `paper/taiwan-vt/EXECUTION.md` 與 `paper/taiwan-vt/review_history/fable_deep_review_20260711/README.md` §5 後，從 **P0-1（TWII γ decision package → owner sign-off）** 開始：
>
> 1. 這是**需 owner 過目的決策點**——先備妥 decision email（兩選項：(a) 換 canonical 0.105/0.109 + 跨國敘事反轉重寫〔推薦〕；(b) 找回 0.272 原始估計環境補 JSON〔成本高、大概率失敗〕），附證據包（`experiments/paper2_twii_fullsample_gamma_provenance/results.json` + K892 rolling max 0.236），寄 `send-alert` 請 owner sign-off。**未取得 sign-off 前不動 γ headline**（F1 沒有繞過路徑，所有下游修訂都卡在它）。
> 2. sign-off 後：全文替換 0.272 → canonical（intro L10/L14、Table 1 L51、Table 2 L150、§3.2 footnote、conclusion L539）+ 跨國比較句重寫 + 修 conclusion spec 標籤錯置。
> 3. 接著平行推進 P0-3（comment-swallow，不需 owner）、P0-4（§7 窗口）、P0-5（措辭降級），P0-2（rolling block）走 follow-up agent 任務 `fable0711_taiwanvt_rolling_gamma`（calendar-aligned 重跑）。
> 4. P0 六項清完 → xelatex → `reproduce.py` 0 MISMATCH → `paper-update --paper-id taiwan-vt` → 更新本檔 BADGE / DoD 勾選 + 進度日誌加一行。

### 進度更新 2026-07-13
- 2026-07-13 | **P0-1 TWII γ 全文替換（owner sign-off 2026-07-12 已取得）**：0.272/3.18 全數退役 → canonical 全樣本 0.105/5.31（provenance 實驗，K892 0.109/5.62 佐證）；tab:summary_stats 與 tab:gamma 兩表列 + intro/results/conclusion 三處 prose；跨國敘事誠實反轉（TAIEX 顯著但點估計低於 SPY；賣點改 amplification）；rolling 平均 0.054→0.032、0.060→0.051（K1697）；main_v3.pdf 49pp 0 undefined
- P0-2 rolling block 已由 K1697 aligned 重估支撐（前段 c567e7889 已載入 0056 反轉；本次補平均列與表注 canonical 語句）
