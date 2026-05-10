# Operations Runbook

## Failure Categories
1. Network failures:
   - timeout, DNS, connection reset, TLS/SSL.
2. Structure failures:
   - parser selector mismatch, missing nodes, schema change.
3. Auth failures:
   - 401/403, token/cookie invalid.
4. Unknown failures:
   - anything that does not match known categories.

`/crawler/status` now exposes:
- `data_source_health.sources`
- `data_source_health.failure_categories`

## Emergency Steps
1. Check health snapshot:
   - `GET /crawler/status`
2. Stop risky maintenance runs:
   - avoid `VACUUM` during incident windows.
3. Narrow crawler scope:
   - run with smaller `limit` and stricter `source`.
4. Collect evidence:
   - task logs under `logs/crawler_tasks/`
   - unified task logs under `logs/tasks/*.jsonl`
   - consistency reports under `logs/`

## Rollback
1. Revert to last known good commit.
2. Run merge gates locally:
   - unit tests
   - compile check
   - consistency check
3. Start API and validate:
   - `/health`
   - `/crawler/status`
   - `/quality/report`

## Recovery Verification
1. Launch one crawler task per type (`leaderboard`, `player`, `stb`).
2. Confirm `/crawler/tasks` and `/crawler/tasks/{task_id}/log`.
3. Run consistency script:
   - ensure no blocking checks.
4. Validate GUI critical paths:
   - analytics queries
   - query/export flow
   - plugin schema run flow
