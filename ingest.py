"""
ingest.py — сбор исходных данных и наполнение векторного индекса.

ПРАКТИКА 2. Что делает студент:
  1. clean_text()  — предварительная очистка: переносы, колонтитулы, мусорные пробелы
  2. chunk_text()  — нарезка на чанки фиксированного размера с перекрытием
  3. detect_category() — рубрикация чанка; словарь рубрик задаёте вы под свой домен

  4. черновик gold_dataset.json — 5 вопросов с указанием файлов-источников

Готово и трогать не нужно: обход data/raw/, чтение PDF и TXT, запись в ChromaDB,
замер hit-rate в evaluate_retrieval().

Каждый запуск пересобирает индекс с нуля — коллекция очищается перед наполнением.
Поэтому при подборе параметров достаточно поправить CHUNK_SIZE или CHUNK_OVERLAP
в config.py и запустить ingest.py снова: удалять data/chroma/ руками не нужно.

Критерии приёмки:
  - python ingest.py отрабатывает без ошибок, коллекция непуста
  - у каждого чанка заполнены source, page и category; пустых category нет
  - поиск с фильтром по category возвращает чанки только этой категории
  - в gold_dataset.json не меньше 5 вопросов, у каждого заполнено expected_sources
  - показаны не менее двух замеров с разными CHUNK_SIZE / CHUNK_OVERLAP,
    и выбор итоговых значений объяснён числом, а не вкусом
  - CHUNK_SIZE и CHUNK_OVERLAP берутся из config.py, а не зашиты в код

Про метрику. hit-rate@k отвечает на один вопрос: попал ли фрагмент с ответом
в первые k результатов. Считается механически, сверкой поля source с ожидаемым —
ни модели, ни судьи для этого не нужно, поэтому мерить можно уже здесь, на П2.
Не путайте её с Context Precision из триады RAG: та оценивает, насколько найденное
относится к делу, её считает LLM-судья, и появляется она только на П6. В плане
дисциплины обе назывались «точностью извлечения контекста», хотя это разные вещи.

Запуск:
    python ingest.py          # проиндексировать и сразу замерить
    python ingest.py --eval   # только замер, без переиндексации
"""

import hashlib
from pathlib import Path

import config


# --- Читатели форматов: готовы ---

def read_txt(path: Path) -> list[tuple[int, str]]:
    """Возвращает [(номер страницы, текст)]. У TXT страниц нет, поэтому страница 0."""
    return [(0, path.read_text(encoding="utf-8", errors="ignore"))]


def read_pdf(path: Path) -> list[tuple[int, str]]:
    """Возвращает [(номер страницы, текст)] — постранично, чтобы метаданное page было честным."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]


READERS = {".txt": read_txt, ".md": read_txt, ".pdf": read_pdf}


# --- Ваша часть (П2) ---

def clean_text(text: str) -> str:
    r"""Очистить сырой текст перед нарезкой.

    Что обычно нужно убрать: разрывы слов по переносу строки, повторяющиеся
    колонтитулы, номера страниц отдельной строкой, цепочки пробелов и пустых строк.

    Подсказка: начните с re.sub(r"-\n", "", text) и r"\s+" -> " ", посмотрите
    на результат глазами и добавьте правила под свои исходные данные.
    """
    raise NotImplementedError("П2: реализуйте очистку текста")


def chunk_text(text: str, size: int = config.CHUNK_SIZE,
               overlap: int = config.CHUNK_OVERLAP) -> list[str]:
    """Нарезать текст на чанки размером size с перекрытием overlap.

    Перекрытие нужно, чтобы мысль, попавшая на границу нарезки, не потерялась:
    её хвост окажется в начале следующего чанка.

    Следите за двумя вещами: шаг сдвига равен size - overlap (не size), и
    overlap обязан быть меньше size, иначе цикл не сойдётся.
    """
    raise NotImplementedError("П2: реализуйте нарезку с перекрытием")


def detect_category(text: str, source: str) -> str:
    """Определить рубрику чанка.

    Словарь рубрик — ваш проектный выбор, он зависит от домена. Для налогового
    консультанта это может быть "law" | "faq" | "forms"; для ассистента абитуриента —
    "admission" | "dormitory" | "schedule".

    Достаточно правил по имени файла и ключевым словам — LLM здесь не нужна.
    Пустых категорий быть не должно: заведите рубрику по умолчанию.
    """
    raise NotImplementedError("П2: реализуйте рубрикацию")


# --- Сборка индекса: готова ---

def ingest() -> int:
    """Обходит исходные данные, нарезает и складывает в ChromaDB. Возвращает число чанков.

    Индекс собирается заново с нуля: коллекция очищается перед наполнением.
    Иначе после смены CHUNK_SIZE в коллекции остались бы чанки предыдущей
    нарезки, и hit-rate@5 замерялся бы по смеси двух — молча, без ошибки.
    """
    collection = config.reset_collection()
    total = 0

    # README.md отсеивается намеренно: это шаблонная заглушка каталога,
    # а не документ предметной области. Без отсева она попадает в индекс
    # и выдаётся поиском как знание.
    files = [p for p in config.RAW_DIR.rglob("*")
             if p.suffix.lower() in READERS and p.name != "README.md"]
    if not files:
        raise SystemExit(f"В {config.RAW_DIR} нет файлов .txt/.md/.pdf — положите исходные данные (П2).")

    for path in files:
        for page, raw in READERS[path.suffix.lower()](path):
            cleaned = clean_text(raw)
            if not cleaned:
                continue

            for chunk in chunk_text(cleaned):
                # id детерминированный: одинаковый текст даёт один и тот же чанк,
                # поэтому дубли не возникают даже внутри одного прогона
                chunk_id = hashlib.sha1(
                    f"{path.name}:{page}:{chunk}".encode("utf-8")
                ).hexdigest()

                collection.upsert(
                    ids=[chunk_id],
                    documents=[chunk],
                    metadatas=[{
                        "source": path.name,
                        "page": page,
                        "category": detect_category(chunk, path.name),
                    }],
                )
                total += 1

    return total


# --- Замер качества поиска: готов ---

def evaluate_retrieval(k: int = config.TOP_K) -> float:
    """hit-rate@k по черновику Gold Dataset. Готово, менять не нужно.

    Для каждого вопроса выполняется поиск и проверяется, попал ли в первые k
    результатов хотя бы один чанк из ожидаемых источников.

    Вопросы с пустым expected_sources пропускаются: это проверка отказа отвечать,
    а она требует LLM и меряется на П6, а не здесь.

    Обращается к коллекции напрямую, а не через MCP: на П2 оркестратора ещё нет.
    """
    import json

    dataset_path = Path(__file__).parent / "gold_dataset.json"
    cases = [c for c in json.loads(dataset_path.read_text(encoding="utf-8"))
             if c.get("expected_sources")]

    if not cases:
        print("В gold_dataset.json нет вопросов с expected_sources — замерять нечего (П2).")
        return 0.0

    collection = config.get_collection()
    hits = 0

    print(f"\nhit-rate@{k}  |  чанк {config.CHUNK_SIZE}, overlap {config.CHUNK_OVERLAP}")
    for case in cases:
        result = collection.query(query_texts=[case["question"]], n_results=k)
        found = {(m or {}).get("source", "") for m in (result.get("metadatas") or [[]])[0]}
        hit = bool(found & set(case["expected_sources"]))
        hits += hit
        print(f"  [{'+' if hit else '-'}] {case['question'][:70]}")
        if not hit:
            print(f"      ожидалось: {case['expected_sources']}, найдено: {sorted(found)}")

    rate = hits / len(cases)
    print(f"\nhit-rate@{k} = {rate:.0%}  ({hits} из {len(cases)})")
    skipped = len(json.loads(dataset_path.read_text(encoding="utf-8"))) - len(cases)
    if skipped:
        print(f"Пропущено вопросов без expected_sources: {skipped} — они меряются на П6.")
    return rate


if __name__ == "__main__":
    import sys

    if "--eval" not in sys.argv:
        count = ingest()
        print(f"Индекс пересобран заново. Проиндексировано чанков: {count}")
        print(f"Всего в коллекции: {config.get_collection().count()}")

    evaluate_retrieval()
