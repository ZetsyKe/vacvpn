from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
import uuid
import httpx
from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, firestore
from pydantic import BaseModel
import logging
import secrets
import string
import json
import tempfile

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
        # Способ 1: Попробуем загрузить из полного JSON
        firebase_credentials_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
        
        if firebase_credentials_json:
            logger.info("🚀 Initializing Firebase from FIREBASE_CREDENTIALS_JSON")
            firebase_config = json.loads(firebase_credentials_json)
            cred = credentials.Certificate(firebase_config)
        else:
            # Способ 2: Собираем конфиг из отдельных переменных
            logger.info("🚀 Initializing Firebase from individual environment variables")
            
            private_key = os.getenv("FIREBASE_PRIVATE_KEY", "").replace('\\n', '\n')
            
            if not private_key:
                raise ValueError("FIREBASE_PRIVATE_KEY environment variable is empty")
            
            firebase_config = {
                "type": "service_account",
                "project_id": os.getenv("FIREBASE_PROJECT_ID", "vacvpn-75yegf"),
                "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID", "8e6469cea94608d13c03d57a60f70ad7269e9421"),
                "private_key": private_key,
                "client_email": os.getenv("FIREBASE_CLIENT_EMAIL", "firebase-adminsdk-fbsvc@vacvpn-75yegf.iam.gserviceaccount.com"),
                "client_id": os.getenv("FIREBASE_CLIENT_ID", "118426875107507915166"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_X509_CERT_URL", "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%40vacvpn-75yegf.iam.gserviceaccount.com"),
                "universe_domain": "googleapis.com"
            }
            
            cred = credentials.Certificate(firebase_config)
        
        firebase_admin.initialize_app(cred)
    
    db = firestore.client()
    logger.info("✅ Firebase initialized successfully")
    
except Exception as e:
    logger.error(f"❌ Firebase initialization failed: {str(e)}")
    import traceback
    logger.error(traceback.format_exc())
    db = None

# Модели данных
class PaymentRequest(BaseModel):
    user_id: str
    amount: float
    tariff: str = "month"
    payment_type: str = "tariff"

class UserCreateRequest(BaseModel):
    user_id: str
    username: str = ""
    first_name: str = ""
    last_name: str = ""

class ActivateTariffRequest(BaseModel):
    user_id: str
    tariff: str

class InitUserRequest(BaseModel):
    user_id: str
    username: str = ""
    first_name: str = ""
    last_name: str = ""

# Функции работы с Firebase
def get_user(user_id: str):
    if not db: 
        logger.error("❌ Database not connected")
        return None
    try:
        doc = db.collection('users').document(user_id).get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        logger.error(f"❌ Error getting user: {e}")
        return None

def create_user(user_data: UserCreateRequest):
    if not db: 
        logger.error("❌ Database not connected")
        return
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
                'vpn_key': None,
                'created_at': firestore.SERVER_TIMESTAMP
            })
            logger.info(f"✅ User created: {user_data.user_id}")
    except Exception as e:
        logger.error(f"❌ Error creating user: {e}")

def update_user_balance(user_id: str, amount: float):
    if not db: 
        logger.error("❌ Database not connected")
        return
    try:
        user_ref = db.collection('users').document(user_id)
        user = user_ref.get()
        if user.exists:
            current_balance = user.to_dict().get('balance', 0)
            user_ref.update({'balance': current_balance + amount})
            logger.info(f"✅ Balance updated for user {user_id}: +{amount}")
    except Exception as e:
        logger.error(f"❌ Error updating balance: {e}")

def generate_vpn_key():
    """Генерирует уникальный VPN ключ"""
    alphabet = string.ascii_letters + string.digits
    return 'vpn_' + ''.join(secrets.choice(alphabet) for _ in range(16))

def activate_subscription(user_id: str, tariff: str, days: int):
    if not db: 
        logger.error("❌ Database not connected")
        return None, None
    try:
        now = datetime.now()
        new_end = now + timedelta(days=days)
        
        # Генерируем VPN ключ
        vpn_key = generate_vpn_key()
        
        db.collection('users').document(user_id).update({
            'has_subscription': True,
            'subscription_end': new_end.isoformat(),
            'tariff_type': tariff,
            'vpn_key': vpn_key
        })
        logger.info(f"✅ Subscription activated for user {user_id}: {days} days, VPN key: {vpn_key}")
        return new_end, vpn_key
    except Exception as e:
        logger.error(f"❌ Error activating subscription: {e}")
        return None, None

def save_payment(payment_id: str, user_id: str, amount: float, tariff: str, payment_type: str = "tariff"):
    if not db: 
        logger.error("❌ Database not connected")
        return
    try:
        db.collection('payments').document(payment_id).set({
            'payment_id': payment_id,
            'user_id': user_id,
            'amount': amount,
            'tariff': tariff,
            'status': 'pending',
            'payment_type': payment_type,
            'created_at': firestore.SERVER_TIMESTAMP,
            'yookassa_id': None
        })
        logger.info(f"✅ Payment saved: {payment_id} for user {user_id}")
    except Exception as e:
        logger.error(f"❌ Error saving payment: {e}")

def update_payment_status(payment_id: str, status: str, yookassa_id: str = None):
    if not db: 
        logger.error("❌ Database not connected")
        return
    try:
        update_data = {
            'status': status,
            'yookassa_id': yookassa_id
        }
        if status == 'succeeded':
            update_data['confirmed_at'] = firestore.SERVER_TIMESTAMP
        
        db.collection('payments').document(payment_id).update(update_data)
        logger.info(f"✅ Payment status updated: {payment_id} -> {status}")
    except Exception as e:
        logger.error(f"❌ Error updating payment status: {e}")

def get_payment(payment_id: str):
    if not db: 
        logger.error("❌ Database not connected")
        return None
    try:
        doc = db.collection('payments').document(payment_id).get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        logger.error(f"❌ Error getting payment: {e}")
        return None

def add_referral(referrer_id: str, referred_id: str):
    if not db: 
        logger.error("❌ Database not connected")
        return
    try:
        referral_id = f"{referrer_id}_{referred_id}"
        db.collection('referrals').document(referral_id).set({
            'referrer_id': referrer_id,
            'referred_id': referred_id,
            'bonus_paid': False,
            'created_at': firestore.SERVER_TIMESTAMP
        })
        logger.info(f"✅ Referral added: {referrer_id} -> {referred_id}")
    except Exception as e:
        logger.error(f"❌ Error adding referral: {e}")

def get_referrals(referrer_id: str):
    if not db: 
        logger.error("❌ Database not connected")
        return []
    try:
        referrals = db.collection('referrals').where('referrer_id', '==', referrer_id).stream()
        return [ref.to_dict() for ref in referrals]
    except Exception as e:
        logger.error(f"❌ Error getting referrals: {e}")
        return []

def mark_referral_bonus_paid(referred_id: str):
    if not db: 
        logger.error("❌ Database not connected")
        return
    try:
        referrals = db.collection('referrals').where('referred_id', '==', referred_id).stream()
        for ref in referrals:
            ref.reference.update({'bonus_paid': True})
        logger.info(f"✅ Referral bonus paid for: {referred_id}")
    except Exception as e:
        logger.error(f"❌ Error marking referral bonus paid: {e}")

# Эндпоинты API
@app.get("/")
async def root():
    return {"message": "VAC VPN API is running", "status": "ok", "firebase": "connected" if db else "disconnected"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat(), "firebase": "connected" if db else "disconnected"}

@app.post("/init-user")
async def init_user(request: InitUserRequest):
    """Автоматическое создание пользователя при заходе на сайт"""
    try:
        if not db:
            return {"error": "Database not connected"}
        
        # Проверяем user_id
        if not request.user_id or request.user_id == 'unknown':
            return {"error": "Invalid user ID"}
        
        # Создаем пользователя если не существует
        user_ref = db.collection('users').document(request.user_id)
        if not user_ref.get().exists:
            user_ref.set({
                'user_id': request.user_id,
                'username': request.username,
                'first_name': request.first_name,
                'last_name': request.last_name,
                'balance': 0.0,
                'has_subscription': False,
                'subscription_end': None,
                'tariff_type': 'none',
                'vpn_key': None,
                'created_at': firestore.SERVER_TIMESTAMP
            })
            logger.info(f"✅ User auto-created: {request.user_id}")
            return {"success": True, "message": "User created", "user_id": request.user_id}
        else:
            return {"success": True, "message": "User already exists", "user_id": request.user_id}
            
    except Exception as e:
        logger.error(f"❌ Error initializing user: {e}")
        return {"error": str(e)}

@app.get("/user-data")
async def get_user_info(user_id: str):
    try:
        if not db:
            return {"error": "Database not connected"}
        
        if not user_id or user_id == 'unknown':
            return {"error": "Invalid user ID"}
            
        user = get_user(user_id)
        if not user:
            return {
                "user_id": user_id,
                "balance": 0,
                "has_subscription": False,
                "subscription_end": None,
                "tariff_type": "none",
                "days_remaining": 0,
                "vpn_key": None
            }
        
        has_subscription = user.get('has_subscription', False)
        subscription_end = user.get('subscription_end')
        vpn_key = user.get('vpn_key')
        days_remaining = 0
        
        if has_subscription and subscription_end:
            try:
                end_date = datetime.fromisoformat(subscription_end.replace('Z', '+00:00'))
                now = datetime.now().replace(tzinfo=end_date.tzinfo) if end_date.tzinfo else datetime.now()
                days_remaining = max(0, (end_date - now).days)
            except:
                pass
        
        return {
            "user_id": user_id,
            "balance": user.get('balance', 0),
            "has_subscription": has_subscription,
            "subscription_end": subscription_end,
            "tariff_type": user.get('tariff_type', 'none'),
            "days_remaining": days_remaining,
            "vpn_key": vpn_key
        }
        
    except Exception as e:
        return {"error": f"Error getting user info: {str(e)}"}

@app.post("/create-payment")
async def create_payment(request: PaymentRequest):
    try:
        SHOP_ID = os.getenv("SHOP_ID")
        API_KEY = os.getenv("API_KEY")
        
        if not SHOP_ID or not API_KEY:
            return {"error": "Payment gateway not configured"}
        
        if not db:
            return {"error": "Database not connected"}
        
        # Проверяем user_id
        if not request.user_id or request.user_id == 'unknown':
            return {"error": "Invalid user ID"}
        
        # Тарифы
        tariff_config = {
            "month": {"amount": 150, "description": "Месячная подписка VAC VPN"},
            "year": {"amount": 1300, "description": "Годовая подписка VAC VPN"}
        }
        
        amount = request.amount
        if request.payment_type == "tariff":
            tariff_info = tariff_config.get(request.tariff, tariff_config["month"])
            amount = tariff_info["amount"]
            description = tariff_info["description"]
        else:
            description = f"Пополнение баланса VAC VPN на {amount}₽"
        
        payment_id = str(uuid.uuid4())
        save_payment(payment_id, request.user_id, amount, request.tariff, request.payment_type)
        
        # Данные для ЮKassa
        yookassa_data = {
            "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": "https://t.me/vaaaac_bot"},
            "capture": True,
            "description": description,
            "metadata": {
                "payment_id": payment_id,
                "user_id": request.user_id,
                "tariff": request.tariff,
                "payment_type": request.payment_type
            }
        }
        
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
        
        if response.status_code in [200, 201]:
            payment_data = response.json()
            update_payment_status(payment_id, "pending", payment_data.get("id"))
            
            logger.info(f"💳 Payment created: {payment_id} for user {request.user_id}")
            
            return {
                "success": True,
                "payment_id": payment_id,
                "payment_url": payment_data["confirmation"]["confirmation_url"],
                "amount": amount,
                "status": "pending"
            }
        else:
            return {"error": f"Payment gateway error: {response.status_code}"}
            
    except Exception as e:
        logger.error(f"❌ Error creating payment: {e}")
        return {"error": f"Server error: {str(e)}"}

@app.get("/payment-status")
async def check_payment(payment_id: str, user_id: str):
    try:
        if not db:
            return {"error": "Database not connected"}
            
        if not payment_id or payment_id == 'undefined':
            return {"error": "Invalid payment ID"}
            
        payment = get_payment(payment_id)
        if not payment:
            return {"error": "Payment not found"}
        
        if payment['status'] == 'succeeded':
            return {
                "success": True,
                "status": "succeeded",
                "payment_id": payment_id,
                "amount": payment['amount'],
                "vpn_key": get_user(user_id).get('vpn_key') if get_user(user_id) else None
            }
        
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
                    
                    update_payment_status(payment_id, status, yookassa_id)
                    
                    if status == 'succeeded':
                        user_id = payment['user_id']
                        amount = payment['amount']
                        payment_type = payment['payment_type']
                        tariff = payment['tariff']
                        
                        if payment_type == 'tariff':
                            # Активируем подписку и генерируем VPN ключ
                            tariff_days = 30 if tariff == "month" else 365
                            new_end, vpn_key = activate_subscription(user_id, tariff, tariff_days)
                            
                            # Начисляем реферальный бонус
                            referrals = get_referrals(user_id)
                            for ref in referrals:
                                if not ref.get('bonus_paid', False):
                                    update_user_balance(ref['referrer_id'], 50)
                                    mark_referral_bonus_paid(user_id)
                        else:
                            # Просто пополняем баланс
                            update_user_balance(user_id, amount)
                            vpn_key = get_user(user_id).get('vpn_key') if get_user(user_id) else None
                    
                        return {
                            "success": True,
                            "status": status,
                            "payment_id": payment_id,
                            "amount": amount,
                            "vpn_key": vpn_key
                        }
        
        return {
            "success": True,
            "status": payment['status'],
            "payment_id": payment_id
        }
        
    except Exception as e:
        logger.error(f"❌ Error checking payment: {e}")
        return {"error": f"Error checking payment: {str(e)}"}

@app.post("/add-referral")
async def add_referral_endpoint(referrer_id: str, referred_id: str):
    try:
        if not db:
            return {"error": "Database not connected"}
        if referrer_id == referred_id:
            return {"error": "Cannot refer yourself"}
        
        add_referral(referrer_id, referred_id)
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}

@app.post("/activate-tariff")
async def activate_tariff(request: ActivateTariffRequest):
    try:
        if not db:
            return {"error": "Database not connected"}
            
        user = get_user(request.user_id)
        if not user:
            return {"error": "User not found"}
        
        tariff_amount = 150 if request.tariff == "month" else 1300
        user_balance = user.get('balance', 0)
        
        if user_balance < tariff_amount:
            return {"error": "Insufficient balance"}
        
        # Списываем баланс
        db.collection('users').document(request.user_id).update({
            'balance': user_balance - tariff_amount
        })
        
        # Активируем подписку и генерируем VPN ключ
        tariff_days = 30 if request.tariff == "month" else 365
        new_end, vpn_key = activate_subscription(request.user_id, request.tariff, tariff_days)
        
        return {"success": True, "days_added": tariff_days, "vpn_key": vpn_key}
        
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
