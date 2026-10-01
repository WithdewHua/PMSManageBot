# Design

## Context

The B3 relocation leaves credit writes in the transitional `DatabaseORM` facade and its `CreditsRepository` mixin. The current write primitive opens its own session and assigns an absolute balance, while many callers calculate a new value from an unlocked read. Some multi-domain operations already hold a transaction and therefore cannot safely call a second credit session. The three balance locations are `Statistics.credits`, `PlexUser.credits`, and `EmbyUser.emby_credits`; the latter two are also used before a Telegram account is bound.

The design must preserve the existing synchronous SQLAlchemy model, the two-decimal behavior, existing API responses, and the repository-only database boundary established by `restructure-backend-architecture`.

## Goals / Non-Goals

**Goals:**

- Make every credit mutation a locked database-side delta, with an explicit `*_tx(session, ...)` form for callers that already own a transaction.
- Make transfers atomic and deadlock-safe by locking both account rows in a deterministic order before applying the fee and transfer deltas.
- Preserve atomicity for cross-domain settlements such as blackjack, gift packs, media access, donations, invitations, lines, and watch rewards.
- Invalidate credit caches only after the surrounding transaction commits.
- Remove the absolute-balance `update_user_credits` write path and the credits mixin from the transitional facade.
- Provide deterministic PostgreSQL concurrency tests for transfers, competing deductions, and a representative settlement.

**Non-Goals:**

- No schema or Alembic migration; the existing wide-table columns remain owned by identity.
- No change to credit amounts, rounding, API routes, response schemas, notification wording, or business eligibility rules.
- No promotion of unrelated domains or broad replacement of the `DatabaseORM` facade.
- No conversion of synchronous SQLAlchemy operations to async operations.
- No cache redesign; only mutation invalidation semantics change.

## Decisions

### 1. Use typed account references and delta-only repository primitives

The credits repository will expose a small account-reference type covering exactly one of `tg_id`, `plex_id`, or `emby_id`. It will provide module-level transaction helpers:

- `add_tx(session, account, amount)`
- `deduct_tx(session, account, amount)`
- `get_tx(session, account, *, for_update=False)` for callers that need a locked current value
- standalone service/repository wrappers for operations that own their session

`amount` must be finite and strictly positive. The SQL update will express the new value as `column + delta` or `column - delta`; it will not assign a caller-computed absolute balance. `deduct_tx` will use a conditional update (`current >= amount`) and raise `InsufficientCredits` when no row satisfies it. The transaction helper will not catch or convert exceptions so the caller's transaction can roll back.

**Alternative rejected:** retaining `update_user_credits(credits=...)` behind a new wrapper. That would preserve the lost-update race and make it impossible to prove that all callers use deltas.

### 2. Lock rows in a canonical order for transfers

`credits.service.transfer()` will resolve and lock both Telegram `Statistics` rows in ascending `tg_id` order, regardless of transfer direction. It will calculate the existing 5% fee from the requested amount, deduct `amount + fee` from the sender, add `amount` to the recipient, and commit both changes in one session. The service will translate `InsufficientCredits` into the existing response message at the interface boundary.

The sender and recipient must be distinct valid accounts. All transaction-owned helpers will be used inside this session; no nested `get_session()` call is permitted.

**Alternative rejected:** locking sender first and recipient second. Opposite-direction transfers could deadlock when two requests acquire the rows in reverse order.

### 3. Reuse caller-owned sessions for cross-domain settlements

Each existing credit mutation will be classified as either:

- a standalone operation, which calls a credits service wrapper and invalidates cache after its session commits; or
- a transaction-owned operation, which calls `add_tx`/`deduct_tx` with the caller's session and records the affected cache keys for post-commit invalidation.

Settlement code will not open a second session merely to change credits. The migration will preserve the current transaction boundary of blackjack, gift-pack claims, media access, donation, invitation, lines, treasure, prediction, auction, and watch-reward operations.

**Alternative rejected:** making every caller invoke a new standalone credit service. That would split authoritative domain writes from their credit changes and recreate partial-commit behavior.

### 4. Invalidate caches after commit using explicit mutation results

Credit mutation helpers will return a small mutation result containing the affected logical cache keys. Standalone wrappers will invalidate those keys only after the `with get_session()` block exits successfully. Transaction-owned callers will pass the collected keys to a post-commit invalidation helper after their outer repository transaction commits. A rollback path will discard the pending keys and leave the previously committed cache value untouched.

The cache keys will continue to use the existing `plex:<username>` and `emby:<username>` conventions; Telegram-owned balances will invalidate the keys currently derived by the credit readers rather than introducing a second cache namespace.

**Alternative rejected:** deleting cache entries immediately after each SQL statement. A later failure could then expose a cache miss or re-read an uncommitted value even though the transaction rolls back.

### 5. Preserve the existing error contract while introducing a domain exception

`credits.exceptions.InsufficientCredits` will be the internal signal for a failed deduction. Until the shared `DomainError` base is introduced by the planned domain-promotion work, it will preserve the project's existing business-error compatibility and carry the structured amount/account context needed by services. HTTP and Telegram boundaries will continue producing the current Chinese messages and response shapes.

### 6. Prove migration completeness mechanically

Before deleting the old method, a migration check will scan the live `src/app` tree and fail if it finds:

- an assignment to the three owned credit columns outside the credits repository's approved delta implementation;
- a call to `update_user_credits`;
- a caller that computes an absolute balance and writes it through another facade method; or
- a cross-domain transaction that opens a separate credit session.

The check will record each migrated source unit and the selected `*_tx` or service helper, so future credit writes cannot silently reintroduce the old pattern.

## Risks / Trade-offs

- **[Risk]** Some legacy methods combine credit changes with unrelated writes and have implicit transaction boundaries. → **Mitigation:** inventory every write before editing; migrate transaction-owned paths first and add rollback assertions for each high-risk domain.
- **[Risk]** Row-level locks can reduce throughput under hot users. → **Mitigation:** use one conditional SQL update for simple deltas, keep transactions short, and use deterministic transfer ordering.
- **[Risk]** A cache invalidation may be missed by a newly migrated caller. → **Mitigation:** require mutation-result handling in the migration check and add cache assertions to representative standalone and transaction-owned tests.
- **[Risk]** PostgreSQL locking behavior differs from SQLite. → **Mitigation:** run concurrency tests against a disposable PostgreSQL instance; SQLite remains only a functional smoke-test backend.
- **[Risk]** Rolling back code after some new delta operations have run could expose an old absolute writer. → **Mitigation:** do not deploy until the frozen credit inventory reports zero unresolved writers and the completeness check passes; no database schema change is involved, so rollback is a code/image rollback only.

## Migration Plan

1. Freeze new credit-writing changes and capture a source inventory of all direct assignments and `update_user_credits` calls.
2. Add the credits exception, account reference, delta repository helpers, mutation-result/cache invalidation helper, and transfer service with focused unit tests.
3. Migrate standalone callers, then migrate transaction-owned callers using `*_tx` and post-commit invalidation; keep each batch behavior-equivalent.
4. Run the mechanical completeness check, remove `update_user_credits`, remove `CreditsRepository` from `DatabaseORM`, and update imports and tests.
5. Run SQLite functional tests, PostgreSQL metadata verification, PostgreSQL concurrency tests, architecture contracts, and the full regression suite.
6. Deploy during a maintenance window with the existing normal application rollback procedure. Since this change has no schema or jobstore format change, rollback requires stopping the new application and restoring the prior image only.

## Open Questions

None. The remaining choices are implementation details covered by the task breakdown and must not change the behavior contract above.
