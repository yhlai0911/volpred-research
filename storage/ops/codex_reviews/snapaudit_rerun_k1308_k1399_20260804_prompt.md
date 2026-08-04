# 獨立審查請求：K1308 / K1399 去重後統計量重跑

你是獨立審查者。這是一次**更正性重跑**：兩篇已發佈文章引用的數字建立在含重複列的樣本上，
本次重跑產出更正值供 erratum 填空。**你的裁決決定這些數字能不能寫進 knowledge.json。**

請以懷疑的立場審。你的任務不是確認它看起來合理，而是找出它哪裡可能錯。

## 凍結的位元（審查對象，sha256 已釘死）

| 檔案 | sha256 |
|---|---|
| `experiments/snapaudit_rerun_k1308_k1399_20260804/rerun_dedup_corrections.py` | `da2873ea4192f6403416c90fe06352f9dde660b951c91568ce744f6e9bb88236` |
| `experiments/snapaudit_rerun_k1308_k1399_20260804/snapaudit_rerun_k1308_k1399_20260804_results.json` | `7200a746faaa7e8c024f04ac55f50b69a514ece2f2e97f2f208492705f5137dc` |
| `experiments/k1308/k1308.py` | `11d2eeb190996227017d80445e9a28fdd683526a150667b145c1415295836b0e` |
| `experiments/k1308/k1308_results.json` | `cf329ba186fbc80d36cee834dda8fb0114f6b7e53b4d858d8fcdfc4bdc0b2f01` |
| `experiments/k1399/k1399_vix_decomp.py` | `d0b88a67830d336ac5abb8b570ecb6d66dade4c0e9cd02f094e660cef4455608` |
| `experiments/k1399/k1399_vix_decomp_results.json` | `d5ef6e86c60caa554a01de17dda92221aee4331faa3c911c983d6582388057ee` |

背景請讀 `experiments/snapaudit_rerun_k1308_k1399_20260804/README.md` 與上游
`experiments/snapaudit_unmeasured_20260728/README.md`。

## 事件

`scripts/refresh_paper_snapshots.py` 併發重複 append，使 9 個 canonical CSV 各含 10 個重複交易日
（2026-05-04 ~ 2026-05-15）。污染 rev `d36a418cb`，修復 rev `00b07f07f`。

## 本次重跑宣稱的結果

- **K1308**：n 119→109（9.17% 暴露）；mean 1.5737→1.5237、最近 30 天 2.0643→1.8716、
  CV 0.204→0.1874、vs K1181 t 6.2219→4.8669。13 個欄位變動，**五項 verdict 全不翻**（仍 UNSTABLE）。
- **K1399**：IS n 3522 **不變**、OOS n 1865→1855；水準 DM t −4.40→−4.90、MA5 −3.53→−3.97、
  T vs L +3.47→+3.67、All vs L −0.40(p=0.69)→−0.25(p=0.80)。31 個欄位變動，
  **H1..H5、QLIKE 排序、所有 harvey_pass 全不翻**。

## 請逐項裁決（每項給 PASS / FAIL / UNCERTAIN + 理由）

1. **`keep=` 的任意性**：`load_vix()` 新加的 dedup guard 用 `keep="last"`。腳本宣稱已檢查此選擇
   不影響結果（`vintage_checks.*.duplicate_pairs_value_identical=true`、
   `dedup_keep_reproduces_clean_vintage` 兩者皆 true）。**請自行驗證這個宣稱**，
   不要採信 results.json 的自陳 —— 直接從 `git show d36a418cb:<csv>` 取污染 vintage 比對。
   對照組是 k1592：那裡的重複列帶偽造零報酬，`keep=` 有實質後果。
2. **vintage 等價性檢查是否站得住**：腳本比對工作區 CSV 與 clean rev `00b07f07f`，
   但**限縮到該實驗實際讀取的欄位**（k1308: date+vix_close；k1399: date+spy_adj_close+vix_close）。
   這個限縮是合理的必要條件，還是把真正的差異掃到地毯下？有沒有被讀取但未列入比對的欄位？
3. **窗口 pin 是否正確**：`K1308_PERIOD_END=2026-05-20` 取自 stored `overall_stats.period`，
   `K1399_OOS_END=2026-05-19` 取自 stored `data_period.oos_end`。這兩個端點是否確實還原了
   已發佈 vintage 的取樣範圍？特別注意 k1308 的窗口是從 VIXTWN 自身 min/max 推導，
   pin 只截了上界 —— 下界（2025-12-01）是否可能因 VIXTWN 檔案自身變動而漂移？
4. **K1399 的 IS n 不變是否可信**：宣稱污染日期（2026-05）落在 IS 窗口（至 2018-12-31）之外
   所以 IS 不受影響。但 `is_r2` 在 results.json 裡確實有極微變動（第 15 位小數）。
   這是浮點噪音，還是 IS 樣本其實動了？
5. **「去重後 DM 普遍更顯著」的解釋是否成立**：README 宣稱重複列稀釋了損失差序列的變異估計，
   所以污染讓結果看起來更弱。這個機制在 HLN-corrected DM + NW bandwidth=T^(1/3) 下是否
   真的成立？重複列同時影響分子（平均損失差）與分母（HAC 變異）與 T 本身，方向是否真的確定？
6. **判定不翻的宣稱是否經得起檢查**：有沒有任何統計量在更正後**跨過**了它的決策門檻
   （Harvey |t|>3、p<0.05、CV≤0.15、mean 落在 [1.30,1.50]）而被漏報？請自己從 results.json
   逐一核對，不要採信 README 的表格。
7. **是否有 lookahead 或其他方法論退化**：重跑只加了 dedup 與窗口 pin，未動 IS/OOS 切分與
   `shift` 慣例。請確認這個宣稱屬實，兩個腳本的 diff 沒有引入其他行為改變。
8. **erratum_fill_ins 是否可直接引用**：`snapaudit_rerun_..._results.json` 的 `erratum_fill_ins`
   是兩篇文章的填空來源。其中 `prior_baseline`（1.3906）被判定為「不受污染影響、erratum 不應動」，
   因為它是 K1181 寫死的常數。這個判定對嗎？

## 輸出格式

先寫散文分析，**最後**附一個 JSON block（供機器抽取，不要放在中間）：

```json
{
  "verdict": "PASS | CONDITIONAL_PASS | FAIL",
  "items": [{"id": 1, "verdict": "PASS|FAIL|UNCERTAIN", "reason": "..."}],
  "blocking_issues": ["..."],
  "safe_to_write_knowledge": true,
  "safe_to_quote_in_erratum": true
}
```

`safe_to_write_knowledge=false` 時請明說缺什麼證據。寧可 FAIL 也不要放行不確定的數字 ——
這些值會直接印在對外的更正啟事上。
