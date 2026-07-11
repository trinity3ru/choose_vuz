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

Архитектура прод-режима: лёгкий `api` (без Playwright) отвечает на HTTP и ставит
задания в очередь (`parser_runs`); отдельный `worker` (Playwright + Chromium) разбирает
очередь строго последовательно. Расписание — systemd-таймеры на хосте.

## Документация

- [DEPLOY.md](DEPLOY.md) — размещение и обновление на VPS.
- [DEPLOY_PLAN.md](DEPLOY_PLAN.md) — план доработки под VPS (чек-лист выполнения).
- [backend/README.md](backend/README.md) — устройство парсеров и API.
- [backend/Plan.md](backend/Plan.md) — история разработки парсеров по этапам.

## Локальная разработка

См. `start-dev.ps1` (Docker PostgreSQL + backend + frontend) и backend/README.md.
