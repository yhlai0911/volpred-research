---
name: fb-publishing
description: >
  發佈 VolPred 文章到 Ivan Lai 個人 FB（與 feed 雙發佈）的完整 SOP。涵蓋
  發前查重（好幾個管道會轉發 → 必查是否已發過）、主貼文必附圖（結果圖 + 懶人包）、
  CDP-attach 持久 profile Chrome 機制、繼續→發佈兩段式、第一則留言補連結。
  Trigger: 'FB 發文', '發 FB', 'Ivan Lai FB', 'dual publish', 'trending FB',
  '轉發到 FB', 'fb_realchrome_post'. 語氣/文案規範另見 anti-ai-style +
  trending-repost/references/fb-ivanlai-tone.md（本 skill 不重複，只指路）。
---

# FB 個人帳號（Ivan Lai）發佈 SOP

**唯一機制**：`scripts/fb_realchrome_post.py` — CDP-attach 到**專用持久 profile 的真 GUI Chrome**
（`~/.volpred/fb_chrome_profile`，port 9222）驅動貼文。**不用 Graph API（個人帳號無 headless 發文權）、
不用粉專、不用 headless 假瀏覽器**（老闆硬性約束）。機制演進 + 一次性登入設定見 `docs/fb_realchrome_setup.md`。

## ⛔ 硬規則（違反 = 發文失敗）

1. **發前必查重（好幾個管道會轉發同文到 Ivan FB）** — 這是**第一步、先於任何動作**。查 Ivan Lai 時間軸
   有沒有已發過同主題（老闆可能手動發過、其他管道可能已轉發）。**已發過 → 跳過 FB 主貼文、只做 feed**，
   `mark_fb_post_status.py --status success`（或 skipped），**不重發、不硬補**。查法：worker 有 canonical
   `fb_post_status` idempotency guard（success → skip，除非 `--force`）；但 canonical 只擋「本 pipeline 發過的」，
   **老闆手動/他管道發的要親自看時間軸**（`fb_realchrome_post.py --check` 開 FB 頁 + grep 主題關鍵詞）。
2. **主貼文一定要附圖（結果圖 + 懶人包圖）** — 純文字貼文違反規則（2026-07-07 老闆糾正）。draft 的
   `## 圖片` 區塊列圖 URL（結果圖 e.g. `*_rv_divergence` + 懶人包 e.g. `*_concept/results-*`）；worker 會
   下載 + `set_input_files` 上傳 + 驗證縮圖數>0，**0 張則 ABORT 不發**。
   - **結果圖 vs 懶人包 內容查重（2026-07-07 老闆 Telegram「圖片為什麼會重複」）**：懶人包的 results/近期 panel
     常已完整涵蓋結果圖的同一組數字（如 mile_d12825bb：結果圖兩根 bar = 懶人包 panel1 全期 + panel3 近90日，
     4 張 md5 不同但視覺上讀者會覺得「同一張圖貼兩次」）。**附圖前先看一眼**：若結果圖的圖表已被某張懶人包 panel
     以更完整形式呈現 → **拿掉獨立結果圖，只貼懶人包**；或改挑一張懶人包沒畫到的結果圖。不要為湊「結果圖+懶人包」硬塞重複內容。
3. **主貼文不放連結；連結進第一則留言**（引流；主文放連結會被 FB 降觸及 + 生錯誤預覽卡）。
4. **全形 emoji / 中文用剪貼簿**：中文用 `pbcopy`+`Cmd+V`（`type` 會亂碼）；worker 已內建「貼上前一刻
   pbcopy + pbpaste 驗證 + composer 回讀驗證」防剪貼簿被搶（2026-07-07 差點貼成別的 URL 的教訓）。
5. **語氣**：Ivan Lai 第一人稱、無「朋友問我」開場、無列表體 — 見 `anti-ai-style` +
   `trending-repost/references/fb-ivanlai-tone.md`（唯一語氣來源，本檔不重複）。

## Draft 格式（`storage/drafts/fb_mile_<id>.md`）

```
# mile_id: mile_XXXX
## 主貼文（純文字，不含連結）
<Ivan Lai 語氣正文…>
## 第一則留言（貼連結）
https://volpred.zeabur.app/v3/reports/mile_XXXX
## 圖片（結果圖 + 懶人包，依序）
https://.../<結果圖>.png
https://.../<懶人包 concept>.png
https://.../<懶人包 results-*>.png
```

## 執行流程（風控 gate，逐步不可跳）

```bash
# 1) 查 attach + 登入（自癒：port 沒開會自動起 dedicated Chrome）
uv run python scripts/fb_realchrome_post.py --check       # 期望 [PASS] 已登入

# 2) dry-run：填文 + 附圖，停在送出前，人工看 /tmp/fb_realchrome/post_with_images_*.png
uv run python scripts/fb_realchrome_post.py --post storage/drafts/fb_mile_<id>.md --dry-run

# 3) 真發（idempotency guard 自動查 fb_post_status；已發過會 [SKIP]）
uv run python scripts/fb_realchrome_post.py --post storage/drafts/fb_mile_<id>.md
#   --force 只在確認要覆蓋（例如刪掉舊版重發）時用
```

**⚠️ 撤掉重發不要先 --dry-run 再 --force（2026-07-07 T2 教訓）**：`--dry-run` 會把附圖留在 composer
草稿裡，緊接的 `--force` `set_input_files` 是「**新增**」不是「取代」→ 舊圖 + 新圖疊加（實測 2 舊 + 3 新
= 5 張，重現老闆「圖片重複」）。已加防護：附圖前自動清既存照片 + `縮圖數 != 附圖數` 直接 ABORT 不發。
撤掉重發時**直接 `--force` 一次到位**，看 log `已附 N 張圖（縮圖偵測 N）` 兩數必須相等。

### 撤掉舊貼文（重發前刪除）— `--delete-matching`

老闆要求「撤掉重發」時，先刪舊貼文再 `--post --force`。刪除是對外破壞性動作，走兩段式風控：

```bash
# 段 1：定位 + 截圖目標貼文（不刪）。幾何定位：捲到含 ANCHOR 的正文 → 取其正上方
#        aria-label「對<名字>的這則貼文採取的動作」⋯ 鈕（非「最小容器」heuristic，會誤配）。
uv run python scripts/fb_realchrome_post.py --delete-matching "<貼文正文前幾字>"
#   → 人工看 /tmp/fb_realchrome/delete_target_*.png 確認是「該篇」（勿誤刪置頂/他篇）

# 段 2：確認後真刪（⋯ → 移到垃圾桶 → 確認鈕「移動」）
uv run python scripts/fb_realchrome_post.py --delete-matching "<貼文正文前幾字>" --confirm-delete
```
ANCHOR 用主貼文開頭純文字（避免用被 FB 截斷/「查看更多」的尾段）。FB 虛擬捲動會 unmount
捲太遠的貼文 → 定位用「漸進小捲 + scrollIntoView 保持 mounted」，不要一次捲過頭。

發文兩段式（worker 已處理）：composer → **繼續** → 貼文設定 → **發佈** → 自動補第一則留言連結 →
`mark_fb_post_status.py --status success`。

## 誠實邊界

- CDP-attach 若觸 FB 自動化風控/鎖帳 → **誠實回報物理上限，不硬繞**。
- AI **不能替老闆輸入 FB 密碼**（硬規則）；dedicated Chrome 的一次性 FB 登入只能老闆做。
- 刪除既有貼文（重發用）是對外破壞性動作 → 先確認是「該篇」再刪（screenshot 驗證，勿誤刪置頂/他篇）。

## 相關檔（不重複維護，只指路）

- 機制 + 一次性設定：`docs/fb_realchrome_setup.md`
- Ivan Lai 語氣：`.claude/skills/trending-repost/references/fb-ivanlai-tone.md` + `anti-ai-style`
- 粉專（另一條線，個人優先）：`.claude/skills/trending-repost/references/fb-page-operations.md`
- 狀態機/查重欄位：`scripts/mark_fb_post_status.py`、`storage/reports/feed.json` 的 `fb_post_status`
- 懶人包生圖：`.claude/skills/lazypack-infographic/`
