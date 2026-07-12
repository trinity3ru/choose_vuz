#!/usr/bin/env bash
# Восстановление PostgreSQL VuzFinder из бэкапа (ТЗ §17, §22.11).
#
#   bash scripts/restore-db.sh backups/university-2026-07-12-073000.sql.gz
#   bash scripts/restore-db.sh backups/university-....sql --yes   # без вопроса
#
# ВНИМАНИЕ: восстановление ПОЛНОСТЬЮ ЗАМЕНЯЕТ текущие данные проекта
# (schema public пересоздаётся). Другие базы/проекты VPS не затрагиваются.
# Перед восстановлением остановите worker, чтобы он не писал в базу:
#   docker compose stop worker    (после восстановления: docker compose start worker)

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

BACKUP_FILE="${1:-}"
CONFIRM="${2:-}"

if [[ -z "$BACKUP_FILE" ]]; then
    echo "Использование: bash scripts/restore-db.sh <backups/university-...sql[.gz]> [--yes]" >&2
    exit 1
fi
if [[ ! -f "$BACKUP_FILE" ]]; then
    echo "Файл не найден: $BACKUP_FILE" >&2
    exit 1
fi

if [[ "$CONFIRM" != "--yes" ]]; then
    echo "Восстановление ЗАМЕНИТ все текущие данные БД проекта university."
    read -r -p "Продолжить? [yes/NO] " answer
    [[ "$answer" == "yes" ]] || { echo "Отменено."; exit 1; }
fi

echo "Пересоздаю схему public..."
docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"'

echo "Восстанавливаю из $BACKUP_FILE ..."
case "$BACKUP_FILE" in
    *.gz) gunzip -c "$BACKUP_FILE" ;;
    *)    cat "$BACKUP_FILE" ;;
esac | docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q -v ON_ERROR_STOP=1'

echo "Проверка: список таблиц"
docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt"'
echo "Готово."
