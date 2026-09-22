"""
mcp_client.py — синхронная обёртка над MCP-сервером.

ГОТОВ ЦЕЛИКОМ. Студент его не пишет и не правит.

Зачем он нужен. MCP-сессия асинхронная и живёт поверх stdio подпроцесса, а
Streamlit и оркестратор — синхронные. Открывать сессию на каждый вызов нельзя:
подпроцесс заново поднимал бы ChromaDB и модель эмбеддингов, и один ответ занимал
бы десятки секунд. Поэтому здесь один фоновый поток с вечным event loop, в нём одна
долгоживущая сессия, а наружу торчат обычные синхронные методы.

Использование:
    tools = MCPTools()
    chunks = tools.search("как оформить самозанятость")
    tools.close()
"""

import asyncio
import json
import sys
import threading
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from contracts import Chunk, Message

_SERVER = str(Path(__file__).parent / "mcp_server.py")


class MCPTools:
    """Синхронный клиент MCP-сервера знаний."""

    def __init__(self, server_script: str = _SERVER, timeout: float = 120.0):
        self._timeout = timeout
        self._session: ClientSession | None = None

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._serving = self._submit(self._serve(server_script))
        self._submit(self._wait_ready()).result(timeout=timeout)

    # --- внутренняя механика ---

    def _spin(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    async def _serve(self, server_script: str) -> None:
        """Держит сессию открытой до close().

        Сессия открывается и закрывается внутри одной задачи. Иначе на выходе
        получается RuntimeError: стек ресурсов внутри опирается на cancel scope
        anyio, а тот обязан закрываться в той же задаче, в которой открыт.
        """
        params = StdioServerParameters(command=sys.executable, args=[server_script])
        async with AsyncExitStack() as stack:
            read, write = await stack.enter_async_context(stdio_client(params))
            self._session = await stack.enter_async_context(ClientSession(read, write))
            await self._session.initialize()
            self._ready.set()
            await self._stop.wait()

    async def _wait_ready(self) -> None:
        """Дождаться готовности сессии — или ошибки подключения, если она раньше."""
        ready = asyncio.ensure_future(self._ready.wait())
        serving = asyncio.wrap_future(self._serving)
        done, _ = await asyncio.wait({ready, serving}, return_when=asyncio.FIRST_COMPLETED)
        if serving in done:
            ready.cancel()
            serving.result()   # пробрасываем исходную ошибку, а не ждём таймаута

    async def _call(self, name: str, args: dict):
        # FastMCP разворачивает list[dict] в отдельный content-блок на каждый
        # элемент (mcp/server/fastmcp/server.py, _convert_to_content), поэтому
        # читаются все блоки, а не первый. Другие версии протокола кладут весь
        # массив в один блок — поддерживаются оба случая.
        result = await self._session.call_tool(name, args)
        blocks = [json.loads(block.text) for block in result.content]
        if len(blocks) == 1 and isinstance(blocks[0], list):
            return blocks[0]
        return blocks

    def call(self, name: str, **kwargs):
        """Вызвать инструмент по имени. Возвращает разобранный JSON-результат."""
        return self._submit(self._call(name, kwargs)).result(timeout=self._timeout)

    # --- инструменты ---

    def search(self, query: str, k: int | None = None) -> list[Chunk]:
        args = {"query": query}
        if k is not None:
            args["k"] = k
        return [Chunk(**item) for item in self.call("search", **args)]

    def search_filtered(self, query: str, filters: dict, k: int | None = None) -> list[Chunk]:
        args = {"query": query, "filters": filters}
        if k is not None:
            args["k"] = k
        return [Chunk(**item) for item in self.call("search_filtered", **args)]

    def get_history(self, session_id: str, n: int | None = None) -> list[Message]:
        args = {"session_id": session_id}
        if n is not None:
            args["n"] = n
        return [Message(**item) for item in self.call("get_history", **args)]

    def close(self) -> None:
        if not self._serving.done():
            self._loop.call_soon_threadsafe(self._stop.set)
            self._serving.result(timeout=self._timeout)
        self._loop.call_soon_threadsafe(self._loop.stop)
