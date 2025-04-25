import logging
from aiogram import types, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from database import quiz_data, pool
from service import (
    get_quiz_index,
    update_quiz_index,
    get_user_score,
    update_user_score,
    reset_user_quiz_state,
    generate_options_keyboard,
    get_question,
    update_last_question_message_id, 
    get_last_question_message_id 
)
import ydb


logger = logging.getLogger(__name__)

router = Router()

# Функция для удаления предыдущего сообщения
async def delete_previous_message(message: types.Message, pool: ydb.SessionPool):
    user_id = message.from_user.id
    chat_id = message.chat.id
    last_message_id = await get_last_question_message_id(pool, user_id)
    if last_message_id:
        try:
            # Пытаемся удалить сообщение бота
            await message.bot.delete_message(chat_id=chat_id, message_id=last_message_id)
            logger.debug(f"User {user_id}: Deleted previous message {last_message_id} in chat {chat_id}.")
        except Exception as e:
            # Логируем ошибку, если не удалось удалить 
            logger.warning(f"User {user_id}: Failed to delete previous message {last_message_id} in chat {chat_id}: {e}")
    # Обнуляем message_id в БД после попытки удаления, даже если удаление не удалось
    await update_last_question_message_id(pool, user_id, 0)


# Обработчик команды /start
@router.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id: int = message.from_user.id
    logger.info(f"User {user_id}: Received /start command.")
    if pool is None:
        logger.critical(f"User {user_id}: Global YDB pool is None!")
        await message.answer("Произошла критическая ошибка с подключением к базе данных :( Попробуйте позже.")
        return
    # Удаляем предыдущее сообщение перед началом нового квиза
    await delete_previous_message(message, pool)

    await reset_user_quiz_state(pool, user_id)
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="Начать квиз"))
    await message.answer("Бобро поржаловать! Наржите 'Начать квиз' для старжа.", reply_markup=builder.as_markup(resize_keyboard=True))


# Обработчик команды /quiz или нажатия "Начать квиз"
@router.message(F.text == "Начать квиз")
@router.message(Command("quiz"))
async def cmd_quiz(message: types.Message):
    user_id: int = message.from_user.id
    logger.info(f"User {user_id}: Received /quiz or 'Начать квиз'.")
    if pool is None:
        logger.critical(f"User {user_id}: Global YDB pool is None!")
        await message.answer("Произошла критическая ошибка с подключением к базе данных :( Попробуйте позже.")
        return
    # Удаляем предыдущее сообщение перед началом нового квиза
    await delete_previous_message(message, pool)
    await reset_user_quiz_state(pool, user_id)
    await message.answer("Да начнётся игра!")
    # Передаем pool в get_question (он там нужен как аргумент)
    await get_question(pool, message, user_id)


# Обработчики для ответов
@router.callback_query(F.data == "right_answer")
async def handle_right_answer(callback: types.CallbackQuery):
    user_id: int = callback.from_user.id
    logger.debug(f"User {user_id}: Received right answer callback.")
    if pool is None:
         logger.critical(f"User {user_id}: Global YDB pool is None!")
         await callback.message.answer("Произошла критическая ошибка с подключением к базе данных :( Попробуйте позже.")
         await callback.answer()
         return
    # Удаляем клавиатуру предыдущего сообщения (сообщение с вопросом, на который ответили)
    try:
        await callback.bot.edit_message_reply_markup(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            reply_markup=None
        )
    except Exception as e:
         logger.warning(f"User {user_id}: Failed to edit message reply markup {callback.message.message_id}: {e}")


    current_question_index: int = await get_quiz_index(pool, user_id)

    # Проверяем валидность индекса перед доступом к quiz_data
    if current_question_index is None or current_question_index < 0 or current_question_index >= len(quiz_data):
         logger.error(f"User {user_id}: Invalid question index {current_question_index} in right answer callback. Resetting state.")
         await reset_user_quiz_state(pool, user_id)
         await callback.message.answer("Произошла ошибка состояния квиза :( Попробуйте начать заново.")
         await callback.answer()
         return # Важно выйти после обработки ошибки состояния

    current_score: int = await get_user_score(pool, user_id)
    current_score += 1
    await update_user_score(pool, user_id, current_score)
    await callback.message.answer("Верно!")

    current_question_index += 1
    await update_quiz_index(pool, user_id, current_question_index)

    if current_question_index < len(quiz_data):
        await get_question(pool, callback.message, user_id)
    else:
        total_score: int = await get_user_score(pool, user_id)
        await reset_user_quiz_state(pool, user_id)
        # Обнуляем message_id в БД при завершении квиза
        await update_last_question_message_id(pool, user_id, 0)
        await callback.message.answer(f"Это был последний вопрос! Ваш результат: {total_score} правильных ответов из 10.")
    await callback.answer() # Отвечаем на колбэк


# Обработчик для неправильных ответов
@router.callback_query(F.data == "wrong_answer")
async def handle_wrong_answer(callback: types.CallbackQuery):
    user_id: int = callback.from_user.id
    logger.debug(f"User {user_id}: Received wrong answer callback.")
    if pool is None:
         logger.critical(f"User {user_id}: Global YDB pool is None!")
         await callback.message.answer("Произошла критическая ошибка с подключением к базе данных :( Попробуйте позже.")
         await callback.answer()
         return

    # Удаляем клавиатуру предыдущего сообщения
    try:
        await callback.bot.edit_message_reply_markup(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            reply_markup=None
        )
    except Exception as e:
         logger.warning(f"User {user_id}: Failed to edit message reply markup {callback.message.message_id}: {e}")


    current_question_index: int = await get_quiz_index(pool, user_id)

    # Проверяем валидность индекса перед доступом к quiz_data
    if current_question_index is None or current_question_index < 0 or current_question_index >= len(quiz_data):
         logger.error(f"User {user_id}: Invalid question index {current_question_index} in wrong answer callback. Resetting state.")
         await reset_user_quiz_state(pool, user_id)
         await callback.message.answer("Произошла ошибка состояния квиза :( Попробуйте начать заново.")
         await callback.answer()
         return # Важно выйти после обработки ошибки состояния


    correct_option: int = quiz_data[current_question_index]['correct_option']
    correct_option_text: str = quiz_data[current_question_index]['options'][correct_option]

    await callback.message.answer(f"Неправильно. Правильный ответ: {correct_option_text}")

    current_question_index += 1
    await update_quiz_index(pool, user_id, current_question_index)

    if current_question_index < len(quiz_data):
        await get_question(pool, callback.message, user_id)
    else:
        total_score: int = await get_user_score(pool, user_id)
        await reset_user_quiz_state(pool, user_id)
        # Обнуляем message_id в БД при завершении квиза
        await update_last_question_message_id(pool, user_id, 0)
        await callback.message.answer(f"Это был последний вопрос! Ваш результат: {total_score} правильных ответов из 10.")
    await callback.answer() # Отвечаем на колбэк
