# 網站重構方案 v2

## 現有架構分析

### 論文頁面重構

現在 `/paper` 是硬寫單篇論文。未來有多篇（leverage-direction、taiwan-vt 等），需要改成列表式：

```
/paper                → 論文列表（卡片式）
/paper/[slug]         → 個別論文詳情 + PDF 下載
```

```sql
CREATE TABLE papers (
  id TEXT PRIMARY KEY,             -- leverage-direction, taiwan-vt
  title TEXT NOT NULL,
  authors TEXT NOT NULL,
  abstract TEXT,
  status TEXT DEFAULT 'working',   -- working / submitted / accepted / published
  target_journal TEXT,
  pages INTEGER,
  pdf_url TEXT,                    -- /paper/leverage-direction-matters.pdf
  tags TEXT[],
  score INTEGER,                   -- Codex review score
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

論文卡片顯示：
```
┌─────────────────────────────────────────────────────┐
│ Leverage Direction Matters                          │
│ Yi-Hao Lai · 51 pages · Score: 69/100              │
│ Status: Under revision                             │
│ Target: Journal of Banking & Finance               │
│ [Download PDF] [View Abstract]                     │
├─────────────────────────────────────────────────────┤
│ Taiwan Volatility Targeting with VIX Proxy          │
│ Yi-Hao Lai · Planning                              │
│ Status: Data collection (VIXTWN 42/252 days)       │
│ Target: 財務金融學刊                                  │
│ [View Outline]                                      │
└─────────────────────────────────────────────────────┘
```

### 全站 UI/UX 規劃

#### `/` Feed 首頁
```
現在：文章列表 + tag 篩選
改善：
  - 置頂「研究日記」和「每日建議」卡片
  - 文章卡片加入：瀏覽數、按讚數、閱讀時間估計
  - 按讚/書籤按鈕（需登入）
  - 無限滾動替代分頁
  - 搜尋功能（全文檢索）
```

#### `/risk-forecast` 風險預報
```
現在：表格式即時數據
改善：
  - 儀表板風格（大數字 + 圓餅圖）
  - VIX/GARCH ratio 儀表（綠/黃/紅）
  - 歷史 VIX 走勢圖（最近 30 天）
  - 策略建議卡片（50/50 SPY/GLD 配置）
  - 警報橫幅（ratio > 1.5 時紅色提醒）
```

#### `/vix-calculator` VIX 計算器
```
現在：輸入 VIX → 計算配置（已有 50/50 模式）
改善：
  - 預設帶入即時 VIX（已有）
  - 加入「歷史模擬」：選過去日期看當時建議
  - 加入「情境分析」：VIX=15/20/30/50 時的配置對比表
  - 手機版滑桿調整 VIX（取代輸入框）
```

#### `/questions` Q&A
```
現在：兩欄（研究問答 + 會員排名）
改善：
  - 排名表加入進度條（evaluating→ranked→researching→answered）
  - 已解答問題展開時直接顯示文章摘要
  - 提問成功後動畫反饋
  - 登入提示更顯眼（未登入時）
```

#### `/paper` 論文（已規劃列表式）
```
改善：
  - 每篇論文卡片帶進度條（planning→writing→review→submitted）
  - Abstract 展開/收合
  - 相關 feed 文章連結（這篇論文引用了哪些研究）
  - PDF 預覽（嵌入式 viewer 或首頁截圖）
```

#### `/admin/paper-trading` Portfolio
```
現在：策略配置表格
改善：
  - 累計報酬走勢圖（每個策略一條線）
  - 與 B&H 基準線對比
  - 每日/每月 P&L 報告
  - 當前持倉比例圓餅圖
```

#### `/admin/thinking` Thinking（僅 admin）
```
現在：Thinking journal stream
改善：
  - 保持簡潔（admin 工具）
  - 加入快速篩選：按日期、按 context
  - 「精選為研究日記」按鈕 → 自動建立草稿
```

#### 導航結構重整

現在 8 個項目太多且層級不清。重整為**用戶導向**的 5 個主要入口：

```
主導航（永遠可見，最多 5 個）：
  研究    → Feed 文章列表（首頁）
  工具    → 下拉：VIX 計算器、風險預報
  論文    → 論文列表
  問答    → Q&A + 會員排名
  登入/頭像 → 登入 / 會員中心

次導航（登入後或 admin）：
  Portfolio（Paper Trading）
  後台管理（admin only）
```

對比現在：
| 現在 | 重構後 | 原因 |
|------|--------|------|
| Feed | 研究 | 更清楚，首頁就是 |
| Risk | 工具 > 風險預報 | 合併到工具下拉 |
| 12/VIX | 工具 > VIX 計算器 | 合併到工具下拉 |
| Q&A | 問答 | 保留 |
| Paper | 論文 | 保留 |
| Portfolio | 次導航（登入後） | 非核心功能 |
| Thinking | 後台（admin） | 不對外 |
| Admin | 後台（admin） | 不對外 |

手機版：底部 4 icon（研究、工具、問答、論文）+ 更多（≡）

#### 文章分類與非專業內容

**原則：每個研究發現都要有兩個版本——專業版 + 一般版。讀者可自由篩選。**

文章類型：
| 類型 | 標記 | 讀者 | 風格 |
|------|------|------|------|
| `research` | 📊 研究 | 專業投資人/研究者 | 數據、公式、統計檢定 |
| `general` | 📖 一般 | 非專業投資人 | 白話解說、類比、操作建議 |
| `diary` | 📝 日記 | 所有人 | 研究過程故事 |
| `daily` | 📅 每日 | 所有人 | 每日策略建議 |
| `qa` | ❓ Q&A | 所有人 | 問題解答 |

```sql
ALTER TABLE articles ADD COLUMN
  audience TEXT DEFAULT 'research';  -- research / general / diary / daily / qa
```

前端篩選 UI：
```
[全部] [📖 一般] [📊 研究] [📝 日記] [📅 每日] [❓ Q&A]
```

文章關聯系統（一般 ↔ 研究）：
```sql
ALTER TABLE articles ADD COLUMN
  related_articles TEXT[];  -- 關聯文章 ID 列表
```

一般文章底部顯示「延伸閱讀」：
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 想深入了解？延伸閱讀研究原文：
  → 「Complexity Ceiling：DCC-GARCH 不改善配置 + K/VIX 的數學恆等式」
  → 「Phase Q 總結：複雜度何時停止幫助」
  → 「50/50 SPY/GLD + 12/VIX 完整操作手冊」
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

反向也成立——研究文章底部可顯示：
```
📖 看不懂？讀白話版：
  → 「投資不需要複雜：一個簡單公式如何打敗 99% 的波動率模型」
```

Claude 發文時自動填入 related_articles：
- 一般文章 → related = 對應的研究文章 IDs
- 研究文章 → related = 對應的一般文章 IDs（如果有的話）

一般文章寫作原則：
- 不用統計術語（「DM test p=0.006」→「有統計顯著差異」）
- 用類比（「VIX 就像保險的價格——越貴代表市場越害怕」）
- 專注「so what」（「這意味著你應該...」）
- 有具體操作步驟（「每月第一天查 VIX，計算...」）
- 500-1000 字（比研究文章短）

Claude 在 autonomous research 中的分配：
```
每完成 2-3 篇研究文章 → 寫 1 篇對應的一般文章
例如：
  研究文章：「Complexity Ceiling 第 11 次確認——GINN proxy mismatch」
  一般文章：「為什麼更複雜的模型不一定更好？投資中的 simple beats complex」
```

#### 全站共通改善
```
  - Dark/Light 模式切換
  - 手機版底部導航列（取代頂部 overflow scroll）
  - 載入骨架屏（Skeleton loading）
  - 頁面轉場動畫
  - SEO meta tags（每頁獨立 title/description）
  - PWA 支援（可加到手機桌面）
  - i18n 準備（繁中為主，未來加英文）
```

### 頁面結構（重構後）
| 路徑 | 功能 | 資料來源 |
|------|------|---------|
| `/` | Feed 文章列表 | `/publications/feed` → feed.json |
| `/reports/[id]` | 個別文章 | `/publications/feed/{id}` → reports/{id}.json |
| `/risk-forecast` | 即時風險預報 | `/risk-forecast` → risk_forecast.json |
| `/vix-calculator` | 12/VIX 計算器 | `/risk-forecast`（取 live VIX） |
| `/questions` | Q&A + 會員排名 | `/research/questions` + `/api/questions` |
| `/paper` | 論文下載 | 靜態 PDF |
| `/admin` | 管理面板 | 多個 API |
| `/admin/thinking` | Thinking Journal | `/research/thinking` |
| `/admin/paper-trading` | Paper Trading | `/research/paper-trading` |
| `/admin/program` | 研究計畫 | 靜態 |

### API Routes（15 個）
| 路徑 | 讀/寫 | 資料來源 |
|------|-------|---------|
| `/api/publications/feed` | 讀 | `data-server.ts` → storage/reports/feed.json |
| `/api/publications/feed/[id]` | 讀 | `data-server.ts` → storage/reports/{id}.json |
| `/api/publications/publish` | 寫 | `data-server.ts` → storage/reports/ |
| `/api/research/thinking` | 讀 | `data-server.ts` → storage/memory/thinking_journal.json |
| `/api/research/questions` | 讀 | `data-server.ts` → storage/memory/open_questions.json |
| `/api/research/knowledge` | 讀 | `data-server.ts` → storage/memory/knowledge.json |
| `/api/research/log` | 讀 | `data-server.ts` → storage/memory/research_log.json |
| `/api/research/experiments` | 讀 | `data-server.ts` → storage/memory/experiments.json |
| `/api/research/paper-trading` | 讀 | `data-server.ts` → storage/paper_trading.json |
| `/api/research/summary` | 讀(計算) | 從多個 JSON 合成 |
| `/api/risk-forecast` | 讀 | `data-server.ts` → storage/risk_forecast.json |
| `/api/questions` | 讀+寫 | 本地 user_questions.json（會消失） |
| `/api/sync/[...path]` | 寫 | 接收研究系統 POST 同步 |
| `/api/health` | 讀 | 健康檢查 |
| `/api/notifications` | 讀 | 通知 |

### Lib 層
| 檔案 | 功能 |
|------|------|
| `api.ts` | 前端 fetcher：API first → static fallback，含路徑映射表 |
| `data-server.ts` | 後端：Dev 讀 `../storage/`，Prod 讀 `data/` |

### 資料流（現有，複雜）
```
研究系統寫入 storage/*.json
    ↓ (Dev) data-server.ts 直接讀 ../storage/
    ↓ (Prod) sync-data.sh cp → data/ → git push → Zeabur build
前端 api.ts：
    ↓ tryAPI() → /api/xxx → data-server.ts
    ↓ tryStatic() → /data/xxx.json（fallback）
```

### 核心問題
1. **Dev vs Prod 路徑分裂**：Dev 讀 `../storage/`，Prod 讀 `data/`，需要 sync-data.sh 橋接
2. **用戶數據不持久**：`/api/questions` POST 存本地 JSON，Zeabur 重新部署就消失
3. **無會員驗證**：任何人可提問，無法追蹤用戶
4. **同步延遲**：research system 寫 JSON → 等 sync → 等 push → 等 build → 才生效
5. **路徑映射表**：`api.ts` 的 `staticMap` 是 workaround，增加維護成本

---

## 重構目標

```
研究系統 ──POST──→ Supabase DB ←──Query──→ Next.js API ←── 前端
                        ↑
                  Supabase Auth（會員）
```

**原則：**
- **所有運算在本地端**，結果產生後才 push 到 DB
- `storage/*.json` 仍是研究系統的 source of truth（不變）
- DB 是**展示層** + **用戶數據存儲**
- 資料流單向：本地 → DB → 網頁（研究結果）
- 資料流反向：網頁 → DB → 本地（用戶提問，定時拉取）
- 不再需要 sync-data.sh 和 git push 觸發 build 來更新資料
- 用戶數據永久保存在 DB

---

## 技術選型：Supabase

| 項目 | 規格 |
|------|------|
| 資料庫 | PostgreSQL（Supabase 免費 500MB） |
| Auth | Google OAuth + Magic Link |
| API | Supabase JS Client（前端直連）+ Service Key（研究系統） |
| Realtime | Supabase Realtime（可選，用於即時更新） |
| 成本 | 免費 tier 足夠（資料 < 50MB） |

---

## 會員系統

### 登入方式
- **Google OAuth**（推薦，一鍵登入）
- **Email Magic Link**（備選，無密碼）

### 會員等級
| 等級 | 提問數 | 功能 |
|------|--------|------|
| **Free** | 3 題/月 | 提問、看排名、看已解答 |
| **Premium** | 無限 | + 優先研究、+ 即時通知 |
| **Admin** | 無限 | + 管理所有問題 |

---

## Database Schema

```sql
-- ═══ 會員 ═══
CREATE TABLE profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id),
  display_name TEXT,
  role TEXT DEFAULT 'free',
  questions_remaining INT DEFAULT 3,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ═══ 研究文章 ═══
CREATE TABLE articles (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  content TEXT,
  description TEXT,
  phase TEXT,
  tags TEXT[],
  category TEXT DEFAULT 'milestone',
  proposer TEXT,
  details JSONB,
  published_at TIMESTAMPTZ DEFAULT NOW()
);

-- ═══ 內部研究問題 ═══
CREATE TABLE research_questions (
  id TEXT PRIMARY KEY,
  question TEXT NOT NULL,
  status TEXT DEFAULT 'open',
  priority TEXT DEFAULT 'medium',
  proposer TEXT,
  answer TEXT,
  feed_articles TEXT[],
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ═══ 用戶提問（排名系統）═══
CREATE TABLE user_questions (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id UUID REFERENCES profiles(id),
  question TEXT NOT NULL,
  status TEXT DEFAULT 'evaluating',
  score INTEGER,
  score_breakdown JSONB,
  answer TEXT,
  feed_articles TEXT[],
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ═══ 研究記憶 ═══
CREATE TABLE memory_entries (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,  -- thinking / knowledge / log / experiment
  content JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ═══ 風險預報 ═══
CREATE TABLE risk_forecasts (
  id SERIAL PRIMARY KEY,
  data JSONB NOT NULL,
  generated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ═══ Paper Trading ═══
CREATE TABLE paper_trades (
  id SERIAL PRIMARY KEY,
  strategy TEXT NOT NULL,
  entry JSONB NOT NULL,
  trade_date DATE NOT NULL
);

-- ═══ 用戶行為追蹤 ═══
CREATE TABLE article_views (
  id SERIAL PRIMARY KEY,
  article_id TEXT REFERENCES articles(id),
  user_id UUID REFERENCES profiles(id),  -- NULL = 匿名訪客
  session_id TEXT,                        -- 匿名追蹤用
  action TEXT NOT NULL,                   -- view / like / share / bookmark
  read_time_sec INTEGER,                  -- 閱讀時間（秒）
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 聚合統計（materialized view，定時更新）
CREATE MATERIALIZED VIEW article_stats AS
SELECT
  article_id,
  COUNT(*) FILTER (WHERE action = 'view') AS view_count,
  COUNT(*) FILTER (WHERE action = 'like') AS like_count,
  COUNT(*) FILTER (WHERE action = 'share') AS share_count,
  COUNT(*) FILTER (WHERE action = 'bookmark') AS bookmark_count,
  AVG(read_time_sec) FILTER (WHERE action = 'view' AND read_time_sec > 0) AS avg_read_time_sec,
  COUNT(DISTINCT user_id) FILTER (WHERE action = 'view') AS unique_readers,
  MAX(created_at) AS last_viewed_at
FROM article_views
GROUP BY article_id;

-- RLS: 任何人可寫入 view 記錄，只有 admin 可讀全部
ALTER TABLE article_views ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Anyone can log views" ON article_views FOR INSERT WITH CHECK (true);
CREATE POLICY "Admin read all" ON article_views FOR SELECT USING (
  EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND role = 'admin')
);

-- ═══ Row Level Security ═══
ALTER TABLE articles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public read" ON articles FOR SELECT USING (true);

ALTER TABLE research_questions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public read" ON research_questions FOR SELECT USING (true);

ALTER TABLE user_questions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Own insert" ON user_questions
  FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Public read ranked" ON user_questions
  FOR SELECT USING (status IN ('ranked','researching','answered') OR auth.uid() = user_id);

ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Own read" ON profiles
  FOR SELECT USING (auth.uid() = id);
```

---

## 部署策略：新專案，不影響現有

```
現有（保持運行）：
  volpred-web (GitHub) → Zeabur volpred.zeabur.app
  → 不動，持續運行直到新站穩定

新站（獨立開發）：
  volpred-v2 (GitHub) → Zeabur volpred-v2.zeabur.app（開發期）
  → 穩定後切換 domain 到 volpred.zeabur.app
```

**優點：**
- 現有網站完全不受影響
- 新站可以慢慢開發測試
- 出問題隨時切回舊站
- 可以 A/B 比較兩個版本

**切換時機：**
- 新站所有功能測試通過
- 資料遷移完成（JSON → Supabase）
- 至少跑 1 週無 bug

## 遷移計畫

### Phase 1: Supabase + Auth + 用戶提問（2-3 天）
**目標：用戶提問持久化 + 登入才能提問**

改動：
- 建 Supabase project + 表 + Auth (Google OAuth)
- `frontend/src/lib/supabase.ts`：Supabase client
- `frontend/src/app/questions/page.tsx`：登入 UI + 改用 Supabase insert/select
- `frontend/src/app/layout.tsx`：加入 Auth provider
- `frontend/src/app/api/questions/route.ts`：改讀寫 Supabase

不動：
- 所有其他頁面、API、research system

### Phase 2: 文章遷移（2-3 天）
**目標：feed 存 DB，移除 JSON 複製**

改動：
- `articles` 表匯入現有 324 篇
- `src/volpred/publisher/publisher.py`：改 POST Supabase
- `frontend/src/app/api/publications/`：改讀 Supabase
- `frontend/src/lib/api.ts`：移除 `staticMap` 中的 feed 映射

不動：
- memory 系統、risk forecast

### Phase 3: 研究記憶 + 風險預報（2-3 天）
**目標：所有資料走 DB**

改動：
- `memory_entries` 表匯入 thinking/knowledge/experiments/log
- `src/volpred/memory/system.py`：改寫 Supabase
- `risk_forecasts`、`paper_trades` 表
- `scripts/daily_update.py`：改寫 Supabase
- `frontend/src/lib/data-server.ts`：可移除（不再需要）

### Phase 4: 清理（1 天）
- 移除 `sync-data.sh`
- 移除 `frontend/public/data/*.json`
- 移除 `frontend/src/lib/data-server.ts`
- 簡化 `frontend/src/lib/api.ts`（直接用 Supabase client）
- 更新 crontab（移除 sync 任務）
- 更新 CLAUDE.md、skills

---

## 發文流程重構

### 現在（混亂）
```
Claude 研究完成 → Publisher 直接寫入 feed.json → 立即發布
→ 問題：發布時間不可控，凌晨3點也會發文，一天可能發10篇也可能0篇
```

### 重構後（排程發布）
```
Claude 研究完成 → POST 到後台（status: draft）
    ↓
後台文章管理（admin/articles）：
    → 草稿列表：待審核/待排程的文章
    → 用戶可以：預覽、編輯、排程時間、立即發布、退回修改
    ↓
排程發布系統：
    → 每日固定時段發布（例：每天 9:00 發一篇）
    → 或手動指定發布時間
    → 發布後 status: draft → published
    ↓
前端只顯示 status=published 的文章
```

### Articles 表擴展
```sql
ALTER TABLE articles ADD COLUMN
  status TEXT DEFAULT 'draft',           -- draft / scheduled / published / archived
  scheduled_at TIMESTAMPTZ,              -- 排程發布時間
  created_by TEXT DEFAULT 'claude',      -- claude / admin / user
  reviewed_by UUID REFERENCES profiles(id),
  review_note TEXT;
```

### 發布狀態流
```
draft（草稿）→ scheduled（已排程）→ published（已發布）
    ↑                                      ↓
    └── archived（封存，不顯示但保留）←──────┘
```

### Claude（本機）的操作方式
```python
# 研究完成後，發到後台草稿
pub.publish_milestone(
    title="...", content="...",
    status="draft"  # 不直接 published
)
# → POST to Supabase articles table with status='draft'

# 用戶指示後台管理工作時，Claude 執行：
# - 「把那篇 BTC 文章排到明天早上9點」
#   → UPDATE articles SET status='scheduled', scheduled_at='2026-03-18 09:00'
# - 「把草稿裡的3篇合併成一篇」
#   → 合併 content → INSERT new + UPDATE old status='archived'
# - 「刪掉那篇品質不好的」
#   → UPDATE status='archived'
```

### 排程引擎（Supabase Edge Function 或 cron）
```sql
-- 每小時檢查：scheduled_at <= NOW() 的文章自動發布
UPDATE articles
SET status = 'published'
WHERE status = 'scheduled'
  AND scheduled_at <= NOW();
```

### Claude 自主管理後台（數據驅動）

**原則：用戶定大方向，Claude 自主決策執行。**

用戶只提供大原則，例如：
- 「每天最多發 2 篇」
- 「品質優先於數量」
- 「多寫台灣市場相關的」

Claude 自主執行所有後台管理：

#### 1. 發文策略（自主）
```
研究完成 → 寫入草稿 → Claude 自主決定：
  - 何時發布（根據歷史最佳發布時段）
  - 發布順序（根據內容品質和時效性）
  - 每日發布量（根據用戶設定的上限）
  - 是否合併多篇小發現為一篇深度文章
```

#### 2. 數據分析 → 研究方向調整（自主）
```
定期（每週）分析後台數據：
  - 哪些 tags 的文章瀏覽最高？ → 研究這些方向
  - 哪些文章按讚最多？ → 產出類似風格/深度
  - 平均閱讀時間多長？ → 調整文章長度
  - 會員提問集中在哪些主題？ → 優先研究這些
  - 哪些文章被分享最多？ → 這是「有傳播力」的內容
```

#### 3. 會員管理（自主）
```
  - 監控活躍度，自動識別高價值會員
  - 定期清理不活躍帳號的配額
  - 根據提問品質建議升級 premium
```

#### 4. 內容品質控制（自主）
```
發布前自動檢查：
  - content > 300 字？
  - 有 Markdown 結構？
  - 有數據支撐？
  - tags 合理？
  - 不與最近 7 天的文章重複？
→ 通過 → 排程發布
→ 不通過 → 留在草稿，改善後重新提交
```

#### 5. 研究回饋循環
```
後台數據                研究系統
    │                      │
    ├─ 熱門主題 ──────→ 調整研究方向
    ├─ 閱讀偏好 ──────→ 調整文章風格
    ├─ 會員問題 ──────→ 設定研究優先順序
    ├─ 瀏覽趨勢 ──────→ 判斷發文頻率
    └─ 分享數據 ──────→ 識別高傳播力內容特徵
```

#### 6. Thinking 分層發布

**原則：原始 thinking 是內部 log，精選後才對外發布。**

```
m.think()（原始決策邏輯）
    ↓ 存入 DB memory_entries（admin only）
    ↓
每週 Claude 自動精選 3-5 則有趣的決策瞬間
    ↓ 整理成「研究日記」文章（500-1000 字）
    ↓ 進入草稿 → 排程發布
    ↓
Feed 公開（tag: 研究日記）
```

| 層級 | 內容 | 受眾 | 位置 |
|------|------|------|------|
| Raw thinking | 原始決策日誌 | Admin only | `/admin/thinking`（後台） |
| 研究日記 | 每週精選，整理成可讀文章 | 所有人 | Feed（公開） |
| 即時思考流 | 正在研究什麼、遇到的困難 | Premium 會員 | 專屬頁面或 Realtime |

**研究日記的內容風格：**
- 不是結果摘要（那是 milestone 文章的工作）
- 而是**決策背後的故事**：為什麼測這個？預期 vs 結果？學到什麼？
- 例如：「GINN 看似打破 ceiling，追查後發現是 proxy mismatch——測量工具比模型更重要」

#### 7. 留言/評論系統（預留，暫不開放）

DB schema 先建好，前端暫不顯示：
```sql
CREATE TABLE comments (
  id SERIAL PRIMARY KEY,
  article_id TEXT REFERENCES articles(id),
  user_id UUID REFERENCES profiles(id),
  parent_id INTEGER REFERENCES comments(id),  -- 支援巢狀回覆
  content TEXT NOT NULL,
  status TEXT DEFAULT 'visible',              -- visible / hidden / flagged
  created_at TIMESTAMPTZ DEFAULT NOW()
);
-- 暫不啟用 RLS，等開放時再加
```
開放時機：有穩定會員基礎（50+ 活躍用戶）且有 admin 能力處理 spam/moderation。

#### 8. 會員權限分流（Feature Gating）

**原則：現階段全部開放，但 code 層預埋分流邏輯，付費用戶出現時一鍵切換。**

```
Phase 1（現在）：全部 free，不限制任何功能
Phase 2（有人願意付費時）：啟動 premium 分流
```

```sql
-- Feature flags 表（控制哪些功能需要 premium）
CREATE TABLE feature_flags (
  feature TEXT PRIMARY KEY,
  required_role TEXT DEFAULT 'free',  -- free / premium / admin
  enabled BOOLEAN DEFAULT true,
  description TEXT
);

INSERT INTO feature_flags VALUES
  ('view_feed',         'free',    true, '瀏覽 Feed 文章'),
  ('view_risk_forecast','free',    true, '查看風險預報'),
  ('vix_calculator',    'free',    true, 'VIX 計算器'),
  ('view_paper',        'free',    true, '下載論文'),
  ('ask_question',      'free',    true, '提問（有配額限制）'),
  ('view_ranking',      'free',    true, '查看排名表'),
  ('view_answered',     'free',    true, '查看已解答問題'),
  -- 以下未來切換為 premium
  ('realtime_thinking', 'free',    true, '即時思考流'),       -- 未來 → premium
  ('priority_research', 'free',    true, '優先研究權'),       -- 未來 → premium
  ('full_analytics',    'free',    true, '完整數據分析'),     -- 未來 → premium
  ('unlimited_questions','free',   true, '無限提問'),         -- 未來 → premium
  ('early_access',      'free',    true, '文章提前閱讀'),     -- 未來 → premium
  ('export_data',       'free',    true, '匯出研究數據');     -- 未來 → premium
```

```tsx
// 前端 Feature Gate 元件
function FeatureGate({ feature, children, fallback }) {
  const { user } = useUser()
  const { data: flags } = useFeatureFlags()

  const flag = flags?.[feature]
  if (!flag?.enabled) return null

  const hasAccess = !flag.required_role
    || flag.required_role === 'free'
    || user?.role === flag.required_role
    || user?.role === 'admin'

  return hasAccess ? children : (fallback || <UpgradePrompt />)
}

// 使用方式
<FeatureGate feature="realtime_thinking" fallback={<PremiumBanner />}>
  <RealtimeThinkingStream />
</FeatureGate>
```

**啟動付費時只需：**
```sql
UPDATE feature_flags SET required_role = 'premium'
WHERE feature IN ('realtime_thinking', 'priority_research', 'unlimited_questions', 'early_access');
```
一條 SQL，前端自動分流，不需改 code。

#### 預期的 Premium 定價（參考）
| 方案 | 價格 | 功能 |
|------|------|------|
| Free | $0 | Feed、VIX 計算器、3 題/月、風險預報 |
| Premium | ~$5/月 | 無限提問、優先研究、即時思考流、文章提前閱讀、數據匯出 |

#### 寫入 Skill 的大原則
```
# 後台管理原則（由用戶設定，Claude 自主執行）
- 每日發布上限：2 篇
- 發布時段：台灣時間 9:00 和 18:00
- 品質門檻：content > 500 字 + 有數據表格 + 有結論
- 每週分析一次後台數據，調整研究方向
- 會員問題排名最高者優先研究
- 每週產出一篇「研究日記」（精選 thinking）
- Raw thinking 只在後台顯示，不對外
```

## 改動對照

| 功能 | 現在 | 重構後 |
|------|------|--------|
| 發佈文章 | `Publisher` → 寫 storage JSON | → Supabase `articles` INSERT |
| 記憶系統 | `MemorySystem` → 寫 storage JSON | → Supabase `memory_entries` INSERT |
| 風險預報 | `risk_forecast.py` → 寫 JSON | → Supabase `risk_forecasts` UPSERT |
| 每日更新 | `daily_update.py` → 寫 JSON + sync | → Supabase INSERT |
| 用戶提問 | POST → 本地 JSON（重部署消失）| → Supabase `user_questions` INSERT |
| 前端讀取 | `api.ts` → API/static fallback | → Supabase client 直連 |
| 資料同步 | `sync-data.sh` cp + curl | 不需要（直連 DB）|

## 不變的部分
- Next.js 框架 + Zeabur 部署
- 研究系統 Python CLI + `storage/*.json`（source of truth 不變）
- 本地運算邏輯不變（GARCH、VaR、VT 策略全部在本地跑）
- 論文 LaTeX
- 5-min 數據收集（存本地）
- Git 版本控制

## 關鍵設計：本地 vs DB 的責任劃分
| 資料 | Source of Truth | DB 角色 |
|------|----------------|---------|
| 研究結果（feed, knowledge, thinking） | 本地 storage/ | 展示層（本地 POST 上去）|
| 用戶提問 | DB | 本地定時拉取來研究 |
| 會員帳號 | DB (Supabase Auth) | — |
| 風險預報 | 本地計算 | 展示層 |
| Paper trading | 本地計算 | 展示層 |

---

## Admin Dashboard（後台管理）

### 頁面規劃

| 路徑 | 功能 |
|------|------|
| `/admin` | Dashboard 總覽（KPI 卡片）|
| `/admin/articles` | 文章管理（CRUD、排序、篩選、analytics）|
| `/admin/members` | 會員管理（列表、角色、配額）|
| `/admin/analytics` | 數據分析（圖表、趨勢）|
| `/admin/questions` | 會員問題管理（評分、狀態變更）|

### Dashboard 總覽 KPI
```
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│ 文章總數  │ │ 會員總數  │ │ 今日瀏覽  │ │ 待研究問題│
│   326    │ │   42     │ │   183    │ │    3     │
└──────────┘ └──────────┘ └──────────┘ └──────────┘

┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│ 本週新文章│ │ 本月新會員│ │ 平均閱讀  │ │ 按讚總數  │
│    12    │ │    8     │ │  3m42s   │ │   256    │
└──────────┘ └──────────┘ └──────────┘ └──────────┘
```

### 文章管理 `/admin/articles`
- 列表：標題、**類型**(research/general/diary/daily/qa)、Phase、狀態(draft/scheduled/published)、發佈日期、瀏覽數、按讚數、閱讀時間
- 排序：按日期 / 瀏覽數 / 按讚數 / 類型
- **篩選**：類型、Phase、tags、狀態、日期範圍
- 操作：編輯 content、修改類型/tags、排程、發布、封存、**設定關聯文章**
- **草稿佇列**：待發布文章列表，可拖曳排序、批次排程
- **類型統計**：各類型文章數量佔比、各類型平均瀏覽/按讚
- **關聯管理**：一般文章 ↔ 研究文章的對應關係，自動或手動設定
- 圖表：每日/每週發佈量（按類型分色）、瀏覽趨勢（按類型）

### 會員管理 `/admin/members`
- 列表：Email、顯示名、角色、註冊日期、提問數、最後活動
- 操作：變更角色（free→premium→admin）、重設配額、停用帳號
- 篩選：角色、活躍度、註冊時間
- 統計：新會員趨勢、活躍率、留存率

### 數據分析 `/admin/analytics`
- **流量**：每日/每週 page views、unique visitors
- **文章表現**：Top 10 最多瀏覽 / 最多按讚 / 最長閱讀時間
- **會員行為**：提問分佈、閱讀偏好（哪些 tags 最受歡迎）
- **研究影響**：哪些 Phase 的文章最受歡迎、會員問題主題分佈
- **轉換**：free→premium 轉換率、提問→回答比

### 會員問題管理 `/admin/questions`
- 列表：問題、提出者、分數、狀態、提出日期
- 操作：手動調整分數、變更狀態、指派研究、合併重複問題
- 批次：一鍵評分所有 evaluating 問題

### 權限控制
```sql
-- Admin-only API middleware
CREATE OR REPLACE FUNCTION is_admin()
RETURNS BOOLEAN AS $$
  SELECT EXISTS (
    SELECT 1 FROM profiles
    WHERE id = auth.uid() AND role = 'admin'
  );
$$ LANGUAGE sql SECURITY DEFINER;

-- 所有 admin API 加上檢查
-- Next.js middleware:
-- if (user.role !== 'admin') return NextResponse.redirect('/');
```

### 技術實作
- 圖表：`recharts` 或 `chart.js`（輕量）
- 表格：`@tanstack/react-table`（排序、篩選、分頁）
- 即時更新：Supabase Realtime subscription
- 匯出：CSV 下載（文章列表、會員列表、analytics）

## 時程

| Phase | 內容 | 天數 | 風險 |
|-------|------|------|------|
| 1 | Auth + 用戶提問 | 2-3 | 低 |
| 2 | Feed 遷移 + Analytics | 2-3 | 中 |
| 3 | Memory 遷移 | 2-3 | 中高 |
| 4 | Admin Dashboard | 3-4 | 中 |
| 5 | 清理 + 測試 | 1-2 | 低 |
| **Total** | | **10-15 天** | |

## 成本
| 項目 | 免費 tier |
|------|----------|
| Supabase DB | 500MB |
| Supabase Auth | 50K MAU |
| Zeabur | 不變 |
| **預估月費** | **$0**（資料 < 50MB）|
