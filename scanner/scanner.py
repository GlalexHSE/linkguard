import ipaddress
import json
import logging
import os
import time
from urllib.parse import urlparse

import pika

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scanner")
logging.getLogger("pika").setLevel(logging.WARNING)

AMQP_HOSTS = os.environ["AMQP_HOSTS"].split(",")
AMQP_CREDS = pika.PlainCredentials(os.environ["AMQP_USER"], os.environ["AMQP_PASSWORD"])
SCAN_QUEUE = "links.scan"
RESULT_QUEUE = "links.scan_results"
SUSPICIOUS_WORDS = ("login", "verify", "secure", "account", "update", "wallet", "bank", "password")

with open("/app/blacklist.txt") as f:
    BLACKLIST = {line.strip().lower() for line in f if line.strip() and not line.startswith("#")}


def check(url: str) -> list[str]:
    p = urlparse(url)
    host = (p.hostname or "").lower()
    reasons = []
    if any(host == d or host.endswith("." + d) for d in BLACKLIST):
        reasons.append("домен в чёрном списке")
    try:
        ipaddress.ip_address(host)
        reasons.append("IP-адрес вместо домена")
    except ValueError:
        pass
    if "xn--" in host:
        reasons.append("punycode-домен (возможна подмена символов)")
    if "@" in p.netloc:
        reasons.append("символ @ в адресе (скрывает настоящий хост)")
    if host.count(".") >= 4:
        reasons.append("слишком много поддоменов")
    words = [w for w in SUSPICIOUS_WORDS if w in host]
    if len(words) >= 2:
        reasons.append("подозрительные слова в домене: " + ", ".join(words))
    return reasons


def main():
    params = [pika.ConnectionParameters(host=h, credentials=AMQP_CREDS, connection_attempts=1,
                                        socket_timeout=2, heartbeat=30) for h in AMQP_HOSTS]
    while True:
        try:
            conn = pika.BlockingConnection(params)
            ch = conn.channel()
            for q in (SCAN_QUEUE, RESULT_QUEUE):
                ch.queue_declare(q, durable=True, arguments={"x-queue-type": "quorum"})
            ch.confirm_delivery()

            def on_message(channel, method, _props, body):
                task = json.loads(body)
                time.sleep(1)  # имитация сетевой проверки, чтобы на демо был виден статус pending
                reasons = check(task["url"])
                result = {"code": task["code"],
                          "status": "malicious" if reasons else "clean",
                          "verdict": "; ".join(reasons) or "угроз не найдено"}
                channel.basic_publish("", RESULT_QUEUE, json.dumps(result, ensure_ascii=False),
                                      pika.BasicProperties(delivery_mode=2, content_type="application/json"))
                channel.basic_ack(method.delivery_tag)  # ack только после публикации результата
                log.info("scanned %s %s -> %s", task["code"], task["url"], result["status"])

            ch.basic_qos(prefetch_count=1)
            ch.basic_consume(SCAN_QUEUE, on_message)
            log.info("scanner connected to %s", conn._impl.params.host)
            ch.start_consuming()
        except Exception as e:
            log.warning("scanner error: %r, reconnecting in 2s", e)
            time.sleep(2)


if __name__ == "__main__":
    main()
