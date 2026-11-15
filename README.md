# LinkGuard: сокращатель ссылок с антифишинговой проверкой

Пользователь сокращает длинную ссылку. Пока сервис-сканер не проверил адрес, ссылка имеет статус «проверяется». Опасная ссылка вместо перехода показывает предупреждение, безопасная работает как обычный редирект.

## Компоненты

| Сервис | Технология | Роль |
| :--- | :--- | :--- |
| frontend | nginx 1.27 | Веб-интерфейс, reverse proxy `/api` и `/s` на api, заголовки безопасности |
| api | Python, FastAPI | REST API: CRUD ссылок, редирект, публикация задач в RabbitMQ, приём результатов |
| scanner | Python, pika | Воркер: забирает задачи из очереди, проверяет URL, публикует вердикт |
| pg1, pg2 | PostgreSQL 17 | Master и hot standby с потоковой репликацией |
| pg-watchdog | Python | Следит за ролями узлов и делает автоматический failover (`pg_promote`) |
| backup | PostgreSQL 17 (pg_dump) | Плановое резервное копирование, восстановление через `pg_restore` |
| redis | Redis 7.4 | Кеш редиректов (cache-aside, TTL 300 с), счётчики переходов, rate limit |
| rabbit1..3 | RabbitMQ 4.1 | Кластер из 3 узлов, quorum-очереди `links.scan` и `links.scan_results` |
| firewall | Alpine + iptables | Белый список потоков между контейнерами в цепочке DOCKER-USER |

## Поток данных

1. `POST /api/links` → api пишет ссылку в PostgreSQL (`INSERT`, статус `pending`) и публикует задачу в очередь `links.scan`.
2. scanner потребляет задачу, проверяет адрес (чёрный список, IP вместо домена, punycode, `@` в адресе, много поддоменов, подозрительные слова) и публикует результат в `links.scan_results`.
3. Фоновый consumer в api делает `UPDATE` статуса в БД и удаляет ключ из Redis.
4. `GET /s/<code>` → api ищет ссылку в Redis (`X-Cache: HIT`), при промахе берёт из БД (`SELECT`) и кладёт в кеш (`X-Cache: MISS`).
5. `PATCH` меняет адрес и отправляет его на повторную проверку, `DELETE` удаляет ссылку и чистит кеш.

## Запуск

```bash
git clone https://github.com/GlalexHSE/linkguard.git && cd linkguard
./scripts/deploy.sh          # .env из .env.example, docker compose build + up, правила firewall
```

Веб-интерфейс: http://localhost:8080, панель RabbitMQ: http://localhost:15672 (логин и пароль в `.env`, создаётся из `.env.example` при первом деплое).

## Сегментация сетей

| Сегмент | Подсеть | Участники | Назначение |
| :--- | :--- | :--- | :--- |
| edge | 172.30.1.0/24 | frontend .10, api .20 | Пользовательский трафик. Наружу опубликован только порт 8080 фронтенда |
| data | 172.30.2.0/24 | api .20, pg1 .31, pg2 .32, redis .40, pg-watchdog .50, backup .60 | Хранилища данных |
| broker | 172.30.3.0/24 | api .20, rabbit1-3 .11-.13, scanner .30 | Обмен сообщениями |

Только api входит во все три сегмента. Сканер обрабатывает недоверенные URL, поэтому он изолирован в broker и не имеет доступа к БД и кешу.

## Firewall

Правила в `firewall/rules.conf`, применяются скриптом `firewall/fw.sh` в цепочку `DOCKER-USER` (через неё ядро пропускает трафик между контейнерами, в том числе внутри одного bridge благодаря `br_netfilter`). Политика: established/related → белый список → DROP всего трафика внутри 172.30.0.0/16.

```bash
./scripts/fw.sh show             # все правила со счётчиками пакетов
./scripts/fw-test.sh             # матрица разрешённых и запрещённых соединений
./scripts/fw.sh deny api-redis   # убрать легитимное правило: api отвечает 503 cache unavailable
./scripts/fw.sh apply            # вернуть правила
```

## Отказоустойчивость

PostgreSQL: api подключается строкой `host=pg1,pg2 target_session_attrs=read-write`, libpq сам выбирает узел, который принимает запись.

```bash
docker compose kill pg1                 # аварийное завершение master
docker compose logs -f pg-watchdog      # через ~6 с: FAILOVER: promoted pg2 to master
curl localhost:8080/api/health          # postgres.master = 172.30.2.32
./scripts/pg-rejoin.sh                  # вернуть pg1 как standby нового master
```

RabbitMQ: quorum-очереди реплицируются на 3 узла (Raft), переживают потерю одного узла. Клиенты перебирают узлы rabbit1 → rabbit2 → rabbit3.

```bash
docker compose kill rabbit1
docker compose exec rabbit2 rabbitmq-queues quorum_status links.scan
curl localhost:8080/api/health          # rabbitmq.node = rabbit2
```

Резервное копирование:

```bash
docker compose exec backup bash /opt/backup/backup.sh     # дамп в ./backups
docker compose exec backup bash /opt/backup/restore.sh    # восстановление из последнего дампа
```

## Параметры обслуживания

| Параметр | Значение | Обоснование |
| :--- | :--- | :--- |
| SLO доступности | 99,5 % в месяц (≈3,6 ч простоя) | Учебный сервис без дежурной смены. Сбой одного узла БД или брокера закрывается автоматически |
| SLO задержки редиректа | 95 % запросов быстрее 100 мс | Горячие ссылки отдаются из Redis без обращения к БД |
| RPO | ≤ 1 ч (логическая копия), около 0 при падении master | Дамп раз в час; потоковая репликация держит standby почти в актуальном состоянии |
| RTO / MTTR | ≤ 10 с при падении master, ≤ 15 мин при восстановлении из бэкапа | watchdog: 3 проверки по 2 с + promote; restore небольшой БД занимает минуты, плюс время на решение |
| MTBF узла | ≈ 720 ч (оценка: 1 сбой узла в месяц) | Один хост, WSL/ноутбук: перезагрузки и обновления |
| Хранение бэкапов | 24 последних дампа | Сутки почасовых копий |

Оценка доступности: A = MTBF / (MTBF + MTTR). При MTBF 720 ч и MTTR 10 с получаем почти 100 %. При ручном восстановлении из бэкапа (MTTR 15 мин) A = 720 / 720,25 ≈ 99,97 %, что укладывается в SLO 99,5 % с запасом под плановые работы.
