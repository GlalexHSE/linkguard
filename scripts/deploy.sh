#!/bin/bash
# Сборка и деплой: образы -> контейнеры -> правила firewall.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || cp .env.example .env
docker compose build
docker compose up -d --wait
./scripts/fw.sh apply
docker compose ps
