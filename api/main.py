import json
import logging
import os
import secrets
import string
import threading
import time
from urllib.parse import urlparse

import pika
import psycopg
import redis
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from psycopg.rows import dict_row
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("api")
logging.getLogger("pika").setLevel(logging.WARNING)

PG_DSN = os.environ["PG_DSN"]
AMQP_HOSTS = os.environ["AMQP_HOSTS"].split(",")
AMQP_CREDS = pika.PlainCredentials(os.environ["AMQP_USER"], os.environ["AMQP_PASSWORD"])
SCAN_QUEUE = "links.scan"
RESULT_QUEUE = "links.scan_results"
CACHE_TTL = 300
RATE_LIMIT_PER_MIN = 10
CODE_ALPHABET = string.ascii_letters + string.digits

cache = redis.Redis(host=os.environ["REDIS_HOST"], decode_responses=True,
                    socket_timeout=2, socket_connect_timeout=2)
app = FastAPI(title="LinkGuard API")


class LinkIn(BaseModel):
    url: str


def db():
    return psycopg.connect(PG_DSN, autocommit=True, row_factory=dict_row)


def amqp_connect():
    params = [pika.ConnectionParameters(host=h, credentials=AMQP_CREDS, connection_attempts=1,
                                        socket_timeout=2, blocked_connection_timeout=5, heartbeat=30)
              for h in AMQP_HOSTS]
    conn = pika.BlockingConnection(params)  # pika перебирает узлы по порядку: rabbit1 упал -> rabbit2
    ch = conn.channel()
    for q in (SCAN_QUEUE, RESULT_QUEUE):
        ch.queue_declare(q, durable=True, arguments={"x-queue-type": "quorum"})
    return conn, ch


def publish_scan(code: str, url: str) -> bool:
    try:
        conn, ch = amqp_connect()
        ch.confirm_delivery()
        ch.basic_publish("", SCAN_QUEUE, json.dumps({"code": code, "url": url}),
                         pika.BasicProperties(delivery_mode=2, content_type="application/json"))
        conn.close()
        return True
    except pika.exceptions.AMQPError as e:
        log.error("publish failed: %r", e)
        return False


def results_consumer():
    while True:
        try:
            conn, ch = amqp_connect()

            def on_result(channel, method, _props, body):
                r = json.loads(body)
                with db() as c:
                    c.execute("UPDATE links SET status=%s, verdict=%s, checked_at=now() WHERE code=%s",
                              (r["status"], r["verdict"], r["code"]))
                cache.delete(f"link:{r['code']}")
                channel.basic_ack(method.delivery_tag)
                log.info("scan result %s -> %s (%s)", r["code"], r["status"], r["verdict"])

            ch.basic_qos(prefetch_count=10)
            ch.basic_consume(RESULT_QUEUE, on_result)
            log.info("results consumer connected to %s", conn._impl.params.host)
            ch.start_consuming()
        except Exception as e:
            log.warning("results consumer error: %r, reconnecting in 2s", e)
            time.sleep(2)


@app.on_event("startup")
def start_consumer():
    threading.Thread(target=results_consumer, daemon=True).start()


@app.exception_handler(psycopg.OperationalError)
def db_down(_req, e):
    log.error("database error: %r", e)
    return JSONResponse({"error": "database unavailable", "detail": str(e).strip()}, status_code=503)


@app.exception_handler(redis.RedisError)
def cache_down(_req, e):
    log.error("cache error: %r", e)
    return JSONResponse({"error": "cache unavailable", "detail": str(e)}, status_code=503)


def rate_limit(request: Request):
    ip = request.headers.get("x-real-ip", request.client.host)
    key = f"rl:{ip}:{int(time.time() // 60)}"
    n = cache.incr(key)
    cache.expire(key, 60)
    if n > RATE_LIMIT_PER_MIN:
        raise HTTPException(429, "too many links, try again in a minute")


def validate_url(url: str) -> str:
    url = url.strip()
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc or len(url) > 2048:
        raise HTTPException(422, "only http(s) URLs up to 2048 chars are allowed")
    return url


def with_clicks(rows):
    if not rows:
        return rows
    clicks = cache.mget([f"clicks:{r['code']}" for r in rows])
    for r, c in zip(rows, clicks):
        r["clicks"] = int(c or 0)
    return rows


@app.get("/api/hello")
def hello():
    return {"message": "Hello from LinkGuard api!"}


@app.get("/api/health")
def health():
    result = {}
    try:
        with db() as c:
            row = c.execute("SELECT host(inet_server_addr()) AS addr, pg_is_in_recovery() AS standby").fetchone()
        result["postgres"] = {"ok": True, "master": row["addr"]}
    except psycopg.Error as e:
        result["postgres"] = {"ok": False, "error": str(e).strip()}
    try:
        result["redis"] = {"ok": cache.ping()}
    except redis.RedisError as e:
        result["redis"] = {"ok": False, "error": str(e)}
    try:
        conn, _ = amqp_connect()
        result["rabbitmq"] = {"ok": True, "node": conn._impl.params.host}
        conn.close()
    except pika.exceptions.AMQPError as e:
        result["rabbitmq"] = {"ok": False, "error": repr(e)}
    return result


@app.post("/api/links", status_code=201)
def create_link(body: LinkIn, request: Request):
    url = validate_url(body.url)
    rate_limit(request)
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
    with db() as c:
        link = c.execute("INSERT INTO links (code, target_url) VALUES (%s, %s) RETURNING *",
                         (code, url)).fetchone()
    link["scan_queued"] = publish_scan(code, url)
    return link


@app.get("/api/links")
def list_links():
    with db() as c:
        rows = c.execute("SELECT * FROM links ORDER BY id DESC LIMIT 100").fetchall()
    return with_clicks(rows)


@app.get("/api/links/{code}")
def get_link(code: str):
    with db() as c:
        row = c.execute("SELECT * FROM links WHERE code=%s", (code,)).fetchone()
    if not row:
        raise HTTPException(404, "link not found")
    return with_clicks([row])[0]


@app.patch("/api/links/{code}")
def update_link(code: str, body: LinkIn):
    url = validate_url(body.url)
    with db() as c:
        row = c.execute("UPDATE links SET target_url=%s, status='pending', verdict=NULL, checked_at=NULL "
                        "WHERE code=%s RETURNING *", (url, code)).fetchone()
    if not row:
        raise HTTPException(404, "link not found")
    cache.delete(f"link:{code}")
    row["scan_queued"] = publish_scan(code, url)
    return row


@app.delete("/api/links/{code}")
def delete_link(code: str):
    with db() as c:
        deleted = c.execute("DELETE FROM links WHERE code=%s", (code,)).rowcount
    if not deleted:
        raise HTTPException(404, "link not found")
    cache.delete(f"link:{code}", f"clicks:{code}")
    return {"deleted": code}


@app.get("/api/stats")
def stats():
    with db() as c:
        by_status = {r["status"]: r["n"] for r in
                     c.execute("SELECT status, count(*) AS n FROM links GROUP BY status").fetchall()}
    hits, misses = cache.mget("stats:cache_hit", "stats:cache_miss")
    return {"links_by_status": by_status, "cache_hit": int(hits or 0), "cache_miss": int(misses or 0)}


PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>LinkGuard</title>
<style>body{{font-family:system-ui,sans-serif;max-width:640px;margin:10vh auto;padding:0 16px}}
.box{{border-left:6px solid {color};padding:16px 20px;background:#f6f6f6}}code{{word-break:break-all}}</style>
</head><body><div class="box"><h1>{title}</h1><p>{text}</p><p><code>{url}</code></p></div></body></html>"""


@app.get("/s/{code}")
def follow(code: str):
    key = f"link:{code}"
    cached = cache.get(key)
    if cached:
        link = json.loads(cached)
        cache.incr("stats:cache_hit")
        source = "HIT"
    else:
        with db() as c:
            row = c.execute("SELECT target_url, status, verdict FROM links WHERE code=%s", (code,)).fetchone()
        if not row:
            raise HTTPException(404, "link not found")
        link = dict(row)
        cache.set(key, json.dumps(link, ensure_ascii=False), ex=CACHE_TTL)
        cache.incr("stats:cache_miss")
        source = "MISS"
    cache.incr(f"clicks:{code}")
    headers = {"X-Cache": source}

    if link["status"] == "clean":
        return RedirectResponse(link["target_url"], status_code=302, headers=headers)
    if link["status"] == "malicious":
        html = PAGE.format(color="#c0392b", title="Опасная ссылка",
                           text=f"Переход заблокирован. Причина: {link['verdict']}", url=link["target_url"])
        return HTMLResponse(html, status_code=403, headers=headers)
    html = PAGE.format(color="#e1a100", title="Ссылка проверяется",
                       text="Сканер ещё не проверил адрес. Обновите страницу через пару секунд.",
                       url=link["target_url"])
    return HTMLResponse(html, status_code=202, headers=headers)
