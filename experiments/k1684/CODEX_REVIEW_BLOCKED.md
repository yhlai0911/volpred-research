# K1684 Codex review — BLOCKED（R1 的歷史紀錄）

> [!NOTE]
> **本文件描述的是 R1（2026-07-12 被 BLOCKED 的那一版），保留作為歷史紀錄與 rerun 的驗收清單。**
> R2 canonical 重跑與 R3 primary-review rescue 已完成。歷史 R2 收據見
> [`k1684_rerun_r2_receipt.json`](k1684_rerun_r2_receipt.json)，R3 收據與 primary Codex review 見
> [`k1684_rerun_r3_receipt.json`](k1684_rerun_r3_receipt.json)／[`CODEX_REVIEW_R3.md`](CODEX_REVIEW_R3.md)。
> 新結果與新裁決（`H2_UNSUPPORTED`，**不是** R1 的 `H2_REJECTED`）見 [`README.md`](README.md)。
> 底下「已核對、可作為 rerun anchor 的原始數字」**全部是 R1 的數字**；引用時務必標明是 R1。

- Review date: 2026-07-12
- Reviewer: `/root/k1684_orphan_review`
- Reviewed commit: `cf614a11f`
- Disposition: 保留原始產物作為可重現的失敗實驗；禁止將現有 `H2_REJECTED`
  寫入 knowledge、feed 或 paper narrative。

## Blockers

1. **Headline DM 依賴不穩定的 4-start GJR。**
   `experiments/k854/k854_common_sample_var.py` 的 `fit_gjr` 只有 4 個 starts；K1684
   自己的 perturbation probe 顯示 GJR sigma 最大漂移 29.0277%。在沒有
   >=100 starts、optimizer convergence、likelihood basin 分佈前，aligned-target DM
   `t=+2.3285` 不能承擔裁決。

2. **RV 建構未證明完整含隔夜。**
   K854 分開累加 PM night、AM night 與 day-session returns，會漏掉 PM->AM、
   05:00->08:45 與 13:45->15:00 的 session jumps。「40/40 日期戳正確」不等於
   close-to-close variance 完整。資料仍只用 `TX1`，也違反 experiment preamble
   的「全 TX 合約中每日依成交量選 active contract」規則。另需處理
   TX 13:45 與 ETF 13:30 close 的 information-set 重疊。

3. **`implied_c` 識別與 CI 有誤。**
   `Phi^-1(alpha)/Phi^-1(pi_hat)` 只能在明確的 Normal scale 假設下解讀，
   不能直接套到 CF / HistSim 後以 `|delta c|<0.10` 宣稱純尺度。該映射對
   violation rate 是遞增，原程式卻當成遞減，造成 154 格
   `implied_c_lo95 > implied_c_hi95`；HAR+CF 1% 的 JSON 例子為
   `1.49463 > 1.15676`。

4. **Placebo 會實質改變 GJR。**
   GJR scale factor 為 1.12556，GJRf+CF 5% 由 36/450 FAIL 變成 27/450 PASS；
   因此不能寫成「校準機器沒有動到正確模型」。三個 estimator 也共用
   同一批 r-squared / RV，不是統計上獨立的三份證據。

5. **Gate 與報告口徑過強。**
   Aligned DM `|2.3285|<3`；HAR-a vs HAR `|2.5406|<3`，兩者都未過 Harvey
   門檻。`decide_gate()` 文字說 leg 2 需 GJR PASS，實作卻未檢查。
   `sens_theta_short` 因共同 mask 只剩 n=377，與 primary n=436 不是同樣本。
   尚缺 experiment preamble 要求的 1%/5%、IS/OOS VaR + ES 與 joint VaR-ES loss。

6. **Results 不是原子寫入。**
   原程式直接 `open(final, "w")` + `json.dump`，必須改成 tmp -> `json.load`
   驗證 -> `os.replace`。

## 已核對、可作為 rerun anchor 的原始數字

- TX RV target: HAR 0.1004268 vs GJR 0.2080662；DM -5.1291。
- 0050 r-squared target: HAR 1.8879339 vs GJR 1.6271740；DM +2.3285,
  p=0.02034，但未過 Harvey。
- HAR-a 1.6281438 vs GJR 1.6271740；DM +0.0307, p=0.9755。
- HAR+CF 1%: 17/450 = 3.7778%；HAR-a+CF: 7/450 = 1.5556%，Kupiec
  p=0.2734，Basel yellow，Trinity FAIL。
- Scale estimates: a=1.35362、b=1.34864、c=1.20381、placebo=1.12556。
- Lookahead perturbation audit: 30/30 passed；seed=20260712。
- K854 replication: 11/14 = 78.57%，不是完全複製。

## Rerun acceptance gate

1. 以全 TX 資料每日選成交量最大的 active contract，並以連續 tick path
   納入所有 session boundary jumps；明確封住 13:30/13:45 information set。
2. GJR 至少 100 starts，保存 convergence、objective 與 basin distribution；以 robust fit
   重算所有 headline QLIKE / DM / VaR / ES。
3. 修正 CI 單調性；`implied_c` 僅在分佈假設可識別的 cell 中解讀，
   用 bootstrap / sensitivity 而非未檢定的 `0.10` 閾值區分 scale 與 shape。
4. Placebo 必須以與 HAR 同樣的基準與口徑完整報告，不允許用
   「near 1」取代檢定。
5. DM 正式結論用 Harvey `|t|>3`；每個 sensitivity 使用 pairwise common mask
   並報 n。
6. 同時報 1%/5%、IS/OOS VaR + ES、Fissler-Ziegel joint loss；results 原子寫入。
7. 重跑後只能用新 JSON 數字修改 README，並重新獨立 Codex review；PASS 後
   才允許寫 knowledge 或決定 paper route。
