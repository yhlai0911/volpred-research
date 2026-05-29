# Anti-AI-Style Gate Audit — 2026-05-30 (post-normalizer + backfill)

**Trigger**: 驗證 em-dash normalizer (commit `2130d746`, 2026-05-29 17:35) + backfill 754 篇 (commit `a8eea46a`) 對 published feed 文章的整體 anti-AI-style gate pass rate 影響。

## 方法

- Population: `storage/reports/feed.json` 中 `status=published` 且 `content` ≥100 chars → 1197 篇
- Sampler: `random.Random(seed=20260530).sample(population, 30)` (reproducible)
- Gate: `scripts/anti_ai_gate.py --no-fb-mode --stdin` (FB mode 關掉，因為 sample 含一般文章非 FB-specific)
- Verdict: exit code 0 = PASS；非 0 = FAIL（任一 MUST hit 即 fail）

## 結果

| 指標 | 值 |
|---|---|
| Sample size | 30 |
| Population | 1197 |
| PASS | 20 (66.7%) |
| FAIL | 10 (33.3%) |

## FAIL root-cause 分佈

10 篇 FAIL 中，**8 篇 (80%)** 唯一 MUST hit 是 **1.1「不是...而是」套路對比**。剩 2 篇 (mile_0056089e、mile_073884fd) MUST 類別被 WARN tail 蓋掉未顯示，但同樣含 1 個 MUST。

樣例 FAIL：
- `mile_d037cd91` 50/50 黃金配置：「不是更好的投資標的，而是...」hit 4 次
- `mile_f42dfd96` 恐慌賣出：「不是選股能力，不是內線消息，而是...」hit 3 次
- `mile_62fb1cb5` IV Connectedness：「不是說高連動是好事，而是...」hit 2 次
- `mile_40f0eba7` 5 分鐘避開股災：「不是選錯股票，而是...」hit 2 次

## 判讀

**Em-dash normalizer 成功**：30 篇 sample 中無一篇因 landmine 9（CJK 雙破折號）fail — 之前用戶硬性要求 fix 的 landmine 確實已被 publish-time gate 鎖定，retroactive backfill 也修了既有文章。

**下一個高 ROI normalizer 候選 = MUST 1.1「不是...而是」**：
- 80% FAIL 由此一條造成
- 解掉這條，pass rate 預估從 66.7% → ~93%
- ⚠️ 與 em-dash 不同，1.1 **不能機械替換**（語意對比結構本身有意義；改寫須保留 contrast 但去 AI 句式）
- 兩條可行路徑：
  1. **Publish-time hard reject** — 套用「找到即 reject」原則，逼 agent 改寫；風險：增加 publish 阻力，agent 可能無限 retry
  2. **Reader-facing warning + manual review queue** — 標記但不 reject；風險：違反「programmatic gate」硬規

**WARN 次要 hit**：1.3「無 source claim 語」（「許多投資人」「常聽到」「數據顯示」未指明來源）— 3 篇命中，可作為下一步 normalizer 訓練資料。

## 建議行動

- [ ] 開新 task：`anti_ai_landmine_11_pattern_audit` — 對 1197 篇全 population 跑 gate，統計 MUST 1.1 命中數 + 取樣 top 50 改寫候選
- [ ] 評估 1.1 publish-time gate 加入時機（建議先 dry-run 7 天看 reject rate）
- [ ] WARN 1.3 source claim 詞典補入 anti_ai_gate.py（如「許多」「常」「不少」「不少人」「業界普遍」全標 WARN）

## Artifacts

- 原始 audit JSON: `/tmp/audit_result.json`（本 fire 結束清掉，數字已 inline 此 report）
- Sampler script: `/tmp/normalizer_audit.py`（同上）
- Source commits: `2130d746` (normalizer), `a8eea46a` (backfill)

---

_Generated: 2026-05-30 01:15 台灣時間 by hourly-dispatch 01:07 fire (主線程)._
