# Spec Delta

## Purpose

约定 WebApp 请求如何确认调用者的 Telegram 身份、谁拥有管理员权限，以及认证失败时的表现；保证身份不能伪造，管理员权限只来自部署配置。

## ADDED Requirements

### Requirement: 身份只来自有效的 Telegram 签名

对携带 Telegram initData 的请求，系统 SHALL 用机器人令牌派生的密钥校验签名，校验通过后才能把 initData 中的用户作为请求身份。签名比较 SHALL 使用常量时间比较。

签名缺失或不匹配的请求 SHALL 以 HTTP 401 拒绝，响应体为 `{"detail": <说明>}`。系统 SHALL NOT 因认证失败返回 500。

#### Scenario: 有效签名

- **WHEN** 请求携带由 Telegram 正确签名、且在有效期内的 initData
- **THEN** 系统以 initData 中的用户作为请求身份处理请求

#### Scenario: 篡改用户信息

- **WHEN** 请求携带的 initData 中，`user` 字段在签名之后被修改
- **THEN** 系统返回 401，不以任何用户身份处理请求

#### Scenario: 生产环境使用模拟 hash

- **WHEN** 未开启开发模拟认证，请求携带 `hash=mock_hash_for_development`
- **THEN** 系统按签名无效处理，返回 401

### Requirement: 开发模拟认证必须显式开启

系统 SHALL 只在部署配置显式开启开发模拟认证时，才接受模拟 hash 并信任其中的用户信息。这个开关 SHALL 默认关闭，并且只能通过部署配置设置，不能通过后台接口修改。开启时，系统 SHALL 在启动日志中给出警告。

#### Scenario: 默认关闭

- **WHEN** 部署配置中没有设置开发模拟认证
- **THEN** 携带模拟 hash 的请求返回 401

#### Scenario: 本地开发开启

- **WHEN** 本地部署配置开启了开发模拟认证，前端开发服务器发送模拟 initData
- **THEN** 系统以模拟用户身份处理请求，并且启动日志中有开启模拟认证的警告

### Requirement: initData 有效期

系统 SHALL 拒绝以下 initData，返回 401：

- 缺少 `auth_date`。
- `auth_date` 早于可配置的有效期，默认 24 小时。
- `auth_date` 超前当前时间 5 分钟以上。

#### Scenario: 超过有效期

- **WHEN** 请求携带的 initData 签名有效，但 `auth_date` 是 25 小时前
- **THEN** 系统返回 401

#### Scenario: 缺少 auth_date

- **WHEN** 请求携带的 initData 签名有效，但没有 `auth_date`
- **THEN** 系统返回 401

### Requirement: 管理员权限只由配置的管理员列表决定

用户的 Telegram ID 包含在部署配置 `TG_ADMIN_CHAT_ID` 中时，系统 SHALL 视其为管理员；否则 SHALL NOT 授予管理员权限。代码中 SHALL NOT 存在任何固定授予管理员权限的用户 ID。

#### Scenario: 未配置的固定 ID

- **WHEN** ID 为 123456789 的已认证用户调用管理员接口，而该 ID 不在 `TG_ADMIN_CHAT_ID` 中
- **THEN** 系统返回 403

#### Scenario: 配置中的管理员

- **WHEN** ID 在 `TG_ADMIN_CHAT_ID` 中的已认证用户调用管理员接口
- **THEN** 系统按管理员身份处理请求

### Requirement: 管理员列表的解析与来源无关

无论 `TG_ADMIN_CHAT_ID` 来自 `data/.env`（逗号分隔）还是环境变量（JSON 列表），系统 SHALL 把每一项解析为整数，并保留负数的群组 ID。无法解析的项 SHALL 被忽略，并记录警告。

#### Scenario: 环境变量中的字符串 ID

- **WHEN** 环境变量以 JSON 列表 `["1001"]` 提供 `TG_ADMIN_CHAT_ID`
- **THEN** ID 为 1001 的已认证用户拥有管理员权限

#### Scenario: 负数的群组 ID

- **WHEN** `data/.env` 中 `TG_ADMIN_CHAT_ID=1001,-1002003004`
- **THEN** 管理员通知同时发送给 1001 和群组 -1002003004

#### Scenario: 无法解析的项

- **WHEN** `TG_ADMIN_CHAT_ID` 中包含无法解析为整数的项
- **THEN** 系统忽略该项并记录警告，其余各项照常生效

### Requirement: 认证数据不进入日志

系统 SHALL NOT 在任何级别的日志中写入 initData 原文或签名。认证相关的日志只允许包含用户 ID、`auth_date` 和失败原因。

#### Scenario: 签名校验失败

- **WHEN** 一个请求因签名无效被拒绝
- **THEN** 日志中记录失败原因，不包含该请求的 initData 原文或 hash

### Requirement: 会话密钥来自部署配置

系统 SHALL 使用部署配置 `SESSION_SECRET_KEY` 作为 Web 会话的签名密钥。未配置时，系统 SHALL 为本进程生成随机密钥，并在启动日志中给出警告。

#### Scenario: 已配置会话密钥

- **WHEN** 部署配置中设置了 `SESSION_SECRET_KEY`
- **THEN** 服务重启前后签发的会话 Cookie 都能通过校验

#### Scenario: 未配置会话密钥

- **WHEN** 部署配置中没有 `SESSION_SECRET_KEY`
- **THEN** 系统使用随机密钥正常启动，并在启动日志中警告

### Requirement: 支付回调的签名与金额校验

系统 SHALL 只处理签名正确的 UPay 支付回调，并且签名 SHALL 使用常量时间比较。

- 未配置 UPay 签名密钥时，系统 SHALL 拒绝创建加密货币订单，拒绝全部回调，并在启动日志中警告。
- 回调中的订单金额与本地订单记录不一致时，系统 SHALL 拒绝入账，保持订单状态不变，并通知管理员。
- 入账的积分和捐赠额 SHALL 以本地订单记录的金额为准。
- 系统 SHALL NOT 在日志中写入签名原文串或签名密钥。

#### Scenario: 未配置签名密钥

- **WHEN** 部署配置中没有 UPay 签名密钥，有人发送一个按空密钥计算签名的"支付成功"回调
- **THEN** 系统拒绝该回调，订单状态和用户积分都不变

#### Scenario: 金额不一致

- **WHEN** 一个签名正确的回调所报的金额与本地订单金额不同
- **THEN** 系统不入账，订单保持原状态，管理员收到告警

#### Scenario: 日志不含密钥

- **WHEN** 系统处理一次 UPay 下单或回调
- **THEN** 日志中不出现签名原文串，也不出现签名密钥
