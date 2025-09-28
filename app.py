from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import os
import uuid
import httpx
from dotenv import load_dotenv
from datetime import datetime, timedelta
import sqlite3
from pydantic import BaseModel
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv('backend/key.env')

app = FastAPI(title="VAC VPN API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Модели данных
class PaymentRequest(BaseModel):
    user_id: str
    amount: float
    tariff: str = "month"
    description: str = ""
    payment_type: str = "tariff"  # tariff или balance

class UserCreateRequest(BaseModel):
    user_id: str
    username: str = ""
    first_name: str = ""
    last_name: str = ""

class ActivateTariffRequest(BaseModel):
    user_id: str
    tariff: str
    amount: float

# Инициализация БД
def init_db():
    conn = sqlite3.connect('vacvpn.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            balance REAL DEFAULT 0,
            has_subscription BOOLEAN DEFAULT FALSE,
            subscription_end TEXT,
            tariff_type TEXT DEFAULT 'none',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_id TEXT UNIQUE,
            yookassa_id TEXT,
            user_id TEXT,
            amount REAL,
            tariff TEXT,
            status TEXT DEFAULT 'pending',
            payment_type TEXT DEFAULT 'tariff',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            confirmed_at TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id TEXT,
            referred_id TEXT,
            bonus_paid BOOLEAN DEFAULT FALSE,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# Функции работы с БД
def get_db_connection():
    return sqlite3.connect('vacvpn.db')

def get_user(user_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    columns = [column[0] for column in cursor.description]
    user = cursor.fetchone()
    conn.close()
    return dict(zip(columns, user)) if user else None

def create_user(user_data: UserCreateRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_data.user_id, user_data.username, user_data.first_name, 
          user_data.last_name, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def update_user_balance(user_id: str, amount: float):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()

def activate_subscription(user_id: str, tariff: str, days: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    now = datetime.now()
    new_end = now + timedelta(days=days)
    
    cursor.execute('''
        UPDATE users 
        SET has_subscription = TRUE, subscription_end = ?, tariff_type = ?
        WHERE user_id = ?
    ''', (new_end.isoformat(), tariff, user_id))
    
    conn.commit()
    conn.close()
    return new_end

def save_payment(payment_id: str, user_id: str, amount: float, tariff: str, payment_type: str = "tariff"):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO payments (payment_id, user_id, amount, tariff, payment_type, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (payment_id, user_id, amount, tariff, payment_type, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def update_payment_status(payment_id: str, status: str, yookassa_id: str = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if status == 'succeeded':
        cursor.execute('''
            UPDATE payments 
            SET status = ?, yookassa_id = ?, confirmed_at = ?
            WHERE payment_id = ?
        ''', (status, yookassa_id, datetime.now().isoformat(), payment_id))
    else:
        cursor.execute('''
            UPDATE payments SET status = ?, yookassa_id = ? 
            WHERE payment_id = ?
        ''', (status, yookassa_id, payment_id))
    
    conn.commit()
    conn.close()

def get_payment(payment_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM payments WHERE payment_id = ?', (payment_id,))
    columns = [column[0] for column in cursor.description]
    payment = cursor.fetchone()
    conn.close()
    return dict(zip(columns, payment)) if payment else None

def add_referral(referrer_id: str, referred_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR IGNORE INTO referrals (referrer_id, referred_id, created_at)
        VALUES (?, ?, ?)
    ''', (referrer_id, referred_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_referrals(referrer_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM referrals WHERE referrer_id = ?', (referrer_id,))
    columns = [column[0] for column in cursor.description]
    referrals = cursor.fetchall()
    referrals_dict = [dict(zip(columns, row)) for row in referrals]
    conn.close()
    return referrals_dict

def mark_referral_bonus_paid(referred_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE referrals SET bonus_paid = TRUE WHERE referred_id = ?
    ''', (referred_id,))
    conn.commit()
    conn.close()

# Эндпоинты API
@app.get("/")
async def root():
    return {"message": "VAC VPN API is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.post("/create-payment")
async def create_payment(request: PaymentRequest):
    try:
        SHOP_ID = os.getenv("SHOP_ID")
        API_KEY = os.getenv("API_KEY")
        
        logger.info(f"Creating payment for user {request.user_id}, amount: {request.amount}, tariff: {request.tariff}")
        
        if not SHOP_ID or not API_KEY:
            logger.error("Payment gateway not configured")
            return {"error": "Payment gateway not configured"}
        
        # Определяем параметры тарифа
        tariff_config = {
            "month": {"amount": 150, "description": "Месячная подписка VAC VPN"},
            "year": {"amount": 1300, "description": "Годовая подписка VAC VPN"}
        }
        
        # Используем переданную сумму или берем из конфига
        amount = request.amount
        if request.payment_type == "tariff":
            tariff_info = tariff_config.get(request.tariff, tariff_config["month"])
            amount = tariff_info["amount"]
            description = tariff_info["description"]
        else:
            description = f"Пополнение баланса VAC VPN на {amount}₽"
        
        # Создаем уникальный ID платежа
        payment_id = str(uuid.uuid4())
        
        # Сохраняем платеж в БД
        save_payment(payment_id, request.user_id, amount, request.tariff, request.payment_type)
        
        # Данные для ЮKassa
        yookassa_data = {
            "amount": {
                "value": f"{amount:.2f}", 
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect", 
                "return_url": "https://t.me/vaaaac_bot"
            },
            "capture": True,
            "description": description,
            "metadata": {
                "payment_id": payment_id,
                "user_id": request.user_id,
                "tariff": request.tariff,
                "payment_type": request.payment_type
            }
        }
        
        logger.info(f"Sending request to YooKassa: {yookassa_data}")
        
        # Создаем платеж в ЮKassa
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.yookassa.ru/v3/payments",
                auth=(SHOP_ID, API_KEY),
                headers={
                    "Content-Type": "application/json",
                    "Idempotence-Key": payment_id
                },
                json=yookassa_data,
                timeout=30.0
            )
        
        logger.info(f"YooKassa response status: {response.status_code}")
        
        if response.status_code in [200, 201]:
            payment_data = response.json()
            
            # Обновляем платеж с ID из ЮKassa
            update_payment_status(payment_id, "pending", payment_data.get("id"))
            
            return {
                "success": True,
                "payment_id": payment_id,
                "payment_url": payment_data["confirmation"]["confirmation_url"],
                "amount": amount,
                "status": "pending"
            }
        else:
            logger.error(f"YooKassa error: {response.status_code} - {response.text}")
            return {
                "error": f"Payment gateway error: {response.status_code}",
                "details": response.text
            }
            
    except Exception as e:
        logger.error(f"Server error in create_payment: {str(e)}")
        return {"error": f"Server error: {str(e)}"}

@app.get("/payment-status")
async def check_payment(payment_id: str, user_id: str):
    try:
        payment = get_payment(payment_id)
        if not payment:
            return {"error": "Payment not found"}
        
        # Если платеж уже подтвержден
        if payment['status'] == 'succeeded':
            return {
                "success": True,
                "status": "succeeded",
                "payment_id": payment_id,
                "amount": payment['amount'],
                "tariff": payment['tariff'],
                "payment_type": payment['payment_type']
            }
        
        # Проверяем статус в ЮKassa
        yookassa_id = payment['yookassa_id']
        if yookassa_id:
            SHOP_ID = os.getenv("SHOP_ID")
            API_KEY = os.getenv("API_KEY")
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api.yookassa.ru/v3/payments/{yookassa_id}",
                    auth=(SHOP_ID, API_KEY),
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    yookassa_data = response.json()
                    status = yookassa_data.get('status')
                    
                    # Обновляем статус платежа
                    update_payment_status(payment_id, status, yookassa_id)
                    
                    # Если платеж успешен - обрабатываем
                    if status == 'succeeded':
                        user_id = payment['user_id']
                        tariff = payment['tariff']
                        amount = payment['amount']
                        payment_type = payment['payment_type']
                        
                        if payment_type == 'tariff':
                            # Активируем подписку
                            tariff_days = 30 if tariff == "month" else 365
                            activate_subscription(user_id, tariff, tariff_days)
                            
                            # Начисляем реферальный бонус
                            referrals = get_referrals(user_id)
                            for ref in referrals:
                                if not ref['bonus_paid']:  # Если бонус еще не выплачен
                                    update_user_balance(ref['referrer_id'], 50)  # Начисляем 50₽ рефереру
                                    mark_referral_bonus_paid(user_id)
                                    logger.info(f"Referral bonus paid to {ref['referrer_id']} for user {user_id}")
                        
                        # Начисляем баланс (для пополнения или тарифа)
                        update_user_balance(user_id, amount)
                        logger.info(f"Payment succeeded for user {user_id}, amount: {amount}")
                    
                    return {
                        "success": True,
                        "status": status,
                        "payment_id": payment_id,
                        "amount": amount,
                        "tariff": tariff,
                        "payment_type": payment_type
                    }
        
        return {
            "success": True,
            "status": payment['status'],
            "payment_id": payment_id
        }
        
    except Exception as e:
        logger.error(f"Error checking payment: {str(e)}")
        return {"error": f"Error checking payment: {str(e)}"}

@app.get("/user-data")
async def get_user_info(user_id: str):
    try:
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
        
        # Проверяем статус подписки
        has_subscription = user['has_subscription']
        subscription_end = user['subscription_end']
        days_remaining = 0
        
        if has_subscription and subscription_end:
            try:
                end_date = datetime.fromisoformat(subscription_end.replace('Z', '+00:00'))
                now = datetime.now().replace(tzinfo=end_date.tzinfo) if end_date.tzinfo else datetime.now()
                days_remaining = max(0, (end_date - now).days)
                
                if days_remaining == 0:
                    # Подписка истекла
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute('UPDATE users SET has_subscription = FALSE WHERE user_id = ?', (user_id,))
                    conn.commit()
                    conn.close()
                    has_subscription = False
            except Exception as e:
                logger.error(f"Error parsing subscription end date: {e}")
                has_subscription = False
        
        return {
            "user_id": user_id,
            "balance": user['balance'] or 0,
            "has_subscription": has_subscription,
            "subscription_end": subscription_end,
            "tariff_type": user['tariff_type'] or "none",
            "days_remaining": days_remaining
        }
        
    except Exception as e:
        logger.error(f"Error getting user info: {str(e)}")
        return {"error": f"Error getting user info: {str(e)}"}

@app.post("/create-user")
async def create_user_endpoint(request: UserCreateRequest):
    try:
        create_user(request)
        logger.info(f"User created: {request.user_id}")
        return {"success": True, "user_id": request.user_id}
    except Exception as e:
        logger.error(f"Error creating user: {str(e)}")
        return {"error": str(e)}

@app.post("/add-referral")
async def add_referral_endpoint(referrer_id: str, referred_id: str):
    try:
        if referrer_id == referred_id:
            return {"error": "Cannot refer yourself"}
        
        add_referral(referrer_id, referred_id)
        logger.info(f"Referral added: {referrer_id} -> {referred_id}")
        return {"success": True}
    except Exception as e:
        logger.error(f"Error adding referral: {str(e)}")
        return {"error": str(e)}

@app.post("/activate-tariff")
async def activate_tariff(request: ActivateTariffRequest):
    try:
        user = get_user(request.user_id)
        if not user:
            return {"error": "User not found"}
        
        if user['balance'] < request.amount:
            return {"error": "Insufficient balance"}
        
        # Списываем сумму с баланса
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', 
                      (request.amount, request.user_id))
        
        # Активируем подписку
        tariff_days = 30 if request.tariff == "month" else 365
        activate_subscription(request.user_id, request.tariff, tariff_days)
        
        conn.commit()
        conn.close()
        
        logger.info(f"Tariff activated for user {request.user_id}, days: {tariff_days}")
        return {"success": True, "days_added": tariff_days}
        
    except Exception as e:
        logger.error(f"Error activating tariff: {str(e)}")
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
