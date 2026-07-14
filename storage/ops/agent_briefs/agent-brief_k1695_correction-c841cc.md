# K1695 更正：exposure-matched drawdown（招牌結論是 artifact）

**Model**: claude-opus-4-8 / xhigh (per model_router)
**Task id**: k1695_exposure_matched_correction (P1)
**Worktree**: 你在自己的 worktree，只准動 `experiments/k1695/`，禁碰 feed.json / knowledge.json / storage/memory/*

## 背景（已由主線程 hourly-02 獨立驗證，不是待證假設）

K1695 宣稱「12/VIX overlay 在 13 個國際股市提供 drawdown protection，平均 ΔMDD +12.61pp，13/13 為正」。
主線程用 repo canonical `volpred.stats.drawdown.compare_max_drawdown` 讀 pinned
`experiments/k1695/data/paired_common_returns.csv.gz` 重跑，確認：

| 口徑 | 平均 ΔMDD | 為正市場數 |
|---|---|---|
| raw（K1695 報告的） | +12.61 pp | 13/13 |
| exposure-matched | −0.87 pp | 7/13 |

- raw 數字與 `k1695_results.json` 的 `average_delta_mdd_pp = 12.6139` 吻合 → 差異來自**口徑不是 bug**。
- `compare_max_drawdown` 對 13/13 市場亮 `exposure_mismatch=True`：VT 實現波動只有 BH 的 0.61–0.68 倍，
  遠超 `.claude/rules/experiments.md:140` 的 20% 門檻，該規則明寫此時 raw MDD 差異不可單獨報告。
- `k1695_results.json` 通篇無 exposure 欄位。

完整證據：`storage/ops/k1695_exposure_artifact_verification.md`（先讀）。

## 要做（依序）

1. **重跑 K1695**，一律改用 canonical `volpred.stats.drawdown.compare_max_drawdown`。
   `k1695_results.json` 必須新增 exposure 欄位：每個市場的 realized vol ratio、`exposure_mismatch` flag、
   raw ΔMDD 與 exposure-matched ΔMDD 並列。**raw 數字不可刪**（那是真實計算），但不可單獨當結論。
2. **補 null 分佈**：circular-shift 或 phase-randomized null（固定 seed）。
   目前證據只支持「exposure-matched ΔMDD 約等於零」，**不可宣稱「顯著為負」** —— 沒有 null 就沒有顯著性。
   跑完才知道 −0.87pp 落在 null 分佈的哪裡；如實報告，不論結果。
3. **`.inference.primary` 的 90% CI 與 `decision.kill_triggered` 用同曝險口徑重算**。
   原本的 joint stationary-bootstrap 90% CI [4.2, 19.3] pp 是 raw 口徑 → 必須有一份 exposure-matched 版本。
4. **Codex 審**（`codex exec`，中文 prompt 用 heredoc + stdin）：審代碼與口徑，不是審結論。
5. 更新 `experiments/k1695/README.md`：明寫舊結論被推翻、推翻的理由、新結論的強度邊界。

## 防錯規則（硬性）

- **研究誠實 > 一切**。null result 如實報告。結論強度不可超過證據：沒跑 null 就只能說「約等於零」。
- signal 明確 lag（月底 VIX → 下月部位），bootstrap / null 全部固定 seed。
- **禁寫** `storage/memory/knowledge.json`（K1259 教訓：agent 不得寫知識庫）。主線程驗過才寫。
- 產出留在 `experiments/k1695/`。完成後在 worktree commit。

## 成功標準

`k1695_results.json` 同時含 raw 與 exposure-matched 口徑 + exposure 欄位 + null 分佈 p-value；
README 說清結論被推翻；Codex 審過。**這份更正 gate 住 paper vt-trend-following 的 Table 5 + 第三項
contribution，以及 feed 上多篇已發佈文章的回溯更正** —— 數字必須經得起逐條核對。
