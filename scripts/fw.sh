#!/bin/bash
# Обёртка над контейнером firewall: ./scripts/fw.sh apply|show|deny <rule>|off
cd "$(dirname "$0")/.."
docker compose --profile firewall run --rm firewall "$@"
