# PASS

審查對象：frozen commit `89644f548adac795ed28e4d336bc74ad6bc13585`。所有受審 bytes 均直接取自該 commit；未採信目前不同的 HEAD 或既有未追蹤 `post_run_review.md`，亦未修改任何檔案。

## 1. Lookahead / origin / ledger

- HAR feature 明確 `shift(1)`；origin `t` 的訓練資料止於 `t-1`。
- EWMA 使用 squared return 的 `shift(1)`。
- GJR refit 使用 `returns[start:origin]`；非 refit recursion 只加入 `return[t-1]`。
- Proxy bias、leave-one-out residual weights 均用 `[t-500,t)`；當期 proxy 只構成評分 target。
- 各 target/model 的 scale calibration 僅用過去 actual/forecast pairs。
- Eligibility 在 calibration 前建立，只依 target validity 與 lagged model inputs；input available 但 raw forecast 無效會 `RuntimeError`，不會以 estimator failure 縮 ledger。Calibrated forecast 缺口也 fail closed。
- 2,048 candidates 中：invalid target 8、HAR input-unavailable 25、重疊 1，故共同 ledger 為 `2048-(8+25-1)=2016`。GJR/EWMA input exclusion 均為 0。
- HAR exclusion indices hash 獨立重算為 `03d8a8fec3dd1f999aa5fe0699725c16ba097a1770d5daef2b1f4a33a1abfff9`。
- 六 targets、三模型的 `n_oos` 全為 2,016，共用 2018-02-01 至 2026-07-14 的同一 ledger。

## 2. Data provenance

獨立逐檔重讀 live raw archive：

- Cache 引用檔：3,548。
- Source directory：3,549。
- 3,548/3,548 的 size 與 SHA-256 均吻合；missing=0、drift=0。
- 唯一 extra：`Daily_2026_07_15TX.csv`。
- Cache 日期仍止於 2026-07-14，因此 extra 未進 proxy cache、canonical join 或 evaluation ledger。
- Byte inventory 重算：`e2cdad08c98a13c0c789e2b2719a969c7e8489ee56a8f276e7657e23b38ef554`，吻合。
- Size/mtime inventory 重算：`56ea4a0aa4ee4bfacab1e7b286235c20c5439f29f1189d768937cb9a8ceb22f0`，吻合。
- Cache SHA-256：`9413478c3151b52839c9c81e615e94b613591774d3bc616fbe8016fbaffec46f`。
- Canonical RV SHA-256：`662409120515ff5404566c0cc3ae08508c26101957d6dcc461903bc66677a692`。
- Cache/canonical one-to-one join：3,548/3,548；contract mismatch=0，RV5 最大差 `1.3877787807814457e-16`，day-return 最大差 0。
- Collector、experiment、MCS、evaluation code hashes均與 results 記錄及 frozen bytes 相符。

## 3. Statistics

- QLIKE 為 `actual/predicted - log(actual/predicted) - 1`；evaluation gate 已先要求 actual/forecast 有限且正值，pointwise helper 的數值 floor 不影響本次樣本。
- DM 確實呼叫 repo canonical Newey–West HAC helper，`h=1` 仍有至少 lag 1 的 automatic bandwidth；沒有誤稱 HLN correction。
- 所有 `harvey_abs_t_gt_3` flags 均與實際 `abs(t_stat)>3` 一致。
- MCS 使用 HLN `T_R` variant、stationary bootstrap、alpha=0.10、1,000 reps、seed=42。
- 六個 full-OOS targets 的點估計 winner 與 MCS 均為 singleton `{HAR_RV5}`，足以依預註冊規則推出 `PROXY_ROBUST_STATISTICAL_RANKING`。
- Early split 的兩次 elimination p-value 均為 `0.093`：在 10% 門檻下為 singleton，但若改用 5% 門檻，第一輪即不會淘汰。README 已明確揭露此敏感性。
- Early HAR-vs-GJR DM `t=-2.861` 未通過 Harvey screen；README 只宣稱 full-OOS 的 `-4.63/-4.24` 通過，沒有把 half-sample 結果過度升格。

## 4. Independent recomputation

- JSON strict parse 成功；315 個浮點值全部 finite，無 `NaN`、Infinity 或非標準 JSON constant。
- Ledger：2,016 個唯一、遞增日期。
- Ledger hash 重算：`8d778f2407d606cbee63a903412dcc4527e50baeb83a141762eeb12266df75d6`，吻合。
- 六 targets 的 QLIKE 排名重算皆為 `HAR_RV5 < EWMA_R2 < GJR_GARCH`。
- Consensus QLIKE：
  - HAR `0.183917562174689`
  - EWMA `0.240543279183831`
  - GJR `0.259311013065063`
- HAR relative reduction：對 EWMA `23.540760399%`；對 GJR `29.074527148%`，吻合 README 的 23.5%/29.1%。
- Split counts 依 ledger 日期重算：early=1,020、late=996，合計2,016，吻合 JSON。
- MCS model partitions、p-value ranges與 survivor/elimination sets均自洽。

## 5. Artifact / prose

- README 的 raw/OOS 期間、樣本數、ledger hash、exclusion arithmetic、QLIKE、DM statistics、MCS sets及限制均與 JSON 一致。
- 圖表 SHA 與 template 相符；實際檢視確認六組 target、三模型順序、QLIKE 軸、共同 ledger 註解與 singleton MCS 註解均正確。`Day r²` 的較大 QLIKE 使用同一尺度呈現，沒有錯標。
- README 與 limitations 明確限定為 observed-proxy robustness；沒有宣稱 consensus 是 latent integrated variance、HAR 是 latent-IV 全域最優、或提出因果/交易結論。

## 6. Tests / gate

- 在 frozen-identical bytes 上直接執行五項純函式測試，全部通過：RV grid endpoints、PIT consensus/scale、HAR origin invariance、GJR refit/non-refit alignment、common-ledger/fail-closed behavior。
- 完整 pytest collection 與 `experiment_gates run` 因 sandbox 沒有任何 writable temp/Matplotlib cache directory 而中止；這些中止未被當作 PASS 證據。需要 `tmp_path` 的 mutation test亦未假報成功；其核心 raw-byte條件改以真實3,548檔逐檔核驗。
- `verdict-template` 可唯讀重生六檔 claim surface，且其 hash map 與 committed template逐鍵相等。
- 六個 `reviewed_sha256` 均與 frozen bytes完全吻合；無 hash drift、方法 blocker、數字不一致或過度宣稱。

```VERDICT_JSON
{
  "kid": "k1704",
  "verdict": "PASS",
  "reviewer": "codex/gpt-5 independent K1704 post-run review",
  "reviewed_at": "2026-07-16T05:56:19Z",
  "reviewed_commit": "89644f548adac795ed28e4d336bc74ad6bc13585",
  "review_artifact": "post_run_review.md",
  "blocking_defects": [],
  "reviewed_sha256": {
    "K1704.py": "033914650d6baa6684be661b778e91f9f749dac0f8caf6d035230d8abab83114",
    "K1704_charts.py": "32829da7b7c522699d337a44572575c09931218818c3f7f7feb6ede1873c00bd",
    "K1704_qlike_by_proxy.png": "3137abbd9709d108c69fd212897d3a7a147ff524fdb7e825b7f77334aaa43aa5",
    "K1704_results.json": "a412e7969f76879a4565a01b4713f2d270f3406505d38a7fd98c2921da5bbb06",
    "README.md": "ab0a1c6c342410e8031bb539ee55dd9c79b4ab23104d0ba150a647e7ab0f3080",
    "test_K1704.py": "26e9a72d834d82b73b2fcc1e0bf91af020c27c90a31bbf5c6217dc296ef2b5d4"
  }
}
```
