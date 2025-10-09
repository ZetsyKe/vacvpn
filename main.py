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
import re

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

# Тарифы (фиксированная подписка на период)
TARIFFS = {
    "1month": {
        "name": "1 Месяц",
        "price": 150.0,
        "days": 30
    },
    "3month": {
        "name": "3 Месяца", 
        "price": 400.0,
        "days": 90
    },
    "1year": {
        "name": "1 Год",
        "price": 1200.0,
        "days": 365
    }
}

# Реферальные бонусы (в днях)
REFERRAL_BONUS_DAYS = 7

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
    tariff: str = "1month"
    payment_type: str = "tariff"

class ActivateTariffRequest(BaseModel):
    user_id: str
    tariff: str

class InitUserRequest(BaseModel):
    user_id: str
    username: str = ""
    first_name: str = ""
    last_name: str = ""
    start_param: str = None

class VlessConfigRequest(BaseModel):
    user_id: str

# Функции работы с Firebase
def get_user(user_id: str):
    if not db: 
        return None
    try:
        doc = db.collection('users').document(user_id).get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        logger.error(f"❌ Error getting user: {e}")
        return None

def update_subscription_days(user_id: str, additional_days: int):
    """Обновляет количество дней подписки"""
    if not db: 
        return False
    try:
        user_ref = db.collection('users').document(user_id)
        user = user_ref.get()
        
        if user.exists:
            user_data = user.to_dict()
            current_days = user_data.get('subscription_days', 0)
            new_days = current_days + additional_days
            
            # Если подписка была неактивна и мы добавляем дни - активируем ее
            has_subscription = user_data.get('has_subscription', False)
            if not has_subscription and additional_days > 0:
                has_subscription = True
            
            update_data = {
                'subscription_days': new_days,
                'has_subscription': has_subscription,
                'updated_at': firestore.SERVER_TIMESTAMP
            }
            
            # Если это первая активация подписки, устанавливаем UUID
            if has_subscription and not user_data.get('vless_uuid'):
                update_data['vless_uuid'] = VLESS_SERVERS[0]["uuid"]
                update_data['subscription_start'] = datetime.now().isoformat()
            
            user_ref.update(update_data)
            logger.info(f"✅ Subscription days updated for user {user_id}: {current_days} -> {new_days} (+{additional_days})")
            return True
        else:
            logger.error(f"❌ User {user_id} not found")
            return False
    except Exception as e:
        logger.error(f"❌ Error updating subscription days: {e}")
        return False

def create_user(user_data: dict):
    if not db: 
        return
    try:
        user_ref = db.collection('users').document(user_data['user_id'])
        if not user_ref.get().exists:
            user_ref.set({
                'user_id': user_data['user_id'],
                'username': user_data.get('username', ''),
                'first_name': user_data.get('first_name', ''),
                'last_name': user_data.get('last_name', ''),
                'balance': 0.0,
                'has_subscription': False,
                'subscription_days': 0,
                'subscription_start': None,
                'vless_uuid': None,
                'created_at': firestore.SERVER_TIMESTAMP
            })
            logger.info(f"✅ User created: {user_data['user_id']}")
    except Exception as e:
        logger.error(f"❌ Error creating user: {e}")

def create_vless_config(user_id: str, vless_uuid: str, server_config: dict):
    """Создает VLESS конфигурацию"""
    address = server_config["address"]
    port = server_config["port"]
    sni = server_config["sni"]
    server_uuid = server_config["uuid"]
    
    vless_link = f"vless://{server_uuid}@{address}:{port}?encryption=none&flow=xtls-rprx-vision&security=tls&sni={sni}&fp=randomized&type=ws&path=%2Fray&host={address}#VAC_VPN_{user_id}"
    
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

def process_subscription_days(user_id: str):
    """Обрабатывает списание дней подписки"""
    if not db:
        return False
    
    try:
        user = get_user(user_id)
        if not user or not user.get('has_subscription', False):
            return True
            
        subscription_days = user.get('subscription_days', 0)
        last_check = user.get('last_subscription_check')
        today = datetime.now().date()
        
        # Если это первая проверка или прошло больше дня с последней проверки
        if not last_check:
            # Устанавливаем дату первой проверки
            db.collection('users').document(user_id).update({
                'last_subscription_check': today.isoformat()
            })
            return True
        else:
            try:
                last_date = datetime.fromisoformat(last_check.replace('Z', '+00:00')).date()
                days_passed = (today - last_date).days
                
                if days_passed > 0:
                    # Списываем дни
                    new_days = max(0, subscription_days - days_passed)
                    
                    update_data = {
                        'subscription_days': new_days,
                        'last_subscription_check': today.isoformat()
                    }
                    
                    # Если дни закончились - деактивируем подписку
                    if new_days == 0:
                        update_data['has_subscription'] = False
                    
                    db.collection('users').document(user_id).update(update_data)
                    logger.info(f"✅ Subscription days processed for user {user_id}: {subscription_days} -> {new_days} (-{days_passed} days)")
                    
            except Exception as e:
                logger.error(f"❌ Error processing subscription days: {e}")
        
        return True
            
    except Exception as e:
        logger.error(f"❌ Error processing subscription: {e}")
        return False

def save_payment(payment_id: str, user_id: str, amount: float, tariff: str, payment_type: str = "tariff"):
    if not db: 
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
        return None
    try:
        doc = db.collection('payments').document(payment_id).get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        logger.error(f"❌ Error getting payment: {e}")
        return None

def add_referral(referrer_id: str, referred_id: str):
    if not db: 
        return False
    try:
        referral_id = f"{referrer_id}_{referred_id}"
        db.collection('referrals').document(referral_id).set({
            'referrer_id': referrer_id,
            'referred_id': referred_id,
            'bonus_paid': True,
            'bonus_days': REFERRAL_BONUS_DAYS,
            'created_at': firestore.SERVER_TIMESTAMP
        })
        logger.info(f"✅ Referral added: {referrer_id} -> {referred_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Error adding referral: {e}")
        return False

def get_referrals(referrer_id: str):
    if not db: 
        return []
    try:
        referrals = db.collection('referrals').where('referrer_id', '==', referrer_id).stream()
        return [ref.to_dict() for ref in referrals]
    except Exception as e:
        logger.error(f"❌ Error getting referrals: {e}")
        return []

# Извлечение referrer_id из start_param
def extract_referrer_id(start_param: str) -> str:
    if not start_param:
        return None
    
    logger.info(f"🔍 Extracting referrer_id from: '{start_param}'")
    
    if start_param.startswith('ref_'):
        referrer_id = start_param.replace('ref_', '')
        logger.info(f"✅ Found ref_ format: {referrer_id}")
        return referrer_id
    
    if start_param.isdigit():
        logger.info(f"✅ Found digit format: {start_param}")
        return start_param
    
    patterns = [
        r'ref_(\d+)',
        r'ref(\d+)',  
        r'referral_(\d+)',
        r'referral(\d+)',
        r'startapp_(\d+)',
        r'startapp(\d+)',
        r'(\d{8,})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, start_param)
        if match:
            referrer_id = match.group(1)
            logger.info(f"✅ Found with pattern '{pattern}': {referrer_id}")
            return referrer_id
    
    logger.info(f"⚠️ Using raw start_param as referrer_id: {start_param}")
    return start_param

# Эндпоинты API
@app.get("/")
async def root():
    return {
        "message": "VAC VPN API is running", 
        "status": "ok", 
        "firebase": "connected" if db else "disconnected"
    }

@app.post("/init-user")
async def init_user(request: InitUserRequest):
    """Автоматическое создание пользователя при заходе на сайт"""
    try:
        logger.info(f"🔍 INIT-USER START: user_id={request.user_id}, start_param='{request.start_param}'")
        
        if not db:
            return {"error": "Database not connected"}
        
        if not request.user_id or request.user_id == 'unknown':
            return {"error": "Invalid user ID"}
        
        # Извлекаем referrer_id из start_param
        referrer_id = None
        is_referral = False
        bonus_applied = False
        
        if request.start_param:
            referrer_id = extract_referrer_id(request.start_param)
            logger.info(f"🎯 Extracted referrer_id: {referrer_id}")
            
            if referrer_id:
                referrer = get_user(referrer_id)
                
                if referrer and referrer_id != request.user_id:
                    referral_id = f"{referrer_id}_{request.user_id}"
                    referral_exists = db.collection('referrals').document(referral_id).get().exists
                    
                    if not referral_exists:
                        is_referral = True
        
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
                'subscription_days': 0,
                'subscription_start': None,
                'vless_uuid': None,
                'created_at': firestore.SERVER_TIMESTAMP
            }
            
            # Если это реферал, начисляем бонусы
            if is_referral and referrer_id:
                logger.info(f"💰 APPLYING REFERRAL BONUS: New user {request.user_id} gets {REFERRAL_BONUS_DAYS} days, referrer {referrer_id} gets +{REFERRAL_BONUS_DAYS} days")
                
                # Новый пользователь получает 7 дней подписки
                user_data['subscription_days'] = REFERRAL_BONUS_DAYS
                user_data['has_subscription'] = True
                user_data['vless_uuid'] = VLESS_SERVERS[0]["uuid"]
                user_data['subscription_start'] = datetime.now().isoformat()
                user_data['referred_by'] = referrer_id
                bonus_applied = True
                
                # Пригласивший получает +7 дней к своей подписке
                update_subscription_days(referrer_id, REFERRAL_BONUS_DAYS)
                
                # Сохраняем запись о реферале
                referral_id = f"{referrer_id}_{request.user_id}"
                db.collection('referrals').document(referral_id).set({
                    'referrer_id': referrer_id,
                    'referred_id': request.user_id,
                    'new_user_bonus_days': REFERRAL_BONUS_DAYS,
                    'referrer_bonus_days': REFERRAL_BONUS_DAYS,
                    'bonus_paid': True,
                    'created_at': firestore.SERVER_TIMESTAMP
                })
            
            user_ref.set(user_data)
            logger.info(f"✅ User created: {request.user_id}, referral: {is_referral}, bonus_applied: {bonus_applied}")
            
            return {
                "success": True, 
                "message": "User created with referral bonus" if bonus_applied else "User created",
                "user_id": request.user_id,
                "is_referral": is_referral,
                "bonus_applied": bonus_applied
            }
        else:
            user_data = user_doc.to_dict()
            has_bonus = user_data.get('referred_by') is not None
            
            return {
                "success": True, 
                "message": "User already exists", 
                "user_id": request.user_id,
                "is_referral": has_bonus,
                "bonus_applied": has_bonus
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
            
        # Обрабатываем списание дней подписки
        process_subscription_days(user_id)
            
        user = get_user(user_id)
        if not user:
            return {
                "user_id": user_id,
                "balance": 0,
                "has_subscription": False,
                "subscription_days": 0,
                "vless_uuid": None
            }
        
        has_subscription = user.get('has_subscription', False)
        subscription_days = user.get('subscription_days', 0)
        vless_uuid = user.get('vless_uuid')
        
        return {
            "user_id": user_id,
            "balance": user.get('balance', 0),
            "has_subscription": has_subscription,
            "subscription_days": subscription_days,
            "vless_uuid": vless_uuid
        }
        
    except Exception as e:
        return {"error": f"Error getting user info: {str(e)}"}

@app.post("/activate-tariff")
async def activate_tariff(request: ActivateTariffRequest):
    try:
        SHOP_ID = os.getenv("SHOP_ID")
        API_KEY = os.getenv("API_KEY")
        
        if not SHOP_ID or not API_KEY:
            return {"error": "Payment gateway not configured"}
        
        if not db:
            return {"error": "Database not connected"}
            
        user = get_user(request.user_id)
        if not user:
            return {"error": "User not found"}
        
        if request.tariff not in TARIFFS:
            return {"error": "Invalid tariff"}
            
        tariff_data = TARIFFS[request.tariff]
        tariff_price = tariff_data["price"]
        tariff_days = tariff_data["days"]
        
        # Создаем платеж через ЮKassa
        payment_id = str(uuid.uuid4())
        save_payment(payment_id, request.user_id, tariff_price, request.tariff, "tariff")
        
        yookassa_data = {
            "amount": {"value": f"{tariff_price:.2f}", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": "https://t.me/vaaaac_bot"},
            "capture": True,
            "description": f"Покупка подписки {tariff_data['name']} - VAC VPN",
            "metadata": {
                "payment_id": payment_id,
                "user_id": request.user_id,
                "tariff": request.tariff,
                "payment_type": "tariff",
                "tariff_days": tariff_days
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
            
            logger.info(f"💳 Tariff payment created: {payment_id} for user {request.user_id}")
            
            return {
                "success": True,
                "payment_id": payment_id,
                "payment_url": payment_data["confirmation"]["confirmation_url"],
                "amount": tariff_price,
                "days": tariff_days,
                "status": "pending",
                "message": "Перейдите по ссылке для оплаты подписки"
            }
        else:
            return {"error": f"Payment gateway error: {response.status_code}"}
        
    except Exception as e:
        logger.error(f"❌ Error activating tariff: {e}")
        return {"error": str(e)}

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
                        tariff = payment['tariff']
                        tariff_days = TARIFFS[tariff]["days"]
                        
                        # Активируем подписку - добавляем дни
                        success = update_subscription_days(user_id, tariff_days)
                        
                        if not success:
                            logger.error(f"❌ Failed to activate subscription for user {user_id}")
                            return {"error": "Failed to activate subscription"}
                        
                        logger.info(f"✅ Subscription activated for user {user_id}: +{tariff_days} days")
                        
                        return {
                            "success": True,
                            "status": status,
                            "payment_id": payment_id,
                            "amount": payment['amount'],
                            "days_added": tariff_days
                        }
        
        return {
            "success": True,
            "status": payment['status'],
            "payment_id": payment_id
        }
        
    except Exception as e:
        logger.error(f"❌ Error checking payment: {e}")
        return {"error": f"Error checking payment: {str(e)}"}

@app.post("/vless-config")
async def get_vless_config(request: VlessConfigRequest):
    """Получить VLESS конфигурацию для пользователя"""
    try:
        if not db:
            return {"error": "Database not connected"}
            
        # Обрабатываем списание дней перед выдачей конфигурации
        process_subscription_days(request.user_id)
            
        user = get_user(request.user_id)
        if not user:
            return {"error": "User not found"}
        
        vless_uuid = user.get('vless_uuid')
        if not vless_uuid:
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
            "configs": configs
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting VLESS config: {e}")
        return {"error": f"Error getting VLESS config: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
