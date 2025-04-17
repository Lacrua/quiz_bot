from aiogram import types
from aiogram import F
import random 
from aiogram.utils.keyboard import InlineKeyboardBuilder


# Вопросы и переменные
from quiz import quiz_data

questions = []
current_q_index = 0
correct_answers = 0

bot = None
def set_bot(instance):
    global bot
    bot = instance

def get_shuffled_questions():
    global questions
    questions = quiz_data.copy()
    random.shuffle(questions)

async def send_question(chat_id):
    global questions, current_q_index
    if current_q_index >= len(questions):
        await send_result(chat_id)
        return
    q = questions[current_q_index]
    options = q['options']
    correct_option = options[q['correct_option']]
    kb = generate_options_keyboard(options, correct_option)
    await bot.send_message(chat_id, q['question'], reply_markup=kb)

def generate_options_keyboard(answer_options, right_answer,):
    builder = InlineKeyboardBuilder()
    for option in answer_options:
        callback_data = "right" if option == right_answer else "wrong"
        builder.add(types.InlineKeyboardButton(text=option, callback_data=callback_data))
    builder.adjust(1)
    return builder.as_markup()

async def send_result(chat_id):
    global correct_answers
    await bot.send_message(chat_id, f"Вы ответили правильно на {correct_answers} из {len(questions)} вопросов.")
    # Кнопка "Начать заново"
    kb = generate_start_over_keyboard()
    await bot.send_message(chat_id, "Хотите пройти заново?", reply_markup=kb)

def generate_start_over_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="Начать заново", callback_data="restart"))
    return builder.as_markup()

async def handle_answer(callback: types.CallbackQuery):
    global current_q_index, correct_answers
    await callback.message.delete()
    if callback.data == "right":
        correct_answers += 1
    current_q_index += 1
    await send_question(callback.message.chat.id)

async def handle_restart(callback: types.CallbackQuery):
    global current_q_index, correct_answers
    get_shuffled_questions()
    current_q_index = 0
    correct_answers = 0
    await callback.message.delete()
    await send_question(callback.message.chat.id)

async def cmd_start(message: types.Message):
    global questions, current_q_index, correct_answers
    get_shuffled_questions()
    current_q_index = 0
    correct_answers = 0
    await message.answer("Да начнётся игра!")
    await send_question(message.chat.id)