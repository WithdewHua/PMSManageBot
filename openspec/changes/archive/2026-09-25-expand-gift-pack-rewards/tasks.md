## 1. 奖励类型登记与校验

- [x] 1.1 在 `src/app/webapp/schemas/gift_pack.py` 新增 `WheelFreeSpinsReward`（count 1–100、expiry_days 1–365）、`TournamentWalletReward`（amount (0, 100000]）、`InviteCodesReward`（count 1–20、privileged: bool）、`LineScheduleUnlockReward`、`DownloadUnlockReward`，并加入 `RewardItem` 判别联合；验证：越界与非正值的请求被 422 拒绝，重复类型仍被拒绝
- [x] 1.2 在 `db.py` 集中登记奖励类型元数据（是否需绑定 / 文案 / 统计汇总口径，见 design.md D7），`_gift_pack_reward_label` 改为读取登记表；验证：7 种类型均输出 D7 表中的文案
- [x] 1.3 `create_gift_pack` / `update_gift_pack` 的自动补绑定规则由 `has_premium_reward` 推广为「含任一需绑定的奖励」；验证：只含线路调度解锁的礼包创建后 eligibility 带 `require_binding: "any"`，只含积分与免费机会的礼包不带

## 2. 免费机会来源解耦（21 点侧）

- [x] 2.1 周上限计数（`db.py:3230`）增加 `source == 'blackjack'` 过滤；验证：用户本周持有 5 张 `gift_pack` 来源的机会时，打满阈值仍获得 21 点来源的机会
- [x] 2.2 获得通知游标（`claim_unnotified_blackjack_freespins`）只挑 21 点来源的行，但游标按扫描范围内的最大 id 推进；验证：礼包行与 21 点行交错插入时，只返回 21 点行，且游标越过礼包行
- [x] 2.3 `consume_blackjack_freespin` 的返回值增加 `source`，并在 docstring 注明适用于所有来源；验证：消耗顺序仍是最早到期优先、不区分来源
- [x] 2.4 `routers/activities/luckywheel.py` 单次转盘按消耗到的机会来源映射 `wheel_stats.source`（`blackjack` 映射为 `blackjack_free`，`gift_pack` 映射为 `gift_pack_free`）；`LuckyWheelSpinResult` 的 `used_free_spin` 对任何免费来源都为真，并新增 `free_spin_source`；验证：分别消耗两种来源的机会，参与记录的来源正确
- [x] 2.5 `scripts/blackjack_retention_audit.py` 两处计数（:112、:207）加 `source == 'blackjack'`；验证：构造礼包来源的发放与使用后，运行脚本得到的手数进度与让利率与不含这些数据时一致

## 3. 事务内发放分支

- [x] 3.1 实现 `wheel_free_spins` 分支：按 count 写入 `source='gift_pack'` 的行，`expires_at_ms = 领取时刻 + expiry_days`；快照记录次数与到期时间；验证：领取后 `get_blackjack_freespin_summary` 的可用次数增加 count
- [x] 3.2 实现 `tournament_wallet` 分支：复用积分分支的 `Statistics` 行锁累加 `tournament_wallet_credits`，快照记录 `balance_after`；验证：积分不变、余额增加，同一礼包同时含积分与余额也能正常领取
- [x] 3.3 实现 `_grant_feature_unlock_tx`（线路调度 / 下载），直接读永久解锁标记列判断「已拥有」，已拥有的服务记为 skipped、不阻断；下载解锁的服务加入提交后的待同步列表；验证：Premium 且未永久解锁的用户领取后标记列为 1，已解锁的服务快照为 skipped
- [x] 3.4 实现 `_grant_invite_codes_tx`：在调用方 session 内用 `uuid4().hex` 插入 `Invitation` 行，快照记录生成的码；验证：领取 20 枚不撞主键，因其他奖励项失败而回滚时不留下 `Invitation` 行
- [x] 3.5 特权码：在所有数据库写入完成后、事务提交前，持模块级 `threading.Lock` 追加 `settings.PRIVILEGED_CODES` 并写 `.env`，写失败则抛异常使整笔领取回滚；验证：模拟写配置失败时领取回滚且无新 `Invitation` 行，成功时生成的码对邀请注册按特权处理

## 4. 提交后副作用与通知

- [x] 4.1 新增 `apply_download_unlock_to_media(tg_id, service)`（Plex 走 `update_sync_for_user`，Emby 走 `update_download_permission_for_user`），在 `claim_gift_pack` 提交后执行；失败时在响应对应条目的 `message` 写明同步未完成，并用 `_notify_detached` 发「需人工处理」的管理员通知（文案与「发放失败已回滚」不同）；验证：模拟同步抛错时领取仍成功、响应里有说明、管理员通知被触发
- [x] 4.2 `get_gift_pack_stats` 的 `reward_totals` 与过期汇总通知改为按登记表逐类型汇总；验证：含全部 7 种奖励的礼包，统计里每种类型的合计正确

## 5. 前端

- [x] 5.1 `GiftPackAdminPanel.vue`：奖励类型下拉增加 5 种新类型及各自的参数表单（次数 / 有效天数 / 数额 / 数量 + 特权开关 / 无参数），「需绑定」提示改为读取所有需绑定的类型；验证：`npm run lint` 通过，能创建含全部 7 种奖励的礼包
- [x] 5.2 `GiftPackDialog.vue` / `GiftPackPromptDialog.vue`：新类型的奖励标签与领取结果展示（免费机会显示到期时间、余额显示到账后余额、邀请码逐枚展示并可复制、解锁类显示各服务结果与跳过原因）；验证：已领取礼包能在礼包中心再次看到生成的邀请码
- [x] 5.3 `LuckyWheel.vue`：「本次消耗了 21 点免费机会」按 `free_spin_source` 选择文案，角标与说明文字不再暗示只来自 21 点；验证：消耗礼包来源的机会时显示「礼包免费机会」

## 6. 测试与收尾

- [x] 6.1 新增 `tests/test_gift_pack_rewards.py`，覆盖 3.1–3.5 与 4.1 的 spec 场景（发放、跳过、回滚不留邀请码、同步失败不回滚）；验证：`pytest tests/test_gift_pack_rewards.py` 通过
- [x] 6.2 在 `tests/test_blackjack_retention.py` 补充来源解耦的回归用例（周上限、通知游标、消耗来源、最早到期优先）；验证：`pytest tests/` 全部通过
- [x] 6.3 运行 `ruff check src/ && ruff format --check src/` 与前端 `npm run lint`；验证：无新增告警
- [x] 6.4 归档时同步更新 `openspec/specs/gift-pack/spec.md` 的 Purpose 段落（奖励类型不再只有积分与 Premium 天数）；验证：`openspec validate --strict` 通过
