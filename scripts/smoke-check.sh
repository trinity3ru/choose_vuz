#!/usr/bin/env bash
# Smoke-check стека VuzFinder (DEPLOY_PLAN, этап 9.2).
#
# Запуск из каталога проекта (нужен заполненный .env):
#   bash scripts/smoke-check.sh
#
# Что проверяет:
# 1) образы собираются;
# 2) api-образ БЕЗ Playwright/Chromium (ТЗ §25.9-10), worker — с flock и CLI;
# 3) postgres поднимается (healthcheck), миграции применяются;
# 4) api отвечает: /health и /api/v1/parser/health;
# 5) frontend отвечает на :3000 изнутри proxy-сети.
#
# Стек остаётся запущенным (это штатное состояние после деплоя).

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

pass() { echo "  OK: $1"; }
fail() { echo "  FAIL: $1" >&2; exit 1; }

[[ -f .env ]] || fail "нет .env (скопируйте .env.example и заполните)"

echo "[1/6] Сборка образов..."
docker compose build --quiet
pass "docker compose build"

echo "[2/6] api-образ: без Playwright/Chromium..."
docker compose run --rm --no-deps api python -c "
import importlib.util, sys
assert importlib.util.find_spec('playwright') is None, 'playwright найден в api-образе'
assert importlib.util.find_spec('bs4') is None, 'bs4 найден в api-образе'
import app.main, app.cli
assert not [m for m in sys.modules if m.startswith('playwright')]
" >/dev/null || fail "api-образ содержит парсерные зависимости"
pass "api без Playwright; app.main и app.cli импортируются"

echo "[3/6] worker-образ: flock и CLI..."
docker compose run --rm --no-deps worker bash -c \
    "which flock >/dev/null && python -m app.cli --help >/dev/null" \
    || fail "worker: нет flock или не работает CLI"
pass "worker: flock и CLI на месте"

echo "[4/6] postgres + миграции..."
docker compose up -d postgres >/dev/null
docker compose run --rm api alembic upgrade head >/dev/null || fail "alembic upgrade head"
pass "миграции применены"

echo "[5/6] api: /health и /api/v1/parser/health..."
docker compose up -d api worker frontend >/dev/null
sleep 5
docker compose exec -T api python -c "
import urllib.request, json
h = json.load(urllib.request.urlopen('http://localhost:8000/health'))
assert h == {'status': 'ok'}, h
r = json.load(urllib.request.urlopen('http://localhost:8000/api/v1/parser/health'))
assert 'universities' in r and len(r['universities']) > 0, r
print('  вузов в health:', len(r['universities']))
" || fail "api не отвечает"
pass "api отвечает"

echo "[6/6] frontend: :3000 из proxy-сети..."
proxy_net="$(grep -E '^PROXY_NETWORK_NAME=' .env | tail -1 | cut -d= -f2- | tr -d '[:space:]')"
proxy_net="${proxy_net:-npm_default}"
code=$(docker run --rm --network "$proxy_net" curlimages/curl:8.10.1 \
    -s -o /dev/null -w '%{http_code}' http://university-frontend:3000/ || echo 000)
[[ "$code" == "200" ]] || fail "frontend вернул $code (ожидался 200)"
pass "frontend отдаёт 200 на university-frontend:3000"

echo ""
echo "Smoke-check пройден. Стек запущен:"
docker compose ps --format 'table {{.Name}}\t{{.Status}}'
