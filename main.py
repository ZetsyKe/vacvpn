from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from payment import create_payment
from dotenv import load_dotenv
import logging
import sqlite3
from datetime import datetime

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://vacvpn.vercel.app", "https://web.telegram.org"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

load_dotenv("backend/key.env")

# Инициализация БД
def init_db():
    conn = sqlite3.connect('vacvpn.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance REAL DEFAULT 0,
            has_subscription BOOLEAN DEFAULT FALSE,
            subscription_end TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.post("/create-payment")
async def payment_endpoint(request: Request):
    try:
        logger.info("Обработка запроса /create-payment")
        
        data = await request.json()
        user_id = request.headers.get("X-Telegram-User-ID", "unknown")
        data["user_id"] = user_id
        
        logger.info(f"Данные запроса: {data}")
        
        result = await create_payment(request)
        
        if "error" in result:
            logger.error(f"Ошибка платежа: {result}")
            return JSONResponse(result, status_code=500)
            
        logger.info("Платеж успешно создан")
        return JSONResponse(result)
        
    except Exception as e:
        error_msg = f"Ошибка обработки: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return JSONResponse({"error": error_msg}, status_code=500)

@app.get("/check-subscription")
async def check_subscription(user_id: int):
    try:
        conn = sqlite3.connect('vacvpn.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT has_subscription, subscription_end 
            FROM users 
            WHERE user_id = ?
        ''', (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        if not result:
            # Создаем нового пользователя с балансом 0
            conn = sqlite3.connect('vacvpn.db')
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO users (user_id, balance)
                VALUES (?, 0)
            ''', (user_id,))
            conn.commit()
            conn.close()
            return JSONResponse({"has_subscription": False, "balance": 0})
        
        has_sub, sub_end = result
        if has_sub and sub_end:
            active = datetime.now() < datetime.fromisoformat(sub_end)
            return JSONResponse({"has_subscription": active})
        
        return JSONResponse({"has_subscription": False})
    
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/get-balance")
async def get_balance(user_id: int):
    try:
        conn = sqlite3.connect('vacvpn.db')
        cursor = conn.cursor()
        
        # Проверяем существование пользователя
        cursor.execute('SELECT 1 FROM users WHERE user_id = ?', (user_id,))
        if not cursor.fetchone():
            # Создаем нового пользователя с балансом 0
            cursor.execute('''
                INSERT INTO users (user_id, balance)
                VALUES (?, 0)
            ''', (user_id,))
            conn.commit()
            balance = 0
        else:
            cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
            balance = cursor.fetchone()[0] or 0
        
        conn.close()
        return JSONResponse({"balance": balance})
    
    except Exception as e:
        logger.error(f"Ошибка получения баланса: {str(e)}")
        return JSONResponse({"balance": 0})

@app.post("/payment-webhook")
async def yookassa_webhook(request: Request):
    """Эндпоинт для вебхука от ЮKassa"""
    try:
        data = await request.json()
        event = data.get("event")
        
        if event == "payment.succeeded":
            metadata = data.get("object", {}).get("metadata", {})
            user_id = metadata.get("user_id")
            amount = float(data.get("object", {}).get("amount", {}).get("value", 0))
            
            if user_id:
                conn = sqlite3.connect('vacvpn.db')
                cursor = conn.cursor()
                
                # Обновляем баланс
                cursor.execute('''
                    INSERT OR IGNORE INTO users (user_id, balance)
                    VALUES (?, 0)
                ''', (user_id,))
                
                cursor.execute('''
                    UPDATE users 
                    SET balance = balance + ?
                    WHERE user_id = ?
                ''', (amount, user_id))
                
                conn.commit()
                conn.close()
        
        return JSONResponse({"status": "success"})
    
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/")
async def health_check():
    return {"status": "ok"}
