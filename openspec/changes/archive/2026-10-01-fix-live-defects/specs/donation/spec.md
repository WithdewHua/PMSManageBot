# Spec Delta

## Purpose

约定捐赠登记和登记相关的通知：已经提交的登记不会因为通知失败而消失，通知中的积分与实际入账一致。

## ADDED Requirements

### Requirement: 捐赠登记

用户提交捐赠登记后，登记一经保存，接口 SHALL 返回成功。管理员通知 SHALL 在保存之后尽力发送，通知失败 SHALL 只记录日志，SHALL NOT 删除登记或让接口报告失败。保存失败时，接口 SHALL 返回失败，SHALL NOT 留下登记。

#### Scenario: 通知管理员失败

- **WHEN** 登记已保存，发送管理员通知时出错
- **THEN** 接口返回成功，登记保留，管理员可以在后台看到并处理它

### Requirement: 登记捐赠的 bot 通知

管理员通过 bot 登记捐赠后，通知中的积分 SHALL 等于这次实际入账的积分。

#### Scenario: 倍率为 5

- **WHEN** 捐赠倍率为 5，管理员登记 10 元捐赠
- **THEN** 用户入账 50 积分，通知中显示 50
