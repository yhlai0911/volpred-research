---
name: reference_zeabur_deploy_target
description: 前端部署=CLI deploy-zeabur-safe.sh 到 volpred-v3 服務；搬機器只需改 config.deploy 三個 ID
metadata: 
  node_type: memory
  type: reference
  originSessionId: df279cec-2a1a-4970-b0ae-111055444eb8
---

**前端怎麼部署上線**（2026-06-02 釐清，別再忘）：

- **方法 = CLI**：`cd frontend-v2-fix && ./scripts/deploy-zeabur-safe.sh`（`zeabur deploy` 上傳 working dir → build → 部署）。**不靠 git push**。
- **live 站 `volpred.zeabur.app` = `volpred-v3` 服務**（綁 domain 的那個）。部署 target 必須是它。
- **唯一真實來源 = `config/project_targets.json` 的 `.deploy`**（`zeabur_project_id` / `zeabur_environment_id` / `services.volpred-v3`）。腳本三個 ID 都從 config 讀（env-id 2026-06-02 才改成讀 config，之前硬編）。

**搬機器（換伺服器）= 只改 config.deploy 那三個 ID，方法不變**。2026-06-02 搬到新機器（Tencent Tokyo，新 project）後，正確值：
- project `6a15c5a8f14c612a409a4d77` / env `6a15c5a85dd63457627dd6c7` / volpred-v3 `6a15c5a9938e05c2b6854117`
- 舊機器存 `config .deploy._legacy_pre_20260602`（已遷移、勿用）

**坑（2026-06-02 花很久才搞懂）**：
- `volpred-web`（`…116`，GitHub `yhlai0911/volpred-web`）**沒綁 domain、不是前端、勿動**；別把它當成 v3。
- 服務頁 Source 顯示 `registry-oci…` 只是 `zeabur deploy` build 後 image 存放處，**不代表不能 CLI 部署**（我曾誤判）。
- target 對（…117）→ deployment 直接 RUNNING+上線；target 錯（舊 project 69be521a / volpred-web …116）→ build 成功但 deployment `REMOVED`、永不上線。
- 驗證部署**一定要看 live render**（`curl`/瀏覽器看 volpred.zeabur.app），別只信 `deployed successfully`（那只是上傳成功）；也別 `| tail` 把腳本 exit code 蓋掉。

前端原始碼 repo = github `yhlai0911/volpred-v2`（記錄用；部署不靠它）。關聯 [[reference_strategy_card_metrics_window]]。
