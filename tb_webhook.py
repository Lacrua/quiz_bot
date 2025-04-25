import os
import json
import traceback
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.exceptions import TelegramBadRequest
from database import pool as ydb_pool
import ydb
import handlers

# Настройка базового логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Создаем один раз при запуске
dp = Dispatcher()
# Роутеры включаются в диспетчер
dp.include_router(handlers.router) # handlers импортирован явно

API_TOKEN = os.getenv("API_TOKEN")
if not API_TOKEN:
    logger.error("API_TOKEN environment variable not set!")
    raise ValueError("API_TOKEN environment variable not set!")

bot = Bot(token=API_TOKEN)

logger.info("Bot and Dispatcher initialized.")
logger.info(f"YDB Pool imported and ready: {ydb_pool is not None}")


async def process_event(event: dict):
    """
    Processes a single incoming event from the webhook.
    """
    log_event = event.copy()
    if 'body' in log_event and isinstance(log_event['body'], str) and len(log_event['body']) > 500:
        log_event['body'] = log_event['body'][:500] + '...'
    logger.info(f"Received event: {json.dumps(log_event)}")

    body_str = event.get('body')
    if not body_str:
        logger.warning("Received event with no body.")
        raise ValueError("Нет тела запроса")

    try:
        event_body = json.loads(body_str)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON body: {body_str[:200]}...", exc_info=True)
        raise ValueError("Некорректное тело запроса (не JSON)") from e

    try:
        # Хэндлеры используют глобальный импортированный pool
        update = types.Update.model_validate(event_body, context={"bot": bot}) 
        await dp.feed_update(bot, update)
        logger.info("Event processed successfully.")
    except TelegramBadRequest as e:
        logger.warning(f"Telegram API bad request: {e}", exc_info=True)
        pass # Считаем обработку успешной для Telegram

    except Exception as e:
        logger.error("Error processing update:", exc_info=True)
        raise # Пробрасываем исключение выше


async def webhook(event: dict, context: object) -> dict:
    """
    Entry point for the Yandex Cloud Function.
    Handles incoming HTTP requests from Telegram webhook.
    """
    if event and event.get('httpMethod') == 'POST':
        try:
            await process_event(event)
            return {'statusCode': 200, 'body': 'ok'}
        except Exception:
            # process_event уже залогировал специфичные ошибки
            return {'statusCode': 500}
    else:
        method = event.get('httpMethod', 'UNKNOWN') if event else 'None'
        logger.warning(f"Received non-POST request (method: {method}). Returning 405.")
        return {'statusCode': 405}
