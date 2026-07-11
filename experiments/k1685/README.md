# K1685 — K1393-faithful GARCH-X 延長 OOS 覆核

## 結論

**收件審查：PASS。研究裁決：`GO_WITH_FRAGILITY_DISCLOSURE`。**

K988/K1393-faithful 的 A4f（`VIX²` multiplicative GARCH-X）在延長至
2026-07-10 的完整 OOS 上仍優於 GJR：A4f QLIKE `1.431558`、GJR
`1.515680`，相對改善 `5.550%`，canonical HAC-DM `t=+3.9656`。正號代表
`loss_GJR - loss_A4f > 0`，亦即 A4f 較佳。

這不是「不受規格影響的穩健顯著」。對兩個模型都增加 9 個 seeded starts 後，
完整 OOS 的 DM 只剩 `t=+3.0098`；canonical lag 13 剛過 `|t|>3`，lag 10
敏感度為 `2.9901`。因此 Paper 9 可保留「完整 OOS 點估計與預先指定 canonical
檢定仍支持 A4f」的方向性 headline，但必須揭露 optimizer / HAC 敏感性，不可寫成
廣泛穩健的顯著優勢。

## 特殊 provenance：orphaned compute

這份結果不是由 supervising agent 正常回傳。原 job 在 timeout 後被標為 failed，
但 agent 產生的 compute 子行程沒有一起被終止，並在 supervising agent 死亡約 24
分鐘後完成計算、寫下結果。產物後來由 commit `3ccaf6a11` 保存於
`agent/k1685-garchx-oos` worktree。

因此原始 `k1685_garchx_oos_extension_results.json` 的數字在收件前一律視為未驗證：

- 不採信 agent summary，只從 JSON 核對。
- 另跑 `k1685_parameter_audit.py`，獨立重算 primary 與 multistart 兩條完整 OOS
  路徑，逐次保存參數、收斂 start 數與 persistence。
- 原 JSON 的 `verdict="GO"` 是收件前 generator 的 raw verdict；修後 code 與本 README
  的最終裁決為 `GO_WITH_FRAGILITY_DISCLOSURE`。
- 收件修正只處理 provenance fail-closed、原子寫檔、裁決 gate 與圖表 anchor；沒有
  手改任何績效或檢定數字。

## Data & Methodology

| 項目 | 設定 |
|---|---|
| 方法論類型 | empirical forecast comparison |
| 資料來源 | yfinance `1.2.0`: SPY adjusted close、`^VIX` close |
| pinned snapshot | `data/k1685_spy_vix_snapshot.csv` |
| snapshot SHA256 | `eee7f9c62ce3ed3ee68d2bffeb3c9386fb8a6343e1a053379cfc89058518e3fb` |
| 原始期間 / 列數 | 2000-01-03～2026-07-10；6,669 列 |
| OOS | 2019-01-02～2026-07-10；1,890 trading days |
| estimation window | rolling 2,000 days |
| refit | 每 63 個 OOS steps |
| primary starts | 3 個 K988/K1393 canonical starts |
| robustness starts | 3 canonical + 9 seeded random starts；兩模型對稱增加 |
| seed | 42，且每次 refit 使用 `seed + t_idx` |
| forecast target | close-to-close conditional variance；以 `r_t²` 作 noisy proxy |
| primary loss | Patton QLIKE：`actual/pred - log(actual/pred) - 1` |
| inference | `volpred.stats.model_evaluation.dm_test(..., h=1)`；HAC lag `ceil(n^(1/3))` |
| multiple-testing gate | Harvey et al. (2016) 慣例 `|t|>3` |

`r_t²` 不是無噪音 latent variance；本實驗只宣稱 proxy-robust QLIKE 排名與 DM
比較，不宣稱直接觀察到真實條件變異數。A4f 與 GJR 都預測 daily
close-to-close variance，因此 target 對稱。

### 時序與 lookahead

預測日 `i` 的 training slice 是 `[i-W, i)`；one-step forecast 只讀
`r[i-1]` 與 `VIX[i-1]`，`r[i]` 只在 forecast 完成後進入 loss。所有 model input
讀取均由 `CausalView` 檢查，若讀到 origin day 或未來 index 會 raise；程式啟動時也會
先跑一個會故意觸發 guard 的 self-test。

## 核心結果

| 規格 / 樣本 | n | GJR QLIKE | A4f QLIKE | canonical DM t | p | 判讀 |
|---|---:|---:|---:|---:|---:|---|
| K1393 anchor，paper CSV，3 starts | 1,825 | 1.525163 | 1.432462 | +3.6122 | 0.000312 | A4f，過門檻 |
| 完整延長 OOS，3 starts | 1,890 | 1.515680 | 1.431558 | +3.9656 | 0.000076 | A4f，過門檻 |
| 完整延長 OOS，12 starts | 1,890 | 1.506443 | 1.437832 | +3.0098 | 0.002649 | A4f，僅高於門檻 0.0098 |
| 新增 65 日單獨 | 65 | 1.370685 | 1.333203 | +0.9120 | 0.365202 | 方向同，但不顯著 |

Pipeline gate 以 K1393 的 legacy kernel / bandwidth convention 精確重現
`t=3.6029009652`、兩個 QLIKE 與 `n=1825`，所有差值為零。Canonical DM 在同一
anchor 使用 lag 13，因此是 `t=3.6122`。

80 個 monthly endpoint scan 中沒有一個 t 值轉負；範圍為 `1.5786`～`3.9917`，
27 個高於 3。這是路徑描述，不是 80 次互相獨立的 confirmatory tests。

## 收斂與 stationarity 稽核

`k1685_parameter_audit.json` 逐次保存 30 個 primary refits 與 30 個 multistart
refits，且逐欄重現原 JSON 的 n、兩個 QLIKE、DM t/p 與 HAC lag。

| Audit path | GJR persistence range | A4f persistence range | 每次 refit 最少成功 starts |
|---|---:|---:|---:|
| primary 3-start | 0.912183～0.983849 | 0.820669～0.949559 | GJR 3；A4f 2 |
| symmetric 12-start | 0.946687～0.994075 | 0.595639～0.954607 | GJR 11；A4f 6 |

GJR 為了忠實復現 K1393，likelihood 本身沒有加入 persistence `<1` 的 hard bound；
本次 post-hoc full-population audit 證明所有實際選定解都 `<1`。這只驗證本次 pinned
run，不代表無約束的 generator 對任何新資料都必然定態。

## Data-integrity finding

Paper 9 的舊 CSV `paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv`
含 10 個重複日期（2026-05-04～2026-05-15，每日兩列）。一般
`sort_index + shift` 會把它們轉成假零報酬，並使下一列產生錯位 return；這段正好落在
K1391 新增的 41 日窗口內。K1391 的 sign reversal 因此同時混入 degraded A4f spec
與資料污染，不能當成 faithful extension 的反證。

本實驗不手改舊 CSV；修正必須回到 collector，按 date de-duplicate 並遵守 SPY
交易日曆。主程式現在會自行計算 snapshot 與 paper CSV SHA256，任一輸入漂移即
fail closed，不再只信任 sidecar 文字。

## 產物

- `k1685_garchx_oos_extension.py`：完整實驗與圖表 generator
- `k1685_garchx_oos_extension_results.json`：orphaned compute 的原始數字產物
- `k1685_parameter_audit.py` / `k1685_parameter_audit.json`：收斂、參數、persistence
  與數字重現 audit
- `k1685_codex_review.md`：收件前後的 primary-path review
- `data/`：pinned SPY/VIX snapshot 與 provenance
- `figures/`：endpoint sensitivity 與 cumulative loss differential

## 重現

使用既有 pinned snapshot，不要加 `--refetch`：

```bash
uv run python experiments/k1685/k1685_garchx_oos_extension.py
uv run python experiments/k1685/k1685_parameter_audit.py
```

第一支會重跑完整七路估計；第二支只重跑 full-OOS primary + multistart，專門驗證
收斂與 persistence。Results 與 parameter-audit JSON 均以同目錄 temp file 寫入、
重新 parse 後再 `os.replace`。

## 參考

- Engle, Ghysels, and Sohn (2013), GARCH-MIDAS long/short-run variance decomposition.
- Patton (2011), volatility forecast comparison robust to noisy variance proxies.
- Diebold and Mariano (1995), predictive accuracy comparison.
- Harvey, Liu, and Zhu (2016), multiple-testing-aware threshold for new factors.
- K988、K1391、K1393、K1027。
