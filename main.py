from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uuid
import httpx
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация
SHOP_ID = "ваш_shop_id"  # Замените на реальный
API_KEY = "ваш_api_key"  # Замените на реальный
DAILY_RATE = 5.0  # 5 руб/день
REFERRAL_BONUS = 50.0  # 50 руб за реферала

app = FastAPI()

# Временное хранилище данных
users_db = {}
referral_db = {}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", response_class=HTMLResponse)
async def home():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.post("/create-payment")
async def create_payment(request: Request):
    try:
        data = await request.json()
        user_id = data.get("user_id")
        amount = float(data.get("amount", 100))
        tariff = data.get("tariff", "month")
        
        # Инициализация пользователя
        if user_id not in users_db:
            users_db[user_id] = {
                "balance": 0,
                "last_payment": None,
                "tariff": tariff
            }
        
        # Создаем платеж в ЮKassa
        payment_id = str(uuid.uuid4())
        payment_data = {
            "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": "https://t.me/vaaaac_bot"},
            "capture": True,
            "description": "Пополнение баланса VAC VPN",
            "metadata": {
                "user_id": user_id,
                "amount": amount,
                "payment_id": payment_id
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
                json=payment_data
            )
        
        if resp.status_code == 200:
            payment_info = resp.json()
            
            # Мгновенное зачисление баланса
            users_db[user_id]["balance"] += amount
            users_db[user_id]["last_payment"] = datetime.now().isoformat()
            
            # Начисление реферального бонуса
            if user_id in referral_db:
                referrer_id = referral_db[user_id]
                if referrer_id in users_db:
                    users_db[referrer_id]["balance"] += REFERRAL_BONUS
            
            return {
                "success": True,
                "payment_url": payment_info["confirmation"]["confirmation_url"],
                "new_balance": users_db[user_id]["balance"]
            }
        
        raise HTTPException(status_code=400, detail="Ошибка создания платежа")
    
    except Exception as e:
        logger.error(f"Payment error: {str(e)}")
        raise HTTPException(status_code=500, detail="Ошибка сервера")

@app.post("/register-referral")
async def register_referral(referrer_id: str, user_id: str):
    if user_id not in referral_db:
        referral_db[user_id] = referrer_id
        return {"status": "success"}
    return {"status": "already_registered"}

@app.get("/user-info")
async def get_user_info(user_id: str):
    if user_id not in users_db:
        raise HTTPException(status_code=404, detail="User not found")
    
    user = users_db[user_id]
    days_left = int(user["balance"] / DAILY_RATE)
    
    return {
        "balance": user["balance"],
        "days_left": days_left,
        "tariff": user["tariff"]
    }
