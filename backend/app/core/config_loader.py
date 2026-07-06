"""
Загрузка и валидация файла config.json.

Функция load_config читает JSON-файл, проверяет его через Pydantic-схему
и возвращает готовый объект AppConfig. При ошибке бросает понятное исключение
с указанием, что именно не так (файл не найден, битый JSON, неверное поле).
"""

import json
from pathlib import Path

from pydantic import ValidationError

from app.core.config import settings
from app.schemas.config_schema import AppConfig


class ConfigError(Exception):
    """Ошибка загрузки или валидации config.json (с понятным текстом)."""

    pass


def load_config(path: Path | None = None) -> AppConfig:
    """
    Прочитать и проверить config.json.

    :param path: путь к файлу; по умолчанию берётся из настроек (settings.config_path).
    :return: провалидированный объект конфигурации AppConfig.
    :raises ConfigError: если файл не найден, содержит битый JSON
                         или не проходит валидацию схемы.
    """
    config_path = path or settings.config_path

    # 1. Проверяем, что файл существует.
    if not config_path.exists():
        raise ConfigError(f"Файл конфигурации не найден: {config_path}")

    # 2. Читаем и разбираем JSON. Отдельно ловим синтаксические ошибки JSON.
    try:
        raw_text = config_path.read_text(encoding="utf-8")
        raw_data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"Файл {config_path} содержит некорректный JSON: {exc}"
        ) from exc

    # 3. Валидируем структуру через Pydantic. Ошибки делаем читаемыми.
    try:
        return AppConfig.model_validate(raw_data)
    except ValidationError as exc:
        # Собираем список проблемных полей в понятный текст.
        problems = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"])
            problems.append(f"  - поле '{location}': {error['msg']}")
        details = "\n".join(problems)
        raise ConfigError(
            f"Ошибка в структуре config.json:\n{details}"
        ) from exc
