# K1736 — 偏度風險溢酬「期限結構」作長 horizon 尾部訊號

**Model**: opus / xhigh (per model_router)
**Task id**: K1736（pool 已 claim，status=in_progress）
**Worktree**: `.claude/worktrees/dispatch-slot-1-e9403ded-k1736`（你只能寫這裡）
**Canonical result artifact**: `experiments/K1736/K1736_results.json`

---

## 0. 開工前必讀（不可略過）

1. `docs/error_log.md` — 先看已知踩坑
2. `.claude/rules/experiments.md` — 實驗三件套與 artifact gate 契約
3. `.claude/skills/autonomous-research/references/experiment-preamble.md`
4. `research_program.md` — 本題來自 line 635 的 unchecked item

---

## 1. 動機

CBOE SKEW 這條線在本專案已被打過很多次，**全部是 level 打法、全部 NULL**：

| K | 內容 | 結論 |
|---|---|---|
| K181 / K184 | CBOE SKEW 作波動率預測 | NULL |
| K210 | VIX-SKEW ratio | NULL |
| K258 | SKEW dynamics | NULL |
| K447 | SKEW tail risk | NULL（反而有害、子期間不穩） |
| K535 | SKEW 進 HAR 框架 | NULL，VIX sufficiency #34 |
| K979 | CBOE SKEW vs VIX | NULL，SKEW 無增量（VIX² 非線性更有用） |
| K43 | SKEW / VIX3M **level** | 已做 |

**本題的差異化（唯一理由）**：不打 level，打 **term-structure slope**，且**目標換成長 horizon**（6–12 個月 SPY 報酬 / drawdown），不是次日/次月 RV。文獻依據：JFQA 2025 crash-risk premium / skewness swap 一線的結果指出 skew premium 在長 horizon 較強 —— 也就是說前面 7 個 NULL 打的是「短 horizon + level」那一格，本題打的是**另一格**。

⚠️ **這個差異化必須在 README 裡寫清楚並被你自己檢驗**。如果你做完發現實質上又退化成 level 打法（例如 slope 與 level 相關係數 >0.9），**如實說出來並標為 NULL/退化**，不要硬凹成新發現。

## 2. 差異化的前提：term structure 到底建不建得出來（先做這步，這是本題最大風險）

^SKEW 是 **30 天** risk-neutral skewness 指標，CBOE **沒有免費的 SKEW3M / SKEW6M**。所以「skew premium 期限結構」不是現成資料，要你自己建，而且**建法必須可辯護**。

**Step 1（觀察先於計算，AGENTS.md 第 6 條）**：先確認資料真的抓得到、期間多長、有多少缺值。
- `^SKEW`、`^VIX`、`^VIX3M`（可再試 `^VIX6M`）、`SPY`（或 `^GSPC` 拉長樣本）
- yfinance 對 `^SKEW` / `^VIX3M` 的覆蓋**不保證**；抓不到就改用 CBOE 官方公開 CSV，並在 README 記下實際來源 URL 與抓取日期
- 輸出：每個序列的起訖日、N、缺值率 → 寫進 results.json 的 `data_diagnostics`

**Step 2**：建構 skew-premium term structure proxy。可接受的做法（擇一或並列，但要說明選擇理由）：
- (a) **realized skewness 期限結構**：由日報酬算 h ∈ {21, 63, 126, 252} 交易日的 realized skewness，配對 ^SKEW（30d RN skew）→ premium_h = RN_skew − RealizedSkew_h；slope = premium_252 − premium_21
- (b) **VIX term structure 作 skew 的 conditioning**：用 (^VIX3M − ^VIX) 或 (^VIX6M − ^VIX) 當期限結構維度，與 ^SKEW 交互
- (c) 你若有更好的建法，寫明推導與文獻出處

**若你的誠實結論是「免費資料建不出真正的 risk-neutral skew 期限結構」→ 這本身就是有價值的結果**：寫成 data-limitation NULL，說明需要什麼資料（例如 OptionMetrics / 完整期權鏈）才能做，**不要用代理硬撐再宣稱有發現**。

## 3. 方法論硬規則（違反即實驗作廢）

1. **Lookahead（最高風險）**：`signal.shift(1)`，t-1 訊號對 t 報酬。程式碼裡要有明確 lag，README 要有 lookahead policy 段落。
2. **Seed 固定**：`seed=42`（numpy / 任何 bootstrap / 抽樣）。
3. **重疊觀測是本題的頭號統計陷阱**：6–12 個月報酬用日頻滾動 → 觀測嚴重重疊，OLS t-stat 會**大幅高估**顯著性。
   - 必須用 **Hodrick (1992) 1B standard errors** 或 Newey–West with lag ≥ horizon（兩者最好都報）
   - 必須報 **effective sample size**（獨立非重疊期數 ≈ 樣本年數 / horizon 年數）。^SKEW 從 1990 起算，12 個月 horizon 大約只有 ~35 個獨立觀測 —— **這個數字要在 README 和 results.json 裡明講**
   - 建議並列 **非重疊** 子樣本回歸作 robustness
4. **多重檢定**：多個 horizon × 多個目標（報酬 / max drawdown）→ 必須做多重性校正（Romano–Wolf 優先，至少要報 unadjusted 與 adjusted 並列）。這是 K1680 那條線的教訓。
5. **樣本外**：不要只報 in-sample R²。至少一個 OOS 設計（expanding window），並用 Clark–West 或 Diebold–Mariano 作正式檢定。
6. **子期間穩定性**：K447 就是敗在子期間不穩。切至少 3 個子期間（含 2008、2020）報結果。
7. **不可過度宣稱**：結論強度不得超過證據。NULL 如實報告 —— 本專案 NULL 是正常產出，不是失敗。

## 4. 成功標準

實驗**完成**的定義（不是「有正結果」）：
- [ ] `experiments/K1736/README.md` — 動機 / 資料來源與期間 / 方法 / lookahead policy / 重疊觀測處理 / 成功標準 / 局限
- [ ] `experiments/K1736/K1736.py` — 可重跑，含 `signal.shift(1)` 與 seed=42
- [ ] `experiments/K1736/K1736_results.json` — 所有數字程式化產出，含 `data_diagnostics`、effective sample size、adjusted / unadjusted p-values
- [ ] 圖表（至少 1 張：slope 時序 + 目標變數）
- [ ] 收尾**必須呼叫 canonical helper**（run-time 產生 spec，不可事後補 —— K1708 教訓）：

```python
from volpred.research.reproduce_spec import finalize_experiment

finalize_experiment(
    results=payload, entrypoint=__file__,
    canonical_result="K1736_results.json",
    inputs=[...], seeds=[("numpy", 42)], started_at=T0,
)
```
- [ ] 自查通過：`python3 scripts/check_experiment_artifacts.py check --path experiments/K1736`
- [ ] worktree 內 commit

**判定門檻**：CONDITIONAL_PASS 是寫入 knowledge 的最低標準。正結果、NULL、data-limitation NULL 三者都是可接受的結案，**編造或過度宣稱不是**。

## 5. 邊界（絕對禁止）

- ❌ 不准寫 `storage/memory/knowledge.json`（K1259 —— knowledge 條目只能主線程寫）
- ❌ 不准動 `storage/reports/feed.json`、`thinking_journal.json`、`experiment_experiences.json`
- ❌ 不准碰 Supabase / Mirror sync
- ❌ 不准 `git worktree remove --force`
- ❌ 不准假數字、不准把「跑不出來」寫成「沒有效果」（兩者是不同結論）
- ✅ 你的產出只應在 `experiments/K1736/` 底下

## 6. 交付

完成後在 worktree 內 commit。主線程會在後續 fire 的 PHASE A 收件：驗數字、派 Codex 審、合併 worktree、寫 knowledge 條目。
