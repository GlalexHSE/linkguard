#!/bin/bash
set -euo pipefail
file="/backups/links_$(date +%Y%m%d_%H%M%S).dump"
# Дамп пишется во временный файл и переименовывается только после успеха:
# при недоступной БД не остаётся пустого .dump, который вытеснил бы хорошие копии из ротации.
if ! pg_dump "$PG_CONN" --format=custom --file="$file.part"; then
  rm -f "$file.part"
  echo "backup FAILED: database unavailable" >&2
  exit 1
fi
mv "$file.part" "$file"
echo "backup created: $file ($(du -h "$file" | cut -f1))"
