import asyncio
from aiogram import Bot, Dispatcher, F
from handlers import cmd_start, handle_answer, handle_restart
import handlers
from config import API_TOKEN


bot = None
def set_bot(instance):
    global bot
    bot = instance


async def main():
    global bot
    bot = Bot(token=API_TOKEN)

    handlers.set_bot(bot)

    dp = Dispatcher()

    # Регистрация обработчиков
    dp.message.register(cmd_start)
    dp.callback_query.register(handle_answer, F.data.in_({"right", "wrong"}))
    dp.callback_query.register(handle_restart, F.data == "restart")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())