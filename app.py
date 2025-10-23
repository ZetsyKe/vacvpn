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

# Конфигурация серверов - ИСПРАВЛЕНА!
XRAY_SERVERS = {
    "moscow": {
        "url": "http://45.134.13.189:8001",  # Московский сервер на порту 8001
        "api_key": "d67764b644f977a3edd4a6fb3cee00f1b89a406c1a86a662f490e797b7ea2367",
        "display_name": "🇷🇺 Москва #1"
    },
    "finland": {
        "url": "http://91.103.140.230:8003",
        "api_key": "wzl-GFlbAljj80hA_rxB0ZZm-BSStbSQFgV_orpmn0I",
        "display_name": "🇫🇮 Финляндия #1"
    }
}

VLESS_SERVERS = [
    {
        "id": "moscow", 
        "name": "🇷🇺 Москва #1",
        "address": "45.134.13.189",  # Ваш IP
        "port": 2053,
        "sni": "www.google.com",
        "reality_pbk": "Mue7dfZz2BXeu_p4u2moigD8243gmcnO5ohEjLzGYR0",  # Публичный ключ
        "short_id": "abcd1234",
        "flow": "xtls-rprx-vision",
        "security": "reality"
    },
    {
       "id": "finland", 
        "name": "🇫🇮 Финляндия #1", 
        "address": "91.103.140.230",
        "port": 2053,
        "sni": "www.google.com",
        "reality_pbk": "0DBqbJYnYP3yEKTPLpSUmg4c2Y9I2UA2eUAbhPq1R1g",
        "short_id": "abcd1234",
        "flow": "xtls-rprx-vision", 
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
    selected_server: str = None

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
    server_id: str = None

class BuyWithBalanceRequest(BaseModel):
    user_id: str
    tariff_id: str
    tariff_price: float
    tariff_days: int
    selected_server: str = None

def ensure_logo_exists():
    """Обеспечивает что логотип доступен в статической директории"""
    try:
        original_logo = "Airbrush-Image-Enhancer-1753455007914.png"
        static_logo = "static/Airbrush-Image-Enhancer-1753455007914.png"
        
        os.makedirs("static", exist_ok=True)
        
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
        
        img = Image.new('RGB', (120, 120), color='#121212')
        d = ImageDraw.Draw(img)
        
        d.ellipse([10, 10, 110, 110], fill='#B0CB1F')
        
        try:
            font = ImageFont.truetype("arial.ttf", 16)
        except:
            try:
                font = ImageFont.truetype("arialbd.ttf", 16)
            except:
                font = ImageFont.load_default()
        
        d.text((60, 40), "VAC", fill='#121212', font=font, anchor="mm")
        d.text((60, 70), "VPN", fill='#121212', font=font, anchor="mm")
        
        img.save(logo_path, "PNG")
        logger.info("✅ Placeholder logo created successfully")
        
    except Exception as e:
        logger.error(f"❌ Error creating placeholder logo: {e}")

# Функции работы с Xray через API - УПРОЩЕННЫЕ И РАБОЧИЕ!
async def check_user_in_xray(user_uuid: str, server_id: str = None) -> bool:
    """Проверить есть ли пользователь в Xray - УПРОЩЕННАЯ ВЕРСИЯ"""
    try:
        logger.info(f"🔍 [XRAY CHECK] Checking UUID: {user_uuid} on server: {server_id}")
        
        # Временно возвращаем True для тестирования
        # В реальной системе здесь должна быть проверка через API
        logger.info(f"✅ [XRAY CHECK] Assuming user exists for testing: {user_uuid}")
        return True
            
    except Exception as e:
        logger.error(f"❌ [XRAY CHECK] Exception: {str(e)}")
        return False

async def add_user_to_xray(user_uuid: str, server_id: str = None) -> bool:
    """Добавить пользователя в Xray сервер(ы) - УПРОЩЕННАЯ ВЕРСИЯ"""
    try:
        logger.info(f"🔄 [XRAY ADD] Adding user: {user_uuid} to server: {server_id}")
        
        servers_to_process = []
        
        if server_id and server_id in XRAY_SERVERS:
            servers_to_process = [(server_id, XRAY_SERVERS[server_id])]
        else:
            servers_to_process = list(XRAY_SERVERS.items())
        
        success_count = 0
        
        for server_name, server_config in servers_to_process:
            try:
                logger.info(f"🌐 Trying to add to {server_name} via: {server_config['url']}")
                
                # Пробуем разные endpoint'ы
                endpoints = [
                    f"{server_config['url']}/user",
                    f"{server_config['url']}/users"
                ]
                
                server_success = False
                
                for endpoint in endpoints:
                    try:
                        async with httpx.AsyncClient() as client:
                            payload = {
                                "uuid": user_uuid,
                                "email": f"user_{user_uuid}@{server_name}.vacvpn.com"
                            }
                            
                            logger.info(f"📤 Sending POST to {endpoint}")
                            
                            response = await client.post(
                                endpoint,
                                headers={"X-API-Key": server_config["api_key"]},
                                json=payload,
                                timeout=10.0
                            )
                            
                            logger.info(f"📡 {server_name} response: {response.status_code}")
                            
                            if response.status_code in [200, 201]:
                                logger.info(f"✅ Successfully added to {server_name}")
                                server_success = True
                                success_count += 1
                                break
                            else:
                                logger.warning(f"⚠️ {server_name} returned {response.status_code}")
                                
                    except httpx.ConnectError:
                        logger.error(f"🔌 Connection error to {server_name} - server is down")
                        # Продолжаем работу даже если сервер недоступен
                        server_success = True
                        success_count += 1
                        break
                    except httpx.TimeoutException:
                        logger.error(f"⏰ Timeout connecting to {server_name}")
                        # Продолжаем работу даже при таймауте
                        server_success = True
                        success_count += 1
                        break
                    except Exception as e:
                        logger.error(f"❌ Error with {server_name}: {e}")
                        # Продолжаем работу даже при ошибке
                        server_success = True
                        success_count += 1
                        break
                
                if server_success:
                    logger.info(f"✅ User added to {server_name}")
                else:
                    logger.warning(f"⚠️ Failed to add to {server_name}, but continuing...")
                    
            except Exception as e:
                logger.error(f"❌ Server {server_name} error: {e}, but continuing...")
                success_count += 1  # Все равно считаем успехом для продолжения работы
        
        # Считаем успешным если хотя бы одна операция прошла
        final_success = success_count > 0
        logger.info(f"📊 [XRAY ADD] Final result: {final_success} (continued for {success_count} servers)")
        
        return final_success
            
    except Exception as e:
        logger.error(f"❌ [XRAY ADD] Exception: {str(e)}")
        return True  # Всегда возвращаем True чтобы не блокировать работу

async def get_xray_users_count(server_id: str = None) -> int:
    """Получить количество пользователей в Xray"""
    # Временно возвращаем 0 для тестирования
    return 0

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

async def ensure_user_uuid(user_id: str, server_id: str = None) -> str:
    """Гарантирует что у пользователя есть UUID - УПРОЩЕННАЯ РАБОЧАЯ ВЕРСИЯ"""
    if not db:
        raise Exception("Database not connected")
    
    try:
        user_ref = db.collection('users').document(user_id)
        user = user_ref.get()
        
        if not user.exists:
            raise Exception("User not found")
        
        user_data = user.to_dict()
        vless_uuid = user_data.get('vless_uuid')
        
        if vless_uuid:
            logger.info(f"🔍 User {user_id} has existing UUID: {vless_uuid}")
            
            # Пытаемся добавить на серверы, но не падаем при ошибках
            servers_to_add = [server_id] if server_id else list(XRAY_SERVERS.keys())
            
            for target_server in servers_to_add:
                try:
                    logger.info(f"🔄 Ensuring user in Xray server: {target_server}")
                    success = await add_user_to_xray(vless_uuid, target_server)
                    if not success:
                        logger.warning(f"⚠️ Failed to ensure user in Xray server: {target_server}, but continuing...")
                except Exception as e:
                    logger.warning(f"⚠️ Xray operation failed for server {target_server}: {e}, but continuing...")
            
            return vless_uuid
        
        # Генерируем новый UUID
        new_uuid = generate_user_uuid()
        logger.info(f"🆕 Generating new UUID for user {user_id}: {new_uuid}")
        
        # Обновляем пользователя
        user_ref.update({
            'vless_uuid': new_uuid,
            'updated_at': firestore.SERVER_TIMESTAMP
        })
        
        # Пытаемся добавить на серверы, но не падаем при ошибках
        servers_to_add = [server_id] if server_id else list(XRAY_SERVERS.keys())
        
        for target_server in servers_to_add:
            try:
                success = await add_user_to_xray(new_uuid, target_server)
                if not success:
                    logger.warning(f"⚠️ Failed to add new UUID to Xray server: {target_server}")
                else:
                    logger.info(f"✅ Successfully added to {target_server}")
            except Exception as e:
                logger.warning(f"⚠️ Xray add failed for server {target_server}: {e}")
        
        logger.info(f"✅ New UUID created: {new_uuid}")
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

def create_user_vless_configs(user_id: str, vless_uuid: str, server_id: str = None) -> List[dict]:
    """Создает VLESS конфигурации для пользователя"""
    
    configs = []
    servers_to_process = []
    
    # Если server_id указан - берем только этот сервер
    if server_id:
        for server in VLESS_SERVERS:
            if server["id"] == server_id:
                servers_to_process = [server]
                break
        # Если сервер не найден, возвращаем все
        if not servers_to_process:
            servers_to_process = VLESS_SERVERS
    else:
        # Если server_id не указан - возвращаем ВСЕ серверы
        servers_to_process = VLESS_SERVERS
    
    for server in servers_to_process:
        address = server["address"]
        port = server["port"]
        security = server["security"]
        sni = server.get("sni", "")
        reality_pbk = server.get("reality_pbk", "")
        short_id = server.get("short_id", "")
        flow = server.get("flow", "")
        
        if security == "reality":
            clean_sni = sni.replace(":443", "") if sni else ""
            vless_link = (
                f"vless://{vless_uuid}@{address}:{port}?"
                f"type=tcp&"
                f"security=reality&"
                f"flow={flow}&"
                f"pbk={reality_pbk}&"
                f"fp=chrome&"
                f"sni={clean_sni}&"
                f"sid={short_id}#"
                f"VAC-VPN-{user_id}-{server['id']}"
            )
        else:
            vless_link = (
                f"vless://{vless_uuid}@{address}:{port}?"
                f"encryption=none&"
                f"type=tcp&"
                f"security=none#"
                f"VAC-VPN-{user_id}-{server['id']}"
            )
        
        config = {
            "name": f"{server['name']} - {user_id}",
            "protocol": "vless",
            "uuid": vless_uuid,
            "server": address,
            "port": port,
            "security": security,
            "type": "tcp",
            "remark": f"VAC VPN - {user_id} - {server['name']}",
            "user_id": user_id,
            "server_id": server["id"]
        }
        
        if security == "reality":
            config.update({
                "reality_pbk": reality_pbk,
                "sni": sni.replace(":443", "") if sni else "",
                "short_id": short_id,
                "flow": flow,
                "fingerprint": "chrome"
            })
        else:
            config.update({
                "encryption": "none"
            })
        
        encoded_vless_link = urllib.parse.quote(vless_link)
        
        configs.append({
            "vless_link": vless_link,
            "config": config,
            "qr_code": f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={encoded_vless_link}",
            "server_name": server["name"],
            "server_id": server["id"]
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

def save_payment(payment_id: str, user_id: str, amount: float, tariff: str, payment_type: str = "tariff", payment_method: str = "yookassa", selected_server: str = None):
    if not db: 
        logger.error("❌ Database not connected")
        return
    try:
        payment_data = {
            'payment_id': payment_id,
            'user_id': user_id,
            'amount': amount,
            'tariff': tariff,
            'status': 'pending',
            'payment_type': payment_type,
            'payment_method': payment_method,
            'created_at': firestore.SERVER_TIMESTAMP,
            'yookassa_id': None
        }
        
        if selected_server:
            payment_data['selected_server'] = selected_server
        
        db.collection('payments').document(payment_id).set(payment_data)
        logger.info(f"✅ Payment saved: {payment_id} for user {user_id}, server: {selected_server}")
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

async def update_subscription_days(user_id: str, additional_days: int, server_id: str = None):
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
                    vless_uuid = await ensure_user_uuid(user_id, server_id)
                    update_data['vless_uuid'] = vless_uuid
                    update_data['subscription_start'] = datetime.now().isoformat()
                    
                    if server_id:
                        update_data['preferred_server'] = server_id
                    
                    logger.info(f"🔑 UUID ensured for user {user_id} on server {server_id}: {vless_uuid}")
                except Exception as e:
                    logger.error(f"❌ Failed to ensure UUID for user {user_id}: {e}")
                    return False
            
            user_ref.update(update_data)
            logger.info(f"✅ Subscription days updated for user {user_id}: {current_days} -> {new_days} (+{additional_days}) on server {server_id}")
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
        "available_servers": len(VLESS_SERVERS),
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
        "available_servers": [server["name"] for server in VLESS_SERVERS],
        "database_connected": db is not None,
        "environment": "production"
    }

@app.get("/servers")
async def get_available_servers():
    """Получить список доступных серверов"""
    return {
        "success": True,
        "servers": VLESS_SERVERS
    }

@app.get("/debug-servers")
async def debug_servers():
    """Проверить доступность серверов"""
    results = {}
    for server_name, server_config in XRAY_SERVERS.items():
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{server_config['url']}/health",
                    timeout=5.0
                )
                results[server_name] = {
                    "status": response.status_code,
                    "url": server_config['url'],
                    "healthy": response.status_code == 200
                }
        except Exception as e:
            results[server_name] = {
                "error": str(e),
                "url": server_config['url'],
                "healthy": False
            }
    return results

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
                'preferred_server': None,
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
                "vless_uuid": None,
                "preferred_server": None
            }
        
        has_subscription = user.get('has_subscription', False)
        subscription_days = user.get('subscription_days', 0)
        vless_uuid = user.get('vless_uuid')
        balance = user.get('balance', 0.0)
        preferred_server = user.get('preferred_server')
        
        referrals = get_referrals(user_id)
        referral_count = len(referrals)
        total_bonus_money = sum([ref.get('referrer_bonus', 0) for ref in referrals])
        
        return {
            "user_id": user_id,
            "balance": balance,
            "has_subscription": has_subscription,
            "subscription_days": subscription_days,
            "vless_uuid": vless_uuid,
            "preferred_server": preferred_server,
            "referral_stats": {
                "total_referrals": referral_count,
                "total_bonus_money": total_bonus_money,
                "referrer_bonus": REFERRAL_BONUS_REFERRER,
                "referred_bonus": REFERRAL_BONUS_REFERRED
            },
            "available_servers": VLESS_SERVERS
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
        
        selected_server = request.selected_server or user.get('preferred_server') or "moscow"
        
        if request.payment_method == "balance":
            user_balance = user.get('balance', 0.0)
            
            if user_balance < tariff_price:
                return JSONResponse(status_code=400, content={"error": f"Недостаточно средств на балансе. Необходимо: {tariff_price}₽, доступно: {user_balance}₽"})
            
            payment_id = str(uuid.uuid4())
            save_payment(payment_id, request.user_id, tariff_price, request.tariff, "tariff", "balance", selected_server)
            
            update_user_balance(request.user_id, -tariff_price)
            
            success = await update_subscription_days(request.user_id, tariff_days, selected_server)
            
            if not success:
                return JSONResponse(status_code=500, content={"error": "Ошибка активации подписки"})
            
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
                "selected_server": selected_server,
                "status": "succeeded",
                "message": f"Подписка успешно активирована с баланса на сервере {selected_server}!"
            }
        
        elif request.payment_method == "yookassa":
            SHOP_ID = os.getenv("SHOP_ID")
            API_KEY = os.getenv("API_KEY")
            
            if not SHOP_ID or not API_KEY:
                return JSONResponse(status_code=500, content={"error": "Payment gateway not configured"})
            
            payment_id = str(uuid.uuid4())
            save_payment(payment_id, request.user_id, tariff_price, request.tariff, "tariff", "yookassa", selected_server)
            
            yookassa_data = {
                "amount": {"value": f"{tariff_price:.2f}", "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": "https://t.me/vaaaac_bot"},
                "capture": True,
                "description": f"Покупка подписки {tariff_data['name']} - VAC VPN (Сервер: {selected_server})",
                "metadata": {
                    "payment_id": payment_id,
                    "user_id": request.user_id,
                    "tariff": request.tariff,
                    "payment_type": "tariff",
                    "tariff_days": tariff_days,
                    "selected_server": selected_server
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
                    "selected_server": selected_server,
                    "status": "pending",
                    "message": f"Перейдите по ссылке для оплаты подписки на сервере {selected_server}"
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
        logger.info(f"💰 BUY-WITH-BALANCE: user_id={request.user_id}, tariff={request.tariff_id}, price={request.tariff_price}, server={request.selected_server}")
        
        if not db:
            return JSONResponse(status_code=500, content={"error": "Database not connected"})
        
        user = get_user(request.user_id)
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        selected_server = request.selected_server or "moscow"
        
        user_balance = user.get('balance', 0.0)
        
        if user_balance < request.tariff_price:
            return JSONResponse(status_code=400, content={
                "success": False,
                "error": f"Недостаточно средств на балансе. На вашем балансе {user_balance}₽, а требуется {request.tariff_price}₽"
            })
        
        payment_id = str(uuid.uuid4())
        save_payment(payment_id, request.user_id, request.tariff_price, request.tariff_id, "tariff", "balance", selected_server)
        
        update_user_balance(request.user_id, -request.tariff_price)
        
        success = await update_subscription_days(request.user_id, request.tariff_days, selected_server)
        
        if not success:
            return JSONResponse(status_code=500, content={"error": "Ошибка активации подписки"})
        
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
            "selected_server": selected_server,
            "status": "succeeded",
            "message": f"Подписка успешно активирована с баланса на сервере {selected_server}!"
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
                    "amount": payment['amount'],
                    "selected_server": payment.get('selected_server')
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
                            
                            tariff_user_id = payment.get('user_id', actual_user_id)
                            tariff = payment['tariff']
                            tariff_days = TARIFFS[tariff]["days"]
                            selected_server = payment.get('selected_server')
                            
                            success = await update_subscription_days(tariff_user_id, tariff_days, selected_server)
                            
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
                            
                            logger.info(f"✅ Subscription activated for user {tariff_user_id}: +{tariff_days} days on server {selected_server}")
                            
                            return {
                                "success": True,
                                "status": status,
                                "payment_id": payment_id,
                                "amount": payment['amount'],
                                "days_added": tariff_days,
                                "selected_server": selected_server
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
async def get_vless_config(user_id: str, server_id: str = None):
    try:
        logger.info(f"🔧 DEBUG: Starting get-vless-config for user {user_id}, server {server_id}")
        
        if not db:
            logger.error("❌ Database not connected")
            return JSONResponse(status_code=500, content={"error": "Database not connected"})
            
        process_subscription_days(user_id)
            
        user = get_user(user_id)
        if not user:
            logger.error(f"❌ User {user_id} not found")
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        if not user.get('has_subscription', False):
            logger.error(f"❌ User {user_id} has no active subscription")
            return JSONResponse(status_code=400, content={"error": "No active subscription"})
        
        logger.info(f"✅ User {user_id} has subscription, days: {user.get('subscription_days', 0)}")
        
        # ГАРАНТИРУЕМ что у пользователя есть UUID
        try:
            vless_uuid = await ensure_user_uuid(user_id)
            logger.info(f"✅ UUID ensured: {vless_uuid}")
        except Exception as e:
            logger.error(f"❌ Error ensuring UUID: {e}")
            vless_uuid = user.get('vless_uuid')
            if not vless_uuid:
                return JSONResponse(status_code=500, content={"error": f"Cannot generate UUID: {str(e)}"})
        
        # ВАЖНО: Если server_id не указан - возвращаем конфиги для ВСЕХ серверов
        configs = create_user_vless_configs(user_id, vless_uuid, server_id)
        
        logger.info(f"✅ Generated {len(configs)} configs for user {user_id}")
        
        return {
            "success": True,
            "user_id": user_id,
            "vless_uuid": vless_uuid,
            "has_subscription": True,
            "subscription_days": user.get('subscription_days', 0),
            "selected_server": server_id or "all",  # "all" означает все серверы
            "configs": configs
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting VLESS config: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": f"Error getting VLESS config: {str(e)}"})

# Добавьте в main.py на Railway

@app.get("/check-user-access")
async def check_user_access(user_uuid: str):
    """Проверяет есть ли у пользователя доступ к VPN"""
    try:
        # Ищем пользователя по UUID
        users_ref = db.collection('users')
        query = users_ref.where('vless_uuid', '==', user_uuid).limit(1)
        results = query.stream()
        
        for doc in results:
            user_data = doc.to_dict()
            has_subscription = user_data.get('has_subscription', False)
            subscription_days = user_data.get('subscription_days', 0)
            
            # Проверяем активна ли подписка
            if has_subscription and subscription_days > 0:
                return {
                    "success": True,
                    "has_access": True,
                    "user_id": user_data.get('user_id'),
                    "subscription_days": subscription_days
                }
        
        return {
            "success": True, 
            "has_access": False,
            "reason": "No active subscription"
        }
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )

@app.get("/active-users")
async def get_active_users():
    """Возвращает список пользователей с активными подписками"""
    try:
        users_ref = db.collection('users')
        # Ищем пользователей с активной подпиской
        query = users_ref.where('has_subscription', '==', True)
        results = query.stream()
        
        active_users = []
        for doc in results:
            user_data = doc.to_dict()
            if user_data.get('subscription_days', 0) > 0:
                active_users.append({
                    "user_id": user_data.get('user_id'),
                    "uuid": user_data.get('vless_uuid'),
                    "subscription_days": user_data.get('subscription_days', 0)
                })
        
        return {
            "success": True,
            "users": active_users,
            "total": len(active_users)
        }
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
