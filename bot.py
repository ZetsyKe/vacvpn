import osimport os
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

# Инициализация БД (только для отслеживания рефералов)
def init_db():
    conn = sqlite3.connect('vacvpn.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Улучшенные функции для работы с API
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

async def create_payment(user_id: int, tariff: str, amount: float):
    """Создает платеж через API"""
    url = f"{API_BASE_URL}/create-payment"
    json_data = {
        "user_id": str(user_id),
        "tariff": tariff,
        "amount": amount,
        "description": f"Подписка VAC VPN ({'месячная' if tariff == 'month' else 'годовая'})"
    }
    return await make_api_request(url, "POST", json_data=json_data)

async def check_payment_status(payment_id: str, user_id: str):
    """Проверяет статус платежа через API"""
    url = f"{API_BASE_URL}/payment-status"
    params = {"payment_id": payment_id, "user_id": user_id}
    return await make_api_request(url, "GET", params=params)

# Функции для работы с рефералами (локальная БД)
def add_referral(referrer_id: int, referred_id: int):
    """Добавляет запись о реферале"""
    conn = sqlite3.connect('vacvpn.db')
    cursor = conn.cursor()
    
    # Проверяем, нет ли уже такой записи
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
    
    # Всего приглашено
    cursor.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ?', (user_id,))
    total = cursor.fetchone()[0]
    
    conn.close()
    return total

# Клавиатуры
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.row(
        types.KeyboardButton(text="🔐 Личный кабинет"),
        types.KeyboardButton(text="👥 Рефералка")
    )
    builder.row(
        types.KeyboardButton(text="🛠️ Техподдержка"),
        types.KeyboardButton(text="💰 Купить подписку")
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

def get_tariff_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="📅 Месяц - 299₽", callback_data="tariff_month"),
        types.InlineKeyboardButton(text="📅 Год - 2990₽", callback_data="tariff_year")
    )
    builder.row(
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

def get_payment_keyboard(payment_url: str, payment_id: str):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="💳 Оплатить подписку", url=payment_url)
    )
    builder.row(
        types.InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_payment_{payment_id}"),
        types.InlineKeyboardButton(text="📊 Статус оплаты", callback_data=f"payment_status_{payment_id}")
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

👫 <b>Пригласите друга и получите бонус!</b>
"""
    if is_referral:
        message += "\n🎉 Вы зарегистрировались по реферальной ссылке! Бонус будет начислен после активации подписки."
    
    return message

async def get_cabinet_message(user_id: int):
    """Получает информацию о кабинете через API"""
    user_data = await get_user_info(user_id)
    
    if user_data and 'error' not in user_data:
        balance = user_data.get('balance', 0)
        has_subscription = user_data.get('has_subscription', False)
        subscription_end = user_data.get('subscription_end')
        days_remaining = user_data.get('days_remaining', 0)
        tariff_type = user_data.get('tariff_type', 'нет')
        
        status_text = "✅ Активна" if has_subscription else "❌ Неактивна"
        
        if has_subscription and subscription_end:
            end_date = datetime.fromisoformat(subscription_end.replace('Z', '+00:00'))
            subscription_info = f"до {end_date.strftime('%d.%m.%Y')} ({days_remaining} дней)"
        else:
            subscription_info = "нет активной подписки"
        
        return f"""
<b>Личный кабинет VAC VPN</b>

💰 Баланс: <b>{balance}₽</b>
📅 Статус подписки: <b>{status_text}</b>
🎯 Тариф: <b>{tariff_type}</b>
⏰ Срок действия: <b>{subscription_info}</b>

💡 Для управления подпиской используйте веб-кабинет.
"""
    else:
        error_msg = user_data.get('error', 'Неизвестная ошибка') if user_data else 'Ошибка соединения'
        return f"""
<b>Личный кабинет VAC VPN</b>

❌ Не удалось загрузить данные: {error_msg}

Попробуйте обновить данные или обратитесь в поддержку.
"""

def get_ref_message(user_id: int):
    total_referrals = get_referral_stats(user_id)
    
    return f"""
<b>Реферальная программа VAC VPN</b>

Пригласите друга по вашей ссылке:
<code>https://t.me/{BOT_USERNAME}?start=ref_{user_id}</code>

📊 <b>Ваша статистика:</b>
• Всего приглашено: <b>{total_referrals} чел.</b>
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
                        text=f"🎉 У вас новый реферал!\nПользователь @{user.username or 'без username'} присоединился по вашей ссылке."
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

@dp.message(lambda message: message.text == "💰 Купить подписку")
async def buy_subscription_handler(message: types.Message):
    await message.answer(
        "📦 <b>Выберите тариф подписки:</b>\n\n"
        "📅 <b>Месячная</b> - 299₽\n"
        "• Доступ на 30 дней\n"
        "• Поддержка 3 устройств\n"
        "• Полная скорость\n\n"
        "📅 <b>Годовая</b> - 2990₽\n"
        "• Доступ на 365 дней\n"
        "• Поддержка 5 устройств\n"
        "• Приоритетная поддержка\n"
        "• Экономия 15%",
        reply_markup=get_tariff_keyboard()
    )

# Обработчики callback-кнопок
@dp.callback_query(lambda c: c.data == "back_to_menu")
async def back_to_menu_handler(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "Главное меню VAC VPN",
        reply_markup=None
    )
    await callback.message.answer(
        "Выберите действие:",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "refresh_cabinet")
async def refresh_cabinet_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cabinet_text = await get_cabinet_message(user_id)
    await callback.message.edit_text(cabinet_text, reply_markup=get_cabinet_keyboard())
    await callback.answer("✅ Данные обновлены")

@dp.callback_query(lambda c: c.data == "refresh_refs")
async def refresh_refs_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    await callback.message.edit_text(get_ref_message(user_id), reply_markup=get_ref_keyboard(user_id))
    await callback.answer("✅ Статистика обновлена")

@dp.callback_query(lambda c: c.data.startswith("tariff_"))
async def tariff_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    tariff = callback.data.replace("tariff_", "")
    
    tariff_config = {
        "month": {"amount": 299, "name": "месячная"},
        "year": {"amount": 2990, "name": "годовая"}
    }
    
    tariff_info = tariff_config.get(tariff)
    if not tariff_info:
        await callback.answer("❌ Ошибка выбора тарифа")
        return
    
    # Создаем платеж через API
    payment_result = await create_payment(user_id, tariff, tariff_info["amount"])
    
    if payment_result and 'error' not in payment_result:
        payment_url = payment_result.get('payment_url')
        payment_id = payment_result.get('payment_id')
        
        await callback.message.edit_text(
            text=f"""
<b>Оплата {tariff_info['name']} подписки</b>

💳 Сумма: <b>{tariff_info['amount']}₽</b>
📝 Описание: {tariff_info['name']} подписка VAC VPN

1. Нажмите «Оплатить подписку»
2. Проведите платеж через ЮKassa
3. Вернитесь в бот и нажмите «Проверить оплату»

⏳ Обычно оплата проходит за 1-2 минуты.
""",
            reply_markup=get_payment_keyboard(payment_url, payment_id)
        )
    else:
        error_msg = payment_result.get('error', 'Неизвестная ошибка') if payment_result else 'Ошибка соединения'
        await callback.message.edit_text(
            text=f"❌ Ошибка создания платежа:\n{error_msg}\n\nПопробуйте позже или обратитесь в поддержку.",
            reply_markup=InlineKeyboardBuilder().add(
                types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_menu")
            ).as_markup()
        )
    
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("check_payment_"))
async def check_payment_handler(callback: types.CallbackQuery):
    payment_id = callback.data.replace("check_payment_", "")
    user_id = callback.from_user.id
    
    # Проверяем статус платежа через API
    payment_status = await check_payment_status(payment_id, str(user_id))
    
    if payment_status and 'error' not in payment_status:
        status = payment_status.get('status', 'pending')
        
        if status == 'succeeded':
            await callback.message.edit_text(
                text="""
✅ <b>Оплата прошла успешно!</b>

🎉 Ваша подписка активирована!
💰 Баланс пополнен на сумму оплаты.

Теперь вы можете использовать VPN-сервис.
Для управления подпиской перейдите в личный кабинет.
""",
                reply_markup=InlineKeyboardBuilder().add(
                    types.InlineKeyboardButton(text="🔐 Личный кабинет", callback_data="refresh_cabinet")
                ).as_markup()
            )
            
        elif status == 'pending':
            await callback.answer("⏳ Платеж обрабатывается. Попробуйте через минуту.", show_alert=True)
        else:
            await callback.answer("❌ Платеж не найден или отменен.", show_alert=True)
    else:
        error_msg = payment_status.get('error', 'Неизвестная ошибка') if payment_status else 'Ошибка соединения'
        await callback.answer(f"❌ Ошибка проверки платежа: {error_msg}", show_alert=True)
    
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("payment_status_"))
async def payment_status_handler(callback: types.CallbackQuery):
    payment_id = callback.data.replace("payment_status_", "")
    user_id = callback.from_user.id
    
    payment_status = await check_payment_status(payment_id, str(user_id))
    
    if payment_status and 'error' not in payment_status:
        status = payment_status.get('status', 'pending')
        amount = payment_status.get('amount', 0)
        tariff = payment_status.get('tariff', 'unknown')
        
        status_texts = {
            'succeeded': '✅ Успешно оплачен',
            'pending': '⏳ Ожидает оплаты', 
            'canceled': '❌ Отменен',
            'waiting_for_capture': '⏳ Ожидает подтверждения'
        }
        
        status_text = status_texts.get(status, '❓ Неизвестный статус')
        
        await callback.answer(
            f"Статус платежа: {status_text}\n"
            f"Сумма: {amount}₽\n"
            f"Тариф: {tariff}",
            show_alert=True
        )
    else:
        await callback.answer("❌ Не удалось получить статус платежа", show_alert=True)

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
