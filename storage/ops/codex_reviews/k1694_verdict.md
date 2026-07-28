## 1. Bootstrap

橫截面重抽機制已修好：

- 每次抽到某月份，該月所有商品列會一起保留，確實維持 month-level cross-sectional block。
- `k = 0..149` 是每次抽樣位置的唯一整數標籤；同一原始月份被重抽多次也不會發生 entity-time index collision。
- `n_boot = 2000/2000` 證明 estimator 現在確實有執行。

但 headline CI 仍不成立：

- 主 spec1 包含時間趨勢 `t`：[K1694.py:472](/Users/yhlai0911/volpred-research/experiments/K1694/K1694.py:472)。
- Bootstrap RHS 省略 `t`：[K1694.py:521](/Users/yhlai0911/volpred-research/experiments/K1694/K1694.py:521)。
- 主模型使用 3,293 列；bootstrap 使用 3,300 列。原因是主模型額外要求 `rv_z` 非空，而 bootstrap 沒有；同時 `NaN > median` 會讓缺少 RV 的 `highvol` 被錯標成 0。

唯讀重算顯示：

- 現有 bootstrap spec/sample point：`3.5093e-04`
- 同 bootstrap sample 加回 `t`：`3.2834e-04`
- 主 sample、不含 `t`：`3.3285e-04`
- 真正主 spec1：`3.1464e-04`

所以 [K1694_results.json:346](/Users/yhlai0911/volpred-research/experiments/K1694/K1694_results.json:346) 的 CI 不是 reported primary coefficient 的 CI，卻被寫進 `primary_interaction.bootstrap_ci95`。這是阻擋 PASS 的規格錯配。

此外，現行做法是 IID month-cluster bootstrap：保留同月橫截面，但破壞月份間序列相關。若「block bootstrap」意指處理 FCM 高自相關，則應改為 consecutive moving/stationary block；否則必須明確稱作 month-cluster bootstrap。

## 2. Lookahead／lag

`merge_asof(... direction="backward")` 相對於合成的 `avail_date` 確實不會選到晚於 outcome month-end 的資料，因此機械方向本身正確。

但「訊號嚴格早於結果」不正確：

- FCM availability 通常落在 outcome 月中。
- `d_nonrep` 是整月 DCOT 平均值相對前月平均值的變化，因此包含 availability 之前的週資料。
- 最明顯的是 2026-07：DCOT cache 只到 7 月 7 日，FCM availability 是 7 月 15 日，但程式以名義上的 7 月 31 日作 merge key，因而把 7 月 15 日才「可得」的 FCM factor 配給完全發生在其前的 outcome。

對純粹 ex-post association，這不必然使係數失效，因為 FCM underlying as-of month 本身更早；但不能解讀為 predictive、causal，或 known-before-outcome。

30–90 日 grid 只證明結果對不同 synthetic vintage shift 不敏感。它既沒有核對真實發布日，也沒有把 outcome 限制成 availability 後的第一個完整月份，因此不足以退休 timing concern。

## 3. NULL 是否由 bug 製造

目前點估計證據確實偏向「不支持負向 crowding-out」，但正式 artifact 尚不足以採信：

- 全樣本 `rv_z`／median `highvol` 對 retrospective association 可以接受；對 predictive specification 則有 regime-label lookahead。偏誤方向不確定，不能斷言它會把結果推向 NULL。
- 主回歸的 complete-case cascade 沒有明顯大量錯刪；真正異常是 bootstrap 多出的 7 列及其 `highvol=0` 錯標。
- FCM 是單一月度共同因子，實際時間資訊約 150 個月，不是 3,293 個獨立觀察。month clustering、DK 和 aggregate time-series check 是合理防護；results limitations 也有承認。
- `_acf_bandwidth()` 完全沒有讀取 residual：[K1694.py:421](/Users/yhlai0911/volpred-research/experiments/K1694/K1694.py:421)。所以傳入 zero vector 並沒有「從零殘差算 ACF」，而是永遠使用 `max(ceil(T^(1/3)), 4)`。這個固定規則可以是可辯護的 heuristic，但不能宣稱 bandwidth 由 residual ACF 決定。

唯讀診斷中，DK bandwidth 1–24 的 spec1 t 值仍只有約 1.55–1.74；排除不完整的 2026-07 後，`t_DK=1.60`、`t_cluster=1.64`。因此 bandwidth 和 partial month 暫時沒有顯示出製造 NULL，但這些敏感度尚未正式寫入可重現結果。

另外，`NULL` 必須限定為「負向 binary high-vol crowding-out hypothesis 未獲支持」，不能寫成「完全沒有關聯」：continuous `fcm_x_rvz` 其實是正向且顯著，`t_DK=2.50`、month-cluster t=2.54。

## 4. Results JSON 的過度陳述

需要修正：

- `bootstrap_interaction_spec1` 和 `primary_interaction.bootstrap_ci95` 冒充 primary spec1 的 CI。
- `panel_span` 寫到 `2026-07`，但該月 DCOT 只有一週，RV 只有 10 個交易日且僅 15 個商品；未揭露為 partial month。
- Limitations 漏列 synthetic publication dates、月內 timing overlap、full-sample regime labels，以及 bootstrap 不保留序列相關。
- 程式文件宣稱有「全落後 predictive spec」，實際沒有：[K1694.py:36](/Users/yhlai0911/volpred-research/experiments/K1694/K1694.py:36)。
- 缺少 runtime-generated `reproduce_spec.json`／code-input trace；artifact checker 因此仍明確阻擋。knowledge entry 缺失則是等待本次 review 的預期狀態。

最低修復要求是：讓 bootstrap 共用 spec1 的完全相同 design matrix、sample 與 `t`；處理缺失 RV；決定 temporal-block 或誠實標成 month-cluster bootstrap；排除 partial month；修正 timing/bandwidth 方法描述並重跑正式 artifacts。

VERDICT: FAIL
