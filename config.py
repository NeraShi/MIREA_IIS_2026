"""
config.py — конфигурация и общие ресурсы проекта.

Готов целиком. Студент правит только значения констант под свой домен (П2, П5)
и никогда не трогает get_collection().

Почему клиент ChromaDB живёт здесь, а не в ingest.py: модель эмбеддингов должна
быть одна и та же при записи индекса (ingest.py) и при чтении (mcp_server.py).
Если развести это по двум файлам, рано или поздно они разъедутся — и поиск начнёт
молча возвращать мусор вместо ошибки. Одна точка создания коллекции это исключает.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
CHROMA_DIR = DATA_DIR / "chroma"
DB_PATH = DATA_DIR / "memory.db"
SECURITY_LOG = BASE_DIR / "security_logs.txt"

# --- Параметры RAG (подбираются на П2) ---
COLLECTION_NAME = "knowledge_base"
EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
CHUNK_SIZE = 512      # символов в чанке
CHUNK_OVERLAP = 64    # перекрытие между соседними чанками
TOP_K = 5             # сколько чанков возвращает поиск

# --- Параметры памяти (подбираются на П5) ---
MEMORY_WINDOW = 10    # сколько последних сообщений уходит в контекст LLM

# --- LLM ---
LLM_BACKEND = os.getenv("LLM_BACKEND", "gigachat")
GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS", "")
GIGACHAT_MODEL = os.getenv("GIGACHAT_MODEL", "GigaChat")
GIGACHAT_VERIFY_SSL = os.getenv("GIGACHAT_VERIFY_SSL", "false").lower() == "true"
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "deepseek-r1:1.5b")

# --- Экономика (П8) ---
# Цена за 1 000 000 токенов в рублях. Тарифы меняются — подставьте актуальные
# из личного кабинета провайдера и укажите в отчёте дату, на которую они взяты.
# Вход и выход тарифицируются по-разному, поэтому это две константы, а не одна.
PRICE_INPUT_PER_1M = 0.0
PRICE_OUTPUT_PER_1M = 0.0

# --- Каналы ---
VK_TOKEN = os.getenv("VK_TOKEN", "")


def _client():
    import chromadb
    from chromadb.config import Settings

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    # Телеметрия выключена: она ходит в сеть, которой в аудитории может не быть.
    # Сама по себе эта настройка вывод не чистит — от сообщений
    # "Failed to send telemetry event" спасает пин posthog<4 в requirements.txt.
    return chromadb.PersistentClient(
        path=str(CHROMA_DIR),
        settings=Settings(anonymized_telemetry=False),
    )


def get_collection():
    """Единственная точка доступа к коллекции ChromaDB. Создаёт её при первом вызове."""
    from chromadb.utils import embedding_functions

    embedder = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
    )
    return _client().get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedder,
        metadata={"hnsw:space": "cosine"},
    )


def reset_collection():
    """Удалить коллекцию целиком и создать пустую. Вызывается из ingest.py (П2).

    Нужна потому, что идентификатор чанка считается из его текста: при другом
    размере нарезки получаются другие идентификаторы, и старые чанки остаются
    в коллекции. Без сброса замер идёт по смеси двух нарезок, и заметить это
    по выводу невозможно — ошибки нет, просто число ни о чём.
    """
    client = _client()
    names = {c if isinstance(c, str) else c.name for c in client.list_collections()}
    if COLLECTION_NAME in names:
        client.delete_collection(COLLECTION_NAME)
    return get_collection()
