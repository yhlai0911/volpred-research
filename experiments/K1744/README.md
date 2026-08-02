# K1744 — Latin America private-credit funding-gap transmission

## 結論

**INCONCLUSIVE / INSUFFICIENT_DATA**。這不是科學 null，也不是先前失敗 job 的成功續接。前一個 `agent-brief-k1744-552fde40` 在研究開始前即被 quota 拒絕，分類固定為 **ZERO_SALVAGE**；本 fresh-worktree retry 沒有讀取或採用舊 worktree 的程式、資料或 artifact（JSON: `/recovery`、`/conclusion`）。

Proxy feasibility gate 在任何 ETF outcome request 之前失敗，因此本輪 outcome rows 為 **0**（JSON: `/data/sample/outcome_rows`），沒有估計值、raw p-value 或 Holm-adjusted p-value（JSON: `/estimates`）。精確原因：The preregistered Private Debt Investor record-level enumeration/export was not accessible: the inspected public response required sign-in/account creation and exposed neither provider record IDs nor historical version/as-of timestamps. Public sponsor pages supplied isolated examples, not a complete regional fund universe. Therefore missing search hits cannot be coded as zero-event months, event-count thresholds cannot be evaluated, and no point-in-time monthly proxy can be constructed without selection/backfill bias.

## 動機與差異化

ECLAC 報告拉丁美洲與加勒比海每年約有 **USD 650 billion** 的發展融資缺口（JSON: `/literature/institutional_motivation/eclac_annual_financing_gap_usd_billion`）。CFA Institute 2026 專文把 LatAm 私募信貸描述為結構化融資、基礎建設、中型企業與家族／fintech 成長融資，而非美國典型 LBO direct lending；同文指出區域私募信貸占企業放款低於 **1%**，2025 年 LatAm 策略募資約 **USD 800 million**（JSON: `/literature/institutional_motivation/cfa_latam_private_credit_share_of_corporate_lending_upper_bound_pct`、`/literature/institutional_motivation/cfa_latam_fundraising_2025_usd_million`）。這些 2025–2026 數字只作 institutional motivation，絕不回填成歷史可得訊號。

K1744 與通用 BDC spillover 不同：K1332/K1499 使用上市 BDC 價格壓力，K1487 使用廣義 GDELT private-credit news；K1744 預註冊的 estimand 是 **LatAm 區域資本供給／funding-gap transmission**。ILF、EWW、ECH、EPU、EWZ、CEW、EMLC、EMB 與 UUP 共 **9** 檔只會是流動市場 proxy，不是私募信貸資產（JSON: `/design/fixed_market_universe_count`、`/design/fixed_market_universe`）。即使日後可執行，結論也只能是 predictive/associational，不能稱因果。

## Proxy preregistration 與 data provenance

Primary exposure 在 outcome inspection 前已鎖定（`proxy_preregistration.json` SHA-256 見 JSON: `/inputs/proxy_preregistration/sha256`）：每月完整枚舉具有 LatAm 專屬或至少半數 LatAm mandate 的 private-credit/private-debt fund **final close**，以 legal fund name + vintage + close date 去重，再取 `log1p(count)`。枚舉框必須是帶 provider record ID、export-as-of、版本／更新時間與檔案 SHA-256 的 PDI record-level export；逐筆 point-in-time 時間則必須回到 sponsor 官方 final-close release。只有年月、回溯報表日期或今天搜尋到的文章都不合格。

Feasibility success 需要至少 **36** 個 distinct events、**24** 個 nonzero months 與 lag 後至少 **60** 個 full-basket common months（JSON: `/proxy/feasibility/thresholds`）。本輪三項 observed count 都是 `null`，代表不可測，不代表零（JSON: `/proxy/feasibility/observed`、`/proxy/feasibility/unknown_counts_are_not_zero`）。

`raw_cache_manifest.json` 保存每個官方／學術頁面的直接 URL、publication/release date、實際 access timestamp、HTTP status、response SHA-256 與 byte size（JSON: `/inputs/raw_cache_manifest`；逐來源見 `/literature/primary_sources`）。未保存第三方全文；因沒有合格 record-level proxy export，也沒有可合法宣稱的 raw proxy rows。

## 預註冊方法（若 gate 通過才會執行）

- 月頻 forecast origin：月末交易日收盤；outcome month 的 exposure 只能來自前一月，程式固定由 `prepare_exposure_for_outcome()` 明確執行 `.shift(1)`（JSON: `/design/explicit_signal_lag`）。
- 三個分離 channel：equity（ILF/EWW/ECH/EPU/EWZ）、FX/local bond（CEW/EMLC）、hard-currency bond（EMB）；UUP 只作 USD factor（JSON: `/design/channels`）。
- 三個 outcomes：次月 realized variance、次月最差日 left-tail loss、60-trading-day UUP beta 絕對值的次月變化（JSON: `/design/outcome_lock/targets`）。
- Baseline 與 candidate 用完全相同資訊集、lag 與 common rows；RV 使用 AR/HAR-family baseline，其他 target 使用對應 AR(1) baseline（JSON: `/design/outcome_lock/baseline`、`/design/outcome_lock/candidate`）。
- Primary family 固定為 **9** cells，Holm step-down 校正整個 family；HAC/DM bandwidth 不得退化成 `h-1`，必須用 repository canonical bandwidth 並報 sensitivity（JSON: `/design/primary_family`）。所有 permutation/bootstrap 路徑固定 **seed=42**（JSON: `/seed`）。
- 價格診斷原應報 ETF inception、delisting、missingness、duplicate、timezone、extremes、revision 與 full-basket common-sample loss；因 proxy gate 先失敗，這些全部標 `NOT_RUN_BY_FEASIBILITY_CONTRACT`，沒有用 forward fill 掩蓋（JSON: `/data/ticker_diagnostics`）。

## Success / null / blocked criteria

`SUPPORTED` 必須先通過 proxy gate，且同一 outcome family 至少兩個 channel 出現 expected-sign、Holm-adjusted p<0.05 的 primary effect；secondary robustness 不得救援 primary failure。`NULL` 只可在 proxy 可行且完整 **9**-cell family 真正估計後成立。任何 provenance、complete-enumeration、event-count 或 common-sample requirement 失敗都只能是 `INCONCLUSIVE`（完整 machine policy: `proxy_preregistration.json` `/verdict_policy`；本輪結果: `K1744_results.json` `/conclusion`）。

## Primary sources

- CFA Institute, *How private credit investment is filling a funding gap in Latin America*, 2026-06-04: https://www.cfainstitute.org/insights/articles/latin-america-private-credit-investment-growth
- Preece and Wilson, CFA Institute RPC, *Understanding the Growth of Private Markets*, 2026-06-22, DOI 10.56227/26.1.12: https://rpc.cfainstitute.org/research/reports/2026/understanding-growth-private-markets
- ECLAC, financing-for-development release, 2025-07-03: https://www.cepal.org/en/pressreleases/faced-financing-development-challenges-latin-american-and-caribbean-countries-need
- Matvos, Piskorski, and Seru, NBER W34991, 2026-03-18, DOI 10.3386/w34991: https://www.nber.org/papers/w34991
- Buchak, Matvos, Piskorski, and Seru, NBER W32176, 2024-02-27, DOI 10.3386/w32176: https://www.nber.org/papers/w32176
- Corsi, *A Simple Approximate Long-Memory Model of Realized Volatility*, DOI 10.1093/jjfinec/nbp001: https://doi.org/10.1093/jjfinec/nbp001

## 結果與限制

No empirical run occurred. Primary estimate、raw p-value、adjusted p-value 與 robustness direction 都不存在（JSON: `/estimates/primary_adjusted_p_value`、`/robustness/direction`）。此 artifact 的有效發現只限於：目前可存取來源不足以建立 preregistered complete/PIT proxy；不能推論 funding-gap transmission 存在、為零或方向相反。

主要限制完整列於 JSON `/limitations`。沒有畫圖，因為沒有有效 empirical sample；以文字框或假圖替代會違反研究誠實。
