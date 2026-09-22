"""
contracts.py — типы и интерфейсы, общие для всех слоёв.

ГОТОВ ЦЕЛИКОМ. НЕ МЕНЯТЬ НИ ОДНОЙ СИГНАТУРЫ.

На этих контрактах держится всё остальное: два канала доставки (app.py и vk_bot.py)
вызывают одно ядро, тесты обращаются к тому же ядру, а смена бэкенда LLM не требует
правок в оркестраторе. Изменение контракта ломает всё это разом, поэтому правки
сюда вносит только преподаватель.
"""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Chunk:
    """Фрагмент документа из векторного индекса (П2)."""
    text: str
    source: str        # имя файла-источника
    page: int          # номер страницы; 0 для форматов без страниц
    category: str      # домен-зависимая рубрика, словарь задаёт студент на П2
    score: float = 0.0 # косинусное сходство с запросом


@dataclass
class Message:
    """Реплика диалога (П5)."""
    role: str          # user | assistant | system
    content: str
    timestamp: str = ""


@dataclass
class GuardResult:
    """Вердикт слоя безопасности (П7)."""
    allowed: bool
    reason: str | None = None      # какой паттерн сработал
    matched: list[str] = field(default_factory=list)


class LLMClient(Protocol):
    """Общий интерфейс языковой модели (П4).

    Реализуется дважды — GigaChatClient и OllamaClient. Оркестратор работает
    только через этот протокол и не знает, какой бэкенд под ним.
    """

    def generate(self, messages: list[dict], temperature: float = 0.3) -> str:
        """messages — список {"role": ..., "content": ...} в порядке диалога."""
        ...

    def count_tokens(self, text: str) -> int:
        """Оценка длины в токенах до отправки запроса (П4: экономика токенов)."""
        ...
