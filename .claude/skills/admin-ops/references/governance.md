# Incident Closure Gate

平台問題只能用兩種結案狀態：

- `contained`：症狀暫停，但五步尚未全過。
- `root_cause_fixed_and_verified`：以下五步都有 evidence。

## 五步

1. **症狀**：讀 live source、log、receipt、時間戳與上下游交接。
2. **根因**：定位到 logic、contract、clock、state machine、API、permission、checker
   或 architecture。
3. **底層修正**：修改可重播的 code／contract／automation；補值或重跑只算止血。
4. **回歸**：重跑案例與測試，再由 provider/API/hash/downstream acknowledgement 回讀。
5. **制度化**：把防復發落在既有 owner 的 checker、contract、skill 或操作紀錄。

根因未知時回報 `blocked`；只有一次乾淨 observation 時仍是 `contained`。不要以 process
exit 0、UI toast 或手工資料修正代替下游 evidence。
