# Strategy Launch Research Gate

本文件只判斷 verified strategy experiment 是否值得交給平台 owner；active metadata、期間、
threshold與上架狀態以 `STRATEGY_REGISTRY` 及 `docs/strategy-registry.md` 為準。

## Inputs

- Canonical experiment result/spec/review verdict
- `scripts/evaluate_new_strategy.py` 的同期間比較
- Current active strategy registry
- Cross-OOS、sensitivity、cost、turnover與drawdown evidence
- Article/operating explanation proposal

所有期間與active peer set在執行當下由canonical sources取得，不在skill保存日期快照。

## Gate

### 1. Same-period comparison

Candidate與current active peers使用相同period、lag、cost、return alignment及missing-day
rule。正式比較優先用`evaluate_new_strategy.py`。

### 2. Cross-OOS

使用多個不重疊regimes。列出每段period、sample、benchmark、metric與formal test；
不能只報勝場總數。

### 3. Independent review

Review必須pin現有code/result/README bytes，至少檢查information set、成本、return
alignment、selection與formal inference。

### 4. Sensitivity

對真正控制策略行為的參數做預先定義variation。報完整surface，不只報最好的point。

### 5. Risk gate

報realized volatility、turnover、raw及exposure-matched drawdown，並依experiment rules
比較phase-randomization null。低曝險造成的淺MDD不能當timing evidence。

## Verdict

- `PASS`：五項gate及artifact provenance完整，可交平台owner。
- `HOLD`：有潛力但缺OOS、review、sensitivity或operational evidence。
- `FAIL`：公平比較、正式檢定或風險證據不支持上架。

Verdict附strategy key、result identity、sample、每項gate evidence與limitations。

## Handoff

PASS只授權建立platform handoff，不授權直接改DB、歷史tracking或active registry。
下一步讀`add-strategy-guide.md`，由主線程重新讀task-pool mode後交給正式platform owner。
