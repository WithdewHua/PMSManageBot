## Why

特权邀请码存放在 `.env` 的 `PRIVILEGED_CODES` 列表里，而它唯一的效力是"凭码注册时不受注册开关限制"。这个列表和数据库之间存在几个问题。

- **兑换不在一个事务里**：兑换分三步，先在数据库里标记已用，再从内存列表中删掉这个码，最后重写 `.env`。
  - 删除时如果码已经不在列表里，会报错，但标记和外部开号都已完成。
  - 写 `.env` 失败时不报错。重启后，这个已被使用的码又出现在列表里。
- **列表和数据库对不上**：礼包提交失败、插入失败或手工添加，都可能让列表里出现数据库中不存在的码。检查接口只看列表，所以会对这些码返回"是特权码"。
- **写入没有统一加锁**：礼包发放特权码，是架构里唯一"提交前写 `.env`"的例外，靠模块锁保护；但兑换、转盘和管理员生成这几条路径写同一个列表时，都不持这把锁。
- **历史丢失**：兑换后码就从列表中删除，"哪些已用的码曾是特权码"这一信息随之丢失。
- **所有邀请码都可能被兑换两次**：凭码注册先调用 Plex 或 Emby 开号，再标记已用，而标记用的 UPDATE 不检查 `is_used`。所以同一个码并发兑换时，可能开出两个外部账号。普通码也是如此。

## What Changes

- **特权属性存进数据库**：在邀请表上新增 `is_privileged` 列，附带 alembic 迁移。特权只是已有邀请记录上的一个属性，所以不另建新表。兑换后保留这个标记，以便追溯。
- **发放、校验和兑换都在普通数据库事务中完成**：
  - 管理员生成、转盘奖励、礼包奖励这三条发放特权码的路径，都在各自的事务里写入这个标记。
  - 礼包不再有"提交前写 `.env`"的例外和对应的模块锁，同时更新 `docs/architecture.md` 的例外清单。
- **一个码只能成功兑换一次**：
  - 凭码注册先在事务里预占邀请码，即带 `is_used=0` 条件标记为已用，然后再调用 Plex 或 Emby 开号；开号失败时，释放这个码。
  - 并发兑换时只有一个请求能预占成功，另一个直接得到"已被使用"，不会触发外部开号。
  - 普通码和特权码都遵守这条规则。
- **首次启动时导入旧数据**：
  - 读取升级前实际生效的 `PRIVILEGED_CODES`，把其中存在且未使用的码标记为特权码。
  - 已使用或在数据库中不存在的码，跳过并记录日志。
  - 导入只执行一次，完成标记记录在系统配置里。
- **检查接口保持不变**：`check-privileged` 和 `batch-check-privileged` 的 URL、请求和响应格式都不变。判断依据改为"码存在、未使用，并且是特权码"。正常情况下结果与现在相同，只有列表和数据库不一致的情况会变为 false。
- **删除 `Settings.PRIVILEGED_CODES` 和 invitation 里所有写 `.env` 的代码**。`save_config_to_env_file` 此时仍被线路目录使用，由 `move-line-catalog-to-database` 删除。
- **BREAKING（运维）**：导入完成后，`.env` 里的 `PRIVILEGED_CODES` 不再生效。

## Capabilities

### New Capabilities

- `invitation-codes`：邀请码（包括特权码）的发放、校验和兑换，具体包括：
  - 特权码的效力。
  - 一个码只能成功兑换一次，以及并发兑换和外部开号失败时的结果。
  - 特权状态查询接口的判断规则。
  - 从旧配置导入。

### Modified Capabilities

无。`gift-pack` 规格中"特权邀请码具有既有效力"的要求不变。

## Impact

- **代码**：
  - `domains/invitation/`：模型、repository、service、检查接口。
  - `domains/gift_pack/`：删除特权码持久化的调用。
  - `domains/luckywheel/`：`gen_privileged_code` 发码路径。
  - `core/config.py`：删除 `PRIVILEGED_CODES`。
  - `docs/architecture.md`：更新例外清单。
- **数据库**：需要 alembic 迁移，给 `invitation` 表新增 `is_privileged` 列，默认值为 0。
- **依赖**：
  - `unify-business-configuration`：复用它读取旧配置来源的逻辑。
  - `promote-account-domains`：invitation 已经提升为目标形态。
  - `promote-gift-pack-domain`：礼包已经通过 invitation 的 `*_tx` 发码，特权码的持久化集中在 invitation。
