## Why

业务参数分散在两个地方，而且都没有类型约束：

- **`.env` 里的运行时开关**：12 个业务开关和价格放在 `.env` 里，包括注册开关、各项积分价格、流量上限和会员开关。后台接口和 bot 在运行时先改 `settings`，再用 `save_config_to_env_file` 重写整个 `.env` 文件，这类调用约有 20 处。
- **只能手改 `.env` 的参数**：`NSFW_LIBS`、`DONATION_MULTIPLIER`、`CREDITS_COST_PER_10GB` 等业务参数没有后台入口。
- **`SystemConfig` 里的配置**：转盘、21 点和勋章中心的配置存在 `SystemConfig` 表里，每个领域都自己实现了一套"默认值 + JSON 合并"。

运行时重写 `.env` 有三个问题：

- 写入不是原子的。
- 基础设施配置和业务参数混在同一个文件里。
- 环境变量的优先级高于 `data/.env`。如果部署时用环境变量设了同名的键，后台改过的值在重启后会被环境变量覆盖。

## What Changes

- **新增 `core/domain_config.py`**：`DomainConfig` 由名称、Pydantic 模型和从 `.env` 取初值的映射组成。它复用 `SystemConfig` 表存储，在进程内缓存；写入时先校验，再持久化，最后清除缓存。
- **各领域在 `config.py` 里声明自己的业务配置**，迁入以下内容：
  - 全部 12 个运行时开关。
  - 只在 `.env` 里的业务参数。
  - 转盘、21 点、勋章中心的现有配置。它们沿用原来的存储键，兼容已有数据。
- **首次读取时写入初值**：如果数据库里还没有值，就从当前的 `.env` 或环境变量取值写入。已部署的实例不会丢配置。
- **后台接口保持不变**：后台设置接口和 `/set_register` 命令的 URL、参数和返回格式不变，内部改为调用 `config.update()`。运行时不再为业务参数写 `.env`。
- **`.env` 只保留启动、基础设施和密钥配置**：`Settings` 删除已经迁出的业务字段。
- **不含特权邀请码和线路目录**：这两项分别由 `move-privileged-codes-to-database` 和 `move-line-catalog-to-database` 处理。在此之前，`save_config_to_env_file` 只剩这两类调用方。
- **BREAKING（运维）**：迁移后，在 `.env` 里修改已迁出的业务参数不再生效，需要到后台修改。

## Capabilities

### New Capabilities

- `business-configuration`：业务参数的存放和生效规则，包括：
  - 哪些参数属于业务配置。
  - 初值从哪里来，以及各来源的优先级。
  - 后台修改立即生效，并且重启后保留。
  - `.env` 只承载基础设施配置和密钥。

### Modified Capabilities

无。`database-configuration` 只约定数据库连接配置，不受影响。

## Impact

- **代码**：
  - `core/config.py`、`core/domain_config.py`，以及各领域的 `config.py`。
  - 后台设置相关的 admin_router 和 bot 命令。
  - 测试夹具：原来 monkeypatch `settings.X` 的测试，改用配置夹具。
- **数据**：`SystemConfig` 表新增若干配置行，表结构不变。
- **回退**：升级后在后台改过的值，回退到旧版本后会丢失，因为旧版本只读 `.env`。
- **依赖**：`restructure-backend-architecture`。它可以和 promote 变更并行，但建议排在 `promote-gift-pack-domain` 之后。
