# Tasks

## 1. 认证修复（dev）

- [x] 1.1 新增部署配置 `WEBAPP_DEV_MOCK_AUTH`（默认 false）和 `WEBAPP_INIT_DATA_MAX_AGE`（默认 86400），以及 `core/auth.mock_auth_enabled()`；开关打开时在启动日志中记警告；在 `.env.example` 和 AGENTS.md 中写明本地开发的设置方法。验证：`tests/test_webapp_auth_security.py` 覆盖默认关闭、开启警告和配置说明。
- [x] 1.2 改写 `verify_telegram_data`：用 `hmac.compare_digest` 比较签名，校验 `auth_date` 的有效期和时间超前，并返回失败原因。验证：安全回归覆盖真实签名、篡改 `user`、缺少 hash/auth_date、过期、超前及两个边界值。
- [x] 1.3 改写 `TelegramAuthMiddleware`：认证失败时直接返回 401 JSON 响应，只在开关打开时接受模拟 hash，日志不再包含 initData 原文；`get_telegram_user` 删除模拟分支。验证：TestClient 覆盖伪造签名、模拟 hash 开关、公开接口和脱敏日志，响应符合 design D4。
- [x] 1.4 从 `check_admin_permission` 中删除 123456789 的特判；把 `TG_ADMIN_CHAT_ID` 改为 `list[int]`，并加上统一的解析器，`_load_from_env_file` 也使用它。验证：安全回归覆盖固定 ID 拒绝、正/负 ID、JSON/逗号来源、非法项警告和管理员通知目标。
  - 未配置的 123456789 调用管理员接口返回 403。
  - `data/.env` 形式 `1001,-1002003004,abc` 解析为 `[1001, -1002003004]`，并有一条警告。
  - 环境变量形式 `["1001"]` 解析为 `[1001]`。
  - 管理员通知的发送目标包含负数的群组 ID。
- [x] 1.5 在 `api/app.py` 中让 `SessionMiddleware` 使用 `SESSION_SECRET_KEY`；未配置时生成随机密钥，并记一条警告。验证：安全回归确认配置密钥优先、缺失时生成临时密钥并警告；SessionMiddleware 仍由 API assembly 注册。
- [ ] 1.6 按 design D6 加固 UPay：删除签名原文串的日志；改用常量时间比较；密钥为空时拒绝下单和回调，并在启动时警告；回调金额与订单金额不一致时拒绝入账并通知管理员；按订单金额入账。验证：
  - 测试覆盖空密钥下伪造回调被拒绝、签名错误、金额不一致（订单和积分都不变，管理员替身收到通知）、正常回调按订单金额入账。
  - 用 caplog 断言日志中不出现密钥和签名原文串。

## 2. 生产分支移植

- [ ] 2.1 确认生产镜像对应的提交，在该提交上创建 hotfix 分支，对旧布局的 `app/webapp/middlewares.py`、`app/webapp/auth.py`、`app/webapp/__init__.py`、`app/config.py`、`app/modules/upay.py` 和加密货币捐赠路由，移植 1.1–1.6 的修改。验证：hotfix 分支的 diff 只包含这些文件、测试和文档。
- [ ] 2.2 把第 1 组的测试移植到 hotfix 分支，只调整导入路径。验证：hotfix 分支上这些测试全部通过，用例与 dev 上一一对应。

## 3. 发布前验证

- [ ] 3.1 在本地用 hotfix 镜像和生产形态的配置启动服务，分别发送四类请求：伪造签名、模拟 hash、过期 initData、正常签名；再在未配置 UPay 密钥的情况下发送一次伪造回调。验证：前三类返回 401，正常签名返回 200；伪造回调被拒绝；日志中不出现 initData 和 UPay 密钥。
- [ ] 3.2 检查生产配置中 `TG_ADMIN_CHAT_ID` 的实际取值，列出修复后会开始收到通知的负数群组 ID，请维护者确认。验证：确认结论已记录；需要删除的 ID 已从配置中移除。
- [ ] 3.3 在 dev 上运行全量回归：`pytest tests/`、`ruff check`、`ruff format --check`、`lint-imports`、`pre-commit run --all-files`，然后运行 `openspec validate fix-webapp-auth-bypass --strict`。验证：全部通过。
- [ ] 3.4 编写发布说明，包含六点：
  - 用户在 Mini App 停留超过 24 小时后，需要重新打开。
  - 本地开发需要打开模拟认证开关。
  - 负数群组开始收到管理员通知。
  - 未配置 UPay 密钥的实例，会停止接收加密货币捐赠。
  - 发布后需要轮换 UPay 密钥。
  - 建议检查近期的特权码生成、设置修改和积分转账记录。

  验证：发布说明包含以上六点。
