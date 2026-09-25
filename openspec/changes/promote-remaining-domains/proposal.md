## Why

剩下的领域包括捐赠、加密货币捐赠、Vaultwarden，以及三个读模型。它们体量小、依赖少，放在最后统一提升，为移除门面做准备。

## What Changes

- **按提升模板处理三个业务领域**：`donation`、`crypto_donation`、`vaultwarden`。
- **整理三个读模型**：`rankings`、`reports`、`profile`。
  - 每个读模型的查询都收拢到自己的 repository 里，只读不写。
  - 用到其他领域业务规则的地方，改为调用该领域的 service。
  - bot 排行命令和排行接口共用同一套查询。
- **对外行为不变**。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。这是纯重构，现有的 `rankings` 规格不变，`.openspec.yaml` 设置 `skip_specs: true`。

## Impact

- **代码**：上述六个领域。
- **依赖**：`promote-reward-domains`（捐赠触发的勋章颁发已改为事件），以及此前的各个 promote 变更。
