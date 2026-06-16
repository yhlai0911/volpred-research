# K1511 — 機構作空 × 散戶跟漲的「角色反轉」月份識別與台股驗證（PoC）

**Branch**: `agent-k1511-rolereversal`
**Date**: 2026-06-16
**Status**: PoC（將 verdict 填於 `k1511_results.json`）
**Seed**: 42

## 動機

EFM 2026 "Who Drives Momentum Returns" 工作論文發現美股「角色反轉月份」（機構 net sell × 散戶 net buy）後 1 個月，動能/個股報酬有 ~+40bp 的條件性差異。本實驗將此假說平移至台股市場、用 TWSE 公開資料做最小可驗證 PoC，回答：

> 台股市場是否也存在「外資作空、散戶加碼」月份在下一月 0050 報酬上的條件性差異？

## 與相鄰 K 的差異化

- 不是 vol 預測，不直接與 K1509（TIPS regime）/ K1510（SUE→RV）重疊。
- 不做個股 panel（避開 50 檔成份股月 panel 的時間炸開），用 0050 ETF 月度報酬做 condition-on-month 檢定。
- 未來可延伸：(a) 中位數 vs mean robust check；(b) 拆 sub-period（2014-2019 vs 2020-2026）；(c) 改個股 panel 做 cross-section。

## 資料

| 欄位 | 來源 | 頻率 | 樣本 |
|------|------|------|------|
| `foreign_net_twd` | TWSE BFI82U（三大法人月度買賣金額）→ 外資及陸資 + 外資自營商合計淨買賣 (TWD 元) | 月 | 2014-01 ~ 最新 |
| `margin_balance_kntwd` | TWSE MI_MARGN（信用交易統計）→ 融資餘額金額（千元 NTD），取每月最後交易日 | 月 | 2014-01 ~ 最新 |
| `ret_log` | yfinance `0050.TW` 月底 Close → log return | 月 | 2014-01 ~ 最新 |

衍生欄位：

- `retail_flow = diff(margin_balance_kntwd)`（散戶融資餘額變化）
- `inst_sign = sign(foreign_net_twd)`
- `retail_sign = sign(retail_flow)`
- `role_reversal = (inst_sign != retail_sign) & both!=0`（任一方向 sign mismatch）
- `inst_sell_retail_buy = (inst_sign<0) & (retail_sign>0)`（focus subset）
- `ret_next = ret_log.shift(-1)`（signal at t, target = t+1 return）

## 方法

1. **Lag 嚴格**：`ret_next = ret_log.shift(-1)`。signal 在月底 t（外資月度淨買賣 + 月底融資餘額已實現），target = t+1 月對數報酬。
2. **Focus 假說**：機構淨賣 × 散戶融資加碼 → 下月 0050 報酬條件分配與其他月份不同。
3. **檢定**：
   - Welch two-sample t-test（focus vs other）
   - OLS dummy regression with Newey-West HAC SE（maxlags=3，月度資料）
4. **次要假說**：任何 sign mismatch（broader role-reversal）也跑一次（探索性，不調整 FWER）。
5. **Seed**：42（為後續 block bootstrap 預留）。

## Verdict gate

- `PASS_PRELIMINARY`: |t_stat_NW| > 1.96 且 N_focus ≥ 24
- `INCONCLUSIVE`: 1.0 < |t| ≤ 1.96 或 N_focus < 24
- `NULL`: |t| ≤ 1.0
- `DATA_FAIL`: 資料抓不到 → blocker

## 結果

詳見 `k1511_results.json`。

**核心數字（2014-03 ~ 2026-04, N=144 個月）**：

| metric | value |
|--------|------:|
| N_total | 144 |
| N_inst_sell_retail_buy (focus) | 39 |
| N_other | 105 |
| mean_focus（focus 月後 1M 報酬均值） | 152.2 bp |
| mean_other | 172.8 bp |
| **mean_diff_bp（focus − other）** | **−20.6 bp** |
| Welch t-stat | −0.19 (p = 0.85) |
| **OLS dummy + Newey-West t-stat** | **−0.22 (p = 0.83)** |
| 任何 sign-mismatch 月份 N | 59 |
| any_reversal β | −125.3 bp |
| any_reversal NW t-stat | −1.56 (p = 0.12) |
| **Verdict** | **NULL** |

**結論摘要**：

1. 「外資作空 × 散戶融資加碼」月份在下一月的 0050 報酬上**沒有顯著差異**（mean diff −21bp, p = 0.83）。
2. 廣義 sign-mismatch（任一方向反轉）effect 為 −125bp t = −1.56（p = 0.12），方向上 reversal 月份 underperform，但 underpowered。
3. 結果與 EFM 2026 美股「機構作空 × 散戶跟漲後 +40bp」**方向相反**，且**統計上 indistinguishable from zero**。可能解釋：
   - 台股機構結構差異（外資 ≠ 美股 institutional total；融資戶 ≠ 散戶 total）
   - 樣本期含 2020 疫情、2022 升息 cycle 等 regime 變化
   - 0050 偏權值股，role-reversal 效應可能在中小型股更明顯

圖：`fig_a_role_reversal_returns.png`（focus vs other 月後 1M 報酬分布 + boxplot）

**初始 PoC bug 記事（保留 audit trail）**：
- 第一次 fetch 時 TWSE BFI82U 對 2017+ 月份回應不穩，造成 inst flow 只抓到 40 筆中 35 筆是 2014-2016，sample 萎縮成 N=37（2014-03~2018-01）。當時暫時觀察到 mean_diff=+253bp t=1.59 是 **小樣本 noise**，**並非真效應**。修補：加入 5-attempt exponential backoff retry，重抓滿 144 個月後 effect 收斂到 −21bp t=−0.22（NULL）。Lesson 是「small N + 大 effect = high prior on bug or noise」原則的活生生例子，記入 `docs/error_log.md` 候選。

## Limitation（重要）

1. **散戶 proxy**：TWSE 融資餘額是有融資戶的散戶行為，不代表所有散戶；ETF / 海外複委託 / option 散戶不在內。
2. **機構 proxy**：用「外資及陸資」代表機構不含投信、自營（保留 cleanness — 外資是台股最大機構淨買賣者）。可延伸 robust check 加投信。
3. **0050 不是台股 broad market**：0050 偏大型權值股 weighting，role-reversal 也可能在中小型股更顯著（PoC 不擴張）。
4. **樣本 ~144 月，N_focus 估計 30-60**：powered for medium effect (~50bp/month) 但 underpowered for small effect。
5. **單一 holding horizon**：只測 t+1 月；EFM 美股版本還測 1-3 月 + cumulative。

## Next step（不在本 PoC scope）

1. Block bootstrap 1000 iter 確認 t-test CI（→ `scripts/k1511_bootstrap.py`，enqueue 到 compute_queue）
2. 拆 sub-period 2014-2019 vs 2020-2026 看是否穩定
3. 改 broader market index（TAIEX）vs 0050 robust check
4. 加入 holding period h ∈ {1, 2, 3} 月做 EFM-style horizon scan
5. 若 PASS_PRELIMINARY → 排 daily_article draft

## Codex Review

**SKIPPED — TODO**：2026-06-16 PoC 執行時 Codex CLI (`codex exec --skip-git-repo-check -s read-only`) 連續 stall ~11 min 無輸出；依任務 brief「Codex 卡 ≥ 5 min skip + 標 TODO」rule 移除阻塞。主線程 follow-up 應跑 Codex 二次審或 `feature-dev:code-reviewer` subagent fallback（依 `.claude/rules/experiments.md` 的 Codex diagnostic 5-step + subagent fallback path），通過後才寫 `knowledge.json`。本 PoC 主要 review checklist 已在主線程 pre-tool hook 處驗證：
- `signal.shift(-1)` 用於 `ret_next` → signal at t, target = t+1，無 lookahead
- HAC `maxlags=3` 月度資料合理（≈3 月自相關 cap，Newey-West rule of thumb T^(1/4) ≈ 3.5）
- focus 與 other 共用同樣 lag 規則（兩組都用 t+1 forward return）

## 可復現性

```bash
cd /Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-k1511-rolereversal
uv run python experiments/k1511/k1511.py
# 輸出：experiments/k1511/k1511_results.json + fig_a_role_reversal_returns.png
# 第一次跑會打 TWSE API 數百次（每月一次 BFI82U + 一次 MI_MARGN），耗時 ~10-20 min；
# 之後 data/*.parquet cache 命中秒回。
```

## 檔案

- `k1511.py` — 主腳本
- `k1511_results.json` — 核心結果
- `k1511_panel.parquet` — 月度 panel cache
- `data/*.parquet` — TWSE / yfinance 原始 cache
- `fig_a_role_reversal_returns.png` — 結果圖
