## Why

礼包是跨领域写入最多的地方：

- repository 约 2,000 行。一次领取事务会直接写 7 个领域的表：积分、会员、转盘免费次数、锦标赛余额、邀请码、线路调度解锁和下载权限；另外还会在提交前写 `.env`。
- 领取条件要统计多个活动的参与数据。
- 路由从 `ValueError` 的文本里解析 JSON，以此取得条件进度。

所以在 21 点试点之后，第二个提升礼包，用它来检验 `*_tx` 规则。

## What Changes

- **按提升模板处理 `gift_pack`**，模板由 `promote-blackjack-domain` 确立。
- **奖励发放全部改为调用目标领域的 `*_tx`**，并复用领取事务的 session，沿用现有"奖励发放复用调用方 session"的约定。如果目标领域还没有提升，就先在它的 repository 里新增对应的 `*_tx`。
- **条件判断拆成两步**：先由 repository 在锁内通过各领域的查询 `*_tx` 取数，再由 rules 做纯计算。
- **提交后的副作用移到 service**：媒体服务器权限同步、售罄通知和同步失败通知仍在提交后执行。
- **用类型化异常携带条件进度**：`ConditionsNotMet` 等异常直接携带条件进度，不再从异常文本里解析 JSON。
- **暂时保留特权邀请码的例外**："提交前写 `.env`"这个例外先保留，由 `move-privileged-codes-to-database` 移除。
- **对外表现不变**：接口和领取语义都保持原样。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。这是纯重构，现有的 `gift-pack` 规格不变，`.openspec.yaml` 设置 `skip_specs: true`。

## Impact

- **代码**：
  - `domains/gift_pack/`。
  - 为礼包提供 `*_tx` 的领域：credits、premium、luckywheel、blackjack、invitation、lines、media_access。
- **依赖**：
  - `make-credit-changes-atomic`
  - `promote-blackjack-domain`：提供 `DomainError`，以及锦标赛余额和免费次数的 `*_tx`。
