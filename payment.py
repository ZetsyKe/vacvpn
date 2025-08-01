from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os
import uuid
import httpx
from dotenv import load_dotenv
import logging
from datetime import datetime, timedelta
from typing import Dict

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv('backend/key.env')

SHOP_ID = os.getenv("SHOP_ID")
API_KEY = os.getenv("API_KEY")

# Имитация базы данных
users_db: Dict[str, Dict] = {}
referral_db: Dict[str, str] = {}  # user_id -> referrer_id
DAILY_RATE = 5.0  # 5 руб/день
REFERRAL_BONUS = 50.0  # 50 руб за реферала

app = FastAPI()

def update_user_balance(user_id: str, amount: float, is_referral=False):
    """Обновляет баланс пользователя с учетом реферальной программы"""
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
    
    # Начисляем бонус рефереру
    if not is_referral and amount > 0 and user_id in referral_db:
        referrer_id = referral_db[user_id]
        if referrer_id in users_db:
            users_db[referrer_id]["balance"] += REFERRAL_BONUS
            logger.info(f"Начислен реферальный бонус {REFERRAL_BONUS} руб. пользователю {referrer_id}")
    
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
        
        # Только создаем платеж в ЮKassa, но НЕ зачисляем на баланс
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
                "user_id": user_id,
                "amount": amount  # Сохраняем сумму для вебхука
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
                json=data,
                timeout=10
            )

        if resp.status_code in (200, 201):
            payment_data = resp.json()
            return {
                "payment_url": payment_data["confirmation"]["confirmation_url"],
                "payment_id": payment_id
            }
        else:
            error_msg = f"Ошибка ЮKassa: {resp.status_code} - {resp.text}"
            logger.error(error_msg)
            return {"error": error_msg}, 500

    except Exception as e:
        error_msg = f"Ошибка сервера: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {"error": error_msg}, 500

@app.post("/payment-webhook")
async def payment_webhook(request: Request):
    """Эндпоинт для обработки уведомлений от ЮKassa"""
    try:
        data = await request.json()
        event = data.get('event')
        
        if event == 'payment.succeeded':
            payment = data.get('object', {})
            if payment.get('paid') and payment.get('status') == 'succeeded':
                metadata = payment.get('metadata', {})
                user_id = metadata.get('user_id')
                amount = float(metadata.get('amount', 0))
                
                if user_id and amount > 0:
                    user = update_user_balance(user_id, amount)
                    logger.info(f"Зачислено {amount} руб. на баланс пользователя {user_id}. Новый баланс: {user['balance']}")
                    return {"status": "success"}
        
        return {"status": "ignored"}
    except Exception as e:
        logger.error(f"Ошибка в вебхуке: {str(e)}", exc_info=True)
        return {"status": "error"}, 500

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

@app.post("/register-referral")
async def register_referral(referrer_id: str, user_id: str):
    """Регистрация реферала"""
    try:
        if user_id not in referral_db:
            referral_db[user_id] = referrer_id
            logger.info(f"Пользователь {user_id} зарегистрирован по реферальной ссылке от {referrer_id}")
            return {"status": "success"}
        return {"status": "already_registered"}
    except Exception as e:
        error_msg = f"Ошибка регистрации реферала: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {"error": error_msg}, 500
