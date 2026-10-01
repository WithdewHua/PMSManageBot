## Why

转盘、夺宝、预言、竞拍四个活动的问题很相似：

- 路由里写着业务流程和通知。
- 按异常字符串分支处理错误：夺宝的路由有 13 行、预言有 11 行按异常文本分支，其中还有被前面分支遮蔽的情况；四个路由里共有 65 个 `except Exception`，会把领域异常改写成 500。
- 调度和启动恢复的逻辑写在路由模块里。

此外，还有几处具体问题：

- **转盘一次抽奖分成至少 6 个独立事务**：扣参与费、发邀请码或会员、增减积分、写抽奖统计都各自提交。免费次数的认领、抽奖和释放也不在同一事务里，靠补偿逻辑兜底。
- **转盘的"下一次生成特权码"开关**：它存在转盘配置的 JSON 里，抽奖时读出、修改、写回，没有加锁。
- **免费次数汇总反读 21 点的数据**：21 点试点把汇总函数搬进了 luckywheel，但它仍直接读 21 点的配置行和 `blackjack_hands_since_freespin` 列。21 点已经依赖 luckywheel，这是数据层面的反向依赖。
- **预言的排行查询不在 rankings 里**：它们在 `prediction/repository/part_2.py`。rankings 通过门面调用它们，但因为扫描器的盲区，这两处调用不在基线里；而且调用被 try 包着，一旦 mixin 被摘除，排行会静默变空。
- **两处绕过积分增量 API 的写法**：夺宝和预言在用户没有统计行时，直接用 `Statistics(credits=…)` 建行并写入积分。
- **夺宝路由里内嵌了一个 ETH JSON-RPC 客户端。**
- **竞拍结束任务的调度方式**：它按函数引用放在内存 jobstore，添加和删除的调用分散在路由和任务里。

21 点试点确立模板后，这四个活动可以批量提升。

## What Changes

- **按提升模板处理四个活动领域**：`luckywheel`、`treasure`、`prediction`、`auction`。
  - 抛出类型化异常的地方，就是原来产生业务拒绝的地方，而不是按消息文本翻译。每个接口的状态码和 detail 逐项冻结后保持不变，包括被遮蔽分支的实际结果。
  - 路由的兜底 `except Exception` 之前，先把领域异常原样抛出。
  - 预言的 repository 按子主题重组（市场、下注、结算、分析），清除序号模块的例外。
  - ETH JSON-RPC 客户端移到 `integrations/`。
- **转盘单次抽奖改为单事务**：
  - 扣参与费、消耗免费次数、发放奖品（积分，邀请码经 invitation 的 `*_tx`，会员天数经 premium 的 `*_tx`）和写抽奖统计，都在同一个事务里完成。
  - 通知在提交后发送。
  - 只改变失败情况下的结果，正常路径不变。
- **转盘成为免费次数账本的唯一入口**：
  - 消耗、释放和汇总的函数改为与来源无关的命名。
  - "来源 → 抽奖统计来源"的映射只保留一份。
  - 汇总中 21 点的进度部分，由 21 点在组装层注册查询函数提供，luckywheel 不再读取 21 点的配置和列。
  - "下一次生成特权码"开关的消费，改为在配置行锁内做条件更新，保证只有一次抽奖能消费成功。
- **一次性调度统一改为具名任务**：夺宝自动开期在 B3 时已经是持久化的具名任务。竞拍结束任务改为具名任务 `auction.finish`，仍然放在内存 jobstore 中，任务 id、触发时间和启动恢复都不变。为此，`schedule_task` 需要支持内存 jobstore。
- **通知由 service 在提交后调用**：夺宝和预言的通知函数原本就在 notifications 里，改为由 service 在提交后调用，不再由路由直接 await。竞拍的通知文案移入 notifications，通知模块不再查数据库。
- **排行查询保留在所属领域**：预言排行依赖预言的派奖规则，作为分析函数保留在 prediction，通过 service 暴露。rankings 改为经过自己的 service 调用它们。转盘和夺宝的排行由 `promote-remaining-domains` 处理。
- **接手 21 点试点的遗留基线条目**：`promote-blackjack-domain` 已经完成，名下还有 18 条没有后续变更负责，本变更一并清除：
  - repository 中对积分缓存失效的显式登记。礼包变更之后，积分的 `*_tx` 会自己登记，这些调用已经多余。四个活动领域中的同类调用也一样删除。
  - 现金局路由直接读取积分余额，改为经过 21 点的 service。
  - repository 中已经没有调用方、直接写勋章表的 `award_or_renew_badge`。
- **行为不变**。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。这是纯重构，`.openspec.yaml` 设置 `skip_specs: true`。

## Impact

- **代码**：
  - 四个活动领域。
  - `blackjack`：repository 中的显式缓存登记和无用函数、现金局路由的余额读取。
  - `core/scheduler.py`：具名任务支持内存 jobstore。
  - `integrations/`：新增 ETH JSON-RPC 客户端。
  - `rankings/service.py` 和 `rankings/router.py`：预言排行的 2 处调用。
  - `app/subscriptions.py`：注册 21 点的免费次数进度查询。
  - `scripts/blackjack_retention_audit.py`：改用 luckywheel 的配置 API。
- **依赖**：
  - `promote-blackjack-domain`：提供模板和 `DomainError`。
  - `make-credit-changes-atomic`。
  - `promote-gift-pack-domain`：提供 premium 和 invitation 的 `*_tx`、基线重键脚本、`types` 角色，以及积分 `*_tx` 的缓存失效自登记。
  - `unify-business-configuration`：转盘配置和随机性参数已是领域配置。
- **不在范围内**：勋章触发的环（design D3 第 1 处）仍由 `promote-reward-domains` 负责。本变更不移动三个路由中调度勋章检查的调用，只随行号变化重写基线键。
