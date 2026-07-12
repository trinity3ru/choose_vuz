"""
Import-гигиена: HTTP-парсеры не должны тянуть Playwright.

Требование деплоя: api-образ собирается без Playwright/Chromium, поэтому
импорт HTTP-парсеров (и в будущем app.main) обязан работать в окружении,
где playwright не установлен, и не должен загружать его там, где установлен.

Проверяем в отдельном интерпретаторе (subprocess), чтобы на результат
не влияли модули, уже загруженные другими тестами.
"""

import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Все HTTP-парсеры (11 вузов) + их база.
HTTP_PARSER_MODULES = [
    "app.parser.http_base",
    "app.parser.itmo",
    "app.parser.samara",
    "app.parser.samgtu",
    "app.parser.spbgu",
    "app.parser.tltsu",
    "app.parser.leti",
    "app.parser.mpei",
    "app.parser.spbau",
    "app.parser.kpfu",
    "app.parser.guap",
    "app.parser.spmi",
    "app.parser.hse",
]


def test_http_parsers_do_not_import_playwright():
    """Импорт всех HTTP-парсеров не загружает playwright."""
    code = (
        "import os, sys; "
        "os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://t:t@localhost/t'); "
        + "; ".join(f"import {m}" for m in HTTP_PARSER_MODULES)
        + "; assert not [m for m in sys.modules if m.startswith('playwright')], "
        "'playwright загружен HTTP-парсерами'"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_api_and_cli_do_not_import_playwright():
    """
    api-образ собирается без Playwright: import app.main, app.cli и очереди
    не должен его загружать (ленивый импорт парсеров в CLI — раунд D плана).
    """
    code = (
        "import os, sys; "
        "os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://t:t@localhost/t'); "
        "import app.main; import app.cli; import app.services.queue; "
        "import app.scheduler.jobs; import app.api.parser_routes; "
        "bad = [m for m in sys.modules if m.startswith(('playwright', 'app.parser', 'bs4', 'openpyxl'))]; "
        "assert not bad, f'api-контур тянет парсеры: {bad}'"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_playwright_parsers_still_importable():
    """Playwright-парсеры (СПбПУ, СПбГУТ) по-прежнему импортируются."""
    code = (
        "import os; "
        "os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://t:t@localhost/t'); "
        "import app.parser.spbstu, app.parser.sut"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
