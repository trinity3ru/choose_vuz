# План доработки VuzFinder под деплой на VPS Hostkey (v5)

Источник требований: `TZ_VuzFinder_VPS_Hostkey.md`.
Ветка работ: `vps-deploy` (репозиторий `choose_vuz`, `main` не трогаем до мержа).

## Контекст и решения (зафиксировано)

- **Репозиторий:** существующий `choose_vuz`. В гите — только `backend/` + `frontend/`; это уже
  монорепо, deploy-файлы кладём в корень. Отдельный `vuzfinder/` не создаём.
- **Не входит в деплой:** `выбор-вуза-рф/`, `анализатор_списков_поступающих_спбпу/` (untracked → в `.gitignore`).
- **Frontend:** Vite + React SPA; в проде — статика через `nginx:alpine` (`listen 3000`, SPA-fallback).
  Базовый URL API — build-time `VITE_API_URL`. На Next.js не мигрируем.
- **Деплой на сервере (этап 11)** требует SSH к VPS.

---

## Разрешённые уточнения

### Раунд A (v2)
1. **Очередь замкнута** — worker = постоянный `consume-queue` с атомарным захватом
   (`FOR UPDATE SKIP LOCKED`), `PARSER_CONCURRENCY=1`. Источники: API `/parser/run` и systemd
   → `enqueue` (только БД). enqueue дедуплицирует (`queued`/`running`).
2. **Разрыв API → Playwright** — раздельные requirements; тонкий `queue.py` без импорта парсеров;
   `app.main`/`app.api.*` не импортируют парсеры.
3. **`parser_type` обязателен** — `Literal["http","playwright"]`; playwright только у SPBSTU/SUT.
4. **Снимок → вуз** — `parse_snapshots.university_id` (FK) + `parser_run_id` (FK).
5. **`records_changed`** — `added+removed+modified` относительно последнего успешного снимка вуза.

### Раунд B (v3)
6. **HTTP-парсеры → httpx (СЕЙЧАС, отдельный ранний этап).** 11 из 13 парсеров переводим с
   `playwright.request` на `httpx`; Playwright остаётся только у **СПбПУ** и **СПбГУТ**.
   Каждый переведённый парсер — с тестом/фикстурой (сохранённый HTML/JSON/xlsx). http-парсеры
   не импортируют `playwright`. Это снижает риск и потребление worker'а и позволяет позже
   разнести лёгкие HTTP-запуски и тяжёлые браузерные.
7. **Ключ `records_changed` = `(major_id, applicant_code)`**, а не только `applicant_code`
   (один абитуриент подаёт на несколько направлений одного вуза → иначе ложные add/remove/modify).
   `modified` по `{total_score, priority, has_agreement, review_status}`. Нет предыдущего успешного
   снимка → `records_changed = NULL`.
8. **Обработка «зависших» задач.** Команда `recover-stuck-runs`: помечает `running`-задачи старше
   `PARSER_STUCK_MINUTES` как `failed` (`error_message="worker interrupted"`) и шлёт уведомление.
   Вызывается при старте consumer и отдельным systemd-таймером. Снимает блокировку дедупликации
   после падения worker'а.
9. **`flock` оставляем вместе с advisory-lock.** Критерий приёмки ТЗ §25.25 буквально требует
   `flock`. Consumer запускаем через обёртку с `flock` (единственный consumer), а advisory-lock
   PostgreSQL — вторая защита (в т.ч. для ручного `parse-university`). Формальное ТЗ + надёжность.
10. **Frontend-этап возвращён.** `frontend/src/api.ts` (`BASE="/api/v1/data"` жёстко) → база из
    `VITE_API_URL` (в dev — пустая, работает Vite-прокси). Плюс: prod-CORS только для
    `https://vuzfinder.ru` и `https://www.vuzfinder.ru`; показ свежести/устаревания из
    `/parser/health`; понятное состояние «API временно недоступно».
11. **`ON DELETE SET NULL` для `parse_snapshots.parser_run_id`** — cleanup снимков и retention
    запусков независимы: удаление снимка не трогает историю `parser_runs`, удаление запуска
    обнуляет ссылку у снимка, а не каскадит.

### Раунд C (v4)
12. **Миграция старых `parse_snapshots` (явное правило).** `university_id NOT NULL` нельзя
    гарантированно заполнить у старых полностью неудачных снимков (нет ни заявлений, ни MajorStats).
    В миграции: backfill через `Applicant → Major → University`; при отсутствии заявлений —
    через `MajorStats → Major → University`; оставшиеся неатрибутируемые legacy-снимки **удалить**
    перед установкой `NOT NULL` (данные пока dev-объёма) — зафиксировать как отдельный техшаг.
13. **Отдельная проверка stale.** `recover-stuck-runs` обслуживает только зависшие `running`.
    Stale-алерт нужен и когда таймеры не сработали или worker вообще не стартовал. Команда
    `check-parser-health` (stale по `PARSER_STALE_HOURS`) + почасовой systemd-таймер → Telegram.
14. **Порог «резкого падения записей».** `PARSER_RECORDS_DROP_PERCENT=50`: алерт, если
    `records_saved` упал на ≥ порога относительно последнего успешного запуска вуза; для первого
    запуска сравнения нет.
15. **Готовность Docker-сервисов.** В `compose.yaml` — `healthcheck` для PostgreSQL и
    `depends_on: { postgres: { condition: service_healthy } }` для `api` и `worker`.
    В worker-образе явно установить `flock` (пакет `util-linux`), не полагаясь на базовый образ.

### Раунд D (v5)
16. **Общий lock-файл для `flock`.** Lock внутри одного worker-контейнера не защитит от случайно
    поднятого второго контейнера. Используем общий lock-файл на хосте: bind mount
    `./locks:/var/lock/university`, `flock` берёт `/var/lock/university/parser.lock`. Advisory-lock
    PostgreSQL остаётся второй защитой.
17. **DB-only CLI-команды выполняются через `api`-контейнер, а не worker.** `enqueue`,
    `recover-stuck-runs`, `check-parser-health`, `cleanup-snapshots` — только БД (+Telegram), без
    Playwright. systemd-таймеры вызывают их через `docker compose exec -T api python -m app.cli ...`,
    чтобы stale/recover-уведомления приходили **даже при неработающем worker**. Требование к коду:
    в `app/cli.py` импорт парсеров (`parser_runner`/`app.parser.*`) — **ленивый**, внутри команд
    `consume-queue`/`parse-*`, чтобы `app.cli` был import-safe в api-образе (без Playwright).

---

## Этап 0. Каркас деплоя

- [x] 0.1. Ветка `vps-deploy` от `main`.
- [x] 0.2. Усилить корневой `.gitignore`: `.env`, `**/.venv/`, `**/node_modules/`, `*.zip`,
  `*.pdf`, `parser-logs/`, `parser-screenshots/`, `backups/`, `postgres-data/`, `locks/`,
  `выбор-вуза-рф/`, `анализатор_списков_поступающих_спбпу/`,
  `backend/*_sample.json`, `backend/scripts/*.html`, `backend/itmo_api.json`.
- [x] 0.3. Заготовки: `.env.example`, `DEPLOY.md` (скелет), корневой `README.md`
  (`docker/`, `scripts/`, `compose.yaml` появятся на этапах 5–7 вместе с содержимым).

## Этап 1. Рефактор HTTP-парсеров на httpx (ранний, с фикстурами)

- [x] 1.1. `app/parser/http_base.py`: класс `HttpParser` (клиент httpx, общий цикл направлений,
  `_prepare`/`_parse_major`, `compute_status`); `base.py` Playwright не импортирует.
- [x] 1.2. Переведены 11 парсеров с `playwright.request` на `httpx`: ITMO, SAMARA, SAMGTU, SPBGU,
  TLTSU (таймаут 120с, свой `_parse_all`), LETI, MPEI, SPBAU (xlsx, свой `_parse_all`),
  KPFU (cp1251), GUAP, SPMI (кэш по specialization_id). Логика «общий конкурс» сохранена.
- [x] 1.3. Playwright остался только у SPBSTU и SUT (реальная браузерная сессия/cookies).
- [x] 1.4. `backend/tests/test_http_parsers.py`: фикстуры на каждый из 11 парсеров (HTML/JSON/xlsx
  по реальной разметке) + тесты partial/failed поведения базы. 15 тестов зелёные.
- [x] 1.5. `backend/tests/test_import_hygiene.py`: subprocess-тест — импорт 11 http-парсеров
  не загружает `playwright`; spbstu/sut импортируются.

## Этап 2. Backend: очередь, CLI, разрыв импортов, зависимости

- [x] 2.1. `app/services/queue.py` — enqueue/claim/finalize/recover по `parser_runs` (только БД):
  дедуп; атомарный claim (`FOR UPDATE SKIP LOCKED`); пометка «зависших»; advisory-lock хелперы.
- [x] 2.2. `app/cli.py`: `parse-all`, `parse-university <code>`, `enqueue <code>`, `consume-queue`
  (`--once`; recover при старте; graceful SIGTERM), `recover-stuck-runs`, `check-parser-health`,
  `cleanup-snapshots`. Коды выхода `0/1/2`. Регистронезависимый код. Ленивый импорт парсеров.
- [x] 2.3. Разрыв импортов: `parser_routes` ставит задания через `queue` (`/parser/start` →
  enqueue всех включённых или одного, дубликаты в skipped); `scheduler/jobs.py` тоже enqueue;
  тест: `app.main`/`app.cli`/`queue`/`jobs`/`routes` не тянут playwright/bs4/openpyxl/app.parser.
- [x] 2.4. Зависимости разделены: `requirements-base.txt`, `requirements-api.txt`
  (+fastapi/uvicorn/apscheduler), `requirements-worker.txt` (+playwright/bs4/openpyxl),
  `requirements.txt` = api+worker (локальная разработка), `requirements-dev.txt` (+pytest).
- [x] 2.5. APScheduler в проде off: старт только при `ENABLE_SCHEDULER=true` (default false).
- [x] 2.6. `parser_type: Literal["http","playwright"]` — обязательное поле схемы; проставлен в
  `config.json` (SPBSTU/SUT → playwright, остальные 11 → http).
- [x] 2.7. (из этапа 3, досрочно) Модель `app/models/parser_run.py` + миграция `b7c2d9e41a05`
  (`parser_runs` + индексы). Статусы: queued/running/success/partial/failed/skipped.
- [x] 2.8. `start-dev.ps1`: отдельное окно worker (`consume-queue`) — dev повторяет прод.
- [x] 2.9. Тесты `tests/test_queue.py` против тестовой PostgreSQL (очередь/дедуп/FIFO/finalize/
  recover/advisory-lock/CLI) — суммарно 30 passed. Живой smoke на dev-БД: `enqueue itmo` →
  `consume-queue --once` → реальный парсинг ИТМО (4 направления, success) → health: ITMO fresh.

## Этап 3. БД: `parser_runs`, ссылки снимка, retention

- [x] 3.1. Модель `parser_run.py` (ТЗ §11) — сделана на этапе 2 (п. 2.7).
- [x] 3.2. Миграция `c4f1a8d27b93`: `parse_snapshots.parser_run_id` (FK, **ON DELETE SET NULL**);
  `parse_snapshots.university_id` (FK CASCADE, index) с явным backfill:
  (1) `Applicant → Major → University`; (2) `MajorStats → Major → University`;
  (3) неатрибутируемые legacy-снимки удаляются; затем `NOT NULL`.
  Применена к dev-БД: все 131 снимка атрибутированы по 13 вузам, удалений 0.
- [x] 3.3. `storage.save_parse_result(university, result, parser_run_id=None)` проставляет
  `university_id` + `parser_run_id`; `parser_runner.run_university` прокидывает id запуска.
- [x] 3.4. `app/services/changes.py::compute_records_changed`: ключ `(major_id, applicant_code)`;
  `added+removed+modified` (поля `{total_score, priority, has_agreement, review_status}`) vs
  последнего `success`-снимка вуза; нет предыдущего → `NULL`. Считается в CLI (`_execute_run`)
  до финализации; ошибки метрики не роняют запуск.
- [x] 3.5. `cleanup-snapshots`: retention независимы — подтверждено тестом (снимок удалён,
  parser_runs целы; `parser_run_id` у снимков остальных запусков обнуляется только при
  удалении самого запуска).
- [x] 3.6. Тесты `tests/test_snapshots.py` (6 шт.): ссылки снимка, семантика records_changed
  (added/removed/modified, ключ по направлению, сравнение только с success), retention.
  Суммарно 36 passed. Живой E2E: повторный парсинг ИТМО → records_changed=11,
  снимок связан с запуском (snapshot_linked=true).

## Этап 4. Health-API (без импорта парсеров)

- [x] 4.1. `GET /api/v1/parser/health` — по вузу: `last_success_at`, `last_run_status`, `age_hours`,
  `is_stale` (`PARSER_STALE_HOURS`), `records_found/saved`, `last_error`. Логика вынесена в общий
  `app/services/health.py` — его же использует CLI `check-parser-health` (systemd-таймер).
- [x] 4.2. `GET /api/v1/parser/runs` — фильтры `limit/offset/university_code/status/date_from/date_to`,
  `total` для пагинации, новые сверху.
- [x] 4.3. `POST /api/v1/parser/run/{code}` — Bearer `PARSER_TRIGGER_TOKEN`: без токена `401`,
  неверный `403`, успех `202` (enqueue, дубликат → `already_queued`), неизвестный вуз `404`,
  токен не настроен → `503`.
- [x] 4.4. `/parser/start`, `/parser/status` помечены `deprecated=True` (OpenAPI) с указанием замены.
- [x] 4.5. Тесты `tests/test_api.py` (10 шт., httpx.ASGITransport + тестовая PostgreSQL):
  stale/fresh/старый success/failed с ошибкой; фильтры и пагинация runs; матрица токена
  401/403/404/202/дедуп/503. Суммарно 46 passed. Живой smoke uvicorn на dev-БД:
  health отдаёт 13 вузов, runs показывает records_changed=11, матрица POST подтверждена curl.

## Этап 5. Frontend (Vite SPA)

- [x] 5.1. `frontend/src/api.ts`: база из `VITE_API_URL` (в dev пусто — Vite-прокси, в prod —
  `https://api.vuzfinder.ru`); `vite-env.d.ts` с типизацией. Инъекция проверена по бандлу.
- [x] 5.2. `hooks/useParserHealth.ts` + бейдж свежести в шапке по выбранному вузу:
  «Обновлено N ч назад» (зелёный) / «⚠ …» (stale, оранжевый) / «Данные ещё не собирались».
  Ошибка health некритична — бейдж просто скрывается.
- [x] 5.3. `ApiUnavailableError` (сетевые ошибки + 5xx) → экран «API временно недоступно»
  с кнопкой «Повторить» на обоих уровнях: список вузов (App) и заявления (useApplicantData.retry).
- [x] 5.4. Prod-CORS через env: `CORS_ORIGINS=https://vuzfinder.ru,https://www.vuzfinder.ru`
  в корневом `.env.example`; main.py использует `settings.cors_origins_list` (без изменений кода).
- [x] 5.5. Сборка: `tsc -b && vite build` чистые; строки новых экранов и prod-URL
  подтверждены в собранном бандле.

## Этап 6. Docker: три образа + compose

- [x] 6.1. `docker/api.Dockerfile` — `python:3.11-slim`, `requirements-api.txt`, без Chromium,
  non-root `apiuser`; uvicorn:8000. Проверено: playwright в образе отсутствует, alembic на месте.
- [x] 6.2. `docker/worker.Dockerfile` — база `mcr.microsoft.com/playwright/python:v1.49.1-noble`,
  `requirements-worker.txt`; `util-linux` (flock) установлен явно; команда:
  `flock -n /var/lock/university/parser.lock python -m app.cli consume-queue`
  (lock на bind-mounted `./locks:/var/lock/university`). Для Chromium под root добавлена
  настройка `BROWSER_NO_SANDBOX` (spbstu/sut передают `chromium_sandbox=False`);
  запуск браузера в контейнере проверен.
- [x] 6.3. `docker/frontend.Dockerfile` (node:22 build → nginx:alpine) + `docker/frontend/nginx.conf`
  (`listen 3000`, SPA-fallback, gzip, кэш assets); `VITE_API_URL` — build-arg. Проверено:
  GET / и SPA-роут → 200, prod-URL вшит в бандл.
- [x] 6.4. `compose.yaml` (`name: university`): `container_name` `university-*`; сети `proxy`
  (external, имя из `PROXY_NETWORK_NAME`) + `university_internal` (internal). Отклонение от
  эскиза ТЗ: worker дополнительно в `university_egress` (обычный bridge) — ему нужен ИСХОДЯЩИЙ
  доступ к сайтам вузов, а `internal: true` режет весь трафик; входящих портов у worker нет,
  из интернета он недоступен. Postgres — только internal. Портов наружу нет.
  `healthcheck` postgres (`pg_isready`) + `depends_on: service_healthy` для api/worker.
- [x] 6.5. Лимиты (ТЗ §18: 3g/2.5+shm1g, 1.5g/1.0, 700m/0.75×2) и ротация логов
  (`json-file` 20m×5 через YAML-якорь); volumes `postgres-data`, `./parser-logs`,
  `./parser-screenshots`, `./locks`. Добавлен `.dockerignore` (контекст — корень репо).
- [x] 6.6. Живой прогон полного стека локально (сеть `npm_default` создана как на VPS):
  `compose up -d --build` → postgres healthy → `compose run --rm api alembic upgrade head`
  (3 миграции) → POST `/parser/run/itmo` с токеном (202) → worker-контейнер спарсил ИТМО
  (4143 записи, success) → health: ITMO FRESH. Доступность по именам контейнеров из
  proxy-сети (как будет ходить NPM): `university-frontend:3000` → 200,
  `university-api:8000/health` → 200. Стек снят `compose down -v` (только `university_*`).

## Этап 7. Расписание (systemd) + flock

- [x] 7.1. `scripts/systemd/university-parser@.service` (oneshot,
  `ExecStart=docker compose exec -T api python -m app.cli enqueue %i`) + `scripts/install-timers.sh`:
  генерирует per-code `@.timer` из `config.json` (сдвиг 00:30/шаг 30 мин, флаги `--start/--step`,
  `--uninstall`, `Persistent=true`); подставляет фактический каталог проекта в юниты.
  Dry-run проверен: 13 слотов 00:30→06:30 точно по ТЗ §9.1, переход через полночь корректен.
- [x] 7.2. `university-recover.service`/`.timer` — `recover-stuck-runs` каждые 15 минут через
  `api`-контейнер; recover также выполняется при старте consumer (этап 2).
- [x] 7.3. `university-health-check.service`/`.timer` — почасовой `check-parser-health` (в :05)
  через `api`-контейнер → stale-алерт придёт даже при мёртвом worker. `SuccessExitStatus=0 2`
  (exit 2 «есть stale» — отчёт, не сбой юнита).
- [x] 7.4. Защита от параллельного парсинга (готово на этапах 2/6): flock на общем lock-файле
  хоста (`./locks:/var/lock/university`) — команда worker-контейнера; advisory-lock PostgreSQL —
  вторая защита (consume-queue и ручной `parse-university`). `PARSER_CONCURRENCY=1` обеспечен
  конструктивно: единственный consumer разбирает очередь строго последовательно.

## Этап 8. Telegram-алерты + бэкапы

- [x] 8.1. `app/services/notifications.py` (DB-only, httpx): события `failed`, `partial`,
  `records=0`, «резкое падение» (≥ `PARSER_RECORDS_DROP_PERCENT` от последнего успешного
  запуска; без базы сравнения — тихо), `worker interrupted`, сводный stale-алерт.
  Настройки `TELEGRAM_*` добавлены в Settings. Вызовы: `_execute_run` (после finalize),
  `recover-stuck-runs` + старт consumer, `check-parser-health`. Все отправки best-effort —
  ошибки алертов никогда не роняют парсинг. Тесты: 10 сценариев (56 passed суммарно).
- [x] 8.2. `scripts/backup-db.sh`: `pg_dump` внутри postgres-контейнера (креды из окружения
  контейнера, .env не парсится) → `backups/university-<штамп>.sql.gz`; защита от пустого
  дампа; ретеншн `find -mtime +N -delete` (`BACKUP_RETENTION_DAYS`, default 14).
  `scripts/restore-db.sh <файл> [--yes]`: пересоздание схемы public + восстановление
  (.sql и .sql.gz), подтверждение обязательно. `university-backup.{service,timer}` —
  ежедневно в 07:30 (после ночных парсеров); включён в `install-timers.sh` (install/uninstall).
  Живой roundtrip на compose-postgres: seed → backup (gz) → DROP TABLE → restore →
  данные вернулись («42 | до бэкапа»).

## Этап 9. Тесты и smoke-check

- [x] 9.1. `backend/tests/` — 56 тестов против тестовой PostgreSQL, накоплены по этапам:
  парсер-фикстуры 11 вузов (этап 1), очередь/CLI/advisory-lock (этап 2), снимки и
  records_changed (этап 3), health-API и токен (этап 4), алерты (этап 8), import-гигиена.
- [x] 9.2. `scripts/smoke-check.sh` (6 шагов): build → api-образ без playwright/bs4 +
  импорт app.main/app.cli → worker: flock+CLI → postgres healthy + `alembic upgrade head`
  → `/health` и `/api/v1/parser/health` (13 вузов) → frontend :3000 из proxy-сети.
  Живой прогон пройден полностью; стек остаётся запущенным (штатное послед деплоя состояние).

## Этап 10. Конфиги и документация

- [x] 10.1. `.env.example` полный: ТЗ §19 + `PROXY_NETWORK_NAME`, `VITE_API_URL`,
  `QUEUE_POLL_SECONDS`, `PARSER_STUCK_MINUTES`, `PARSER_RECORDS_DROP_PERCENT`,
  `ENABLE_SCHEDULER` (MIGRATION_DATABASE_URL помечен как зарезервированный —
  Alembic использует DATABASE_URL).
- [x] 10.2. `DEPLOY.md` полный: 12 разделов ТЗ §22 (подготовка VPS → git pull-обновление),
  systemd-таймеры, smoke-check, раздел «Что запрещено» (ТЗ §4.13), чек-лист приёмки
  ТЗ §25 (25 пунктов). Корневой `README.md` (архитектура, интерфейсы, dev) и
  `backend/README.md` (очередь вместо 409, health-API, CLI, parser_type, структура)
  актуализированы.

## Этап 11. Деплой на сервере — ВЫПОЛНЕН 2026-07-12 ✅

- [x] 11.1. `/opt/university`, `git clone -b vps-deploy`, `.env` (диагностика VPS сохранена
  в `/root/vps-before-vuzfinder/`). Открытие: NPM на этом VPS в `network_mode: host` →
  добавлен `compose.override.yaml` (loopback-порты 127.0.0.1:8086/8087, раунд-фикс `a8be832`).
- [x] 11.2. `build` → том postgres пересоздан (пароль в томе «замораживается» при initdb;
  плюс fix `64090af`: `%` в пароле ломал configparser в alembic/env.py) → 3 миграции → `up -d`.
  `smoke-check.sh` — 6/6 на VPS.
- [x] 11.3. DNS `@/www/api` → IP VPS; Proxy Host'ы NPM: vuzfinder.ru→127.0.0.1:8086,
  api.vuzfinder.ru→127.0.0.1:8087; SSL Let's Encrypt + Force SSL + HTTP/2. HTTPS 200.
- [x] 11.4. `install-timers.sh` установлен (13 слотов + recover + health + backup);
  пробный `backup-db.sh` создан; соседние проекты живы (docker stats — норма, swap не тронут).
- [x] 11.5. Первый полный прогон: все 13 вузов success (~130 тыс. записей; СПбПУ 76277).
  Полевые фиксы по итогам: `75f4d67` — из конфига SPBSTU убраны 4 кода, отсутствующие
  на сайте (63/63 → success); `c14fe62` — у lk.samgtu.ru истёк TLS-сертификат
  (12.07 09:18 UTC), для SAMGTU временно `verify_ssl=False` (TODO: вернуть после
  обновления сертификата вузом).

---

## Порядок и безопасность

- Этапы 1–10 — только локально в ветке `vps-deploy`, коммитим по этапам.
- Этап 1 (httpx) — первый содержательный: даёт чистое разделение http/playwright, на которое
  опираются образы, лимиты и parser_type.
- Ничего на сервере не выполняем до согласования (этап 11).
- Принцип ТЗ §27: падение/зависание Playwright в worker не роняет frontend, API, NPM и соседние
  проекты VPS.
