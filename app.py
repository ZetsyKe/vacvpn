import os
import asyncio
import httpx
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder, WebAppInfo
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import uuid
from datetime import datetime, timedelta
from pydantic import BaseModel
import firebase_admin
from firebase_admin import credentials, db as firebase_db
import json
import sqlite3
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация FastAPI
app = FastAPI(title="VAC VPN API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Загрузка переменных окружения
TOKEN = os.getenv("TOKEN")
WEB_APP_URL = "https://vacvpn.vercel.app"
SUPPORT_NICK = "@vacvpn_support"
TG_CHANNEL = "@vac_vpn"
API_BASE_URL = os.getenv("RENDER_EXTERNAL_URL", "")

if not API_BASE_URL:
    API_BASE_URL = "https://vacvpn-backend.onrender.com"

BOT_USERNAME = "vaaaac_bot"

# Инициализация Firebase
try:
    firebase_cred = os.getenv("FIREBASE_CREDENTIALS")
    if firebase_cred:
        cred_dict = json.loads(firebase_cred)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://vacvpn-75yegf-default-rtdb.firebaseio.com/'
        })
        logger.info("✅ Firebase Realtime Database инициализирован")
    else:
        logger.warning("❌ FIREBASE_CREDENTIALS not found")
except Exception as e:
    logger.error(f"❌ Firebase initialization error: {e}")

# Инициализация бота
if TOKEN:
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
else:
    logger.error("❌ TOKEN not found")
    bot = None
    dp = None

# Модели данных
class PaymentRequest(BaseModel):
    user_id: str
    amount: float
    tariff: str = "month"
    description: str = ""
    payment_type: str = "tariff"

class UserCreateRequest(BaseModel):
    user_id: str
    username: str = ""
    first_name: str = ""
    last_name: str = ""

# Инициализация БД для рефералов
def init_db():
    try:
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
        logger.info("✅ SQLite database initialized")
    except Exception as e:
        logger.error(f"❌ Error initializing database: {e}")

init_db()

# Функции для работы с рефералами
def add_referral(referrer_id: int, referred_id: int):
    try:
        conn = sqlite3.connect('vacvpn.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT id FROM referrals WHERE referrer_id = ? AND referred_id = ?', 
                      (referrer_id, referred_id))
        existing = cursor.fetchone()
        
        if not existing:
            cursor.execute('INSERT INTO referrals (referrer_id, referred_id, created_at) VALUES (?, ?, ?)',
                          (referrer_id, referred_id, datetime.now().isoformat()))
            conn.commit()
            logger.info(f"✅ Реферал добавлен: {referrer_id} -> {referred_id}")
        
        conn.close()
    except Exception as e:
        logger.error(f"❌ Error adding referral: {e}")

def get_referral_stats(user_id: int):
    try:
        conn = sqlite3.connect('vacvpn.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ?', (user_id,))
        total = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND bonus_paid = ?', (user_id, True))
        with_bonus = cursor.fetchone()[0]
        
        conn.close()
        return total, with_bonus
    except Exception as e:
        logger.error(f"❌ Error getting referral stats: {e}")
        return 0, 0

# Функции работы с Firebase
def get_user(user_id: str):
    try:
        ref = firebase_db.reference(f'users/{user_id}')
        user_data = ref.get()
        return user_data
    except Exception as e:
        logger.error(f"❌ Error getting user from Firebase: {e}")
        return None

def create_user_in_firebase(user_data: UserCreateRequest):
    try:
        ref = firebase_db.reference(f'users/{user_data.user_id}')
        
        existing_user = ref.get()
        if not existing_user:
            user_data_dict = {
                'user_id': str(user_data.user_id),
                'username': user_data.username,
                'first_name': user_data.first_name,
                'last_name': user_data.last_name,
                'balance': 0.0,
                'has_subscription': False,
                'subscription_end': None,
                'tariff_type': 'none',
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            ref.set(user_data_dict)
            logger.info(f"✅ User created in Firebase: {user_data.user_id}")
        else:
            logger.info(f"ℹ️ User already exists in Firebase: {user_data.user_id}")
            
        return True
    except Exception as e:
        logger.error(f"❌ Error creating user in Firebase: {e}")
        return False

def update_user_balance(user_id: str, amount: float):
    try:
        ref = firebase_db.reference(f'users/{user_id}')
        user_data = ref.get()
        
        if user_data:
            current_balance = user_data.get('balance', 0)
            new_balance = current_balance + amount
            
            ref.update({
                'balance': new_balance,
                'updated_at': datetime.now().isoformat()
            })
            logger.info(f"✅ Баланс обновлен: {user_id} {current_balance} -> {new_balance}")
            return True
        else:
            create_user_in_firebase(UserCreateRequest(
                user_id=user_id,
                username="",
                first_name="",
                last_name=""
            ))
            return update_user_balance(user_id, amount)
    except Exception as e:
        logger.error(f"❌ Error updating user balance in Firebase: {e}")
        return False

def activate_subscription(user_id: str, tariff: str, days: int):
    try:
        ref = firebase_db.reference(f'users/{user_id}')
        user_data = ref.get()
        
        if not user_data:
            create_user_in_firebase(UserCreateRequest(
                user_id=user_id,
                username="",
                first_name="",
                last_name=""
            ))
            user_data = {}
        
        now = datetime.now()
        
        if user_data.get('has_subscription') and user_data.get('subscription_end'):
            current_end_str = user_data['subscription_end']
            try:
                current_end = datetime.fromisoformat(current_end_str.replace('Z', '+00:00'))
                if current_end > now:
                    new_end = current_end + timedelta(days=days)
                else:
                    new_end = now + timedelta(days=days)
            except:
                new_end = now + timedelta(days=days)
        else:
            new_end = now + timedelta(days=days)
        
        ref.update({
            'has_subscription': True,
            'subscription_end': new_end.isoformat(),
            'tariff_type': tariff,
            'updated_at': datetime.now().isoformat()
        })
        
        logger.info(f"✅ Подписка активирована: {user_id} на {days} дней")
        return new_end
    except Exception as e:
        logger.error(f"❌ Error activating subscription in Firebase: {e}")
        return None

def save_payment(payment_data: dict):
    try:
        payment_id = payment_data['payment_id']
        ref = firebase_db.reference(f'payments/{payment_id}')
        payment_data['created_at'] = datetime.now().isoformat()
        ref.set(payment_data)
        return True
    except Exception as e:
        logger.error(f"❌ Error saving payment to Firebase: {e}")
        return False

def update_payment_status(payment_id: str, status: str, yookassa_id: str = None):
    try:
        ref = firebase_db.reference(f'payments/{payment_id}')
        update_data = {
            'status': status,
            'updated_at': datetime.now().isoformat()
        }
        
        if yookassa_id:
            update_data['yookassa_id'] = yookassa_id
            
        if status == 'succeeded':
            update_data['confirmed_at'] = datetime.now().isoformat()
            
        ref.update(update_data)
        return True
    except Exception as e:
        logger.error(f"❌ Error updating payment status in Firebase: {e}")
        return False

def get_payment(payment_id: str):
    try:
        ref = firebase_db.reference(f'payments/{payment_id}')
        payment = ref.get()
        return payment
    except Exception as e:
        logger.error(f"❌ Error getting payment from Firebase: {e}")
        return None

# Клавиатуры для бота
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

# Обработчики бота (если бот активен)
if bot and dp:
    @dp.message(Command("start"))
    async def cmd_start(message: types.Message):
        user = message.from_user
        args = message.text.split()
        is_referral = False

        # Создаем пользователя в Firebase
        create_user_in_firebase(UserCreateRequest(
            user_id=str(user.id),
            username=user.username or "",
            first_name=user.first_name or "",
            last_name=user.last_name or ""
        ))

        if len(args) > 1 and args[1].startswith('ref_'):
            try:
                referrer_id = int(args[1][4:])
                referred_id = user.id

                if referred_id != referrer_id:
                    add_referral(referrer_id, referred_id)
                    is_referral = True
                    
                    try:
                        await bot.send_message(
                            chat_id=referrer_id,
                            text=f"🎉 У вас новый реферал!\nПользователь @{user.username or 'без username'} присоединился по вашей ссылке.\nБонус 50₽ будет начислен после оплаты подписки."
                        )
                    except Exception as e:
                        logger.info(f"Не удалось уведомить реферера {referrer_id}: {e}")
            except ValueError:
                logger.warning(f"Неверный формат реферальной ссылки: {args[1]}")

        welcome_message = f"""
<b>Добро пожаловать в VAC VPN, {user.first_name}!</b>

🚀 Получите безопасный и быстрый доступ к интернету с нашей VPN-службой.
        """
        
        if is_referral:
            welcome_message += "\n🎉 Вы зарегистрировались по реферальной ссылке! Бонус будет начислен после активации подписки."

        await message.answer(
            text=welcome_message,
            reply_markup=get_main_keyboard()
        )

    @dp.message(Command("cabinet"))
    async def cmd_cabinet(message: types.Message):
        user_id = message.from_user.id
        try:
            user_data = get_user(str(user_id))
            if user_data:
                balance = user_data.get('balance', 0)
                has_subscription = user_data.get('has_subscription', False)
                status = "✅ Активна" if has_subscription else "❌ Неактивна"
                
                message_text = f"""
<b>Личный кабинет VAC VPN</b>

💰 Баланс: <b>{balance}₽</b>
📅 Статус подписки: <b>{status}</b>

💡 Для покупки подписки используйте веб-кабинет.
"""
            else:
                message_text = "❌ Не удалось загрузить данные. Попробуйте позже."
                
            await message.answer(message_text, reply_markup=get_cabinet_keyboard())
        except Exception as e:
            logger.error(f"Error in cabinet command: {e}")
            await message.answer("❌ Ошибка загрузки данных.", reply_markup=get_cabinet_keyboard())

    # Запуск бота в отдельной задаче
    async def run_bot():
        logger.info("🤖 Бот VAC VPN запускается...")
        try:
            await dp.start_polling(bot)
        except Exception as e:
            logger.error(f"❌ Ошибка запуска бота: {e}")

# Эндпоинты FastAPI
@app.get("/")
async def health_check():
    return {
        "status": "ok", 
        "message": "VAC VPN API is running", 
        "api_base_url": API_BASE_URL,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/user-data")
async def get_user_info_endpoint(user_id: str):
    try:
        user = get_user(user_id)
        
        if not user:
            create_user_in_firebase(UserCreateRequest(
                user_id=user_id,
                username="",
                first_name="",
                last_name=""
            ))
            user = get_user(user_id)
        
        if not user:
            return {
                "user_id": user_id,
                "balance": 0,
                "has_subscription": False,
                "subscription_end": None,
                "tariff_type": "none",
                "days_remaining": 0
            }
        
        has_subscription = user.get('has_subscription', False)
        subscription_end = user.get('subscription_end')
        days_remaining = 0
        
        if has_subscription and subscription_end:
            try:
                end_date = datetime.fromisoformat(subscription_end.replace('Z', '+00:00'))
                if end_date > datetime.now():
                    days_remaining = (end_date - datetime.now()).days
                else:
                    ref = firebase_db.reference(f'users/{user_id}')
                    ref.update({
                        'has_subscription': False,
                        'updated_at': datetime.now().isoformat()
                    })
                    has_subscription = False
            except:
                has_subscription = False
        
        return {
            "user_id": user_id,
            "balance": user.get('balance', 0),
            "has_subscription": has_subscription,
            "subscription_end": subscription_end,
            "tariff_type": user.get('tariff_type', 'none'),
            "days_remaining": days_remaining
        }
        
    except Exception as e:
        logger.error(f"❌ Error in get_user_info: {e}")
        return {
            "user_id": user_id,
            "balance": 0,
            "has_subscription": False,
            "subscription_end": None,
            "tariff_type": "none",
            "days_remaining": 0
        }

@app.post("/create-user")
async def create_user_endpoint(request: UserCreateRequest):
    try:
        success = create_user_in_firebase(request)
        return {"success": True, "user_id": request.user_id}
    except Exception as e:
        logger.error(f"❌ Error in create-user: {e}")
        return {"success": False, "error": str(e)}

@app.post("/create-payment")
async def create_payment(request: PaymentRequest):
    try:
        SHOP_ID = os.getenv("SHOP_ID")
        API_KEY = os.getenv("API_KEY")
        
        if not SHOP_ID or not API_KEY:
            return {"error": "Payment gateway not configured"}
        
        logger.info(f"🔄 Creating payment for user {request.user_id}, amount: {request.amount}, tariff: {request.tariff}")
        
        is_test_payment = request.amount <= 2.00
        
        payment_id = str(uuid.uuid4())
        
        payment_data = {
            "payment_id": payment_id,
            "user_id": request.user_id,
            "amount": request.amount,
            "tariff": request.tariff,
            "payment_type": request.payment_type,
            "status": "pending",
            "description": request.description,
            "is_test": is_test_payment
        }
        save_payment(payment_data)
        
        if is_test_payment:
            logger.info(f"✅ Test payment auto-confirmed: {payment_id}")
            
            if request.payment_type == 'tariff':
                tariff_days = 30 if request.tariff == "month" else 365
                activate_subscription(request.user_id, request.tariff, tariff_days)
            else:
                update_user_balance(request.user_id, request.amount)
            
            update_payment_status(payment_id, 'succeeded', 'test_payment')
            
            return {
                "success": True,
                "payment_id": payment_id,
                "payment_url": "https://t.me/vaaaac_bot",
                "amount": request.amount,
                "status": "succeeded"
            }
        
        # Для реальных платежей
        return {
            "success": False,
            "error": "Real payments temporarily disabled"
        }
            
    except Exception as e:
        error_msg = f"Server error: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return {"error": error_msg}

@app.get("/check-payment")
async def check_payment(payment_id: str, user_id: str):
    try:
        logger.info(f"🔄 Checking payment: {payment_id} for user: {user_id}")
        
        payment = get_payment(payment_id)
        if not payment:
            return {"error": "Payment not found"}
        
        if payment.get('is_test') or payment.get('status') == 'succeeded':
            return {
                "success": True,
                "status": "succeeded",
                "payment_id": payment_id,
                "amount": payment.get('amount'),
                "payment_type": payment.get('payment_type', 'tariff')
            }
        
        return {
            "success": True,
            "status": payment.get('status', 'pending'),
            "payment_id": payment_id
        }
        
    except Exception as e:
        error_msg = f"Error checking payment: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return {"error": error_msg}

# Запуск приложения
@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Starting VAC VPN API...")
    logger.info(f"🌐 API Base URL: {API_BASE_URL}")
    
    # Запускаем бота в фоновом режиме, если есть токен
    if TOKEN and bot:
        asyncio.create_task(run_bot())

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
