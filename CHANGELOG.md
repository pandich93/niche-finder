# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

Nothing yet.

## [0.1.0] - 2026-09-06

Initial public release.

### Added

- **MCP server** (`backend/interfaces/mcp/server.py`) — 24 tools for Claude
  Desktop: collection (`collect_niche`, `collect_channel`,
  `collect_trending`, `refresh_stats`, `refresh_channels`,
  `refresh_categories`), free sections (`viral_videos_small_channels`,
  `recently_added_outlier_channels`, `high_future_competition`,
  `most_popular_categories`, `trending_keywords`, `search_outliers`,
  `niche_overview`, `list_niches`, `db_stats`, `data_coverage`), and channel
  tracking/analysis (`track_channel`, `channel_analytics`,
  `compare_channels`, `channel_velocity`, `title_changes`,
  `best_time_to_publish`, `title_patterns`, `calibrate_maturity_curve`, and
  more).
- **HTTP API** (`backend/interfaces/http/api.py`, FastAPI) exposing the same
  use cases as the MCP server, for the dashboard.
- **Background worker** (`backend/interfaces/worker/main.py`) that snapshots
  view/subscriber counts on a schedule — the only reason growth rate,
  acceleration, and period comparisons can exist at all.
- **Dashboard** (`frontend/`, no build step, plain ES modules): Overview,
  Viral videos, Outlier channels, Categories, Keywords, Channel tracker,
  Niches, Channel detail, and Data screens.
- **PostgreSQL storage** with a schema migration path from the earlier
  SQLite-based prototype (`backend/migrate_sqlite_to_postgres.py`).
- **Docker Compose** setup bringing up Postgres, the worker, the dashboard,
  and the MCP server (stdio and HTTP profile) with one command.
- **CI** (GitHub Actions): smoke tests against a real Postgres service
  container, a `docker compose build` check, and an auto-updated test
  coverage badge.
- MIT license.
