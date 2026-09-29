# Design

## Context

动机见 proposal.md。本设计假定以下变更已完成：

- `promote-gift-pack-domain`：premium 已有 `grant_premium_days_tx` 和 `sync_premium_media_access`；lines 已有 `unlock_line_schedule_tx`；media_access 已有 `unlock_download_tx`；基线重键脚本、`types` 角色和积分 `*_tx` 的缓存失效自登记可用。
- `unify-business-configuration`：`premium_free` 和 `line_schedule_unlock_credits` 已归 lines 配置，两个流量额度已归 traffic 配置，会员相关的键归 premium 配置，`unlock_credits`、`download_unlock_credits`、`nsfw_libs` 归 media_access 配置；`SystemConfigRepository` 已从门面摘除，lines 改用 `core.kv`。
- `promote-account-domains`：identity 提供类型化查询和兼容层；traffic 已有 `service.rename_user`。

现状（调研时的 `3f27100`）：

| 领域 | 规模 | mixin | 说明 |
|---|---|---|---|
| lines | 2,923 行 | `LinesRepository`，24 个方法，其中 7 个没有调用方 | 用户接口 20 个，管理员接口 12 个；`api/app.py` 按函数名挂载路由，函数改名会导致启动失败 |
| custom_lines | 2,162 行 | 无 | repository 只有 2 个函数，SQL 分散在路由、管理员路由、任务和 service 中 |
| traffic | 1,498 行 | `TrafficRepository`，9 个方法，其中 7 个主要被外部调用 | 没有 service |
| premium | 1,781 行 | `PremiumRepository`，8 个方法 | service 有 582 行，来自旧 premium.py |
| media_access | 783 行 | `MediaAccessRepository`，5 个方法 | |

**lines**

- 绑定流程：先检查权限，再调用 `set_*_line`（独立事务，不检查影响行数），最后写 Redis。旧值不是高级线路时，先把它写进 `*_last_user_defined_line`，再写 `*_user_defined_line`。
- 自动切换任务每分钟运行一次：
  - 选出已解锁或 `is_premium` 为 1 的用户，不检查到期时间。
  - 没有生效的调度时不回退到原线路。
  - 目标线路为 "auto" 时，数据库里写字面量 "auto"，并删除 Redis 键。
  - 选出用户的读取 session 一直开着，期间又逐人写入。
- 网关缓存（Redis db2，无 TTL）：`user_info:plex|emby:<小写用户名>`、`*_user_defined_line:*`、`*_last_user_defined_line:*`。`write_user_info_cache` 每 15 分钟全量写入一次。
- 高级线路的判定用子串匹配（`lines/rules.py:37`，直接读 settings）；免费列表用精确匹配。

**custom_lines**

- 状态机包括：申请、审批、驳回、用户和管理员下线、上线、续期、删除。
- 三个定时任务（到期检查、流量检查、月度结算）和删除、下线，都在打开的 session 里依次 await 解绑、禁用调度和发送 Telegram，最后才提交。
- 结算按线路逐条调用 `credits_service.add`，没有结算记录。
- 上线、续期和提交申请的 ImportError 回归及异常原文泄露已由 `fix-live-defects` 修复，后续提升冻结修复后的成功和失败响应。

**traffic**

- 流量采集任务每分钟一次：从 Redis db15 用 Lua 移动队列，解析 nginx 和 stream 两种日志，token 转用户名时查 db3 缓存（Emby 未命中时调 API），用 `event_hash` 的唯一键去重，每 500 条插入并提交一次。
- 月度聚合与清理任务在每月 1 日 01:00 运行，逐行用 SAVEPOINT。
- `_get_line_monthly_traffic` 是模块级函数，使用调用方的 session，吞掉异常并返回 0。

**premium**

- 购买顺序：由 `fix-live-defects` 冻结为扣分与会员授予同一事务；扣分失败时会员不变，永久会员返回固定拒绝。
- 到期任务：逐用户隔离处理，逐个用户撤销下载权限并解绑会员线路；线路为 NULL 时不会中断整批。这些行为已由 `fix-live-defects` 修复。
- 会员线路的解绑逻辑与 lines 的 `unbind_*_premium_free` 重复。
- rules 直接读 settings。
- 会员流量欠额列由 watch_rewards 用原生 SQL 写了 6 处。

**media_access**

- NSFW 解锁和锁定：先调 Plex 或 Emby，成功后再在两个独立事务里扣分或退分、设置标志。
- 下载解锁：先扣分，再设标志，两个事务；设标志时不检查影响行数。
- `check_download_unlock` 与 lines 的 `check_line_schedule_unlock` 几乎逐行重复，而"会员是否有效"有三种口径：
  - 只看标志：额度、线路权限、网关缓存。
  - 看标志加到期时间：media_access、lines、gift_pack。
  - 结算口径：watch_rewards。
- `update_all_lib` 没有调用方。

**基线**

- 本变更名下 199 条：lines 90、custom_lines 43、premium 33、media_access 24、traffic 9。其中 lines→profile 64 条、custom_lines→profile 26 条，都是 `profile.schemas` 中的模型。
- import-linter：三个线路相关领域有 49 条忽略项，premium 和 media_access 有 16 条，外加门面组合边和门面冻结的放行项。

**测试**：只有 `test_b3_decycles` 和少量装配测试；没有 fakeredis。

## Goals / Non-Goals

**Goals：**

- 五个领域达到目标形态：入口只调用 service，所有 SQL 在 repository 中，跨域调用经 service 或 `*_tx`。
- 每个用例的数据库写入都在一个事务里完成；媒体服务器同步和通知都在提交后执行，失败时通过补偿保持用户看到的结果不变。
- 线路目录只能通过 lines 的目录接口读写，为 `move-line-catalog-to-database` 替换存储做好准备。
- 网关的 Redis 键和值、接口响应、调度任务，都与现在逐字一致。
- 清空本变更名下的基线条目和忽略项。

**Non-Goals：**

- 不重复修复已由 `fix-live-defects` 完成的缺陷；本变更冻结以下修复后的行为：
  - 自建线路上线、续期和提交申请成功路径可正常导入并返回成功，失败响应不暴露异常原文。
  - 月度结算幂等，按配置时区计算月份，并按不区分大小写的所有者规则排除流量。
  - 会员到期任务逐用户隔离，能撤销应撤销的下载权限，NULL 线路不会中断整批。
  - 永久会员购买返回固定业务拒绝；零额退款是无操作。
  - 线路预览对他人账号返回完整目录，当前线路返回 `null`；自己的账号继续使用个性化权限结果。
- 不统一"会员是否有效"的口径，只命名和去重。
- 不迁移线路目录的存储；不改线路名的子串匹配和精确匹配。
- 不改 Emby 与 Plex 线路列表之间现有的差异，包括 Emby 免费项追加的 "PREMIUM" 标签。

## Decisions

### D1 线路目录接口

新增 `lines/catalog.py`（repository 角色）和 `lines.service` 中的目录函数，作为读写线路目录的唯一入口：

```python
def normal_lines() -> list[str]: ...
def premium_lines() -> list[str]: ...
def free_premium_lines() -> list[str]: ...
def line_tags(name: str) -> list[str]: ...
def all_line_tags() -> dict[str, list[str]]: ...
def add_line(name: str, *, premium: bool) -> None: ...
def delete_line(name: str, *, premium: bool) -> None: ...
def set_line_tags(name: str, tags: list[str]) -> None: ...
def set_free_premium_lines(names: list[str]) -> None: ...
```

- **存储不变**：本变更中，这些函数仍然读写 `settings` 加 `save_config_to_env_file`（两个线路列表），以及 `core.kv`（标签和免费线路）。顺序、去重和编码规则都与现在一致。
- **改为调用目录接口的地方**：
  - lines 的路由和 service。
  - premium 的管理员路由（高级线路的增删、免费线路设置）。
  - traffic 和 premium 的 repository（高级流量统计）。
  - reports 的设置总览与流量总览。
  - `lines.rules.is_binded_premium_line`：改为纯函数，以高级线路列表作为参数。
- **架构检查**：禁止在 lines 以外读取 `STREAM_BACKEND`、`PREMIUM_STREAM_BACKEND`，或 `SystemConfig` 中的 `line_tag`、`free_premium_line` 键。

### D2 "会员是否有效"与宽表读取规则

- **命名三种口径**：在 `identity/rules.py` 中，为宽表会员列的三种读取口径各写一个纯函数：
  - `premium_flag_set(row)`：只看标志。
  - `premium_active(row, now)`：看标志加到期时间；到期时间无法解析时，按调用方原来的回退方式处理，由参数指定。
  - 结算口径：仍放在 `premium.rules`。
- **放在 identity 的原因**：列在 identity 的宽表上，而 lines 和 media_access（T2）不能依赖 premium（T3）。
- **不改口径**：每个调用点改用与原来相同口径的函数，由测试逐一证明结果不变。
- **合并重复的检查**：`check_download_unlock` 和 `check_line_schedule_unlock` 中重复的部分改为调用这些函数。

### D3 premium

- **repository**：改为模块级函数，并删除 service 中的 SQL 和 4 处延迟导入门面。新增 `update_traffic_debt_tx(session, account, *, debt_bytes, updated_date)`，供观看结算使用。
- **购买**：`premium.service.purchase(tg_id, service, days)` 在一个事务里依次执行：锁统计行 → `deduct_tx`（金额与原来一致，包括浮点截断）→ `grant_premium_days_tx`。提交后同步媒体权限并发送通知。
  - 扣分失败时，会员不会被授予。
  - 永久会员购买的固定业务拒绝已由 `fix-live-defects` 处理，这里冻结修复后的行为。
- **到期、临期、统计三个任务**：查询移进 repository，编排放在 service。执行顺序（先批量降级并提交，再逐个处理）保持不变。
- **会员线路的解绑**：统一调用 `lines.service.unbind_premium_line(account)`，删除 premium 中的重复实现。两份实现在各种输入下的数据库写入和 Redis 写入完全相同，先用对照测试证明这一点，再删除重复。
- **管理员路由**：premium 管理员路由中管理线路目录的 8 个接口，路径和函数名都不变，内部改为调用 `lines.service` 的目录函数。
- **错误契约**：`sync_media_permission` 和 `update_premium_status` 删除门面参数。原来用 `NameError` 表示"未绑定"的信号，改为类型化异常 `PremiumAccountNotBound`；到本变更时，外部调用方已全部改用 `*_tx`，不再依赖这个信号。

### D4 media_access：提交后同步与补偿

- **NSFW 解锁**：
  1. 事务 A：扣分并设置解锁标志和时间。
  2. 提交后，调用 Plex 或 Emby 修改媒体库权限。
  3. 媒体调用失败时，执行补偿事务 B：还原标志，并用 `add_tx` 退还积分，然后返回原来的错误响应。
- **NSFW 锁定**：
  1. 事务 A：清除标志，并按 `caculate_credits_fund` 退分；退分为 0 时跳过积分调用。
  2. 提交后，调用媒体服务器移除媒体库。
  3. 失败时执行补偿：恢复标志并扣回退款。
- **下载解锁**：在一个事务里完成扣分和设置标志，设置标志时检查影响行数；未绑定时抛出类型化异常，整体回滚。提交后同步媒体服务器，失败时与现在一样只记 warning。未绑定时不扣分、返回"请先绑定 Plex/Emby 账户"，这一修复已由 `fix-live-defects` 的 D11 完成（复用 `unlock_download_tx`），本变更保持修复后的行为。
- **补偿失败**：记录 error 并通知管理员。
- **`caculate_credits_fund`**：改为纯函数，接收 `now` 和当前价格作为参数；仍按当前价格计算退款，与现状一致。
- **`update_all_lib`**：没有调用方。先查手动运维清单，并经维护者确认后删除。

备选方案：保持"先调媒体服务器、成功后再写库"。这样一来，外部调用成功、而数据库写入失败时，没有任何补偿（例如用户得到权限却没有付费），而且与"外部副作用在提交后执行"的架构规则相冲突。

### D5 lines

- **repository**：改为模块级函数。7 个没有调用方的方法，经维护者确认后删除。
- **service**：绑定、解绑、认证绑定、调度的增删改和解锁、自动切换，由 service 编排；Redis 的写入在提交后执行。网关缓存的读写集中在 `lines/gateway_cache.py`（core.cache 之上的一层薄封装），键名、值的格式和 JSON 键序都与现在逐字一致。
- **自动切换**：先读出候选用户并关闭读取 session，再逐人处理，每人一个事务。选择调度、跨越午夜、使用 "auto" 字面量、没有调度时不回退，这些行为都不变。
- **接口**：路由函数名保持不变，以兼容 `api/app.py` 按名挂载。
- **模型归位**：`profile/schemas.py` 中 lines 的 18 个模型搬进 `lines/schemas.py`。`test_b2_assembly` 中的导入同步修改。

### D6 custom_lines

- **repository**：新建完整的 repository，SQL 全部移入。状态流转由 service 编排。
- **状态变更单事务**：每次状态变更在一个事务里完成：状态、有效期和流量限额，以及禁用相关的调度（经 lines 的 `*_tx`）。提交后，再解绑用户线路（经 lines.service，每人一个事务）并发送通知。
- **删除**：删除前的当月结算，仍在删除之前完成。
- **三个定时任务**：先在一个事务里完成状态变更并提交，再在事务之外执行解绑和通知，不再在打开的 session 里 await 网络。任务的触发器和 id 都不变。
- **结算**：公式移入 `rules.py`。积分发放改为 `credits.repository.add_tx`，每条线路一个事务，发放顺序和通知与现在一致。
- **模型归位**：`profile/schemas.py` 中的 9 个 CustomLine 模型搬进 `custom_lines/schemas.py`。

### D7 traffic

- **新增 service**：提供 `daily_usage(...)`、`premium_line_statistics(...)`、`traffic_rank(...)`（读模型使用的分析函数）和 `rename_user(...)`（已由 account 变更新增）。
- **rules**：日志解析、`event_hash` 的计算和 token 的判定移入 `rules.py`，都是纯函数。
- **repository**：批量插入与去重、月度聚合与清理、`_get_line_monthly_traffic`，都放在 repository，并各有 `*_tx` 版本。
- **任务**：采集任务的 Redis 队列操作放在 service（通过 `core.redis`）；批大小、确认和推回的逻辑不变。

### D8 基线与合约

- **清除**：本变更名下的 199 条基线条目；三个线路相关领域的 49 条忽略项；premium 和 media_access 的 16 条忽略项；门面组合边和门面冻结的放行项。从门面删除 `LinesRepository`、`TrafficRepository`、`PremiumRepository`、`MediaAccessRepository`。
- **`promote-gift-pack-domain` 带来的变化**：
  - 它的 D3 放行了 `types` 角色。本变更名下以 `credits.types` 为目标的 15 条在那时就会被清除，所以实施时是 184 条。
  - 它的 D3 还让 credits 的 `*_tx` 自己登记提交后的缓存失效。lines 和 media_access 中各 1 处对 `register_cache_invalidation` 的显式调用因此变得多余：确认对应的积分写入都经过 `*_tx` 后直接删除，不搬进 service。
- **暂不能迁移的调用**：摘除 lines 和 traffic 的 mixin 后，profile 和 reports 在入口层的调用会失效；这些调用属于 remaining 变更。为此，与 identity 的做法相同，本变更提供只做转发的兼容层 `LinesCompat` 和 `TrafficCompat`，仍由门面组合，负责变更标为 `retire-legacy-db-facade`；profile 和 reports 在 `promote-remaining-domains` 中迁移。
- **重键**：行号移动的条目，用重键脚本处理。

## Risks / Trade-offs

- **[补偿事务本身失败]** → 记录 error 并通知管理员，由人工处理；用测试覆盖"媒体失败且补偿也失败"的情况。这种情况比现在"外部已生效、库没有更新"更容易发现。
- **[网关缓存格式漂移]** → 缓存写入集中在一个模块；测试用 fakeredis 逐字比对键名和值（包括 JSON 键序），夹具来自当前实现。
- **[按函数名挂载的路由]** → 路由函数名保持不变；启动时的装配测试和路由总数断言兜底。
- **[改动面大]** → tasks 按领域分组，每组独立回归；先做 traffic 和 lines（被依赖方），再做 custom_lines、premium、media_access。
- **[解绑实现合并]** → 先用对照测试证明两份实现的行为完全相同，再删除 premium 中的那一份。

## Migration Plan

1. 冻结五个领域的接口、Redis 写入、调度和通知的快照，补齐行为测试（引入 fakeredis）。
2. 依次提升 traffic、lines（包括目录接口）、custom_lines、premium、media_access。每个领域一组提交，每组都全量回归。
3. 模型归位；提供兼容层；清理基线和合约。
4. 在一次性 PostgreSQL 上做并发和补偿测试；在生产形态副本上彩排绑定、调度切换、会员购买与到期、NSFW 和下载解锁、自建线路的上线和结算，以及流量采集（外部服务用替身）。
5. 部署：没有 schema 变更。回退就是回退镜像。

## Open Questions

无。
