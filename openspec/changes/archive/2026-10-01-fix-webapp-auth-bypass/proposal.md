## Why

WebApp 的认证可以被完全绕过，而且问题从 2025-06-14（`ce56075`）起就一直存在。重构前的 `app/webapp/` 和重构后的 `app/api/`、`app/core/` 里都有：

- **模拟认证没有开关**：认证中间件只要看到 initData 里的 `hash` 等于 `mock_hash_for_development`，就跳过签名校验；`get_telegram_user` 随后直接信任请求里 `user` 字段的 JSON。所以任何人都能伪造请求头，冒充任意 Telegram 用户：转走积分、领礼包、兑换邀请码。
- **硬编码的管理员**：`check_admin_permission` 把 ID 为 123456789 的用户直接当作管理员。这个 ID 正是前端开发模式模拟用户的 ID。两个问题叠加，不需要知道任何真实 ID，就能调用所有管理员接口，包括生成特权邀请码和修改业务设置。

同一条链路上还有几处较轻的问题：

- **没有有效期**：initData 的 `auth_date` 从不校验，拿到一份就可以永久重放。
- **签名比较**：签名用 `==` 比较，不是常量时间比较。
- **日志泄露**：中间件在 debug 日志里写入完整的 initData，签名失败时在 warning 日志里写入前 100 个字符，这些日志可以直接拿来重放。
- **签名无效时返回 500**：签名无效时，中间件在自己的 `try` 里抛出 401，又被 `except Exception` 接住，改成 400 重新抛出。而中间件抛出的 `HTTPException` 不经过 FastAPI 的异常处理器，所以最终返回 500。
- **session 密钥**：`api/app.py` 读的是并不存在的 `WEBAPP_SESSION_SECRET_KEY`，配置好的 `SESSION_SECRET_KEY` 从未生效，每次启动都换一个随机密钥。目前代码里没有使用 session，所以暂时没有实际影响。
- **`TG_ADMIN_CHAT_ID` 的解析**：
  - 从 `data/.env` 读取时，非纯数字的项会被静默丢弃，其中包括负数的群组 ID。
  - 从环境变量读取时，元素保持为字符串，于是管理员判断永远不成立。

UPay 支付回调也有同类问题：

- **密钥进了日志**：生成签名时，以 INFO 级别打印签名串，而签名串末尾就是 `UPAY_SECRET_KEY`。
- **密钥为空时回调可以伪造**：`UPAY_SECRET_KEY` 默认为空串。没有配置密钥的实例，任何人都能算出合法签名，伪造"支付成功"回调并获得积分。
- **入账金额没有核对**：入账金额取回调里的 `amount`，没有和订单记录的金额比较。

生产环境跑的是重构前的代码，同样受影响。这个变更独立于重构的顺序，应当最先实施并尽快发布。

## What Changes

- **模拟认证默认关闭**：
  - 新增部署配置 `WEBAPP_DEV_MOCK_AUTH`，默认为 false，只能通过 `data/.env` 或环境变量设置，不属于业务配置。
  - 关闭时，模拟 hash 按普通的无效签名处理。
  - 开启时，启动日志给出明确警告。
- **删除硬编码的管理员**：管理员身份只由 `TG_ADMIN_CHAT_ID` 决定。`.env.example` 中本来就把 `TG_ADMIN_CHAT_ID` 设为 123456789，所以本地开发的模拟用户仍然是管理员。
- **校验 initData 的有效期**：
  - 缺少 `auth_date`、早于有效期（新增部署配置 `WEBAPP_INIT_DATA_MAX_AGE`，默认 86,400 秒）或超前当前时间 5 分钟以上的请求，一律拒绝。
  - 签名改用常量时间比较。
- **认证失败统一返回 401**：由中间件直接生成 `{"detail": …}` 响应，不再抛异常，也就不会再变成 500。
- **日志不再记录 initData 原文**：只记录用户 ID、`auth_date` 和失败原因。
- **session 密钥读取 `SESSION_SECRET_KEY`**：没有配置时，仍生成随机密钥，并记一条警告。
- **统一 `TG_ADMIN_CHAT_ID` 的解析**：无论来自哪个来源，都解析成整数列表并保留负数的群组 ID；无法解析的项记警告后忽略。
- **加固 UPay 回调**：
  - 日志中不再出现签名串和密钥。
  - 签名改用常量时间比较。
  - 没有配置 `UPAY_SECRET_KEY` 时，拒绝创建加密货币订单，也拒绝所有回调；启动时给出警告。
  - 入账金额以订单记录为准；回调中的金额与订单不一致时，拒绝入账并通知管理员。
- **向生产分支移植**：在生产实际运行的分支上，对重构前的文件（`app/webapp/middlewares.py`、`app/webapp/auth.py`、`app/webapp/__init__.py`、`app/config.py`）做同样的修复，单独发布。
- **BREAKING（本地开发）**：本地前端开发需要在 `data/.env` 中设置 `WEBAPP_DEV_MOCK_AUTH=true`。
- **BREAKING（用户）**：Mini App 打开超过 24 小时后再发起请求，会收到 401，需要重新打开。
- **BREAKING（运维）**：原来被静默丢弃的负数群组 ID，此后会正常收到管理员通知。

## Capabilities

### New Capabilities

- `webapp-authentication`：WebApp 请求的身份认证与管理员授权，包括：
  - 签名校验和有效期。
  - 开发模拟认证的开关。
  - 管理员身份的来源，以及管理员列表的解析。
  - 认证失败时的响应。
  - 认证数据不进入日志。
  - 支付回调的签名与金额校验。

### Modified Capabilities

无。

## Impact

- **代码**：
  - `core/auth.py`、`api/middlewares.py`、`api/app.py`，以及 `core/config.py` 中的 `TG_ADMIN_CHAT_ID` 解析和两项新增部署配置。
  - `integrations/upay.py` 和 `domains/crypto_donation/router.py` 中的签名与回调处理。
  - 生产分支上对应的旧文件。
- **前端**：不需要改动。模拟认证只在 `NODE_ENV=development` 时注入。
- **文档**：AGENTS.md 补充本地开发说明；`.env.example` 增加两项部署配置和说明。
- **测试**：新增中间件、管理员判断和配置解析的测试。
- **发布**：生产分支单独打热修复版本；dev 分支同步合入。与重构的各个变更之间没有依赖。
