import logging
import aiohttp
import asyncio
import json
import random
import string
import os
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Command, Text
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiohttp import web

API_TOKEN = '6775113338:AAEelfoW-YxQhfEGjLw1_XCt7lIbVOsSW6g'

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

with open('admin_id.json', 'r') as f:
    admin_id = json.load(f)["admin_id"]

# Загрузка активных ключей
def load_keys():
    try:
        with open('active_keys.json', 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_keys():
    with open('active_keys.json', 'w') as f:
        json.dump(active_keys, f, indent=4)

active_keys = load_keys()

# Загрузка API токенов
def load_api_tokens():
    try:
        with open('api_tokens.json', 'r') as f:
            data = f.read().strip()  # Убираем возможные пробелы
            if not data:
                return []  # Если файл пуст, возвращаем пустой список
            return json.loads(data)
    except (FileNotFoundError, json.JSONDecodeError):
        logging.error("Файл с API токенами пуст или имеет неверный формат.")
        return []

api_tokens = load_api_tokens()

# Функция выбора случайного токена
def get_random_token():
    if api_tokens:
        return random.choice(api_tokens)  # Случайный выбор токена
    return None

button_create_link = KeyboardButton(text='Create Link')
button_create_key = KeyboardButton(text='Create Key')
button_reset = KeyboardButton(text='Reset')

markup_user = ReplyKeyboardMarkup(
    keyboard=[
        [button_create_link],
        [button_reset]
    ],
    resize_keyboard=True
)
markup_admin = ReplyKeyboardMarkup(
    keyboard=[
        [button_create_link],
        [button_create_key],
        [button_reset]
    ],
    resize_keyboard=True
)

class URLState(StatesGroup):
    url = State()
    number = State()

def is_key_valid(user_id):
    key_info = active_keys.get(user_id)
    if key_info:
        key, expiry = key_info
        if expiry > asyncio.get_event_loop().time():
            return True
    return False

@dp.message_handler(Command("start"))
async def send_welcome(message: types.Message):
    if message.from_user.id == admin_id:
        await message.reply(
            "Вы администратор. Используйте кнопку 'Create Key' для создания ключа.",
            reply_markup=markup_admin
        )
    else:
        if is_key_valid(message.from_user.id):
            await message.reply(
                "Нажмите на кнопку 'Create Link', чтобы создать короткие ссылки.",
                reply_markup=markup_user
            )
        else:
            await message.reply("Для доступа к боту, пожалуйста, введите активационный ключ.")

@dp.message_handler(Text(equals="Create Key"), user_id=admin_id)
async def handle_create_key(message: types.Message):
    key = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    expiry = asyncio.get_event_loop().time() + 86400
    active_keys[admin_id] = (key, expiry)
    save_keys()
    await message.reply(f"Ключ для активации: {key}\nЭтот ключ активен 24 часа.")

@dp.message_handler(Text(equals="Create Link"))
async def handle_create_link(message: types.Message, state: FSMContext):
    if message.from_user.id != admin_id and not is_key_valid(message.from_user.id):
        await message.reply("Вы не активированы. Введите активационный ключ.")
        return

    await state.finish()
    await message.reply("Введите URL (например, google.com):")
    await state.set_state(URLState.url.state)

@dp.message_handler(Text(equals="Reset"))
async def handle_reset(message: types.Message, state: FSMContext):
    await state.finish()
    await message.reply("Вы вернулись на начальный экран.", reply_markup=markup_user)

@dp.message_handler(state=URLState.url)
async def process_url(message: types.Message, state: FSMContext):
    if message.text == 'Reset':
        await handle_reset(message, state)
        return

    if not message.text or message.text == 'Create Link':
        await message.reply("Введите корректный URL.")
        return

    await state.update_data(url=message.text)
    await message.reply("Введите количество запросов:")
    await state.set_state(URLState.number.state)

# Функция для выполнения запросов с семафором для ограничения потоков
async def perform_request(session, url, semaphore):
    async with semaphore:  # Ограничиваем количество одновременно выполняемых задач
        api_token = get_random_token()  # Каждый запрос получает новый токен
        if not api_token:
            return None

        post_url = f"https://api.ok.ru/fb.do?application_key=CBAJNKCNEBABABABA&format=json&allow_dupes=true&hide_statistics=true&method=shortlink.create&url={url}&access_token={api_token}"

        async with session.post(post_url) as response:
            return await response.json()

@dp.message_handler(state=URLState.number)
async def process_number(message: types.Message, state: FSMContext):
    if message.text == 'Reset':
        await handle_reset(message, state)
        return

    try:
        number = int(message.text)
        if number <= 0:
            await message.reply("Введите положительное число.")
            return
    except ValueError:
        await message.reply("Введите корректное число.")
        return

    data = await state.get_data()
    url = data.get('url')

    if not url:
        await message.reply("Не удалось получить URL. Пожалуйста, введите его снова.")
        return

    links = []

    max_concurrent_tasks = 10  # Здесь можно указать количество потоков
    semaphore = asyncio.Semaphore(max_concurrent_tasks)

    async with aiohttp.ClientSession() as session:
        tasks = [perform_request(session, url, semaphore) for _ in range(number)]
        results = await asyncio.gather(*tasks)
        links = [result.get('shortUrl') for result in results if result and result.get('shortUrl')]

    file_path = "short_links.txt"
    with open(file_path, 'w') as f:
        for link in links:
            f.write(link + '\n')

    await bot.send_document(message.chat.id, types.InputFile(file_path))
    await state.finish()

@dp.message_handler()
async def get_activation_key(message: types.Message):
    if message.from_user.id != admin_id:
        if message.text:
            if message.text in [key for key, _ in active_keys.values()]:
                expiry = asyncio.get_event_loop().time() + 86400
                active_keys[message.from_user.id] = (message.text, expiry)
                save_keys()
                await message.reply("Вы активированы и можете использовать бота.", reply_markup=markup_user)
            else:
                await message.reply("Неверный ключ. Пожалуйста, введите правильный ключ активации.")

async def keep_alive():
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get('https://google.com/') as response:
                    if response.status == 200:
                        logging.info("Keep-alive request successful.")
                    else:
                        logging.warning(f"Keep-alive request failed with status: {response.status}")
        except Exception as e:
            logging.error(f"Keep-alive request error: {e}")
        await asyncio.sleep(600)  # Отправляем запрос каждые 10 минут

async def main():
    logging.info("Starting bot...")

    # Запуск простого веб-сервера для поддержки платформы
    app = web.Application()
    app.router.add_get("/", lambda request: web.Response(text="Bot is running"))

    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

    # Запуск keep-alive задачи
    keep_alive_task = asyncio.create_task(keep_alive())

    try:
        await dp.start_polling()
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped.")
    finally:
        keep_alive_task.cancel()  # Отменяем keep-alive задачу при завершении

if __name__ == '__main__':
    asyncio.run(main())
