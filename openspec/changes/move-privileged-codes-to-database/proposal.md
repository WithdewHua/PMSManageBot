## Why

特权邀请码存放在 `.env` 的 `PRIVILEGED_CODES` 列表里。兑换分三步：先在数据库里完成邀请，再从内存列表中删掉这个码，最后重写 `.env`。这三步不在同一个事务里，同一个码被并发兑换时，数据库和文件的内容可能对不上。

礼包发放特权码也因此成了架构里唯一的"提交前写 `.env`"例外，需要靠模块锁来保护。

## What Changes

- **特权码改存数据库**：特权码成为 `invitation` 领域的数据。具体是新建一张表，还是在邀请表上加标记，由 design 决定。
- **用普通事务处理全部操作**：发放、校验和兑换都在普通的数据库事务里完成。兑换时加行锁，保证一个码只能兑换一次。
- **首次启动时导入旧数据**：把 `.env` 中现有的 `PRIVILEGED_CODES` 导入数据库，导入是幂等的。
- **礼包改用 `*_tx` 发放特权码**：改为调用 `invitation` 的 `*_tx`，同时删除"提交前写 `.env`"的例外和对应的模块锁。
- **接口保持不变**：`check-privileged`、批量检查等接口的 URL 和响应都不变。
- **顺带清理**：如果此时 `save_config_to_env_file` 已经没有其他调用方，就一并删除。
- **BREAKING（运维）**：导入完成后，`.env` 里的 `PRIVILEGED_CODES` 不再生效。

## Capabilities

### New Capabilities

- `invitation-codes`：邀请码（包括特权码）的发放、校验和兑换，具体包括：
  - 特权码的效力。
  - 一个码只能成功兑换一次，以及并发兑换时的结果。
  - 从旧配置导入。

### Modified Capabilities

无。`gift-pack` 规格中"特权邀请码具有既有效力"的要求不变。

## Impact

- **代码**：
  - `domains/invitation/`
  - `domains/gift_pack/`：奖励发放
  - `core/config.py`：删除 `PRIVILEGED_CODES`
  - `docs/architecture.md`：更新例外清单
- **数据库**：需要 alembic 迁移。
- **依赖**：`unify-business-configuration`、`promote-account-domains`、`promote-gift-pack-domain`。
