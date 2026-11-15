import logging
import os
import time

import psycopg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pg-watchdog")

NODES = os.environ["PG_NODES"].split(",")
CONN = "host={} dbname={} user={} password={} connect_timeout=1".format(
    "{}", os.environ["PG_DB"], os.environ["PG_USER"], os.environ["PG_PASSWORD"])
FAILS_BEFORE_PROMOTE = 3
INTERVAL = 2


def role(node: str):
    try:
        with psycopg.connect(CONN.format(node), autocommit=True) as c:
            return "standby" if c.execute("SELECT pg_is_in_recovery()").fetchone()[0] else "master"
    except psycopg.Error:
        return "down"


def main():
    fails = 0
    last = None
    while True:
        roles = {n: role(n) for n in NODES}
        if roles != last:
            log.info("cluster state: %s", roles)
            last = roles
        masters = [n for n, r in roles.items() if r == "master"]
        standbys = [n for n, r in roles.items() if r == "standby"]
        if masters:
            fails = 0
        elif standbys:
            fails += 1
            log.warning("no master for %d checks", fails)
            if fails >= FAILS_BEFORE_PROMOTE:  # ~6 секунд без master, чтобы не реагировать на кратковременный сбой
                target = standbys[0]
                with psycopg.connect(CONN.format(target), autocommit=True) as c:
                    c.execute("SELECT pg_promote()")
                log.warning("FAILOVER: promoted %s to master", target)
                fails = 0
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
