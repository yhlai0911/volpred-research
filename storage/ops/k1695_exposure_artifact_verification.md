# K1695 招牌結論 = exposure artifact（主線程獨立驗證）

- **驗證者**：hourly-02 主線程（不採信 agent 數字，重跑一次）
- **時間**：2026-07-15 02:35 台灣時間
- **起因**：K1695 general 文章 writer agent 在寫作過程中發現，並如實上報

## 結論

K1695 的招牌結論「vt-trend 在 13 個國際市場提供 drawdown protection，通過 pre-registered gate」
**在同曝險口徑下不成立**。它衡量的是「少冒險」，不是「會擇時」。

## 證據（用 repo canonical `volpred.stats.drawdown.compare_max_drawdown`，讀 pinned
`experiments/k1695/data/paired_common_returns.csv.gz`）

| 口徑 | 平均 ΔMDD | 為正的市場數 |
|---|---|---|
| raw（K1695 報告的） | **+12.61 pp** | 13/13 |
| exposure-matched（同風險） | **−0.87 pp** | 7/13 |

- 我重算的 raw +12.61pp 與 `k1695_results.json` 的 `average_delta_mdd_pp = 12.6139` 吻合
  → 差異來自**口徑**，不是 bug。
- `compare_max_drawdown` 對 **13/13 市場**都亮 `exposure_mismatch=True`：VT 的實現波動只有
  buy-and-hold 的 **0.61–0.68 倍**（低 32–39%），遠超 `.claude/rules/experiments.md:140` 的 **20%** 門檻。
  該規則明寫：波動差 >20% 時 raw MDD 差異**不可單獨報告**。
- `k1695_results.json` 通篇**沒有任何 exposure 欄位**。README / codex_review 亦未觸及。
- 該策略平均只放 72.6% 股票。一個「永遠只放七成三、完全不看 VIX」的常數減碼策略，在
  exposure-matched gap 上得分恰好 0 —— K1695 拿到的 −0.87pp 與它無法區分。

## 連帶影響（必須處理，不可留在 backlog）

1. **`k1695_results.json` / README 的結論需回溯更正**；`.inference.primary` 的 90% CI
   [+4.22, +19.30] 與 `decision.kill_triggered=false` 都是對**帳面** ΔMDD 做的，一併繼承問題。
2. **paper `vt-trend-following`**：Table 5 與第三項 contribution（international drawdown
   protection）**建議暫緩**，需先補 exposure-matched + circular-shift / phase-randomized null。
3. **同 bug class**：K1265b / K1702 曾出現過同一類問題 → 這是 class 不是個案，
   `compare_max_drawdown` 已經會亮旗，但**沒有機械 gate 強制實驗必須用它**。真正的根因在這裡。
4. **K1695 的 general 文章暫不發佈** —— 草稿（誠實寫成 null）留在 worktree
   `dispatch-slot-1-3217f0b2-k1695`，等更正後的認證結果出來再發。先發文等於用未認證的
   agent 分析推翻已認證的實驗，順序是反的。

## 未做（明確標示 scope）

- 沒跑 phase-randomized / circular-shift null（超出本班 scope）→ 所以只能說「同曝險下平均約等於零、
  7/13 接近擲硬幣」，**不宣稱顯著為負**。
- 沒碰 `experiments/k1695/` 任何檔（review_verdict sha pin 完好，certify gate 仍過）。
