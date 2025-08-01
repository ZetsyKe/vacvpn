from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import os
import uuid
import httpx
from dotenv import load_dotenv
import logging
from datetime import datetime
from typing import Dict, Set
import json

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv('backend/key.env')

SHOP_ID = os.getenv("SHOP_ID")
API_KEY = os.getenv("API_KEY")

# Константы
DAILY_RATES = {
    "month": 5.0,  # 150 руб / 30 дней
    "year": 3.56   # 1300 руб / 365 дней
}
REFERRAL_BONUS = 50.0
DATABASE_FILE = "data.json"

# Загрузка данных
def load_data():
    try:
        with open(DATABASE_FILE, "r") as f:
            return json.load(f)
    except:
        return {
            "users": {},
            "referrals": {},
            "processed_payments": []
        }

def save_data(data):
    with open(DATABASE_FILE, "w") as f:
        json.dump(data, f)

app = FastAPI()

@app.post("/pay")
async def create_payment(request: Request):
    data = load_data()
    try:
        body = await request.json()
        amount = float(body.get("amount", 100))
        user_id = body.get("user_id", "unknown")
        tariff = body.get("tariff", "month")
        payment_id = str(uuid.uuid4())

        # Создание платежа в ЮKassa
        yookassa_data = {
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
                json=yookassa_data,
                timeout=10
            )

        if resp.status_code in (200, 201):
            payment_data = resp.json()
            return {
                "payment_url": payment_data["confirmation"]["confirmation_url"],
                "payment_id": payment_id
            }
        raise HTTPException(status_code=400, detail="Payment creation failed")

    except Exception as e:
        logger.error(f"Payment error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/payment-webhook")
async def payment_webhook(request: Request):
    data = load_data()
    try:
        webhook_data = await request.json()
        if webhook_data.get('event') == 'payment.succeeded':
            payment = webhook_data['object']
            metadata = payment.get('metadata', {})
            payment_id = payment.get('id')
            
            if payment_id in data["processed_payments"]:
                return {"status": "already_processed"}
                
            user_id = metadata.get('user_id')
            amount = float(metadata.get('amount', 0))
            tariff = metadata.get('tariff', 'month')

            if user_id and amount > 0:
                # Обновляем баланс
                if user_id not in data["users"]:
                    data["users"][user_id] = {
                        "balance": 0.0,
                        "last_charge_date": datetime.now().isoformat(),
                        "tariff": tariff
                    }
                
                user = data["users"][user_id]
                now = datetime.now()
                last_charge = datetime.fromisoformat(user["last_charge_date"])
                days_passed = (now - last_charge).days
                
                if days_passed > 0:
                    charge_amount = days_passed * DAILY_RATES[user["tariff"]]
                    user["balance"] = max(0, user["balance"] - charge_amount)
                    user["last_charge_date"] = now.isoformat()
                
                user["balance"] += amount
                user["tariff"] = tariff
                
                # Начисляем реферальный бонус
                if user_id in data["referrals"]:
                    referrer_id = data["referrals"][user_id]
                    if referrer_id in data["users"]:
                        data["users"][referrer_id]["balance"] += REFERRAL_BONUS
                
                data["processed_payments"].append(payment_id)
                save_data(data)
                
                return {"status": "success"}
        
        return {"status": "ignored"}
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/user-info")
async def get_user_info(user_id: str):
    data = load_data()
    if user_id not in data["users"]:
        raise HTTPException(status_code=404, detail="User not found")
    
    user = data["users"][user_id]
    return {
        "balance": user["balance"],
        "tariff": user["tariff"],
        "daily_rate": DAILY_RATES[user["tariff"]]
    }

@app.post("/register-referral")
async def register_referral(referrer_id: str, user_id: str):
    data = load_data()
    if user_id not in data["referrals"]:
        data["referrals"][user_id] = referrer_id
        save_data(data)
        return {"status": "success"}
    return {"status": "already_registered"}
