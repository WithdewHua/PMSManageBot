## Why

后端约 55% 的代码集中在 5 个文件里：

- `databases/db.py` 只有一个类 `DatabaseORM`，却有 314 个方法、14,014 行，覆盖约 29 个业务领域。8 月 16 日它还是 7,337 行，40 天内翻了一倍。
- `databases/db_func.py`（3,014 行）既放定时任务，又放被 8 个路由当工具库调用的业务函数。
- `webapp/routers/user.py`（2,874 行）、`webapp/routers/admin.py`（1,906 行）、`models/models.py`（1,542 行，31 个模型）。

依赖方向也有多处反了，现在全靠函数内的 import 绕开循环依赖：

- `db.py` 反过来调用 `app.premium`。
- `modules/custom_line.py` 从 `routers/admin.py` 导入业务函数。
- `db_func.py` 和 prediction 路由互相导入。

定时任务散在 7 处以上。

结果是改一个功能，人和 agent 都要在上万行代码里跨文件搜索，也很难判断新代码该放哪、改动会波及哪里。现有约定（AGENTS.md 的"业务逻辑放 db.py 或 modules"）本身就是巨文件的成因。现在工作区干净、没有进行中的 change，适合一次性确立目标架构并完成搬迁；拖得越久，db.py 越大，搬迁成本越高。

## What Changes

- **确立目标架构**：
  - 业务代码按领域组织在 `app/domains/<name>/` 下，每个领域内按固定角色分文件（`router`、`admin_router`、`schemas`、`models`、`repository`、`service`、`rules`、`exceptions`、`constants`、`config`、`jobs`、`notifications`、`bot`）。
  - 领域之外的顶层结构：`core/` 放公共设施，`integrations/` 放外部 API 客户端，`api/` 负责组装 FastAPI，`bot/` 负责组装 Bot，另有声明式任务表 `schedule.py` 和模型注册表 `model_registry.py`。
- **写下架构规则**：
  - 新增 `docs/architecture.md`，内容包括分层、领域目录与表/列组归属、领域依赖图、例外清单和配置分类。
  - 重写 AGENTS.md 的架构约定部分，并加一张"新代码放哪"清单。
- **以机械搬迁为默认，行为零变更**：
  - B3 搬迁若引入 B2 冻结提交中不存在的领域依赖环，只对构成新环的调用面做逐项审阅的局部去环；不得借此重构其他遗留业务逻辑、开放新的环豁免或改变 HTTP/Bot/调度行为。对调整过的查询必须比较结果、会话及事务边界、异常传播和副作用顺序；未证明等价不得封存为旧债。
  - `db.py` 的方法拆到各领域的 `repository`。过渡期这些 repository 是 mixin，仍由 `app.databases.db` 门面组合，所以 687 处 `db.xxx()` 调用不用改。
  - `models.py` 拆到各领域的 `models.py`，alembic 和 `init_db` 通过 `model_registry` 拿到完整元数据。
  - 路由、schemas、Bot 命令、定时任务、通知，以及写在路由里的编排函数，都迁到所属领域。
  - 将 `db_func.py` 的同步积分／用户信息手动入口和 `utils/report.py` 的报表 CLI 迁为 `app.manage` 的显式子命令。旧模块按 B3 计划删除，因此手动命令的调用路径会变化；执行顺序、参数默认值、返回／输出与副作用须逐项对比，不得擅自删除这些运维功能。
  - `modules/` 下的外部客户端迁到 `integrations/`。`config`、`log`、`scheduler`、`session`、`redis`、`cache` 和通用工具迁到 `core/`。
- **用机器校验架构**：
  - 引入 import-linter，校验这几类约束：顶层分层、领域分层且无环、领域内分层、数据访问范围（入口不碰数据层，SQLAlchemy 和 models 只在 repository 里用）、`rules` 保持纯函数、外部客户端隔离、旧门面不再有新的使用者。
  - 现存违规写进 ignore 清单，每条标注由哪个后续变更负责清理。B2 接口搬迁及 B3 编排搬迁会分别使原本不在 `domains/` 扫描范围内的旧违规首次进入该范围；两批只允许对能追溯到各自冻结基准提交、源码单元、未变调用 AST 和实际导入绑定的机械迁入旧债逐条审阅并精确重设过渡基线。B3 为消除新增领域环而调整过的调用不能冒充未变的机械迁入。每批封存后清单只减不增；任何新业务调用均不得借重设基线混入。
  - 新增架构测试，覆盖四项：跨领域调用面（包括经由门面的调用）、单文件行数预算、模型注册完整、过渡期各 mixin 之间不重名。
- **删除死代码**：删除全仓库零调用的 `DatabaseORM._CurWrapper` / `cur` 兼容层。
- **保留手动运维入口**：`rebind_user_tg_id`（TG 换绑）在代码里没有调用方，但管理员会手动执行它。
  - 它照常搬迁，放进新的 `tg_rebind` 领域。B 阶段之后仍然可以用 `db.rebind_user_tg_id(...)` 调用。
  - 它目前会漏迁近期新增的几张表。本变更原样搬迁，不做修复，修复由后续的 `promote-tg-rebind-domain` 负责。
  - `docs/architecture.md` 新增"手动运维操作"清单，登记这类入口，避免再被当成死代码。
- **迁移持久化任务**：21 点手牌超时和夺宝自动重开这两类任务存在 APScheduler 的 SQLAlchemy jobstore 里，以函数路径引用。如果不迁移，APScheduler 加载时会删掉无法解析的任务。
  - 这两类任务改为按稳定的任务名调度，以后再搬动代码也不用迁移。
  - 启动时一次性改写 jobstore 里的旧引用。

以下内容不在本变更范围内，由后续变更负责：

- 把 mixin 改成模块级函数、抽出 service、引入类型化异常。
- 积分原子化、配置统一。
- 删除其他无引用的方法。删除前要逐个和维护者确认，排除手动运维入口。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。这是纯重构，不改变任何对外行为，因此 `.openspec.yaml` 设置 `skip_specs: true`。

## Impact

### 修改

- `src/app` 下几乎所有 Python 文件都会被移动或拆分。`tests/`、`scripts/`、`alembic/env.py` 里的导入路径和 monkeypatch 目标同步更新。
- `main.py` 仍是入口，`python -m app.main` 不变。任务注册改为读取 `schedule.py`，uvicorn 的目标从 `"app.webapp:app"` 改为 `"app.api.app:app"`。
- 新增三处：
  - `docs/architecture.md`
  - `tests/architecture/`
  - `scripts/refactor/`：搬迁和校验工具，保留到 `retire-legacy-db-facade` 为止，后续的领域提升仍要用它做接口和元数据对比。
- `pyproject.toml` 的 test extra 新增 `import-linter`，`.pre-commit-config.yaml` 新增 `lint-imports` 本地 hook。

### 不受影响

- HTTP 接口的路径、参数、响应和状态码，以及 Bot 命令。
- 数据库结构：没有 alembic 迁移。
- 配置项与 `.env`、前端、Docker 入口。

### 风险

- **与并行开发冲突**：搬迁几乎触及所有后端文件，和并行开发的功能分支冲突会很大。搬迁期间冻结后端功能开发；搬迁由脚本按映射表执行，必要时可以在最新主干上重跑。
- **运行时才暴露的断裂**：函数内的延迟导入、字符串形式的模块路径、持久化任务的函数引用，以及两个手动 CLI 的旧调用路径，这些只在运行时才会出错。由导入校验、任务引用迁移和一次性 CLI 行为对比覆盖，见 design.md。
- **回滚**：若 B3 部署后已有具名持久化任务，须在维护窗口先停止所有使用该 jobstore 的 B3 调度器进程，用 B3 代码和配置运行带 `--scheduler-stopped` 确认的反向脚本，再回退镜像并启动旧进程。不能在 B3 调度器运行时反向改写：B3 已删除旧函数路径，APScheduler 加载回退后的记录会将无法解析的任务从 jobstore 删除。

### 后续变更

以下变更都依赖本变更，建议按这个顺序进行：

1. `make-credit-changes-atomic`
2. `promote-blackjack-domain`（试点）
3. `promote-gift-pack-domain`
4. `unify-business-configuration`
5. `promote-activity-domains`
6. `promote-account-domains`
7. `move-privileged-codes-to-database`
8. `promote-line-domains`
9. `move-line-catalog-to-database`
10. `promote-reward-domains`
11. `promote-remaining-domains`
12. `promote-tg-rebind-domain`
13. `retire-legacy-db-facade`
