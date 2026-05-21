# Claude Code Skill Handoff

更新日期：2026-05-16

這份文件整理目前與 `trending_repost`、`Facebook / Ivan Lai 同步發佈`、`anti-ai-style` 最相關的 canonical skills / rules，供 Claude Code 直接載入與遵守。

## 必讀 canonical 檔案

1. `.claude/skills/trending-repost/SKILL.md`
2. `.claude/skills/anti-ai-style/SKILL.md`
3. `.claude/rules/publishing.md`

必要時再補讀：

4. `.claude/skills/feed-publisher/SKILL.md`

## 這次要交付 Claude Code 的核心任務型別

### `trending_repost`

用途：

- 從熱門、高流量文章或議題出發
- 以 VolPred 的角度重寫成可發佈文章
- 不是翻譯，不是摘要，不是貼近改寫

風格定位：

- 參考 `havingchien` 類型的 Substack / commentary newsletter
- 可借 `genre / pacing / commentary tone`
- 不可引用原文
- 不可貼近改寫原文

## `trending_repost` 非談判規則

1. 必須先做選題掃描，不是直接下筆。
2. 必須做去撞題 / 查重。
3. 必須能接到 VolPred 視角：
   - 波動率
   - 風險
   - 策略
   - 方法論
   - 數據解讀
4. 必須先組 `evidence package`，再開始寫。
5. 必須符合平台文章標準，不可只有評論。
6. 必須 co-run `anti-ai-style`。
7. `trending_repost` 每天最多 `2` 篇。
8. VolPred 站內不是進 draft，而是直接 `published`。

## VolPred 證據標準

Claude Code 寫這類文章時，至少要滿足：

- 至少 `3` 個可獨立驗證的數字 / 事實
- 至少 `1` 個表
- 至少 `1` 個圖
- 至少 `1` 層簡單量化分析
- 最好有統計檢查或明確的比較框架

最低要求不是「有數字就好」，而是：

- 數字要支持主張
- 主張要比新聞轉述多一層
- 可追溯來源要清楚

## `anti-ai-style` 的地位

`anti-ai-style` 不是可選修飾，而是 publish gate。

Claude Code 必須理解：

- 所有讀者向文章都要跑 `anti-ai-style`
- `trending_repost` 必跑
- 若仍有 AI 味、翻譯腔、模板腔、空泛評論，不得發布

### `anti-ai-style` 實際要抓的方向

1. 不要寫成制式分析報告口吻。
2. 不要連續使用高頻 AI 句型。
3. 每一句都要有新信息，不要湊字數。
4. 不要把情緒、意義、轉折講得過度直白。
5. 不能只靠同模型自我感覺良好，要當成真正的編輯檢查。

## Facebook / Ivan Lai 發佈規則

這部分已是 canonical 規則，不是偏好。

### 同步發佈

- `trending_repost` 除了 VolPred feed，也要同步發到 `Facebook / Ivan Lai`

### Facebook 文案規則

1. Facebook 文案必須是改寫版，不可直接貼 VolPred 內文。
2. Facebook 主貼文不要放 VolPred 連結。
3. VolPred 原文連結放在留言區第一則留言。
4. Facebook 文案要符合 `Ivan Lai` 舊文口吻，不是制式財經摘要。

### Ivan Lai FB 口吻摘要

- 先個人觀察或判斷
- 句子短
- 段落短
- 保留留白
- 不把論證一次講滿
- 不把站內長文硬縮成 FB 摘要
- 比較像一個人的觀察，而不是標準分析稿

## 建議 Claude Code 的執行順序

1. 讀 `.claude/skills/trending-repost/SKILL.md`
2. 讀 `.claude/skills/anti-ai-style/SKILL.md`
3. 讀 `.claude/rules/publishing.md`
4. 先掃題、查重、確認 VolPred angle
5. 先組 evidence package
6. 寫 VolPred 版
7. 跑 anti-ai-style 修稿
8. 發 VolPred 正文
9. 改寫 Facebook 版
10. 發 Facebook 主文
11. 在留言區第一則補 VolPred 連結

## 這次實測得到的 Facebook 操作備註

這條很重要，建議 Claude Code 一併遵守：

- `Computer Use` 逐字輸入 Facebook 中文時，可能掉字或變形
- 中文 Facebook 文案建議優先用「整段貼上」而不是逐字輸入
- 先貼上，再肉眼檢查，再送出

這不是抽象建議，是已實測過的操作結論。

## 最短交付版

如果只要一句話交付 Claude Code，可以直接這樣說：

> 之後凡是 `trending_repost`，請先讀 `.claude/skills/trending-repost/SKILL.md`、`.claude/skills/anti-ai-style/SKILL.md`、`.claude/rules/publishing.md`；文章必須有 VolPred 證據標準、必跑 anti-ai-style、VolPred 直接 published、同步發到 Ivan Lai Facebook，FB 主文不用連結、連結放第一則留言，且 FB 文案要符合 Ivan Lai 舊文口吻。
