from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import os
import uuid
import httpx
from dotenv import load_dotenv
from datetime import datetime, timedelta
import sqlite3
from pydantic import BaseModel

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

class UserCreateRequest(BaseModel):
    user_id: str
    username: str = ""
    first_name: str = ""
    last_name: str = ""

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
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            confirmed_at TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referral_bonuses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id TEXT,
            referred_id TEXT,
            bonus_amount INTEGER DEFAULT 50,
            paid BOOLEAN DEFAULT FALSE,
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
    user = cursor.fetchone()
    conn.close()
    return user

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
    
    # Получаем текущую дату окончания подписки
    cursor.execute('SELECT subscription_end FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    
    now = datetime.now()
    if result and result[0]:
        current_end = datetime.fromisoformat(result[0])
        if current_end > now:
            new_end = current_end + timedelta(days=days)
        else:
            new_end = now + timedelta(days=days)
    else:
        new_end = now + timedelta(days=days)
    
    cursor.execute('''
        UPDATE users 
        SET has_subscription = TRUE, subscription_end = ?, tariff_type = ?
        WHERE user_id = ?
    ''', (new_end.isoformat(), tariff, user_id))
    
    conn.commit()
    conn.close()
    return new_end

def save_payment(payment_id: str, user_id: str, amount: float, tariff: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO payments (payment_id, user_id, amount, tariff, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (payment_id, user_id, amount, tariff, datetime.now().isoformat()))
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
    payment = cursor.fetchone()
    conn.close()
    return payment

# Эндпоинты API
@app.post("/create-payment")
async def create_payment(request: PaymentRequest):
    try:
        SHOP_ID = os.getenv("SHOP_ID")
        API_KEY = os.getenv("API_KEY")
        
        if not SHOP_ID or not API_KEY:
            return {"error": "Payment gateway not configured"}
        
        # Определяем параметры тарифа
        tariff_config = {
            "month": {"days": 30, "description": "Месячная подписка VAC VPN"},
            "year": {"days": 365, "description": "Годовая подписка VAC VPN"}
        }
        
        tariff_info = tariff_config.get(request.tariff, tariff_config["month"])
        
        # Создаем уникальный ID платежа
        payment_id = str(uuid.uuid4())
        
        # Сохраняем платеж в БД
        save_payment(payment_id, request.user_id, request.amount, request.tariff)
        
        # Данные для ЮKassa
        yookassa_data = {
            "amount": {
                "value": f"{request.amount:.2f}", 
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect", 
                "return_url": "https://t.me/vaaaac_bot"
            },
            "capture": True,
            "description": tariff_info["description"],
            "metadata": {
                "payment_id": payment_id,
                "user_id": request.user_id,
                "tariff": request.tariff
            }
        }
        
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
        
        if response.status_code in [200, 201]:
            payment_data = response.json()
            
            # Обновляем платеж с ID из ЮKassa
            update_payment_status(payment_id, "pending", payment_data.get("id"))
            
            return {
                "success": True,
                "payment_id": payment_id,
                "payment_url": payment_data["confirmation"]["confirmation_url"],
                "amount": request.amount,
                "status": "pending"
            }
        else:
            return {
                "error": f"Payment gateway error: {response.status_code}",
                "details": response.text
            }
            
    except Exception as e:
        return {"error": f"Server error: {str(e)}"}

@app.get("/check-payment")
async def check_payment(payment_id: str):
    try:
        payment = get_payment(payment_id)
        if not payment:
            return {"error": "Payment not found"}
        
        # Если платеж уже подтвержден
        if payment[6] == 'succeeded':  # status field
            return {
                "success": True,
                "status": "succeeded",
                "payment_id": payment_id,
                "amount": payment[4]  # amount field
            }
        
        # Проверяем статус в ЮKassa
        yookassa_id = payment[2]  # yookassa_id field
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
                    
                    # Если платеж успешен - активируем подписку
                    if status == 'succeeded':
                        user_id = payment[3]  # user_id field
                        tariff = payment[5]   # tariff field
                        amount = payment[4]   # amount field
                        
                        # Активируем подписку
                        tariff_days = 30 if tariff == "month" else 365
                        activate_subscription(user_id, tariff, tariff_days)
                        
                        # Начисляем баланс
                        update_user_balance(user_id, amount)
                    
                    return {
                        "success": True,
                        "status": status,
                        "payment_id": payment_id,
                        "amount": amount
                    }
        
        return {
            "success": True,
            "status": payment[6],  # current status
            "payment_id": payment_id
        }
        
    except Exception as e:
        return {"error": f"Error checking payment: {str(e)}"}

@app.get("/user-info")
async def get_user_info(user_id: str):
    try:
        user = get_user(user_id)
        if not user:
            return {
                "user_id": user_id,
                "balance": 0,
                "has_subscription": False,
                "subscription_end": None,
                "tariff_type": "none"
            }
        
        # Проверяем статус подписки
        has_subscription = bool(user[5])  # has_subscription field
        subscription_end = user[6]        # subscription_end field
        
        if has_subscription and subscription_end:
            end_date = datetime.fromisoformat(subscription_end)
            if end_date < datetime.now():
                # Подписка истекла
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('UPDATE users SET has_subscription = FALSE WHERE user_id = ?', (user_id,))
                conn.commit()
                conn.close()
                has_subscription = False
        
        return {
            "user_id": user_id,
            "balance": user[4] or 0,  # balance field
            "has_subscription": has_subscription,
            "subscription_end": subscription_end,
            "tariff_type": user[7] or "none"  # tariff_type field
        }
        
    except Exception as e:
        return {"error": f"Error getting user info: {str(e)}"}

@app.post("/create-user")
async def create_user_endpoint(request: UserCreateRequest):
    try:
        create_user(request)
        return {"success": True, "user_id": request.user_id}
    except Exception as e:
        return {"error": str(e)}

@app.get("/check-subscription")
async def check_subscription(user_id: str):
    user_info = await get_user_info(user_id)
    if "error" in user_info:
        return user_info
    
    return {
        "active": user_info["has_subscription"],
        "subscription_end": user_info["subscription_end"],
        "days_remaining": max(0, (datetime.fromisoformat(user_info["subscription_end"]) - datetime.now()).days) 
        if user_info["subscription_end"] else 0
    }

# Webhook для ЮKassa (опционально)
@app.post("/yookassa-webhook")
async def yookassa_webhook(request: Request):
    try:
        data = await request.json()
        
        payment_id = data.get('object', {}).get('id')
        status = data.get('object', {}).get('status')
        
        if status == 'succeeded':
            # Находим наш payment_id по ID ЮKassa
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT payment_id, user_id, tariff, amount FROM payments WHERE yookassa_id = ?', (payment_id,))
            payment = cursor.fetchone()
            
            if payment:
                our_payment_id, user_id, tariff, amount = payment
                
                # Активируем подписку
                tariff_days = 30 if tariff == "month" else 365
                activate_subscription(user_id, tariff, tariff_days)
                
                # Начисляем баланс
                update_user_balance(user_id, amount)
                
                # Обновляем статус платежа
                update_payment_status(our_payment_id, 'succeeded', payment_id)
        
        return {"status": "ok"}
    
    except Exception as e:
        print(f"Webhook error: {e}")
        return {"status": "error"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
