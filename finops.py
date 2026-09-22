"""
finops.py — стоимость владения системой и эффект оптимизаций.

ПРАКТИКА 8. Что делает студент:
  1. заполнить PRICE_INPUT_PER_1M и PRICE_OUTPUT_PER_1M в config.py — из тарифов провайдера
  2. estimate_tco() — расчёт стоимости на сценарий нагрузки, заданный преподавателем
  3. провести одну оптимизацию из Л8 и повторить замер

Готово: measure_dialog() — прогон эталонного диалога со снятием расхода токенов,
и compare() — печать отчёта до/после.

Критерии приёмки:
  - замер сделан на реальных вызовах модели, а не оценкой на глаз
  - расход разделён на вход и выход: они тарифицируются по-разному
  - TCO посчитан на сценарий преподавателя, допущения выписаны явно
  - оптимизация даёт измеримый эффект, показанный числом до и после
  - названа цена оптимизации: что именно ухудшилось
  - отрицательный результат с объяснением засчитывается

Откуда берутся числа. Оркестратор накапливает расход по каждому вызову в
orchestrator.usage — отдельно вход и отдельно выход. Это не оценка, а то, что
реально ушло в модель, поэтому расчёт воспроизводим и проверяем на ревью.

Что оптимизировать (Л8):
  - обрезка окна памяти: MEMORY_WINDOW в config.py — прямо режет вход
  - прунинг истории в SQLite: старые сессии не должны копиться вечно
  - кэширование контекста: повторяющиеся системные блоки не пересылать заново
  - квантование локальной модели INT8/INT4 — если считаете на Ollama

У каждой из них есть цена. Короче окно памяти — хуже связность диалога.
Кэш — риск устаревших ответов. Агрессивнее квантование — ниже качество генерации.
Назвать эту цену обязательно: оптимизация без названной цены не засчитывается.

Два замера делаются двумя запусками, а не одним: оптимизация меняет config.py,
и «до» с «после» в одном процессе не снять. Первый запуск снимает базовый замер
и сохраняет его в data/finops_baseline.json, второй — сравнивает с ним.

Запуск:
    python finops.py            # первый раз — замер «до», второй — «после» и сравнение
    python finops.py --reset    # забыть замер «до» и начать заново
"""

import json
import sys
from dataclasses import asdict, dataclass

import config
from orchestrator import Orchestrator

# Замер «до» переживает перезапуск: оптимизация меняет config.py, поэтому
# оба замера в одном процессе не сделать. Первый прогон сохраняет базовый
# замер сюда, второй — сравнивает с ним.
BASELINE = config.DATA_DIR / "finops_baseline.json"

# Эталонный диалог: одинаковый до и после оптимизации, иначе замеры несравнимы.
# ЗАМЕНИТЕ на вопросы своего домена, но потом не меняйте между двумя прогонами.
REFERENCE_DIALOG = [
    "ЗАМЕНИТЕ: первый вопрос по вашему домену",
    "ЗАМЕНИТЕ: уточняющий вопрос, опирающийся на первый ответ",
    "ЗАМЕНИТЕ: вопрос из другого раздела базы знаний",
]


@dataclass
class Measurement:
    """Результат одного замера."""
    label: str
    turns: int
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def cost(self) -> float:
        """Стоимость самого замера в рублях."""
        return (self.prompt_tokens / 1_000_000 * config.PRICE_INPUT_PER_1M
                + self.completion_tokens / 1_000_000 * config.PRICE_OUTPUT_PER_1M)


def save_baseline(measurement: Measurement) -> None:
    """Сохранить замер «до» на диск. Готово, менять не нужно."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps(asdict(measurement), ensure_ascii=False, indent=2),
                        encoding="utf-8")


def load_baseline() -> Measurement | None:
    """Прочитать замер «до», если он был сделан раньше. Готово, менять не нужно."""
    if not BASELINE.exists():
        return None
    return Measurement(**json.loads(BASELINE.read_text(encoding="utf-8")))


def measure_dialog(label: str, questions: list[str] | None = None) -> Measurement:
    """Прогнать эталонный диалог и снять расход токенов. Готово, менять не нужно."""
    questions = questions or REFERENCE_DIALOG
    orchestrator = Orchestrator()
    session_id = f"finops:{label}"

    try:
        for question in questions:
            orchestrator.handle(session_id, question)
        usage = orchestrator.usage
        return Measurement(
            label=label,
            turns=len(usage),
            prompt_tokens=sum(u["prompt_tokens"] for u in usage),
            completion_tokens=sum(u["completion_tokens"] for u in usage),
        )
    finally:
        orchestrator.reset(session_id)
        orchestrator.close()


def estimate_tco(measurement: Measurement, dialogs_per_day: int,
                 turns_per_dialog: int) -> dict:
    """Стоимость владения на сценарий нагрузки, заданный преподавателем.

    Верните словарь с ключами: "per_dialog", "per_day", "per_month", "per_year".

    Ход рассуждения: из замера известна стоимость turns реплик. Приведите её к
    одной реплике, умножьте на turns_per_dialog, потом на dialogs_per_day, потом
    на 30 и на 365.

    Две ловушки. Первая: расход на реплику не постоянен — с ростом истории диалога
    вход растёт, поэтому средняя по замеру занижает длинные диалоги. Отметьте это
    как допущение. Вторая: считайте вход и выход раздельно до самого конца, их
    цены отличаются в разы, и усреднение искажает результат.
    """
    raise NotImplementedError("П8: реализуйте расчёт TCO")


def compare(before: Measurement, after: Measurement,
            dialogs_per_day: int, turns_per_dialog: int) -> None:
    """Печать отчёта до/после. Готово, менять не нужно."""
    tco_before = estimate_tco(before, dialogs_per_day, turns_per_dialog)
    tco_after = estimate_tco(after, dialogs_per_day, turns_per_dialog)

    def delta(old: float, new: float) -> str:
        if not old:
            return "—"
        return f"{(new - old) / old * 100:+.1f}%"

    print(f"\nСценарий: {dialogs_per_day} диалогов в сутки по {turns_per_dialog} реплик")
    print(f"Тарифы: вход {config.PRICE_INPUT_PER_1M} ₽ / 1М, "
          f"выход {config.PRICE_OUTPUT_PER_1M} ₽ / 1М")
    if not (config.PRICE_INPUT_PER_1M or config.PRICE_OUTPUT_PER_1M):
        print("ВНИМАНИЕ: тарифы в config.py нулевые — стоимость посчитается как ноль (П8).")

    print(f"\n{'':<22}{before.label:>16}{after.label:>16}{'изменение':>14}")
    rows = [
        ("токенов на вход", before.prompt_tokens, after.prompt_tokens),
        ("токенов на выход", before.completion_tokens, after.completion_tokens),
        ("токенов всего", before.total_tokens, after.total_tokens),
    ]
    for name, old, new in rows:
        print(f"{name:<22}{old:>16,}{new:>16,}{delta(old, new):>14}")

    for key, title in [("per_day", "рублей в сутки"), ("per_month", "рублей в месяц"),
                       ("per_year", "рублей в год")]:
        old, new = tco_before[key], tco_after[key]
        print(f"{title:<22}{old:>16,.2f}{new:>16,.2f}{delta(old, new):>14}")


if __name__ == "__main__":
    # TODO (П8): подставьте сценарий, который задал преподаватель
    DIALOGS_PER_DAY = 500
    TURNS_PER_DIALOG = 8

    if "--reset" in sys.argv:
        BASELINE.unlink(missing_ok=True)
        print("Замер «до» сброшен. Следующий прогон снимет его заново.")
        raise SystemExit(0)

    baseline = load_baseline()

    if baseline is None:
        baseline = measure_dialog("до")
        save_baseline(baseline)
        print(f"Замер «до»: {baseline.turns} реплик, "
              f"{baseline.prompt_tokens:,} на вход, {baseline.completion_tokens:,} на выход")
        print(f"Сохранён в {BASELINE.name}.")
        print("Проведите одну оптимизацию и запустите finops.py снова — "
              "он снимет замер «после» и напечатает сравнение.")
    else:
        after = measure_dialog("после")
        compare(baseline, after, DIALOGS_PER_DAY, TURNS_PER_DIALOG)
        print("\nЧтобы начать замеры заново: python finops.py --reset")
