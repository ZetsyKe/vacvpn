from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import os
import uuid
import httpx
from dotenv import load_dotenv
from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, firestore
from pydantic import BaseModel
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv('backend/key.env')

app = FastAPI(title="VAC VPN API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Инициализация Firebase
try:
    if not firebase_admin._apps:
        firebase_config = {
            "type": "service_account",
            "project_id": os.getenv("FIREBASE_PROJECT_ID"),
            "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
            "private_key": os.getenv("FIREBASE_PRIVATE_KEY", "").replace('\\n', '\n'),
            "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
            "client_id": os.getenv("FIREBASE_CLIENT_ID"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        }
        cred = credentials.Certificate(firebase_config)
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    logger.info("Firebase initialized successfully")
except Exception as e:
    logger.error(f"Firebase initialization failed: {e}")
    db = None

# Модели данных
class PaymentRequest(BaseModel):
    user_id: str
    amount: float
    tariff: str = "month"
    description: str = ""
    payment_type: str = "tariff"  # tariff или balance

class UserCreateRequest(BaseModel):
    user_id: str
    username: str = ""
    first_name: str = ""
    last_name: str = ""

class ActivateTariffRequest(BaseModel):
    user_id: str
    tariff: str
    amount: float

# Функции работы с Firebase
def get_user(user_id: str):
    if not db: return None
    try:
        doc = db.collection('users').document(user_id).get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        logger.error(f"Error getting user: {e}")
        return None

def create_user(user_data: UserCreateRequest):
    if not db: return
    try:
        user_ref = db.collection('users').document(user_data.user_id)
        if not user_ref.get().exists:
            user_ref.set({
                'user_id': user_data.user_id,
                'username': user_data.username,
                'first_name': user_data.first_name,
                'last_name': user_data.last_name,
                'balance': 0.0,
                'has_subscription': False,
                'subscription_end': None,
                'tariff_type': 'none',
                'created_at': firestore.SERVER_TIMESTAMP
            })
    except Exception as e:
        logger.error(f"Error creating user: {e}")

def update_user_balance(user_id: str, amount: float):
    if not db: return
    try:
        user_ref = db.collection('users').document(user_id)
        user = user_ref.get()
        if user.exists:
            current_balance = user.to_dict().get('balance', 0)
            user_ref.update({'balance': current_balance + amount})
    except Exception as e:
        logger.error(f"Error updating balance: {e}")

def activate_subscription(user_id: str, tariff: str, days: int):
    if not db: return
    try:
        now = datetime.now()
        new_end = now + timedelta(days=days)
        
        db.collection('users').document(user_id).update({
            'has_subscription': True,
            'subscription_end': new_end.isoformat(),
            'tariff_type': tariff
        })
        return new_end
    except Exception as e:
        logger.error(f"Error activating subscription: {e}")
        return None

def save_payment(payment_id: str, user_id: str, amount: float, tariff: str, payment_type: str = "tariff"):
    if not db: return
    try:
        db.collection('payments').document(payment_id).set({
            'payment_id': payment_id,
            'user_id': user_id,
            'amount': amount,
            'tariff': tariff,
            'status': 'pending',
            'payment_type': payment_type,
            'created_at': firestore.SERVER_TIMESTAMP,
            'yookassa_id': None,
            'confirmed_at': None
        })
    except Exception as e:
        logger.error(f"Error saving payment: {e}")

def update_payment_status(payment_id: str, status: str, yookassa_id: str = None):
    if not db: return
    try:
        update_data = {
            'status': status,
            'yookassa_id': yookassa_id
        }
        if status == 'succeeded':
            update_data['confirmed_at'] = firestore.SERVER_TIMESTAMP
        
        db.collection('payments').document(payment_id).update(update_data)
    except Exception as e:
        logger.error(f"Error updating payment status: {e}")

def get_payment(payment_id: str):
    if not db: return None
    try:
        doc = db.collection('payments').document(payment_id).get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        logger.error(f"Error getting payment: {e}")
        return None

def add_referral(referrer_id: str, referred_id: str):
    if not db: return
    try:
        referral_id = f"{referrer_id}_{referred_id}"
        db.collection('referrals').document(referral_id).set({
            'referrer_id': referrer_id,
            'referred_id': referred_id,
            'bonus_paid': False,
            'created_at': firestore.SERVER_TIMESTAMP
        })
    except Exception as e:
        logger.error(f"Error adding referral: {e}")

def get_referrals(referrer_id: str):
    if not db: return []
    try:
        referrals = db.collection('referrals').where('referrer_id', '==', referrer_id).stream()
        return [ref.to_dict() for ref in referrals]
    except Exception as e:
        logger.error(f"Error getting referrals: {e}")
        return []

def mark_referral_bonus_paid(referred_id: str):
    if not db: return
    try:
        referrals = db.collection('referrals').where('referred_id', '==', referred_id).stream()
        for ref in referrals:
            ref.reference.update({'bonus_paid': True})
    except Exception as e:
        logger.error(f"Error marking referral bonus paid: {e}")

# Эндпоинты API
@app.get("/")
async def root():
    return {"message": "VAC VPN API is running", "status": "ok"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat(), "firebase": "connected" if db else "disconnected"}

@app.post("/create-payment")
async def create_payment(request: PaymentRequest):
    try:
        SHOP_ID = os.getenv("SHOP_ID")
        API_KEY = os.getenv("API_KEY")
        
        logger.info(f"Creating payment for user {request.user_id}, amount: {request.amount}, tariff: {request.tariff}")
        
        if not SHOP_ID or not API_KEY:
            logger.error("Payment gateway not configured")
            return {"error": "Payment gateway not configured"}
        
        if not db:
            return {"error": "Database not connected"}
        
        # Определяем параметры тарифа
        tariff_config = {
            "month": {"amount": 150, "description": "Месячная подписка VAC VPN"},
            "year": {"amount": 1300, "description": "Годовая подписка VAC VPN"}
        }
        
        # Используем переданную сумму или берем из конфига
        amount = request.amount
        if request.payment_type == "tariff":
            tariff_info = tariff_config.get(request.tariff, tariff_config["month"])
            amount = tariff_info["amount"]
            description = tariff_info["description"]
        else:
            description = f"Пополнение баланса VAC VPN на {amount}₽"
        
        # Создаем уникальный ID платежа
        payment_id = str(uuid.uuid4())
        
        # Сохраняем платеж в БД
        save_payment(payment_id, request.user_id, amount, request.tariff, request.payment_type)
        
        # Данные для ЮKassa
        yookassa_data = {
            "amount": {
                "value": f"{amount:.2f}", 
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect", 
                "return_url": "https://t.me/vaaaac_bot"
            },
            "capture": True,
            "description": description,
            "metadata": {
                "payment_id": payment_id,
                "user_id": request.user_id,
                "tariff": request.tariff,
                "payment_type": request.payment_type
            }
        }
        
        logger.info(f"Sending request to YooKassa: {yookassa_data}")
        
        # Создаем платеж в ЮKassa
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.yookassa.ru/v3/payments",
                auth=(SHOP_ID, API_KEY),
                headers={
                    "Content-Type": "application/json",
                    "Idempotence-Key": payment_id
                },
                json=yookassa_data,
                timeout=30.0
            )
        
        logger.info(f"YooKassa response status: {response.status_code}")
        
        if response.status_code in [200, 201]:
            payment_data = response.json()
            
            # Обновляем платеж с ID из ЮKassa
            update_payment_status(payment_id, "pending", payment_data.get("id"))
            
            return {
                "success": True,
                "payment_id": payment_id,
                "payment_url": payment_data["confirmation"]["confirmation_url"],
                "amount": amount,
                "status": "pending"
            }
        else:
            logger.error(f"YooKassa error: {response.status_code} - {response.text}")
            return {
                "error": f"Payment gateway error: {response.status_code}",
                "details": response.text
            }
            
    except Exception as e:
        logger.error(f"Server error in create_payment: {str(e)}")
        return {"error": f"Server error: {str(e)}"}

@app.get("/payment-status")
async def check_payment(payment_id: str, user_id: str):
    try:
        if not db:
            return {"error": "Database not connected"}
            
        payment = get_payment(payment_id)
        if not payment:
            return {"error": "Payment not found"}
        
        # Если платеж уже подтвержден
        if payment['status'] == 'succeeded':
            return {
                "success": True,
                "status": "succeeded",
                "payment_id": payment_id,
                "amount": payment['amount'],
                "tariff": payment['tariff'],
                "payment_type": payment['payment_type']
            }
        
        # Проверяем статус в ЮKassa
        yookassa_id = payment.get('yookassa_id')
        if yookassa_id:
            SHOP_ID = os.getenv("SHOP_ID")
            API_KEY = os.getenv("API_KEY")
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api.yookassa.ru/v3/payments/{yookassa_id}",
                    auth=(SHOP_ID, API_KEY),
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    yookassa_data = response.json()
                    status = yookassa_data.get('status')
                    
                    # Обновляем статус платежа
                    update_payment_status(payment_id, status, yookassa_id)
                    
                    # Если платеж успешен - обрабатываем
                    if status == 'succeeded':
                        user_id = payment['user_id']
                        tariff = payment['tariff']
                        amount = payment['amount']
                        payment_type = payment['payment_type']
                        
                        if payment_type == 'tariff':
                            # Активируем подписку
                            tariff_days = 30 if tariff == "month" else 365
                            activate_subscription(user_id, tariff, tariff_days)
                            
                            # Начисляем реферальный бонус
                            referrals = get_referrals(user_id)
                            for ref in referrals:
                                if not ref.get('bonus_paid', False):
                                    update_user_balance(ref['referrer_id'], 50)
                                    mark_referral_bonus_paid(user_id)
                                    logger.info(f"Referral bonus paid to {ref['referrer_id']} for user {user_id}")
                        
                        # Начисляем баланс
                        update_user_balance(user_id, amount)
                        logger.info(f"Payment succeeded for user {user_id}, amount: {amount}")
                    
                    return {
                        "success": True,
                        "status": status,
                        "payment_id": payment_id,
                        "amount": amount,
                        "tariff": tariff,
                        "payment_type": payment_type
                    }
        
        return {
            "success": True,
            "status": payment['status'],
            "payment_id": payment_id
        }
        
    except Exception as e:
        logger.error(f"Error checking payment: {str(e)}")
        return {"error": f"Error checking payment: {str(e)}"}

@app.get("/user-data")
async def get_user_info(user_id: str):
    try:
        if not db:
            return {"error": "Database not connected"}
            
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
        
        # Проверяем статус подписки
        has_subscription = user.get('has_subscription', False)
        subscription_end = user.get('subscription_end')
        days_remaining = 0
        
        if has_subscription and subscription_end:
            try:
                end_date = datetime.fromisoformat(subscription_end.replace('Z', '+00:00'))
                now = datetime.now().replace(tzinfo=end_date.tzinfo) if end_date.tzinfo else datetime.now()
                days_remaining = max(0, (end_date - now).days)
                
                if days_remaining == 0:
                    # Подписка истекла
                    db.collection('users').document(user_id).update({
                        'has_subscription': False
                    })
                    has_subscription = False
            except Exception as e:
                logger.error(f"Error parsing subscription end date: {e}")
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
        logger.error(f"Error getting user info: {str(e)}")
        return {"error": f"Error getting user info: {str(e)}"}

@app.post("/create-user")
async def create_user_endpoint(request: UserCreateRequest):
    try:
        if not db:
            return {"error": "Database not connected"}
        create_user(request)
        logger.info(f"User created: {request.user_id}")
        return {"success": True, "user_id": request.user_id}
    except Exception as e:
        logger.error(f"Error creating user: {str(e)}")
        return {"error": str(e)}

@app.post("/add-referral")
async def add_referral_endpoint(referrer_id: str, referred_id: str):
    try:
        if not db:
            return {"error": "Database not connected"}
        if referrer_id == referred_id:
            return {"error": "Cannot refer yourself"}
        
        add_referral(referrer_id, referred_id)
        logger.info(f"Referral added: {referrer_id} -> {referred_id}")
        return {"success": True}
    except Exception as e:
        logger.error(f"Error adding referral: {str(e)}")
        return {"error": str(e)}

@app.post("/activate-tariff")
async def activate_tariff(request: ActivateTariffRequest):
    try:
        if not db:
            return {"error": "Database not connected"}
            
        user = get_user(request.user_id)
        if not user:
            return {"error": "User not found"}
        
        if user.get('balance', 0) < request.amount:
            return {"error": "Insufficient balance"}
        
        # Списываем сумму с баланса
        new_balance = user.get('balance', 0) - request.amount
        db.collection('users').document(request.user_id).update({
            'balance': new_balance
        })
        
        # Активируем подписку
        tariff_days = 30 if request.tariff == "month" else 365
        activate_subscription(request.user_id, request.tariff, tariff_days)
        
        logger.info(f"Tariff activated for user {request.user_id}, days: {tariff_days}")
        return {"success": True, "days_added": tariff_days}
        
    except Exception as e:
        logger.error(f"Error activating tariff: {str(e)}")
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
