# K1720 — 槓桿 ETF 機械再平衡與尾盤波動放大

**Model**: opus / xhigh (per model_router)
**Task id**: K1720 (P3 experiment)
**Worktree cwd**: `.claude/worktrees/dispatch-slot-3-87c7269d-k1720`（唯一允許寫入處；禁碰 canonical checkout、禁 git add/commit，merge 由後續 fire 走 merge_worktree.sh）

## 研究問題（grounded：research_program.md line 571）

槓桿 ETF（LETF）為維持固定槓桿倍數 k，每日收盤前須機械再平衡，理論再平衡需求
∝ (k² − k) × 當日報酬 × AUM。假說：在大漲/大跌日，這股同向的尾盤 order-flow 會**放大尾盤
（last hour）已實現波動與價格 continuation**，且放大幅度隨 LETF 總 AUM 上升。
來源：arXiv / JPM 2025 "beyond volatility drag"。

## 資料

- 標的：TQQQ (3x QQQ)、SQQQ (-3x QQQ)、SSO (2x SPX) — 用 **1h bar**（yfinance intraday，
  注意 yfinance intraday 僅回溯有限期間；能取多長就取多長，於 README 記錄實際樣本窗與 bar 數）。
- 底層/對照：QQQ、SPY 同頻 1h bar 作為 benchmark（尾盤 vol 的市場基準）。
- LETF AUM：用 yfinance / 公開資料近似各 ETF 的 AUM 或 shares outstanding × price 作 proxy；
  無法逐日取得則用可得的月/季頻 AUM，於 README 明記 proxy 與限制。

## 方法（依 .claude/rules/experiments.md — 先讀）

1. **README.md**：motivation + method + **lookahead policy** + success criteria（明確寫 CONDITIONAL_PASS / PASS 門檻）。
2. **K1720.py**：
   - 定義「尾盤 vol」= 每日最後一根（或最後 N 根）1h bar 的 realized range/return vol。
   - 定義大漲跌日 = 底層當日 |report| 超過某分位（如 top/bottom decile），事件窗做 last-hour vol 對比 non-event 日。
   - 核心檢定：last-hour vol / continuation 是否在大漲跌日顯著高於平常，且與 LETF (k²−k)×|ret|×AUM 的 rebalance-pressure proxy 正相關（cross-section 或 rolling 回歸）。
   - **嚴禁 lookahead**：任何 predictor 一律 `signal.shift(1)`；固定 `seed=42`。
   - 至少一個統計檢定（t-test / 回歸係數顯著性 / event-window before-after），報告 effect size 與 CI。
3. **K1720_results.json**：byte-traceable outputs（樣本窗、bar 數、各係數/檢定統計量/p-value/effect size）。

## 產出物（相對 cwd）

- `experiments/K1720/README.md`
- `experiments/K1720/K1720.py`
- `experiments/K1720/K1720_results.json`  ← result-artifact，runner 只驗存在

## 誠實與 sanity check（HARD）

- 研究誠實 > 一切：不得編數字；NULL / 不顯著就如實記 NULL，一樣有價值。
- yfinance intraday 樣本可能很短 → 若樣本不足以支撐檢定，README 明記限制並降級為 descriptive
  （report 有限樣本下的方向性證據），不要硬套顯著性。
- Mission sanity check：這是 vol 預測研究線的機制性題目，結論須能回答「LETF rebalance 是否
  是尾盤 vol 的一個可觀測驅動」。

## 收尾

- 完成後由後續 fire 的 PHASE A 收：Codex review（primary path；額度不足則 subagent/audit fallback）
  → CONDITIONAL_PASS 以上才寫 knowledge entry → merge worktree。
- 本 agent job 只負責產出上述三檔並自我驗證數字一致，不寫 knowledge.json、不 merge。
