import os
import asyncio
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

# Ваш оригинальный код
load_dotenv("backend/key.env")
TOKEN = os.getenv("TOKEN")
WEB_APP_URL = "https://vacvpn.vercel.app"
SUPPORT_NICK = "@vacvpn_support"
TG_CHANNEL = "@vac_vpn"

if not TOKEN:
    raise ValueError("❌ Переменная TOKEN не найдена в key.env")

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

referrals_db: Dict[int, List[int]] = {}
user_balances: Dict[int, int] = {}
referral_checks: Dict[int, bool] = {}
pending_referral_bonuses: Dict[int, int] = {}  # Новый словарь для отложенных бонусов

# Инициализация Firebase (с проверкой доступности)
def init_firebase():
    if not FIREBASE_AVAILABLE:
        print("❌ Firebase недоступен. Продолжаем работу без Firebase.")
        return False
    
    try:
        # Проверяем, не инициализирован ли Firebase уже
        if not firebase_admin._apps:
            # Способ 1: Попробовать найти файл с ключом
            cred_path = "backend/firebase-key.json"
            if os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
                print("✅ Найден файл с ключом Firebase")
            else:
                # Способ 2: Использовать переменную окружения
                firebase_cred = os.getenv("FIREBASE_CREDENTIALS")
                if firebase_cred:
                    cred_dict = json.loads(firebase_cred)
                    cred = credentials.Certificate(cred_dict)
                    print("✅ Использованы credentials из переменной окружения")
                else:
                    print("❌ Firebase credentials не найдены")
                    return False
            
            # Получаем URL базы данных
            database_url = os.getenv("FIREBASE_DATABASE_URL")
            if not database_url:
                print("❌ FIREBASE_DATABASE_URL не найден")
                return False
            
            # Инициализируем Firebase
            firebase_admin.initialize_app(cred, {
                'databaseURL': database_url
            })
            print("✅ Firebase успешно инициализирован")
            return True
    except Exception as e:
        print(f"❌ Ошибка инициализации Firebase: {e}")
        return False
    
    return True

# Инициализируем Firebase
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

# Функции для работы с Firebase (с проверкой доступности)
def sync_user_to_firebase(user_id: int, user_data: dict):
    """Автоматически синхронизирует данные пользователя с Firebase"""
    if not FIREBASE_INITIALIZED:
        return
    
    try:
        ref = db.reference(f'/users/{user_id}')
        ref.set(user_data)
        print(f"✅ Данные пользователя {user_id} автоматически синхронизированы с Firebase")
    except Exception as e:
        print(f"❌ Ошибка синхронизации с Firebase: {e}")

def get_user_from_firebase(user_id: int):
    """Получает данные пользователя из Firebase"""
    if not FIREBASE_INITIALIZED:
        return None
    
    try:
        ref = db.reference(f'/users/{user_id}')
        return ref.get()
    except Exception as e:
        print(f"❌ Ошибка получения данных из Firebase: {e}")
    return None

def update_balance_in_firebase(user_id: int, balance: float):
    """Автоматически обновляет баланс пользователя в Firebase"""
    if not FIREBASE_INITIALIZED:
        return
    
    try:
        ref = db.reference(f'/users/{user_id}/balance')
        ref.set(balance)
        print(f"✅ Баланс пользователя {user_id} автоматически обновлен в Firebase: {balance}₽")
    except Exception as e:
        print(f"❌ Ошибка обновления баланса в Firebase: {e}")

def update_subscription_in_firebase(user_id: int, subscription_data: dict):
    """Автоматически обновляет данные подписки в Firebase"""
    if not FIREBASE_INITIALIZED:
        return
    
    try:
        ref = db.reference(f'/users/{user_id}/subscription')
        ref.set(subscription_data)
        print(f"✅ Подписка пользователя {user_id} автоматически обновлена в Firebase")
    except Exception as e:
        print(f"❌ Ошибка обновления подписки в Firebase: {e}")

# Функции для работы с локальной БД
def create_or_update_user(user_id: int, username: str = "", first_name: str = "", last_name: str = ""):
    """Создает или обновляет пользователя в локальной БД и автоматически синхронизирует с Firebase"""
    conn = sqlite3.connect('vacvpn.db')
    cursor = conn.cursor()
    
    # Получаем текущий баланс
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
    
    # Автоматическая синхронизация с Firebase (если доступен)
    if FIREBASE_INITIALIZED:
        user_data = {
            'user_id': user_id,
            'username': username,
            'first_name': first_name,
            'last_name': last_name,
            'telegram_info': {
                'username': username,
                'first_name': first_name,
                'last_name': last_name
            },
            'created_at': datetime.now().isoformat(),
            'balance': current_balance,
            'subscription': {
                'active': check_user_subscription(user_id),
                'end_date': None
            },
            'last_sync': datetime.now().isoformat()
        }
        sync_user_to_firebase(user_id, user_data)

def add_referral_bonus(referrer_id: int, referred_id: int):
    """Добавляет запись о реферальном бонусе в БД (но не начисляет сразу)"""
    conn = sqlite3.connect('vacvpn.db')
    cursor = conn.cursor()
    
    # Проверяем, не существует ли уже такая запись
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
    """Получает количество ожидающих бонусов"""
    conn = sqlite3.connect('vacvpn.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT COUNT(*) FROM referral_bonuses 
        WHERE referrer_id = ? AND paid_out = FALSE
    ''', (referrer_id,))
    
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_total_earned_bonuses(referrer_id: int):
    """Получает общее количество заработанных бонусов (включая выплаченные)"""
    conn = sqlite3.connect('vacvpn.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT COUNT(*) FROM referral_bonuses 
        WHERE referrer_id = ?
    ''', (referrer_id,))
    
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_paid_bonuses_count(referrer_id: int):
    """Получает количество выплаченных бонусов"""
    conn = sqlite3.connect('vacvpn.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT COUNT(*) FROM referral_bonuses 
        WHERE referrer_id = ? AND paid_out = TRUE
    ''', (referrer_id,))
    
    count = cursor.fetchone()[0]
    conn.close()
    return count

# Клавиатуры (убрал кнопку синхронизации)
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

def get_ref_keyboard(user_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="🤜🤛 Поделиться ссылкой",
            url=f"https://t.me/share/url?url=https://t.me/vacvpnbot?start=ref_{user_id}"
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

def get_cabinet_message(user_id: int):
    # Получаем данные из Firebase для отображения актуальной информации
    firebase_data = get_user_from_firebase(user_id) if FIREBASE_INITIALIZED else None
    balance = firebase_data.get('balance', 0) if firebase_data else user_balances.get(user_id, 0)
    
    status_icon = "✅" if FIREBASE_INITIALIZED else "❌"
    status_text = "активна" if FIREBASE_INITIALIZED else "неактивна"
    
    return f"""
<b>Личный кабинет VAC VPN</b>

💰 Текущий баланс: <b>{balance}₽</b>
🔗 Синхронизация: <b>{status_text}</b> {status_icon}

Данные автоматически синхронизируются с облаком.
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

💰 Баланс начисляется после подтверждения активности реферала.
"""

def get_support_message():
    return f"""
<b>Техническая поддержка VAC VPN</b>

Если у вас возникли вопросы или проблемы:

📞 Telegram: {SUPPORT_NICK}
📢 Наш канал: {TG_CHANNEL}
"""

def get_stats_message(user_id: int):
    firebase_data = get_user_from_firebase(user_id) if FIREBASE_INITIALIZED else None
    local_balance = user_balances.get(user_id, 0)
    firebase_balance = firebase_data.get('balance', 0) if firebase_data else 0
    
    sync_status = "✅ Активна" if FIREBASE_INITIALIZED and firebase_data else "❌ Неактивна"
    balance_match = "✅ Совпадают" if local_balance == firebase_balance else "⚠️ Различаются"
    
    # Статистика рефералов
    total_referrals = get_total_earned_bonuses(user_id)
    pending_bonuses = get_pending_bonuses_count(user_id)
    paid_bonuses = get_paid_bonuses_count(user_id)
    
    return f"""
<b>Статистика синхронизации</b>

📊 Локальный баланс: <b>{local_balance}₽</b>
☁️ Баланс в Firebase: <b>{firebase_balance}₽</b>
🔀 Соответствие: <b>{balance_match}</b>

🔄 Статус синхронизации: <b>{sync_status}</b>

<b>Реферальная статистика:</b>
├ Всего приглашено: <b>{total_referrals} чел.</b>
├ Ожидает выплаты: <b>{pending_bonuses} чел.</b>
└ Выплачено: <b>{paid_bonuses} чел.</b>

Все изменения автоматически сохраняются в облако.
"""

# Функции работы с подпиской
def check_user_subscription(user_id: int):
    conn = sqlite3.connect('vacvpn.db')
    cursor = conn.cursor()
    cursor.execute('SELECT has_subscription, subscription_end FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        return False
    
    has_sub, sub_end = result
    if has_sub and sub_end:
        subscription_active = datetime.now() < datetime.fromisoformat(sub_end)
        
        # Автоматическая синхронизация статуса подписки с Firebase
        subscription_data = {
            'active': subscription_active,
            'end_date': sub_end if subscription_active else None,
            'last_checked': datetime.now().isoformat()
        }
        update_subscription_in_firebase(user_id, subscription_data)
        
        return subscription_active
    return False

def activate_user_subscription(user_id: int, days: int):
    end_date = (datetime.now() + timedelta(days=days)).isoformat()
    conn = sqlite3.connect('vacvpn.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO users (user_id, has_subscription, subscription_end)
        VALUES (?, TRUE, ?)
    ''', (user_id, end_date))
    conn.commit()
    conn.close()
    
    # Автоматическая синхронизация с Firebase
    subscription_data = {
        'active': True,
        'end_date': end_date,
        'days': days,
        'activated_at': datetime.now().isoformat()
    }
    update_subscription_in_firebase(user_id, subscription_data)

# Обработчики команд
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user
    args = message.text.split()
    is_referral = False

    # Автоматически создаем/обновляем пользователя
    create_or_update_user(
        user.id, 
        user.username or "", 
        user.first_name or "", 
        user.last_name or ""
    )

    if len(args) > 1 and args[1].startswith('ref_'):
        referrer_id = int(args[1][4:])
        referred_id = user.id

        if referred_id != referrer_id:
            if referrer_id not in referrals_db:
                referrals_db[referrer_id] = []

            if referred_id not in referrals_db[referrer_id]:
                referrals_db[referrer_id].append(referred_id)
                # Теперь НЕ начисляем бонус сразу, а только записываем в БД
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
    # Автоматически синхронизируем данные перед показом личного кабинета
    user_id = message.from_user.id
    user_data = {
        'user_id': user_id,
        'username': message.from_user.username or "",
        'first_name': message.from_user.first_name or "",
        'last_name': message.from_user.last_name or "",
        'balance': user_balances.get(user_id, 0),
        'subscription': {
            'active': check_user_subscription(user_id),
            'end_date': None
        },
        'last_sync': datetime.now().isoformat()
    }
    sync_user_to_firebase(user_id, user_data)
    
    await message.answer(
        text=get_cabinet_message(message.from_user.id),
        reply_markup=get_cabinet_keyboard()
    )

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
    await message.answer(
        text=get_stats_message(message.from_user.id)
    )

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

# Обработчик для проверки подписки
@dp.message(lambda message: message.text == "🔐 Проверить подписку")
async def check_subscription_handler(message: types.Message):
    has_sub = check_user_subscription(message.from_user.id)
    await message.answer(
        f"Статус подписки: {'✅ Активна' if has_sub else '❌ Неактивна'}"
    )

# Команда для принудительной синхронизации (на всякий случай)
@dp.message(Command("sync"))
async def cmd_sync(message: types.Message):
    user_id = message.from_user.id
    user_data = {
        'user_id': user_id,
        'username': message.from_user.username or "",
        'first_name': message.from_user.first_name or "",
        'last_name': message.from_user.last_name or "",
        'balance': user_balances.get(user_id, 0),
        'subscription': {
            'active': check_user_subscription(user_id),
            'end_date': None
        },
        'last_sync': datetime.now().isoformat()
    }
    sync_user_to_firebase(user_id, user_data)
    await message.answer("✅ Данные автоматически синхронизированы с Firebase!")

# Команда для админа чтобы вручную начислить бонусы
@dp.message(Command("pay_bonus"))
async def cmd_pay_bonus(message: types.Message):
    # Проверяем, является ли пользователь админом (добавьте свою логику проверки)
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
        
        # Находим все ожидающие бонусы для этого пользователя
        conn = sqlite3.connect('vacvpn.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, referred_id FROM referral_bonuses 
            WHERE referrer_id = ? AND paid_out = FALSE
        ''', (user_id,))
        
        pending_bonuses = cursor.fetchall()
        
        if not pending_bonuses:
            await message.answer(f"❌ У пользователя {user_id} нет ожидающих бонусов.")
            conn.close()
            return
        
        total_bonus = len(pending_bonuses) * 50
        
        # Начисляем бонусы
        current_balance = user_balances.get(user_id, 0)
        user_balances[user_id] = current_balance + total_bonus
        
        # Обновляем статус бонусов как выплаченные
        for bonus_id, referred_id in pending_bonuses:
            cursor.execute('''
                UPDATE referral_bonuses 
                SET paid_out = TRUE, paid_out_at = ?
                WHERE id = ?
            ''', (datetime.now().isoformat(), bonus_id))
        
        conn.commit()
        conn.close()
        
        # Обновляем баланс в Firebase
        update_balance_in_firebase(user_id, user_balances[user_id])
        
        await message.answer(f"✅ Пользователю {user_id} начислено {total_bonus}₽ за {len(pending_bonuses)} рефералов.")
        
        # Уведомляем пользователя
        try:
            await bot.send_message(
                chat_id=user_id,
                text=f"🎉 Вам начислен реферальный бонус: {total_bonus}₽ за {len(pending_bonuses)} приглашенных друзей!"
            )
        except:
            pass
            
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

async def main():
    # Добавим информацию о статусе при запуске
    if FIREBASE_INITIALIZED:
        print("✅ Бот запущен с автоматической синхронизацией Firebase")
    else:
        print("⚠️ Бот запущен без Firebase. Данные будут храниться только локально.")
    
    await bot.set_chat_menu_button(
        menu_button=types.MenuButtonWebApp(
            text="VAC VPN",
            web_app=WebAppInfo(url=WEB_APP_URL)
        )
    )
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
