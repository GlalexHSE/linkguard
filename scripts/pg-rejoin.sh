#!/bin/bash
# Возврат упавшего pg1 в кластер после failover: старые данные удаляются,
# узел клонируется с нового master (pg2) и стартует как standby.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose rm -sf pg1
docker volume rm linkguard_pg1-data
PG1_REPLICATE_FROM=pg2 docker compose up -d --no-deps --wait pg1
docker compose logs pg1 | grep standby
