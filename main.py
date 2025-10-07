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

# КОНФИГУРАЦИЯ VLESS СЕРВЕРОВ
VLESS_SERVERS = [
    {
        "address": "45.134.13.189",
        "port": 8443,
        "sni": "localhost",
        "uuid": "f1cc0e69-45b2-43e8-b24f-fd2197615211"
    }
]

# Тарифы (сумма которая НАЧИСЛЯЕТСЯ на баланс)
TARIFFS = {
    "month": {
        "name": "Месячный",
        "price": 150.0,        # 150₽ НАЧИСЛЯЕТСЯ на баланс
        "daily_cost": 5.0      # 5₽ в день СПИСЫВАЕТСЯ
    },
    "year": {
        "name": "Годовой", 
        "price": 1300.0,       # 1300₽ НАЧИСЛЯЕТСЯ на баланс
        "daily_cost": 3.56     # 3.56₽ в день СПИСЫВАЕТСЯ
    }
}

# Инициализация Firebase
try:
    if not firebase_admin._apps:
        firebase_credentials_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
        
        if firebase_credentials_json:
            logger.info("🚀 Initializing Firebase from FIREBASE_CREDENTIALS_JSON")
            firebase_config = json.loads(firebase_credentials_json)
            cred = credentials.Certificate(firebase_config)
        else:
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
    start_param: str = None  # Для реферальных ссылок

class ActivateTariffRequest(BaseModel):
    user_id: str
    tariff: str

class ChangeTariffRequest(BaseModel):
    user_id: str
    new_tariff: str

class InitUserRequest(BaseModel):
    user_id: str
    username: str = ""
    first_name: str = ""
    last_name: str = ""
    start_param: str = None  # Для реферальных ссылок

class UpdateBalanceRequest(BaseModel):
    user_id: str
    amount: float

class VlessConfigRequest(BaseModel):
    user_id: str

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
                'current_tariff': None,
                'subscription_start': None,
                'last_deduction_date': None,
                'vless_uuid': None,
                'created_at': firestore.SERVER_TIMESTAMP
            })
            logger.info(f"✅ User created: {user_data.user_id}")
    except Exception as e:
        logger.error(f"❌ Error creating user: {e}")

def update_user_balance(user_id: str, amount: float):
    if not db: 
        logger.error("❌ Database not connected")
        return False
    try:
        user_ref = db.collection('users').document(user_id)
        user = user_ref.get()
        if user.exists:
            current_balance = user.to_dict().get('balance', 0)
            new_balance = current_balance + amount
            user_ref.update({'balance': new_balance})
            logger.info(f"✅ Balance updated for user {user_id}: {current_balance} -> {new_balance} (+{amount})")
            return True
        else:
            logger.error(f"❌ User {user_id} not found")
            return False
    except Exception as e:
        logger.error(f"❌ Error updating balance: {e}")
        return False

def generate_vless_uuid():
    """Генерирует UUID для VLESS"""
    return str(uuid.uuid4())

def create_vless_config(user_id: str, vless_uuid: str, server_config: dict):
    """Создает VLESS конфигурацию"""
    address = server_config["address"]
    port = server_config["port"]
    sni = server_config["sni"]
    server_uuid = server_config["uuid"]
    
    # Создаем VLESS ссылку с правильными параметрами
    vless_link = f"vless://{server_uuid}@{address}:{port}?encryption=none&flow=xtls-rprx-vision&security=tls&sni={sni}&fp=randomized&type=ws&path=%2Fray&host={address}#VAC_VPN_{user_id}"
    
    # Создаем конфиг для приложений
    config = {
        "protocol": "vless",
        "uuid": server_uuid,
        "server": address,
        "port": port,
        "encryption": "none",
        "flow": "xtls-rprx-vision",
        "security": "tls",
        "sni": sni,
        "fingerprint": "randomized",
        "type": "ws",
        "path": "/ray",
        "host": address,
        "remark": f"VAC VPN - {user_id}"
    }
    
    return {
        "vless_link": vless_link,
        "config": config,
        "qr_code": f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={vless_link}"
    }

def activate_subscription(user_id: str, tariff: str):
    if not db: 
        logger.error("❌ Database not connected")
        return None
    try:
        # Используем статичный UUID сервера
        server_uuid = VLESS_SERVERS[0]["uuid"]
        logger.info(f"🆔 Using static server UUID for user {user_id}: {server_uuid}")
        
        # Обновляем данные пользователя
        user_ref = db.collection('users').document(user_id)
        
        user_doc = user_ref.get()
        if not user_doc.exists:
            logger.error(f"❌ User {user_id} not found in database")
            return None
            
        update_data = {
            'has_subscription': True,
            'current_tariff': tariff,
            'vless_uuid': server_uuid,
            'subscription_start': datetime.now().isoformat(),
            'last_deduction_date': datetime.now().isoformat(),
            'updated_at': firestore.SERVER_TIMESTAMP
        }
        
        user_ref.update(update_data)
        logger.info(f"✅ Subscription activated for user {user_id}: tariff {tariff}, UUID: {server_uuid}")
        
        return server_uuid
    except Exception as e:
        logger.error(f"❌ Error activating subscription: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None

def change_tariff(user_id: str, new_tariff: str):
    if not db: 
        logger.error("❌ Database not connected")
        return False
    try:
        user_ref = db.collection('users').document(user_id)
        
        user_doc = user_ref.get()
        if not user_doc.exists:
            logger.error(f"❌ User {user_id} not found in database")
            return False
            
        user_data = user_doc.to_dict()
        
        if not user_data.get('has_subscription', False):
            logger.error(f"❌ User {user_id} doesn't have active subscription")
            return False
            
        current_tariff = user_data.get('current_tariff')
        if current_tariff == new_tariff:
            logger.info(f"ℹ️ User {user_id} already has tariff {new_tariff}")
            return True
            
        # Меняем тариф
        user_ref.update({
            'current_tariff': new_tariff,
            'last_deduction_date': datetime.now().isoformat(),
            'updated_at': firestore.SERVER_TIMESTAMP
        })
        
        logger.info(f"✅ Tariff changed for user {user_id}: {current_tariff} -> {new_tariff}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error changing tariff: {e}")
        return False

def apply_referral_bonus(referred_id: str, referrer_id: str):
    """Начисляет бонусы за реферала"""
    if not db:
        return False
    
    try:
        # Начисляем 100₽ новому пользователю
        update_user_balance(referred_id, 100.0)
        
        # Начисляем 50₽ тому, кто пригласил
        update_user_balance(referrer_id, 50.0)
        
        # Сохраняем запись о реферале
        referral_id = f"{referrer_id}_{referred_id}"
        db.collection('referrals').document(referral_id).set({
            'referrer_id': referrer_id,
            'referred_id': referred_id,
            'new_user_bonus': 100.0,
            'referrer_bonus': 50.0,
            'bonus_paid': True,
            'created_at': firestore.SERVER_TIMESTAMP
        })
        
        logger.info(f"🎁 Referral bonuses applied: {referred_id} +100₽, {referrer_id} +50₽")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error applying referral bonus: {e}")
        return False

def process_daily_deductions(user_id: str):
    """Обрабатывает ежедневные списания за подписку"""
    if not db:
        return False
    
    try:
        user = get_user(user_id)
        if not user or not user.get('has_subscription', False):
            return True
            
        current_tariff = user.get('current_tariff')
        if not current_tariff or current_tariff not in TARIFFS:
            logger.error(f"❌ Invalid tariff for user {user_id}: {current_tariff}")
            return False
            
        last_deduction = user.get('last_deduction_date')
        today = datetime.now().date()
        
        # Если это первое списание или прошло больше дня с последнего списания
        if not last_deduction:
            deduction_date = today
        else:
            try:
                last_date = datetime.fromisoformat(last_deduction.replace('Z', '+00:00')).date()
                deduction_date = last_date
            except:
                deduction_date = today
        
        # Проверяем нужно ли списывать сегодня
        if deduction_date < today:
            daily_cost = TARIFFS[current_tariff]["daily_cost"]
            current_balance = user.get('balance', 0)
            
            if current_balance >= daily_cost:
                # Списание средств
                new_balance = current_balance - daily_cost
                db.collection('users').document(user_id).update({
                    'balance': new_balance,
                    'last_deduction_date': today.isoformat()
                })
                logger.info(f"✅ Daily deduction for user {user_id}: -{daily_cost}₽, new balance: {new_balance}₽")
                return True
            else:
                # Недостаточно средств - отключаем подписку
                db.collection('users').document(user_id).update({
                    'has_subscription': False,
                    'current_tariff': None,
                    'vless_uuid': None
                })
                logger.info(f"❌ Insufficient funds for user {user_id}, subscription deactivated")
                return False
        else:
            # Списание уже было сегодня
            return True
            
    except Exception as e:
        logger.error(f"❌ Error processing daily deductions: {e}")
        return False

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
        return False
    try:
        referral_id = f"{referrer_id}_{referred_id}"
        db.collection('referrals').document(referral_id).set({
            'referrer_id': referrer_id,
            'referred_id': referred_id,
            'bonus_paid': True,
            'bonus_amount': 50.0,
            'created_at': firestore.SERVER_TIMESTAMP
        })
        logger.info(f"✅ Referral added: {referrer_id} -> {referred_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Error adding referral: {e}")
        return False

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
    return {
        "message": "VAC VPN API is running", 
        "status": "ok", 
        "firebase": "connected" if db else "disconnected",
        "vless_server": VLESS_SERVERS[0]["address"],
        "port": VLESS_SERVERS[0]["port"]
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy", 
        "timestamp": datetime.now().isoformat(), 
        "firebase": "connected" if db else "disconnected",
        "server_config": {
            "address": VLESS_SERVERS[0]["address"],
            "port": VLESS_SERVERS[0]["port"],
            "uuid": VLESS_SERVERS[0]["uuid"][:8] + "..."
        }
    }

@app.post("/init-user")
async def init_user(request: InitUserRequest):
    """Автоматическое создание пользователя при заходе на сайт"""
    try:
        if not db:
            return {"error": "Database not connected"}
        
        # Проверяем user_id
        if not request.user_id or request.user_id == 'unknown':
            return {"error": "Invalid user ID"}
        
        # Проверяем реферальную ссылку
        is_referral = False
        referrer_id = None
        bonus_applied = False
        
        if request.start_param:
            # Обрабатываем разные форматы реферальных ссылок
            if request.start_param.startswith('ref_'):
                referrer_id = request.start_param.replace('ref_', '')
                is_referral = True
            elif request.start_param.isdigit():
                # Если start_param это просто ID пользователя
                referrer_id = request.start_param
                is_referral = True
            
            if is_referral:
                logger.info(f"🎯 Referral detected: {referrer_id} -> {request.user_id}")
        
        # Создаем пользователя если не существует
        user_ref = db.collection('users').document(request.user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            user_data = {
                'user_id': request.user_id,
                'username': request.username,
                'first_name': request.first_name,
                'last_name': request.last_name,
                'balance': 0.0,
                'has_subscription': False,
                'current_tariff': None,
                'subscription_start': None,
                'last_deduction_date': None,
                'vless_uuid': None,
                'created_at': firestore.SERVER_TIMESTAMP
            }
            
            # Если это реферал, начисляем бонусы
            if is_referral and referrer_id:
                # Проверяем что реферер существует и это не сам пользователь
                referrer = get_user(referrer_id)
                if referrer and referrer_id != request.user_id:
                    # Проверяем что бонус еще не начислялся
                    referral_id = f"{referrer_id}_{request.user_id}"
                    referral_exists = db.collection('referrals').document(referral_id).get().exists
                    
                    if not referral_exists:
                        # Начисляем 100₽ новому пользователю
                        user_data['balance'] = 100.0
                        user_data['referred_by'] = referrer_id
                        bonus_applied = True
                        
                        # Начисляем 50₽ тому, кто пригласил
                        update_user_balance(referrer_id, 50.0)
                        
                        # Сохраняем запись о реферале
                        db.collection('referrals').document(referral_id).set({
                            'referrer_id': referrer_id,
                            'referred_id': request.user_id,
                            'new_user_bonus': 100.0,
                            'referrer_bonus': 50.0,
                            'bonus_paid': True,
                            'created_at': firestore.SERVER_TIMESTAMP
                        })
                        
                        logger.info(f"🎁 Referral bonuses applied: {request.user_id} +100₽, {referrer_id} +50₽")
                    else:
                        logger.info(f"ℹ️ Referral already processed: {request.user_id}")
                else:
                    logger.warning(f"⚠️ Invalid referrer: {referrer_id}")
            
            user_ref.set(user_data)
            logger.info(f"✅ User created: {request.user_id}, referral: {is_referral}")
            
            # Если бонус был начислен, возвращаем обновленные данные пользователя
            if bonus_applied:
                user_data_after_bonus = user_ref.get().to_dict()
                return {
                    "success": True, 
                    "message": "User created with referral bonus",
                    "user_id": request.user_id,
                    "is_referral": is_referral,
                    "bonus_applied": bonus_applied,
                    "user_data": {
                        "balance": user_data_after_bonus.get('balance', 0),
                        "has_subscription": user_data_after_bonus.get('has_subscription', False),
                        "current_tariff": user_data_after_bonus.get('current_tariff'),
                        "vless_uuid": user_data_after_bonus.get('vless_uuid'),
                        "daily_cost": 0
                    }
                }
            else:
                return {
                    "success": True, 
                    "message": "User created", 
                    "user_id": request.user_id,
                    "is_referral": is_referral,
                    "bonus_applied": bonus_applied
                }
        else:
            # Пользователь уже существует
            user_data = user_doc.to_dict()
            has_bonus = user_data.get('referred_by') is not None
            
            return {
                "success": True, 
                "message": "User already exists", 
                "user_id": request.user_id,
                "is_referral": has_bonus,
                "bonus_applied": has_bonus,
                "user_data": {
                    "balance": user_data.get('balance', 0),
                    "has_subscription": user_data.get('has_subscription', False),
                    "current_tariff": user_data.get('current_tariff'),
                    "vless_uuid": user_data.get('vless_uuid'),
                    "daily_cost": TARIFFS[user_data.get('current_tariff')]["daily_cost"] if user_data.get('current_tariff') in TARIFFS else 0
                }
            }
            
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
            
        # Обрабатываем ежедневные списания
        process_daily_deductions(user_id)
            
        user = get_user(user_id)
        if not user:
            return {
                "user_id": user_id,
                "balance": 0,
                "has_subscription": False,
                "current_tariff": None,
                "vless_uuid": None,
                "daily_cost": 0
            }
        
        has_subscription = user.get('has_subscription', False)
        current_tariff = user.get('current_tariff')
        vless_uuid = user.get('vless_uuid')
        daily_cost = 0
        
        if has_subscription and current_tariff in TARIFFS:
            daily_cost = TARIFFS[current_tariff]["daily_cost"]
        
        return {
            "user_id": user_id,
            "balance": user.get('balance', 0),
            "has_subscription": has_subscription,
            "current_tariff": current_tariff,
            "vless_uuid": vless_uuid,
            "daily_cost": daily_cost
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
        
        # Определяем сумму платежа
        amount = request.amount
        if request.payment_type == "tariff":
            if request.tariff not in TARIFFS:
                return {"error": "Invalid tariff"}
            amount = TARIFFS[request.tariff]["price"]
            description = f"Покупка тарифа {TARIFFS[request.tariff]['name']} - VAC VPN"
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
                "amount": payment['amount']
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
                        
                        # Пополняем баланс
                        update_user_balance(user_id, amount)
                        
                        if payment_type == 'tariff':
                            # Активируем подписку
                            vless_uuid = activate_subscription(user_id, tariff)
                            
                            if not vless_uuid:
                                logger.error(f"❌ Failed to activate subscription for user {user_id}")
                                return {"error": "Failed to activate subscription"}
                            
                            # Начисляем реферальный бонус
                            referrals = get_referrals(user_id)
                            for ref in referrals:
                                if not ref.get('bonus_paid', False):
                                    update_user_balance(ref['referrer_id'], 50)
                                    mark_referral_bonus_paid(user_id)
                    
                        return {
                            "success": True,
                            "status": status,
                            "payment_id": payment_id,
                            "amount": amount
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
        
        success = add_referral(referrer_id, referred_id)
        if success:
            return {"success": True, "message": "Referral added successfully"}
        else:
            return {"error": "Failed to add referral"}
    except Exception as e:
        return {"error": str(e)}

@app.post("/update-balance")
async def update_balance_endpoint(request: UpdateBalanceRequest):
    """Эндпоинт для обновления баланса пользователя"""
    try:
        if not db:
            return {"error": "Database not connected"}
        
        logger.info(f"🔄 Updating balance for user {request.user_id}: +{request.amount}₽")
        
        # Обновляем баланс
        success = update_user_balance(request.user_id, request.amount)
        
        if success:
            # Получаем обновленные данные пользователя для подтверждения
            user = get_user(request.user_id)
            if user:
                return {
                    "success": True, 
                    "message": f"Баланс обновлен на +{request.amount}₽",
                    "new_balance": user.get('balance', 0)
                }
            else:
                return {"error": "User not found after update"}
        else:
            return {"error": "Failed to update balance"}
            
    except Exception as e:
        logger.error(f"❌ Error updating balance: {e}")
        return {"error": str(e)}

@app.post("/activate-tariff")
async def activate_tariff(request: ActivateTariffRequest):
    try:
        if not db:
            return {"error": "Database not connected"}
            
        user = get_user(request.user_id)
        if not user:
            return {"error": "User not found"}
        
        if request.tariff not in TARIFFS:
            return {"error": "Invalid tariff"}
            
        tariff_data = TARIFFS[request.tariff]
        tariff_price = tariff_data["price"]
        daily_cost = tariff_data["daily_cost"]
        
        # НАЧИСЛЯЕМ сумму тарифа на баланс
        new_balance = user.get('balance', 0) + tariff_price
        update_user_balance(request.user_id, tariff_price)
        
        # Активируем подписку
        vless_uuid = activate_subscription(request.user_id, request.tariff)
        
        if not vless_uuid:
            return {"error": "Failed to generate VLESS configuration"}
        
        return {
            "success": True, 
            "tariff": request.tariff,
            "tariff_name": tariff_data['name'],
            "daily_cost": daily_cost,
            "amount_added": tariff_price,
            "vless_uuid": vless_uuid,
            "new_balance": new_balance,
            "message": f"✅ Тариф активирован! На баланс добавлено {tariff_price}₽. Ежедневное списание: {daily_cost}₽"
        }
        
    except Exception as e:
        logger.error(f"❌ Error activating tariff: {e}")
        return {"error": str(e)}

@app.post("/change-tariff")
async def change_tariff_endpoint(request: ChangeTariffRequest):
    """Сменить тариф"""
    try:
        if not db:
            return {"error": "Database not connected"}
            
        user = get_user(request.user_id)
        if not user:
            return {"error": "User not found"}
        
        if not user.get('has_subscription', False):
            return {"error": "No active subscription"}
            
        if request.new_tariff not in TARIFFS:
            return {"error": "Invalid tariff"}
            
        current_tariff = user.get('current_tariff')
        if current_tariff == request.new_tariff:
            return {"error": "You already have this tariff"}
        
        # Меняем тариф
        success = change_tariff(request.user_id, request.new_tariff)
        
        if success:
            return {
                "success": True,
                "message": f"Тариф успешно изменен на {TARIFFS[request.new_tariff]['name']}",
                "new_tariff": request.new_tariff,
                "new_tariff_name": TARIFFS[request.new_tariff]['name'],
                "daily_cost": TARIFFS[request.new_tariff]['daily_cost']
            }
        else:
            return {"error": "Failed to change tariff"}
            
    except Exception as e:
        logger.error(f"❌ Error changing tariff: {e}")
        return {"error": str(e)}

@app.post("/vless-config")
async def get_vless_config(request: VlessConfigRequest):
    """Получить VLESS конфигурацию для пользователя"""
    try:
        if not db:
            return {"error": "Database not connected"}
            
        # Обрабатываем ежедневные списания перед выдачей конфигурации
        process_daily_deductions(request.user_id)
            
        user = get_user(request.user_id)
        if not user:
            return {"error": "User not found"}
        
        vless_uuid = user.get('vless_uuid')
        if not vless_uuid:
            logger.error(f"❌ VLESS UUID not found for user {request.user_id}")
            return {"error": "VLESS UUID not found. Activate subscription first."}
        
        if not user.get('has_subscription', False):
            return {"error": "No active subscription"}
        
        # Создаем конфиги для всех серверов
        configs = []
        for server in VLESS_SERVERS:
            config = create_vless_config(request.user_id, vless_uuid, server)
            configs.append(config)
        
        return {
            "success": True,
            "user_id": request.user_id,
            "vless_uuid": vless_uuid,
            "configs": configs,
            "instructions": {
                "android": "Скачайте V2RayNG из Play Store и импортируйте конфигурацию",
                "ios": "Скачайте Shadowrocket из App Store и импортируйте конфигурацию", 
                "windows": "Скачайте V2RayN и импортируйте конфигурацию",
                "macos": "Скачайте V2RayU и импортируйте конфигурацию"
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting VLESS config: {e}")
        return {"error": f"Error getting VLESS config: {str(e)}"}

@app.get("/subscription-status")
async def check_subscription_status(user_id: str):
    """Проверить статус подписки"""
    try:
        if not db:
            return {"error": "Database not connected"}
            
        # Обрабатываем ежедневные списания
        process_daily_deductions(user_id)
            
        user = get_user(user_id)
        if not user:
            return {"error": "User not found"}
        
        has_subscription = user.get('has_subscription', False)
        current_tariff = user.get('current_tariff')
        daily_cost = TARIFFS[current_tariff]["daily_cost"] if current_tariff in TARIFFS else 0
        
        return {
            "success": True,
            "has_subscription": has_subscription,
            "current_tariff": current_tariff,
            "daily_cost": daily_cost,
            "vless_uuid": user.get('vless_uuid')
        }
        
    except Exception as e:
        return {"error": str(e)}

@app.get("/check-referral")
async def check_referral(user_id: str):
    """Проверить реферальный статус пользователя"""
    try:
        if not db:
            return {"error": "Database not connected"}
            
        user = get_user(user_id)
        if not user:
            return {"error": "User not found"}
        
        referred_by = user.get('referred_by')
        has_bonus = referred_by is not None
        
        return {
            "success": True,
            "has_referral_bonus": has_bonus,
            "referred_by": referred_by,
            "bonus_amount": 100.0 if has_bonus else 0
        }
        
    except Exception as e:
        return {"error": str(e)}
        
@app.delete("/clear-all-referrals")
async def clear_all_referrals():
    """Полностью очистить всю историю рефералов (админская функция)"""
    try:
        if not db:
            return {"error": "Database not connected"}
        
        # Получаем все рефералы
        referrals_ref = db.collection('referrals')
        referrals = referrals_ref.stream()
        
        deleted_count = 0
        
        # Удаляем все рефералы
        for ref in referrals:
            ref.reference.delete()
            deleted_count += 1
        
        logger.info(f"🗑️ Deleted all referrals: {deleted_count} records")
        
        return {
            "success": True,
            "message": f"Удалено {deleted_count} реферальных записей",
            "deleted_count": deleted_count
        }
            
    except Exception as e:
        logger.error(f"❌ Error clearing referrals: {e}")
        return {"error": str(e)}
@app.post("/force-refresh-balance")
async def force_refresh_balance(user_id: str):
    """Принудительно обновить баланс пользователя"""
    try:
        if not db:
            return {"error": "Database not connected"}
        
        if not user_id or user_id == 'unknown':
            return {"error": "Invalid user ID"}
            
        user = get_user(user_id)
        if not user:
            return {"error": "User not found"}
        
        return {
            "success": True,
            "user_id": user_id,
            "balance": user.get('balance', 0),
            "has_subscription": user.get('has_subscription', False),
            "current_tariff": user.get('current_tariff'),
            "vless_uuid": user.get('vless_uuid'),
            "daily_cost": TARIFFS[user.get('current_tariff')]["daily_cost"] if user.get('current_tariff') in TARIFFS else 0
        }
        
    except Exception as e:
        logger.error(f"❌ Error refreshing balance: {e}")
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
