---
name: 3-model review discipline
description: Production article 上線 24h 內必走 3-model review (Claude write → Gemini text → Codex source-code)；Hook 強制 metric edit 重跑前獨立 codex 審；Audit 至少 3-pass grep variant
type: feedback
originSessionId: 91283b9e-7227-43f5-88bb-9d92168d243a
---
每篇 production article 出 publication pipeline 後 24 小時內必須跑 **3-model review pipeline**：

1. **Claude (write)** — 主線程或 worktree agent 完成 article + 自我 sanity check
2. **Gemini-2.5-pro (text framing)** — 讀 article markdown，抓 framing / overclaim / 內部數字一致性
3. **Codex GPT-5.4 (source-code)** — 讀 source code (`experiments/*.py` + `*_results.json`)，抓 implementation-level bugs gemini 純文字 review 看不到的

**Why**: 2026-05-02 session 跑了 6 篇 article 二審，gemini 一審 PASS 但 codex 抓出 20+ source-level real bugs（K518 21年/27年 + 5×5 區間錯 / K672 spec mismatch / K655 BH 60/40 應為 daily-rebalanced / K1018 metric helper cumsum + dm_test 非標準 / FOMC sign error + VIX 對帳 + T-2 id 誤 / K549 CI overclaim + 多重比較 framing + lookahead）。Gemini 純讀 markdown 看不到 implementation backing 是已驗證 systematic blindspot — pattern 已寫入 `.claude/rules/agent-delegation.md`。

**How to apply**:

1. **每篇 production article publish 後**，主線程派 codex 二審 bg task；中文 prompt **必用 heredoc**（避免 printf UTF-8 % char bug — K655 first attempt 撞過）。Verdict 格式 `AGREE_PASS / NEEDS_FIX_NEW / NEEDS_FIX_OVERLAP`。
2. **Codex CLI quota 易撞**（OpenAI usage limit）。撞線時用 **gemini-2.5-pro stop-gap** 暫代 + verdict 標 `PASS_WITH_CAVEAT / DEFER_TO_CODEX`，等 quota reset 後 retry codex 深度 audit。Stop-gap 不能取代 codex（gemini 看不到 implementation backing）。
3. **Metric helper / source code edit 重跑前必獨立 codex 審**，即使是已 audit 過的 pattern 複製。Hook `PreToolUse:Bash` 會強制提醒，不可繞過。
4. **Code audit 必走 3-pass framework**（K1018-derivative incident bound 5 files × 3 audit pass 確認）：
   - Pass 1: var-bound bare assignment grep（`cum = np.cumsum`）
   - Pass 2: method-call + inline pattern grep（`\.cumsum()`，包含 `ret.cumsum() - ret.cumsum().cummax()` 之類）
   - Pass 3: helper-function definition grep（`def max_drawdown / def mdd / def compute_mdd`）+ 看 docstring 是否自承 "arithmetic cumulative sum" 等 red flag

**Cost note**: 一次 codex 二審 ~10-15 min wall-clock + ~2 min token-budget；3-4 篇連跑會撞 quota（觀察值：2026-05-02 21:44 CST 跑完 FOMC + K549 後撞 limit reset 12:47 AM CST = ~3hr）。預算上不可在同 session 排 5+ 篇連審；視 article 重要性排序、低重要的隔下 reset 周期再審。

**Output**: 每篇 codex review 都記入 `storage/memory/knowledge.json`（pattern entry: `<article_id>_codex_review_<n>_findings_2026_xx_xx`）+ 累計 review pattern 寫入 `research_program.md` 的 "Article 三模 Review Pattern" section。
