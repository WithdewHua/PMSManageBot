## Why

礼包是跨领域写入最多的地方：

- repository 约 2,200 行。一次领取事务要写 7 个领域的数据：
  - 积分和转盘免费次数已经改为调用目标领域的 `*_tx`。
  - 会员天数通过 premium 的 service 函数写入，但要把门面实例传进去；而且读到期时间和写入不在同一个 session 里。
  - 锦标赛余额、邀请码、线路调度解锁和下载权限，仍然直接写其他领域的表或列。
  - 另外还会在提交前写 `.env`。
- 领取条件和受众条件要统计 7 个领域的参与数据，repository 直接导入这些领域的模型。
- 路由从 `ValueError` 的文本里解析 JSON，以此取得条件进度；删除接口靠错误文案里是否含"不存在"来区分 404 和 400。

所以在 21 点试点之后，第二个提升礼包，用它来检验 `*_tx` 规则。

另外，礼包和 21 点的 repository 包是 B 阶段由 `split_repository.py` 按行数机械切出来的 `part_N.py`：方法按原顺序装箱，约 740 行切一刀，文件名不带任何信息，同一个文件里混着互不相关的职责（例如 21 点的 `part_6.py` 里有锦标赛手牌操作和勋章续期，`part_7.py` 里有锦标赛结算和配置读写）。这违背了"代码位置由领域和角色唯一确定"的目标。21 点试点按原计划保留了这些文件，所以由本变更一并按子主题重组。

## What Changes

- **按提升模板处理 `gift_pack`**，模板由 `promote-blackjack-domain` 确立。
- **奖励发放全部改为调用目标领域的 `*_tx`**，并复用领取事务的 session，沿用现有"奖励发放复用调用方 session"的约定。如果目标领域还没有提升，就先在它的 repository 里新增对应的 `*_tx`。
- **条件判断拆成两步**：先由 repository 在锁内通过各领域的查询 `*_tx` 取数，再由 rules 做纯计算。
- **提交后的副作用移到 service**：媒体服务器权限同步、售罄通知和同步失败通知仍在提交后执行。
- **用类型化异常携带条件进度**：`ConditionsNotMet` 等异常直接携带条件进度，不再从异常文本里解析 JSON。
- **暂时保留特权邀请码的例外**："提交前写 `.env`"这个例外先保留，由 `move-privileged-codes-to-database` 移除。
- **按子主题重组 repository 包**：
  - 礼包和 21 点的 `repository/part_N.py` 按子主题重新组织和命名，例如礼包的条件、奖励、管理、领取、提醒，21 点的手牌、结算、奖池、留存、锦标赛。
  - 先以只做函数搬移和导入更新的提交完成，函数体逐字不变，用现有的 AST 校验工具证明；然后再做语义改造。这样 git 能追踪每个函数的来历。
  - 21 点的重组在 `promote-blackjack-domain` 完成后进行，不改变它的对外导出和行为。
  - 新增架构检查，禁止领域内出现 `part_N` 这类序号模块。`prediction` 的两个 part 文件登记为过渡例外，由 `promote-activity-domains` 清除。
  - 更新 `docs/architecture.md` 里的提升模板：角色文件改成包时按子主题拆分，不按行数切分。
- **对外表现不变**：接口和领取语义都保持原样。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。这是纯重构，现有的 `gift-pack` 规格不变，`.openspec.yaml` 设置 `skip_specs: true`。

## Impact

- **代码**：
  - `domains/gift_pack/`。
  - 为奖励发放提供写入 `*_tx` 的领域：credits、premium、luckywheel、blackjack、invitation、lines、media_access。
  - 为条件取数提供查询 `*_tx` 的领域：luckywheel、blackjack、treasure、prediction、auction、invitation、badges。
  - premium 的媒体权限同步函数改为不需要传入门面实例。
  - `domains/blackjack/repository/`：除新增锦标赛余额入账的 `*_tx` 外，只做按子主题的重组，不改行为。
  - `tests/architecture/`（禁止序号模块的检查）、`docs/architecture.md`（提升模板）。
- **依赖**：
  - `make-credit-changes-atomic`
  - `promote-blackjack-domain`：提供 `DomainError` 与提升模板；转盘免费次数的 `grant_free_spins_tx` 已由它加入 luckywheel。锦标赛余额的入账 `*_tx` 不在它的任务里，由本变更加入 blackjack repository。
