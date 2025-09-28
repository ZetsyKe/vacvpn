import os
import asyncio
import httpx
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder, WebAppInfo
from dotenv import load_dotenv
from typing import Dict, List
import sqlite3
from datetime import datetime
import json
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv("backend/key.env")
TOKEN = os.getenv("TOKEN")
WEB_APP_URL = "https://vacvpn.vercel.app"
SUPPORT_NICK = "@vacvpn_support"
TG_CHANNEL = "@vac_vpn"
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")  
BOT_USERNAME = "vaaaac_bot"

if not TOKEN:
    raise ValueError("❌ Переменная TOKEN не найдена в key.env")

# Настройка бота
bot = Bot(
    token=TOKEN, 
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# Инициализация БД для рефералов (локальная SQLite)
def init_db():
    conn = sqlite3.connect('vacvpn.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            bonus_paid BOOLEAN DEFAULT FALSE
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Функции для работы с API
async def make_api_request(url: str, method: str = "GET", json_data: dict = None, params: dict = None):
    """Упрощенная функция для запросов к API"""
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
    """Получает информацию о пользователе через API"""
    url = f"{API_BASE_URL}/user-data"
    params = {"user_id": str(user_id)}
    return await make_api_request(url, "GET", params=params)

async def create_user(user_data: dict):
    """Создает пользователя через API"""
    url = f"{API_BASE_URL}/create-user"
    return await make_api_request(url, "POST", json_data=user_data)

# Функции для работы с рефералами (локальная БД)
def add_referral(referrer_id: int, referred_id: int):
    """Добавляет запись о реферале"""
    conn = sqlite3.connect('vacvpn.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT id FROM referrals WHERE referrer_id = ? AND referred_id = ?', 
                  (referrer_id, referred_id))
    existing = cursor.fetchone()
    
    if not existing:
        cursor.execute('INSERT INTO referrals (referrer_id, referred_id, created_at) VALUES (?, ?, ?)',
                      (referrer_id, referred_id, datetime.now().isoformat()))
        conn.commit()
        logger.info(f"Реферал добавлен: {referrer_id} -> {referred_id}")
    
    conn.close()

def get_referral_stats(user_id: int):
    """Получает статистику по рефералам"""
    conn = sqlite3.connect('vacvpn.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ?', (user_id,))
    total = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND bonus_paid = ?', (user_id, True))
    with_bonus = cursor.fetchone()[0]
    
    conn.close()
    return total, with_bonus

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
    builder.row(
        types.InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_cabinet"),
        types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_menu")
    )
    return builder.as_markup()

def get_ref_keyboard(user_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="🤜🤛 Поделиться ссылкой",
            url=f"https://t.me/share/url?url=https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
        )
    )
    builder.row(
        types.InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_refs"),
        types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_menu")
    )
    return builder.as_markup()

def get_support_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="📞 Написать в поддержку",
            url=f"https://t.me/{SUPPORT_NICK[1:]}"
        )
    )
    builder.row(
        types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_menu")
    )
    return builder.as_markup()

# Текстовые сообщения
def get_welcome_message(user_name: str, is_referral: bool = False):
    message = f"""
<b>Добро пожаловать в VAC VPN, {user_name}!</b>

🚀 Получите безопасный и быстрый доступ к интернету с нашей VPN-службой.

📊 <b>Основные возможности:</b>
• 🔒 Защита ваших данных
• 🌐 Обход блокировок
• 🚀 Высокая скорость
• 📱 Работа на всех устройствах

💳 <b>Оплата подписки:</b>
Для покупки подписки перейдите в веб-кабинет через меню бота.

👫 <b>Пригласите друга и получите бонус!</b>
"""
    if is_referral:
        message += "\n🎉 Вы зарегистрировались по реферальной ссылке! Бонус будет начислен после активации подписки."
    
    return message

async def get_cabinet_message(user_id: int):
    """Получает информацию о кабинете через API"""
    user_data = await get_user_info(user_id)
    
    # Всегда показываем кабинет, даже если есть ошибка
    balance = user_data.get('balance', 0)
    has_subscription = user_data.get('has_subscription', False)
    subscription_end = user_data.get('subscription_end')
    days_remaining = user_data.get('days_remaining', 0)
    tariff_type = user_data.get('tariff_type', 'нет')
    
    status_text = "✅ Активна" if has_subscription else "❌ Неактивна"
    
    if has_subscription and subscription_end:
        try:
            end_date = datetime.fromisoformat(subscription_end.replace('Z', '+00:00'))
            subscription_info = f"до {end_date.strftime('%d.%m.%Y')} ({days_remaining} дней)"
        except:
            subscription_info = "ошибка даты"
    else:
        subscription_info = "нет активной подписки"
    
    return f"""
<b>Личный кабинет VAC VPN</b>

💰 Баланс: <b>{balance}₽</b>
📅 Статус подписки: <b>{status_text}</b>
🎯 Тариф: <b>{tariff_type}</b>
⏰ Срок действия: <b>{subscription_info}</b>

💡 Для покупки подписки используйте веб-кабинет.
"""

def get_ref_message(user_id: int):
    total_referrals, with_bonus = get_referral_stats(user_id)
    
    return f"""
<b>Реферальная программа VAC VPN</b>

Пригласите друга по вашей ссылке:
<code>https://t.me/{BOT_USERNAME}?start=ref_{user_id}</code>

📊 <b>Ваша статистика:</b>
• Всего приглашено: <b>{total_referrals} чел.</b>
• С начисленным бонусом: <b>{with_bonus} чел.</b>
• Бонус за приглашение: <b>50₽</b> на баланс

💡 Бонус начисляется после того как приглашенный друг активирует подписку!
"""

def get_support_message():
    return f"""
<b>Техническая поддержка VAC VPN</b>

Если у вас возникли вопросы или проблемы:

📞 Telegram: {SUPPORT_NICK}
📢 Наш канал: {TG_CHANNEL}

⏰ Время ответа: обычно в течение 1-2 часов
"""

# Обработчики команд
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user
    args = message.text.split()
    is_referral = False

    # Создаем/обновляем пользователя в API
    await create_user({
        "user_id": str(user.id),
        "username": user.username or "",
        "first_name": user.first_name or "",
        "last_name": user.last_name or ""
    })

    # Обработка реферальной ссылки
    if len(args) > 1 and args[1].startswith('ref_'):
        try:
            referrer_id = int(args[1][4:])
            referred_id = user.id

            if referred_id != referrer_id:
                add_referral(referrer_id, referred_id)
                is_referral = True
                
                # Уведомляем реферера
                try:
                    await bot.send_message(
                        chat_id=referrer_id,
                        text=f"🎉 У вас новый реферал!\nПользователь @{user.username or 'без username'} присоединился по вашей ссылке.\nБонус 50₽ будет начислен после оплаты подписки."
                    )
                except Exception as e:
                    logger.info(f"Не удалось уведомить реферера {referrer_id}: {e}")
        except ValueError:
            logger.warning(f"Неверный формат реферальной ссылки: {args[1]}")

    await message.answer(
        text=get_welcome_message(user.first_name, is_referral),
        reply_markup=get_main_keyboard()
    )

@dp.message(Command("cabinet"))
async def cmd_cabinet(message: types.Message):
    user_id = message.from_user.id
    cabinet_text = await get_cabinet_message(user_id)
    await message.answer(cabinet_text, reply_markup=get_cabinet_keyboard())

@dp.message(Command("referral"))
async def cmd_referral(message: types.Message):
    user_id = message.from_user.id
    await message.answer(get_ref_message(user_id), reply_markup=get_ref_keyboard(user_id))

@dp.message(Command("support"))
async def cmd_support(message: types.Message):
    await message.answer(get_support_message(), reply_markup=get_support_keyboard())

# Обработчики кнопок
@dp.message(lambda message: message.text == "🔐 Личный кабинет")
async def cabinet_handler(message: types.Message):
    await cmd_cabinet(message)

@dp.message(lambda message: message.text == "👥 Рефералка")
async def referral_handler(message: types.Message):
    await cmd_referral(message)

@dp.message(lambda message: message.text == "🛠️ Техподдержка")
async def support_handler(message: types.Message):
    await cmd_support(message)

@dp.message(lambda message: message.text == "🌐 Веб-кабинет")
async def web_app_handler(message: types.Message):
    user = message.from_user
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="📲 Открыть веб-кабинет",
            web_app=WebAppInfo(url=WEB_APP_URL)
        )
    )
    await message.answer(
        f"🌐 <b>Веб-кабинет VAC VPN</b>\n\n"
        f"Для покупки подписки и управления аккаунтом откройте веб-кабинет:",
        reply_markup=builder.as_markup()
    )

# Обработчики callback-кнопок
@dp.callback_query(lambda c: c.data == "back_to_menu")
async def back_to_menu_handler(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        "Главное меню VAC VPN",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "refresh_cabinet")
async def refresh_cabinet_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cabinet_text = await get_cabinet_message(user_id)
    
    try:
        await callback.message.edit_text(cabinet_text, reply_markup=get_cabinet_keyboard())
        await callback.answer("✅ Данные обновлены")
    except Exception as e:
        await callback.message.answer(cabinet_text, reply_markup=get_cabinet_keyboard())
        await callback.answer("✅ Данные обновлены")

@dp.callback_query(lambda c: c.data == "refresh_refs")
async def refresh_refs_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    new_ref_message = get_ref_message(user_id)
    
    try:
        await callback.message.edit_text(new_ref_message, reply_markup=get_ref_keyboard(user_id))
        await callback.answer("✅ Статистика обновлена")
    except Exception as e:
        await callback.message.answer(new_ref_message, reply_markup=get_ref_keyboard(user_id))
        await callback.answer("✅ Статистика обновлены")

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
