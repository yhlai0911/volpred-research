# 2026-07-27 — CI root repair task 缺 execution contract，fire 能啟動卻不能修

## 證據化症狀

Main Test Suite run `30258321227` 在 `tests/test_covered_article_dedup.py`
collection 穩定因 `shared_state_lock` ImportError 失敗。CI watcher 建立
`ci-root-30256296797` 並多次成功 request/launch 新架構 fire，但 task 是 mutating
`platform_ops` 且沒有 `write_intent`／`declared_output_paths`，supervisor 不能
preassign；hourly worker 直接 claim 又被 `supervisor_preassignment_required`
拒絕。結果每班只能重做診斷，不能把 working-tree 修正交給 isolated producer/finalizer。

## 根因與底層重構

CI watcher 只把 failed log 壓成一行文字，丟失 producer isolation 所需的 exact path
evidence；「已建修復 task」與「task 可執行」兩個狀態被混為一談。Watcher 現在從
完整 GitHub failed-step log 抽取 known source roots 下的 literal file paths，
拒絕 absolute/traversal/storage/glob 並限制 32 路徑；有可信路徑才把
`write_intent=repo_patch`、exact `declared_output_paths` 與空 post-actions 綁進
一般及 uncapped root repair task，讓既有 supervisor preassignment/finalizer 契約接管。

## 回歸與 live read-back

真實 run `30258321227` log 回放精確得到
`scripts/mark_covered_article_tasks.py`、`scripts/mark_task_blocked.py` 與
`tests/test_covered_article_dedup.py`，沒有 runner 絕對路徑；惡意 path fixture 全被拒。
CI watcher 與 task preassignment scoped suite 73 passed。直接修復已由互動 session
以 task `ci-root-30256296797` 正式 claim/start/complete，repair commit
`c0a62a612fe3c165f03aeaeb7c33035489f0312b`；committed-version 最小重現及 8 個
target tests 皆綠。

## 狀態

Execution-contract 根因為 `root_cause_fixed_and_verified`；GitHub main 是否恢復
綠燈仍須等 owner-only push 後由 CI watcher 做 descendant read-back，未發生前不得
宣稱整個 CI incident 已結案。
