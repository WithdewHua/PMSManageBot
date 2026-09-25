## Why

21 点（含锦标赛）是最大的领域：repository 约 4,300 行，路由约 1,860 行，至少 5 个定时任务，还有自己的引擎、通知和配置。它也是测试最全的领域，所以适合第一个按目标架构提升，并把做法沉淀成模板。它身上集中了几类典型问题：

- 路由里有 20 处按异常字符串分支的错误处理。
- `_settle_blackjack_hand`（239 行）这类函数把纯计算、加锁、写库和发通知混在一起。
- 21 点直接往转盘的免费次数表里写数据；转盘消耗这些次数时，又反过来读 21 点的配置。这是 design D3 记录的第 3 处环。

## What Changes

- **确立提升模板**，写进 `docs/architecture.md`，后续的 promote 变更都照此执行：
  1. 先补"记录现有行为"的测试。本领域已有较全的测试，只补缺口。
  2. 把 repository mixin 改为模块级函数，从门面上摘掉。其他领域原来经由门面调用本领域方法的地方，改为调用本领域的 service 或 `*_tx`。
  3. 新增 service。路由、任务和 bot 只调用 service；通知、调度等副作用在提交后由 service 执行。
  4. 把纯计算抽到 rules，包括结算、赔付、奖池、返水和留存的计算。
  5. 业务上的拒绝改为抛出类型化异常。
  6. 跨层导入改为按模块导入。
  7. 清空本领域名下的基线条目。
- **新增 `core/errors.py`**：提供 `DomainError` 基类，携带错误码、HTTP 状态和结构化数据；api 层统一把它转换成 HTTP 响应。本变更是第一个用到它的地方。
- **消除 D3 第 3 处环**：21 点发放转盘免费次数时，改为调用 `luckywheel` 提供的 `grant_free_spins_tx`，并在发放时把消耗阶段需要的参数存到账本行上。为此 `luckywheel_free_spins` 需要加列，附带 alembic 迁移。
- **对外表现不变**：接口的路径、参数、响应、状态码和错误文案都保持原样。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。这是纯重构，现有的 `blackjack`、`blackjack-tournament` 规格不变，`.openspec.yaml` 设置 `skip_specs: true`。

## Impact

- **代码**：
  - `domains/blackjack/`。
  - `domains/luckywheel/`：新增免费次数的发放接口。
  - `core/errors.py` 和 `api/app.py`：统一的异常映射。
  - 所有调用 21 点方法的领域：礼包、转盘、勋章颁发、排行榜。
- **数据库**：`luckywheel_free_spins` 新增参数快照列，由 alembic 迁移添加，并回填旧行。
- **依赖**：`restructure-backend-architecture`、`make-credit-changes-atomic`。
