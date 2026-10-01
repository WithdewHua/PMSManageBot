# credits Specification

## Purpose
Defines the consistency guarantees for user credit balances across concurrent transfers, rewards, purchases, and media-account synchronization, so no accepted operation loses another operation's credit change.

## Requirements

### Requirement: Atomic credit changes
The system SHALL apply each accepted credit gain or cost as an atomic change to the user's current balance. Concurrent changes to the same balance SHALL not overwrite each other. This guarantee SHALL cover Telegram-user credits and credits held by Plex or Emby accounts before binding to a Telegram user.

#### Scenario: Concurrent gains and costs
- **WHEN** a reward and a cost modify the same user's balance concurrently and both operations succeed
- **THEN** the final balance includes both changes exactly once, irrespective of their completion order

#### Scenario: Concurrent unbound-account updates
- **WHEN** credits on an unbound Plex or Emby account are updated while another operation updates the same account
- **THEN** the resulting balance reflects every successful update without a lost write

### Requirement: Insufficient funds prevent deduction
The system SHALL reject a credit cost that exceeds the available balance, and SHALL not reduce the balance below zero or commit any other writes that must succeed or fail with that cost. The only exception is the premium traffic charge applied during daily watch-reward settlement, which by design MAY reduce the balance below zero.

#### Scenario: Competing deductions
- **WHEN** two concurrent costs each observe a balance sufficient for only one of them
- **THEN** at most one cost succeeds, the other reports insufficient credits through its existing user-facing error contract, and no partial changes from the rejected cost remain

### Requirement: Transfers conserve credits
The system SHALL move credits between two users as one indivisible operation: the sender's decrease and recipient's increase SHALL either both commit or both roll back. Concurrent transfers between the same users in either direction SHALL complete without deadlock or lost updates.

#### Scenario: Simultaneous opposite-direction transfers
- **WHEN** users A and B initiate transfers to one another at the same time
- **THEN** successful transfers preserve the sum of both balances and neither balance becomes negative

#### Scenario: Insufficient sender balance
- **WHEN** the sender has insufficient credits at the point their balance is changed
- **THEN** neither account balance changes and the existing transfer error is returned

### Requirement: Cross-feature credit operations are indivisible
A feature that changes credits and related records as one user action SHALL commit or roll back all those changes together. The system SHALL not open a separate credit transaction for an operation that must be atomic with its associated records.

#### Scenario: Reward settlement fails after a credit change
- **WHEN** a game, gift, or purchase transaction changes credits but fails before completing the corresponding settlement records
- **THEN** neither the balance change nor the settlement records are committed

### Requirement: Committed credit balances and cached values agree
The system SHALL invalidate affected cached credit balances only after a successful commit, not on a transaction that rolls back. Existing two-decimal rounding rules and user-facing response shapes and messages SHALL remain unchanged except for the prevention of concurrent lost updates or overdrafts.

#### Scenario: Successful credit update
- **WHEN** a credit change commits
- **THEN** the next read cannot use a stale cached pre-change balance

#### Scenario: Rolled-back credit update
- **WHEN** a credit change rolls back
- **THEN** its uncommitted balance is not exposed through the credit cache

#### Scenario: Sequential operation compatibility
- **WHEN** a previously supported reward, charge, or transfer runs without concurrency
- **THEN** the balance rounding, response format, and applicable user-facing messages match the previous behavior

### Requirement: 零额积分变动是无操作

积分的增加和扣除 SHALL 把数额为 0 的请求视为无操作：余额不变，不写库，返回变化量为 0 的结果，调用方的流程照常继续。数额为负 SHALL 仍然被拒绝。

#### Scenario: NSFW 锁定时退款为 0

- **WHEN** 用户锁定 NSFW 媒体库，按规则算出的退款为 0
- **THEN** 解锁标志被清除，余额不变，接口返回原来的成功响应

#### Scenario: 价格设为 0

- **WHEN** 管理员把某项功能的价格设为 0，用户随后使用这项功能
- **THEN** 功能照常生效，余额不变，不出现"积分更新失败"之类的错误

#### Scenario: 负数

- **WHEN** 某个调用以负数增加或扣除积分
- **THEN** 请求被拒绝，余额不变

### Requirement: 会员流量费是唯一的透支例外

观看结算中的会员流量费 SHALL 可以把余额扣成负数。除此之外的所有扣费和转账 SHALL 仍然拒绝超过余额的请求，并保持余额不低于零；余额已经为负的用户，发起其他扣费或转账时 SHALL 被拒绝。

#### Scenario: 会员流量费超过余额

- **WHEN** 用户余额为 5，会员流量费为 20
- **THEN** 余额变为 -15

#### Scenario: 欠款随账户迁移

- **WHEN** 一个未绑定的 Plex 账户余额为 -15，用户把它绑定到余额为 40 的 TG 账户
- **THEN** TG 账户余额变为 25，Plex 账户余额变为 0

#### Scenario: 负余额用户购买功能

- **WHEN** 余额为 -15 的用户解锁一项需要 10 积分的功能
- **THEN** 请求因积分不足被拒绝，余额不变
