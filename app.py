from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
import uuid
import httpx
from dotenv import load_dotenv
import logging
from datetime import datetime, timedelta
import sqlite3
import asyncio
from pydantic import BaseModel

# Загрузка переменных окружения
load_dotenv('backend/key.env')

app = FastAPI(title="VAC VPN API")

# CORS для веб-приложения
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
    payment_type: str = "tariff"

class UserDataRequest(BaseModel):
    user_id: str
    username: str = ""
    first_name: str = ""
    last_name: str = ""

# Подключение к БД
def get_db():
    conn = sqlite3.connect('vacvpn.db')
    try:
        yield conn
    finally:
        conn.close()

# Инициализация БД
def init_database():
    conn = sqlite3.connect('vacvpn.db')
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            balance REAL DEFAULT 0,
            has_subscription BOOLEAN DEFAULT FALSE,
            subscription_start TEXT,
            subscription_end TEXT,
            tariff_type TEXT DEFAULT 'month',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Таблица платежей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_id TEXT UNIQUE,
            yookassa_payment_id TEXT,
            user_id TEXT,
            amount REAL,
            tariff TEXT,
            days INTEGER,
            description TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    conn.commit()
    conn.close()

init_database()

# Эндпоинты для веб-приложения
@app.get("/")
async def read_index():
    return FileResponse("index.html")

@app.get("/user-data")
async def get_user_data(user_id: str, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute('''
        SELECT user_id, balance, has_subscription, subscription_end, tariff_type
        FROM users WHERE user_id = ?
    ''', (user_id,))
    
    result = cursor.fetchone()
    
    if not result:
        return {
            "user_id": user_id,
            "balance": 0,
            "has_subscription": False,
            "subscription_end": None,
            "tariff_type": "none",
            "days_remaining": 0
        }
    
    user_id, balance, has_subscription, subscription_end, tariff_type = result
    
    days_remaining = 0
    if has_subscription and subscription_end:
        end_date = datetime.fromisoformat(subscription_end)
        days_remaining = max(0, (end_date - datetime.now()).days)
    
    return {
        "user_id": user_id,
        "balance": balance,
        "has_subscription": bool(has_subscription),
        "subscription_end": subscription_end,
        "tariff_type": tariff_type,
        "days_remaining": days_remaining
    }

@app.post("/create-payment")
async def create_payment_endpoint(request: PaymentRequest):
    try:
        SHOP_ID = os.getenv("SHOP_ID")
        API_KEY = os.getenv("API_KEY")
        
        if not SHOP_ID or not API_KEY:
            return {"error": "Payment gateway not configured"}
        
        # Определяем дни по тарифу
        tariff_config = {
            "month": {"days": 30, "description": "Месячная подписка VAC VPN"},
            "year": {"days": 365, "description": "Годовая подписка VAC VPN"}
        }
        
        tariff_info = tariff_config.get(request.tariff, tariff_config["month"])
        days = tariff_info["days"]
        description = request.description or tariff_info["description"]
        
        payment_id = str(uuid.uuid4())
        
        # Создаем запись в БД
        conn = sqlite3.connect('vacvpn.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO payments 
            (payment_id, user_id, amount, tariff, days, description)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (payment_id, request.user_id, request.amount, request.tariff, days, description))
        conn.commit()
        conn.close()
        
        # Данные для ЮKassa
        yookassa_data = {
            "amount": {"value": f"{request.amount:.2f}", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": "https://t.me/vaaaac_bot"},
            "capture": True,
            "description": description,
            "metadata": {
                "payment_id": payment_id,
                "user_id": request.user_id,
                "tariff": request.tariff,
                "days": days,
                "payment_type": request.payment_type
            }
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.yookassa.ru/v3/payments",
                auth=(SHOP_ID, API_KEY),
                headers={
                    "Content-Type": "application/json",
                    "Idempotence-Key": payment_id
                },
                json=yookassa_data,
                timeout=30.0
            )
        
        if resp.status_code in (200, 201):
            payment_data = resp.json()
            
            # Обновляем запись с ID ЮKassa
            conn = sqlite3.connect('vacvpn.db')
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE payments SET yookassa_payment_id = ? 
                WHERE payment_id = ?
            ''', (payment_data.get('id'), payment_id))
            conn.commit()
            conn.close()
            
            return {
                "payment_id": payment_id,
                "payment_url": payment_data["confirmation"]["confirmation_url"],
                "amount": request.amount,
                "status": "pending"
            }
        else:
            return {"error": f"Payment gateway error: {resp.status_code}"}
            
    except Exception as e:
        return {"error": f"Server error: {str(e)}"}

@app.get("/payment-status")
async def get_payment_status(payment_id: str, user_id: str):
    try:
        conn = sqlite3.connect('vacvpn.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT status, yookassa_payment_id, amount, tariff, days
            FROM payments WHERE payment_id = ? AND user_id = ?
        ''', (payment_id, user_id))
        
        result = cursor.fetchone()
        
        if not result:
            return {"error": "Payment not found"}
        
        status, yookassa_id, amount, tariff, days = result
        
        # Если статус уже успешный
        if status == 'succeeded':
            return {
                "payment_id": payment_id,
                "status": "success",
                "amount": amount,
                "tariff": tariff
            }
        
        # Проверяем статус в ЮKassa
        if yookassa_id:
            SHOP_ID = os.getenv("SHOP_ID")
            API_KEY = os.getenv("API_KEY")
            
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"https://api.yookassa.ru/v3/payments/{yookassa_id}",
                    auth=(SHOP_ID, API_KEY),
                    timeout=10.0
                )
                
                if resp.status_code == 200:
                    yookassa_data = resp.json()
                    new_status = yookassa_data.get('status')
                    
                    # Обновляем статус в БД
                    cursor.execute('UPDATE payments SET status = ? WHERE payment_id = ?', 
                                 (new_status, payment_id))
                    
                    # Если платеж успешен - активируем подписку
                    if new_status == 'succeeded':
                        await activate_subscription(user_id, tariff, days)
                    
                    conn.commit()
                    
                    return {
                        "payment_id": payment_id,
                        "status": "success" if new_status == 'succeeded' else new_status,
                        "amount": amount,
                        "tariff": tariff
                    }
        
        return {
            "payment_id": payment_id,
            "status": status,
            "amount": amount,
            "tariff": tariff
        }
        
    except Exception as e:
        return {"error": f"Error checking status: {str(e)}"}
    finally:
        conn.close()

async def activate_subscription(user_id: str, tariff: str, days: int):
    try:
        conn = sqlite3.connect('vacvpn.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT subscription_end FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        current_time = datetime.now()
        
        if result and result[0]:
            current_end = datetime.fromisoformat(result[0])
            if current_end > current_time:
                new_end = current_end + timedelta(days=days)
            else:
                new_end = current_time + timedelta(days=days)
        else:
            new_end = current_time + timedelta(days=days)
        
        cursor.execute('''
            INSERT OR REPLACE INTO users 
            (user_id, has_subscription, subscription_start, subscription_end, tariff_type, updated_at)
            VALUES (?, TRUE, ?, ?, ?, ?)
        ''', (user_id, current_time.isoformat(), new_end.isoformat(), tariff, current_time.isoformat()))
        
        conn.commit()
        conn.close()
        
        return True
        
    except Exception as e:
        print(f"Error activating subscription: {e}")
        return False

# Эндпоинты для бота (совместимость)
@app.get("/check-subscription")
async def check_subscription(user_id: str):
    user_data = await get_user_data(user_id)
    return {
        "active": user_data["has_subscription"],
        "days_remaining": user_data["days_remaining"],
        "subscription_end": user_data["subscription_end"]
    }

@app.post("/create-user")
async def create_user(user_data: UserDataRequest):
    try:
        conn = sqlite3.connect('vacvpn.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO users 
            (user_id, username, first_name, last_name, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_data.user_id, user_data.username, user_data.first_name, 
              user_data.last_name, datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
        
        return {"success": True, "user_id": user_data.user_id}
    except Exception as e:
        return {"error": str(e)}

# Обслуживание статических файлов
app.mount("/", StaticFiles(directory="."), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
