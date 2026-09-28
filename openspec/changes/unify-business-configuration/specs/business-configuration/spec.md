# Spec Delta

## Purpose

约定业务参数存放在哪里、初值从哪里来、修改后何时生效，以及修改非法时如何处理；让管理员的修改立即生效、重启后保留，并且不会被部署配置意外覆盖。

## ADDED Requirements

### Requirement: 业务配置与部署配置分开存放

系统 SHALL 把可以在运行时调整的业务参数作为业务配置存放在数据库中，把启动所需的参数、基础设施连接和密钥作为部署配置，由 `data/.env` 或环境变量提供。

业务配置 SHALL 至少包括以下参数：

- 注册开关：`PLEX_REGISTER`、`EMBY_REGISTER`。
- 会员与线路开关：`PREMIUM_FREE`、`PREMIUM_UNLOCK_ENABLED`、`CREDITS_TRANSFER_ENABLED`。
- 积分价格：`INVITATION_CREDITS`、`UNLOCK_CREDITS`、`DOWNLOAD_UNLOCK_CREDITS`、`LINE_SCHEDULE_UNLOCK_CREDITS`、`PREMIUM_DAILY_CREDITS`、`CREDITS_COST_PER_10GB`、`VAULTWARDEN_REDEEM_CREDITS`。
- 流量额度：`USER_TRAFFIC_LIMIT`、`PREMIUM_USER_TRAFFIC_LIMIT`。
- 其他：`NSFW_LIBS`、`DONATION_MULTIPLIER`、`VAULTWARDEN_ENABLED`、`UPAY_CRYPTO_TYPES`。
- 已经存放在数据库中的幸运转盘配置、转盘随机性参数、21 点配置和勋章中心配置。

特权邀请码列表和线路目录不属于本要求，在各自迁移完成前保持原有的存放方式。

#### Scenario: 业务参数不再写入部署配置文件

- **WHEN** 管理员修改任意一项业务配置
- **THEN** 系统只更新数据库中的该项配置，不改写 `data/.env`

#### Scenario: 部署配置保持原样

- **WHEN** 系统启动
- **THEN** 数据库连接、外部服务地址、Telegram 令牌等部署配置仍按原有规则从 `data/.env` 和环境变量读取

### Requirement: 初值取升级前实际生效的值

某项业务配置在数据库中还没有值时，系统 SHALL 用升级前该实例实际生效的值写入初值。

- 取值的优先级 SHALL 与升级前一致：`data/.env` 中出现的键优先，其次是系统环境变量，再次是工作目录下的 `.env`，最后是代码默认值。
- 初值 SHALL 只写入一次。系统 SHALL NOT 覆盖数据库中已有的值。

#### Scenario: 从 data/.env 取初值

- **WHEN** 数据库中还没有 `DONATION_MULTIPLIER`，`data/.env` 中该键为 9，环境变量中为 7
- **THEN** 系统写入的初值是 9

#### Scenario: 从环境变量取初值

- **WHEN** 数据库中还没有 `UNLOCK_CREDITS`，`data/.env` 中没有该键，环境变量中为 111
- **THEN** 系统写入的初值是 111

#### Scenario: 使用代码默认值

- **WHEN** 数据库中还没有某项业务配置，`data/.env`、环境变量和工作目录下的 `.env` 中也都没有它
- **THEN** 系统写入该项的代码默认值

#### Scenario: 已有值不被覆盖

- **WHEN** 数据库中已经有某项业务配置，而 `data/.env` 中该键的值与之不同
- **THEN** 系统继续使用数据库中的值，不做任何改写

### Requirement: 数据库中的值是业务配置唯一的有效来源

业务配置一旦写入数据库，系统 SHALL 只使用数据库中的值。`data/.env`、环境变量和工作目录下的 `.env` 中同名的键 SHALL NOT 再影响业务行为。

这些旧键仍然存在时，系统 SHALL 正常启动，并在日志中提示这些键已经迁出、不再生效。

#### Scenario: 修改 .env 不再生效

- **WHEN** 运维在 `data/.env` 中修改已迁出的 `INVITATION_CREDITS` 并重启
- **THEN** 系统仍使用数据库中的值，并在启动日志中提示 `INVITATION_CREDITS` 已迁出、不再生效

#### Scenario: 残留的旧键不妨碍启动

- **WHEN** 工作目录下的 `.env` 或环境变量中仍有已迁出的业务键
- **THEN** 系统正常启动，不因为这些键报错

### Requirement: 修改立即生效并在重启后保留

管理员通过后台接口或 bot 命令修改业务配置后，系统 SHALL 在处理下一次请求、命令或任务时使用新值，不需要重启。修改 SHALL 在重启后保留。

一次修改 SHALL 要么完整生效，要么完全不生效；即使存储失败，也 SHALL NOT 出现"当前进程已按新值运行、数据库仍是旧值"这种不一致。

#### Scenario: 后台修改立即生效

- **WHEN** 管理员把 `UNLOCK_CREDITS` 从 100 改为 120，随后有用户发起 NSFW 解锁
- **THEN** 这次解锁按 120 积分计价

#### Scenario: 重启后保留

- **WHEN** 管理员修改某项业务配置后，服务重启
- **THEN** 重启后生效的是修改后的值

#### Scenario: 存储失败

- **WHEN** 管理员修改某项业务配置时，数据库写入失败
- **THEN** 接口返回失败，当前进程和数据库都保持原值

### Requirement: 非法修改被拒绝

每项业务配置 SHALL 有明确的类型和取值约束。违反约束的修改 SHALL 被拒绝，原值不变。

后台设置接口在拒绝时 SHALL 沿用现有的响应格式：HTTP 200，`success` 为 false，`message` 说明原因。

#### Scenario: 积分数值收到布尔值

- **WHEN** 管理员向积分类设置接口提交布尔值 `true`
- **THEN** 接口返回 `success=false`，该项配置保持原值

#### Scenario: 数值超出范围

- **WHEN** 管理员提交负数的积分价格或流量额度
- **THEN** 接口返回 `success=false`，该项配置保持原值

### Requirement: 既有后台设置接口保持兼容

现有 12 个 `POST /api/admin/settings/<slug>` 设置接口和 `GET /api/admin/settings` 设置总览接口，SHALL 保持原有的 URL、鉴权、请求字段和响应格式。

以下现有的请求语义 SHALL 保留：

- 请求缺少字段时，重置为该接口原有的默认值。
- 开关接口按真值解释 `enabled` 字段。

在此基础上，系统 SHALL 保证当前生效的值与持久化的值一致。

兼容接口 `POST /api/admin/settings/emby-premium-free` SHALL 与 `POST /api/admin/settings/premium-free` 的行为相同。

#### Scenario: 开关接口缺少字段

- **WHEN** 管理员调用 `POST /api/admin/settings/plex-register`，请求体中没有 `enabled` 字段
- **THEN** Plex 注册开关被设为关闭，接口返回 `success=true`

#### Scenario: 生效值与重启后的值一致

- **WHEN** 管理员调用开关接口时传入字符串 `"false"`
- **THEN** 该开关当前生效的值与重启后生效的值相同

#### Scenario: 设置总览

- **WHEN** 管理员请求 `GET /api/admin/settings`
- **THEN** 响应中仍包含原有的全部键，取值为各项业务配置当前生效的值

#### Scenario: 兼容接口

- **WHEN** 管理员调用 `POST /api/admin/settings/emby-premium-free`
- **THEN** 系统按 `premium-free` 接口的规则修改该开关，不返回服务器错误

### Requirement: 注册开关命令持久化

管理员用 bot 命令 `/set_register <plex|emby> <flag>` 修改注册开关时，系统 SHALL 像后台接口一样持久化这次修改，重启后保留。命令的参数格式、权限要求和回复文案 SHALL 保持不变。

#### Scenario: 命令修改在重启后保留

- **WHEN** 管理员发送 `/set_register emby 0`，随后服务重启
- **THEN** 重启后 Emby 注册仍为关闭

### Requirement: 原本只能改 .env 的参数提供后台设置

对 `NSFW_LIBS`、`DONATION_MULTIPLIER`、`CREDITS_COST_PER_10GB`、`VAULTWARDEN_ENABLED`、`VAULTWARDEN_REDEEM_CREDITS`、`UPAY_CRYPTO_TYPES` 六项，系统 SHALL 提供管理员可用的后台设置入口：

- 设置接口的响应格式与现有设置接口相同。
- 设置总览中包含这六项当前生效的值。
- 前端管理页提供对应的控件。

修改这六项 SHALL 只影响之后发生的操作：

- 修改捐赠倍率 SHALL NOT 重算已有捐赠对应的积分。
- 修改 NSFW 媒体库列表 SHALL NOT 自动改变已有用户在媒体服务器上的权限。

#### Scenario: 修改捐赠倍率

- **WHEN** 管理员把捐赠倍率从 5 改为 6
- **THEN** 之后登记的捐赠按 6 倍计算积分，已有用户的积分余额不变

#### Scenario: 修改 NSFW 媒体库列表

- **WHEN** 管理员修改 NSFW 媒体库列表
- **THEN** 之后发生的媒体库权限操作按新列表执行，已有用户的媒体服务器权限不会因这次修改被自动改变

#### Scenario: 关闭 Vaultwarden 兑换

- **WHEN** 管理员关闭 Vaultwarden 兑换
- **THEN** 之后的兑换请求按功能关闭处理，不需要重启

### Requirement: 已存于数据库的配置保持原值

幸运转盘配置、转盘随机性参数、21 点配置和勋章中心配置，SHALL 继续使用原有的存储数据：

- 升级后读到的值 SHALL 与升级前相同。
- 缺少的字段按原有规则补上默认值。其中，21 点配置在字段层面合并，`tournament_defaults` 作为整体替换。

存储的数据损坏、无法解析时，系统 SHALL 使用默认值继续运行，并记录错误；SHALL NOT 用默认值覆盖存储中的原始数据。

#### Scenario: 升级后读取原有配置

- **WHEN** 升级前管理员已经保存过 21 点配置
- **THEN** 升级后读到的 21 点配置与升级前完全一致

#### Scenario: 存储的数据损坏

- **WHEN** 转盘配置在存储中已经损坏、无法解析
- **THEN** 系统按默认配置运行并记录错误，存储中的原始数据保持不变

### Requirement: 读取出错不改写配置

读取业务配置时如果发生数据库错误，系统 SHALL 把它当作错误处理；SHALL NOT 当作"没有配置"而写入默认值或初值。

#### Scenario: 数据库短暂不可用

- **WHEN** 读取 21 点配置时数据库暂时不可用
- **THEN** 这次操作以错误结束，数据库中已保存的 21 点配置不被改写

### Requirement: 并发修改不丢失

同时修改同一领域的不同配置项时，系统 SHALL 保留每一项修改。同时修改同一项时，SHALL 以最后提交的修改为准，存储中的数据 SHALL 保持完整、可以解析。

#### Scenario: 同时修改两项会员设置

- **WHEN** 两位管理员同时分别修改 `PREMIUM_DAILY_CREDITS` 和 `PREMIUM_UNLOCK_ENABLED`
- **THEN** 两项修改都生效，重启后也都保留
