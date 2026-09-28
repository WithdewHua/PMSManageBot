# Tasks

## 1. 覆盖登记与测试基座

- [ ] 1.1 按 design D3 给各领域 models 中存 TG ID 的列加上 `info={"tg_id": "user"|"admin"}`，给名称可疑但并非 TG ID 的列加上 `info={"tg_id": False}`；在 `tg_rebind/constants.py` 中登记两处编码位置（`credits_by_<ID>` 和礼包受众名单）。验证：`check_metadata_pg.py` 显示 schema 没有变化；33 个数值列都有标记。
- [ ] 1.2 在 `tests/architecture` 中新增换绑覆盖检查：被标记的列必须出现在所属领域的 `REASSIGNED_TG_ID_COLUMNS` 中，且该领域在参与者列表里；名称可疑的列必须有标记。验证：在临时模型中新增一个未标记的 `foo_tg_id` 列时检查失败；新增一个已标记、但没有登记迁移的列时检查失败。
- [ ] 1.3 编写由登记表驱动的测试夹具：给同一个用户在每个被标记的列、每个编码位置上各造一条数据；并提供三种数据库后端：SQLite 关外键、SQLite 开外键、一次性 PostgreSQL（通过环境变量启用）。验证：夹具在三种后端上都能建出完整的数据；新增标记列时，夹具自动覆盖它。

## 2. 各领域的检查与迁移函数

- [ ] 2.1 identity：
  - 定位旧身份：按旧 ID、小写的 Plex 邮箱、小写的 Emby 用户名。
  - 按 `tg_id` 升序锁定两边的 `statistics` 行；确保新行存在。
  - 迁移 Plex、Emby、Overseerr 账号行，最后删除旧行。
  - 检查"新 ID 已绑定同类媒体账号"和"两边都有 Overseerr"。
  - 在 `identity/types.py` 中定义 `TgIdReassignIssue`。

  验证：单元测试覆盖定位时忽略大小写、两类冲突，以及删除旧行时不违反外键。
- [ ] 2.2 credits、donation、blackjack：
  - 积分用 `move_tx` 整额转移；捐赠额相加；钱包余额和两个计数器相加。
  - 迁移手牌、锦标赛报名、周返水和锦标赛创建人。
  - blackjack 检查未结束的手牌、报名中或进行中的赛事、同一周的返水、同一场赛事的报名。

  验证：数值相加的测试通过；每类冲突和在途状态都会被拒绝；积分缓存只在提交后失效。
- [ ] 2.3 badges、gift_pack、luckywheel：迁移勋章并检查同一枚勋章；迁移礼包领取状态、`created_by` 和受众名单中的 ID（替换后去重）并检查同一礼包；迁移免费次数账本和转盘统计。验证：受众名单同时包含新旧两个 ID 时，改写后只剩一个新 ID；每项冲突都有测试。
- [ ] 2.4 treasure、prediction、auction、invitation、lines、custom_lines、crypto_donation、vaultwarden：迁移各自的用户列和审计列；invitation 把 `used_by` 中的 `credits_by_<旧ID>` 改写为新 ID。验证：每个领域的迁移函数返回的计数与夹具中的数据条数一致；夹具中不再残留旧 ID。

## 3. 编排、服务与命令

- [ ] 3.1 实现 `tg_rebind` 的 repository 编排：按 design D2 的步骤执行，汇总全部问题后抛出 `TgRebindRejected`；支持演练模式（执行完毕后回滚）；未绑定的媒体账号走 D5 的绑定路径。实现 service 的提交后缓存刷新和管理员提示标志，以及类型化异常。验证：在三种数据库后端上分别跑以下场景，结果一致：
  - 换到全新 ID、合并到已有 ID。
  - 每一类冲突、21 点在途。
  - 未绑定账号。
  - 旧 ID 等于新 ID。
  - 中途注入失败，数据全部回滚。
  - 演练模式下数据库和缓存都不变。
- [ ] 3.2 在 `app/manage.py` 中新增 `rebind-tg-id` 子命令：参数互斥，按 design D7 输出结果和退出码；旧 ID 是管理员时给出提示。把 `app.manage` 加入 import-linter 的顶层分层合约。验证：CLI 测试覆盖参数解析、成功、被拒绝（列出全部问题，退出码 2）、找不到账号（退出码 3）、演练和管理员提示；`lint-imports` 通过。
- [ ] 3.3 删除 `TgRebindRepository` 和 `db.rebind_user_tg_id`；清理 20 条基线条目和 2 条门面组合忽略项，并下调封存计数；在 `docs/architecture.md` 的手动运维清单中写入 `rebind-tg-id`、`legacy-credit-sync`、`report` 三个命令，以及各类冲突的手动处理指引，并注明 `smoke_b1.py` 已失效。验证：门面上查不到换绑方法；`pytest tests/architecture` 通过；文档中的命令示例能按原样执行。

## 4. 历史数据与集成验证

- [ ] 4.1 编写只读脚本 `scripts/check_dangling_tg_ids.py`，按登记表列出指向不存在 `statistics` 行的 TG ID，包括数值列、`credits_by_<ID>` 和礼包受众名单。验证：测试证明脚本能找出人为构造的悬空 ID，而且不写数据库。
- [ ] 4.2 在生产形态的本地副本上运行悬空 ID 检查；对抽样的用户对先演练、再真实执行换绑，并核对计数和网关用户缓存。验证：检查结果已交给维护者，并记录了处理决定；演练与真实执行的计数一致；缓存中的 `tg_id` 是新 ID。
- [ ] 4.3 运行全量回归：`pytest tests/`、`ruff check`、`ruff format --check`、`lint-imports`、`pre-commit run --all-files`，然后运行 `openspec validate promote-tg-rebind-domain --strict`。验证：全部通过；工作区干净。
