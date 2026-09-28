# Tasks

## 1. 数据模型与发放

- [ ] 1.1 在 invitation 模型中新增 `is_privileged SMALLINT NOT NULL DEFAULT 0`，编写 alembic 迁移，并更新 model registry。验证：在一次性 PostgreSQL 上执行 upgrade → downgrade → upgrade；`check_metadata_pg.py` 没有差异；已有的行都得到默认值 0。
- [ ] 1.2 让 `issue_codes_tx(privileged=True)` 直接写入特权标记；删除 `persist_privileged_codes_tx`、礼包对它的调用，以及模块锁；转盘和管理员生成都改用 `invitation.service.generate_codes(..., privileged=True)`；在 `docs/architecture.md` 的例外清单中删除"特权码提交前写 `.env`"。验证：三条发放路径各有测试，确认特权标记与邀请记录一起写入，事务失败时一起回滚；礼包测试中不再出现 `.env` 写入；文档与代码一致。

## 2. 兑换与检查

- [ ] 2.1 按 design D2 把 Plex 和 Emby 的凭码注册改为"预占—开号—确认"：预占时读取特权标记，据此判断注册开关；开号失败时释放邀请码。验证：
  - 注册关闭时，特权码注册成功，普通码被拒绝。
  - 开号失败后，码恢复为未使用，特权标记不变。
  - 在一次性 PostgreSQL 上并发注册同一个码，外部开号的替身只被调用一次。
- [ ] 2.2 把单个和批量检查接口改为按"存在、未使用、有特权标记"判断，契约不变。验证：接口测试覆盖未使用的特权码、已使用的特权码、普通码、不存在的码，以及混合批量；响应格式与冻结夹具一致。
- [ ] 2.3 删除 invitation 中所有写 `.env` 的代码，以及对特权码列表的增删。验证：`src/app/domains/invitation` 中不再出现 `save_config_to_env_file` 和 `PRIVILEGED_CODES`；兑换测试全部通过。

## 3. 一次性导入

- [ ] 3.1 实现启动时的一次性导入：用 `LegacyEnvSource` 读取升级前实际生效的列表，按 design D4 的规则标记或跳过，并在 `core.kv` 中写入完成标记；`.env` 中残留这个键时，启动时发出警告；删除 `Settings.PRIVILEGED_CODES`。验证：
  - 导入覆盖四类码：未使用、已使用、不存在、重复。
  - 重复启动时不再导入。
  - 导入之后修改 `.env`，不产生任何影响。
- [ ] 3.2 新增只读脚本 `scripts/export_privileged_codes.py`，把未使用的特权码导出为 `PRIVILEGED_CODES=` 行，用于回退。验证：测试证明导出的行被旧版 `Settings` 读取后，与数据库中的特权码一致；脚本不写数据库。

## 4. 集成验证

- [ ] 4.1 生产形态本地彩排：在完整数据库副本和 `data/.env` 上启动新版本，核对导入日志中标记和跳过的清单，交给维护者确认；外部接口用替身，用一个特权码完成一次注册。验证：清单确认结论已记录；注册成功，并保留特权标记。
- [ ] 4.2 运行全量回归：`pytest tests/`、`ruff check`、`ruff format --check`、`lint-imports`、`pre-commit run --all-files`，然后运行 `openspec validate move-privileged-codes-to-database --strict`。验证：全部通过；工作区干净。
