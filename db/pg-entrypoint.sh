#!/bin/bash
# Один скрипт для обоих узлов. Без REPLICATE_FROM узел инициализируется как master,
# с REPLICATE_FROM на пустом каталоге данных клонируется с указанного узла и стартует как standby.
set -e
PGDATA=${PGDATA:-/var/lib/postgresql/data}

if [ -z "$REPLICATE_FROM" ]; then
  cp /opt/pg/schema.sql /opt/pg/init-replication.sh /docker-entrypoint-initdb.d/
elif [ ! -s "$PGDATA/PG_VERSION" ]; then
  echo "standby: waiting for $REPLICATE_FROM"
  until pg_isready -h "$REPLICATE_FROM" -U "$POSTGRES_USER" -q; do sleep 1; done
  mkdir -p "$PGDATA" && chown postgres:postgres "$PGDATA" && chmod 700 "$PGDATA"
  PGPASSWORD="$REPL_PASSWORD" gosu postgres \
    pg_basebackup -h "$REPLICATE_FROM" -U replicator -D "$PGDATA" -R -X stream
  echo "standby: base backup from $REPLICATE_FROM done"
fi

exec docker-entrypoint.sh postgres -c wal_keep_size=256MB -c hot_standby=on
