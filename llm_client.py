"""
llm_client.py — доступ к языковой модели за общим интерфейсом.

ПРАКТИКА 4. Что делает студент:
  1. GigaChatClient.generate() — вызов Сбер GigaChat через официальный SDK
  2. OllamaClient.generate()   — вызов локальной модели через HTTP API Ollama
  3. count_tokens()            — оценка длины промпта до отправки

Готово и трогать не нужно: build_client() и выбор бэкенда по LLM_BACKEND.

Критерии приёмки:
  - смена LLM_BACKEND с gigachat на ollama не требует правки orchestrator.py
  - длина промпта считается до отправки и логируется
  - оба клиента принимают один и тот же список messages и возвращают строку

НЕ МЕНЯТЬ: сигнатуру generate(messages, temperature) — она объявлена в contracts.py
и на неё опирается оркестратор.

Зачем абстракция. Учебные квоты кончаются, сеть в аудитории падает, а занятие
должно продолжаться. Ollama — фолбэк, который работает офлайн. Заодно это
материал для сравнения авторегрессионной модели и reasoning-модели из Л4:
у llama3.2:3b в ответе виден блок рассуждений, у GigaChat — нет.

Третий бэкенд — fake_llm.FakeClient, офлайн-заглушка без сети и ключей. Она
нужна для отладки, когда недоступны оба клиента, и ваши реализации не заменяет:
работа, сданная на LLM_BACKEND=fake, не принимается.
"""

import config, re, requests
from contracts import LLMClient


class GigaChatClient:
    """Клиент Сбер GigaChat API."""

    def __init__(self):
        self.model = config.GIGACHAT_MODEL
        # TODO (П4): создать клиент
        # from gigachat import GigaChat
        # self._client = GigaChat(credentials=config.GIGACHAT_CREDENTIALS,
        #                         model=self.model,
        #                         verify_ssl_certs=config.GIGACHAT_VERIFY_SSL)

    def generate(self, messages: list[dict], temperature: float = 0.3) -> str:
        """Отправить диалог в GigaChat и вернуть текст ответа.

        SDK принимает структуру вида {"messages": [...], "temperature": ...}.
        Ответ лежит в response.choices[0].message.content.
        Не забудьте обработать сетевую ошибку: занятие не должно падать трассировкой.
        """
        raise NotImplementedError("П4: реализуйте вызов GigaChat")

    def count_tokens(self, text: str) -> int:
        """Оценка длины в токенах.

        У GigaChat есть метод tokens_count. Если он недоступен, дайте оценку:
        для русского текста примерно один токен на 3 символа. Точность здесь
        не главное — важно видеть порядок величины и связать его со стоимостью.
        """
        raise NotImplementedError("П4: реализуйте подсчёт токенов")


class OllamaClient:
    """Клиент локального инференса через Ollama."""

    def __init__(self):
        self.model = config.OLLAMA_MODEL
        self.host = config.OLLAMA_HOST

    _THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

    def generate(self, messages: list[dict], temperature: float = 0.3) -> str:
        url = f"{self.host}/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        try:
            response = requests.post(url, json=payload, timeout=300)
            response.raise_for_status()
            data = response.json()
            content = (data.get("message", {}).get("content") or "").strip()

            # llama3.2:3b - reasoning-модель: рассуждения приходят либо в поле
            # message.thinking, либо внутри текста в тегах <think>...</think>.
            # Для ответа пользователю их убираем - они служебные и мешают
            # читать ответ со ссылками на источники
            content = self._THINK_RE.sub("", content).strip()

            if not content:
                return "Ошибка: Ollama вернула пустой ответ."
            return content

        except requests.exceptions.Timeout:
            return "Ошибка: сервис Ollama не ответил за отведённое время."
        except requests.exceptions.ConnectionError:
            return f"Ошибка: не удалось подключиться к Ollama по адресу {self.host}."
        except requests.exceptions.HTTPError as e:
            return f"Ошибка HTTP от Ollama: {e}."
        except (ValueError, KeyError) as e:
            return f"Ошибка: некорректный ответ от Ollama ({e})."

    def count_tokens(self, text: str) -> int:
        """Грубая оценка: ~1 токен на 3 символа русского текста.

        Точность здесь не нужна - важно видеть порядок величины и связать
        со стоимостью на П8. Для пустой строки возвращаем 0.
        """
        return len(text) // 3


def build_client() -> LLMClient:
    """Выбрать бэкенд по конфигурации. Готово, менять не нужно."""
    if config.LLM_BACKEND == "ollama":
        return OllamaClient()
    if config.LLM_BACKEND == "gigachat":
        return GigaChatClient()
    if config.LLM_BACKEND == "fake":
        # Импорт внутри ветки: без него fake_llm тянулся бы при любом бэкенде
        from fake_llm import FakeClient

        return FakeClient()
    raise ValueError(
        f"Неизвестный LLM_BACKEND: {config.LLM_BACKEND!r}. "
        f"Допустимо: gigachat | ollama | fake"
    )
