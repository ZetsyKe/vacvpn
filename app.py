import os
import logging
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder, WebAppInfo
import httpx

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
TOKEN = os.getenv("TOKEN")
WEB_APP_URL = "https://vacvpn.vercel.app"
SUPPORT_NICK = "@vacvpn_support"
TG_CHANNEL = "@vac_vpn"
API_BASE_URL = os.getenv("RENDER_EXTERNAL_URL", "https://vacvpn-backend.onrender.com")
BOT_USERNAME = "vaaaac_bot"

if not TOKEN:
    raise ValueError("❌ Переменная TOKEN не найдена")

# Настройка бота
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Функции для работы с API
async def make_api_request(url: str, method: str = "GET", json_data: dict = None, params: dict = None):
    try:
        timeout_config = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout_config) as client:
            if method.upper() == "GET":
                response = await client.get(url, params=params)
            elif method.upper() == "POST":
                response = await client.post(url, json=json_data)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"API returned status {response.status_code}")
                return {"error": f"API error: {response.status_code}"}
                
    except Exception as e:
        logger.error(f"API request error: {e}")
        return {"error": f"Connection error: {str(e)}"}

async def get_user_info(user_id: int):
    url = f"{API_BASE_URL}/user-data"
    params = {"user_id": str(user_id)}
    return await make_api_request(url, "GET", params=params)

async def create_user(user_data: dict):
    url = f"{API_BASE_URL}/create-user"
    return await make_api_request(url, "POST", json_data=user_data)

# Клавиатуры
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.row(
        types.KeyboardButton(text="🔐 Личный кабинет"),
        types.KeyboardButton(text="👥 Рефералка")
    )
    builder.row(
        types.KeyboardButton(text="🛠️ Техподдержка"),
        types.KeyboardButton(text="🌐 Веб-кабинет")
    )
    return builder.as_markup(resize_keyboard=True)

def get_cabinet_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="📲 Открыть веб-кабинет",
            web_app=WebAppInfo(url=WEB_APP_URL)
        )
    )
    return builder.as_markup()

# Обработчики команд
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user

    # Создаем пользователя в API
    await create_user({
        "user_id": str(user.id),
        "username": user.username or "",
        "first_name": user.first_name or "",
        "last_name": user.last_name or ""
    })

    welcome_message = f"""
<b>Добро пожаловать в VAC VPN, {user.first_name}!</b>

🚀 Получите безопасный и быстрый доступ к интернету с нашей VPN-службой.

💳 <b>Оплата подписки:</b>
Для покупки подписки перейдите в веб-кабинет через меню бота.
"""

    await message.answer(
        text=welcome_message,
        reply_markup=get_main_keyboard()
    )

@dp.message(lambda message: message.text == "🔐 Личный кабинет")
async def cabinet_handler(message: types.Message):
    user_id = message.from_user.id
    user_data = await get_user_info(user_id)
    
    if user_data and 'balance' in user_data:
        balance = user_data.get('balance', 0)
        has_subscription = user_data.get('has_subscription', False)
        status_text = "✅ Активна" if has_subscription else "❌ Неактивна"
        
        cabinet_text = f"""
<b>Личный кабинет VAC VPN</b>

💰 Баланс: <b>{balance}₽</b>
📅 Статус подписки: <b>{status_text}</b>

💡 Для покупки подписки используйте веб-кабинет.
"""
    else:
        cabinet_text = "❌ Не удалось загрузить данные. Попробуйте позже."
    
    await message.answer(cabinet_text, reply_markup=get_cabinet_keyboard())

@dp.message(lambda message: message.text == "🌐 Веб-кабинет")
async def web_app_handler(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="📲 Открыть веб-кабинет",
            web_app=WebAppInfo(url=WEB_APP_URL)
        )
    )
    await message.answer(
        "🌐 <b>Веб-кабинет VAC VPN</b>\n\n"
        "Для покупки подписки и управления аккаунтом откройте веб-кабинет:",
        reply_markup=builder.as_markup()
    )

@dp.message(lambda message: message.text == "🛠️ Техподдержка")
async def support_handler(message: types.Message):
    support_text = f"""
<b>Техническая поддержка VAC VPN</b>

Если у вас возникли вопросы или проблемы:

📞 Telegram: {SUPPORT_NICK}
📢 Наш канал: {TG_CHANNEL}

⏰ Время ответа: обычно в течение 1-2 часов
"""
    await message.answer(support_text)

# Запуск бота
async def main():
    logger.info("🤖 Бот VAC VPN запускается...")
    logger.info(f"🌐 API сервер: {API_BASE_URL}")
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"❌ Ошибка запуска бота: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
