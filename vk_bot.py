"""
vk_bot.py — канал доставки в VK.

ГОТОВ ЦЕЛИКОМ. Студент его не пишет.

Адаптер намеренно тонкий: он переводит сообщение VK в вызов ядра и возвращает
ответ обратно. Ни поиска, ни промптов, ни проверок безопасности здесь нет — всё
это живёт в ядре и потому одинаково работает для обоих каналов. Если бы guardrail
стоял в app.py, как в первой редакции плана, этот файл был бы дырой в защите.

Запуск:
    python vk_bot.py
Требуется VK_TOKEN — токен сообщества с включёнными Long Poll и правом писать.
"""

import asyncio
import logging

from vkbottle.bot import Bot, Message as VkMessage

import config
from orchestrator import Orchestrator

logging.basicConfig(level=logging.INFO)

bot = Bot(token=config.VK_TOKEN)
orchestrator = Orchestrator()


@bot.on.private_message()
async def handle_message(message: VkMessage) -> None:
    session_id = f"vk:{message.peer_id}"
    text = (message.text or "").strip()

    if not text:
        await message.answer("Пришлите вопрос текстом.")
        return

    # handle() синхронный и ходит в сеть — уводим его с event loop бота,
    # иначе один медленный запрос заморозит всех остальных пользователей.
    answer = await asyncio.to_thread(orchestrator.handle, session_id, text)
    await message.answer(answer)


if __name__ == "__main__":
    if not config.VK_TOKEN:
        raise SystemExit("VK_TOKEN не задан. Заполните .env по образцу .env.example.")
    bot.run_forever()
