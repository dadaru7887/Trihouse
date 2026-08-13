# Dynamic Smoke Job Time Design

## Problem

`db/seed_dev.sql` creates `JOB-DEV-001` with `created_at` and `due_at`
hard-coded to 2026-08-03. A newly initialized development database therefore
shows an already overdue job during the 2026-08-13 integration test.

This is seed-data staleness, not a timezone conversion or Gateway API problem.

## Chosen Design

When the smoke job is inserted into a fresh database:

- set `created_at` to `CURRENT_TIMESTAMP(6)`;
- set `due_at` to `DATE_ADD(CURRENT_TIMESTAMP(6), INTERVAL 1 HOUR)`;
- keep the existing Asia/Seoul MySQL session behavior;
- on an idempotent seed rerun, keep the job's original timestamps instead of
  extending the deadline again.

The last rule means `due_at` must not be updated in the `ON DUPLICATE KEY
UPDATE` clause. It prevents repeated seed application from continuously moving
the same job's deadline.

## Alternatives Considered

1. Use current time plus one hour (chosen): remains useful whenever the seed is
   installed and gives the manual test a clear execution window.
2. Replace the date with a new fixed 2026-08-13 value: fixes only today's run
   and becomes stale again.
3. Remove the smoke job: avoids stale scheduling but removes useful Gateway and
   UI test data.

## Verification

The integration seed test will apply the seed twice and assert:

- `created_at` falls within the first seed execution window;
- `due_at` is exactly one hour after `created_at`;
- applying the seed a second time does not move either timestamp;
- the existing Orange lot and location mapping remains unchanged.

After the test passes, recreate `compose.db_test.yaml` so the running manual-test
database receives the corrected seed.
