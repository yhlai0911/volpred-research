# Task: 研究線重開 — TAIFEX tick 5-min RV intraday 波動率題組

**Model**: opus / xhigh (per model_router, task_type=experiment)
**task id**: `research_taifex_intraday_rv_line`（P3，餓死 74.8h，本班清 starvation lockout 派出）
**worktree cwd**: `.claude/worktrees/dispatch-slot-1-30aeb902-taifexrv`（branch `wt/dispatch-slot-1-30aeb902-taifexrv`）
**owner token**（work_log 的 actor/owner 必須逐字用）：`hourly-slot-1-30aeb902a444412ebc77a4d4b9a51a6f`

## 背景

Owner 於 2026-07-14 裁決：**以自有 TAIFEX tick 取代付費 US intraday 資料線**。前置任務
`taifexdata_dropbox_organize` 已 succeeded，canonical 資料已就位：

- 路徑：`data/intraday/taifex_tick/<contract>/<yyyymm>.parquet`
- 覆蓋：TX / TX1 / TX2 各 3548 交易日，2012-01-02 ~ 2026-07-14，10644 檔 / 35.9GB
- 258 個缺口 = 國定假日，**不是資料洞**（已驗證，不要當成 missing data 處理）
- era 邊界：9 欄 → 10 欄實測切在 **2012-06-14**
- **夜盤自 2017-05-16 才啟用** —— 這是本題組最重要的結構斷點，任何跨 2017-05-16 的日盤/夜盤分解都必須處理這個 regime change，不可整段 pool
- 資料組織說明見該目錄 README（schema / 缺口 / consumer guide）

## 目標（本 job 的完整交付）

重開這條研究線，做到**一個 K 完整跑完 + 後續 K 有可執行 brief**，不要三個都做半套：

### 1. 設計 2-3 個 K 的題組（寫成 brief，不要全部執行）

候選方向（description 原文給的三個，可依資料實況調整但要說明理由）：
- (a) **TX 5-min RV 的 HAR-intraday vs daily HAR 增益** —— 對照既有 K1095 系列
- (b) **夜盤 / 日盤 RV 分解**對隔日波動率預測的資訊含量
- (c) 選擇權 tick 的 IV surface 微結構訊號

每個 brief 要有：research question、可證偽的 H0、資料切法（含 2017-05-16 夜盤斷點與 2012-06-14 era 邊界怎麼處理）、baseline、評估指標（QLIKE / DM test）、預期成本。

### 2. 完整執行其中**優先序最高的那一個**（建議 (a)，因為有 K1095 對照組，NULL 也有意義）

走 `.claude/skills/autonomous-research/SKILL.md` + 實驗三件套（script / results.json / README）。
硬性要求：

- **OOS 紀律**：train/test 切分不得有 lookahead。5-min RV 聚合到日頻預測隔日時，
  當日 RV 只能用到收盤，禁止用未來 bar。
- **Baseline 必須是誠實的對照**：daily HAR-RV（用同一段樣本、同一 loss）。
  不是「調過參的新模型 vs 沒調過的 baseline」。
- **NULL 是可接受且有價值的結果**。intraday 沒增益就寫沒增益 —— 這條線是為了取代
  付費資料，證明「自有 tick 打不贏 daily」本身就是省錢的決策依據。禁止為了好看調樣本、
  換指標、或事後挑期間。
- 統計檢定：QLIKE + Diebold-Mariano（HAC-robust）。報 point estimate 與 p-value，
  不要只報方向。
- 記憶體：35.9GB 全量別一次讀。先用 **子樣本**（例如 2018-2026 的 TX 連續月）把 pipeline
  跑通並驗證正確性，樣本範圍在 results.json 的 metadata 誠實記明。若要全量掃描，
  另外開 compute_queue job，不要在本 job 裡硬幹。

### 3. 產出

- `experiments/<kid>/<kid>.py`、`experiments/<kid>/<kid>_results.json`、`experiments/<kid>/README.md`
- **`storage/ops/taifex_rv_line_handoff.json`（worktree 內相對路徑）—— 這是本 job 的
  `--result-artifact`，是成功後置條件，runner 只驗它存不存在。必須真的寫出來，schema：**

  ```json
  {
    "executed_k_id": "kXXXX",
    "verdict": "PASS|NULL|FAIL",
    "headline_numbers": {"qlike_baseline": 0.0, "qlike_model": 0.0, "dm_t": 0.0, "dm_p": 0.0},
    "sample": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "n_days": 0, "contracts": ["TX"]},
    "results_json_path": "experiments/kXXXX/kXXXX_results.json",
    "planned_k_briefs": [{"k_id": "kXXXX", "question": "...", "h0": "...", "cost": "..."}],
    "branch": "wt/dispatch-slot-1-30aeb902-taifexrv",
    "commit": "<hash>",
    "caveats": ["誠實列出沒做到的部分"]
  }
  ```

  數字必須與 `<kid>_results.json` 逐一對得上（後續 followup 會逐項核對，對不上視同 FAIL）。
- results.json 的 metadata 必須含：實際樣本期間、樣本數、排除了什麼、為什麼

## 禁止

- ❌ 假數字、樂觀四捨五入、把「還沒跑」寫成「已驗證」
- ❌ 寫 `storage/knowledge.json`（agent 禁寫 knowledge，K1259 教訓；由後續 followup 主線程寫）
- ❌ `git push`、`--no-verify`、force push
- ❌ 改動 worktree 外的 canonical 檔案

## 允許 / 要求的 git 行為

在你自己的 worktree (`.claude/worktrees/dispatch-slot-1-30aeb902-taifexrv`) 內正常 commit
你的實驗檔（分支 `wt/dispatch-slot-1-30aeb902-taifexrv`）。合併回 main 由後續 fire 的
PHASE A followup 走正式 `merge_worktree.sh`，不是你的事。

## work_log

在 worktree 內 append 一筆到 `storage/work_log.json`（JSON array）：`actor` 與 `owner` 逐字等於
上面的 owner token，`task_type` = `experiment`。用 python 讀寫，寫後 re-parse 驗證，**絕不可截斷此檔**。

## 回傳格式

最終回覆是給後續 followup 主線程的資料，不是給人看的信。請回：
1. 執行的 K id + verdict（PASS / NULL / FAIL）+ 關鍵數字（QLIKE baseline vs model、DM t / p）
2. 實際樣本期間與樣本數
3. 另外 2 個 K 的 brief 摘要（各 3 行）
4. worktree branch 名 + commit hash
5. 已知 caveat / 沒做到的部分（誠實列，不要藏）
