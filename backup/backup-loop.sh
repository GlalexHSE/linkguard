#!/bin/bash
# Плановое резервное копирование: каждые BACKUP_INTERVAL секунд делает дамп текущего master
# и хранит 24 последних копии.
set -u
while true; do
  /bin/bash /opt/backup/backup.sh
  ls -1t /backups/*.dump 2>/dev/null | tail -n +25 | xargs -r rm -f
  sleep "$BACKUP_INTERVAL"
done
