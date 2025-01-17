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

config = configparser.ConfigParser()
config.read("config.ini")

TG_TOKEN = config["Telegram"]["token"]
GC_TOKEN = config["GigaChat"]["token"]
rq_uid = str(uuid.uuid4())

url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"

payload = {
    'scope': 'GIGACHAT_API_PERS'
}
headers = {
    'Content-Type': 'application/x-www-form-urlencoded',
    'Accept': 'application/json',
    'RqUID': rq_uid,
    'Authorization': f'Basic {GC_TOKEN}'
}

response = requests.request("POST", url, headers=headers, data=payload, verify=False)
giga_token = response.json()["access_token"]

print(response.text)

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
            await db.execute("INSERT INTO messages (user_id, message, state, datetime) VALUES (?, ?, ?, ?)",
                             (message.from_user.id, message.text, str(current_state), message.date))

            if message.text[0] == '/':
                action = "use_command"
            else:
                action = "send_message"
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
    await message.answer(f"Привет, {message.from_user.first_name}!\nДля начала работы введите Ваши фамилию и имя:")
    await state.update_data(lastfirstname=f"{message.from_user.last_name} {message.from_user.first_name}")
    await state.set_state(Form.name)


@dp.message(Form.name)
async def name_enter(message: Message, state: FSMContext):
    if len(message.text.split()) != 2:
        await message.answer(
            f"Проверь правильность написания, для регистрации нужно ввести фамилию и имя.")
        return
    last_name, first_name = message.text.split()
    async with aiosqlite.connect('bot.db') as db:
        async with db.execute("SELECT id FROM users WHERE id = ?", (message.from_user.id,)) as cursor:
            await cursor.execute('INSERT INTO users (id, last_name, first_name, current_language, reminder) VALUES ('
                                 '?, ?, ?, ?, null)',
                                 (message.from_user.id, last_name, first_name, ""))
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
                await db.commit()

            button_0 = KeyboardButton(text="Пройти тест")
            button_1 = KeyboardButton(text="Новичок A0")
            button_2 = KeyboardButton(text="Начальный A1-A2")
            button_3 = KeyboardButton(text="Продвинутый B1-B2")
            button_4 = KeyboardButton(text="Профессиональный C1")
            keyboard = ReplyKeyboardMarkup(keyboard=[[button_0], [button_1, button_2], [button_3, button_4]],
                                           resize_keyboard=True)
            await message.answer(text=f"Вы выбрали {message.text} язык.\n\nТеперь необходимо выбрать "
                                      f"уровень языка или пройти тест на определение уровня. Выберете уровень "
                                      f"на клавиатуре или пройдите тест на уровень языка.",
                                 reply_markup=keyboard)
            await state.set_state(Form.choose_level)


@dp.message(Form.choose_level)
async def choose_language(message: Message, state: FSMContext):
    if message.text == "Пройти тест":
        pass
    else:
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


@dp.message(Command("on"))
async def cmd_set_time(message: Message):
    async with aiosqlite.connect('bot.db') as db:
        await db.execute('UPDATE users SET (reminder) = (?) WHERE id = (?)',
                         (13, message.from_user.id))
        await db.commit()


@dp.message(Command("off"))
async def cmd_set_time(message: Message):
    async with aiosqlite.connect('bot.db') as db:
        await db.execute('UPDATE users SET reminder = null WHERE id = (?)',
                         (message.from_user.id, ))
        await db.commit()


@dp.message(State(None))
async def prtext(message: Message):
    await message.answer("Не очень понимаю, о чем вы говорите. Воспользуйтесь командой /help или меню команд, "
                         "чтобы работать с ботом.")


async def start_bot():
    commands = [BotCommand(command='help', description='Подсказка со всеми командами'),
                BotCommand(command='choose', description='Выбор или смена изучаемого языка'),
                BotCommand(command='set_time', description='Выбрать время напоминания для изучения')]
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
            CREATE TABLE IF NOT EXISTS messages (
                user_id INTEGER,
                message TEXT,
                state TEXT,
                datetime TEXT
            )
        ''')

        await db.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                user_id INTEGER,
                action TEXT,
                text TEXT,
                datetime TEXT
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
