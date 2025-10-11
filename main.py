from fastapi import FastAPI
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
import json
import urllib.parse

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

# Конфигурация сервера
VLESS_SERVERS = [
    {
        "name": "🇷🇺 Ваш сервер #1",
        "address": "45.134.13.189",
        "port": 8443,
        "sni": "www.ign.com",
        "reality_pbk": "BoTEvceuDTYQ38S-Nd5KgUJ2VDew4Q7-J3eFeVg8ckY",
        "short_id": "2bd6a8283e",
        "flow": "",
        "security": "reality"
    }
]

# Тарифы
TARIFFS = {
    "1month": {
        "name": "1 Месяц",
        "price": 150.0,
        "days": 30
    },
    "1year": {
        "name": "1 Год", 
        "price": 1300.0,
        "days": 365
    }
}

# Реферальная система
REFERRAL_BONUS_REFERRER = 50.0
REFERRAL_BONUS_REFERRED = 100.0

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
    db = None

# Модели данных
class InitUserRequest(BaseModel):
    user_id: str
    username: str = ""
    first_name: str = ""
    last_name: str = ""
    start_param: str = None

class ActivateTariffRequest(BaseModel):
    user_id: str
    tariff: str
    payment_method: str = "yookassa"

class BuyWithBalanceRequest(BaseModel):
    user_id: str
    tariff_id: str
    tariff_price: float
    tariff_days: int

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

def update_user_balance(user_id: str, amount: float):
    if not db: 
        return False
    try:
        user_ref = db.collection('users').document(user_id)
        user = user_ref.get()
        
        if user.exists:
            user_data = user.to_dict()
            current_balance = user_data.get('balance', 0.0)
            new_balance = current_balance + amount
            
            user_ref.update({
                'balance': new_balance,
                'updated_at': firestore.SERVER_TIMESTAMP
            })
            
            logger.info(f"💰 Balance updated for user {user_id}: {current_balance} -> {new_balance}")
            return True
        else:
            logger.error(f"❌ User {user_id} not found")
            return False
    except Exception as e:
        logger.error(f"❌ Error updating balance: {e}")
        return False

def generate_user_uuid():
    return str(uuid.uuid4())

# Функция активации подписки
async def update_subscription_days(user_id: str, additional_days: int):
    if not db: 
        return False
    try:
        user_ref = db.collection('users').document(user_id)
        user = user_ref.get()
        
        if user.exists:
            user_data = user.to_dict()
            current_days = user_data.get('subscription_days', 0)
            new_days = current_days + additional_days
            
            has_subscription = user_data.get('has_subscription', False)
            if not has_subscription and additional_days > 0:
                has_subscription = True
            
            update_data = {
                'subscription_days': new_days,
                'has_subscription': has_subscription,
                'updated_at': firestore.SERVER_TIMESTAMP
            }
            
            # Генерируем уникальный UUID для пользователя
            if has_subscription and not user_data.get('vless_uuid'):
                user_uuid = generate_user_uuid()
                update_data['vless_uuid'] = user_uuid
                update_data['subscription_start'] = datetime.now().isoformat()
                logger.info(f"🔑 Generated new UUID for user {user_id}: {user_uuid}")
            
            user_ref.update(update_data)
            logger.info(f"✅ Subscription days updated for user {user_id}: {current_days} -> {new_days}")
            return True
        else:
            logger.error(f"❌ User {user_id} not found")
            return False
    except Exception as e:
        logger.error(f"❌ Error updating subscription days: {e}")
        return False

def add_referral_bonus_immediately(referrer_id: str, referred_id: str):
    if not db: 
        return False
    
    try:
        update_user_balance(referrer_id, 50.0)
        update_user_balance(referred_id, 100.0)
        
        referral_id = f"{referrer_id}_{referred_id}"
        db.collection('referrals').document(referral_id).set({
            'referrer_id': referrer_id,
            'referred_id': referred_id,
            'referrer_bonus': 50.0,
            'referred_bonus': 100.0,
            'bonus_paid': True,
            'created_at': firestore.SERVER_TIMESTAMP
        })
        
        logger.info(f"✅ Referral bonuses applied: {referrer_id} +50₽, {referred_id} +100₽")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error adding referral bonus: {e}")
        return False

def create_vless_config(user_id: str, vless_uuid: str, server_config: dict):
    address = server_config["address"]
    port = server_config["port"]
    reality_pbk = server_config["reality_pbk"]
    sni = server_config["sni"]
    short_id = server_config["short_id"]
    flow = server_config["flow"]
    
    vless_link = (
        f"vless://{vless_uuid}@{address}:{port}?"
        f"type=tcp&"
        f"security=reality&"
        f"flow={flow}&"
        f"pbk={reality_pbk}&"
        f"fp=chrome&"
        f"sni={sni}&"
        f"sid={short_id}#"
        f"VAC-VPN-{user_id}"
    )
    
    config = {
        "name": server_config["name"],
        "protocol": "vless",
        "uuid": vless_uuid,
        "server": address,
        "port": port,
        "security": "reality",
        "reality_pbk": reality_pbk,
        "sni": sni,
        "short_id": short_id,
        "flow": flow,
        "type": "tcp",
        "fingerprint": "chrome",
        "remark": f"VAC VPN Reality - {user_id}"
    }
    
    encoded_vless_link = urllib.parse.quote(vless_link)
    
    return {
        "vless_link": vless_link,
        "config": config,
        "qr_code": f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={encoded_vless_link}"
    }

def process_subscription_days(user_id: str):
    if not db:
        return False
    
    try:
        user = get_user(user_id)
        if not user or not user.get('has_subscription', False):
            return True
            
        subscription_days = user.get('subscription_days', 0)
        last_check = user.get('last_subscription_check')
        today = datetime.now().date()
        
        if not last_check:
            db.collection('users').document(user_id).update({
                'last_subscription_check': today.isoformat()
            })
            return True
        else:
            try:
                last_date = datetime.fromisoformat(last_check.replace('Z', '+00:00')).date()
                days_passed = (today - last_date).days
                
                if days_passed > 0:
                    new_days = max(0, subscription_days - days_passed)
                    
                    update_data = {
                        'subscription_days': new_days,
                        'last_subscription_check': today.isoformat()
                    }
                    
                    if new_days == 0:
                        update_data['has_subscription'] = False
                    
                    db.collection('users').document(user_id).update(update_data)
                    logger.info(f"✅ Subscription days processed for user {user_id}: {subscription_days} -> {new_days}")
                    
            except Exception as e:
                logger.error(f"❌ Error processing subscription days: {e}")
        
        return True
            
    except Exception as e:
        logger.error(f"❌ Error processing subscription: {e}")
        return False

def save_payment(payment_id: str, user_id: str, amount: float, tariff: str, payment_method: str = "yookassa"):
    if not db: 
        return
    try:
        db.collection('payments').document(payment_id).set({
            'payment_id': payment_id,
            'user_id': user_id,
            'amount': amount,
            'tariff': tariff,
            'status': 'pending',
            'payment_method': payment_method,
            'created_at': firestore.SERVER_TIMESTAMP,
        })
        logger.info(f"✅ Payment saved: {payment_id} for user {user_id}")
    except Exception as e:
        logger.error(f"❌ Error saving payment: {e}")

def update_payment_status(payment_id: str, status: str):
    if not db: 
        return
    try:
        update_data = {'status': status}
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

def get_referrals(referrer_id: str):
    if not db: 
        return []
    try:
        referrals = db.collection('referrals').where('referrer_id', '==', referrer_id).stream()
        return [ref.to_dict() for ref in referrals]
    except Exception as e:
        logger.error(f"❌ Error getting referrals: {e}")
        return []

def extract_referrer_id(start_param: str) -> str:
    if not start_param:
        return None
    
    if start_param.startswith('ref_'):
        return start_param.replace('ref_', '')
    
    if start_param.isdigit():
        return start_param
    
    patterns = [
        r'ref_(\d+)',
        r'ref(\d+)',  
        r'referral_(\d+)',
        r'(\d{8,})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, start_param)
        if match:
            return match.group(1)
    
    return start_param

# Эндпоинты API
@app.get("/")
async def root():
    return {
        "message": "VAC VPN API is running", 
        "status": "ok", 
        "firebase": "connected" if db else "disconnected",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy", 
        "timestamp": datetime.now().isoformat(), 
        "firebase": "connected" if db else "disconnected",
    }

@app.post("/init-user")
async def init_user(request: InitUserRequest):
    try:
        if not db:
            return {"error": "Database not connected"}
        
        if not request.user_id or request.user_id == 'unknown':
            return {"error": "Invalid user ID"}
        
        referrer_id = None
        is_referral = False
        bonus_applied = False
        
        if request.start_param:
            referrer_id = extract_referrer_id(request.start_param)
            
            if referrer_id:
                referrer = get_user(referrer_id)
                
                if referrer and referrer_id != request.user_id:
                    referral_id = f"{referrer_id}_{request.user_id}"
                    referral_exists = db.collection('referrals').document(referral_id).get().exists
                    
                    if not referral_exists:
                        is_referral = True
                        bonus_result = add_referral_bonus_immediately(referrer_id, request.user_id)
                        if bonus_result:
                            bonus_applied = True
        
        user_ref = db.collection('users').document(request.user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            user_data = {
                'user_id': request.user_id,
                'username': request.username,
                'first_name': request.first_name,
                'last_name': request.last_name,
                'balance': 100.0 if bonus_applied else 0.0,
                'has_subscription': False,
                'subscription_days': 0,
                'vless_uuid': None,
                'created_at': firestore.SERVER_TIMESTAMP
            }
            
            if is_referral and referrer_id:
                user_data['referred_by'] = referrer_id
            
            user_ref.set(user_data)
            
            return {
                "success": True, 
                "message": "User created",
                "user_id": request.user_id,
                "is_referral": is_referral,
                "bonus_applied": bonus_applied
            }
        else:
            user_data = user_doc.to_dict()
            has_referrer = user_data.get('referred_by') is not None
            
            return {
                "success": True, 
                "message": "User already exists", 
                "user_id": request.user_id,
                "is_referral": has_referrer,
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
        balance = user.get('balance', 0.0)
        
        referrals = get_referrals(user_id)
        referral_count = len(referrals)
        total_bonus_money = sum([ref.get('referrer_bonus', 0) for ref in referrals])
        
        return {
            "user_id": user_id,
            "balance": balance,
            "has_subscription": has_subscription,
            "subscription_days": subscription_days,
            "vless_uuid": vless_uuid,
            "referral_stats": {
                "total_referrals": referral_count,
                "total_bonus_money": total_bonus_money,
            }
        }
        
    except Exception as e:
        return {"error": f"Error getting user info: {str(e)}"}

@app.post("/buy-with-balance")
async def buy_with_balance(request: BuyWithBalanceRequest):
    try:
        if not db:
            return {"error": "Database not connected"}
        
        user = get_user(request.user_id)
        if not user:
            return {"error": "User not found"}
        
        user_balance = user.get('balance', 0.0)
        
        if user_balance < request.tariff_price:
            return {
                "success": False,
                "error": f"Недостаточно средств на балансе. На вашем балансе {user_balance}₽, а требуется {request.tariff_price}₽"
            }
        
        payment_id = str(uuid.uuid4())
        save_payment(payment_id, request.user_id, request.tariff_price, request.tariff_id, "balance")
        
        update_user_balance(request.user_id, -request.tariff_price)
        
        success = await update_subscription_days(request.user_id, request.tariff_days)
        
        if not success:
            return {"error": "Ошибка активации подписки"}
        
        if user.get('referred_by'):
            referrer_id = user['referred_by']
            referral_id = f"{referrer_id}_{request.user_id}"
            
            referral_exists = db.collection('referrals').document(referral_id).get().exists
            
            if not referral_exists:
                add_referral_bonus_immediately(referrer_id, request.user_id)
        
        update_payment_status(payment_id, "succeeded")
        
        return {
            "success": True,
            "payment_id": payment_id,
            "amount": request.tariff_price,
            "days": request.tariff_days,
            "message": "Подписка успешно активирована с баланса!"
        }
        
    except Exception as e:
        logger.error(f"❌ Error in buy-with-balance: {e}")
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
        tariff_days = tariff_data["days"]
        
        if request.payment_method == "balance":
            user_balance = user.get('balance', 0.0)
            
            if user_balance < tariff_price:
                return {"error": f"Недостаточно средств на балансе. Необходимо: {tariff_price}₽, доступно: {user_balance}₽"}
            
            payment_id = str(uuid.uuid4())
            save_payment(payment_id, request.user_id, tariff_price, request.tariff, "balance")
            
            update_user_balance(request.user_id, -tariff_price)
            
            success = await update_subscription_days(request.user_id, tariff_days)
            
            if not success:
                return {"error": "Ошибка активации подписки"}
            
            if user.get('referred_by'):
                referrer_id = user['referred_by']
                referral_id = f"{referrer_id}_{request.user_id}"
                
                referral_exists = db.collection('referrals').document(referral_id).get().exists
                
                if not referral_exists:
                    add_referral_bonus_immediately(referrer_id, request.user_id)
            
            update_payment_status(payment_id, "succeeded")
            
            return {
                "success": True,
                "payment_id": payment_id,
                "amount": tariff_price,
                "days": tariff_days,
                "message": "Подписка успешно активирована с баланса!"
            }
        
        elif request.payment_method == "yookassa":
            SHOP_ID = os.getenv("SHOP_ID")
            API_KEY = os.getenv("API_KEY")
            
            if not SHOP_ID or not API_KEY:
                return {"error": "Payment gateway not configured"}
            
            payment_id = str(uuid.uuid4())
            save_payment(payment_id, request.user_id, tariff_price, request.tariff, "yookassa")
            
            yookassa_data = {
                "amount": {"value": f"{tariff_price:.2f}", "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": "https://t.me/vaaaac_bot"},
                "capture": True,
                "description": f"Покупка подписки {tariff_data['name']} - VAC VPN",
                "metadata": {
                    "payment_id": payment_id,
                    "user_id": request.user_id,
                    "tariff": request.tariff,
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
                
                return {
                    "success": True,
                    "payment_id": payment_id,
                    "payment_url": payment_data["confirmation"]["confirmation_url"],
                    "amount": tariff_price,
                    "days": tariff_days,
                    "message": "Перейдите по ссылке для оплаты подписки"
                }
            else:
                return {"error": f"Payment gateway error: {response.status_code}"}
        
        else:
            return {"error": "Invalid payment method"}
        
    except Exception as e:
        logger.error(f"❌ Error activating tariff: {e}")
        return {"error": str(e)}

@app.get("/get-vless-config")
async def get_vless_config(user_id: str):
    try:
        if not db:
            return {"error": "Database not connected"}
            
        process_subscription_days(user_id)
            
        user = get_user(user_id)
        if not user:
            return {"error": "User not found"}
        
        vless_uuid = user.get('vless_uuid')
        if not vless_uuid:
            return {"error": "VLESS UUID not found. Activate subscription first."}
        
        if not user.get('has_subscription', False):
            return {"error": "No active subscription"}
        
        configs = []
        for server in VLESS_SERVERS:
            config = create_vless_config(user_id, vless_uuid, server)
            configs.append(config)
        
        return {
            "success": True,
            "user_id": user_id,
            "vless_uuid": vless_uuid,
            "configs": configs
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting VLESS config: {e}")
        return {"error": f"Error getting VLESS config: {str(e)}"}
