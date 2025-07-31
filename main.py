from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from payment import create_payment
from dotenv import load_dotenv
import logging
import sqlite3
import  datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://vacvpn.vercel.app", "https://web.telegram.org"],
    allow_methods=["POST"],
    allow_headers=["*"],
)

load_dotenv("backend/key.env")

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
