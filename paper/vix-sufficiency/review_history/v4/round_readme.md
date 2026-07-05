# vix-sufficiency — Review Round v4

**Paper**: "Can Anything Beat VIX? A Systematic Out-of-Sample Evaluation of Thirteen Signal Families…"
**Body reviewed**: `main_v4.tex`（1294 行，2026-07-01 修訂）
**Round date**: 2026-07-06（台灣時間）
**Reviewer**: Codex CLI 0.142.3（latex-academic-reviewer rubric，200K tokens），primary path
**Secondary (agy) 二審**: 失敗（macOS 缺 `timeout` 指令，wrapper abort）— 本輪僅 codex primary；下輪補 agy（改 `gtimeout` 或無 timeout）

## Verdict：**REJECT**（投稿前需 major revision）

非因 null result 不可發，而是核心 inference、publication timing、claim-evidence matching 有會被 desk-reject / referee 否決的硬傷。最適 target：**IJF 第一 / JBF 第二**（修成短 null note 可投 FRL）；JFE/RFS 目前貢獻不足。

## SEVERE（3；投稿 blocker）

1. **Table 6 與自家來源實驗 K752 直接衝突（研究誠實 critical）**
   - 論文 Table 6（行 640-649）報三個 competing signals 各時期 Harvey pass = **0/5**，note 稱「No signal passes… in any era」+「VIX sufficiency is not an artifact of any particular market regime」。
   - 但 `experiments/k752_vix_sufficiency_eras_results.json` synthesis（行 489-490）明寫 `any_competing_signal_harvey: **true**`、`vix_sufficient_all_eras: **false**`，且有多筆 `harvey_pass: true`（行 357/370/383/473 — vol momentum 於 GFC/COVID era 通過），conclusion 亦寫「Some competing signals have era-specific value」。
   - **本機已驗證**（2026-07-06 jq/grep confirm）。論文 headline「VIX sufficient in all eras」被自家 source data 反駁。若 Table 6 用了不同 spec/era binning，須在文中明確 reconcile；否則構成 overclaim + 內部矛盾。**必修才能投稿**。

2. **Nested forecast inference 用普通 DM，缺 Clark-West 校正**
   - VIX-only vs VIX+signal 是 nested comparison（行 282/371），但主 DM 段未施用 Clark-West / West-style nested MSFE correction，也未在主段施 HLN small-sample correction。對 null-result 論文這偏向「接受 null」，是核心風險。

3. **Publication-delay / lookahead lag convention 前後不一致**
   - Table 1 note（行 197）：daily USEPU/NFCI/ANFCI = shift(2)、WLEMU/STLFSI4 = shift(1)；publication-delay table（行 340）：NFCI/ANFCI/STLFSI4 weekly = shift(2)；method 段（行 359）：Families 12/13 primary 全 shift(2)；robustness（行 851）：corrected variant 對 daily EPU 保留 shift(1)。timing convention 未鎖定 = top-tier 硬傷。
   - 另 Family 10 overnight VIX 用 `VIX_open,t`（行 240），但總規則稱所有 signal 在 t-1 close 可得（行 197/264）— forecast origin 需重寫或明示。

## MAJOR（8）

- Holm/DM/MCS family 不一致：Holm 只套 10 個 regression tests（行 388），排除 portfolio/Bitcoin/策略/allocation，但 abstract（行 48）稱「all results survive Holm-Bonferroni」。Family 12/13 raw p 顯著但 HB p=1.000（行 482）— 僅在改 directional one-sided p 才合理，表格目前混報。
- Harvey `|t|>3.0` over-attribution：方法段有「approximate conservative」緩和（行 388），但 abstract/intro（行 48/80）仍像 universal threshold。
- VaR/ES：Basel traffic-light 口徑未正式引用；5% VaR 若用 scaled threshold 不能稱 Basel standard（行 1031/1056）。GJR-GARCH(t) 未交代 Student-t unit-variance scaling（行 1048）；source `k780_tail_first_es.py:296` 直接 `t_dist.ppf` × sigma 未縮放。
- CRRA welfare overclaim：break-even 是 mean-variance CE（行 1073），但敘事轉成 drawdown insurance + 「most retail investors」（行 1105），缺 estimation uncertainty / utility CI / TC sensitivity。
- Abstract/conclusion overclaim：CV=0.33 說成「demonstrating time-invariance」（行 48）；結論推到「daily-frequency frontier exhausted」+ regulator implication（行 1133/1137）。證據最多支持「本設計與日頻收盤資訊下未發現穩健增量」。
- 「41.8% QLIKE improvement」方向錯：文中把 intraday frontier 當正結果（行 98/1021），但 `k745_results.json` 顯示 best 5-min QLIKE 0.109 > best daily 0.077，`improvement_pct = -41.8`（惡化），且 N=37 preliminary。
- Pre-specification 無 registry：「pre-specified thirteen」與「families 12-13 added in this revision」同段並存（行 74/165）— 需 timestamped frozen analysis plan。
- Citation gaps/orphans：缺 Clark-West、West、HLN、Acerbi-Szekely ES backtest、Basel traffic-light source、CBOE VIX white paper、Carr-Wu VRP、Engle-Gallo AMEM inline；`engle2006`/`bollerslev2020` 疑未 inline cite、`luo2019` 支撐偏弱（行 208/1241）。

## 已具備（無需補）

Campbell-Thompson、Patton、Harvey、Diebold-Mariano、Hansen MCS、Newey-West、Holm、Kupiec/Christoffersen citation 齊全。QLIKE 方向可救：文中 `log h + r²/h`（行 299）與 canonical `actual/predicted − log(actual/predicted) − 1` 只差 model-invariant constant，須明說等價並統一尺度。

## Top-3 投稿 blocker（給下輪 paper_body）

1. 修 Table 6 / K752 衝突（reconcile spec 或改敘事，不可 overclaim all-era sufficiency）
2. 重做 nested forecast inference（Clark-West）+ 統一 multiple-testing family
3. 鎖定 publication-delay / lag convention，逐 signal 寫清 forecast origin

## Artifacts

- `codex_latex_review.md` — Codex 全文 review
- 本檔 — round README + verdict
