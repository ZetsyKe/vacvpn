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

# Конфигурация VLESS серверов
VLESS_SERVERS = [
    {
        "address": "vpn1.vacvpn.com",
        "port": 443,
        "sni": "vpn1.vacvpn.com"
    },
    {
        "address": "vpn2.vacvpn.com", 
        "port": 443,
        "sni": "vpn2.vacvpn.com"
    },
    {
        "address": "vpn3.vacvpn.com",
        "port": 443,
        "sni": "vpn3.vacvpn.com"
    }
]

# Тарифы (ежедневное списание)
TARIFFS = {
    "month": {
        "name": "Месячный",
        "daily_cost": 5.0,  # 150₽ / 30 дней = 5₽ в день
        "total_cost": 150.0
    },
    "year": {
        "name": "Годовой", 
        "daily_cost": 0.41,  # 150₽ / 365 дней ≈ 0.41₽ в день
        "total_cost": 150.0
    }
}

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
    
    # Создаем VLESS ссылку
    vless_link = f"vless://{vless_uuid}@{address}:{port}?encryption=none&security=tls&sni={sni}&fp=randomized&type=ws&path=%2F&host={address}#VAC_VPN_{user_id}"
    
    # Создаем конфиг для приложений
    config = {
        "protocol": "vless",
        "uuid": vless_uuid,
        "server": address,
        "port": port,
        "encryption": "none",
        "security": "tls",
        "sni": sni,
        "fingerprint": "randomized",
        "type": "ws",
        "path": "/",
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
        # Генерируем UUID для VLESS
        vless_uuid = generate_vless_uuid()
        logger.info(f"🆔 Generated VLESS UUID for user {user_id}: {vless_uuid}")
        
        # Обновляем данные пользователя
        user_ref = db.collection('users').document(user_id)
        
        # Получаем текущие данные пользователя
        user_doc = user_ref.get()
        if not user_doc.exists:
            logger.error(f"❌ User {user_id} not found in database")
            return None
            
        update_data = {
            'has_subscription': True,
            'current_tariff': tariff,
            'vless_uuid': vless_uuid,
            'last_deduction_date': datetime.now().isoformat(),
            'updated_at': firestore.SERVER_TIMESTAMP
        }
        
        user_ref.update(update_data)
        logger.info(f"✅ Subscription activated for user {user_id}: tariff {tariff}, UUID: {vless_uuid}")
        
        # Проверяем что данные сохранились
        updated_user = user_ref.get()
        if updated_user.exists:
            saved_uuid = updated_user.to_dict().get('vless_uuid')
            logger.info(f"✅ UUID saved in database: {saved_uuid}")
        else:
            logger.error("❌ Failed to verify UUID save")
            
        return vless_uuid
    except Exception as e:
        logger.error(f"❌ Error activating subscription: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None

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
                    'current_tariff': None
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
                'current_tariff': None,
                'last_deduction_date': None,
                'vless_uuid': None,
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
        
        # Тарифы
        tariff_config = {
            "month": {"amount": 150, "description": "Пополнение баланса VAC VPN"},
            "year": {"amount": 150, "description": "Пополнение баланса VAC VPN"}
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
            # Получаем обновленные данные пользователя
            user = get_user(user_id)
            return {
                "success": True,
                "status": "succeeded",
                "payment_id": payment_id,
                "amount": payment['amount'],
                "vless_uuid": user.get('vless_uuid') if user else None
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
                            # Активируем подписку и генерируем VLESS UUID
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
                        
                        user = get_user(user_id)
                        vless_uuid = user.get('vless_uuid') if user else None
                    
                        return {
                            "success": True,
                            "status": status,
                            "payment_id": payment_id,
                            "amount": amount,
                            "vless_uuid": vless_uuid
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
        
        # Проверяем достаточно ли средств для активации (минимум 1 день)
        if request.tariff not in TARIFFS:
            return {"error": "Invalid tariff"}
            
        daily_cost = TARIFFS[request.tariff]["daily_cost"]
        user_balance = user.get('balance', 0)
        
        if user_balance < daily_cost:
            return {"error": f"Insufficient balance. Need at least {daily_cost}₽ for one day"}
        
        # Активируем подписку и генерируем VLESS UUID
        vless_uuid = activate_subscription(request.user_id, request.tariff)
        
        if not vless_uuid:
            return {"error": "Failed to generate VLESS configuration"}
        
        return {
            "success": True, 
            "tariff": request.tariff,
            "daily_cost": daily_cost,
            "vless_uuid": vless_uuid
        }
        
    except Exception as e:
        logger.error(f"❌ Error activating tariff: {e}")
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
            # Проверяем есть ли подписка
            if user.get('has_subscription'):
                logger.error(f"❌ User {request.user_id} has subscription but no UUID")
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

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
