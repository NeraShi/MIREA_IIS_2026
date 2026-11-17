"""
mcp_client.py — синхронная обёртка над MCP-сервером.

Транспорт: streamable-http (127.0.0.1:8765). stdio-транспорт нестабилен
на Windows + Python 3.13 (OSError 22 / TimeoutError на кириллице), поэтому
сервер поднимается отдельным процессом по HTTP. Чтобы Orchestrator()
оставался самодостаточным (как в шаблоне), сервер запускается автоматически
при первом MCPTools(), если порт ещё не слушается, и гасится при close()
или выходе процесса.
"""

import asyncio
import atexit
import json
import socket
import subprocess
import sys
import threading
import time
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from contracts import Chunk, Message

_SERVER = str(Path(__file__).parent / "mcp_server.py")
_HOST = "127.0.0.1"
_PORT = 8765
_URL = f"http://{_HOST}:{_PORT}/mcp"


class MCPTools:
    """Синхронный клиент MCP-сервера знаний."""

    def __init__(self, server_script: str = _SERVER, timeout: float = 120.0):
        self._server_script = server_script
        self._timeout = timeout
        self._session: ClientSession | None = None
        self._proc: subprocess.Popen | None = None

        # Самодостаточность: если сервер ещё не слушает порт — поднимаем его.
        self._ensure_server()

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._serving = self._submit(self._serve())
        self._submit(self._wait_ready()).result(timeout=timeout)

    # --- автозапуск сервера ---

    def _ensure_server(self) -> None:
        if self._port_open():
            # Сервер уже запущен — другим Orchestrator или вручную.
            # Мы его не гасим: им владеет тот, кто запустил.
            return
        log_path = Path(self._server_script).parent / "data" / "mcp_server.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = open(log_path, "w", encoding="utf-8")
        self._proc = subprocess.Popen(
            [sys.executable, self._server_script],
            stdout=log_file,
            stderr=log_file,
        )
        atexit.register(self._shutdown_server)

        for _ in range(120):  # 60 секунд
            if self._port_open():
                return
            if self._proc.poll() is not None:
                raise RuntimeError(
                    f"mcp_server.py упал с кодом {self._proc.returncode}. "
                    f"Смотрите {log_path}."
                )
            time.sleep(0.5)
        raise RuntimeError(f"mcp_server.py не поднялся за 60 секунд. Смотрите {log_path}.")

    @staticmethod
    def _port_open() -> bool:
        with socket.socket() as s:
            s.settimeout(0.5)
            return s.connect_ex((_HOST, _PORT)) == 0

    def _shutdown_server(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    # --- механика сессии ---

    def _spin(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    async def _serve(self) -> None:
        async with AsyncExitStack() as stack:
            read, write, _ = await stack.enter_async_context(
                streamablehttp_client(_URL)
            )
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
        self._shutdown_server()