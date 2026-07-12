# K1697 — taiwan-vt Table 2 rolling block：calendar-aligned fresh-snapshot 重跑

**Status**: complete（2026-07-12）
**Upstream**: `paper/taiwan-vt` P0-2（`EXECUTION.md`；`review_history/fable_deep_review_20260711/README.md` F2）
**Predecessor**: `experiments/paper2_taiwan_indiv_rolling_gamma`（本實驗解除其全部三個 caveat）

## 動機

body_v3.tex Table `tab:gamma` 的 rolling-window（w=2000）列 — Hon Hai 2317、MediaTek 2454、
Mega 2886、0056 ETF、TWII rolling 0.272、9-stock/10-security rolling 平均（0.054/0.060）、
footnote rolling ratios（5.0×/4.5×）— 只溯源到已刪除 K530 run 的 knowledge entry N121/N120，
**無存活 JSON、不可復現**（fable deep review 致命傷 F2）。

前作 `paper2_taiwan_indiv_rolling_gamma` 已確立「legacy 值不可復現」，但其 calendar alignment
受制於 stale 離線 snapshot：common_end 被 k1302 的 2383/2886 CSV 綁死在 **2025-01-22**，且
各檔混用 adj-close / raw-close 價格欄。fable review 明定：**採納前必須以 aligned snapshot 重跑**
— 即本實驗。

K1697 解除的三個 caveat：
1. **Stale common_end** → 全新 yfinance pinned snapshot（`auto_adjust=False`），common_end =
   **2026-07-09**（最新共同交易日）
2. **混用價格欄** → 全部證券統一 Adj Close log returns（canonical）+ raw Close 敏感度變體
3. **Single-start MLE** → 每次估計 = arch 預設起點 + **100 個 seeded 隨機起點**，取最高收斂
   log-likelihood（K1213 教訓），並記錄 basin 診斷

## 方法（與 K892 canonical 的關係）

Spec 完全沿用 K892 `rolling_w2000.last_window` 慣例：GJR-GARCH(1,1)、Constant mean、Normal
innovations、`arch` MLE on returns×100、rolling w=2000 取**最後一個** 2000-obs 窗口、robust
（Bollerslev–Wooldridge）t 值、persistence = α + 0.5γ + β。

差異點（全部顯式記錄）：
- **Log returns**（沿用前作；K892 用 simple pct_change — reconciliation 顯示同端點差異僅 ~0.007）
- **Calendar alignment**：全部 13 檔台股序列截斷到 common_end = 2026-07-09（typhoon 休市
  2026-07-10 的 placeholder 列已由過濾規則自動剔除）再取最後 2000 obs；各檔窗口同端點
  （起點 2018-04 前後，依各檔自身交易日曆）
- **Multistart**：101 起點/估計，seed 由 (ticker, variant) 決定性導出（BASE_SEED=1697）
- **無 lookahead 面**：γ 為窗口內 in-sample 描述性估計，非 forecast/signal；所有隨機程序固定 seed

### Reconciliation（證明差異來自端點，不是資料或程式）

把**新 snapshot** 截斷到前人的端點、換回前人的 convention 重估 — 全部精確命中：

| 檢查 | K1697 重算 | 對照值 | 來源 |
|---|---|---|---|
| TWII simple returns、端點 2026-04-05 | γ=0.2614 / t=3.32 | 0.2614 / 3.32 | K892 `rolling_w2000.last_window` |
| TWII log returns、端點 2025-01-22 | γ=0.1575 / t=2.57 | 0.158 / 2.57 | 前作 aligned |
| 2886 log returns、端點 2025-01-22 | γ=0.0539 / t=1.42 | 0.054 / 1.41 | 前作 aligned |
| TWII log returns、端點 2026-04-05（隔離） | γ=0.2685 / t=3.40 | — | log-vs-simple 僅貢獻 ~0.007 |

→ 新 snapshot 與舊資料源一致、pipeline 無 bug；canonical 數字的變動**純粹來自窗口端點前移
＋價格欄統一**。

## 資料

- `data/*.csv`：14 檔 pinned snapshot（OHLC + Adj Close + Volume，`auto_adjust=False`，
  2008-01-01 起，下載於 2026-07-12；`data/snapshot_manifest.json` 記錄逐檔下載時戳/版本/列數）
- Placeholder 過濾：Volume==0 且 O==H==L==C 的列剔除（TWSE 休市殘影；2026-07-10 全市場
  placeholder 即為此類）。0056 剔除 265 列，其中 **249 列集中在 2008**（早期資料 artifact），
  落在最終 2000-obs 窗口內僅 1 列（2024-01-15）— 對估計無實質影響。逐檔剔除數在 results JSON
  `data.per_ticker_cleaning`。
- 0050.TW 的 yfinance 歷史現起於 2009-01（非 2008-01）— 不影響 last-window 估計，如實記錄。

## 結果 — Table 2 rebind 對照表

Canonical = **adjclose 變體、端點 2026-07-09**。γ / t（robust BW）：

| 列 | Legacy（N121/N120，現行渲染值） | 前作 aligned（端點 2025-01-22） | **K1697 canonical（端點 2026-07-09）** | rawclose 敏感度 |
|---|---|---|---|---|
| TWII rolling | 0.272 / 3.18 | 0.157 / 2.57 | **0.198 / 1.86** | 0.198 / 1.86 |
| 0050.TW | （表列 full-sample 0.097/3.60，canonical K892，不受影響） | 0.079 / 1.90 | **0.105 / 2.01** | 0.104 / 1.98 |
| TSMC 2330（參考） | （表列 full-sample 0.052/3.98，不受影響） | — | **0.040 / 1.28** | 0.039 / 1.24 |
| Hon Hai 2317 | 0.052 / 1.14 | 0.015 / 0.45 | **0.016 / 0.42** | 0.010 / 0.25 |
| MediaTek 2454 | 0.044 / 0.96 | 0.027 / 1.22 | **0.017 / 0.80** | 0.020 / 0.55 |
| Elite Material 2383 | （僅入平均） | 0.034 / 0.77 | **0.026 / 1.03** | 0.025 / 1.03 |
| Mega Financial 2886 | 0.179 / 2.42 | 0.054 / 1.41 | **0.171 / 1.58** | 0.184 / 3.32 |
| Chunghwa 2412 | （僅入平均） | −0.041 / −0.74 | **−0.030 / −0.55** | −0.014 / −0.11 |
| Fubon 2881 | （僅入平均） | 0.001 / 0.03 | **0.008 / 0.26** | −0.024 / −0.83 |
| Cathay 2882 | （僅入平均） | 0.026 / 0.65 | **0.024 / 0.57** | 0.008 / 0.17 |
| Yuanta 2885 | （僅入平均） | 0.063 / 1.12 | **0.025 / 0.51** | −0.027 / −0.44 |
| CTBC 2891 | （僅入平均） | 0.038 / 1.08 | **0.031 / 0.67** | 0.016 / 0.35 |
| 0056.TW | 0.112 / 1.87 | 0.202 / 2.89 | **0.222 / 2.95** | 0.146 / 1.92 |
| SPY（參考） | （表列 0.211/5.79，legacy，M3 另案） | — | **0.200 / 4.09** | 0.193 / 4.03 |
| **9-stock 平均** | 0.054 | 0.024 | **0.032** | 0.022 |
| **10-security 平均（含 0056）** | 0.060 | 0.042 | **0.051** | 0.034 |
| **ratio（TWII base，9-stock）** | 5.0× | 6.5× | **6.2×** | 9.0× |
| **ratio（TWII base，10-security）** | 4.5× | 3.8× | **3.9×** | 5.8× |

K1697 canonical 排序（rolling γ，高→低）：**0056（0.222）> TWII（0.198）> 2886（0.171）>
0050（0.105）> TSMC（0.040）> 其餘個股（0.031 ~ −0.030）**。5% 顯著者僅 0056（t=2.95）、
0050（t=2.01）、SPY（t=4.09）；TWII rolling t=1.86 僅 10% 邊際。

## 敘事翻轉清單（rebind 時必須同步改寫的正文）

1. **TWII rolling 0.272/3.18 死亡（再確認）**：fresh aligned 端點下 γ=0.198、**t=1.86 掉出 5%
   顯著**。§3.1「statistically significant (γ=0.272, t=3.18)」的 rolling 敘事不可保留；顯著的
   槓桿效應宣稱應改掛 canonical full-sample（0.105/5.31，provenance 實驗）。
2. **0056「second-highest」死亡**：0.222 = **全場最高，高於 TWII index（0.198）**。兩個可復現
   aligned 端點（2025-01、2026-07）下 0056 皆高於 TWII rolling — 此排序 robust。§3.2
   「Sensitivity to 0056.TW inclusion」段的「second-highest / inclusion bias 是 conservative
   （方向上仍成立：納入 0056 使 ratio 6.2×→3.9×，但幅度遠大於舊述）」須整段重寫。
3. **rolling 平均與 footnote ratios 全部換值**：9-stock 0.054→0.032、10-security 0.060→0.051、
   ratio 5.0×→6.2×、4.5×→3.9×（TWII base = 可復現 0.198，非 legacy 0.272）。
4. **2886 的 0.179/2.42**：點估計巧合地接近 K1697 的 0.171，但 t=1.58 不顯著，且端點敏感度極大
   （2025-01 端點 = 0.054）— 不可讀作「legacy 復活」。
5. **顯著性版圖改變**：rolling 列中只剩 0056 與 0050 過 5%。個股 rolling γ 全部不顯著（與
   canonical full-sample 結論一致：個股層級槓桿效應弱）。

**不受影響**：paper 主線 amplification 故事（canonical full-sample γ̄=0.027、TAIEX 0.114、
ratio 4.2–4.7×、K1370 bootstrap CI [2.28, 6.58]）— K1697 只重建 rolling 顯示層。

## 關鍵方法論發現 — rolling last-window γ 的端點敏感度

同一 spec 下 TWII rolling γ：0.157（端點 2025-01-22）→ 0.269（2026-04-05）→ 0.198
（2026-07-09）— 端點移動下擺盪 0.11，其中 **2026-04 → 2026-07 三個月就掉 0.07**。2886 更劇烈：
0.054（2025-01）↔ 0.171（2026-07）。

含義（給 P0-1/P0-2 rebind 決策）：
- legacy 0.272 落在某些端點的可達範圍內（2026-04 端點 log-ret 給 0.2685），但 vintage 不明、
  無 JSON，**untraceable 判定不變**；重點是 rolling last-window 本質上不適合當 headline —
  任何單一端點的 rolling 值半年內就會漂移。
- 建議 rebind 走向（paper_decision，主線程裁決）：(a) rolling 列全部換 K1697 值＋明註 as-of
  端點與敏感度 caveat；或 (b) Table 2 直接砍 rolling variant、只留 canonical full-sample 列，
  rolling 降級為 sensitivity 一句話。兩案皆需同步重寫 §3.2 0056 段。
- Table 2 註「Newey–West HAC」與實際估計量不符：rolling 列 t 值實為 arch robust
  （Bollerslev–Wooldridge）MLE t — rebind 時必須修正註解措辭（前作已標記同一問題）。

## Multistart 診斷（K1213 檢查）

全部 28 個估計（14 檔 × 2 變體）：**101/101 起點收斂、全部單一 basin**（n_at_best_basin ≈
101/101；預設起點與最佳 basin 一致）— 本問題不存在 K1213 型 multistart fragility；per-fit
診斷在 results JSON `multistart` 欄。

## 限制

1. Rolling last-window γ 是移動標靶的快照 — 上表 canonical 值綁定端點 2026-07-09，引用時必須
   帶 as-of 日期。
2. t 值為 arch robust（BW）MLE t，非 NW-HAC（同前作；表註措辭待 rebind 修正）。
3. Adj Close 序列的除息調整因子會隨未來配息回溯改變 — 這正是 snapshot pinning 的理由；復現
   一律讀 `data/` 內 pinned CSV（腳本 Phase 1 只在 CSV 缺失時觸發下載）。
4. rawclose 敏感度顯示高股息金融股（2881/2885 變號、2886 t 值 1.58↔3.32、0056 0.222↔0.146）
   對價格欄選擇敏感 — canonical 取調整後價格（除息日的假負報酬會污染不對稱性估計），
   與 K892/前作的 adj 慣例一致。
5. SPY 列僅供參考（不屬台股 rolling block；表中 SPY 為 legacy 值，M3 另案 canonical 化）。

## 檔案

- `k1697_rolling_gamma_rerun.py` — 完整 pipeline（snapshot → clean → align → multistart MLE →
  comparison → reconciliation）
- `k1697_results.json` — 全部估計、multistart 診斷、對照表、reconciliation、資料清理統計
- `data/` — 14 檔 pinned CSV + `snapshot_manifest.json`

## Codex review

（見文末補記）
