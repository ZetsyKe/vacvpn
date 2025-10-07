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
        "price": 150.0,
        "daily_cost": 5.0
    },
    "year": {
        "name": "Годовой", 
        "price": 1300.0,
        "daily_cost": 3.56
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
    start_param: str = None

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
    start_param: str = None

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

def create_user(user_data: dict):
    if not db: 
        logger.error("❌ Database not connected")
        return
    try:
        user_ref = db.collection('users').document(user_data['user_id'])
        if not user_ref.get().exists:
            user_ref.set(user_data)
            logger.info(f"✅ User created: {user_data['user_id']}")
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

def activate_subscription(user_id: str, tariff: str):
    if not db: 
        logger.error("❌ Database not connected")
        return None
    try:
        server_uuid = VLESS_SERVERS[0]["uuid"]
        logger.info(f"🆔 Using static server UUID for user {user_id}: {server_uuid}")
        
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
        logger.info(f"✅ Subscription activated for user {user_id}: tariff {tariff}")
        
        return server_uuid
    except Exception as e:
        logger.error(f"❌ Error activating subscription: {e}")
        return None

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
            return False
            
        last_deduction = user.get('last_deduction_date')
        today = datetime.now().date()
        
        if not last_deduction:
            deduction_date = today
        else:
            try:
                last_date = datetime.fromisoformat(last_deduction.replace('Z', '+00:00')).date()
                deduction_date = last_date
            except:
                deduction_date = today
        
        if deduction_date < today:
            daily_cost = TARIFFS[current_tariff]["daily_cost"]
            current_balance = user.get('balance', 0)
            
            if current_balance >= daily_cost:
                new_balance = current_balance - daily_cost
                db.collection('users').document(user_id).update({
                    'balance': new_balance,
                    'last_deduction_date': today.isoformat()
                })
                logger.info(f"✅ Daily deduction for user {user_id}: -{daily_cost}₽")
                return True
            else:
                db.collection('users').document(user_id).update({
                    'has_subscription': False,
                    'current_tariff': None,
                    'vless_uuid': None
                })
                logger.info(f"❌ Insufficient funds for user {user_id}, subscription deactivated")
                return False
        else:
            return True
            
    except Exception as e:
        logger.error(f"❌ Error processing daily deductions: {e}")
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

# Эндпоинты API
@app.get("/")
async def root():
    return {"message": "VAC VPN API is running", "status": "ok"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.post("/init-user")
async def init_user(request: InitUserRequest):
    try:
        if not db:
            return {"error": "Database not connected"}
        
        if not request.user_id or request.user_id == 'unknown':
            return {"error": "Invalid user ID"}
        
        # Обрабатываем реферальную ссылку
        is_referral = False
        referrer_id = None
        
        if request.start_param:
            if request.start_param.startswith('ref_'):
                referrer_id = request.start_param.replace('ref_', '')
                is_referral = True
            elif request.start_param.isdigit():
                referrer_id = request.start_param
                is_referral = True
            
            if is_referral:
                logger.info(f"🎯 Referral detected: {referrer_id} -> {request.user_id}")
        
        # Создаем пользователя если не существует
        user_ref = db.collection('users').document(request.user_id)
        if not user_ref.get().exists:
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
            
            # Начисляем бонусы за реферала
            bonus_applied = False
            if is_referral and referrer_id and referrer_id != request.user_id:
                referrer = get_user(referrer_id)
                if referrer:
                    referral_exists = db.collection('referrals').document(f"{referrer_id}_{request.user_id}").get().exists
                    if not referral_exists:
                        user_data['balance'] = 100.0
                        user_data['referred_by'] = referrer_id
                        apply_referral_bonus(request.user_id, referrer_id)
                        bonus_applied = True
                        logger.info(f"🎁 Referral bonus applied for new user: {request.user_id}")
            
            user_ref.set(user_data)
            
            return {
                "success": True, 
                "message": "User created", 
                "user_id": request.user_id,
                "is_referral": is_referral,
                "bonus_applied": bonus_applied
            }
        else:
            return {
                "success": True, 
                "message": "User already exists", 
                "user_id": request.user_id
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
        
        if not request.user_id or request.user_id == 'unknown':
            return {"error": "Invalid user ID"}
        
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
                        
                        update_user_balance(user_id, amount)
                        
                        if payment_type == 'tariff':
                            vless_uuid = activate_subscription(user_id, tariff)
                            if not vless_uuid:
                                return {"error": "Failed to activate subscription"}
                    
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
        
        new_balance = user.get('balance', 0) + tariff_price
        update_user_balance(request.user_id, tariff_price)
        
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
            "message": f"✅ Тариф активирован! На баланс добавлено {tariff_price}₽"
        }
        
    except Exception as e:
        logger.error(f"❌ Error activating tariff: {e}")
        return {"error": str(e)}

@app.post("/vless-config")
async def get_vless_config(request: VlessConfigRequest):
    try:
        if not db:
            return {"error": "Database not connected"}
            
        process_daily_deductions(request.user_id)
            
        user = get_user(request.user_id)
        if not user:
            return {"error": "User not found"}
        
        vless_uuid = user.get('vless_uuid')
        if not vless_uuid:
            return {"error": "VLESS UUID not found. Activate subscription first."}
        
        if not user.get('has_subscription', False):
            return {"error": "No active subscription"}
        
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
