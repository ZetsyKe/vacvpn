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
XRAY_SERVERS = {
    "moscow": {
        "url": "http://localhost:8003",  # Локальный на московском сервере
        "api_key": "moscow_api_key_here",
        "display_name": "🇷🇺 Москва #1"
    },
    "finland": {
        "url": "http://91.103.140.230:8003",  # ДОЛЖЕН БЫТЬ ТВОЙ IP!
        "api_key": "wzl-GFlbAljj80hA_rxB0ZZm-BSStbSQFgV_orpmn0I",
        "display_name": "🇫🇮 Финляндия #1"
    }
}

VLESS_SERVERS = [
    {
        "id": "moscow",
        "name": "🇷🇺 Москва #1",
        "address": "45.134.13.189", 
        "port": 2053,
        "sni": "www.google.com",
        "reality_pbk": "AZIvYvIEtJv5aA5-F-6gMg3a6KXuMgRJIHBLdp-7bAQ",
        "short_id": "abcd1234",
        "flow": "",
        "security": "reality",
        "xray_server": "moscow"
    },
    {
        "id": "finland", 
        "name": "🇫🇮 Финляндия #1", 
        "address": "91.103.140.230",
        "port": 2053,
        "sni": "www.google.com",
        "reality_pbk": "RiEEU2vtCrHqkR2wU8PexxXJQ2DGvRIbo3VmeBfVdXw",
        "short_id": "abcd1234",
        "flow": "",
        "security": "reality",
        "xray_server": "finland"
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
    selected_server: str = None  # Новое поле для выбора сервера

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
    server_id: str = None  # ID выбранного сервера

class BuyWithBalanceRequest(BaseModel):
    user_id: str
    tariff_id: str
    tariff_price: float
    tariff_days: int
    selected_server: str = None  # Новое поле для выбора сервера

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
async def check_user_in_xray(user_uuid: str, server_id: str = None) -> bool:
    """Проверить есть ли пользователь в Xray на конкретном сервере"""
    try:
        logger.info(f"🔍 [XRAY CHECK] Starting check for UUID: {user_uuid} on server: {server_id}")
        
        # Если указан конкретный сервер, проверяем только его
        if server_id and server_id in XRAY_SERVERS:
            server_config = XRAY_SERVERS[server_id]
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{server_config['url']}/users/{user_uuid}",
                        headers={"X-API-Key": server_config['api_key']},
                        timeout=30.0
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        exists = data.get("exists", False)
                        logger.info(f"✅ [XRAY CHECK] User exists in {server_id}: {exists}")
                        return exists
                    else:
                        logger.warning(f"⚠️ [XRAY CHECK] Server {server_id} returned {response.status_code}")
                        return False
                        
            except Exception as e:
                logger.warning(f"⚠️ [XRAY CHECK] Server {server_id} error: {e}")
                return False
        
        # Если сервер не указан, проверяем все серверы
        for server_name, server_config in XRAY_SERVERS.items():
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{server_config['url']}/users/{user_uuid}",
                        headers={"X-API-Key": server_config["api_key"]},
                        timeout=30.0
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        exists = data.get("exists", False)
                        if exists:
                            logger.info(f"✅ [XRAY CHECK] User exists in {server_name} Xray: {exists}")
                            return True
                        else:
                            logger.info(f"❌ [XRAY CHECK] User NOT found in {server_name}")
                    
            except Exception as e:
                logger.warning(f"⚠️ [XRAY CHECK] Server {server_name} error: {e}")
        
        logger.error(f"❌ [XRAY CHECK] User not found in any Xray server: {user_uuid}")
        return False
            
    except Exception as e:
        logger.error(f"❌ [XRAY CHECK] Exception: {str(e)}")
        return False

async def add_user_to_xray(user_uuid: str, server_id: str = None) -> bool:
    """Добавить пользователя в Xray сервер(ы)"""
    try:
        logger.info(f"🔄 [XRAY ADD] Starting to add user: {user_uuid} to server: {server_id}")
        
        success_count = 0
        servers_to_process = []
        
        # Определяем в какие серверы добавлять пользователя
        if server_id and server_id in XRAY_SERVERS:
            # Добавляем только на указанный сервер
            servers_to_process = [(server_id, XRAY_SERVERS[server_id])]
        else:
            # Добавляем на все серверы
            servers_to_process = list(XRAY_SERVERS.items())
        
        total_servers = len(servers_to_process)
        
        for server_name, server_config in servers_to_process:
            try:
                async with httpx.AsyncClient() as client:
                    # Пробуем разные endpoint'ы
                    endpoints = [
                        f"{server_config['url']}/user",
                        f"{server_config['url']}/users"
                    ]
                    
                    server_success = False
                    for endpoint in endpoints:
                        try:
                            logger.info(f"🌐 [XRAY ADD] Adding to {server_name} via: {endpoint}")
                            
                            payload = {
                                "uuid": user_uuid,
                                "email": f"user_{user_uuid}@{server_name}.vacvpn.com"
                            }
                            
                            response = await client.post(
                                endpoint,
                                headers={"X-API-Key": server_config["api_key"]},
                                json=payload,
                                timeout=30.0
                            )
                            
                            logger.info(f"📡 [XRAY ADD] {server_name} response: {response.status_code} - {response.text}")
                            
                            if response.status_code in [200, 201]:
                                data = response.json()
                                status = data.get("status", "")
                                message = data.get("message", "")
                                
                                if status == "success" or "user added" in message.lower():
                                    logger.info(f"✅ [XRAY ADD] User successfully added to {server_name}")
                                    server_success = True
                                    break
                                elif "already exists" in message.lower():
                                    logger.info(f"✅ [XRAY ADD] User already exists in {server_name}")
                                    server_success = True
                                    break
                                else:
                                    logger.info(f"⚠️ [XRAY ADD] {server_name} unexpected response: {data}")
                            
                        except Exception as e:
                            logger.warning(f"⚠️ [XRAY ADD] {server_name} endpoint {endpoint} error: {e}")
                    
                    if server_success:
                        success_count += 1
                        logger.info(f"✅ [XRAY ADD] Successfully added to {server_name}")
                    else:
                        logger.warning(f"❌ [XRAY ADD] Failed to add to {server_name}")
                            
            except Exception as e:
                logger.warning(f"⚠️ [XRAY ADD] Server {server_name} error: {e}")
        
        # Считаем успешным если добавили хотя бы в один сервер
        final_success = success_count > 0
        logger.info(f"📊 [XRAY ADD] Final result: {final_success} ({success_count}/{total_servers} servers)")
        
        return final_success
            
    except Exception as e:
        logger.error(f"❌ [XRAY ADD] Exception: {str(e)}")
        return False

async def get_xray_users_count(server_id: str = None) -> int:
    """Получить количество пользователей в Xray"""
    try:
        count = 0
        servers_to_check = []
        
        if server_id and server_id in XRAY_SERVERS:
            servers_to_check = [(server_id, XRAY_SERVERS[server_id])]
        else:
            servers_to_check = list(XRAY_SERVERS.items())
        
        for server_name, server_config in servers_to_check:
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{server_config['url']}/users",
                        headers={"X-API-Key": server_config["api_key"]},
                        timeout=30.0
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        users = data.get("users", [])
                        count += len(users)
            except Exception as e:
                logger.warning(f"⚠️ Error getting users from {server_name}: {e}")
        
        return count
            
    except Exception as e:
        logger.error(f"❌ Error getting Xray users: {e}")
        return 0

async def remove_user_from_xray(user_uuid: str, server_id: str = None) -> bool:
    """Удалить пользователя из Xray через API"""
    try:
        success_count = 0
        servers_to_process = []
        
        if server_id and server_id in XRAY_SERVERS:
            servers_to_process = [(server_id, XRAY_SERVERS[server_id])]
        else:
            servers_to_process = list(XRAY_SERVERS.items())
        
        for server_name, server_config in servers_to_process:
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.delete(
                        f"{server_config['url']}/users/{user_uuid}",
                        headers={"X-API-Key": server_config["api_key"]},
                        timeout=30.0
                    )
                    
                    if response.status_code == 200:
                        logger.info(f"✅ User {user_uuid} removed from {server_name} Xray")
                        success_count += 1
                    else:
                        logger.error(f"❌ Failed to remove user from {server_name} Xray: {response.status_code}")
                        
            except Exception as e:
                logger.error(f"❌ Error removing user from {server_name} Xray: {e}")
        
        return success_count > 0
                
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

async def ensure_user_uuid(user_id: str, server_id: str = None) -> str:
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
            
            # Проверяем есть ли в Xray на нужном сервере
            if not await check_user_in_xray(vless_uuid, server_id):
                logger.warning(f"⚠️ UUID exists but not in Xray, re-adding to server: {server_id}")
                success = await add_user_to_xray(vless_uuid, server_id)
                if not success:
                    raise Exception(f"Failed to add existing UUID to Xray server: {server_id}")
            
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
        success = await add_user_to_xray(new_uuid, server_id)
        if not success:
            raise Exception(f"Failed to add new UUID to Xray server: {server_id}")
        
        logger.info(f"✅ New UUID created and added to Xray server {server_id}: {new_uuid}")
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
    
    # Определяем какие серверы обрабатывать
    if server_id:
        # Ищем конкретный сервер по ID
        for server in VLESS_SERVERS:
            if server["id"] == server_id:
                servers_to_process = [server]
                break
    else:
        # Обрабатываем все серверы
        servers_to_process = VLESS_SERVERS
    
    for server in servers_to_process:
        address = server["address"]
        port = server["port"]
        security = server["security"]
        sni = server.get("sni", "")
        reality_pbk = server.get("reality_pbk", "")
        short_id = server.get("short_id", "")
        flow = server.get("flow", "")
        
        # Создаем VLESS ссылку в зависимости от типа безопасности
        if security == "reality":
            # Reality конфиг
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
            # Простой VLESS без безопасности
            vless_link = (
                f"vless://{vless_uuid}@{address}:{port}?"
                f"encryption=none&"
                f"type=tcp&"
                f"security=none#"
                f"VAC-VPN-{user_id}-{server['id']}"
            )
        
        # Конфиг для приложений
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
        
        # Добавляем Reality параметры если нужно
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
                    
                    # Сохраняем выбранный сервер если указан
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

@app.get("/check-xray-connection")
async def check_xray_connection():
    """Проверить подключение к Xray Manager"""
    try:
        results = {}
        for server_name, server_config in XRAY_SERVERS.items():
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{server_config['url']}/health",
                        headers={"X-API-Key": server_config["api_key"]},
                        timeout=10.0
                    )
                    results[server_name] = {
                        "connected": response.status_code == 200,
                        "status_code": response.status_code,
                        "response": response.text
                    }
            except Exception as e:
                results[server_name] = {"connected": False, "error": str(e)}
        
        return results
    except Exception as e:
        return {"error": str(e)}

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
                'preferred_server': None,  # Добавляем поле для предпочитаемого сервера
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
        
        # Проверяем выбранный сервер
        selected_server = request.selected_server
        if selected_server and selected_server not in [server["id"] for server in VLESS_SERVERS]:
            return JSONResponse(status_code=400, content={"error": "Invalid server selected"})
        
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
        
        # Проверяем выбранный сервер
        selected_server = request.selected_server
        if selected_server and selected_server not in [server["id"] for server in VLESS_SERVERS]:
            return JSONResponse(status_code=400, content={"error": "Invalid server selected"})
        
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
                            
                            # Для тарифов используем user_id из платежа
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
        
        # Если сервер не указан, используем предпочитаемый сервер пользователя или первый доступный
        if not server_id:
            server_id = user.get('preferred_server')
            if not server_id and VLESS_SERVERS:
                server_id = VLESS_SERVERS[0]["id"]
        
        # Проверяем валидность сервера
        if server_id not in [server["id"] for server in VLESS_SERVERS]:
            return JSONResponse(status_code=400, content={"error": "Invalid server ID"})
        
        # ГАРАНТИРУЕМ что у пользователя есть UUID и он в Xray на выбранном сервере
        vless_uuid = await ensure_user_uuid(user_id, server_id)
        
        # Создаем конфиги для выбранного сервера
        configs = create_user_vless_configs(user_id, vless_uuid, server_id)
        
        logger.info(f"✅ Generated {len(configs)} configs for user {user_id} on server {server_id}")
        
        return {
            "success": True,
            "user_id": user_id,
            "vless_uuid": vless_uuid,
            "has_subscription": True,
            "subscription_days": user.get('subscription_days', 0),
            "selected_server": server_id,
            "configs": configs
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting VLESS config: {e}")
        return JSONResponse(status_code=500, content={"error": f"Error getting VLESS config: {str(e)}"})

@app.post("/server/{server_id}/add-user")
async def server_add_user(server_id: str, request: dict):
    """Эндпоинт для добавления пользователя на сервер"""
    try:
        if server_id not in XRAY_SERVERS:
            return JSONResponse(status_code=404, content={"error": "Server not found"})
        
        user_uuid = request.get('uuid')
        if not user_uuid:
            return JSONResponse(status_code=400, content={"error": "UUID required"})
        
        # Здесь логика добавления пользователя в Xray
        success = await add_user_to_xray_direct(user_uuid, server_id)
        
        if success:
            return {"status": "success", "message": f"User added to {server_id}"}
        else:
            return JSONResponse(status_code=500, content={"error": "Failed to add user"})
            
    except Exception as e:
        logger.error(f"❌ Error in server add user: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

async def add_user_to_xray_direct(user_uuid: str, server_id: str) -> bool:
    """Прямое добавление пользователя в Xray конфиг"""
    try:
        # Эта функция будет запускаться на каждом сервере через SSH
        # или через агент на сервере
        return True
    except Exception as e:
        logger.error(f"❌ Error adding user directly: {e}")
        return False

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
async def admin_generate_unique_uuid(user_id: str, server_id: str = None):
    """Принудительно генерирует уникальный UUID для пользователя на конкретном сервере"""
    try:
        vless_uuid = await ensure_user_uuid(user_id, server_id)
        
        return {
            "success": True,
            "user_id": user_id,
            "vless_uuid": vless_uuid,
            "server_id": server_id,
            "message": f"Unique UUID generated and added to Xray server: {server_id}"
        }
        
    except Exception as e:
        logger.error(f"❌ Error generating unique UUID: {e}")
        return {"error": str(e)}

@app.get("/admin/user-uuid-info")
async def admin_user_uuid_info(user_id: str):
    """Информация о UUID пользователя на всех серверах"""
    try:
        user = get_user(user_id)
        if not user:
            return {"error": "User not found"}
        
        vless_uuid = user.get('vless_uuid')
        server_status = {}
        
        # Проверяем статус на каждом сервере
        for server_id in XRAY_SERVERS.keys():
            in_xray = await check_user_in_xray(vless_uuid, server_id) if vless_uuid else False
            server_status[server_id] = {
                "in_xray": in_xray,
                "server_name": XRAY_SERVERS[server_id].get("display_name", server_id)
            }
        
        return {
            "user_id": user_id,
            "has_uuid": vless_uuid is not None,
            "vless_uuid": vless_uuid,
            "server_status": server_status,
            "has_subscription": user.get('has_subscription', False),
            "subscription_days": user.get('subscription_days', 0),
            "preferred_server": user.get('preferred_server')
        }
        
    except Exception as e:
        return {"error": str(e)}

@app.post("/admin/generate-uuid-for-user")
async def generate_uuid_for_user(user_id: str, server_id: str = None):
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
            # Проверяем есть ли в Xray на указанном сервере, если нет - добавляем
            if not await check_user_in_xray(existing_uuid, server_id):
                success = await add_user_to_xray(existing_uuid, server_id)
                if success:
                    return {
                        "success": True,
                        "message": f"UUID {existing_uuid} добавлен в Xray сервер: {server_id}",
                        "user_uuid": existing_uuid,
                        "server_id": server_id,
                        "action": "added_to_xray"
                    }
                else:
                    return {"error": f"Не удалось добавить UUID в Xray сервер: {server_id}"}
            else:
                return {
                    "success": True,
                    "message": f"UUID уже существует и есть в Xray сервере: {server_id}",
                    "user_uuid": existing_uuid,
                    "server_id": server_id,
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
        
        # Добавляем в Xray на указанный сервер
        success = await add_user_to_xray(user_uuid, server_id)
        if success:
            return {
                "success": True,
                "message": f"Сгенерирован новый UUID и добавлен в Xray сервер: {server_id}",
                "user_uuid": user_uuid,
                "server_id": server_id,
                "action": "generated_and_added"
            }
        else:
            return {"error": f"Не удалось добавить UUID в Xray сервер: {server_id}"}
        
    except Exception as e:
        logger.error(f"❌ Error generating UUID: {e}")
        return {"error": str(e)}

@app.get("/admin/xray-users")
async def get_xray_users(server_id: str = None):
    """Показать всех пользователей в Xray конфиге через API"""
    try:
        results = {}
        servers_to_check = []
        
        if server_id and server_id in XRAY_SERVERS:
            servers_to_check = [(server_id, XRAY_SERVERS[server_id])]
        else:
            servers_to_check = list(XRAY_SERVERS.items())
        
        for server_name, server_config in servers_to_check:
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{server_config['url']}/users",
                        headers={"X-API-Key": server_config["api_key"]},
                        timeout=30.0
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        results[server_name] = {
                            "users": data.get("users", []),
                            "count": len(data.get("users", [])),
                            "server_name": server_config.get("display_name", server_name)
                        }
                    else:
                        results[server_name] = {"error": f"Status: {response.status_code}"}
            except Exception as e:
                results[server_name] = {"error": str(e)}
        
        return results
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
            # Удаляем пользователя из всех Xray серверов
            await remove_user_from_xray(user['vless_uuid'])
        
        user_ref = db.collection('users').document(user_id)
        user_ref.update({
            'balance': 0.0,
            'subscription_days': 0,
            'has_subscription': False,
            'vless_uuid': None,
            'preferred_server': None,
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

@app.post("/admin/test-add-user")
async def test_add_user(user_id: str, server_id: str = None):
    """Тестовый endpoint для добавления пользователя в Xray"""
    try:
        # Получаем или создаем UUID для пользователя
        user = get_user(user_id)
        if not user:
            return {"error": "User not found"}
        
        vless_uuid = user.get('vless_uuid')
        if not vless_uuid:
            vless_uuid = generate_user_uuid()
            # Обновляем пользователя
            user_ref = db.collection('users').document(user_id)
            user_ref.update({
                'vless_uuid': vless_uuid,
                'updated_at': firestore.SERVER_TIMESTAMP
            })
        
        # Добавляем в Xray на указанный сервер
        success = await add_user_to_xray(vless_uuid, server_id)
        
        if success:
            return {
                "success": True,
                "user_id": user_id,
                "vless_uuid": vless_uuid,
                "server_id": server_id,
                "message": f"User successfully added to Xray server: {server_id}"
            }
        else:
            return {
                "success": False,
                "error": f"Failed to add user to Xray server: {server_id}"
            }
            
    except Exception as e:
        logger.error(f"❌ Error in test add user: {e}")
        return {"error": str(e)}

@app.get("/admin/server-status")
async def admin_server_status():
    """Статус всех серверов"""
    try:
        status = {}
        for server_id, server_config in XRAY_SERVERS.items():
            try:
                async with httpx.AsyncClient() as client:
                    # Проверка здоровья
                    health_response = await client.get(
                        f"{server_config['url']}/health",
                        headers={"X-API-Key": server_config["api_key"]},
                        timeout=10.0
                    )
                    
                    # Получение пользователей
                    users_response = await client.get(
                        f"{server_config['url']}/users",
                        headers={"X-API-Key": server_config["api_key"]},
                        timeout=10.0
                    )
                    
                    status[server_id] = {
                        "name": server_config.get("display_name", server_id),
                        "health": health_response.status_code == 200,
                        "users_count": len(users_response.json().get("users", [])) if users_response.status_code == 200 else 0,
                        "url": server_config["url"]
                    }
                    
            except Exception as e:
                status[server_id] = {
                    "name": server_config.get("display_name", server_id),
                    "health": False,
                    "error": str(e),
                    "url": server_config["url"]
                }
        
        return status
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
