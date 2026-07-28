# K1734 rev2 — H1 accept gate 與 H1 宣稱不一致（Codex primary-path FAIL 的定向修正）

## 裁決來源

`storage/ops/codex_reviews/k1734_primary_path_verdict.md` → **VERDICT: FAIL**
（job `compute-k1734-primary-path-codex-certification-review-1785248077`）。

這是 K1734 的**第一次 primary-path 審查**。先前兩個 PASS 來自 fallback reviewer
（`gemini-agy` 與 claude subagent），**兩個都沒抓到這個缺陷** —— 這正是 certification gate
堅持不以 fallback PASS 收尾的理由，不要因為「已經兩個 PASS」就輕看本裁決。

## Blocking defect（主線程已獨立複驗，可直接採信）

**H1 有兩條腿，accept gate 只測了一條。**

README / results 對 H1 的宣稱是：EM carry proxy 報酬分佈的左尾顯著比右尾厚、
**且在壓力期放大得更快**。

但 `k1734.py:354-356` 的 accept 條件是：

```python
left_tail_fatter = (desc["skew"] < 0 and boot_skew["excludes_zero"]
                    and boot_svdiff["observed"] > 0 and boot_svdiff["excludes_zero"])
```

只有 skew 與 downside-minus-upside semivariance 兩項。緊接在上面算出來的
`amp_down` / `amp_up`（ES 壓力期/平靜期放大倍數）**完全沒有進入 accept 條件**。

而 `K1734_results.json` 的 `H1_left_tail_asymmetry.verdict_primary` 是：

| 欄位 | 值 |
|---|---|
| `skew` | −0.29517596 |
| `semivar_diff` | 1.5708052e-06 |
| `downside_es_amplification` | **1.3519854** |
| `upside_es_amplification` | **1.3020383** |
| `accept` | **True** |

也就是說：README 用 **1.35× 對 1.30×** 這組**點估計**去支撐「壓力期放大得更快」，
但這組數字**沒有任何檢定**（沒有對 `amp_down − amp_up` 做 bootstrap CI，也沒有進 accept gate），
而且兩者差距極小。**未檢定的點估計差不能當成假說成立的證據** ——
這違反 AGENTS.md 研究誠實原則第 7 條（方法論必須有正式檢定，不要只看圖/看數下結論）
與第 10 條（結論強度不能超過證據）。

## 你要做的事

**先決定走 (A) 還是 (B)，並在產出裡寫明理由。兩條都誠實，不要兩邊各做一半。**

### (A) 補檢定，讓 gate 真的測到第二條腿（較有資訊量，建議優先評估）

1. 對 `amp_down − amp_up`（或等價的 ratio-of-ratios）做**與現有 bootstrap 同口徑**的
   區間估計 —— 沿用檔內既有 bootstrap 設計（同 seed、同 reps、同 block 處理），
   不要自創一套新方法。壓力期/平靜期切分沿用現有 `vix_stress_threshold`，不得為了讓結果
   好看而改門檻。
2. 把該檢定**納入 `left_tail_fatter` 的 accept 條件**，讓 gate 與 H1 的文字宣稱一致。
3. 重跑，**如實接受新結果**。

   ⚠️ **1.3520 vs 1.3020 差距很小，很可能檢定不顯著。若如此，H1 的第二條腿就是不成立**，
   你必須讓 H1 的 verdict 與 `verdicts.overall` 字串**照實改變**
   （目前 overall 是 `LEFT_TAIL_ASYMMETRY_CONFIRMED_PLUS_SMALL_OOS_LEAD_YEN_TRIGGER_REJECTED`）。
   **這是可接受、甚至是預期的結果 —— null 如實報告（原則 9）。**
   絕對禁止：放寬檢定門檻、改單雙尾口徑、換 stress 定義、或挑一個會過的變體來讓 H1 存活。

### (B) 收窄宣稱，讓文字只講 gate 真的測到的東西

1. 把 H1 的敘述在 **README、`verdicts`、`overall` 字串、以及 results 內所有相關字串**
   一律收窄為「左尾顯著比右尾厚」，**移除「壓力期放大得更快」這條腿**。
2. `downside_es_amplification` / `upside_es_amplification` 可以保留，但必須明標為
   **未檢定的描述性數字（descriptive, not tested）**，且不得出現在任何支撐 H1 的論證裡。
3. 檢查 `overall` 字串是否仍然準確。

## 一併處理

- **審查不完整**：該 verdict 檔自述「workspace read-only、無法建立檔案」而只報了這一個
  blocking defect 就停下，我在 prompt 裡要求的五個維度（lookahead / leakage / statistics /
  honesty / verdict_supported）**其餘部分沒有覆蓋**。所以修完之後仍需完整重審，
  不能把「只剩這一項」當成前提。
- 修改後 `K1734.py` 的 bytes 會變 → **必須用 run-time `finalize_experiment()` 重新產出
  `reproduce_spec.json` 與 results**，讓 `code_trace` 的 sha/size 與磁碟一致
  （AGENTS.md 2026-07-22 K1708 教訓；目前這三者是一致的 `cc8045ac…` / 44,339 B，
  不要修完後留下漂移）。
- README 每個數字都必須仍對得上它引用的 JSON 路徑（該檔宣稱 byte-traceable）。
- BH-FDR family 若因新增檢定而改變成員數，`bh_fdr` 與 README §BH-FDR 段落要同步更新，
  包含既有的 CW 單尾保守加倍處理。

## Worktree

`/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-1e5922b4-k1734`

## 產出契約

寫 `experiments/K1734/k1734_h1_gate_fix_report.json`，至少包含：

- `route`：`"A"` 或 `"B"`，與選擇理由
- `h1_second_limb`：走 A 時填檢定方法、統計量、CI、p 值與是否顯著；走 B 時填移除了哪些字串
- `verdict_change`：`verdicts.H1_accept` 與 `verdicts.overall` 修改前後的值（沒變也要寫明沒變）
- `gate_code_change`：`k1734.py` 中 accept 條件的 before/after
- `spec_refresh`：新的 `code_trace` sha256/size，並確認與 `reproduce_spec.entrypoint` 及磁碟一致
- `readme_sync`：改了哪些段落
- `status`：`READY_FOR_CODEX_REREVIEW` 或 `BLOCKED`（附原因）

完成後 **commit worktree**。

## 禁止

merge（主線程的事）；寫 `knowledge.json`（K1259）；自行 enqueue Codex；
為了讓 H1 存活而調整檢定口徑、stress 門檻或顯著水準；
把未檢定的點估計差繼續當作假說證據；force-remove worktree。

**Model**: opus / max (per model_router, experiment attempt 1 — at_ceiling=true, exhausted=false)
