#!/bin/sh
set -eu

MYSQL_HOST="${MYSQL_HOST:-mysql}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_DATABASE="${MYSQL_DATABASE:-knowledge_post_agent}"
MYSQL_USER="${MYSQL_USER:-app}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-}"
MYSQL_PASSWORD_FILE="${MYSQL_PASSWORD_FILE:-}"
INIT_SQL="${INIT_SQL:-/app/shared/sql/init.sql}"
MIGRATION_DIR="${MIGRATION_DIR:-/app/shared/sql/migrations}"
WAIT_SECONDS="${MIGRATION_WAIT_SECONDS:-120}"

if [ -n "$MYSQL_PASSWORD_FILE" ] && [ -f "$MYSQL_PASSWORD_FILE" ]; then
  MYSQL_PASSWORD="$(cat "$MYSQL_PASSWORD_FILE")"
fi

if [ -z "$MYSQL_PASSWORD" ]; then
  echo "MYSQL_PASSWORD or MYSQL_PASSWORD_FILE is required" >&2
  exit 1
fi

if [ ! -f "$INIT_SQL" ]; then
  echo "missing init SQL: $INIT_SQL" >&2
  exit 1
fi

if [ ! -d "$MIGRATION_DIR" ]; then
  echo "missing migration dir: $MIGRATION_DIR" >&2
  exit 1
fi

deadline=$(( $(date +%s) + WAIT_SECONDS ))
until MYSQL_PWD="$MYSQL_PASSWORD" mysqladmin ping \
  -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" --protocol=tcp --silent >/dev/null 2>&1; do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "timed out waiting for MySQL at $MYSQL_HOST:$MYSQL_PORT" >&2
    exit 1
  fi
  sleep 2
done

echo "applying init schema: $INIT_SQL"
MYSQL_PWD="$MYSQL_PASSWORD" mysql \
  -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" --protocol=tcp "$MYSQL_DATABASE" < "$INIT_SQL"

for migration in "$MIGRATION_DIR"/*.sql; do
  [ -e "$migration" ] || continue
  echo "applying migration: $(basename "$migration")"
  MYSQL_PWD="$MYSQL_PASSWORD" mysql \
    -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" --protocol=tcp "$MYSQL_DATABASE" < "$migration"
done

echo "database migrations applied"
