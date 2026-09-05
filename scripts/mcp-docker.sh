#!/usr/bin/env sh
# Launcher for the MCP server inside Docker, for Claude Desktop / Claude Code.
#
# Point your MCP config at this script instead of a long `docker run` line:
#   "niche-finder": { "command": "/full/path/to/scripts/mcp-docker.sh" }
#
# It shares the same named volumes as `docker compose up worker`, so the tools
# see everything the background collector has gathered.
#
# The data itself lives in Postgres, in the `niche-finder_default` network
# that `docker compose up` creates -- this script must run AFTER that at least
# once, and joins that network by name so `POSTGRES_HOST=postgres` resolves.
set -eu
DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENV_ARG=""
[ -f "$DIR/.env" ] && ENV_ARG="--env-file $DIR/.env"
[ -z "$ENV_ARG" ] && [ -f "$DIR/backend/.env" ] && ENV_ARG="--env-file $DIR/backend/.env"

# Код монтируется из репозитория, поэтому Claude Desktop всегда запускает
# текущую версию — пересобирать образ нужно только при смене requirements.txt.
exec docker run --rm -i \
  --network niche-finder_default \
  $ENV_ARG \
  -e POSTGRES_HOST=postgres \
  -v "$DIR/backend:/app:ro" \
  -v niche-finder-models:/models \
  niche-finder:latest python server.py
