# DEPLOY.md — размещение VuzFinder на VPS Hostkey

> Скелет. Разделы заполняются по мере выполнения DEPLOY_PLAN.md (этап 10).
> Главный принцип: VuzFinder — отдельный compose-проект `university` в `/opt/university`,
> не задевающий соседние проекты VPS (см. ТЗ, §4.19).

## 1. Подготовка VPS

- Зафиксировать текущее состояние (`docker ps`, `docker network ls`, `ss -tulpn`,
  `df -h`, `free -h` → сохранить в `/root/vps-before-vuzfinder/`).
- Определить имя proxy-сети Nginx Proxy Manager: `docker network ls`.

## 2. Клонирование

```bash
mkdir -p /opt/university && cd /opt/university
git clone git@github.com:trinity3ru/choose_vuz.git .
```

## 3. Создание .env

```bash
cp .env.example .env
# заполнить POSTGRES_PASSWORD, PARSER_TRIGGER_TOKEN, TELEGRAM_*
```

## 4. Сборка контейнеров

```bash
cd /opt/university
docker compose build
```

## 5. Миграции

```bash
docker compose run --rm api alembic upgrade head
```

## 6. Запуск

```bash
docker compose up -d
```

## 7. Домен и Nginx Proxy Manager

- DNS: `A @`, `A www`, `A api` → IP VPS.
- Proxy Host: `vuzfinder.ru, www.vuzfinder.ru` → `university-frontend:3000`.
- Proxy Host: `api.vuzfinder.ru` → `university-api:8000`.
- SSL: Let's Encrypt, Force SSL, HTTP/2.

## 8. Ручной запуск парсера

```bash
cd /opt/university
docker compose exec -T api python -m app.cli enqueue spbstu   # поставить в очередь
docker compose exec -T worker python -m app.cli parse-university spbstu  # синхронно
```

## 9. Логи

```bash
docker compose logs -f api
docker compose logs -f worker
ls parser-logs/
```

## 10. Backup

```bash
bash scripts/backup-db.sh
```

## 11. Restore

```bash
bash scripts/restore-db.sh backups/university-YYYY-MM-DD-HHMMSS.sql
```

## 12. Обновление через git pull

```bash
cd /opt/university
git pull
docker compose build
docker compose run --rm api alembic upgrade head
docker compose up -d
```
