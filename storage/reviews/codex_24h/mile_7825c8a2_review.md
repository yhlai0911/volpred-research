# Codex 24h Review — mile_7825c8a2 (K1396)

- **Article**: 只贏一點點，很多時候還不能算模型真的比較強
- **Draft source**: `/tmp/mile_7825c8a2.md` extracted from `storage/reports/feed.json`
- **Task**: `paper_review_mile_7825c8a2`
- **Reviewed**: 2026-06-03 台灣時間
- **Reviewer**: Codex CLI
- **Verdict**: **CONDITIONAL_PASS**

## Summary

這篇的核心教育點是對的：`K1396` 的三模型比較確實呈現「點估計有排名，但沒有任何一組差距跨過 Harvey `|t| > 3` 門檻」。文中的平均 QLIKE、三組 DM 值、`1.4%` 這個小幅領先口徑，都能和實驗結果對上。

不過 source-code review 後有一個需要補的限制：`K1396` 裡的 A4f OOS path 並不是完整遞迴 forecast，而是在每個 refit boundary 用 steady-state `g` 近似。這不會推翻文章「小幅領先不能當 definitive victory」的主結論，因為文章本來就偏保守；但如果要說成三模型完整公平 horse race，仍需加一句方法限制。

## Numeric verification

下列主數字與 `experiments/k1396/k1396_results.json` 一致：

| Draft line | Claim | Source | Match |
|---|---|---|---|
| 17-19 | 1.561 / 1.539 / 1.523 | `mean_qlike.HAR/A4f/HAR_VIX` | ✓ |
| 23 | 較新版本比老方法好約 1.4% | `(1.56115 - 1.53895) / 1.56115 ≈ 1.42%` | ✓ |
| 33-35 | 0.87 / -0.88 / -2.60 | `dm_tests.*.t_stat` | ✓ |
| 37 | 都沒跨過嚴格門檻 | 三組 `harvey_significant = false` | ✓ |
| 71 | OOS 起點 2019-01-01、n=1866 | `configuration.oos_start`, `sample_sizes.n_oos` | ✓ |

## Findings

1. **Main anti-overclaim message is correct and source-supported** — `/tmp/mile_7825c8a2.md:27-39,51-65`
   這篇最重要的句子其實是對的：有排名，不等於已經贏到足以當成結論。  
   `K1396` 的三組 DM 統計量分別是 `+0.866`, `-0.877`, `-2.604`，全部都未達 Harvey `|t| > 3.0`。文中沒有把 `p=0.009` 那組 conventional significance 說成 publication-grade superiority，這點比很多 reader-facing 文章更誠實。

2. **Article should disclose the A4f approximation if it wants to frame this as a clean horse race** — `experiments/k1396/k1396.py:313-318`, `/tmp/mile_7825c8a2.md:9-10,31-35`
   script 明寫：A4f forecast 在 OOS 使用的是 `steady-state g` 近似，而不是沿著 IS terminal state 做完整遞迴：
   - `# Note: this uses steady-state g; a proper recursion would continue from IS`
   - `# For the refit boundary, steady-state g ≈ unconditional mean`
   
   所以這個 benchmark 比較可以支撐「目前這版 K1396 下，差距不足以下重話」，但不宜被理解成最終、無近似的 definitive horse race。文章現有口氣已偏保守，因此我不判 FAIL；但建議在註腳補一句方法限制。

3. **Lookahead audit is clean** — `experiments/k1396/k1396.py:282-289`
   HAR forecast 用的是 `r2[t-1]`, `mean(r2[t-5:t])`, `mean(r2[t-22:t])`, `vix_sq[t-1]`，沒有把當日 target 洩漏進 forecast。  
   A4f 也用 `vix_vals[t-1]` 進入 `tau_t`，沒有 same-day VIX lookahead。這篇文章在 lookahead 維度可以過。

4. **One wording nuance to keep honest: “真的拉開了” should remain tied to this protocol, not all possible protocols** — `/tmp/mile_7825c8a2.md:53`
   這句本身沒錯，但若後續要重發或改稿，建議補成「在這個 protocol 下還不足以說真的拉開了」。因為 `K1396` 本身就有一個近似說明，而且同系列比較曾有不同 proxy / 路徑下的數值差異。

## Lookahead audit

- PASS — HAR/HAR-VIX 1-step forecast 全部使用 lagged RV/VIX features，見 [k1396.py](../../experiments/k1396/k1396.py:282)。
- PASS — A4f `tau_t` 使用 `vix_vals[t - 1]`，沒有 same-day VIX 洩漏，見 [k1396.py](../../experiments/k1396/k1396.py:291)。

## Recommended fixes

1. 在文末註腳補一句：`此比較採用 K1396 的同一套 OOS protocol；其中 A4f 路徑使用 steady-state g 近似，因此結論宜解讀為「未見穩健 superiority」，而不是最終定案。`
2. 若要讓 line 53 更嚴謹，可改成：`目前這個 protocol 下看到的排名差距，還不足以讓你很有把握地說誰真的拉開了。`
