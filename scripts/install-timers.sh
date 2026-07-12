#!/usr/bin/env bash
# Установка systemd-таймеров VuzFinder (ТЗ §9): ночные слоты парсинга по вузам,
# recover зависших задач и почасовой health-check.
#
# Запуск на VPS от root из каталога проекта:
#   sudo bash scripts/install-timers.sh                  # слоты с 00:30 шагом 30 мин
#   sudo bash scripts/install-timers.sh --start 01:00 --step 20
#   sudo bash scripts/install-timers.sh --uninstall      # снять все таймеры
#
# Что делает:
# 1) копирует статические юниты из scripts/systemd/ в /etc/systemd/system/,
#    подставляя фактический каталог проекта вместо /opt/university;
# 2) генерирует по одному таймеру university-parser@<CODE>.timer на каждый
#    включённый вуз из backend/config.json, разнося их по ночным слотам
#    (ТЗ §9.1: 00:30 — вуз 1, 01:00 — вуз 2, ...);
# 3) systemctl daemon-reload + enable --now для всех таймеров.
#
# Тестовый прогон без systemd (генерация в каталог, без systemctl):
#   DRY_RUN=1 bash scripts/install-timers.sh

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_SRC="$PROJECT_DIR/scripts/systemd"
UNIT_DST="/etc/systemd/system"
START="00:30"
STEP_MIN=30
UNINSTALL=0

# Тестовый режим: юниты пишутся в локальный каталог, systemctl не вызывается.
if [[ "${DRY_RUN:-0}" == "1" ]]; then
    UNIT_DST="$PROJECT_DIR/.dry-run-units"
    rm -rf "$UNIT_DST" && mkdir -p "$UNIT_DST"
    systemctl() { echo "[dry-run] systemctl $*"; }
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --start) START="$2"; shift 2 ;;
        --step) STEP_MIN="$2"; shift 2 ;;
        --uninstall) UNINSTALL=1; shift ;;
        *) echo "Неизвестный аргумент: $1" >&2; exit 1 ;;
    esac
done

# Коды включённых вузов из config.json (порядок как в файле).
# PYTHON — переопределение интерпретатора (для локального dry-run на Windows).
codes=$(cd "$PROJECT_DIR" && "${PYTHON:-python3}" -c "
import json
cfg = json.load(open('backend/config.json', encoding='utf-8'))
print(' '.join(u['code'] for u in cfg['universities'] if u.get('enabled', True)))
")

if [[ "$UNINSTALL" == "1" ]]; then
    echo "Снимаю таймеры VuzFinder..."
    for code in $codes; do
        systemctl disable --now "university-parser@$code.timer" 2>/dev/null || true
        rm -f "$UNIT_DST/university-parser@$code.timer"
    done
    systemctl disable --now university-recover.timer university-health-check.timer 2>/dev/null || true
    rm -f "$UNIT_DST"/university-parser@.service \
          "$UNIT_DST"/university-recover.{service,timer} \
          "$UNIT_DST"/university-health-check.{service,timer}
    systemctl daemon-reload
    echo "Готово."
    exit 0
fi

# 1) Статические юниты (WorkingDirectory подставляется под фактический каталог).
for unit in "$UNIT_SRC"/*.service "$UNIT_SRC"/*.timer; do
    name="$(basename "$unit")"
    sed "s|/opt/university|$PROJECT_DIR|g" "$unit" > "$UNIT_DST/$name"
done

# 2) Пер-вузовые таймеры со сдвигом по слотам.
start_minutes=$(( 10#${START%%:*} * 60 + 10#${START##*:} ))
index=0
echo "Расписание ночных запусков (старт $START, шаг $STEP_MIN мин):"
for code in $codes; do
    total=$(( start_minutes + index * STEP_MIN ))
    hh=$(printf "%02d" $(( (total / 60) % 24 )))
    mm=$(printf "%02d" $(( total % 60 )))
    index=$(( index + 1 ))

    cat > "$UNIT_DST/university-parser@$code.timer" <<EOF
# Сгенерировано scripts/install-timers.sh — ночной слот вуза $code.
[Unit]
Description=VuzFinder: nightly parse of $code at $hh:$mm

[Timer]
OnCalendar=*-*-* $hh:$mm:00
Persistent=true

[Install]
WantedBy=timers.target
EOF
    echo "  $hh:$mm  $code"
done

# 3) Включение.
systemctl daemon-reload
for code in $codes; do
    systemctl enable --now "university-parser@$code.timer"
done
systemctl enable --now university-recover.timer university-health-check.timer

echo ""
systemctl list-timers 'university-*' --no-pager || true
echo "Готово: $(echo $codes | wc -w) вузов + recover + health-check."
