# Tasks

## 1. Inventory and Guardrails

- [x] 1.1 Build a frozen inventory of every write to `Statistics.credits`, `PlexUser.credits`, `EmbyUser.emby_credits`, and every `update_user_credits` caller; verify the inventory identifies each source function, transaction owner, cache key, and expected delta with a dedicated test.
- [x] 1.2 Add the credits migration completeness checker and reviewed mapping file; verify it fails on absolute assignments, `update_user_credits` calls, missing transaction-owner decisions, or untracked new credit writers.
- [x] 1.3 Document the three-column ownership, canonical lock order, cache post-commit rule, and migration rollback boundary in `docs/architecture.md`; verify OpenSpec and the architecture documentation checks pass.

## 2. Credits Primitives

- [x] 2.1 Add `credits.exceptions.InsufficientCredits` and a typed account reference/result model; verify invalid account references, non-positive amounts, NaN/infinite values, and structured insufficient-funds context with unit tests.
- [x] 2.2 Implement repository `get_tx`, `add_tx`, and `deduct_tx` helpers for Telegram, Plex, and Emby balances using row locks, SQL-side deltas, and conditional deductions; verify sequential behavior and rollback on a disposable PostgreSQL database.
- [x] 2.3 Implement standalone wrappers and post-commit cache invalidation using mutation results; verify successful updates invalidate affected keys while rolled-back updates do not alter the cache.
- [x] 2.4 Implement `credits.service.transfer` with deterministic row-lock ordering, the existing 5% fee, one transaction, and preserved response/error behavior; verify successful, insufficient, self-transfer, and opposite-direction transfer cases.

## 3. Standalone Caller Migration

- [ ] 3.1 Migrate the credits router and all standalone service/job callers from absolute writes to the credits service or delta repository API; verify the source inventory has no unresolved standalone writer and the existing route tests pass.
- [ ] 3.2 Migrate standalone reward, donation, invitation, line, media-access, traffic, and watch-reward credit changes; verify each caller preserves its previous rounding, logging, and user-facing result with focused domain tests.
- [ ] 3.3 Migrate unbound Plex and Emby credit updates and cache refresh paths without routing them through Telegram statistics; verify concurrent unbound-account updates retain every successful delta.

## 4. Transaction-Owned Caller Migration

- [ ] 4.1 Migrate blackjack cash, tournament, cashback, and settlement credit changes to caller-owned `*_tx` helpers; verify settlement records and balances roll back together on injected failure.
- [ ] 4.2 Migrate gift-pack claims, rewards, privileged-code handling, and media permission unlocks to caller-owned credit helpers; verify row locks, reward records, and post-commit side effects preserve existing behavior.
- [ ] 4.3 Migrate treasure, prediction, auction, custom-line, premium, and remaining domain transactions; verify each affected domain has a rollback test and no nested credit session.
- [ ] 4.4 Migrate cross-domain TG rebind and account merge credit handling; verify rebinding remains atomic and all three balance locations retain the existing merge semantics.

## 5. Remove the Absolute-Write Path

- [ ] 5.1 Remove `CreditsRepository.update_user_credits`, replace all imports and facade calls, and remove the credits mixin from `DatabaseORM`; verify importing the facade exposes no absolute credit writer and all credit callers resolve to approved helpers.
- [ ] 5.2 Update tests, refactoring mappings, and architecture exemptions for the promoted credits domain; verify the migration completeness checker, import-linter, and architecture baseline ratchet all pass without a new violation.
- [ ] 5.3 Review and document any manual credit-management entry point before deletion; verify the manual-operations inventory contains an explicit maintainer-approved decision for each zero-code-caller public method.

## 6. Concurrency and Integration Verification

- [ ] 6.1 Add disposable-PostgreSQL concurrency tests for competing deductions, concurrent gains and costs, opposite-direction transfers, unbound-account updates, and a representative blackjack or gift settlement; verify no lost updates, no negative balances, and conserved transfer totals.
- [ ] 6.2 Run API and domain behavior smoke tests against a production-shaped disposable PostgreSQL copy; verify response shapes, two-decimal rounding, cache invalidation, and rollback behavior match the pre-change snapshots.
- [ ] 6.3 Run `ruff check`, `ruff format --check`, `PYTHONPATH=src .venv/bin/lint-imports --no-cache`, architecture tests, the full backend regression suite, and PostgreSQL metadata comparison; verify all pass with no schema drift.
- [ ] 6.4 Update the change documentation with the final mutation inventory, concurrency evidence, deployment/rollback notes, and remaining follow-up ownership; verify `openspec validate make-credit-changes-atomic --strict` and a clean working tree.
