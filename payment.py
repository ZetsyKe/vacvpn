from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os
import uuid
import httpx
from dotenv import load_dotenv
import logging
from datetime import datetime, timedelta
import json

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv('backend/key.env')

SHOP_ID = os.getenv("SHOP_ID")
API_KEY = os.getenv("API_KEY")

# Имитация базы данных
users_db = {}
DAILY_RATE = 5.0  # 5 рублей в день

app = FastAPI()

def update_user_balance(user_id: str, amount: float):
    """Обновляет баланс пользователя с ежедневным списанием"""
    if user_id not in users_db:
        users_db[user_id] = {
            "balance": 0.0,
            "last_charge_date": datetime.now().isoformat(),
            "tariff": "month"
        }
    
    user = users_db[user_id]
    now = datetime.now()
    last_charge = datetime.fromisoformat(user["last_charge_date"]) if isinstance(user["last_charge_date"], str) else user["last_charge_date"]
    days_passed = (now - last_charge).days
    
    if days_passed > 0:
        charge_amount = days_passed * DAILY_RATE
        user["balance"] = max(0, user["balance"] - charge_amount)
        user["last_charge_date"] = now.isoformat()
        logger.info(f"Списано {charge_amount} руб. за {days_passed} дней. Баланс: {user['balance']} руб.")
    
    user["balance"] += amount
    users_db[user_id] = user
    return user

@app.post("/pay")
async def create_payment(request: Request):
    try:
        logger.info("=== Начало обработки платежа ===")
        
        if not SHOP_ID or not API_KEY:
            error_msg = "Не настроены SHOP_ID или API_KEY в .env файле"
            logger.error(error_msg)
            return {"error": error_msg}, 500
        
        body = await request.json()
        logger.info(f"Получены данные: {body}")
        
        amount = float(body.get("amount", 100))
        user_id = body.get("user_id", "unknown")
        payment_id = str(uuid.uuid4())
        
        # Создаем платеж в ЮKassa
        data = {
            "amount": {
                "value": f"{amount:.2f}",
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": "https://t.me/vaaaac_bot"
            },
            "capture": True,
            "description": "Пополнение баланса VAC VPN",
            "metadata": {
                "payment_id": payment_id,
                "user_id": user_id
            }
        }

        logger.info(f"Отправка запроса в ЮKassa: {data}")
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.yookassa.ru/v3/payments",
                auth=(SHOP_ID, API_KEY),
                headers={
                    "Content-Type": "application/json",
                    "Idempotence-Key": payment_id
                },
                json=data,
                timeout=10
            )

        logger.info(f"Ответ ЮKassa: {resp.status_code}, {resp.text}")
        
        if resp.status_code in (200, 201):
            payment_data = resp.json()
            logger.info(f"Данные платежа: {payment_data}")
            
            if not payment_data.get("confirmation", {}).get("confirmation_url"):
                error_msg = "ЮKassa не вернула confirmation_url"
                logger.error(error_msg)
                return {"error": error_msg}, 500
            
            # Зачисляем средства на баланс
            user = update_user_balance(user_id, amount)
            days_left = int(user["balance"] / DAILY_RATE)
            
            return {
                "payment_url": payment_data["confirmation"]["confirmation_url"],
                "new_balance": user["balance"],
                "days_left": days_left
            }
        else:
            error_msg = f"Ошибка ЮKassa: {resp.status_code} - {resp.text}"
            logger.error(error_msg)
            return {"error": error_msg}, 500

    except Exception as e:
        error_msg = f"Ошибка сервера: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {"error": error_msg}, 500

@app.get("/user-info")
async def get_user_info(user_id: str):
    try:
        if user_id not in users_db:
            return {"error": "User not found"}, 404
        
        user = users_db[user_id]
        now = datetime.now()
        last_charge = datetime.fromisoformat(user["last_charge_date"]) if isinstance(user["last_charge_date"], str) else user["last_charge_date"]
        days_passed = (now - last_charge).days
        
        if days_passed > 0:
            charge_amount = days_passed * DAILY_RATE
            user["balance"] = max(0, user["balance"] - charge_amount)
            user["last_charge_date"] = now.isoformat()
            users_db[user_id] = user
            logger.info(f"Списано {charge_amount} руб. за {days_passed} дней")
        
        days_left = int(user["balance"] / DAILY_RATE)
        
        return {
            "balance": user["balance"],
            "days_left": days_left,
            "last_charge_date": user["last_charge_date"],
            "tariff": user.get("tariff", "month")
        }
        
    except Exception as e:
        error_msg = f"Ошибка сервера: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {"error": error_msg}, 500
