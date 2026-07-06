"""
Базовый абстрактный класс парсера.

От него наследуются парсеры конкретных вузов (СПбПУ, в будущем ИТМО и т.д.).
Единый интерфейс parse() позволяет запускать любой парсер одинаково,
не зная деталей конкретного сайта (принцип полиморфизма / OCP из SOLID).
"""

from abc import ABC, abstractmethod

from app.schemas.config_schema import UniversityConfig
from app.schemas.parser_schema import ParseResult


class BaseParser(ABC):
    """
    Абстрактный парсер одного вуза.

    Наследник получает конфиг вуза (список направлений, url) и реализует
    метод parse(), который собирает данные и возвращает ParseResult.
    """

    def __init__(self, university: UniversityConfig, request_delay_seconds: float = 1.5):
        # Конфигурация вуза: url, список направлений с параметрами отбора.
        self.university = university
        # Пауза между запросами направлений (защита от блокировок).
        self.request_delay_seconds = request_delay_seconds

    @abstractmethod
    async def parse(self) -> ParseResult:
        """Собрать данные по всем направлениям вуза и вернуть результат."""
        raise NotImplementedError
