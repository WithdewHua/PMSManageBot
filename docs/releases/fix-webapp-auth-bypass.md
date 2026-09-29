# WebApp 认证与 UPay 安全修复

发布 `fix-webapp-auth-bypass` 时请完成以下事项：

1. Mini App 的 Telegram `initData` 有效期默认为 24 小时；用户停留超过 24 小时后，需要重新打开 Mini App 获取新的 `initData`。
2. 本地前端开发如果不连接真实 Telegram，需要在 `data/.env` 中显式设置 `WEBAPP_DEV_MOCK_AUTH=true`；生产环境必须保持关闭。
3. `TG_ADMIN_CHAT_ID` 中配置的负数群组 ID 将不再被静默丢弃，并会开始收到管理员通知；发布前必须确认这些群组确实应当接收通知。
4. 未配置 `UPAY_SECRET_KEY` 的实例会停止创建加密货币捐赠订单，并拒绝加密货币支付回调。
5. 发布后必须轮换 UPay 签名密钥，并同步更新部署配置。
6. 建议检查近期的特权码生成、设置修改和积分转账记录；本次修复不包含历史访问审计。

## 生产发布顺序

1. 以 `origin/main` 的生产基线 `ae8a5fca8dc57b5dc841cb14fe4efa2084bed8a9` 创建
   `hotfix/webapp-auth-bypass-ae8a5fc`。
2. 解压并应用 `openspec/changes/fix-webapp-auth-bypass/production-hotfix.patch.gz`，并运行旧布局认证回归和生产形态 smoke（例如 `gzip -dc ... | git apply`）。
3. 配置真实的 `SESSION_SECRET_KEY`、`UPAY_SECRET_KEY` 和经过确认的 `TG_ADMIN_CHAT_ID`。
4. 单独构建、发布 hotfix 镜像，再观察认证失败、UPay 回调和管理员通知日志。
5. 发布后轮换 UPay 密钥，并限制旧日志的访问权限。

生产补丁的基线、允许变更路径、校验结果和 SHA-256 记录在
`openspec/changes/fix-webapp-auth-bypass/production-hotfix.json`。
