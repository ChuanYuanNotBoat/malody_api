# Capability Matrix Baseline

Generated: 2026-05-07

## API
- Covered domains:
  - `players/*`
  - `charts/*`
  - `analytics/*`
  - `crawler/*`
  - `quality/*`
  - `plugins/*`
  - `query/*`
  - `page-parser/*`
  - `official-api/*`
  - `system/*`
- New consistency/ops capability:
  - `GET /crawler/status` includes `data_source_health` summary.

## CLI (`malody_stats.py`)
- Command system:
  - Plugin-based command installation via `stats_cli/plugins/*`.
  - `update` command uses centralized whitelist config (`utils/stats_update_runner.py`).
  - `export` command validates type/options through centralized rules (`utils/stats_export_runner.py`).
- Regression assets:
  - `tests/fixtures/cli_regression_cases.json`
  - `tests/test_stats_cli_regression_cases.py`

## Desktop GUI (`desktop/`)
- Existing operational tabs:
  - Overview
  - Crawler Control
  - Data Quality
  - DB Maintenance
  - Plugins
- New capabilities in this baseline:
  - Analytics tab:
    - mode comparison
    - player comparison
    - chart trends
  - Query & Export tab:
    - predefined query execution
    - query result rendering
    - chart export URL workflow
  - Crawler advanced params by crawler type.
  - Plugin schema-driven payload form (`run_schema`).
