#!/usr/bin/env bash
set -euo pipefail

DEMO=false
SMTP=false
for arg in "$@"; do
    case "$arg" in
        --demo) DEMO=true ;;
        --smtp) SMTP=true ;;
        *) echo "Unknown argument: $arg" >&2; exit 1 ;;
    esac
done

COMPOSE_FILES="-f docker-compose.yml"
if [ "$DEMO" = true ]; then
    COMPOSE_FILES="$COMPOSE_FILES -f docker-compose.demo.yml"
fi
if [ "$SMTP" = true ]; then
    COMPOSE_FILES="$COMPOSE_FILES -f docker-compose.smtp.yml"
fi

echo "Starting heartbeat-monitor..."
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES up -d --build

echo "Waiting for backend..."
for i in $(seq 1 60); do
    if curl -sf http://localhost:8000/api/v1/system/status >/dev/null 2>&1; then
        echo "Ready at http://localhost:8000"
        curl -s http://localhost:8000/api/v1/system/status
        echo
        exit 0
    fi
    sleep 1
done

echo "ERROR: backend did not become ready within 60 seconds" >&2
exit 1
