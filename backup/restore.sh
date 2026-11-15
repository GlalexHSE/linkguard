#!/bin/bash
set -euo pipefail
file="${1:-$(ls -1t /backups/*.dump | head -1)}"
echo "restoring from $file"
pg_restore --dbname="$PG_CONN" --clean --if-exists --no-owner "$file"
echo "restore done"
