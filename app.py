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

# Инициализация Firebase
try:
    if not firebase_admin._apps:
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
        }
        cred = credentials.Certificate(firebase_config)
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    logger.info("Firebase initialized successfully")
except Exception as e:
    logger.error(f"Firebase initialization failed: {e}")
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

# Функции работы с Firebase
def get_user(user_id: str):
    if not db: return None
    doc = db.collection('users').document(user_id).get()
    return doc.to_dict() if doc.exists else None

def create_user(user_data: UserCreateRequest):
    if not db: return
    user_ref = db.collection('users').document(user_data.user_id)
    if not user_ref.get().exists:
        user_ref.set({
            'user_id': user_data.user_id,
            'username': user_data.username,
            'first_name': user_data.first_name,
            'last_name': user_data.last_name,
            'balance': 0.0,
            'has_subscription': False,
            'subscription_end': None,
            'tariff_type': 'none',
            'created_at': firestore.SERVER_TIMESTAMP
        })

def update_user_balance(user_id: str, amount: float):
    if not db: return
    user_ref = db.collection('users').document(user_id)
    user = user_ref.get()
    if user.exists:
        current_balance = user.to_dict().get('balance', 0)
        user_ref.update({'balance': current_balance + amount})

def activate_subscription(user_id: str, tariff: str, days: int):
    if not db: return
    new_end = datetime.now() + timedelta(days=days)
    db.collection('users').document(user_id).update({
        'has_subscription': True,
        'subscription_end': new_end.isoformat(),
        'tariff_type': tariff
    })

def save_payment(payment_id: str, user_id: str, amount: float, tariff: str, payment_type: str = "tariff"):
    if not db: return
    db.collection('payments').document(payment_id).set({
        'payment_id': payment_id,
        'user_id': user_id,
        'amount': amount,
        'tariff': tariff,
        'status': 'pending',
        'payment_type': payment_type,
        'created_at': firestore.SERVER_TIMESTAMP
    })

# Эндпоинты API
@app.get("/")
async def root():
    return {"message": "VAC VPN API is running", "status": "ok"}

@app.get("/health")
async def health():
    firebase_status = "connected" if db else "disconnected"
    return {"status": "healthy", "firebase": firebase_status}

@app.post("/create-user")
async def create_user_endpoint(request: UserCreateRequest):
    try:
        create_user(request)
        return {"success": True, "user_id": request.user_id}
    except Exception as e:
        return {"error": str(e)}

@app.get("/user-data/{user_id}")
async def get_user_info(user_id: str):
    try:
        user = get_user(user_id)
        if not user:
            return {"user_id": user_id, "balance": 0, "has_subscription": False}
        
        return {
            "user_id": user_id,
            "balance": user.get('balance', 0),
            "has_subscription": user.get('has_subscription', False),
            "subscription_end": user.get('subscription_end'),
            "tariff_type": user.get('tariff_type', 'none')
        }
    except Exception as e:
        return {"error": str(e)}

@app.post("/create-payment")
async def create_payment(request: PaymentRequest):
    try:
        SHOP_ID = os.getenv("SHOP_ID")
        API_KEY = os.getenv("API_KEY")
        
        if not SHOP_ID or not API_KEY:
            return {"error": "Payment gateway not configured"}
        
        # Тарифы
        tariff_config = {
            "month": {"amount": 150, "description": "Месячная подписка VAC VPN"},
            "year": {"amount": 1300, "description": "Годовая подписка VAC VPN"}
        }
        
        amount = request.amount
        if request.payment_type == "tariff":
            tariff_info = tariff_config.get(request.tariff, tariff_config["month"])
            amount = tariff_info["amount"]
            description = tariff_info["description"]
        else:
            description = f"Пополнение баланса на {amount}₽"
        
        payment_id = str(uuid.uuid4())
        save_payment(payment_id, request.user_id, amount, request.tariff, request.payment_type)
        
        # Данные для ЮKassa
        yookassa_data = {
            "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": "https://t.me/vaaaac_bot"},
            "capture": True,
            "description": description,
            "metadata": {"payment_id": payment_id, "user_id": request.user_id}
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.yookassa.ru/v3/payments",
                auth=(SHOP_ID, API_KEY),
                headers={"Content-Type": "application/json", "Idempotence-Key": payment_id},
                json=yookassa_data,
                timeout=30.0
            )
        
        if response.status_code in [200, 201]:
            payment_data = response.json()
            return {
                "success": True,
                "payment_id": payment_id,
                "payment_url": payment_data["confirmation"]["confirmation_url"],
                "amount": amount
            }
        else:
            return {"error": f"Payment error: {response.status_code}"}
            
    except Exception as e:
        return {"error": f"Server error: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
