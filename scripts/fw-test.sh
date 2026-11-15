#!/bin/bash
# Матрица проверок: из контейнера-источника пытаемся открыть TCP-соединение к адресу назначения.
cd "$(dirname "$0")/.."

checks=(
  "allow frontend 172.30.1.20:8000 фронт -> api"
  "allow api      172.30.2.31:5432 api -> PostgreSQL pg1"
  "allow api      172.30.2.40:6379 api -> Redis"
  "allow api      172.30.3.11:5672 api -> RabbitMQ rabbit1"
  "allow scanner  172.30.3.12:5672 сканер -> RabbitMQ rabbit2"
  "allow pg2      172.30.2.31:5432 репликация pg2 -> pg1"
  "allow backup   172.30.2.31:5432 бэкап -> PostgreSQL"
  "deny  frontend 172.30.2.31:5432 фронт -> БД (другой сегмент)"
  "deny  frontend 172.30.2.40:6379 фронт -> Redis (другой сегмент)"
  "deny  scanner  172.30.2.31:5432 сканер -> БД (другой сегмент)"
  "deny  scanner  172.30.3.20:8000 сканер -> api (тот же сегмент broker)"
  "deny  backup   172.30.2.40:6379 бэкап -> Redis (тот же сегмент data)"
  "deny  redis    172.30.2.31:5432 Redis -> БД (тот же сегмент data)"
)

failed=0
for c in "${checks[@]}"; do
  read -r expect src dst desc <<<"$c"
  if docker compose exec -T "$src" timeout 2 bash -c "</dev/tcp/${dst%:*}/${dst#*:}" 2>/dev/null; then
    got=allow
  else
    got=deny
  fi
  if [ "$got" = "$expect" ]; then mark=OK; else mark=FAIL; failed=1; fi
  printf "%-4s ожидалось %-5s факт %-5s %-8s -> %-17s %s\n" "$mark" "$expect" "$got" "$src" "$dst" "$desc"
done
exit $failed
