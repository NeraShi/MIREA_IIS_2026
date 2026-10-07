"""
orchestrator.py — ядро системы: конечный автомат, переключающий роли агентов.

ПРАКТИКА 3. Что делает студент:
  1. описать роли в ROLES — минимум две, с разными зонами ответственности
  2. заполнить INTENT_TO_ROLE и TRANSITIONS — граф переходов автомата
  3. реализовать detect_intent() — определение интента пользователя

Готово и трогать не нужно: route(), handle(), подключение MCP и LLM.

Критерии приёмки:
  - ролей не меньше двух, у каждой описана своя зона ответственности
  - граф переходов задан структурой данных, а не цепочкой if по всему файлу
  - смена интента в диалоге переключает роль, это видно в логе
  - неизвестный интент не роняет процесс, а уходит в состояние по умолчанию
  - контекст при переходе не теряется: вторая роль видит найденное первой
  - вызов инструмента идёт через MCP-клиент, а не прямым импортом функции поиска

НЕ МЕНЯТЬ: сигнатуру handle(session_id, text) -> str. Это единственная точка
входа в систему, и её вызывают оба канала (app.py, vk_bot.py) и test_suite.py.

Порядок сдачи. На П3 сквозного ответа ещё не будет: build_messages() и клиент LLM
пишутся на П4. Проверяйте автомат отдельно — вызовом detect_intent() и route()
на наборе фраз. Сквозной ответ появится на П4, память подключится на П5.
"""

import logging

import guardrails
import memory
import prompts
from contracts import Chunk
from llm_client import build_client
from mcp_client import MCPTools

log = logging.getLogger(__name__)

BLOCKED_REPLY = "Запрос отклонён слоем безопасности. Переформулируйте вопрос по существу темы."


class Orchestrator:
    """Оркестратор ролей на конечном автомате."""

    ROLES: dict[str, dict] = {
        "analyst": {
            "description": "ищет факты в базе знаний и отвечает со ссылками на источники",
            "temperature": 0.2, 
            "filters": {},  # {} = искать по всему индексу
        },
        "clarifier": {
            "description": "запрашивает необходимые/дополнительные уточняющие условия",
            "temperature": 0.3,
            "filters": {},
        },
        "verifier": {
            "description": "проверяет, что найденная аналитиком норма применима",
            "temperature": 0.1,
            "filters": {},
        },
    }

    INITIAL_ROLE = "analyst"
    FALLBACK_ROLE = "analyst"

    TRANSITIONS: dict[str, set[str]] = {
        "analyst":   {"analyst", "clarifier", "verifier"},
        "clarifier": {"analyst", "verifier"},
        "verifier":  {"analyst", "clarifier"},
    }

    # --- Какой интент какой ролью обслуживается ---
    INTENT_TO_ROLE: dict[str, str] = {
        "question": "analyst",
        "clarify": "clarifier",
        "verify": "verifier",
    }

    def __init__(self):
        self.tools = MCPTools()
        self.llm = build_client()
        memory.create_schema()
        self._state: dict[str, str] = {}      # session_id -> текущая роль
        self._context: dict[str, list[Chunk]] = {}  # session_id -> что нашла прошлая роль
        self.usage: list[dict] = []           # расход токенов по вызовам, на нём считается TCO (П8)

    _VERIFY_MARKERS = (
        "проверь", "перепроверь", "проверьте",
        "ты уверен", "вы уверены", "уверен ли",
        "точно ли", "верно ли", "правильно ли", "правда ли",
        "так ли это", "так ли", "разве",
        "подтверди", "сверь", "пересмотри",
        "не ошиб", "не ошибаешься",
    )

    _CLARIFY_MARKERS = (
        "уточни", "уточните", "давай уточним",
        "не знаю", "непонятно", "непонятн", "неясно", "не ясно",
        "а в моём случае", "а в моем случае", "а как у меня",
        "какой у меня случай", "какой мой случай",
        "какие условия", "что мне указать", "что нужно знать",
    )

    # Реплика описывает ситуацию действием, но условий не называет.
    _SITUATION_MARKERS = (
        "клиент", "заказчик", "заплатил", "перевёл", "получил",
        "оплатил", "заказ", "работаю", "оказываю", "выполнил",
    )

    # Условия, без которых ответ по НПД неоднозначен.
    _CONDITION_MARKERS = (
        "физлицо", "физическое лицо", "организация",
        "юрлицо", "юридическое лицо",
        "нпд", "самозанят", "лимит", "превыс", "ставка", "регион",
    )

    # Если в реплике есть такое слово — это вопрос к аналитику, а не ситуация
    # без условий. Иначе «почему клиент платит налоги» уходило бы в clarifier.
    _QUESTION_MARKERS = (
        "как", "почему", "зачем", "объясни", "расскажи",
        "где", "что такое", "какой документ", "какая статья",
    )

    _SITUATION_MAX_WORDS = 12

    def detect_intent(self, text: str) -> str:
        """
        Определяет интент реплики по набору правил
        1 AGENT per 1 MESSAGE
        """
        low = text.lower().replace("ё", "е")
        words = low.split()

        # Скепсис — самое специфичное правило
        if any(m in low for m in self._VERIFY_MARKERS):
            return "verify"

        # Явная просьба уточнить
        if any(m in low for m in self._CLARIFY_MARKERS):
            return "clarify"

        # Ситуация без условий
        is_situation = (
            len(words) <= self._SITUATION_MAX_WORDS
            and any(m in low for m in self._SITUATION_MARKERS)
            and not any(m in low for m in self._CONDITION_MARKERS)
            and not any(m in low for m in self._QUESTION_MARKERS)
            and not text.rstrip().endswith("?")
        )
        if is_situation:
            return "clarify"

        # Fallback
        return "question"

    # --- Готовая механика: менять не нужно ---

    def route(self, session_id: str, intent: str) -> str:
        """Перевести автомат в новое состояние и вернуть активную роль."""
        current = self._state.get(session_id, self.INITIAL_ROLE)
        target = self.INTENT_TO_ROLE.get(intent, self.FALLBACK_ROLE)

        allowed = self.TRANSITIONS.get(current, {self.FALLBACK_ROLE})
        rolled_back = target not in allowed
        if rolled_back:
            log.warning("Переход %s -> %s запрещён, откат в %s",
                        current, target, self.FALLBACK_ROLE)
            target = self.FALLBACK_ROLE

        if target != current:
            # Про откат сказано прямо: иначе строка «verifier -> analyst (интент verify)»
            # читается как «интент verify обслуживается ролью analyst», то есть наоборот.
            log.info("Сессия %s: роль %s -> %s (интент %s%s)",
                     session_id, current, target, intent, ", откат" if rolled_back else "")

        self._state[session_id] = target
        return target

    def handle(self, session_id: str, text: str) -> str:
        """Единственная точка входа. Оба канала и тесты идут сюда.

        Конвейер: guardrail -> память -> интент -> роль -> поиск через MCP ->
        сборка промпта -> LLM -> память -> ответ.
        """
        verdict = guardrails.check(text)
        if not verdict.allowed:
            guardrails.log_attempt(session_id, text, verdict)
            log.warning("Сессия %s: запрос заблокирован (%s)", session_id, verdict.reason)
            return BLOCKED_REPLY

        previous_role = self._state.get(session_id, self.INITIAL_ROLE)
        intent = self.detect_intent(text)
        role = self.route(session_id, intent)
        role_config = self.ROLES[role]

        filters = role_config.get("filters") or {}
        if filters:
            chunks = self.tools.search_filtered(text, filters)
        else:
            chunks = self.tools.search(text)

        # Контекст переезжает между ролями: при переключении новая роль видит
        # и свои фрагменты, и то, что нашла предыдущая, — иначе разговор рвётся.
        # Признак переноса — смена роли, а не пустая выдача: поиск по реплике
        # «а в моём случае?» возвращает не ноль фрагментов, а пять нерелевантных.
        if role != previous_role:
            known = {(c.source, c.page, c.text[:80]) for c in chunks}
            chunks = chunks + [c for c in self._context.get(session_id, [])
                               if (c.source, c.page, c.text[:80]) not in known]
        self._context[session_id] = chunks

        history = memory.window(session_id)

        # Реплика пользователя сохраняется после чтения окна, а не до него.
        # Иначе текущий вопрос уходил бы в модель дважды — в истории и в блоке
        # с фрагментами, — а полезная глубина окна была бы N−1, а не N.
        memory.save(session_id, "user", text)

        messages = prompts.build_messages(role, text, chunks, history)

        # Считается одним вызовом по склеенному тексту, а не по сообщению на вызов:
        # у облачного клиента count_tokens() — обращение к API, и поштучный подсчёт
        # добавлял бы к каждому вопросу столько сетевых запросов, сколько сообщений.
        prompt_size = self.llm.count_tokens("\n".join(m["content"] for m in messages))
        log.info("Сессия %s: роль %s, чанков %d, промпт ~%d токенов",
                 session_id, role, len(chunks), prompt_size)

        answer = self.llm.generate(messages, temperature=role_config["temperature"])

        # Вход и выход считаются раздельно: они тарифицируются по разным ценам (П8)
        self.usage.append({
            "session_id": session_id,
            "role": role,
            "prompt_tokens": prompt_size,
            "completion_tokens": self.llm.count_tokens(answer),
        })

        memory.save(session_id, "assistant", answer)
        return answer

    def reset(self, session_id: str) -> None:
        """Сбросить сессию: состояние автомата, контекст и историю."""
        self._state.pop(session_id, None)
        self._context.pop(session_id, None)
        memory.clear(session_id)

    def close(self) -> None:
        self.tools.close()
