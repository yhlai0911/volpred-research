# K1733 — AI 基建資金鏈的波動傳導（hyperscaler/semis × power-grid/utility × credit）

**Model**: claude-opus-5 / xhigh (per model_router)
**Task id**: K1733（`storage/next_tasks.json`）
**Experiment id**: `k1733`（目錄一律小寫 `experiments/k1733/`，檔名 `K1733.py` / `K1733_results.json`）

## 0. 開工前必讀（不可跳過）

1. `docs/error_log.md`
2. `.claude/rules/experiments.md`
3. `.claude/skills/autonomous-research/references/experiment-preamble.md`
4. `research_program.md` 的方法論約束段（Patton / DM / Harvey / bootstrap 標準）

## 1. 動機

來源：`research_program.md` line 606 未勾選項。J.P. Morgan 2026 alternatives outlook 指出 AI
data-center financing 正從 public 移向 private market。若 AI capex 衝擊真的先打到**實體瓶頸**
（電力、電網、基建）與**融資成本**（credit），再傳到 Nasdaq 的已實現波動，那麼 XLU/PAVE/HYG/LQD
的 vol 應該對 SMH/QQQ 的 RV 有領先資訊。這是可交易的 lead-lag 主張，也是可以被否證的主張。

## 2. 差異化與**必守的方法論紅線**（本節是本實驗成敗關鍵）

知識庫已有三條直接相關且**已被更正過**的結論，本實驗若重蹈同一個錯誤即視為失敗：

- **K628b（2026-07-13 CORRECTED）**：Cross-asset vol spillover network 的 SPY 最大淨傳出者
  量級 +43.7pp 是 **Cholesky 排序產物**；改用 order-invariant KPPS GFEVD 後降為 +14.6pp。
- **K865b**：Diebold-Yilmaz 的 SPY-hub **方向性**結論是 Cholesky 排序假象 —— order-invariant
  GFEVD (KPPS) 推翻方向性宣稱，但**總溢出本身是真的**。
- **K907**：spillover TCI 與 VIX 幾乎無關（r=0.001），是獨立風險維度 —— 不要把 TCI 當 VIX 代理，
  也不要在沒檢查前宣稱「新指標」。

**因此本實驗的硬約束**：

1. K1733 的核心假設**本質上是方向性的**（電力/credit → Nasdaq RV），而方向性正是 K628b/K865b
   翻車的地方。**禁止**用 Cholesky-ordered FEVD 支撐任何方向性宣稱。一律用
   **order-invariant KPPS GFEVD**，並額外報告 **ordering robustness**（至少隨機重排順序
   ≥100 次，報 net-directional 的分佈與符號穩定率）。符號不穩 → 結論必須降級為 NULL。
2. 任何「A 領先 B」的宣稱要有正式檢定，不能只看相關或只看圖：Granger（HAC-robust）+
   lag-specific 係數 + block-bootstrap CI。多資產多 lag 必做 **FDR（Benjamini-Hochberg, q=0.1）**。
3. 明確區分「總溢出真實」vs「方向性可疑」兩種結論強度（K865b 的教訓就是這兩者不同命）。

## 3. 資料

- yfinance 日頻，`auto_adjust=False`，Open 用 AdjClose/Close 重新縮放（沿用 K1813 的作法）。
- 三籃：
  - **AI 端**：MSFT、NVDA、SMH、QQQ
  - **實體瓶頸端**：XLU、PAVE（PAVE 上市較晚，樣本起點以**共同可用期間**為準，不可用 NaN 假裝有資料）
  - **信用端**：HYG、LQD
- 期間：download 從 1990-01-01 抓（實際樣本由共同可用期間決定，**必須在 results.json 明列
  每個 ticker 的 first/last date 與 N**）。OOS 切點 2015-01-01；若共同期間晚於 2015 則另訂並說明理由。
- RV 定義與 vol proxy 的口徑要寫清楚（例如 20d 已實現波動、或 Parkinson/Garman-Klass），
  並在 README 說明為何選它。

## 4. 假設與成功標準（必須事前寫死，事後不可改口徑）

- **H1（總溢出存在）**：三籃構成的系統有顯著總溢出（TCI 顯著 > 隨機化基準）。
  criterion：block-bootstrap p < 0.05。
- **H2（方向性：實體/信用 → AI）**：KPPS GFEVD 下，XLU/PAVE/HYG/LQD → {SMH,QQQ} 的 net
  directional spillover > 0 且 FDR 後顯著，**且** ordering-robustness 檢查中符號穩定率 ≥ 90%。
  任一條不成立 → H2 判 REJECT / PARTIAL，不得含糊。
- **H3（領先資訊有增量預測力）**：把實體/信用 vol 加進 Nasdaq RV 的預測式，對
  HAR-RV baseline 有顯著改善。criterion：**nested 情況用 Clark-West**（不是 DM）；
  OOS R² 增量 + block-bootstrap CI。加入成本/實務考量時報含成本結果。
- **H4（可交易性，若 H2/H3 任一成立才做）**：以 t-1 訊號、t 報酬建策略，對 buy-and-hold 與
  ungated baseline 各比一次，cost grid 0/1/5 bp/side。**若某規則只在高成本欄位「勝出」，
  必須明確判定為 turnover artifact，不得當成有效訊號**（沿用 K1813 H3 的判讀紀律）。

**NULL 是完全可接受的結果**，而且以先前 spillover 系列的紀錄看，NULL 或「總溢出真、方向性假」
是相當可能的結局。如實報告即為成功。

## 5. 防錯規則（違反任一即實驗失敗）

- **Lookahead 是最高風險**：程式碼要有明確 `signal.shift(1)` 或等效 lag；禁止 same-day 訊號乘
  same-day 報酬；baseline 與新策略用**同一個** lag 慣例。
- **另做 lookahead 因果探針**（照 K1813 的作法，這是已驗證有效的模式）：把 T 之後的報酬換成
  N(0, 0.5) 噪音重建訊號，確認訊號不變 / 選擇不受污染，把 `violations` 列進 results.json。
- **固定 seed = 42**（bootstrap / 重排 / 任何抽樣）。
- Sharpe 或改善幅度好得不像真的 → 先當成 bug 查，不要先慶祝。
- 滾動/樣本外一律只用當時可得資訊估參數。

## 6. 產出（三件套 + spec，缺一即 BLOCKED）

- `experiments/k1733/README.md` — 動機 / 方法 / lookahead policy / 成功標準 / 結果 / 局限
- `experiments/k1733/K1733.py`
- `experiments/k1733/K1733_results.json`
- 圖表（真圖，不可 ASCII 冒充）放 `experiments/k1733/figures/`
- 原始資料快照放 `experiments/k1733/data/`

**reproduce_spec 必須在 run-time 產生**（AGENTS.md 2026-07-22 / K1708 教訓 —— 事後補寫會與漂移後的
程式不一致）。收尾呼叫 canonical helper：

```python
from volpred.research.reproduce_spec import finalize_experiment

finalize_experiment(
    results=payload, entrypoint=__file__,
    canonical_result="K1733_results.json",
    inputs=[...], seeds=[("numpy", 42)], started_at=T0,
)
```

自查：`python3 scripts/check_experiment_artifacts.py check --path experiments/k1733`

`K1733_results.json` 必含：`k_id` / `title` / `data_source` / `config`（含 seed、期間、grid）/
每 ticker 的樣本涵蓋 / `descriptive` / 各假設的檢定統計量與 p 值 / FDR 後結論 /
`ordering_robustness` / `lookahead_diagnostics` / `verdicts`（H1-H4 各自 ACCEPT/PARTIAL/REJECT + criterion）。

## 7. 邊界

- **只寫 `experiments/k1733/` 內的檔案。**
- **禁止**修改共享狀態：`storage/reports/feed.json`、`storage/memory/knowledge.json`、
  `storage/memory/thinking_journal.json`、`storage/memory/experiment_experiences.json`、
  Supabase / Mirror sync。
- **禁止**自己寫 knowledge.json（K1259：只有主線程能寫，數字由主線程程式化從 results.json 取）。
- 完成後在你的 worktree 內 commit；由主線程用 `bash scripts/merge_worktree.sh` 合併。

## 8. Mission sanity check

收尾前自問並在 README 回答：這個結果如果是真的，對 VolPred 的波動預測或策略有什麼可用之處？
如果是 NULL，它排除了哪一條看似合理的路？（NULL 的價值就在這裡，要寫出來。）
