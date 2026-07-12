# Бэкенд парсера конкурсных списков вузов

Сервис на FastAPI, который собирает конкурсные списки абитуриентов с сайтов вузов
(на данный момент — 13 вузов), сохраняет их в PostgreSQL с историей (снимками)
и отдаёт API для управления парсером.

Подробности: [Plan.md](Plan.md), спецификации в [specs/](specs/).

## Технологии

- FastAPI — веб-сервис и API управления
- Playwright — получение браузерной сессии сайта вуза
- PostgreSQL + SQLAlchemy (async) + Alembic — хранение и миграции
- APScheduler — периодический запуск парсинга
- Pydantic — валидация конфига и данных

## Поддерживаемые вузы

- **СПбПУ** (`SPBSTU`) — `my.spbstu.ru`, данные приходят в формате JSON.
- **СПбГУТ** (`SUT`) — `priem.sut.ru`, данные приходят в формате HTML (разбор через BeautifulSoup).
- **Самарский университет** (`SAMARA`) — `priemsamara.ru`, готовый server-rendered HTML,
  открывается по прямому `pk` без JS и cookie (парсим категорию «Общий конкурс»).
- **Самарский политех / СамГТУ** (`SAMGTU`) — `samgtu.ru` (Angular), данные из JSON-API
  `lk.samgtu.ru` (парсим категорию «Основные места в рамках КЦП»).
- **СПбГУ** (`SPBGU`) — `enrollelists.spbu.ru` (Vue), данные из JSON-API
  `/api/reports/priem-list-02/data` (ответ — HTML-блок, парсим BeautifulSoup).
- **ТГУ, Тольятти** (`TLTSU`) — `edu.tltsu.ru` (BIRT-отчёт), режим `preview` отдаёт
  готовый HTML (парсим BeautifulSoup, берём «Основные места (бюджет)»).
- **ЛЭТИ / СПбГЭТУ** (`LETI`) — `lists.priem.etu.ru`, GET `list.html?id=UUID`
  (HTML таблицы, берём «Основные места»).
- **МЭИ** (`MPEI`) — `pk.mpei.ru/info/entrants_listN.html`, готовый server-rendered HTML
  (таблица «По конкурсу», общий бюджетный конкурс; `external_id` = имя файла страницы).
- **ИТМО** (`ITMO`) — `abit.itmo.ru` (Next.js, SSR): данные встроены в страницу внутри
  `<script id="__NEXT_DATA__">` как JSON. Браузер не нужен; `external_id` = `competitive_group_id`.
- **Алферовский университет / СПбАУ** (`SPBAU`) — `spbau.ru`, списки публикуются только
  в виде xlsx (разбор через openpyxl; берём «Общий конкурс», очная, бюджет).
- **КФУ** (`KPFU`) — `kpfu.ru` через iframe `abiturient.kpfu.ru`, фильтры задаются
  GET-параметрами (без AJAX), HTML разбирается BeautifulSoup; `external_id` = id института.
- **ГУАП** (`GUAP`) — `priem.guap.ru`, server-rendered HTML: сводная таблица направлений +
  отдельная страница-список на каждую программу (`.pk-ratings-table`).
- **Санкт-Петербургский горный университет** (`SPMI`) — `priem2026.spmi.ru`,
  server-rendered HTML (BeautifulSoup); `external_id` = `specialization_id` укрупнённой программы.
- **НИУ ВШЭ, Москва и Санкт-Петербург** (`HSE_MSK`, `HSE_SPB`) — `pk.hse.ru`,
  JSON-API Angular-приложения; кампусы заведены как два вуза с общим классом парсера,
  принадлежность кампусу проверяется по полю `filial` заголовка группы;
  `external_id` = оба UUID из URL списка через `/`.

Каждый вуз — отдельный класс-наследник `BaseParser`. Чтобы добавить новый вуз,
нужно написать класс парсера и внести его в реестр `PARSER_REGISTRY`
(в `app/services/parser_runner.py`), а также добавить вуз в `config.json`.

## Как устроен парсер СПбПУ

Страница `my.spbstu.ru/.../list-applicants/bachelor` подгружает данные тремя AJAX-запросами.
Парсер открывает страницу через Playwright один раз (получает cookies), а дальше
забирает готовый JSON прямыми запросами через контекст браузера — без эмуляции кликов:

- `POST /home/get-code-list` — список направлений (id + название)
- `GET  /home/get-abit-list` — строки таблицы абитуриентов
- `POST /home/get-direction-info` — сводка (места, заявления, согласия)

## Как устроен парсер СПбГУТ

Страница `priem.sut.ru/spisok-abiturientov` работает иначе:

- `POST /new_site/inc/ajax_abitur_2025.php` (`action=get_spec`) — список конкурсных групп
  (аналог направлений), приходит JSON с HTML-опциями.
- `POST /spisok-abiturientov` (`action=get_result_new` + скрытый token) — таблица результатов,
  приходит как HTML целой страницы; парсер выбирает строки `tr[id^=tr_11_]` через BeautifulSoup.

## Как устроен парсер Самарского университета

Страница `priemsamara.ru/ratings/?pk=N&pay=budget&filter=all` — обычный HTML с готовой
таблицей (ни JS, ни cookie не нужны), поэтому парсер делает простой HTTP GET через
HTTP-клиент Playwright (`playwright.request`, без запуска браузера) и разбирает разметку
BeautifulSoup. `pk` каждого направления задаётся в конфиге в поле `external_id`.

- Бюджетный список разбит на таблицы-категории (`bak_table_idN`): квоты и «Общий конкурс».
  Парсер выбирает таблицу с заголовком «Общий конкурс».
- Число колонок-предметов меняется по направлениям, поэтому значения читаются по устойчивым
  крайним колонкам (первые 3 слева, последние 6 справа).

## Как устроен парсер СамГТУ (Самарский политех)

Страница `samgtu.ru/admission/competetivegroup` — Angular-приложение; URL при клике не
меняется, данные берутся из двух JSON-эндпоинтов ЛК (обычный GET, без cookie/CSRF), поэтому
браузер не нужен — используется HTTP-клиент Playwright:

- `GET lk.samgtu.ru/publics/competetivegroup/kcps` — список конкурсных групп
  (id, название «код + направление», форма, вуз/филиал, места, заявления).
- `GET lk.samgtu.ru/publics/competetivegroup/rating?id=<CGID>` — строки абитуриентов группы.

Направление сопоставляется с группой по коду в рантайме (очная форма, головной вуз,
`PlaceTypeID=1` — «Основные места в рамках КЦП»), из строк рейтинга берутся только записи
той же категории.

## Как устроен парсер СПбГУ

Страница `enrollelists.spbu.ru/reports/PriemList02.php` — Vue-приложение; строки грузятся
AJAX. Браузер не нужен (обычные GET/POST без cookie), используется HTTP-клиент Playwright:

- Базовая страница (очная + Бюджет) содержит встроенный JSON `#priem-list-02-report-meta`
  с `id` отчёта, `report_upload_id` и списком направлений (`specialities`) с их UUID.
- `POST /api/reports/priem-list-02/data` с телом
  `{report_priem_list_02_id, speciality_ids:[UUID], filters}` возвращает `{blocks:[{html}]}` —
  готовый HTML таблицы, который парсится BeautifulSoup.

Направление сопоставляется по коду. Если под кодом несколько образовательных программ
(напр. 03.03.01, 09.03.03), парсятся все программы и объединяются в один список.

## Как устроен парсер ТГУ (Тольятти)

Списки — BIRT-отчёт. Интерактивный режим `run` отдаёт AJAX-оболочку, поэтому используется
режим `preview` — он возвращает готовый HTML целиком (обычный GET, без браузера; ответ
тяжёлый ~1.5 МБ и медленный, таймаут увеличен до 120 c).

- Один параметр `dep` (институт) содержит сразу несколько направлений/программ.
- Отчёт разбирается целиком: по div.style_7 определяется текущее направление (по коду) и
  категория; берутся строки только категории «Основные места … (бюджет)».
- Число колонок-предметов меняется, поэтому используются устойчивые крайние колонки
  (слева 8, справа 3). Согласие выражается значением «Электронное».

## Как устроен парсер ЛЭТИ

Страница abit.etu.ru встраивает виджет со `lists.priem.etu.ru`. Данные — обычный GET:

- `GET lists.priem.etu.ru/public/list.html?id=<UUID>` — HTML таблицы абитуриентов.

UUID списка задаётся в конфиге через `external_id` (из параметра `id` в URL направления).
Берём только строки с условием «Основные места» (общий бюджетный конкурс).
Согласие: «Электронное» = есть. Браузер не нужен.

## Как устроен парсер МЭИ

Каждое направление публикуется на отдельной странице `pk.mpei.ru/info/entrants_listN.html`:

- `GET pk.mpei.ru/info/<external_id>` — HTML с таблицей «По конкурсу» (общий бюджет).

Имя файла страницы задаётся в конфиге через `external_id` (например `entrants_list16.html`).
Строки таблицы: `tr[id^=p]`, 15 колонок. Места — из текста «Количество вакантных мест: N».
Согласие: «да» = есть. Браузер не нужен (HTTP-клиент Playwright + BeautifulSoup).

## Как устроен парсер ИТМО

Сайт `abit.itmo.ru` — приложение на Next.js с server-side rendering: данные списка
встроены прямо в HTML внутри тега `<script id="__NEXT_DATA__">` (JSON). Поэтому браузер
и выполнение JS не нужны — обычный GET через HTTP-клиент Playwright.

- Направление открывается по прямому `competitive_group_id` из конфига (`external_id`),
  URL строится как `{university.url}/{external_id}`
  (например `https://abit.itmo.ru/rating/bachelor/budget/2342`).
- Нужен браузерный `User-Agent`, иначе сайт может отдать заглушку.

## Как устроен парсер СПбАУ (Алферовский университет)

Списки публикуются только как xlsx-файл на странице `/campaign/bachelor/documents`.

- Парсер находит ссылку на актуальный xlsx на странице и скачивает файл (обычный GET,
  без браузера), разбирает его через openpyxl.
- Один файл содержит все конкурсные группы; для направления 03.03.01 объединяются
  подходящие блоки («Общий конкурс», очная форма, бюджет).

## Как устроен парсер КФУ

Данные на `kpfu.ru` встроены через iframe `abiturient.kpfu.ru`. Фильтры работают
GET-параметрами (полная перезагрузка страницы, без AJAX), поэтому браузер не нужен —
HTTP-клиент Playwright, HTML разбирается BeautifulSoup.

- `external_id` в конфиге = id института (`p_faculty`); id программы (`p_speciality`)
  находится по коду направления в выпадающем списке.
- Форма, кампус и категория фиксированы (бакалавриат, очная, бюджет, основной кампус),
  берётся раздел «Основной конкурс».

## Как устроен парсер ГУАП

Сводная страница `bach/lists/list_1_1_1_1` — server-rendered HTML с таблицей направлений
и ссылками на бюджетные списки. Каждая программа — отдельная страница с таблицей
`.pk-ratings-table`. Браузер не нужен (обычный GET через `playwright.request`).

- Парсер сначала читает сводную таблицу (сопоставление код → ссылка на список),
  затем загружает страницу каждого направления из конфига.
- Под одним кодом направления бывает несколько программ — они объединяются в один
  список (как у СПбГУ).

## Как устроен парсер ВШЭ (Москва и Санкт-Петербург)

Страница `pk.hse.ru/admissions/.../applicants/<setId>/<groupId>` — Angular-приложение;
данные из JSON-API `/admissions/api` (браузер не нужен, httpx):

- `GET /competitve-group/{groupId}` (опечатка «competitve» — авторская, из API ВШЭ) —
  заголовок: программа, кампус (`filial`), тип мест (`placeType`, «Б» = бюджет),
  места (`placeCount`), дата формирования (`updatedAt`);
- `GET /applicant?level=BAK&placeType={placeTypeId}&setOfCompetitiveGroupId={setId}
  &page=N&size=500` — страницы списка (Spring Page, парсер обходит все).

Кампусы — два вуза конфига (`HSE_MSK`, `HSE_SPB`) с общим классом `HseParser`:
парсер сверяет `filial` заголовка с городом вуза и требует `placeType.code == «Б»`,
поэтому перепутанный URL (чужой кампус или платный список) даёт явную ошибку.
`external_id` направления = `"<setId>/<groupId>"` — оба UUID из адресной строки.
Согласие: `isConcertToEnrollment`; БВИ: `isWithoutExamsAdmReasonBool`.

## Как устроен парсер Горного университета (СПб)

Списки отдаются как server-rendered HTML: `GET priem2026.spmi.ru/list?direction_id=7`
`&specialization_id=N&applicant_type_id=2&applicant_consent_id=0`. Браузер не нужен —
HTTP-клиент Playwright + BeautifulSoup.

- `external_id` в конфиге = `specialization_id` укрупнённой программы на сайте.
- Несколько кодов направлений (например 09.03.01 и 09.03.02) могут указывать на один
  `specialization_id` — список на сайте общий, поэтому загрузка кэшируется по id.

## Установка

Требуется Python 3.11+ и Docker (для PostgreSQL).

```powershell
# 1. Виртуальное окружение и зависимости
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Браузер для Playwright
.\.venv\Scripts\python.exe -m playwright install chromium

# 3. PostgreSQL в Docker (порт 5544, чтобы не конфликтовать с другими БД)
docker run -d --name univer_parser_db -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=univer_parser -p 5544:5432 postgres:16-alpine

# 4. Настройки: скопировать пример и при необходимости поправить
copy .env.example .env

# 5. Применить миграции (создать таблицы)
.\.venv\Scripts\alembic.exe upgrade head
```

## Запуск

```powershell
# API (парсинг сам не выполняет — только очередь и выдача данных):
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Worker (в отдельном окне — разбирает очередь parser_runs):
.\.venv\Scripts\python.exe -m app.cli consume-queue
```

Документация API (Swagger): http://127.0.0.1:8000/docs
Проще всего — `start-dev.ps1` из корня репозитория (поднимает всё сразу).

## API

Мониторинг и управление (см. также DEPLOY.md):

- `GET  /health` — проверка, что сервис жив
- `GET  /api/v1/parser/health` — свежесть данных по каждому вузу (stale, last_error...)
- `GET  /api/v1/parser/runs` — история запусков
  (`limit/offset/university_code/status/date_from/date_to`)
- `POST /api/v1/parser/run/{code}` — ручной запуск вуза, Bearer `PARSER_TRIGGER_TOKEN`
  (401 без токена / 403 неверный / 202 поставлено в очередь)
- `GET  /api/v1/config` — текущая конфигурация
- `POST /api/v1/parser/start`, `GET /api/v1/parser/status` — deprecated

Данные для фронтенда: `GET /api/v1/data/universities`, `GET /api/v1/data/applicants`.

## CLI (python -m app.cli)

- `enqueue <code>` — поставить вуз в очередь (DB-only, работает в api-образе)
- `consume-queue [--once]` — цикл воркера (парсит, только в worker-образе)
- `parse-university <code>` / `parse-all` — прямой запуск (advisory-lock)
- `recover-stuck-runs` — пометить зависшие running-задачи (worker interrupted)
- `check-parser-health` — отчёт о свежести + stale-алерт в Telegram
- `cleanup-snapshots` — удалить снимки старше `SNAPSHOT_RETENTION_DAYS`

Коды выхода: 0 — успех, 1 — ошибка, 2 — частичный/подозрительный результат.
Коды вузов регистронезависимы (`itmo` == `ITMO`).

## Конфигурация

Список вузов и направлений задаётся вручную в [config.json](config.json).
У каждого вуза обязателен `parser_type`: `http` (обычные запросы, httpx) или
`playwright` (нужен браузер — СПбПУ, СПбГУТ). Направления сопоставляются с сайтом
по коду (например, `09.03.04`); для вузов с прямым идентификатором программы
указывается `external_id`. Интервал автозапуска планировщика
(`parser_settings.parse_interval_hours`) действует только при `ENABLE_SCHEDULER=true`
(локальная разработка); в проде расписание — systemd-таймеры.

## Как добавить направление существующему вузу

Общий цикл (все правки — только через git, не на VPS):

```text
1. Найти идентификатор направления на сайте вуза (см. таблицу ниже)
2. Добавить объект в majors вуза в config.json
3. Проверить конфиг:   python -c "from app.core.config_loader import load_config; load_config()"
4. Живой прогон:       python -m app.cli parse-university <CODE>   (dev-БД)
5. commit + push
6. VPS: git pull && docker compose build api worker && docker compose up -d api worker
7. VPS: docker compose exec -T api python -m app.cli enqueue <code> → проверить /parser/health
```

Способ сопоставления направления с сайтом у каждого вуза свой:

| Вуз | Сопоставление | Где брать идентификатор |
|---|---|---|
| SPBSTU | по коду в рантайме | Код должен буквально совпадать с `my.spbstu.ru` (get-code-list). Синтетические суффиксы (`38.03.01_29`) сайт не знает |
| SUT | по коду в рантайме | Код из списка групп `priem.sut.ru` (get_spec) |
| SAMARA | `external_id` = pk | Открыть рейтинг направления на `priemsamara.ru`, взять `?pk=N` из URL |
| SAMGTU | по коду в рантайме | Название группы в API kcps начинается с кода (очная, СамГТУ, КЦП) |
| SPBGU | по коду в рантайме | Код из meta отчёта; несколько программ одного кода объединяются |
| TLTSU | по коду в рантайме, но в пределах одного `dep` | Направления другого института = другой `dep` в `university.url` — сейчас парсится один институт |
| LETI | `external_id` = UUID | На `abit.etu.ru` открыть список направления, взять `id=UUID` из URL виджета `lists.priem.etu.ru` |
| MPEI | `external_id` = имя файла | Оглавление `pk.mpei.ru/info/entrants_list.html` → `entrants_listN.html` направления |
| ITMO | `external_id` = competitive_group_id | Число из URL `abit.itmo.ru/rating/bachelor/budget/<id>` |
| SPBAU | по форме/категории в xlsx | Направление должно присутствовать в общем xlsx (сейчас только 03.03.01) |
| SPMI | `external_id` = specialization_id | Ссылки укрупнённых групп на `priem2026.spmi.ru/specialization?direction_id=7`; несколько кодов могут делить один id |
| KPFU | `external_id` = id института (p_faculty) | Институт из URL iframe `abiturient.kpfu.ru`; программа находится по коду в выпадающем списке |
| GUAP | по коду в рантайме | Код из сводной таблицы `priem.guap.ru/bach/lists/list_1_1_1_1` |
| HSE_MSK / HSE_SPB | `external_id` = `setId/groupId` | Открыть бюджетный список направления на `pk.hse.ru`, взять оба UUID из URL `/applicants/<setId>/<groupId>`; кампус и «бюджетность» парсер проверит сам |

## Как добавить новый вуз

```text
1. Разведка сайта: как отдаются списки (HTML / JSON / xlsx)? нужен ли браузер?
   → parser_type: http (почти всегда достаточно) или playwright.
   Полезно сохранить образцы ответов (см. scripts/explore_*.py как образец).
2. Код (два файла):
   app/parser/<code>_mapping.py — чистый разбор разметки → ApplicantRow
   app/parser/<code>.py         — класс-наследник HttpParser:
                                  _parse_major() + при необходимости _prepare();
                                  особые случаи — см. tltsu (один отчёт),
                                  spbau (общий xlsx), spmi (кэш), kpfu (cp1251)
3. Зарегистрировать класс в PARSER_REGISTRY (app/services/parser_runner.py)
4. Добавить вуз в config.json: code UPPERCASE, parser_type, enabled, majors
5. Тесты (три места!):
   - tests/test_http_parsers.py — фикстура по реальной разметке + тест parse()
   - tests/test_import_hygiene.py — добавить модуль в HTTP_PARSER_MODULES
   - pytest -q — все зелёные
6. Живой прогон: python -m app.cli parse-university <CODE>
7. Описание вуза в README (раздел «Поддерживаемые вузы» + «Как устроен парсер»)
8. commit + push
9. VPS: git pull && docker compose build api worker && docker compose up -d api worker
10. VPS: sudo bash scripts/install-timers.sh   ← ОБЯЗАТЕЛЬНО: новый вуз = новый ночной слот
11. VPS: enqueue <code> → /parser/health: success, is_stale=false
```

Частые грабли:
- забыли PARSER_REGISTRY → «Нет парсера для вуза X» в логах worker;
- забыли install-timers.sh → вуз парсится только вручную, через сутки придёт stale-алерт;
- у сайта просрочен/самоподписанный TLS-сертификат → точечно `verify_ssl = False`
  в классе парсера с комментарием-TODO (см. SamgtuParser);
- сайт отдаёт заглушку без браузерного User-Agent → он уже задан в HttpParser;
- Playwright использовать только когда без браузера действительно нельзя (ТЗ §8.2).

## Структура

```text
app/
├── main.py            # точка входа, lifespan, роутеры
├── cli.py             # команды воркера и обслуживания (python -m app.cli)
├── core/              # настройки, подключение к БД, загрузка конфига
├── models/            # таблицы БД (SQLAlchemy), в т.ч. parser_runs
├── schemas/           # Pydantic: валидация конфига и данных парсера
├── parser/            # BaseParser/HttpParser + парсеры 13 вузов
├── services/          # queue, storage, changes, health, notifications, runner
├── api/               # HTTP-эндпоинты
└── scheduler/         # периодическая постановка в очередь (dev, APScheduler)
```

Тесты: `pytest` из каталога backend (56 шт.; нужна тестовая PostgreSQL,
см. tests/conftest.py).
