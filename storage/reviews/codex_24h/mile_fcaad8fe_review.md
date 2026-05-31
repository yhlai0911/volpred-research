# Codex 24h Review — mile_fcaad8fe (K1116f)

- **Article**: 為什麼只有公債吃這套？我們把另類數據丟到三個資產，結果只有 TLT 點頭
- **Draft source**: `/tmp/mile_fcaad8fe.md`
- **Task**: `paper_review_mile_fcaad8fe`
- **Reviewed**: 2026-05-31 台灣時間
- **Reviewer**: Codex CLI
- **Verdict**: **CONDITIONAL_PASS**

## Summary

主結論基本安全：`K1116f` 確實顯示 GLD / BTC 在 PIT 下仍是 NULL，TLT 只有 `finstress` 在 `pit_shift0` 出現 `DM t≈+3.74`，但 `QLIKE` 改善只有 `+0.50%`，過不了經濟門檻。

這篇沒有明顯數字捏造，但有 2 類要修的地方：

1. 一處結論強度超過實驗本身能支持的範圍。
2. 一處文句殘留機械式措辭，會拉出 AI 味。

## Numeric verification

| Draft line | Claim | results.json / README | Match |
|---|---|---|---|
| 9-11 | GLD 沒戲、BTC 沒戲、TLT 勉強舉手 | `k1116f_results.json.asset_results` | ✓ |
| 21 | GLD finstress 約 -3 | GLD `iv_vs_finstress = -3.341 / -3.341 / -3.029` | ✓ |
| 22 | BTC 在 +1 到 +1.4 間 | BTC finstress `1.370 / 1.370 / 1.035` | ✓ |
| 23 | TLT 唯一一格 +3.74 | TLT `pit_shift0 iv_vs_finstress = +3.7434` | ✓ |
| 47 | TLT `+3.74 / +3.74 / +2.00` | TLT three variants | ✓ |
| 49 | QLIKE 改善 `+0.50% / +0.50% / +0.18%` | TLT `qlike_improvement_pct` | ✓ |
| 63 | 170 週共同 OOS | README + results | ✓ |
| 71 | sample 2018-01-12 至 2026-04-10、OOS 170 週 | README §2.1 | ✓ |

## Findings

1. **Open-question framing drifts beyond the experiment’s own conclusion** — `/tmp/mile_fcaad8fe.md:63`
文中寫「如果換成日頻 HAR-RV，或者把樣本拉到完整金融危機期間，TLT 那個 marginal signal 有沒有可能進化成真的可交易訊號，仍是 open question。」  
這句比 `K1116f` 自己的 README 更開。README 的正式口徑是：TLT 這個現象在 `magnitude`、`stability`、`kitchen-sink` 三面都 fail，並傾向把它解讀成 `regime artifact`，不是結構性 signal。比較安全的說法應該是「若改成其他頻率或更長樣本，結果可能改變，但目前沒有證據支持可交易訊號」。

2. **AI 味 / 機械措辭** — `/tmp/mile_fcaad8fe.md:17`
`每根柱子是一個 兩模型比較顯著 檢定的 t 值` 這句不自然，像編修殘留。建議直接改成「每根柱子是比較『金融壓力指數模型』和『原生 IV 模型』預測準度的 DM t 值」。

3. **AI 味 / 套路式收束** — `/tmp/mile_fcaad8fe.md:67`
`另類數據不會免費送你 alpha 這條結論已經第 N 次被重新確認` 有明顯平台口號感。不是錯，但會比前文方法敘事更像宣傳收尾，建議改成具體一點，例如「在目前這 12 個格子裡，沒有任何一格同時通過統計與經濟門檻」。

## Lookahead audit

- PASS — `K1116f` 明確重用 `K1116c` 的 PIT 面板，`release_date <= F` 的 construction 寫在程式與 README 中，`pit_shift0` 不是 lookahead。
- PASS — weekly baseline 與 alt-data lag 規則與 README 一致，沒有 same-week 偷吃 future release 的跡象。

## Recommended fixes

1. 把 line 63 降級，避免暗示 TLT 很可能只是差資料頻率就會變成可交易訊號。
2. 清掉 line 17 的機械句型。
3. 把最後一句從抽象口號改成直接對應本次 12-cell 結果。
