# K1708 選項A stage 2/2 — 用真實 own-restriction 數字關掉 round-3 BLOCKER，再送 round-4

**Model**: opus / xhigh (per model_router)

## 背景（已由主線程驗證，不必重驗）

- full-sample rerun 已完成（compute job `compute-k1708-full-sample-rerun-a-own-restriction-1784685543`，
  exit 0，02:00→02:41）。工作目錄 = `.claude/worktrees/dispatch-slot-1-457427c2-k1708`。
- **verdict 仍為 `NULL`**（`qualified_markets: []`）—— 未翻正，符合 §15 的事前預期，可以繼續。
- **code_trace drift（round-3 BLOCKER 3 的根）已消失**：rerun 後 `K1708_results.json` 的
  `code_trace["K1708.py"].sha256 = 4a8236ff9b83...`、`size_bytes = 126998`，與 worktree 內
  現行 `experiments/k1708/K1708.py` 逐位元一致（主線程 shasum 驗過）。
- rerun 後 payload 已含新口徑欄位：`cw_vs_own_restriction`（TAIFEX_TX: t=1.2364, p_one_sided=0.1082）、
  `regime_qlike_vs_own_restriction`（high=-0.004445, low=+0.002401）、`control_series=HAR_KF_DISC_AT_DELTA_ONE`。

## 硬性邊界

- **禁止合併 worktree**。所有改動留在 `.claude/worktrees/dispatch-slot-1-457427c2-k1708`。
- **禁止把 verdict 推向非 NULL**。若你的改動讓 label 變動，停手、寫報告、回報異常。
- **禁用 fallback reviewer**。round-1/2/3 都是 Codex primary-path FAIL；換 reviewer =
  湮滅比較基準，等同造假。
- 研究誠實 > 一切。不得寫「will fix later」當作 closure。

## 三件事

### (1) 用真實數字填 `gate_transition_audit` 的 cross-comparator 欄位

round-3 BLOCKER 1 的核心：`gate_transition_audit()` 在 stored payload 上只能回
`cross_comparator_comparison.possible = false`，因為 own-restriction 對照序列從未被保存 ——
於是「新 gate 比舊 gate 緊或鬆」只能靠 `legacy_derive_verdict()` 這個**作者自己重建的舊邏輯**
去論證，是循環的。

現在 rerun 已產生真實的 own-restriction 數字。要做的是：

- 對 rerun 後的 payload 跑 `gate_transition_audit()`，確認
  `cw_vs_own_restriction.evaluable` 現在為 `true`、`cross_comparator_comparison.possible`
  現在為 `true`，並把兩個 gate 的並列結果（各自的 t 向量、通過集合、以及交集/差集）寫進
  每個 market 的 `gate_transition_audit`。
- README §8.2.1 的「comparator 橫移、兩個方向都不可排序」在**這一份真實資料上**現在是可
  評估的：把它從「不可評估、只能靠合成 t 向量舉反例」升級為「在 TAIFEX_TX 實資料上，
  新舊 gate 各自的判定為 X / Y」。照實寫，包含「本資料上兩者同為 NULL、因此這一組觀測
  不足以區分鬆緊」這種弱結論 —— 弱結論照寫，不要美化成強證據。
- 對應測試（`test_gate_audit_reports_the_stored_payload_as_not_comparable`）現在斷言的是
  舊事實。**不要直接刪**：改成同時釘住兩件事 —— (a) 舊的 stored payload（缺欄位）仍
  回 `possible=false`；(b) 新的 rerun payload 回 `possible=true` 且並列表非空。這樣測試
  才「咬得住」（round-2 BLOCKER 4 的教訓）。

### (2) 寫 `experiments/k1708/reproduce_spec.json`

`scripts/experiment_gates.py` / `check_experiment_artifacts.py` 會擋缺檔的合併。
現在 code_trace 與現行 K1708.py 一致，才寫得出誠實的 spec。內容必須是**真的能重跑出這份
results 的指令與環境**，不是樣板。寫完跑：

```
uv run python scripts/experiment_gates.py run --path experiments/k1708
```

### (3) 送 Codex primary-path round-4 review

用 codex-cli skill（`codex exec`，read-only sandbox，model 與 round-3 相同：`gpt-5.6-sol`，
reasoning effort high）。prompt 必須：

- 明說這是 **round 4**，round-3 的 BLOCKER 清單見
  `storage/ops/k1708_codex_review_round3_20260722.md`（先讀，把 round-3 的 BLOCKER 逐條列進 prompt）。
- 要 reviewer 判定的是：rerun 產生的真實數字**是否真的關掉**了循環論證（BLOCKER 1）與
  code_trace drift（BLOCKER 3），以及 (1) 改過的測試是否仍具鑑別力。
- 附硬規則：不得為了配合而 PASS；不得接受「稍後修」；research verdict 是 NULL，本次
  review 只審 gate/test 正確性，不重審研究結論。

報告存 `storage/ops/k1708_codex_review_round4_20260722.md`（完整 stdout，不裁剪）。

## 交付物

在 worktree 內產出，並在最後回傳 JSON 摘要：

- `experiments/k1708/K1708_results.json`（已含填好的 gate_transition_audit）
- `experiments/k1708/reproduce_spec.json`
- `experiments/k1708/README.md`（§8.2.1 更新）
- `experiments/k1708/test_k1708.py`（測試升級）
- `storage/ops/k1708_codex_review_round4_20260722.md`
- `experiments/k1708/K1708_stage2_summary.json` — 欄位：
  `{"verdict_label": ..., "gate_audit_possible": bool, "experiment_gates_pass": bool,
    "codex_round4_verdict": "PASS|FAIL", "codex_blockers": [...], "merge_ready": bool}`

**merge_ready 只有在 round-4 PASS 且 experiment_gates 過才可為 true。** review 未 PASS 前
不得合併 —— 合併由後續 fire 的人做，你只負責把狀態做到可被判定。
