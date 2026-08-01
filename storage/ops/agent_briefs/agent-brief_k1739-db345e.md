# K1739 — 商品短期（1–4 週）動能與反轉「共存」驗證及 vol 條件

**Model**: opus / xhigh (per model_router, task_type=experiment)
**Task id**: K1739（pool task 已 in_progress，owner=hourly-slot-1-ae8721c1a51948e59abf36181ed29947）
**Worktree（你唯一可寫的地方）**: `.claude/worktrees/dispatch-slot-1-ae8721c1-k1739`，branch `k1739-slot1-ae8721c1`
**產出目錄**: `experiments/K1739/`

---

## 0. 開工前必讀（不可跳）

1. `AGENTS.md` §研究誠實原則、§實驗與研究流程、§實驗 artifact gate
2. `.claude/rules/experiments.md`
3. `.claude/skills/autonomous-research/references/experiment-preamble.md`
4. `docs/error_log.md`（至少掃最近 30 天 + 搜 "lookahead" / "bootstrap" / "yfinance"）
5. 在 `storage/memory/knowledge.json` 用 grep/jq 搜相關 K（**禁止整檔讀取**）

## 1. 動機與文獻

JFEM / SSRN 2026 在商品市場發現：**短期（1–4 週）動能與反轉並非由 horizon 區分，而是「共存」**，
傳統「1 週反轉、12–1 月動能」的 horizon 二分法可能是把兩個並存機制平均掉的結果。
本實驗以美股商品 ETF 代理版檢定：**同一 horizon 下，動能與反轉是否被 vol regime 分離**。

**開工前先做文獻檢索（≥3 篇，WebSearch）**，把 citation 寫進 README「文獻」段；
若文獻顯示本設計已被同口徑做過，在 README 明確寫差異化或改設計，不要硬做重複題。

## 2. 相關既有 K（差異化基準）

grep 確認過的鄰近條目（都**不是**同題，本實驗有差異化空間）：

- `K662` ★ Commodity VT — VIX 對 GLD/USO 無效，equity vol framework 不轉移到商品
- `K21` Commodity VT — supply-driven vol 與 VIX 正交
- `K1129` / `K1135` / `K1136` GAS / skew-t 商品 compendium — 全 NULL（**vol 模型**題，非 return predictability）
- `K1481` EIA inventory surprise 作商品 RV regime feature — NULL
- `K1347` CVaR-RP（含 PDBC）— FAIL
- `research_rp_05c316a53f` 12-1M 動能報酬集中於隔夜（cross-sectional momentum）

**差異化**：以上都不是「短期 return 動能/反轉的 vol-regime 條件分離」。本實驗第一次在商品 ETF 上
把 **regime × past-return 交互項**當主檢定量。**K662/K21 的教訓要吃進來**：商品 vol 不可用 VIX 代理，
regime 一律用**商品自身 realized vol**（見 §4）。

## 3. 資料

- yfinance：`GLD, SLV, USO, UNG, CPER, PDBC`（adjusted close，日頻）
- 期間：各資產取自身 inception 起至 2026-07-31；**pooled 分析另外用 common sample**
  （PDBC 2014-11 起 → common start 2015-01-01），兩種樣本都報，不要只挑好看的
- 週報酬：以週五收盤（或當週最後交易日）對齊，明確寫對齊規則
- **USO / UNG 有 roll / reverse-split 歷史** → 用 adjusted close，並在 README 說明此代理限制
  （ETF ≠ 期貨 excess return；這是 honest limitation，不可略過）

## 4. 方法（核心設計）

**H1（主檢定）**：同一 horizon h ∈ {1, 2, 3, 4} 週，過去 h 週報酬對未來 h 週報酬的預測係數
**在高 vol regime 與低 vol regime 符號相反**（一邊動能、一邊反轉）。

pooled panel 預測回歸：

```
r_{i,t+1..t+h} = α + β1 · past_i,t(h) + β2 · past_i,t(h) × HighVol_i,t + β3 · HighVol_i,t + ε
```

- `past_i,t(h)` = 資產 i 截至第 t 週（含）的過去 h 週累積報酬
- `HighVol_i,t` = 資產 i 自身 realized vol（trailing 63 日，日報酬）**在其 trailing 2-year 分佈**
  的上/下 tercile 或中位數 dummy；**expanding/rolling window 只用 t 以前資訊**
- **關鍵檢定量 = β2**（regime 分離）；β1 與 β1+β2 各自的符號與顯著性一併報

**Lookahead 政策（最高風險，必須代碼可見）**：
- 所有 signal（past return、vol regime）在進 regression 前一律 `.shift(1)`，或等效地
  用 `t` 期末資訊預測 `t+1` 起的報酬 —— 二選一，**在代碼裡留註解說明採哪一種**，不可兩種混用
- **嚴禁 same-week 訊號乘 same-week 報酬**
- overlapping h 週報酬 → 標準誤必須用 **Newey-West HAC，lag ≥ h**（或 Hodrick 1992）

**推論標準**：
- 主檢定 β2：HAC t-stat；**多重檢定（4 horizons × 2 樣本 × asset-level）一律過 BH-FDR**
- **block bootstrap（stationary bootstrap，block ≈ 8 週，B=2000，seed=42）**產生 β2 的經驗分佈，
  與 HAC 交叉驗證；兩者結論不一致要如實寫出來
- 單一資產 time-series 版本另做，但**主結論以 pooled panel（asset clustered SE）為準**

**H2（次要，可選但建議）**：cross-sectional 版本 —— 6 檔 ETF 依過去 h 週報酬排序做 long-short
（top-2 minus bottom-2，週再平衡，**signal shift(1)**），檢定該策略報酬是否在高/低 aggregate
commodity vol regime 下符號相反。報 Sharpe、t-stat、以及**扣掉合理交易成本（單邊 5bp）後**的結果。

**必守**：baseline 與所有 variant 用**同一 lag 慣例**；Sharpe 高得不像真的 = 先當成 bug 查。

## 5. 成功標準（NULL 是完全可接受的結果）

實驗**成功**的定義是「結論可信」，不是「找到效應」：

- 三件套齊全且數字可回溯到程式化計算
- lookahead policy 在代碼中明確可見
- 主檢定量 β2 有 HAC + bootstrap 雙路徑推論 + BH-FDR 多重校正
- 若 β2 不顯著 → **如實寫 NULL**，並報 power 討論（樣本週數、可偵測 effect size）
- 若 β2 顯著 → 必做 robustness：改 vol window（21/63/126 日）、改 regime 切法（median vs tercile）、
  改 common vs full sample、去掉 UNG（最極端 roll decay）各跑一次；**任一 robustness 翻號就降級結論**
- 結論強度不得超過證據（ETF 代理 ≠ 期貨；6 檔 ≠ 完整商品 universe，README 要寫明）

## 6. 交付物（artifact gate 會擋）

1. `experiments/K1739/README.md` — 動機 / 文獻（≥3 篇）/ 資料與期間與樣本數 / 方法 /
   **lookahead policy** / 成功標準 / 結果 / 限制 / 相關 K
2. `experiments/K1739/K1739.py` — 可重跑；seed=42；`.shift(1)` 或等效 lag 明確；
   結尾**必須**呼叫 canonical helper 讓 results 與 reproduce_spec 同一次 trace 寫出：
   ```python
   from volpred.research.reproduce_spec import finalize_experiment
   finalize_experiment(
       results=payload, entrypoint=__file__,
       canonical_result="K1739_results.json",
       inputs=[...], seeds=[("numpy", 42)], started_at=T0,
   )
   ```
   （**不要事後補 spec** —— K1708 就是這樣讓 spec 描述到一份已漂移的程式）
3. `experiments/K1739/K1739_results.json` — 所有報進 README 的數字都要在這裡有對應欄位
4. 圖表（≥2）：至少「β2 by horizon with CI」與「high/low vol regime 下 past-vs-future return 散佈」
5. 自查：`python3 scripts/check_experiment_artifacts.py check --path experiments/K1739`

## 7. 邊界（硬規）

- **只寫 `experiments/K1739/` 內的檔**（加必要的 `scripts/` 繪圖腳本也可，但不碰其他實驗）
- **禁止修改共享狀態**：`storage/reports/feed.json`、`storage/memory/knowledge.json`、
  `storage/memory/thinking_journal.json`、`storage/memory/experiment_experiences.json`、
  Supabase / Mirror sync
- **knowledge.json 條目由主線程寫（K1259 gate）** —— 你不要寫，但要在 README 留可直接程式化取數的欄位
- 完成後在 worktree 內 `git add` + `git commit`（主線程之後用 `scripts/merge_worktree.sh` 合併）
- 禁止 force push / `--no-verify` / `git worktree remove --force`
- 資料抓不到、模型不收斂、樣本不足 → **如實寫下來並標 blocked/limitation**，不可捏造或用 synthetic 數據頂替

## 8. 完成回報

最後輸出一段結構化摘要：主檢定 β2（各 horizon 的點估計 / HAC t / bootstrap p / BH-adjusted）、
結論分級（SUPPORTED / NULL / INCONCLUSIVE）、robustness 是否一致、已 commit 的 sha、artifact 路徑。
