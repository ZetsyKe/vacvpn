from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import os
import uuid
import httpx
from dotenv import load_dotenv
import logging
from datetime import datetime
from typing import Dict, Set

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv('backend/key.env')

SHOP_ID = os.getenv("SHOP_ID")
API_KEY = os.getenv("API_KEY")

# Тарифные планы
TARIFFS = {
    "month": {
        "daily_rate": 5.0,  # 150 руб / 30 дней = 5 руб/день
        "price": 150
    },
    "year": {
        "daily_rate": 3.56,  # 1300 руб / 365 дней ≈ 3.56 руб/день
        "price": 1300
    }
}
REFERRAL_BONUS = 50.0

# Базы данных
users_db: Dict[str, Dict] = {}
referral_db: Dict[str, str] = {}
processed_payments: Set[str] = set()

app = FastAPI()

def update_user_balance(user_id: str, amount: float, tariff: str = "month"):
    """Обновляет баланс с учетом тарифного плана"""
    if user_id not in users_db:
        users_db[user_id] = {
            "balance": 0.0,
            "last_charge_date": datetime.now().isoformat(),
            "tariff": tariff
        }
    
    user = users_db[user_id]
    now = datetime.now()
    last_charge = datetime.fromisoformat(user["last_charge_date"]) if isinstance(user["last_charge_date"], str) else user["last_charge_date"]
    days_passed = (now - last_charge).days
    
    if days_passed > 0:
        daily_rate = TARIFFS[user["tariff"]]["daily_rate"]
        charge_amount = days_passed * daily_rate
        user["balance"] = max(0, user["balance"] - charge_amount)
        user["last_charge_date"] = now.isoformat()
        logger.info(f"Списано {charge_amount:.2f} руб. за {days_passed} дней")
    
    user["balance"] += amount
    user["tariff"] = tariff  # Обновляем тариф
    users_db[user_id] = user
    return user

@app.post("/pay")
async def create_payment(request: Request):
    try:
        body = await request.json()
        amount = float(body.get("amount", 100))
        user_id = body.get("user_id", "unknown")
        tariff = body.get("tariff", "month")
        payment_id = str(uuid.uuid4())

        data = {
            "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": "https://t.me/vaaaac_bot"},
            "capture": True,
            "description": "Пополнение баланса VAC VPN",
            "metadata": {
                "payment_id": payment_id,
                "user_id": user_id,
                "amount": amount,
                "tariff": tariff
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
            raise HTTPException(status_code=400, detail="Payment creation failed")

    except Exception as e:
        logger.error(f"Payment error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/payment-webhook")
async def payment_webhook(request: Request):
    try:
        data = await request.json()
        event = data.get('event')
        
        if event == 'payment.succeeded':
            payment = data.get('object', {})
            if payment.get('paid'):
                metadata = payment.get('metadata', {})
                payment_id = payment.get('id')
                
                if payment_id in processed_payments:
                    return {"status": "already_processed"}
                
                user_id = metadata.get('user_id')
                amount = float(metadata.get('amount', 0))
                tariff = metadata.get('tariff', 'month')
                
                if user_id and amount > 0:
                    # Зачисляем средства
                    user = update_user_balance(user_id, amount, tariff)
                    processed_payments.add(payment_id)
                    
                    # Начисляем реферальный бонус
                    if user_id in referral_db:
                        referrer_id = referral_db[user_id]
                        if referrer_id in users_db:
                            users_db[referrer_id]["balance"] += REFERRAL_BONUS
                    
                    return {"status": "success"}
        
        return {"status": "ignored"}
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/user-info")
async def get_user_info(user_id: str):
    if user_id not in users_db:
        raise HTTPException(status_code=404, detail="User not found")
    
    user = users_db[user_id]
    return {
        "balance": user["balance"],
        "tariff": user["tariff"],
        "daily_rate": TARIFFS[user["tariff"]]["daily_rate"]
    }
