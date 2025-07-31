from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from payment import create_payment
from dotenv import load_dotenv
import logging
import sqlite3
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://vacvpn.vercel.app", "https://web.telegram.org"],
    allow_methods=["*"],
    allow_headers=["*"],
)

load_dotenv("backend/key.env")

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
    """Основной эндпоинт для создания платежа"""
    try:
        data = await request.json()
        user_id = request.headers.get("X-Telegram-User-ID", "unknown")
        data["user_id"] = user_id
        
        result = await create_payment(request)
        
        if "error" in result:
            status_code = 400 if "Недостаточно средств" in result.get("error", "") or "активная подписка" in result.get("error", "") else 500
            logger.error(f"Ошибка платежа: {result}")
            return JSONResponse(result, status_code=status_code)
            
        return JSONResponse(result)
        
    except Exception as e:
        error_msg = f"Ошибка обработки: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return JSONResponse({"error": error_msg}, status_code=500)

@app.post("/buy-with-balance")
async def buy_with_balance(request: Request):
    """Эндпоинт для покупки через баланс"""
    try:
        data = await request.json()
        user_id = data.get("user_id")
        tariff = data.get("tariff")
        
        if not user_id or not tariff:
            return JSONResponse({"error": "Не указан user_id или tariff"}, status_code=400)
        
        # Формируем запрос для create_payment
        request._body = JSONResponse({
            "user_id": user_id,
            "tariff": tariff,
            "use_balance": True
        }).body
        
        return await payment_endpoint(request)
        
    except Exception as e:
        error_msg = f"Ошибка покупки через баланс: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return JSONResponse({"error": error_msg}, status_code=500)

@app.get("/get-balance")
async def get_balance(user_id: int):
    """Получение баланса пользователя"""
    try:
        conn = sqlite3.connect('vacvpn.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        
        if not result:
            cursor.execute('INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)', (user_id,))
            conn.commit()
            balance = 0
        else:
            balance = result[0]
        
        conn.close()
        return JSONResponse({"balance": balance})
    
    except Exception as e:
        logger.error(f"Ошибка получения баланса: {str(e)}")
        return JSONResponse({"balance": 0})

@app.get("/check-subscription")
async def check_subscription(user_id: int):
    """Проверка статуса подписки"""
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
            return JSONResponse({"has_subscription": False})
        
        has_sub, sub_end = result
        if has_sub and sub_end:
            active = datetime.now() < datetime.fromisoformat(sub_end)
            return JSONResponse({"has_subscription": active})
        
        return JSONResponse({"has_subscription": False})
    
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/")
async def health_check():
    return {"status": "ok"}
