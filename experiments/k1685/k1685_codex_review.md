# K1685 Codex 收件審查

- 審查時間：2026-07-12T05:30:00+08:00
- 審查者：Codex primary path（主線程）
- 獨立覆核：fresh-context code reviewer + fresh-context result auditor
- 最終 code/package verdict：**PASS**
- 最終 research verdict：**GO_WITH_FRAGILITY_DISCLOSURE**

## 審查範圍

本次不是抽查 suspect subset，而是覆蓋：

- `k1685_garchx_oos_extension.py` 的模型、rolling state、時序、loss、DM、裁決、
  provenance 與寫檔路徑。
- 原始 results JSON 的 11 個 DM reports、80 個 endpoint records 與所有 top-level
  audit blocks。
- `k1685_parameter_audit.json` 的完整 60 個 refits：primary 30 + multistart 30。
- 每個 refit 的兩組 raw params、persistence、成功 starts；不是只信 summary min/max。
- snapshot 與 paper CSV 的實際 digest、列數、日期與 duplicate invariant。
- 兩張圖；endpoint 圖以原尺寸視覺核對。

Artifact digests：

| Artifact | SHA256 |
|---|---|
| orphaned results JSON | `1fd7fd8488cdfa2c66c54acc07459d9d643303d60dc1b51c953b3b2f99c97ec3` |
| parameter audit JSON | `0e4fc56badfe208f965011f0d8e37f4ce3d852db930163557a14d12121bcacf4` |
| pinned snapshot | `eee7f9c62ce3ed3ee68d2bffeb3c9386fb8a6343e1a053379cfc89058518e3fb` |

## 修前 findings

1. **BLOCKING — 無收斂 / persistence 證據**：orphaned results 沒保存 fitted params；
   GJR 為忠實沿用 K1393 而沒有 hard stationarity constraint，無法從原 JSON 證明
   選定解皆 `<1`。
2. **BLOCKING — verdict 沒 gate multistart**：原 `GO` 只看 primary full-OOS；即使
   multistart 不過門檻也會宣告可出稿。
3. **HIGH — provenance 只信 sidecar**：主程式未自行計算 snapshot / paper CSV
   digest；輸入被換掉時仍會記錄舊 SHA。
4. **MEDIUM — 圖表 anchor 標錯**：圖上寫 2026-04-07，實際取的是最近的 monthly
   endpoint 2026-03-31。
5. **MEDIUM — results 非原子寫入**：supervisor/child orphan failure class 可能留下
   truncated JSON。
6. **PACKAGE — README 缺失**：不符合實驗三件套。

## 修正與驗證

### 1. Convergence / stationarity full-population audit

新增 `k1685_parameter_audit.py`，只重跑兩條 headline-relevant full-OOS path，逐次
保存參數與 optimizer diagnostics。Audit 的 `t_idx` 都是
`0, 63, ..., 1827`，兩路各 30、無缺漏或重複。

| Path | GJR persistence | A4f persistence | 每次最少成功 starts |
|---|---:|---:|---:|
| primary | 0.912183–0.983849 | 0.820669–0.949559 | 3 / 2 |
| multistart | 0.946687–0.994075 | 0.595639–0.954607 | 11 / 6 |

60 個 refits 的 raw params 重算 persistence 與 JSON 欄位最大差異為 0；selected
stationarity violation 為 0。部分 A4f starts 未收斂已如實保存，但每個 model/refit
至少有一個成功 start，且被選參數皆 finite。

### 2. 數字與 DM

- 完整 OOS：2019-01-02～2026-07-10，`n=1890`。
- Primary：GJR QLIKE `1.5156804461`、A4f `1.4315581375`、改善 `5.5501%`；
  canonical DM `t=+3.965576`、`p=0.00007595`、HAC lag 13。
- Multistart：DM `t=+3.009752`、`p=0.00264922`、lag 13。
- K1393 legacy anchor `t=3.6029009652`、兩個 legacy QLIKE 與 `n=1825` 精確
  重現，差值為零。
- Parameter audit 逐欄重現原 results 的 n、兩個 QLIKE、DM t/p、HAC lag；所有
  checks 為 true。
- DM 方向為 `d = loss_GJR - loss_A4f`；正 t 的解讀正確。

### 3. 生成流程

- 主程式現在計算 snapshot 與 paper CSV SHA256，並驗證 snapshot row/date/duplicate
  invariant；假 sidecar hash 的 negative test 會 raise。
- `GO` 同時 gate primary 與 multistart；本次數字對應
  `GO_WITH_FRAGILITY_DISCLOSURE`。
- Endpoint 圖直接取 exact 2026-04-07 report，不再拿 03-31 月末點冒充；重生後
  視覺核對正常。
- Results 與 parameter-audit JSON 都走同目錄 temp → flush/fsync → parse →
  `os.replace`。

### 4. 測試

- `py_compile`：PASS。
- `scripts/tests/test_dm_hac_lag_ratchet.py`：`3 passed`。
- 兩份 JSON `json.tool`：PASS。
- CausalView positive/negative self-test：PASS。
- Provenance real inputs + tampered-hash negative test：PASS。
- `git diff --check`：PASS。
- Parameter audit：exit 0 / `overall_status=PASS`。

## Blind spots 與殘餘 caveats

- Parameter audit 重用同一 generator 的模型與 DM function；它不是第二套獨立
  econometric implementation。它能驗證 orphaned output 的 deterministic
  reproducibility、收斂與 stationarity，不能排除兩條路徑共有的理論 bug。為此另做
  了 code-level state/lag/target review。
- 原始 results JSON 保留收件前 raw `verdict="GO"`，不手改歷史產物；機器下游若只
  讀該欄仍可能過度解讀。Knowledge 與 paper tracker 必須使用本 review 的 final
  verdict。
- Multistart t 只比門檻高 `0.0098`，lag 10 sensitivity 為 `2.9901`；anchor
  multistart亦未過 3。這是實質脆弱性，不是 rounding trivia。
- GJR generator 仍沒有 hard persistence bound，僅證明本次 pinned run 的 60 個
  selected fits 定態；新資料重跑仍須保留 audit。
- 新增 65 日單獨 DM `t=0.9120`、p=.365；完整 OOS 的支持來自累積長樣本，不能寫成
  「近期資料本身再次顯著確認」。

## 最終裁決

**PASS 收件。** 數字、時序、canonical DM/HAC、anchor replication、完整參數 audit
與 package 三件套均通過。Paper 9 的方向性 A4f headline 可存活，但只以
`GO_WITH_FRAGILITY_DISCLOSURE` 進入後續 P0 修稿；不得省略 optimizer/HAC 敏感性，
也不得再用含重複日期的 paper CSV 延長樣本。
