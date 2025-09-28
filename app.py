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
from firebase_admin import credentials, db as firebase_db
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

# Инициализация Firebase Realtime Database
try:
    # Получаем credentials из переменных окружения
    firebase_cred = os.getenv("FIREBASE_CREDENTIALS")
    if firebase_cred:
        cred_dict = json.loads(firebase_cred)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://vacvpn-75yegf-default-rtdb.firebaseio.com/'
        })
        print("✅ Firebase Realtime Database инициализирован")
    else:
        raise Exception("FIREBASE_CREDENTIALS not found")
except Exception as e:
    print(f"❌ Firebase initialization error: {e}")

# Модели данных
class PaymentRequest(BaseModel):
    user_id: str
    amount: float
    tariff: str = "month"
    description: str = ""
    payment_type: str = "tariff"

class UserCreateRequest(BaseModel):
    user_id: str
    username: str = ""
    first_name: str = ""
    last_name: str = ""

# Функции работы с Firebase Realtime Database
def get_user(user_id: str):
    """Получает пользователя из Firebase"""
    try:
        ref = firebase_db.reference(f'users/{user_id}')
        user_data = ref.get()
        return user_data
    except Exception as e:
        print(f"Error getting user from Firebase: {e}")
        return None

def create_user(user_data: UserCreateRequest):
    """Создает пользователя в Firebase"""
    try:
        ref = firebase_db.reference(f'users/{user_data.user_id}')
        
        # Проверяем, существует ли уже пользователь
        existing_user = ref.get()
        if not existing_user:
            user_data_dict = {
                'user_id': str(user_data.user_id),
                'username': user_data.username,
                'first_name': user_data.first_name,
                'last_name': user_data.last_name,
                'balance': 0.0,
                'has_subscription': False,
                'subscription_end': None,
                'tariff_type': 'none',
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            ref.set(user_data_dict)
            print(f"✅ User created in Firebase: {user_data.user_id}")
        else:
            print(f"ℹ️ User already exists in Firebase: {user_data.user_id}")
            
        return True
    except Exception as e:
        print(f"❌ Error creating user in Firebase: {e}")
        return True

def update_user_balance(user_id: str, amount: float):
    """Обновляет баланс пользователя в Firebase"""
    try:
        ref = firebase_db.reference(f'users/{user_id}')
        user_data = ref.get()
        
        if user_data:
            current_balance = user_data.get('balance', 0)
            new_balance = current_balance + amount
            
            ref.update({
                'balance': new_balance,
                'updated_at': datetime.now().isoformat()
            })
            print(f"✅ Баланс обновлен: {user_id} {current_balance} -> {new_balance}")
            return True
        else:
            # Если пользователя нет - создаем его
            create_user(UserCreateRequest(
                user_id=user_id,
                username="",
                first_name="",
                last_name=""
            ))
            return update_user_balance(user_id, amount)
    except Exception as e:
        print(f"❌ Error updating user balance in Firebase: {e}")
        return False

def activate_subscription(user_id: str, tariff: str, days: int):
    """Активирует подписку пользователя в Firebase"""
    try:
        ref = firebase_db.reference(f'users/{user_id}')
        user_data = ref.get()
        
        if not user_data:
            # Создаем пользователя если не существует
            create_user(UserCreateRequest(
                user_id=user_id,
                username="",
                first_name="",
                last_name=""
            ))
            user_data = {}
        
        now = datetime.now()
        
        # Если уже есть активная подписка, продлеваем ее
        if user_data.get('has_subscription') and user_data.get('subscription_end'):
            current_end_str = user_data['subscription_end']
            try:
                current_end = datetime.fromisoformat(current_end_str.replace('Z', '+00:00'))
                if current_end > now:
                    new_end = current_end + timedelta(days=days)
                else:
                    new_end = now + timedelta(days=days)
            except:
                new_end = now + timedelta(days=days)
        else:
            new_end = now + timedelta(days=days)
        
        ref.update({
            'has_subscription': True,
            'subscription_end': new_end.isoformat(),
            'tariff_type': tariff,
            'updated_at': datetime.now().isoformat()
        })
        
        print(f"✅ Подписка активирована: {user_id} на {days} дней")
        return new_end
    except Exception as e:
        print(f"❌ Error activating subscription in Firebase: {e}")
        return None

def save_payment(payment_data: dict):
    """Сохраняет платеж в Firebase"""
    try:
        payment_id = payment_data['payment_id']
        ref = firebase_db.reference(f'payments/{payment_id}')
        payment_data['created_at'] = datetime.now().isoformat()
        ref.set(payment_data)
        return True
    except Exception as e:
        print(f"❌ Error saving payment to Firebase: {e}")
        return False

def update_payment_status(payment_id: str, status: str, yookassa_id: str = None):
    """Обновляет статус платежа в Firebase"""
    try:
        ref = firebase_db.reference(f'payments/{payment_id}')
        update_data = {
            'status': status,
            'updated_at': datetime.now().isoformat()
        }
        
        if yookassa_id:
            update_data['yookassa_id'] = yookassa_id
            
        if status == 'succeeded':
            update_data['confirmed_at'] = datetime.now().isoformat()
            
        ref.update(update_data)
        return True
    except Exception as e:
        print(f"❌ Error updating payment status in Firebase: {e}")
        return False

def get_payment(payment_id: str):
    """Получает платеж из Firebase"""
    try:
        ref = firebase_db.reference(f'payments/{payment_id}')
        payment = ref.get()
        return payment
    except Exception as e:
        print(f"❌ Error getting payment from Firebase: {e}")
        return None

def save_referral_bonus(referrer_id: str, referred_id: str, amount: int = 50):
    """Сохраняет реферальный бонус в Firebase"""
    try:
        bonus_id = str(uuid.uuid4())
        ref = firebase_db.reference(f'referral_bonuses/{bonus_id}')
        bonus_data = {
            'referrer_id': referrer_id,
            'referred_id': referred_id,
            'bonus_amount': amount,
            'paid': True,
            'created_at': datetime.now().isoformat(),
            'paid_at': datetime.now().isoformat()
        }
        ref.set(bonus_data)
        return True
    except Exception as e:
        print(f"❌ Error saving referral bonus to Firebase: {e}")
        return False

# Эндпоинты API
@app.post("/create-payment")
async def create_payment(request: PaymentRequest):
    try:
        SHOP_ID = os.getenv("SHOP_ID")
        API_KEY = os.getenv("API_KEY")
        
        if not SHOP_ID or not API_KEY:
            return {"error": "Payment gateway not configured"}
        
        print(f"🔄 Creating payment for user {request.user_id}, amount: {request.amount}, tariff: {request.tariff}")
        
        # Для тестовых платежей используем специальные настройки
        is_test_payment = request.amount <= 2.00  # Тестовые суммы
        
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
            "description": request.description,
            "is_test": is_test_payment
        }
        save_payment(payment_data)
        
        # Если это тестовый платеж - сразу возвращаем успех
        if is_test_payment:
            print(f"✅ Test payment auto-confirmed: {payment_id}")
            
            # Активируем подписку для тестового платежа
            if request.payment_type == 'tariff':
                tariff_days = 30 if request.tariff == "month" else 365
                activate_subscription(request.user_id, request.tariff, tariff_days)
                
                # Начисляем реферальные бонусы
                await process_referral_bonuses(request.user_id)
            else:
                # Пополнение баланса
                update_user_balance(request.user_id, request.amount)
            
            # Обновляем статус платежа
            update_payment_status(payment_id, 'succeeded', 'test_payment')
            
            return {
                "success": True,
                "payment_id": payment_id,
                "payment_url": "https://t.me/vaaaac_bot",
                "amount": request.amount,
                "status": "succeeded"
            }
        
        # Данные для ЮKassa (для реальных платежей)
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
        
        print(f"📤 Sending request to YooKassa: {yookassa_data}")
        
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
        
        print(f"📥 YooKassa response status: {response.status_code}")
        
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
            error_msg = f"Payment gateway error: {response.status_code}"
            print(f"❌ {error_msg}")
            return {"error": error_msg}
            
    except Exception as e:
        error_msg = f"Server error: {str(e)}"
        print(f"❌ {error_msg}")
        return {"error": error_msg}

@app.get("/check-payment")
async def check_payment(payment_id: str, user_id: str):
    try:
        print(f"🔄 Checking payment: {payment_id} for user: {user_id}")
        
        payment = get_payment(payment_id)
        if not payment:
            return {"error": "Payment not found"}
        
        # Если это тестовый платеж или уже подтвержден
        if payment.get('is_test') or payment.get('status') == 'succeeded':
            return {
                "success": True,
                "status": "succeeded",
                "payment_id": payment_id,
                "amount": payment.get('amount'),
                "payment_type": payment.get('payment_type', 'tariff')
            }
        
        # Проверяем статус в ЮKassa для реальных платежей
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
                    
                    print(f"📊 YooKassa payment status: {status}")
                    
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
                        "amount": payment.get('amount')
                    }
        
        return {
            "success": True,
            "status": payment.get('status', 'pending'),
            "payment_id": payment_id
        }
        
    except Exception as e:
        error_msg = f"Error checking payment: {str(e)}"
        print(f"❌ {error_msg}")
        return {"error": error_msg}

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
            
            print(f"🎉 Начисляем реферальный бонус: {referrer_id} за пользователя {user_id}")
            
            # Начисляем бонус рефереру
            update_user_balance(referrer_id, 50)
            
            # Сохраняем в Firebase для истории
            save_referral_bonus(referrer_id, user_id, 50)
            
            # Отмечаем бонус как выплаченный в локальной БД
            cursor.execute('UPDATE referrals SET bonus_paid = ? WHERE referred_id = ? AND referrer_id = ?', 
                         (True, int(user_id), int(referrer_id)))
            conn.commit()
            
            print(f"✅ Реферальный бонус 50₽ начислен пользователю {referrer_id}")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Error processing referral bonuses: {e}")
        return False

@app.get("/user-data")
async def get_user_info(user_id: str):
    try:
        user = get_user(user_id)
        
        # ЕСЛИ ПОЛЬЗОВАТЕЛЯ НЕТ - СОЗДАЕМ ЕГО СРАЗУ
        if not user:
            print(f"🆕 User {user_id} not found, creating...")
            create_user(UserCreateRequest(
                user_id=user_id,
                username="",
                first_name="",
                last_name=""
            ))
            user = get_user(user_id)  # Пытаемся получить снова
        
        # Если все равно нет - возвращаем базовые данные
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
            try:
                end_date = datetime.fromisoformat(subscription_end.replace('Z', '+00:00'))
                if end_date > datetime.now():
                    days_remaining = (end_date - datetime.now()).days
                else:
                    # Подписка истекла
                    ref = firebase_db.reference(f'users/{user_id}')
                    ref.update({
                        'has_subscription': False,
                        'updated_at': datetime.now().isoformat()
                    })
                    has_subscription = False
            except:
                # Если ошибка парсинга даты
                has_subscription = False
        
        return {
            "user_id": user_id,
            "balance": user.get('balance', 0),
            "has_subscription": has_subscription,
            "subscription_end": subscription_end,
            "tariff_type": user.get('tariff_type', 'none'),
            "days_remaining": days_remaining
        }
        
    except Exception as e:
        print(f"❌ Error in get_user_info: {e}")
        # ВСЕГДА возвращаем успешный ответ
        return {
            "user_id": user_id,
            "balance": 0,
            "has_subscription": False,
            "subscription_end": None,
            "tariff_type": "none",
            "days_remaining": 0
        }

@app.post("/create-user")
async def create_user_endpoint(request: UserCreateRequest):
    try:
        # ВСЕГДА возвращаем успех
        success = create_user(request)
        return {"success": True, "user_id": request.user_id}
    except Exception as e:
        print(f"❌ Error in create-user: {e}")
        return {"success": True, "user_id": request.user_id}

@app.get("/check-subscription")
async def check_subscription(user_id: str):
    user_info = await get_user_info(user_id)
    
    return {
        "active": user_info.get("has_subscription", False),
        "subscription_end": user_info.get("subscription_end"),
        "days_remaining": user_info.get("days_remaining", 0)
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
            # Создаем пользователя если не существует
            create_user(UserCreateRequest(user_id=user_id, username="", first_name="", last_name=""))
            user = get_user(user_id)
        
        if user.get('balance', 0) < amount:
            return {"error": "Insufficient balance"}
        
        # Активируем подписку
        tariff_days = 30 if tariff == "month" else 365
        new_end = activate_subscription(user_id, tariff, tariff_days)
        
        if new_end:
            # Списываем средства с баланса
            ref = firebase_db.reference(f'users/{user_id}')
            ref.update({
                'balance': user.get('balance', 0) - amount,
                'updated_at': datetime.now().isoformat()
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
        
        print(f"🔄 Webhook received: {status} for payment {payment_id}")
        
        if status == 'succeeded':
            # Находим наш payment_id по ID ЮKassa
            ref = firebase_db.reference('payments')
            payments = ref.order_by_child('yookassa_id').equal_to(payment_id).get()
            
            for payment_id_key, payment in payments.items():
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
                update_payment_status(payment_id_key, 'succeeded', payment_id)
                
                print(f"✅ Webhook processed successfully for user {user_id}")
        
        return {"status": "ok"}
    
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        return {"status": "error"}

# Health check endpoint
@app.get("/")
async def health_check():
    return {"status": "ok", "message": "VAC VPN API is running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
