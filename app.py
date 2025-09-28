from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import os
import uuid
import httpx
from dotenv import load_dotenv
from datetime import datetime, timedelta
import sqlite3
from pydantic import BaseModel
import firebase_admin
from firebase_admin import credentials, firestore
import json

# Загрузка переменных окружения
load_dotenv('backend/key.env')

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
    # Получаем credentials из переменных окружения
    firebase_cred = os.getenv("FIREBASE_CREDENTIALS")
    if firebase_cred:
        cred_dict = json.loads(firebase_cred)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
    else:
        # Альтернативный способ инициализации
        firebase_admin.initialize_app()
except Exception as e:
    print(f"Firebase initialization error: {e}")

# Инициализация Firestore
db = firestore.client()

# Модели данных
class PaymentRequest(BaseModel):
    user_id: str
    amount: float
    tariff: str = "month"
    description: str = ""
    payment_type: str = "tariff"  # tariff или balance

class UserCreateRequest(BaseModel):
    user_id: str
    username: str = ""
    first_name: str = ""
    last_name: str = ""

class ReferralBonusRequest(BaseModel):
    referrer_id: str
    referred_id: str

# Функции работы с Firebase
def get_user(user_id: str):
    """Получает пользователя из Firebase"""
    try:
        doc_ref = db.collection('users').document(str(user_id))
        doc = doc_ref.get()
        if doc.exists:
            return doc.to_dict()
        return None
    except Exception as e:
        print(f"Error getting user from Firebase: {e}")
        return None

def create_user(user_data: UserCreateRequest):
    """Создает пользователя в Firebase"""
    try:
        user_ref = db.collection('users').document(str(user_data.user_id))
        user_data_dict = {
            'user_id': str(user_data.user_id),
            'username': user_data.username,
            'first_name': user_data.first_name,
            'last_name': user_data.last_name,
            'balance': 0.0,
            'has_subscription': False,
            'subscription_end': None,
            'tariff_type': 'none',
            'created_at': firestore.SERVER_TIMESTAMP,
            'updated_at': firestore.SERVER_TIMESTAMP
        }
        user_ref.set(user_data_dict)
        return True
    except Exception as e:
        print(f"Error creating user in Firebase: {e}")
        return False

def update_user_balance(user_id: str, amount: float):
    """Обновляет баланс пользователя в Firebase"""
    try:
        user_ref = db.collection('users').document(str(user_id))
        user_data = user_ref.get().to_dict()
        
        if user_data:
            new_balance = user_data.get('balance', 0) + amount
            user_ref.update({
                'balance': new_balance,
                'updated_at': firestore.SERVER_TIMESTAMP
            })
            return True
        return False
    except Exception as e:
        print(f"Error updating user balance in Firebase: {e}")
        return False

def activate_subscription(user_id: str, tariff: str, days: int):
    """Активирует подписку пользователя в Firebase"""
    try:
        user_ref = db.collection('users').document(str(user_id))
        user_data = user_ref.get().to_dict()
        
        if user_data:
            now = datetime.now()
            
            # Если уже есть активная подписка, продлеваем ее
            if user_data.get('has_subscription') and user_data.get('subscription_end'):
                current_end = user_data['subscription_end']
                if isinstance(current_end, str):
                    current_end = datetime.fromisoformat(current_end.replace('Z', '+00:00'))
                
                if current_end > now:
                    new_end = current_end + timedelta(days=days)
                else:
                    new_end = now + timedelta(days=days)
            else:
                new_end = now + timedelta(days=days)
            
            user_ref.update({
                'has_subscription': True,
                'subscription_end': new_end.isoformat(),
                'tariff_type': tariff,
                'updated_at': firestore.SERVER_TIMESTAMP
            })
            
            return new_end
        return None
    except Exception as e:
        print(f"Error activating subscription in Firebase: {e}")
        return None

def save_payment(payment_data: dict):
    """Сохраняет платеж в Firebase"""
    try:
        payments_ref = db.collection('payments').document(payment_data['payment_id'])
        payment_data['created_at'] = firestore.SERVER_TIMESTAMP
        payments_ref.set(payment_data)
        return True
    except Exception as e:
        print(f"Error saving payment to Firebase: {e}")
        return False

def update_payment_status(payment_id: str, status: str, yookassa_id: str = None):
    """Обновляет статус платежа в Firebase"""
    try:
        payment_ref = db.collection('payments').document(payment_id)
        update_data = {
            'status': status,
            'updated_at': firestore.SERVER_TIMESTAMP
        }
        
        if yookassa_id:
            update_data['yookassa_id'] = yookassa_id
            
        if status == 'succeeded':
            update_data['confirmed_at'] = firestore.SERVER_TIMESTAMP
            
        payment_ref.update(update_data)
        return True
    except Exception as e:
        print(f"Error updating payment status in Firebase: {e}")
        return False

def get_payment(payment_id: str):
    """Получает платеж из Firebase"""
    try:
        payment_ref = db.collection('payments').document(payment_id)
        payment = payment_ref.get()
        if payment.exists:
            return payment.to_dict()
        return None
    except Exception as e:
        print(f"Error getting payment from Firebase: {e}")
        return None

def add_referral_bonus(referrer_id: str, referred_id: str, amount: int = 50):
    """Добавляет запись о реферальном бонусе"""
    try:
        bonus_ref = db.collection('referral_bonuses').document()
        bonus_data = {
            'referrer_id': referrer_id,
            'referred_id': referred_id,
            'bonus_amount': amount,
            'paid': False,
            'created_at': firestore.SERVER_TIMESTAMP
        }
        bonus_ref.set(bonus_data)
        return True
    except Exception as e:
        print(f"Error adding referral bonus to Firebase: {e}")
        return False

def mark_referral_bonus_paid(referrer_id: str, referred_id: str):
    """Отмечает реферальный бонус как выплаченный"""
    try:
        # Находим бонус по referrer_id и referred_id
        bonuses_ref = db.collection('referral_bonuses')
        query = bonuses_ref.where('referrer_id', '==', referrer_id).where('referred_id', '==', referred_id).where('paid', '==', False)
        bonuses = query.get()
        
        for bonus in bonuses:
            bonus.reference.update({
                'paid': True,
                'paid_at': firestore.SERVER_TIMESTAMP
            })
        
        return True
    except Exception as e:
        print(f"Error marking referral bonus as paid in Firebase: {e}")
        return False

# Эндпоинты API
@app.post("/create-payment")
async def create_payment(request: PaymentRequest):
    try:
        SHOP_ID = os.getenv("SHOP_ID")
        API_KEY = os.getenv("API_KEY")
        
        if not SHOP_ID or not API_KEY:
            return {"error": "Payment gateway not configured"}
        
        # Определяем параметры тарифа
        tariff_config = {
            "month": {"days": 30, "description": "Месячная подписка VAC VPN"},
            "year": {"days": 365, "description": "Годовая подписка VAC VPN"}
        }
        
        tariff_info = tariff_config.get(request.tariff, tariff_config["month"])
        
        # Создаем уникальный ID платежа
        payment_id = str(uuid.uuid4())
        
        # Сохраняем платеж в Firebase
        payment_data = {
            "payment_id": payment_id,
            "user_id": request.user_id,
            "amount": request.amount,
            "tariff": request.tariff,
            "payment_type": request.payment_type,
            "status": "pending",
            "description": request.description
        }
        save_payment(payment_data)
        
        # Данные для ЮKassa
        yookassa_data = {
            "amount": {
                "value": f"{request.amount:.2f}", 
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect", 
                "return_url": "https://t.me/vaaaac_bot"
            },
            "capture": True,
            "description": tariff_info["description"],
            "metadata": {
                "payment_id": payment_id,
                "user_id": request.user_id,
                "tariff": request.tariff,
                "payment_type": request.payment_type
            }
        }
        
        # Создаем платеж в ЮKassa
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
            
            # Обновляем платеж с ID из ЮKassa
            update_payment_status(payment_id, "pending", payment_data.get("id"))
            
            return {
                "success": True,
                "payment_id": payment_id,
                "payment_url": payment_data["confirmation"]["confirmation_url"],
                "amount": request.amount,
                "status": "pending"
            }
        else:
            return {
                "error": f"Payment gateway error: {response.status_code}",
                "details": response.text
            }
            
    except Exception as e:
        return {"error": f"Server error: {str(e)}"}

@app.get("/check-payment")
async def check_payment(payment_id: str, user_id: str):
    try:
        payment = get_payment(payment_id)
        if not payment:
            return {"error": "Payment not found"}
        
        # Если платеж уже подтвержден
        if payment.get('status') == 'succeeded':
            return {
                "success": True,
                "status": "succeeded",
                "payment_id": payment_id,
                "amount": payment.get('amount'),
                "payment_type": payment.get('payment_type', 'tariff')
            }
        
        # Проверяем статус в ЮKassa
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
                    
                    # Обновляем статус платежа
                    update_payment_status(payment_id, status, yookassa_id)
                    
                    # Если платеж успешен - обрабатываем его
                    if status == 'succeeded':
                        user_id = payment.get('user_id')
                        tariff = payment.get('tariff')
                        amount = payment.get('amount')
                        payment_type = payment.get('payment_type', 'tariff')
                        
                        if payment_type == 'tariff':
                            # Активируем подписку
                            tariff_days = 30 if tariff == "month" else 365
                            activate_subscription(user_id, tariff, tariff_days)
                            
                            # Начисляем реферальные бонусы
                            await process_referral_bonuses(user_id)
                        else:
                            # Пополнение баланса
                            update_user_balance(user_id, amount)
                        
                        return {
                            "success": True,
                            "status": "succeeded",
                            "payment_id": payment_id,
                            "amount": amount,
                            "payment_type": payment_type
                        }
                    
                    return {
                        "success": True,
                        "status": status,
                        "payment_id": payment_id,
                        "amount": amount
                    }
        
        return {
            "success": True,
            "status": payment.get('status', 'pending'),
            "payment_id": payment_id
        }
        
    except Exception as e:
        return {"error": f"Error checking payment: {str(e)}"}

async def process_referral_bonuses(user_id: str):
    """Обрабатывает реферальные бонусы после успешной оплаты"""
    try:
        # Импортируем здесь, чтобы избежать циклического импорта
        import sqlite3
        
        # Проверяем локальную БД на наличие реферала
        conn = sqlite3.connect('vacvpn.db')
        cursor = conn.cursor()
        cursor.execute('SELECT referrer_id FROM referrals WHERE referred_id = ? AND bonus_paid = ?', (int(user_id), False))
        referral = cursor.fetchone()
        
        if referral:
            referrer_id = str(referral[0])
            
            # Начисляем бонус рефереру
            update_user_balance(referrer_id, 50)
            
            # Отмечаем бонус как выплаченный в локальной БД
            cursor.execute('UPDATE referrals SET bonus_paid = ? WHERE referred_id = ? AND referrer_id = ?', 
                         (True, int(user_id), int(referrer_id)))
            conn.commit()
            
            # Сохраняем в Firebase для истории
            add_referral_bonus(referrer_id, user_id, 50)
            
            # Уведомляем реферера
            try:
                # Здесь можно добавить отправку уведомления через бота
                print(f"Реферальный бонус начислен: {referrer_id} за пользователя {user_id}")
            except Exception as e:
                print(f"Ошибка уведомления реферера: {e}")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"Error processing referral bonuses: {e}")
        return False

@app.get("/user-data")
async def get_user_info(user_id: str):
    try:
        user = get_user(user_id)
        if not user:
            return {
                "user_id": user_id,
                "balance": 0,
                "has_subscription": False,
                "subscription_end": None,
                "tariff_type": "none",
                "days_remaining": 0
            }
        
        # Проверяем статус подписки
        has_subscription = user.get('has_subscription', False)
        subscription_end = user.get('subscription_end')
        days_remaining = 0
        
        if has_subscription and subscription_end:
            if isinstance(subscription_end, str):
                end_date = datetime.fromisoformat(subscription_end.replace('Z', '+00:00'))
            else:
                end_date = subscription_end
                
            if end_date < datetime.now():
                # Подписка истекла
                try:
                    user_ref = db.collection('users').document(str(user_id))
                    user_ref.update({
                        'has_subscription': False,
                        'updated_at': firestore.SERVER_TIMESTAMP
                    })
                    has_subscription = False
                except Exception as e:
                    print(f"Error updating expired subscription: {e}")
            else:
                days_remaining = (end_date - datetime.now()).days
        
        return {
            "user_id": user_id,
            "balance": user.get('balance', 0),
            "has_subscription": has_subscription,
            "subscription_end": subscription_end,
            "tariff_type": user.get('tariff_type', 'none'),
            "days_remaining": days_remaining
        }
        
    except Exception as e:
        return {"error": f"Error getting user info: {str(e)}"}

@app.post("/create-user")
async def create_user_endpoint(request: UserCreateRequest):
    try:
        success = create_user(request)
        if success:
            return {"success": True, "user_id": request.user_id}
        else:
            return {"error": "Failed to create user"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/check-subscription")
async def check_subscription(user_id: str):
    user_info = await get_user_info(user_id)
    if "error" in user_info:
        return user_info
    
    return {
        "active": user_info["has_subscription"],
        "subscription_end": user_info["subscription_end"],
        "days_remaining": user_info["days_remaining"]
    }

@app.post("/activate-tariff")
async def activate_tariff(request: Request):
    try:
        data = await request.json()
        user_id = data.get('user_id')
        tariff = data.get('tariff')
        amount = data.get('amount')
        
        if not all([user_id, tariff, amount]):
            return {"error": "Missing required parameters"}
        
        # Проверяем баланс пользователя
        user = get_user(user_id)
        if not user:
            return {"error": "User not found"}
        
        if user.get('balance', 0) < amount:
            return {"error": "Insufficient balance"}
        
        # Активируем подписку
        tariff_days = 30 if tariff == "month" else 365
        new_end = activate_subscription(user_id, tariff, tariff_days)
        
        if new_end:
            # Списываем средства с баланса
            user_ref = db.collection('users').document(str(user_id))
            user_ref.update({
                'balance': user.get('balance', 0) - amount,
                'updated_at': firestore.SERVER_TIMESTAMP
            })
            
            # Обрабатываем реферальные бонусы
            await process_referral_bonuses(user_id)
            
            return {
                "success": True,
                "message": f"Тариф активирован на {tariff_days} дней",
                "subscription_end": new_end.isoformat()
            }
        else:
            return {"error": "Failed to activate subscription"}
            
    except Exception as e:
        return {"error": f"Error activating tariff: {str(e)}"}

# Webhook для ЮKassa
@app.post("/yookassa-webhook")
async def yookassa_webhook(request: Request):
    try:
        data = await request.json()
        
        payment_id = data.get('object', {}).get('id')
        status = data.get('object', {}).get('status')
        
        if status == 'succeeded':
            # Находим наш payment_id по ID ЮKassa
            payments_ref = db.collection('payments')
            query = payments_ref.where('yookassa_id', '==', payment_id)
            payments = query.get()
            
            for payment_doc in payments:
                payment = payment_doc.to_dict()
                our_payment_id = payment.get('payment_id')
                user_id = payment.get('user_id')
                tariff = payment.get('tariff')
                amount = payment.get('amount')
                payment_type = payment.get('payment_type', 'tariff')
                
                if payment_type == 'tariff':
                    # Активируем подписку
                    tariff_days = 30 if tariff == "month" else 365
                    activate_subscription(user_id, tariff, tariff_days)
                    
                    # Обрабатываем реферальные бонусы
                    await process_referral_bonuses(user_id)
                else:
                    # Пополнение баланса
                    update_user_balance(user_id, amount)
                
                # Обновляем статус платежа
                update_payment_status(our_payment_id, 'succeeded', payment_id)
        
        return {"status": "ok"}
    
    except Exception as e:
        print(f"Webhook error: {e}")
        return {"status": "error"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
