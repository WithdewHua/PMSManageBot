## Why

所有领域都提升完以后，`app.databases.db` 这个门面就只剩 identity 和 invitation 两个兼容层，而且它们已经没有调用方了。再保留门面，只会给人和 agent 留下一条过时的调用路径。

同时，重构期间为过渡而设的配置、工具和文档也该清理了：

- import-linter 里有专为门面设置的合约和放行项。其中门面冻结合约和 SQLAlchemy 合约的放行项，在门面删除后会直接报错。
- 架构测试里有专门检查门面和 mixin 的扫描，还有依赖 B2、B3 冻结提交的来源审计测试。
- `scripts/refactor/` 下有 22 个搬迁、审计、冒烟脚本和 663 KB 的映射表。
- AGENTS.md 和 `docs/architecture.md` 里有过渡期规则，以及已经过时的路径和计数。

启动时的任务引用迁移（`LEGACY_TASK_REFS`）不能直接删除。目前没有证据表明所有实例都运行过 B3 之后的版本：生产环境尚未部署 B3，README 又引导他人使用 GHCR 镜像。如果直接删除迁移，还没迁移过的实例在启动时会被 APScheduler 删掉无法解析的任务记录，夺宝的自动开期又没有补救机制。

## What Changes

- **删除 `app/databases/`**：包括门面、`DatabaseORM`，以及 identity、invitation 的兼容层。
- **改写 import-linter 配置**：
  - 删除门面冻结合约。
  - 删除其他合约中指向 `app.databases`、`app.models` 的放行项和禁止项。
  - 顶层分层合约改为 `(app.domains)`。
  - 六层领域合约改为 `exhaustive = true`。
- **确认基线已清空**：
  - 删除全部 `ignore_imports` 条目。
  - `baseline.json` 只保留行数预算的例外（如果还有的话）。
  - 删除门面和 mixin 专用的扫描，以及 B2、B3 来源审计测试。
  - 积分写入检查从 refactor 工具改为常驻的架构测试。
- **把任务引用迁移移出应用**：
  - 删除 `LEGACY_TASK_REFS`、启动时的迁移、`core/scheduler.py` 中的 pickle 改写和过渡开关，以及 `core/db.py` 中专用的 jobstore 改写助手。
  - 迁移和反向迁移改为独立脚本 `scripts/migrate_legacy_job_refs.py`，不被应用导入。
  - 应用启动时对 jobstore 做只读检查：发现旧格式的任务引用，就拒绝启动，并提示先运行这个脚本。
- **精简 `scripts/refactor/`**：
  - 删除一次性的搬迁、审计、冒烟工具和数据文件（包括映射表和 BASE 文件）。
  - 快照工具和元数据比对工具去掉与门面、BASE 相关的逻辑，移到 `scripts/` 下继续使用。
  - 删除 `main.py` 中只为快照比对保留的兼容垫片。
  - `tests/refactor/` 中测试生产代码的用例移到常规测试目录。
- **处理仍在导入门面的 4 个手动脚本**：逐个请维护者确认，保留的改用领域 API，不再需要的删除。
- **更新文档**：从 AGENTS.md 和 `docs/architecture.md` 中删除过渡期规则和过时内容，改写为终态描述。
- **行为不变**。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。这是纯重构，`.openspec.yaml` 设置 `skip_specs: true`。

## Impact

- **代码**：
  - `app/databases/`、`core/scheduler.py`、`core/db.py`、`schedule.py`、`main.py`。
  - `pyproject.toml`（import-linter 配置）。
  - `tests/architecture/`、`tests/refactor/`、`tests/conftest.py`。
  - `scripts/refactor/`，以及 `scripts/` 下导入门面的 4 个脚本。
  - AGENTS.md、`docs/architecture.md`、`.pre-commit-config.yaml`。
- **运维**：从 B3 之前的版本升级时，先运行一次 `scripts/migrate_legacy_job_refs.py`，否则应用会拒绝启动并给出提示。回退到 B3 之前的镜像时，用同一脚本的反向模式。
- **依赖**：其余 13 个后续变更全部完成，包括 `fix-webapp-auth-bypass`。
