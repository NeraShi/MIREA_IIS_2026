"""
test_suite.py — прогон Gold Dataset и оценка ответов промптом-судьёй.

ПРАКТИКА 6. Что делает студент:
  1. расширить gold_dataset.json с пяти вопросов, написанных на П2, до десяти,
     добавив к каждому эталонный ответ в поле expected
  2. написать JUDGE_PROMPT — промпт-судью по триаде RAG-метрик
  3. реализовать judge() — вызов судьи и разбор его вердикта

Готово: загрузка датасета, прогон через ядро, сводный отчёт.

Критерии приёмки:
  - в gold_dataset.json ровно 10 вопросов, среди них есть заведомо сложные:
    вне исходных данных, на стыке разделов, с неоднозначной формулировкой
  - пять вопросов с П2 сохранены; замена вопроса допускается только с письменным
    объяснением, чем он оказался негоден
  - прогон проходит все 10 без падений
  - судья возвращает три оценки триады на каждый вопрос, а не одну общую
  - в отчёте зафиксирована хотя бы одна пойманная галлюцинация
    (или обоснованно показано, что их нет)
  - обе метрики измерены и разведены: hit-rate@5 (механически, ingest.py, с П2)
    и Context Precision из триады (судьёй, здесь). В отчёте видно, что это
    разные числа, а не одно под двумя именами

Почему судьёй выступает LLM. Классические Accuracy и F1 на свободном тексте
не работают: верный ответ можно сформулировать десятком способов, и посимвольное
сравнение забракует их все. Сильная модель в роли эксперта-оценщика сравнивает
смысл — это и есть LLM-as-a-judge (Л6).

Запуск:
    python test_suite.py
"""

import json
import statistics
import uuid
from pathlib import Path

from llm_client import build_client
from orchestrator import Orchestrator

DATASET = Path(__file__).parent / "gold_dataset.json"

# TODO (П6): промпт-судья.
# Он должен вернуть СТРОГО JSON с тремя оценками от 0 до 1 и коротким обоснованием:
#   faithfulness     — ответ не противоречит найденным фрагментам и ничего не выдумывает
#   answer_relevance — ответ отвечает именно на заданный вопрос
#   context_precision— найденные фрагменты действительно относятся к вопросу
# Требуйте JSON явно и покажите пример вывода — иначе разбирать будет нечего.
JUDGE_PROMPT = """"""


def judge(llm, question: str, answer: str, expected: str) -> dict:
    """Оценить один ответ. Возвращает {"faithfulness": float, "answer_relevance": float,
    "context_precision": float, "comment": str}.

    Подсказка: модели любят обрамлять JSON в ```json ... ``` — снимите обрамление
    перед json.loads(), иначе разбор упадёт на первом же вопросе.
    """
    raise NotImplementedError("П6: реализуйте вызов судьи и разбор вердикта")


def run() -> None:
    """Прогнать датасет и напечатать отчёт. Готово, менять не нужно."""
    cases = json.loads(DATASET.read_text(encoding="utf-8"))
    if len(cases) < 10:
        print(f"ВНИМАНИЕ: в датасете {len(cases)} вопросов, по критериям П6 нужно 10.\n")

    orchestrator = Orchestrator()
    judge_llm = build_client()
    scores: dict[str, list[float]] = {
        "faithfulness": [], "answer_relevance": [], "context_precision": []
    }

    try:
        for case in cases:
            # Своя сессия на вопрос: иначе память от прошлого вопроса исказит оценку
            session_id = f"test:{uuid.uuid4()}"
            answer = orchestrator.handle(session_id, case["question"])
            verdict = judge(judge_llm, case["question"], answer, case.get("expected", ""))

            for metric in scores:
                scores[metric].append(float(verdict.get(metric, 0.0)))

            flag = "ГАЛЛЮЦИНАЦИЯ" if float(verdict.get("faithfulness", 1)) < 0.5 else "ok"
            print(f"[{case['id']:>2}] {flag:<13} "
                  f"F={verdict.get('faithfulness')} "
                  f"AR={verdict.get('answer_relevance')} "
                  f"CP={verdict.get('context_precision')}")
            print(f"     вопрос: {case['question']}")
            print(f"     ответ:  {answer[:160]}")
            print(f"     судья:  {verdict.get('comment', '')}\n")
    finally:
        orchestrator.close()

    print("--- Сводка ---")
    for metric, values in scores.items():
        if values:
            print(f"{metric:<18} {statistics.mean(values):.2f}")
    hallucinations = sum(1 for v in scores["faithfulness"] if v < 0.5)
    print(f"Галлюцинаций: {hallucinations} из {len(cases)}")


if __name__ == "__main__":
    run()
