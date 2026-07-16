# K1707 — 選擇權競價效益在壓力期是否崩解

## 預註冊狀態

本 README 在正式執行 `K1707.py` 前固定研究問題、資料充分性 gate 與成功標準。程式必須先通過 source-level Codex review；若 gate 不通過，不估 confirmatory interaction，也不把 pseudo-data 描述統計包裝成市場實證。

## 動機

Khan、Hendershott 與 Riordan（2026）發現選擇權 price-improvement auction 平均帶來較高 price improvement、較低 effective spread，但競價本身的 bidder competition 並不普遍。K1707 問的是另一個問題：這項平均 execution-quality benefit 在事前已知的市場壓力狀態是否縮小。

這與 K1341 的股票指數重組日 auction proxy、以及 `research_friday_triple_witching_closing_auction_concentra` 的日內收盤競價 proxy 不同；本題使用作者公開的選擇權交易結構 pseudo-sample，直接辨識 `AUCTION_IND`、price improvement、effective spread 與 multiple-bidder 欄位。

## Data & Methodology

### 作者資料

- 來源：Harvard Dataverse，`doi:10.7910/DVN/LMB13N`，檔案 `opra_pseudo-2.sas7bdat`。
- 授權：CC0 1.0。
- 官方 MD5：`f15b6286a6954f059bb59c31227eeb66`。
- 理想資料：完整且有真實 timestamp、option symbol 與 OPRA quote/trade history 的作者原始資料。
- 實際 proxy：作者刻意縮小、匿名化並對各變數獨立加噪的 pseudo-data。作者 README 明說它不能重現論文結果，日期與時間也不同於原始資料。

因此本研究的最高口徑是 `replication-sample stress diagnostic`；它不能證明真實選擇權市場的壓力期因果效果。

### 壓力訊號

- 來源：FRED `VIXCLS`。
- Frozen CSV SHA-256：`cc3575202272b4cf18a43b4ab95fc6cabd82195e224999a2da39337341bffb78`；不同 bytes 一律中止。
- 每個 pseudo calendar date 只使用前一日結束前已知的 VIX close；程式中明確建立 `signal = VIXCLS.ffill().shift(1)`。
- confirmatory high-stress 定義固定為 `signal >= 30`，不得看完樣本後改分箱。

### Data-support gate

confirmatory `auction × high_stress` interaction 只有在以下條件全部滿足時才執行：

1. 至少 80 個 distinct pseudo dates；
2. 至少 30 個 `VIX>=30` dates；
3. 至少 10 個 distinct underlying symbols；
4. pseudo date 中週末占比為 0。

任一失敗即判 `INSUFFICIENT_STRESS_SUPPORT`。仍可報告全樣本 auction/continuous 描述統計，但因作者明說 timestamps 已改動，不估任何 VIX slope 或 p-value、不得稱 null，也不得寫入 knowledge.json 的 PASS-family 結論。

### Outcomes

- `PIMP_C`：price improvement（cents），越高越好。
- `EffectiveSpread_C`：effective spread（cents），越低越好。
- `EQ`：effective/quoted spread ratio，越低越好。
- `MULTIPLE_IND`：auction-only 多 bidder rate，與 auction/continuous benefit 分開報告。
- dispersion：每個 pseudo date × auction cell 的 trade-level outcome 標準差。

描述性的 auction benefit 定義為：

- price improvement：`auction - continuous`；
- effective spread / EQ / dispersion：`continuous - auction`。

正值表示 auction execution quality 較佳。全樣本 benefit 直接用全部可用 pseudo trades 的 pooled sufficient statistics 計算，不對 pseudo dates 等權。完整 raw date roster（包括 outcome 全缺的日期）才用來對接 VIX 與稽核 stress support；VIX 不進入描述效果產物。

## Lookahead policy

- VIX 必須 `.shift(1)`；同日 VIX 不可解釋同日交易品質。
- pseudo timestamp 不是作者真實 timestamp，故不得宣稱 point-in-time 原始市場 replication。
- 隨機程序固定 `seed=42`；本次若 support gate 失敗，不啟動 permutation/bootstrap。

## 成功標準

- 完成三件套：README、`K1707.py`、`K1707_results.json`，另含 frozen aggregate panel、source manifest 與至少一張真圖。
- source checksum、列數、日期、標的數、週末日期與 VIX support 可機械重算。
- 若 gate 通過：才估預註冊 interaction，按 outcome family 做 Holm 校正，placebo 與 date-level randomization inference 至少 1,000 次。
- 若 gate 不通過：完整交付 adequacy audit，verdict 必須是 `INSUFFICIENT_STRESS_SUPPORT`，不把未拒絕寫成「效果不存在」。

## 文獻與官方來源

1. Khan, S. A., Hendershott, T., & Riordan, R. (2026). “Option Auctions.” *Review of Financial Studies*, 39(3), 783–834. DOI `10.1093/rfs/hhaf043`.
2. Bryzgalova, S., Pavlova, A., & Sikorskaya, T. (2023). “Retail Trading in Options and the Rise of the Big Three Wholesalers.” *Journal of Finance*. DOI `10.1111/jofi.13285`.
3. Anand, A., & Muravyev, D. (2024). “Does Internalization Impact Quote Competition?” SSRN `4891227`.
4. Battalio, R. H., & Jennings, R. H. (2024). “On the Potential Cost of Mandating Qualified Auctions for Marketable Retail Orders.” *Journal of Investing*, 33(1), 69–99. DOI `10.3905/joi.2023.1.287`.
5. Cboe. “US Options Exchange Crossing Orders — Automated Improvement Mechanism.”
6. Federal Reserve Bank of St. Louis. FRED series `VIXCLS`.

## 執行

```bash
uv run python experiments/k1707/K1707.py
```

大型 Dataverse raw file 放在 gitignored 的 `storage/cache/k1707/`；若不存在，程式會從 pinned datafile ID 下載並驗 MD5。可提交的 aggregate panel 足以重算本次 adequacy audit 與描述統計。

## 結果（2026-07-16）

科學 verdict：`INSUFFICIENT_STRESS_SUPPORT`。公開 pseudo-data 有 1,161,488 筆，其中 auction 384,580 筆（33.11%），但只有 16 個 pseudo dates、3 個匿名標的、0 個 `VIX>=30` dates，且 6 個日期落在週末。四項預註冊 support gate 因而全數失敗；confirmatory `auction × high_stress` interaction 未執行。

全樣本 pooled pseudo-data 描述量顯示：price improvement benefit 4.909 cents、effective-spread benefit 5.242 cents、EQ benefit 0.396，auction-only multiple-bidder rate 5.07%。這些數字只描述經獨立加噪且縮小的公開檔，不能當作真實 OPRA、市場壓力效果或 null evidence。

兩次完整重跑的 results JSON、aggregate panel、manifest、frozen VIX 與兩張 PNG SHA-256 全部一致。若未來取得真實 timestamp 的 OPRA 樣本，只有在至少 80 個交易日、30 個事前 `VIX>=30` 日與 10 個標的都滿足後，才可啟動預註冊 interaction inference。
