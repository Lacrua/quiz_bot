import logging
from database import pool, execute_update_query, execute_select_query, quiz_data
import ydb 
from aiogram.utils.keyboard import InlineKeyboardBuilder 
from aiogram import types


# Заводим логгер
logger = logging.getLogger(__name__)


def generate_options_keyboard(answer_options, right_answer):
    builder = InlineKeyboardBuilder()
    for option in answer_options:
        builder.add(types.InlineKeyboardButton(
            text=option,
            callback_data="right_answer" if option == right_answer else "wrong_answer")
        )
    builder.adjust(1)
    return builder.as_markup()


# pool добавлен как первый аргумент
async def get_question(pool: ydb.SessionPool, message: types.Message, user_id):
    logger.debug(f"User {user_id}: Getting question.")
    # Получение текущего вопроса из словаря состояний пользователя
    current_question_index = await get_quiz_index(pool, user_id) # Передаем pool
    logger.debug(f"User {user_id}: Current question index: {current_question_index}")

    # Улучшенная проверка на выход за пределы quiz_data
    if current_question_index is None or current_question_index < 0 or current_question_index >= len(quiz_data):
        logger.error(f"User {user_id}: Invalid question index {current_question_index} in get_question! Resetting state.")
        await reset_user_quiz_state(pool, user_id) # Передаем pool
        current_question_index = await get_quiz_index(pool, user_id) # Передаем pool
        if current_question_index is None or current_question_index < 0 or current_question_index >= len(quiz_data):
             logger.critical(f"User {user_id}: State reset failed or quiz_data is empty.")
             await message.answer("Критическая ошибка при подготовке квиза :( Обратитесь к администратору.")
             return

        # Если сброс помог и индекс стал валидным (обычно 0)
        question: str = quiz_data[current_question_index]['question']
        options: list[str] = quiz_data[current_question_index]['options']
        correct_option_index: int = quiz_data[current_question_index]['correct_option']
        kb = generate_options_keyboard(options, options[correct_option_index])
        sent_message = await message.answer("Произошла ошибка с индексом вопроса, но состояние сброшено. Начнем заново.")
        # Очищаем предыдущее сообщение перед отправкой первого вопроса после сброса
        await message.bot.delete_message(chat_id=message.chat.id, message_id=sent_message.message_id) # Удаляем сообщение "Произошла ошибка..."
        sent_message = await message.answer(question, reply_markup=kb)
        await update_last_question_message_id(pool, user_id, sent_message.message_id) # Сохраняем message_id
        return

    # Если индекс изначально валидный
    question: str = quiz_data[current_question_index]['question']
    options: list[str] = quiz_data[current_question_index]['options']
    correct_option_index: int = quiz_data[current_question_index]['correct_option']
    kb = generate_options_keyboard(options, options[correct_option_index])

    sent_message = await message.answer(question, reply_markup=kb)
    await update_last_question_message_id(pool, user_id, sent_message.message_id) # Сохраняем message_id
    logger.debug(f"User {user_id}: Sent question index {current_question_index}, message_id {sent_message.message_id}.")


# pool добавлен как первый аргумент
async def get_quiz_index(pool: ydb.SessionPool, user_id):
    logger.debug(f"User {user_id}: Getting quiz index.")
    query = """
        DECLARE $user_id AS Uint64;

        SELECT question_index, last_question_message_id
        FROM `quiz_state`
        WHERE user_id == $user_id;
    """
    # Ключ в словаре БЕЗ символа $, _format_kwargs добавит $
    params = {'user_id': user_id}
    results = await execute_select_query(pool, query, **params)
    logger.debug(f"User {user_id}: Quiz state query results: {results}")

    if len(results) == 0:
        logger.info(f"User {user_id}: No quiz state found, returning 0.")
        # Если нет состояния, сбросим его и вернем 0
        await reset_user_quiz_state(pool, user_id)
        return 0
    # Проверяем наличие ключа перед доступом
    # results[0] - это словарь после преобразования в database.py
    if "question_index" not in results[0] or results[0]["question_index"] is None:
        logger.warning(f"User {user_id}: Quiz index is missing or None, returning 0.")
        return 0

    index = results[0]["question_index"]
    logger.debug(f"User {user_id}: Found quiz index {index}.")
    return index


# pool добавлен как первый аргумент
async def update_quiz_index(pool: ydb.SessionPool, user_id, question_index):
    logger.debug(f"User {user_id}: Updating quiz index to {question_index}.")
    query = """
        DECLARE $user_id AS Uint64;
        DECLARE $question_index AS Uint64;

        UPSERT INTO `quiz_state` (`user_id`, `question_index`)
        VALUES ($user_id, $question_index);
    """
    # Ключи в словаре БЕЗ символа $
    params = {
        'user_id': user_id,
        'question_index': question_index,
    }

    await execute_update_query(
        pool,
        query,
        **params
    )
    logger.debug(f"User {user_id}: Quiz index updated.")

# Новая функция для обновления message_id
async def update_last_question_message_id(pool: ydb.SessionPool, user_id: int, message_id: int):
    logger.debug(f"User {user_id}: Updating last question message_id to {message_id}.")
    query = """
        DECLARE $user_id AS Uint64;
        DECLARE $message_id AS Uint64; -- Telegram message_id может быть большим, используем Uint64

        UPDATE `quiz_state`
        SET last_question_message_id = $message_id
        WHERE user_id == $user_id;
    """
    params = {
        'user_id': user_id,
        'message_id': message_id,
    }
    await execute_update_query(pool, query, **params)
    logger.debug(f"User {user_id}: Last question message_id updated.")


# pool добавлен как первый аргумент
async def get_user_score(pool: ydb.SessionPool, user_id: int) -> int:
    logger.debug(f"User {user_id}: Getting user score.")
    query = """
        DECLARE $user_id AS Uint64;

        SELECT score, last_question_message_id
        FROM `quiz_state`
        WHERE user_id == $user_id;
    """
    # Ключ в словаре БЕЗ символа $
    params = {'user_id': user_id}
    results = await execute_select_query(pool, query, **params)
    logger.debug(f"User {user_id}: User score query results: {results}")

    if results:
        # results[0] - это словарь
        score = results[0].get('score') # Используем .get() для безопасного доступа
        logger.debug(f"User {user_id}: Found score {score}.")
        return score or 0
    else:
        logger.info(f"User {user_id}: No quiz state found for score, resetting.")
        await reset_user_quiz_state(pool, user_id)
        return 0

# pool добавлен как первый аргумент
async def update_user_score(pool: ydb.SessionPool, user_id: int, score: int):
    logger.debug(f"User {user_id}: Updating user score to {score}.")
    query = """
        DECLARE $user_id AS Uint64;
        DECLARE $score AS Uint64;

        UPDATE `quiz_state`
        SET score = $score
        WHERE user_id == $user_id;
    """
    params = {'user_id': user_id, 'score': score}
    await execute_update_query(pool, query, **params)
    logger.debug(f"User {user_id}: Score updated.")

# pool добавлен как первый аргумент
async def reset_user_quiz_state(pool: ydb.SessionPool, user_id: int):
    logger.info(f"User {user_id}: Resetting quiz state.")
    query = """
        DECLARE $user_id AS Uint64;

        UPSERT INTO `quiz_state` (user_id, question_index, score, last_question_message_id)
        VALUES ($user_id, 0, 0, 0);
    """
    params = {'user_id': user_id}
    await execute_update_query(pool, query, **params)
    logger.info(f"User {user_id}: Quiz state reset.")

# Новая функция для получения message_id
async def get_last_question_message_id(pool: ydb.SessionPool, user_id: int) -> int | None:
    logger.debug(f"User {user_id}: Getting last question message_id.")
    query = """
        DECLARE $user_id AS Uint64;

        SELECT last_question_message_id
        FROM `quiz_state`
        WHERE user_id == $user_id;
    """
    params = {'user_id': user_id}
    results = await execute_select_query(pool, query, **params)
    logger.debug(f"User {user_id}: Last message_id query results: {results}")

    # results - это список словарей после преобразования в database.py
    if results and results[0].get('last_question_message_id') is not None:
        message_id = results[0]['last_question_message_id']
        logger.debug(f"User {user_id}: Found last message_id {message_id}.")
        return message_id
    else:
        logger.info(f"User {user_id}: No last message_id found, returning None.")
        return None
