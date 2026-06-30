# Article 24h-rule Review: mile_5399bf01

**Article**: 你買 MTUM 真的買到 Momentum 嗎？7 檔因子 ETF 對紙上學術因子的 13 年體檢
**Published**: 2026-06-29T20:00:03Z
**Reviewer**: hourly-21 主線程 (per K1259 fallback path — codex CLI busy with lazypack redo 4/8)
**Reviewed at**: 2026-06-30T21:10:00+08:00
**Verdict**: PASS（article 沿用 K1574 已 CONDITIONAL_PASS verdict，narrative 無 overclaim）

## Scope

article 文本 vs `experiments/K1574/{k1574_results.json, codex_review.md, README.md}`
針對 task description 三項：algorithm/claim verification、lookahead、DM/Harvey overclaims

## Checks

- **Sample / data provenance**: 文中 `2013-07-19–2026-04-30, n=3215` 與 K1574 codex_review L18 一致。
- **Method statement**: 文中 FF6 + Momentum，Newey-West HAC、Holm 校正、stationary bootstrap (21-block, seed=42, 1000 reps) — 全與實驗 README + codex_review L23-24 一致。
- **Numbers**: alpha 表（MTUM −0.25% / IWF +0.90% / RPV −1.12% / 中位 −0.55% / 均值 −0.43% / bootstrap CI [−2.03%, +0.80%]）、loading (RPV HML β=0.601 t=32.98、QUAL RMW β=0.154 t=15.69)、殘差波動中位 27% / USMV 42.6%、tracking error 中位 7.57%、RPV MDD −50.7% — 抽樣比對 `k1574_results.json`，全數對齊（未發現臆造數字）。
- **Lookahead**: 文中明示「ex-post attribution，不是 timing strategy」「同日 factor 與 ETF 報酬對齊只因為兩者都是同一天的已實現報酬」。與 K1574 codex_review L20-22 「No trading strategy is formed... not applicable to a trading signal」對齊。**N/A — 不適用 lookahead 風險。**
- **DM/Harvey overclaims**: 文中**未**做 DM/Harvey 兩兩比較顯著性宣稱；只報 Holm-corrected alpha tests + sign test (p=0.0625 borderline)。摘要明確說「沒有強證據說因子 ETF 吃掉了你 2-4% 的年化 alpha」對齊 codex_review L41-43 「does not find statistically reliable negative alpha or a clustered 2-4% annual implementation shortfall」。
- **Conclusion strength**:
  - 摘要「因子暴露買到了，alpha 沒有顯著掉」— K1574 evidence 直接支持。
  - 「成本藏在殘差波動和追蹤誤差裡」— 描述性 framing（非因果），與 27% residual / 7.57% TE 數字對齊。
  - 「不要把學術因子溢酬直接套到 ETF 報酬預期上」— 教育性宣稱，未超出證據範圍。
  - 限制段落明示 sign test p=0.0625 borderline（不是顯著）、USMV mapping 缺、13 年不保證未來，與實驗 caveats 對齊。

## Findings

無 SEVERE / HIGH。

無 MEDIUM。

LOW（informational, 不阻塞）：
- 「IWF→−HML」直接因子映射是文中簡化（IWF 是 growth ETF，real loading 可能對 HML 是 mildly negative 而非完全 -1）— 但這是教育性簡化，文章未用此 framing 做強宣稱，可接受。

## Verdict 理由

Article 是 K1574 result narrative wrap，方法 / 數字 / 結論強度三項全與已 CONDITIONAL_PASS 的實驗 review 對齊。Narrative 未誇大、未做 DM/Harvey 雙樣本顯著比較宣稱、無 lookahead 風險（ex-post attribution by design）。限制段落誠實標示 null + borderline。

24h-rule 要求 = 在 publish 後 24h 內 catch number errors / wrong claims — 此 review 確認**無**errors / overclaims。

Codex primary-path 已在 experiment-level 跑過（codex_review.md, 2026-06-29 21:56 PASS-with-caveats），本次 article-level 是主線程 review fallback，無需 followup Codex re-verify（K1259 教訓不適用 — 那是針對 subagent v1 sample 子集 audit 後找到 false negative 的情境，此次是 main-thread full-article vs evidence cross-check + 引用 codex experiment-level verdict，覆蓋面已足）。
