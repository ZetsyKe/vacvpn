import os
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
import uuid
import json

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация FastAPI
app = FastAPI(title="VAC VPN API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Простое хранилище в памяти (для демо)
users_db = {}
payments_db = {}

# Модели данных
class PaymentRequest(BaseModel):
    user_id: str
    amount: float
    tariff: str = "month"
    description: str = ""
    payment_type: str = "tariff"

class UserCreateRequest(BaseModel):
    user_id: str
    username: str = ""
    first_name: str = ""
    last_name: str = ""

# Функции работы с данными
def get_user(user_id: str):
    return users_db.get(user_id)

def create_user_in_db(user_data: UserCreateRequest):
    if user_data.user_id not in users_db:
        users_db[user_data.user_id] = {
            'user_id': str(user_data.user_id),
            'username': user_data.username,
            'first_name': user_data.first_name,
            'last_name': user_data.last_name,
            'balance': 0.0,
            'has_subscription': False,
            'subscription_end': None,
            'tariff_type': 'none',
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        logger.info(f"✅ User created: {user_data.user_id}")
    return True

def update_user_balance(user_id: str, amount: float):
    if user_id in users_db:
        current_balance = users_db[user_id].get('balance', 0)
        new_balance = current_balance + amount
        users_db[user_id]['balance'] = new_balance
        users_db[user_id]['updated_at'] = datetime.now().isoformat()
        logger.info(f"✅ Баланс обновлен: {user_id} {current_balance} -> {new_balance}")
        return True
    return False

def activate_subscription(user_id: str, tariff: str, days: int):
    if user_id not in users_db:
        create_user_in_db(UserCreateRequest(
            user_id=user_id,
            username="",
            first_name="",
            last_name=""
        ))
    
    now = datetime.now()
    new_end = now + timedelta(days=days)
    
    users_db[user_id].update({
        'has_subscription': True,
        'subscription_end': new_end.isoformat(),
        'tariff_type': tariff,
        'updated_at': datetime.now().isoformat()
    })
    
    logger.info(f"✅ Подписка активирована: {user_id} на {days} дней")
    return new_end

def save_payment(payment_data: dict):
    payment_id = payment_data['payment_id']
    payment_data['created_at'] = datetime.now().isoformat()
    payments_db[payment_id] = payment_data
    return True

def update_payment_status(payment_id: str, status: str, yookassa_id: str = None):
    if payment_id in payments_db:
        payments_db[payment_id]['status'] = status
        payments_db[payment_id]['updated_at'] = datetime.now().isoformat()
        
        if yookassa_id:
            payments_db[payment_id]['yookassa_id'] = yookassa_id
            
        if status == 'succeeded':
            payments_db[payment_id]['confirmed_at'] = datetime.now().isoformat()
        return True
    return False

def get_payment(payment_id: str):
    return payments_db.get(payment_id)

# Эндпоинты FastAPI
@app.get("/")
async def health_check():
    return {
        "status": "ok", 
        "message": "VAC VPN API is running", 
        "users_count": len(users_db),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/user-data")
async def get_user_info_endpoint(user_id: str):
    try:
        user = get_user(user_id)
        
        if not user:
            create_user_in_db(UserCreateRequest(
                user_id=user_id,
                username="",
                first_name="",
                last_name=""
            ))
            user = get_user(user_id)
        
        if not user:
            return {
                "user_id": user_id,
                "balance": 0,
                "has_subscription": False,
                "subscription_end": None,
                "tariff_type": "none",
                "days_remaining": 0
            }
        
        has_subscription = user.get('has_subscription', False)
        subscription_end = user.get('subscription_end')
        days_remaining = 0
        
        if has_subscription and subscription_end:
            try:
                end_date = datetime.fromisoformat(subscription_end.replace('Z', '+00:00'))
                if end_date > datetime.now():
                    days_remaining = (end_date - datetime.now()).days
                else:
                    users_db[user_id]['has_subscription'] = False
                    users_db[user_id]['updated_at'] = datetime.now().isoformat()
                    has_subscription = False
            except:
                has_subscription = False
        
        return {
            "user_id": user_id,
            "balance": user.get('balance', 0),
            "has_subscription": has_subscription,
            "subscription_end": subscription_end,
            "tariff_type": user.get('tariff_type', 'none'),
            "days_remaining": days_remaining
        }
        
    except Exception as e:
        logger.error(f"❌ Error in get_user_info: {e}")
        return {
            "user_id": user_id,
            "balance": 0,
            "has_subscription": False,
            "subscription_end": None,
            "tariff_type": "none",
            "days_remaining": 0
        }

@app.post("/create-user")
async def create_user_endpoint(request: UserCreateRequest):
    try:
        success = create_user_in_db(request)
        return {"success": True, "user_id": request.user_id}
    except Exception as e:
        logger.error(f"❌ Error in create-user: {e}")
        return {"success": False, "error": str(e)}

@app.post("/create-payment")
async def create_payment(request: PaymentRequest):
    try:
        logger.info(f"🔄 Creating payment for user {request.user_id}, amount: {request.amount}, tariff: {request.tariff}")
        
        is_test_payment = request.amount <= 2.00
        
        payment_id = str(uuid.uuid4())
        
        payment_data = {
            "payment_id": payment_id,
            "user_id": request.user_id,
            "amount": request.amount,
            "tariff": request.tariff,
            "payment_type": request.payment_type,
            "status": "pending",
            "description": request.description,
            "is_test": is_test_payment
        }
        save_payment(payment_data)
        
        if is_test_payment:
            logger.info(f"✅ Test payment auto-confirmed: {payment_id}")
            
            if request.payment_type == 'tariff':
                tariff_days = 30 if request.tariff == "month" else 365
                activate_subscription(request.user_id, request.tariff, tariff_days)
            else:
                update_user_balance(request.user_id, request.amount)
            
            update_payment_status(payment_id, 'succeeded', 'test_payment')
            
            return {
                "success": True,
                "payment_id": payment_id,
                "payment_url": "https://t.me/vaaaac_bot",
                "amount": request.amount,
                "status": "succeeded"
            }
        
        return {
            "success": False,
            "error": "Real payments temporarily disabled"
        }
            
    except Exception as e:
        error_msg = f"Server error: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return {"error": error_msg}

@app.get("/check-payment")
async def check_payment(payment_id: str, user_id: str):
    try:
        logger.info(f"🔄 Checking payment: {payment_id} for user: {user_id}")
        
        payment = get_payment(payment_id)
        if not payment:
            return {"error": "Payment not found"}
        
        if payment.get('is_test') or payment.get('status') == 'succeeded':
            return {
                "success": True,
                "status": "succeeded",
                "payment_id": payment_id,
                "amount": payment.get('amount'),
                "payment_type": payment.get('payment_type', 'tariff')
            }
        
        return {
            "success": True,
            "status": payment.get('status', 'pending'),
            "payment_id": payment_id
        }
        
    except Exception as e:
        error_msg = f"Error checking payment: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return {"error": error_msg}

@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
