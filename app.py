from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import os
import logging
import asyncio
from datetime import datetime
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
if os.path.exists("static") and os.listdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Конфигурация
XRAY_MANAGER_URL = os.getenv("XRAY_MANAGER_URL", "http://45.134.13.189:8001")
XRAY_API_KEY = os.getenv("XRAY_API_KEY", "vac-vpn-secret-key-2024")

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

class BuyWithBalanceRequest(BaseModel):
    user_id: str
    tariff_id: str
    tariff_price: float
    tariff_days: int

# Глобальные переменные для состояния приложения
bot_status = {
    "is_running": False,
    "last_activity": None,
    "errors": []
}

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

def add_referral_bonus_immediately(referrer_id: str, referred_id: str):
    if not db: 
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
        
        logger.info(f"✅ Immediate referral bonuses applied")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error adding immediate referral bonus: {e}")
        return False

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
    ]
    
    for pattern in patterns:
        match = re.search(pattern, start_param)
        if match:
            referrer_id = match.group(1)
            logger.info(f"✅ Found with pattern '{pattern}': {referrer_id}")
            return referrer_id
    
    logger.info(f"⚠️ Using raw start_param as referrer_id: {start_param}")
    return start_param

def get_referrals(referrer_id: str):
    if not db: 
        return []
    try:
        referrals = db.collection('referrals').where('referrer_id', '==', referrer_id).stream()
        return [ref.to_dict() for ref in referrals]
    except Exception as e:
        logger.error(f"❌ Error getting referrals: {e}")
        return []

# Функция для запуска бота в отдельном процессе
def run_bot():
    """Запуск бота в отдельном процессе"""
    try:
        logger.info("🤖 Starting Telegram bot in separate process...")
        subprocess.run([sys.executable, "bot.py"], check=True)
    except Exception as e:
        logger.error(f"❌ Bot execution error: {e}")
        bot_status["is_running"] = False
        bot_status["errors"].append(str(e))

@app.on_event("startup")
async def startup_event():
    """Действия при запуске приложения"""
    logger.info("🚀 VAC VPN Server starting up...")
    
    # Автоматически запускаем бота при старте
    if not bot_status["is_running"]:
        logger.info("🔄 Starting Telegram bot automatically...")
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()
        bot_status["is_running"] = True
        bot_status["last_activity"] = datetime.now().isoformat()
        logger.info("✅ Telegram bot started successfully")

# API ЭНДПОИНТЫ
@app.get("/")
async def root():
    """Главная страница"""
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    
    return {
        "message": "VAC VPN API is running", 
        "status": "ok",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/health")
async def health_check():
    """Проверка здоровья системы"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "VAC VPN API",
        "bot": {
            "is_running": bot_status["is_running"]
        }
    }

@app.post("/init-user")
async def init_user(request: InitUserRequest):
    try:
        logger.info(f"🔍 INIT-USER START: user_id={request.user_id}")
        
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
            logger.info(f"✅ User created: {request.user_id}")
            
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
                "total_bonus_money": total_bonus_money
            }
        }
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Error getting user info: {str(e)}"})

@app.post("/add-balance")
async def add_balance(request: AddBalanceRequest):
    try:
        logger.info(f"💰 ADD-BALANCE: user_id={request.user_id}, amount={request.amount}")
        
        if not db:
            return JSONResponse(status_code=500, content={"error": "Database not connected"})
            
        user = get_user(request.user_id)
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        if request.amount < 10:
            return JSONResponse(status_code=400, content={"error": "Минимальная сумма пополнения 10₽"})
        
        if request.amount > 50000:
            return JSONResponse(status_code=400, content={"error": "Максимальная сумма пополнения 50,000₽"})
        
        # Просто добавляем баланс (без реальной оплаты для демо)
        success = update_user_balance(request.user_id, request.amount)
        
        if success:
            return {
                "success": True,
                "message": f"Баланс пополнен на {request.amount}₽",
                "balance_added": request.amount
            }
        else:
            return JSONResponse(status_code=500, content={"error": "Ошибка пополнения баланса"})
        
    except Exception as e:
        logger.error(f"❌ Error adding balance: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/get-vless-config")
async def get_vless_config(user_id: str):
    try:
        if not db:
            return JSONResponse(status_code=500, content={"error": "Database not connected"})
            
        user = get_user(user_id)
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        # Проверяем активную подписку
        if not user.get('has_subscription', False):
            return JSONResponse(status_code=400, content={"error": "No active subscription"})
        
        vless_uuid = user.get('vless_uuid')
        if not vless_uuid:
            vless_uuid = generate_user_uuid()
            user_ref = db.collection('users').document(user_id)
            user_ref.update({
                'vless_uuid': vless_uuid,
                'updated_at': firestore.SERVER_TIMESTAMP
            })
        
        # Создаем конфигурацию
        configs = []
        for server in VLESS_SERVERS:
            vless_link = (
                f"vless://{vless_uuid}@{server['address']}:{server['port']}?"
                f"type=tcp&"
                f"security=reality&"
                f"flow={server['flow']}&"
                f"pbk={server['reality_pbk']}&"
                f"fp=chrome&"
                f"sni={server['sni']}&"
                f"sid={server['short_id']}#"
                f"VAC-VPN-{user_id}"
            )
            
            config = {
                "name": f"{server['name']} - {user_id}",
                "protocol": "vless",
                "uuid": vless_uuid,
                "server": server['address'],
                "port": server['port'],
                "security": "reality",
                "reality_pbk": server['reality_pbk'],
                "sni": server['sni'],
                "short_id": server['short_id'],
                "flow": server['flow'],
                "type": "tcp",
                "fingerprint": "chrome"
            }
            
            configs.append({
                "vless_link": vless_link,
                "config": config,
                "server_name": server["name"]
            })
        
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

# Статические файлы
@app.get("/favicon.ico")
async def favicon():
    return FileResponse("static/favicon.ico" if os.path.exists("static/favicon.ico") else None)

@app.get("/{filename}")
async def serve_static(filename: str):
    """Serve static files"""
    if os.path.exists(filename):
        return FileResponse(filename)
    raise HTTPException(status_code=404, detail="File not found")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8443))
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
        reload=False
    )
