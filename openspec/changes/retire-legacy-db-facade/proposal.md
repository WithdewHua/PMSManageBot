## Why

所有领域都提升完以后，`app.databases.db` 这个门面就不再组合任何 mixin 了。再保留它，只会给人和 agent 留下一条过时的调用路径。

## What Changes

- **删除 `app/databases/`**：包括门面和 `DatabaseORM`。同时删除"门面冻结"合约，以及领域分层合约里专为门面设置的忽略项。
- **确认基线已清空**：删除全部 `ignore_imports` 条目。`baseline.json` 只保留行数预算的例外（如果还有的话）。
- **删除任务引用迁移**：删除 `LEGACY_TASK_REFS` 和启动时的任务引用迁移。前提是所有已部署的实例都运行过 B3 之后的版本。
- **精简 `scripts/refactor/`**：删除一次性的搬迁工具，保留仍然有用的快照和校验工具。
- **更新文档**：从 AGENTS.md 和 `docs/architecture.md` 中删除过渡期规则。
- **行为不变**。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。这是纯重构，`.openspec.yaml` 设置 `skip_specs: true`。

## Impact

- **代码**：`app/databases/`、`pyproject.toml`（import-linter 配置）、`tests/architecture/`、`scripts/refactor/` 和相关文档。
- **依赖**：其余 12 个后续变更全部完成。
