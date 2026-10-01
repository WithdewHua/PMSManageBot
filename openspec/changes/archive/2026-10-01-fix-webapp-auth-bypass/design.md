# Design

## Context

动机见 proposal.md，行为约定见 `specs/webapp-authentication/spec.md`。

现状（dev 的 `3f27100`）：

- `api/middlewares.py` 的 `TelegramAuthMiddleware`：
  - 请求头里没有 initData 时直接放行，由各接口的 `require_telegram_auth` 返回 401。
  - 有 initData 时，遇到模拟 hash 就直接信任；否则调用 `core/auth.verify_telegram_data`。
  - 校验失败时抛出 `HTTPException(401)`，被同一个 `try` 的 `except Exception` 改成 400 重新抛出。在 Starlette 里，用户中间件位于异常处理器之外，所以最终响应是 500（已用最小示例验证）。
- `core/auth.py`：
  - `verify_telegram_data` 用 `==` 比较签名，不看 `auth_date`。
  - `get_telegram_user` 对模拟 hash 和真实 hash 走同一套 JSON 解析。
  - `check_admin_permission` 先判断 `user.id == 123456789`。
- `api/app.py` 按 `WEBAPP_SESSION_SECRET_KEY` 配置 `SessionMiddleware`，这个字段不存在；代码中没有任何地方读写 `request.session`。
- `integrations/upay.py:52-57` 以 INFO 级别打印签名原文串，而签名原文串的末尾就是密钥；签名用 `==` 比较；`UPAY_SECRET_KEY` 默认为空串。回调按 trade_id 找到订单后，以回调中的 `amount` 入账。
- `core/config.py` 的 `_load_from_env_file` 把 `TG_ADMIN_CHAT_ID` 按 `isdigit()` 过滤后转成 int；pydantic 从环境变量得到的是 `list[str]`。这个字段有 141 处读取，包括管理员判断和管理员通知。
- 前端 `main.js` 只在 `NODE_ENV === 'development'` 且没有真实 initData 时，才注入模拟 initData（用户 ID 为 123456789）。
- 生产分支（`origin/main` `ae8a5fc`）使用重构前的布局。同样的问题在 `app/webapp/middlewares.py`、`app/webapp/auth.py`、`app/webapp/__init__.py`、`app/config.py` 中都有。

## Goals / Non-Goals

**Goals：**

- 伪造身份和伪造管理员在任何部署中都不可能；本地开发仍能用模拟认证。
- 认证失败返回确定的 401，不再出现 500。
- 修复可以原样移植到生产分支，单独发布。

**Non-Goals：**

- 不重新设计认证方案，比如引入服务端 session 或 JWT。
- 不改接口的业务鉴权规则。例如 `check-privileged` 是否需要登录，由 `move-privileged-codes-to-database` 决定。
- 不把 `TG_ADMIN_CHAT_ID` 迁成业务配置。它仍然是部署配置。

## Decisions

### D1 模拟认证改为部署开关，默认关闭

- **新增部署配置**：`Settings` 新增 `WEBAPP_DEV_MOCK_AUTH: bool = False`。
- **判断改在一处**：新增 `core/auth.mock_auth_enabled()`，中间件和 `get_telegram_user` 都只通过它判断，不再各自比对字符串。
- **开关关闭时**：模拟 hash 就是一个错误的签名，走正常的校验失败路径，返回 401。
- **开关打开时**：`api/lifespan` 在启动时记一条 warning。
- **本地开发**：前端开发流程不变，本地 `data/.env` 加上 `WEBAPP_DEV_MOCK_AUTH=true` 即可。AGENTS.md 和 `.env.example` 写明这一点。

备选方案是完全删除模拟认证，但这会让本地前端开发必须接入真实的 Telegram，成本过高。另一个备选方案是按 `WEBAPP_URL` 或主机名自动判断开发环境，但它可以被错误配置或伪造，所以不采用。

### D2 删除硬编码的管理员，统一管理员列表的解析

- **删除后门**：`check_admin_permission` 删除 123456789 的特判，只判断 `user.id in settings.TG_ADMIN_CHAT_ID`。
- **统一解析**：把 `TG_ADMIN_CHAT_ID` 的类型改为 `list[int]`，并加一个 pydantic `field_validator(mode="before")`：
  - 接受逗号分隔的字符串，也接受列表。
  - 每一项去掉空白后按 `int()` 解析，保留负数。
  - 无法解析的项记 warning 并忽略。
- **两个来源走同一套规则**：`_load_from_env_file` 中 `TG_ADMIN_CHAT_ID` 的特殊分支改为调用同一个解析函数，所以 `data/.env` 和环境变量的结果一致。

负数群组 ID 此前被静默丢弃，修复后会开始收到管理员通知，这一变化写在 proposal 的 BREAKING 中。

### D3 签名校验与有效期

- **签名比较**：`verify_telegram_data` 改用 `hmac.compare_digest` 比较签名，并返回失败原因（签名缺失、签名不匹配、缺少 `auth_date`、已过期、时间超前），供中间件记录日志。
- **有效期**：
  - 新增部署配置 `WEBAPP_INIT_DATA_MAX_AGE: int = 86400`，单位秒。
  - `auth_date` 早于 `now - max_age`，或晚于 `now + 300`，都判为无效。

备选方案是更短的有效期，比如 1 小时。Mini App 打开以后，initData 在整个会话里保持不变，太短的有效期会让长时间停留的用户频繁收到 401。24 小时在防重放和体验之间取中。

### D4 中间件直接返回 401 响应

中间件不再抛 `HTTPException`，而是直接 `return JSONResponse(status_code=401, content={"detail": ...})`：

| 情形 | detail |
|---|---|
| 签名无效 | 无效的 Telegram 认证数据 |
| 已过期 | Telegram 认证数据已过期，请重新打开应用 |
| 无法解析 | 无法处理 Telegram 认证数据 |

解析和校验都在 `try` 中完成，但 `except` 只处理解析错误。没有 initData 的请求照旧放行。

### D5 日志与 session 密钥

- **日志**：
  - 删除 `logger.debug(f"{init_data=}")`，也删除 warning 日志里的 initData 片段。
  - 失败日志只包含失败原因、`auth_date`；如果能解析出 `user.id`，也一并记录。
- **session 密钥**：
  - `api/app.py` 使用 `settings.SESSION_SECRET_KEY`；为空时生成随机值，并记一条 warning。
  - `SessionMiddleware` 保持挂载，行为与现在一致，只是配置终于生效了。

### D6 UPay 回调加固

- **日志**：`integrations/upay.py` 删除打印签名原文串和签名的两行日志。签名失败时只记录订单号和失败原因。
- **签名比较**：`verify_callback_signature` 改用 `hmac.compare_digest` 比较签名。
- **密钥为空**：`UPAY_SECRET_KEY` 为空时，`UPayService` 视为未配置：
  - 创建订单返回原有的"服务不可用"类错误。
  - 回调一律返回签名校验失败，状态码和响应体与现在签名错误时相同。
  - 启动时记一条警告。
- **金额核对**：回调处理在按 trade_id 找到订单之后，比较回调的 `amount` 与订单记录的金额，按两位小数比较。
  - 不一致时，不改订单状态、不入账，并通知管理员。
  - 一致时，按订单记录的金额入账。
- **范围之外**：重复回调的幂等性问题（完成订单的 UPDATE 不带状态条件）不属于认证问题，由 `promote-remaining-domains` 的 D2（回调幂等与单事务）处理。那个变更只落在重构分支上，所以生产分支在重构版本上线之前，仍然依赖 UPay 不重复回调。

### D7 向生产分支移植

- **修复在两处同时进行**：
  - dev（新布局）实施完整修复并配测试。
  - 在生产实际运行的提交上拉一个 hotfix 分支，对旧布局的对应文件做同样的修改，并移植同样的测试。UPay 相关的旧文件是 `app/modules/upay.py` 和加密货币捐赠的路由。
- **两个分支的测试用例一致**：只调整导入路径，确保两处行为相同。
- **发布**：hotfix 单独打镜像发布，不夹带其他改动。发布前在本地用生产镜像验证 4 类请求，逐一核对状态码：伪造签名、模拟 hash、过期 initData、正常请求；并验证一次空密钥下的伪造回调被拒绝。

## Risks / Trade-offs

- **[生产实际运行的提交不明确]** → 实施前先确认生产镜像对应的提交（`origin/main` 停在 2026-01-04，未必是生产版本），在那个提交上拉 hotfix 分支。
- **[长时间停留的用户收到 401]** → 有效期可以配置；前端收到 401 时已有的错误提示足以引导用户重新打开。发布说明里写明这一点。
- **[负数群组开始收到通知]** → 发布前检查生产配置里 `TG_ADMIN_CHAT_ID` 的实际取值，确认这些群组确实应该收到通知；如果不应该，就先从配置中删除。
- **[本地开发忘记开启开关]** → 所有接口都会返回 401，现象明确；AGENTS.md 和 `.env.example` 都写明开关。
- **[漏洞已存在一年多]** → 本变更不做追溯审计。发布后，建议运维检查访问日志中是否出现过 `mock_hash_for_development`（请求头不一定被记录，能查多少查多少），并复查近期的特权码生成和积分转账记录。
- **[UPay 密钥已经进过日志]** → 发布后在 UPay 端轮换密钥，同步更新部署配置，并清理或限制旧日志的访问。
- **[未配置密钥的实例会停止接收加密货币捐赠]** → 这类实例原本接受可伪造的回调，停用是预期的结果。发布说明中写明：需要这项功能，就必须配置密钥。

## Migration Plan

1. 在 dev 上实施修复并配测试（D1–D6）。
2. 确认生产提交，拉 hotfix 分支移植修复，并跑同样的测试。
3. 用生产镜像在本地验证 4 类请求和伪造回调，然后单独发布 hotfix。
4. 发布后按 Risks 的建议检查日志和近期的敏感操作。
5. 回退：回退镜像即可。回退会重新暴露漏洞，只能作为临时手段。

## Open Questions

无。
