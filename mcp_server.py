"""
mcp_server.py — MCP-сервер, отдающий инструменты работы со знаниями.

ГОТОВ ЦЕЛИКОМ. Студент его не пишет — это инфраструктура протокола (Л3).

Сервер публикует три инструмента:
  search(query, k)                    — семантический поиск по индексу
  search_filtered(query, filters, k)  — то же, но с фильтром по метаданным
  get_history(session_id, n)          — последние n реплик сессии

Оркестратор обращается к ним как MCP-клиент (mcp_client.py), а не прямым импортом.
В этом смысл: инструменты описаны схемой, вызываются по протоколу, и их набор
можно расширить, не трогая ядро.

Запускается автоматически как подпроцесс из mcp_client.py. Вручную — для отладки:
    python mcp_server.py
"""

from mcp.server.fastmcp import FastMCP

import config

mcp = FastMCP("iis-rag")


def _to_chunks(result: dict) -> list[dict]:
    """Разворачивает ответ ChromaDB в плоский список чанков."""
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]

    chunks = []
    for text, meta, distance in zip(documents, metadatas, distances):
        meta = meta or {}
        chunks.append({
            "text": text,
            "source": meta.get("source", ""),
            "page": meta.get("page", 0),
            "category": meta.get("category", ""),
            # ChromaDB настроена на косинусное расстояние; сходство = 1 - расстояние
            "score": round(1.0 - float(distance), 4),
        })
    return chunks


@mcp.tool()
def search(query: str, k: int = config.TOP_K) -> list[dict]:
    """Семантический поиск по базе знаний. Возвращает k наиболее близких фрагментов."""
    collection = config.get_collection()
    return _to_chunks(collection.query(query_texts=[query], n_results=k))


@mcp.tool()
def search_filtered(query: str, filters: dict, k: int = config.TOP_K) -> list[dict]:
    """Поиск с фильтром по метаданным.

    filters — словарь вида {"category": "regulations"} или {"source": "nk_rf.pdf"}.
    Пустой словарь равносилен обычному search.
    """
    collection = config.get_collection()
    where = filters or None
    if where and len(where) > 1:
        # ChromaDB требует явный оператор при нескольких условиях
        where = {"$and": [{key: value} for key, value in filters.items()]}
    return _to_chunks(collection.query(query_texts=[query], n_results=k, where=where))


@mcp.tool()
def get_history(session_id: str, n: int = config.MEMORY_WINDOW) -> list[dict]:
    """Последние n реплик сессии. Начинает работать после практики 5."""
    import memory

    return [
        {"role": m.role, "content": m.content, "timestamp": m.timestamp}
        for m in memory.window(session_id, n)
    ]


if __name__ == "__main__":
    mcp.run()
