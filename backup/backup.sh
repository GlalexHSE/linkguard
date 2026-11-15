#!/bin/bash
set -euo pipefail
file="/backups/links_$(date +%Y%m%d_%H%M%S).dump"
pg_dump "$PG_CONN" --format=custom --file="$file"
echo "backup created: $file ($(du -h "$file" | cut -f1))"
