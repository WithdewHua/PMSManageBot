## Why

业务参数分散在两个地方，而且都没有类型约束：

- **`.env` 里的运行时开关**：12 个业务开关和价格放在 `.env` 里，包括注册开关、各项积分价格、流量上限和会员开关。后台接口在运行时先改内存中的 `settings`，再用 `save_config_to_env_file` 重写整个 `data/.env`。这个函数共有 20 处调用：12 处是这些开关，4 处是线路目录，4 处是特权邀请码。
- **只能手改 `.env` 的参数**：`NSFW_LIBS`、`DONATION_MULTIPLIER`、`CREDITS_COST_PER_10GB`、`VAULTWARDEN_ENABLED`、`VAULTWARDEN_REDEEM_CREDITS`、`UPAY_CRYPTO_TYPES` 这 6 个业务参数没有后台入口，改了要重启才生效。
- **`SystemConfig` 里的配置**：转盘（含随机性参数）、21 点和勋章中心的配置存在 `SystemConfig` 表里。
  - 每个领域各写了一套默认值和合并逻辑：21 点做浅合并；转盘用 Pydantic 补缺省值；勋章中心不是 JSON，而是两行 `"1"`/`"0"` 和原文。
  - 读失败时，`get_system_config` 吞掉异常、返回空值，调用方会把它当成"还没有配置"而写入默认值。一次偶发的读错误，就可能用默认值覆盖已有配置；比如 21 点会被写成停用。

运行时重写 `.env` 本身也不可靠：

- **写入不是原子的**：先截断、再整体重写。写失败时只打印一行，接口照样返回成功，而内存里的值已经改了。
- **加载器遇到坏行就停**：启动时逐行加载 `data/.env`，解析到出错的一行就停止，后面所有的键都不再加载。积分类接口会接受 bool，写出 `INVITATION_CREDITS=True` 之后，下次启动就会在这一行中断。新键追加在文件末尾，最容易受影响。
- **改动会静默丢失**：同名键重复时，只更新第一处，而加载时生效的是后面的旧值。写成 `KEY = v`（等号两侧有空格）的键，替换会失败，也不会追加。
- **内存和重启后的值不一致**：开关接口在内存里存 `bool(enabled)`，文件里写 `str(enabled).lower()`。传入字符串 `"false"` 时，内存里是开启，重启后却是关闭。
- **`/set_register` 不落盘**：这个 bot 命令只改内存，重启后就丢了；而后台改同一个开关会落盘。
- **基础设施配置和业务参数混在同一个文件里。**

实测的配置优先级是：`data/.env` 中出现的键 > 系统环境变量 > 工作目录 `.env` > 代码默认值。之前有两处写反了：本提案早先的版本和 AGENTS.md 都说"环境变量优先于 `data/.env`"。

## What Changes

- **新增 `core/domain_config.py`**：
  - `DomainConfig` 由名称、Pydantic 模型、存储位置和旧配置来源的映射组成。
  - 它复用 `SystemConfig` 表存储，在进程内缓存。
  - 写入时先校验，再在数据库事务中持久化，提交后清除缓存。
  - 读失败时报错，不会拿默认值覆盖已有配置。
- **`SystemConfig` 读写收拢到 `core/kv.py` 的模块级函数**：提供 `*_tx` 版本，区分"没有这一行"和"读取出错"。同时从门面摘除 `SystemConfigRepository`。
- **各领域在 `config.py` 里声明自己的业务配置**，每个配置只归一个领域，迁入以下内容：
  - 全部 12 个运行时开关和价格。
  - 6 个只在 `.env` 里的业务参数。
  - 转盘、随机性、21 点、勋章中心的现有配置。它们沿用原来的存储键和合并规则，兼容已有数据。
- **首次启动时写入初值**：如果数据库里还没有某项配置，就写入升级前这个实例实际生效的值，按上面的实测优先级取值。只在"没有这一行"时写入，不覆盖已有值。已部署的实例不会丢配置。
- **后台接口保持不变**：
  - 12 个后台设置接口、设置总览接口的 URL、参数和返回格式不变，内部改为调用领域配置的 `update()`。
  - 缺字段时重置为默认值、开关按真值解释这类现有语义都保留。
  - 以下几处行为有变化：
    - `/set_register` 改为持久化，与后台修改同一个开关的效果一致。
    - 积分类数值接口拒绝 bool。
    - 已经损坏的兼容接口 `/settings/emby-premium-free` 修复为与 `/settings/premium-free` 相同。
- **为 6 个无入口的参数新增后台设置**：
  - 新增 6 个 `POST /api/admin/settings/<slug>` 接口，设置总览里也加上这 6 项。
  - 前端管理页新增对应的控件。
  - 修改立即生效，只影响之后的操作：
    - 捐赠倍率不重算已有积分。
    - 改 `NSFW_LIBS` 不会自动重新同步已有用户的媒体服务器权限。
- **`.env` 只保留启动、基础设施和密钥配置**：
  - `Settings` 删除已经迁出的业务字段。
  - 旧的键仍然留在 `.env` 或环境变量里时，启动时只记一条"已迁出，不再生效"的警告，不会因为未知键而启动失败。
- **不含特权邀请码和线路目录**：这两项分别由 `move-privileged-codes-to-database` 和 `move-line-catalog-to-database` 处理。在此之前，`save_config_to_env_file` 只剩这两类共 8 处调用。
- **BREAKING（运维）**：迁移后，在 `.env` 或环境变量里修改已迁出的业务参数不再生效，需要到后台修改。

## Capabilities

### New Capabilities

- `business-configuration`：业务参数的存放和生效规则，包括：
  - 哪些参数属于业务配置，以及 `.env` 里还剩什么。
  - 初值从哪里来，以及各来源的优先级。
  - 后台修改立即生效，并且重启后保留；非法值被拒绝。
  - 既有后台接口的兼容性，以及新增的 6 项后台设置。
  - 已存于系统配置表的配置保持原值；读取出错时不会被默认值覆盖。

### Modified Capabilities

无。`database-configuration` 只约定数据库连接配置，不受影响。

## Impact

- **代码**：
  - `core/config.py`、`core/kv.py`，新增 `core/domain_config.py`。
  - 各领域新增或改写 `config.py`。
  - 12 个设置接口所在的 admin_router、`/set_register` 命令、设置总览接口；新增 6 个设置接口。
  - 68 处业务参数读取点改为读取领域配置。其中导入时就被固定下来的读取，要改成调用时读取；integrations 的默认参数改由调用方传入。
  - `tests/architecture`：新增跨域读取配置的规则；`update()` 只允许配置所属领域调用。
  - 测试夹具：pytest 不再读取仓库里的 `data/.env`；原来 monkeypatch `settings.X` 的测试改用配置夹具。
- **前端**：`webapp-frontend` 的管理页（`Management.vue`）和 `adminService.js` 新增 6 项设置。
- **数据**：`SystemConfig` 表新增若干配置行，表结构不变。
- **回退**：旧版本只读 `.env`，所以升级后在后台改过的值，回退后会丢失。回退前，用只读脚本把数据库中的业务配置导出为 `.env` 片段，写回 `data/.env`。
- **依赖**：`restructure-backend-architecture`。建议排在 `promote-gift-pack-domain` 之后。21 点在 `promote-blackjack-domain` 中新增的 `blackjack/config.py`，由本变更改为 `DomainConfig` 声明。
