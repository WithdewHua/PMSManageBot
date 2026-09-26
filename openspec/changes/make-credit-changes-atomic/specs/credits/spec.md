# Spec Delta

## Purpose

Defines the consistency guarantees for user credit balances across concurrent transfers, rewards, purchases, and media-account synchronization, so no accepted operation loses another operation's credit change.

## ADDED Requirements

### Requirement: Atomic credit changes
The system SHALL apply each accepted credit gain or cost as an atomic change to the user's current balance. Concurrent changes to the same balance SHALL not overwrite each other. This guarantee SHALL cover Telegram-user credits and credits held by Plex or Emby accounts before binding to a Telegram user.

#### Scenario: Concurrent gains and costs
- **WHEN** a reward and a cost modify the same user's balance concurrently and both operations succeed
- **THEN** the final balance includes both changes exactly once, irrespective of their completion order

#### Scenario: Concurrent unbound-account updates
- **WHEN** credits on an unbound Plex or Emby account are updated while another operation updates the same account
- **THEN** the resulting balance reflects every successful update without a lost write

### Requirement: Insufficient funds prevent deduction
The system SHALL reject a credit cost that exceeds the available balance, and SHALL not reduce the balance below zero or commit any other writes that must succeed or fail with that cost.

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
