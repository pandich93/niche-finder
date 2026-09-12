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

ENV_FILE=""
[ -f "$DIR/.env" ] && ENV_FILE="$DIR/.env"
[ -z "$ENV_FILE" ] && [ -f "$DIR/backend/.env" ] && ENV_FILE="$DIR/backend/.env"

# ВАЖНО: здесь НЕЛЬЗЯ использовать `docker run --env-file`.
# `docker compose` парсит .env по правилам dotenv и снимает кавычки вокруг
# значения, а `docker run --env-file` читает строку буквально — и
# YOUTUBE_API_KEY="AIza..." уезжает в контейнер вместе с кавычками. Тогда
# воркер (через compose) работает, а MCP-сервер получает битый ключ и КАЖДЫЙ
# вызов к YouTube API падает. Ровно это сломало сессию 6 сентября 2026.
# Поэтому разбираем файл сами и снимаем обрамляющие кавычки.
set --
if [ -n "$ENV_FILE" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    line=$(printf '%s' "$line" | tr -d '\r')
    line=${line# }
    line=${line#export }
    case "$line" in
      ''|\#*) continue ;;
      *=*) ;;
      *) continue ;;
    esac
    name=${line%%=*}
    value=${line#*=}
    case "$name" in
      ''|*[!A-Za-z0-9_]*) continue ;;
      # NICHE_DATABASE_URL в .env описывает путь к базе С ХОСТА
      # (localhost:5433). Внутри контейнера localhost -- это сам контейнер, а в
      # _dsn() этот URL важнее POSTGRES_*, поэтому он бы перебил
      # POSTGRES_HOST=postgres ниже и сломал MCP-сервер. Оставляем его хосту.
      NICHE_DATABASE_URL) continue ;;
    esac
    case "$value" in
      '"'*'"') value=${value#\"}; value=${value%\"} ;;
      "'"*"'") value=${value#\'}; value=${value%\'} ;;
    esac
    set -- "$@" -e "$name=$value"
  done < "$ENV_FILE"
fi

# Код монтируется из репозитория, поэтому Claude Desktop всегда запускает
# текущую версию — пересобирать образ нужно только при смене requirements.txt.
exec docker run --rm -i \
  --network niche-finder_default \
  "$@" \
  -e POSTGRES_HOST=postgres \
  -v "$DIR/backend:/app:ro" \
  -v niche-finder-models:/models \
  niche-finder:latest python server.py
