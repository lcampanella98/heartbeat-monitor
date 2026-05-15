#!/usr/bin/env bash
set -euo pipefail

WIPE=false
for arg in "$@"; do
    case "$arg" in
        --wipe) WIPE=true ;;
        *) echo "Unknown argument: $arg" >&2; exit 1 ;;
    esac
done

if [ "$WIPE" = true ]; then
    docker compose down -v
    echo "Stopped and wiped volumes."
else
    docker compose down
    echo "Stopped."
fi
