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
from datetime import datetime, timedelta
import json
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Попытка импорта Firebase с обработкой ошибок
try:
    import firebase_admin
    from firebase_admin import credentials, db
    FIREBASE_AVAILABLE = True
except ImportError:
    print("❌ Библиотека firebase-admin не установлена. Установите: pip install firebase-admin")
    FIREBASE_AVAILABLE = False
except Exception as e:
    print(f"❌ Ошибка импорта Firebase: {e}")
    FIREBASE_AVAILABLE = False

# Загрузка переменных окружения
load_dotenv("backend/key.env")
TOKEN = os.getenv("TOKEN")
WEB_APP_URL = "https://vacvpn.vercel.app"
SUPPORT_NICK = "@vacvpn_support"
TG_CHANNEL = "@vac_vpn"
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")  

if not TOKEN:
    raise ValueError("❌ Переменная TOKEN не найдена в key.env")

# Настройка бота с улучшенными параметрами
bot = Bot(
    token=TOKEN, 
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)
dp = Dispatcher()

# Улучшенные настройки для клиента
class CustomBotProperties(DefaultBotProperties):
    def __init__(self):
        super().__init__()
        self.timeout = 30  # Увеличиваем таймаут
        self.server = "https://api.telegram.org"  # Явно указываем сервер

referrals_db: Dict[int, List[int]] = {}
user_balances: Dict[int, int] = {}
referral_checks: Dict[int, bool] = {}
pending_referral_bonuses: Dict[int, int] = {}

# Инициализация Firebase
def init_firebase():
    if not FIREBASE_AVAILABLE:
        print("❌ Firebase недоступен. Продолжаем работу без Firebase.")
        return False
    
    try:
        if not firebase_admin._apps:
            cred_path = "backend/firebase-key.json"
            if os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
                print("✅ Найден файл с ключом Firebase")
            else:
                firebase_cred = os.getenv("FIREBASE_CREDENTIALS")
                if firebase_cred:
                    cred_dict = json.loads(firebase_cred)
                    cred = credentials.Certificate(cred_dict)
                    print("✅ Использованы credentials из переменной окружения")
                else:
                    print("❌ Firebase credentials не найдены")
                    return False
            
            database_url = os.getenv("FIREBASE_DATABASE_URL")
            if not database_url:
                print("❌ FIREBASE_DATABASE_URL не найден")
                return False
            
            firebase_admin.initialize_app(cred, {'databaseURL': database_url})
            print("✅ Firebase успешно инициализирован")
            return True
    except Exception as e:
        print(f"❌ Ошибка инициализации Firebase: {e}")
        return False
    
    return True

FIREBASE_INITIALIZED = init_firebase()

# Инициализация БД
def init_db():
    conn = sqlite3.connect('vacvpn.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance REAL DEFAULT 0,
            has_subscription BOOLEAN DEFAULT FALSE,
            subscription_end TEXT,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referral_bonuses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER,
            bonus_amount INTEGER DEFAULT 50,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            paid_out BOOLEAN DEFAULT FALSE,
            paid_out_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Функции для работы с Firebase
def sync_user_to_firebase(user_id: int, user_data: dict):
    if not FIREBASE_INITIALIZED:
        return
    try:
        ref = db.reference(f'/users/{user_id}')
        ref.set(user_data)
        print(f"✅ Данные пользователя {user_id} синхронизированы с Firebase")
    except Exception as e:
        print(f"❌ Ошибка синхронизации с Firebase: {e}")

def get_user_from_firebase(user_id: int):
    if not FIREBASE_INITIALIZED:
        return None
    try:
        ref = db.reference(f'/users/{user_id}')
        return ref.get()
    except Exception as e:
        print(f"❌ Ошибка получения данных из Firebase: {e}")
    return None

def update_balance_in_firebase(user_id: int, balance: float):
    if not FIREBASE_INITIALIZED:
        return
    try:
        ref = db.reference(f'/users/{user_id}/balance')
        ref.set(balance)
        print(f"✅ Баланс пользователя {user_id} обновлен в Firebase: {balance}₽")
    except Exception as e:
        print(f"❌ Ошибка обновления баланса в Firebase: {e}")

def update_subscription_in_firebase(user_id: int, subscription_data: dict):
    if not FIREBASE_INITIALIZED:
        return
    try:
        ref = db.reference(f'/users/{user_id}/subscription')
        ref.set(subscription_data)
        print(f"✅ Подписка пользователя {user_id} обновлена в Firebase")
    except Exception as e:
        print(f"❌ Ошибка обновления подписки в Firebase: {e}")

# Улучшенные функции для работы с API с повторными попытками
async def make_api_request_with_retry(url: str, method: str = "GET", json_data: dict = None, params: dict = None, max_retries: int = 3):
    """Универсальная функция для запросов с повторными попытками"""
    for attempt in range(max_retries):
        try:
            timeout_config = httpx.Timeout(30.0, connect=10.0)  # Увеличиваем таймауты
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
                    logger.warning(f"Attempt {attempt + 1}: API returned status {response.status_code}")
                    
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
            logger.warning(f"Attempt {attempt + 1}: Connection error - {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)  # Экспоненциальная задержка
                continue
            else:
                logger.error(f"All {max_retries} attempts failed")
                return None
        except Exception as e:
            logger.error(f"Unexpected error in API request: {e}")
            return None
    
    return None

async def check_subscription_api(user_id: int):
    """Проверяет подписку через API"""
    url = f"{API_BASE_URL}/check-subscription"
    params = {"user_id": str(user_id)}
    
    result = await make_api_request_with_retry(url, "GET", params=params)
    return result

async def create_payment_api(user_id: int, tariff: str, amount: float):
    """Создает платеж через API"""
    url = f"{API_BASE_URL}/create-payment"
    json_data = {
        "user_id": str(user_id),
        "tariff": tariff,
        "amount": amount,
        "description": f"Подписка VAC VPN ({'месячная' if tariff == 'month' else 'годовая'})"
    }
    
    result = await make_api_request_with_retry(url, "POST", json_data=json_data, max_retries=2)
    return result

async def get_user_info_api(user_id: int):
    """Получает информацию о пользователе через API"""
    url = f"{API_BASE_URL}/user-info"
    params = {"user_id": str(user_id)}
    
    result = await make_api_request_with_retry(url, "GET", params=params)
    return result

async def create_user_api(user_data: dict):
    """Создает пользователя через API"""
    url = f"{API_BASE_URL}/create-user"
    
    result = await make_api_request_with_retry(url, "POST", json_data=user_data)
    return result

# Функции для работы с локальной БД
def create_or_update_user(user_id: int, username: str = "", first_name: str = "", last_name: str = ""):
    conn = sqlite3.connect('vacvpn.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    current_balance = result[0] if result else 0
    
    cursor.execute('''
        INSERT OR REPLACE INTO users 
        (user_id, username, first_name, last_name, created_at, balance)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, username, first_name, last_name, datetime.now().isoformat(), current_balance))
    
    conn.commit()
    conn.close()
    
    # Создаем пользователя в API (асинхронно, но без ожидания)
    asyncio.create_task(create_user_api({
        "user_id": str(user_id),
        "username": username,
        "first_name": first_name,
        "last_name": last_name
    }))
    
    # Синхронизация с Firebase
    if FIREBASE_INITIALIZED:
        user_data = {
            'user_id': user_id,
            'username': username,
            'first_name': first_name,
            'last_name': last_name,
            'telegram_info': {'username': username, 'first_name': first_name, 'last_name': last_name},
            'created_at': datetime.now().isoformat(),
            'balance': current_balance,
            'subscription': {'active': False, 'end_date': None},
            'last_sync': datetime.now().isoformat()
        }
        sync_user_to_firebase(user_id, user_data)

def add_referral_bonus(referrer_id: int, referred_id: int):
    conn = sqlite3.connect('vacvpn.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id FROM referral_bonuses 
        WHERE referrer_id = ? AND referred_id = ? AND paid_out = FALSE
    ''', (referrer_id, referred_id))
    
    existing = cursor.fetchone()
    
    if not existing:
        cursor.execute('''
            INSERT INTO referral_bonuses (referrer_id, referred_id, bonus_amount, created_at)
            VALUES (?, ?, 50, ?)
        ''', (referrer_id, referred_id, datetime.now().isoformat()))
        
        conn.commit()
        print(f"✅ Запись о реферальном бонусе добавлена: {referrer_id} -> {referred_id}")
    
    conn.close()

def get_pending_bonuses_count(referrer_id: int):
    conn = sqlite3.connect('vacvpn.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM referral_bonuses WHERE referrer_id = ? AND paid_out = FALSE', (referrer_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_total_earned_bonuses(referrer_id: int):
    conn = sqlite3.connect('vacvpn.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM referral_bonuses WHERE referrer_id = ?', (referrer_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_paid_bonuses_count(referrer_id: int):
    conn = sqlite3.connect('vacvpn.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM referral_bonuses WHERE referrer_id = ? AND paid_out = TRUE', (referrer_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count

# Клавиатуры
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.row(
        types.KeyboardButton(text="🔐 Личный кабинет"),
        types.KeyboardButton(text="👥 Рефералка")
    )
    builder.row(
        types.KeyboardButton(text="🛠️ Техподдержка"),
        types.KeyboardButton(text="📊 Статистика")
    )
    builder.row(
        types.KeyboardButton(text="💰 Купить подписку"),
        types.KeyboardButton(text="🔍 Проверить подписку")
    )
    return builder.as_markup(resize_keyboard=True)

def get_cabinet_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="📲 Открыть личный кабинет",
            web_app=WebAppInfo(url=WEB_APP_URL)
        )
    )
    builder.row(
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
            url=f"https://t.me/share/url?url=https://t.me/vaaaac_bot?start=ref_{user_id}"
        )
    )
    builder.row(
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
<b>Рады видеть вас снова, {user_name}!</b>

Используйте кнопки ниже для управления вашим аккаунтом VAC VPN.

👫 Пригласите друга в VAC VPN и получите бонус!

📌 Обязательно подпишитесь на наш канал ({TG_CHANNEL})!
"""
    if is_referral:
        message += "\n🎉 Вы зарегистрировались по реферальной ссылке!"
    
    return message

async def get_cabinet_message(user_id: int):
    """Получает информацию о кабинете через API"""
    api_data = await get_user_info_api(user_id)
    
    if api_data and 'error' not in api_data:
        balance = api_data.get('balance', 0)
        has_subscription = api_data.get('has_subscription', False)
        subscription_end = api_data.get('subscription_end')
        tariff_type = api_data.get('tariff_type', 'нет')
        
        status_text = "✅ Активна" if has_subscription else "❌ Неактивна"
        
        if has_subscription and subscription_end:
            end_date = datetime.fromisoformat(subscription_end.replace('Z', '+00:00'))
            days_remaining = (end_date - datetime.now()).days
            subscription_info = f"до {end_date.strftime('%d.%m.%Y')} ({days_remaining} дней)"
        else:
            subscription_info = "нет активной подписки"
        
        return f"""
<b>Личный кабинет VAC VPN</b>

💰 Текущий баланс: <b>{balance}₽</b>
📅 Подписка: <b>{status_text}</b>
🎯 Тариф: <b>{tariff_type}</b>
⏰ Срок действия: <b>{subscription_info}</b>

Данные синхронизированы с сервером.
"""
    else:
        return """
<b>Личный кабинет VAC VPN</b>

❌ Не удалось загрузить данные с сервера.
Попробуйте позже или обратитесь в поддержку.
"""

def get_ref_message(user_id: int):
    balance = user_balances.get(user_id, 0)
    total_referrals = get_total_earned_bonuses(user_id)
    pending_bonuses = get_pending_bonuses_count(user_id)
    paid_bonuses = get_paid_bonuses_count(user_id)
    
    return f"""
<b>Реферальная программа VAC VPN</b>

Пригласите друга по вашей ссылке:
<code>https://t.me/vacvpnbot?start=ref_{user_id}</code>

<b>Ваша статистика:</b>
├ Всего приглашено: <b>{total_referrals} чел.</b>
├ Ожидает выплаты: <b>{pending_bonuses} чел.</b>
├ Выплачено: <b>{paid_bonuses} чел.</b>
└ Заработано: <b>{balance}₽</b>

За каждого приглашённого друга вы получаете <b>50₽</b> на баланс!
"""

def get_support_message():
    return f"""
<b>Техническая поддержка VAC VPN</b>

Если у вас возникли вопросы или проблемы:

📞 Telegram: {SUPPORT_NICK}
📢 Наш канал: {TG_CHANNEL}
"""

async def get_stats_message(user_id: int):
    api_data = await get_user_info_api(user_id)
    local_balance = user_balances.get(user_id, 0)
    
    if api_data and 'error' not in api_data:
        api_balance = api_data.get('balance', 0)
        has_subscription = api_data.get('has_subscription', False)
        
        sync_status = "✅ Активна" 
        balance_match = "✅ Совпадают" if local_balance == api_balance else "⚠️ Различаются"
        
        total_referrals = get_total_earned_bonuses(user_id)
        pending_bonuses = get_pending_bonuses_count(user_id)
        paid_bonuses = get_paid_bonuses_count(user_id)
        
        return f"""
<b>Статистика синхронизации</b>

📊 Локальный баланс: <b>{local_balance}₽</b>
☁️ Баланс в API: <b>{api_balance}₽</b>
🔀 Соответствие: <b>{balance_match}</b>

🔄 Статус синхронизации: <b>{sync_status}</b>
📅 Подписка: <b>{'✅ Активна' if has_subscription else '❌ Неактивна'}</b>

<b>Реферальная статистика:</b>
├ Всего приглашено: <b>{total_referrals} чел.</b>
├ Ожидает выплаты: <b>{pending_bonuses} чел.</b>
└ Выплачено: <b>{paid_bonuses} чел.</b>
"""
    else:
        return """
<b>Статистика синхронизации</b>

❌ Не удалось получить данные с сервера API.
Проверьте соединение или обратитесь в поддержку.
"""

# Обработчики команд
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user
    args = message.text.split()
    is_referral = False

    create_or_update_user(user.id, user.username or "", user.first_name or "", user.last_name or "")

    if len(args) > 1 and args[1].startswith('ref_'):
        referrer_id = int(args[1][4:])
        referred_id = user.id

        if referred_id != referrer_id:
            if referrer_id not in referrals_db:
                referrals_db[referrer_id] = []

            if referred_id not in referrals_db[referrer_id]:
                referrals_db[referrer_id].append(referred_id)
                add_referral_bonus(referrer_id, referred_id)
                referral_checks[referred_id] = True
                is_referral = True
                
                try:
                    await bot.send_message(
                        chat_id=referrer_id,
                        text=f"🎉 Новый реферал!\nID: {referred_id}\nБонус будет начислен после подтверждения активности."
                    )
                except:
                    pass

    await message.answer(
        text=get_welcome_message(user.full_name, is_referral),
        reply_markup=get_main_keyboard()
    )

@dp.message(lambda message: message.text == "🔐 Личный кабинет")
async def cabinet_handler(message: types.Message):
    user_id = message.from_user.id
    
    cabinet_text = await get_cabinet_message(user_id)
    
    await message.answer(
        text=cabinet_text,
        reply_markup=get_cabinet_keyboard()
    )

@dp.message(lambda message: message.text == "💰 Купить подписку")
async def buy_subscription_handler(message: types.Message):
    await message.answer(
        text="""
<b>Выберите тариф подписки:</b>

📅 <b>Месячная подписка - 299₽</b>
• Доступ ко всем серверам
• Безлимитный трафик  
• Поддержка 24/7
• Автопродление

📅 <b>Годовая подписка - 2990₽</b> (🔥 Выгоднее!)
• Все преимущества месячной
• Экономия 20% 
• Приоритетная поддержка
• Автопродление
""",
        reply_markup=get_tariff_keyboard()
    )

@dp.message(lambda message: message.text == "🔍 Проверить подписку")
async def check_subscription_handler(message: types.Message):
    user_id = message.from_user.id
    
    subscription_data = await check_subscription_api(user_id)
    
    if subscription_data and 'error' not in subscription_data:
        has_sub = subscription_data.get('active', False)
        days_remaining = subscription_data.get('days_remaining', 0)
        subscription_end = subscription_data.get('subscription_end')
        
        if has_sub and subscription_end:
            end_date = datetime.fromisoformat(subscription_end.replace('Z', '+00:00'))
            status_text = f"✅ Активна (осталось {days_remaining} дней)\nДата окончания: {end_date.strftime('%d.%m.%Y %H:%M')}"
        else:
            status_text = "❌ Неактивна"
        
        await message.answer(f"""
<b>Статус вашей подписки:</b>

{status_text}

Для продления подписки нажмите "💰 Купить подписку"
""")
    else:
        await message.answer("❌ Не удалось проверить статус подписки. Попробуйте позже.")

@dp.message(lambda message: message.text == "👥 Рефералка")
async def ref_handler(message: types.Message):
    await message.answer(
        text=get_ref_message(message.from_user.id),
        reply_markup=get_ref_keyboard(message.from_user.id),
        disable_web_page_preview=True
    )

@dp.message(lambda message: message.text == "🛠️ Техподдержка")
async def support_handler(message: types.Message):
    await message.answer(
        text=get_support_message(),
        reply_markup=get_support_keyboard()
    )

@dp.message(lambda message: message.text == "📊 Статистика")
async def stats_handler(message: types.Message):
    stats_text = await get_stats_message(message.from_user.id)
    await message.answer(text=stats_text)

# Обработчики callback-кнопок
@dp.callback_query(lambda c: c.data == "back_to_menu")
async def back_to_menu_handler(callback: types.CallbackQuery):
    await callback.message.edit_text(
        text=get_welcome_message(callback.from_user.full_name),
        reply_markup=None
    )
    await callback.message.answer(
        text="Вы вернулись в главное меню",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("tariff_"))
async def tariff_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    tariff = callback.data.replace("tariff_", "")
    
    tariff_config = {
        "month": {"amount": 299, "days": 30, "name": "месячная"},
        "year": {"amount": 2990, "days": 365, "name": "годовая"}
    }
    
    tariff_info = tariff_config.get(tariff)
    if not tariff_info:
        await callback.answer("❌ Ошибка выбора тарифа")
        return
    
    # Создаем платеж через API
    payment_result = await create_payment_api(user_id, tariff, tariff_info["amount"])
    
    if payment_result and 'error' not in payment_result:
        payment_url = payment_result.get('payment_url')
        payment_id = payment_result.get('payment_id')
        
        # Создаем кнопку для оплаты
        builder = InlineKeyboardBuilder()
        builder.row(
            types.InlineKeyboardButton(text="💳 Оплатить подписку", url=payment_url)
        )
        builder.row(
            types.InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_payment_{payment_id}")
        )
        builder.row(
            types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_menu")
        )
        
        await callback.message.edit_text(
            text=f"""
<b>Оплата {tariff_info['name']} подписки</b>

Сумма к оплате: <b>{tariff_info['amount']}₽</b>
Срок действия: <b>{tariff_info['days']} дней</b>

Нажмите кнопку ниже для оплаты через ЮKassa.
После оплаты нажмите "Проверить оплату".
""",
            reply_markup=builder.as_markup()
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
    
    # Здесь должна быть логика проверки статуса платежа через API
    # Пока заглушка
    await callback.answer("✅ Функция проверки оплаты будет реализована скоро!", show_alert=True)

# Команда для принудительной синхронизации
@dp.message(Command("sync"))
async def cmd_sync(message: types.Message):
    user_id = message.from_user.id
    user_data = {
        'user_id': user_id,
        'username': message.from_user.username or "",
        'first_name': message.from_user.first_name or "",
        'last_name': message.from_user.last_name or "",
        'balance': user_balances.get(user_id, 0),
        'subscription': {'active': False, 'end_date': None},
        'last_sync': datetime.now().isoformat()
    }
    sync_user_to_firebase(user_id, user_data)
    
    # Синхронизацифя с API
    await create_user_api({
        "user_id": str(user_id),
        "username": message.from_user.username or "",
        "first_name": message.from_user.first_name or "",
        "last_name": message.from_user.last_name or ""
    })
    
    await message.answer("✅ Данные синхронизированы с Firebase и API!")

# Команда для админа
@dp.message(Command("pay_bonus"))
async def cmd_pay_bonus(message: types.Message):
    ADMIN_IDS = [123456789]  # Замените на ваш ID
    
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    try:
        args = message.text.split()
        if len(args) < 2:
            await message.answer("Использование: /pay_bonus <user_id>")
            return
        
        user_id = int(args[1])
        
        conn = sqlite3.connect('vacvpn.db')
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM referral_bonuses WHERE referrer_id = ? AND paid_out = FALSE', (user_id,))
        pending_bonuses = cursor.fetchall()
        
        if not pending_bonuses:
            await message.answer(f"❌ У пользователя {user_id} нет ожидающих бонусов.")
            conn.close()
            return
        
        total_bonus = len(pending_bonuses) * 50
        current_balance = user_balances.get(user_id, 0)
        user_balances[user_id] = current_balance + total_bonus
        
        for bonus_id, referred_id in pending_bonuses:
            cursor.execute('UPDATE referral_bonuses SET paid_out = TRUE, paid_out_at = ? WHERE id = ?', 
                          (datetime.now().isoformat(), bonus_id))
        
        conn.commit()
        conn.close()
        
        update_balance_in_firebase(user_id, user_balances[user_id])
        
        await message.answer(f"✅ Пользователю {user_id} начислено {total_bonus}₽ за {len(pending_bonuses)} рефералов.")
        
        try:
            await bot.send_message(
                chat_id=user_id,
                text=f"🎉 Вам начислен реферальный бонус: {total_bonus}₽ за {len(pending_bonuses)} приглашенных друзей!"
            )
        except:
            pass
            
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# Улучшенная функция запуска бота с обработкой ошибок
async def main():
    if FIREBASE_INITIALIZED:
        print("✅ Бот запущен с автоматической синхронизацией Firebase")
    else:
        print("⚠️ Бот запущен без Firebase. Данные будут храниться только локально.")
    
    print(f"🌐 API сервер: {API_BASE_URL}")
    
    try:
        await bot.set_chat_menu_button(
            menu_button=types.MenuButtonWebApp(
                text="VAC VPN",
                web_app=WebAppInfo(url=WEB_APP_URL)
            )
        )
        
        # Улучшенный запуск polling с обработкой ошибок
        await dp.start_polling(
            bot, 
            allowed_updates=dp.resolve_used_update_types(),
            close_bot_session=True
        )
        
    except KeyboardInterrupt:
        print("🛑 Бот остановлен пользователем")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Программа завершена")
