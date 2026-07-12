#!/usr/bin/env bash
# Ежедневный backup PostgreSQL VuzFinder (ТЗ §17).
#
# Запуск из каталога проекта (вручную или таймером university-backup.timer):
#   bash scripts/backup-db.sh
#
# Дамп пишется в backups/university-ДАТА-ВРЕМЯ.sql.gz; копии старше
# BACKUP_RETENTION_DAYS (из .env, по умолчанию 14 дней) удаляются.
#
# Учётные данные БД не парсятся из .env: pg_dump выполняется внутри
# контейнера postgres и берёт POSTGRES_USER/POSTGRES_DB из его окружения.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

BACKUP_DIR="$PROJECT_DIR/backups"
mkdir -p "$BACKUP_DIR"

# Ретеншн из .env (строка вида BACKUP_RETENTION_DAYS=14), иначе 14.
RETENTION_DAYS=14
if [[ -f .env ]]; then
    from_env="$(grep -E '^BACKUP_RETENTION_DAYS=' .env | tail -1 | cut -d= -f2- | tr -d '[:space:]' || true)"
    [[ "$from_env" =~ ^[0-9]+$ ]] && RETENTION_DAYS="$from_env"
fi

STAMP="$(date +%F-%H%M%S)"
OUT="$BACKUP_DIR/university-$STAMP.sql.gz"

echo "Backup -> $OUT"
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
    | gzip > "$OUT"

# Пустой дамп — признак проблемы: не считаем такой backup успешным.
if [[ ! -s "$OUT" ]] || [[ "$(stat -c%s "$OUT" 2>/dev/null || stat -f%z "$OUT")" -lt 200 ]]; then
    echo "ОШИБКА: дамп пустой или подозрительно мал: $OUT" >&2
    rm -f "$OUT"
    exit 1
fi

echo "Размер: $(du -h "$OUT" | cut -f1)"

# Очистка старых копий.
deleted=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'university-*.sql*' \
    -mtime +"$RETENTION_DAYS" -print -delete | wc -l)
echo "Удалено старых копий (>${RETENTION_DAYS}д): $deleted"
echo "Готово."
