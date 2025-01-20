import configparser
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router, F
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import Message
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, KeyboardButtonPollType
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import BotCommand, BotCommandScopeDefault
from aiogram.types import CallbackQuery
from aiogram.utils.chat_action import ChatActionSender
from aiogram.types import ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from html import escape
import asyncio
import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import requests
import uuid
import datetime
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_gigachat.chat_models import GigaChat
from random import randint

config = configparser.ConfigParser()
config.read("config.ini")

TG_TOKEN = config["Telegram"]["token"]
GC_TOKEN = config["GigaChat"]["token"]

llm = GigaChat(
    credentials=GC_TOKEN,
    scope="GIGACHAT_API_PERS",
    model="GigaChat",
    verify_ssl_certs=False
)

LANGUAGES = {"en": "🇬🇧 Английский",
             "fr": "🇫🇷 Французский",
             "it": "🇮🇹 Итальянский",
             "gr": "🇩🇪 Немецкий",
             "sp": "🇪🇸 Испанский"}

LEVELS = {"0": "Новичок A0",
          "A": "Начальный A1-A2",
          "B": "Продвинутый B1-B2",
          "C": "Профессиональный C1"}

logging.basicConfig(force=True, level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=TG_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())


class Form(StatesGroup):
    name = State()
    choose_language = State()
    choose_level = State()
    reminder_time_enter = State()
    study_translate = State()


class Keyboard:
    menu_button_1 = InlineKeyboardButton(text="🔤 Изучать слова",
                                         callback_data="study_words")
    menu_button_2 = InlineKeyboardButton(text="ℹ️ Изучать темы",
                                         callback_data="study_topics")
    menu_button_3 = InlineKeyboardButton(text="⏰ Настроить напоминания",
                                         callback_data="set_reminder")
    menu_keyboard = InlineKeyboardMarkup(inline_keyboard=[[menu_button_1, menu_button_2], [menu_button_3]])


class SomeMiddleware(BaseMiddleware):
    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any]
    ) -> Any:
        message: Message = data['event_update'].message
        chat_id = message.chat.id
        state: FSMContext = data.get('state')
        current_state = await state.get_state()

        async with aiosqlite.connect('bot.db') as db:
            if message.text[0] == '/':
                action = "use_command"
            else:
                action = "send_message"
                await db.execute("INSERT INTO messages (user_id, message, state, datetime) VALUES (?, ?, ?, ?)",
                                 (message.from_user.id, message.text, str(current_state), message.date))
            await db.execute("INSERT INTO logs (user_id, action, text, datetime) VALUES (?, ?, ?, ?)",
                             (message.from_user.id, action, message.text, message.date))

            await db.commit()

        async with aiosqlite.connect('bot.db') as db:
            cursor = await db.execute("SELECT * FROM users")
            rows = await cursor.fetchall()
            print('rows %s' % rows)

        if message.text != '/start' and current_state != Form.name:
            async with aiosqlite.connect('bot.db') as db:
                async with db.execute("SELECT id FROM users WHERE id = ?", (chat_id,)) as cursor:
                    if await cursor.fetchone() is None:
                        await bot.send_message(chat_id=chat_id,
                                               text='Вы не зарегистрированы! Зарегистрируйтесь, используя команду '
                                                    '/start')
                        return
        result = await handler(event, data)
        return result


@dp.message(CommandStart(), State(None))
async def cmd_start(message: Message, state: FSMContext):
    async with aiosqlite.connect('bot.db') as db:
        async with db.execute("SELECT id FROM users WHERE id = ?", (message.from_user.id,)) as cursor:
            if await cursor.fetchone() is None:
                await message.answer(f"Привет, {message.from_user.first_name}!\nДля начала работы введите Ваши "
                                     f"фамилию и имя:")
                await state.update_data(lastfirstname=f"{message.from_user.last_name} {message.from_user.first_name}")
                await state.set_state(Form.name)
                return
        await bot.send_message(chat_id=message.from_user.id,
                               text="Меню",
                               reply_markup=Keyboard.menu_keyboard)


@dp.message(Form.name)
async def name_enter(message: Message, state: FSMContext):
    if len(message.text.split()) != 2:
        await message.answer(
            f"Проверь правильность написания, для регистрации нужно ввести фамилию и имя.")
        return
    last_name, first_name = message.text.split()
    async with aiosqlite.connect('bot.db') as db:
        async with db.execute("SELECT id FROM users WHERE id = ?", (message.from_user.id,)) as cursor:
            await cursor.execute('INSERT INTO users (id, last_name, first_name) VALUES (?, ?, ?)',
                                 (message.from_user.id, last_name, first_name))
            await db.commit()
    await state.clear()

    button_1 = KeyboardButton(text=LANGUAGES['en'])
    button_2 = KeyboardButton(text=LANGUAGES['fr'])
    button_3 = KeyboardButton(text=LANGUAGES['it'])
    button_4 = KeyboardButton(text=LANGUAGES['gr'])
    button_5 = KeyboardButton(text=LANGUAGES['sp'])
    button_6 = KeyboardButton(text="❌ Отмена")
    keyboard = ReplyKeyboardMarkup(keyboard=[[button_1, button_2, button_3], [button_4, button_5], [button_6]],
                                   resize_keyboard=True)

    await state.set_state(Form.choose_language)
    await message.answer(text=f"Данные зарегистрированы!\n\n"
                              f"Теперь необходимо выбрать язык для изучения на клавиатуре.",
                         reply_markup=keyboard)


@dp.message(Command("help"))
async def cmd_help(message: Message):
    async with aiosqlite.connect('bot.db') as db:
        cursor = await db.execute("SELECT * FROM logs")
        rows = await cursor.fetchall()
        print('rows %s' % rows)
    await message.answer("Вот список доступных команд:\n"
                         "/help – Показать описание команд\n"
                         "/choose – Выбор или смена изучаемого языка\n"
                         "/set_time – Поставить напоминание с новым словом для изучения (доступно только после выбора "
                         "языка)")


@dp.message(Command("choose"))
async def cmd_choose(message: Message, state: FSMContext):
    button_1 = KeyboardButton(text=LANGUAGES['en'])
    button_2 = KeyboardButton(text=LANGUAGES['fr'])
    button_3 = KeyboardButton(text=LANGUAGES['it'])
    button_4 = KeyboardButton(text=LANGUAGES['gr'])
    button_5 = KeyboardButton(text=LANGUAGES['sp'])
    button_6 = KeyboardButton(text="❌ Отмена")
    keyboard = ReplyKeyboardMarkup(keyboard=[[button_1, button_2, button_3], [button_4, button_5], [button_6]],
                                   resize_keyboard=True)
    async with aiosqlite.connect('bot.db') as db:
        cursor = await db.execute("SELECT current_language FROM users WHERE id = (?)", (message.from_user.id,))
        language = await cursor.fetchone()
        language = language[0]

    if language == "":
        await message.answer(text="Выберете язык из доступных на клавиатуре.",
                             reply_markup=keyboard)
    else:
        await message.answer(text="❗️У вас уже выбран язык. При выборе другого прогресс будет потерян. \n\nЕсли вы "
                                  "хотите выйти из выбора языка для изучения, выберите кнопку  ❌ Отмена. Иначе "
                                  "выберете язык из доступных на клавиатуре.",
                             reply_markup=keyboard)
    await state.set_state(Form.choose_language)


@dp.message(Form.choose_language)
async def choose_language(message: Message, state: FSMContext):
    if message.text not in LANGUAGES.values():
        if message.text == "❌ Отмена":
            await message.answer(text="Хорошо! Отменяю выбор языка.",
                                 reply_markup=ReplyKeyboardRemove())
            await state.clear()
            return

        await message.answer(text="Такой язык пока что недоступен, вы можете выбрать другой на клавиатуре")
        return
    for code, language in LANGUAGES.items():
        if language == message.text:
            async with aiosqlite.connect('bot.db') as db:
                await db.execute('UPDATE users SET (current_language) = (?) WHERE id = (?)',
                                 (code, message.from_user.id))
                await db.execute('DELETE FROM words WHERE user_id = (?)',
                                 (message.from_user.id,))
                await db.commit()

            button_1 = KeyboardButton(text="Новичок A0")
            button_2 = KeyboardButton(text="Начальный A1-A2")
            button_3 = KeyboardButton(text="Продвинутый B1-B2")
            button_4 = KeyboardButton(text="Профессиональный C1")
            keyboard = ReplyKeyboardMarkup(keyboard=[[button_1, button_2], [button_3, button_4]],
                                           resize_keyboard=True)
            await message.answer(text=f"Вы выбрали {message.text} язык.\n\nТеперь необходимо выбрать "
                                      f"уровень языка на клавиатуре.",
                                 reply_markup=keyboard)
            await state.set_state(Form.choose_level)


@dp.message(Form.choose_level)
async def choose_language(message: Message, state: FSMContext):
    for code, level in LEVELS.items():
        if level == message.text:
            async with aiosqlite.connect('bot.db') as db:
                await db.execute('UPDATE users SET (current_level) = (?) WHERE id = (?)',
                                 (code, message.from_user.id))
                await db.commit()
                await message.answer(
                    text="Хорошо, записал ваш уровень. Буду рекомендовать темы и слова именно по вашему "
                         "уровню!",
                    reply_markup=ReplyKeyboardRemove())
                await state.clear()
                return
    await message.answer(text="Выбирете что-то на клавиатуре.")


@dp.message(Command("menu"))
async def cmd_menu(message: Message):
    await message.answer(text="Меню",
                         reply_markup=Keyboard.menu_keyboard)


@dp.callback_query(F.data == "study_words")
async def callback_study_words(callback: CallbackQuery, state: FSMContext):
    async with aiosqlite.connect('bot.db') as db:
        async with db.execute("SELECT * FROM words WHERE user_id = (?) and repeat > 0",
                              (callback.from_user.id,)) as cursor:
            results = await cursor.fetchall()
            print(results)
            if len(results) > 0 and randint(1, 10) % 2 == 0:
                foreign_word = results[randint(0, len(results) - 1)][1]
                print(foreign_word)
                await state.update_data(word=foreign_word)
                await state.set_state(Form.study_translate)
                exit_button = InlineKeyboardButton(text="Отмена",
                                                   callback_data="exit")
                await bot.send_message(chat_id=callback.from_user.id,
                                       text=f"Давайте повторим слово {foreign_word}\n"
                                            f"Вам необходимо написать его перевод",
                                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[[exit_button]]))
                await callback.answer()
                return

        async with db.execute("SELECT * FROM users WHERE id = (?)", (callback.from_user.id,)) as cursor:
            async for row in cursor:
                user_lang, user_lvl = LANGUAGES[row[3]], LEVELS[row[4]]

                norm = True
                while norm:
                    try:
                        messages = [SystemMessage(
                            content=f"Ты бот-репетитор по {user_lang}, с тобой занимается пользователь уровня "
                                    f"{user_lvl}, ты помогаешь пользователю изучать язык."
                        ), HumanMessage(content='Предложи новое слово. Формат ответа: "(слово, перевод этого слова)". '
                                                'Не пиши ничего лишнего.')]
                        res = llm.invoke(messages)
                        foreign_word, russian_word = res.content.replace('(', '').replace(')', '').split(', ')
                        messages.append(res)
                        norm = False
                    except:
                        print("Ошибка: глупая нейронка")

                await bot.send_message(chat_id=callback.from_user.id,
                                       text=f'Новое слово для изучения – {foreign_word}\n'
                                            f'Оно означает "{russian_word}"')
                await db.execute("INSERT INTO words (user_id, word, translation, repeat) VALUES (?, ?, ?, ?)",
                                 (callback.from_user.id, foreign_word, russian_word, 2))
                await db.commit()
                await callback.answer()


@dp.message(Form.study_translate)
async def study_translate(message: Message, state: FSMContext):
    foreign_word = await state.get_data()
    foreign_word = foreign_word['word']
    messages = [HumanMessage(content=f"Тебе нужно проверить: совпадает ли {foreign_word} с переводом {message.text}. "
                                     f"Напиши только Да или Нет.")]
    res = llm.invoke(messages)
    if res.content.lower() == "да":
        await message.answer("Правильно!")
        async with aiosqlite.connect('bot.db') as db:
            async with db.execute("SELECT * FROM words WHERE user_id = (?) and word = (?)",
                                  (message.from_user.id, foreign_word)) as cursor:
                async for row in cursor:
                    repeat = row[3]
                    await db.execute("UPDATE words SET repeat = (?) WHERE user_id = (?) and word = (?)",
                                     (repeat - 1, message.from_user.id, foreign_word))
                    await db.commit()
    else:
        await message.answer("Неправильно, повтори попытку")

    await state.clear()


@dp.callback_query(F.data == "exit")
async def exit_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await bot.send_message(chat_id=callback.from_user.id,
                           text="Меню",
                           reply_markup=Keyboard.menu_keyboard)
    await callback.answer()


@dp.callback_query(F.data == "study_topics")
async def study_topics(callback: CallbackQuery):
    async with aiosqlite.connect('bot.db') as db:
        async with db.execute("SELECT * FROM users WHERE id = (?)", (callback.from_user.id,)) as cursor:
            async for row in cursor:
                user_lang, user_lvl = LANGUAGES[row[3]], LEVELS[row[4]]
                messages = [SystemMessage(content=f"Ты бот-репетитор по {user_lang}, с тобой занимается пользователь "
                                                  f"уровня {user_lvl}, ты помогаешь пользователю изучать язык."),
                            HumanMessage(content=f"Нужно доступно объяснить любую тему по грамматике")]
                res = llm.invoke(messages)
                await bot.send_message(chat_id=callback.from_user.id,
                                       text=res.content)
                await callback.answer()


@dp.message(Command("on"))
async def cmd_on(message: Message, state: FSMContext):
    async with aiosqlite.connect('bot.db') as db:
        user_language = await db.execute('SELECT current_language FROM users WHERE id = (?) AND current_language <> ""',
                                         (message.from_user.id,))
        user_language = await user_language.fetchone()
        if user_language is None:
            await message.answer(text="Вы сможете настроить уведомления после выбора изучаемого языка\n\n"
                                      "Подсказка: /choose")
            return
        await message.answer("Для установления времени напоминания введите час, в который я буду тебе писать.\n\n"
                             "Например: 13\n"
                             "Тогда я буду отправлять напоминание в 13.00 по МСК\n"
                             "Для отмены напиши слово Отмена")
        await state.set_state(Form.reminder_time_enter)


@dp.callback_query(F.data == "set_reminder")
async def callback_set_reminder(callback: CallbackQuery, state: FSMContext):
    async with aiosqlite.connect('bot.db') as db:
        user_language = await db.execute('SELECT current_language FROM users WHERE id = (?) AND current_language <> ""',
                                         (callback.from_user.id,))
        user_language = await user_language.fetchone()
        if user_language is None:
            await bot.send_message(chat_id=callback.from_user.id,
                                   text="Вы сможете настроить уведомления после выбора изучаемого языка\n\n"
                                        "Подсказка: /choose")
            await callback.answer()
            return
        await bot.send_message(chat_id=callback.from_user.id,
                               text="Для установления времени напоминания введите час, в который я буду тебе "
                                    "писать.\n\n"
                                    "Например: 13\n"
                                    "Тогда я буду отправлять напоминание в 13.00 по МСК\n"
                                    "Для отмены напиши слово Отмена")
        await callback.answer()
        await state.set_state(Form.reminder_time_enter)


@dp.message(Form.reminder_time_enter)
async def time_enter(message: Message, state: FSMContext):
    if message.text == "Отмена":
        await state.clear()
        await message.answer("Хорошо, вернул в меню.")
        return

    try:
        number = int(message.text)
    except:
        number = 100

    if number < 0 or number > 23:
        await message.answer("Введено неправильное значение, попробуйте снова.")
        return

    async with aiosqlite.connect('bot.db') as db:
        await db.execute('UPDATE users SET (reminder) = (?) WHERE id = (?)',
                         (number, message.from_user.id))
        await db.commit()

    await message.answer(f"⏰ Хорошо! Буду уведомлять вас в {number} часов каждый день.\n\n"
                         f"Для выключения напоминаний используйте команду /off")
    await bot.send_message(chat_id=message.from_user.id,
                           text="Меню",
                           reply_markup=Keyboard.menu_keyboard)
    await state.clear()


@dp.message(Command("off"))
async def cmd_off(message: Message):
    async with aiosqlite.connect('bot.db') as db:
        await db.execute('UPDATE users SET reminder = null WHERE id = (?)',
                         (message.from_user.id,))
        await db.commit()
    await message.answer("Вы отключили напоминания.")


@dp.message(State(None))
async def prtext(message: Message):
    async with aiosqlite.connect('bot.db') as db:
        async with db.execute("SELECT * FROM users WHERE id = (?)", (message.from_user.id,)) as cursor:
            async for row in cursor:
                user_lang, user_lvl = LANGUAGES[row[3]], LEVELS[row[4]]
                messages = [SystemMessage(content=f"Ты бот-репетитор по {user_lang}, с тобой занимается пользователь "
                                                  f"уровня {user_lvl}, ты помогаешь пользователю изучать язык. "
                                                  f"Если вопрос не связан с изучением языка, скажи, что ты не можешь "
                                                  f"ничего сказать по этой теме – это важно. Тебе нельзя разговаривать "
                                                  f"на другие темы."),
                            HumanMessage(content=message.text)]
                res = llm.invoke(messages)
                await bot.send_message(chat_id=message.from_user.id,
                                       text=res.content)


async def start_bot():
    commands = [BotCommand(command='menu', description='Открыть меню'),
                BotCommand(command='choose', description='Выбор или смена изучаемого языка'),
                BotCommand(command='on', description='Выбрать время напоминания для изучения'),
                BotCommand(command='off', description='Отключить напоминание'),
                BotCommand(command='help', description='Подсказка со всеми командами')]
    await bot.set_my_commands(commands, BotCommandScopeDefault())


async def start_db():
    async with aiosqlite.connect('bot.db') as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER,
                last_name TEXT,
                first_name TEXT,
                current_language TEXT,
                current_level TEXT,
                reminder INTEGER
            )
        ''')
        await db.commit()

        await db.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                user_id INTEGER,
                action TEXT,
                text TEXT,
                datetime TEXT
            )
        ''')

        await db.execute('''
            CREATE TABLE IF NOT EXISTS words (
                user_id INTEGER,
                word TEXT,
                translation TEXT,
                repeat INTEGER
            )
        ''')
        await db.commit()


async def send_msg(dp):
    hours = datetime.datetime.now().hour

    async with aiosqlite.connect('bot.db') as db:
        if hours == 0:
            async with db.execute("SELECT * FROM users WHERE reminder IS NOT NULL AND reminder > 24") as cursor:
                async for row in cursor:
                    await db.execute("UPDATE users SET (reminder) = (?) WHERE id = (?)", (row[5] // 100, row[0]))

        async with db.execute("SELECT * FROM users WHERE reminder IS NOT NULL AND reminder < 25") as cursor:
            async for row in cursor:
                user_time = row[5]
                if user_time == hours:
                    await bot.send_message(chat_id=row[0], text='⏰ Пора изучать новые слова')
                    await db.execute("UPDATE users SET (reminder) = (?) WHERE id = (?)", (user_time * 100, row[0]))
        await db.commit()


async def main():
    scheduler = AsyncIOScheduler(timezone='Europe/Moscow')
    job = scheduler.add_job(send_msg, 'interval', seconds=10, args=(dp,))
    scheduler.start()
    dp.message.outer_middleware(SomeMiddleware())
    dp.startup.register(start_bot)
    dp.startup.register(start_db)
    try:
        print("Бот запущен")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.remove_job(job.id)
        await bot.session.close()
        print("Бот остановлен")


asyncio.run(main())
