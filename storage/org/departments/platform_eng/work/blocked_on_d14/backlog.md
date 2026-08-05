# blocked-on-D14 待辦清單（核准後照這份解凍，不需重新診斷）

依 D14 裁決 (a)：以下全部**停在原地**，不重複開單、不找繞路寫法。
每一項都已完成診斷或規格，核准後直接施工。

| # | 事項 | 修改面 | 已備妥的東西 |
|---|---|---|---|
| 1 | 控制閘 evidence source 失明（詞彙表雙源漂移 ＋ tombstone 欄位） | `src/volpred/ops/`、`config/control_gate_registry.json`、`tests/` | `work/alert_control_gate_source_health_20260802/diagnosis_and_patch.md`（P1–P6 定稿） |
| 2 | reproduce gate 整檔 hash 誤判 | `scripts/reproduce_check.py`、`tests/` | `work/reproduce_gate_import_surface/`（診斷 ＋ 可逐字貼上的 helper ＋ 實測結果） |
| 3 | 無 sidecar index.lock 機械出口 | `scripts/dispatch_supervisor/phase_z.py`、`scripts/tests/` | `work/sidecarless_index_lock/`（forensics ＋ mechanical_exit_spec） |
| 4 | F1／F2／F3 token 會計 | `scripts/token_usage_report.py`、`~/.volpred/bin/cron_token_report.sh` | 尚未診斷（F2 方向經資源監控部更正為 fork root，回歸期望值：Codex billable 136,756,562、邏輯 session 131） |
| 5 | 五支文章圖表腳本歸位 | `scripts/gen_*_article_charts.py` | **圖已交付**；腳本在 `work/content_charts/`，以 marker 定位 repo root，搬過去不需改任何一行 |
| 6 | path claim 幽靈鎖（被拒寫入仍留 45 分鐘 claim） | `scripts/hooks/` | 治理部診斷 ＋ 本部門第一人稱佐證；偏好修法＝PreToolUse 下 provisional、無成功 PostToolUse 就撤銷 |
| 7 | org_attach settings 生成（含 D5-1／D9） | `scripts/org/org_attach.py` | 經理已實測，D14 已升老闆 |
| 8 | 三張 canonical（compute queue source_task_terminal／K1750 collection／CI fire 執行契約 3-strike） | `scripts/`、`src/` | 未診斷 |
| 9 | **新單**：`check_experiment_artifacts.py` 的 knowledge 條目比對是 substring 匹配 | `scripts/check_experiment_artifacts.py`、`tests/` | 見下 |
| 10 | 四張 CI 紅燈（四個獨立根因） | `scripts/`、`src/`、`tests/`、`config/` | 分類與最新一張的唯讀確認見 `work/pool_classification/` |

## 第 9 項的細節（研究部實證，非推測）

任何 kid 只要是既有 kid 的字串延伸（`k1095_v3` ⊃ `k1095`）就自動繼承前作的 gate
通過權——變體實驗因此對 topic dedup 隱形，而 artifact gate 仍亮綠燈。

修法方向採**比對 results JSON 的 `experiment_id` 欄位**，而不是 word-boundary：
word-boundary 仍然要猜命名慣例（`k1095-v3`、`k1095_v3`、`K1095V3` 要各補一條規則），
欄位比對是直接問資料本人。落地時同步補一條回歸測試，用 `k1095` 與 `k1095_v3`
兩個真實 id 斷言後者不繼承前者。

## 解凍時的順序建議（不是裁決，是本部門的看法）

1. 第 10 項那張 manifest CI 紅燈——一道指令、對全 repo 生效、所有部門的 push 都掛著
2. 第 6、7 項——它們是「讓其他部門能自己動」的前提，做完就不必再有代工窗口
3. 第 1、2、3 項——已有定稿，施工即驗收
4. 第 4、8、9、10 項其餘——需要新的診斷時間
5. 第 5 項——圖已交付，腳本歸位隨時可做，不急
