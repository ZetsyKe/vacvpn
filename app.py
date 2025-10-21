from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import os
import logging
import asyncio
from datetime import datetime, timedelta
import threading
import subprocess
import sys
import uuid
import httpx
import firebase_admin
from firebase_admin import credentials, firestore
from pydantic import BaseModel
import re
import json
import urllib.parse
from typing import List, Optional
from PIL import Image, ImageDraw, ImageFont
import io

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="VAC VPN API",
    description="Complete VAC VPN Service with API and Web Interface",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Монтируем статические файлы
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Конфигурация
# Конфигурация
XRAY_SERVERS = {
    "moscow": {
        "url": "http://45.134.13.189:8001",
        "api_key": "vac-vpn-secret-key-2024"
    },
    "finland": {
        "url": "http://91.103.140.230:8001",
        "api_key": "finland-secret-key-2024"
    }
}
XRAY_MANAGER_URL = "http://45.134.13.189:8001"
XRAY_API_KEY = "vac-vpn-secret-key-2024"
VLESS_SERVERS = [
    {
        "name": "🇷🇺 Москва #1",
        "address": "45.134.13.189",
        "port": 2053,
        "sni": "www.google.com",
        "reality_pbk": "AZTvYvIEtJv5aAS-F-6gMg3a6KXuMgRJIHBIdp-7bAQ",
        "short_id": "abcd1234",  
        "flow": "",
        "security": "reality"
    },
    {
    "name": "🇫🇮 Финляндия #1",
    "address": "91.103.140.230",  # Правильный IP
    "port": 2053,
    "sni": "www.google.com", 
    "reality_pbk": "GFjSOSi6S6Mynt8BkyUK2cfuFzrLZ2A4BsOmx99b8U0",  # Публичный ключ
    "short_id": "ef123456",  # Short ID
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
        logger.info("🚀 Initializing Firebase for Railway")
        
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
            "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_X509_CERT_URL"),
            "universe_domain": "googleapis.com"
        }
        
        required_fields = ["project_id", "private_key", "client_email"]
        for field in required_fields:
            if not firebase_config.get(field):
                raise ValueError(f"Missing required Firebase config field: {field}")
        
        cred = credentials.Certificate(firebase_config)
        firebase_admin.initialize_app(cred)
    
    db = firestore.client()
    logger.info("✅ Firebase initialized successfully")
    
except Exception as e:
    logger.error(f"❌ Firebase initialization failed: {str(e)}")
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
    payment_method: str = "yookassa"

class AddBalanceRequest(BaseModel):
    user_id: str
    amount: float
    payment_method: str = "yookassa"

class InitUserRequest(BaseModel):
    user_id: str
    username: str = ""
    first_name: str = ""
    last_name: str = ""
    start_param: str = None

class VlessConfigRequest(BaseModel):
    user_id: str

class BuyWithBalanceRequest(BaseModel):
    user_id: str
    tariff_id: str
    tariff_price: float
    tariff_days: int

def ensure_logo_exists():
    """Обеспечивает что логотип доступен в статической директории"""
    try:
        original_logo = "Airbrush-Image-Enhancer-1753455007914.png"
        static_logo = "static/Airbrush-Image-Enhancer-1753455007914.png"
        
        # Создаем static директорию если ее нет
        os.makedirs("static", exist_ok=True)
        
        # Если оригинальный логотип существует, копируем его в static
        if os.path.exists(original_logo) and not os.path.exists(static_logo):
            import shutil
            shutil.copy2(original_logo, static_logo)
            logger.info(f"✅ Logo copied to static directory: {static_logo}")
        elif os.path.exists(static_logo):
            logger.info(f"✅ Logo already exists in static directory: {static_logo}")
        else:
            logger.warning("⚠️ Original logo file not found, creating placeholder")
            create_placeholder_logo()
            
    except Exception as e:
        logger.error(f"❌ Error ensuring logo exists: {e}")
        create_placeholder_logo()

def create_placeholder_logo():
    """Создает placeholder логотип если основной не найден"""
    try:
        logo_path = "static/Airbrush-Image-Enhancer-1753455007914.png"
        
        # Создаем изображение 120x120
        img = Image.new('RGB', (120, 120), color='#121212')
        d = ImageDraw.Draw(img)
        
        # Рисуем зеленый круг
        d.ellipse([10, 10, 110, 110], fill='#B0CB1F')
        
        # Добавляем текст VAC VPN
        try:
            # Пробуем использовать системный шрифт
            font = ImageFont.truetype("arial.ttf", 16)
        except:
            try:
                font = ImageFont.truetype("arialbd.ttf", 16)
            except:
                # Fallback на стандартный шрифт
                font = ImageFont.load_default()
        
        # Текст белым цветом
        d.text((60, 40), "VAC", fill='#121212', font=font, anchor="mm")
        d.text((60, 70), "VPN", fill='#121212', font=font, anchor="mm")
        
        # Сохраняем изображение
        img.save(logo_path, "PNG")
        logger.info("✅ Placeholder logo created successfully")
        
    except Exception as e:
        logger.error(f"❌ Error creating placeholder logo: {e}")

# Функции работы с Xray через API
async def add_user_to_xray(user_uuid: str) -> bool:
    """Добавить пользователя во все Xray серверы"""
    try:
        logger.info(f"🔄 [XRAY ADD] Adding user to all Xray servers: {user_uuid}")
        
        results = []
        for server_name, server_config in XRAY_SERVERS.items():
            try:
                async with httpx.AsyncClient() as client:
                    endpoints = [
                        f"{server_config['url']}/users?uuid={user_uuid}",
                        f"{server_config['url']}/user?uuid={user_uuid}",
                        f"{server_config['url']}/add?uuid={user_uuid}",
                        f"{server_config['url']}/add-user?uuid={user_uuid}"
                    ]
                    
                    server_success = False
                    for endpoint in endpoints:
                        try:
                            logger.info(f"🔗 [XRAY ADD] Trying endpoint: {endpoint}")
                            response = await client.post(endpoint, timeout=30.0)
                            
                            if response.status_code == 200:
                                logger.info(f"✅ [XRAY ADD] User {user_uuid} added to {server_name} via {endpoint}")
                                server_success = True
                                break
                            else:
                                logger.warning(f"⚠️ [XRAY ADD] Endpoint {endpoint} failed: {response.status_code}")
                                
                        except Exception as e:
                            logger.warning(f"⚠️ [XRAY ADD] Endpoint {endpoint} error: {e}")
                    
                    results.append(server_success)
                    
            except Exception as e:
                logger.error(f"❌ [XRAY ADD] Error adding user to {server_name}: {e}")
                results.append(False)
        
        # Возвращаем True если пользователь добавлен хотя бы на один сервер
        success = any(results)
        logger.info(f"📊 [XRAY ADD] Overall result: {success} (moscow: {results[0]}, finland: {results[1]})")
        return success
                
    except Exception as e:
        logger.error(f"❌ [XRAY ADD] Critical error: {e}")
        return False

async def check_user_in_xray(user_uuid: str) -> bool:
    """Проверить есть ли пользователь хотя бы в одном Xray"""
    try:
        logger.info(f"🔍 [XRAY CHECK] Starting check for UUID: {user_uuid}")
        
        for server_name, server_config in XRAY_SERVERS.items():
            try:
                async with httpx.AsyncClient() as client:
                    endpoints = [
                        f"{server_config['url']}/users/{user_uuid}",
                        f"{server_config['url']}/user/{user_uuid}",
                        f"{server_config['url']}/check/{user_uuid}",
                        f"{server_config['url']}/users?uuid={user_uuid}"
                    ]
                    
                    for endpoint in endpoints:
                        try:
                            logger.info(f"🌐 [XRAY CHECK] Making request to: {endpoint}")
                            response = await client.get(endpoint, timeout=30.0)
                            
                            logger.info(f"📡 [XRAY CHECK] Response status: {response.status_code}")
                            
                            if response.status_code == 200:
                                data = response.json()
                                exists = data.get("exists", False)
                                if exists:
                                    logger.info(f"✅ [XRAY CHECK] User exists in {server_name} Xray: {exists}")
                                    return True
                        
                        except Exception as e:
                            logger.warning(f"⚠️ [XRAY CHECK] Endpoint {endpoint} error: {e}")
                            
            except Exception as e:
                logger.warning(f"⚠️ [XRAY CHECK] Server {server_name} error: {e}")
        
        logger.error(f"❌ [XRAY CHECK] User not found in any Xray server: {user_uuid}")
        return False
            
    except Exception as e:
        logger.error(f"❌ [XRAY CHECK] Exception: {str(e)}")
        return False

async def get_xray_users_count() -> int:
    """Получить количество пользователей в Xray"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{XRAY_MANAGER_URL}/users",
                headers={"Authorization": f"Bearer {XRAY_API_KEY}"},
                timeout=30.0
            )
            
            if response.status_code == 200:
                users = response.json()
                return len(users)
            return 0
            
    except Exception as e:
        logger.error(f"❌ Error getting Xray users: {e}")
        return 0

async def remove_user_from_xray(user_uuid: str) -> bool:
    """Удалить пользователя из Xray через API"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{XRAY_MANAGER_URL}/users/{user_uuid}",
                headers={"Authorization": f"Bearer {XRAY_API_KEY}"},
                timeout=30.0
            )
            
            if response.status_code == 200:
                logger.info(f"✅ User {user_uuid} removed from Xray via API")
                return True
            else:
                logger.error(f"❌ Failed to remove user from Xray: {response.status_code} - {response.text}")
                return False
                
    except Exception as e:
        logger.error(f"❌ Error removing user from Xray via API: {e}")
        return False

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

def update_user_balance(user_id: str, amount: float):
    if not db: 
        logger.error("❌ Database not connected")
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
            
            logger.info(f"💰 Balance updated for user {user_id}: {current_balance} -> {new_balance} ({'+' if amount > 0 else ''}{amount}₽)")
            return True
        else:
            logger.error(f"❌ User {user_id} not found")
            return False
    except Exception as e:
        logger.error(f"❌ Error updating balance: {e}")
        return False

def generate_user_uuid():
    """Генерация уникального UUID для пользователя"""
    return str(uuid.uuid4())

async def ensure_user_uuid(user_id: str) -> str:
    """Гарантирует что у пользователя есть UUID и он в Xray"""
    if not db:
        raise Exception("Database not connected")
    
    try:
        user_ref = db.collection('users').document(user_id)
        user = user_ref.get()
        
        if not user.exists:
            raise Exception("User not found")
        
        user_data = user.to_dict()
        vless_uuid = user_data.get('vless_uuid')
        
        # Если UUID уже есть, проверяем его в Xray
        if vless_uuid:
            logger.info(f"🔍 User {user_id} has existing UUID: {vless_uuid}")
            
            # Проверяем есть ли в Xray
            if not await check_user_in_xray(vless_uuid):
                logger.warning(f"⚠️ UUID exists but not in Xray, re-adding: {vless_uuid}")
                success = await add_user_to_xray(vless_uuid)
                if not success:
                    raise Exception("Failed to add existing UUID to Xray")
            
            return vless_uuid
        
        # Генерируем новый UUID
        new_uuid = generate_user_uuid()
        logger.info(f"🆕 Generating new UUID for user {user_id}: {new_uuid}")
        
        # Обновляем пользователя
        user_ref.update({
            'vless_uuid': new_uuid,
            'updated_at': firestore.SERVER_TIMESTAMP
        })
        
        # Добавляем в Xray
        success = await add_user_to_xray(new_uuid)
        if not success:
            raise Exception("Failed to add new UUID to Xray")
        
        logger.info(f"✅ New UUID created and added to Xray: {new_uuid}")
        return new_uuid
        
    except Exception as e:
        logger.error(f"❌ Error ensuring user UUID: {e}")
        raise

def add_referral_bonus_immediately(referrer_id: str, referred_id: str):
    if not db: 
        logger.error("❌ Database not connected")
        return False
    
    try:
        logger.info(f"💰 Immediate referral bonuses: referrer {referrer_id} gets 50₽, referred {referred_id} gets 100₽")
        
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
        
        logger.info(f"✅ Immediate referral bonuses applied: {referrer_id} +50₽, {referred_id} +100₽")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error adding immediate referral bonus: {e}")
        return False

def create_user_vless_configs(user_id: str, vless_uuid: str) -> List[dict]:
    """Создает уникальные VLESS Reality конфигурации для пользователя"""
    
    configs = []
    
    for server in VLESS_SERVERS:
        address = server["address"]
        port = server["port"]
        reality_pbk = server["reality_pbk"]
        sni = server["sni"]
        short_id = server["short_id"]
        flow = server["flow"]
        
        # Убираем порт из SNI если есть
        clean_sni = sni.replace(":443", "")
        
        # Создаем уникальный VLESS ссылку для этого пользователя
        vless_link = (
            f"vless://{vless_uuid}@{address}:{port}?"
            f"type=tcp&"
            f"security=reality&"
            f"flow={flow}&"
            f"pbk={reality_pbk}&"
            f"fp=chrome&"
            f"sni={clean_sni}&"
            f"sid={short_id}#"
            f"VAC-VPN-{user_id}"
        )
        
        # Конфиг для приложений
        config = {
            "name": f"{server['name']} - {user_id}",
            "protocol": "vless",
            "uuid": vless_uuid,  # Уникальный для каждого пользователя
            "server": address,
            "port": port,
            "security": "reality",
            "reality_pbk": reality_pbk,
            "sni": clean_sni,
            "short_id": short_id,
            "flow": flow,
            "type": "tcp",
            "fingerprint": "chrome",
            "remark": f"VAC VPN Reality - {user_id}",
            "user_id": user_id  # Добавляем ID пользователя
        }
        
        encoded_vless_link = urllib.parse.quote(vless_link)
        
        configs.append({
            "vless_link": vless_link,
            "config": config,
            "qr_code": f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={encoded_vless_link}",
            "server_name": server["name"]
        })
    
    return configs

def process_subscription_days(user_id: str):
    if not db:
        logger.error("❌ Database not connected")
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
                    logger.info(f"✅ Subscription days processed for user {user_id}: {subscription_days} -> {new_days} (-{days_passed} days)")
                    
            except Exception as e:
                logger.error(f"❌ Error processing subscription days: {e}")
        
        return True
            
    except Exception as e:
        logger.error(f"❌ Error processing subscription: {e}")
        return False

def save_payment(payment_id: str, user_id: str, amount: float, tariff: str, payment_type: str = "tariff", payment_method: str = "yookassa"):
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
            'payment_method': payment_method,
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

async def update_subscription_days(user_id: str, additional_days: int):
    if not db: 
        logger.error("❌ Database not connected")
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
            
            # ГАРАНТИРУЕМ что у пользователя есть UUID при активации подписки
            if has_subscription:
                try:
                    vless_uuid = await ensure_user_uuid(user_id)
                    update_data['vless_uuid'] = vless_uuid
                    update_data['subscription_start'] = datetime.now().isoformat()
                    logger.info(f"🔑 UUID ensured for user {user_id}: {vless_uuid}")
                except Exception as e:
                    logger.error(f"❌ Failed to ensure UUID for user {user_id}: {e}")
                    return False
            
            user_ref.update(update_data)
            logger.info(f"✅ Subscription days updated for user {user_id}: {current_days} -> {new_days} (+{additional_days})")
            return True
        else:
            logger.error(f"❌ User {user_id} not found")
            return False
    except Exception as e:
        logger.error(f"❌ Error updating subscription days: {e}")
        return False

# Функция для запуска бота в отдельном процессе
def run_bot():
    """Запуск бота в отдельном процессе"""
    try:
        logger.info("🤖 Starting Telegram bot in separate process...")
        subprocess.run([sys.executable, "bot.py"], check=True)
    except Exception as e:
        logger.error(f"❌ Bot execution error: {e}")

@app.on_event("startup")
async def startup_event():
    """Действия при запуске приложения"""
    logger.info("🚀 VAC VPN Server starting up...")
    
    # Копируем логотип в статическую директорию если его там нет
    ensure_logo_exists()
    
    # Автоматически запускаем бота при старте
    logger.info("🔄 Starting Telegram bot automatically...")
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    logger.info("✅ Telegram bot started successfully")

# API ЭНДПОИНТЫ
@app.get("/")
async def root():
    """Главная страница"""
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    
    xray_users_count = await get_xray_users_count()
    return {
        "message": "VAC VPN API is running", 
        "status": "ok",
        "firebase": "connected" if db else "disconnected",
        "xray_users": xray_users_count,
        "environment": "production",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/health")
async def health_check():
    """Проверка здоровья системы"""
    xray_users_count = await get_xray_users_count()
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "VAC VPN API",
        "firebase": "connected" if db else "disconnected",
        "xray_users": xray_users_count,
        "database_connected": db is not None,
        "environment": "production"
    }

@app.get("/check-xray-connection")
async def check_xray_connection():
    """Проверить подключение к Xray Manager"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{XRAY_MANAGER_URL}/health",
                timeout=10.0
            )
            return {
                "connected": response.status_code == 200,
                "status_code": response.status_code,
                "response": response.text
            }
    except Exception as e:
        return {"connected": False, "error": str(e)}

@app.delete("/clear-referrals/{user_id}")
async def clear_referrals(user_id: str):
    try:
        if not db:
            return {"error": "Database not connected"}
        
        referrals_ref = db.collection('referrals').where('referrer_id', '==', user_id)
        referrals = referrals_ref.stream()
        for ref in referrals:
            ref.reference.delete()
        
        user_ref = db.collection('users').document(user_id)
        user_ref.update({
            'referred_by': firestore.DELETE_FIELD
        })
        
        logger.info(f"🧹 Cleared referrals for user {user_id}")
        return {"success": True, "message": "Referrals cleared"}
        
    except Exception as e:
        logger.error(f"❌ Error clearing referrals: {e}")
        return {"error": str(e)}

@app.post("/init-user")
async def init_user(request: InitUserRequest):
    try:
        logger.info(f"🔍 INIT-USER START: user_id={request.user_id}, start_param='{request.start_param}'")
        
        if not db:
            return JSONResponse(status_code=500, content={"error": "Database not connected"})
        
        if not request.user_id or request.user_id == 'unknown':
            return JSONResponse(status_code=400, content={"error": "Invalid user ID"})
        
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
                        bonus_result = add_referral_bonus_immediately(referrer_id, request.user_id)
                        if bonus_result:
                            bonus_applied = True
                            logger.info(f"🎉 Referral bonuses applied immediately for {request.user_id}")
        
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
                'subscription_start': None,
                'vless_uuid': None,
                'created_at': firestore.SERVER_TIMESTAMP
            }
            
            if is_referral and referrer_id:
                user_data['referred_by'] = referrer_id
                logger.info(f"🔗 User {request.user_id} referred by {referrer_id}")
            
            user_ref.set(user_data)
            logger.info(f"✅ User created: {request.user_id}, referral: {is_referral}, bonus_applied: {bonus_applied}")
            
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
                "bonus_applied": False
            }
            
    except Exception as e:
        logger.error(f"❌ Error initializing user: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/user-data")
async def get_user_info(user_id: str):
    try:
        if not db:
            return JSONResponse(status_code=500, content={"error": "Database not connected"})
        
        if not user_id or user_id == 'unknown':
            return JSONResponse(status_code=400, content={"error": "Invalid user ID"})
            
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
                "referrer_bonus": REFERRAL_BONUS_REFERRER,
                "referred_bonus": REFERRAL_BONUS_REFERRED
            }
        }
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Error getting user info: {str(e)}"})

@app.post("/add-balance")
async def add_balance(request: AddBalanceRequest):
    try:
        logger.info(f"💰 ADD-BALANCE START: user_id={request.user_id}, amount={request.amount}, payment_method={request.payment_method}")
        
        if not db:
            return JSONResponse(status_code=500, content={"error": "Database not connected"})
            
        user = get_user(request.user_id)
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        if request.amount < 10:
            return JSONResponse(status_code=400, content={"error": "Минимальная сумма пополнения 10₽"})
        
        if request.amount > 50000:
            return JSONResponse(status_code=400, content={"error": "Максимальная сумма пополнения 50,000₽"})
        
        if request.payment_method == "yookassa":
            SHOP_ID = os.getenv("SHOP_ID")
            API_KEY = os.getenv("API_KEY")
            
            if not SHOP_ID or not API_KEY:
                return JSONResponse(status_code=500, content={"error": "Payment gateway not configured"})
            
            payment_id = str(uuid.uuid4())
            save_payment(payment_id, request.user_id, request.amount, "balance", "balance", "yookassa")
            
            yookassa_data = {
                "amount": {"value": f"{request.amount:.2f}", "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": "https://t.me/vaaaac_bot"},
                "capture": True,
                "description": f"Пополнение баланса VAC VPN на {request.amount}₽",
                "metadata": {
                    "payment_id": payment_id,
                    "user_id": request.user_id,
                    "payment_type": "balance",
                    "amount": request.amount
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
                    "amount": request.amount,
                    "status": "pending",
                    "message": f"Перейдите по ссылке для пополнения баланса на {request.amount}₽"
                }
            else:
                return JSONResponse(status_code=500, content={"error": f"Payment gateway error: {response.status_code}"})
        else:
            return JSONResponse(status_code=400, content={"error": "Invalid payment method"})
        
    except Exception as e:
        logger.error(f"❌ Error adding balance: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/activate-tariff")
async def activate_tariff(request: ActivateTariffRequest):
    try:
        if not db:
            return JSONResponse(status_code=500, content={"error": "Database not connected"})
            
        user = get_user(request.user_id)
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        if request.tariff not in TARIFFS:
            return JSONResponse(status_code=400, content={"error": "Invalid tariff"})
            
        tariff_data = TARIFFS[request.tariff]
        tariff_price = tariff_data["price"]
        tariff_days = tariff_data["days"]
        
        if request.payment_method == "balance":
            user_balance = user.get('balance', 0.0)
            
            if user_balance < tariff_price:
                return JSONResponse(status_code=400, content={"error": f"Недостаточно средств на балансе. Необходимо: {tariff_price}₽, доступно: {user_balance}₽"})
            
            payment_id = str(uuid.uuid4())
            save_payment(payment_id, request.user_id, tariff_price, request.tariff, "tariff", "balance")
            
            update_user_balance(request.user_id, -tariff_price)
            
            success = await update_subscription_days(request.user_id, tariff_days)
            
            if not success:
                return JSONResponse(status_code=500, content={"error": "Ошибка активации подписки"})
            
            # Начисляем реферальные бонусы при первой покупке
            if user.get('referred_by'):
                referrer_id = user['referred_by']
                referral_id = f"{referrer_id}_{request.user_id}"
                
                referral_exists = db.collection('referrals').document(referral_id).get().exists
                
                if not referral_exists:
                    logger.info(f"🎁 Applying referral bonus for {request.user_id} referred by {referrer_id}")
                    add_referral_bonus_immediately(referrer_id, request.user_id)
            
            update_payment_status(payment_id, "succeeded")
            
            return {
                "success": True,
                "payment_id": payment_id,
                "amount": tariff_price,
                "days": tariff_days,
                "status": "succeeded",
                "message": "Подписка успешно активирована с баланса!"
            }
        
        elif request.payment_method == "yookassa":
            SHOP_ID = os.getenv("SHOP_ID")
            API_KEY = os.getenv("API_KEY")
            
            if not SHOP_ID or not API_KEY:
                return JSONResponse(status_code=500, content={"error": "Payment gateway not configured"})
            
            payment_id = str(uuid.uuid4())
            save_payment(payment_id, request.user_id, tariff_price, request.tariff, "tariff", "yookassa")
            
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
                return JSONResponse(status_code=500, content={"error": f"Payment gateway error: {response.status_code}"})
        
        else:
            return JSONResponse(status_code=400, content={"error": "Invalid payment method"})
        
    except Exception as e:
        logger.error(f"❌ Error activating tariff: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/buy-with-balance")
async def buy_with_balance(request: BuyWithBalanceRequest):
    try:
        logger.info(f"💰 BUY-WITH-BALANCE: user_id={request.user_id}, tariff={request.tariff_id}, price={request.tariff_price}")
        
        if not db:
            return JSONResponse(status_code=500, content={"error": "Database not connected"})
        
        user = get_user(request.user_id)
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        user_balance = user.get('balance', 0.0)
        
        if user_balance < request.tariff_price:
            return JSONResponse(status_code=400, content={
                "success": False,
                "error": f"Недостаточно средств на балансе. На вашем балансе {user_balance}₽, а требуется {request.tariff_price}₽"
            })
        
        payment_id = str(uuid.uuid4())
        save_payment(payment_id, request.user_id, request.tariff_price, request.tariff_id, "tariff", "balance")
        
        update_user_balance(request.user_id, -request.tariff_price)
        
        success = await update_subscription_days(request.user_id, request.tariff_days)
        
        if not success:
            return JSONResponse(status_code=500, content={"error": "Ошибка активации подписки"})
        
        # Начисляем реферальные бонусы при первой покупке
        if user.get('referred_by'):
            referrer_id = user['referred_by']
            referral_id = f"{referrer_id}_{request.user_id}"
            
            referral_exists = db.collection('referrals').document(referral_id).get().exists
            
            if not referral_exists:
                logger.info(f"🎁 Applying referral bonus for {request.user_id} referred by {referrer_id}")
                add_referral_bonus_immediately(referrer_id, request.user_id)
        
        update_payment_status(payment_id, "succeeded")
        
        return {
            "success": True,
            "payment_id": payment_id,
            "amount": request.tariff_price,
            "days": request.tariff_days,
            "status": "succeeded",
            "message": "Подписка успешно активирована с баланса!"
        }
        
    except Exception as e:
        logger.error(f"❌ Error in buy-with-balance: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/payment-status")
async def check_payment(payment_id: str, user_id: str):
    try:
        if not db:
            return JSONResponse(status_code=500, content={"error": "Database not connected"})
            
        if not payment_id or payment_id == 'undefined':
            return JSONResponse(status_code=400, content={"error": "Invalid payment ID"})
            
        payment = get_payment(payment_id)
        if not payment:
            return JSONResponse(status_code=404, content={"error": "Payment not found"})
        
        # Используем user_id из параметра, а не из payment
        actual_user_id = user_id if user_id != 'undefined' else payment.get('user_id')
        
        if not actual_user_id or actual_user_id == 'undefined':
            return JSONResponse(status_code=400, content={"error": "Invalid user ID"})
        
        if payment['status'] == 'succeeded':
            if payment['payment_type'] == 'balance':
                return {
                    "success": True,
                    "status": "succeeded",
                    "payment_id": payment_id,
                    "amount": payment['amount'],
                    "balance_added": payment['amount']
                }
            else:
                return {
                    "success": True,
                    "status": "succeeded",
                    "payment_id": payment_id,
                    "amount": payment['amount']
                }
        
        if payment.get('payment_method') == 'yookassa':
            yookassa_id = payment.get('yookassa_id')
            if yookassa_id:
                SHOP_ID = os.getenv("SHOP_ID")
                API_KEY = os.getenv("API_KEY")
                
                if not SHOP_ID or not API_KEY:
                    return JSONResponse(status_code=500, content={"error": "Payment gateway not configured"})
                
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"https://api.yookassa.ru/v3/payments/{yookassa_id}",
                        auth=(SHOP_ID, API_KEY),
                        timeout=30.0
                    )
                    
                    if response.status_code == 200:
                        yookassa_data = response.json()
                        status = yookassa_data.get('status')
                        
                        update_payment_status(payment_id, status, yookassa_id)
                        
                        if status == 'succeeded':
                            if payment['payment_type'] == 'balance':
                                amount = payment['amount']
                                success = update_user_balance(actual_user_id, amount)
                                
                                if success:
                                    logger.info(f"✅ Balance topped up for user {actual_user_id}: +{amount}₽")
                                    return {
                                        "success": True,
                                        "status": status,
                                        "payment_id": payment_id,
                                        "amount": amount,
                                        "balance_added": amount,
                                        "message": f"Баланс успешно пополнен на {amount}₽!"
                                    }
                                else:
                                    return JSONResponse(status_code=500, content={"error": "Ошибка пополнения баланса"})
                            
                            # Для тарифов используем user_id из платежа
                            tariff_user_id = payment.get('user_id', actual_user_id)
                            tariff = payment['tariff']
                            tariff_days = TARIFFS[tariff]["days"]
                            
                            success = await update_subscription_days(tariff_user_id, tariff_days)
                            
                            if not success:
                                logger.error(f"❌ Failed to activate subscription for user {tariff_user_id}")
                                return JSONResponse(status_code=500, content={"error": "Failed to activate subscription"})
                            
                            user = get_user(tariff_user_id)
                            if user and user.get('referred_by'):
                                referrer_id = user['referred_by']
                                referral_id = f"{referrer_id}_{tariff_user_id}"
                                
                                referral_exists = db.collection('referrals').document(referral_id).get().exists
                                
                                if not referral_exists:
                                    logger.info(f"🎁 Applying referral bonus for {tariff_user_id} referred by {referrer_id}")
                                    add_referral_bonus_immediately(referrer_id, tariff_user_id)
                            
                            logger.info(f"✅ Subscription activated for user {tariff_user_id}: +{tariff_days} days")
                            
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
        return JSONResponse(status_code=500, content={"error": f"Error checking payment: {str(e)}"})

@app.get("/get-vless-config")
async def get_vless_config(user_id: str):
    try:
        if not db:
            return JSONResponse(status_code=500, content={"error": "Database not connected"})
            
        # Обрабатываем списание дней подписки
        process_subscription_days(user_id)
            
        user = get_user(user_id)
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        # Проверяем активную подписку
        if not user.get('has_subscription', False):
            return JSONResponse(status_code=400, content={"error": "No active subscription"})
        
        # ГАРАНТИРУЕМ что у пользователя есть UUID и он в Xray
        vless_uuid = await ensure_user_uuid(user_id)
        
        # Создаем уникальные конфиги для этого пользователя
        configs = create_user_vless_configs(user_id, vless_uuid)
        
        logger.info(f"✅ Generated {len(configs)} unique configs for user {user_id}")
        
        return {
            "success": True,
            "user_id": user_id,
            "vless_uuid": vless_uuid,
            "has_subscription": True,
            "subscription_days": user.get('subscription_days', 0),
            "configs": configs
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting VLESS config: {e}")
        return JSONResponse(status_code=500, content={"error": f"Error getting VLESS config: {str(e)}"})

# Эндпоинт для получения логотипа
@app.get("/logo")
async def get_logo():
    """Возвращает логотип"""
    logo_path = "static/Airbrush-Image-Enhancer-1753455007914.png"
    if os.path.exists(logo_path):
        return FileResponse(logo_path, media_type="image/png")
    else:
        # Создаем логотип если его нет
        create_placeholder_logo()
        if os.path.exists(logo_path):
            return FileResponse(logo_path, media_type="image/png")
        else:
            raise HTTPException(status_code=404, detail="Logo not found")

# Админские эндпоинты для управления Xray через API
@app.post("/admin/generate-unique-uuid")
async def admin_generate_unique_uuid(user_id: str):
    """Принудительно генерирует уникальный UUID для пользователя"""
    try:
        vless_uuid = await ensure_user_uuid(user_id)
        
        return {
            "success": True,
            "user_id": user_id,
            "vless_uuid": vless_uuid,
            "message": "Unique UUID generated and added to Xray"
        }
        
    except Exception as e:
        logger.error(f"❌ Error generating unique UUID: {e}")
        return {"error": str(e)}

@app.get("/admin/user-uuid-info")
async def admin_user_uuid_info(user_id: str):
    """Информация о UUID пользователя"""
    try:
        user = get_user(user_id)
        if not user:
            return {"error": "User not found"}
        
        vless_uuid = user.get('vless_uuid')
        in_xray = await check_user_in_xray(vless_uuid) if vless_uuid else False
        
        return {
            "user_id": user_id,
            "has_uuid": vless_uuid is not None,
            "vless_uuid": vless_uuid,
            "in_xray": in_xray,
            "has_subscription": user.get('has_subscription', False),
            "subscription_days": user.get('subscription_days', 0)
        }
        
    except Exception as e:
        return {"error": str(e)}

@app.post("/admin/generate-uuid-for-user")
async def generate_uuid_for_user(user_id: str):
    """Принудительно сгенерировать UUID для пользователя и добавить в Xray"""
    try:
        if not db:
            return {"error": "Database not connected"}
        
        user = get_user(user_id)
        if not user:
            return {"error": "User not found"}
        
        # Если у пользователя уже есть UUID
        existing_uuid = user.get('vless_uuid')
        if existing_uuid:
            # Проверяем есть ли в Xray, если нет - добавляем
            if not await check_user_in_xray(existing_uuid):
                success = await add_user_to_xray(existing_uuid)
                if success:
                    return {
                        "success": True,
                        "message": f"UUID {existing_uuid} добавлен в Xray",
                        "user_uuid": existing_uuid,
                        "action": "added_to_xray"
                    }
                else:
                    return {"error": f"Не удалось добавить UUID в Xray"}
            else:
                return {
                    "success": True,
                    "message": f"UUID уже существует и есть в Xray",
                    "user_uuid": existing_uuid,
                    "action": "already_exists"
                }
        
        # Если UUID нет - генерируем новый
        user_uuid = generate_user_uuid()
        
        # Обновляем пользователя в базе
        user_ref = db.collection('users').document(user_id)
        user_ref.update({
            'vless_uuid': user_uuid,
            'updated_at': firestore.SERVER_TIMESTAMP
        })
        
        # Добавляем в Xray
        success = await add_user_to_xray(user_uuid)
        if success:
            return {
                "success": True,
                "message": f"Сгенерирован новый UUID и добавлен в Xray",
                "user_uuid": user_uuid,
                "action": "generated_and_added"
            }
        else:
            return {"error": f"Не удалось добавить UUID в Xray"}
        
    except Exception as e:
        logger.error(f"❌ Error generating UUID: {e}")
        return {"error": str(e)}

@app.get("/admin/xray-users")
async def get_xray_users():
    """Показать всех пользователей в Xray конфиге через API"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{XRAY_MANAGER_URL}/users",
                headers={"Authorization": f"Bearer {XRAY_API_KEY}"},
                timeout=5.0
            )
            
            if response.status_code == 200:
                users = response.json()
                return {"users": users, "count": len(users)}
            else:
                return {"error": f"Failed to get Xray users: {response.status_code}"}
    except Exception as e:
        return {"error": str(e)}

@app.post("/admin/add-balance")
async def admin_add_balance(user_id: str, amount: float):
    try:
        if not db:
            return {"error": "Database not connected"}
        
        success = update_user_balance(user_id, amount)
        if success:
            return {"success": True, "message": f"Баланс пользователя {user_id} пополнен на {amount}₽"}
        else:
            return {"error": "Не удалось пополнить баланс"}
            
    except Exception as e:
        logger.error(f"❌ Error adding balance: {e}")
        return {"error": str(e)}

@app.post("/admin/reset-user")
async def admin_reset_user(user_id: str):
    try:
        if not db:
            return {"error": "Database not connected"}
        
        user = get_user(user_id)
        if user and user.get('vless_uuid'):
            # Удаляем пользователя из Xray
            await remove_user_from_xray(user['vless_uuid'])
        
        user_ref = db.collection('users').document(user_id)
        user_ref.update({
            'balance': 0.0,
            'subscription_days': 0,
            'has_subscription': False,
            'vless_uuid': None,
            'referred_by': firestore.DELETE_FIELD,
            'updated_at': firestore.SERVER_TIMESTAMP
        })
        
        referrals_ref = db.collection('referrals').where('referrer_id', '==', user_id)
        referrals = referrals_ref.stream()
        for ref in referrals:
            ref.reference.delete()
        
        referrals_ref = db.collection('referrals').where('referred_id', '==', user_id)
        referrals = referrals_ref.stream()
        for ref in referrals:
            ref.reference.delete()
        
        return {"success": True, "message": f"Данные пользователя {user_id} сброшены"}
        
    except Exception as e:
        logger.error(f"❌ Error resetting user: {e}")
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
