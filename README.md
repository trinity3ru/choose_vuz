# VuzFinder

Сервис мониторинга конкурсных списков российских вузов: парсеры собирают списки
абитуриентов с сайтов 13 вузов, сохраняют историю в PostgreSQL, дашборд показывает
динамику и позиции.

Продакшен: https://vuzfinder.ru (frontend) + https://api.vuzfinder.ru (API).

## Состав

| Каталог      | Что это |
|--------------|---------|
| `backend/`   | FastAPI API + парсеры + CLI worker (Python 3.11, SQLAlchemy async, Alembic) |
| `frontend/`  | Дашборд (Vite + React + Recharts), в проде — статика на :3000 |
| `docker/`    | Dockerfile'ы api / worker / frontend |
| `scripts/`   | Деплой, бэкапы, systemd-таймеры |
| `compose.yaml` | Docker Compose проекта `university` для VPS |

## Архитектура прод-режима

Лёгкий `api` (без Playwright) отвечает на HTTP и ставит задания в очередь
(таблица `parser_runs`); отдельный `worker` (Playwright + Chromium) разбирает
очередь строго последовательно под flock + advisory-lock. Расписание — systemd-таймеры
на хосте (ночные слоты по вузу, recover зависших задач, почасовой health-check,
ежедневный backup). Проблемы парсеров (failed/partial/0 записей/резкое падение/stale)
уходят алертами в Telegram.

Ключевые интерфейсы:

- `GET /api/v1/parser/health` — свежесть данных по каждому вузу (stale);
- `GET /api/v1/parser/runs` — история запусков с фильтрами;
- `POST /api/v1/parser/run/{code}` — ручной запуск (Bearer-токен);
- CLI (`python -m app.cli`): `enqueue`, `consume-queue`, `parse-university`,
  `parse-all`, `recover-stuck-runs`, `check-parser-health`, `cleanup-snapshots`.

## Документация

- [DEPLOY.md](DEPLOY.md) — размещение и обновление на VPS + чек-лист приёмки.
- [DEPLOY_PLAN.md](DEPLOY_PLAN.md) — план доработки под VPS (чек-лист выполнения).
- [backend/README.md](backend/README.md) — устройство парсеров и API.
- [backend/Plan.md](backend/Plan.md) — история разработки парсеров по этапам.

## Локальная разработка

`start-dev.ps1` поднимает Docker PostgreSQL, backend (uvicorn), окно worker
(`consume-queue` — как в проде) и frontend (Vite). Тесты: `cd backend && pytest`
(нужна тестовая БД, см. tests/conftest.py). Smoke контейнерного стека:
`bash scripts/smoke-check.sh` (нужен `.env`).
