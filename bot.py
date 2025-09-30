import os
import asyncio
import httpx
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder, WebAppInfo
from dotenv import load_dotenv
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
API_BASE_URL = os.getenv("API_BASE_URL", "https://vacvpn-api-production-d067.up.railway.app")
BOT_USERNAME = "vaaaac_bot"

if not TOKEN:
    raise ValueError("❌ Переменная TOKEN не найдена в key.env")

# Настройка бота
bot = Bot(
    token=TOKEN, 
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# Хранилище для отслеживания уже обработанных рефералов
processed_referrals = set()

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
    url = f"{API_BASE_URL}/init-user"
    return await make_api_request(url, "POST", json_data=user_data)

async def add_referral_api(referrer_id: str, referred_id: str):
    """Добавляет реферала через API"""
    url = f"{API_BASE_URL}/add-referral"
    return await make_api_request(url, "POST", json_data={
        "referrer_id": referrer_id,
        "referred_id": referred_id
    })

async def update_user_balance(user_id: str, amount: float):
    """Начисляет бонус на баланс пользователя через API"""
    try:
        url = f"{API_BASE_URL}/update-balance"
        result = await make_api_request(url, "POST", json_data={
            "user_id": user_id,
            "amount": amount
        })
        
        if result and result.get('success'):
            logger.info(f"✅ Бонус {amount}₽ успешно начислен пользователю {user_id}")
            return True
        else:
            error_msg = result.get('error', 'Unknown error') if result else 'No response'
            logger.error(f"❌ Ошибка начисления бонуса пользователю {user_id}: {error_msg}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Ошибка при вызове API обновления баланса: {e}")
        return False

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
        message += "\n🎉 Вы зарегистрировались по реферальной ссылке! Бонус 50₽ уже начислен на ваш баланс!"
    
    return message

async def get_cabinet_message(user_id: int):
    """Получает информацию о кабинете через API"""
    user_data = await get_user_info(user_id)
    
    if user_data.get('error'):
        return f"""
<b>Личный кабинет VAC VPN</b>

❌ Ошибка загрузки данных: {user_data['error']}

💡 Попробуйте обновить данные или обратитесь в поддержку.
"""
    
    balance = user_data.get('balance', 0)
    has_subscription = user_data.get('has_subscription', False)
    subscription_end = user_data.get('subscription_end')
    days_remaining = user_data.get('days_remaining', 0)
    tariff_type = user_data.get('tariff_type', 'нет')
    
    status_text = "✅ Активна" if has_subscription else "❌ Неактивна"
    
    if has_subscription and subscription_end:
        try:
            from datetime import datetime
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
    return f"""
<b>Реферальная программа VAC VPN</b>

Пригласите друга по вашей ссылке:
<code>https://t.me/{BOT_USERNAME}?start=ref_{user_id}</code>

🎁 <b>Бонус за приглашение:</b>
• 50₽ на баланс за каждого друга
• Бонус начисляется сразу после регистрации по вашей ссылке

💡 Делитесь ссылкой и получайте бонусы!
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
    user_create_result = await create_user({
        "user_id": str(user.id),
        "username": user.username or "",
        "first_name": user.first_name or "",
        "last_name": user.last_name or ""
    })

    logger.info(f"User create result: {user_create_result}")

    # Обработка реферальной ссылки
    if len(args) > 1 and args[1].startswith('ref_'):
        try:
            referrer_id = args[1][4:]
            referred_id = str(user.id)
            
            # Проверяем валидность ID
            if not referrer_id.isdigit():
                logger.warning(f"Неверный формат referrer_id: {referrer_id}")
            elif referred_id == referrer_id:
                logger.info("Пользователь пытается использовать свою ссылку")
            else:
                # Создаем уникальный ключ для этого реферала
                referral_key = f"{referrer_id}_{referred_id}"
                
                # Проверяем, не обрабатывали ли мы уже этого реферала
                if referral_key not in processed_referrals:
                    # Добавляем в обработанные
                    processed_referrals.add(referral_key)
                    
                    # Добавляем реферала в систему
                    referral_result = await add_referral_api(referrer_id, referred_id)
                    logger.info(f"Referral result: {referral_result}")
                    
                    # НАЧИСЛЯЕМ БОНУС 50₽ СРАЗУ
                    bonus_amount = 50.0
                    bonus_result = await update_user_balance(referrer_id, bonus_amount)
                    
                    if bonus_result:
                        logger.info(f"✅ Бонус 50₽ начислен рефереру {referrer_id}")
                        is_referral = True
                        
                        # Уведомляем реферера только если бонус успешно начислен
                        try:
                            await bot.send_message(
                                chat_id=int(referrer_id),
                                text=f"🎉 <b>У вас новый реферал!</b>\n\n"
                                     f"👤 Пользователь: @{user.username or user.first_name}\n"
                                     f"💰 <b>Бонус 50₽ уже начислен на ваш баланс!</b>\n\n"
                                     f"Продолжайте приглашать друзей и зарабатывать больше! 🚀"
                            )
                            logger.info(f"✅ Уведомление отправлено рефереру {referrer_id}")
                        except Exception as e:
                            logger.error(f"❌ Не удалось уведомить реферера {referrer_id}: {e}")
                    else:
                        logger.error(f"❌ Не удалось начислить бонус рефереру {referrer_id}")
                        # Удаляем из обработанных, чтобы попробовать снова
                        processed_referrals.discard(referral_key)
                else:
                    logger.info(f"Реферал {referral_key} уже обработан ранее")
                    
        except Exception as e:
            logger.error(f"❌ Ошибка обработки реферальной ссылки: {e}")

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
