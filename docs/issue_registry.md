# Issue Registry — 編號制度

> Boss 指令（2026-06-01 22:41 email，被 gmail dedup bug 丟棄、2026-06-10 回收）：
> 「以後有 issue 應該要編號，後面修好的話要連編號一起報告」

## 規則

1. **編號格式**：`ISS-NNN`（遞增，不重用）。
2. **開立時機**：任何 CRITICAL / 連續 warn / 用戶抓到的問題 → 先在本檔登記拿編號，再開修。
3. **Alert email 標題帶編號**：`[VolPred Alert][CRITICAL] ISS-007 Host cron failure …`。
4. **修復回報必引用編號**：boss report / loop summary 寫「ISS-007 已修復（commit abc1234）」。
5. **狀態**：`open` / `fixed` / `wont_fix`；fixed 必附 commit hash + 驗證方式。
6. 與 `docs/error_log.md` 分工：error_log = 教訓與根因敘事；本檔 = 對 boss 的追蹤編號索引（一行一 issue）。

## Registry

| ID | 開立 | 狀態 | 標題 | 修復 commit / 驗證 |
|----|------|------|------|--------------------|
| ISS-001 | 2026-05-25 | fixed | Host cron failure（hourly dispatch 連續失敗警報；boss 6/4「立刻解決」、6/7「從底層修正」） | 2026-06-10 `_is_audit_signal_log` pattern fix + dashboard monitored 補 4 jobs；連續 3 日無誤報 |
| ISS-002 | 2026-06-10 | fixed | 文章 narrative-arc 重複（K1449/K1091 銅 dup，boss 抓到） | `45ff5d05` arc-dedup 三層 hard gate + regression tests |
| ISS-003 | 2026-06-10 | fixed | Boss 回信被 gmail subject-dedup 系統性丟棄（5 封進垃圾桶、3 指令未執行） | gmail_inbox_poll terminal-status filter；5 封已回收 triage |
| ISS-004 | 2026-06-10 | fixed | FB 監控雙盲（event_article awaiting 對 dashboard/audit 不可見） | dashboard + audit_fb_pipeline 雙源合併；6 篇 awaiting 已可見 |
| ISS-005 | 2026-06-10 | open | 排程沉默死亡偵測缺口（LaunchAgent 死掉 log 凍結在 exit 0 永不警報） | monitored 補 4 jobs + no_fire_evidence 已落地；host_cron_fail 的 log-freeze 偵測待補 |
| ISS-006 | 2026-06-10 | open | release_pool lost-update race + unpublish 無 lock（process audit 3-3/3-4） | 待設計（critical section 重構） |
| ISS-007 | 2026-06-10 | open | 兩個紙上 gate：provenance CI 未接線（audit 2-1）+ paper reproduce gate 無實作（audit 7-1） | 待接線 cron_memory_health + update_paper_full 最小 gate |
| ISS-008 | 2026-06-10 | open | task status vocabulary 失控（24 種 free-form；audit 1-1/1-2） | 待設計（canonical status 集 + migration） |

## ISS-009: mirror feed.json 整檔 PUT 21MB 超時（2026-06-11）
- 症狀：`PUT /api/sync/feed.json` 21MB body，server >180s 無回應（auth 已通，小檔 200）
- 影響：mirror replica 的 feed 整檔同步不可用；canonical Supabase 單篇 sync 正常，無讀者面影響
- 方向：incremental sync（只推 delta）或 gzip + server 端 streaming parse；或廢止整檔 mirror path（評估 mirror feed 是否仍有讀者）
- Priority: P3
