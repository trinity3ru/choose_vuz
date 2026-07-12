# DEPLOY.md — размещение VuzFinder на VPS Hostkey

Проект — отдельный Docker Compose-проект `university` в `/opt/university`.
Главный принцип (ТЗ §4.19): **не задеть соседние проекты VPS** — не занимать
порты 80/443, не трогать чужие контейнеры/сети/тома, весь HTTP-трафик через
существующий Nginx Proxy Manager.

Все команды выполняются **из `/opt/university`**.

---

## 1. Подготовка VPS

Зафиксировать текущее состояние (ТЗ §4.14):

```bash
mkdir -p /root/vps-before-vuzfinder
docker ps                  > /root/vps-before-vuzfinder/docker-ps.txt
docker compose ls          > /root/vps-before-vuzfinder/docker-compose-ls.txt
docker network ls          > /root/vps-before-vuzfinder/docker-network-ls.txt
docker volume ls           > /root/vps-before-vuzfinder/docker-volume-ls.txt
docker stats --no-stream   > /root/vps-before-vuzfinder/docker-stats.txt
df -h                      > /root/vps-before-vuzfinder/df-h.txt
free -h                    > /root/vps-before-vuzfinder/free-h.txt
ss -tulpn                  > /root/vps-before-vuzfinder/ss-tulpn.txt
```

Найти имя proxy-сети Nginx Proxy Manager (понадобится для `.env`):

```bash
docker network ls
# ожидаемо: npm_default / nginx-proxy-manager_default / nginxproxymanager_default
```

## 2. Клонирование проекта

```bash
mkdir -p /opt/university && cd /opt/university
git clone git@github.com:trinity3ru/choose_vuz.git .
```

## 3. Создание .env

```bash
cd /opt/university
cp .env.example .env
nano .env
```

Обязательно заполнить:
- `POSTGRES_PASSWORD` — сильный пароль БД (и продублировать его в `DATABASE_URL`);
- `PARSER_TRIGGER_TOKEN` — токен ручного запуска парсера;
- `PROXY_NETWORK_NAME` — имя сети NPM из шага 1;
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — для алертов (или `TELEGRAM_ALERTS_ENABLED=false`).

## 4. Сборка контейнеров

```bash
cd /opt/university
docker compose build
```

## 5. Миграции

```bash
cd /opt/university
docker compose up -d postgres
docker compose run --rm api alembic upgrade head
```

Миграции НЕ выполняются автоматически при старте API — только этой командой (ТЗ §16).

## 6. Запуск

```bash
cd /opt/university
docker compose up -d
docker compose ps        # все четыре контейнера Up, postgres healthy
```

Быстрая самопроверка стека (сборка, api без Chromium, миграции, health, frontend):

```bash
bash scripts/smoke-check.sh
```

## 7. Домен и Nginx Proxy Manager

DNS (у регистратора):

```text
A   @     IP_СЕРВЕРА
A   www   IP_СЕРВЕРА
A   api   IP_СЕРВЕРА
```

Проверка распространения DNS: `dig vuzfinder.ru`, `dig api.vuzfinder.ru`.

В Nginx Proxy Manager создать два Proxy Host.

**На текущем VPS NPM работает с `network_mode: host`** и не резолвит имена
контейнеров — он проксирует на loopback-порты хоста. Наши порты публикует
`compose.override.yaml` (только на 127.0.0.1 — из интернета недоступны):

| Domain Names | Scheme | Forward Hostname | Port |
|---|---|---|---|
| `vuzfinder.ru`, `www.vuzfinder.ru` | http | `127.0.0.1` | 8086 |
| `api.vuzfinder.ru` | http | `127.0.0.1` | 8087 |

(Вариант для NPM в bridge-сети: forward на `university-frontend:3000` и
`university-api:8000` по общей сети `PROXY_NETWORK_NAME`; тогда
`compose.override.yaml` не нужен.)

SSL для обоих: Request a new SSL Certificate (Let's Encrypt), Force SSL, HTTP/2.

Проверка:

```bash
curl -I https://vuzfinder.ru
curl -I https://api.vuzfinder.ru/health
```

## 8. Расписание парсеров (systemd)

```bash
cd /opt/university
sudo bash scripts/install-timers.sh
systemctl list-timers 'university-*'
```

Создаёт: ночные слоты по вузу (00:30, 01:00, … шаг 30 мин — из `backend/config.json`),
recover зависших задач каждые 15 мин, почасовой health-check (stale-алерты),
ежедневный backup в 07:30. Пересоздать с другим графиком:
`sudo bash scripts/install-timers.sh --start 01:00 --step 20`. Снять всё: `--uninstall`.

## 9. Ручной запуск парсера

```bash
cd /opt/university

# поставить вуз в очередь (worker подхватит сам):
docker compose exec -T api python -m app.cli enqueue spbstu

# либо через API с токеном:
curl -X POST -H "Authorization: Bearer $PARSER_TRIGGER_TOKEN" \
  https://api.vuzfinder.ru/api/v1/parser/run/spbstu

# синхронный запуск одного вуза (в worker, с advisory-lock):
docker compose exec -T worker python -m app.cli parse-university spbstu

# все вузы подряд:
docker compose exec -T worker python -m app.cli parse-all
```

Состояние: `GET https://api.vuzfinder.ru/api/v1/parser/health` и
`GET .../api/v1/parser/runs?limit=20`.

## 10. Логи

```bash
cd /opt/university
docker compose logs -f api
docker compose logs -f worker
ls parser-logs/ parser-screenshots/
```

Docker-логи ротируются автоматически (json-file, 20 МБ × 5 файлов на контейнер).

## 11. Backup и восстановление

Backup создаётся ежедневно таймером; вручную:

```bash
cd /opt/university
bash scripts/backup-db.sh          # -> backups/university-ДАТА.sql.gz
```

Восстановление (ЗАМЕНЯЕТ все данные проекта; соседей VPS не трогает):

```bash
cd /opt/university
docker compose stop worker
bash scripts/restore-db.sh backups/university-YYYY-MM-DD-HHMMSS.sql.gz
docker compose start worker
```

Копии старше `BACKUP_RETENTION_DAYS` (14 дней) удаляются автоматически.

## 12. Обновление через git pull

```bash
cd /opt/university
git pull
docker compose build
docker compose run --rm api alembic upgrade head
docker compose up -d
```

Если менялся состав вузов в `backend/config.json` — переустановить таймеры:
`sudo bash scripts/install-timers.sh`.

---

## Что запрещено (ТЗ §4.13)

```bash
docker stop $(docker ps -q)      # НЕЛЬЗЯ — остановит соседние проекты
docker system prune -a           # НЕЛЬЗЯ
docker volume prune              # НЕЛЬЗЯ
docker network prune             # НЕЛЬЗЯ
docker compose down              # только из /opt/university и осознанно
```

## Чек-лист приёмки (ТЗ §25)

1. [ ] Проект в `/opt/university`.
2. [ ] `vuzfinder.ru` открывает frontend.
3. [ ] `api.vuzfinder.ru` открывает FastAPI (`/health` → ok).
4. [ ] SSL выпущены через Nginx Proxy Manager.
5. [ ] Существующие проекты VPS работают.
6. [ ] PostgreSQL не доступен извне (`ss -tulpn | grep 5432` — пусто).
7. [ ] FastAPI не запускает регулярные парсеры сам (ENABLE_SCHEDULER=false).
8. [ ] Worker запускает парсер вуза через CLI (`parse-university spbstu`).
9. [ ] Playwright установлен только в worker-контейнере.
10. [ ] API-контейнер без Chromium (`scripts/smoke-check.sh`, шаг 2).
11. [ ] `GET /api/v1/parser/health` отвечает.
12. [ ] `GET /api/v1/parser/runs` отвечает.
13. [ ] `POST /api/v1/parser/run/{code}` защищён токеном (401/403/202).
14. [ ] История запусков в таблице `parser_runs`.
15. [ ] Логи парсеров в `/opt/university/parser-logs`.
16. [ ] Скриншоты ошибок в `/opt/university/parser-screenshots`.
17. [ ] Telegram-уведомление приходит при ошибке парсера.
18. [ ] Frontend показывает время последнего обновления данных.
19. [ ] Ежедневный backup создаётся в `/opt/university/backups`.
20. [ ] Старые backup-файлы удаляются по retention.
21. [ ] Команда восстановления — раздел 11 этого файла.
22. [ ] Docker-логи ротируются (json-file 20m×5 в compose.yaml).
23. [ ] Контейнеры имеют лимиты ресурсов (`docker stats`).
24. [ ] Парсеры запускаются ночью по расписанию (`systemctl list-timers 'university-*'`).
25. [ ] Параллельный запуск тяжёлых парсеров заблокирован (flock + advisory-lock).
